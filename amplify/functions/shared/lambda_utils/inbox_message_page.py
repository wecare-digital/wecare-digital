"""Bounded, cursor-based reads from the existing canonical Inbox indexes."""
from __future__ import annotations

from base64 import b64decode, urlsafe_b64encode
import json
import re

from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import BotoCoreError, ClientError

CHANNELS = ("whatsapp", "sms", "rcs", "email", "voice")
MAX_PAGE = 100
_CURSOR_LIMIT = 8192
_SERIALIZER = TypeSerializer()
_DESERIALIZER = TypeDeserializer()


def _encode(scope, positions):
    if not positions:
        return None
    values = {
        stream: ({name: _SERIALIZER.serialize(value) for name, value in key.items()} if key else None)
        for stream, key in positions.items()
    }
    doc = json.dumps([1, scope, values], separators=(",", ":")).encode()
    return urlsafe_b64encode(doc).decode().rstrip("=")


def _decode(cursor, scope, partition, streams):
    if cursor is None:
        return dict.fromkeys(streams)
    try:
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= _CURSOR_LIMIT:
            raise ValueError
        raw = b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        version, claimed_scope, values = json.loads(raw)
        if version != 1 or scope != claimed_scope or not isinstance(values, dict):
            raise ValueError
        if not values or not set(values).issubset(streams):
            raise ValueError
        positions = {}
        for stream, key in values.items():
            if key is None:
                positions[stream] = None
                continue
            if not isinstance(key, dict) or not 1 <= len(key) <= 4:
                raise ValueError
            for name, value in key.items():
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
                    raise ValueError
                if not isinstance(value, dict) or len(value) != 1:
                    raise ValueError
                tag, data = next(iter(value.items()))
                if tag not in ("N", "S") or not isinstance(data, str) or not 1 <= len(data) <= 1024:
                    raise ValueError
                if tag == "N" and not re.fullmatch(r"-?[0-9]{1,38}(?:\.[0-9]{1,38})?(?:[eE][+-]?[0-9]{1,3})?", data):
                    raise ValueError
            if key.get(partition) != {"S": stream}:
                raise ValueError
            positions[stream] = {name: _DESERIALIZER.deserialize(value) for name, value in key.items()}
        return positions
    except (ValueError, TypeError, OverflowError, ArithmeticError) as exc:
        raise ValueError("Invalid or mismatched inbox cursor.") from exc


def read_page(table, *, contact_id, channel, direction, limit, cursor, logger):
    """Read one page per relevant index partition, without falling back to a scan.

    An overview page is channel-balanced, not one global timeline slice. Return
    every fetched row so advancing a partition never drops results. A thread uses
    only the contact index; the caller can continue through an empty filtered page.
    """
    if channel not in (*CHANNELS, "all") or direction not in ("", "inbound", "outbound"):
        raise ValueError("Invalid inbox filter.")
    if contact_id and len(contact_id) > 250:
        raise ValueError("Invalid contact ID.")
    partition = "contactId" if contact_id else "channel"
    streams = (contact_id,) if contact_id else (CHANNELS if channel == "all" else (channel,))
    scope = [contact_id, channel, direction]
    positions = _decode(cursor, scope, partition, streams)
    limit = max(1, min(MAX_PAGE, limit))
    per_partition = max(1, limit // len(streams))
    messages, failed_channels, next_positions = [], [], {}
    filter_expression = Attr("direction").eq(direction) if direction else None
    if contact_id and channel != "all":
        match = Attr("channel").eq(channel)
        filter_expression = match if filter_expression is None else (match & filter_expression)

    for stream, previous in positions.items():
        query = {
            "IndexName": f"{partition}-index",
            "KeyConditionExpression": Key(partition).eq(stream),
            "ScanIndexForward": False,
            "Limit": per_partition,
        }
        if previous is not None:
            query["ExclusiveStartKey"] = previous
        if filter_expression is not None:
            query["FilterExpression"] = filter_expression
        try:
            result = table.query(**query)
        except (BotoCoreError, ClientError) as exc:
            if contact_id or len(streams) == 1:
                raise
            logger.warning("inbox_partition_read_failed channel=%s type=%s", stream, type(exc).__name__)
            failed_channels.append(stream)
            next_positions[stream] = previous
            continue
        messages.extend(result["Items"])
        if result.get("LastEvaluatedKey"):
            next_positions[stream] = result["LastEvaluatedKey"]

    messages.sort(key=lambda row: (
        float(row.get("timestamp") or 0), str(row.get("id") or "")
    ), reverse=True)
    return messages, _encode(scope, next_positions), failed_channels, len(positions)
