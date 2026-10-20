"""Primary-phone protection and consent-as-evidence on the contacts handler.

Two FEAT-003 guarantees proven against the real handler (loaded by path) with the contacts
fake table:

  * a provider-VERIFIED primary phone cannot be silently overwritten by a lower-trust
    manual/import edit - the conflicting change is routed to review (409
    PRIMARY_PHONE_REVIEW_REQUIRED);
  * consent is append-only evidence - an append never erases history, OPTED_OUT is respected,
    and a bulk import can never manufacture an opt-in for an address book.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "amplify/functions/shared"))
sys.path.insert(0, os.path.dirname(__file__))

from contacts_fake_table import FakeContactsResource, FakeContactsTable  # noqa: E402
from lambda_utils.identity import consent as consent_evidence  # noqa: E402
from lambda_utils.identity import provenance  # noqa: E402

HANDLER_PATH = ROOT / "amplify/functions/core/contacts/handler.py"


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setenv("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")
    spec = importlib.util.spec_from_file_location("contacts_feat003_handler", HANDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Auth is exercised elsewhere; here we go straight at the private functions, which is also
    # how test_crm_api and the merge tests reach this handler.
    return module


def _row(**overrides):
    row = {
        "id": "c1", "contactId": "c1",
        "name": "Asha", "phone": "+919000000000", "email": "asha@example.com",
        "createdAt": 1, "updatedAt": 1, "deletedAt": None,
    }
    row.update(overrides)
    return row


def _bind(handler, monkeypatch, table):
    monkeypatch.setattr(handler, "dynamodb", FakeContactsResource(table))


# ── primary-phone protection ────────────────────────────────────────────────────

def test_a_verified_phone_is_not_overwritten_by_a_manual_edit(handler, monkeypatch):
    table = FakeContactsTable([_row(**{
        provenance.PROVENANCE_ATTRIBUTE: {"phone": "WHATSAPP_INBOUND"},
    })])
    _bind(handler, monkeypatch, table)

    resp = handler._update("c1", {"phone": "+919111111111"}, "req", "")
    assert resp["statusCode"] == 409
    body = json.loads(resp["body"])
    assert body["errorCode"] == handler.PRIMARY_PHONE_REVIEW_REQUIRED
    # Nothing was written: the verified routing identity survives untouched.
    stored = next(r for r in table.items if r["id"] == "c1")
    assert stored["phone"] == "+919000000000"


def test_a_verified_phone_is_not_overwritten_by_an_import_edit(handler, monkeypatch):
    table = FakeContactsTable([_row(**{
        provenance.PROVENANCE_ATTRIBUTE: {"phone": "TRUECALLER"},
    })])
    _bind(handler, monkeypatch, table)

    resp = handler._update(
        "c1", {"phone": "+919111111111", "importSource": True}, "req", "")
    assert resp["statusCode"] == 409
    assert json.loads(resp["body"])["errorCode"] == handler.PRIMARY_PHONE_REVIEW_REQUIRED


def test_an_unclaimed_phone_may_be_edited_and_records_operator_provenance(handler, monkeypatch):
    # No fieldSources: a legacy row. The edit is allowed and stamps the operator provenance so
    # the NEXT edit is evaluated against a recorded source.
    table = FakeContactsTable([_row()])
    _bind(handler, monkeypatch, table)

    resp = handler._update("c1", {"phone": "+919222222222"}, "req", "")
    assert resp["statusCode"] == 200
    # The update expression carried the merged fieldSources with phone=DASHBOARD.
    last = table.updates[-1]
    assert provenance.PROVENANCE_ATTRIBUTE in last["UpdateExpression"]
    stamped = next(v for k, v in last["ExpressionAttributeValues"].items()
                   if isinstance(v, dict) and "phone" in v)
    assert stamped["phone"] == "DASHBOARD"


def test_an_unchanged_phone_is_not_a_conflict(handler, monkeypatch):
    table = FakeContactsTable([_row(**{
        provenance.PROVENANCE_ATTRIBUTE: {"phone": "WHATSAPP_INBOUND"},
    })])
    _bind(handler, monkeypatch, table)
    # Same value re-submitted: `needs_review` sees no change, so it is allowed (and in practice
    # a no-op write).
    resp = handler._update("c1", {"phone": "+919000000000", "name": "Asha V"}, "req", "")
    assert resp["statusCode"] == 200


# ── consent evidence routes ───────────────────────────────────────────────────────

def test_consent_append_layers_history_and_read_derives_current_state(handler, monkeypatch):
    table = FakeContactsTable([_row()])
    _bind(handler, monkeypatch, table)

    first = handler._consent_append(
        "c1", {"channel": "WHATSAPP", "state": "OPTED_IN", "source": "WEB_FORM",
               "reference": "form#1"}, "req", "")
    assert first["statusCode"] == 200

    second = handler._consent_append(
        "c1", {"channel": "WHATSAPP", "state": "OPTED_OUT", "source": "CUSTOMER_REQUEST"},
        "req", "")
    assert second["statusCode"] == 200
    ledger = json.loads(second["body"])["ledger"]
    assert len(ledger) == 2, "the opt-in evidence must survive the opt-out"

    read = handler._consent_read("c1", "req", "")
    summary = json.loads(read["body"])["summary"]
    assert summary["WHATSAPP"]["state"] == consent_evidence.OPTED_OUT
    assert summary["WHATSAPP"]["history"] == 2
    assert summary["WHATSAPP"]["sendable"] is False


def test_consent_append_refuses_an_invalid_record(handler, monkeypatch):
    table = FakeContactsTable([_row()])
    _bind(handler, monkeypatch, table)
    resp = handler._consent_append(
        "c1", {"channel": "TELEGRAM", "state": "OPTED_IN", "source": "WEB_FORM"}, "req", "")
    assert resp["statusCode"] == 400


def test_consent_import_cannot_manufacture_an_opt_in(handler, monkeypatch):
    table = FakeContactsTable([_row()])
    _bind(handler, monkeypatch, table)
    resp = handler._consent_import(
        "c1", {"records": [
            {"channel": "WHATSAPP", "state": "OPTED_IN", "importSource": "CSV_IMPORT",
             "at": 1_700_000_000},
        ]}, "req", "")
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["imported"] == 0
    assert len(body["refused"]) == 1
    # No opt-in evidence was written for the channel, so it is not sendable.
    assert "WHATSAPP" not in body["summary"]


def test_consent_import_accepts_existing_evidence_and_opt_outs(handler, monkeypatch):
    table = FakeContactsTable([_row()])
    _bind(handler, monkeypatch, table)
    resp = handler._consent_import(
        "c1", {"records": [
            {"channel": "EMAIL", "state": "OPTED_IN", "importSource": "MIGRATION",
             "at": 1_700_000_000, "evidenceSource": "DOUBLE_OPT_IN",
             "reference": "mailchimp:list#9"},
            {"channel": "SMS", "state": "OPTED_OUT", "importSource": "CSV_IMPORT",
             "at": 1_700_000_000},
        ]}, "req", "")
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["imported"] == 2
    assert body["summary"]["EMAIL"]["state"] == consent_evidence.OPTED_IN
    assert body["summary"]["EMAIL"]["source"] == "DOUBLE_OPT_IN"
    assert body["summary"]["SMS"]["state"] == consent_evidence.OPTED_OUT
