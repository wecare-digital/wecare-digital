"""F003 Drop Docs Flow endpoint.

Security boundary:
- identity comes only from a server-issued, expiring Flow session;
- target choices are re-read from stores owned by that identity;
- DocumentPicker media is re-read from Meta with the receiving phone id bound;
- bytes are written only under the gated secure/d/public/drop-docs/ prefix;
- staff-facing metadata is written to DocumentTable;
- the Flow completion record is claimed idempotently before the session is consumed.

The older DOC_FORM/REVIEW handlers remain read-only compatibility for unpublished previews.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3

from flows.orders import fetch_orders_for_flow, get_order
from flows.common import dynamodb
from lambda_utils import (
    contact_store,
    customer_auth,
    flow_completion,
    flow_sessions,
    media_paths,
    shared_tables,
)
from lambda_utils.ecommerce import service_request_store, single_order_flow
from lambda_utils.meta_client import MetaGraphClient

logger = logging.getLogger(__name__)

CAPABILITY = "drop_docs"
FLOW_CODE = "WD_F003_DROP_DOCS"
FLOW_TYPE = "drop_docs"
REJECTED = "This document form session is no longer valid. Open Drop Docs again."

DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "stack-wecare-digital-DocumentTable")
SERVICE_REQUESTS_TABLE = os.environ.get(
    "SERVICE_REQUESTS_TABLE", "stack-wecare-digital-ServiceRequestsTable"
)
PAYMENT_ATTEMPTS_TABLE = shared_tables.payment_attempts_table_name()
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "wecare-digital-get")
WABA2_ID = os.environ.get("WABA2_ID", "2513394156072604")
PHONE1_META_ID = os.environ.get("PHONE1_META_ID", "1016149501586345")
PHONE2_META_ID = os.environ.get("PHONE2_META_ID", "1055232054343117")

MAX_FILES = 10
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
_s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
_meta = MetaGraphClient()


def _session_table():
    return dynamodb.Table(shared_tables.flow_drafts_table_name())


def _verify(flow_token: str):
    return flow_sessions.verify_session(
        _session_table(),
        capability=CAPABILITY,
        token=flow_token,
        rejected_message=REJECTED,
    )


def _contact(phone: str) -> Dict[str, Any]:
    try:
        return contact_store.lookup(
            dynamodb.Table(shared_tables.contacts_table_name()), phone
        ) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Drop Docs contact lookup failed: %s", type(exc).__name__)
        return {}


def _masked_phone(phone: str) -> str:
    digits = contact_store.digits(phone)
    if not digits:
        return ""
    keep_prefix = min(2, len(digits))
    hidden = max(0, len(digits) - keep_prefix - 4)
    return "+" + digits[:keep_prefix] + " " + ("•" * hidden) + digits[-4:]


def _customer_identity(contact: Dict[str, Any], phone: str) -> Optional[customer_auth.CustomerIdentity]:
    """Return the pre-existing verified commerce identity, never mint one here."""
    owner = str(contact.get("checkoutCustomerId") or "").strip()
    if not customer_auth.is_cognito_subject(owner):
        return None
    canonical = contact_store.canonical_phone(phone)
    if not canonical:
        return None
    return customer_auth.CustomerIdentity(
        customer_id=owner,
        subject=owner,
        phone=canonical,
        phone_verified=True,
    )

def _paid_request(session: Any, identity: Optional[customer_auth.CustomerIdentity]) -> Dict[str, Any]:
    """The finalized DROP_DOCS payment bound to this Flow session.

    Legacy launches bind to a ServiceRequests row. New single-order launches deliberately create
    no WD-REQ row and instead prove the PaymentAttempt + existing Order service activity.
    """
    if session.launch_channel != flow_sessions.LAUNCH_PAYMENT or identity is None:
        raise ValueError("Open Drop Docs from your paid request.")

    if session.service_request_key:
        row = dynamodb.Table(SERVICE_REQUESTS_TABLE).get_item(
            Key={"requestId": session.service_request_key}, ConsistentRead=True
        ).get("Item") or {}
        attempt_id = str(row.get("paymentAttemptId") or "").strip()
        order_id = str(row.get("orderId") or "").strip()
        if (row.get("kind") != service_request_store.DROP_DOCS
                or str(row.get("customerId") or "") != identity.customer_id
                or not order_id or not attempt_id):
            raise ValueError("This Drop Docs payment is not available.")

        attempt = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE).get_item(
            Key={"paymentAttemptId": attempt_id}, ConsistentRead=True
        ).get("Item") or {}
        if (str(attempt.get("status") or "") != "PAYMENT_PAID"
                or str(attempt.get("finalizationStage") or "") != "ORDER_FINALIZED"
                or str(attempt.get("orderId") or "") != order_id
                or str(attempt.get("customerId") or "") != identity.customer_id):
            raise ValueError("This Drop Docs payment is not finalized.")
        return row

    try:
        binding = single_order_flow.verify_paid_session(
            session=session,
            attempts=dynamodb.Table(PAYMENT_ATTEMPTS_TABLE),
            orders=dynamodb.Table(shared_tables.orders_table_name()),
            capability=CAPABILITY,
            service_code="DROP_DOCS",
            phone=identity.phone,
        )
    except single_order_flow.PaidFlowBindingError as exc:
        raise ValueError("This Drop Docs payment is not finalized.") from exc
    if binding.customer_id != identity.customer_id:
        raise ValueError("This Drop Docs payment is not available.")

    return {
        "kind": service_request_store.DROP_DOCS,
        "customerId": binding.customer_id,
        "paymentAttemptId": binding.payment_attempt_id,
        "orderId": binding.order_id,
        "orderNumber": binding.order_number,
        "publicRequestId": "",
        "singleOrderService": True,
        "dropDocsCompletedAt": binding.attempt.get("dropDocsCompletedAt"),
    }


def _upload_claim_id(flow_token: str) -> str:
    """Opaque stable claim id; never persist the raw Flow token."""
    return hashlib.sha256(str(flow_token).encode("utf-8")).hexdigest()


def _claim_upload_entitlement(
    session: Any,
    identity: customer_auth.CustomerIdentity,
    flow_token: str,
) -> Dict[str, Any]:
    """Reserve one paid entitlement before any customer document bytes are written."""
    claim_id = _upload_claim_id(flow_token)
    now = int(time.time())

    if session.service_request_key:
        table = dynamodb.Table(SERVICE_REQUESTS_TABLE)
        key = {"requestId": session.service_request_key}
        condition = (
            "kind=:kind AND customerId=:owner "
            "AND attribute_not_exists(dropDocsCompletedAt) "
            "AND (attribute_not_exists(dropDocsUploadClaimId) "
            "OR dropDocsUploadClaimId=:claim)"
        )
        values = {
            ":claim": claim_id,
            ":now": now,
            ":uploading": "UPLOAD_IN_PROGRESS",
            ":kind": service_request_store.DROP_DOCS,
            ":owner": identity.customer_id,
        }
    else:
        table = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE)
        key = {"paymentAttemptId": session.payment_attempt_id}
        condition = (
            "#status=:paid AND singleOrderService=:true AND serviceCode=:kind "
            "AND selectedOrderId=:order AND customerId=:owner "
            "AND attribute_not_exists(dropDocsCompletedAt) "
            "AND (attribute_not_exists(dropDocsUploadClaimId) "
            "OR dropDocsUploadClaimId=:claim)"
        )
        values = {
            ":claim": claim_id,
            ":now": now,
            ":uploading": "UPLOAD_IN_PROGRESS",
            ":paid": "PAYMENT_PAID",
            ":true": True,
            ":kind": "DROP_DOCS",
            ":order": session.order_id,
            ":owner": identity.customer_id,
        }

    try:
        kwargs = {
            "Key": key,
            "UpdateExpression": (
                "SET dropDocsUploadClaimId=:claim, dropDocsUploadClaimedAt=:now, "
                "dropDocsStatus=:uploading, updatedAt=:now"
            ),
            "ConditionExpression": condition,
            "ExpressionAttributeValues": values,
            "ReturnValues": "ALL_NEW",
        }
        if not session.service_request_key:
            kwargs["ExpressionAttributeNames"] = {"#status": "status"}
        response = table.update_item(**kwargs)
        attrs = response.get("Attributes") or {}
        if not session.service_request_key:
            attrs.setdefault("publicRequestId", "")
            attrs.setdefault("orderId", session.order_id)
            attrs.setdefault("orderNumber", session.order_number)
        return attrs
    except Exception as exc:  # noqa: BLE001
        current = table.get_item(Key=key, ConsistentRead=True).get("Item") or {}
        if current.get("dropDocsCompletedAt"):
            raise ValueError("This paid Drop Docs request has already been used.") from exc
        if str(current.get("dropDocsUploadClaimId") or "") != claim_id:
            raise ValueError("This paid Drop Docs request is already being used.") from exc
        raise

def _order_targets(phone: str) -> List[Dict[str, str]]:
    """Customer-owned orders labelled by reference, date/time, and customer-safe purpose."""
    targets: List[Dict[str, str]] = []
    try:
        for order in fetch_orders_for_flow(phone, "")[:20]:
            order_id = str(order.get("id") or "").strip()
            title = str(order.get("title") or order_id).strip()
            if not order_id:
                continue
            detail = get_order(order_id) or {}
            purpose = str(detail.get("itemsSummary") or "").strip()
            if purpose:
                purpose = purpose[:28]
                label = f"Order · {title} · {purpose}"
            else:
                label = f"Order · {title}"
            targets.append({
                "id": "order:" + order_id,
                "title": label[:72],
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("Drop Docs order lookup failed: %s", type(exc).__name__)
    return targets


def _request_targets(identity: Optional[customer_auth.CustomerIdentity]) -> List[Dict[str, str]]:
    """Only requests from the proven customer's customerId GSI partition."""
    if identity is None:
        return []
    try:
        rows, _cursor = service_request_store.list_for_customer(
            dynamodb.Table(SERVICE_REQUESTS_TABLE), identity, limit=20
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Drop Docs request lookup failed: %s", type(exc).__name__)
        return []

    out: List[Dict[str, str]] = []
    for row in rows:
        public_id = str(row.get("requestId") or "").strip()
        if not public_id:
            continue
        kind = str(row.get("kind") or "request").replace("_", " ").title()
        out.append({
            "id": "request:" + public_id,
            "title": (f"Request · {public_id} · {kind}")[:72],
        })
    return out


def handle_init(data: Dict, flow_token: str, request_id: str) -> Dict:
    """INIT -> SELECT_TARGET with verified-customer orders/requests only."""
    try:
        session = _verify(flow_token)
    except flow_sessions.FlowSessionRejected as exc:
        return {
            "screen": "SELECT_TARGET",
            "data": {
                "error": str(exc),
                "phone_number": "",
                "targets": [{"id": "unavailable", "title": REJECTED}],
            },
        }
    except flow_sessions.FlowSessionUnavailable:
        return {
            "screen": "SELECT_TARGET",
            "data": {
                "error": "Please try again.",
                "phone_number": "",
                "targets": [{"id": "unavailable", "title": "Please try again"}],
            },
        }

    if session.consumed_at:
        return {
            "screen": "SELECT_TARGET",
            "data": {
                "error": REJECTED,
                "phone_number": "",
                "targets": [{"id": "unavailable", "title": REJECTED}],
            },
        }

    contact = _contact(session.phone)
    identity = _customer_identity(contact, session.phone)
    try:
        paid_request = _paid_request(session, identity)
    except ValueError as exc:
        return {
            "screen": "SELECT_TARGET",
            "data": {
                "error": str(exc),
                "phone_number": "",
                "targets": [{"id": "unavailable", "title": str(exc)[:72]}],
            },
        }
    if paid_request.get("dropDocsCompletedAt"):
        return {
            "screen": "SELECT_TARGET",
            "data": {
                "error": "This paid Drop Docs request has already been used.",
                "phone_number": "",
                "targets": [{"id": "unavailable", "title": "Drop Docs already completed"}],
            },
        }
    targets = _order_targets(session.phone) + _request_targets(identity)
    if not targets:
        targets = [{"id": "unavailable", "title": "No matching orders or requests found"}]

    return {
        "screen": "SELECT_TARGET",
        "data": {
            "phone_number": _masked_phone(session.phone),
            "targets": targets,
        },
    }

def _normalise_picker(value: Any) -> List[Dict[str, Any]]:
    """Accept Meta's picker string or an already-decoded list without trusting its metadata."""
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if isinstance(value, dict):
        value = value.get("documents") or value.get("files") or [value]
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _media_id(entry: Dict[str, Any]) -> str:
    for key in ("media_id", "mediaId", "id"):
        value = str(entry.get(key) or "").strip()
        if value:
            return value
    return ""


def _original_name(entry: Dict[str, Any], fallback_ext: str) -> str:
    for key in ("file_name", "filename", "name"):
        value = os.path.basename(str(entry.get(key) or "").strip())
        if value:
            return value[:180]
    return "document" + fallback_ext


def _graph_phone(waba: str) -> str:
    return PHONE2_META_ID if str(waba or "") == WABA2_ID else PHONE1_META_ID


def _validate_target(
    selected_target: str,
    phone: str,
    identity: Optional[customer_auth.CustomerIdentity],
) -> Dict[str, str]:
    """Verify the selected target belongs to the verified customer."""
    selected = str(selected_target or "").strip()
    if not selected or selected == "unavailable":
        raise ValueError("Choose an order or request.")

    if selected.startswith("order:"):
        selected_id = selected.split(":", 1)[1]
        try:
            for order in fetch_orders_for_flow(phone, "")[:20]:
                order_id = str(order.get("id") or "").strip()
                if order_id != selected_id:
                    continue
                short = str(order.get("title") or "").split("—", 1)[0].strip()
                display = "WD-ORD-" + short if short else order_id
                return {"kind": "order", "id": order_id, "display": display}
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Drop Docs selected order lookup failed: %s", type(exc).__name__)
        raise ValueError("The selected order is no longer available for this account.")

    if selected.startswith("request:"):
        selected_id = selected.split(":", 1)[1]
        if identity is None:
            raise ValueError("The selected request cannot be verified for this account.")
        try:
            rows, _cursor = service_request_store.list_for_customer(
                dynamodb.Table(SERVICE_REQUESTS_TABLE), identity, limit=20
            )
            for row in rows:
                public_id = str(row.get("requestId") or "").strip()
                if public_id != selected_id:
                    continue
                return {"kind": "request", "id": public_id, "display": public_id}
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Drop Docs selected request lookup failed: %s", type(exc).__name__)
        raise ValueError("The selected request is no longer available for this account.")

    raise ValueError("Select a valid order or request.")

def _fetch_media(entry: Dict[str, Any], graph_phone: str) -> Tuple[bytes, str, str, str]:
    """Retrieve one picker file from Meta, binding the lookup to the receiving phone."""
    media_id = _media_id(entry)
    if not media_id:
        raise ValueError("A selected document could not be read.")

    meta = _meta.get(
        media_id,
        params={"phone_number_id": graph_phone},
        phone_id=graph_phone,
    )
    if _meta.is_error(meta):
        raise RuntimeError("A selected document could not be retrieved.")

    mime = str(meta.get("mime_type") or entry.get("mime_type") or "").lower().strip()
    if mime not in ALLOWED_MIME:
        raise ValueError("Only PDF, JPG and PNG documents are accepted.")

    try:
        declared_size = int(meta.get("file_size") or entry.get("file_size") or 0)
    except (TypeError, ValueError):
        declared_size = 0
    if declared_size > MAX_FILE_BYTES:
        raise ValueError("Each document must be 10 MB or smaller.")

    url = str(meta.get("url") or "").strip()
    if not url.startswith("https://"):
        raise RuntimeError("A selected document could not be retrieved.")
    blob = _meta.download_file(url, phone_id=graph_phone)
    if not blob:
        raise RuntimeError("A selected document was empty.")
    if len(blob) > MAX_FILE_BYTES:
        raise ValueError("Each document must be 10 MB or smaller.")

    digest = hashlib.sha256(blob).hexdigest()
    provider_hash = str(meta.get("sha256") or "").strip().lower()
    if provider_hash and len(provider_hash) == 64 and provider_hash != digest:
        raise RuntimeError("A selected document failed its integrity check.")

    ext = ALLOWED_MIME[mime]
    name = _original_name(entry, ext)
    return blob, mime, digest, name


def _document_ids(flow_token: str, media_id: str, digest: str) -> Tuple[str, str]:
    seed = hashlib.sha256(
        (str(flow_token) + "|" + str(media_id) + "|" + digest).encode("utf-8")
    ).hexdigest()
    doc_id = "WD-DOC-" + seed[:20].upper()
    ref_num = int(seed[20:32], 16) % 1000000
    return doc_id, "wecare-digital-" + f"{ref_num:06d}"


def _store_one(
    *,
    entry: Dict[str, Any],
    session: Any,
    contact: Dict[str, Any],
    target: Dict[str, str],
    note: str,
    request_id: str,
    paid_request: Dict[str, Any],
) -> Dict[str, Any]:
    graph_phone = _graph_phone(session.waba)
    blob, mime, digest, original_name = _fetch_media(entry, graph_phone)
    media_id = _media_id(entry)
    ext = ALLOWED_MIME[mime]
    key = media_paths.DROP_DOCS_UPLOAD_PREFIX + "flow/wecare-digital-" + digest + ext

    # Direct private write: no public/incoming intermediate key is created.
    _s3.put_object(
        Bucket=MEDIA_BUCKET,
        Key=key,
        Body=blob,
        ContentType=mime,
        Metadata={"sha256": digest, "source": "whatsapp-flow"},
    )
    head = _s3.head_object(Bucket=MEDIA_BUCKET, Key=key)
    if int(head.get("ContentLength") or 0) != len(blob):
        raise RuntimeError("The document could not be confirmed in private storage.")

    doc_id, doc_ref = _document_ids("", media_id, digest)
    # Include the verified Flow session only in the DynamoDB idempotency key, never S3 paths.
    doc_id, doc_ref = _document_ids(session.created_at, media_id, digest)
    now = int(time.time())
    contact_id = str(contact.get("id") or contact.get("contactId") or "").strip()
    customer_name = str(
        contact.get("contactBookName") or contact.get("name") or contact.get("profileName") or ""
    ).strip()
    canonical_phone = contact_store.canonical_phone(session.phone)
    item: Dict[str, Any] = {
        "documentId": doc_id,
        "documentRef": doc_ref,
        "referenceIssuedAt": Decimal(str(now)),
        "referenceVersion": 1,
        "contactId": contact_id,
        "customerPhone": canonical_phone,
        "customerName": customer_name,
        "sourceType": "flow",
        "documentType": "other",
        "documentTypeLabel": "Customer document",
        "originalFileName": original_name,
        "fileName": doc_ref + ext,
        "mimeType": mime,
        "fileSize": len(blob),
        "storageKey": key,
        "s3Bucket": MEDIA_BUCKET,
        "verificationStatus": "uploaded",
        "remarks": note[:1000],
        "sha256": digest,
        "sourceMediaId": media_id,
        "dropDocsRequestId": str(paid_request.get("publicRequestId") or ""),
        "dropDocsOrderId": str(paid_request.get("orderId") or ""),
        "dropDocsPaymentAttemptId": str(paid_request.get("paymentAttemptId") or ""),
        "targetKind": target["kind"],
        "targetReference": target["display"],
        "createdAt": Decimal(str(now)),
        "updatedAt": Decimal(str(now)),
        "uploadedAt": Decimal(str(now)),
    }
    if target["kind"] == "order":
        item["orderId"] = target["id"]
    elif target["kind"] == "request":
        item["serviceRequestId"] = target["id"]
    elif target["kind"] == "manual":
        item["manualReference"] = target["display"]

    table = dynamodb.Table(DOCUMENTS_TABLE)
    try:
        table.put_item(
            Item={k: v for k, v in item.items() if v not in ("", None)},
            ConditionExpression="attribute_not_exists(documentId)",
        )
    except Exception as exc:  # noqa: BLE001
        code = str(getattr(exc, "response", {}).get("Error", {}).get("Code") or "")
        if code != "ConditionalCheckFailedException":
            raise
        existing = table.get_item(
            Key={"documentId": doc_id}, ConsistentRead=True
        ).get("Item") or {}
        if str(existing.get("sha256") or "") != digest:
            raise RuntimeError("Document idempotency collision.")
        item = existing

    return {
        "documentId": str(item.get("documentId") or doc_id),
        "documentRef": str(item.get("documentRef") or doc_ref),
        "key": str(item.get("storageKey") or key),
        "filename": str(item.get("fileName") or doc_ref + ext),
        "type": str(item.get("mimeType") or mime),
    }


def handle_upload(data: Dict, flow_token: str, request_id: str) -> Dict:
    """UPLOAD data_exchange -> terminal SUCCESS after every selected file is private and indexed."""
    try:
        session = _verify(flow_token)
    except flow_sessions.FlowSessionRejected:
        return {"screen": "UPLOAD", "data": {"error_message": REJECTED}}
    except flow_sessions.FlowSessionUnavailable:
        return {"screen": "UPLOAD", "data": {"error_message": "Please try again."}}

    # A retry of the exact data_exchange may occur after the endpoint answered but before the
    # device received the response. Idempotent document ids + completion claim make it safe.
    contact = _contact(session.phone)
    identity = _customer_identity(contact, session.phone)
    try:
        paid_request = _paid_request(session, identity)
    except ValueError as exc:
        return {"screen": "UPLOAD", "data": {"error_message": str(exc)[:200]}}
    if paid_request.get("dropDocsCompletedAt"):
        return {"screen": "UPLOAD", "data": {"error_message": "This paid Drop Docs request has already been used."}}
    selected_target = str(
        data.get("selected_target")
        or data.get("parent_order")
        or data.get("manual_order_number")
        or ""
    ).strip()
    note = str(data.get("note") or "").strip()
    picker = _normalise_picker(data.get("documents"))

    if not note:
        return {"screen": "UPLOAD", "data": {"error_message": "Add a note before sending documents."}}

    if not picker:
        return {"screen": "UPLOAD", "data": {"error_message": "Choose at least one document."}}
    if len(picker) > MAX_FILES:
        return {"screen": "UPLOAD", "data": {"error_message": "Choose up to 10 documents."}}
    try:
        if not session.service_request_key:
            # Direct paid launch already proved one existing order. The Flow input must name that
            # same public Order Number; never re-query a picker or trust another customer value.
            raw_order = selected_target.split(":", 1)[1] if selected_target.startswith("order:") else selected_target
            if raw_order.upper() != session.order_number.upper():
                raise ValueError("The selected order does not match this Drop Docs payment.")
            target = {
                "kind": "order",
                "id": session.order_id,
                "display": session.order_number,
            }
        else:
            target = _validate_target(selected_target, session.phone, identity)
    except ValueError as exc:
        return {"screen": "UPLOAD", "data": {"error_message": str(exc)[:200]}}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Drop Docs target validation failed: %s", type(exc).__name__)
        return {"screen": "UPLOAD", "data": {"error_message": "Please try again."}}

    # Claim the paid entitlement before fetching or writing any customer bytes. Retries from
    # this exact Flow token are idempotent; another token for the same purchase is refused.
    try:
        paid_request = _claim_upload_entitlement(session, identity, flow_token)
    except ValueError as exc:
        return {"screen": "UPLOAD", "data": {"error_message": str(exc)[:200]}}
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "f003_drop_docs_claim_failed",
            "errorType": type(exc).__name__,
            "requestId": request_id,
        }))
        return {"screen": "UPLOAD", "data": {"error_message": "Please try again."}}

    stored: List[Dict[str, Any]] = []
    try:
        for entry in picker:
            stored.append(
                _store_one(
                    entry=entry,
                    session=session,
                    contact=contact,
                    target=target,
                    note=note,
                    request_id=request_id,
                    paid_request=paid_request,
                )
            )
    except ValueError as exc:
        return {"screen": "UPLOAD", "data": {"error_message": str(exc)[:200]}}
    except Exception as exc:  # noqa: BLE001
        logger.error(json.dumps({
            "event": "f003_drop_docs_store_failed",
            "errorType": type(exc).__name__,
            "requestId": request_id,
        }))
        return {
            "screen": "UPLOAD",
            "data": {"error_message": "We could not store that document securely. Please try again."},
        }

    attachments = [
        {"key": x["key"], "filename": x["filename"], "type": x["type"]}
        for x in stored
    ]
    contact_id = str(contact.get("id") or contact.get("contactId") or "").strip()
    sender_name = str(
        contact.get("contactBookName") or contact.get("name") or contact.get("profileName") or ""
    ).strip()
    completion_data = {
        "selected_target": selected_target,
        "target_display": target["display"],
        "note": note,
        "documents": attachments,
        "paid_request": str(paid_request.get("publicRequestId") or ""),
        "paid_order": str(paid_request.get("orderNumber") or paid_request.get("orderId") or ""),
    }
    result = flow_completion.claim_completion(
        flow_token=flow_token,
        screen="UPLOAD",
        flow_code=FLOW_CODE,
        flow_type=FLOW_TYPE,
        phone=session.phone,
        contact_id=contact_id,
        sender_name=sender_name,
        form_data=completion_data,
        reference_prefix="WD-DOC",
        status="submitted",
        extra={"documentIds": [x["documentId"] for x in stored], "attachments": attachments},
        ttl_seconds=0,
        request_id=request_id,
        channel="whatsapp",
    )
    if result.status == "error":
        return {
            "screen": "UPLOAD",
            "data": {"error_message": "Your files are safe, but we could not finish the record. Please try again."},
        }

    submission_id = result.submission_id or result.reference or stored[0]["documentRef"]
    now = int(time.time())
    update_names = {"#status": "dropDocsStatus"}
    update_values = {
        ":completed": "COMPLETED",
        ":now": now,
        ":submission": submission_id,
        ":target_kind": target["kind"],
        ":target_id": target["id"],
        ":target_display": target["display"],
        ":note": note,
        ":document_ids": [x["documentId"] for x in stored],
    }
    if session.service_request_key:
        final_table = dynamodb.Table(SERVICE_REQUESTS_TABLE)
        final_key = {"requestId": session.service_request_key}
        final_condition = (
            "kind=:kind AND customerId=:owner AND attribute_not_exists(dropDocsCompletedAt) "
            "AND dropDocsUploadClaimId=:claim"
        )
        final_names = update_names
        final_values = {
            **update_values,
            ":kind": service_request_store.DROP_DOCS,
            ":owner": identity.customer_id,
            ":claim": _upload_claim_id(flow_token),
        }
    else:
        final_table = dynamodb.Table(PAYMENT_ATTEMPTS_TABLE)
        final_key = {"paymentAttemptId": session.payment_attempt_id}
        final_condition = (
            "#paymentStatus=:paid AND singleOrderService=:true AND serviceCode=:kind "
            "AND selectedOrderId=:order AND customerId=:owner "
            "AND attribute_not_exists(dropDocsCompletedAt) AND dropDocsUploadClaimId=:claim"
        )
        final_names = {**update_names, "#paymentStatus": "status"}
        final_values = {
            **update_values,
            ":paid": "PAYMENT_PAID",
            ":true": True,
            ":kind": "DROP_DOCS",
            ":order": session.order_id,
            ":owner": identity.customer_id,
            ":claim": _upload_claim_id(flow_token),
        }

    try:
        final_table.update_item(
            Key=final_key,
            UpdateExpression=(
                "SET #status=:completed, dropDocsCompletedAt=:now, flowSubmissionId=:submission, "
                "dropDocsTargetKind=:target_kind, dropDocsTargetId=:target_id, "
                "dropDocsTargetDisplay=:target_display, dropDocsNote=:note, "
                "dropDocsDocumentIds=:document_ids, fulfillmentCompletedAt=:now, updatedAt=:now "
                "REMOVE dropDocsUploadClaimId, dropDocsUploadClaimedAt"
            ),
            ConditionExpression=final_condition,
            ExpressionAttributeNames=final_names,
            ExpressionAttributeValues=final_values,
        )
    except Exception as exc:  # noqa: BLE001
        current = final_table.get_item(Key=final_key, ConsistentRead=True).get("Item") or {}
        if str(current.get("flowSubmissionId") or "") != submission_id:
            logger.error(json.dumps({
                "event": "f003_paid_request_bind_failed",
                "errorType": type(exc).__name__,
                "requestId": request_id,
            }))
            return {
                "screen": "UPLOAD",
                "data": {"error_message": "Your files are safe, but we could not finish the paid request. Please contact support."},
            }

    flow_sessions.mark_consumed(_session_table(), token=flow_token)
    reference = result.reference or stored[0]["documentRef"]
    return {
        "screen": "CONFIRMATION",
        "data": {
            "message": "Your documents are stored securely and linked for review.",
            "file_count": str(len(stored)),
            "reference_number": target["display"],
            "note": note or "",
            "submission_id": result.submission_id or reference,
            "attachments": attachments,
        },
    }


# Compatibility for old unpublished three-screen previews. No writes or sends.
def handle_doc_form(data: Dict, flow_token: str, request_id: str) -> Dict:
    return {
        "screen": "REVIEW",
        "data": {
            "doc_type": data.get("doc_type", ""),
            "order_id": data.get("order_id", "none"),
            "description": data.get("description", "") or "—",
        },
    }


def handle_review(data: Dict, flow_token: str, request_id: str) -> Dict:
    return {
        "screen": "CONFIRM",
        "data": {
            "doc_id": "",
            "message": "Use the current Drop Docs form to upload documents directly.",
        },
    }
