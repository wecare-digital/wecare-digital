"""A synthetic dry-run cannot erase either protected contact or financial evidence."""
import pytest

from lambda_utils.erasure.selective_preview import (
    build_preview, ErasurePreviewError, RETAIN_PROTECTED, RETAIN_FINANCIAL,
    RETAIN_LEGAL_LOCK, REVIEW_REQUIRED, ELIGIBLE_FOR_APPROVAL,
)


def data(*, complete=False):
    contacts = [
        {"id": "held-a", "name": "Same display name", "phone": "+911111111111",
         "locked": True, "lockedReason": "created"},
        {"id": "held-b", "name": "Same display name", "phone": "+912222222222",
         "locked": True, "lockedReason": "created"},
        {"id": "new-c", "phone": "+913333333333", "locked": True, "lockedReason": "created"},
        {"id": "paid-d", "phone": "+914444444444", "locked": False,
         "checkoutCustomerId": "buyer-123"},
        {"id": "legal-e", "phone": "+915555555555",
         "locked": True, "lockedReason": "legal-hold"},
        {"id": "keyword-f", "phone": "+916666666666", "locked": False},
    ]
    messages = {
        "MessagesTable": [
            {"id": "ma", "contactId": "held-a", "content": "Hello"},
            {"id": "mb", "contactId": "held-b", "content": "Another hello"},
            {"id": "mc", "contactId": "new-c", "content": "nonfinancial"},
            {"id": "mf", "contactId": "keyword-f", "content": "Razorpay refund receipt"},
            {"id": "unknown", "content": "mystery without contact"},
        ],
        "WhatsAppInboundTable": [
            {"id": "ib", "contactId": "held-b", "content": "Hi"},
        ],
        "WhatsAppOutboundTable": [
            {"id": "ob", "contactId": "held-b", "content": "Reply"},
        ],
    }
    financial = {
        "payments": [{"id": "provider_row", "orderId": "order-9", "paymentId": "pay-9"}],
        "payment_attempts": [{"id": "attempt_row", "referenceId": "ref-9", "orderId": "order-9"}],
        "invoices": [{"id": "invoice_row", "orderId": "order-9", "invoiceId": "inv-9"}],
        "orders": [{"id": "order_row", "orderId": "order-9", "customerId": "buyer-123"}],
    }
    return dict(contacts=contacts, messages=messages, financial=financial,
                protected_contact_ids={"held-a", "held-b"},
                dependency_inventory_complete=complete)


def test_two_identical_names_are_distinct_and_both_protected():
    result = build_preview(**data())
    assert result.contacts["held-a"] == RETAIN_PROTECTED
    assert result.contacts["held-b"] == RETAIN_PROTECTED
    assert result.messages[("MessagesTable", "ma")] == RETAIN_PROTECTED
    assert result.messages[("MessagesTable", "mb")] == RETAIN_PROTECTED
    assert result.messages[("WhatsAppInboundTable", "ib")] == RETAIN_PROTECTED
    assert result.messages[("WhatsAppOutboundTable", "ob")] == RETAIN_PROTECTED
    assert result.summary["contacts"]["protected"] == 2
    assert not result.executable


def test_finance_graph_holds_customer_with_provider_only_payment_row():
    result = build_preview(**data())
    assert result.contacts["paid-d"] == RETAIN_FINANCIAL
    assert result.contacts["keyword-f"] == RETAIN_FINANCIAL
    assert result.contacts["legal-e"] == RETAIN_LEGAL_LOCK
    for source, entries in data()["financial"].items():
        assert result.summary["financial"]["sourceRecordCounts"][source] == len(entries)


def test_created_lock_is_reviewable_but_never_automatically_unlocked():
    result = build_preview(**data())
    assert result.contacts["new-c"] == REVIEW_REQUIRED
    assert result.messages[("MessagesTable", "mc")] == REVIEW_REQUIRED
    assert result.summary["deletedContacts"] == 0
    assert result.summary["deletedMessages"] == 0

    # When a separate *complete* inventory exists, a created lock is not
    # misrepresented as a paid/legal lock. This is STILL not execution approval.
    # A purposely unlinked orphan message remains REVIEW_REQUIRED.
    complete = build_preview(**data(complete=True))
    assert complete.contacts["new-c"] == ELIGIBLE_FOR_APPROVAL
    assert not complete.executable


def test_orphans_are_never_marked_deletable_by_missing_finance_keywords():
    result = build_preview(**data(complete=True))
    assert result.messages[("MessagesTable", "unknown")] == REVIEW_REQUIRED


def test_finance_clue_retains_its_entire_conversation():
    inp = data(complete=True)
    inp["messages"]["MessagesTable"].append({
        "id": "keyword-f2", "contactId": "keyword-f",
        "content": "Ordinary conversation context"})
    result = build_preview(**inp)
    assert result.contacts["keyword-f"] == RETAIN_FINANCIAL
    assert result.messages[("MessagesTable", "keyword-f2")] == RETAIN_FINANCIAL


def test_versioned_media_blocks_message_without_specific_object_inventory():
    inp = data(complete=True)
    inp["messages"]["MessagesTable"].append(
        {"id": "med", "contactId": "new-c", "s3Key": "private/example"})
    result = build_preview(**inp)
    assert result.messages[("MessagesTable", "med")] == REVIEW_REQUIRED


@pytest.mark.parametrize("remove", ["financial", "message_source", "protected"])
def test_incomplete_evidence_refuses_preview(remove):
    inp = data()
    if remove == "financial":
        del inp["financial"]["payments"]
    if remove == "message_source":
        del inp["messages"]["WhatsAppInboundTable"]
    if remove == "protected":
        inp["contacts"].pop(0)
    with pytest.raises(ErasurePreviewError):
        build_preview(**inp)


def test_duplicate_primary_key_never_produces_candidate():
    inp = data(complete=True)
    inp["messages"]["MessagesTable"].append(
        {"id": "ma", "contactId": "new-c"})
    with pytest.raises(ErasurePreviewError):
        build_preview(**inp)


def test_unlinked_financial_record_refuses_candidate_even_with_complete_flag():
    inp = data(complete=True)
    inp["financial"]["payments"].append(
        {"note": "provider record without reconciliation identity"})
    result = build_preview(**inp)
    assert result.contacts["new-c"] == REVIEW_REQUIRED
    assert not result.executable


def test_no_write_or_unconditional_bulk_delete_apis():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    planner = (root / "amplify/functions/shared/lambda_utils/erasure/selective_preview.py").read_text()
    cli = (root / "scripts/preview_selective_erasure.py").read_text()
    for content in (planner, cli):
        for forbidden in (
            ".delete_item(", ".batch_writer(", "DeleteItem", "DROP TABLE",
            ".update_item(", ".put_item(", "ALLOW_MESSAGE_CLEAR_ALL",
        ):
            assert forbidden not in content
