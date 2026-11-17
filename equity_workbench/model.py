"""Materialize reviewable operating forecasts and a market-weighted WACC."""

from copy import deepcopy
from datetime import date, timedelta

from .core import evaluate_case
from .validation import _number


SCENARIOS = ("downside", "base", "upside")


def _measure(row, key, minimum, maximum):
    value = row.get(key)
    if not _number(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be a number between {minimum} and {maximum}")
    return value


def _rationale(row):
    rationale = row.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Each assumption set and forecast period needs a rationale")
    return rationale


def capital_cost(inputs, facts):
    if inputs.get("method") == "lseg_starmine":
        wacc = _measure(inputs, "wacc", 0.0001, 1)
        debt_weight = _measure(inputs, "debt_weight", 0, 1)
        equity_cost = _measure(inputs, "cost_of_equity", 0, 1)
        debt_cost = _measure(inputs, "debt_cost_component", 0, 1)
        difference = wacc - (equity_cost * (1 - debt_weight) + debt_cost * debt_weight)
        if abs(difference) > .0005:
            raise ValueError("LSEG WACC does not reconcile to its published components")
        if not isinstance(inputs.get("as_of"), str):
            raise ValueError("LSEG capital costs require a provider date")
        return {**inputs, "component_difference_bps": difference * 10_000, "rationale": _rationale(inputs)}
    risk_free = _measure(inputs, "risk_free_rate", 0, 1)
    premium = _measure(inputs, "equity_risk_premium", 0, 1)
    beta = _measure(inputs, "beta", 0, 10)
    debt_cost = _measure(inputs, "pre_tax_cost_of_debt", 0, 1)
    tax = _measure(inputs, "tax_rate", 0, 1)
    price = _measure(facts["market_price"], "value", 1e-12, 1e15)
    shares = _measure(facts["shares_outstanding"], "value", 1e-12, 1e15)
    equity = price * shares
    debt = _measure(facts["debt"], "value", 0, 1e15)
    debt_weight = debt / (equity + debt)
    equity_cost = risk_free + beta * premium
    return {
        **inputs, "market_equity": equity, "market_debt": debt, "debt_weight": debt_weight,
        "cost_of_equity": equity_cost, "after_tax_cost_of_debt": debt_cost * (1 - tax),
        "wacc": (1 - debt_weight) * equity_cost + debt_weight * debt_cost * (1 - tax),
        "rationale": _rationale(inputs),
    }


def _forecast_row(row, start, revenue):
    capex = _measure(row, "capex_rate", 0, 1) * revenue
    depreciation = _measure(row, "depreciation_rate", 0, 1) * revenue
    intangible = _measure(row, "net_other_investment_rate", -1, 1) * revenue
    working_capital = _measure(row, "working_capital_investment_rate", -1, 1) * revenue
    return {
        "period_start": start.isoformat(), "period_end": row["period_end"],
        "revenue": revenue, "operating_margin": _measure(row, "operating_margin", 0, 1),
        "tax_rate": _measure(row, "tax_rate", 0, 1),
        "net_reinvestment": capex - depreciation + intangible + working_capital,
        "rationale": _rationale(row),
    }, {
        "period_end": row["period_end"], "capex": capex, "depreciation": depreciation,
        "net_other_investment": intangible, "working_capital_investment": working_capital,
    }


def materialize_plan(case, plan):
    """Produce three independent explicit cases for the existing DCF."""
    if not isinstance(plan, dict) or plan.get("version") != "1":
        raise ValueError("Forecast plan version must be '1'")
    configurations = plan["scenarios"]
    if set(configurations) != set(SCENARIOS):
        raise ValueError("Provide downside, base and upside forecast plans")
    capital = capital_cost(plan["capital_cost"], case["facts"])
    starting_revenue = _measure(plan, "starting_annual_revenue", 0.000001, 1e15)
    valuation_date = date.fromisoformat(case["valuation_date"])
    first_day = valuation_date + timedelta(days=1)
    paths = {}
    for name in SCENARIOS:
        configuration = configurations[name]
        explicit_case = deepcopy(case)
        forecasts, investments = [], []
        previous_revenue = starting_revenue
        start = first_day
        stub = configuration.get("stub")
        if stub:
            stub_revenue = _measure(stub, "revenue", 0.000001, starting_revenue)
            forecast, investment = _forecast_row(stub, start, stub_revenue)
            forecasts.append(forecast)
            investments.append(investment)
            final_day = date.fromisoformat(stub["period_end"])
            if not 0 < (final_day - start).days + 1 < 365:
                raise ValueError("Forecast stub must be shorter than a year and entirely after valuation")
            start = final_day + timedelta(days=1)
        annual = configuration["annual"]
        if not annual:
            raise ValueError(f"At least one annual year needed for {name}")
        for row in annual:
            end = date.fromisoformat(row["period_end"])
            if (end - start).days + 1 not in (365, 366):
                raise ValueError("Annual driver rows must cover a full fiscal year")
            revenue = previous_revenue * (1 + _measure(row, "revenue_growth", -0.99, 10))
            forecast, investment = _forecast_row(row, start, revenue)
            forecasts.append(forecast)
            investments.append(investment)
            previous_revenue = revenue
            start = end + timedelta(days=1)
        terminal = configuration["terminal"]
        explicit_case["forecasts"] = forecasts
        explicit_case["assumptions"] = {
            "wacc": capital["wacc"], "discount_convention": "end_period_actual_365",
            "terminal_growth": terminal["growth"], "terminal_roic": terminal["roic"],
            "terminal_tax_rate": terminal["tax_rate"], "terminal_operating_margin": terminal["operating_margin"],
            "rationale": _rationale(terminal),
        }
        if terminal["operating_margin"] != forecasts[-1]["operating_margin"]:
            raise ValueError(f"Fade the final explicit margin to the terminal margin in {name}")
        paths[name] = {
            "case": explicit_case, "investment": investments, "rationale": _rationale(configuration),
        }
    grids = {tuple(row["period_end"] for row in path["case"]["forecasts"]) for path in paths.values()}
    if len(grids) != 1:
        raise ValueError("All scenarios must use the same fiscal forecast dates")
    return capital, paths


def evaluate_plan(case, plan):
    if plan.get("version") == "equity-1":
        from .equity_models import evaluate_equity
        return case, evaluate_equity(case, plan)
    capital, paths = materialize_plan(case, plan)
    results = {name: evaluate_case(path["case"]) for name, path in paths.items()}
    values = [results[name]["value_per_share"] for name in SCENARIOS]
    if not values[0] <= values[1] <= values[2]:
        raise ValueError("Scenario hypotheses produce an inverted value range")
    result = results["base"]
    result["capital_cost"] = capital
    difference = capital.get("component_difference_bps", 0)
    if abs(difference) > .1:
        result["checks"].append({
            "severity": "warning", "code": "provider_wacc_difference",
            "message": f"StarMine WACC differs by {difference:+.2f} bp from its displayed two-component reconstruction. The published rate is used.",
        })
    result["scenarios"] = {
        name: {
            **{key: results[name][key] for key in
               ("value_per_share", "upside_fraction", "bridge", "forecast_rows", "terminal")},
            "assumptions": path["case"]["assumptions"],
            "investment": path["investment"],
            "rationale": path["rationale"],
        }
        for name, path in paths.items()
    }
    if "alternate_beta" in plan["capital_cost"]:
        alternate_inputs = dict(plan["capital_cost"])
        alternate_inputs["beta"] = alternate_inputs.pop("alternate_beta")
        alternate = capital_cost(alternate_inputs, case["facts"])
        alternate_case = deepcopy(paths["base"]["case"])
        alternate_case["assumptions"]["wacc"] = alternate["wacc"]
        alternate_result = evaluate_case(alternate_case)
        result["beta_cross_check"] = {
            "beta": alternate["beta"], "wacc": alternate["wacc"],
            "value_per_share": alternate_result["value_per_share"],
        }
    return paths["base"]["case"], result
