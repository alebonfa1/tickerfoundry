"""Offline contract tests; these do not prove live API/model behavior."""
import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from equity_workbench.astra import (
    AstraError, DataPermissionError, ModelOutputError,
    run_agent_review, run_research,
)
from equity_workbench.core import evaluate_case


class FakeClient:
    def __init__(self, outputs, *, failure=None, status="completed", observed=None):
        self.outputs = copy.deepcopy(outputs)
        self.failure = failure
        self.status = status
        self.calls = []
        self.observed = observed or []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return SimpleNamespace(
            status=self.status,
            output_text=json.dumps(self.outputs.pop(0)),
            output=[{"type": "web_search_call", "action": {"sources": [
                {"url": url} for url in self.observed]}}],
        )


def review(role):
    return {
        "role": role, "summary": "Evidence remains incomplete.",
        "findings": [{"severity": "material", "title": "Verify share definition",
                      "explanation": "The economic share denominator needs review.",
                      "source_ids": ["s1"],
                      "input_paths": ["/case/facts/valuation_shares/value"],
                      "required_action": "Reconcile to the issuer filing."}],
        "missing_evidence": [], "limitations": ["No source document was fetched."],
    }


def dossier():
    return {
        "requested_company": "Fictional Example", "as_of": "2026-11-10",
        "issuer_status": "resolved",
        "candidates": [{"name": "Fictional Example", "ticker": "EXAMPLE",
                        "exchange": "FICTIONAL", "country": "US", "source_ids": ["s1"]}],
        "sources": [{"id": "s1", "title": "Fictional annual report",
                     "url": "https://example.org/report", "published_at": "2026-02-01",
                     "source_type": "company_filing"}],
        "claims": [{"id": "c1", "topic": "business", "text": "Synthetic test claim.",
                    "source_ids": ["s1"], "status": "reported"}],
        "sections": [{"heading": "Business", "summary": "Synthetic test summary.", "claim_ids": ["c1"]}],
        "missing_inputs": [{"name": "market_price", "reason": "Not collected."}],
        "limitations": ["Synthetic test response."],
    }


class AstraTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).resolve().parents[1] / "examples" / "synthetic_company.json"
        self.case = json.loads(fixture.read_text())
        self.case["sources"][0]["id"] = "s1"
        for fact in self.case["facts"].values():
            fact["source_id"] = "s1"
        self.result = evaluate_case(self.case)

    def test_unattached_private_fields_never_transmitted(self):
        for location in ("top", "company", "fact", "source", "forecast", "assumption", "result"):
            with self.subTest(location=location):
                case, result = copy.deepcopy((self.case, self.result))
                destination = {
                    "top": case, "company": case["company"],
                    "fact": case["facts"]["cash"], "source": case["sources"][0],
                    "forecast": case["forecasts"][0], "assumption": case["assumptions"],
                    "result": result,
                }[location]
                destination["unattached_private_document"] = "PRIVATE MATERIAL WITHOUT PERMISSION"
                client = FakeClient([])
                with self.assertRaises(AstraError):
                    run_agent_review(case, result, client=client)
                self.assertEqual(client.calls, [])

    def test_modified_calculation_or_wrong_case_never_transmitted(self):
        result = copy.deepcopy(self.result)
        result["value_per_share"] += 10
        client = FakeClient([])
        with self.assertRaises(AstraError):
            run_agent_review(self.case, result, client=client)
        self.assertEqual(client.calls, [])

    def test_permission_denied_before_any_api_call(self):
        for permission in (None, "unknown", "restricted"):
            with self.subTest(permission=permission):
                case = copy.deepcopy(self.case)
                case["sources"][0]["cloud_processing"] = permission
                client = FakeClient([])
                with self.assertRaises(DataPermissionError):
                    run_agent_review(case, self.result, client=client)
                self.assertEqual(client.calls, [])

    def test_empty_source_ledger_is_not_permission(self):
        client = FakeClient([])
        with self.assertRaises(DataPermissionError):
            run_agent_review({"sources": []}, {}, client=client)
        self.assertEqual(client.calls, [])

    def test_review_roles_isolated_then_critic_and_inputs_immutable(self):
        client = FakeClient([review(role) for role in ("accounting", "business_risk", "critical_reviewer")])
        snapshot = copy.deepcopy((self.case, self.result))
        output = run_agent_review(self.case, self.result, client=client)
        self.assertEqual((self.case, self.result), snapshot)
        self.assertEqual(len(client.calls), 3)
        self.assertFalse(output["publishable"])
        for request in client.calls:
            self.assertEqual(request["model"], "gpt-6-astra")
            self.assertFalse(request["store"])
            self.assertNotIn("tools", request)
            self.assertTrue(request["text"]["format"]["strict"])
        first = json.loads(client.calls[0]["input"][1]["content"])
        second = json.loads(client.calls[1]["input"][1]["content"])
        third = json.loads(client.calls[2]["input"][1]["content"])
        self.assertNotIn("previous_reviews", first)
        self.assertNotIn("previous_reviews", second)
        self.assertEqual(len(third["previous_reviews"]), 2)

    def test_unknown_citation_blocks_further_reviews(self):
        item = review("accounting")
        item["findings"][0]["source_ids"] = ["invented-source"]
        client = FakeClient([item])
        with self.assertRaises(ModelOutputError):
            run_agent_review(self.case, self.result, client=client)
        self.assertEqual(len(client.calls), 1)

    def test_invented_input_pointer_rejected(self):
        item = review("accounting")
        item["findings"][0]["input_paths"] = ["/calculation/invented"]
        with self.assertRaises(ModelOutputError):
            run_agent_review(self.case, self.result, client=FakeClient([item]))

    def test_provider_errors_do_not_echo_credentials_or_payload(self):
        client = FakeClient([], failure=ValueError("secret-api-key PRIVATE PAYLOAD"))
        with self.assertRaises(AstraError) as error:
            run_agent_review(self.case, self.result, client=client)
        self.assertNotIn("secret-api-key", str(error.exception))
        self.assertNotIn("PRIVATE PAYLOAD", str(error.exception))

    def test_incomplete_response_not_accepted(self):
        client = FakeClient([review("accounting")], status="incomplete")
        with self.assertRaises(ModelOutputError):
            run_agent_review(self.case, self.result, client=client)
        self.assertEqual(len(client.calls), 1)

    def test_research_bounded_and_source_links_present(self):
        client = FakeClient([dossier()], observed=["https://example.org/report"])
        output = run_research("Fictional Example", "2026-11-10", client=client,
                              allowed_domains=["example.org"])
        self.assertFalse(output["publishable"])
        self.assertEqual(output["web_evidence_url_count"], 1)
        request = client.calls[0]
        self.assertEqual(request["max_tool_calls"], 6)
        self.assertEqual(request["tool_choice"], "required")
        self.assertEqual(request["tools"][0]["filters"]["allowed_domains"], ["example.org"])

    def test_research_post_cutoff_source_rejected(self):
        data = dossier()
        data["sources"][0]["published_at"] = "2026-11-11"
        with self.assertRaises(ModelOutputError):
            run_research("Fictional Example", "2026-11-10", client=FakeClient([data]))

    def test_research_unknown_source_or_claim_rejected(self):
        for part in ("source", "claim"):
            with self.subTest(part=part):
                data = dossier()
                if part == "source":
                    data["claims"][0]["source_ids"] = ["fabricated"]
                else:
                    data["sections"][0]["claim_ids"] = ["fabricated"]
                with self.assertRaises(ModelOutputError):
                    run_research("Fictional Example", "2026-11-10", client=FakeClient([data]))

    def test_unmatched_web_source_is_explicit_limitation(self):
        output = run_research("Fictional Example", "2026-11-10", client=FakeClient([dossier()]))
        self.assertTrue(any("not matched" in warning for warning in output["warnings"]))

    def test_ambiguous_name_cannot_blend_company_analysis(self):
        data = dossier()
        data["issuer_status"] = "ambiguous"
        data["candidates"].append(dict(data["candidates"][0], ticker="SECOND"))
        with self.assertRaises(ModelOutputError):
            run_research("Fictional Example", "2026-11-10", client=FakeClient([data]))
        data["claims"] = []
        data["sections"] = []
        output = run_research("Fictional Example", "2026-11-10", client=FakeClient([data]))
        self.assertEqual(output["dossier"]["issuer_status"], "ambiguous")

    def test_url_with_credentials_or_private_host_rejected(self):
        for url in ("https://user:password@example.org/report", "https://127.0.0.1/report", "http://example.org/report"):
            with self.subTest(url=url):
                data = dossier()
                data["sources"][0]["url"] = url
                with self.assertRaises(ModelOutputError):
                    run_research("Fictional Example", "2026-11-10", client=FakeClient([data]))

    def test_missing_structured_field_is_not_silently_defaulted(self):
        data = dossier()
        del data["missing_inputs"]
        with self.assertRaises(ModelOutputError):
            run_research("Fictional Example", "2026-11-10", client=FakeClient([data]))

    def test_unbounded_request_rejected_before_network(self):
        client = FakeClient([])
        with self.assertRaises(AstraError):
            run_research("Fictional Example", "2026-11-10", client=client, max_output_tokens=1000000)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
