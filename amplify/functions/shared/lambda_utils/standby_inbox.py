"""Project WhatsApp standby copies into the staff inbox without taking reply ownership.

Meta's standby hook belongs to an AI/other primary responder. This writes a
read-only, deduplicated message breadcrumb; it never invokes WhatsApp sending,
changes a customer's identity, or assumes a phone hidden by Meta.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from lambda_utils.message_store import build_message_item

logger = logging.getLogger(__name__)

MESSAGES_TABLE = os.environ.get("UNIFIED_MESSAGES_TABLE", "stack-wecare-digital-MessagesTable")
CONTACTS_TABLE = os.environ.get("CONTACTS_TABLE", "stack-wecare-digital-ContactsTable")
CLAIMS_TABLE = os.environ.get("IDENTITY_CLAIMS_TABLE", "stack-wecare-digital-IdentityClaimsTable")

# Verified Meta sender-phone / business-portfolio mapping; do not infer a portfolio
# from a BSUID alone. Unknown partner identities receive a separate inbox thread.
PORTFOLIO_BY_PHONE = {
    "1016149501586345": "382642103987922",
    "1055232054343117": "125951953587391",
}
INBOX_PHONE_ID = {
    "1016149501586345": "phone-number-id-waba1-direct-1016149501586345",
    "1055232054343117": "phone-number-id-waba-t-direct-1055232054343117",
}


def profile_name_from_contacts(message: Dict[str, Any], contacts: Any) -> str:
    """Read a signed WhatsApp profile name without guessing the sender identity.

    A standby batch may include multiple messages/contacts. Use only an exact
    message.from_user_id -> contact.user_id or message.from -> contact.wa_id
    match. Never infer a match from array order or a single contact alone.
    """
    message = message or {}
    bsuid = str(message.get("from_user_id") or "").strip()
    wa_id = str(message.get("from") or "").strip()
    if not bsuid and not wa_id or not isinstance(contacts, list):
        return ""
    matched = [
        row for row in contacts if isinstance(row, dict)
        and ((bsuid and str(row.get("user_id") or "") == bsuid)
             or (wa_id and str(row.get("wa_id") or "") == wa_id))
    ]
    if len(matched) != 1:
        return ""
    profile = matched[0].get("profile") or {}
    if not isinstance(profile, dict):
        return ""
    name = " ".join(str(profile.get("name") or "").split())[:160]
    if not name or name.lower() == "unknown" or name.replace("+", "").isdigit():
        return ""
    return name


def _verified_contact(resource: Any, phone_id: str, bsuid: str) -> Optional[Dict[str, Any]]:
    portfolio_id = PORTFOLIO_BY_PHONE.get(phone_id)
    if not portfolio_id or not bsuid or len(bsuid) > 128:
        return None

    claim = resource.Table(CLAIMS_TABLE).get_item(
        Key={"claimKey": f"WHATSAPP_BSUID#{portfolio_id}#{bsuid}"},
        ConsistentRead=True,
    ).get("Item") or {}
    contact_id = str(claim.get("contactId") or "")
    if not contact_id:
        return None
    contact = resource.Table(CONTACTS_TABLE).get_item(
        Key={"id": contact_id}, ConsistentRead=True
    ).get("Item") or {}
    identity = (contact.get("whatsappIdentities") or {}).get(portfolio_id) or {}
    if (
        not contact
        or contact.get("deletedAt")
        or contact.get("isDeleted")
        or str(contact.get("mergeState") or "").lower() == "merged"
        or str(contact.get("contactId") or contact.get("id") or "") != contact_id
        or not isinstance(identity, dict)
        or str(identity.get("bsuid") or "") != bsuid
    ):
        return None
    return contact


def mirror(
    phone_number_id: str,
    *,
    bsuid: str = "",
    wa_id: str = "",
    message: Optional[Dict[str, Any]] = None,
    content: str = "",
    sender_name: str = "",
    resource: Any = None,
) -> bool:
    """Idempotently mirror one standby event into MessagesTable (read-only).

    Returns False on failure so an alarm/reconciliation job can detect gaps.
    Never writes ContactsTable, invokes an AI agent, or sends a reply.
    """
    phone_id = str(phone_number_id or "").strip()
    identifier = str(bsuid or "").strip() or str(wa_id or "").strip()
    message = message or {}
    wamid = str(message.get("id") or "").strip()[:128]
    if not (phone_id and identifier and wamid):
        logger.warning('{"event":"standby_inbox_mirror_skipped","reason":"missing_identity"}')
        return False

    thread_key = f"{phone_id}#{identifier}"
    digest = hashlib.sha256(thread_key.encode("utf-8")).hexdigest()
    mid = "standby_" + hashlib.sha256(f"{phone_id}#{wamid}".encode("utf-8")).hexdigest()[:40]
    try:
        now = int(time.time())
        timestamp = int(message.get("timestamp") or now)
        if timestamp <= 0 or timestamp > now + 300:
            raise ValueError("standby timestamp outside safe bounds")

        db = resource or boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        try:
            contact = _verified_contact(db, phone_id, str(bsuid or "").strip())
        except Exception as exc:
            # A failed identity lookup must never attach this message to a guessed person.
            logger.warning(json.dumps({
                "event": "standby_inbox_identity_lookup_failed",
                "errorType": type(exc).__name__,
            }))
            contact = None

        cid = str(contact.get("contactId") or contact.get("id") or "") if contact else ""
        # The signed standby webhook can carry a WhatsApp profile name even when
        # the business-scoped identity is not yet linked to a CRM contact. Show
        # that provider-supplied name; never turn it into a verified contact link.
        profile_name = str(sender_name or "").strip()[:160]
        saved_name = str(contact.get("name") or "").strip() if contact else ""
        display_name = (saved_name if saved_name.lower() not in ("", "unknown") else "")
        display_name = display_name or profile_name or f"WhatsApp contact #{digest[:6].upper()}"
        item = build_message_item(
            channel="whatsapp",
            direction="inbound",
            contact_id=cid or f"wa-standby:{digest[:24]}",
            content=str(content or "")[:4000],
            status="received",
            message_id=mid,
            timestamp=timestamp,
            message_type=str(message.get("type") or "unsupported"),
            whatsapp_message_id=wamid,
            aws_phone_number_id=INBOX_PHONE_ID.get(phone_id, phone_id),
            sender_name=display_name,
        )
        item["standbySourced"] = True
        item["routingOwner"] = "ai_agent"
        item["replyAllowed"] = False
        if bsuid:
            item["senderBsuid"] = str(bsuid)
        if contact and contact.get("phone"):
            item["senderPhone"] = str(contact["phone"])
        # A media ID identifies the provider object; it is not a downloadable file.
        # Never fake an S3 key or public media URL for standby-only context.
        typ = str(message.get("type") or "")
        media = message.get(typ) if typ in {"image", "video", "audio", "document", "sticker"} else None
        if isinstance(media, dict) and media.get("id"):
            item["mediaId"] = str(media["id"])

        table = db.Table(MESSAGES_TABLE)
        prior = table.query(
            IndexName="whatsappMessageId-index",
            KeyConditionExpression=Key("whatsappMessageId").eq(wamid),
            Limit=2,
        ).get("Items") or []
        if prior:
            return True
        try:
            table.put_item(Item=item, ConditionExpression=Attr("id").not_exists())
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return True
            raise
        logger.info(json.dumps({
            "event": "standby_inbox_mirrored",
            "phoneNumberId": phone_id,
            "verifiedContact": bool(contact),
            "messageType": typ or "unsupported",
        }))
        return True
    except Exception as exc:
        logger.warning(json.dumps({
            "event": "standby_inbox_mirror_failed",
            "errorType": type(exc).__name__,
        }))
        return False
