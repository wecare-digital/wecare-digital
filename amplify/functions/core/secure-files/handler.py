"""Secure file sharing for wecare.digital/get/secure.

Three tiers exist on the ``wecare-digital-get`` bucket. This function owns the
gated one:

    o/       open, auto-download, served straight off CloudFront. Not our concern.
    secure/  this file. A named customer, verified by WhatsApp OTP, pays per
             download and receives a single-use short-lived presigned URL.

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
# The OTP trigger refuses a user whose WABA scope does not match, so new users
# must be stamped with the same value the auth Lambda expects.
META_WABA_ID = os.environ.get("META_WABA_ID", "2094615664435155")

PRICE_PAISE = int(os.environ.get("SECURE_FILE_PRICE_PAISE", "4900"))  # Rs. 49
UPLOAD_URL_TTL = int(os.environ.get("UPLOAD_URL_TTL_SECONDS", "900"))
# Web redeem: the browser follows this immediately, so it can be very short.
DOWNLOAD_URL_TTL = int(os.environ.get("DOWNLOAD_URL_TTL_SECONDS", "60"))
# WhatsApp link delivery: a person reads a message and taps when they get to it, which
# is not within 60 seconds. Sending a URL that has already expired by the time it is
# read is worse than useless - the customer has paid and sees a failure. 24 hours is
# the ceiling anyway, since SigV4 presigned URLs signed with temporary Lambda
# credentials cannot outlive the role session.
WHATSAPP_LINK_TTL = int(os.environ.get("WHATSAPP_LINK_TTL_SECONDS", str(6 * 3600)))
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
    if not phone:
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
        # "pdf" / "image" arrive as a WhatsApp attachment; "link" goes out as a URL.
        "deliverable": item.get("deliverable", "unknown"),
    }
    if admin:
        out["ownerName"] = item.get("ownerName")
        out["ownerPhoneMasked"] = mask_phone(item.get("ownerPhone", ""))
        out["uploadedBy"] = item.get("uploadedBy")
    return _decimal_safe(out)


# ── admin: create the customer and the upload slot ────────────────────────────

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
      this does not match its configured WABA, so an unstamped user could never
      receive a code.
    """
    client = _cognito_client()
    e164 = "+" + phone
    attrs = [
        {"Name": "phone_number", "Value": e164},
        {"Name": "phone_number_verified", "Value": "true"},
        {"Name": "custom:partner_waba_id", "Value": META_WABA_ID},
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
    except client.exceptions.UsernameExistsException:
        username = e164
        client.admin_update_user_attributes(
            UserPoolId=CUSTOMER_POOL_ID, Username=username, UserAttributes=attrs
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

    username = _ensure_customer_user(phone, name)

    file_id = f"{uuid.uuid4().hex}-{uuid.uuid4().hex}"
    basename = f"wecare-digital-{file_id}{_safe_extension(filename)}"
    key = UPLOAD_PREFIX + basename
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    _table(FILES_TABLE).put_item(
        Item={
            "fileId": file_id,
            "s3Key": key,
            "ownerPhone": phone,
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


# ── customer: list, order, download ───────────────────────────────────────────

def _customer_list(identity: Dict[str, Any], origin: str) -> Dict[str, Any]:
    result = _table(FILES_TABLE).query(
        IndexName="owner-created-index",
        KeyConditionExpression="ownerPhone = :p",
        ExpressionAttributeValues={":p": identity["phone"]},
        ScanIndexForward=False,
        Limit=100,
    )
    items = [i for i in result.get("Items", []) if i.get("status") == "active"]
    return cors_response(
        200,
        {
            "files": [_public_file(i, admin=False) for i in items],
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

    if grant.get("channel") != "whatsapp":
        return True, "confirmed; web channel collects by redeem"
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
    if grant.get("consumed"):
        return False
    if grant.get("paid"):
        # Already paid but the redeem still failed, so the cause was something else.
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
    file_id: str,
    grant_id: str,
    identity: Dict[str, Any],
    item: Dict[str, Any],
    origin: str,
):
    """Spend a grant that reconciliation just marked paid.

    Still a conditional update, still single use - reconciliation changes only whether
    the grant is payable, never whether it has already been spent.
    """
    try:
        _table(GRANTS_TABLE).update_item(
            Key={"grantId": grant_id},
            UpdateExpression="SET consumed = :true, consumedAt = :now",
            ConditionExpression=(
                "attribute_exists(grantId) AND fileId = :fid AND ownerPhone = :p "
                "AND paid = :true AND consumed = :false"
            ),
            ExpressionAttributeValues={
                ":true": True,
                ":false": False,
                ":now": int(time.time()),
                ":fid": file_id,
                ":p": identity["phone"],
            },
        )
    except ClientError:
        return cors_response(
            403,
            {
                "error": "GRANT_NOT_REDEEMABLE",
                "message": "This download link is not valid. Please pay again to download.",
            },
            origin,
        )

    return cors_response(
        200,
        {
            "downloadUrl": _download_url(item),
            "expiresInSeconds": DOWNLOAD_URL_TTL,
        },
        origin,
    )


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
    """Spend a paid grant for a 60-second presigned URL.

    The conditional update is the whole mechanism: it flips ``consumed`` only if it
    is currently false, so two concurrent requests cannot both win and a forwarded
    link is dead on second use.
    """
    params = event.get("queryStringParameters") or {}
    grant_id = str(params.get("grant") or "").strip()
    if not grant_id:
        return cors_response(400, {"error": "grant is required"}, origin)

    item = _owned_active_file(file_id, identity)
    if not item:
        return _not_registered(origin)

    try:
        updated = _table(GRANTS_TABLE).update_item(
            Key={"grantId": grant_id},
            UpdateExpression="SET consumed = :true, consumedAt = :now",
            ConditionExpression=(
                "attribute_exists(grantId) AND fileId = :fid AND ownerPhone = :p "
                "AND paid = :true AND consumed = :false"
            ),
            ExpressionAttributeValues={
                ":true": True,
                ":false": False,
                ":now": int(time.time()),
                ":fid": file_id,
                ":p": identity["phone"],
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise

        # The grant is unpaid, already spent, expired, or not this caller's - the
        # condition cannot say which. Before refusing, check whether it is merely
        # unpaid *as far as we know*: the webhook may never have arrived.
        #
        # This is the difference between "the customer was charged and gets nothing"
        # and "the customer waits two seconds". It asks Razorpay directly, which is
        # the same authority the webhook relays, and never trusts the client.
        if _reconcile_grant(grant_id, file_id, identity):
            return _redeem_after_reconcile(file_id, grant_id, identity, item, origin)

        return cors_response(
            403,
            {
                "error": "GRANT_NOT_REDEEMABLE",
                "message": "This download link is not valid. Please pay again to download.",
            },
            origin,
        )

    # downloads under the readable name, never the opaque key
    url = _download_url(item)

    try:
        _table(FILES_TABLE).update_item(
            Key={"fileId": file_id},
            UpdateExpression="ADD downloadCount :one",
            ExpressionAttributeValues={":one": 1},
        )
    except ClientError:
        pass  # a missed counter must never fail a paid download

    logger.info(
        json.dumps(
            {
                "event": "secure_file_downloaded",
                "fileId": file_id,
                "ownerPhone": mask_phone(identity["phone"]),
                "paymentId": _decimal_safe(updated.get("Attributes", {})).get("paymentId", ""),
            }
        )
    )
    return cors_response(
        200, {"downloadUrl": url, "expiresInSeconds": DOWNLOAD_URL_TTL}, origin
    )


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
        promoted = dropdocs_storage.promote_to_secure(
            _s3_client(), bucket=BUCKET, source_key=source_key)
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
