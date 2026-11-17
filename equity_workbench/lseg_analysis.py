"""Turn a frozen Workspace snapshot into a reproducible equity DCF."""

from calendar import monthrange
from datetime import date, datetime, time, timezone
from statistics import median
from zoneinfo import ZoneInfo

from .cli import input_template
from .lseg_workspace import REQUESTS, quote_currency, request_specs, valuation_route
from .validation import _number, zoned_timestamp


LSEG_METHOD = "https://developers.lseg.com/en/article-catalog/article/fundamentals-estimates-dcf"
LSEG_DATA = "https://developers.lseg.com/en/api-catalog/lseg-data-platform/lseg-data-library-for-python"
PERIOD = "TR.TotalRevenue.periodenddate"


def cell(row, code):
    value = row.get(code.upper())
    if value is None or value == "":
        raise ValueError(f"Workspace returned no value for {code}; check coverage and entitlements")
    return value


def numeric(row, code, *, optional=False):
    value = row.get(code.upper()) if optional else cell(row, code)
    if optional and value in (None, ""):
        return None
    if not _number(value):
        raise ValueError(f"Workspace returned a nonnumeric value for {code}")
    return value


def day(row, code):
    return date.fromisoformat(cell(row, code)[:10])


def one_row(ric, rows, group):
    if len(rows) != 1 or rows[0].get("Instrument", "").casefold() != ric.casefold():
        raise ValueError(f"Expected one {group} observation for the exact RIC {ric}")
    return rows[0]


def check_identity(ric, rows):
    row = one_row(ric, rows, "identity")
    sector = cell(row, "TR.TRBCEconomicSector")
    if sector in {"Financials", "Real Estate"}:
        raise ValueError(f"{sector} requires a dedicated valuation model")
    if cell(row, "TR.InstrumentType") != "Ordinary Shares":
        raise ValueError("Select a primary ordinary-share listing")
    primary = cell(row, "TR.PrimaryRIC")
    if primary.casefold() != ric.casefold():
        raise ValueError(f"Use the primary RIC from Workspace: {primary}")
    exchange = cell(row, "TR.ExchangeName")
    if ("nasdaq" not in exchange.casefold() and exchange != "New York Stock Exchange"
            or cell(row, "TR.PriceClose.currency") != "USD" or not cell(row, "TR.ISIN").startswith("US")):
        raise ValueError("This DCF covers US ordinary shares in USD on Nasdaq or NYSE")
    price_day = day(row, "TR.PriceClose.date")
    if any(day(row, code) != price_day for code in ("TR.CompanyMarketCap.date", "TR.IssueMarketCap.date")):
        raise ValueError("Workspace price and market capitalization must have the same trading date")
    company_cap = numeric(row, "TR.CompanyMarketCap")
    issue_cap = numeric(row, "TR.IssueMarketCap")
    if company_cap <= 0 or abs(issue_cap / company_cap - 1) > .01:
        raise ValueError("Issue and company market capitalization differ; this listing needs a share-class valuation")
    return row


def check_market_identity(ric, rows, requested_isin=None):
    row = one_row(ric, rows, "identity")
    primary = cell(row, "TR.PrimaryRIC")
    if primary.casefold() != ric.casefold() or cell(row, "TR.InstrumentType") != "Ordinary Shares":
        raise ValueError(f"Select the primary ordinary-share listing: {primary}")
    isin = cell(row, "TR.ISIN")
    if requested_isin and isin != requested_isin:
        raise ValueError(f"Workspace identifier mismatch: expected ISIN {requested_isin}, got {isin}")
    currency, _ = quote_currency(cell(row, "TR.PriceClose.currency"))
    if not isinstance(currency, str) or len(currency) != 3 or currency.upper() != currency:
        raise ValueError("Quote currency requires an explicit unit conversion")
    quote_date = day(row, "TR.PriceClose.date")
    for prefix in ("TR.CompanyMarketCap", "TR.IssueMarketCap"):
        if cell(row, prefix + ".currency") != currency or day(row, prefix + ".date") != quote_date:
            raise ValueError("Price and market caps must share a completed trading date and major currency")
    company, issue = (numeric(row, prefix) for prefix in ("TR.CompanyMarketCap", "TR.IssueMarketCap"))
    if not 0 < issue <= 1.01 * company:
        raise ValueError("Issue market capitalization cannot be reconciled to the company's capitalization")
    cell(row, "TR.TRBCEconomicSector")
    return row


def market_observation(identity, stamp):
    exchange = cell(identity, "TR.ExchangeName")
    currency, scale = quote_currency(cell(identity, "TR.PriceClose.currency"))
    quote_day = day(identity, "TR.PriceClose.date")
    name = exchange.casefold()
    if "nasdaq" in name or "new york" in name or "nyse" in name:
        zone, closing = ZoneInfo("America/New_York"), time(16)
    elif "london stock exchange" in name:
        zone, closing = ZoneInfo("Europe/London"), time(16, 30)
    elif name == "xetra":
        zone, closing = ZoneInfo("Europe/Berlin"), time(17, 30)
    else:
        zone, closing = timezone.utc, time(23, 59, 59)
    cutoff = stamp.astimezone(zone)
    quoted_at = datetime.combine(quote_day, closing, zone)
    if quoted_at > cutoff or (cutoff.date() - quote_day).days > 7:
        raise ValueError("Workspace did not return a recent completed close")
    price = numeric(identity, "TR.PriceClose") / scale
    if price <= 0:
        raise ValueError("Workspace closing price must be positive")
    return cutoff, quoted_at, currency, price


def statements(ric, rows, cutoff, *, annual):
    result = []
    for row in rows:
        if row.get("Instrument", "").casefold() != ric.casefold():
            raise ValueError("Workspace financials contain the wrong instrument")
        end = day(row, PERIOD)
        if end > cutoff:
            raise ValueError("Workspace financial period is after the information cutoff")
        record = {"period_end": end}
        codes = {
            "revenue": "TR.TotalRevenue", "ebit": "TR.EBIT", "pretax": "TR.NetIncomeBeforeTaxes",
            "tax": "TR.F.IncTax", "net_income": "TR.F.NetIncAfterMinIntr",
            "normalized_net_income": "TR.F.NormNetIncBottomLine", "interest": "TR.InterestExpense",
            "assets": "TR.TotalAssets", "liabilities": "TR.TotalLiabilities", "equity": "TR.TotalEquity",
            "debt": "TR.TotalDebt", "cash": "TR.CashAndSTInvestments",
            "senior_claims": "TR.F.DebtInclPrefEqMinIntrTot", "cfo": "TR.F.NetCashFlowOp",
            "cash_capex": "TR.F.PPEPurchCF", "stock_comp": "TR.F.ShrBasedPaymtCF",
            "shares_at_period_end": "TR.F.ComShrOutsTot",
            "eps_basic_shares": "TR.F.ShrUsedToCalcBasicEPSTot",
            "eps_diluted_shares": "TR.F.ShrUsedToCalcDilEPSTot",
        }
        record.update({name: numeric(row, code) for name, code in codes.items()})
        record["investments"] = numeric(row, "TR.LongTermInvestments", optional=True)
        record["gross_finance_lease_assets"] = numeric(row, "TR.F.ROUTangCapFinLeaseGrossSuppl", optional=True)
        record["noncurrent_finance_lease_debt"] = numeric(row, "TR.F.CapLeaseObligLT", optional=True)
        if abs(record["assets"] - record["liabilities"] - record["equity"]) > max(1, record["assets"] * .0001):
            raise ValueError(f"Workspace balance sheet fails to reconcile for {end}")
        if record["revenue"] <= 0 or any(record[key] < 0 for key in ("cash_capex", "stock_comp", "debt", "cash", "interest")):
            raise ValueError(f"Unexpected cash-flow sign or revenue for {end}")
        result.append(record)
    gap = (365, 366) if annual else range(85, 98)
    result.sort(key=lambda row: row["period_end"])
    if len(result) < (4 if annual else 5):
        raise ValueError("The workflow needs four full fiscal years and at least five fiscal quarters")
    if any((b["period_end"] - a["period_end"]).days not in gap for a, b in zip(result, result[1:])):
        raise ValueError("Workspace financial periods overlap or are missing, or the fiscal calendar needs a dedicated model")
    return result


def net_investment(window, opening, tax):
    """Estimate economic investment from cash conversion and gross finance-lease growth."""
    closing = window[-1]
    gross_start = opening["gross_finance_lease_assets"]
    gross_end = closing["gross_finance_lease_assets"]
    has_leases = (opening["noncurrent_finance_lease_debt"] or closing["noncurrent_finance_lease_debt"]
                  or gross_start is not None or gross_end is not None)
    sums = {key: sum(row[key] for row in window) for key in ("revenue", "ebit", "cfo", "cash_capex", "stock_comp", "interest")}
    if has_leases and (gross_start is None or gross_end is None):
        return {**sums, "lease_asset_growth_proxy": None, "cash_flow_proxy": None, "net_investment_rate": None}
    lease_growth = max(0, gross_end - gross_start) if has_leases else 0
    cash_proxy = sums["cfo"] - sums["cash_capex"] - sums["stock_comp"] + sums["interest"] * (1 - tax) - lease_growth
    return {
        **sums, "lease_asset_growth_proxy": lease_growth, "cash_flow_proxy": cash_proxy,
        "net_investment_rate": (sums["ebit"] * (1 - tax) - cash_proxy) / sums["revenue"],
    }


def consensus(ric, rows):
    row = one_row(ric, rows, "consensus")
    end = day(row, "TR.RevenueMean.periodenddate")
    if day(row, "TR.EBITMean.periodenddate") != end:
        raise ValueError("Revenue and EBIT consensus must refer to the same fiscal year")
    sales, ebit = numeric(row, "TR.RevenueMean"), numeric(row, "TR.EBITMean")
    if not 0 < ebit < sales:
        raise ValueError("Positive sales and operating income consensus are required")
    return {"period_end": end, "revenue": sales, "ebit": ebit}


def capital_assumptions(ric, rows, cutoff):
    row = one_row(ric, rows, "capital cost")
    as_of = day(row, "TR.WACC.date")
    if not 0 <= (cutoff - as_of).days <= 7:
        raise ValueError("StarMine WACC must be dated within seven days of the information cutoff")
    return {
        "method": "lseg_starmine", "as_of": as_of.isoformat(), "wacc": numeric(row, "TR.WACC") / 100,
        "beta": numeric(row, "TR.WACCBeta"), "cost_of_equity": numeric(row, "TR.WACCCostOfEquity") / 100,
        "debt_cost_component": numeric(row, "TR.WACCCostOfDebt") / 100,
        "debt_weight": numeric(row, "TR.WACCDebtWeight") / 100,
        "rationale": "LSEG StarMine point estimate. Compare the published WACC with the displayed weighted debt and equity cost components, without a second tax adjustment.",
    }


def _future_row(end, margin, tax, investment, rationale, **driver):
    return {
        "period_end": end.isoformat(), "operating_margin": margin, "tax_rate": tax,
        "capex_rate": 0, "depreciation_rate": 0, "net_other_investment_rate": investment,
        "working_capital_investment_rate": 0, "rationale": rationale, **driver,
    }


def scenario_paths(current, following, annual, quarters, cutoff, tax, wacc):
    recent = quarters[-1]
    years = [net_investment([b], a, tax) for a, b in zip(annual[-4:], annual[-3:])]
    ttm = net_investment(quarters[-4:], quarters[-5], tax)
    latest_rates = [row["net_investment_rate"] for row in (years[-1], ttm) if row["net_investment_rate"] is not None]
    historic_rates = [year["net_investment_rate"] for year in years if year["net_investment_rate"] is not None]
    if not latest_rates:
        raise ValueError("Current economic reinvestment requires a gross finance-lease roll-forward")
    reinvestment = max(latest_rates + ([median(historic_rates)] if historic_rates else []))
    if not 0 < ttm["ebit"] < ttm["revenue"] or not 0 <= reinvestment <= .8:
        raise ValueError("Cash conversion or trading profitability is outside the automatic FCFF model")
    annual_end = annual[-1]["period_end"]
    fiscal_history = [q for q in quarters if annual[-2]["period_end"] < q["period_end"] <= annual_end]
    if len(fiscal_history) != 4:
        raise ValueError("Four fiscal quarters are required to reconcile annual data")
    for key in ("revenue", "ebit", "cfo", "cash_capex", "stock_comp"):
        actual = annual[-1][key]
        if abs(sum(q[key] for q in fiscal_history) - actual) > max(1, .005 * abs(actual)):
            raise ValueError(f"Discrete fiscal quarters fail to reconcile to FY0 for {key}")

    end = current["period_end"]
    next_end = following["period_end"]
    if not annual_end <= recent["period_end"] <= cutoff < end or (end - annual_end).days not in (365, 366):
        raise ValueError("The first consensus fiscal year does not follow the latest reported fiscal year")
    if (next_end - end).days not in (365, 366):
        raise ValueError("The next consensus year must be a full consecutive fiscal year")
    reported_this_fy = [row for row in quarters if row["period_end"] > annual_end]
    remaining_sales = current["revenue"] - sum(row["revenue"] for row in reported_this_fy)
    remaining_ebit = current["ebit"] - sum(row["ebit"] for row in reported_this_fy)
    if not 0 < remaining_ebit < remaining_sales:
        raise ValueError("Consensus less reported fiscal quarters does not give a positive operating stub")
    fraction = (end - cutoff).days / (end - recent["period_end"]).days
    near_growth = following["revenue"] / current["revenue"] - 1
    near_margin = following["ebit"] / following["revenue"]
    normal_margin = (near_margin + median(row["ebit"] / row["revenue"] for row in annual[-3:])) / 2
    capital = [row["equity"] + row["debt"] - row["cash"] - (row["investments"] or 0) for row in annual[-4:]]
    if any(value <= 0 for value in capital):
        raise ValueError("The reported capital base needs a dedicated ROIC analysis")
    returns = [row["ebit"] * (1-tax) / ((a + b) / 2)
               for row, a, b in zip(annual[-3:], capital, capital[1:])]
    base_roic = min(.25, max(.06, (median(returns) + wacc) / 2))
    paths = {}
    for name, tilt in (("downside", -1), ("base", 0), ("upside", 1)):
        rationale = {
            "downside": "Test slower growth, lower margins and greater near-term operating investment.",
            "base": "Anchor near-term sales and EBIT to Workspace consensus and fade toward mature economics.",
            "upside": "Test stronger growth, higher margins and lower near-term operating investment.",
        }[name]
        g = .025 + tilt * .005
        roic = base_roic + tilt * .02
        if wacc <= g or roic <= g:
            raise ValueError("StarMine WACC or estimated terminal ROIC is below the model's terminal growth")
        terminal_margin = normal_margin * (1 + tilt * .1)
        terminal_investment = terminal_margin * (1-tax) * g / roic
        stub = _future_row(
            end, remaining_ebit / remaining_sales, tax, reinvestment,
            "FY1 consensus less reported discrete quarters, prorated for days still ahead. Reinvestment is based on historical cash conversion.",
            revenue=remaining_sales * fraction,
        )
        future = []
        for offset in range(5):
            year = next_end.year + offset
            m = next_end.month
            year_end = next_end if offset == 0 else date(year, m, min(next_end.day, monthrange(year, m)[1]))
            fade = offset / 4
            margin = near_margin * (1 + tilt * .1) * (1 - fade) + terminal_margin * fade
            growth = (near_growth + tilt * .03) * (1 - fade) + g * fade
            invest = max(0, reinvestment - tilt * .015) * (1 - fade) + terminal_investment * fade
            future.append(_future_row(year_end, margin, tax, invest, rationale, revenue_growth=growth))
        paths[name] = {
            "rationale": rationale, "stub": stub, "annual": future,
            "terminal": {"growth": g, "roic": roic, "tax_rate": tax,
                         "operating_margin": future[-1]["operating_margin"],
                         "rationale": "Scenario policy for long-run USD growth. ROIC fades halfway from historical book ROIC toward WACC, within model bounds."},
        }
    return paths, years, ttm


def materialize_workspace(snapshot):
    schema = snapshot.get("schema")
    if schema not in {"lseg-workspace-1", "lseg-workspace-2"}:
        raise ValueError("Unsupported Workspace snapshot version")
    stamp = zoned_timestamp(snapshot.get("snapshot_at"))
    if stamp is None:
        raise ValueError("Workspace snapshot requires a timestamp with UTC offset")
    ric = snapshot["ric"]
    requests = snapshot["requests"]
    def rows(key):
        return requests[key]["rows"]

    if schema == "lseg-workspace-1":
        identity = check_identity(ric, rows("identity"))
        route, specs = "fcff", REQUESTS
    else:
        identity = check_market_identity(ric, rows("identity"), snapshot.get("requested_isin"))
        route = valuation_route(identity)
        if route != snapshot.get("route"):
            raise ValueError("The snapshot valuation route does not match the issuer classification")
        specs = request_specs(route, quote_currency(cell(identity, "TR.PriceClose.currency"))[0])
    for key, (fields, parameters) in specs.items():
        request = requests[key]
        if request.get("fields") != list(fields) or request.get("parameters") != parameters:
            raise ValueError(f"Snapshot field definitions or units differ for the Workspace {key} request")
    cutoff, quoted_at, currency, price = market_observation(identity, stamp)
    quote_day = quoted_at.date()
    if route != "fcff":
        from .equity_models import prepare_equity
        return prepare_equity(ric, identity, requests, route, cutoff, quoted_at, currency, price)
    annual = statements(ric, rows("annual"), cutoff.date(), annual=True)
    quarterly = statements(ric, rows("quarterly"), cutoff.date(), annual=False)
    quarter = quarterly[-1]
    if (cutoff.date() - quarter["period_end"]).days > 150:
        raise ValueError("The latest Workspace financial period is too old for the automatic workflow")
    recent_tax = [row["tax"] / row["pretax"] for row in annual[-3:] if row["pretax"] > 0 and row["ebit"] > 0]
    if len(recent_tax) != 3 or any(not 0 <= rate <= .5 for rate in recent_tax):
        raise ValueError("A three-year positive-earnings tax history is required for the cash tax proxy")
    tax = median(recent_tax)
    current = consensus(ric, rows("consensus_fy1"))
    following = consensus(ric, rows("consensus_fy2"))
    capital = capital_assumptions(ric, rows("capital"), cutoff.date())
    paths, historical_cash, ttm = scenario_paths(current, following, annual, quarterly, cutoff.date(), tax, capital["wacc"])
    market_cap = numeric(identity, "TR.CompanyMarketCap") / 1e6
    issue_cap = numeric(identity, "TR.IssueMarketCap") / 1e6
    basic_shares = market_cap / price
    if quarter["shares_at_period_end"] <= 0 or abs(basic_shares / quarter["shares_at_period_end"] - 1) > .05:
        raise ValueError("Price-implied shares fail to reconcile to the latest reported share count")
    dilution = quarter["eps_diluted_shares"] - quarter["eps_basic_shares"]
    claims = quarter["senior_claims"] - quarter["debt"]
    if min(dilution, claims) < 0 or dilution > .1 * basic_shares:
        raise ValueError("Share dilution or senior claims require instrument-specific review")

    case = input_template(cell(identity, "TR.CommonName"), cutoff.date().isoformat())
    case["valuation_at"] = cutoff.isoformat()
    case["company"].update(ticker=ric, exchange=cell(identity, "TR.ExchangeName"), currency=currency)
    case["sources"] = [
        {"id": sid, "title": title, "url": LSEG_DATA if sid == "LSEG-QUOTE" else LSEG_METHOD,
         "published_at": quoted_at.isoformat() if sid == "LSEG-QUOTE" else cutoff.isoformat(),
         "retrieved_at": stamp.isoformat(), "redistribution": "unknown", "cloud_processing": "unknown"}
        for sid, title in (
            ("LSEG-QUOTE", f"Workspace closing market data for {ric}"),
            ("LSEG-FIN", "Workspace standardized annual and quarterly statements"),
            ("LSEG-EST", "Workspace current consensus estimates"),
            ("LSEG-WACC", "Workspace StarMine WACC"),
        )
    ]
    def fact(value, basis, market=False):
        return {
            "value": value, "basis": basis, "source_id": "LSEG-QUOTE" if market else "LSEG-FIN",
            "period_end": (quote_day if market else quarter["period_end"]).isoformat(),
        }

    case["facts"] = {
        "cash": fact(quarter["cash"], "Workspace TR.CashAndSTInvestments at fiscal quarter close; treats cash as excess."),
        "debt": fact(quarter["debt"], "Workspace TR.TotalDebt at carrying value, with finance leases where included."),
        "other_claims": fact(claims, "TR.F.DebtInclPrefEqMinIntrTot less TR.TotalDebt; carrying values."),
        "other_nonoperating_assets": fact(quarter["investments"] or 0,
                                         "TR.LongTermInvestments carrying value. No quantified bridge adjustment when this item is unavailable."),
        "shares_outstanding": fact(basic_shares, "Company cap / primary price. For multiclass firms this is a price-equivalent share count assuming the observed class share of total capitalization.", True),
        "valuation_shares": fact(basic_shares + dilution, "Matched-close shares plus the latest quarterly diluted-minus-basic EPS share increment as a proxy."),
        "market_cap": fact(market_cap, f"Workspace TR.CompanyMarketCap, millions of {currency}. Issue market cap {issue_cap:.3f}m.", True),
        "market_price": fact(price, "Workspace TR.PriceClose for the latest completed regular session.", True)
        | {"observed_at": quoted_at.isoformat(), "observation_basis": "latest_completed_session"},
    }
    normalized_gap = sum(q["net_income"] - q["normalized_net_income"] for q in quarterly[-4:])
    industry = cell(identity, "TR.TRBCIndustryGroup")
    plan = {
        "version": "1", "starting_annual_revenue": current["revenue"],
        "capital_cost": capital, "scenarios": paths,
        "research": {
            "ric": ric, "isin": cell(identity, "TR.ISIN"), "industry": industry, "market_day": quote_day.isoformat(),
            "annual": [row | {"period_end": row["period_end"].isoformat()} for row in annual[-4:]],
            "consensus": [row | {"period_end": row["period_end"].isoformat()} for row in (current, following)],
            "ttm": ttm, "normalized_income_gap": normalized_gap, "cash_history": historical_cash,
        },
        "editorial": {
            "business": f"{case['company']['name']} ({ric}), settore LSEG {industry}, ISIN {cell(identity, 'TR.ISIN')}.",
            "evidence": f"LSEG riporta ricavi per {ttm['revenue'] / 1000:.2f} mld {currency} e un margine EBIT del {ttm['ebit']/ttm['revenue']:.1%} sugli ultimi quattro trimestri.",
            "assumptions": "Stime LSEG di ricavi ed EBIT per i primi due esercizi, WACC StarMine e reinvestimento stimato dalla conversione in cassa.",
            "risk": "Verificare la sostenibilità dei margini, la qualità del flusso di cassa e la spesa per gli investimenti, inclusi gli impegni da leasing.",
            "falsifier": "Confrontare ricavi, margini e reinvestimento dei prossimi risultati con gli intervalli delle previsioni.",
        },
    }
    return case, plan
