"""Direct common-equity valuation for financial firms and equity REITs."""

from datetime import date
import math
from statistics import median

from .lseg_analysis import LSEG_DATA, LSEG_METHOD, cell, day, numeric, one_row


SCENARIOS = {"downside": -1, "base": 0, "upside": 1}
LABELS = {"residual_income": "Residual income", "reit_dividends": "Dividend discount model"}


def _earnings_history(ric, rows, cutoff):
    history = []
    for row in rows:
        if row.get("Instrument", "").casefold() != ric.casefold():
            raise ValueError("Workspace returned an equity history for the wrong RIC")
        fiscal_end = day(row, "TR.F.ShHoldEqCom.periodenddate")
        if fiscal_end > cutoff:
            raise ValueError("Workspace returned a future financial statement")
        history.append({
            "period_end": fiscal_end.isoformat(),
            "book": numeric(row, "TR.F.ShHoldEqCom"),
            "earnings": numeric(row, "TR.F.IncAvailToComShr"),
            "shares": numeric(row, "TR.F.ComShrOutsTot"),
            "basic_eps_shares": numeric(row, "TR.F.ShrUsedToCalcBasicEPSTot"),
            "diluted_eps_shares": numeric(row, "TR.F.ShrUsedToCalcDilEPSTot"),
            "reported_dividends": numeric(row, "TR.F.DivPaidCashTotCF", optional=True),
            "net_share_buybacks": numeric(row, "TR.F.ComStockBuybackNet", optional=True),
        })
    history.sort(key=lambda row: row["period_end"])
    if len({row["period_end"] for row in history}) != len(history):
        raise ValueError("Duplicate financial periods")
    return history


def prepare_equity(ric, identity, requests, method, cutoff, close, currency, price):
    def rows(group):
        return requests[group]["rows"]

    code = "TR.NetProfitMean" if method == "residual_income" else "TR.FFOMean"
    estimates = []
    for horizon in ("fy1", "fy2"):
        row = one_row(ric, rows(f"consensus_{horizon}"), horizon)
        end = day(row, code + ".periodenddate")
        if end != day(row, "TR.DPSMean.periodenddate"):
            raise ValueError("Earnings/FFO and dividend estimates have different fiscal periods")
        estimates.append({"period_end": end.isoformat(), "profit_or_ffo": numeric(row, code),
                          "dps": numeric(row, "TR.DPSMean")})
    capital = one_row(ric, rows("capital"), "equity cost")
    capital_day = day(capital, "TR.WACC.date")
    if not 0 <= (cutoff.date() - capital_day).days <= 7:
        raise ValueError("Workspace cost of equity is stale or dated after the cutoff")
    cost = numeric(capital, "TR.WACCCostOfEquity") / 100
    annual, quarterly = [], []
    market_cap = numeric(identity, "TR.CompanyMarketCap") / 1e6
    shares = market_cap / price
    if method == "residual_income":
        annual = _earnings_history(ric, rows("annual"), cutoff.date())
        quarterly = _earnings_history(ric, rows("quarterly"), cutoff.date())
        if len(annual) < 4 or len(quarterly) < 4:
            raise ValueError("Residual income needs four reported fiscal years and four quarters")
        latest = quarterly[-1]
        if (cutoff.date() - date.fromisoformat(latest["period_end"])).days > 185:
            raise ValueError("Common book value is too old for the automated estimate")
        if latest["shares"] <= 0 or abs(shares / latest["shares"] - 1) > .07:
            raise ValueError("Issue-adjusted market shares and reported shares need reconciliation")
        dilution = latest["diluted_eps_shares"] - latest["basic_eps_shares"]
        if not 0 <= dilution <= .1 * shares:
            raise ValueError("Quarterly dilution needs a class-specific analysis")
        shares += dilution
    issue_cap = numeric(identity, "TR.IssueMarketCap") / 1e6
    cap_fraction = issue_cap / market_cap
    source_date = cutoff.isoformat()
    case = {
        "company": {"name": cell(identity, "TR.CommonName"), "ticker": ric,
                    "isin": cell(identity, "TR.ISIN"), "currency": currency,
                    "exchange": cell(identity, "TR.ExchangeName")},
        "valuation_date": cutoff.date().isoformat(), "valuation_at": source_date,
        "method": method, "market_date": close.date().isoformat(),
        "market_price": price, "market_cap": market_cap, "issue_cap": issue_cap,
        "issue_market_fraction": cap_fraction, "valuation_shares": shares, "synthetic": False,
        "sources": [
            {"id": "LSEG-QUOTE", "title": "Workspace primary market quote", "url": LSEG_DATA,
             "observed_at": close.isoformat()},
            {"id": "LSEG-FIN", "title": "Workspace fundamentals, consensus and StarMine cost of equity",
             "url": LSEG_METHOD, "observed_at": source_date},
        ],
    }
    plan = {
        "version": "equity-1", "method": method, "estimates": estimates, "annual": annual,
        "quarterly": quarterly, "cost_of_equity": cost, "cost_date": capital_day.isoformat(),
        "beta": numeric(capital, "TR.WACCBeta"),
        "terminal_growth": .015 if currency in {"JPY", "CHF"} else .025,
        "industry": cell(identity, "TR.TRBCIndustryGroup"),
    }
    return case, plan


def _periods(estimates, cutoff):
    first, second = [date.fromisoformat(row["period_end"]) for row in estimates]
    if not 0 < (first - cutoff).days <= 366 or (second - first).days not in {365, 366}:
        raise ValueError("Expected a current fiscal stub and the next full year in consensus")
    return [first, second, *(date(second.year + i, second.month, min(second.day, 28)
                                  if second.month == 2 else second.day) for i in range(1, 5))]


def _residual_inputs(plan, case, cutoff, ends):
    annual = plan["annual"][-4:]
    quarter = plan["quarterly"][-1]
    book = quarter["book"]
    if min([book] + [row["book"] for row in annual]) <= 0:
        raise ValueError("Residual income requires a positive common equity capital base")
    previous_year = date.fromisoformat(annual[-1]["period_end"])
    latest = date.fromisoformat(quarter["period_end"])
    if not previous_year <= latest <= cutoff < ends[0] or (ends[0] - previous_year).days not in {365, 366}:
        raise ValueError("Latest book value and the first consensus period do not line up")
    retained_year = sum(row["earnings"] for row in plan["quarterly"] if date.fromisoformat(row["period_end"]) > previous_year)
    first, second = plan["estimates"]
    fraction = (ends[0] - cutoff).days / (ends[0] - latest).days
    residual_earnings = (first["profit_or_ffo"] - retained_year) * fraction
    if min(first["profit_or_ffo"], second["profit_or_ffo"]) <= 0:
        raise ValueError("Consensus requires a positive full-year common income path")
    shares = case["valuation_shares"]
    divs = [first["dps"] * shares * (ends[0] - cutoff).days / (ends[0] - previous_year).days, second["dps"] * shares]
    returns = [b["earnings"] / ((a["book"] + b["book"]) / 2) for a, b in zip(annual, annual[1:])]
    base_roe = min(.25, max(.045, (median(returns) + plan["cost_of_equity"]) / 2))
    return book, [residual_earnings, second["profit_or_ffo"]], divs, base_roe


def _residual_path(case, plan, cost, growth, tilt, cutoff, ends):
    book, earnings_start, dividend_start, base_roe = _residual_inputs(plan, case, cutoff, ends)
    terminal_roe = base_roe * (1 + .15 * tilt)
    if terminal_roe <= growth:
        raise ValueError("Stable growth exceeds sustainable return on common equity")
    start = cutoff
    beginning_book = book
    present_dividends, present_residual = 0.0, 0.0
    rows = []
    for index, end in enumerate(ends):
        elapsed = (end - cutoff).days / 365
        period_rate = (1 + cost) ** ((end - start).days / 365) - 1
        factor = (1 + cost) ** -elapsed
        if index < 2:
            income = earnings_start[index] * (1 + .12 * tilt)
            dividend = dividend_start[index]
        else:
            years = (end - start).days / 365
            fade = (index - 1) / (len(ends) - 2)
            reference_roe = earnings_start[1] / book
            income = beginning_book * years * ((1 - fade) * reference_roe * (1 + .12 * tilt) + fade * terminal_roe)
            retention = (1 - fade) * (1 - dividend_start[1] / earnings_start[1]) + fade * growth / terminal_roe
            dividend = income * (1 - retention)
        residual = income - beginning_book * period_rate
        ending_book = beginning_book + income - dividend
        if dividend < 0 or ending_book <= 0:
            raise ValueError("Forecast dividend or common book value needs regulatory and capital review")
        present_dividends += dividend * factor
        present_residual += residual * factor
        rows.append({"period_end": end.isoformat(), "common_income": income, "dividends": dividend,
                     "beginning_book": beginning_book, "ending_book": ending_book,
                     "residual_income": residual, "pv_residual_income": residual * factor})
        beginning_book, start = ending_book, end
    terminal_residual = beginning_book * (terminal_roe - cost) / (cost - growth)
    value = book + present_residual + factor * terminal_residual
    dividend_equivalent = present_dividends + factor * beginning_book * (terminal_roe - growth) / (cost - growth)
    if not math.isclose(value, dividend_equivalent, rel_tol=1e-10, abs_tol=1e-8):
        raise ValueError("Clean-surplus residual income and dividend present values do not reconcile")
    market_equity = case["valuation_shares"] * case["market_price"]
    implied_roe = cost + (market_equity - book - present_residual) * (cost - growth) / (beginning_book * factor)
    return {
        "value_per_share": value / case["valuation_shares"], "forecast_rows": rows,
        "terminal_growth": growth, "terminal_roe": terminal_roe, "cost_of_equity": cost,
        "implied_terminal_roe": implied_roe, "dividend_equivalent_value": dividend_equivalent,
    }


def _reit_path(case, plan, cost, growth, tilt, cutoff, ends):
    first, second = plan["estimates"]
    for row in (first, second):
        if not 0 < row["dps"] <= row["profit_or_ffo"]:
            raise ValueError("Positive consensus dividends must be covered by forward FFO")
    margin = second["dps"] / second["profit_or_ffo"]
    stub = (ends[0] - cutoff).days / 365
    annual_ffo = second["profit_or_ffo"]
    present, rows = 0.0, []
    for index, end in enumerate(ends):
        if index < 2:
            inputs = (first, second)[index]
            dividends = inputs["dps"] * (stub if index == 0 else 1) * (1 + .06 * tilt)
            ffo = inputs["profit_or_ffo"] * (1 + .06 * tilt)
        else:
            fade = (index - 1) / (len(ends) - 2)
            annual_ffo *= 1 + (1 - fade) * (second["profit_or_ffo"] / first["profit_or_ffo"] - 1 + .02 * tilt) + fade * growth
            ffo = annual_ffo * (1 + .06 * tilt)
            dividends = ffo * margin
        factor = (1 + cost) ** (-(end - cutoff).days / 365)
        present += dividends * factor
        rows.append({"period_end": end.isoformat(), "ffo_per_share_annualized": ffo,
                     "dividend_per_share": dividends, "pv_dividend_per_share": dividends * factor})
    terminal = dividends * (1 + growth) / (cost - growth)
    implied_tail = (case["market_price"] - present) / factor
    return {
        "value_per_share": present + terminal * factor, "forecast_rows": rows,
        "cost_of_equity": cost, "terminal_growth": growth, "forward_price_to_ffo": case["market_price"] / first["profit_or_ffo"],
        "implied_terminal_dividend_growth": ((implied_tail * cost - dividends) / (implied_tail + dividends)
                                             if implied_tail > 0 else None),
    }


def evaluate_equity(case, plan):
    method = case["method"]
    if method != plan["method"] or method not in LABELS:
        raise ValueError("Unsupported direct equity model")
    cutoff = date.fromisoformat(case["valuation_date"])
    ends = _periods(plan["estimates"], cutoff)
    cost = plan["cost_of_equity"]
    calc = _residual_path if method == "residual_income" else _reit_path
    scenarios = {}
    for name, tilt in SCENARIOS.items():
        growth = plan["terminal_growth"] + tilt * .005
        if not 0 <= growth < cost < 1:
            raise ValueError("Cost of equity must exceed terminal growth")
        scenarios[name] = calc(case, plan, cost, growth, tilt, cutoff, ends)
    base = scenarios["base"]
    sensitivity = []
    for delta in (-.01, 0, .01):
        adjusted = cost + delta
        value = calc(case, plan, adjusted, plan["terminal_growth"], 0, cutoff, ends)["value_per_share"] if adjusted > plan["terminal_growth"] else None
        sensitivity.append({"cost_of_equity": adjusted, "value_per_share": value})
    return {
        "equity_method": method, "method_label": LABELS[method], "market_price": case["market_price"],
        "status": "needs_review", "publication_ready": False, "scenarios": scenarios,
        "value_per_share": base["value_per_share"], "forecast_rows": base["forecast_rows"],
        "cost_of_equity": cost, "sensitivities": sensitivity,
        "checks": [{"severity": "warning", "code": "publication_rights_unresolved",
                    "message": "Workspace data and provider-derived results are local research drafts."}],
    }
