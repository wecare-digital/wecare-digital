"""The internal contract between the WhatsApp ingress and the inbound worker.

What was here before
--------------------
`wecare-whatsapp-calling` verifies Meta's signature on `/whatsapp`, then forwards
non-call events to `wecare-inbound-whatsapp` by `lambda_client.invoke`. It wrapped
them in a *synthetic SNS envelope*:

    {"Records": [{"Sns": {"Message": "{\\"whatsAppWebhookEntry\\": \\"{...}\\"}"}}]}

That shape is a fossil. It dates from an architecture where Meta delivered through
AWS End User Messaging Social into an SNS topic, and it no longer describes
anything: there is no SNS topic subscription to this function in
`amplify/backend.ts`, in `amplify/backend-resources.ts`, or in the live
event-source mappings - the only SNS references left in IaC are CloudWatch alarm
topics. The AWS account has no linked WABA.

It cost three things:

  * The webhook entry was **double JSON-encoded** - a string inside a string
    inside a dict - so every consumer paid two `json.loads` and any logging of the
    envelope was unreadable.
  * It lied about the source. A reader seeing `Records[].Sns` reasonably concludes
    a topic exists and looks for a subscription that was never there. Two
    documents in `docs/meta-whatsapp/` still describe that ingress.
  * It made the boundary untyped. Nothing declared which fields the worker needs,
    so `dlq-replay` stores an `originalRecord` and invokes with it directly,
    never rebuilding this envelope - meaning replay of an inbound failure does
    not reproduce the shape the worker parses.

The contract
------------
`build()` emits a flat, self-describing event. `parse()` accepts it **and** the
legacy envelope, and returns a uniform list of work items either way.

Accepting both is not indecision. The producer and the consumer are separate
Lambdas deployed separately, and the invoke is asynchronous: at the moment the new
producer ships there can be in-flight events carrying the old shape, and
`dlq-replay` may hold stored payloads in it for as long as its DLQ retention. The
legacy arm is therefore load-bearing until both have drained, and `parse()` reports
which shape it saw so that can be measured rather than assumed.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

SOURCE_META_DIRECT = "meta-direct"
CONTRACT_VERSION = 1

#: The inbound worker's dead-letter queue, the one durable place a work item lands when it cannot
#: be processed (the worker) or handed over (the ingress). `wecare-dlq-replay` reads it and
#: invokes the worker with the stored `originalRecord`, which is this module's typed event.
INBOUND_DLQ_DEFAULT_URL = (
    "https://sqs.us-east-1.amazonaws.com/775261844268/stack-wecare-digital-inbound-dlq")


def inbound_dlq_url() -> str:
    """The inbound DLQ URL: `INBOUND_DLQ_URL`, else the manifest's `DLQ_URL`, else the queue.

    The default is deliberate. With neither variable set (the live state of the worker), the
    worker's `_send_to_dlq` returned without sending and every failed work item was dropped, and
    replay read `INBOUND_DLQ_URL` while its own configuration names the queue `DLQ_URL`.
    """
    return (os.environ.get("INBOUND_DLQ_URL") or os.environ.get("DLQ_URL")
            or INBOUND_DLQ_DEFAULT_URL)


def build(*, entry: Dict[str, Any], waba_id: str,
          meta_phone_number_ids: List[str], request_id: str) -> Dict[str, Any]:
    """The typed event the ingress sends to the inbound worker.

    `entry` is the Meta webhook entry as a dict - not a JSON string. It was
    double-encoded in the legacy shape for no reason other than SNS carrying a
    string body.
    """
    return {
        "source": SOURCE_META_DIRECT,
        "version": CONTRACT_VERSION,
        "wabaId": waba_id,
        "metaPhoneNumberIds": list(meta_phone_number_ids or []),
        "requestId": request_id,
        "entry": entry,
    }


def _try_dict(value: Any, *, depth: int = 2) -> Dict[str, Any] | None:
    """Decode to a dict, or `None` when it cannot be one. Never raises.

    `None` and `{}` are deliberately different answers. A record whose inner entry
    is unparsable is skipped entirely, while one whose entry is merely absent is
    kept with an empty entry - behaviour `test_an_unparsable_inner_entry_is_skipped`
    pins, and which collapsing both to `{}` would quietly break.
    """
    for _ in range(max(1, depth)):
        if isinstance(value, dict):
            return value
        if not isinstance(value, (str, bytes, bytearray)):
            return None
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    return value if isinstance(value, dict) else None


def _as_dict(value: Any, *, depth: int = 2) -> Dict[str, Any]:
    """Decode to a dict, or give back an empty one. Never raises.

    `json.loads` returning successfully does not mean it returned an object. A
    double-encoded SNS `Message` - a JSON string whose content is itself JSON -
    decodes one level to a `str`, and the previous code went straight to
    `message.get("context")` on it. That is the live crash this fixes:

        AttributeError: 'str' object has no attribute 'get'
        wa_internal_event.py:80 in _from_legacy_sns

    Nine of them in 7 days on `wecare-inbound-whatsapp`, and they mattered more than
    their count: `parse` documents that it "is never an exception, because this sits
    at the top of an async worker where raising would send a poison event to the DLQ
    on every retry". An AttributeError from a helper broke that promise, so the event
    was retried and re-crashed rather than being skipped.

    `depth` allows the second decode the module docstring already claimed to
    tolerate. Anything that is still not a dict is not guessed at.
    """
    return _try_dict(value, depth=depth) or {}


def _from_legacy_sns(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Unwrap the synthetic SNS envelope. Tolerates the double encoding."""
    items: List[Dict[str, Any]] = []
    for record in event.get("Records") or []:
        raw = ((record or {}).get("Sns") or {}).get("Message") or "{}"
        message = _try_dict(raw)
        if message is None:
            # Unparsable, or valid JSON that is not an object - the crash this
            # replaces. Skip the record rather than raise, per `parse`'s contract.
            continue
        ctx = _as_dict(message.get("context"))
        entry = _try_dict(message.get("whatsAppWebhookEntry") or "{}")
        if entry is None:
            continue
        waba_ids = ctx.get("MetaWabaIds") or []
        items.append({
            "shape": "legacy-sns",
            "entry": entry,
            "waba_ids": list(waba_ids),
            "waba_id": waba_ids[0] if waba_ids else "",
            "phone_number_ids": list(ctx.get("MetaPhoneNumberIds") or []),
            "message_id": message.get("messageId") or "",
        })
    return items


def _from_typed(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Defensive against a producer that stringified `entry` anyway. Uses the same
    # helper as the legacy arm so a JSON string encoding a non-object cannot travel
    # onward as a `str` and crash a downstream `.get()` instead of here.
    entry = _as_dict(event.get("entry"))
    waba_id = event.get("wabaId") or ""
    return [{
        "shape": "typed",
        "entry": entry,
        "waba_ids": [waba_id] if waba_id else [],
        "waba_id": waba_id,
        "phone_number_ids": list(event.get("metaPhoneNumberIds") or []),
        "message_id": event.get("requestId") or "",
    }]


def parse(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize either shape into a list of work items.

    Each item carries `entry` (a dict), `waba_ids`, `waba_id`,
    `phone_number_ids`, `message_id`, and `shape` so the caller can log which
    form arrived and know when the legacy arm has stopped being used.

    Returns an empty list for anything unrecognised; the caller decides whether
    that is worth an error. It is never an exception, because this sits at the top
    of an async worker where raising would send a poison event to the DLQ on every
    retry.
    """
    if not isinstance(event, dict):
        return []
    if event.get("source") == SOURCE_META_DIRECT or "entry" in event:
        return _from_typed(event)
    if event.get("Records"):
        return _from_legacy_sns(event)
    return []


def is_internal_event(event: Dict[str, Any]) -> bool:
    """True when this looks like either internal shape rather than an HTTP request."""
    return bool(parse(event))
