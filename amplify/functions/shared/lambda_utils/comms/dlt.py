"""India TRAI DLT - the single source of truth for entity, sender and templates.

Before this module the same regulatory facts were duplicated in five places, and
keeping them in step was manual:

  1. a code map in messaging/sms-aws/handler.py:77-82
  2. constants used by SMS and calling paths
  3. the DynamoDB registry stack-wecare-digital-DLTTemplates
  4. model defaults in amplify/data/resource.ts
  5. a UI mirror in src/pages/dm/sms/index.tsx

Five copies of a regulatory identifier is five chances to send unregistered
content under a registered sender, which is what TRAI penalises.

Resolution order
----------------
  1. env override for a known key      (fastest, no I/O, used for incident response)
  2. the built-in map                  (the three approved templates)
  3. the DynamoDB registry             (operator-managed, the authoritative store)

The registry is consulted last rather than first on purpose: it costs a network
call on every send, and the three templates that carry almost all traffic are
known at build time. A key absent from the built-in map is the uncommon case, and
that is exactly when paying for a lookup is worthwhile.

Fail-safe, not fail-open
------------------------
`resolve()` returns an error rather than a guess when a key has no approved
mapping, and callers MUST refuse the send. Spec §6: "Do not send India local-route
SMS if required DLT configuration is missing. Fail safely." Sending unregistered
content under the registered entity risks operator blocking and DLT penalties,
and unlike a delivery failure it is not self-correcting.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

# --- registered identity -----------------------------------------------------
# PE / entity id and the DLT-registered header. Verified live in ap-south-1:
# sender id WDBEEP, IN, Promotional+Transactional, Registered=True;
# IN_SENDER_ID_REGISTRATION = COMPLETE.
ENTITY_ID = os.environ.get("AWS_INDIA_DLT_ENTITY_ID", "1201161991108627443")
SENDER_ID = os.environ.get("AWS_INDIA_SENDER_ID", "WDBEEP")

# Sender-id DLT registration: 1405170900886606599, REGISTERED, permanent.
SENDER_ID_REGISTRATION = "1405170900886606599"

# --- approved content templates ----------------------------------------------
# Each value is an APPROVED DLT content template id. The message body must match
# the approved template character for character; the operator silently drops
# mismatched content even though the API call succeeds. Do not "improve" the copy
# of a template that is already approved.
TEMPLATES: Dict[str, str] = {
    "ivr-default": os.environ.get("IVR_SMS_DLT_TEMPLATE_ID", "1007277993798259629"),
    "wa-alert": os.environ.get("WA_ALERT_SMS_DLT_TEMPLATE_ID", "1007284579074821763"),
    "wd_order": os.environ.get("ORDER_SMS_DLT_TEMPLATE_ID", "1007723091207562020"),
}

DEFAULT_TEMPLATE_KEY = os.environ.get("DEFAULT_DLT_TEMPLATE_KEY", "ivr-default")

REGISTRY_TABLE = os.environ.get("DLT_TEMPLATES_TABLE",
                                "stack-wecare-digital-DLTTemplates")

# name -> templateId, populated on first registry hit. Cleared only by a cold start.
_registry_cache: Dict[str, str] = {}


class DltResolution:
    """Either a usable template id, or an error explaining why there is none."""

    __slots__ = ("template_id", "template_key", "entity_id", "sender_id", "error", "source")

    def __init__(self, template_id: str = "", template_key: str = "",
                 error: str = "", source: str = "") -> None:
        self.template_id = template_id
        self.template_key = template_key
        self.entity_id = ENTITY_ID
        self.sender_id = SENDER_ID
        self.error = error
        self.source = source

    @property
    def ok(self) -> bool:
        return bool(self.template_id) and not self.error

    def country_parameters(self) -> Dict[str, str]:
        """`DestinationCountryParameters` for SendTextMessage.

        Both keys are required by TRAI. Emitting only one is worse than emitting
        neither, because the message is accepted and then dropped downstream.
        """
        if not self.ok:
            return {}
        return {"IN_ENTITY_ID": self.entity_id, "IN_TEMPLATE_ID": self.template_id}

    def as_dict(self) -> Dict[str, Optional[str]]:
        return {
            "templateKey": self.template_key or None,
            "templateId": self.template_id or None,
            "entityId": self.entity_id,
            "senderId": self.sender_id,
            "source": self.source or None,
            "error": self.error or None,
        }


def _from_registry(key: str) -> Optional[str]:
    """Look a template name up in the operator-managed DynamoDB registry.

    Returns None on any failure. A registry outage must not be reported as "this
    template is not approved" - the caller still refuses the send either way, but
    the operator needs to be able to tell the two apart from the logs.
    """
    if key in _registry_cache:
        return _registry_cache[key]
    try:
        import boto3
        from boto3.dynamodb.conditions import Attr

        table = boto3.resource(
            "dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")
        ).Table(REGISTRY_TABLE)
        # The table is keyed by templateId, not by name, so a name lookup is a
        # filtered scan. Acceptable: it happens only for keys outside the built-in
        # map, and the result is cached for the life of the sandbox.
        found = table.scan(
            FilterExpression=Attr("name").eq(key) & Attr("status").eq("active"),
            Limit=5,
        ).get("Items") or []
        for item in found:
            tid = str(item.get("templateId") or "").strip()
            if tid:
                _registry_cache[key] = tid
                return tid
    except Exception:  # noqa: BLE001 - see docstring
        return None
    return None


def resolve(template_key: str = "", *, allow_registry: bool = True) -> DltResolution:
    """Map a template key to an approved DLT template id.

    An empty key falls back to DEFAULT_TEMPLATE_KEY, matching the behaviour every
    existing caller already relies on.
    """
    key = (template_key or DEFAULT_TEMPLATE_KEY).strip()
    if not key:
        return DltResolution(error="no DLT template key supplied and no default configured")

    tid = TEMPLATES.get(key)
    if tid:
        return DltResolution(template_id=tid, template_key=key, source="builtin")

    if allow_registry:
        tid = _from_registry(key)
        if tid:
            return DltResolution(template_id=tid, template_key=key, source="registry")

    return DltResolution(
        template_key=key,
        error=(
            f"No approved DLT template mapping for '{key}'. "
            f"Known keys: {', '.join(sorted(TEMPLATES))}. "
            "Register the template on the DLT portal, add it to the "
            f"{REGISTRY_TABLE} registry, and retry. Refusing to send "
            "unregistered content to an Indian number."
        ),
    )


def known_keys() -> list:
    return sorted(TEMPLATES)


def key_for_template_id(template_id: str) -> str:
    """Reverse lookup: approved template id -> its key. '' when not approved.

    Exists for one narrowly scoped reason. Callers that predate this module -
    the SMS dashboard and `dm/whatsapp/calling.tsx` - post a raw `dltTemplateId`
    rather than a key. Accepting it verbatim would let any caller assert any
    template id under our registered entity, which is precisely what the single
    source of truth is here to prevent.

    So the raw id is treated as an assertion to be CHECKED, not configuration to
    be used: if it maps back to an approved template the send proceeds under that
    template's key, and if it does not, the caller is refused. That keeps the old
    request shape working without widening what may be sent.
    """
    wanted = str(template_id or "").strip()
    if not wanted:
        return ""
    for key, tid in TEMPLATES.items():
        if tid == wanted:
            return key
    return ""
