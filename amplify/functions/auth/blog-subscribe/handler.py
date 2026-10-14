"""Public blog-subscription front door.

The browser may request and verify one WhatsApp OTP and one email OTP, then submit the
subscription. Verification proof is server-held: a successful OTP exchange mints a short-lived
opaque proof row in the existing DownloadGrantsTable. The final subscribe action checks both proof
rows against the normalized phone/email before it can write ContactsTable.

This function never creates a Cognito user and never opens the staff-only /contacts endpoint.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time
import uuid
from hashlib import sha256
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambda_utils import contact_key, customer_session, otp_challenge, otp_throttle
from lambda_utils.identity import subscriber_id
from lambda_utils.comms import verification_email
from lambda_utils.identity import customer as identity
from lambda_utils.logging import get_logger
from lambda_utils.response import cors_response, extract_origin, options_response
from lambda_utils.validation import sanitize_html

logger = get_logger(__name__)

REGION = os.environ.get("AWS_REGION", "us-east-1")
OTP_TABLE = os.environ.get("OTP_TABLE", "stack-wecare-digital-DownloadGrantsTable")
CONTACTS_TABLE = os.environ.get("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")
OTP_PEPPER_SECRET_ID = os.environ.get("OTP_PEPPER_SECRET_ID", "wecare/otp/pepper")
SENDER_FUNCTION = os.environ.get("SENDER_FUNCTION", "wecare-whatsapp-business-api:live")
META_PHONE_NUMBER_ID = os.environ.get("META_PHONE_NUMBER_ID", "1016149501586345")
OTP_TEMPLATE_NAME = os.environ.get("OTP_TEMPLATE_NAME", "wecare_otp")
OTP_TEMPLATE_LANGUAGE = os.environ.get("OTP_TEMPLATE_LANGUAGE", "en")

PHONE_PURPOSE = "blog_subscribe_phone"
EMAIL_PURPOSE = "blog_subscribe_email"
PROOF_PURPOSE = "blog_subscribe_proof"
PROOF_PREFIX = "blog-proof#"
PROOF_TTL_SECONDS = 15 * 60
BLOG_TAG = "blog-subscriber"

_dynamodb = None
_lambda = None
_secrets = None
_pepper_cache: Dict[str, str] = {}


def _no_store(response: Dict[str, Any]) -> Dict[str, Any]:
    hardened = dict(response)
    hardened["headers"] = customer_session.harden_session_headers(response.get("headers") or {})
    return hardened


def _otp_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(OTP_TABLE)


def _contacts_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(CONTACTS_TABLE)


def _lambda_client():
    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=REGION)
    return _lambda


def _ses_client():
    return boto3.client("sesv2", region_name=REGION)


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


def _action(event: Dict[str, Any], body: Dict[str, Any]) -> str:
    explicit = str(body.get("action") or event.get("action") or "").strip().lower()
    allowed = {
        "phone_request", "phone_verify", "email_request", "email_verify", "subscribe",
    }
    return explicit if explicit in allowed else ""


def _send_phone_code(e164: str, code: str) -> None:
    body = {
        "to": "".join(ch for ch in e164 if ch.isdigit()),
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
    if int(result.get("statusCode") or 500) >= 300:
        raise RuntimeError("internal WhatsApp sender rejected the verification message")


def _proof_digest(kind: str, subject: str) -> str:
    message = ("blog-proof\x1f" + kind + "\x1f" + subject).encode("utf-8")
    return hmac.new(_pepper().encode("utf-8"), message, sha256).hexdigest()


def _issue_proof(kind: str, subject: str) -> str:
    proof_id = secrets.token_urlsafe(24)
    now = int(time.time())
    _otp_table().put_item(Item={
        "grantId": PROOF_PREFIX + proof_id,
        "purpose": PROOF_PURPOSE,
        "kind": kind,
        "subjectDigest": _proof_digest(kind, subject),
        "createdAt": now,
        "expiresAt": now + PROOF_TTL_SECONDS,
    })
    return proof_id


def _proof_valid(proof_id: Any, kind: str, subject: str) -> bool:
    proof = str(proof_id or "").strip()
    if not proof or len(proof) > 128:
        return False
    try:
        item = _otp_table().get_item(Key={"grantId": PROOF_PREFIX + proof}).get("Item") or {}
    except Exception:  # noqa: BLE001
        return False
    if item.get("purpose") != PROOF_PURPOSE or item.get("kind") != kind:
        return False
    if int(item.get("expiresAt") or 0) < int(time.time()):
        return False
    stored = str(item.get("subjectDigest") or "")
    wanted = _proof_digest(kind, subject)
    return bool(stored) and hmac.compare_digest(stored, wanted)


def _throttle(event: Dict[str, Any], subject: str, origin: str) -> Optional[Dict[str, Any]]:
    try:
        otp_throttle.check_and_consume(_otp_table(), phone_e164=subject, event=event)
        return None
    except otp_throttle.OtpThrottled as exc:
        return _no_store(otp_throttle.throttled_response(exc, event))
    except otp_throttle.ThrottleStoreUnavailable:
        return _no_store(cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin))


def _request_phone(event: Dict[str, Any], body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    try:
        phone = identity.normalize_phone_preserving_country(body.get("phone"))
    except identity.InvalidPhoneNumber:
        return _no_store(cors_response(400, {"error": "INVALID_PHONE"}, origin))
    limited = _throttle(event, phone, origin)
    if limited:
        return limited
    try:
        issued = otp_challenge.issue(
            _otp_table(), purpose=PHONE_PURPOSE, subject=phone, pepper=_pepper())
        _send_phone_code(phone, issued.code)
    except otp_challenge.ResendTooSoon as exc:
        return _no_store(cors_response(
            429, {"error": "RESEND_TOO_SOON", "retryAfterSeconds": exc.retry_after_seconds}, origin))
    except otp_challenge.ResendLimitReached:
        return _no_store(cors_response(429, {"error": "RESEND_LIMIT_REACHED"}, origin))
    except otp_challenge.OtpStorageUnavailable:
        return _no_store(cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin))
    except Exception:  # noqa: BLE001
        return _no_store(cors_response(502, {"error": "SEND_FAILED"}, origin))
    return _no_store(cors_response(200, {"status": "sent", **issued.as_public_dict()}, origin))


def _verify_phone(body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    try:
        phone = identity.normalize_phone_preserving_country(body.get("phone"))
    except identity.InvalidPhoneNumber:
        return _no_store(cors_response(400, {"error": "INVALID_PHONE"}, origin))
    code = str(body.get("code") or "").strip()
    if not code:
        return _no_store(cors_response(400, {"error": "CODE_REQUIRED"}, origin))
    try:
        result = otp_challenge.verify(
            _otp_table(), purpose=PHONE_PURPOSE, subject=phone, code=code, pepper=_pepper())
    except otp_challenge.OtpStorageUnavailable:
        return _no_store(cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin))
    if not result.ok:
        logger.info(json.dumps({"event": "blog_phone_verification_failed",
                                "outcome": result.outcome}))
        return _no_store(cors_response(400, {"status": result.public_outcome()}, origin))
    proof = _issue_proof("phone", phone)
    return _no_store(cors_response(
        200, {"status": "VERIFIED", "proof": proof, "expiresInSeconds": PROOF_TTL_SECONDS}, origin))


def _request_email(event: Dict[str, Any], body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    try:
        email = identity.normalize_email(body.get("email"))
    except identity.InvalidEmailAddress:
        return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))
    limited = _throttle(event, email, origin)
    if limited:
        return limited
    try:
        issued = otp_challenge.issue(
            _otp_table(), purpose=EMAIL_PURPOSE, subject=email, pepper=_pepper())
        verification_email.send(
            _ses_client(), to_address=email, code=issued.code,
            first_name=str(body.get("firstName") or "").strip(),
            ttl_minutes=max(1, issued.ttl_seconds // 60),
        )
    except otp_challenge.ResendTooSoon as exc:
        return _no_store(cors_response(
            429, {"error": "RESEND_TOO_SOON", "retryAfterSeconds": exc.retry_after_seconds}, origin))
    except otp_challenge.ResendLimitReached:
        return _no_store(cors_response(429, {"error": "RESEND_LIMIT_REACHED"}, origin))
    except otp_challenge.OtpStorageUnavailable:
        return _no_store(cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin))
    except verification_email.VerificationEmailFailed:
        return _no_store(cors_response(502, {"error": "SEND_FAILED"}, origin))
    return _no_store(cors_response(200, {"status": "sent", **issued.as_public_dict()}, origin))


def _verify_email(body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    try:
        email = identity.normalize_email(body.get("email"))
    except identity.InvalidEmailAddress:
        return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))
    code = str(body.get("code") or "").strip()
    if not code:
        return _no_store(cors_response(400, {"error": "CODE_REQUIRED"}, origin))
    try:
        result = otp_challenge.verify(
            _otp_table(), purpose=EMAIL_PURPOSE, subject=email, code=code, pepper=_pepper())
    except otp_challenge.OtpStorageUnavailable:
        return _no_store(cors_response(503, {"error": "TEMPORARILY_UNAVAILABLE"}, origin))
    if not result.ok:
        logger.info(json.dumps({"event": "blog_email_verification_failed",
                                "outcome": result.outcome}))
        return _no_store(cors_response(400, {"status": result.public_outcome()}, origin))
    proof = _issue_proof("email", email)
    return _no_store(cors_response(
        200, {"status": "VERIFIED", "proof": proof, "expiresInSeconds": PROOF_TTL_SECONDS}, origin))


def _active_match(index: str, field: str, value: str) -> Optional[Dict[str, Any]]:
    """Return one active match, but fail closed if the identity lookup is unavailable.

    A query outage is not "no contact". Treating it that way could create a duplicate while an
    existing row is merely unreadable. The handler-level error boundary returns 500 instead.
    """
    response = _contacts_table().query(
        IndexName=index,
        KeyConditionExpression=Key(field).eq(value),
        Limit=5,
    )
    for item in response.get("Items") or []:
        if item.get("deletedAt") is None:
            return item
    return None


def _merged_tags(existing: Any) -> list[str]:
    values = existing if isinstance(existing, list) else []
    out = [str(value).strip() for value in values if str(value).strip()]
    if BLOG_TAG not in {value.lower() for value in out}:
        out.append(BLOG_TAG)
    return out


def _upsert_contact(first: str, last: str, phone: str, email: str) -> str:
    table = _contacts_table()
    phone_match = _active_match("phone-index", "phone", phone)
    email_match = _active_match("email-index", "email", email)
    phone_id = contact_key.resolve(phone_match) if phone_match else ""
    email_id = contact_key.resolve(email_match) if email_match else ""
    if phone_id and email_id and phone_id != email_id:
        return "conflict"

    now = int(time.time())
    existing = phone_match or email_match
    name = f"{first} {last}".strip()
    if existing:
        contact_id = contact_key.resolve(existing)
        tags = _merged_tags(existing.get("tags"))
        table.update_item(
            Key={"id": contact_id},
            UpdateExpression=(
                "SET #name=:name, firstName=:first, lastName=:last, phone=:phone, email=:email, "
                "tags=:tags, optInWhatsApp=:yes, optInEmail=:yes, allowlistWhatsApp=:yes, "
                "allowlistEmail=:yes, optInSms=:no, allowlistSms=:no, "
                "phoneVerifiedAt=if_not_exists(phoneVerifiedAt,:now), "
                "emailVerifiedAt=if_not_exists(emailVerifiedAt,:now), "
                "blogSubscribedAt=if_not_exists(blogSubscribedAt,:now), updatedAt=:now"
            ),
            ExpressionAttributeNames={"#name": "name"},
            ExpressionAttributeValues={
                ":name": name, ":first": first, ":last": last, ":phone": phone, ":email": email,
                ":tags": tags, ":yes": True, ":no": False, ":now": now,
            },
        )
        return "updated"

    # Deterministic for an identical phone+email pair, so a replay converges instead of duplicating.
    contact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"wecare:blog:{phone}|{email}"))
    item = {
        **contact_key.contact_item_keys(contact_id),
        **subscriber_id.new_contact_fields(now=now),
        "name": name,
        "firstName": first,
        "lastName": last,
        "phone": phone,
        "email": email,
        "tags": [BLOG_TAG],
        "optInWhatsApp": True,
        "optInEmail": True,
        "optInSms": False,
        "allowlistWhatsApp": True,
        "allowlistEmail": True,
        "allowlistSms": False,
        "phoneVerifiedAt": now,
        "emailVerifiedAt": now,
        "blogSubscribedAt": now,
        "createdAt": now,
        "updatedAt": now,
        "deletedAt": None,
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(id)")
    except Exception as exc:  # noqa: BLE001
        response = getattr(exc, "response", None) or {}
        if response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        table.update_item(
            Key={"id": contact_id},
            UpdateExpression="SET updatedAt=:now, tags=:tags",
            ExpressionAttributeValues={":now": now, ":tags": [BLOG_TAG]},
        )
        return "updated"
    return "created"


def _subscribe(body: Dict[str, Any], origin: str) -> Dict[str, Any]:
    first = sanitize_html(body.get("firstName"), max_length=100).strip()
    last = sanitize_html(body.get("lastName"), max_length=100).strip()
    if not first or not last:
        return _no_store(cors_response(400, {"error": "NAME_REQUIRED"}, origin))
    try:
        phone = identity.normalize_phone_preserving_country(body.get("phone"))
        email = identity.normalize_email(body.get("email"))
    except identity.InvalidPhoneNumber:
        return _no_store(cors_response(400, {"error": "INVALID_PHONE"}, origin))
    except identity.InvalidEmailAddress:
        return _no_store(cors_response(400, {"error": "INVALID_EMAIL"}, origin))

    if not (
        _proof_valid(body.get("phoneProof"), "phone", phone)
        and _proof_valid(body.get("emailProof"), "email", email)
    ):
        return _no_store(cors_response(400, {"error": "VERIFICATION_REQUIRED"}, origin))

    outcome = _upsert_contact(first, last, phone, email)
    if outcome == "conflict":
        return _no_store(cors_response(409, {"error": "SUBSCRIPTION_CONFLICT"}, origin))
    logger.info(json.dumps({"event": "blog_subscribed", "outcome": outcome}))
    return _no_store(cors_response(200, {"status": "SUBSCRIBED"}, origin))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    origin = extract_origin(event)
    rc = event.get("requestContext", {}) or {}
    method = rc.get("http", {}).get("method", event.get("httpMethod", "")).upper()
    if method == "OPTIONS":
        return _no_store(options_response(origin))
    if method != "POST":
        return _no_store(cors_response(405, {"error": "METHOD_NOT_ALLOWED"}, origin))

    body = _body(event)
    action = _action(event, body)
    if not action:
        return _no_store(cors_response(400, {"error": "INVALID_ACTION"}, origin))

    try:
        if action == "phone_request":
            return _request_phone(event, body, origin)
        if action == "phone_verify":
            return _verify_phone(body, origin)
        if action == "email_request":
            return _request_email(event, body, origin)
        if action == "email_verify":
            return _verify_email(body, origin)
        return _subscribe(body, origin)
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({"event": "blog_subscribe_error",
                                 "action": action, "error": type(exc).__name__}))
        return _no_store(cors_response(500, {"error": "INTERNAL_ERROR"}, origin))
