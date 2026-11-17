from copy import deepcopy
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from equity_workbench.cli import load_json, run_case, write_json
from equity_workbench.editorial import write_drafts
from equity_workbench.evidence import Filing, frozen_bytes, nasdaq_closes, price_return_beta
from equity_workbench.model import evaluate_plan
from equity_workbench.validation import validate_case
from test_core import hand_solvable_case


def plan_fixture():
    annual = {
        "period_end": "2026-12-31", "revenue_growth": .1, "operating_margin": .2, "tax_rate": .25,
        "capex_rate": .04, "depreciation_rate": .02, "net_other_investment_rate": .01,
        "working_capital_investment_rate": 0, "rationale": "Synthetic annual investment bridge.",
    }
    terminal = {
        "growth": 0, "roic": .1, "operating_margin": .2, "tax_rate": .25,
        "rationale": "Synthetic steady state.",
    }
    scenario = {"rationale": "Synthetic state.", "annual": [annual], "terminal": terminal}
    plan = {
        "version": "1", "starting_annual_revenue": 100,
        "capital_cost": {
            "risk_free_rate": .04, "equity_risk_premium": .06, "beta": 1, "tax_rate": .25,
            "pre_tax_cost_of_debt": .05, "rationale": "Synthetic cost of capital.",
        },
        "scenarios": {name: deepcopy(scenario) for name in ("downside", "base", "upside")},
        "editorial": dict.fromkeys(("business", "evidence", "assumptions", "risk", "falsifier"), "Test copy."),
    }
    return plan


def timestamped_case():
    case = hand_solvable_case()
    case["synthetic"] = False
    case["company"]["exchange"] = "TEST"
    cutoff = "2025-12-31T16:00:00-05:00"
    case["valuation_at"] = cutoff
    case["facts"]["market_price"]["observed_at"] = cutoff
    case["sources"][0]["url"] = "https://example.test/fictional"
    return case


class PlanTests(unittest.TestCase):
    def test_driver_bridge_against_hand_calculations(self):
        case, result = evaluate_plan(hand_solvable_case(), plan_fixture())
        wacc = (140 * .1 + 20 * .05 * .75) / 160
        ev = (13.2 + 16.5 / wacc) / (1 + wacc)
        self.assertAlmostEqual(result["capital_cost"]["wacc"], wacc)
        self.assertAlmostEqual(case["forecasts"][0]["net_reinvestment"], 3.3)
        self.assertAlmostEqual(result["value_per_share"], (ev - 10) / 10)
        self.assertAlmostEqual(result["scenarios"]["base"]["terminal"]["fcff"], 16.5)

    def test_terminal_margin_must_fade(self):
        plan = plan_fixture()
        plan["scenarios"]["upside"]["terminal"]["operating_margin"] = .5
        with self.assertRaisesRegex(ValueError, "terminal margin"):
            evaluate_plan(hand_solvable_case(), plan)

    def test_alternate_beta_changes_only_the_discount_rate(self):
        plan = plan_fixture()
        plan["capital_cost"]["alternate_beta"] = .7
        _, result = evaluate_plan(hand_solvable_case(), plan)
        alternate = result["beta_cross_check"]
        self.assertAlmostEqual(alternate["wacc"], (140 * .082 + 20 * .05 * .75) / 160)
        self.assertGreater(alternate["value_per_share"], result["value_per_share"])

    def test_cutoff_blocks_same_day_after_hours_filings(self):
        case = timestamped_case()
        self.assertFalse([i for i in validate_case(case) if i["severity"] == "error"])
        case["sources"][0]["published_at"] = "2025-12-31T21:01:00Z"
        self.assertIn("lookahead_source", {i["code"] for i in validate_case(case)})
        case["facts"]["market_price"]["observed_at"] = "2025-12-31T21:01:00Z"
        self.assertIn("market_close_mismatch", {i["code"] for i in validate_case(case)})
        case["sources"][0]["url"] = "https://name:credential@example.test/private"
        self.assertIn("source_url", {i["code"] for i in validate_case(case)})

    def test_drafts_replay_and_refuse_changed_calculations(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            case, plan = root / "case.json", root / "plan.json"
            write_json(case, timestamped_case())
            write_json(plan, plan_fixture())
            self.assertEqual(run_case(case, root / "run", plan_path=plan), 0)
            write_drafts(root / "run", root / "draft")
            calculation = root / "run/calculations.json"
            result = load_json(calculation)
            self.assertIn(f'{result["value_per_share"]:.2f}', (root / "draft/linkedin.md").read_text(encoding="utf-8"))
            result["value_per_share"] += 1
            write_json(calculation, result)
            with self.assertRaisesRegex(ValueError, "does not match"):
                write_drafts(root / "run", root / "changed")
            self.assertFalse((root / "changed").exists())


def filing_fixture(extra=""):
    return f"""
<html xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:context id="reported">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000123</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <ix:nonFraction id="f-1" name="test:Cash" contextRef="reported" unitRef="usd" scale="3" decimals="-3">123</ix:nonFraction>
  {extra}
</html>
""".encode()


class EvidenceTests(unittest.TestCase):
    def test_selects_precision_and_rejects_conflicting_observations(self):
        tag = '<ix:nonFraction id="f-2" name="test:Cash" contextRef="reported" unitRef="usd" scale="3" decimals="-4">{}</ix:nonFraction>'
        good = Filing(filing_fixture(tag.format("120")), cik="0000000123")
        self.assertEqual(good.fact("test:Cash", end="2025-12-31")["raw_value"], "1.23E+5")
        bad = Filing(filing_fixture(tag.format("100")), cik="0000000123")
        with self.assertRaisesRegex(ValueError, "Conflicting values"):
            bad.fact("test:Cash", end="2025-12-31")
        with self.assertRaisesRegex(ValueError, "specified SEC CIK"):
            Filing(filing_fixture(), cik="0000000321")

    def test_market_history_requires_complete_and_matching_sessions(self):
        days = [date(2025, 12, i) for i in (8, 9, 10)]
        stock = dict(zip(days, [100, 120, 120]))
        benchmark = dict(zip(days, [100, 110, 110]))
        self.assertAlmostEqual(price_return_beta(stock, benchmark, minimum=2)["beta"], 2)
        benchmark.pop(days[0])
        with self.assertRaisesRegex(ValueError, "matched sessions"):
            price_return_beta(stock, benchmark, minimum=2)
        snapshot = {
            "status": {"rCode": 200}, "data": {
                "symbol": "TEST", "totalRecords": 2,
                "tradesTable": {"rows": [{"date": "12/10/2025", "close": "$12.50"}]},
            },
        }
        with self.assertRaisesRegex(ValueError, "truncated"):
            nasdaq_closes(snapshot, "TEST", days[-1])

    def test_snapshot_hash_blocks_changed_evidence(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload"
            path.write_bytes(b"data")
            with self.assertRaisesRegex(ValueError, "Snapshot hash differs"):
                frozen_bytes(path, "old-hash")
