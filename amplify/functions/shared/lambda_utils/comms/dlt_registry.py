"""CRUD for the operator-managed TRAI DLT template registry.

`comms.dlt` READS this registry to resolve a template key that is not in the
built-in map. This module is how an operator WRITES it.

The two are deliberately separate modules. `dlt.resolve()` runs on the send path
and must stay a fast, read-only lookup with no administrative surface; a registry
write is a rare, audited, operator action. Keeping the mutation code out of the
send path means a bug in template administration cannot affect message sending.

Why this moved
--------------
The DLT registry is application-owned regulatory data: it is a record of content templates approved
by the Indian regulator under our own registered entity, and it outlives any
carrier. Deleting that Lambda without first moving this would have taken the live
registry with it.

What a DLT template is, and is not
----------------------------------
A TRAI DLT content template is registered on the DLT portal, under a registered
entity (PE) id, with a registered header (sender id). The approved BODY must match
what is actually sent character for character - the operator drops mismatched
content while still returning success at the API layer.

It is NOT an AWS template of any kind. The classic Pinpoint template CRUD that
used to sit in `sms-aws` managed a different, unrelated object and could not
satisfy DLT; it has been removed.

This module stores what was approved. It cannot itself approve anything, and it
does not talk to the DLT portal - registration is a manual step on the portal.
"""
from __future__ import annotations

import os
import re
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from . import dlt as dlt_mod

REGISTRY_TABLE = os.environ.get("DLT_TEMPLATES_TABLE",
                                "stack-wecare-digital-DLTTemplates")

# {#var#} is the DLT portal's variable syntax.
_VARIABLE_RE = re.compile(r"\{#(\w+)#\}")

_VALID_MESSAGE_TYPES = ("SERVICE_IMPLICIT", "SERVICE_EXPLICIT",
                        "TRANSACTIONAL", "PROMOTIONAL")


class RegistryError(Exception):
    """A caller-correctable problem with a registry request."""

    def __init__(self, message: str, code: str = "INVALID_REQUEST") -> None:
        super().__init__(message)
        self.code = code


def _table():
    import boto3
    return boto3.resource(
        "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")
    ).Table(REGISTRY_TABLE)


def extract_variables(content: str) -> List[str]:
    """The {#var#} placeholders in an approved body, de-duplicated, in order.

    Order is preserved rather than sorted: DLT variables are positional in the
    approved template, so presenting them alphabetically would mislead an
    operator filling them in.
    """
    seen: List[str] = []
    for name in _VARIABLE_RE.findall(content or ""):
        if name not in seen:
            seen.append(name)
    return seen


def normalize(item: Dict[str, Any]) -> Dict[str, Any]:
    """Registry row -> API shape. Never raises on a partial row."""
    content = item.get("content", "") or ""
    variables = item.get("variables") or extract_variables(content)
    created = item.get("createdAt") or 0
    updated = item.get("updatedAt") or created
    return {
        "templateId": item.get("templateId", ""),
        "name": item.get("name", ""),
        "content": content,
        "messageType": item.get("messageType", ""),
        "senderId": item.get("senderId", "") or dlt_mod.SENDER_ID,
        "entityId": item.get("entityId", "") or dlt_mod.ENTITY_ID,
        "variables": list(variables),
        "variableCount": len(variables),
        "status": item.get("status", "active"),
        # A row whose name matches a built-in key is what comms.dlt would find.
        "isBuiltinKey": item.get("name", "") in dlt_mod.TEMPLATES,
        "createdAt": int(float(created or 0)),
        "updatedAt": int(float(updated or 0)),
    }


def list_templates(limit: int = 100) -> Dict[str, Any]:
    """Every registered template, newest first.

    A scan is correct here: the table is keyed by templateId, the row count is in
    the tens, and an operator listing templates wants all of them.
    """
    limit = max(1, min(int(limit or 100), 500))
    result = _table().scan(Limit=limit)
    items = result.get("Items", []) or []
    items.sort(key=lambda row: float(row.get("createdAt", 0) or 0), reverse=True)
    return {
        "templates": [normalize(row) for row in items],
        "count": len(items),
        # So a UI can show which keys the send path knows without a lookup.
        "builtinKeys": dlt_mod.known_keys(),
        "entityId": dlt_mod.ENTITY_ID,
        "senderId": dlt_mod.SENDER_ID,
    }


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    if not template_id:
        raise RegistryError("templateId is required")
    item = _table().get_item(Key={"templateId": str(template_id)}).get("Item")
    return normalize(item) if item else None


def create_template(body: Dict[str, Any]) -> Dict[str, Any]:
    """Record a template that has ALREADY been approved on the DLT portal."""
    template_id = str(body.get("templateId") or body.get("dltTemplateId") or "").strip()
    content = str(body.get("content") or "")
    if not template_id:
        raise RegistryError("templateId is required")
    if not content:
        raise RegistryError("content is required")

    message_type = str(body.get("messageType") or "SERVICE_EXPLICIT").strip().upper()
    if message_type not in _VALID_MESSAGE_TYPES:
        raise RegistryError(
            f"messageType must be one of {', '.join(_VALID_MESSAGE_TYPES)}",
            code="INVALID_MESSAGE_TYPE")

    now = int(time.time())
    variables = body.get("variables") or extract_variables(content)
    item = {
        "templateId": template_id,
        "name": str(body.get("name") or "").strip() or f"Template {template_id[:8]}",
        "content": content,
        "messageType": message_type,
        # Default to the registered identity rather than accepting anything: a
        # template recorded under an unregistered sender is not usable, and
        # storing one would make the registry disagree with reality.
        "senderId": str(body.get("senderId") or "").strip() or dlt_mod.SENDER_ID,
        "entityId": str(body.get("entityId") or "").strip() or dlt_mod.ENTITY_ID,
        "variables": list(variables),
        "status": "active",
        "createdAt": Decimal(str(now)),
        "updatedAt": Decimal(str(now)),
    }
    _table().put_item(Item=item)
    return normalize(item)


def update_template(body: Dict[str, Any]) -> Dict[str, Any]:
    """Patch a registered template. Only supplied fields change."""
    template_id = str(body.get("templateId") or body.get("dltTemplateId") or "").strip()
    if not template_id:
        raise RegistryError("templateId is required")

    now = int(time.time())
    sets = ["updatedAt = :now"]
    values: Dict[str, Any] = {":now": Decimal(str(now))}
    names: Dict[str, str] = {}

    if "name" in body:
        sets.append("#n = :name")
        names["#n"] = "name"
        values[":name"] = str(body["name"])
    if "content" in body:
        content = str(body["content"] or "")
        if not content:
            raise RegistryError("content cannot be emptied")
        sets.append("content = :content")
        values[":content"] = content
        # Variables are derived from the body, never supplied independently -
        # otherwise the stored list can drift from the approved text.
        sets.append("variables = :vars")
        values[":vars"] = extract_variables(content)
    if "messageType" in body:
        message_type = str(body["messageType"]).strip().upper()
        if message_type not in _VALID_MESSAGE_TYPES:
            raise RegistryError(
                f"messageType must be one of {', '.join(_VALID_MESSAGE_TYPES)}",
                code="INVALID_MESSAGE_TYPE")
        sets.append("messageType = :mt")
        values[":mt"] = message_type
    if "senderId" in body:
        sets.append("senderId = :sid")
        values[":sid"] = str(body["senderId"])
    if "entityId" in body:
        sets.append("entityId = :eid")
        values[":eid"] = str(body["entityId"])
    if "status" in body:
        status = str(body["status"]).strip().lower()
        if status not in ("active", "inactive"):
            raise RegistryError("status must be active or inactive",
                                code="INVALID_STATUS")
        sets.append("#s = :status")
        names["#s"] = "status"
        values[":status"] = status

    kwargs: Dict[str, Any] = {
        "Key": {"templateId": template_id},
        "UpdateExpression": "SET " + ", ".join(sets),
        "ExpressionAttributeValues": values,
        "ReturnValues": "ALL_NEW",
        # Refuse to create a row via update: a typo'd id would otherwise add a
        # template nobody registered.
        "ConditionExpression": "attribute_exists(templateId)",
    }
    if names:
        kwargs["ExpressionAttributeNames"] = names

    from botocore.exceptions import ClientError
    try:
        result = _table().update_item(**kwargs)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise RegistryError(f"no registered template with id {template_id}",
                                code="NOT_FOUND") from exc
        raise
    return normalize(result.get("Attributes", {}) or {})


def delete_template(template_id: str) -> Dict[str, Any]:
    """Remove a registry row.

    Refuses to delete a template the send path has a built-in mapping for.
    Deleting one of those would not stop it being used - `dlt.resolve()` checks
    the built-in map first - so the only effect would be to make the registry
    disagree with what is actually being sent.
    """
    template_id = str(template_id or "").strip()
    if not template_id:
        raise RegistryError("templateId is required")

    if template_id in dlt_mod.TEMPLATES.values():
        raise RegistryError(
            f"template {template_id} is a built-in approved template used by the "
            "send path. Removing the registry row would not stop it being used "
            "and would leave the registry inconsistent with live traffic. "
            "Set status=inactive instead.",
            code="BUILTIN_TEMPLATE_PROTECTED")

    _table().delete_item(Key={"templateId": template_id})
    return {"deleted": template_id}
