import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest

from equity_workbench.cli import main, input_template, load_json
from equity_workbench.reporting import write_report, source_link
from equity_workbench.validation import validate_case


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_company.json"


class CliTests(unittest.TestCase):
    def test_demo_outputs_reconcile_and_remain_fictional(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            folder = Path(temp) / "demo"
            self.assertEqual(main(["demo", "--out", str(folder)]), 0)
            calc = load_json(folder / "calculations.json")
            audit = load_json(folder / "audit.json")
            page = (folder / "report.html").read_text()
            self.assertIn(f'{calc["value_per_share"]:,.2f}', page)
            self.assertIn(f'{calc["market_price"]:,.2f}', page)
            self.assertIn("FICTIONAL TEST DATA", page)
            self.assertFalse(audit["publication_ready"])
            self.assertEqual(audit["checks"], calc["checks"])
            self.assertEqual(len(audit["code_sha256"]), 64)
            self.assertTrue((folder / "forecast.csv").exists())

    def test_missing_inputs_produce_blocked_report_without_price(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            root = Path(temp)
            case = input_template("Netflix", "2026-11-10")
            path = root / "case.json"
            path.write_text(json.dumps(case))
            self.assertEqual(main(["run", "--input", str(path), "--out", str(root / "out")]), 2)
            self.assertFalse((root / "out" / "calculations.json").exists())
            self.assertIn("BLOCKED", (root / "out" / "report.html").read_text())

    def test_input_template_has_no_fictional_company_financials(self):
        case = input_template("A real company", "2026-11-10")
        self.assertFalse(case["synthetic"])
        self.assertTrue(all(fact["value"] is None for fact in case["facts"].values()))
        self.assertEqual(case["forecasts"][0]["period_start"], "2026-11-11")
        self.assertTrue(any(i["severity"] == "error" for i in validate_case(case)))

    def test_previous_run_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            folder = Path(temp) / "demo"
            self.assertEqual(main(["demo", "--out", str(folder)]), 0)
            before = (folder / "audit.json").read_bytes()
            self.assertEqual(main(["demo", "--out", str(folder)]), 2)
            self.assertEqual(before, (folder / "audit.json").read_bytes())

    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.json"
            for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    load_json(path)

    def test_blocked_report_handles_malformed_shapes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "blocked.html"
            write_report(path, {"company": "x", "assumptions": None, "sources": None}, None, {"checks": []})
            self.assertIn("BLOCKED", path.read_text())
            self.assertEqual(source_link({"title": "Unsafe", "url": "https://[bad"}), "Unsafe")

    def test_report_escapes_untrusted_titles_and_blocks_script_links(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.html"
            case = copy.deepcopy(load_json(FIXTURE))
            case["company"]["name"] = '<script>alert("x")</script>'
            case["sources"][0]["url"] = "javascript:alert(1)"
            write_report(path, case, None, {"checks": []})
            page = path.read_text()
            self.assertNotIn('<script>alert', page)
            self.assertNotIn('href="javascript:', page)
            self.assertIn('&lt;script&gt;', page)


if __name__ == "__main__":
    unittest.main()
