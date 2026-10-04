"""Asking Razorpay whether a payment actually happened. The only thing that may assert it.

Why this is in the shared layer
-------------------------------
The pattern already existed, and it was right, but it lived inside one function:
`core/secure-files/razorpay_orders.order_is_paid`, reachable only by that handler. Meanwhile
`payments/razorpay-webhook` — the function that receives every real payment event — trusted the
event body.

Copying the check into the webhook would have given this codebase **two implementations of the one
question that decides whether money moved**, and the second would be the untested one. So it moves
here, and both callers use it.

Why a webhook body is not evidence
----------------------------------
`razorpay_orders`' own docstring records the reason, and it is specific rather than theoretical:
the webhook signing secret is present in this repository's **public git history**. Anyone who read
that history can forge a signature-valid `payment.captured`. Rotating the secret would close that;
taking the secret out of the decision closes it permanently and does not depend on a rotation ever
happening.

So a webhook is a trigger to verify. An authenticated response to a request *we* made is the
evidence.

Only `captured` counts
----------------------
`authorized` means the funds are held, not taken. Granting on it hands over goods for a payment
that can still fail. This module reports `captured` and nothing else as paid — the same line
`secure-files` drew.

Which secret
------------
`wecare/razorpay/api`, which holds `key_id` and `key_secret`. **Not** `wecare/razorpay-webhook`,
which has only ever held `webhook_secret`. Conflating them has already cost this codebase once:
`partner-onboarding` read the API pair out of the webhook secret, got empty strings, and every
customer-service top-up returned 501 until it was found.

Read lazily, at request time. A module-scope read is cached for the life of the execution
environment, so a rotation would not take effect until every warm sandbox recycled.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: key_id + key_secret. See the note above about the other secret.
RAZORPAY_SECRET_ID = os.environ.get("RAZORPAY_SECRET_ID", "wecare/razorpay/api")

API_BASE = "https://api.razorpay.com/v1"
TIMEOUT_SECONDS = 10

#: The only status that means the money is ours.
CAPTURED = "captured"

_secrets_client = None
_cached: Optional[Dict[str, str]] = None


class RazorpayUnavailable(RuntimeError):
    """Razorpay could not be reached or answered with an error.

    Distinct from "not paid", and the distinction is the whole point: an unreachable provider means
    we do not know, and not knowing must never create an order.
    """


def _client():
    global _secrets_client
    if _secrets_client is None:
        import boto3
        _secrets_client = boto3.client(
            "secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return _secrets_client


def _credentials() -> Dict[str, str]:
    """`key_id` and `key_secret`, cached per sandbox. Never logged, never returned to a caller."""
    global _cached
    if _cached is None:
        raw = _client().get_secret_value(SecretId=RAZORPAY_SECRET_ID)
        parsed = json.loads(raw.get("SecretString") or "{}")
        _cached = {
            "key_id": (parsed.get("key_id") or "").strip(),
            "key_secret": (parsed.get("key_secret") or "").strip(),
        }
    if not _cached["key_id"] or not _cached["key_secret"]:
        # Names the secret to look at and nothing about its contents.
        raise RazorpayUnavailable(
            f"key_id/key_secret missing from {RAZORPAY_SECRET_ID}")
    return _cached


def _get(path: str) -> Dict:
    creds = _credentials()
    token = base64.b64encode(
        f"{creds['key_id']}:{creds['key_secret']}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        f"{API_BASE}{path}", method="GET",
        headers={"Authorization": f"Basic {token}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Status only. The request carried basic auth and Razorpay's error bodies echo request
        # context, so neither belongs in a log or an exception message.
        raise RazorpayUnavailable(f"Razorpay returned HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise RazorpayUnavailable("Razorpay unreachable") from None


def payment_is_captured(payment_id: str) -> Tuple[bool, int, str]:
    """`(captured, amount_paise, currency)` for one Razorpay payment id.

    Used when the event names a payment directly, which is the common case for
    `payment.captured`. Raises `RazorpayUnavailable` rather than reporting "not paid" when the
    answer is unknown.
    """
    if not payment_id:
        raise ValueError("payment_id is required")
    payment = _get(f"/payments/{urllib.parse.quote(payment_id, safe='')}")
    status = str(payment.get("status") or "")
    return (
        status == CAPTURED,
        int(payment.get("amount") or 0),
        str(payment.get("currency") or ""),
    )


def payment_capture_details(payment_id: str) -> Tuple[bool, int, str, str]:
    """`(captured, amount_paise, currency, provider_order_id)` for one Razorpay payment id.

    The same authoritative readback as `payment_is_captured`, but it also returns the payment's
    provider `order_id`. The legacy-invoice path needs that id to prove this capture belongs to the
    provider order recorded against the invoice (R2 binding): amount equality alone cannot
    establish that THIS payment settles THIS invoice. The order id is read from Razorpay's API
    response, never from the webhook event body. Raises `RazorpayUnavailable` rather than reporting
    "not paid" when the answer is unknown.
    """
    if not payment_id:
        raise ValueError("payment_id is required")
    payment = _get(f"/payments/{urllib.parse.quote(payment_id, safe='')}")
    status = str(payment.get("status") or "")
    return (
        status == CAPTURED,
        int(payment.get("amount") or 0),
        str(payment.get("currency") or ""),
        str(payment.get("order_id") or ""),
    )


def order_is_paid(order_id: str) -> Tuple[bool, str, int, str]:
    """`(paid, payment_id, amount_paise, currency)` for a Razorpay order.

    Same shape and same semantics as `secure-files.razorpay_orders.order_is_paid`, which this
    generalises: it now also returns the currency, because the reconciliation path has to compare
    it explicitly rather than assume INR.
    """
    if not order_id:
        raise ValueError("order_id is required")
    payload = _get(f"/orders/{urllib.parse.quote(order_id, safe='')}/payments")
    for payment in payload.get("items", []) or []:
        if str(payment.get("status") or "") == CAPTURED:
            return (
                True,
                str(payment.get("id") or ""),
                int(payment.get("amount") or 0),
                str(payment.get("currency") or ""),
            )
    return False, "", 0, ""


def verifier_for_event(payment_id: str = "", order_id: str = "", *,
                       load_attempt=None):
    """Verify a capture bound to a trusted attempt, never just an event reference.

    The attempt must already carry a providerOrderId or providerPaymentId derived
    from payment initiation or an authenticated Meta lookup. A webhook must not
    supply its own binding. Missing bindings fail closed for reconciliation.
    """
    if not payment_id and not order_id:
        raise ValueError("a payment id or an order id is required to verify")

    def verify(reference_id: str) -> Tuple[bool, str, int, str]:
        from lambda_utils.ecommerce.money import positive_paise
        attempt = load_attempt(reference_id) if load_attempt else None
        if not attempt:
            raise RazorpayUnavailable("payment attempt binding is unavailable")
        bound_payment = str(attempt.get("providerPaymentId") or "")
        bound_order = str(attempt.get("providerOrderId") or "")
        if not bound_payment and not bound_order:
            raise RazorpayUnavailable("payment attempt has no verified provider binding")
        if bound_payment and payment_id and bound_payment != payment_id:
            raise RazorpayUnavailable("payment id disagrees with stored binding")
        target = bound_payment or payment_id
        if target:
            payment = _get(f"/payments/{urllib.parse.quote(target, safe='')}")
            payments = [payment]
        else:
            # Only a stored order id may select the payments being checked.
            payload = _get(f"/orders/{urllib.parse.quote(bound_order, safe='')}/payments")
            payments = payload.get("items") or []
        captured = []
        for payment in payments:
            actual_id = payment.get("id")
            if not actual_id or (target and actual_id != target):
                raise RazorpayUnavailable("provider returned an unexpected payment")
            if bound_order and payment.get("order_id") != bound_order:
                raise RazorpayUnavailable("payment belongs to another provider order")
            if str(payment.get("status") or "") == CAPTURED:
                captured.append(payment)
        if not captured:
            return False, "", 0, ""
        if len(captured) != 1:
            raise RazorpayUnavailable("multiple captures require reconciliation")
        paid = captured[0]
        return True, paid["id"], positive_paise(paid.get("amount")), str(paid.get("currency") or "")

    return verify


__all__ = [
    "RAZORPAY_SECRET_ID",
    "CAPTURED",
    "RazorpayUnavailable",
    "payment_is_captured",
    "payment_capture_details",
    "order_is_paid",
    "verifier_for_event",
]
