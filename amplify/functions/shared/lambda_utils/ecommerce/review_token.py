"""Order-bound tokens for the "Leave Review" FLOW button on the paid-invoice template.

Purpose
-------
`wecare_default_invoice_image_template` carries a FLOW button (index 0) that opens F002 Leave
Review. Meta echoes the button's `flow_token` back inside the completion's `response_json`, so the
token is the only thing that can tie a review to the ORDER and INVOICE it was written about. The
old token was random (`flow-<uuid>-waba-1-ph-<digits>`), carried the customer's phone number, and
was never recorded anywhere, so every review landed on the contact alone.

This module mints an opaque token, records what it stands for, and resolves it later:

    REVIEWTOKEN#<token>  ->  {invoiceId, orderId, referenceId, contactId, customerUuid}

Authority
---------
- The invoice engine (`send_invoice_whatsapp`) is the only minter and binder. It writes the row on
  CommerceKeys before the template is sent.
- The inbound handler (`customer_ideas.save_idea`) is the only resolver. A binding is advisory
  attribution: it never changes who the review belongs to. The sender's own contact decides that,
  and a binding whose `contactId` disagrees with the sender is ignored.

The token carries no personal data. It is `review-` plus 24 URL-safe random characters, which is
well inside Meta's flow_token limits and unguessable.

Failure posture
---------------
Binding raises `OrderIdentityUnavailable` on a storage error so the caller can decide; the invoice
engine logs and still sends the GST invoice, because a review link is never worth a lost invoice.
Resolution returns None on any miss, malformed token or storage error: a review must be saved even
when its order cannot be found.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from typing import Any, Dict, Optional

from lambda_utils.ecommerce import order_keys

logger = logging.getLogger(__name__)

#: Every token this module mints starts with this, so a resolver can tell one from Meta's own
#: placeholder (`unused`) or a legacy random token without a storage read.
TOKEN_PREFIX = "review-"

#: The CommerceKeys row prefix. CommerceKeys has no TTL; a binding lives as long as the invoice.
KEY_PREFIX = "REVIEWTOKEN#"
KIND = "REVIEW_TOKEN_BINDING"

_TOKEN_RE = re.compile(r"^review-[A-Za-z0-9_-]{24}$")

#: The attributes a binding carries, in one place so the binder and the resolver cannot drift.
BOUND_FIELDS = ("invoiceId", "orderId", "referenceId", "contactId", "customerUuid")


def mint() -> str:
    """A fresh opaque review token. 18 random bytes encode to exactly 24 URL-safe characters."""
    return TOKEN_PREFIX + secrets.token_urlsafe(18)


def is_review_token(value: Any) -> bool:
    """True for a token this module could have minted. Pure; no storage read."""
    return isinstance(value, str) and bool(_TOKEN_RE.fullmatch(value))


def _key(token: str) -> str:
    return KEY_PREFIX + token


def bind(table: Any, *, token: str, invoice_id: str, order_id: str = "",
         reference_id: str = "", contact_id: str = "", customer_uuid: str = "",
         now: Optional[int] = None, key_attr: str = "orderId") -> bool:
    """Record what `token` stands for. True when written, False when the token already existed.

    Conditional on the row being absent, so a token can never be re-pointed at another order.
    Empty optional fields are omitted rather than stored as blanks.
    """
    if not is_review_token(token):
        raise ValueError("not a review token")
    if not invoice_id:
        raise ValueError("invoice_id is required")
    item: Dict[str, Any] = {
        "kind": KIND,
        "reviewToken": token,
        "invoiceId": invoice_id,
        "createdAt": int(now if now is not None else time.time()),
    }
    for name, value in (("orderId", order_id), ("referenceId", reference_id),
                        ("contactId", contact_id), ("customerUuid", customer_uuid)):
        if value:
            # `orderId` is the table's partition attribute, so the bound order is stored under a
            # different name and translated back on resolve.
            item["boundOrderId" if name == "orderId" else name] = str(value)
    item[key_attr] = _key(token)
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(%s)" % key_attr)
        return True
    except Exception as error:  # noqa: BLE001 - classified below
        if order_keys.is_conditional_failure(error):
            return False
        raise order_keys.OrderIdentityUnavailable(
            "could not bind a review token: %s" % type(error).__name__) from error


def resolve(table: Any, token: Any, *, key_attr: str = "orderId") -> Optional[Dict[str, str]]:
    """The binding for `token` as `{invoiceId, orderId, referenceId, contactId, customerUuid}`.

    None for a token this module did not mint, an unknown token, or a storage error. Never raises:
    the caller is saving a customer's review and must not lose it to an attribution lookup.
    """
    if not is_review_token(token):
        return None
    try:
        row = table.get_item(Key={key_attr: _key(token)}, ConsistentRead=True).get("Item")
    except Exception as error:  # noqa: BLE001 - attribution is best-effort by contract
        logger.warning('{"event":"review_token_resolve_failed","error":"%s"}',
                       type(error).__name__)
        return None
    if not row or row.get("kind") != KIND:
        return None
    binding = {
        "invoiceId": str(row.get("invoiceId") or ""),
        "orderId": str(row.get("boundOrderId") or ""),
        "referenceId": str(row.get("referenceId") or ""),
        "contactId": str(row.get("contactId") or ""),
        "customerUuid": str(row.get("customerUuid") or ""),
    }
    return {name: value for name, value in binding.items() if value}


__all__ = ["TOKEN_PREFIX", "KEY_PREFIX", "KIND", "BOUND_FIELDS", "mint", "is_review_token",
           "bind", "resolve"]
