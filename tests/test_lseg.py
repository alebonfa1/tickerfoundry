"""Fictional response shapes for the Workspace-to-DCF boundary."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from equity_workbench.cli import load_json, main, write_json
from equity_workbench.lseg_analysis import materialize_workspace
from equity_workbench.lseg_workspace import REQUESTS
from equity_workbench.model import evaluate_plan


RIC = "EXAMPLE.O"


def tagged(values):
    return {"Instrument": RIC, **{key.upper(): value for key, value in values.items()}}


def financial_row(period, revenue):
    return tagged({
        "TR.TotalRevenue.periodenddate": period, "TR.TotalRevenue": revenue, "TR.EBIT": .2 * revenue,
        "TR.NetIncomeBeforeTaxes": .19 * revenue, "TR.F.IncTax": .0475 * revenue,
        "TR.F.NetIncAfterMinIntr": .1425 * revenue, "TR.F.NormNetIncBottomLine": .1425 * revenue,
        "TR.InterestExpense": .01 * revenue, "TR.TotalAssets": 900, "TR.TotalEquity": 500,
        "TR.TotalLiabilities": 400, "TR.TotalDebt": 200, "TR.CashAndSTInvestments": 50,
        "TR.F.DebtInclPrefEqMinIntrTot": 200, "TR.F.NetCashFlowOp": .16 * revenue,
        "TR.F.PPEPurchCF": .03 * revenue, "TR.F.ShrBasedPaymtCF": .01 * revenue,
        "TR.F.ComShrOutsTot": 100, "TR.F.ShrUsedToCalcBasicEPSTot": 100,
        "TR.F.ShrUsedToCalcDilEPSTot": 101,
    })


def workspace_fixture():
    identity = tagged({
        "TR.CommonName": "Fictional regression fixture", "TR.PrimaryRIC": RIC, "TR.ExchangeName": "Nasdaq",
        "TR.ISIN": "US0000000000", "TR.InstrumentType": "Ordinary Shares", "TR.TRBCEconomicSector": "Technology",
        "TR.TRBCIndustryGroup": "Fictional sector", "TR.PriceClose": 30, "TR.PriceClose.date": "2026-02-13",
        "TR.PriceClose.currency": "USD", "TR.IssueMarketCap": 3e9, "TR.CompanyMarketCap": 3e9,
        "TR.IssueMarketCap.date": "2026-02-13", "TR.CompanyMarketCap.date": "2026-02-13",
    })
    capital = tagged({
        "TR.WACC": 10, "TR.WACC.date": "2026-02-13", "TR.WACCCostOfEquity": 11, "TR.WACCCostOfDebt": 6,
        "TR.WACCDebtWeight": 20, "TR.WACCBeta": 1.2,
    })
    def estimates(period, revenue, ebit):
        return tagged({"TR.RevenueMean.periodenddate": period, "TR.EBITMean.periodenddate": period,
                       "TR.RevenueMean": revenue, "TR.EBITMean": ebit})

    annual = [financial_row(f"{year}-12-31", 1000 + (year - 2022) * 100) for year in range(2022, 2026)]
    quarters = [financial_row("2024-12-31", 300)] + [
        financial_row(f"2025-{end}", 325) for end in ("03-31", "06-30", "09-30", "12-31")
    ]
    requests = {
        "identity": [identity], "annual": annual, "quarterly": quarters, "capital": [capital],
        "consensus_fy1": [estimates("2026-12-31", 1400, 280)],
        "consensus_fy2": [estimates("2027-12-31", 1550, 325.5)],
    }
    return {
        "schema": "lseg-workspace-1", "ric": RIC, "sdk_version": "fictional",
        "snapshot_at": "2026-02-14T14:00:00Z", "requests": {
            name: {"rows": rows, "fields": list(REQUESTS[name][0]), "parameters": dict(REQUESTS[name][1])}
            for name, rows in requests.items()
        },
    }


class WorkspaceTests(unittest.TestCase):
    def test_consensus_dilution_and_stub_map_to_the_dcf(self):
        case, plan = materialize_workspace(workspace_fixture())
        explicit, result = evaluate_plan(case, plan)
        self.assertEqual(result["market_price"], 30)
        self.assertEqual(case["facts"]["valuation_shares"]["value"], 101)
        self.assertEqual(case["facts"]["market_price"]["period_end"], "2026-02-13")
        self.assertEqual(case["valuation_date"], "2026-02-14")
        self.assertAlmostEqual(result["capital_cost"]["wacc"], .10)
        self.assertAlmostEqual(explicit["forecasts"][0]["revenue"], 1400 * 320 / 365)
        self.assertAlmostEqual(explicit["forecasts"][1]["revenue"], 1550)
        self.assertAlmostEqual(explicit["forecasts"][1]["net_reinvestment"], 1550 * .0225)

    def test_refuses_unsupported_share_structure_and_sectors(self):
        for key, value, reason in (
            ("TR.ISSUEMARKETCAP", 1e9, "share-class"),
            ("TR.TRBCECONOMICSECTOR", "Financials", "dedicated"),
        ):
            with self.subTest(key=key):
                snapshot = workspace_fixture()
                snapshot["requests"]["identity"]["rows"][0][key] = value
                with self.assertRaisesRegex(ValueError, reason):
                    materialize_workspace(snapshot)

    def test_rejects_cumulative_quarter_cash_flow(self):
        snapshot = workspace_fixture()
        snapshot["requests"]["quarterly"]["rows"][-1]["TR.F.NETCASHFLOWOP"] *= 3
        with self.assertRaisesRegex(ValueError, "Discrete fiscal quarters"):
            materialize_workspace(snapshot)
        snapshot = workspace_fixture()
        snapshot["requests"]["annual"]["parameters"]["Scale"] = 3
        with self.assertRaisesRegex(ValueError, "units differ"):
            materialize_workspace(snapshot)

    def test_missing_data_and_stale_closes_cannot_enter_the_model(self):
        base = workspace_fixture()
        missing = deepcopy(base)
        missing["requests"]["annual"]["rows"][-1]["TR.EBIT"] = None
        with self.assertRaisesRegex(ValueError, "TR.EBIT"):
            materialize_workspace(missing)
        base["snapshot_at"] = "2026-02-23T14:00:00Z"
        with self.assertRaisesRegex(ValueError, "recent completed close"):
            materialize_workspace(base)

    def test_replay_does_not_call_provider(self):
        with TemporaryDirectory() as tmp, patch("equity_workbench.lseg_workspace.fetch_snapshot") as fetch:
            root = Path(tmp)
            snapshot = root / "workspace.json"
            write_json(snapshot, workspace_fixture())
            code = main(["analyze", "--from-snapshot", str(snapshot), "--out", str(root / "run"), "--drafts"])
            self.assertEqual(code, 0)
            fetch.assert_not_called()
            self.assertEqual(load_json(root / "run/valuation/audit.json")["evidence"]["provider"], "LSEG Workspace")
            self.assertTrue((root / "run/valuation/report.html").is_file())
            draft = (root / "run/social/linkedin.md").read_text(encoding="utf-8")
            self.assertIn("Chiusura 2026-02-13 30.00 USD", draft)
