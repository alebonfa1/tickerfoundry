"""Economic invariants and hand-calculated examples, not output snapshots."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from equity_workbench.core import evaluate_case, reverse_terminal_margin, sensitivity_table


def hand_solvable_case():
    path = Path(__file__).resolve().parents[1] / "examples" / "synthetic_company.json"
    case = json.loads(path.read_text(encoding="utf-8"))
    case["assumptions"].update(wacc=0.10, terminal_growth=0.0, terminal_roic=0.10,
                               terminal_operating_margin=0.20, terminal_tax_rate=0.25)
    case["forecasts"] = [{
        "period_start": "2026-01-01", "period_end": "2026-12-31",
        "revenue": 100.0, "operating_margin": 0.20, "tax_rate": 0.25,
        "net_reinvestment": 0.0, "rationale": "Hand-calculated fictional steady-state perpetuity; no growth and no net investment.",
    }]
    values = {"cash": 10.0, "debt": 20.0, "other_claims": 0.0,
              "other_nonoperating_assets": 0.0, "shares_outstanding": 10.0,
              "valuation_shares": 10.0, "market_price": 14.0, "market_cap": 140.0}
    for name, value in values.items():
        case["facts"][name]["value"] = value
    return case


class ValuationTests(unittest.TestCase):
    def test_hand_solvable_perpetuity_and_equity_bridge(self):
        result = evaluate_case(hand_solvable_case())
        # FCFF = 100*.2*.75 = 15; EV = 15/.10 = 150.
        self.assertAlmostEqual(result["forecast_rows"][0]["fcff"], 15.0)
        self.assertAlmostEqual(result["enterprise_value"], 150.0)
        self.assertAlmostEqual(result["equity_value"], 140.0)
        self.assertAlmostEqual(result["value_per_share"], 14.0)
        self.assertAlmostEqual(result["upside_fraction"], 0.0)

    def test_all_inclusive_content_reinvestment_is_counted_once(self):
        case = hand_solvable_case()
        case["forecasts"][0]["net_reinvestment"] = 5.0
        case["forecasts"][0]["rationale"] = "This five includes the content cash/amortization gap and all other net investment exactly once."
        result = evaluate_case(case)
        self.assertAlmostEqual(result["forecast_rows"][0]["fcff"], 10.0)
        self.assertAlmostEqual(result["value_per_share"], 14.0 - 5.0 / 1.1 / 10.0)

    def test_money_and_share_scaling_preserves_per_share_value(self):
        case = hand_solvable_case()
        original = evaluate_case(case)
        for name, fact in case["facts"].items():
            if name != "market_price":
                fact["value"] *= 7
        for row in case["forecasts"]:
            row["revenue"] *= 7
            row["net_reinvestment"] *= 7
        result = evaluate_case(case)
        self.assertAlmostEqual(result["value_per_share"], original["value_per_share"])
        self.assertAlmostEqual(result["enterprise_value"], original["enterprise_value"] * 7)

    def test_debt_changes_equity_without_changing_operating_ev(self):
        case = hand_solvable_case()
        case["facts"]["debt"]["value"] += 10.0
        result = evaluate_case(case)
        self.assertAlmostEqual(result["enterprise_value"], 150.0)
        self.assertAlmostEqual(result["value_per_share"], 13.0)

    def test_terminal_growth_requires_reinvestment(self):
        case = hand_solvable_case()
        case["assumptions"].update(terminal_growth=0.03, terminal_roic=0.15)
        result = evaluate_case(case)
        terminal_nopat = 100.0 * 1.03 * 0.2 * 0.75
        terminal_fcff = terminal_nopat * (1.0 - 0.03 / 0.15)
        expected_ev = (15.0 + terminal_fcff / (0.10 - 0.03)) / 1.1
        self.assertAlmostEqual(result["terminal"]["reinvestment_rate"], 0.20)
        self.assertAlmostEqual(result["enterprise_value"], expected_ev)

    def test_reverse_margin_recovers_known_answer(self):
        result = reverse_terminal_margin(hand_solvable_case(), target_price=14.0)
        self.assertEqual(result["status"], "solved")
        self.assertAlmostEqual(result["terminal_operating_margin"], 0.2)
        self.assertAlmostEqual(result["price_residual"], 0.0)

    def test_reverse_margin_reports_no_solution_instead_of_clamping(self):
        for target in (0.1, 1000.0):
            with self.subTest(target=target):
                result = reverse_terminal_margin(hand_solvable_case(), target_price=target)
                self.assertEqual(result["status"], "no_solution")
                self.assertIsNone(result["terminal_operating_margin"])

    def test_invalid_reverse_request_is_rejected(self):
        for value in (float("nan"), float("inf"), True, 0.0, -1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reverse_terminal_margin(hand_solvable_case(), target_price=value)

    def test_sensitivity_recomputes_and_marks_invalid_growth(self):
        case = hand_solvable_case()
        cells = sensitivity_table(case)
        center = next(c for c in cells if c["wacc"] == 0.10 and c["terminal_growth"] == 0.0)
        self.assertAlmostEqual(center["value_per_share"], 14.0)
        self.assertTrue(any(c["status"] == "invalid_assumptions" for c in cells))
        lower = next(c for c in cells if abs(c["wacc"] - 0.09) < 1e-9 and c["terminal_growth"] == 0.0)
        higher = next(c for c in cells if abs(c["wacc"] - 0.11) < 1e-9 and c["terminal_growth"] == 0.0)
        self.assertGreater(lower["value_per_share"], center["value_per_share"])
        self.assertLess(higher["value_per_share"], center["value_per_share"])

    def test_input_not_mutated(self):
        case = hand_solvable_case()
        snapshot = deepcopy(case)
        evaluate_case(case)
        self.assertEqual(case, snapshot)

    def test_synthetic_arithmetic_cannot_be_publication_ready(self):
        result = evaluate_case(hand_solvable_case())
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["status"], "research_draft")

    def test_basic_market_cap_is_separate_from_diluted_equity(self):
        case = hand_solvable_case()
        case["facts"]["valuation_shares"]["value"] = 12.0
        result = evaluate_case(case)
        self.assertAlmostEqual(result["derived_market_cap"], 140.0)
        self.assertAlmostEqual(result["price_implied_diluted_equity_value"], 168.0)
        self.assertAlmostEqual(result["value_per_share"], 140.0 / 12.0)

    def test_bad_case_never_generates_a_valuation(self):
        case = hand_solvable_case()
        case["facts"]["debt"]["value"] = None
        with self.assertRaises(ValueError):
            evaluate_case(case)


if __name__ == "__main__":
    unittest.main()
