"""Value the same common-share claim from net cash flows across issuers."""

from datetime import date
import math

from .validation import _date, _number, validate_case


SCENARIOS = ("downside", "base", "upside")
CONVENTION = "end_period_actual_365"


def check_scenarios(case, as_of, sources, add):
    if case.get("discount_convention") != CONVENTION:
        add("discount_convention", f"discount_convention must be {CONVENTION}.")
    cases = case.get("scenarios")
    if not isinstance(cases, dict) or set(cases) != set(SCENARIOS):
        add("equity_scenarios", "Supply downside, base and upside scenarios.")
        return
    calendars = []
    for name in SCENARIOS:
        path = cases[name]
        if not isinstance(path, dict):
            add("equity_scenario", f"{name} must be a forecast object.")
            continue
        cost, growth = path.get("cost_of_equity"), path.get("terminal_growth")
        if not (_number(cost) and _number(growth) and 0 <= growth < cost < 1):
            add("equity_terminal_spread", f"{name} requires nonnegative growth below the equity discount rate and a discount rate below 100%.")
        elif cost - growth < .02:
            add("narrow_terminal_spread", f"{name} has less than two percentage points between equity cost and growth.", "warning")
        cash = path.get("terminal_annual_cash_flow")
        if not _number(cash) or cash <= 0:
            add("equity_terminal_cash_flow", f"{name} requires positive normalized net cash to common equity for the first terminal year.")
        check_basis(path, sources, name, add)
        periods = path.get("forecasts")
        if not isinstance(periods, list) or not periods:
            add("equity_forecasts", f"{name} needs an explicit dated cash-flow forecast.")
            continue
        calendar = []
        previous = as_of
        for index, row in enumerate(periods):
            label = f"{name}.forecasts[{index}]"
            if not isinstance(row, dict):
                add("equity_forecast", f"{label} must be a forecast object.")
                continue
            start, end = _date(row.get("period_start")), _date(row.get("period_end"))
            if not start or not end or not 0 <= (end - start).days <= 365:
                add("equity_period", f"{label} needs valid start and end dates at most one year apart.")
            else:
                days = (end - start).days + 1
                if (previous and (start - previous).days != 1) or (index > 0 and days not in (365, 366)):
                    add("equity_calendar", f"{label} must follow the prior period and cover a full fiscal year after any initial stub.")
                if index == len(periods) - 1 and days not in (365, 366):
                    add("equity_terminal_period", f"{label} must be a full year before the terminal period.")
                previous = end
            calendar.append((start, end))
            flow = row.get("net_cash_to_common")
            if not _number(flow):
                add("equity_cash_flow", f"{label}.net_cash_to_common must be a finite number in millions.")
            check_basis(row, sources, label, add)
        calendars.append(calendar)
    if any(calendar != calendars[0] for calendar in calendars[1:]):
        add("equity_scenario_calendar", "Use the same dates for all three scenarios.")


def check_basis(data, sources, label, add):
    rationale = data.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        add("equity_rationale", f"{label} requires a rationale for the projected owner cash flows or terminal assumptions.")
    ids = data.get("source_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(sid, str) or sid not in sources for sid in ids):
        add("equity_source_ids", f"{label} needs source_ids that resolve to data in the source register.")


def discount_path(path, cutoff, shares, price, cost):
    growth = path["terminal_growth"]
    flows = []
    for row in path["forecasts"]:
        elapsed = (date.fromisoformat(row["period_end"]) - cutoff).days / 365
        factor = (1 + cost) ** -elapsed
        flows.append(row | {"discount_years": elapsed, "discount_factor": factor,
                            "present_value": row["net_cash_to_common"] * factor})
    explicit = math.fsum(row["present_value"] for row in flows)
    discount = flows[-1]["discount_factor"]
    terminal = path["terminal_annual_cash_flow"] / (cost - growth) * discount
    equity = explicit + terminal
    implied = (price * shares - explicit) * (cost - growth) / discount
    if not all(map(math.isfinite, (equity, explicit, terminal, implied, equity / shares / price))):
        raise ValueError("Computed values are not finite. Check amounts, units and the terminal spread.")
    return {"forecast_rows": flows, "cost_of_equity": cost, "terminal_growth": growth,
            "terminal_annual_cash_flow": path["terminal_annual_cash_flow"], "explicit_present_value": explicit,
            "terminal_present_value": terminal, "equity_value": equity, "value_per_share": equity / shares,
            "upside_fraction": equity / shares / price - 1, "terminal_value_share": terminal / equity if equity else None,
            "implied_terminal_annual_cash_flow": implied}


def evaluate_common_equity(case):
    checks = validate_case(case)
    if any(item["severity"] == "error" for item in checks):
        raise ValueError("The common-equity case failed input checks.")
    cutoff = date.fromisoformat(case["valuation_date"])
    shares, price = (case["facts"][field]["value"] for field in ("valuation_shares", "market_price"))
    paths = case["scenarios"]
    scenarios = {name: discount_path(paths[name], cutoff, shares, price, paths[name]["cost_of_equity"])
                 for name in SCENARIOS}
    if not scenarios["downside"]["value_per_share"] <= scenarios["base"]["value_per_share"] <= scenarios["upside"]["value_per_share"]:
        checks.append({"severity": "warning", "code": "equity_scenario_order",
                       "message": "Scenario values are out of order. Review the assumptions and labels."})
    base = scenarios["base"]
    sensitivities = []
    for shift in (-.01, 0, .01):
        cost = base["cost_of_equity"] + shift
        value = (discount_path(paths["base"], cutoff, shares, price, cost)["value_per_share"]
                 if base["terminal_growth"] < cost < 1 else None)
        sensitivities.append({"cost_of_equity": cost, "value_per_share": value})
    return {"valuation_basis": "common_equity_cash_flows", "value_per_share": base["value_per_share"],
            "market_price": price, "valuation_shares": shares, "forecast_rows": base["forecast_rows"],
            "scenarios": scenarios, "sensitivities": sensitivities, "checks": checks, "publication_ready": False}
