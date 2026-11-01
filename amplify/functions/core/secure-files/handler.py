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

Payment initiation does not live here
-------------------------------------
Secure-files owns entitlement verification, redemption and delivery only. New purchases must
enter through the canonical commerce/checkout PaymentAttempt path. Legacy settlement helpers are
retained temporarily only so an already-issued historical secure-file Razorpay order can still be
verified and delivered; no HTTP route in this Lambda can create a new payment.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets as pysecrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from boto3.dynamodb.types import TypeSerializer
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

from lambda_utils import customer_auth, media_paths, whatsapp_templates
from lambda_utils.direct_send import META_PHONE_TO_WABA, waba_for_meta_phone
from lambda_utils.ecommerce import (catalog_service_checkout, document_errors,
                                  dropdocs_storage, service_request_store)
from lambda_utils.ecommerce import vault_window
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
# Historical metadata only: already-published Vault rows may still refer to the
# old Drop Docs intake. Never route any new Vault upload through Drop Docs.
DROPDOCS_PREFIX = media_paths.LEGACY_DROP_DOCS_UPLOAD_PREFIX
# Operator-selected Vault-only storage, protected by the edge private-prefix list.
VAULT_UPLOAD_PREFIX = media_paths.VAULT_UPLOAD_PREFIX

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
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "stack-wecare-digital-DocumentTable")
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
#
# Customer OTP is delivered from WABA1 ONLY: there is no `wecare_otp` AUTHENTICATION
# template approved on WABA2, so `auth/customer-whatsapp-auth` pins its gate to the
# primary WABA and denies every other. A stamp this function can write MUST therefore be
# one that gate accepts, or the customer is minted into a permanent sign-in lockout. So
# the stampable set is the OTP-accepted set - the primary WABA alone - NOT every WABA the
# messaging map (`META_PHONE_TO_WABA`) can route an outbound send to. WABA2 remains a
# valid outbound messaging number; it is simply never a customer sign-in identity.
PRIMARY_WABA_ID = "2094615664435155"  # WABA1 WECARE.DIGITAL, +91 93309 94400
KNOWN_WABA_IDS = frozenset({PRIMARY_WABA_ID})
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

    Read per call, not captured at import: a repoint that only takes effect once every warm
    sandbox recycles is not a repoint.
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
    # Fail closed on a WABA the OTP gate does not accept. `derived` can be a WABA the
    # messaging map routes to but that is NOT a customer sign-in identity (WABA2 today):
    # stamping it would mint a permanent sign-in lockout, so return '' and let
    # `_ensure_customer_user` refuse the upload instead.
    if derived not in KNOWN_WABA_IDS:
        if derived:
            logger.warning(
                json.dumps(
                    {
                        "event": "secure_files_waba_not_otp_accepted",
                        "wabaId": _loggable_waba(derived),
                    }
                )
            )
        return ""
    return derived

UPLOAD_URL_TTL = int(os.environ.get("UPLOAD_URL_TTL_SECONDS", "900"))
# Web redeem: the browser follows this immediately, so it can be very short. It is the only
# presigned link this function issues; WhatsApp delivery sends a Vault page link instead.
DOWNLOAD_URL_TTL = int(os.environ.get("DOWNLOAD_URL_TTL_SECONDS", "60"))
GRANT_TTL = int(os.environ.get("GRANT_TTL_SECONDS", "1800"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(100 * 1024 * 1024)))

_META_MEDIA_RULES = {
    ".aac": ("audio/aac", 16 * 1024 * 1024),
    ".amr": ("audio/amr", 16 * 1024 * 1024),
    ".mp3": ("audio/mpeg", 16 * 1024 * 1024),
    ".m4a": ("audio/mp4", 16 * 1024 * 1024),
    ".ogg": ("audio/ogg", 16 * 1024 * 1024),
    ".txt": ("text/plain", 100 * 1024 * 1024),
    ".xls": ("application/vnd.ms-excel", 100 * 1024 * 1024),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 100 * 1024 * 1024),
    ".doc": ("application/msword", 100 * 1024 * 1024),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", 100 * 1024 * 1024),
    ".ppt": ("application/vnd.ms-powerpoint", 100 * 1024 * 1024),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", 100 * 1024 * 1024),
    ".pdf": ("application/pdf", 100 * 1024 * 1024),
    ".jpeg": ("image/jpeg", 5 * 1024 * 1024),
    ".png": ("image/png", 5 * 1024 * 1024),
    ".3gp": ("video/3gpp", 16 * 1024 * 1024),
    ".mp4": ("video/mp4", 16 * 1024 * 1024),
}

def _meta_media_limit(filename: str, content_type: str) -> int:
    ext = os.path.splitext(str(filename or "").strip().lower())[1]
    rule = _META_MEDIA_RULES.get(ext)
    if not rule or str(content_type or "").strip().lower() != rule[0]:
        return 0
    return min(MAX_UPLOAD_BYTES, rule[1])

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


_lambda = None


def _lambda_client():
    """The client for the payment-request invoke: ONE attempt, and an answer inside our timeout.

    A payment request ends in a WhatsApp send, so botocore must not retry a read timeout (that
    would be a second Review and Pay), and the read timeout sits below this function's 30 s so
    an ambiguous call is reported as "check the chat" rather than killing the request.
    """
    global _lambda
    if _lambda is None:
        from botocore.config import Config

        _lambda = boto3.client(
            "lambda", region_name=REGION,
            config=Config(connect_timeout=5, read_timeout=24,
                          retries={"total_max_attempts": 1, "mode": "standard"}),
        )
    return _lambda


def _dropdocs_attach_enabled() -> bool:
    """Whether the Drop Docs attach route answers at all. Defaults OFF.

    Read per call, not captured at import: a posture switch that only takes effect once
    every warm sandbox recycles is not much of a switch. There is no UI
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


def _window_closed(entitlement: Optional[Dict[str, Any]], origin: str) -> Dict[str, Any]:
    """Every paid window on this file has been used. Distinct from not-paid and not-yours, so
    the Vault page can offer the renewal instead of telling a paying customer to contact
    support."""
    return cors_response(
        403,
        {
            "error": "ACCESS_WINDOW_CLOSED",
            "message": "Your 24-hour access has ended. Renew on the website or through WhatsApp to download again.",
            "windowCount": vault_window.window_count(entitlement),
            "renewable": True,
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


def _paid_marks(item: Dict[str, Any]) -> bool:
    """Whether the file row records a purchase at all, whatever state its entitlement is in."""
    return bool(item.get("vaultPaymentStatus") == "PAID" or item.get("vaultEntitlementId")
                or item.get("vaultAccessGrantId"))


def _access_state(item: Dict[str, Any], entitlement: Optional[Dict[str, Any]], now: int) -> str:
    """`vault_window.access_state`, plus one state the window math cannot see.

    ``PAID_UNVERIFIED``: the row records a purchase but no active entitlement could be read for
    this caller. It is kept apart from ``UNPAID`` on purpose - showing it as unpaid is how a
    paid customer gets asked for ₹49 again. The answer for it is reconciliation, not a sale.
    """
    if entitlement:
        return vault_window.access_state(entitlement, now)
    return "PAID_UNVERIFIED" if _paid_marks(item) else "UNPAID"


def _public_file(item: Dict[str, Any], *, admin: bool,
                 entitlement: Optional[Dict[str, Any]] = None,
                 now: Optional[int] = None) -> Dict[str, Any]:
    """Shape a record for the client. The S3 key never leaves the backend.

    When an `entitlement` is supplied (admin list enriches it), the 24h access-window status is
    computed from it so the workspace can show "Active · ends in Xh" / "Expired" / "Awaiting
    purchase" — the same predicate the redeem path gates on, so screen and backend never disagree.
    """
    now = int(time.time()) if now is None else int(now)
    out = {
        "fileId": item.get("fileId"),
        "displayName": _system_name_for_file(item) if item.get("sourceDocumentId") else item.get("displayName"),
        "tag": item.get("tag") or "",
        "originalFilename": item.get("originalFilename"),
        "contentType": item.get("contentType"),
        "sizeBytes": item.get("sizeBytes"),
        "status": item.get("status"),
        "createdAt": item.get("createdAt"),
        "downloadCount": item.get("downloadCount", 0),
        "vaultPaymentStatus": item.get('vaultPaymentStatus'),
        "vaultOrderNumber": item.get('vaultOrderNumber'),
        "vaultRequestNumber": item.get('vaultRequestNumber'),
        # Access-window view (display-only; the authoritative gate is _redeem).
        "accessWindowStatus": vault_window.status_label(entitlement, now),
        "accessWindowOpen": vault_window.window_open(entitlement, now),
        "accessWindowEndsAt": vault_window.window_ends_at(entitlement),
        "accessWindowCount": vault_window.window_count(entitlement),
        "accessState": _access_state(item, entitlement, now),
        # "pdf" / "image" arrive as a WhatsApp attachment; "link" goes out as a URL.
        "deliverable": item.get("deliverable", "unknown"),
    }
    if admin:
        out["ownerName"] = item.get("ownerName")
        out["ownerPhoneMasked"] = mask_phone(item.get("ownerPhone", ""))
        out["uploadedBy"] = item.get("uploadedBy")
        out["sourceDocumentId"] = item.get("sourceDocumentId")
        out["workspaceRecordVersion"] = int(item.get("workspaceRecordVersion") or 0)
        out["lastOfferBodyText"] = item.get("lastOfferBodyText")
        out["lastOfferRequestedBy"] = item.get("lastOfferRequestedBy")
        out["lastOfferRequestedAt"] = item.get("lastOfferRequestedAt")
        out["lastOfferOutcome"] = item.get("lastOfferOutcome")
        out["lastPaymentRequestedBy"] = item.get("lastPaymentRequestedBy")
        out["lastPaymentRequestedAt"] = item.get("lastPaymentRequestedAt")
        out["lastPaymentRequestOutcome"] = item.get("lastPaymentRequestOutcome")
        out["lastAccessSentBy"] = item.get("lastAccessSentBy")
        out["lastAccessSentAt"] = item.get("lastAccessSentAt")
        out["lastAccessSendOutcome"] = item.get("lastAccessSendOutcome")
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


def _vault_direct_upload_enabled() -> bool:
    """Fail closed until the exact S3 prefix is blocked by deployed Lambda@Edge."""
    return str(os.environ.get("VAULT_DIRECT_UPLOAD_ENABLED", "false")).strip().lower() == "true"


def _upload_init(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Staff-only Vault intake, independent of the Drop Docs customer service."""
    if not _vault_direct_upload_enabled():
        return cors_response(503, {
            "error": "VAULT_UPLOAD_NOT_READY",
            "message": "Vault uploads remain disabled until private CDN access has been verified.",
        }, origin)
    body = json.loads(event.get("body") or "{}")
    name = str(body.get("name") or "").strip()
    # Optional operator label for finding a file later (e.g. "Passport", "Invoice Mar"). Free
    # text, bounded and stripped of control chars; it is display-only and never part of a key.
    tag = "".join(c for c in str(body.get("tag") or "").strip() if c.isprintable())[:60]
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
    media_limit = _meta_media_limit(filename, content_type)
    if not media_limit:
        return cors_response(
            415, {"error": "UNSUPPORTED_MEDIA_TYPE",
                  "message": "Use a WhatsApp-supported file type with a matching extension and MIME type."},
            origin,
        )
    if size <= 0 or size > media_limit:
        return cors_response(
            413, {"error": "FILE_TOO_LARGE", "limitBytes": media_limit}, origin
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
    key = VAULT_UPLOAD_PREFIX + basename
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    _table(FILES_TABLE).put_item(
        Item={
            "fileId": file_id,
            "s3Key": key,
            "ownerPhone": phone,
            "ownerCustomerId": owner_customer_id,
            "ownerName": name,
            "cognitoUsername": username,
            "displayName": basename,
            "tag": tag,
            "originalFilename": filename,
            "contentType": content_type,
            "sizeBytes": size,
            # Decided at confirm time, once the real object is measured rather than
            # trusted from the browser: "pdf", "image", or "link" when the type
            # cannot be opened inline on WhatsApp.
            "deliverable": "unknown",
            # pending until the object is actually in the bucket, so a failed
            # browser upload cannot leave a file the customer can be charged for
            "status": "pending",
            "workspaceRecordVersion": WORKSPACE_VAULT_RECORD_VERSION,
            "downloadCount": 0,
            "uploadedBy": (event.get("_auth") or {}).get("username", ""),
            "createdAt": now,
        }
    )

    # Signed create-only PUT: a presigned URL stays valid for up to 15 minutes.
    # A second PUT must never overwrite an already-confirmed or paid Vault file.
    # The browser must send If-None-Match: * exactly as signed.
    upload_url = _s3_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type,
                "IfNoneMatch": "*"},
        ExpiresIn=UPLOAD_URL_TTL,
    )

    logger.info(
        json.dumps(
            {
                "event": "vault_direct_upload_init",
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
            "displayName": basename,
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
    """Confirm staff-owned Vault bytes only after S3 HEAD proves they exist."""
    if not _vault_direct_upload_enabled():
        return cors_response(503, {"error": "VAULT_UPLOAD_NOT_READY"}, origin)
    table = _table(FILES_TABLE)
    item = table.get_item(Key={"fileId": file_id}, ConsistentRead=True).get("Item")
    if not item:
        return cors_response(404, {"error": "Unknown fileId"}, origin)
    status = item.get("status")
    if status == "active":
        # A retried confirm (the browser lost the first answer) is success, not a second write.
        return cors_response(
            200,
            _decimal_safe({"fileId": file_id, "status": "active", "sizeBytes": item.get("sizeBytes"),
                           "deliverable": item.get("deliverable", "unknown")}),
            origin,
        )
    if status != "pending":
        # Only an upload in progress can be confirmed. Without this a confirm call quietly
        # turned a REVOKED file back into an active, downloadable one.
        return cors_response(409, {"error": "FILE_NOT_PENDING",
                                   "message": "This file is not awaiting an upload."}, origin)

    upload_key = str(item.get("s3Key") or "")
    if not upload_key.startswith(VAULT_UPLOAD_PREFIX) or upload_key.endswith("/"):
        return cors_response(409, {"error": "NOT_A_DIRECT_VAULT_UPLOAD"}, origin)
    try:
        head = _s3_client().head_object(Bucket=BUCKET, Key=upload_key)
    except ClientError:
        return cors_response(
            409, {"error": "Upload not found in storage; retry the upload"}, origin
        )

    size = int(head["ContentLength"])
    # Prefer what S3 recorded over what the browser asserted at upload-init.
    content_type = head.get("ContentType") or item.get("contentType") or ""
    media_limit = _meta_media_limit(str(item.get("originalFilename") or ""), str(content_type))
    if not media_limit or size <= 0 or size > media_limit:
        table.update_item(
            Key={"fileId": file_id},
            UpdateExpression="SET #s = :rejected, sizeBytes = :size, rejectedReason = :why",
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":rejected": "rejected", ":pending": "pending",
                                       ":size": size, ":why": "META_MEDIA_LIMIT"},
        )
        logger.warning(json.dumps({"event": "vault_upload_rejected_media", "fileId": file_id,
                                   "sizeBytes": size}))
        return cors_response(
            413 if media_limit else 415,
            {"error": "FILE_TOO_LARGE" if media_limit else "UNSUPPORTED_MEDIA_TYPE"},
            origin)
    # Vault sends only an owner-bound paid URL. Never copy to a public rendition.
    deliverable = "link"
    delivery_key = ""

    try:
        table.update_item(
            Key={"fileId": file_id},
            UpdateExpression=(
                "SET #s = :active, sizeBytes = :size, contentType = :ct, "
                "deliverable = :d, deliveryKey = :dk"
            ),
            ConditionExpression="#s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":active": "active", ":pending": "pending", ":size": size, ":ct": content_type,
                ":d": deliverable, ":dk": delivery_key,
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        # Revoked (or confirmed) while this request was measuring the object.
        return cors_response(409, {"error": "FILE_NOT_PENDING",
                                   "message": "This file is not awaiting an upload."}, origin)
    logger.info(
        json.dumps({"event": "vault_direct_upload_active", "fileId": file_id,
                    "deliverable": deliverable, "sizeBytes": size})
    )
    return cors_response(
        200,
        {"fileId": file_id, "status": "active", "sizeBytes": size,
         "deliverable": deliverable},
        origin,
    )




def _system_name_for_file(item: Dict[str, Any]) -> str:
    """Canonical Vault name for an already-published row, including legacy rows."""
    current = os.path.basename(str(item.get("displayName") or "").strip())
    if current.startswith("wecare-digital-"):
        return current
    file_id = str(item.get("fileId") or "")
    original = str(item.get("originalFilename") or "").strip()
    return f"wecare-digital-{file_id}{_safe_extension(original)}"


def _admin_publish_document(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Retired cross-service bridge: Drop Docs is customer intake, not Vault intake.

    Historical Vault records linked to DocumentTable stay readable, but new Vault
    uploads must use the staff-only /secure-files/upload-init + /confirm path.
    This tombstone performs no S3, DocumentTable, payment or WhatsApp side effect.
    """
    return cors_response(410, {
        "error": "DROP_DOCS_VAULT_PUBLISH_RETIRED",
        "message": "Drop Docs is for customer uploads. Staff must upload to Vault separately.",
    }, origin)


# Rows created before this marker are retained as audit history but are not shown as current
# Workspace documents. New publishes carry this version; revoked rows always leave Documents and
# remain visible from the Logs view.
WORKSPACE_VAULT_RECORD_VERSION = 2

#: Upper bound on one admin listing. Each read is one DynamoDB page, so the list is complete up
#: to this many rows and says so (`truncated`) beyond it, instead of an arbitrary first 100.
ADMIN_LIST_MAX_ITEMS = 1000
_ADMIN_LIST_MAX_PAGES = 20
ADMIN_LOG_MAX_ITEMS = 100


def _storage_object_present(key: Any) -> Optional[bool]:
    """Whether a stored Vault object exists in S3, without exposing its key to Workspace.

    None means S3 could not answer reliably; False means the key is absent. Logs use this as the
    storage truth instead of assuming an old SecureFilesTable row still has bytes behind it.
    """
    value = str(key or "").strip()
    if not value:
        return False
    try:
        _s3_client().head_object(Bucket=BUCKET, Key=value)
        return True
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        logger.warning(json.dumps({"event": "vault_log_storage_check_failed",
                                   "error": code or type(exc).__name__}))
        return None




def _admin_list(event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Current Workspace documents, or the retained Vault audit log when ?view=logs."""
    params = event.get("queryStringParameters") or {}
    table = _table(FILES_TABLE)
    view = str(params.get("view") or "documents").strip().lower()
    if view not in ("documents", "logs"):
        return cors_response(400, {"error": "Invalid Vault view"}, origin)

    mobile = params.get("mobile")
    if mobile:
        try:
            phone = normalise_phone(mobile)
        except ValueError:
            return cors_response(400, {"error": "Invalid mobile number"}, origin)
        read = lambda **page: table.query(  # noqa: E731 - one call shape for both readers
            IndexName="owner-created-index",
            KeyConditionExpression="ownerPhone = :p",
            ExpressionAttributeValues={":p": phone},
            ScanIndexForward=False,
            **page,
        )
    else:
        read = lambda **page: table.scan(**page)  # noqa: E731

    collected: list = []
    start_key = None
    truncated = False
    for _page in range(_ADMIN_LIST_MAX_PAGES):
        kwargs: Dict[str, Any] = {"Limit": 200}
        if start_key:
            kwargs["ExclusiveStartKey"] = start_key
        result = read(**kwargs)
        collected.extend(result.get("Items", []))
        start_key = result.get("LastEvaluatedKey")
        if not start_key or len(collected) >= ADMIN_LIST_MAX_ITEMS:
            break
    if start_key or len(collected) > ADMIN_LIST_MAX_ITEMS:
        truncated = True

    if view == "documents":
        # Production rows that pre-date this contract are history, not live Workspace inventory.
        # New rows carry the marker below; revocation moves a row out of Documents immediately.
        collected = [
            item for item in collected
            if item.get("status") == "active"
            and int(item.get("workspaceRecordVersion") or 0) >= WORKSPACE_VAULT_RECORD_VERSION
        ]

    items = sorted(
        collected, key=lambda i: str(i.get("createdAt", "")), reverse=True
    )[:(ADMIN_LOG_MAX_ITEMS if view == "logs" else ADMIN_LIST_MAX_ITEMS)]

    if view == "logs":
        logs = []
        for item in items:
            row = _public_file(item, admin=True, entitlement=None, now=int(time.time()))
            row["legacyRecord"] = int(item.get("workspaceRecordVersion") or 0) < WORKSPACE_VAULT_RECORD_VERSION
            row["storageOriginalPresent"] = _storage_object_present(item.get("s3Key"))
            row["storageDeliveryPresent"] = (
                _storage_object_present(item.get("deliveryKey"))
                if item.get("deliveryKey") else False
            )
            row["revokedAt"] = item.get("revokedAt")
            row["revokedBy"] = item.get("revokedBy")
            logs.append(row)
        return cors_response(200, {
            "logs": logs, "count": len(logs),
            "truncated": truncated or len(collected) > ADMIN_LOG_MAX_ITEMS,
            "storage": {
                "bucket": BUCKET,
                "sourcePrefix": VAULT_UPLOAD_PREFIX,
                "legacySourcePrefix": DROPDOCS_PREFIX,
                "deliveryPrefix": DELIVER_PREFIX,
            },
        }, origin)

    # Documents view: enrich current active files with entitlement/window status.
    now = int(time.time())
    grants = _table(GRANTS_TABLE)
    out = []
    for item in items:
        entitlement = None
        eid = str(item.get("vaultEntitlementId") or "")
        try:
            if eid:
                entitlement = grants.get_item(Key={"grantId": eid}).get("Item")
            elif _paid_marks(item) and item.get("ownerCustomerId"):
                entitlement = _entitlement_for_file(str(item["ownerCustomerId"]), str(item["fileId"]))
        except ClientError:
            entitlement = None
        out.append(_public_file(item, admin=True, entitlement=entitlement, now=now))
    return cors_response(200, {
        "files": out,
        "count": len(out),
        "truncated": truncated,
        "storage": {
            "bucket": BUCKET,
            "sourcePrefix": VAULT_UPLOAD_PREFIX,
            "legacySourcePrefix": DROPDOCS_PREFIX,
            "deliveryPrefix": DELIVER_PREFIX,
        },
    }, origin)


def _message_status_for_verified_send(wamid: str) -> Dict[str, Any]:
    """Read webhook-updated delivery evidence for an exact, server-recorded provider ID.

    The MessagesTable whatsappMessageId-index is a point lookup (never a scan).
    One file's staff audit WAMID is the only lookup input; no arbitrary phone or
    provider ID supplied by the caller is accepted. Unknown != delivered.
    """
    if not isinstance(wamid, str) or not wamid.startswith("wamid.") or len(wamid) > 512:
        return {"status": "NOT_TRACKED", "observedAt": None}
    try:
        rows = _table(os.environ.get(
            "MESSAGES_TABLE", "stack-wecare-digital-MessagesTable")).query(
            IndexName="whatsappMessageId-index",
            KeyConditionExpression="whatsappMessageId = :wamid",
            ExpressionAttributeValues={":wamid": wamid},
            Limit=3,
        ).get("Items") or []
    except ClientError as exc:
        logger.warning(json.dumps({"event": "vault_message_status_read_failed",
                                   "error": exc.response.get("Error", {}).get("Code", "AWS_ERROR")}))
        return {"status": "UNAVAILABLE", "observedAt": None}
    acceptable = {"accepted", "sent", "delivered", "read", "failed", "unknown", "pending"}
    outbound = [row for row in rows
                if str(row.get("whatsappMessageId") or "") == wamid
                and str(row.get("direction") or "").lower() == "outbound"]
    if not outbound:
        return {"status": "NOT_TRACKED", "observedAt": None}
    row = max(outbound, key=lambda item: int(item.get("statusUpdatedAt") or item.get("timestamp") or 0))
    status = str(row.get("status") or "").lower()
    return {
        "status": status.upper() if status in acceptable else "UNKNOWN",
        "observedAt": int(row.get("statusUpdatedAt") or row.get("timestamp") or 0) or None,
    }


def _logged_send_evidence(wamid: str, sent_at: Any) -> Dict[str, Any]:
    """Safe status/time projection from an already server-bound send audit row.

    A delivery-log WAMID is proof of provider submission, never handset
    delivery. Only a monotonic webhook-updated message row may say READ or
    DELIVERED. Never return phone, invoice, payment, raw WAMID or S3 data.
    """
    try:
        at = int(sent_at or 0)
    except (TypeError, ValueError):
        at = 0
    at = at if 0 < at < 5000000000 else None
    if not isinstance(wamid, str) or not wamid.startswith("wamid.") or len(wamid) > 512:
        return {"status": "NOT_TRACKED", "observedAt": at}
    proof = _message_status_for_verified_send(wamid)
    if proof["status"] == "NOT_TRACKED":
        return {"status": "ACCEPTED", "observedAt": at, "source": "SEND_LOG"}
    if proof["status"] == "UNAVAILABLE":
        return {"status": "UNAVAILABLE", "observedAt": at}
    return {
        "status": proof["status"],
        "observedAt": proof.get("observedAt") or at,
        "source": "MESSAGE_STATUS",
    }


def _verified_vault_payment_evidence(item: Dict[str, Any]) -> Dict[str, Any]:
    """Bounded joins through a paid entitlement to the latest paid invoice.

    The file's server-written owner, immutable entitlement and paid grant must
    ALL match. No joins by phone/name/amount, scans, external requests or sends.
    Invoices are resolved by the exact payment reference on the verified grant.
    Missing/ambiguous audit evidence stays NOT_TRACKED, never guessed.
    """
    none = {"status": "NOT_TRACKED", "observedAt": None}
    result = {"nativePay": none, "processing": none,
              "completed": none, "invoice": none, "autoAccess": none}
    entitlement_id = str(item.get("vaultEntitlementId") or "")
    if not entitlement_id or not item.get("ownerCustomerId") or not item.get("ownerPhone"):
        return result
    grants = _table(GRANTS_TABLE)
    entitlement = grants.get_item(
        Key={"grantId": entitlement_id}, ConsistentRead=True).get("Item") or {}
    if not (entitlement.get("recordType") == "VAULT_ENTITLEMENT"
            and entitlement.get("entitlementState") == "ACTIVE"
            and entitlement.get("customerId") == item["ownerCustomerId"]
            and entitlement.get("ownerPhone") == item["ownerPhone"]
            and entitlement.get("fileId") == item["fileId"]):
        return result
    grant_id = str(entitlement.get("lastGrantId")
                   or entitlement.get("sourceGrantId") or "")
    grant = grants.get_item(
        Key={"grantId": grant_id}, ConsistentRead=True).get("Item") if grant_id else {}
    if not grant or not (grant.get("paid") is True
                         and grant.get("customerId") == item["ownerCustomerId"]
                         and grant.get("ownerPhone") == item["ownerPhone"]
                         and grant.get("fileId") == item["fileId"]
                         and grant.get("entitlementId") == entitlement_id):
        return result
    ref = str(grant.get("reference") or "")
    if not ref or len(ref) > 160:
        return result
    # The automatic Access Vault send belongs to the exact paid request/grant.
    # This is a direct PK read already permitted for secure-files, not a scan
    # by phone number, amount, order name or provider message ID.
    request_id = str(grant.get("requestId") or "")
    if request_id:
        request = _table(SERVICE_REQUESTS_TABLE).get_item(
            Key={"requestId": request_id}, ConsistentRead=True).get("Item") or {}
        if (request.get("requestId") == request_id
                and request.get("kind") == "VAULT"
                and request.get("customerId") == item["ownerCustomerId"]
                and request.get("vaultFileId") == item["fileId"]
                and request.get("referenceId") == ref
                and request.get("vaultNotificationStatus") == "ACCEPTED"):
            result["autoAccess"] = _logged_send_evidence(
                str(request.get("vaultNotificationStatusMessageId") or ""), None)
    # The outbound payment template is bound by the same server-owned reference.
    outbound = _table(os.environ.get(
        "WA_OUTBOUND_TABLE", "stack-wecare-digital-WhatsAppOutboundTable"))
    payment_projections = outbound.query(
        IndexName="paymentReferenceId-index",
        KeyConditionExpression="paymentReferenceId = :ref",
        ExpressionAttributeValues={":ref": ref},
        Limit=15,
    ).get("Items") or []
    # This GSI is INCLUDE, not ALL: it projects the primary id and sender IDs
    # but NOT WAMID, createdAt or message type. Read each exact projected PK,
    # keeping the lookup bounded and refusing unmatched references.
    payment_rows = []
    for projection in payment_projections:
        row_id = str(projection.get("id") or "")
        if not row_id or len(row_id) > 160:
            continue
        row = outbound.get_item(
            Key={"id": row_id}, ConsistentRead=True).get("Item") or {}
        if row.get("paymentReferenceId") == ref:
            payment_rows.append(row)
    native = [row for row in payment_rows
              if str(row.get("direction") or "").lower() == "outbound"
              and str(row.get("messageType") or "").lower() in ("template", "payment")
              and str(row.get("whatsappMessageId") or "").startswith("wamid.")]
    if native:
        chosen = min(native, key=lambda row: int(row.get("createdAt") or 0))
        result["nativePay"] = _logged_send_evidence(
            str(chosen.get("whatsappMessageId") or ""),
            chosen.get("createdAt"))
    # The reference join is exact and bounded; two invoices are ambiguous evidence.
    invoices = _table(os.environ.get(
        "INVOICES_TABLE", "stack-wecare-digital-InvoicesTable")).query(
        IndexName="referenceId-index",
        KeyConditionExpression="referenceId = :ref",
        ExpressionAttributeValues={":ref": ref},
        Limit=2,
    ).get("Items") or []
    paid = [row for row in invoices
            if row.get("referenceId") == ref
            and str(row.get("paymentStatus") or "").lower() == "paid"
            and row.get("invoiceId")]
    if len(invoices) != 1 or len(paid) != 1:
        return result
    invoice_id = str(paid[0]["invoiceId"])
    logs = _table(os.environ.get(
        "INVOICE_DELIVERY_TABLE", "stack-wecare-digital-InvoiceDeliveryLogTable")).query(
        KeyConditionExpression="invoiceId = :id",
        ExpressionAttributeValues={":id": invoice_id},
        ScanIndexForward=False, Limit=30,
        ConsistentRead=True,
    ).get("Items") or []
    for row in logs:
        channel = str(row.get("channel") or "").lower()
        status = str(row.get("status") or "").lower()
        if channel == "whatsapp_order_status":
            key = status if status in ("processing", "completed") else ""
        elif channel == "whatsapp":
            key = "invoice"
        else:
            continue
        if key and result[key]["status"] == "NOT_TRACKED":
            evidence = _logged_send_evidence(
                str(row.get("waMessageId") or ""), row.get("timestamp"))
            # An invoice log can contain a definite provider refusal as well.
            if evidence["status"] == "NOT_TRACKED" and status in ("failed", "rejected"):
                evidence = {"status": "FAILED", "observedAt": int(row.get("timestamp") or 0),
                            "source": "SEND_LOG"}
            result[key] = evidence
    return result


def _admin_message_log(file_id: str, origin: str) -> Dict[str, Any]:
    """Staff-only status view for provider IDs belonging to one bound Vault file.

    Does NOT expose customer phone, file keys, raw WAMIDs, payment details or
    invite any resend. Stages 2-4 may have their own order/invoice log rows but
    are never guessed from the file's paid marker.
    """
    # Unlike a send, historical audits must remain accessible for revoked rows.
    # The admin route has already passed require_auth(Operator), and accepts
    # only the file ID, never customer-provided phone or provider IDs.
    item = _table(FILES_TABLE).get_item(
        Key={"fileId": file_id}, ConsistentRead=True).get("Item") or {}
    if not item:
        return _no_store(cors_response(404, {"error": "UNKNOWN_FILE"}, origin))
    offer = _message_status_for_verified_send(str(item.get("lastOfferMessageId") or ""))
    access = _message_status_for_verified_send(str(item.get("lastAccessMessageId") or ""))
    try:
        paid_evidence = _verified_vault_payment_evidence(item)
        scope = "file_bound_verified_paid_reference"
    except ClientError as exc:
        logger.warning(json.dumps({"event": "vault_paid_message_audit_unavailable",
                                   "error": exc.response.get("Error", {}).get("Code", "AWS_ERROR")}))
        paid_evidence = {}
        scope = "file_bound_only_paid_audit_unavailable"
    return _no_store(cors_response(200, {
        "fileId": file_id,
        "evidence": {"offer": offer, **paid_evidence, "access": access},
        "scope": scope,
        "otherStages": "NO_GUESSED_WAMIDS_OR_DELIVERY",
    }, origin))


def _admin_revoke(file_id: str, event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Revoke rather than delete: the audit trail of who was charged survives."""
    try:
        _table(FILES_TABLE).update_item(
            Key={"fileId": file_id},
            UpdateExpression="SET #s = :revoked, revokedAt = :now, revokedBy = :by",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":revoked": "revoked",
                ":now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                ":by": str((event.get("_auth") or {}).get("username", ""))[:128],
            },
            ConditionExpression="attribute_exists(fileId)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return cors_response(404, {"error": "Unknown fileId"}, origin)
        raise
    item = _table(FILES_TABLE).get_item(
        Key={"fileId": file_id}, ConsistentRead=True).get("Item") or {}
    source_document_id = str(item.get("sourceDocumentId") or "")
    if source_document_id:
        try:
            _table(DOCUMENTS_TABLE).update_item(
                Key={"documentId": source_document_id},
                UpdateExpression="REMOVE vaultFileId, vaultPublishedAt SET updatedAt=:now",
                ConditionExpression="vaultFileId=:file",
                ExpressionAttributeValues={":file": file_id, ":now": int(time.time())},
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
    logger.info(json.dumps({"event": "secure_file_revoked", "fileId": file_id,
                            "sourceDocumentId": source_document_id}))
    return cors_response(200, {"fileId": file_id, "status": "revoked"}, origin)



# ── Vault native WhatsApp payment, or resend the Access Vault link ────────────

BUSINESS_API_FUNCTION = os.environ.get(
    "VAULT_PAYMENT_FUNCTION", "wecare-whatsapp-business-api:live")

#: One interpretation of the native Vault payment sender's outcomes for both customer and staff
#: callers. The sender is the existing WhatsApp ORDER_DETAILS / Review and Pay rail; this Lambda
#: never builds a payment payload, never trusts a browser amount and never opens the website cart.
_PAYMENT_REQUEST_REPLIES: Dict[str, Tuple[int, str]] = {
    "PAYMENT_REQUEST_SENT": (
        200, "Payment request sent to the registered WhatsApp number. Complete Review and Pay there."),
    "PAYMENT_REQUEST_UNCONFIRMED": (
        202, "The payment request may have been sent. Check WhatsApp before trying again."),
    "CATALOG_SERVICE_RECONCILIATION_REQUIRED": (
        202, "A Vault payment may already be in progress. Check WhatsApp before trying again."),
    "CATALOG_SERVICE_ALREADY_PREPARING": (
        202, "A Vault payment request is already being prepared. Check WhatsApp."),
    "CATALOG_SERVICE_ALREADY_PREPARED": (
        202, "A Vault payment request is already in progress. Check WhatsApp."),
    "NATIVE_SERVICE_PAYMENT_ALREADY_IN_PROGRESS": (
        409, "Another service payment is already in progress. Complete it in WhatsApp before starting Vault payment."),
    "VAULT_ACCESS_ACTIVE": (
        409, "This file is already paid and available. Do not pay again."),
    "PAID_UNVERIFIED": (
        409, "A payment is recorded for this file but access is still being confirmed. Do not pay again."),
    "CONTACT_AMBIGUOUS": (
        409, "This WhatsApp number is linked to more than one contact. Nothing was sent."),
    "WHATSAPP_IDENTITY_REQUIRED": (
        409, "The registered WhatsApp identity is not ready for payment. Nothing was sent."),
    "VAULT_FILE_UNAVAILABLE": (
        409, "This document is not available for Vault payment."),
    "VAULT_PAYMENT_NOT_PREPARED": (
        409, "Vault payment could not be prepared. Nothing was sent."),
    "NATIVE_SERVICE_META_NOT_READY": (
        503, "WhatsApp payment is temporarily unavailable. Nothing was sent."),
    "NATIVE_SERVICE_WRITEBACK_NOT_READY": (
        503, "WhatsApp payment is temporarily unavailable. Nothing was sent."),
    "NATIVE_SERVICE_ROLLOUT_DISABLED": (
        503, "WhatsApp Vault payments are switched off. Nothing was sent."),
    "CATALOG_SERVICE_UNAVAILABLE": (
        503, "Vault payment is temporarily unavailable. Nothing was sent."),
    "PAYMENT_REQUEST_NOT_SENT": (
        502, "The payment request was not sent. Nothing was charged."),
    "PAYMENT_REQUEST_REFUSED": (
        502, "The payment request was refused before payment. Nothing was charged."),
    "PAYMENT_INITIATION_DISABLED": (
        503, "WhatsApp payment is temporarily unavailable. Nothing was sent."),
}


#: This is a manual notification, not a payment order. API acceptance is not delivery.
_VAULT_OFFER_REPLIES: Dict[str, Tuple[int, str]] = {
    "VAULT_OFFER_SENT": (
        200, "Vault-ready message accepted by WhatsApp. The customer can tap Unlock Vault to request payment."),
    "VAULT_OFFER_UNCONFIRMED": (
        202, "The Vault-ready message may have been sent. Check the chat before trying again."),
    "VAULT_OFFER_RECENT": (
        202, "A Vault-ready message was recently attempted. Check the chat before resending."),
    "VAULT_OFFER_NOT_SENT": (
        502, "The Vault-ready message was not sent. Nothing was charged."),
    "VAULT_ACCESS_ACTIVE": (
        409, "This file is already paid. Send Access Vault instead of another payment offer."),
    "CONTACT_AMBIGUOUS": (
        409, "This WhatsApp number is linked to more than one customer. Nothing was sent."),
    "VAULT_FILE_UNAVAILABLE": (
        409, "This file is not available for a Vault-ready message."),
    "NATIVE_SERVICE_ROLLOUT_DISABLED": (
        503, "The WhatsApp Vault service is currently disabled. Nothing was sent."),
}


def _owned_file_for_admin(file_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The active, owner-bound file row, or (None, refusal code)."""
    item = _table(FILES_TABLE).get_item(Key={"fileId": file_id}, ConsistentRead=True).get("Item")
    if not item:
        return None, "UNKNOWN_FILE"
    if item.get("status") != "active":
        return None, "FILE_NOT_ACTIVE"
    if not item.get("ownerCustomerId") or not item.get("ownerPhone"):
        # A legacy ownerless file: a matching phone must never establish its owner.
        return None, "FILE_OWNER_UNBOUND"
    return item, None


def _admin_staff_download(file_id: str, origin: str) -> Dict[str, Any]:
    """Operator-only short-lived preview; bypasses customer payment, not staff auth."""
    item, refusal = _owned_file_for_admin(file_id)
    if refusal:
        return cors_response(404 if refusal == "UNKNOWN_FILE" else 409,
                             {"error": refusal}, origin)
    if not _vault_file_storage_ready(item):
        return _vault_storage_unavailable(origin)
    logger.info(json.dumps({"event": "vault_staff_download_authorized", "fileId": file_id[:120]}))
    return _no_store(cors_response(
        200, {"url": _download_url(item), "expiresInSeconds": DOWNLOAD_URL_TTL}, origin))


def _file_access_state(item: Dict[str, Any], now: int) -> str:
    """Authoritative sale/download state for one owner-bound file."""
    eid = str(item.get("vaultEntitlementId") or "")
    entitlement = None
    if eid:
        row = _table(GRANTS_TABLE).get_item(Key={"grantId": eid}, ConsistentRead=True).get("Item") or {}
        if (row.get("recordType") == "VAULT_ENTITLEMENT" and row.get("entitlementState") == "ACTIVE"
                and row.get("customerId") == item.get("ownerCustomerId")
                and row.get("fileId") == item.get("fileId")):
            entitlement = row
    if entitlement is None and _paid_marks(item):
        entitlement = _entitlement_for_file(str(item["ownerCustomerId"]), str(item["fileId"]))
    return _access_state(item, entitlement, now)


def _start_native_vault_payment(
    item: Dict[str, Any], state: str, origin: str, *, requested_by: str,
    payment_description: str = catalog_service_checkout.VAULT_ITEM_DESCRIPTION_DEFAULT,
) -> Dict[str, Any]:
    """Ask the existing native WhatsApp rail for ONE exact-file Review and Pay.

    The only values passed across the internal boundary are re-read from the owner-bound file row.
    The business-api re-checks the file and customer again, creates the file-bound service intent
    including the durable entitlement proof for EXPIRED renewal, then commerce owns authoritative
    ProductsTable pricing, GST/fees, PaymentAttempt/PAYREF reservation and the Meta ORDER_DETAILS
    send. There is no website cart, no browser amount and no Meta Flow in this Vault path.
    """
    # A published row is not proof that the requested private S3 bytes are
    # actually available. No customer should receive a charge for a dead link.
    if not _vault_file_storage_ready(item):
        return _vault_storage_unavailable(origin)
    if not catalog_service_checkout.valid_vault_item_description(payment_description):
        return cors_response(400, {"error": "INVALID_VAULT_ITEM_DESCRIPTION"}, origin)
    try:
        response = _lambda_client().invoke(
            FunctionName=BUSINESS_API_FUNCTION,
            InvocationType="RequestResponse",
            Payload=json.dumps({
                "internalAction": "catalogService", "action": "sendPayment",
                "fileId": str(item["fileId"]),
                "ownerCustomerId": str(item["ownerCustomerId"]),
                "ownerPhone": str(item["ownerPhone"]),
                "requestedBy": str(requested_by or "")[:64],
                "paymentItemDescription": payment_description,
            }).encode("utf-8"),
        )
        answer = json.loads(response["Payload"].read() or b"{}")
        if response.get("FunctionError"):
            answer = {"outcome": "PAYMENT_REQUEST_UNCONFIRMED"}
    except Exception as exc:  # noqa: BLE001
        # A timeout may happen after Meta accepted the idempotent send. Never auto-retry a money
        # message from here; tell the caller to check WhatsApp.
        logger.warning(json.dumps({"event": "vault_native_payment_invoke_unconfirmed",
                                   "error": type(exc).__name__}))
        answer = {"outcome": "PAYMENT_REQUEST_UNCONFIRMED"}

    outcome = str(answer.get("outcome") or "PAYMENT_REQUEST_UNCONFIRMED")
    try:
        _table(FILES_TABLE).update_item(
            Key={"fileId": str(item.get("fileId") or "")},
            UpdateExpression=("SET lastPaymentRequestedBy=:by, lastPaymentRequestedAt=:at, "
                              "lastPaymentRequestOutcome=:outcome"),
            ExpressionAttributeValues={
                ":by": str(requested_by or "unknown")[:128],
                ":at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                ":outcome": outcome[:80],
            },
        )
    except Exception as exc:  # noqa: BLE001 - audit write must not duplicate a money message
        logger.warning(json.dumps({"event": "vault_payment_actor_audit_failed",
                                   "error": type(exc).__name__}))
    logger.info(json.dumps({"event": "vault_native_payment_requested",
                            "fileId": str(item.get("fileId") or ""),
                            "outcome": outcome, "renewal": state == "EXPIRED",
                            "requestedBy": str(requested_by or "")[:32]}))
    code, message = _PAYMENT_REQUEST_REPLIES.get(
        outcome, (502, "Vault payment could not be started. Nothing was charged."))
    body = {
        "outcome": outcome,
        "fileId": str(item.get("fileId") or ""),
        "message": message,
        "renewal": state == "EXPIRED",
        "accessState": state,
    }
    if code >= 400:
        body["error"] = outcome
    return cors_response(code, body, origin)


def _customer_request_payment(
    file_id: str, event: Dict[str, Any], identity: Dict[str, Any], origin: str,
) -> Dict[str, Any]:
    """Customer Vault CTA -> native WhatsApp Review and Pay for this exact owned file.

    The path parameter only names a candidate. Ownership is re-proven from the customer-pool
    session against both permanent customer id and verified phone before any payment call.
    OPEN/READY and PAID_UNVERIFIED are terminal no-charge answers.
    """
    item = _owned_active_file(file_id, identity)
    if not item:
        return _not_registered(origin)
    # Customer requests NEVER set the item wording. Only the staff Vault editor
    # may choose it, and only for the one ₹49 service item. No body fields read.
    state = _file_access_state(item, int(time.time()))
    if state in ("OPEN", "READY"):
        code, message = _PAYMENT_REQUEST_REPLIES["VAULT_ACCESS_ACTIVE"]
        return cors_response(code, {
            "error": "VAULT_ACCESS_ACTIVE", "outcome": "VAULT_ACCESS_ACTIVE",
            "fileId": file_id, "accessState": state, "message": message,
        }, origin)
    if state == "PAID_UNVERIFIED":
        code, message = _PAYMENT_REQUEST_REPLIES["PAID_UNVERIFIED"]
        return cors_response(code, {
            "error": "PAID_UNVERIFIED", "outcome": "PAID_UNVERIFIED",
            "fileId": file_id, "accessState": state, "message": message,
        }, origin)
    return _start_native_vault_payment(
        item, state, origin, requested_by="customer")



def _admin_send_vault_offer(file_id: str, event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Compatibility tombstone: never emit a new retired Unlock Vault template.

    Previously sent signed quick replies still resolve through catalogService.unlock;
    removing the outbound sender must not strand those existing customers.
    """
    return _no_store(cors_response(410, {
        "error": "VAULT_OFFER_RETIRED",
        "message": "Unlock Vault offers are retired. Send the owner-bound Review & Pay request.",
    }, origin))


def _admin_payment_media_preview(origin: str) -> Dict[str, Any]:
    """Presigned S3 GETs for exactly two approved, non-customer payment images.

    Only staff Operators reach this endpoint. Never accept a caller-supplied key:
    a signing endpoint with any fileId or arbitrary S3 key could bypass the Vault
    payment/ownership gates. These URLs are display-only and expire after 60s.
    """
    from lambda_utils import template_media

    approved = {
        "headerPreviewUrl": "secure/d/public/whatsapp/wa-tpl/whatsapp-header.png",
        "itemPreviewUrl":
            "secure/d/public/whatsapp/wa-tpl/WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png",
    }
    media = {
        "headerPreviewUrl": template_media.PAYMENT_TEMPLATE_HEADER,
        "itemPreviewUrl": template_media.DEFAULT_ORDER_ITEM_THUMBNAIL,
    }
    if any(key not in template_media.RETAINED_MEDIA_KEYS
           or media[name] != "https://wecare.digital/get/" + key
           for name, key in approved.items()):
        return _no_store(cors_response(503, {
            "error": "PAYMENT_MEDIA_NOT_APPROVED",
        }, origin))
    client = _s3_client()
    signed = {}
    try:
        for name, key in approved.items():
            client.head_object(Bucket=BUCKET, Key=key)
            signed[name] = client.generate_presigned_url(
                "get_object", Params={"Bucket": BUCKET, "Key": key},
                ExpiresIn=60, HttpMethod="GET",
            )
    except Exception as error:
        logger.warning(json.dumps({
            "event": "vault_media_preview_unavailable", "reason": type(error).__name__,
        }))
        return _no_store(cors_response(503, {
            "error": "PAYMENT_MEDIA_PREVIEW_UNAVAILABLE",
        }, origin))
    return _no_store(cors_response(200, {**signed, "expiresInSeconds": 60}, origin))

def _admin_request_payment(file_id: str, event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Staff-triggered native Review and Pay for one owner-bound Vault file.

    This uses the same exact-file native WhatsApp payment rail as the customer Vault CTA. The
    legacy sendOffer business-api action remains only as a rolling-deploy alias; no new
    request-ready/Unlock Vault message is created here.
    """
    item, refusal = _owned_file_for_admin(file_id)
    if refusal:
        return cors_response(409 if refusal != "UNKNOWN_FILE" else 404, {"error": refusal}, origin)
    if item.get("sourceDocumentId"):
        system_name = _system_name_for_file(item)
        if str(item.get("displayName") or "") != system_name:
            _table(FILES_TABLE).update_item(
                Key={"fileId": file_id},
                UpdateExpression="SET displayName=:n",
                ExpressionAttributeValues={":n": system_name},
            )
            item["displayName"] = system_name
    try:
        body = json.loads(event.get("body") or "{}")
    except (TypeError, ValueError):
        return cors_response(400, {"error": "INVALID_PAYMENT_REQUEST"}, origin)
    if not isinstance(body, dict):
        return cors_response(400, {"error": "INVALID_PAYMENT_REQUEST"}, origin)
    description = body.get(
        "paymentItemDescription", catalog_service_checkout.VAULT_ITEM_DESCRIPTION_DEFAULT)
    if not catalog_service_checkout.valid_vault_item_description(description):
        return cors_response(400, {"error": "INVALID_VAULT_ITEM_DESCRIPTION"}, origin)
    state = _file_access_state(item, int(time.time()))
    if state in ("OPEN", "READY"):
        code, message = _PAYMENT_REQUEST_REPLIES["VAULT_ACCESS_ACTIVE"]
        return cors_response(code, {
            "error": "VAULT_ACCESS_ACTIVE", "outcome": "VAULT_ACCESS_ACTIVE",
            "fileId": file_id, "accessState": state, "message": message,
        }, origin)
    if state == "PAID_UNVERIFIED":
        code, message = _PAYMENT_REQUEST_REPLIES["PAID_UNVERIFIED"]
        return cors_response(code, {
            "error": "PAID_UNVERIFIED", "outcome": "PAID_UNVERIFIED",
            "fileId": file_id, "accessState": state, "message": message,
        }, origin)
    if description != catalog_service_checkout.VAULT_ITEM_DESCRIPTION_DEFAULT:
        # Staff-customized text is allowed only while the ProductsTable Vault
        # variant is exactly ₹49. Revalidate here as well as during checkout.
        try:
            if not _vault_offer_catalog_price_valid():
                return cors_response(409, {"error": "VAULT_ITEM_NOT_49",
                    "message": "Only the ₹49 Vault item description is editable. Refresh pricing."}, origin)
        except Exception as error:
            logger.warning(json.dumps({"event": "vault_item_price_read_failed",
                                       "reason": type(error).__name__}))
            return cors_response(503, {"error": "VAULT_PRICE_UNAVAILABLE"}, origin)
    return _start_native_vault_payment(
        item, state, origin,
        requested_by=str((event.get("_auth") or {}).get("username", "staff"))[:64],
        payment_description=description)


def _admin_send_access(file_id: str, event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """Resend Access Vault and persist the authenticated staff actor. Never charges."""
    item, refusal = _owned_file_for_admin(file_id)
    if refusal:
        return cors_response(409 if refusal != "UNKNOWN_FILE" else 404, {"error": refusal}, origin)
    state = _file_access_state(item, int(time.time()))
    if state == "UNPAID":
        return cors_response(409, {"error": "NOT_PAID",
                                   "message": "This file has not been paid for. Request payment instead."},
                             origin)
    if state == "EXPIRED":
        return cors_response(409, {"error": "WINDOW_EXPIRED",
                                   "message": "The paid access window has ended. Send a renewal payment request instead."}, origin)
    if state == "PAID_UNVERIFIED":
        return cors_response(409, {"error": "PAID_UNVERIFIED",
                                   "message": "A payment is recorded for this file but its access "
                                              "could not be read. Reconcile it; nothing was sent."},
                             origin)
    # Do not send a download link for a missing private S3 object.
    if not _vault_file_storage_ready(item):
        return _vault_storage_unavailable(origin)
    from whatsapp_delivery import send_vault_link

    actor = str((event.get("_auth") or {}).get("username", "staff"))[:128]
    ok, detail = send_vault_link(phone=str(item["ownerPhone"]), file_row=item)
    outcome = "VAULT_LINK_SENT" if ok else "VAULT_LINK_NOT_SENT"
    # Only a confirmed provider ID can later be joined to webhook delivery events.
    wamid = str(detail) if ok and str(detail).startswith("wamid.") and len(str(detail)) <= 512 else ""
    try:
        _table(FILES_TABLE).update_item(
            Key={"fileId": file_id},
            UpdateExpression=("SET lastAccessSentBy=:by, lastAccessSentAt=:at, "
                              "lastAccessSendOutcome=:outcome, lastAccessMessageId=:wamid"),
            ExpressionAttributeValues={
                ":by": actor,
                ":at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                ":outcome": outcome,
                ":wamid": wamid,
            },
        )
    except Exception as exc:  # noqa: BLE001 - send result stands even if audit enrichment fails
        logger.warning(json.dumps({"event": "vault_access_actor_audit_failed",
                                   "error": type(exc).__name__}))
    logger.info(json.dumps({"event": "vault_access_link_resent", "fileId": file_id,
                            "ok": ok, "requestedBy": actor[:32]}))
    if not ok:
        return cors_response(502, {"error": outcome, "outcome": outcome,
                                   "message": "Nothing could be sent: " + detail}, origin)

    # If a paid window was READY (e.g. automatic delivery was missed), the first
    # accepted Access Vault message must start the SAME 24-hour clock. A free
    # staff resend may never hold a READY entitlement open indefinitely.
    # When OPEN, this function NEVER opens another window or extends the end.
    if state == "READY":
        try:
            entitlement = _entitlement_for_file(str(item["ownerCustomerId"]), file_id)
            if (not entitlement
                    or entitlement.get("ownerPhone") != item.get("ownerPhone")
                    or vault_window.access_state(entitlement, int(time.time())) not in ("READY", "OPEN")):
                raise ValueError("Paid window could not be verified")
            refreshed = _open_access_window(entitlement)
            if not vault_window.window_open(refreshed, int(time.time())):
                raise ValueError("Paid window did not open")
            state = "OPEN"
        except Exception as error:
            # Meta may already have accepted the link. Never call send again.
            logger.warning(json.dumps({"event": "vault_resend_window_unconfirmed",
                                       "error": type(error).__name__,
                                       "fileId": file_id}))
            return cors_response(202, {
                "error": "VAULT_LINK_ACCEPTED_WINDOW_UNVERIFIED",
                "outcome": "VAULT_LINK_ACCEPTED_WINDOW_UNVERIFIED",
                "message": "WhatsApp accepted the link, but the 24-hour window needs reconciliation. Do not resend automatically.",
            }, origin)
    return cors_response(200, {"outcome": outcome, "fileId": file_id,
                               "accessState": state,
                               "message": "The Access Vault link was accepted by WhatsApp. Delivery is not yet verified."}, origin)


# ── durable paid entitlement + renewable transport sessions ──────────────────

ENTITLEMENT_PREFIX = "vault-entitlement#"
SESSION_PREFIX = "vault-session#"


def _entitlement_id(customer_id: str, file_id: str) -> str:
    return ENTITLEMENT_PREFIX + str(customer_id) + "#" + str(file_id)


def _entitlement_for_file(customer_id: str, file_id: str) -> Optional[Dict[str, Any]]:
    """The caller's durable entitlement for one file, or None. Read-only; no migration."""
    if not customer_id or not file_id:
        return None
    row = _table(GRANTS_TABLE).get_item(
        Key={"grantId": _entitlement_id(customer_id, file_id)}, ConsistentRead=True
    ).get("Item") or {}
    if (row.get("recordType") == "VAULT_ENTITLEMENT"
            and row.get("entitlementState") == "ACTIVE"
            and row.get("customerId") == customer_id
            and row.get("fileId") == file_id):
        return row
    return None


def _window_already_open(identity: Dict[str, Any], file_id: str) -> bool:
    """feat-006: True when the caller already has an OPEN access window for this file.

    The 'never charge while a window is open' guard. ₹49 buys one window; inside it a new
    charge would be a double-charge for access the customer already has, so the charge
    entrypoints refuse and the customer is pointed at their live access instead. Once the
    window closes this returns False and a fresh ₹49 opens a NEW window on the SAME durable
    entitlement (Path C renewal) — no second entitlement row.
    """
    entitlement = _entitlement_for_file(str(identity.get("subject") or ""), file_id)
    return vault_window.window_open(entitlement, int(time.time()))


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


def _open_access_window(entitlement: Dict[str, Any], now: Optional[int] = None) -> Dict[str, Any]:
    """Open (or renew) the 24h access window on a durable entitlement, at delivery.

    ₹49 buys one window of ``VAULT_ACCESS_WINDOW_HOURS``; inside it every download is free. This
    is the only place the window is opened. It is idempotent: if a window is already open,
    ``vault_window.open_window`` returns no changes, so a duplicate tap / webhook replay neither
    re-charges nor double-increments ``accessWindowCount``. The write is conditioned so two
    concurrent opens converge on one window rather than racing the counter.
    """
    now = int(time.time()) if now is None else int(now)
    fields, opened = vault_window.open_window(entitlement, now)
    if not opened:
        return entitlement
    try:
        _table(GRANTS_TABLE).update_item(
            Key={"grantId": entitlement["grantId"]},
            UpdateExpression=(
                "SET accessWindowStartedAt = :s, accessWindowEndsAt = :e, "
                "accessWindowCount = :c"
            ),
            # Only advance from the count we read: a racing opener either saw the same prior
            # count (one wins, one no-ops on the condition) or a later one (we yield).
            ConditionExpression=(
                "attribute_exists(grantId) AND entitlementState = :active AND "
                "(attribute_not_exists(accessWindowCount) OR accessWindowCount = :prev)"
            ),
            ExpressionAttributeValues={
                ":s": fields["accessWindowStartedAt"],
                ":e": fields["accessWindowEndsAt"],
                ":c": fields["accessWindowCount"],
                ":prev": vault_window.window_count(entitlement),
                ":active": "ACTIVE",
            },
        )
        logger.info(json.dumps({
            "event": "vault_access_window_opened",
            "entitlementId": entitlement["grantId"],
            "windowCount": fields["accessWindowCount"],
            "endsAt": fields["accessWindowEndsAt"],
        }))
    except ClientError as exc:
        # A lost race means another opener already set a window; re-read and return current truth.
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    refreshed = _table(GRANTS_TABLE).get_item(
        Key={"grantId": entitlement["grantId"]}, ConsistentRead=True).get("Item") or entitlement
    return refreshed


def _vault_file_storage_ready(item: Dict[str, Any]) -> bool:
    """Never issue a dead or untrusted S3 link as if it were a successful download.

    The private-object HEAD happens after verified customer ownership + paid window
    checks. It cannot reveal existence to an anonymous customer and reads no bytes.
    """
    key = str(item.get("s3Key") or "")
    if not key.startswith(SECURE_PREFIX) or key.endswith("/") or len(key) > 1024:
        logger.warning(json.dumps({"event": "vault_download_invalid_storage_reference",
                                   "fileId": str(item.get("fileId") or "")[:120]}))
        return False
    try:
        result = _s3_client().head_object(Bucket=BUCKET, Key=key)
        return int(result.get("ContentLength") or 0) > 0
    except ClientError as exc:
        logger.warning(json.dumps({"event": "vault_download_storage_check_failed",
                                   "errorCode": exc.response.get("Error", {}).get("Code", ""),
                                   "fileId": str(item.get("fileId") or "")[:120]}))
        return False


def _vault_storage_unavailable(origin: str) -> Dict[str, Any]:
    return _no_store(cors_response(503, {
        "error": "VAULT_STORAGE_UNAVAILABLE",
        "message": "The private file could not be verified in storage. Do not pay again. Contact support.",
    }, origin))


def _issue_download_session(entitlement: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    """Record one expiring transport attempt without changing financial entitlement."""
    now = int(time.time())
    # A presigned URL must expire NO LATER THAN the paid window. A link issued in
    # the last few seconds must not create free access beyond the 24h deadline.
    remaining = vault_window.window_ends_at(entitlement) - now
    if remaining <= 0:
        raise ValueError("paid access window expired before issuing transport")
    ttl = min(int(DOWNLOAD_URL_TTL), remaining)
    session_id = SESSION_PREFIX + uuid.uuid4().hex
    url = _download_url(item, ttl=ttl)
    _table(GRANTS_TABLE).put_item(Item={
        "grantId": session_id, "recordType": "VAULT_DOWNLOAD_SESSION",
        "entitlementId": entitlement["grantId"], "customerId": entitlement["customerId"],
        "fileId": entitlement["fileId"], "ownerPhone": entitlement["ownerPhone"],
        "createdAt": now, "expiresAt": now + ttl,
    })
    return {
        "downloadUrl": url,
        "expiresInSeconds": ttl,
        "downloadSessionId": session_id,
        "entitlementId": entitlement["grantId"],
    }


def _queue_vault_review(entitlement: Dict[str, Any]) -> None:
    """Retired: the paid invoice template owns the single Leave Review Flow button."""
    return None


# ── customer: list, order, download ───────────────────────────────────────────

def _customer_file_view(item: Dict[str, Any], identity: Dict[str, Any], now: int) -> Dict[str, Any]:
    """One authorised file's public view, reused by list and exact-file reads.

    Do not infer payment from the pointer alone. Preserve durable entitlement
    fallback when a post-capture file pointer was not written.
    """
    access_id = str(item.get('vaultEntitlementId') or item.get('vaultAccessGrantId') or '')
    entitlement = _active_entitlement(access_id, item['fileId'], identity) if access_id else None
    if entitlement is None and _paid_marks(i):
        # The pointer write after payment is best effort; the deterministic entitlement is
        # the durable record, so a lost pointer must not make a paid file look unpaid.
        fallback = _entitlement_for_file(str(identity['subject']), str(item['fileId']))
        if fallback and fallback.get('ownerPhone') == identity['phone']:
            entitlement = fallback
    # The window view is the customer's own now, so the page can say "open until …",
    # "opens on first download" or "renew" instead of guessing from a failed download.
    view = _public_file(i, admin=False, entitlement=entitlement, now=now)
    if entitlement:
        view['paidEntitlementId'] = entitlement['grantId']
        view['paidGrantId'] = entitlement['grantId']  # old website bundles
        view['deliveryStatus'] = 'READY'
    return view


def _customer_exact_file(file_id: str, identity: Dict[str, Any], origin: str) -> Dict[str, Any]:
    """O(1) owner-scoped lookup for /vault/?file= links, even beyond 100 rows."""
    # Invalid and unowned/revoked IDs get exactly the same response.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", file_id or ""):
        return _no_store(cors_response(404, {"error": "File unavailable"}, origin))
    item = _owned_active_file(file_id, identity)
    if not item:
        return _no_store(cors_response(404, {"error": "File unavailable"}, origin))
    view = _customer_file_view(item, identity, int(time.time()))
    return _no_store(cors_response(200, {"files": [view], "count": 1}, origin))


def _customer_list(identity: Dict[str, Any], origin: str) -> Dict[str, Any]:
    result = _table(FILES_TABLE).query(
        IndexName="owner-created-index",
        KeyConditionExpression="ownerPhone = :p",
        ExpressionAttributeValues={":p": identity["phone"]},
        ScanIndexForward=False,
        Limit=100,
    )
    items = []
    now = int(time.time())
    for projected in result.get('Items', []):
        i = _table(FILES_TABLE).get_item(Key={'fileId': projected['fileId']}, ConsistentRead=True).get('Item') or {}
        if (i.get('status') != 'active' or i.get('ownerPhone') != identity['phone']
                or not identity.get('subject') or i.get('ownerCustomerId') != identity['subject']):
            continue
        items.append(_customer_file_view(i, identity, now))
    return cors_response(
        200,
        {
            "files": items,
            "count": len(items),
        },
        origin,
    )


def _owned_active_file(file_id: str, identity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The record, but only if this caller owns it and it is active.

    Every failure mode returns None so callers cannot tell them apart. Strongly consistent, so a
    file revoked a moment ago cannot still be signed for download from a stale replica.
    """
    item = _table(FILES_TABLE).get_item(Key={"fileId": file_id}, ConsistentRead=True).get("Item")
    if not item or item.get("status") != "active":
        return None
    if item.get("ownerPhone") != identity["phone"]:
        return None
    if not identity.get('subject') or item.get('ownerCustomerId') != identity['subject']:
        return None
    return item


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
    entitlement = _ensure_entitlement(refreshed)
    if not entitlement:
        return False, "paid entitlement could not be established"
    _point_file_at_entitlement(grant, entitlement)
    if grant.get("channel") != "whatsapp":
        return True, "confirmed; web channel collects by renewable entitlement"
    return deliver_over_whatsapp(str(grant["grantId"]))


def _point_file_at_entitlement(grant: Dict[str, Any], entitlement: Dict[str, Any]) -> bool:
    """Record the paid entitlement on the file row, which the Vault page's list reads.

    Makes customer-list reads direct and independent of the expiring legacy grant, and is what
    gives a WhatsApp Vault link a Download button. Never raises: payment and entitlement stay
    durable even if this derived pointer needs reconciliation.
    """
    try:
        _table(FILES_TABLE).update_item(
            Key={"fileId": grant["fileId"]},
            UpdateExpression="SET vaultEntitlementId = :e, vaultPaymentStatus = :paid",
            ConditionExpression="ownerCustomerId = :owner AND #s = :active",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":e": entitlement["grantId"], ":paid": "PAID",
                ":owner": grant["customerId"], ":active": "active",
            },
        )
        return True
    except ClientError:
        logger.warning(json.dumps({"event": "vault_entitlement_pointer_write_failed",
                                   "fileId": grant.get("fileId", "")}))
        return False


def _reconcile_grant(grant_id: str, file_id: str, identity: Dict[str, Any]) -> bool:
    """Mark an unpaid grant paid if Razorpay says the order was actually captured.

    The safety net for a webhook that never arrives. Returns True only when the grant
    was genuinely unspent, belongs to this caller and this file, and Razorpay confirms
    a captured payment.

    Deliberately narrow. It refuses to touch a grant that is already ``consumed``, so
    it cannot be used to replay a spent download. The ownership checks live here; the
    actual payment decision and the write are delegated to ``_confirm_with_razorpay``,
    which is the only function in this system that may set ``paid``.

    Not flag-gated. 27099fc3 retired SECURE_FILES_PAYMENT_ENABLED so that historical grants
    keep settling, but left a call to the deleted flag reader here; a customer presenting an
    unpaid legacy grant then hit a NameError and a 500 instead of this reconciliation.
    """
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
    # A consumed+unpaid legacy row is internally inconsistent: historical redeem only consumed
    # rows that were already paid. Do not let reconciliation turn corrupted state into access.
    if grant.get("consumed"):
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
    # A reconcile means a fresh payment just confirmed, so this opens its window — the same
    # delivery-starts-the-clock rule as the main redeem path, and the same paid-window rule.
    if not _vault_file_storage_ready(item):
        return _vault_storage_unavailable(origin)
    now = int(time.time())
    if not vault_window.window_open(entitlement, now):
        entitlement = _open_access_window(entitlement, now)
    if not vault_window.window_open(entitlement, now):
        return _window_closed(entitlement, origin)
    # Revalidate expiry after S3 HEAD/entitlement writes; no URL past window end.
    if vault_window.window_ends_at(entitlement) <= int(time.time()):
        return _window_closed(entitlement, origin)
    try:
        payload = _issue_download_session(entitlement, item)
    except ValueError:
        return _window_closed(entitlement, origin)
    payload["accessWindowEndsAt"] = vault_window.window_ends_at(entitlement)
    payload["accessWindowCount"] = vault_window.window_count(entitlement)
    _queue_vault_review(entitlement)
    return cors_response(200, payload, origin)


def _safe_download_filename(item: Dict[str, Any]) -> str:
    system_name = _system_name_for_file(item)
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", os.path.basename(system_name))[:180]
    if not safe.startswith("wecare-digital-") or safe in ("wecare-digital-",):
        safe = "wecare-digital-" + uuid.uuid4().hex + _safe_extension(system_name)
    return safe


def _download_url(item: Dict[str, Any], ttl: Optional[int] = None) -> str:
    """A presigned GET that downloads under the readable filename.

    ``ttl`` defaults to the short web value: the browser follows the redeem redirect at once.
    """
    return _s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET,
            "Key": item["s3Key"],
            # Keep content-disposition strictly ASCII, even for a legacy row with
            # arbitrary displayName. New names remain exactly wecare-digital-UUID.ext.
            "ResponseContentDisposition": (
                f'attachment; filename="{_safe_download_filename(item)}"'
            ),
        },
        ExpiresIn=int(ttl or DOWNLOAD_URL_TTL),
    )


def open_vault_access_window(grant_id: str) -> Tuple[bool, str]:
    """Open the next already-paid Vault window without sending a second message.

    The caller supplies only a grant id. Ownership, file identity and the durable entitlement
    are re-derived here, and the shared window writer refuses to open anything unless an unused
    paid window exists. The paid WhatsApp service flow calls this immediately before sending
    the approved Access Vault template, so delivery starts the same 24-hour clock as the
    secure-files WhatsApp delivery path.
    """
    grant = _table(GRANTS_TABLE).get_item(
        Key={"grantId": grant_id}, ConsistentRead=True).get("Item") or {}
    if not grant or not grant.get("paid"):
        return False, "grant is not paid"

    file_id = str(grant.get("fileId") or "")
    item = _table(FILES_TABLE).get_item(
        Key={"fileId": file_id}, ConsistentRead=True).get("Item") or {}
    if (not item or item.get("status") != "active"
            or item.get("ownerPhone") != grant.get("ownerPhone")
            or not grant.get("customerId")
            or item.get("ownerCustomerId") != grant.get("customerId")):
        return False, "grant and file ownership do not match"

    entitlement = _ensure_entitlement(grant)
    if not entitlement:
        return False, "paid entitlement could not be established"
    if item.get("vaultEntitlementId") != entitlement["grantId"]:
        _point_file_at_entitlement(grant, entitlement)

    before = vault_window.window_count(entitlement)
    refreshed = _open_access_window(entitlement)
    if not vault_window.window_open(refreshed, int(time.time())):
        return False, "no paid access window is available"
    return True, "window_open:" + str(max(before, vault_window.window_count(refreshed)))


def deliver_over_whatsapp(grant_id: str) -> Tuple[bool, str]:
    """Send the paid file to the customer on WhatsApp. Called only after payment.

    Lives here rather than in the webhook so the ownership and deliverability rules sit
    next to the data that defines them. The webhook calls it by grant id and nothing
    else, so there is no path by which a caller can name a file directly.
    """
    grant = _table(GRANTS_TABLE).get_item(Key={"grantId": grant_id}, ConsistentRead=True).get("Item")
    if not grant or not grant.get("paid"):
        return False, "grant is not paid"

    item = _table(FILES_TABLE).get_item(
        Key={"fileId": grant["fileId"]}, ConsistentRead=True).get("Item")
    if not item or item.get("status") != "active":
        return False, "file is not active"
    if item.get("ownerPhone") != grant.get("ownerPhone"):
        return False, "grant and file disagree on owner"
    if not grant.get('customerId') or item.get('ownerCustomerId') != grant['customerId']:
        return False, "grant and file disagree on permanent owner"

    # The message only links to the Vault page, so the entitlement and the file's pointer to
    # it must exist BEFORE it is sent: that page shows a Download button only for a file whose
    # row names an active entitlement. confirm_and_deliver writes both already; this path is
    # also reached directly (internalAction deliverOverWhatsApp, the delivery reconciler).
    entitlement = _ensure_entitlement(grant)
    if not entitlement:
        return False, "paid entitlement could not be established"
    if item.get("vaultEntitlementId") != entitlement["grantId"]:
        _point_file_at_entitlement(grant, entitlement)

    from whatsapp_delivery import send_vault_link

    # One approved template for every deliverable type; see whatsapp_delivery's docstring.
    ok, detail = send_vault_link(phone=str(grant["ownerPhone"]), file_row=item)

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

    # feat-004: the 24h window starts AT DELIVERY, for the WhatsApp entry path too — not only
    # on the web redeem. On a successful send, open (or confirm) the window on the durable
    # entitlement so both entry paths start the same clock. Idempotent via _open_access_window,
    # so a duplicate webhook / resend does not re-open or double-count. A failed send leaves the
    # window closed, which is correct: nothing was delivered, so the clock has not started.
    if ok:
        _open_access_window(entitlement)

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

    # The access window governs free re-download. The FIRST redeem after a paid entitlement opens
    # the window (delivery is when the clock starts, per the owner rule); redeems inside the
    # window are free; once it closes, access needs a fresh ₹49 (feat-006 renewal), so we refuse
    # here rather than hand out transport the customer has not paid for.
    # Storage must exist BEFORE we open a paid window, otherwise a missing object
    # consumes an entire 24-hour purchase on a failed download.
    if not _vault_file_storage_ready(item):
        return _vault_storage_unavailable(origin)
    now = int(time.time())
    if vault_window.window_open(entitlement, now):
        pass  # inside an open window — free re-download
    elif vault_window.unused_paid_windows(entitlement) > 0:
        # A paid window not opened yet (the first purchase, or a renewal): this download opens it.
        entitlement = _open_access_window(entitlement, now)
    if not vault_window.window_open(entitlement, now):
        return _window_closed(entitlement, origin)

    # Revalidate expiry after S3 HEAD/entitlement writes; no URL past window end.
    if vault_window.window_ends_at(entitlement) <= int(time.time()):
        return _window_closed(entitlement, origin)
    try:
        payload = _issue_download_session(entitlement, item)
    except ValueError:
        return _window_closed(entitlement, origin)
    payload["accessWindowEndsAt"] = vault_window.window_ends_at(entitlement)
    payload["accessWindowCount"] = vault_window.window_count(entitlement)
    _queue_vault_review(entitlement)
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
        "windowEndsAt": vault_window.window_ends_at(entitlement),
    }))
    return cors_response(200, payload, origin)



# ── Drop Docs: make a document private BEFORE it is a document ────────────────
#
# A Drop Docs document can arrive over WhatsApp, where `inbound-whatsapp-handler` writes it
# to `secure/d/public/whatsapp/incoming/` - a prefix CloudFront E2GP22R4BIFGQ3 serves
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
    # `phone_verified=True` is a fact here, not an assumption: `_customer_identity` returns None
    # unless `phone_number_verified` was the string 'true'.
    return customer_auth.CustomerIdentity(
        customer_id=subject, phone=identity.get("phone", ""), subject=subject,
        phone_verified=True)


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


# ── operator-approved Vault scheduled actions; never generic template sends ─────

VAULT_SCHEDULE_TABLE = os.environ.get(
    "SCHEDULED_TABLE", "stack-wecare-digital-ScheduledMessagesTable")
VAULT_SCHEDULE_KIND = "VAULT_ACTION_V1"
VAULT_SCHEDULE_ACTIONS = {"payment", "access"}  # legacy offer schedules fail closed
VAULT_SCHEDULE_MAX_ITEMS = 20
_DDB_SERIALIZER = TypeSerializer()


def _ddb_encoded(value: Any) -> Dict[str, Any]:
    return _DDB_SERIALIZER.serialize(value)


def _schedule_time(raw: Any) -> str:
    """Canonical UTC ISO time; 10-minute preflight and 30-day max."""
    if not isinstance(raw, str) or len(raw) > 48:
        raise ValueError("Scheduled time must be an ISO date with timezone")
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Invalid scheduled time") from None
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Scheduled time requires a timezone")
    moment = moment.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    if not now + timedelta(minutes=10) <= moment <= now + timedelta(days=30):
        raise ValueError("Choose a time at least 10 minutes ahead and within 30 days")
    return moment.isoformat(timespec="microseconds")


def _vault_offer_catalog_price_valid() -> bool:
    """Match the approved ₹49 template to the *live* ProductsTable variant.

    The customer checkout still owns pricing. This only refuses an advertising
    mismatch and NEVER supplies an amount to checkout.
    """
    from lambda_utils.ecommerce import service_pricing_native, service_requests
    sku = service_requests.SERVICE_VARIANT_BY_KIND[service_requests.VAULT]
    table = _table(os.environ.get("PRODUCTS_TABLE", "stack-wecare-digital-ProductsTable"))
    for product_id in service_requests.SERVICE_PRODUCT_IDS:
        row = table.get_item(Key={"id": product_id}, ConsistentRead=True).get("Item") or {}
        if row.get("status") != "active":
            continue
        for variant in row.get("variants") or []:
            if str(variant.get("sku") or variant.get("id") or "") == sku:
                price = service_pricing_native._variant_paise({
                    "priceMinor": variant.get("priceMinor"),
                    "currency": row.get("currency", "INR"),
                    "status": variant.get("status", "active"),
                })
                return price == 4900
    return False


def _vault_schedule_public(row: Dict[str, Any]) -> Dict[str, Any]:
    """No private owner, raw phone, provider IDs or storage keys."""
    return {
        "scheduledId": str(row.get("id") or ""),
        "fileId": str(row.get("fileId") or ""),
        "action": str(row.get("vaultAction") or ""),
        "offerBodyText": str(row.get("offerBodyText") or ""),
        "paymentItemDescription": str(row.get("paymentItemDescription") or ""),
        "scheduledAt": str(row.get("scheduledAt") or ""),
        "status": str(row.get("status") or ""),
        "createdAt": str(row.get("createdAt") or ""),
        "sentAt": str(row.get("sentAt") or ""),
        "updatedAt": str(row.get("updatedAt") or ""),
        "errorMessage": str(row.get("errorMessage") or "")[:80],
    }


def _read_vault_schedules(item: Dict[str, Any]) -> list:
    ids = item.get("vaultScheduledActionIds") or []
    if not isinstance(ids, list):
        return []
    result = []
    table = _table(VAULT_SCHEDULE_TABLE)
    for schedule_id in ids[-VAULT_SCHEDULE_MAX_ITEMS:]:
        if not isinstance(schedule_id, str) or not schedule_id.startswith("vault-"):
            continue
        row = table.get_item(Key={"id": schedule_id}, ConsistentRead=True).get("Item") or {}
        if (row.get("kind") != VAULT_SCHEDULE_KIND
                or row.get("fileId") != item["fileId"]
                or row.get("ownerCustomerId") != item["ownerCustomerId"]):
            continue
        result.append(row)
    return sorted(result, key=lambda row: str(row.get("scheduledAt") or ""), reverse=True)


def _admin_list_vault_schedules(file_id: str, origin: str) -> Dict[str, Any]:
    item, refusal = _owned_file_for_admin(file_id)
    if refusal:
        return cors_response(409 if refusal != "UNKNOWN_FILE" else 404,
                             {"error": refusal}, origin)
    return _no_store(cors_response(200, {
        "schedules": [_vault_schedule_public(row) for row in _read_vault_schedules(item)],
    }, origin))


def _admin_create_vault_schedule(file_id: str, event: Dict[str, Any], origin: str) -> Dict[str, Any]:
    body = json.loads(event.get("body") or "{}")
    if not isinstance(body, dict):
        return cors_response(400, {"error": "INVALID_SCHEDULE"}, origin)
    action = body.get("action")
    if action not in VAULT_SCHEDULE_ACTIONS:
        return cors_response(400, {"error": "ACTION_NOT_SCHEDULABLE"}, origin)
    description = catalog_service_checkout.VAULT_ITEM_DESCRIPTION_DEFAULT
    if action == "payment":
        description = body.get("paymentItemDescription", description)
        if not catalog_service_checkout.valid_vault_item_description(description):
            return cors_response(400, {"error": "INVALID_VAULT_ITEM_DESCRIPTION"}, origin)
    if (action == "payment"
            and description != catalog_service_checkout.VAULT_ITEM_DESCRIPTION_DEFAULT):
        try:
            if not _vault_offer_catalog_price_valid():
                return cors_response(409, {"error": "VAULT_ITEM_NOT_49",
                    "message": "Only the ₹49 Vault item description is editable. Refresh pricing."}, origin)
        except Exception as error:
            logger.warning(json.dumps({"event": "vault_schedule_item_price_read_failed",
                                       "reason": type(error).__name__}))
            return cors_response(503, {"error": "VAULT_PRICE_UNAVAILABLE"}, origin)
    try:
        when = _schedule_time(body.get("scheduledAt"))
    except ValueError as error:
        return cors_response(400, {"error": "INVALID_TIME", "message": str(error)}, origin)
    text = ""
    if action == "offer":
        text = body.get("offerBodyText")
        if (not isinstance(text, str) or not text or len(text) > 60
                or whatsapp_templates.vault_offer_document_name(text) != text):
            return cors_response(400, {
                "error": "INVALID_OFFER_VARIABLE",
                "message": "Enter a single line of 1–60 characters for WhatsApp {{1}}.",
            }, origin)
    item, refusal = _owned_file_for_admin(file_id)
    if refusal:
        return cors_response(409 if refusal != "UNKNOWN_FILE" else 404,
                             {"error": refusal}, origin)
    state = _file_access_state(item, int(time.time()))
    if action in ("offer", "payment") and state not in ("UNPAID", "EXPIRED"):
        return cors_response(409, {"error": "NO_PAYMENT_REQUEST_NEEDED"}, origin)
    if action == "access" and state not in ("OPEN", "READY"):
        return cors_response(409, {"error": "PAID_ACCESS_REQUIRED"}, origin)
    if action == "offer":
        try:
            if not _vault_offer_catalog_price_valid():
                return cors_response(409, {"error": "OFFER_PRICE_CHANGED",
                    "message": "The approved ₹49 offer no longer matches the catalogue."}, origin)
        except Exception:
            return cors_response(503, {"error": "PRICE_CHECK_UNAVAILABLE"}, origin)

    previous = item.get("vaultScheduledActionIds")
    if previous is not None and not isinstance(previous, list):
        return cors_response(409, {"error": "SCHEDULE_INDEX_INVALID"}, origin)
    previous = previous or []
    # Same action cannot have two pending sends to one owner-bound file.
    existing = _read_vault_schedules(item)
    if any(row.get("status") in ("PENDING", "DISPATCHING")
           and row.get("vaultAction") == action for row in existing):
        return cors_response(409, {"error": "SCHEDULE_ALREADY_PENDING"}, origin)
    # Reused files can be scheduled repeatedly. Keep all pending rows plus the
    # most recent completed outcomes, retaining the underlying immutable audit
    # rows in ScheduledMessagesTable without indefinitely growing this file.
    pending_ids = {str(row["id"]) for row in existing
                   if row.get("status") in ("PENDING", "DISPATCHING")}
    if len(pending_ids) >= 10:
        return cors_response(409, {"error": "TOO_MANY_PENDING_SCHEDULES"}, origin)
    old_ids = [sid for sid in previous if isinstance(sid, str)]
    archive_ids = [sid for sid in old_ids if sid not in pending_ids]
    retained_ids = (archive_ids[-9:] + [sid for sid in old_ids if sid in pending_ids])
    retained_ids = list(dict.fromkeys(retained_ids))[-(VAULT_SCHEDULE_MAX_ITEMS - 1):]

    schedule_id = "vault-" + uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    actor = str((event.get("_auth") or {}).get("username") or "staff")[:64]
    row = {
        "id": schedule_id, "scheduledId": schedule_id,
        "kind": VAULT_SCHEDULE_KIND, "vaultAction": action,
        "fileId": file_id, "ownerCustomerId": str(item["ownerCustomerId"]),
        "scheduledAt": when, "status": "PENDING", "createdAt": now,
        "updatedAt": now, "createdBy": actor,
        # The schedule contains neither the phone nor the private file key.
        "templateName": {
            "offer": "wecare_vault_request_ready",
            "payment": "wecare_whatapp_native_pay_template",
            "access": "wecare_default_download",
        }[action],
        "offerBodyText": text,
        "paymentItemDescription": description if action == "payment" else "",
    }
    values = {
        ":owner": _ddb_encoded(item["ownerCustomerId"]),
        ":active": _ddb_encoded("active"),
        ":updated": _ddb_encoded(retained_ids + [schedule_id]),
    }
    if item.get("vaultScheduledActionIds") is not None:
        values[":old"] = _ddb_encoded(previous)
        old_condition = "vaultScheduledActionIds = :old"
    else:
        old_condition = "attribute_not_exists(vaultScheduledActionIds)"
    # One transaction: no orphan schedule can dispatch without its owning file
    # recording the ID. The snapshot condition prevents concurrent duplicates.
    try:
        boto3.client("dynamodb", region_name=REGION).transact_write_items(
            TransactItems=[
                {"Put": {
                    "TableName": VAULT_SCHEDULE_TABLE,
                    "Item": {k: _ddb_encoded(v) for k, v in row.items()},
                    "ConditionExpression": "attribute_not_exists(id)",
                }},
                {"Update": {
                    "TableName": FILES_TABLE,
                    "Key": {"fileId": _ddb_encoded(file_id)},
                    "UpdateExpression": "SET vaultScheduledActionIds = :updated",
                    "ConditionExpression": (
                        "attribute_exists(fileId) AND #status = :active "
                        "AND ownerCustomerId = :owner AND " + old_condition
                    ),
                    "ExpressionAttributeNames": {"#status": "status"},
                    "ExpressionAttributeValues": values,
                }},
            ],
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            return cors_response(409, {"error": "SCHEDULE_CHANGED",
                "message": "Schedule selection changed. Refresh before retrying."}, origin)
        raise
    return _no_store(cors_response(201, {
        "schedule": _vault_schedule_public(row),
        "message": "Scheduled for reviewable, one-time delivery; no message sent yet.",
    }, origin))


def _admin_cancel_vault_schedule(file_id: str, schedule_id: str, origin: str) -> Dict[str, Any]:
    item, refusal = _owned_file_for_admin(file_id)
    if refusal:
        return cors_response(409 if refusal != "UNKNOWN_FILE" else 404,
                             {"error": refusal}, origin)
    if schedule_id not in (item.get("vaultScheduledActionIds") or []):
        return cors_response(404, {"error": "UNKNOWN_SCHEDULE"}, origin)
    row = _table(VAULT_SCHEDULE_TABLE).get_item(
        Key={"id": schedule_id}, ConsistentRead=True).get("Item") or {}
    if (row.get("kind") != VAULT_SCHEDULE_KIND
            or row.get("fileId") != file_id
            or row.get("ownerCustomerId") != item["ownerCustomerId"]):
        return cors_response(404, {"error": "UNKNOWN_SCHEDULE"}, origin)
    try:
        _table(VAULT_SCHEDULE_TABLE).update_item(
            Key={"id": schedule_id},
            UpdateExpression="SET #status=:cancelled, updatedAt=:now",
            ConditionExpression="#status=:pending AND fileId=:file AND ownerCustomerId=:owner",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":cancelled": "CANCELLED", ":pending": "PENDING",
                ":now": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                ":file": file_id, ":owner": item["ownerCustomerId"],
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return cors_response(409, {"error": "ALREADY_PROCESSING",
                "message": "This scheduled send is already claimed or cancelled."}, origin)
        raise
    return _no_store(cors_response(200, {
        "scheduledId": schedule_id, "status": "CANCELLED",
    }, origin))


def _dispatch_vault_scheduled_action(event: Dict[str, Any]) -> Dict[str, Any]:
    """Only the cron worker can supply the one-use DB dispatch token.

    No auth bypass through API Gateway: this branch is internal-only and the
    token must equal the currently claimed ScheduledMessagesTable row. A
    conditional update consumes it BEFORE any message could be sent.
    """
    schedule_id = str(event.get("scheduleId") or "")
    token = str(event.get("dispatchToken") or "")
    if (not schedule_id.startswith("vault-") or len(schedule_id) != 38
            or len(token) < 20 or len(token) > 128):
        return {"result": "FAILED", "reason": "INVALID_DISPATCH"}
    table = _table(VAULT_SCHEDULE_TABLE)
    row = table.get_item(Key={"id": schedule_id}, ConsistentRead=True).get("Item") or {}
    now = datetime.now(timezone.utc)
    if (row.get("kind") != VAULT_SCHEDULE_KIND or row.get("status") != "DISPATCHING"
            or str(row.get("dispatchToken") or "") != token
            or row.get("vaultAction") not in VAULT_SCHEDULE_ACTIONS
            or not row.get("fileId") or not row.get("ownerCustomerId")):
        return {"result": "FAILED", "reason": "CLAIM_MISMATCH"}
    try:
        due = datetime.fromisoformat(str(row["scheduledAt"]).replace("Z", "+00:00"))
        if due.tzinfo is None or not due <= now <= due + timedelta(minutes=90):
            return {"result": "FAILED", "reason": "STALE_OR_FUTURE_SCHEDULE"}
    except (TypeError, ValueError):
        return {"result": "FAILED", "reason": "INVALID_DUE_TIME"}
    file_id = str(row["fileId"])
    file_row, refusal = _owned_file_for_admin(file_id)
    if refusal or str(file_row.get("ownerCustomerId") or "") != str(row["ownerCustomerId"]):
        return {"result": "FAILED", "reason": "OWNER_OR_FILE_CHANGED"}
    action = row["vaultAction"]
    state = _file_access_state(file_row, int(time.time()))
    if action in ("offer", "payment") and state not in ("UNPAID", "EXPIRED"):
        return {"result": "FAILED", "reason": "ALREADY_PAID_OR_UNAVAILABLE"}
    if action == "access" and state not in ("OPEN", "READY"):
        return {"result": "FAILED", "reason": "ACCESS_WINDOW_NOT_ACTIVE"}
    if action == "offer":
        try:
            if not _vault_offer_catalog_price_valid():
                return {"result": "FAILED", "reason": "OFFER_PRICE_CHANGED"}
        except Exception:
            return {"result": "DISPATCH_UNKNOWN", "reason": "PRICE_CHECK_UNAVAILABLE"}
    try:
        # One-time claim prevents replay even if the worker transport is retried.
        table.update_item(
            Key={"id": schedule_id},
            UpdateExpression="SET vaultExecutedAt=:now",
            ConditionExpression=(
                "#status=:dispatching AND dispatchToken=:token "
                "AND attribute_not_exists(vaultExecutedAt)"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":now": now.isoformat(timespec="microseconds"),
                ":dispatching": "DISPATCHING", ":token": token,
            },
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return {"result": "FAILED", "reason": "ALREADY_DISPATCHED"}
        return {"result": "DISPATCH_UNKNOWN", "reason": "CLAIM_UNAVAILABLE"}

    actor = "scheduled:" + str(row.get("createdBy") or "staff")[:54]
    internal_event = {"_auth": {"username": actor}}
    if action == "offer":
        internal_event["body"] = json.dumps({"offerBodyText": row.get("offerBodyText") or ""})
        answer = _admin_send_vault_offer(file_id, internal_event, "")
    elif action == "payment":
        # Store and dispatch the exact wording chosen when scheduled; never
        # pick up a later UI edit or change a previously issued invoice.
        internal_event["body"] = json.dumps({"paymentItemDescription":
            row.get("paymentItemDescription")
            or catalog_service_checkout.VAULT_ITEM_DESCRIPTION_DEFAULT})
        answer = _admin_request_payment(file_id, internal_event, "")
    else:
        answer = _admin_send_access(file_id, internal_event, "")

    code = answer.get("statusCode")
    try:
        payload = json.loads(answer.get("body") or "{}")
    except (TypeError, ValueError):
        payload = {}
    outcome = str(payload.get("outcome") or "")
    accepted = {"offer": "VAULT_OFFER_SENT", "payment": "PAYMENT_REQUEST_SENT",
                "access": "VAULT_LINK_SENT"}[action]
    if code == 200 and outcome == accepted:
        return {"result": "SENT", "reason": ""}
    if isinstance(code, int) and 400 <= code < 500 and code != 408:
        return {"result": "FAILED", "reason": outcome[:70] or "ACTION_REFUSED"}
    # A 202 or provider/server error may follow a real send. Never auto-retry.
    return {"result": "DISPATCH_UNKNOWN", "reason": "SEND_UNCONFIRMED"}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    if (event.get("internalAction") == "dispatchScheduledVaultAction"
            and not event.get("requestContext")):
        return _dispatch_vault_scheduled_action(event)

    # Internal async dispatch from the Razorpay webhook. Deliberately checked before
    # anything else and keyed on a field API Gateway cannot produce, so no HTTP caller
    # can reach it: an event arriving through the API always carries a requestContext,
    # and this branch requires its absence.
    if event.get("internalAction") == "openVaultAccessWindow" and not event.get("requestContext"):
        grant_id = str(event.get("grantId") or "")
        ok, detail = open_vault_access_window(grant_id) if grant_id else (False, "no grantId")
        logger.info(
            json.dumps({"event": "vault_window_open_result", "ok": ok, "detail": detail})
        )
        return {"ok": ok, "detail": detail}

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

    # Every internal action is handled above, so an unrecognised one is refused here rather than
    # falling through to the HTTP router. `require_auth` treats an event without an API Gateway
    # context as an internal call and lets it pass, so a misspelt action, or a caller deployed
    # ahead of this function, used to get the whole staff file list back as a 200. IAM still
    # decides who may invoke this function; this decides what an unknown request gets: nothing.
    if event.get("internalAction") and not event.get("requestContext"):
        action = "".join(ch for ch in str(event.get("internalAction"))[:40]
                         if ch.isascii() and (ch.isalnum() or ch == "_"))
        logger.warning(json.dumps({"event": "secure_files_unknown_internal_action",
                                   "action": action}))
        return {"ok": False, "detail": "unknown internal action"}

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
        if tail == ["mine"] and method == "GET":
            identity = _customer_identity(event)
            if not identity:
                return cors_response(401, {"error": "Verification required"}, origin)
            # Each Access Vault message carries one opaque file ID. Do not make
            # the browser find it inside a capped owner list: that loses files
            # older than the first 100 despite an otherwise valid exact link.
            query = event.get("queryStringParameters") or {}
            if isinstance(query, dict) and "file" in query:
                return _customer_exact_file(query.get("file"), identity, origin)
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

        if len(tail) == 2 and tail[1] == "download":
            identity = _customer_identity(event)
            if not identity:
                return cors_response(401, {"error": "Verification required"}, origin)
            if method == "GET":
                return _redeem(tail[0], event, identity, origin)
            return cors_response(405, {"error": "Method not allowed"}, origin)

        # This route is shared by customer and staff callers. A verified customer-pool token is
        # handled before the admin Authenticator; a staff token falls through to Operator auth.
        if len(tail) == 2 and tail[1] == "request-payment" and method == "POST":
            identity = _customer_identity(event)
            if identity:
                return _customer_request_payment(tail[0], event, identity, origin)

        # ---- admin surface ---------------------------------------------------
        denied = require_auth(event, "Operator")
        if denied is not None:
            return denied

        if not tail:
            if method == "GET":
                return _admin_list(event, origin)
            return cors_response(405, {"error": "Method not allowed"}, origin)

        if tail == ["publish-document"] and method == "POST":
            return _admin_publish_document(event, origin)
        if tail == ["payment-media-preview"] and method == "GET":
            return _admin_payment_media_preview(origin)
        # Vault-only staff upload; default-off until the private CDN gate is verified.
        if tail == ["upload-init"] and method == "POST":
            return _upload_init(event, origin)
        if len(tail) == 2 and tail[1] == "confirm" and method == "POST":
            return _upload_confirm(tail[0], origin)
        if len(tail) == 2 and tail[1] == "staff-download" and method == "GET":
            return _admin_staff_download(tail[0], origin)
        if len(tail) == 2 and tail[1] == "revoke" and method == "POST":
            return _admin_revoke(tail[0], event, origin)
        if len(tail) == 2 and tail[1] == "schedules":
            if method == "GET":
                return _admin_list_vault_schedules(tail[0], origin)
            if method == "POST":
                return _admin_create_vault_schedule(tail[0], event, origin)
        if len(tail) == 3 and tail[1] == "schedules" and method == "DELETE":
            return _admin_cancel_vault_schedule(tail[0], tail[2], origin)
        if len(tail) == 2 and tail[1] == "send-offer" and method == "POST":
            return _admin_send_vault_offer(tail[0], event, origin)
        if len(tail) == 2 and tail[1] == "message-log" and method == "GET":
            return _admin_message_log(tail[0], origin)
        if len(tail) == 2 and tail[1] == "request-payment" and method == "POST":
            return _admin_request_payment(tail[0], event, origin)
        if len(tail) == 2 and tail[1] == "send-access" and method == "POST":
            return _admin_send_access(tail[0], event, origin)

        return cors_response(404, {"error": f"Unknown route {path}"}, origin)

    except json.JSONDecodeError:
        return cors_response(400, {"error": "Body must be valid JSON"}, origin)
    except Exception as exc:  # noqa: BLE001
        # type only: an exception message can carry data we did not construct
        logger.error(json.dumps({"event": "secure_files_error", "error": type(exc).__name__}))
        return cors_response(500, {"error": "Internal error"}, origin)
