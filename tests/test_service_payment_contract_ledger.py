"""Read-only service payment ledger and shared media contracts.

Only pure Python helpers and source contracts are tested. No AWS, Meta, payment,
customer notification, invoice creation, or S3 operation is executed.
"""

from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))

from lambda_utils import template_media  # noqa: E402
from lambda_utils.ecommerce import service_invoice_ledger, service_pricing_native  # noqa: E402


class FakeKeys:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def get_item(self, *, Key, ConsistentRead=False):
        self.calls.append((Key, ConsistentRead))
        if Key.get("orderId") == "PAYREF#WD-PAY-VALID":
            return {"Item": self.row} if self.row else {}
        return {}


class FakeAttempts:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def get_item(self, *, Key, ConsistentRead=False):
        self.calls.append((Key, ConsistentRead))
        return {"Item": self.row} if self.row else {}


def fixture():
    invoice = {
        "invoiceId": "inv-valid",
        "referenceId": "WD-PAY-VALID",
        "paymentId": "pay_valid",
        "total": Decimal("84.97"),
        "currency": "INR",
    }
    reservation = {
        "referenceId": "WD-PAY-VALID", "paymentAttemptId": "attempt-valid",
    }
    attempt = {
        "paymentAttemptId": "attempt-valid",
        "referenceId": "WD-PAY-VALID",
        "serviceKind": "VAULT",
        "status": "PAYMENT_PAID",
        "verifiedProviderPaymentId": "pay_valid",
        "verifiedCapturedPaise": Decimal(8497),
        "currency": "INR",
        "invoiceId": "inv-valid",
    }
    return invoice, reservation, attempt


def test_verified_vault_uses_only_reservation_and_exact_provider_evidence():
    invoice, res, attempt = fixture()
    keys, attempts = FakeKeys(res), FakeAttempts(attempt)
    assert service_invoice_ledger.verified_service_kind(invoice, keys, attempts) == "VAULT"
    assert keys.calls == [({"orderId": "PAYREF#WD-PAY-VALID"}, True)]
    assert attempts.calls == [({"paymentAttemptId": "attempt-valid"}, True)]


def test_website_payment_id_and_missing_optional_invoice_id_are_supported():
    invoice, res, attempt = fixture()
    invoice["providerPaymentId"] = invoice.pop("paymentId")
    attempt.pop("invoiceId")
    assert service_invoice_ledger.verified_service_kind(
        invoice, FakeKeys(res), FakeAttempts(attempt)
    ) == "VAULT"


def test_unlinked_customer_invoice_cannot_fake_a_vault_purchase():
    invoice, res, attempt = fixture()
    invoice["purpose"] = "Vault"
    for key, new in [
        ("referenceId", "WD-PAY-OTHER"),
        ("paymentId", "pay_other"),
        ("total", Decimal("85.00")),
        ("currency", "USD"),
    ]:
        changed = {**invoice, key: new}
        assert service_invoice_ledger.verified_service_kind(
            changed, FakeKeys(res), FakeAttempts(attempt)
        ) == ""
    for key, new in [
        ("serviceKind", "OTHER"),
        ("status", "PAYMENT_PENDING"),
        ("verifiedProviderPaymentId", "pay_other"),
        ("verifiedCapturedPaise", 8498),
        ("invoiceId", "inv-other"),
        ("referenceId", "WD-PAY-OTHER"),
        ("currency", "USD"),
    ]:
        changed = {**attempt, key: new}
        assert service_invoice_ledger.verified_service_kind(
            invoice, FakeKeys(res), FakeAttempts(changed)
        ) == ""


def test_missing_lineage_or_unpaid_invoice_does_not_create_vault_attribution():
    invoice, res, attempt = fixture()
    assert service_invoice_ledger.verified_service_kind(
        invoice, FakeKeys(None), FakeAttempts(attempt)
    ) == ""
    assert service_invoice_ledger.verified_service_kind(
        invoice, FakeKeys(res), FakeAttempts(None)
    ) == ""
    no_provider = {**invoice, "paymentId": ""}
    assert service_invoice_ledger.verified_service_kind(
        no_provider, FakeKeys(res), FakeAttempts(attempt)
    ) == ""


def test_media_contract_is_exactly_production_outbound_template_media():
    for kind in ("VAULT", "DROP_DOCS"):
        templates = service_pricing_native._payment_templates(kind)
        assert templates["headerImage"] == template_media.PAYMENT_TEMPLATE_HEADER
        assert templates["itemThumbnail"] == template_media.DEFAULT_ORDER_ITEM_THUMBNAIL
        assert templates["headerImage"] != templates["itemThumbnail"]
        assert templates["nativePay"] == "wecare_whatapp_native_pay_template"
    assert service_pricing_native._payment_templates("SUBMIT_REQUEST") is None


def test_vault_pricing_remains_server_authoritative_integer_paise():
    paise = 4900
    breakdown = service_pricing_native._collect_breakdown("VAULT", paise)
    assert breakdown["itemSubtotalPaise"] == paise
    assert breakdown["supplyGstPaise"] == 882
    assert breakdown["expressPaise"] > 0
    assert breakdown["totalPayablePaise"] > paise
    assert all(isinstance(v, int) for v in breakdown.values())


def test_workspace_shares_real_ledger_and_blocks_unbound_service_invoices():
    service = (ROOT / "src/pages/workspace/service/index.tsx").read_text()
    pay = (ROOT / "src/pages/workspace/payments/index.tsx").read_text()
    ledger = (ROOT / "src/components/workspace/pay/InvoiceRecords.tsx").read_text()
    client = (ROOT / "src/api/client.ts").read_text()
    preset = (ROOT / "src/components/workspace/pay/PayFlow.tsx").read_text()
    vault = (ROOT / "src/components/workspace/service/VaultJourneyPreview.tsx").read_text()
    engine = (ROOT / "amplify/functions/payments/invoice-engine/handler.py").read_text()

    assert 'serviceKind="VAULT"' in service
    assert 'serviceKind="VAULT"' in pay
    assert "serviceKind ? { serviceKind }" in ledger
    assert "query.set( 'serviceKind', params.serviceKind )" in client
    assert "service_invoice_ledger.verified_service_kind" in engine
    assert "if ( choice.needsTarget )" in preset
    assert "PaymentTemplateMedia" in vault
    assert "PaymentTemplateMedia" in pay
    assert "choice.kind === 'VAULT'" in pay
    assert "api.deleteInvoice(" not in ledger
    assert "api.sendPaymentLink(" not in ledger
