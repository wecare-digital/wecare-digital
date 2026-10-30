"""Regression pins for resolving duplicate Customers into the canonical stored row.

These are source-contract tests because the Contacts Lambda has a wide import graph and the
failure here crossed three layers: the Lambda 409 payload, the shared API client, and the
Customers modal. Keeping the assertions together prevents a future cleanup in one layer from
silently restoring the generic-error dead end.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_duplicate_409_names_canonical_owner_without_duplicate_pii():
    source = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()

    helper = source[
        source.index("def _duplicate_owner_row"):
        source.index("def _check_duplicate")
    ]
    assert "identity_claims.owner" in helper
    assert "ConsistentRead=True" in helper
    assert "'existingContactId'" in helper
    assert "'existingArchived'" in helper
    assert "'errorCode': 'CONTACT_ALREADY_EXISTS'" in helper
    assert "existing.get(ARCHIVED_AT_ATTRIBUTE) is not None" in helper

    create = source[source.index("def _create"):source.index("# ─── READ ONE")]
    assert "_duplicate_conflict_payload(phone, email, dup)" in create
    assert "_duplicate_conflict_payload(" in create
    assert "identity_claims.IdentityClaimConflict" in create

    # The wire refusal stays PII-safe: the UI retrieves the authenticated row by id instead.
    payload = helper[helper.index("def _duplicate_conflict_payload"):]
    assert "existing.get('name')" not in payload
    assert "existing.get('phone')" not in payload
    assert "existing.get('email')" not in payload


def test_archived_customer_stays_hidden_from_normal_queue_but_resolvable_on_conflict():
    source = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()

    active_filter = source[
        source.index("def _active_contact_filter"):
        source.index("# ─── COUNT")
    ]
    assert "ARCHIVED_AT_ATTRIBUTE" in active_filter
    assert "_identity_contact_filter()" in active_filter

    owner = source[
        source.index("def _duplicate_owner_row"):
        source.index("def _duplicate_conflict_payload")
    ]
    # The conflict resolver intentionally uses the broader identity filter, not the daily queue
    # filter, so an archived row can be found without making archived customers searchable.
    assert "_identity_contact_filter()" in owner
    assert "_active_contact_filter()" not in owner


def test_api_client_preserves_structured_refusal_metadata_for_customer_resolution():
    source = (ROOT / "src/api/client.ts").read_text()

    assert "details?: Record<string, unknown>" in source
    assert "let errorBody: Record<string, unknown> | null = null" in source
    assert "const refusalCode = errorBody?.errorCode ?? errorBody?.code" in source
    assert "errorBody || undefined" in source


def test_customers_modal_fetches_exact_duplicate_and_restores_archived_before_payment():
    source = (ROOT / "src/pages/workspace/customers/index.tsx").read_text()

    assert "result.failure.details?.existingContactId" in source
    assert "api.getContact(existingId)" in source
    assert "existing.archivedAt" in source
    assert "Existing archived customer" in source
    assert "Restore customer" in source
    assert "api.restoreContact(contactId)" in source
    assert "if (!duplicateContact || duplicateContact.archivedAt) return;" in source


def test_customer_modal_distinguishes_existing_customer_from_orphaned_identity_claim():
    page = (ROOT / "src/pages/workspace/customers/index.tsx").read_text()
    backend = (ROOT / "amplify/functions/core/contacts/handler.py").read_text()

    assert "CONTACT_IDENTITY_RECONCILIATION_REQUIRED" in backend
    assert "result.failure.code === 'CONTACT_IDENTITY_RECONCILIATION_REQUIRED'" in page
    assert "result.failure.details?.reconciliationRequired === true" in page
    assert "Identity needs reconciliation" in page
    assert "No duplicate customer was created." in page

    # A normal duplicate remains actionable rather than surfacing a raw HTTP status.
    assert "This WhatsApp number already belongs to an existing customer. Search by number to open it." in page
    assert "Search customer" in page
    assert "searchExistingCustomer" in page
    assert ".replace(/^HTTP\\s+\\d+:\\s*/i, '')" in page


def test_customer_create_modal_uses_workspace_card_layout():
    page = (ROOT / "src/pages/workspace/customers/index.tsx").read_text()
    css = (ROOT / "src/styles/workspace.css").read_text()

    assert "contacts-workspace-form-v2" in page
    assert "contacts-form-section" in page
    assert "Workspace · Customers" in page
    assert "Customer identity" in page
    assert "Work details" in page
    assert "contacts-address-preview" in page

    assert "Customers — Workspace-native create/edit surface." in css
    assert ".contacts-workspace-form-v2 .contacts-form-section" in css
    assert "border-radius: 16px" in css
    assert ".contacts-reconciliation-card" in css
