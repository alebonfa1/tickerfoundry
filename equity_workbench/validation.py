"""Input validation for a deliberately narrow, explicit-forecast FCFF model.

Validation checks consistency and provenance metadata. It does not verify a
source's contents, confer data rights, or certify an investment conclusion.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import math
from typing import Any
from urllib.parse import urlparse


REQUIRED_FACTS = (
    "cash", "debt", "other_claims", "other_nonoperating_assets",
    "shares_outstanding", "valuation_shares", "market_price",
)
RIGHTS_VALUES = {"permitted", "restricted", "unknown"}


def _number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Normalize for deterministic comparison of date-only and zoned strings.
        if parsed.tzinfo is not None:
            from datetime import timezone
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def zoned_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def validate_case(case: Any) -> list[dict[str, str]]:
    """Return errors and warnings without filling, coercing, or fixing inputs."""
    issues: list[dict[str, str]] = []

    def add(code: str, message: str, severity: str = "error") -> None:
        issues.append({"severity": severity, "code": code, "message": message})

    if not isinstance(case, dict):
        add("case_type", "The case must be a JSON object.")
        return issues
    if case.get("schema_version") != "0.1":
        add("schema_version", "schema_version must be '0.1'.")
    if not isinstance(case.get("synthetic"), bool):
        add("synthetic_flag", "synthetic must explicitly be true or false.")
    elif case["synthetic"]:
        add("synthetic_fixture", "Fictional data: demonstration only, never a company valuation for publication.", "warning")

    as_of = _date(case.get("valuation_date"))
    if as_of is None:
        add("valuation_date", "valuation_date must be an ISO calendar date (YYYY-MM-DD).")
    cutoff = zoned_timestamp(case.get("valuation_at"))
    if "valuation_at" in case and (cutoff is None or cutoff.date() != as_of):
        add("valuation_at", "valuation_at must include a UTC offset and agree with valuation_date in market-local time.")

    company = case.get("company")
    if not isinstance(company, dict):
        add("company", "company must be an object.")
        company = {}
    for field in ("name", "ticker", "exchange", "currency"):
        if not isinstance(company.get(field), str) or not company[field].strip():
            add("company_" + field, f"company.{field} must be a nonempty string.")
    if company.get("sector_model") != "non_financial":
        add("unsupported_sector", "Only the non_financial FCFF route is implemented; banks, insurers, REITs and other specialist routes require their own model.")
    currency = company.get("currency")
    if isinstance(currency, str) and (len(currency) != 3 or not currency.isalpha() or currency != currency.upper()):
        add("currency", "Use one uppercase three-letter currency code throughout the case.")
    expected_units = {"money": "millions", "shares": "millions", "price": "currency_per_share"}
    if case.get("units") != expected_units:
        add("units", "units must explicitly be money='millions', shares='millions', price='currency_per_share'; normalize before importing.")

    sources = case.get("sources")
    source_map: dict[str, dict] = {}
    if not isinstance(sources, list) or not sources:
        add("sources", "At least one provenance source is required.")
        sources = []
    for index, source in enumerate(sources):
        path = f"sources[{index}]"
        if not isinstance(source, dict):
            add("source_type", f"{path} must be an object.")
            continue
        sid = source.get("id")
        if not isinstance(sid, str) or not sid.strip():
            add("source_id", f"{path}.id must be a nonempty string.")
        elif sid in source_map:
            add("duplicate_source_id", f"Duplicate source id: {sid}.")
        else:
            source_map[sid] = source
        if not isinstance(source.get("title"), str) or not source["title"].strip():
            add("source_title", f"{path}.title must be a nonempty string.")
        url = source.get("url")
        try:
            parsed_url = urlparse(url) if isinstance(url, str) else None
        except ValueError:
            parsed_url = None
        allowed_schemes = {"https", "http"} | ({"synthetic"} if case.get("synthetic") is True else set())
        if (parsed_url is None or parsed_url.scheme not in allowed_schemes or not parsed_url.hostname
                or parsed_url.username is not None or parsed_url.password is not None):
            add("source_url", f"{path}.url must be a source URL; synthetic:// is permitted only for fictional fixtures.")
        published = _timestamp(source.get("published_at"))
        retrieved = _timestamp(source.get("retrieved_at"))
        publication_time = zoned_timestamp(source.get("published_at"))
        if cutoff:
            if publication_time is None or zoned_timestamp(source.get("retrieved_at")) is None:
                add("source_timestamp_required", f"{path} requires offset-aware publication and retrieval timestamps.")
            elif publication_time > cutoff:
                add("lookahead_source", f"{path} was published after the valuation cutoff.")
        if published is None:
            add("source_publication_date", f"{path}.published_at must be an ISO date or timestamp.")
        elif as_of and not cutoff and published.date() > as_of:
            add("lookahead_source", f"{path} was published after valuation_date; it cannot support this historical valuation.")
        if retrieved is None:
            add("source_retrieval_date", f"{path}.retrieved_at must be an ISO date or timestamp.")
        elif published and retrieved < published:
            add("retrieval_before_publication", f"{path} was retrieved before its stated publication time.")
        for permission in ("redistribution", "cloud_processing"):
            if not isinstance(source.get(permission), str) or source[permission] not in RIGHTS_VALUES:
                add("source_rights", f"{path}.{permission} must be permitted, restricted or unknown.")
        if isinstance(source.get("redistribution"), str) and source["redistribution"] in {"unknown", "restricted"}:
            add("publication_rights_unresolved", f"{path} has no asserted permission for public redistribution. A metadata assertion is not a license review.", "warning")

    facts = case.get("facts")
    if not isinstance(facts, dict):
        add("facts", "facts must be an object.")
        facts = {}
    for name in REQUIRED_FACTS:
        if name not in facts:
            add("missing_fact", f"facts.{name} is required; missing values are not zero.")
    for name, fact in facts.items():
        path = f"facts.{name}"
        if not isinstance(fact, dict):
            add("fact_type", f"{path} must include value, source_id, period_end and basis.")
            continue
        value = fact.get("value")
        if not _number(value):
            add("fact_value", f"{path}.value must be a finite number; null, booleans and numeric strings are not accepted.")
        elif value < 0 or (name in {"shares_outstanding", "valuation_shares", "market_price"} and value <= 0):
            add("fact_range", f"{path} must be nonnegative; share counts and market price must be strictly positive.")
        sid = fact.get("source_id")
        if not isinstance(sid, str) or sid not in source_map:
            add("unknown_source", f"{path}.source_id does not resolve to a source.")
        fact_date = _date(fact.get("period_end"))
        if fact_date is None:
            add("fact_period", f"{path}.period_end must be YYYY-MM-DD.")
        elif as_of:
            if fact_date > as_of:
                add("lookahead_fact", f"{path}.period_end is after valuation_date.")
            elif (as_of - fact_date).days > (7 if name == "market_price" else 180):
                add("stale_fact", f"{path} is dated {fact_date}; confirm it is suitable for {as_of}.", "warning")
        source = source_map.get(sid) if isinstance(sid, str) else None
        publication = (zoned_timestamp(source.get("published_at")) if cutoff
                       else _timestamp(source.get("published_at"))) if source else None
        if fact_date and publication and fact_date > publication.date():
            add("fact_after_source_publication", f"{path}.period_end is later than the referenced source's publication date; that source cannot support the later observation.")
        if not isinstance(fact.get("basis"), str) or not fact["basis"].strip():
            add("fact_basis", f"{path}.basis must explain its definition, including share-count and claims treatment.")
        if cutoff and name == "market_price":
            observed = zoned_timestamp(fact.get("observed_at"))
            if fact.get("observation_basis") == "latest_completed_session":
                if (observed is None or observed > cutoff or observed.date() != fact_date
                        or not 0 <= (cutoff.date() - observed.date()).days <= 7):
                    add("market_close_mismatch", f"{path} requires a completed session within seven calendar days of the cutoff.")
            elif observed is None or observed != cutoff or cutoff.date() != fact_date:
                add("market_close_mismatch", f"{path}.observed_at must match the selected closing cutoff and session.")

    def fact_value(name: str) -> float | None:
        item = facts.get(name)
        value = item.get("value") if isinstance(item, dict) else None
        return value if _number(value) else None

    basic, diluted = fact_value("shares_outstanding"), fact_value("valuation_shares")
    if basic is not None and diluted is not None and diluted < basic:
        add("dilution_basis", "valuation_shares cannot be below current shares_outstanding in this model; reconcile dates and dilution treatment.")
    observed_cap, price = fact_value("market_cap"), fact_value("market_price")
    if observed_cap is not None and price is not None and basic is not None and price > 0 and basic > 0:
        calculated_cap = price * basic
        if abs(observed_cap - calculated_cap) > max(0.01 * calculated_cap, 1e-9):
            add("market_cap_mismatch", "Reported market_cap differs by more than 1% from price × basic shares; reconcile dates, units and corporate actions.")

    assumptions = case.get("assumptions")
    if not isinstance(assumptions, dict):
        add("assumptions", "assumptions must be an object.")
        assumptions = {}
    for name in ("wacc", "terminal_growth", "terminal_roic", "terminal_operating_margin", "terminal_tax_rate"):
        if not _number(assumptions.get(name)):
            add("assumption_value", f"assumptions.{name} must be a finite number.")
    if not isinstance(assumptions.get("rationale"), str) or not assumptions["rationale"].strip():
        add("assumption_rationale", "assumptions.rationale must explain the economic assumptions and their sources or judgments.")
    if assumptions.get("discount_convention") != "end_period_actual_365":
        add("discount_convention", "The implemented convention must be declared: end_period_actual_365 (end-period cash flows, actual days / 365).")
    wacc, growth, roic = (assumptions.get(k) for k in ("wacc", "terminal_growth", "terminal_roic"))
    if _number(wacc) and wacc <= 0:
        add("wacc_range", "WACC must be strictly positive.")
    if _number(growth) and growth < 0:
        add("terminal_growth_range", "Negative perpetual growth needs a separate run-off model; this starter supports nonnegative terminal growth.")
    if _number(roic) and roic <= 0:
        add("terminal_roic_range", "Terminal ROIC must be strictly positive.")
    if _number(wacc) and _number(growth) and wacc <= growth:
        add("terminal_spread", "WACC must be strictly greater than terminal growth.")
    elif _number(wacc) and _number(growth) and wacc - growth < 0.02:
        add("narrow_terminal_spread", "WACC minus terminal growth is below two percentage points; value is highly sensitive.", "warning")
    if _number(growth) and _number(roic) and growth >= roic:
        add("terminal_reinvestment", "This positive-terminal-FCFF model requires terminal growth < terminal ROIC; growth/ROIC must be below 100%.")
    for name in ("terminal_operating_margin", "terminal_tax_rate"):
        if _number(assumptions.get(name)) and not 0 <= assumptions[name] <= 1:
            add("assumption_range", f"assumptions.{name} must be between 0 and 1.")
    if _number(assumptions.get("terminal_tax_rate")) and assumptions["terminal_tax_rate"] == 1:
        add("terminal_tax", "A 100% terminal tax rate is outside this positive-terminal-FCFF model.")

    forecasts = case.get("forecasts")
    if not isinstance(forecasts, list) or not forecasts:
        add("forecasts", "At least one explicit future forecast period is required.")
        forecasts = []
    previous_end = as_of
    for index, row in enumerate(forecasts):
        path = f"forecasts[{index}]"
        if not isinstance(row, dict):
            add("forecast_type", f"{path} must be an object.")
            continue
        start, end = _date(row.get("period_start")), _date(row.get("period_end"))
        if start is None or end is None:
            add("forecast_dates", f"{path} requires ISO period_start and period_end dates.")
        else:
            if end < start:
                add("forecast_order", f"{path} ends before it starts.")
            if as_of and start <= as_of:
                add("elapsed_forecast", f"{path} contains already elapsed cash flows. Only cash flows after valuation_date may be discounted.")
            if previous_end and start != previous_end + timedelta(days=1):
                add("forecast_gap_or_overlap", f"{path} must begin on the day after the preceding period (or valuation_date).")
            days = (end - start).days + 1
            if days > 366 or days <= 0:
                add("forecast_period_length", f"{path} must cover at most one year; use explicit consecutive forecast periods.")
            if index == len(forecasts) - 1 and days not in (365, 366):
                add("terminal_annualization", "The final forecast must cover a full 365/366-day year before a perpetuity is applied.")
            previous_end = end
        for name in ("revenue", "operating_margin", "tax_rate", "net_reinvestment"):
            if not _number(row.get(name)):
                add("forecast_value", f"{path}.{name} must be a finite number.")
        if _number(row.get("revenue")) and row["revenue"] <= 0:
            add("forecast_revenue", f"{path}.revenue must be positive in this operating-company model.")
        for name in ("operating_margin", "tax_rate"):
            if _number(row.get(name)) and not 0 <= row[name] <= 1:
                add("forecast_range", f"{path}.{name} must be between 0 and 1; losses and tax-loss carryforwards require a specialist extension.")
        if _number(row.get("net_reinvestment")) and row["net_reinvestment"] < 0:
            add("negative_reinvestment", f"{path} assumes a net release of invested capital; explain why it is sustainable for this period.", "warning")
        if not isinstance(row.get("rationale"), str) or not row["rationale"].strip():
            add("forecast_rationale", f"{path}.rationale must explain the forecast and the all-inclusive net-reinvestment calculation.")
    return issues
