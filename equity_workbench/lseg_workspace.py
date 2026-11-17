"""Read-only LSEG Workspace requests and local snapshot capture."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re


IDENTITY = (
    "TR.CommonName", "TR.PrimaryRIC", "TR.ExchangeName", "TR.ISIN", "TR.InstrumentType",
    "TR.TRBCEconomicSector", "TR.TRBCIndustryGroup",
    "TR.PriceClose", "TR.PriceClose.date", "TR.PriceClose.currency",
    "TR.CompanyMarketCap", "TR.CompanyMarketCap.date", "TR.IssueMarketCap", "TR.IssueMarketCap.date",
)
MARKET_CURRENCIES = ("TR.CompanyMarketCap.currency", "TR.IssueMarketCap.currency")
STATEMENTS = (
    "TR.TotalRevenue.periodenddate", "TR.TotalRevenue", "TR.EBIT", "TR.NetIncomeBeforeTaxes",
    "TR.F.IncTax", "TR.F.NetIncAfterMinIntr", "TR.F.NormNetIncBottomLine", "TR.InterestExpense",
    "TR.TotalAssets", "TR.TotalLiabilities", "TR.TotalEquity", "TR.TotalDebt", "TR.CashAndSTInvestments",
    "TR.F.DebtInclPrefEqMinIntrTot", "TR.LongTermInvestments",
    "TR.F.NetCashFlowOp", "TR.F.PPEPurchCF", "TR.F.ShrBasedPaymtCF",
    "TR.F.ROUTangCapFinLeaseGrossSuppl", "TR.F.CapLeaseObligLT",
    "TR.F.ComShrOutsTot", "TR.F.ShrUsedToCalcBasicEPSTot", "TR.F.ShrUsedToCalcDilEPSTot",
)
ESTIMATES = ("TR.RevenueMean.periodenddate", "TR.RevenueMean", "TR.EBITMean.periodenddate", "TR.EBITMean")
CAPITAL = ("TR.WACC.date", "TR.WACC", "TR.WACCBeta",
           "TR.WACCCostOfEquity", "TR.WACCCostOfDebt", "TR.WACCDebtWeight")
MONEY = {"Curn": "USD", "Scale": 6}
REQUESTS = {
    "identity": (IDENTITY, {}),
    "annual": (STATEMENTS, MONEY | {"Period": "FY0", "Frq": "FY", "SDate": 0, "EDate": -3}),
    "quarterly": (STATEMENTS, MONEY | {"Period": "FQ0", "Frq": "FQ", "SDate": 0, "EDate": -7}),
    "consensus_fy1": (ESTIMATES, MONEY | {"Period": "FY1"}),
    "consensus_fy2": (ESTIMATES, MONEY | {"Period": "FY2"}),
    "capital": (CAPITAL, {}),
}
EQUITY_HISTORY = (
    "TR.F.ShHoldEqCom.periodenddate", "TR.F.ShHoldEqCom", "TR.F.IncAvailToComShr",
    "TR.F.ComShrOutsTot", "TR.F.ShrUsedToCalcBasicEPSTot", "TR.F.ShrUsedToCalcDilEPSTot",
    "TR.F.DivPaidCashTotCF", "TR.F.ComStockBuybackNet",
)
EQUITY_ESTIMATES = (
    "TR.NetProfitMean.periodenddate", "TR.NetProfitMean", "TR.DPSMean.periodenddate", "TR.DPSMean",
)
REIT_ESTIMATES = ("TR.FFOMean.periodenddate", "TR.FFOMean", "TR.DPSMean.periodenddate", "TR.DPSMean")
EQUITY_CAPITAL = ("TR.WACC.date", "TR.WACCCostOfEquity", "TR.WACCBeta")
FX_MINOR = {"GBp": ("GBP", 100), "GBX": ("GBP", 100), "ZAc": ("ZAR", 100), "ILA": ("ILS", 100)}


def quote_currency(value):
    return FX_MINOR.get(value, (value, 1))


def valuation_route(row):
    sector = row.get("TR.TRBCECONOMICSECTOR")
    if sector == "Financials":
        return "residual_income"
    if sector == "Real Estate" and "REIT" in (row.get("TR.TRBCINDUSTRYGROUP") or ""):
        return "reit_dividends"
    return "fcff"


def request_specs(route, currency):
    if route == "fcff":
        return {
            key: (fields if key != "identity" else fields + MARKET_CURRENCIES,
                  params | {"Curn": currency} if "Curn" in params else params)
            for key, (fields, params) in REQUESTS.items()
        }
    money = MONEY | {"Curn": currency}
    estimates = EQUITY_ESTIMATES if route == "residual_income" else REIT_ESTIMATES
    specs = {"identity": (IDENTITY + MARKET_CURRENCIES, {})}
    if route == "residual_income":
        specs.update({
            "annual": (EQUITY_HISTORY, money | {"Period": "FY0", "Frq": "FY", "SDate": 0, "EDate": -3}),
            "quarterly": (EQUITY_HISTORY, money | {"Period": "FQ0", "Frq": "FQ", "SDate": 0, "EDate": -7}),
        })
    specs.update({
        "consensus_fy1": (estimates, money | {"Period": "FY1"}),
        "consensus_fy2": (estimates, money | {"Period": "FY2"}),
        "capital": (EQUITY_CAPITAL, {}),
    })
    return specs


def check_ric(value):
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,24}", value):
        raise ValueError("Enter a primary equity RIC such as MSFT.O or use search to look it up")
    return value


def resolve_listing(ld, identifier):
    value = check_ric(identifier)
    isin = re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", value.upper())
    if "." in value:
        return value, None
    kinds = ld.discovery.SymbolTypes
    kind = kinds.ISIN if isin else kinds.TICKER_SYMBOL
    try:
        frame = ld.discovery.convert_symbols(
            [value.upper()], from_symbol_type=kind, to_symbol_types=[kinds.RIC],
        )
        matches = sorted({row["RIC"] for row in rows_from_frame(frame) if row.get("RIC")})
    except Exception as exc:
        raise RuntimeError(f"Workspace symbology request failed ({type(exc).__name__}). Use the primary RIC.") from exc
    if len(matches) != 1:
        choices = ", ".join(matches[:12]) or "none"
        raise ValueError(f"{identifier} did not resolve to exactly one listing ({choices}). Supply a primary RIC.")
    return matches[0], value.upper() if isin else None


@contextmanager
def desktop_session():
    try:
        import lseg.data as ld
    except ImportError as exc:
        raise RuntimeError('Install the LSEG integration with python -m pip install ".[lseg]"') from exc
    try:
        session = ld.open_session(name="desktop.workspace")
    except Exception as exc:
        raise RuntimeError(
            f"Workspace desktop connection failed ({type(exc).__name__}). Open Workspace, sign in, "
            "and check that your subscription supports the LSEG Data Library."
        ) from exc
    try:
        if getattr(session.open_state, "name", None) != "Opened":
            raise RuntimeError("Workspace desktop session is closed. Sign in to Workspace and retry.")
        yield ld
    finally:
        ld.close_session()


def rows_from_frame(frame):
    return json.loads(frame.to_json(orient="records", date_format="iso", double_precision=15))


def search(query):
    if not query.strip():
        raise ValueError("Enter a company name or a ticker")
    with desktop_session() as ld:
        try:
            frame = ld.discovery.search(
                view=ld.discovery.Views.EQUITY_QUOTES,
                query=query, select="RIC,DocumentTitle,ExchangeName", top=25,
            )
            return [
                row for row in rows_from_frame(frame)
                if row.get("RIC") and "Ordinary Share" in (row.get("DocumentTitle") or "")
            ]
        except Exception as exc:
            raise RuntimeError(f"LSEG search failed ({type(exc).__name__}). Try the exact RIC.") from exc


def fetch_snapshot(identifier):
    from .lseg_analysis import check_market_identity

    groups = {}
    with desktop_session() as ld:
        ric, requested_isin = resolve_listing(ld, identifier)
        def get(key, fields, parameters):
            try:
                frame = ld.get_data(ric, list(fields), parameters or None, header_type=ld.HeaderType.NAME)
                groups[key] = {"fields": list(fields), "parameters": parameters, "rows": rows_from_frame(frame)}
            except Exception as exc:
                raise RuntimeError(
                    f"LSEG {key} request failed ({type(exc).__name__}). Check the RIC and Workspace data entitlements."
                ) from exc

        get("identity", IDENTITY + MARKET_CURRENCIES, {})
        identity = check_market_identity(ric, groups["identity"]["rows"], requested_isin)
        route = valuation_route(identity)
        currency, _ = quote_currency(identity["TR.PRICECLOSE.CURRENCY"])
        for key, (fields, parameters) in request_specs(route, currency).items():
            if key != "identity":
                get(key, fields, parameters)
        return {
            "schema": "lseg-workspace-2", "ric": ric, "identifier": identifier,
            "requested_isin": requested_isin, "route": route, "sdk_version": ld.__version__,
            "snapshot_at": datetime.now(timezone.utc).isoformat(), "requests": groups,
        }
