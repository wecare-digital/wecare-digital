"""Customer identity 409 and safe delete/void regression coverage.

Exercises the actual Contacts duplicate-payload function in isolation with read-only fake
DynamoDB tables, and pins the Workspace UI to non-purging deletion semantics.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
HANDLER = ROOT / "amplify/functions/core/contacts/handler.py"
CUSTOMERS = ROOT / "src/pages/workspace/customers/index.tsx"
API = ROOT / "src/api/client.ts"
PAY = ROOT / "src/components/workspace/pay/PayFlow.tsx"
INVOICE = ROOT / "amplify/functions/payments/invoice-engine/handler.py"


def conflict_payload(*, owner: str = "", row: dict | None = None,
                     existing: dict | None = None, lookup_failure: bool = False):
    source = HANDLER.read_text()
    parsed = ast.parse(source)
    fn = next(node for node in parsed.body
              if isinstance(node, ast.FunctionDef) and node.name == "_duplicate_conflict_payload")
    if fn.decorator_list:
        raise AssertionError("Unexpected decorator on duplicate conflict helper")

    class ContactTable:
        reads = 0

        def get_item(self, **kwargs):
            self.reads += 1
            assert kwargs["ConsistentRead"] is True
            if lookup_failure:
                raise RuntimeError("temporary lookup failure")
            return {"Item": row} if row is not None else {}

    contacts = ContactTable()

    class Dynamo:
        def Table(self, name):
            return object() if name.endswith("IdentityClaimsTable") else contacts

    env = {
        "Dict": Dict, "Any": Any, "Optional": Optional, "json": json,
        "dynamodb": Dynamo(),
        "identity_claims": SimpleNamespace(
            TABLE_NAME="stack-wecare-digital-IdentityClaimsTable",
            owner=lambda _table, _kind, _value: owner,
        ),
        "contact_key": SimpleNamespace(
            key=lambda contact_id: {"id": contact_id},
            resolve=lambda item: item.get("id", ""),
        ),
        "_duplicate_owner_row": lambda _phone, _email, exclude_id=None: existing,
        "ARCHIVED_AT_ATTRIBUTE": "archivedAt",
        "CONTACTS_TABLE": "stack-wecare-digital-ContactsTable",
        "MERGE_COMPLETE": "merged",
        "logger": SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    }
    module = ast.Module(body=[fn], type_ignores=[])
    exec(compile(module, str(HANDLER), "exec"), env)
    result = env["_duplicate_conflict_payload"]("+918100640044", None, "A contact already exists")
    return result, contacts.reads


def test_missing_claim_owner_is_not_labeled_an_openable_existing_contact():
    result, reads = conflict_payload(owner="wa918100640044")
    assert reads == 1
    assert result["errorCode"] == "CONTACT_IDENTITY_RECONCILIATION_REQUIRED"
    assert result["reconciliationRequired"] is True
    assert result["identityType"] == "PHONE"
    assert "existingContactId" not in result
    assert "administrator" in result["error"].lower()


def test_deleted_claim_owner_stays_blocked_for_administrator_review():
    result, _ = conflict_payload(
        owner="wa918100640044",
        row={"id": "wa918100640044", "deletedAt": 1234},
    )
    assert result["errorCode"] == "CONTACT_IDENTITY_RECONCILIATION_REQUIRED"
    assert "existingContactId" not in result


def test_actual_existing_archived_customer_still_resolves_for_restore():
    result, reads = conflict_payload(
        existing={"id": "customer-001", "archivedAt": 1234},
    )
    assert reads == 0
    assert result["errorCode"] == "CONTACT_ALREADY_EXISTS"
    assert result["existingContactId"] == "customer-001"
    assert result["existingArchived"] is True


def test_unreadable_claim_owner_does_not_pretend_an_orphan_was_proven():
    result, _ = conflict_payload(owner="wa918100640044", lookup_failure=True)
    assert result["errorCode"] == "CONTACT_ALREADY_EXISTS"
    assert not result.get("reconciliationRequired")


def test_no_claim_owner_keeps_legacy_duplicate_refusal():
    result, reads = conflict_payload()
    assert reads == 0
    assert result["errorCode"] == "CONTACT_ALREADY_EXISTS"


def test_customer_soft_delete_is_guarded_and_never_purges_payment_history():
    api = API.read_text()
    customers = CUSTOMERS.read_text()
    handler = HANDLER.read_text()
    assert "softDeleteContactResult" in api
    assert "method: 'DELETE'" in api
    assert "api.softDeleteContactResult(contactId)" in customers
    assert "hardDeleteContact(" not in customers
    assert "Delete customer" in customers and "Archive" in customers
    assert "phone stays reserved" in customers.lower()
    assert "danger: true" in customers
    assert "_hard_delete_refusal(contact_id" in handler
    assert "HARD_DELETE_DISABLED" in handler
    assert "CONTACT_IDENTITY_RECONCILIATION_REQUIRED" in customers
    assert "Search by number to open it" not in customers


def test_invoice_delete_remains_impossible_and_ui_offers_conditional_void():
    api = API.read_text()
    pay = PAY.read_text()
    engine = INVOICE.read_text()
    assert "api.cancelInvoiceResult( inv.invoiceId" in pay
    assert "canCancelInvoice( inv )" in pay
    assert "Void invoice" in pay
    assert "Delete is unavailable for issued GST invoices" in pay
    assert "api.deleteInvoice(" not in pay
    assert "return _resp(410, {" in engine[engine.index("def delete_invoice("):]
    assert "INVOICE_IMMUTABLE" in engine
    assert "INVOICE_CANCEL_MONEY_MOVED" in engine


def test_archive_and_delete_share_atomic_mutation_guard():
    customers = CUSTOMERS.read_text()
    assert "const customerMutationInFlight = useRef(false)" in customers
    archive = customers[customers.index("const handleArchive = async"):customers.index("const handleDeleteCustomer = async")]
    delete = customers[customers.index("const handleDeleteCustomer = async"):customers.index("const handleUnlock = async")]
    for action in (archive, delete):
        assert "if (deleting || customerMutationInFlight.current) return;" in action
        assert "if (!ok || customerMutationInFlight.current) return;" in action
        assert "customerMutationInFlight.current = true" in action
        assert "customerMutationInFlight.current = false" in action


def test_legacy_success_without_delete_type_refreshes_customer_list():
    customers = CUSTOMERS.read_text()
    delete = customers[customers.index("const handleDeleteCustomer = async"):customers.index("const handleUnlock = async")]
    assert "result.data?.success" in delete
    assert "result.data.deleteType === 'soft' || result.data.deleteType == null" in delete
    assert "await loadContacts();" in delete
    assert "api.softDeleteContactResult(contactId)" in delete
