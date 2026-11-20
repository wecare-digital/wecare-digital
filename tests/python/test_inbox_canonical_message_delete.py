"""Single-row inbox deletion must preserve payments, media, and unknown identities.

Only in-memory fixtures. Never contacts a live AWS table.
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "amplify/functions/core/messages-delete/handler.py"
spec = importlib.util.spec_from_file_location("messages_delete_canonical_contract", SOURCE)
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)


class Table:
    def __init__(self, row=None):
        self.row = row
        self.deletes = []

    def get_item(self, *, Key, ConsistentRead=False):
        assert ConsistentRead is True
        return {"Item": self.row} if self.row else {}

    def delete_item(self, **kwargs):
        self.deletes.append(kwargs)


class Db:
    def __init__(self, message=None, contact=None, meta=None):
        self.tables = {
            handler.CANONICAL_TABLE: Table(message),
            handler.CONTACTS_TABLE: Table(contact),
            handler.CONVERSATION_META_TABLE: Table(meta),
            handler.INVOICES_TABLE: Table(),
            handler.ORDERS_TABLE: Table(),
        }

    def Table(self, name):
        return self.tables[name]


class Link:
    def __init__(self, blocked=False):
        self.blocked = blocked


def event(mfa=True):
    return {"_auth": {
        "role": "Admin", "mfaEnrolled": mfa,
        "username": "synthetic-operator",
    }}


def record(**extra):
    return {
        "id": "msg-1", "contactId": "contact-1", "channel": "whatsapp",
        "messageType": "text", "content": "hello, good afternoon", **extra,
    }


def payload(result):
    return int(result["statusCode"]), json.loads(result["body"])


@pytest.fixture
def setup(monkeypatch):
    import lambda_utils.middleware as middleware
    monkeypatch.setattr(middleware, "require_auth", lambda _ev, required_role="Viewer": None)
    monkeypatch.setattr(handler, "record_audit", lambda **_kw: "audit-123")
    monkeypatch.setattr(
        handler.contact_payment_links, "has_payment_links", lambda **_kw: Link(),
    )
    db = Db(message=record(), contact={"id": "contact-1", "phone": "+15550000000"})
    monkeypatch.setattr(handler, "dynamodb", db)
    return db


def test_normal_text_requires_audit_and_exact_primary_key(setup):
    status, result = payload(handler._delete_canonical_message(event(), "", "msg-1"))
    assert status == 200
    assert result["rowDeleted"] is True
    assert result["erasureComplete"] is False
    assert result["auditId"] == "audit-123"
    writes = setup.tables[handler.CANONICAL_TABLE].deletes
    assert len(writes) == 1
    assert writes[0]["Key"] == {"id": "msg-1"}
    assert "contactId = :cid" in writes[0]["ConditionExpression"]
    assert writes[0]["ExpressionAttributeValues"][":cid"] == "contact-1"


def test_media_and_payment_words_are_not_deleted(setup):
    for row in [
        record(s3Key="secure/d/private/image.png"),
        record(mediaId="media-id"),
        record(content="Please pay the invoice"),
        record(paymentRequestId="payment-ref"),
        record(messageType="flow_response"),
    ]:
        setup.tables[handler.CANONICAL_TABLE].row = row
        status, result = payload(handler._delete_canonical_message(event(), "", "msg-1"))
        assert status == 409
        assert result["errorCode"] == "MESSAGE_REVIEW_REQUIRED"
    assert not setup.tables[handler.CANONICAL_TABLE].deletes


def test_captured_payment_protects_even_plain_text(setup, monkeypatch):
    monkeypatch.setattr(
        handler.contact_payment_links, "has_payment_links", lambda **_kw: Link(True),
    )
    status, result = payload(handler._delete_canonical_message(event(), "", "msg-1"))
    assert status == 409
    assert result["errorCode"] == "MESSAGE_FINANCIAL_HISTORY"
    assert not setup.tables[handler.CANONICAL_TABLE].deletes


def test_retention_hold_blocks_deletion(setup):
    setup.tables[handler.CONVERSATION_META_TABLE].row = {
        "conversationId": "contact-1", "tags": ["retention-hold"]
    }
    status, result = payload(handler._delete_canonical_message(event(), "", "msg-1"))
    assert status == 409
    assert result["errorCode"] == "MESSAGE_RETENTION_HOLD"
    assert not setup.tables[handler.CANONICAL_TABLE].deletes


def test_missing_identity_or_audit_failure_fails_closed(setup, monkeypatch):
    setup.tables[handler.CONTACTS_TABLE].row = None
    status, _ = payload(handler._delete_canonical_message(event(), "", "msg-1"))
    assert status == 409
    setup.tables[handler.CONTACTS_TABLE].row = {"id": "contact-1"}
    monkeypatch.setattr(handler, "record_audit", lambda **_kw: None)
    status, result = payload(handler._delete_canonical_message(event(), "", "msg-1"))
    assert status == 503
    assert result["errorCode"] == "MESSAGE_AUDIT_UNAVAILABLE"
    assert not setup.tables[handler.CANONICAL_TABLE].deletes


def test_admin_mfa_is_not_optional(setup):
    status, result = payload(handler._delete_canonical_message(event(False), "", "msg-1"))
    assert status == 403
    assert result["errorCode"] == "MESSAGE_DELETE_ADMIN_MFA_REQUIRED"
    assert not setup.tables[handler.CANONICAL_TABLE].deletes
