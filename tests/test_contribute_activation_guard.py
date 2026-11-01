"""Static release contract for the *approval-dependent* no-flag Contribute proposal.

No Lambda invocation, database access, WhatsApp send, provider request or payment.
This is only code evidence; Finance/tax approval remains a separate requirement.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = ROOT / "amplify/functions/ecommerce/checkout/handler.py"
PRICE = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/service_pricing_native.py"
STAFF = ROOT / "amplify/functions/shared/lambda_utils/ecommerce/staff_contribution.py"


class ActivationGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkout = CHECKOUT.read_text(encoding="utf-8")
        cls.price = PRICE.read_text(encoding="utf-8")
        cls.staff = STAFF.read_text(encoding="utf-8")

    def test_no_temporary_payment_feature_flag_remains(self):
        for text in (self.checkout, self.price):
            self.assertNotIn("STAFF_CONTRIBUTE_NATIVE_SEND_ENABLED", text)
            self.assertNotIn("CONTRIBUTE_TAXABLE_NATIVE_PAYMENT_ENABLED", text)
            self.assertNotIn("_contribute_taxable_release_enabled", text)
            self.assertNotIn("_staff_contribution_release_enabled", text)

    def test_admin_and_verified_customer_boundaries_survive(self):
        for required in (
            'require_auth(event, required_role="Admin")',
            '"role") != "Admin"',
            "staff_actor_hash=actor_hash",
            "_native_whatsapp_identity(",
            "CONTACT_IDENTITY_CONFLICT",
            "CONTRIBUTION_CUSTOMER_UNVERIFIED",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.checkout)

    def test_one_live_payment_and_immutable_quote_protection_survive(self):
        for required in (
            "_staff_contribution_catalog_is_current(",
            "ConsistentRead=True",
            "valid_staff_contribution_snapshot(",
            "_wa_cart_live_key(",
            "_claim_wa_cart(",
            "_record_wa_cart(",
            "_release_wa_cart(",
            "sendUnconfirmed",
            "CONTRIBUTION_REQUEST_ALREADY_OPEN",
            "CONTRIBUTION_CATALOG_CHANGED",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.checkout)
        # Prevent a missing/malformed catalog identity from ever reaching DynamoDB.
        self.assertIn("if (not product_id or not variant_id", self.checkout)
        self.assertIn("or product_id not in CONTRIBUTION_PRODUCT_IDS", self.checkout)
        self.assertIn("or variant_id not in CONTRIBUTION_CHOICES_PAISE", self.checkout)
        self.assertIn("catalogGrossPaise", self.staff)
        self.assertIn("convenience_gst_paise", self.staff)
        self.assertIn("price == Decimal(STAFF_CONTRIBUTION_TOTAL_PAISE)", self.staff)

    def test_no_client_money_override_or_generic_template_send(self):
        self.assertIn('set(body) != {"action", "contactId"}', self.checkout)
        self.assertIn("CONTRIBUTION_QUANTITY_MUST_BE_ONE", self.checkout)
        self.assertIn("_contribution_breakdown(paise)", self.price)


if __name__ == "__main__":
    unittest.main()
