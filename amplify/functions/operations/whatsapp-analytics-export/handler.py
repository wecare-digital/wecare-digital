"""Privacy-bounded WhatsApp operational analytics exporter.

Runs on a schedule. Reads only operational metadata from the canonical DynamoDB
sources and writes newline-delimited JSON snapshots to the existing private S3
analytics prefix. It never exports customer phone numbers, customer/contact IDs,
message bodies, Flow answers, line items, names, addresses, or free-form notes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, Mapping

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET = os.environ.get("ANALYTICS_BUCKET", "wecare-digital-get")
PREFIX = os.environ.get(
    "ANALYTICS_PREFIX", "secure/d/public/whatsapp/analytics/operational"
).strip("/")
MAX_ROWS_PER_DATASET = int(os.environ.get("MAX_ROWS_PER_DATASET", "100000"))

OUTBOUND_TABLE = os.environ.get(
    "OUTBOUND_TABLE", "stack-wecare-digital-WhatsAppOutboundTable"
)
FLOW_SUBMISSIONS_TABLE = os.environ.get(
    "FLOW_SUBMISSIONS_TABLE", "stack-wecare-digital-FlowSubmissionTable"
)
ORDERS_TABLE = os.environ.get("ORDERS_TABLE", "stack-wecare-digital-OrderTable")
SYSTEM_EVENT_TABLE = os.environ.get(
    "SYSTEM_EVENT_TABLE", "stack-wecare-digital-SystemEventTable"
)

_dynamodb = boto3.resource("dynamodb", region_name=REGION)
_ddb = _dynamodb.meta.client
_s3 = boto3.client("s3", region_name=REGION)

DATASETS: Dict[str, Dict[str, Any]] = {
    "delivery_lifecycle": {
        "table": OUTBOUND_TABLE,
        "attributes": [
            "id", "timestamp", "createdAt", "updatedAt", "status", "templateName",
            "templateCategory", "whatsappMessageId", "paymentReferenceId", "wabaId",
            "phoneNumberId", "type", "messageType", "direction", "isTemplate",
        ],
    },
    "flow_submissions": {
        "table": FLOW_SUBMISSIONS_TABLE,
        "attributes": [
            "submissionId", "submissionNumber", "flowCode", "flowId", "status",
            "paymentStatus", "createdAt", "updatedAt", "orderId", "paymentRefId", "channel",
        ],
    },
    "orders": {
        "table": ORDERS_TABLE,
        "attributes": [
            "orderId", "shortId", "orderNumber", "source", "channel", "orderStatus",
            "status", "paymentStatus", "amountPaise", "currency", "createdAt", "updatedAt",
            "referenceId", "finalizationStage",
        ],
    },
    "template_lifecycle": {
        "table": SYSTEM_EVENT_TABLE,
        "attributes": [
            "id", "eventType", "wabaId", "phoneNumberId", "severity", "acknowledged",
            "createdAt", "eventData",
        ],
    },
}

_TEMPLATE_EVENT_DATA_KEYS = {
    "template", "templateName", "status", "quality", "category", "language",
    "reasonCode", "errorCode",
}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _scan_projected(table_name: str, attributes: Iterable[str]) -> Iterable[dict]:
    names = {f"#a{i}": attr for i, attr in enumerate(attributes)}
    projection = ", ".join(names)
    paginator = _ddb.get_paginator("scan")
    count = 0
    for page in paginator.paginate(
        TableName=table_name,
        ProjectionExpression=projection,
        ExpressionAttributeNames=names,
    ):
        for item in page.get("Items", []):
            count += 1
            if count > MAX_ROWS_PER_DATASET:
                raise RuntimeError(
                    f"{table_name} exceeds MAX_ROWS_PER_DATASET={MAX_ROWS_PER_DATASET}; "
                    "switch this source to native export/Glue before increasing the guard"
                )
            yield _json_value(item)


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def _delivery(row: Mapping[str, Any]) -> dict:
    return {
        "record_id": _as_text(row.get("id")),
        "event_time": _as_text(row.get("timestamp") or row.get("createdAt") or row.get("updatedAt")),
        "status": _as_text(row.get("status")),
        "template_name": _as_text(row.get("templateName")),
        "template_category": _as_text(row.get("templateCategory")),
        "whatsapp_message_id": _as_text(row.get("whatsappMessageId")),
        "payment_reference_id": _as_text(row.get("paymentReferenceId")),
        "waba_id": _as_text(row.get("wabaId")),
        "phone_number_id": _as_text(row.get("phoneNumberId")),
        "message_type": _as_text(row.get("messageType") or row.get("type")),
        "direction": _as_text(row.get("direction")),
        "is_template": bool(row.get("isTemplate", False)),
    }


def _flow(row: Mapping[str, Any]) -> dict:
    return {
        "submission_id": _as_text(row.get("submissionId")),
        "submission_number": _as_text(row.get("submissionNumber")),
        "flow_code": _as_text(row.get("flowCode")),
        "flow_id": _as_text(row.get("flowId")),
        "status": _as_text(row.get("status")),
        "payment_status": _as_text(row.get("paymentStatus")),
        "created_at": _as_text(row.get("createdAt")),
        "updated_at": _as_text(row.get("updatedAt")),
        "order_id": _as_text(row.get("orderId")),
        "payment_reference_id": _as_text(row.get("paymentRefId")),
        "channel": _as_text(row.get("channel")),
    }


def _order(row: Mapping[str, Any]) -> dict:
    amount = row.get("amountPaise")
    return {
        "order_id": _as_text(row.get("orderId")),
        "short_id": _as_text(row.get("shortId")),
        "order_number": _as_text(row.get("orderNumber")),
        "source": _as_text(row.get("source")),
        "channel": _as_text(row.get("channel")),
        "order_status": _as_text(row.get("orderStatus")),
        "status": _as_text(row.get("status")),
        "payment_status": _as_text(row.get("paymentStatus")),
        "amount_paise": int(amount) if isinstance(amount, (int, Decimal)) else None,
        "currency": _as_text(row.get("currency")),
        "created_at": _as_text(row.get("createdAt")),
        "updated_at": _as_text(row.get("updatedAt")),
        "reference_id": _as_text(row.get("referenceId")),
        "finalization_stage": _as_text(row.get("finalizationStage")),
    }


def _template_lifecycle(row: Mapping[str, Any]) -> dict | None:
    event_type = _as_text(row.get("eventType"))
    if "template" not in event_type.lower():
        return None
    event_data: dict = {}
    raw = row.get("eventData")
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                event_data = parsed
        except json.JSONDecodeError:
            event_data = {}
    safe = {k: event_data.get(k) for k in _TEMPLATE_EVENT_DATA_KEYS if k in event_data}
    template_name = safe.get("templateName") or safe.get("template")
    return {
        "event_id": _as_text(row.get("id")),
        "event_type": event_type,
        "waba_id": _as_text(row.get("wabaId")),
        "phone_number_id": _as_text(row.get("phoneNumberId")),
        "severity": _as_text(row.get("severity")),
        "acknowledged": bool(row.get("acknowledged", False)),
        "created_at": int(row.get("createdAt"))
        if isinstance(row.get("createdAt"), (int, Decimal)) else None,
        "template_name": _as_text(template_name),
        "status": _as_text(safe.get("status")),
        "quality": _as_text(safe.get("quality")),
        "category": _as_text(safe.get("category")),
        "language": _as_text(safe.get("language")),
        "reason_code": _as_text(safe.get("reasonCode")),
        "error_code": _as_text(safe.get("errorCode")),
    }


_TRANSFORMS: Dict[str, Callable[[Mapping[str, Any]], dict | None]] = {
    "delivery_lifecycle": _delivery,
    "flow_submissions": _flow,
    "orders": _order,
    "template_lifecycle": _template_lifecycle,
}


def _export_dataset(name: str, now: datetime, run_id: str) -> dict:
    cfg = DATASETS[name]
    transform = _TRANSFORMS[name]
    rows = []
    for source in _scan_projected(cfg["table"], cfg["attributes"]):
        item = transform(source)
        if item is not None:
            rows.append(item)

    body = "".join(
        json.dumps(row, separators=(",", ":"), sort_keys=True, default=_json_value) + "\n"
        for row in rows
    ).encode("utf-8")
    date = now.strftime("%Y-%m-%d")
    hour = now.strftime("%H")
    key = (
        f"{PREFIX}/{name}/snapshot_date={date}/snapshot_hour={hour}/"
        f"part-{run_id}.json"
    )
    _s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=body,
        ContentType="application/x-ndjson",
        ServerSideEncryption="AES256",
    )
    return {"dataset": name, "rows": len(rows), "key": key}


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    request_id = getattr(context, "aws_request_id", "manual")
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{request_id[:24]}"
    results = [_export_dataset(name, now, run_id) for name in DATASETS]
    return {
        "ok": True,
        "runId": run_id,
        "bucket": BUCKET,
        "prefix": PREFIX,
        "datasets": results,
        "privacyBounded": True,
    }
