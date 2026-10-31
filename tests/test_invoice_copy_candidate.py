"""No-network regression for the unapproved invoice-copy migration candidate.

The current approved invoice template MUST keep working until Meta separately
approves the new version and the frozen payment rail has an authorized rollout.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/check_invoice_copy_candidate.py"
SPEC = importlib.util.spec_from_file_location("check_invoice_copy_candidate", SOURCE)
assert SPEC and SPEC.loader
candidate_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate_gate)


def valid_template() -> dict:
    return {
        "id": "121234567890123",
        "name": "wecare_invoice_receipt_v2",
        "language": "en",
        "status": "APPROVED",
        "category": "UTILITY",
        "components": [
            {"type": "HEADER", "format": "IMAGE"},
            {"type": "BODY", "text": candidate_gate.CANDIDATE_BODY},
            {"type": "FOOTER", "text": "WECARE.DIGITAL"},
            {"type": "BUTTONS", "buttons": [
                {"type": "FLOW", "text": "Leave Review",
                 "flow_id": 993862443003108, "flow_action": "DATA_EXCHANGE"}
            ]},
        ],
    }


class CandidateGateTests(unittest.TestCase):
    def check(self, template: dict, *, pinned_id: str = "121234567890123") -> list[str]:
        return candidate_gate.validate(template, expected_id=pinned_id)

    def test_exact_approved_receipt_is_eligible_only_for_review(self) -> None:
        self.assertEqual(self.check(valid_template()), [])
        self.assertIn("requires_payment_owner_and_handset_approval", SOURCE.read_text())

    def test_current_duplicate_payment_received_body_fails(self) -> None:
        t = valid_template()
        t["components"][1]["text"] = "✅ Payment received. Your transaction has been confirmed."
        self.assertTrue(any("body differs" in e for e in self.check(t)))

    def test_meta_approval_is_required(self) -> None:
        t = valid_template()
        t["status"] = "PENDING"
        self.assertTrue(any("APPROVED" in e for e in self.check(t)))

    def test_pinned_id_and_utility_category_are_required(self) -> None:
        t = valid_template()
        t["category"] = "MARKETING"
        result = self.check(t, pinned_id="1782246473079550")
        self.assertTrue(any("template ID" in e for e in result))
        self.assertTrue(any("UTILITY" in e for e in result))
        self.assertTrue(any("numeric ID" in e for e in self.check(t, pinned_id="not-pinned")))

    def test_invoice_media_and_footer_cannot_be_removed(self) -> None:
        t = valid_template()
        t["components"][0]["format"] = "TEXT"
        t["components"][2]["text"] = "Unreviewed Sender"
        self.assertTrue(any("IMAGE" in e for e in self.check(t)))
        self.assertTrue(any("footer" in e for e in self.check(t)))

    def test_leave_review_flow_binding_must_be_exact(self) -> None:
        for field, value in (
            ("flow_id", 39581903361452878),
            ("flow_action", "NAVIGATE"),
            ("text", "Pay again"),
            ("type", "URL"),
        ):
            with self.subTest(field=field):
                t = valid_template()
                t["components"][3]["buttons"][0][field] = value
                self.assertTrue(any("Leave Review FLOW" in e for e in self.check(t)))

    def test_no_extra_payment_or_marketing_buttons(self) -> None:
        t = valid_template()
        t["components"][3]["buttons"].append({"type": "URL", "text": "Buy again"})
        self.assertTrue(any("exactly one" in e for e in self.check(t)))

    def test_missing_component_or_invalid_provider_shape_fails_closed(self) -> None:
        t = valid_template()
        t["components"].pop()
        self.assertTrue(self.check(t))
        self.assertTrue(self.check([]))

    def test_cli_returns_success_only_for_exact_meta_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "provider.json"
            source.write_text(json.dumps(valid_template()), encoding="utf-8")
            args = ["--file", str(source), "--expected-id", "121234567890123"]
            self.assertEqual(candidate_gate.main(args), 0)
            t = valid_template()
            t["status"] = "PENDING"
            source.write_text(json.dumps(t), encoding="utf-8")
            self.assertEqual(candidate_gate.main(args), 1)


if __name__ == "__main__":
    unittest.main()
