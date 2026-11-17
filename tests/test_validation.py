"""Tests for omissions, date leakage, accounting scope and malformed input."""

import json
from pathlib import Path
import unittest

from equity_workbench.validation import validate_case


def fixture():
    path = Path(__file__).resolve().parents[1] / "examples" / "synthetic_company.json"
    return json.loads(path.read_text(encoding="utf-8"))


def error_codes(case):
    return {i["code"] for i in validate_case(case) if i["severity"] == "error"}


class ValidationTests(unittest.TestCase):
    def test_complete_fixture_has_no_hard_errors(self):
        self.assertEqual(error_codes(fixture()), set())

    def test_missing_and_null_are_not_zero(self):
        case = fixture()
        del case["facts"]["other_claims"]
        self.assertIn("missing_fact", error_codes(case))
        case = fixture()
        case["facts"]["other_claims"]["value"] = None
        self.assertIn("fact_value", error_codes(case))

    def test_nonfinite_boolean_and_enormous_numbers_are_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"), True, "100", 10 ** 1000):
            with self.subTest(value_type=type(value).__name__):
                case = fixture()
                case["facts"]["cash"]["value"] = value
                self.assertIn("fact_value", error_codes(case))

    def test_nonpositive_share_count_is_rejected(self):
        for value in (0, -5):
            case = fixture()
            case["facts"]["valuation_shares"]["value"] = value
            self.assertIn("fact_range", error_codes(case))

    def test_wacc_not_above_growth_blocks_perpetuity(self):
        case = fixture()
        case["assumptions"]["wacc"] = case["assumptions"]["terminal_growth"]
        self.assertIn("terminal_spread", error_codes(case))

    def test_terminal_growth_cannot_be_financed_for_free(self):
        case = fixture()
        case["assumptions"]["terminal_roic"] = case["assumptions"]["terminal_growth"]
        self.assertIn("terminal_reinvestment", error_codes(case))

    def test_source_published_after_valuation_is_rejected(self):
        case = fixture()
        case["sources"][0]["published_at"] = "2026-01-01T00:00:00Z"
        self.assertIn("lookahead_source", error_codes(case))

    def test_old_source_cannot_support_a_later_fact(self):
        case = fixture()
        case["sources"][0]["published_at"] = "2024-12-31"
        self.assertIn("fact_after_source_publication", error_codes(case))

    def test_retrieval_before_publication_is_rejected(self):
        case = fixture()
        case["sources"][0]["retrieved_at"] = "2025-12-30T23:00:00Z"
        self.assertIn("retrieval_before_publication", error_codes(case))

    def test_unknown_or_duplicate_source_is_rejected(self):
        case = fixture()
        case["facts"]["cash"]["source_id"] = "MISSING"
        self.assertIn("unknown_source", error_codes(case))
        case = fixture()
        case["sources"].append(dict(case["sources"][0]))
        self.assertIn("duplicate_source_id", error_codes(case))

    def test_elapsed_cashflows_and_period_gaps_are_rejected(self):
        case = fixture()
        case["forecasts"][0]["period_start"] = "2025-12-31"
        self.assertIn("elapsed_forecast", error_codes(case))
        case = fixture()
        case["forecasts"][1]["period_start"] = "2027-01-02"
        self.assertIn("forecast_gap_or_overlap", error_codes(case))

    def test_terminal_requires_annual_final_period(self):
        case = fixture()
        case["forecasts"][-1]["period_end"] = "2028-06-30"
        self.assertIn("terminal_annualization", error_codes(case))

    def test_source_permissions_wrong_type_do_not_crash(self):
        for field in ("redistribution", "cloud_processing"):
            case = fixture()
            case["sources"][0][field] = []
            self.assertIn("source_rights", error_codes(case))

    def test_invalid_ipv6_url_does_not_crash(self):
        case = fixture()
        case["sources"][0]["url"] = "https://[bad"
        self.assertIn("source_url", error_codes(case))

    def test_non_objects_are_rejected_without_exceptions(self):
        for case in (None, [], "company", 7):
            self.assertEqual(error_codes(case), {"case_type"})
        case = fixture()
        case["facts"] = []
        self.assertIn("facts", error_codes(case))
        case = fixture()
        case["sources"] = [None]
        self.assertIn("source_type", error_codes(case))

    def test_unsupported_sectors_are_explicit(self):
        for route in ("bank", "insurance", "reit", "crypto"):
            case = fixture()
            case["company"]["sector_model"] = route
            self.assertIn("unsupported_sector", error_codes(case))

    def test_loss_forecasts_require_a_tax_loss_extension(self):
        case = fixture()
        case["forecasts"][0]["operating_margin"] = -0.2
        self.assertIn("forecast_range", error_codes(case))

    def test_market_cap_must_reconcile_to_basic_shares(self):
        case = fixture()
        case["facts"]["market_cap"]["value"] *= 10
        self.assertIn("market_cap_mismatch", error_codes(case))

    def test_assumptions_and_net_investment_require_rationale(self):
        case = fixture()
        case["assumptions"]["rationale"] = "  "
        case["forecasts"][0]["rationale"] = ""
        self.assertIn("assumption_rationale", error_codes(case))
        self.assertIn("forecast_rationale", error_codes(case))


if __name__ == "__main__":
    unittest.main()
