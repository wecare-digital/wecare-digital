"""No-side-effect source guard for Pay & Flow after the 2026-11-02 rebuild.

Runs during Amplify prebuild. It tests the UI boundary only: the canonical
payment engine and provider integrations have their own executable tests.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class PayFlowWorkspaceArchitectureTests(unittest.TestCase):
    def test_three_sections_stay_in_one_canonical_route(self):
        s = read("src/pages/workspace/payments/index.tsx")
        for name in ("'collect'", "'vault'", "'contribute'",
                     "'display'", "'create'", "'ledger'"):
            self.assertIn(name, s)
        self.assertIn("components/workspace/pay/PayFlow", s)
        self.assertIn("components/workspace/pay/CollectOverview", s)
        self.assertIn("components/workspace/pay/VaultWorkbench", s)
        self.assertIn("components/workspace/pay/ContributePaymentPlan", s)
        self.assertNotIn("components/workspace/service/SecureFiles", s)

    def test_vault_is_exact_file_and_approved_template_only(self):
        s = read("src/components/workspace/pay/VaultWorkbench.tsx")
        for call in ("initVaultFileUpload", "uploadVaultFileBytes",
                     "confirmVaultFileUpload", "listSecureFiles",
                     "requestSecureFilePayment", "sendSecureFileAccess",
                     "readVaultMessageDeliveryLog"):
            self.assertIn(call, s)
        for forbidden in ("sendSecureFileOffer(", "sendWhatsAppInteractive(",
                          "isInteractive:", "interactiveType:", "orderDetails:"):
            self.assertNotIn(forbidden, s)
        self.assertIn("file.accessState === 'UNPAID'", s)
        self.assertIn("!file.lastPaymentRequestedAt", s)
        self.assertIn("inFlight.current", s)
        self.assertIn("file.status === 'active'", s)

    def test_contribute_reuses_guarded_single_send(self):
        s = read("src/components/workspace/pay/ContributeStaffControls.tsx")
        self.assertIn("sendStaffContributionPaymentOnce", s)
        self.assertIn("getStaffContributionSendReadiness", s)
        self.assertIn("TARGET_PAISE = 30000", s)
        self.assertIn("sendLocked", s)
        self.assertIn("priceMatches", s)

    def test_service_links_target_canonical_vault_and_contribute(self):
        s = read("src/pages/workspace/service/index.tsx")
        self.assertIn("components/workspace/pay/VaultWorkbench", s)
        self.assertIn("components/workspace/pay/ContributePaymentPlan", s)
        self.assertIn('return <Contribute workspaceView="display" />;', s)
        # The modules restored by PR #2193 remain available for other services.
        self.assertIn("components/workspace/service/CustomerDropDocs", s)
        self.assertIn("components/workspace/service/ShipmentTrackingPanel", s)
        content = read("src/pages/workspace/content/index.tsx")
        self.assertIn("components/workspace/seo/BlogManager", content)

    def test_vault_timing_adapter_does_not_restore_offer(self):
        s = read("src/components/workspace/pay/VaultDeliveryTiming.tsx")
        self.assertIn("./VaultJourneyPreview", s)
        adapter = read("src/components/workspace/pay/VaultJourneyPreview.ts")
        self.assertIn("step.role !== 'ready_offer'", adapter)
        self.assertNotIn("sendWhatsApp", adapter)


if __name__ == "__main__":
    unittest.main()
