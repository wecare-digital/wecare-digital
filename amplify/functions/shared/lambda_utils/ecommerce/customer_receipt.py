"""An authenticated, owner-authorised, private Download-receipt built from the immutable paid snapshot.

Section 9: offer a Download receipt on success and in history. The hard requirements, and how each
is met here:

Private, never public, never the bag-icon folder
-------------------------------------------------
A receipt carries a name, an address, a GSTIN and a purchase history. It is written under
`media_paths.secure(...)` - the edge-gated root - and handed out ONLY as a short-lived presigned URL
from `receipt_links.signed_url`. It is never written under `media_paths.public(...)`, and never under
the public bag-icon media prefix (`o/stream/media/...`); `assert_private_key` refuses any key outside
the secure root so a future edit cannot quietly re-publish it. There is no listing endpoint - a
receipt is reachable only by a proven owner asking for a specific order they own.

Owner-authorised, cross-customer denial
----------------------------------------
Authority comes from the session, never from the request. `customer_auth` proves the caller is a
customer; `authorize_resource` checks the snapshot's `customerId` against that proven identity. A
snapshot that belongs to someone else is refused with the SAME "not found or not yours" response as a
missing one, so the endpoint is not an existence oracle for other people's orders.

Generated from the immutable verified-paid snapshot
---------------------------------------------------
The receipt is rendered from a frozen `checkout_pricing.QuoteSnapshot` - the exact amounts the
customer reviewed and paid - not from live cart or pricing. The amounts come straight from the
snapshot's rounded integer-paise components; nothing is recomputed, so the printed total always
equals the charged total.

Reuses the invoice-engine design
--------------------------------
The HTML/PNG/PDF look is the WhatsApp invoice design. This module builds the invoice dict the engine
expects and calls the engine's own `_build_invoice_html`, so there is one receipt design, not two.
The engine function is injected (a callable) so this module needs no S3/boto to be imported or tested.

Idempotent regeneration
-----------------------
The storage key is DERIVED from the snapshot hash and the format, so regenerating a receipt for the
same paid snapshot targets the same object every time - a second request overwrites identical bytes
rather than creating a parallel receipt. Two customers, two snapshots, two different hashes, two
different keys; the same customer regenerating is one key. The snapshot hash already changes if
anything about the order changes (see `checkout_pricing`), so a changed order is a different receipt
by construction.

The S3 PutObject / presign network calls are BLOCKED here (no AWS). The S3 client is injected and the
tests mock it; the code path that stores and signs is complete and asserted against the mock.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Dict, List, Optional

from lambda_utils import media_paths, receipt_links
from lambda_utils.customer_auth import CustomerIdentity, CustomerNotAuthorized, authorize_resource
from lambda_utils.ecommerce import order_channel
from lambda_utils.ecommerce.checkout_pricing import QuoteSnapshot

logger = logging.getLogger(__name__)

#: Allowed render formats. PNG and PDF are the invoice-engine outputs; HTML is the source both are
#: rendered from and is useful for a browser download.
ALLOWED_FORMATS = ("pdf", "png", "html")

#: The private root every receipt key must sit under. A receipt outside `secure/` is edge-public.
_SECURE_ROOT = media_paths.SECURE_ROOT

#: Where receipts live inside the gated root. NOT the public bag-icon prefix `o/stream/media/...`.
RECEIPT_PREFIX = "stack/receipts/"


class ReceiptError(RuntimeError):
    """A receipt could not be produced."""


def _format(fmt: str) -> str:
    f = str(fmt or "pdf").lower().lstrip(".")
    if f not in ALLOWED_FORMATS:
        raise ReceiptError(f"unsupported receipt format {fmt!r}; one of {ALLOWED_FORMATS}")
    return f


def receipt_key(snapshot: QuoteSnapshot, *, fmt: str = "pdf") -> str:
    """The DETERMINISTIC storage key for a snapshot's receipt in a given format.

    Derived from the snapshot hash and the format, so idempotent regeneration lands on the same
    object. Rooted under the gated prefix; `assert_private_key` is applied so this can never be moved
    to a public root by a careless edit.
    """
    f = _format(fmt)
    # The snapshot hash is already a 256-bit digest over the frozen order; truncating keeps the key
    # short while staying far past guessable, and the gated root means it is never served unsigned.
    stem = hashlib.sha256(
        f"receipt\x1f{snapshot.snapshot_hash}\x1f{f}".encode("utf-8")
    ).hexdigest()[:32]
    key = media_paths.secure(f"{RECEIPT_PREFIX}wecare-digital-{stem}.{f}")
    return assert_private_key(key)


def assert_private_key(key: str) -> str:
    """Return `key` if it is under the gated root, else raise.

    The last line of defence against a receipt being written somewhere public. A receipt under
    `o/` - and especially under the bag-icon media prefix `o/stream/media/...` - would be fetchable
    without authentication the moment its URL leaked, which is the exact disclosure this file exists
    to prevent.
    """
    if not isinstance(key, str) or not key.startswith(_SECURE_ROOT):
        raise ReceiptError(
            f"refusing a receipt key outside the gated root: {key!r}. A receipt carries a name, an "
            "address and a GSTIN and must never be written to a public prefix."
        )
    if media_paths.PUBLIC_ROOT + "stream/media/" in key or key.startswith(
            media_paths.PUBLIC_ROOT):
        raise ReceiptError("a receipt must not be written to the public bag-icon media prefix")
    return key


def invoice_dict_from_snapshot(snapshot: QuoteSnapshot, *,
                               order_number: str,
                               invoice_number: str = "",
                               channel: str = "",
                               customer_uuid: str = "") -> Dict[str, Any]:
    """Build the invoice dict the engine's `_build_invoice_html` expects, from the frozen snapshot.

    Every money field is taken from the snapshot's integer-paise components and converted to rupees
    for the engine's rupee-denominated template - the conversion is the only arithmetic, and it is
    exact because paise are integers. Nothing is recomputed from live pricing: the receipt shows what
    was reviewed and paid.

    `invoice_number` and `channel` are PASSED IN, never derived here. The number especially: only
    `invoice-engine._get_next_invoice_number` may mint one, because issuing a number advances the
    GST Rule 46(b) consecutive series for the financial year and a number cannot be reassigned once
    it has reached a customer. A download is a read, so it prints the number the order already has
    and renders no `Invoice No:` row when there is none - which is the honest answer for a website
    order that was never invoiced by the engine. `channel` goes through `order_channel.canonical`,
    so an absent value prints `Source: Website`, true of every order placed so far.

    `customer_uuid` is PASSED IN on exactly the same footing, and for the same reason: the caller
    holds the order row, so it knows the public customer id; this function must not reach for one
    and must never mint a substitute. Empty is the honest answer for every order row written
    before the attribute existed, and the renderers draw no `Customer ID:` row for an empty one
    rather than a label with nothing after it.
    """
    quote = snapshot.quote
    frozen = dict(snapshot.frozen_data or {})
    address = frozen.get("address") or {}
    items_in = frozen.get("items") or []

    def _rupees(paise: int) -> float:
        return round(int(paise) / 100.0, 2)

    items: List[Dict[str, Any]] = []
    for raw in items_in:
        item = dict(raw) if isinstance(raw, dict) else {}
        items.append({
            "name": str(item.get("name") or item.get("title") or "Item"),
            "amount": _rupees(item.get("amountPaise", 0)) if "amountPaise" in item
            else float(item.get("amount", 0) or 0),
            "quantity": int(item.get("quantity", 1) or 1),
        })

    return {
        "invoiceId": f"receipt-{snapshot.snapshot_hash[:32]}",
        "invoiceNumber": invoice_number,
        "orderId": order_number,
        "referenceId": order_number,
        "channel": order_channel.canonical(channel),
        # NOT canonicalised, because there is nothing to canonicalise: unlike `channel`, which
        # has a true default, an absent customer id has no substitute and must stay absent. The
        # renderers suppress the row for "".
        "customerUuid": str(customer_uuid or ""),
        "entryPoint": "website_checkout",
        "status": "paid",
        "paymentStatus": "captured",
        "customerName": str(address.get("name") or ""),
        "customerPhone": str(address.get("phone") or ""),
        "customerEmail": str(address.get("email") or ""),
        "shippingAddress": str(address.get("line") or address.get("shippingAddress") or ""),
        "billingAddress": str(address.get("line") or address.get("billingAddress") or ""),
        "items": items,
        # Amounts straight from the frozen quote, in rupees for the engine template.
        "subtotal": _rupees(quote.collection_before_convenience_paise),
        "convenienceFee": _rupees(quote.convenience_fee_paise + quote.convenience_gst_paise),
        "total": _rupees(quote.total_payable_paise),
        "currency": quote.currency,
        "gstin": quote.buyer_gstin or "",
        "sellerGstin": quote.seller_gstin,
    }


def generate_receipt(*,
                     identity: CustomerIdentity,
                     snapshot: QuoteSnapshot,
                     order_number: str,
                     s3_client: Any,
                     build_invoice_html: Callable[[Dict[str, Any], List[Dict[str, Any]]], str],
                     bucket: str,
                     fmt: str = "pdf",
                     invoice_number: str = "",
                     channel: str = "",
                     customer_uuid: str = "",
                     ttl_seconds: Optional[int] = None,
                     render: Optional[Callable[[str, str], bytes]] = None,
                     now: Optional[int] = None) -> Dict[str, Any]:
    """Authorise, render from the frozen snapshot, store privately, and return a bounded-expiry link.

    Authorisation first: the snapshot must belong to the proven caller, or this raises
    `CustomerNotAuthorized` with the same opaque result a missing one would.

    Rendering reuses `build_invoice_html` (the engine's own function, injected). For PNG/PDF a
    `render(html, fmt)` callable turns the HTML into bytes - also injected, because the engine's
    rasteriser needs PIL/fonts from S3 that are unavailable offline; the HTML path needs no renderer.

    Idempotent: the key is derived from the snapshot, so a second call stores identical bytes to the
    same object. The returned link is signed and short-lived via `receipt_links`, which refuses a TTL
    past its one-week ceiling.
    """
    # Authority from the token, resource checked against it. Cross-customer => CustomerNotAuthorized.
    authorize_resource(identity, {"customerId": snapshot.customer_id}, owner_field="customerId")

    f = _format(fmt)
    key = receipt_key(snapshot, fmt=f)
    # Threaded, not invented. The caller holds the order row, so it knows the invoice number (if
    # the engine ever issued one), the channel and the public customer id; this function must not
    # reach for any of them, and must never synthesise a number - see invoice_dict_from_snapshot.
    # All three default to "", which renders no `Invoice No:` row, no `Customer ID:` row and
    # `Source: Website`.
    invoice = invoice_dict_from_snapshot(
        snapshot, order_number=order_number,
        invoice_number=invoice_number, channel=channel,
        customer_uuid=customer_uuid)
    html = build_invoice_html(invoice, invoice.get("items", []))

    if f == "html":
        body = html.encode("utf-8")
        content_type = "text/html; charset=utf-8"
    else:
        if render is None:
            raise ReceiptError(
                f"a {f} receipt needs a renderer; the engine's rasteriser is injected because it "
                "needs fonts/images from S3 unavailable offline"
            )
        body = render(html, f)
        content_type = "application/pdf" if f == "pdf" else "image/png"

    # Store under the gated root. Idempotent: same key, same bytes on regeneration.
    try:
        s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
    except Exception as error:  # noqa: BLE001
        # Type only; an S3 error message can echo the key.
        logger.warning('{"event":"receipt_store_failed","reason":"%s"}', type(error).__name__)
        raise ReceiptError(f"could not store the receipt: {type(error).__name__}") from error

    filename = f"receipt-{order_number}.{f}" if order_number else f"receipt.{f}"
    url = receipt_links.signed_url(
        s3_client, bucket=bucket, key=key, filename=filename, ttl_seconds=ttl_seconds)
    # The URL carries a grant; it never reaches a log. The customer id does not either.
    logger.info('{"event":"receipt_generated","format":"%s"}', f)
    return {"key": key, "url": url, "format": f}


__all__ = [
    "ALLOWED_FORMATS",
    "RECEIPT_PREFIX",
    "ReceiptError",
    "receipt_key",
    "assert_private_key",
    "invoice_dict_from_snapshot",
    "generate_receipt",
]
