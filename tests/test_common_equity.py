from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from equity_workbench import INVESTMENT_DISCLAIMER
from equity_workbench.cli import input_template, load_json, run_case, write_json
from equity_workbench.common_equity import evaluate_common_equity
from equity_workbench.validation import validate_case


def sample_case():
    case = input_template("Fictional issuer", "2025-12-31", "common-equity")
    case["synthetic"] = True
    case["company"].update(ticker="EXAMPLE", exchange="Fictional exchange", currency="USD")
    case["sources"] = [{"id": "F", "title": "Fictional test data", "url": "synthetic://fixture/common-equity",
                        "published_at": "2025-12-31", "retrieved_at": "2025-12-31",
                        "redistribution": "permitted", "cloud_processing": "permitted"}]
    for name, value in (("market_price", 12), ("shares_outstanding", 100), ("valuation_shares", 100)):
        case["facts"][name] = {"value": value, "source_id": "F", "period_end": "2025-12-31", "basis": "Fictional."}
    for path, flow in zip(case["scenarios"].values(), (80, 100, 120), strict=True):
        path.update(cost_of_equity=.10, terminal_growth=0, terminal_annual_cash_flow=flow,
                    source_ids=["F"], rationale="Sustained hypothetical cash flow after all claims.")
        path["forecasts"] = [{"period_start": "2026-01-01", "period_end": "2026-12-31",
                              "net_cash_to_common": flow, "source_ids": ["F"], "rationale": "Fictional cash flow."}]
    return case


class CommonEquityTests(TestCase):
    def test_same_claim_valuation_without_sector_and_matching_terminal_diagnostic(self):
        case = sample_case()
        result = evaluate_common_equity(case)
        self.assertNotIn("sector_model", case["company"])
        self.assertAlmostEqual(result["value_per_share"], 10)
        self.assertAlmostEqual(result["scenarios"]["downside"]["value_per_share"], 8)
        self.assertAlmostEqual(result["scenarios"]["upside"]["value_per_share"], 12)
        base = result["scenarios"]["base"]
        calculated_price = (100 + base["implied_terminal_annual_cash_flow"] / .10) / 1.10 / 100
        self.assertAlmostEqual(calculated_price, 12)

    def test_rejects_missing_data_provenance_and_future_or_discontinuous_inputs(self):
        case = sample_case()
        case["sources"][0]["published_at"] = "2026-01-01"
        case["scenarios"]["base"]["forecasts"][0].update(source_ids=["foreign"], period_start="2026-01-02")
        case["scenarios"]["downside"]["terminal_growth"] = .10
        codes = {record["code"] for record in validate_case(case) if record["severity"] == "error"}
        self.assertTrue({"lookahead_source", "equity_source_ids", "equity_calendar", "equity_terminal_spread"} <= codes)

    def test_files_and_disclaimer_for_valid_and_blocked_cases(self):
        with TemporaryDirectory() as root:
            root = Path(root)
            case = sample_case()
            source = root / "input.json"
            write_json(source, case)
            self.assertEqual(run_case(source, root / "review"), 0)
            result = load_json(root / "review/calculations.json")
            self.assertAlmostEqual(result["value_per_share"], 10)
            self.assertTrue((root / "review/forecast.csv").is_file())
            blocked = deepcopy(case)
            blocked["scenarios"]["base"]["terminal_annual_cash_flow"] = None
            write_json(source, blocked)
            self.assertEqual(run_case(source, root / "blocked"), 2)
            for folder in ("review", "blocked"):
                self.assertIn(INVESTMENT_DISCLAIMER, (root / folder / "report.html").read_text(encoding="utf-8"))
                self.assertEqual(load_json(root / folder / "audit.json")["disclaimer"], INVESTMENT_DISCLAIMER)
            self.assertFalse((root / "blocked/calculations.json").exists())
