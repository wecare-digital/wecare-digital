"""The WhatsApp-first identity link: one claim, and every unsafe case refused.

THE DEFECT. A customer whose whole relationship with us is WhatsApp already has a contact row —
`inbound-whatsapp-handler` created it the first time they messaged in, keyed `wa<digits>` on their
number. That row carries no `checkoutCustomerId`, because only the checkout path writes one. So
when the same person signed in to the website with a WhatsApp OTP, `_owned_contact` found nothing,
the save was treated as a first-time creation, and `_upsert_contact` answered
`409 CONTACT_IDENTITY_CONFLICT` on the phone row it could see but not adopt. The customer could
not check out, and no amount of re-trying helped.

WHAT MAKES THE LINK SAFE, and it is the whole subject of this file. The phone is **not
browser-supplied**: it comes from a Cognito session that only a WhatsApp OTP can mint. That alone
is not enough, so the claim additionally demands an unowned row, exactly one live row on that
number, a row that is not deleted, and evidence that the holder of the handset reached us
(`lastInboundMessageAt`, or a `VERIFIED`-trust phone provenance). Anything else is the existing
generic 409 plus a staff conflict record.

Most assertions below are on the **stored row** rather than on the status code, because the
failures that matter are invisible to a 200: a `checkoutCustomerId` that appeared on somebody
else's contact, an `emailVerifiedAt` that moved without a proof, a second row created beside the
one that should have been claimed. And every refusal asserts three things, not one — the 409, the
absence of a claim on the row, and the absence of the row's name, email and full phone from the
response body. A refusal that leaks the record it refused to link is a lookup service.
"""

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared')))
sys.path.insert(0, os.path.dirname(__file__))

from crm_fake_dynamo import FakeClientError, FakeDynamo  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HANDLER_PATH = ROOT / "amplify/functions/auth/customer-profile/handler.py"

OTP_TABLE = "stack-wecare-digital-DownloadGrantsTable"
CONTACTS_TABLE = "stack-wecare-digital-ContactsTable"

#: The Cognito `sub` is the customer id - see `customer_auth.customer_id_from_attributes`.
CUSTOMER = "11111111-2222-3333-4444-555555555555"
OTHER_CUSTOMER = "99999999-8888-7777-6666-555555555555"

#: Synthetic throughout. The contact id is the one the WhatsApp writers mint: `wa<digits>`.
PHONE = "+919000000000"
WA_CONTACT_ID = "wa919000000000"
OTHER_PHONE = "+919000000001"
EMAIL = "customer@example.com"
PEPPER = "identity-claim-test-pepper"

ADDRESS = {
    "addressLine1": "1 Example Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "postalCode": "560001",
}
ADDRESS_ATTRIBUTE = "checkoutDeliveryAddress"

INBOUND_AT = 1700000000


class Identity:
    """A proven customer session, with the Cognito flag the claim predicate reads."""

    def __init__(self, customer_id=CUSTOMER, phone=PHONE, phone_verified=True):
        self.customer_id = customer_id
        self.phone = phone
        self.subject = customer_id
        self.phone_verified = phone_verified


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("OTP_TABLE", OTP_TABLE)
    monkeypatch.setenv("CONTACTS_TABLE", CONTACTS_TABLE)
    monkeypatch.setenv("APP_ENV", "development")

    spec = importlib.util.spec_from_file_location("customer_profile_claim_matrix", HANDLER_PATH)
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)

    fake = FakeDynamo(
        keys={OTP_TABLE: "grantId", CONTACTS_TABLE: "id"},
        indexes={CONTACTS_TABLE: {
            "phone-index": ("phone", None),
            "email-index": ("email", None),
        }},
    )
    monkeypatch.setattr(h, "_dynamodb", fake)
    monkeypatch.setattr(h, "_pepper", lambda: PEPPER)
    # `lambda_utils.audit` holds its OWN boto3 resource, so an unpatched `record_audit` would
    # reach the live AuditLogsTable from a unit test. Every call is captured instead, which is
    # also what the "no PII in the audit record" tests assert against.
    audited = []
    monkeypatch.setattr(h, "record_audit",
                        lambda action, **kwargs: audited.append({"action": action, **kwargs}))
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (Identity(), None))
    return h, fake, monkeypatch, audited


def sign_in(h, monkeypatch, **kwargs):
    """Re-point the session at a different identity, e.g. one with an unverified phone."""
    monkeypatch.setattr(h.customer_auth, "require_customer",
                        lambda event: (Identity(**kwargs), None))


def event(**body):
    return {
        "requestContext": {"http": {"method": "POST", "sourceIp": "203.0.113.7"}},
        "headers": {"origin": "http://localhost:3000", "authorization": "Bearer test"},
        "body": json.dumps(body),
    }


def proof(h, fake, email=EMAIL):
    token = "proof-fixture"
    now = int(time.time())
    fake.Table(OTP_TABLE).put_item(Item={
        "grantId": h.PROOF_PREFIX + token,
        "purpose": h.PROOF_PURPOSE,
        "subjectDigest": h._proof_digest(email),
        "createdAt": now,
        "expiresAt": now + 600,
    })
    return token


def save(h, fake, **extra):
    """The one body a signing-in customer posts: name, email, a bound proof and an address."""
    return h.handler(event(firstName="Test", lastName="Customer", email=EMAIL,
                           emailProof=proof(h, fake), address=dict(ADDRESS), **extra), None)


def inbound_row(fake, **overrides):
    """A contact exactly as `inbound-whatsapp-handler` writes one.

    `lastInboundMessageAt` set, no `checkoutCustomerId`, and the `wa<digits>` id. Seeded the way
    the real WRITER writes it rather than the way a claim would like to find it, so the predicate
    is under test instead of assumed.
    """
    row = {
        "id": WA_CONTACT_ID, "contactId": WA_CONTACT_ID,
        "phone": PHONE, "name": "WhatsApp Lead", "firstName": "WhatsApp", "lastName": "Lead",
        "email": "lead@example.com",
        "lastInboundMessageAt": INBOUND_AT,
        "tags": ["Lead"],
        "createdAt": 1, "updatedAt": 1, "deletedAt": None,
    }
    row.update(overrides)
    fake.Table(CONTACTS_TABLE).put_item(
        Item={k: v for k, v in row.items() if v is not None or k == "deletedAt"})
    return row


def outbound_row(fake, **overrides):
    """A contact as STAFF outbound creates one: no `lastInboundMessageAt` at all.

    `outbound-whatsapp::_get_or_create_contact_by_phone` never sets it, and `core/contacts`
    writes it as `None` which is stripped before storage. So its absence is exactly "we messaged
    this number; it never messaged us", which is not evidence about who holds the handset.
    """
    return inbound_row(fake, lastInboundMessageAt=None, **overrides)


def rows_by_id(fake):
    return {row["id"]: row for row in fake.all_rows(CONTACTS_TABLE)}


def assert_refused(response, fake, row_id=WA_CONTACT_ID):
    """The three assertions every refusal owes, not just the status code.

    The third one is the one that is easy to forget: a refusal must not become a lookup service
    for the record it refused to link, so the body carries none of that row's identity.
    """
    assert response["statusCode"] == 409
    assert json.loads(response["body"])["error"] == "CONTACT_IDENTITY_CONFLICT"
    row = rows_by_id(fake)[row_id]
    assert "checkoutCustomerId" not in row, "a refused claim must not have written an owner"
    assert "identityClaimedAt" not in row
    for leaked in (row.get("name"), row.get("email"), row.get("phone")):
        if leaked:
            assert str(leaked) not in response["body"]


# ── the claim itself ──────────────────────────────────────────────────────────

def test_an_unowned_inbound_whatsapp_row_is_claimed_by_its_own_number(env):
    h, fake, _, _ = env
    inbound_row(fake)
    response = save(h, fake)
    assert response["statusCode"] == 200

    rows = fake.all_rows(CONTACTS_TABLE)
    assert len(rows) == 1, "the claim edits the existing row; it must not create a second one"
    row = rows[0]
    assert row["id"] == WA_CONTACT_ID, \
        "the claimed row keeps the id the WhatsApp writers minted, not a new deterministic one"
    assert row["checkoutCustomerId"] == CUSTOMER
    assert row["identityClaimedAt"]
    assert row["identityClaimEvidence"] == h.CLAIM_EVIDENCE_INBOUND
    # Moved because THIS request carried a proof bound to the submitted email, which is the only
    # thing that may stamp it. The claim itself writes four attributes and this is not one.
    assert row["emailVerifiedAt"]
    assert row["email"] == EMAIL
    assert row[ADDRESS_ATTRIBUTE]["city"] == "Bengaluru"


def test_the_claim_writes_the_owner_but_never_the_verification(env):
    h, fake, _, _ = env
    inbound_row(fake)
    claimed = h._attempt_claim(PHONE, Identity())
    assert claimed is not None
    row = rows_by_id(fake)[WA_CONTACT_ID]
    assert row["checkoutCustomerId"] == CUSTOMER
    # Claiming is not verifying. `checkout::_checkout_profile` still demands `emailVerifiedAt`,
    # so a claimed row with an unverified email cannot pay - which is the point.
    assert "emailVerifiedAt" not in row
    # And it writes nothing else: no name, no address, no tags, no public customer id.
    assert row["name"] == "WhatsApp Lead"
    assert row["tags"] == ["Lead"]
    assert ADDRESS_ATTRIBUTE not in row
    assert h.customer_uuid.ATTRIBUTE not in row


def test_a_verified_trust_phone_provenance_is_evidence_too(env):
    """The forward path, and the "completed a verified checkout" half of the predicate.

    Nothing on the WhatsApp path writes `fieldSources` yet - `core/crm` is the only writer - so
    this arm is dormant in production today. It is honoured now because a `PAYMENT_VERIFIED`
    phone provenance is evidence of exactly the same quality as an inbound message, and because
    the day the WhatsApp path starts stamping provenance the `lastInboundMessageAt` arm can
    retire without reopening this question.
    """
    h, fake, _, _ = env
    outbound_row(fake, **{h.provenance.PROVENANCE_ATTRIBUTE: {"phone": "PAYMENT_VERIFIED"}})
    response = save(h, fake)
    assert response["statusCode"] == 200
    row = rows_by_id(fake)[WA_CONTACT_ID]
    assert row["checkoutCustomerId"] == CUSTOMER
    assert row["identityClaimEvidence"] == "PAYMENT_VERIFIED"


def test_an_operator_trust_provenance_is_not_evidence(env):
    """`DASHBOARD` is a human on our side typing a number. It proves nothing about the handset."""
    h, fake, _, _ = env
    outbound_row(fake, **{h.provenance.PROVENANCE_ATTRIBUTE: {"phone": "DASHBOARD"}})
    assert_refused(save(h, fake), fake)


# ── the refusals, one per unsafe state ───────────────────────────────────────

def test_a_row_owned_by_another_customer_is_never_claimed(env):
    """THE security boundary. A verified phone is not a key to somebody else's contact."""
    h, fake, _, _ = env
    inbound_row(fake, checkoutCustomerId=OTHER_CUSTOMER)
    response = save(h, fake)
    assert response["statusCode"] == 409
    row = rows_by_id(fake)[WA_CONTACT_ID]
    assert row["checkoutCustomerId"] == OTHER_CUSTOMER, "the other owner must survive untouched"
    assert "identityClaimedAt" not in row
    for leaked in (row["name"], row["email"], row["phone"]):
        assert leaked not in response["body"]


def test_two_live_rows_on_one_number_are_ambiguous_and_refused(env):
    """One number held by two records is a question only a human can answer. Guessing here
    would attach a customer to the wrong person's history."""
    h, fake, _, _ = env
    inbound_row(fake)
    inbound_row(fake, id="wa919000000000-duplicate", contactId="wa919000000000-duplicate")
    response = save(h, fake)
    assert_refused(response, fake)
    assert_refused(response, fake, row_id="wa919000000000-duplicate")


def test_a_staff_or_outbound_only_row_has_no_inbound_evidence_and_is_refused(env):
    h, fake, _, _ = env
    outbound_row(fake)
    assert_refused(save(h, fake), fake)


def test_an_unverified_session_phone_claims_nothing(env):
    """Fail-closed. `CustomerIdentity.phone_verified` defaults to False, so a construction site
    that has not proven the Cognito flag cannot assert it by omission."""
    h, fake, monkeypatch, _ = env
    inbound_row(fake)
    sign_in(h, monkeypatch, phone_verified=False)
    assert_refused(save(h, fake), fake)


def test_a_deleted_row_is_not_claimed_and_is_not_resurrected(env):
    h, fake, _, _ = env
    inbound_row(fake, deletedAt=1699999999)
    response = save(h, fake)
    # A tombstone is invisible to every reader here, so the save creates a fresh row rather than
    # refusing - but the deleted row must not gain an owner, and the new row must not be it.
    assert response["statusCode"] == 200
    tombstone = rows_by_id(fake)[WA_CONTACT_ID]
    assert "checkoutCustomerId" not in tombstone
    assert "identityClaimedAt" not in tombstone
    assert json.loads(response["body"])["contactId"] != WA_CONTACT_ID


def test_an_archived_row_is_refused_by_the_isDeleted_flag_too(env):
    """Two spellings of deleted exist and both are honoured: `deletedAt` is the CRM's soft
    delete, `isDeleted` is the archive flag the WhatsApp flows check."""
    h, fake, _, _ = env
    inbound_row(fake, isDeleted=True)
    _, reason = h._claim_candidate(
        [rows_by_id(fake)[WA_CONTACT_ID]], PHONE, True)
    assert reason == "DELETED_CONTACT"
    assert h._attempt_claim(PHONE, Identity()) is None
    assert "checkoutCustomerId" not in rows_by_id(fake)[WA_CONTACT_ID]


def test_an_email_match_alone_never_produces_a_claim(env):
    """No email-only claim, stated where it would otherwise sneak in.

    The inbound row here is on a DIFFERENT number and carries the submitted email, so the email
    index resolves it while the phone index resolves nothing. That is the shape an email-only
    claim would take, and the answer is the existing 409.
    """
    h, fake, _, _ = env
    inbound_row(fake, phone=OTHER_PHONE, email=EMAIL)
    response = save(h, fake)
    assert response["statusCode"] == 409
    row = rows_by_id(fake)[WA_CONTACT_ID]
    assert "checkoutCustomerId" not in row
    assert "identityClaimedAt" not in row


def test_the_predicate_reads_the_exact_phone_string_and_not_a_prefix(env):
    """`phone-index` is queried on the normalised E.164 string, so a row on a different number
    that merely shares a prefix is not a candidate."""
    h, fake, _, _ = env
    inbound_row(fake, phone=PHONE + "9")
    candidate, reason = h._claim_candidate(fake.all_rows(CONTACTS_TABLE), PHONE, True)
    assert (candidate, reason) == (None, "")


# ── the race, and the replay ─────────────────────────────────────────────────

class RacingContacts:
    """The fake table, except the first `update_item` loses a race it could not have seen.

    The concurrent winner's claim is applied to the row BEFORE this call raises, because that is
    the causal order in production: our conditional write fails *precisely* because somebody else
    already stamped `checkoutCustomerId`. Raising without applying the winner's write would
    assert against a state DynamoDB cannot produce, and the re-read under test would have nothing
    to find.
    """

    def __init__(self, inner, winner, claimed_at):
        self._inner = inner
        self._winner = winner
        self._claimed_at = claimed_at
        self.armed = True

    def update_item(self, **kwargs):
        if self.armed:
            self.armed = False
            row = self._inner.rows[kwargs["Key"]["id"]]
            row["checkoutCustomerId"] = self._winner
            row["identityClaimedAt"] = self._claimed_at
            row["identityClaimEvidence"] = "WHATSAPP_INBOUND"
            raise FakeClientError("ConditionalCheckFailedException")
        return self._inner.update_item(**kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def arm_race(fake, monkeypatch, *, winner, claimed_at):
    """Make the next contacts `update_item` lose to `winner`, once."""
    real_table = fake.Table
    proxy = {}

    def Table(name):  # noqa: N802 - boto3's spelling
        inner = real_table(name)
        if name != CONTACTS_TABLE:
            return inner
        if "it" not in proxy:
            proxy["it"] = RacingContacts(inner, winner, claimed_at)
        # `FakeTable` is a thin view over the parent's rows, so re-pointing keeps the proxy's
        # own `armed` state across the several `_table()` calls one request makes.
        proxy["it"]._inner = inner
        return proxy["it"]

    monkeypatch.setattr(fake, "Table", Table)
    return proxy


def test_a_concurrent_double_claim_has_exactly_one_winner(env):
    """Two requests from the SAME customer, and the loser must not undo the winner.

    The conditional write is what decides it; the re-read is what makes the loser idempotent
    rather than an error. `identityClaimedAt` is the assertion that matters: re-stamping it would
    falsify when the link actually happened.
    """
    h, fake, monkeypatch, _ = env
    inbound_row(fake)
    arm_race(fake, monkeypatch, winner=CUSTOMER, claimed_at=1700000001)

    response = save(h, fake)
    assert response["statusCode"] == 200, "the loser of the race is still a successful save"
    rows = fake.all_rows(CONTACTS_TABLE)
    assert len(rows) == 1
    row = rows[0]
    assert row["checkoutCustomerId"] == CUSTOMER
    assert row["identityClaimedAt"] == 1700000001, \
        "the loser must not re-stamp the moment the winner recorded"


def test_a_race_lost_to_a_DIFFERENT_customer_is_refused(env):
    """The same race, with somebody else winning. The condition is the only thing standing
    between two sessions on one row, so the loser must take the refusal path."""
    h, fake, monkeypatch, _ = env
    inbound_row(fake)
    arm_race(fake, monkeypatch, winner=OTHER_CUSTOMER, claimed_at=1700000001)

    response = save(h, fake)
    assert response["statusCode"] == 409
    row = rows_by_id(fake)[WA_CONTACT_ID]
    assert row["checkoutCustomerId"] == OTHER_CUSTOMER
    assert row["identityClaimedAt"] == 1700000001


def test_a_replayed_save_is_a_plain_owned_row_edit_and_never_re_enters_the_claim(env):
    """Idempotency needs no extra store, and this is why: the second save finds the row already
    owned, so `_owned_contact` returns it and the claim path is not reached at all."""
    h, fake, monkeypatch, _ = env
    inbound_row(fake)
    first = save(h, fake)
    assert first["statusCode"] == 200
    claimed_at = rows_by_id(fake)[WA_CONTACT_ID]["identityClaimedAt"]

    attempts = []
    monkeypatch.setattr(h, "_attempt_claim", lambda *args, **kwargs: attempts.append(1))
    second = h.handler(event(address=dict(ADDRESS, city="Kolkata", state="West Bengal",
                                          postalCode="700016")), None)
    assert second["statusCode"] == 200
    assert attempts == [], "an owned row must not go near the claim path"
    row = rows_by_id(fake)[WA_CONTACT_ID]
    assert row["identityClaimedAt"] == claimed_at
    assert row[ADDRESS_ATTRIBUTE]["city"] == "Kolkata"


# ── what a refusal leaves behind for staff ───────────────────────────────────

def test_a_refusal_marks_the_row_for_staff_reconciliation(env):
    """D6: the conflict record IS the staff surface, and it needs no frontend change.

    `/workspace/contacts` renders arbitrary tags as chips and already searches them, so the
    literal tag is both the badge and the filter. The reason is a CODE and never a value,
    because this row is read by staff and the HTTP answer deliberately says nothing.
    """
    h, fake, _, _ = env
    outbound_row(fake, tags=["Lead", "VIP"])
    assert_refused(save(h, fake), fake)
    row = rows_by_id(fake)[WA_CONTACT_ID]
    assert row["identityConflictAt"]
    assert row["identityConflictReason"] == "NO_INBOUND_EVIDENCE"
    assert row["tags"] == ["Lead", "VIP", h.CONFLICT_TAG]
    # The marker names no value: not the phone, not the email, not the customer id.
    rendered = json.dumps(row["identityConflictReason"])
    for value in (PHONE, EMAIL, CUSTOMER, row["email"]):
        assert value not in rendered


def test_a_second_refusal_does_not_duplicate_the_conflict_tag(env):
    h, fake, _, _ = env
    outbound_row(fake)
    assert_refused(save(h, fake), fake)
    assert_refused(save(h, fake), fake)
    assert rows_by_id(fake)[WA_CONTACT_ID]["tags"].count(h.CONFLICT_TAG) == 1


def test_a_foreign_owned_refusal_is_recorded_without_touching_the_owner(env):
    h, fake, _, _ = env
    inbound_row(fake, checkoutCustomerId=OTHER_CUSTOMER)
    assert save(h, fake)["statusCode"] == 409
    row = rows_by_id(fake)[WA_CONTACT_ID]
    assert row["identityConflictReason"] == "FOREIGN_OWNER"
    assert row["checkoutCustomerId"] == OTHER_CUSTOMER


def test_a_failed_marker_write_still_produces_the_refusal(env):
    """The marker is a convenience for staff; the 409 is the security answer. If the write fails
    the answer must not change, or a throttled table turns a refusal into a 500 - or worse, into
    a save."""
    h, fake, _, _ = env
    outbound_row(fake)
    fake.arm_failure(CONTACTS_TABLE, "update_item",
                     FakeClientError("ProvisionedThroughputExceededException"))
    assert_refused(save(h, fake), fake)
    assert "identityConflictAt" not in rows_by_id(fake)[WA_CONTACT_ID]


# ── the audit record ─────────────────────────────────────────────────────────

def test_a_successful_claim_writes_one_audit_record_with_no_pii(env):
    h, fake, _, audited = env
    inbound_row(fake)
    assert save(h, fake)["statusCode"] == 200
    claims = [entry for entry in audited if entry["action"] == "identity.claim"]
    assert len(claims) == 1
    entry = claims[0]
    assert entry["actor"] == CUSTOMER
    assert entry["resource_type"] == "contact"
    assert entry["resource_id"] == WA_CONTACT_ID
    assert entry["details"]["evidence"] == h.CLAIM_EVIDENCE_INBOUND
    assert entry["details"]["phoneLast4"] == PHONE[-4:]
    rendered = json.dumps(entry)
    assert PHONE not in rendered, "a last-4 tail, never the number"
    for value in (EMAIL, "lead@example.com", "WhatsApp Lead"):
        assert value not in rendered


def test_a_refusal_writes_one_audit_record_naming_the_reason(env):
    h, fake, _, audited = env
    inbound_row(fake, checkoutCustomerId=OTHER_CUSTOMER)
    assert save(h, fake)["statusCode"] == 409
    refusals = [entry for entry in audited if entry["action"] == "identity.claim_refused"]
    assert len(refusals) == 1
    entry = refusals[0]
    assert entry["details"]["reason"] == "FOREIGN_OWNER"
    assert entry["details"]["ownedByOther"] is True
    assert entry["details"]["phoneLast4"] == PHONE[-4:]
    rendered = json.dumps(entry)
    assert PHONE not in rendered
    assert EMAIL not in rendered
    assert OTHER_CUSTOMER not in rendered, "the other owner's id is not ours to log here"


def test_both_audit_actions_are_declared_as_canonical():
    """`ACTIONS` is the declared set, and `tests/test_audit_sink.py` writes every member of it.
    An action missing from there is a record nobody reviews."""
    from lambda_utils import audit
    assert {"identity.claim", "identity.claim_refused"} <= audit.ACTIONS


def test_an_audit_failure_cannot_change_the_outcome(env):
    """`record_audit` already fails open; this asserts the handler does not depend on that.

    A sink that raised would otherwise turn a successful claim into a 500 after the row was
    already linked, which is the worst of both answers.
    """
    h, fake, monkeypatch, _ = env
    inbound_row(fake)

    def boom(*args, **kwargs):
        raise RuntimeError("audit sink unavailable")

    monkeypatch.setattr(h, "record_audit", boom)
    assert save(h, fake)["statusCode"] == 200
    assert rows_by_id(fake)[WA_CONTACT_ID]["checkoutCustomerId"] == CUSTOMER
