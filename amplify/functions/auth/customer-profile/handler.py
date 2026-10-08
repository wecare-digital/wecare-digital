"""Authenticated checkout profile -> Workspace Contacts.

The customer's phone and customer id come only from customer_auth.require_customer(event).
The browser may submit first/last name, email, a short-lived email verification proof, and one
structured delivery address. The proof is bound to the normalized email by the public
email-verification Lambda and stored in the shared OTP table. This endpoint validates that proof
server-side before any CRM write.

PRESENCE-DRIVEN, NOT MODE-DRIVEN
--------------------------------
There is no `mode` field and one is never sent. The frontend's mode decides which fields it
posts; this handler decides what is *required* from what is present in the body and what is
already stored on the row this session owns. Presence means the key is there with a non-empty
value: a blank field is treated as ABSENT, never as a request to clear, because nothing in this
flow can clear a saved field — a profile with a blank verified email or a blank address is a
profile that cannot pay.

Consequently a first-time customer emerges from ONE save ready to pay (name + email + proof +
address are all required when this session owns no row), while a returning customer can save a
new address, or correct a name, without re-proving an email they already proved.

No marketing consent is inferred from making a purchase. New rows default opt-in/allowlist fields
to False; an existing contact's explicit choices are preserved.
"""

from __future__ import annotations

import hmac
import json
import os
import time
import uuid
from hashlib import sha256
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import contact_key, customer_auth, customer_session
from lambda_utils.ecommerce import contact_address
from lambda_utils.identity import customer as identity
from lambda_utils.identity import customer_uuid
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response
from lambda_utils.validation import sanitize_html

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")
OTP_TABLE = os.environ.get("OTP_TABLE", "stack-wecare-digital-DownloadGrantsTable")
CONTACTS_TABLE = os.environ.get("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")
OTP_PEPPER_SECRET_ID = os.environ.get("OTP_PEPPER_SECRET_ID", "wecare/otp/pepper")

PROOF_PURPOSE = "email_verification_proof"
PROOF_PREFIX = "email-proof#"
CUSTOMER_TAG = "Customer"

_dynamodb = None
_secrets = None
_pepper_cache: Dict[str, str] = {}


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    hardened = dict(response)
    hardened["headers"] = customer_session.harden_session_headers(response.get("headers") or {})
    return hardened


def _table(name: str):
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(name)


def _pepper() -> str:
    global _secrets
    if "pepper" in _pepper_cache:
        return _pepper_cache["pepper"]
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=REGION)
    raw = _secrets.get_secret_value(SecretId=OTP_PEPPER_SECRET_ID).get("SecretString", "") or ""
    try:
        parsed = json.loads(raw)
        value = str(parsed.get("pepper") or parsed.get("value") or "").strip()
    except (ValueError, TypeError):
        value = raw.strip()
    if not value:
        raise RuntimeError("OTP pepper is not configured")
    _pepper_cache["pepper"] = value
    return value


def _proof_digest(email: str) -> str:
    return hmac.new(
        _pepper().encode("utf-8"),
        ("email-proof\x1f" + email).encode("utf-8"),
        sha256,
    ).hexdigest()


def _proof_valid(proof_id: Any, email: str) -> bool:
    proof = str(proof_id or "").strip()
    if not proof or len(proof) > 128:
        return False
    item = _table(OTP_TABLE).get_item(
        Key={"grantId": PROOF_PREFIX + proof}
    ).get("Item") or {}
    if item.get("purpose") != PROOF_PURPOSE:
        return False
    if int(item.get("expiresAt") or 0) < int(time.time()):
        return False
    stored = str(item.get("subjectDigest") or "")
    wanted = _proof_digest(email)
    return bool(stored) and hmac.compare_digest(stored, wanted)


def _body(event: Dict[str, Any]) -> Dict[str, Any]:
    raw = event.get("body")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def _active_match(index: str, field: str, value: str) -> Optional[Dict[str, Any]]:
    result = _table(CONTACTS_TABLE).query(
        IndexName=index,
        KeyConditionExpression=Key(field).eq(value),
        Limit=5,
    )
    for item in result.get("Items") or []:
        if item.get("deletedAt") is None:
            return item
    return None


def _claimable(item: Dict[str, Any]) -> bool:
    """Whether this session may take ownership of a row that has no owner yet.

    A CRM-created contact — typed by staff, or arriving from an import or a People sync — carries
    no `checkoutCustomerId`, because only the checkout path ever writes one. Treating that as
    "not mine" made the row invisible and pushed a customer who already exists in the CRM through
    the whole first-time create flow: name, email, a fresh email code, and an address.

    Claiming it is defensible for exactly one reason, and it is worth stating because it is the
    security trade: **the phone is not browser-supplied.** It comes from a Cognito session that
    only a WhatsApp OTP can mint, and the lookup is keyed on the normalised form of that proven
    number. So "a row bearing my verified phone and belonging to nobody" is a row about me.

    It is still a real widening, so it is bounded on both sides:

    - An EMPTY owner only. A row owned by a different `checkoutCustomerId` is refused exactly as
      before — this cannot be used to reach another customer's contact.
    - Claiming is NOT verifying. The claim writes `checkoutCustomerId` and nothing else; it
      never stamps `emailVerifiedAt`, and `checkout/handler.py::_checkout_profile` still demands
      that timestamp before the customer can pay. A claimed row with an unverified email must go
      through email verification like any other.
      Note this is about what claiming *writes*, not about what the row may already hold: a
      claimable row CAN arrive already carrying a verified email, because `auth/blog-subscribe`
      writes one onto an unowned row. See the row-1 comment in `handler` for why that is sound.
    """
    return not str(item.get("checkoutCustomerId") or "").strip()


def _owned_contact(phone: str, customer_id: str) -> Optional[Dict[str, Any]]:
    """The non-deleted contact row this session is allowed to edit, or `None`.

    Three different questions get asked about a contact row and they have three different
    answers. This one is "may this session edit this row?" — non-deleted **and** either already
    owned by this customer or owned by nobody (see `_claimable`). It is deliberately WEAKER than
    `checkout/handler.py::_checkout_profile` ("is this customer ready to pay?", which also
    demands `emailVerifiedAt` and a non-empty `email`), because the required-field and
    email-proof rules below have to be able to see a row that exists but is unverified. The
    stronger predicate would hide it and demote an edit to a creation.

    Keyed on the **normalised** phone — the exact value `_upsert_contact` writes.
    `normalize_phone_preserving_country` is non-trivial (its docstring records `+6591234567`
    becoming `+916591234567` under the older `normalize_phone`), so a lookup on the raw session
    phone could miss the row this request is about to write to, flipping an edit into a creation
    and demanding a full name + email + address + proof from a customer who already has all four.
    """
    result = _table(CONTACTS_TABLE).query(
        IndexName="phone-index",
        KeyConditionExpression=Key("phone").eq(phone),
        Limit=5,
    )
    # An already-owned row is preferred over a claimable one, so a session that has its own row
    # never adopts a stray unowned duplicate on the same number.
    claimable: Optional[Dict[str, Any]] = None
    for item in result.get("Items") or []:
        if item.get("deletedAt") is not None:
            continue
        if item.get("checkoutCustomerId") == customer_id:
            return item
        if claimable is None and _claimable(item):
            claimable = item
    # The claim itself is a WRITE, and it happens in `_upsert_contact`'s edit path, which already
    # emits `checkoutCustomerId=:customer` on every save. Returning the row here is what routes
    # the request down that path instead of the create path.
    return claimable


def _merge_tags(existing: Any) -> list[str]:
    values = existing if isinstance(existing, list) else []
    out = [str(value).strip() for value in values if str(value).strip()]
    if CUSTOMER_TAG.lower() not in {value.lower() for value in out}:
        out.append(CUSTOMER_TAG)
    return out


def _present(value: Any) -> bool:
    """Whether the browser supplied this field at all.

    A key present with an empty or whitespace-only value counts as **absent**. That is what keeps
    `{"email": ""}` on an address edit from becoming a `400 INVALID_EMAIL` on a request that was
    never trying to change the email, and it is why nothing in this handler can clear a field.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (dict, list)):
        return bool(value)
    return bool(str(value if value is not None else "").strip())


def _stored_email(row: Optional[Dict[str, Any]]) -> Optional[str]:
    """The row's email, normalised, or `None` when there is nothing comparable.

    `normalize_email` raises, and a row written by a CRM import or a People sync may hold a value
    that will not normalise. A failure here returns `None`, which the caller reads as "changed"
    and therefore requires a proof — fail-closed, and it never 500s on legacy data.
    """
    try:
        return identity.normalize_email((row or {}).get("email"))
    except identity.InvalidEmailAddress:
        return None


def _set_fragments(*, name: Optional[str], first_name: Optional[str], last_name: Optional[str],
                   phone: str, email: Optional[str], address: Optional[Dict[str, Any]],
                   proof_validated: bool, tags: Optional[list], tags_if_absent: bool = False,
                   customer_id: str, now: int) -> tuple:
    """`(update_expression, names, values)` for one contact mutation. Only supplied fields appear.

    Always written: `phone`, `phoneVerifiedAt=if_not_exists(...)`, `checkoutProfileUpdatedAt`,
    `updatedAt`. Conditionally: the `name`/`firstName`/`lastName` trio (only when BOTH name parts
    were supplied), `email`, `emailVerifiedAt=:now` (**only** when `proof_validated`), the
    address pair, `tags`, `checkoutCustomerId`.

    `tags_if_absent=True` emits `tags=if_not_exists(tags,:tags)` instead of `tags=:tags`. Site (1)
    passes `False`: it holds the existing row, so `_merge_tags(existing.get("tags"))` is a real
    read-modify-write merge and must win — collapsing it toward `if_not_exists` would stop
    `Customer` ever being added to an existing contact that lacks it, which is the one thing
    `_merge_tags` exists for. Site (3) passes `True`: it is the `ConditionalCheckFailedException`
    race fallback and has NOT read the row, so it must not overwrite tags another writer merged.
    Safe because the racing writer is the same `customer_id` by construction — the id is
    `uuid5(... customer_id)`.
    """
    assignments: list[str] = []
    names: Dict[str, str] = {}
    values: Dict[str, Any] = {":phone": phone, ":now": now}

    if name is not None:
        assignments += ["#name=:name", "firstName=:first", "lastName=:last"]
        names["#name"] = "name"
        values.update({":name": name, ":first": first_name, ":last": last_name})
    assignments.append("phone=:phone")
    if email:
        assignments.append("email=:email")
        values[":email"] = email
    if proof_validated:
        assignments.append("emailVerifiedAt=:now")
    if address is not None:
        # A supplied address overwrites the stored one wholesale. There is no partial-field
        # merge, because a half-merged address is a wrong place of supply.
        assignments += [f"{contact_address.ATTRIBUTE}=:address",
                        f"{contact_address.UPDATED_ATTRIBUTE}=:now"]
        values[":address"] = address
    if tags is not None:
        assignments.append("tags=if_not_exists(tags,:tags)" if tags_if_absent else "tags=:tags")
        values[":tags"] = tags
    if customer_id:
        assignments.append("checkoutCustomerId=:customer")
        values[":customer"] = customer_id
    assignments += ["phoneVerifiedAt=if_not_exists(phoneVerifiedAt,:now)",
                    # The PUBLIC customer id, on exactly the same `if_not_exists` footing as
                    # `phoneVerifiedAt` beside it: minted locally every time and discarded by
                    # DynamoDB when the row already has one, so an existing customer keeps the id
                    # already printed on their invoices. Note it is NOT the row `id` - that is
                    # `uuid5(NAMESPACE_URL, "wecare:checkout-customer:<cognito sub>")` a few lines
                    # down, a hash of the Cognito subject, and therefore not publishable.
                    f"{customer_uuid.ATTRIBUTE}="
                    f"if_not_exists({customer_uuid.ATTRIBUTE},:custuuid)",
                    "checkoutProfileUpdatedAt=:now", "updatedAt=:now"]
    values[":custuuid"] = customer_uuid.new_customer_uuid()

    return "SET " + ", ".join(assignments), names, values


def _upsert_contact(*, customer_id: str, phone: str, email: Optional[str] = None,
                    first_name: Optional[str] = None, last_name: Optional[str] = None,
                    address: Optional[Dict[str, Any]] = None,
                    proof_validated: bool = False) -> Dict[str, Any]:
    phone_match = _active_match("phone-index", "phone", phone)
    # The email index is consulted ONLY when an email was supplied. Without this guard an
    # address-only or name-only save issues `Key("email").eq(None)`, DynamoDB answers
    # `ValidationException`, and the `except Exception` arm turns it into `500 INTERNAL_ERROR` —
    # i.e. every save this flow adds would fail.
    #
    # Consequence, stated as a decision rather than left as a surprise: CONTACT_IDENTITY_CONFLICT
    # cannot fire on an email-less save. That is correct — the conflict exists to stop a phone row
    # and a DIFFERENT email row being merged, and with no email in the body there is no second
    # identity to reconcile. The row being written is the one the phone index resolved, which is
    # the one `_owned_contact` already authorised.
    email_match = _active_match("email-index", "email", email) if email else None
    phone_id = contact_key.resolve(phone_match) if phone_match else ""
    email_id = contact_key.resolve(email_match) if email_match else ""
    if phone_id and email_id and phone_id != email_id:
        raise ValueError("CONTACT_IDENTITY_CONFLICT")

    now = int(time.time())
    # The name trio is recomputed and written only when BOTH parts were supplied.
    name = f"{first_name} {last_name}".strip() if (first_name and last_name) else None
    existing = phone_match or email_match
    table = _table(CONTACTS_TABLE)

    if existing:
        # Site (1): the edit path. It holds the row, so tags are a real merge.
        contact_id = contact_key.resolve(existing)
        expression, names, values = _set_fragments(
            name=name, first_name=first_name, last_name=last_name, phone=phone,
            email=email, address=address, proof_validated=proof_validated,
            tags=_merge_tags(existing.get("tags")), tags_if_absent=False,
            customer_id=customer_id, now=now,
        )
        table.update_item(Key={"id": contact_id}, UpdateExpression=expression,
                          ExpressionAttributeValues=values,
                          **({"ExpressionAttributeNames": names} if names else {}))
        return {"contactId": contact_id, "created": False}

    # Site (2): one signed-in customer converges onto one deterministic CRM id when no prior
    # phone/email row exists. Reachable only on creation, where every field is required and
    # therefore present.
    contact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wecare:checkout-customer:{customer_id}"))
    item = {
        **contact_key.contact_item_keys(contact_id),
        # Minted on the create branch for the same reason `_create` in `core/contacts` does: this
        # branch runs only when neither the phone index nor the email index resolved a row, so
        # there is no existing id to preserve. Site (3) below - the race on the deterministic id -
        # goes through `_set_fragments`, which assigns it with `if_not_exists`, so the loser of
        # the race does not replace the winner's id.
        customer_uuid.ATTRIBUTE: customer_uuid.new_customer_uuid(),
        "name": name or "",
        "firstName": first_name or "",
        "lastName": last_name or "",
        "phone": phone,
        "email": email or "",
        "tags": [CUSTOMER_TAG],
        "checkoutCustomerId": customer_id,
        "phoneVerifiedAt": now,
        "checkoutProfileUpdatedAt": now,
        # Purchase/transactional identity is not marketing consent.
        "optInWhatsApp": False,
        "optInEmail": False,
        "optInSms": False,
        "allowlistWhatsApp": False,
        "allowlistEmail": False,
        "allowlistSms": False,
        "createdAt": now,
        "updatedAt": now,
        "deletedAt": None,
    }
    if proof_validated:
        item["emailVerifiedAt"] = now
    if address is not None:
        item[contact_address.ATTRIBUTE] = address
        item[contact_address.UPDATED_ATTRIBUTE] = now
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
        return {"contactId": contact_id, "created": True}
    except Exception as exc:  # noqa: BLE001
        response = getattr(exc, "response", None) or {}
        if response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        # Site (3): the race on the deterministic id. It shares the composer with site (1), so
        # it can no longer silently drop the address or the proof semantics, and it gains
        # `tags=if_not_exists(...)` plus `checkoutCustomerId`.
        expression, names, values = _set_fragments(
            name=name, first_name=first_name, last_name=last_name, phone=phone,
            email=email, address=address, proof_validated=proof_validated,
            tags=[CUSTOMER_TAG], tags_if_absent=True,
            customer_id=customer_id, now=now,
        )
        table.update_item(Key={"id": contact_id}, UpdateExpression=expression,
                          ExpressionAttributeValues=values,
                          **({"ExpressionAttributeNames": names} if names else {}))
        return {"contactId": contact_id, "created": False}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    origin = extract_origin(event)
    rc = event.get("requestContext", {}) or {}
    method = rc.get("http", {}).get("method", event.get("httpMethod", "")).upper()
    if method == "OPTIONS":
        return _no_store(options_response(origin))
    if method != "POST":
        return _no_store(cors_response(405, {"error": "METHOD_NOT_ALLOWED"}, origin))

    identity_session, denied = customer_auth.require_customer(event)
    if denied:
        return _no_store(denied)

    # (1) Shape of the request. `mode` is not accepted and is never sent.
    body = _body(event)
    allowed = {"firstName", "lastName", "email", "emailProof", "address"}
    if set(body) - allowed:
        return _no_store(cors_response(400, {"error": "UNEXPECTED_FIELD"}, origin))

    # (2) The session phone, because the owned-row lookup and every write key on it.
    try:
        phone = identity.normalize_phone_preserving_country(identity_session.phone)
    except identity.InvalidPhoneNumber:
        # MissingCountryCode subclasses InvalidPhoneNumber, so one arm covers both.
        return _no_store(cors_response(400, {"error": "INVALID_SESSION_PHONE"}, origin))

    # (3) The address, BEFORE the main try, and that placement is not stylistic.
    # `UnusableAddress` subclasses `ValueError`, and the main try's `except ValueError` arm ends
    # in a bare `raise` while its `except Exception` arm is a SIBLING on the same try — so an
    # UnusableAddress raised in there escapes handler() as an unhandled Lambda invocation error:
    # no field, no 500 body, and no CORS headers, leaving the browser a network-class failure it
    # cannot read a message out of. A mistyped PIN is the most common error in this form.
    address = None
    if isinstance(body.get("address"), dict) and body["address"]:
        try:
            address = contact_address.normalize_for_storage(body["address"])
        except contact_address.UnusableAddress as bad:
            payload = {"error": "INVALID_ADDRESS", "code": bad.code}
            if bad.field:
                payload["field"] = bad.field
            # No echo of the submitted value: an address in a response body is an address an
            # error-logging layer might capture.
            return _no_store(cors_response(400, payload, origin))

    # (4) The row this session owns, which decides what the rest of the body must carry.
    try:
        owned = _owned_contact(phone, identity_session.customer_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "customer_profile_error", "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))
    creating = owned is None

    # (5) Presence-driven validation, driven by that row.
    first_name = sanitize_html(body.get("firstName"), max_length=100).strip()
    last_name = sanitize_html(body.get("lastName"), max_length=100).strip()
    if creating:
        if not first_name or not last_name:
            return _no_store(cors_response(400, {"error": "NAME_REQUIRED"}, origin))
    elif bool(first_name) != bool(last_name):
        # Half a name is a mistake, not an edit: `name` is recomputed from both parts.
        return _no_store(cors_response(400, {"error": "NAME_REQUIRED"}, origin))

    email = None
    if _present(body.get("email")):
        try:
            email = identity.normalize_email(body.get("email"))
        except identity.InvalidEmailAddress:
            return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))
    elif creating:
        return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))

    if creating and address is None:
        return _no_store(cors_response(
            400, {"error": "INVALID_ADDRESS", "code": "ADDRESS_REQUIRED"}, origin))

    # The email-proof rules are an ORDERED decision list and the first match wins, because two
    # of the cases deliberately overlap.
    if creating:
        # Row 1: a new row needs a proof bound to the submitted email before it can be stamped.
        #
        # A CLAIMED row (phone-matched, previously unowned — see `_claimable`) no longer lands
        # here: `_owned_contact` now returns it, so `creating` is False and the rows below apply.
        #
        # WHAT A CLAIMED ROW CAN AND CANNOT INHERIT, because this is the question the widening
        # actually turns on and there are TWO writers of `emailVerifiedAt` on `ContactsTable`:
        #
        # 1. `_upsert_contact` here, only with `proof_validated`. A row it wrote already carries
        #    a `checkoutCustomerId`, so it is never claimable in the first place.
        # 2. `auth/blog-subscribe/handler.py` — `:345` on its update path and `:373` in its
        #    new-item map — which writes `phone`, `email`, `phoneVerifiedAt` and
        #    `emailVerifiedAt` and NEVER writes `checkoutCustomerId`. That row IS claimable.
        #
        # So a claimed row CAN reach row 4 and save its own stored email with no email proof.
        # That is sound rather than a hole, and the reason is specific: `blog-subscribe` refuses
        # to write the row at all unless it holds BOTH a phone proof and an email proof
        # (`handler.py:408-409`), each minted by its own OTP exchange and each re-checked against
        # the normalised phone/email pair. The binding behind that `emailVerifiedAt` is therefore
        # at least as strong as the one this handler mints, and the claim itself is keyed on a
        # phone a Cognito session proved. Row 4 additionally requires the submitted email to
        # EQUAL the stored one, so no new address can ride in on it.
        #
        # What a claimed row still cannot do is inherit verification nothing ever proved: a
        # CRM-typed or imported row carries no `emailVerifiedAt`, so row 4 cannot match it and
        # any email it submits falls to rows 5/6, which demand a proof.
        proof_required = True
    elif _present(body.get("emailProof")) and email is None:
        # Row 2, and it beats row 3: a proof is a claim about an ADDRESS. Binding it to the
        # stored value would let a proof minted in one request verify another, which is the one
        # outcome the verification invariant forbids. Refuse, and leave the row untouched.
        return _no_store(cors_response(400, {"error": "EMAIL_VERIFICATION_REQUIRED"}, origin))
    elif email is None:
        # Row 3, and it beats row 6: an edit that submits no email requires no proof and never
        # writes emailVerifiedAt. A row with an unverified email already cannot pay, so refusing
        # its address save removes the customer's only way forward and adds no protection.
        proof_required = False
    elif email == _stored_email(owned) and owned.get("emailVerifiedAt"):
        # Row 4: re-proving an address that is already proven, from a session that owns the row.
        proof_required = False
    else:
        # Rows 5 and 6: a changed email, or a stored email that was never verified.
        proof_required = True

    # (6) The proof check and the write.
    try:
        if proof_required and not _proof_valid(body.get("emailProof"), email or ""):
            return _no_store(cors_response(400, {"error": "EMAIL_VERIFICATION_REQUIRED"}, origin))
        result = _upsert_contact(
            customer_id=identity_session.customer_id,
            phone=phone,
            email=email,
            first_name=first_name,
            last_name=last_name,
            address=address,
            proof_validated=proof_required,
        )
    except ValueError as exc:
        if str(exc) == "CONTACT_IDENTITY_CONFLICT":
            return _no_store(cors_response(409, {"error": "CONTACT_IDENTITY_CONFLICT"}, origin))
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "customer_profile_error", "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))

    logger.info(json.dumps({"event": "checkout_customer_profile_saved",
                            "created": bool(result.get("created"))}))

    # The POST-WRITE merged view, not an echo. The frontend feeds this reply straight into
    # `setProfile` and `deriveStatus`, so an echo-only response would be a live bug: an
    # address-only save would blank the identity card's name and email, and a name-only save
    # would report addressComplete:false and send a returning customer back to a form they never
    # opened. Each field is the submitted value when one was supplied, otherwise the value on the
    # owned row — built from the row `_owned_contact` already returned, so there is no extra read.
    merged = dict(owned or {})
    if address is not None:
        merged[contact_address.ATTRIBUTE] = address
    if email:
        merged["email"] = email
    if first_name and last_name:
        merged["firstName"] = first_name
        merged["lastName"] = last_name
        merged["name"] = f"{first_name} {last_name}".strip()

    merged_first = str(merged.get("firstName") or "")
    merged_last = str(merged.get("lastName") or "")
    stored_address = contact_address.from_contact(merged)
    return _no_store(cors_response(200, {
        "status": "PROFILE_READY",
        "contactId": result["contactId"],
        "name": (str(merged.get("name") or "").strip()
                 or f"{merged_first} {merged_last}".strip()),
        "firstName": merged_first,
        "lastName": merged_last,
        "email": str(merged.get("email") or ""),
        # The normalised value this handler wrote, which is the same string the read side
        # resolves the row on.
        "phone": phone,
        "addressComplete": stored_address is not None,
        "address": stored_address,
    }, origin))
