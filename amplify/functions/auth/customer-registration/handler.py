"""The customer registration front door: prove a phone by WhatsApp OTP, then provision a login.

This is the wiring, not the mechanism
-------------------------------------
Every hard part already exists as a tested, storage-agnostic, AWS-free module, and this handler
composes them rather than reimplementing any of them:

- `lambda_utils.identity.registration` — the ordered flow: normalise -> throttle -> issue -> send
  (`begin`), then verify -> resolve/create customer -> provision login (`complete`). It performs no
  AWS call itself; every side effect is injected from here, which is what makes it testable.
- `lambda_utils.otp_throttle`   — per-IP and per-phone limits, fail-closed. The IP axis is the whole
  reason this route exists: a Cognito `CUSTOM_AUTH` trigger receives no client IP, so per-IP
  limiting is structurally impossible there. Here `requestContext.http.sourceIp` exists and cannot
  be spoofed.
- `lambda_utils.otp_challenge`  — the code itself: HMAC-with-pepper at rest, TTL, attempt cap,
  resend cooldown and window, single-use conditional consume.
- `lambda_utils.identity.customer` — `normalize_phone`, `new_customer_id`, `build_customer`.

Two endpoints, and the security properties that shape them
----------------------------------------------------------
`request`  normalise -> throttle -> issue -> send, in that order. The throttle runs BEFORE the code
           is issued and sent, so a refused request never spends a billable WhatsApp message. The
           code is generated inside `otp_challenge.issue`, handed straight to the sender, and never
           logged, echoed, or stored in plaintext.
`verify`   check the code and, on success, resolve or create the customer's ONE ContactsTable row
           (the same row the WhatsApp inbox and checkout use) and administratively provision the
           Cognito login. It stamps no customer id on the Cognito
           user — that attribute is not in the pool's schema; see `_provision_login`. The browser
           then signs in with the existing WhatsApp-OTP `CUSTOM_AUTH` flow — which now works because
           the user exists as CONFIRMED. This handler never returns the customer id or a token: the
           session credential comes from the Cognito sign-in, not from here.

**No enumeration, on either endpoint.** `request` answers identically whether or not the number is
already a customer — there is no "already registered" branch, because that branch is an oracle.
`verify` collapses wrong / expired / used / never-issued into one opaque outcome. See
`RegistrationResult.public_body()`; the real reason stays server-side for logs and metrics.

**The browser never creates a Cognito user.** The customer pool is `AllowAdminCreateUserOnly = true`
by deliberate architecture. Provisioning happens here, on the backend, only after the OTP proves the
caller holds the number. Nothing in this handler calls `SignUp`.

Nothing plaintext is logged
---------------------------
Not the OTP, not the full phone number, not a customer id, not an exception message that could echo
either. Every log line carries an event name, an outcome and counts. Exception handlers log
`type(exc)` only.

Why this is a standalone function, not a branch of customer-whatsapp-auth
-------------------------------------------------------------------------
`customer-whatsapp-auth` is a Cognito `CUSTOM_AUTH` trigger: it has no HTTP surface, no client IP,
and no durable OTP store of its own. This is the opposite — an HTTP door that sees the IP, owns the
throttle, and provisions the very user the trigger later authenticates. Folding one into the other
would mean a single function with two invocation models and two trust boundaries.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import contact_key, contact_store, customer_auth, customer_session, otp_throttle, shared_tables, identity_claims
from lambda_utils.identity import customer as identity
from lambda_utils.identity import registration
from lambda_utils.identity import consent as consent_evidence
from lambda_utils.identity import provenance
from lambda_utils.identity import subscriber_id
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response

logger = get_logger(__name__)


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    """Every response from this door is uncacheable. Applied at the return, not at the builder.

    `response.py::cors_headers` sets no `Cache-Control`, and these responses travel through the
    Amplify `/api/<*>` status-200 rewrite, so a shared cache sits in front of them. A cached OTP
    outcome replayed to a different caller is both an answer about someone else's number and, on the
    verify path, an answer about someone else's session state. `response.py` is deliberately left
    alone - `core/contacts/handler.py:285` removed `Cache-Control` there on purpose - so the
    contract is applied here, by the handler that owns these responses.
    """
    hardened = dict(response)
    hardened["headers"] = customer_session.harden_session_headers(response.get("headers") or {})
    return hardened

# ── configuration ────────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_REGION", "us-east-1")

#: The short-lived challenge + throttle store. `DownloadGrantsTable` (key `grantId`, TTL on
#: `expiresAt`) is the established precedent shared by the WhatsApp-auth probe counter and the
#: email-verification door; both OTP modules default to a `grantId` key.
OTP_TABLE = os.environ.get("OTP_TABLE", "stack-wecare-digital-DownloadGrantsTable")

#: The one person store. A phone verified here resolves to - or creates - the SAME ContactsTable
#: row the WhatsApp inbox, WhatsApp Flows, catalog orders and website checkout use. (This used
#: to target a separate `CustomersTable` of `CUS_<ULID>` records, which never existed in the
#: account and would have been a second identity for every customer.)
CONTACTS_TABLE = shared_tables.contacts_table_name()

#: Signed Meta inbound evidence used by the internal WhatsApp identity bridge.  The bridge never
#: trusts a caller-supplied phone/contact tuple alone; it requires the exact persisted WAMID.
WHATSAPP_INBOUND_TABLE = os.environ.get(
    "WHATSAPP_INBOUND_TABLE", "stack-wecare-digital-WhatsAppInboundTable")
WHATSAPP_INBOUND_MESSAGE_INDEX = "whatsappMessageId-index"
WHATSAPP_IDENTITY_MAX_AGE_SECONDS = 10 * 60

#: The customer Cognito pool. Deliberately NOT the staff pool — the customer_auth helper pins the
#: issuer to this one, and mixing them is the failure that helper exists to prevent.
CUSTOMER_POOL_ID = os.environ.get("CUSTOMER_POOL_ID", "us-east-1_46ULYuukt")

#: The WABA the OTP trigger is bound to. Stamped on the provisioned user as
#: `custom:partner_waba_id`, because the trigger raises `PermissionError` if it does not match —
#: an unstamped user could never receive a code.
META_WABA_ID = os.environ.get("META_WABA_ID", "2094615664435155")
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "1016149501586345")

#: The internal Meta-template sender. Same function and template the CUSTOM_AUTH trigger uses, so
#: the registration OTP and the sign-in OTP are delivered by one path.
SENDER_FUNCTION = os.environ.get("SENDER_FUNCTION", "wecare-whatsapp-business-api:live")
OTP_TEMPLATE_NAME = os.environ.get("OTP_TEMPLATE_NAME", "wecare_otp")
OTP_TEMPLATE_LANGUAGE = os.environ.get("OTP_TEMPLATE_LANGUAGE", "en")

#: Read by reference, lazily, never printed. `block-inline-secrets` allows a `SecretId='wecare/...'`
#: name; this is a name, not a value.
OTP_PEPPER_SECRET_ID = os.environ.get("OTP_PEPPER_SECRET_ID", "wecare/otp/pepper")

#: The provenance a phone proven by this door's WhatsApp OTP is recorded under. An existing
#: VERIFIED source, so a `customer-profile` deployed with an older `lambda_utils` already honours it.
OTP_PHONE_SOURCE = "PAYMENT_VERIFIED"

_dynamodb = None
_lambda = None
_secrets = None
_pepper_cache: Dict[str, str] = {}


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(OTP_TABLE)


def _contacts_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(CONTACTS_TABLE)


def _inbound_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(WHATSAPP_INBOUND_TABLE)

def _claims_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(identity_claims.TABLE_NAME)


def _lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=REGION)
    return _lambda


def _cognito_client():
    return boto3.client("cognito-idp", region_name=REGION)


def _pepper() -> str:
    """Resolve the OTP pepper from Secrets Manager, lazily, cached per environment.

    Read lazily rather than at import scope on purpose: a module-scope read is cached for the life
    of a warm sandbox, so a rotation would keep validating against the old pepper until every
    sandbox recycled. Rotating the pepper invalidates every outstanding code, which is the correct
    blast radius — a customer simply requests another.
    """
    global _secrets
    if "pepper" in _pepper_cache:
        return _pepper_cache["pepper"]
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=REGION)
    raw = _secrets.get_secret_value(SecretId=OTP_PEPPER_SECRET_ID).get("SecretString", "") or ""
    value = ""
    try:
        data = json.loads(raw)
        value = (data.get("pepper") or data.get("value") or "").strip()
    except (ValueError, TypeError):
        value = raw.strip()
    if not value:
        raise RuntimeError("OTP pepper is not configured")
    _pepper_cache["pepper"] = value
    return value


# ── injected side effects ──────────────────────────────────────────────────────

def _send_code(e164: str, code: str) -> None:
    """Deliver the OTP over WhatsApp via the existing Meta-template sender.

    Mirrors `customer-whatsapp-auth._send_otp` exactly: the `wecare_otp` AUTHENTICATION template
    with a `url` button (NOT `copy_code`), because Meta materialises the copy-code affordance of an
    AUTHENTICATION template as a real URL button and rejects `copy_code` outright. Verified against
    the live WABA on 2026-09-25.

    Never logs the code or the full number.
    """
    body = {
        "to": _wa_destination(e164),
        "phoneId": META_PHONE_NUMBER_ID,
        "templateName": OTP_TEMPLATE_NAME,
        "language": OTP_TEMPLATE_LANGUAGE,
        "components": [
            {"type": "body", "parameters": [{"type": "text", "text": code}]},
            {"type": "button", "sub_type": "url", "index": "0",
             "parameters": [{"type": "text", "text": code}]},
        ],
    }
    invoke_event = {
        "httpMethod": "POST",
        "path": "/wa-business/messages/send/template",
        "body": json.dumps(body),
    }
    response = _lambda_client().invoke(
        FunctionName=SENDER_FUNCTION,
        InvocationType="RequestResponse",
        Payload=json.dumps(invoke_event).encode("utf-8"),
    )
    raw = response["Payload"].read()
    result = json.loads(raw.decode("utf-8")) if raw else {}
    if response.get("FunctionError"):
        raise RuntimeError("internal WhatsApp sender Lambda failed")
    status = int(result.get("statusCode") or 500)
    if status >= 300:
        raise RuntimeError(f"internal WhatsApp sender returned HTTP {status}")


def _wa_destination(e164: str) -> str:
    """WhatsApp's digits-only destination for an E.164 number."""
    return "".join(ch for ch in str(e164 or "") if ch.isdigit())


def _as_customer(row: Dict[str, Any]) -> Dict[str, Any]:
    """A contact row in the registration contract: `customerId` is the contact's id."""
    return {**row, "customerId": contact_key.resolve(row)}


def _resolve_customer(e164: str) -> Optional[Dict[str, Any]]:
    """The existing contact for this phone, or None - whichever channel created it.

    `contact_store.lookup` tries the deterministic `wa{digits}` key the inbox writes, then every
    stored spelling on `phone-index`, so a customer who first messaged on WhatsApp or was entered
    by staff is found rather than duplicated. A transient read error returns None; the conditional
    create below is what actually guarantees one contact per phone.
    """
    try:
        row = contact_store.lookup(_contacts_table(), e164)
    except contact_store.IdentityConflict:
        # A strong identity claimed by multiple live contacts must never be treated as a miss:
        # doing so would create a third deterministic contact and make the split worse.
        raise
    except Exception as error:  # noqa: BLE001
        logger.info(json.dumps({"event": "customer_lookup_miss",
                                 "error": type(error).__name__}))
        return None
    return _as_customer(row) if row else None


def _create_customer(e164: str) -> Dict[str, Any]:
    """Create the contact for a verified phone, at most once per phone.

    The id is the same deterministic `wa{digits}` the WhatsApp inbox mints, so when this customer
    later messages on WhatsApp the inbox lands on THIS row instead of creating a second one. The
    write is conditional on the id, so a race between two verifications collapses to one contact.
    Purchase/transactional identity is not marketing consent, so every opt-in starts False, as on
    the website profile path. Names arrive later through the checkout profile.

    The phone carries `PAYMENT_VERIFIED` provenance ("an OTP or payment we verified end to end"),
    because the WhatsApp OTP this row is created behind proves who holds the handset. That is the
    evidence `customer-profile` requires before it links a Cognito sub to a row. Without it, the
    customer this door just created could never save a checkout profile: the claim refused with
    NO_INBOUND_EVIDENCE and the save ended in 409. Only rows created HERE get the stamp. A row
    adopted below (one that already existed for this phone) keeps whatever evidence it had, so a
    staff-typed record is never handed to the session by this door.
    """
    now = int(time.time())
    contact_id = contact_store.deterministic_id(e164)
    if not contact_id:
        raise ValueError("a verified phone is required to create a contact")
    record = {
        **contact_key.contact_item_keys(contact_id),
        **subscriber_id.new_contact_fields(now=now),
        "phone": contact_store.canonical_phone(e164),
        "phoneVerifiedAt": now,
        provenance.PROVENANCE_ATTRIBUTE: {"phone": OTP_PHONE_SOURCE},
        "optInWhatsApp": False,
        "optInEmail": False,
        "optInSms": False,
        "allowlistWhatsApp": False,
        "allowlistEmail": False,
        "allowlistSms": False,
        # Existing Contacts workspace search already indexes tags, so a newly-created website
        # registration is visible to staff without a second customer store or any PII-derived flag.
        "tags": ["website-signup"],
        "createdAt": now,
        "updatedAt": now,
    }
    try:
        identity_claims.claim_identities(
            _claims_table(), contact_id=contact_id,
            phone=record["phone"], now=now)
    except identity_claims.IdentityClaimConflict:
        owner_id = identity_claims.owner(_claims_table(), "PHONE", record["phone"])
        owner = contact_store.lookup(_contacts_table(), contact_id=owner_id) if owner_id else None
        if owner:
            return _as_customer(owner)
        raise
    try:
        _contacts_table().put_item(
            Item=record,
            ConditionExpression="attribute_not_exists(id)",
        )
    except Exception as error:  # noqa: BLE001
        # A losing race means another verification created the contact first. Re-resolve and
        # adopt it rather than raising, so two concurrent verifications converge on one record.
        if _is_conditional_failure(error):
            existing = _resolve_customer(e164)
            if existing and existing.get("customerId"):
                return existing
        raise
    logger.info(json.dumps({"event": "customer_created"}))
    return _as_customer(record)


def _provision_login(e164: str, customer_id: str) -> None:  # noqa: ARG001 - see below
    """Administratively create or update the phone-keyed Cognito user. Idempotent.

    `customer_id` is accepted and deliberately unused. It is part of the `provision_login`
    contract `identity.registration.verify_and_register` injects and calls positionally, so the
    parameter stays; what changed is that there is no longer a Cognito attribute to put it in.

    Mirrors `secure-files._ensure_customer_user`:
    - `MessageAction=SUPPRESS` so Cognito sends no invite (these users have no email and the channel
      is WhatsApp).
    - a permanent random password so the user is CONFIRMED rather than FORCE_CHANGE_PASSWORD, which
      would block CUSTOM_AUTH. Nobody learns it; the only way in is a WhatsApp OTP. Never logged.
    - `custom:partner_waba_id` so the OTP trigger, which fails closed on a WABA mismatch, will issue
      codes for this user.

    IT DOES NOT STAMP `custom:customer_id`, AND IT CANNOT. That attribute is not in pool
    `us-east-1_46ULYuukt`'s schema (measured 2026-10-02: the only custom attribute is
    `custom:partner_waba_id`), so sending it here would have Cognito reject the whole
    `AdminCreateUser` call with `InvalidParameterException`. It was never reached in production,
    because when it was removed this function had no deployed Lambda and no API route, so the
    removal pinned the real contract rather than changing behaviour.

    Session identity now comes from `customer_auth.customer_id_from_attributes`, which derives it
    from the Cognito `sub` - so the login this provisions and the session `customer_auth` proves
    cannot disagree, because neither of them stores a customer id on the user any more. The
    customer RECORD is the ContactsTable row; the website links it to the Cognito `sub` through
    `checkoutCustomerId` when the profile is saved (auth/customer-profile).
    """
    import secrets as pysecrets

    client = _cognito_client()
    attrs = [
        {"Name": "phone_number", "Value": e164},
        {"Name": "phone_number_verified", "Value": "true"},
        {"Name": "custom:partner_waba_id", "Value": META_WABA_ID},
    ]
    try:
        created = client.admin_create_user(
            UserPoolId=CUSTOMER_POOL_ID,
            Username=e164,
            UserAttributes=attrs,
            MessageAction="SUPPRESS",
        )
        username = created["User"]["Username"]
        client.admin_set_user_password(
            UserPoolId=CUSTOMER_POOL_ID,
            Username=username,
            Password=pysecrets.token_urlsafe(24) + "aA1!",
            Permanent=True,
        )
    except client.exceptions.UsernameExistsException:
        client.admin_update_user_attributes(
            UserPoolId=CUSTOMER_POOL_ID, Username=e164, UserAttributes=attrs
        )


def _is_conditional_failure(error: Exception) -> bool:
    response = getattr(error, "response", None) or {}
    return response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"



def _whatsapp_identity_evidence(
    contact: Dict[str, Any], phone: str, source_message_id: str, waba_id: str
) -> bool:
    """Prove this bridge request came from the exact signed Meta inbound message.

    Three independent facts must agree:
      * ContactsTable has exactly ONE live row for the phone and it is this contact;
      * that row's latest inbound WAMID is the capability presented by the caller;
      * WhatsAppInboundTable independently contains the same WAMID/contact/phone/WABA tuple.

    The WAMID is high-entropy, persisted only after signed webhook ingress, and limited to a short
    freshness window.  Knowing a contact id and phone is therefore insufficient to provision.
    """
    if not contact or contact.get("deletedAt") is not None or bool(contact.get("isDeleted")):
        return False
    if contact_store.canonical_phone(contact.get("phone")) != phone:
        return False
    if not source_message_id or str(contact.get("lastInboundWamid") or "") != source_message_id:
        return False
    try:
        last_at = int(contact.get("lastInboundMessageAt") or 0)
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    if last_at <= 0 or now - last_at > WHATSAPP_IDENTITY_MAX_AGE_SECONDS:
        return False

    try:
        page = _inbound_table().query(
            IndexName=WHATSAPP_INBOUND_MESSAGE_INDEX,
            KeyConditionExpression=Key("whatsappMessageId").eq(source_message_id),
            Limit=2,
        )
    except Exception as error:  # noqa: BLE001
        logger.warning(json.dumps({
            "event": "whatsapp_identity_evidence_lookup_failed",
            "error": type(error).__name__,
        }))
        return False

    matches = []
    for row in page.get("Items") or []:
        row_wabas = [str(v) for v in (row.get("metaWabaIds") or [])]
        if (str(row.get("contactId") or "") == contact_key.resolve(contact)
                and contact_store.canonical_phone(row.get("senderPhone")) == phone
                and str(row.get("status") or "") == "received"
                and waba_id in row_wabas):
            matches.append(row)
    return len(matches) == 1

def _cognito_user_for_phone(phone: str) -> Optional[Dict[str, Any]]:
    """The one enabled, phone-verified customer-pool user for phone, or None.

    More than one matching user is an identity conflict and therefore raises rather than picking
    one.  No user is a normal WhatsApp-first state; the caller provisions it server-side without
    asking the customer to leave WhatsApp.
    """
    canonical = contact_store.canonical_phone(phone)
    if not canonical or canonical != phone:
        raise customer_auth.CustomerNotAuthorized("invalid canonical customer phone")
    users = _cognito_client().list_users(
        UserPoolId=CUSTOMER_POOL_ID,
        Filter='phone_number = "' + phone + '"',
        Limit=2,
    ).get("Users") or []
    enabled = [u for u in users if u.get("Enabled", True)]
    if len(enabled) > 1:
        raise customer_auth.CustomerNotAuthorized("ambiguous WhatsApp customer identity")
    if not enabled:
        return None
    attrs = {a["Name"]: a["Value"] for a in enabled[0].get("Attributes", [])}
    if attrs.get("phone_number") != phone or attrs.get("phone_number_verified") != "true":
        raise customer_auth.CustomerNotAuthorized("WhatsApp customer phone is not verified")
    return enabled[0]


def _cognito_user_for_sub(subject: str, phone: str) -> Optional[Dict[str, Any]]:
    """Validate an already-linked owner without trusting the ContactsTable stamp by itself."""
    if not customer_auth.is_cognito_subject(subject):
        return None
    users = _cognito_client().list_users(
        UserPoolId=CUSTOMER_POOL_ID,
        Filter='sub = "' + subject + '"',
        Limit=2,
    ).get("Users") or []
    if len(users) != 1 or not users[0].get("Enabled", True):
        return None
    attrs = {a["Name"]: a["Value"] for a in users[0].get("Attributes", [])}
    if (attrs.get("sub") != subject or attrs.get("phone_number") != phone
            or attrs.get("phone_number_verified") != "true"):
        return None
    return users[0]


def _ensure_whatsapp_identity(event: Dict[str, Any]) -> Dict[str, Any]:
    """Bridge a signed inbound WhatsApp contact to the customer pool, without browser sign-in.

    Trust boundary:
      * callable only as a direct internal Lambda event (the handler rejects API-Gateway shapes);
      * WABA1 only, matching the native payment sender allow-list;
      * exact ContactsTable id + exact E.164 sender phone;
      * signed-inbound evidence (or equally strong VERIFIED provenance) must already exist.

    The bridge creates no session and returns no token.  It only ensures the same Cognito subject
    that a later website sign-in will use exists and stamps that subject on the already-proven
    contact.  Website/API checkout still requires its normal bearer session.
    """
    if str(event.get("wabaId") or "") != META_WABA_ID:
        return {"outcome": "WHATSAPP_IDENTITY_NOT_READY"}

    phone = contact_store.canonical_phone(event.get("senderPhone"))
    contact_id = str(event.get("contactId") or "").strip()
    source_message_id = str(event.get("sourceMessageId") or "").strip()
    if not phone or not contact_id:
        return {"outcome": "WHATSAPP_IDENTITY_NOT_READY"}

    # Fail closed when the phone belongs to more than one live canonical contact.  An explicit
    # GetItem(contact_id) alone would bypass the uniqueness rule used everywhere else.
    try:
        canonical = contact_store.find_by_phone(_contacts_table(), phone)
    except contact_store.IdentityConflict:
        logger.warning(json.dumps({"event": "whatsapp_identity_contact_conflict"}))
        return {"outcome": "WHATSAPP_IDENTITY_CONFLICT"}
    if not canonical or contact_key.resolve(canonical) != contact_id:
        return {"outcome": "WHATSAPP_IDENTITY_NOT_READY"}
    contact = canonical

    existing_owner = str(contact.get("checkoutCustomerId") or "").strip()
    if existing_owner:
        # This is the pre-existing production trust contract: the stored owner must be one enabled
        # customer-pool subject whose verified phone is exactly the WhatsApp sender. No new account
        # or ownership edge is created here, so no WAMID capability is needed.
        if _cognito_user_for_sub(existing_owner, phone) is None:
            logger.warning(json.dumps({"event": "whatsapp_identity_owner_conflict"}))
            return {"outcome": "WHATSAPP_IDENTITY_CONFLICT"}
        return {
            "outcome": "WHATSAPP_IDENTITY_READY",
            "customerId": existing_owner,
            "contactId": contact_id,
            "customerUuid": str(contact.get("customerUuid") or ""),
        }

    # New ownership/provisioning is the sensitive edge. It requires an exact fresh WAMID that
    # customer-registration independently resolves in the signed inbound-message store.
    if not _whatsapp_identity_evidence(
            contact, phone, source_message_id, str(event.get("wabaId") or "")):
        return {"outcome": "WHATSAPP_IDENTITY_NOT_READY"}

    try:
        user = _cognito_user_for_phone(phone)
        if user is None:
            # Same backend-only provisioning used after OTP registration: no invite, no password
            # exposed, and the only future browser sign-in method remains WhatsApp CUSTOM_AUTH.
            _provision_login(phone, contact_id)
            user = _cognito_user_for_phone(phone)
        if user is None:
            return {"outcome": "WHATSAPP_IDENTITY_NOT_READY"}
        attrs = {a["Name"]: a["Value"] for a in user.get("Attributes", [])}
        subject = str(attrs.get("sub") or "")
        if not customer_auth.is_cognito_subject(subject):
            return {"outcome": "WHATSAPP_IDENTITY_NOT_READY"}

        now = int(time.time())
        _contacts_table().update_item(
            Key={"id": contact_id},
            UpdateExpression=(
                "SET checkoutCustomerId=:sub, "
                "phoneVerifiedAt=if_not_exists(phoneVerifiedAt,:now), updatedAt=:now"
            ),
            ConditionExpression=(
                "attribute_exists(id) AND "
                "(attribute_not_exists(checkoutCustomerId) OR checkoutCustomerId=:empty "
                "OR checkoutCustomerId=:sub)"
            ),
            ExpressionAttributeValues={":sub": subject, ":empty": "", ":now": now},
        )
        logger.info(json.dumps({"event": "whatsapp_identity_ready"}))
        return {
            "outcome": "WHATSAPP_IDENTITY_READY",
            "customerId": subject,
            "contactId": contact_id,
            "customerUuid": str(contact.get("customerUuid") or ""),
        }
    except customer_auth.CustomerNotAuthorized:
        logger.warning(json.dumps({"event": "whatsapp_identity_conflict"}))
        return {"outcome": "WHATSAPP_IDENTITY_CONFLICT"}
    except Exception as error:  # noqa: BLE001
        # Conditional failure means another path linked the row concurrently. Re-read once and
        # accept only the exact same phone-bound owner; never overwrite a different owner.
        if _is_conditional_failure(error):
            current = _contacts_table().get_item(
                Key={"id": contact_id}, ConsistentRead=True
            ).get("Item") or {}
            owner = str(current.get("checkoutCustomerId") or "").strip()
            if (owner and _whatsapp_identity_evidence(
                    current, phone, source_message_id, str(event.get("wabaId") or ""))
                    and _cognito_user_for_sub(owner, phone)):
                return {
                    "outcome": "WHATSAPP_IDENTITY_READY",
                    "customerId": owner,
                    "contactId": contact_id,
                    "customerUuid": str(current.get("customerUuid") or ""),
                }
        logger.error(json.dumps({"event": "whatsapp_identity_bridge_failed",
                                 "error": type(error).__name__}))
        return {"outcome": "WHATSAPP_IDENTITY_NOT_READY"}


# ── request/response plumbing ───────────────────────────────────────────────────

def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("body")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {k: v for k, v in event.items()
                if k not in ("requestContext", "headers", "httpMethod", "path",
                             "rawPath", "isBase64Encoded")}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _action(event: Dict[str, Any], body: Dict[str, Any]) -> str:
    """Which operation to run: explicit `action`, or inferred from the path suffix."""
    explicit = str(body.get("action") or event.get("action") or "").strip().lower()
    if explicit in ("request", "verify", "consent"):
        return explicit
    path = str(event.get("rawPath") or event.get("path") or "").lower()
    if path.endswith("/verify"):
        return "verify"
    return "request"


def _reply(result: registration.RegistrationResult, origin: str) -> Dict[str, Any]:
    """Translate a RegistrationResult into an HTTP response, leaking nothing it should not."""
    return _no_store(cors_response(result.http_status(), result.public_body(), origin))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if event.get("internalAction") == "ensureWhatsAppIdentity":
        # API Gateway always supplies at least one of these fields.  Refuse the same payload when
        # it arrives through the public registration endpoint: only a direct Lambda caller with
        # IAM permission may use WhatsApp inbound evidence as identity proof.
        if any(event.get(k) for k in ("requestContext", "rawPath", "path", "httpMethod")):
            return {"outcome": "INTERNAL_INVOCATION_REQUIRED", "statusCode": 403}
        return _ensure_whatsapp_identity(event)

    origin = extract_origin(event)
    rc = event.get("requestContext", {}) or {}
    method = rc.get("http", {}).get("method", event.get("httpMethod", "")).upper()
    if method == "OPTIONS":
        return _no_store(options_response(origin))

    # No JWT requirement, deliberately. Registration runs BEFORE the customer has any session — it
    # is how they come to exist. The control here is the fail-closed per-IP/per-phone throttle plus
    # the fact that neither endpoint reveals whether a number is known. This route is listed in the
    # gateway's AUTH_SKIP_PATHS for that reason, the same position as the email-verification door.

    body = _body(event)
    action = _action(event, body)
    try:
        if action == "consent":
            return _consent(event, origin)
        if action == "verify":
            return _verify(event, body, origin)
        return _request(event, body, origin)
    except Exception as exc:  # noqa: BLE001
        # Type only. An exception message can echo the phone number or the code.
        logger.error(json.dumps({"event": "customer_registration_error",
                                 "action": action, "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))



def _consent(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Record the one explicit marketing opt-in shown with the successful sign-in OTP.

    The endpoint is public at API-Gateway level because request/verify must be, so this action
    authenticates itself with the customer access token. The proven session phone is the lookup
    key; no browser-supplied phone or contact id is accepted.
    """
    customer, denied = customer_auth.require_customer(event)
    if denied:
        return _no_store(denied)
    try:
        phone = identity.normalize_phone_preserving_country(customer.phone)
    except identity.InvalidPhoneNumber:
        return _no_store(cors_response(400, {"error": "INVALID_SESSION_PHONE"}, origin))
    row = contact_store.lookup(_contacts_table(), phone) or {}
    contact_id = contact_key.resolve(row)
    if not contact_id:
        return _no_store(cors_response(409, {"error": "CONTACT_NOT_FOUND"}, origin))

    now = int(time.time())
    if consent_evidence.current_state(
            row, "WHATSAPP", now=now, purpose=consent_evidence.MARKETING
    ) == consent_evidence.OPTED_IN:
        return _no_store(cors_response(200, {"status": "CONSENT_RECORDED"}, origin))

    record = consent_evidence.build_record(
        channel="WHATSAPP",
        state=consent_evidence.OPTED_IN,
        source="WEB_FORM",
        at=now,
        purpose=consent_evidence.MARKETING,
        reference="customer-sign-in-otp",
    )
    ledger = consent_evidence.append(row, record)
    _contacts_table().update_item(
        Key=contact_key.key(contact_id),
        UpdateExpression="SET #ledger=:ledger, optInWhatsApp=:yes, updatedAt=:now",
        ConditionExpression="attribute_exists(id)",
        ExpressionAttributeNames={"#ledger": consent_evidence.ATTRIBUTE},
        ExpressionAttributeValues={":ledger": ledger, ":yes": True, ":now": now},
    )
    return _no_store(cors_response(200, {"status": "CONSENT_RECORDED"}, origin))

def _request(event: Dict[str, Any], body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Issue and send a WhatsApp OTP. Same response whether or not the number is a customer."""
    result = registration.begin(
        raw_phone=body.get("phone"),
        event=event,
        throttle_table=_table(),
        challenge_table=_table(),
        pepper=_pepper(),
        send_code=_send_code,
    )
    if result.outcome == registration.SEND_FAILED:
        # The challenge is stored; the message did not go. A soft failure the client can retry.
        return _no_store(cors_response(
            502, {"status": "send_failed",
                  "message": "Could not send the code. Please try again."}, origin))
    return _reply(result, origin)


def _verify(event: Dict[str, Any], body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Check the code, then resolve/create the customer and provision the login."""
    code = str(body.get("code") or "").strip()
    if not code:
        return _no_store(cors_response(400, {"error": "CODE_REQUIRED"}, origin))

    result = registration.complete(
        raw_phone=body.get("phone"),
        code=code,
        challenge_table=_table(),
        pepper=_pepper(),
        resolve_customer=_resolve_customer,
        create_customer=_create_customer,
        provision_login=_provision_login,
    )
    return _reply(result, origin)
