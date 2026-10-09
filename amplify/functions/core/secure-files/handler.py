"""Secure file sharing for wecare.digital/get/secure.

Three tiers exist on the ``wecare-digital-get`` bucket. This function owns the
gated one:

    o/       open, auto-download, served straight off CloudFront. Not our concern.
    secure/  this file. A named customer, verified by WhatsApp OTP, buys durable
             access to one owned file and receives renewable short-lived presigned URLs.

Why the object key is opaque
----------------------------
Every upload lands at::

    secure/wecare-digital-<uuid4hex>-<uuid4hex><ext>

The key deliberately carries no customer name, no original filename and no
sequence number, so it cannot be guessed and one customer's key reveals nothing
about another's. The consequence is that the key is meaningless to a human, which
is precisely why ``SecureFilesTable`` exists: it is the only place that maps an
opaque key back to a person and a readable name. That table, not the key, answers
"which of these many files belongs to which customer" - via the
``owner-created-index`` GSI, so listing one customer's files is a query rather
than a table scan.

The key being unguessable is a convenience, not the control. CloudFront refuses
the whole ``secure/`` prefix outright (see
``amplify/functions/edge/get-miss-redirect``), so these objects are reachable
only through a presigned URL this function issues after checking ownership and
payment.

Refusal is deliberately uniform
-------------------------------
A caller who is not the owner, and a caller asking for a ``fileId`` that does not
exist, get the byte-identical 403 ``NOT_REGISTERED`` response. Distinguishing them
would confirm that a given file exists, which is the one fact the opaque key is
meant to withhold.

Two authentication paths, deliberately not shared
-------------------------------------------------
Admin routes use ``lambda_utils.middleware.require_auth``, which validates against
the **admin** pool. Customer routes must not: ``require_auth`` hardcodes the admin
pool id, so a customer token would pass ``get_user`` and then silently fall
through to role ``Viewer`` when its group lookup found nothing. Customer auth is
``_customer_identity`` below.

Payment is built but switched off
---------------------------------
``SECURE_FILES_PAYMENT_ENABLED`` defaults to off. While off, order creation
refuses rather than contacting Razorpay, so no payment configuration is touched
and no credential is read. Enabling it is an owner action.
"""

from __future__ import annotations

import base64
import json
import os
import secrets as pysecrets
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from lambda_utils import customer_auth, media_paths
from lambda_utils.direct_send import META_PHONE_TO_WABA, waba_for_meta_phone
from lambda_utils.ecommerce import document_errors, dropdocs_storage, service_request_store
from lambda_utils.logging import get_logger
from lambda_utils.middleware import require_auth
from lambda_utils.response import cors_response, extract_origin, options_response

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")

BUCKET = os.environ.get("SECURE_FILES_BUCKET", "wecare-digital-get")

# Everything gated lives under secure/. The edge function denies that whole prefix,
# so both sub-prefixes below inherit the deny automatically.
SECURE_PREFIX = "secure/"
# u/ holds the original exactly as the operator uploaded it, whatever the type.
UPLOAD_PREFIX = SECURE_PREFIX + "u/"
# d/ holds the rendition that can actually be delivered over WhatsApp. Only PDF and
# images render as something a recipient can open inline; anything else has no d/
# object and falls back to a download link. Recording that at upload time beats
# discovering it at send time, when a customer is already waiting.
DELIVER_PREFIX = SECURE_PREFIX + "d/"
# A Drop Docs document promoted out of the public tree. Composed through media_paths
# rather than concatenated, because this is the one prefix in this file whose keys are
# written by a module that has no business knowing how the locker spells "secure/". The
# three constants above are left hand-built on purpose: rewriting them would change keys
# that are already persisted in SecureFilesTable.
DROPDOCS_PREFIX = media_paths.secure("u/dropdocs/")

# Types WhatsApp recipients can open inline. Documents may be up to 100MB, images
# 5MB, which is why the two are distinguished rather than lumped together.
DELIVERABLE_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "image",
    "image/jpg": "image",
    "image/png": "image",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
FILES_TABLE = os.environ.get("SECURE_FILES_TABLE", "stack-wecare-digital-SecureFilesTable")
GRANTS_TABLE = os.environ.get("DOWNLOAD_GRANTS_TABLE", "stack-wecare-digital-DownloadGrantsTable")
# The Phase O-1 request store. Drop Docs documents are registered against a REQ# row that
# lives there, not in SecureFilesTable: a Drop Docs document belongs to a paid request,
# and the locker owns storage and privacy for it rather than its lifecycle.
SERVICE_REQUESTS_TABLE = os.environ.get(
    "SERVICE_REQUESTS_TABLE", service_request_store.DEFAULT_TABLE_NAME)

# The customer pool, NOT the admin pool. Tokens must prove they came from here.
CUSTOMER_POOL_ID = os.environ.get("CUSTOMER_USER_POOL_ID", "us-east-1_46ULYuukt")
CUSTOMER_POOL_ISSUER = f"https://cognito-idp.{REGION}.amazonaws.com/{CUSTOMER_POOL_ID}"
PARTNER_GROUP = os.environ.get("PARTNER_GROUP", "Partner")

# ── which WABA a customer belongs to ─────────────────────────────────────────
#
# `custom:partner_waba_id` decides which business number a customer's sign-in code
# can ever arrive from: `auth/customer-whatsapp-auth` looks the attribute up in
# `OTP_WABA_MAP` and raises PermissionError on a miss. An unknown value and a
# missing value are indistinguishable there - both deny, both are permanent, and the
# only trace is one denial line in that trigger's log. So this function must write a
# WABA id the gate maps, or write nothing at all. A hardcoded WABA1 literal was the
# third option, and it is the one that misroutes a real customer.
#
# The phone-id -> WABA mapping is NOT restated here. `lambda_utils.direct_send` is its
# single home and already fails closed on an unknown id by returning `''`.
# `wecare-secure-files` is not packaged `standalone`, so the module is bundled into the
# zip and importable - unlike `customer-whatsapp-auth`, whose standalone packaging is
# the documented reason it carries the map as a JSON env var instead.
KNOWN_WABA_IDS = frozenset(META_PHONE_TO_WABA.values())
# The same default `whatsapp_delivery` uses, so the stamp and the sender cannot drift.
DEFAULT_SENDER_PHONE_ID = "1016149501586345"


class UnsafeWabaStamp(RuntimeError):
    """Raised when stamping a WABA would be a guess rather than a fact.

    Two cases, both refusing the upload instead of inventing WABA1: the sender phone
    id does not resolve to a known WABA, and an existing user's current stamp could
    not be read. See `_sender_waba` and `_existing_stamp`.
    """


def _loggable_waba(value) -> str:
    """A Meta id that is safe to print, or `"invalid"`.

    The same structural rule as `customer-whatsapp-auth._loggable_waba`, deliberately:
    E.164 permits at most 15 digits, so an all-ASCII-digit value of 16 or more
    characters cannot be a phone number. Both WABA ids and both Meta phone-number ids
    in this account are 16 digits, so the rule covers either kind of id - which is why
    it also guards the `senderPhoneId` field below.

    It matters here specifically because a masked phone suffix is ambiguous in this
    account (`+918100640044` the QA recipient vs `+919903300044` a business sender), so
    a mistyped env value must never be echoed as though it were an id.

    Not imported from that handler because it is packaged `standalone=True` and nothing
    is importable from it. Only this print guard is restated; the mapping itself is
    shared.

    `ch in "0123456789"` rather than `str.isdigit()`, for the same reason
    `normalise_phone` uses it: `isdigit()` is true for 128 non-ASCII codepoints, and a
    digit-shaped lookalike is not a safe id to print.
    """
    text = str(value or "")
    if len(text) >= 16 and all(ch in "0123456789" for ch in text):
        return text
    return "invalid"


def _sender_phone_id() -> str:
    return str(os.environ.get("META_PHONE_NUMBER_ID", DEFAULT_SENDER_PHONE_ID)).strip()


def _sender_waba() -> str:
    """The WABA this function actually delivers from, or `''` when undeterminable.

    Derived from the Meta phone id every secure-file send leaves from
    (`whatsapp_delivery.META_PHONE_NUMBER_ID`), through the shared map. Deriving rather
    than hardcoding is what makes repointing this function at WABA2's number move the
    stamp with it, instead of leaving customers stamped WABA1 and waiting for a code
    from a number they have never messaged.

    `META_WABA_ID` survives as an override - production sets it, the manifest declares
    it, and `provision_secure_files_api.py` writes it - but a *validated* one. An
    override the shared map does not recognise is a misconfiguration, not an
    instruction, so it is logged and ignored rather than stamped.

    Read per call, not captured at import, for the same reason `_payment_enabled` is: a
    repoint that only takes effect once every warm sandbox recycles is not a repoint.
    """
    derived = waba_for_meta_phone(_sender_phone_id())
    override = str(os.environ.get("META_WABA_ID", "")).strip()
    if override and override != derived:
        if override in KNOWN_WABA_IDS:
            return override
        logger.warning(
            json.dumps(
                {
                    "event": "secure_files_waba_override_rejected",
                    "wabaId": _loggable_waba(override),
                }
            )
        )
    return derived

PRICE_PAISE = int(os.environ.get("SECURE_FILE_PRICE_PAISE", "4900"))  # Rs. 49
UPLOAD_URL_TTL = int(os.environ.get("UPLOAD_URL_TTL_SECONDS", "900"))
# Web redeem: the browser follows this immediately, so it can be very short.
DOWNLOAD_URL_TTL = int(os.environ.get("DOWNLOAD_URL_TTL_SECONDS", "60"))
# Direct links are bearer capabilities. Keep the read window bounded; a customer
# can use authenticated Vault access after the delivery link expires.
WHATSAPP_LINK_TTL = max(60, min(900, int(os.environ.get("WHATSAPP_LINK_TTL_SECONDS", "900"))))
GRANT_TTL = int(os.environ.get("GRANT_TTL_SECONDS", "1800"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))

_s3 = None
_ddb = None
_cognito = None


def _s3_client():
    global _s3
    if _s3 is None:
        # SigV4 + regional endpoint, so presigned URLs are valid in this region.
        from botocore.client import Config

        _s3 = boto3.client(
            "s3",
            region_name=REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
    return _s3


def _table(name: str):
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=REGION)
    return _ddb.Table(name)


def _cognito_client():
    global _cognito
    if _cognito is None:
        _cognito = boto3.client("cognito-idp", region_name=REGION)
    return _cognito


def _payment_enabled() -> bool:
    """Read per call, not captured at import.

    A posture switch that only takes effect once every warm sandbox recycles is
    not much of a switch.
    """
    return str(os.environ.get("SECURE_FILES_PAYMENT_ENABLED", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _dropdocs_attach_enabled() -> bool:
    """Whether the Drop Docs attach route answers at all. Defaults OFF.

    Read per call for the same reason as ``_payment_enabled``: a posture switch that only
    takes effect once every warm sandbox recycles is not much of a switch. There is no UI
    for this in Phase O-2 - ``/drop-docs`` sells the service, and the route that registers
    a document exists but is switched off.
    """
    return str(os.environ.get("DROPDOCS_ATTACH_ENABLED", "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ── phone handling ────────────────────────────────────────────────────────────

def normalise_phone(raw: str) -> str:
    """Digits-only E.164, matching the OTP Lambda's own normalisation.

    A 10-digit Indian mobile is prefixed with 91 so that the number an admin types
    and the number Cognito holds cannot drift apart - if they did, the customer
    would authenticate successfully and then own nothing.
    """
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    if len(digits) == 10 and digits[:1] in "6789":
        digits = "91" + digits
    if not 10 <= len(digits) <= 15:
        raise ValueError("invalid phone number")
    return digits


def mask_phone(raw: str) -> str:
    """Last four only. Never log a full number."""
    try:
        digits = normalise_phone(raw)
    except ValueError:
        return "****"
    return ("*" * max(0, len(digits) - 4)) + digits[-4:]


# ── identity ──────────────────────────────────────────────────────────────────

def _jwt_claims_unverified(token: str) -> Dict[str, Any]:
    """Decode a JWT payload WITHOUT verifying it.

    Safe only because every caller below has already had AWS verify the token via
    ``get_user``. Once that succeeds the token is known to be genuine and
    unmodified, so its claims can be trusted. Never call this on its own.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _bearer(event: Dict[str, Any]) -> str:
    headers = event.get("headers") or {}
    raw = headers.get("authorization") or headers.get("Authorization") or ""
    return raw[7:].strip() if raw[:7].lower() == "bearer " else raw.strip()


def _customer_identity(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve the calling customer, or None.

    ``get_user`` is pool-agnostic: it validates the access token's signature and
    expiry against whichever pool issued it. That alone is not authorisation - a
    token from the admin pool would also pass. So the issuer claim is checked
    afterwards, which is sound precisely because ``get_user`` has already proven
    the token unmodified.
    """
    token = _bearer(event)
    if not token:
        return None
    try:
        user = _cognito_client().get_user(AccessToken=token)
    except ClientError:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning(json.dumps({"event": "customer_auth_error", "error": type(exc).__name__}))
        return None

    if _jwt_claims_unverified(token).get("iss") != CUSTOMER_POOL_ISSUER:
        logger.warning(json.dumps({"event": "customer_auth_wrong_pool"}))
        return None

    attrs = {a["Name"]: a["Value"] for a in user.get("UserAttributes", [])}
    phone = attrs.get("phone_number", "")
    if not phone or attrs.get('phone_number_verified') != 'true' or not attrs.get('sub'):
        return None
    try:
        return {
            "username": user.get("Username", ""),
            "phone": normalise_phone(phone),
            # The Cognito `sub`, which is what `customer_auth` files every customer-owned
            # row under. Additive: every existing route here authorises on `phone` and is
            # unaffected. The Drop Docs arm needs it because a REQ# row's owner IS the sub,
            # and this pool's Username is the E.164 rather than the sub.
            "subject": attrs.get("sub", ""),
        }
    except ValueError:
        return None


# ── responses ─────────────────────────────────────────────────────────────────

def _not_registered(origin: str) -> Dict[str, Any]:
    """The single refusal used for wrong-owner AND nonexistent-file.

    Byte-identical in both cases on purpose. Returning 404 for one and 403 for the
    other would let a caller probe which file ids exist.
    """
    return cors_response(
        403,
        {
            "error": "NOT_REGISTERED",
            "message": "This file is not registered to your number.",
        },
        origin,
    )


def _decimal_safe(obj: Any) -> Any:
    """DynamoDB hands back Decimal; JSON does not want it."""
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_safe(v) for v in obj]
    return obj


def _public_file(item: Dict[str, Any], *, admin: bool) -> Dict[str, Any]:
    """Shape a record for the client. The S3 key never leaves the backend."""
    out = {
        "fileId": item.get("fileId"),
        "displayName": item.get("displayName"),
        "originalFilename": item.get("originalFilename"),
        "contentType": item.get("contentType"),
        "sizeBytes": item.get("sizeBytes"),
        "pricePaise": item.get("pricePaise"),
        "status": item.get("status"),
        "createdAt": item.get("createdAt"),
        "downloadCount": item.get("downloadCount", 0),
        "vaultPaymentStatus": item.get('vaultPaymentStatus'),
        "vaultOrderNumber": item.get('vaultOrderNumber'),
        "vaultRequestNumber": item.get('vaultRequestNumber'),
        # "pdf" / "image" arrive as a WhatsApp attachment; "link" goes out as a URL.
        "deliverable": item.get("deliverable", "unknown"),
    }
    if admin:
        out["ownerName"] = item.get("ownerName")
        out["ownerPhoneMasked"] = mask_phone(item.get("ownerPhone", ""))
        out["uploadedBy"] = item.get("uploadedBy")
    return _decimal_safe(out)


# ── admin: create the customer and the upload slot ────────────────────────────

def _existing_stamp(client, username: str) -> str:
    """The `custom:partner_waba_id` already on this user, or `''` if it has none.

    A read failure raises `UnsafeWabaStamp` instead of defaulting either way, because
    both defaults are wrong. Treating an unread value as absent re-creates the bug -
    it stamps this function's own WABA over a customer who belongs to the other one.
    Treating it as present leaves a user who may have no stamp at all, which the OTP
    gate denies permanently. Not knowing is a reason to stop, not to pick.
    """
    try:
        user = client.admin_get_user(UserPoolId=CUSTOMER_POOL_ID, Username=username)
    except Exception as exc:  # noqa: BLE001
        # type only: an exception message can carry data we did not construct
        logger.error(
            json.dumps(
                {
                    "event": "secure_files_waba_stamp_unreadable",
                    "error": type(exc).__name__,
                }
            )
        )
        raise UnsafeWabaStamp("existing customer's WABA stamp could not be read") from exc
    for attr in user.get("UserAttributes") or []:
        if attr.get("Name") == "custom:partner_waba_id":
            return str(attr.get("Value") or "").strip()
    return ""


def _attrs_for_existing(client, username: str, attrs: list, sender_waba: str) -> list:
    """The attribute list to send to an EXISTING customer - stamp preserved if valid.

    `attrs` is the create-path list; everything except the WABA stamp carries over
    unchanged. The stamp is decided here:

    * already a WABA the shared map knows -> **left untouched**, by omitting the
      attribute from the update entirely. `admin_update_user_attributes` only writes
      what it is given, so omission is the preserve.
    * absent, empty, or a value the map does not know -> stamped with `sender_waba`.
      An unrecognised value is already a permanent OTP denial, so replacing it with a
      mapped id strictly improves that customer's position and cannot misroute
      anything that was working.
    """
    keep = [a for a in attrs if a["Name"] != "custom:partner_waba_id"]
    existing = _existing_stamp(client, username)

    if existing in KNOWN_WABA_IDS:
        logger.info(
            json.dumps(
                {
                    "event": "secure_files_waba_stamp_preserved",
                    "wabaId": _loggable_waba(existing),
                }
            )
        )
        if existing != sender_waba:
            # Correct, and must stay visible rather than be "repaired". The file and
            # payment request leave from this function's only sender; the customer's
            # sign-in code rightly stays on their own WABA. Rewriting their identity
            # so the two agree is exactly the defect being fixed.
            logger.info(
                json.dumps(
                    {
                        "event": "secure_files_cross_waba_delivery",
                        "customerWaba": _loggable_waba(existing),
                        "senderWaba": _loggable_waba(sender_waba),
                    }
                )
            )
        return keep

    logger.info(
        json.dumps(
            {
                "event": "secure_files_waba_stamp_applied",
                "wabaId": _loggable_waba(sender_waba),
                "reason": "existing_stamp_unusable",
            }
        )
    )
    return keep + [{"Name": "custom:partner_waba_id", "Value": sender_waba}]


def _ensure_customer_user(phone: str, name: str) -> str:
    """Create or update the phone-keyed customer so WhatsApp OTP can reach them.

    Three details matter and each has a reason:

    * ``MessageAction='SUPPRESS'`` - Cognito must not send an invite. There is no
      email on these users and an SMS invite would both cost money and bypass the
      WhatsApp channel this flow is built on.
    * a permanent random password - ``admin_create_user`` leaves the user in
      ``FORCE_CHANGE_PASSWORD``, which blocks CUSTOM_AUTH. Setting a permanent
      password moves them to ``CONFIRMED``. Nobody ever learns it; the only way in
      is a WhatsApp OTP. It is generated here, used once, and never logged or
      returned - putting it in a log or a response would turn a passwordless
      design into a credential leak.
    * ``custom:partner_waba_id`` - the OTP trigger raises ``PermissionError`` if
      this value is not one its ``OTP_WABA_MAP`` knows, so an unstamped user could
      never receive a code. It is derived from the sender (``_sender_waba``), and
      on an **existing** user an already-valid stamp is preserved rather than
      overwritten. That second half is the whole point: a customer
      ``partner-onboarding`` legitimately provisioned on WABA2 used to be converted
      to WABA1 by one operator upload, after which their sign-in code arrived from a
      business number they have never messaged.

    Raises ``UnsafeWabaStamp`` rather than guessing a WABA. Creating the user anyway
    would mint a CONFIRMED, phone-keyed, group-joined identity that can never receive
    a code, while the upload appears to succeed and the customer reaches a code screen
    no code will satisfy - a state visible from no surface we have. Refusing the
    upload is recoverable in seconds.
    """
    client = _cognito_client()
    e164 = "+" + phone

    sender_waba = _sender_waba()
    if not sender_waba:
        # Checked BEFORE admin_create_user, not repaired afterwards: the stamp is one
        # element of a single create call, so there is no "stamp it later" here.
        logger.error(
            json.dumps(
                {
                    "event": "secure_files_waba_undeterminable",
                    "senderPhoneId": _loggable_waba(_sender_phone_id()),
                }
            )
        )
        raise UnsafeWabaStamp("sender phone id does not resolve to a known WABA")

    attrs = [
        {"Name": "phone_number", "Value": e164},
        {"Name": "phone_number_verified", "Value": "true"},
        {"Name": "custom:partner_waba_id", "Value": sender_waba},
    ]
    if name:
        attrs.append({"Name": "name", "Value": name[:128]})

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
        logger.info(
            json.dumps(
                {
                    "event": "secure_files_waba_stamp_applied",
                    "wabaId": _loggable_waba(sender_waba),
                    "reason": "new_user",
                }
            )
        )
    except client.exceptions.UsernameExistsException:
        username = e164
        client.admin_update_user_attributes(
            UserPoolId=CUSTOMER_POOL_ID,
            Username=username,
            UserAttributes=_attrs_for_existing(client, username, attrs, sender_waba),
        )

    try:
        client.admin_add_user_to_group(
            UserPoolId=CUSTOMER_POOL_ID, Username=username, GroupName=PARTNER_GROUP
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            json.dumps({"event": "customer_group_add_failed", "error": type(exc).__name__})
        )
    return username


def provision_customer_login(e164: str) -> Tuple[bool, str]:
    """Create the Cognito login for a CRM-created contact. Idempotent. `(ok, detail)`.

    Reached ONLY by async invoke from `core/contacts`, which is gated by
    `CRM_PROVISION_CUSTOMER_LOGIN` (default off). It exists here rather than there because THIS
    role already holds `cognito-idp:AdminCreateUser` scoped to the customer pool
    (`scripts/provision_secure_files_api.py`, Sid `CustomerPoolOnly`), and the CRM's role is
    shared across the fleet - widening it would widen every other function too.

    IT REUSES `_ensure_customer_user` RATHER THAN RESTATING IT. Three details there are
    load-bearing and easy to get wrong in a second copy: `MessageAction=SUPPRESS` (no SMS invite
    on a user with no email), a permanent random password from `secrets` so the user is CONFIRMED
    rather than stuck in FORCE_CHANGE_PASSWORD and CUSTOM_AUTH can run, and
    `custom:partner_waba_id`, without which the OTP trigger raises `PermissionError` and the code
    never arrives. A fork of that function is a fork of all three.

    A CONFLICT IS SUCCESS. The whole point is that a contact can be saved twice: `AliasExists`
    and `UsernameExists` both mean the login this call was asked to guarantee already exists.
    `_ensure_customer_user` already absorbs `UsernameExistsException` itself (it updates the
    attributes instead); `AliasExistsException` is caught here because a phone alias can collide
    with a DIFFERENT username, which that function does not handle.

    USER-LEVEL ADMIN APIS ONLY - no `UpdateUserPool` anywhere in this path. See
    `core/contacts._provision_customer_login` for the 2026-09-28 incident that makes that
    sentence worth writing down.
    """
    text = str(e164 or "")
    digits = text[1:] if text.startswith("+") else text
    # ASCII only, deliberately: `str.isdigit()` is true for an Arabic-Indic digit, which would
    # reach `Username` and reserve an identity indistinguishable to a human from the real one.
    if not digits or not all(ch in "0123456789" for ch in digits):
        return False, "not an E.164 phone"
    if not 8 <= len(digits) <= 15:
        return False, "not an E.164 phone"

    client = _cognito_client()
    try:
        _ensure_customer_user(digits, "")
    except (client.exceptions.AliasExistsException,
            client.exceptions.UsernameExistsException):
        return True, "exists"
    except Exception as exc:  # noqa: BLE001
        # Type only: a Cognito error message can echo the username, which is the phone number.
        logger.error(json.dumps({"event": "customer_login_provision_failed",
                                 "error": type(exc).__name__}))
        return False, type(exc).__name__
    return True, "provisioned"


def _safe_extension(filename: str) -> str:
    """A short, conservative extension, or none.

    Taken from the original name only so the download arrives with a sensible
    suffix. Anything unexpected is dropped rather than sanitised, because the
    extension ends up in an S3 key.
    """
    _, _, tail = str(filename or "").rpartition(".")
    if tail and tail != filename and 1 <= len(tail) <= 8 and tail.isalnum():
        return "." + tail.lower()
    return ""


def _upload_init(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    body = json.loads(event.get("body") or "{}")
    name = str(body.get("name") or "").strip()
    display_name = str(body.get("displayName") or "").strip()
    filename = str(body.get("originalFilename") or "").strip()
    content_type = str(body.get("contentType") or "application/octet-stream").strip()
    size = int(body.get("sizeBytes") or 0)

    try:
        phone = normalise_phone(body.get("mobile"))
    except ValueError:
        return cors_response(400, {"error": "A valid mobile number is required"}, origin)
    if not name:
        return cors_response(400, {"error": "Customer name is required"}, origin)
    if not filename:
        return cors_response(400, {"error": "originalFilename is required"}, origin)
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        return cors_response(
            400, {"error": f"sizeBytes must be between 1 and {MAX_UPLOAD_BYTES}"}, origin
        )

    try:
        username = _ensure_customer_user(phone, name)
    except UnsafeWabaStamp:
        # Already logged with the reason. Refuse the upload rather than provision a
        # customer who could never receive a sign-in code. The body is generic: which
        # WABA is misconfigured is an operator-console fact, not a browser one.
        return cors_response(
            503,
            {
                "error": "CUSTOMER_PROVISIONING_UNAVAILABLE",
                "message": "Customer provisioning is unavailable. Please retry shortly.",
            },
            origin,
        )

    # Bind at creation to the server-resolved Cognito subject, never to a
    # browser-provided customer ID or a future account that inherits this phone.
    try:
        customer = _cognito_client().admin_get_user(
            UserPoolId=CUSTOMER_POOL_ID, Username=username)
        attributes = {a['Name']: a['Value'] for a in customer.get('UserAttributes', [])}
        owner_customer_id = attributes.get('sub')
        if (not owner_customer_id or not customer.get('Enabled', True)
                or normalise_phone(attributes.get('phone_number')) != phone):
            raise ValueError('customer ownership unavailable')
    except Exception:
        return cors_response(503, {'error': 'CUSTOMER_PROVISIONING_UNAVAILABLE'}, origin)

    file_id = f"{uuid.uuid4().hex}-{uuid.uuid4().hex}"
    basename = f"wecare-digital-{file_id}{_safe_extension(filename)}"
    key = UPLOAD_PREFIX + basename
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    _table(FILES_TABLE).put_item(
        Item={
            "fileId": file_id,
            "s3Key": key,
            "ownerPhone": phone,
            "ownerCustomerId": owner_customer_id,
            "ownerName": name,
            "cognitoUsername": username,
            "displayName": display_name or filename,
            "originalFilename": filename,
            "contentType": content_type,
            "sizeBytes": size,
            "pricePaise": PRICE_PAISE,
            # Decided at confirm time, once the real object is measured rather than
            # trusted from the browser: "pdf", "image", or "link" when the type
            # cannot be opened inline on WhatsApp.
            "deliverable": "unknown",
            # pending until the object is actually in the bucket, so a failed
            # browser upload cannot leave a file the customer can be charged for
            "status": "pending",
            "downloadCount": 0,
            "uploadedBy": (event.get("_auth") or {}).get("username", ""),
            "createdAt": now,
        }
    )

    upload_url = _s3_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=UPLOAD_URL_TTL,
    )

    logger.info(
        json.dumps(
            {
                "event": "secure_file_upload_init",
                "fileId": file_id,
                "ownerPhone": mask_phone(phone),
                "sizeBytes": size,
            }
        )
    )
    return cors_response(
        201,
        {
            "fileId": file_id,
            "uploadUrl": upload_url,
            "expiresInSeconds": UPLOAD_URL_TTL,
            "contentType": content_type,
        },
        origin,
    )


def _classify_delivery(content_type: str, size: int) -> str:
    """Whether this file can be opened inline on WhatsApp: "pdf", "image" or "link".

    Judged on the object S3 actually holds, not on what the browser claimed, because
    the browser's Content-Type is a hint and a wrong one would only surface when a
    paying customer received something they could not open.
    """
    kind = DELIVERABLE_TYPES.get((content_type or "").split(";")[0].strip().lower())
    if kind == "image" and size <= MAX_IMAGE_BYTES:
        return "image"
    if kind == "pdf" and size <= MAX_DOCUMENT_BYTES:
        return "pdf"
    # Too large, or a type that would arrive as an unopenable blob. Still sellable -
    # it just goes out as a download link rather than an attachment.
    return "link"


def _upload_confirm(file_id: str, origin: str) -> Dict[str, Any]:
    """Flip pending -> active, but only after proving the object is really there.

    Also creates the ``d/`` rendition when the file can be delivered over WhatsApp.
    That copy is server-side, so the bytes never travel through this function.
    """
    table = _table(FILES_TABLE)
    item = table.get_item(Key={"fileId": file_id}).get("Item")
    if not item:
        return cors_response(404, {"error": "Unknown fileId"}, origin)

    upload_key = item["s3Key"]
    try:
        head = _s3_client().head_object(Bucket=BUCKET, Key=upload_key)
    except ClientError:
        return cors_response(
            409, {"error": "Upload not found in storage; retry the upload"}, origin
        )

    size = int(head["ContentLength"])
    # Prefer what S3 recorded over what the browser asserted at upload-init.
    content_type = head.get("ContentType") or item.get("contentType") or ""
    deliverable = _classify_delivery(content_type, size)

    delivery_key = ""
    if deliverable in ("pdf", "image"):
        delivery_key = DELIVER_PREFIX + upload_key.split("/")[-1]
        try:
            _s3_client().copy_object(
                Bucket=BUCKET,
                Key=delivery_key,
                CopySource={"Bucket": BUCKET, "Key": upload_key},
                ContentType=content_type,
                MetadataDirective="REPLACE",
            )
        except ClientError as exc:
            # Not fatal: the file is still sellable as a download link. Record the
            # downgrade rather than failing an upload that otherwise succeeded.
            logger.warning(
                json.dumps({"event": "delivery_copy_failed", "fileId": file_id,
                            "error": exc.response["Error"]["Code"]})
            )
            deliverable, delivery_key = "link", ""

    table.update_item(
        Key={"fileId": file_id},
        UpdateExpression=(
            "SET #s = :active, sizeBytes = :size, contentType = :ct, "
            "deliverable = :d, deliveryKey = :dk"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":active": "active", ":size": size, ":ct": content_type,
            ":d": deliverable, ":dk": delivery_key,
        },
    )
    logger.info(
        json.dumps({"event": "secure_file_active", "fileId": file_id,
                    "deliverable": deliverable, "sizeBytes": size})
    )
    return cors_response(
        200,
        {"fileId": file_id, "status": "active", "sizeBytes": size,
         "deliverable": deliverable},
        origin,
    )


def _admin_list(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Every file, or one customer's, depending on ?mobile=."""
    params = event.get("queryStringParameters") or {}
    table = _table(FILES_TABLE)

    mobile = params.get("mobile")
    if mobile:
        try:
            phone = normalise_phone(mobile)
        except ValueError:
            return cors_response(400, {"error": "Invalid mobile number"}, origin)
        # the GSI is the whole point: one customer's files without a scan
        result = table.query(
            IndexName="owner-created-index",
            KeyConditionExpression="ownerPhone = :p",
            ExpressionAttributeValues={":p": phone},
            ScanIndexForward=False,
            Limit=100,
        )
    else:
        result = table.scan(Limit=100)

    items = sorted(
        result.get("Items", []), key=lambda i: str(i.get("createdAt", "")), reverse=True
    )
    return cors_response(
        200,
        {"files": [_public_file(i, admin=True) for i in items], "count": len(items)},
        origin,
    )


def _admin_revoke(file_id: str, origin: str) -> Dict[str, Any]:
    """Revoke rather than delete: the audit trail of who was charged survives."""
    try:
        _table(FILES_TABLE).update_item(
            Key={"fileId": file_id},
            UpdateExpression="SET #s = :revoked",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":revoked": "revoked"},
            ConditionExpression="attribute_exists(fileId)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return cors_response(404, {"error": "Unknown fileId"}, origin)
        raise
    return cors_response(200, {"fileId": file_id, "status": "revoked"}, origin)


# ── durable paid entitlement + renewable transport sessions ──────────────────

ENTITLEMENT_PREFIX = "vault-entitlement#"
SESSION_PREFIX = "vault-session#"


def _entitlement_id(customer_id: str, file_id: str) -> str:
    return ENTITLEMENT_PREFIX + str(customer_id) + "#" + str(file_id)


def _ensure_entitlement(grant: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Create/read non-TTL paid entitlement from authoritative paid evidence."""
    customer_id = str(grant.get("customerId") or "")
    file_id = str(grant.get("fileId") or "")
    owner_phone = str(grant.get("ownerPhone") or "")
    if not customer_id or not file_id or not owner_phone or not grant.get("paid"):
        return None
    eid = _entitlement_id(customer_id, file_id)
    table = _table(GRANTS_TABLE)
    existing = table.get_item(Key={"grantId": eid}, ConsistentRead=True).get("Item") or {}
    if existing:
        if (existing.get("recordType") == "VAULT_ENTITLEMENT"
                and existing.get("entitlementState") == "ACTIVE"
                and existing.get("customerId") == customer_id
                and existing.get("fileId") == file_id):
            return existing
        return None
    now = int(time.time())
    entitlement = {
        "grantId": eid, "recordType": "VAULT_ENTITLEMENT", "entitlementState": "ACTIVE",
        "customerId": customer_id, "fileId": file_id, "ownerPhone": owner_phone,
        "sourceGrantId": str(grant.get("grantId") or ""),
        "orderId": str(grant.get("orderId") or ""),
        "paymentId": str(grant.get("paymentId") or ""),
        "paidAmountPaise": int(grant.get("paidAmountPaise") or grant.get("amountPaise") or 0),
        "reference": str(grant.get("reference") or ""),
        "requestId": str(grant.get("requestId") or ""),
        "createdAt": now, "paidAt": int(grant.get("paidAt") or now),
    }
    try:
        table.put_item(Item=entitlement, ConditionExpression="attribute_not_exists(grantId)")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        entitlement = table.get_item(Key={"grantId": eid}, ConsistentRead=True).get("Item") or {}
    return entitlement if entitlement.get("entitlementState") == "ACTIVE" else None


def _active_entitlement(access_id: str, file_id: str,
                        identity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve entitlement or lazily migrate a historical paid grant, even if consumed."""
    row = _table(GRANTS_TABLE).get_item(Key={"grantId": access_id}, ConsistentRead=True).get("Item") or {}
    if not row:
        return None
    if row.get("recordType") != "VAULT_ENTITLEMENT":
        row = _ensure_entitlement(row) or {}
    if (row.get("recordType") != "VAULT_ENTITLEMENT"
            or row.get("entitlementState") != "ACTIVE"
            or row.get("fileId") != file_id
            or row.get("ownerPhone") != identity.get("phone")
            or not identity.get("subject")
            or row.get("customerId") != identity.get("subject")):
        return None
    return row


def _issue_download_session(entitlement: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Record one expiring transport attempt without changing financial entitlement."""
    now = int(time.time())
    session_id = SESSION_PREFIX + uuid.uuid4().hex
    _table(GRANTS_TABLE).put_item(Item={
        "grantId": session_id, "recordType": "VAULT_DOWNLOAD_SESSION",
        "entitlementId": entitlement["grantId"], "customerId": entitlement["customerId"],
        "fileId": entitlement["fileId"], "ownerPhone": entitlement["ownerPhone"],
        "createdAt": now, "expiresAt": now + int(DOWNLOAD_URL_TTL),
    })
    return {
        "downloadUrl": _download_url(item),
        "expiresInSeconds": DOWNLOAD_URL_TTL,
        "downloadSessionId": session_id,
        "entitlementId": entitlement["grantId"],
    }


# ── customer: list, order, download ───────────────────────────────────────────

def _customer_list(identity: Dict[str, Any], origin: str) -> Dict[str, Any]:
    result = _table(FILES_TABLE).query(
        IndexName="owner-created-index",
        KeyConditionExpression="ownerPhone = :p",
        ExpressionAttributeValues={":p": identity["phone"]},
        ScanIndexForward=False,
        Limit=100,
    )
    items = []
    for projected in result.get('Items', []):
        i = _table(FILES_TABLE).get_item(Key={'fileId': projected['fileId']}, ConsistentRead=True).get('Item') or {}
        if (i.get('status') != 'active' or i.get('ownerPhone') != identity['phone']
                or not identity.get('subject') or i.get('ownerCustomerId') != identity['subject']):
            continue
        view = _public_file(i, admin=False)
        access_id = str(i.get('vaultEntitlementId') or i.get('vaultAccessGrantId') or '')
        if access_id:
            entitlement = _active_entitlement(access_id, i['fileId'], identity)
            if entitlement:
                view['paidEntitlementId'] = entitlement['grantId']
                view['paidGrantId'] = entitlement['grantId']  # old website bundles
                view['deliveryStatus'] = 'READY'
        items.append(view)
    return cors_response(
        200,
        {
            "files": items,
            "count": len(items),
            "pricePaise": PRICE_PAISE,
        },
        origin,
    )


def _owned_active_file(file_id: str, identity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The record, but only if this caller owns it and it is active.

    Every failure mode returns None so callers cannot tell them apart.
    """
    item = _table(FILES_TABLE).get_item(Key={"fileId": file_id}).get("Item")
    if not item or item.get("status") != "active":
        return None
    if item.get("ownerPhone") != identity["phone"]:
        return None
    if not identity.get('subject') or item.get('ownerCustomerId') != identity['subject']:
        return None
    return item


def _create_order(file_id: str, identity: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Razorpay Checkout on the web. FALLBACK, not the primary path.

    Nothing in the UI calls this - the page uses ``/whatsapp-pay``. It is kept
    deliberately rather than left behind as an oversight: it is the only route by which
    a customer who has already paid can collect a file when WhatsApp delivery keeps
    failing. ``scripts/reconcile_file_deliveries.py`` retries the send, but a
    permanently unreachable number - blocked, ported away, WhatsApp removed - cannot be
    retried into working, and without this the only recovery is an operator presigning
    an object by hand.

    See docs/SECURE-FILE-SHARING.md. If it is ever removed, a replacement recovery path
    has to exist first.
    """
    item = _owned_active_file(file_id, identity)
    if not item:
        return _not_registered(origin)

    if not _payment_enabled():
        # Refuse loudly rather than silently granting. Nothing here contacts
        # Razorpay or reads a credential while the flag is off.
        return cors_response(
            503,
            {
                "error": "PAYMENT_DISABLED",
                "message": "Paid downloads are not enabled yet.",
                "pricePaise": int(item.get("pricePaise", PRICE_PAISE)),
            },
            origin,
        )

    from razorpay_orders import create_order  # imported lazily: only needed when live

    order = create_order(
        amount_paise=int(item.get("pricePaise", PRICE_PAISE)),
        receipt=f"dl_{file_id[:24]}",
        notes={"fileId": file_id, "purpose": "secure_file_download"},
    )

    now = int(time.time())
    grant_id = uuid.uuid4().hex
    _table(GRANTS_TABLE).put_item(
        Item={
            "grantId": grant_id,
            "fileId": file_id,
            "ownerPhone": identity["phone"],
            "customerId": identity['subject'],
            "orderId": order["id"],
            "amountPaise": int(item.get("pricePaise", PRICE_PAISE)),
            # paid flips only in the webhook, never from a client callback
            "paid": False,
            "consumed": False,
            "createdAt": now,
            "expiresAt": now + GRANT_TTL,
        }
    )
    return cors_response(
        201,
        {
            "grantId": grant_id,
            "orderId": order["id"],
            "amountPaise": int(item.get("pricePaise", PRICE_PAISE)),
            "currency": "INR",
            "keyId": order.get("key_id", ""),
        },
        origin,
    )


def _confirm_with_razorpay(grant: Dict[str, Any], via: str = "webhook") -> Tuple[bool, str]:
    """Ask Razorpay whether this grant's order really has a captured payment.

    THIS is what makes the webhook secret worthless to an attacker.

    Previously a signature-verified webhook set ``paid`` directly, so anyone holding the
    webhook secret - which is readable from this repository's public git history - could
    forge a ``payment.captured`` event and mint themselves a free download. Rotating the
    secret would fix that; so does removing the secret from the decision entirely, and
    that fix does not expire.

    Razorpay's API is now the only thing that can mark a grant paid. A forged webhook
    reaches this function and is answered "no captured payment", which is the same answer
    an attacker gets by not paying at all.

    The trade is availability for integrity: if Razorpay's API is unreachable a real
    payment is not granted immediately. That is recoverable -
    ``scripts/reconcile_file_deliveries.py`` re-runs this path - whereas a forged grant
    is not recoverable, because the file has already left.

    Only ``captured`` counts. ``authorized`` is money held, not taken.

    ``via`` is recorded on the grant purely as an operational signal. ``reconcile`` means
    the sweep got there before the webhook did, which is worth noticing because it
    usually means the webhook subscription is broken.
    """
    if not _payment_enabled():
        return False, "payments disabled"

    order_id = str(grant.get("orderId") or "")
    if not order_id:
        return False, "grant has no orderId"
    if grant.get("consumed"):
        return False, "grant already consumed"

    try:
        from razorpay_orders import order_is_paid

        paid, payment_id, amount_paise = order_is_paid(order_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            json.dumps({"event": "razorpay_confirm_failed", "error": type(exc).__name__})
        )
        return False, "could not reach Razorpay"

    if not paid:
        # Either not paid yet, or a forged event. Indistinguishable here, and it does not
        # matter: both mean "do not grant".
        return False, "no captured payment for this order"

    try:
        _table(GRANTS_TABLE).update_item(
            Key={"grantId": grant["grantId"]},
            UpdateExpression=(
                "SET paid = :true, paymentId = :pid, paidAmountPaise = :amt, "
                "paidAt = :now, paidVia = :via"
            ),
            ConditionExpression="attribute_exists(grantId) AND paid = :false",
            ExpressionAttributeValues={
                ":true": True,
                ":false": False,
                ":pid": payment_id,
                ":amt": int(amount_paise),
                ":now": int(time.time()),
                ":via": via,
            },
        )
    except ClientError:
        # Already paid by a concurrent run. That is success, not failure.
        pass
    return True, payment_id


def confirm_and_deliver(order_id: str) -> Tuple[bool, str]:
    """Confirm a payment with Razorpay and, if real, deliver the file.

    Entry point for the webhook. It is given only an order id, so there is no way for a
    caller to name a file or a recipient - everything else is looked up from the grant
    that this system wrote when it created the order.
    """
    found = _table(GRANTS_TABLE).query(
        IndexName="order-index",
        KeyConditionExpression="orderId = :o",
        ExpressionAttributeValues={":o": order_id},
        Limit=1,
    ).get("Items") or []
    if not found:
        # Expected when a grant expired via TTL before payment completed, and also what a
        # forged event for an unknown order looks like.
        return False, "no grant for that order"

    grant = found[0]
    if not grant.get("paid"):
        ok, detail = _confirm_with_razorpay(grant)
        if not ok:
            logger.warning(
                json.dumps(
                    {
                        "event": "payment_not_confirmed",
                        "alert": "WEBHOOK_CLAIM_UNVERIFIED",
                        "orderId": order_id,
                        "detail": detail,
                    }
                )
            )
            return False, detail

    refreshed = _table(GRANTS_TABLE).get_item(
        Key={"grantId": grant["grantId"]}, ConsistentRead=True).get("Item") or grant
    if not _ensure_entitlement(refreshed):
        return False, "paid entitlement could not be established"
    if grant.get("channel") != "whatsapp":
        return True, "confirmed; web channel collects by renewable entitlement"
    return deliver_over_whatsapp(str(grant["grantId"]))


def _reconcile_grant(grant_id: str, file_id: str, identity: Dict[str, Any]) -> bool:
    """Mark an unpaid grant paid if Razorpay says the order was actually captured.

    The safety net for a webhook that never arrives. Returns True only when the grant
    was genuinely unspent, belongs to this caller and this file, and Razorpay confirms
    a captured payment.

    Deliberately narrow. It refuses to touch a grant that is already ``consumed``, so
    it cannot be used to replay a spent download. The ownership checks live here; the
    actual payment decision and the write are delegated to ``_confirm_with_razorpay``,
    which is the only function in this system that may set ``paid``.
    """
    if not _payment_enabled():
        return False

    table = _table(GRANTS_TABLE)
    grant = table.get_item(Key={"grantId": grant_id}).get("Item")

    # Every mismatch returns False, so this can never widen who may download what.
    if not grant:
        return False
    if grant.get("fileId") != file_id or grant.get("ownerPhone") != identity["phone"]:
        return False
    if not identity.get('subject') or grant.get('customerId') != identity['subject']:
        return False
    if grant.get("paid"):
        return False

    ok, _detail = _confirm_with_razorpay(grant, via="reconcile")
    if not ok:
        return False

    logger.info(
        json.dumps(
            {
                "event": "grant_reconciled_from_razorpay",
                "alert": "WEBHOOK_MAY_NOT_BE_SUBSCRIBED",
                "fileId": file_id,
            }
        )
    )
    return True


def _redeem_after_reconcile(
    file_id: str, grant_id: str, identity: Dict[str, Any],
    item: Dict[str, Any], origin: str,
):
    grant = _table(GRANTS_TABLE).get_item(
        Key={"grantId": grant_id}, ConsistentRead=True).get("Item") or {}
    entitlement = _ensure_entitlement(grant)
    if not entitlement:
        return cors_response(
            403, {"error": "ACCESS_NOT_AUTHORIZED",
                  "message": "Paid access could not be verified. Please contact support; do not pay again."},
            origin)
    entitlement = _active_entitlement(entitlement["grantId"], file_id, identity)
    if not entitlement:
        return _not_registered(origin)
    return cors_response(200, _issue_download_session(entitlement, item), origin)

def _download_url(item: Dict[str, Any], ttl: Optional[int] = None) -> str:
    """A presigned GET that downloads under the readable filename.

    ``ttl`` defaults to the short web value. Pass ``WHATSAPP_LINK_TTL`` when the URL is
    going into a message a human will read later rather than a redirect a browser
    follows now.
    """
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET,
            "Key": item["s3Key"],
            "ResponseContentDisposition": (
                f'attachment; filename="{item.get("originalFilename", "download")}"'
            ),
        },
        ExpiresIn=int(ttl or DOWNLOAD_URL_TTL),
    )


def _send_whatsapp_payment(file_id: str, identity: Dict[str, Any], origin: str):
    """Send the ₹49 request to the customer's WhatsApp as an approved template.

    The customer has already proved they own this number by completing the OTP, so the
    template goes to the verified number from their token - never to a number supplied
    in the request body, which would turn this route into a way to send WhatsApp
    messages to arbitrary people.
    """
    item = _owned_active_file(file_id, identity)
    if not item:
        return _not_registered(origin)

    if not _payment_enabled():
        return cors_response(
            503,
            {
                "error": "PAYMENT_DISABLED",
                "message": "Paid downloads are not enabled yet.",
                "pricePaise": int(item.get("pricePaise", PRICE_PAISE)),
            },
            origin,
        )

    from whatsapp_delivery import reference_id, send_payment_request

    reference = reference_id()
    now = int(time.time())
    grant_id = uuid.uuid4().hex

    # The grant is written BEFORE the send. If the send fails the grant simply expires
    # unredeemed via TTL; if the order were written after a successful send, a customer
    # could pay against a grant that does not exist yet.
    _table(GRANTS_TABLE).put_item(
        Item={
            "grantId": grant_id,
            "fileId": file_id,
            "ownerPhone": identity["phone"],
            "customerId": identity['subject'],
            # The webhook correlates on this. WhatsApp Pay reports the reference, so
            # the reference IS the order id as far as the order-index GSI is concerned.
            "orderId": reference,
            "amountPaise": int(item.get("pricePaise", PRICE_PAISE)),
            "channel": "whatsapp",
            "paid": False,
            "consumed": False,
            "createdAt": now,
            "expiresAt": now + GRANT_TTL,
        }
    )

    ok, detail = send_payment_request(
        phone=identity["phone"],
        file_row=item,
        grant_id=grant_id,
        order_id=reference,
        reference=reference,
    )
    logger.info(
        json.dumps(
            {
                "event": "whatsapp_payment_request",
                "fileId": file_id,
                "ownerPhone": mask_phone(identity["phone"]),
                "ok": ok,
                "detail": detail if ok else "send failed",
            }
        )
    )
    if not ok:
        return cors_response(
            502, {"error": "SEND_FAILED", "message": "Could not send the payment request."}, origin
        )

    return cors_response(
        202,
        {
            "grantId": grant_id,
            "reference": reference,
            "amountPaise": int(item.get("pricePaise", PRICE_PAISE)),
            "sentTo": mask_phone(identity["phone"]),
            "message": "Payment request sent on WhatsApp.",
        },
        origin,
    )


def deliver_over_whatsapp(grant_id: str) -> Tuple[bool, str]:
    """Send the paid file to the customer on WhatsApp. Called only after payment.

    Lives here rather than in the webhook so the ownership and deliverability rules sit
    next to the data that defines them. The webhook calls it by grant id and nothing
    else, so there is no path by which a caller can name a file directly.
    """
    grant = _table(GRANTS_TABLE).get_item(Key={"grantId": grant_id}).get("Item")
    if not grant or not grant.get("paid"):
        return False, "grant is not paid"

    item = _table(FILES_TABLE).get_item(Key={"fileId": grant["fileId"]}).get("Item")
    if not item or item.get("status") != "active":
        return False, "file is not active"
    if item.get("ownerPhone") != grant.get("ownerPhone"):
        return False, "grant and file disagree on owner"
    if not grant.get('customerId') or item.get('ownerCustomerId') != grant['customerId']:
        return False, "grant and file disagree on permanent owner"

    from whatsapp_delivery import send_document, send_download_link

    phone = str(grant["ownerPhone"])
    if item.get("deliverable") in ("pdf", "image"):
        ok, detail = send_document(phone=phone, file_row=item)
    else:
        # Not openable inline on WhatsApp, so send a link instead, on the longer TTL - a
        # person taps when they read the message, not within the web redeem's 60
        # seconds. Generated here rather than reusing the redeem route so delivery does
        # not consume the grant the customer may still redeem on the web.
        ok, detail = send_download_link(
            phone=phone,
            file_row=item,
            url=_download_url(item, ttl=WHATSAPP_LINK_TTL),
        )

    # Record the outcome ON THE GRANT. Until this existed a failed send was only a log
    # line, while the customer had already paid - so nothing could find the people owed
    # a file. scripts/reconcile_file_deliveries.py sweeps on exactly these attributes.
    try:
        _table(GRANTS_TABLE).update_item(
            Key={"grantId": grant_id},
            UpdateExpression=(
                "SET delivered = :d, deliveryDetail = :detail, deliveryAttemptedAt = :now "
                "ADD deliveryAttempts :one"
            ),
            ExpressionAttributeValues={
                ":d": bool(ok),
                ":detail": str(detail)[:200],
                ":now": int(time.time()),
                ":one": 1,
            },
        )
    except ClientError:
        # The send already happened; losing the bookkeeping must not undo it.
        logger.warning(json.dumps({"event": "delivery_state_write_failed"}))

    return ok, detail


def _redeem(file_id: str, event: Dict[str, Any], identity: Dict[str, Any], origin: str):
    """Issue renewable transport from durable paid entitlement; never consume the purchase."""
    params = event.get("queryStringParameters") or {}
    access_id = str(params.get("grant") or "").strip()
    if not access_id:
        return cors_response(400, {"error": "grant is required"}, origin)
    item = _owned_active_file(file_id, identity)
    if not item:
        return _not_registered(origin)

    entitlement = _active_entitlement(access_id, file_id, identity)
    if not entitlement:
        legacy = _table(GRANTS_TABLE).get_item(
            Key={"grantId": access_id}, ConsistentRead=True).get("Item") or {}
        if (legacy and not legacy.get("paid")
                and legacy.get("fileId") == file_id
                and legacy.get("ownerPhone") == identity.get("phone")
                and legacy.get("customerId") == identity.get("subject")
                and _reconcile_grant(access_id, file_id, identity)):
            return _redeem_after_reconcile(file_id, access_id, identity, item, origin)
        return cors_response(
            403, {"error": "ACCESS_NOT_AUTHORIZED",
                  "message": "This file is not authorized for this account. If you already paid, contact support; do not pay again."},
            origin)

    payload = _issue_download_session(entitlement, item)
    try:
        _table(FILES_TABLE).update_item(
            Key={"fileId": file_id},
            UpdateExpression="ADD downloadCount :one",
            ExpressionAttributeValues={":one": 1},
        )
    except ClientError:
        pass
    logger.info(json.dumps({
        "event": "secure_file_download_session_issued", "fileId": file_id,
        "ownerPhone": mask_phone(identity["phone"]),
    }))
    return cors_response(200, payload, origin)



# ── Drop Docs: make a document private BEFORE it is a document ────────────────
#
# A Drop Docs document can arrive over WhatsApp, where `inbound-whatsapp-handler` writes it
# to `o/stack/whatsapp-media/incoming/` - a prefix CloudFront E2GP22R4BIFGQ3 serves
# UNAUTHENTICATED. The locker is reused here for storage and privacy only: it promotes the
# object into `secure/` and the request store refuses to register a document whose key is
# not gated. Nothing in this arm touches the locker's own (disabled) Razorpay path, and
# nothing here charges anything - Drop Docs is paid once, on the one checkout.
#
# The ordering is the guarantee: promote, prove the destination landed with a HEAD, and only
# then write the DOC# row. A failed promotion answers 503 and leaves no row at all, so there
# is no state in which a customer document points at a publicly readable object.


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    """Add ``Cache-Control: no-store`` to a response.

    Document metadata and gated keys must not sit in a shared cache or a browser's disk
    cache. New here rather than reused: the rest of this file predates the convention and
    returns `cors_response` directly, and retrofitting it onto the paid-download routes is
    a separate change with its own blast radius.
    """
    headers = dict(response.get("headers") or {})
    headers["Cache-Control"] = "no-store"
    return {**response, "headers": headers}


def _dropdocs_identity(identity: Dict[str, Any]) -> customer_auth.CustomerIdentity:
    """The proven customer, in the shape the request store authorises on.

    `_customer_identity` has already done the work that matters - `GetUser` proved the token
    live, and the issuer pin proved it came from the CUSTOMER pool rather than the admin one.
    This only re-shapes it. `customer_id` is the Cognito `sub`, matching
    `customer_auth.customer_id_from_attributes`, so a REQ# row written by the services
    Lambda and a document attached here agree on who the owner is.
    """
    subject = str(identity.get("subject") or "")
    return customer_auth.CustomerIdentity(
        customer_id=subject, phone=identity.get("phone", ""), subject=subject)


def _dropdocs_attach(event: Dict[str, Any], identity: Dict[str, Any], origin: str):
    """Register one document against the caller's paid Drop Docs request.

    Answers 503 for every storage failure and for a destination that is somehow not gated,
    because both mean the same thing operationally: nothing was registered, and retrying is
    the right move. A refusal is never a hint - an unknown request, somebody else's request
    and a request that is not Drop Docs all produce the identical `NOT_REGISTERED` body this
    function shares with the paid-download routes.

    THE TARGET REQUEST IS RESOLVED BEFORE ANY BYTE MOVES. An ownership refusal that arrives
    after the promotion would leave an object in ``secure/u/dropdocs/`` with no ``DOC#`` row
    naming it, which no role may delete (`s3:DeleteObject` is granted nowhere, deliberately)
    and which no `system-cleanup` TTL covers - a permanent orphan of up to
    ``MAX_DOCUMENT_BYTES`` minted by a request that was refused. So the order is: prove the
    request is the caller's paid Drop Docs request, THEN copy, THEN register. The
    registration re-resolves it anyway and that re-check stays the authority; this one only
    makes the common refusal free.
    """
    if not _dropdocs_attach_enabled():
        # Checked before the body is read, so a request made while the route is off learns
        # nothing about what the route would have accepted.
        return _no_store(cors_response(
            503,
            {"error": "DROPDOCS_ATTACH_DISABLED",
             "message": "Attaching documents is not enabled yet."},
            origin,
        ))

    proven = _dropdocs_identity(identity)
    if not proven.customer_id:
        return _no_store(cors_response(401, {"error": "Verification required"}, origin))

    body = json.loads(event.get("body") or "{}")
    public_request_id = str(body.get("requestId") or "").strip()
    source_key = str(body.get("sourceKey") or "").strip()
    if not public_request_id or not source_key:
        return _no_store(cors_response(
            400, {"error": "requestId and sourceKey are required"}, origin))

    request_table = _table(SERVICE_REQUESTS_TABLE)
    try:
        # One GetItem pair, before S3 is touched at all. A refusal here transfers nothing
        # and so cannot leave an undeletable orphan in the gated tree.
        service_request_store.resolve_dropdocs_request(
            request_table, proven, public_request_id)
    except customer_auth.CustomerNotAuthorized:
        return _no_store(_not_registered(origin))
    except service_request_store.ServiceIdentityUnavailable as exc:
        logger.error(json.dumps({"event": "dropdocs_attach_unavailable",
                                 "stage": "resolve", "error": type(exc).__name__}))
        return _no_store(cors_response(
            503, {"error": "UNAVAILABLE", "message": "Please try again."}, origin))

    try:
        from lambda_utils.ecommerce.document_source import PRIVATE_INCOMING_PREFIX, owned_message_source
        verified_source = False
        if source_key.startswith(PRIVATE_INCOMING_PREFIX):
            verified_source = owned_message_source(
                _table('stack-wecare-digital-MessagesTable'),
                _table('stack-wecare-digital-ContactsTable'), proven,
                source_key, body.get('messageId'))
            if not verified_source:
                raise document_errors.DocumentRejected('document source unavailable')
        promoted = dropdocs_storage.promote_to_secure(
            _s3_client(), bucket=BUCKET, source_key=source_key,
            **({'verified_private_source': True} if verified_source else {}))
    except document_errors.DocumentRejected as exc:
        # 400, not 503. `sourceKey` is caller-supplied, and the one prefix this route
        # accepts is the WhatsApp arrival tree - naming anything else (another customer's
        # gated upload included) is permanently invalid, not a transient storage failure.
        # The message never names the allowed prefix: a refusal must not teach the caller
        # what would have been accepted.
        logger.warning(json.dumps({"event": "dropdocs_source_refused",
                                   "error": type(exc).__name__}))
        return _no_store(cors_response(
            400,
            {"error": "DOCUMENT_SOURCE_REFUSED",
             "message": "That document cannot be attached. Nothing was attached."},
            origin,
        ))
    except (dropdocs_storage.DocumentPromotionFailed,
            dropdocs_storage.DocumentNotPrivate) as exc:
        # type only: a storage error message can echo back a key or a bucket policy detail
        logger.warning(json.dumps({"event": "dropdocs_promotion_failed",
                                   "error": type(exc).__name__}))
        return _no_store(cors_response(
            503,
            {"error": "DOCUMENT_NOT_STORED",
             "message": "The document could not be stored privately. Nothing was attached."},
            origin,
        ))

    try:
        document = service_request_store.attach_document(
            request_table,
            proven,
            public_request_id,
            storage_key=promoted["storageKey"],
            sha256=promoted["sha256"],
            content_type=promoted["contentType"],
            size_bytes=promoted["sizeBytes"],
            source_key=source_key,
            public_source_retained=bool(promoted["publicSourceRetained"]),
        )
    except customer_auth.CustomerNotAuthorized:
        return _no_store(_not_registered(origin))
    except document_errors.DocumentRejected as exc:
        # Shape, not privacy: a digest or byte count the store will never accept. 400,
        # because retrying the identical request cannot succeed.
        logger.warning(json.dumps({"event": "dropdocs_document_refused",
                                   "error": type(exc).__name__}))
        return _no_store(cors_response(
            400,
            {"error": "DOCUMENT_SOURCE_REFUSED",
             "message": "That document cannot be attached. Nothing was attached."},
            origin,
        ))
    except document_errors.DocumentLimitReached as exc:
        # A stated ceiling, answered readably. Without it the DynamoDB 400 KB item limit
        # eventually turns every further attach into an unreadable validation error.
        logger.warning(json.dumps({"event": "dropdocs_document_limit_reached",
                                   "requestId": public_request_id,
                                   "error": type(exc).__name__}))
        return _no_store(cors_response(
            409,
            {"error": "DOCUMENT_LIMIT_REACHED",
             "message": "This request already holds the maximum number of documents.",
             "limit": service_request_store.MAX_DOCUMENTS_PER_REQUEST},
            origin,
        ))
    except dropdocs_storage.DocumentNotPrivate as exc:
        # The store re-checks gatedness itself and will not be talked out of it. Reaching
        # here means the promotion returned a key the store refused, so no row exists.
        logger.error(json.dumps({"event": "dropdocs_registration_refused",
                                 "alert": "DROPDOCS_KEY_NOT_GATED",
                                 "error": type(exc).__name__}))
        return _no_store(cors_response(
            503,
            {"error": "DOCUMENT_NOT_STORED",
             "message": "The document could not be stored privately. Nothing was attached."},
            origin,
        ))
    except service_request_store.ServiceIdentityUnavailable as exc:
        # ``stage`` distinguishes this from the pre-flight failure above: a table failure
        # before the promotion transferred nothing, one here means an object was copied and
        # no row names it. Same answer to the caller, different thing to investigate.
        logger.error(json.dumps({"event": "dropdocs_attach_unavailable",
                                 "stage": "register", "error": type(exc).__name__}))
        return _no_store(cors_response(
            503, {"error": "UNAVAILABLE", "message": "Please try again."}, origin))

    logger.info(json.dumps({"event": "dropdocs_attached", "requestId": public_request_id,
                            "sha256": document.get("documentId", ""),
                            "promoted": bool(promoted["promoted"])}))
    return _no_store(cors_response(201, {"requestId": public_request_id,
                                         "document": document}, origin))


def _dropdocs_list(public_request_id: str, identity: Dict[str, Any], origin: str):
    """The caller's own documents for one paid Drop Docs request.

    Here rather than held back for a future UI, so `list_documents` has a caller and runs
    under this phase's tests instead of first running in production. Gated by the same
    `DROPDOCS_ATTACH_ENABLED` flag as the write, so the pair switches on together, and the
    refusal is the same `NOT_REGISTERED` body - a list route that answered differently for
    "no such request" and "not yours" would re-open the oracle the attach route closes.

    No key under ``o/`` can appear in the response: `service_request_store._document_view`
    omits ``sourceKey`` and every ``storageKey`` it returns is gated by construction.
    """
    if not _dropdocs_attach_enabled():
        return _no_store(cors_response(
            503,
            {"error": "DROPDOCS_ATTACH_DISABLED",
             "message": "Attaching documents is not enabled yet."},
            origin,
        ))

    proven = _dropdocs_identity(identity)
    if not proven.customer_id:
        return _no_store(cors_response(401, {"error": "Verification required"}, origin))

    try:
        documents = service_request_store.list_documents(
            _table(SERVICE_REQUESTS_TABLE), proven, public_request_id)
    except customer_auth.CustomerNotAuthorized:
        return _no_store(_not_registered(origin))
    except service_request_store.ServiceIdentityUnavailable as exc:
        logger.error(json.dumps({"event": "dropdocs_list_unavailable",
                                 "error": type(exc).__name__}))
        return _no_store(cors_response(
            503, {"error": "UNAVAILABLE", "message": "Please try again."}, origin))

    return _no_store(cors_response(200, {"requestId": public_request_id,
                                         "documents": documents}, origin))


# ── routing ───────────────────────────────────────────────────────────────────

def _path_parts(event: Dict[str, Any]) -> Tuple[str, list]:
    rc = event.get("requestContext", {})
    raw = rc.get("http", {}).get("path") or event.get("rawPath") or event.get("path") or ""
    try:
        from lambda_utils.http_path import strip_stage

        raw = strip_stage(raw, str(rc.get("stage") or ""))
    except Exception:  # noqa: BLE001
        pass
    return raw, [p for p in raw.split("/") if p]


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    # Internal async dispatch from the Razorpay webhook. Deliberately checked before
    # anything else and keyed on a field API Gateway cannot produce, so no HTTP caller
    # can reach it: an event arriving through the API always carries a requestContext,
    # and this branch requires its absence.
    if event.get("internalAction") == "deliverOverWhatsApp" and not event.get("requestContext"):
        grant_id = str(event.get("grantId") or "")
        ok, detail = deliver_over_whatsapp(grant_id) if grant_id else (False, "no grantId")
        logger.info(
            json.dumps({"event": "whatsapp_delivery_result", "ok": ok, "detail": detail})
        )
        return {"ok": ok, "detail": detail}

    # The webhook's only route in. It may assert that an order changed, and nothing more:
    # it cannot say who paid, how much, or which file to send. Those all come from the
    # grant this system wrote, and whether money actually moved comes from Razorpay's API.
    # So a forged event - including one signed with the webhook secret that sits in this
    # repository's public git history - ends at "no captured payment".
    if event.get("internalAction") == "confirmAndDeliver" and not event.get("requestContext"):
        order_id = str(event.get("orderId") or "")
        ok, detail = confirm_and_deliver(order_id) if order_id else (False, "no orderId")
        logger.info(
            json.dumps({"event": "confirm_and_deliver_result", "ok": ok, "detail": detail})
        )
        return {"ok": ok, "detail": detail}

    # Internal async dispatch from the CRM (`core/contacts`), gated THERE by
    # CRM_PROVISION_CUSTOMER_LOGIN which defaults off. Same `requestContext`-absence guard as the
    # two branches above, for the same reason: an event arriving through API Gateway always
    # carries a requestContext, so no HTTP caller can reach this.
    #
    # Worth being precise about what an attacker who could reach it would gain: a phone-keyed
    # customer in the customer pool, with no email and no credential anybody knows. Signing in as
    # that user still requires a WhatsApp OTP delivered to the number itself, so the capability is
    # "create a login for a phone you already control", not "log in as someone".
    if event.get("internalAction") == "provisionCustomerLogin" and not event.get("requestContext"):
        ok, detail = provision_customer_login(str(event.get("phone") or ""))
        logger.info(
            json.dumps({"event": "customer_login_provision_result", "ok": ok, "detail": detail})
        )
        return {"ok": ok, "detail": detail}

    origin = extract_origin(event)
    rc = event.get("requestContext", {})
    method = (
        rc.get("http", {}).get("method") or event.get("httpMethod") or "GET"
    ).upper()
    if method == "OPTIONS":
        return options_response(origin)

    path, parts = _path_parts(event)
    # /secure-files/...  -> drop the leading segment
    tail = parts[1:] if parts and parts[0] == "secure-files" else parts

    try:
        # ---- customer surface ------------------------------------------------
        if tail[:1] == ["mine"] and method == "GET":
            identity = _customer_identity(event)
            if not identity:
                return cors_response(401, {"error": "Verification required"}, origin)
            return _customer_list(identity, origin)

        # Drop Docs. A customer-pool token, never require_auth: that one is hardcoded to
        # the admin pool and would let a customer token fall through to role Viewer.
        if tail == ["dropdocs", "attach"]:
            if method != "POST":
                return _no_store(cors_response(405, {"error": "Method not allowed"}, origin))
            identity = _customer_identity(event)
            if not identity:
                return _no_store(cors_response(401, {"error": "Verification required"}, origin))
            return _dropdocs_attach(event, identity, origin)

        # The read side of the same pair. A literal `dropdocs` segment, so it cannot be
        # confused with the `{fileId}` routes below, and matched before them for the same
        # reason.
        if len(tail) == 3 and tail[0] == "dropdocs" and tail[2] == "documents":
            if method != "GET":
                return _no_store(cors_response(405, {"error": "Method not allowed"}, origin))
            identity = _customer_identity(event)
            if not identity:
                return _no_store(cors_response(401, {"error": "Verification required"}, origin))
            return _dropdocs_list(tail[1], identity, origin)

        if len(tail) == 2 and tail[1] in ("order", "download", "whatsapp-pay"):
            identity = _customer_identity(event)
            if not identity:
                return cors_response(401, {"error": "Verification required"}, origin)
            if tail[1] == "order" and method == "POST":
                return _create_order(tail[0], identity, origin)
            if tail[1] == "whatsapp-pay" and method == "POST":
                return _send_whatsapp_payment(tail[0], identity, origin)
            if tail[1] == "download" and method == "GET":
                return _redeem(tail[0], event, identity, origin)
            return cors_response(405, {"error": "Method not allowed"}, origin)

        # ---- admin surface ---------------------------------------------------
        denied = require_auth(event, "Operator")
        if denied is not None:
            return denied

        if not tail:
            if method == "GET":
                return _admin_list(event, origin)
            return cors_response(405, {"error": "Method not allowed"}, origin)

        if tail == ["upload-init"] and method == "POST":
            return _upload_init(event, origin)
        if len(tail) == 2 and tail[1] == "confirm" and method == "POST":
            return _upload_confirm(tail[0], origin)
        if len(tail) == 2 and tail[1] == "revoke" and method == "POST":
            return _admin_revoke(tail[0], origin)

        return cors_response(404, {"error": f"Unknown route {path}"}, origin)

    except json.JSONDecodeError:
        return cors_response(400, {"error": "Body must be valid JSON"}, origin)
    except Exception as exc:  # noqa: BLE001
        # type only: an exception message can carry data we did not construct
        logger.error(json.dumps({"event": "secure_files_error", "error": type(exc).__name__}))
        return cors_response(500, {"error": "Internal error"}, origin)
