"""Deterministic FCFF valuation. No network access and no model-generated math."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import math
from typing import Any

from .validation import validate_case


def _check(case: dict) -> list[dict[str, str]]:
    checks = validate_case(case)
    errors = [item for item in checks if item["severity"] == "error"]
    if errors:
        raise ValueError("Invalid case: " + "; ".join(f"{i['code']}: {i['message']}" for i in errors))
    return checks


def _dcf(case: dict, terminal_margin: float | None = None) -> dict[str, Any]:
    """Calculate a prevalidated case. All monetary totals are in millions."""
    a = case["assumptions"]
    as_of = date.fromisoformat(case["valuation_date"])
    rows = []
    explicit_pv = 0.0
    for row in case["forecasts"]:
        years = (date.fromisoformat(row["period_end"]) - as_of).days / 365.0
        ebit = row["revenue"] * row["operating_margin"]
        nopat = ebit * (1.0 - row["tax_rate"])
        fcff = nopat - row["net_reinvestment"]
        discount_factor = (1.0 + a["wacc"]) ** (-years)
        pv = fcff * discount_factor
        explicit_pv += pv
        rows.append({
            **row, "discount_years": years, "ebit": ebit, "nopat": nopat,
            "fcff": fcff, "discount_factor": discount_factor, "pv_fcff": pv,
        })
    terminal_revenue = rows[-1]["revenue"] * (1.0 + a["terminal_growth"])
    margin = a["terminal_operating_margin"] if terminal_margin is None else terminal_margin
    terminal_nopat = terminal_revenue * margin * (1.0 - a["terminal_tax_rate"])
    reinvestment_rate = a["terminal_growth"] / a["terminal_roic"]
    terminal_reinvestment = terminal_nopat * reinvestment_rate
    terminal_fcff = terminal_nopat - terminal_reinvestment
    terminal_value = terminal_fcff / (a["wacc"] - a["terminal_growth"])
    terminal_pv = terminal_value * rows[-1]["discount_factor"]
    ev = explicit_pv + terminal_pv
    f = {name: item["value"] for name, item in case["facts"].items()}
    equity = ev + f["cash"] + f["other_nonoperating_assets"] - f["debt"] - f["other_claims"]
    value = equity / f["valuation_shares"]
    calculated_market_cap = f["market_price"] * f["shares_outstanding"]
    price_implied_diluted_equity = f["market_price"] * f["valuation_shares"]
    result = {
        "forecast_rows": rows,
        "terminal": {
            "revenue": terminal_revenue, "operating_margin": margin,
            "tax_rate": a["terminal_tax_rate"], "nopat": terminal_nopat,
            "reinvestment_rate": reinvestment_rate, "net_reinvestment": terminal_reinvestment,
            "fcff": terminal_fcff, "value_at_final_period_end": terminal_value,
            "present_value": terminal_pv,
        },
        "bridge": {
            "explicit_cash_flow_present_value": explicit_pv, "terminal_present_value": terminal_pv,
            "enterprise_value": ev, "cash": f["cash"],
            "other_nonoperating_assets": f["other_nonoperating_assets"],
            "debt": f["debt"], "other_claims": f["other_claims"],
            "equity_value": equity, "valuation_shares": f["valuation_shares"],
        },
        "enterprise_value": ev,
        "equity_value": equity,
        "value_per_share": value,
        "market_price": f["market_price"],
        "upside_fraction": value / f["market_price"] - 1.0,
        "derived_market_cap": calculated_market_cap,
        "price_implied_diluted_equity_value": price_implied_diluted_equity,
        "terminal_value_share": terminal_pv / ev if ev != 0 else None,
        "discount_convention": a["discount_convention"],
    }
    if not all(math.isfinite(number) for number in (ev, equity, value, terminal_value, terminal_pv,
                                                     explicit_pv, calculated_market_cap,
                                                     price_implied_diluted_equity, result["upside_fraction"])):
        raise ValueError("Non-finite computed valuation; inspect scales and assumptions.")
    return result


def reverse_terminal_margin(case: dict, target_price: float | None = None,
                            lower: float = 0.0, upper: float = 1.0) -> dict[str, Any]:
    """Solve for terminal EBIT margin only, leaving all explicit forecasts fixed.

This is a conditional mathematical solution, not a uniquely identified market
expectation or an explanation of a historical price move. Return no_solution
if the target lies outside the declared economic bracket; never clamp it.
"""
    _check(case)
    target = case["facts"]["market_price"]["value"] if target_price is None else target_price
    for name, value in (("target_price", target), ("lower", lower), ("upper", upper)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
    if target <= 0 or not 0 <= lower < upper <= 1:
        raise ValueError("Target price must be positive and the margin bracket must satisfy 0 <= lower < upper <= 1.")
    lo_price = _dcf(case, lower)["value_per_share"]
    hi_price = _dcf(case, upper)["value_per_share"]
    context = {
        "target_price": target,
        "margin_bracket": [lower, upper],
        "price_at_lower_margin": lo_price, "price_at_upper_margin": hi_price,
        "changed_parameter": "terminal_operating_margin_only",
        "conditions": "All explicit forecast margins, revenue, reinvestment, taxes, WACC, terminal growth/ROIC and the equity bridge remain fixed. A terminal margin discontinuity is possible.",
    }
    if not lo_price <= target <= hi_price or hi_price <= lo_price:
        return {**context, "status": "no_solution", "terminal_operating_margin": None,
                "recomputed_price": None, "price_residual": None,
                "reason": "No solution within the declared terminal-margin bracket; the target must not be forced into the model."}
    # Price is affine in the terminal margin when every other input is fixed.
    margin = lower + (target - lo_price) / (hi_price - lo_price) * (upper - lower)
    recomputed = _dcf(case, margin)["value_per_share"]
    return {**context, "status": "solved", "terminal_operating_margin": margin,
            "recomputed_price": recomputed, "price_residual": recomputed - target,
            "reason": "Conditional solution; does not identify investors' unique beliefs."}


def sensitivity_table(case: dict, wacc_offsets: tuple[float, ...] = (-0.01, 0.0, 0.01),
                      growth_offsets: tuple[float, ...] = (-0.005, 0.0, 0.005)) -> list[dict[str, Any]]:
    """Recompute WACC/g sensitivities, including terminal reinvestment changes."""
    _check(case)
    cells = []
    for wacc_offset in wacc_offsets:
        for growth_offset in growth_offsets:
            shifted = deepcopy(case)
            shifted["assumptions"]["wacc"] += wacc_offset
            shifted["assumptions"]["terminal_growth"] += growth_offset
            issues = validate_case(shifted)
            errors = [item["code"] for item in issues if item["severity"] == "error"]
            cells.append({
                "wacc": shifted["assumptions"]["wacc"],
                "terminal_growth": shifted["assumptions"]["terminal_growth"],
                "value_per_share": None if errors else _dcf(shifted)["value_per_share"],
                "status": "invalid_assumptions" if errors else "calculated",
                "errors": errors,
            })
    return cells


def evaluate_case(case: dict) -> dict[str, Any]:
    """Produce an auditable draft; this function cannot approve publication."""
    checks = _check(case)
    result = _dcf(case)
    if result["bridge"]["equity_value"] < 0:
        checks.append({"severity": "warning", "code": "negative_equity_value",
                       "message": "Negative modeled equity value is not a tradable negative share price; distress, limited liability and financing need specialist analysis."})
    terminal_share = result["terminal_value_share"]
    if terminal_share is not None and terminal_share > 0.75:
        checks.append({"severity": "warning", "code": "terminal_value_dominance",
                       "message": "More than 75% of enterprise value comes from terminal value; inspect long-run assumptions and sensitivities."})
    return {
        "schema_version": "0.1", "company": deepcopy(case["company"]),
        "valuation_date": case["valuation_date"], "units": deepcopy(case["units"]),
        "synthetic": case["synthetic"], "status": "research_draft",
        "publication_ready": False,
        "review_required": "Source-content verification, accounting normalization, forecast justification, rights review and human review are not automated by this financial core.",
        "checks": checks, **result,
        "reverse_dcf": reverse_terminal_margin(case),
        "sensitivities": sensitivity_table(case),
        "limitations": [
            "The engine calculates supplied forecasts; it does not retrieve or normalize company financials.",
            "Source metadata validation does not establish that the source actually supports the input.",
            "The implemented route assumes positive operating forecasts and simple cash taxes; banks, insurers, REITs, losses/NOLs and distressed claims require specialist models.",
            "Net reinvestment must already include all net operating investment, including content and working capital, exactly once.",
            "All forecast cash flows are placed at period end under ACT/365; no midyear convention or automated stub estimation is implemented.",
            "The reverse DCF changes terminal margin only and can introduce a discontinuity from the final explicit year; it is a conditional calculation, not a uniquely observed market expectation.",
            "A metadata permission assertion does not establish legal rights or authorize publication.",
        ],
    }
