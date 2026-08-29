import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("outcome.py")
SPEC = importlib.util.spec_from_file_location("outcome", MODULE_PATH)
outcome = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(outcome)


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.value).encode()


class FakeOpener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return FakeResponse(next(self.responses))


def make_receipt(result="partial", accepted=1, rejected=1, earned="0.50"):
    digest = "a" * 64
    body = {
        "schema": "spoolis/outcome-receipt@1",
        "environment": "demo",
        "agreement": {"spool_id": "spl_test", "agreement_version": 1, "agreement_hash": digest},
        "verification": {"plan_version": "1", "plan_hash": digest, "compiler_version": "1", "evidence_policy_version": "1", "run_id": "vr_1", "run_digest": digest, "aggregation_policy": {"policy_id": "all_mandatory_pass", "policy_version": "1"}},
        "evidence_root": digest,
        "condition_results": [
            {"condition_id": "cond_rows", "requirement": "mandatory", "result": result, "method": "deterministic", "verifier_id": "rows", "verifier_version": "1", "evidence_refs": ["ev_1"], "reason": "one row is missing id"}
        ],
        "result": result,
        "units": {"total": accepted + rejected, "accepted": accepted, "rejected": rejected, "earning_rule": {"type": "per_unit", "unit_amount": "0.50"}, "rejection_summary": [{"reason": "missing id", "count": rejected}], "unit_results_digest": digest},
        "amounts": {"earned": earned, "committed": "1.00", "asset": "USD", "decimals": 2},
        "actors": {"payer": {"subject": "spoolis:payer", "kind": "agent"}, "provider": {"subject": "spoolis:provider", "kind": "agent"}},
        "issued_at": "2026-08-29T12:00:00.000Z",
        "nonce": "n_test",
        "algorithm": "Ed25519",
    }
    body["id"] = "ocr_" + outcome.sha256(body)[:24]
    body["signing_key_id"] = "b" * 64
    body["signature"] = "signed"
    return body


class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "conditions": [{"description": "Every row includes id", "deterministic_check": {"checker": "completeness", "required_fields": ["id"]}}],
            "max_amount_cents": 100,
            "unit": {"total_units": 2, "unit_amount_cents": 50},
            "evidence": {"type": "dataset", "rows": [{"id": 1}, {}], "provenance": "uploaded_json"},
        }

    def test_constructs_exact_verify_payload(self):
        self.assertEqual(outcome.verify_payload(self.source), {**self.source, "settlement": "external"})
        with self.assertRaisesRegex(outcome.OutcomeError, "external only"):
            outcome.verify_payload({**self.source, "settlement": "managed"})

    def test_verify_mints_then_verifies_with_bearer_token(self):
        receipt = make_receipt()
        opener = FakeOpener([
            {"token": "sandbox-token", "expires_at": "later", "limits": {}},
            {"spool_id": "spl_verified", "accepted": 1, "rejected": 1, "earned_cents": 50, "receipt": receipt, "receipt_url": "https://spoolis.com/r/" + receipt["id"], "rejections": [{"unit": 2, "reason": "missing id"}]},
        ])
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.json"
            input_path.write_text(json.dumps(self.source))
            result = outcome.run_verify(input_path, opener=opener)
        self.assertEqual([request.full_url for request in opener.requests], [
            "https://spoolis.com/api/sandbox/session",
            "https://spoolis.com/api/sandbox/verify",
        ])
        self.assertNotIn("Authorization", opener.requests[0].headers)
        self.assertEqual(opener.requests[1].headers["Authorization"], "Bearer sandbox-token")
        self.assertEqual(json.loads(opener.requests[1].data), {**self.source, "settlement": "external"})
        self.assertEqual(result["receipt"], receipt)

    def test_digest_check_detects_tampering(self):
        receipt = make_receipt()
        errors, digest = outcome.check_receipt(receipt)
        self.assertEqual(errors, [])
        self.assertEqual(len(digest), 64)
        receipt["amounts"]["earned"] = "0.75"
        errors, _ = outcome.check_receipt(receipt)
        self.assertIn("Receipt ID does not match the canonical receipt content digest.", errors)
        self.assertIn("Earned value does not match accepted units times unit amount.", errors)

    def test_partial_acceptance_rendering_preserves_detail(self):
        receipt = make_receipt()
        rendered = outcome.render_outcome({
            "accepted": 1,
            "rejected": 1,
            "receipt": receipt,
            "receipt_url": "https://spoolis.com/r/" + receipt["id"],
            "rejections": [{"unit": 2, "reason": "missing id"}],
        })
        self.assertIn("Outcome: partial", rendered)
        self.assertIn("cond_rows: partial (one row is missing id)", rendered)
        self.assertIn("Accepted units: 1", rendered)
        self.assertIn("Rejected units: 1", rendered)
        self.assertIn("Rejected unit 2: missing id", rendered)
        self.assertIn("Earned value: 0.50 USD", rendered)
        self.assertIn("Signature: signed", rendered)
        self.assertIn('"schema": "spoolis/outcome-receipt@1"', rendered)


if __name__ == "__main__":
    unittest.main()
