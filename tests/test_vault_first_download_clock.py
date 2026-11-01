"""Vault starts its ONE paid 24h window on first authenticated download.

Tests pure production window math and source contract of the two paid sender
paths. Never invokes AWS, WhatsApp, Razorpay or customer downloads.
"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WINDOW = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/vault_window.py"
SECURE = ROOT / "amplify/functions/core/secure-files/handler.py"
WHATSAPP = ROOT / "amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py"
CUSTOMER = ROOT / "src/components/get/GetPage.tsx"
LEGACY_DOCS = ROOT / "src/components/workspace/service/Documents.tsx"

spec = importlib.util.spec_from_file_location("tested_vault_window", WINDOW)
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)


class FirstDownloadClockTests(unittest.TestCase):
    def test_verified_purchase_remains_ready_until_first_download(self):
        paid = {"grantId": "one-owner-one-file"}
        self.assertEqual(window.paid_window_count(paid), 1)
        self.assertEqual(window.access_state(paid, 1730400000), "READY")
        self.assertEqual(window.unused_paid_windows(paid), 1)

    def test_first_window_opens_for_exactly_24_hours(self):
        paid = {"grantId": "one-owner-one-file"}
        now = 1730400000
        fields, opened = window.open_window(paid, now, hours=24)
        self.assertTrue(opened)
        self.assertEqual(fields["accessWindowStartedAt"], now)
        self.assertEqual(fields["accessWindowEndsAt"], now + 24*3600)
        self.assertEqual(fields["accessWindowCount"], 1)
        current = {**paid, **fields}
        self.assertEqual(window.access_state(current, now+300), "OPEN")
        self.assertEqual(window.seconds_remaining(current, now), 86400)

    def test_replayed_send_and_download_do_not_extend_an_open_window(self):
        now = 1730400000
        paid = {"grantId": "one-owner-one-file",
                "accessWindowStartedAt": now, "accessWindowEndsAt": now+86400,
                "accessWindowCount": 1}
        fields, opened = window.open_window(paid, now+1800, hours=24)
        self.assertFalse(opened)
        self.assertEqual(fields, {})
        self.assertEqual(window.window_ends_at(paid), now+86400)

    def test_expired_paid_file_never_opens_an_unpaid_renewal_window(self):
        now = 1730400000
        paid = {"grantId": "one-owner-one-file",
                "accessWindowStartedAt": now-90000,
                "accessWindowEndsAt": now-3600, "accessWindowCount": 1}
        self.assertEqual(window.access_state(paid, now), "EXPIRED")
        self.assertEqual(window.unused_paid_windows(paid), 0)
        self.assertEqual(window.open_window(paid, now, hours=24), ({}, False))

    def test_legacy_window_remains_bound_to_original_timestamp(self):
        legacy = {"grantId": "paid-before-upgrade",
                  "accessWindowStartedAt": 1700000000,
                  "accessWindowEndsAt": 1700086400,
                  "accessWindowCount": 1}
        self.assertEqual(window.access_state(legacy, 1700000050), "OPEN")
        self.assertEqual(window.access_state(legacy, 1700086400), "EXPIRED")

    def test_paid_whatsapp_sender_does_not_open_time_on_meta_acceptance(self):
        text = WHATSAPP.read_text(encoding="utf-8")
        block = text[text.index("def _prepare_and_send("):text.index("def send_review(")]
        self.assertIn("window_opened = False", block)
        self.assertNotIn("_open_paid_window(", block)
        self.assertNotIn("'openVaultAccessWindow'", block)
        self.assertIn("if not _send_once(", block)

    def test_legacy_secure_files_sender_never_consumes_time_on_acceptance(self):
        text = SECURE.read_text(encoding="utf-8")
        block = text[text.index("def deliver_over_whatsapp("):
                     text.index("def _redeem(", text.index("def deliver_over_whatsapp("))]
        self.assertIn("send_vault_link(", block)
        self.assertNotIn("_open_access_window(", block)
        self.assertIn("return ok, detail", block)

    def test_download_rechecks_owner_and_storage_before_opening(self):
        text = SECURE.read_text(encoding="utf-8")
        block = text[text.index("def _redeem("):text.index("# ── Drop Docs", text.index("def _redeem("))]
        owner = block.index("_owned_active_file(file_id, identity)")
        storage = block.index("if not _vault_file_storage_ready(item)")
        opening = block.index("entitlement = _open_access_window(entitlement, now)")
        self.assertLess(owner, storage)
        self.assertLess(storage, opening)
        self.assertIn("vault_window.unused_paid_windows(entitlement) > 0", block)

    def test_rolling_deploy_old_send_time_action_is_fail_closed(self):
        text = SECURE.read_text(encoding="utf-8")
        start = text.index('if event.get("internalAction") == "openVaultAccessWindow"')
        section = text[start:start+1000]
        self.assertIn('{"ok": False, "detail": "deferred_until_first_authenticated_download"}',
                      section)
        self.assertNotIn("open_vault_access_window(grant_id)", section)

    def test_customer_and_legacy_staff_copy_matches_new_policy(self):
        customer = CUSTOMER.read_text(encoding="utf-8")
        documents = LEGACY_DOCS.read_text(encoding="utf-8")
        self.assertIn("24-hour access begins on your first authenticated download", customer)
        self.assertNotIn("delivery or first download", customer)
        self.assertIn("Paid · access expired · no renewal", documents)
        self.assertNotIn("renewal needed", documents)


if __name__ == "__main__":
    unittest.main()
