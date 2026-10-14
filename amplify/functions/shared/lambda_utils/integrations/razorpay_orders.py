"""Creating a Razorpay order, and verifying the browser's checkout callback signature.

Where this sits in the website Standard Checkout flow (section 8)
-----------------------------------------------------------------
    [customer, signed in]  --create-->  website checkout backend
                                             |  compute payable via checkout_pricing (FEAT-001)
                                             |  reserve a durable request key BEFORE this call
                                             v
                                     create_order()  --POST /v1/orders-->  [Razorpay]
                                             |  persist gateway order id/account/mode/amount
                                             v
                                   browser opens Razorpay Standard Checkout (hosted modal)
                                             |  razorpay_payment_id|razorpay_order_id|razorpay_signature
                                             v
                              verify_checkout_signature()  (HMAC on the SERVER-STORED order id)
                                             |  signed success is still only a trigger
                                             v
                              razorpay_verify.verifier_for_event  (authoritative capture readback)

This module is deliberately two small things and nothing more:

* `create_order` — the one server-side `POST /v1/orders`. It is the only place a payable gateway
  order is created for the website path, and it disables partial payment so a customer cannot pay
  a fraction of the reviewed total.
* `verify_checkout_signature` — the HMAC check Razorpay documents for the browser handoff
  (`razorpay_order_id|razorpay_payment_id` keyed with `key_secret`). It is NOT a payment proof:
  it only confirms the browser result was not tampered with. A paid state still requires
  `razorpay_verify`'s authenticated capture readback.

Why a separate module from `razorpay_verify`
--------------------------------------------
`razorpay_verify` answers one question — "did Razorpay capture this?" — and is the only thing that
may assert a payment happened. Creating an order and checking a callback signature are different
operations with different trust: an order-create is a request we make, and a callback signature is
tamper-evidence on data the browser relayed. Keeping them here, as a sibling, keeps
`razorpay_verify` the single authority on capture while reusing the same lazy-secret,
status-only-logging, `RazorpayUnavailable`-on-error posture.

Which secret, and the lazy read
--------------------------------
`wecare/razorpay/api` (`key_id` + `key_secret`). **Not** `wecare/razorpay-webhook`, which holds
only `webhook_secret`. Conflating them has cost this codebase once already (see `razorpay_verify`
and `core/secure-files/razorpay_orders`). `key_id` is publishable — the browser checkout needs it —
and `key_secret` is used only as HTTP basic auth and the HMAC key here and never leaves this module.
The read is lazy, at request time, cached per sandbox, for the SnapStart reason recorded in
`razorpay_verify`: a module-scope read freezes a rotated value until every warm sandbox recycles.

No value is ever logged. Status codes and exception TYPES only; Razorpay's error bodies echo the
request, which carried basic auth, so neither the body nor the signature prefix is logged.

No SDK
------
`razorpay==2.0.1` is in `requirements-dev.txt` only, so it is not in the Lambda runtime. The Orders
API is one POST and the signature is one HMAC; bundling a dependency to make them would be the
larger risk. This mirrors `core/secure-files/razorpay_orders`, which already does the same.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: key_id + key_secret. See the note above about the other secret.
RAZORPAY_SECRET_ID = os.environ.get("RAZORPAY_SECRET_ID", "wecare/razorpay/api")

API_BASE = "https://api.razorpay.com/v1"
ORDERS_ENDPOINT = API_BASE + "/orders"
TIMEOUT_SECONDS = 10

#: Razorpay's `receipt` tolerates 40 characters; a WD reference always fits.
RECEIPT_MAX_LENGTH = 40

_secrets_client = None
from lambda_utils.secrets_access import JsonSecretCache, SecretAccessError

_credential_cache = JsonSecretCache(ttl_seconds=120)


class RazorpayUnavailable(RuntimeError):
    """Razorpay could not be reached or answered with an error, OR a save could not be confirmed.

    The whole point of the type is to mark AMBIGUITY. An unreachable provider, a timed-out
    order-create, or a create that may have succeeded but whose binding could not be persisted all
    mean the SAME thing: we do not know whether a payable order now exists on Razorpay's side. The
    caller must NEVER respond to this by blindly creating a second payable order — it must use a
    documented lookup/correlation path (`find_order_by_receipt`) to discover whether the first one
    landed, and reconcile, rather than assume an undocumented Orders-API idempotency.
    """


def _client():
    global _secrets_client
    if _secrets_client is None:
        import boto3
        _secrets_client = boto3.client(
            "secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _secrets_client


def _credentials() -> Dict[str, str]:
    """Resolve required API credentials with a bounded, rotation-aware cache."""
    try:
        return _credential_cache.read(
            _client(), RAZORPAY_SECRET_ID, required=("key_id", "key_secret"),
            generation=os.environ.get("SECRETS_REFRESHED_AT", ""),
        )
    except SecretAccessError:
        raise RazorpayUnavailable("required payment credentials unavailable") from None


def public_key_id() -> str:
    """The publishable `key_id`, which the browser checkout needs. Never the secret."""
    return _credentials()["key_id"]


def account_mode(key_id: str) -> str:
    """`test` or `live`, inferred from the key id prefix Razorpay documents.

    `rzp_test_` is test mode; `rzp_live_` is live. The mode is persisted on the binding so a
    callback or a reconciliation can refuse a result produced under a different mode than the one
    the order was created in — a test-mode success must never settle a live-mode order.
    """
    kid = str(key_id or "")
    if kid.startswith("rzp_test_"):
        return "test"
    if kid.startswith("rzp_live_"):
        return "live"
    return "unknown"


def _basic_auth_token(creds: Dict[str, str]) -> str:
    return base64.b64encode(
        f"{creds['key_id']}:{creds['key_secret']}".encode("utf-8")).decode("ascii")


def create_order(*, amount_paise: int, receipt: str,
                 notes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create one INR Razorpay order with partial payment DISABLED. Returns the order record.

    `amount_paise` must be a strictly positive integer number of minor units — the website path
    only ever creates an order for a payable (non-zero) quote. `partial_payment` is forced to
    `False` so a customer cannot pay a fraction of the reviewed total; this is the one release
    decision this module hard-codes rather than leaving to the account default.

    `payment_capture` is left at the account default on purpose: capture behaviour is payment
    configuration and the account owner's decision, not this module's. The result record carries
    the public `key_id` (added here, so the caller never reads the secret) alongside Razorpay's
    `id`, `amount`, `currency`, `status` and `receipt`.

    On any transport error, HTTP error, or timeout this raises `RazorpayUnavailable` — which the
    caller must treat as AMBIGUOUS (see the class docstring), never as a clean failure that
    licenses a second create.
    """
    if isinstance(amount_paise, bool) or type(amount_paise) is not int:
        raise ValueError("amount_paise must be an int of minor units")
    if amount_paise <= 0:
        raise ValueError("amount_paise must be positive")
    if not receipt:
        raise ValueError("receipt is required to correlate an order on timeout")

    creds = _credentials()
    payload = json.dumps({
        "amount": int(amount_paise),
        "currency": "INR",
        "receipt": receipt[:RECEIPT_MAX_LENGTH],
        # Disabled for this release. A customer must pay the full reviewed total or nothing.
        "partial_payment": False,
        "notes": dict(notes or {}),
    }).encode("utf-8")

    request = urllib.request.Request(
        ORDERS_ENDPOINT, data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Basic {_basic_auth_token(creds)}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            order = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Status only: the request carried basic auth and Razorpay's error bodies echo it.
        raise RazorpayUnavailable(f"Razorpay order creation returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        # Includes socket timeout. AMBIGUOUS: the order may or may not have been created.
        raise RazorpayUnavailable("Razorpay unreachable or timed out creating an order") from None

    order["key_id"] = creds["key_id"]
    return order


def find_order_by_receipt(receipt: str) -> Optional[Dict[str, Any]]:
    """Look up an order we previously (maybe) created, by its receipt. For AMBIGUITY recovery.

    When `create_order` raised `RazorpayUnavailable` (a timeout, or a save failure after a possible
    create), the caller must not blindly create a second payable order. The receipt is minted by us
    and unique to the attempt, so this documented lookup lets the caller discover whether the first
    create actually landed and correlate to it. Returns the matching order record, or None when
    none is found. Raises `RazorpayUnavailable` only when the provider itself is unreachable — a
    clean "no such order" is `None`, not an error.

    Razorpay's `GET /v1/orders?receipt=...` filters on the receipt we set. We do NOT depend on any
    undocumented Orders-API idempotency; this is an explicit correlation query.
    """
    if not receipt:
        return None
    creds = _credentials()
    query = urllib.parse.urlencode({"receipt": receipt[:RECEIPT_MAX_LENGTH]})
    request = urllib.request.Request(
        f"{ORDERS_ENDPOINT}?{query}", method="GET",
        headers={"Authorization": f"Basic {_basic_auth_token(creds)}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RazorpayUnavailable(f"Razorpay order lookup returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RazorpayUnavailable("Razorpay unreachable looking up an order by receipt") from None

    for order in payload.get("items", []) or []:
        if str(order.get("receipt") or "") == receipt[:RECEIPT_MAX_LENGTH]:
            order["key_id"] = creds["key_id"]
            return order
    return None


def checkout_signature(order_id: str, payment_id: str) -> str:
    """The HMAC-SHA256 Razorpay documents for the browser Standard Checkout callback.

    Signed string is `razorpay_order_id | razorpay_payment_id` (a literal pipe), keyed with
    `key_secret`. The ORDER ID passed here must be the SERVER-STORED one, never the value the
    browser relayed, which is the whole point of the check: it binds the browser's claimed payment
    to the order WE created.

    Source: Razorpay Standard Checkout "Step 4: Verify Payment Signature".
    https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/
    """
    if not order_id or not payment_id:
        raise ValueError("order_id and payment_id are required to compute a signature")
    creds = _credentials()
    message = f"{order_id}|{payment_id}".encode("utf-8")
    return hmac.new(creds["key_secret"].encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_checkout_signature(*, stored_order_id: str, payment_id: str, signature: str) -> bool:
    """True when the browser callback signature matches, computed over the SERVER-STORED order id.

    Tamper-evidence, NOT a payment proof. A True here means the browser result was not altered in
    transit and names the order we created; it does NOT mean money moved. The caller must still run
    `razorpay_verify` for an authenticated capture readback before any paid state. Uses
    `hmac.compare_digest` so the comparison does not leak timing. A missing field is False, never
    an exception, so a malformed callback simply fails closed.
    """
    if not stored_order_id or not payment_id or not signature:
        return False
    try:
        expected = checkout_signature(stored_order_id, payment_id)
    except RazorpayUnavailable:
        # Secret unavailable: we cannot verify, so we do not approve. Fail closed.
        return False
    return hmac.compare_digest(expected, str(signature))


__all__ = [
    "RAZORPAY_SECRET_ID",
    "RECEIPT_MAX_LENGTH",
    "RazorpayUnavailable",
    "public_key_id",
    "account_mode",
    "create_order",
    "find_order_by_receipt",
    "checkout_signature",
    "verify_checkout_signature",
]
