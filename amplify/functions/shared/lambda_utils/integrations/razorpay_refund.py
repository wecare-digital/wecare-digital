"""Single Razorpay refund execution boundary.

This is deliberately dormant unless REFUND_INITIATION_ENABLED is exactly "true".
Callers must prove business eligibility before entering this module. This module owns only
provider authentication and the one irreversible POST. It never retries an ambiguous request:
Razorpay refunds are irreversible, so a timeout must be reconciled from provider evidence before
another attempt is allowed.
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict

import boto3

API_SECRET_ID = os.environ.get("RAZORPAY_API_SECRET_ID", "wecare/razorpay/api")
_PAYMENT_ID = re.compile(r"^pay_[A-Za-z0-9]+$")


class RefundDisabled(RuntimeError):
    pass


class RefundRejected(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"provider rejected refund with HTTP {status}")
        self.status = status


class RefundAmbiguous(RuntimeError):
    pass


@dataclass(frozen=True)
class RefundResult:
    refund_id: str
    payment_id: str
    amount_paise: int
    status: str


def enabled() -> bool:
    return os.environ.get("REFUND_INITIATION_ENABLED", "").strip().lower() == "true"


def _credentials() -> Dict[str, str]:
    secret = boto3.client(
        "secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1")
    ).get_secret_value(SecretId=API_SECRET_ID)
    data = json.loads(secret.get("SecretString") or "{}")
    key_id = str(data.get("key_id") or "").strip()
    key_secret = str(data.get("key_secret") or "").strip()
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay API credentials are unavailable")
    return {"key_id": key_id, "key_secret": key_secret}


def create_full_refund(
    *,
    payment_id: str,
    amount_paise: int,
    return_submission_id: str,
    order_id: str,
    request_id: str,
) -> RefundResult:
    """Issue exactly one full refund after the caller has durably claimed the case.

    There is intentionally no retry loop. Any network/5xx ambiguity raises RefundAmbiguous;
    the business workflow must reconcile with provider/webhook evidence instead of POSTing again.
    """
    return _create_refund(
        payment_id=payment_id,
        amount_paise=amount_paise,
        return_submission_id=return_submission_id,
        order_id=order_id,
        request_id=request_id,
    )


def create_partial_refund(
    *,
    payment_id: str,
    amount_paise: int,
    return_submission_id: str,
    order_id: str,
    request_id: str,
) -> RefundResult:
    """Issue exactly one partial refund of ``amount_paise`` after the caller has claimed the case.

    This shares every invariant with ``create_full_refund``: one gated, non-retried POST that
    validates the provider echoes back the same payment and the exact requested amount, and that
    treats any 5xx/timeout as RefundAmbiguous. The ONLY difference from the caller's side is intent:
    the caller has derived ``amount_paise`` as a server-authoritative portion of the captured total
    rather than the whole of it. The provider endpoint and request shape are identical — Razorpay
    treats a sub-total ``amount`` as a partial refund — so this stays a thin, explicit alias that
    documents the partial intent without forking the irreversible boundary.
    """
    return _create_refund(
        payment_id=payment_id,
        amount_paise=amount_paise,
        return_submission_id=return_submission_id,
        order_id=order_id,
        request_id=request_id,
    )


def _create_refund(
    *,
    payment_id: str,
    amount_paise: int,
    return_submission_id: str,
    order_id: str,
    request_id: str,
) -> RefundResult:
    """The one irreversible refund POST, shared by the full and partial entry points.

    Keeping a single implementation means the full and partial paths cannot drift on the
    invariants that protect money: the gate, the single non-retried request, the payment-id and
    exact-amount echo check, and the ambiguous-on-5xx/timeout rule all live here once.
    """
    if not enabled():
        raise RefundDisabled("refund initiation is disabled")
    if not _PAYMENT_ID.fullmatch(payment_id or ""):
        raise ValueError("payment_id is not a Razorpay payment id")
    if isinstance(amount_paise, bool) or not isinstance(amount_paise, int) or amount_paise <= 0:
        raise ValueError("amount_paise must be a positive integer")
    if not return_submission_id or not order_id:
        raise ValueError("return submission and order identity are required")

    creds = _credentials()
    token = base64.b64encode(
        f"{creds['key_id']}:{creds['key_secret']}".encode("utf-8")
    ).decode("ascii")
    body = json.dumps(
        {
            "amount": amount_paise,
            "notes": {
                "wecare_return": return_submission_id[:256],
                "wecare_order": order_id[:256],
                "wecare_request": request_id[:256],
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.razorpay.com/v1/payments/{payment_id}/refund",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed provider host
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # A provider 5xx is ambiguous: it may have accepted the irreversible request before
        # failing the response path. Never retry it automatically.
        if int(exc.code) >= 500:
            raise RefundAmbiguous("provider outcome is ambiguous") from exc
        raise RefundRejected(int(exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        raise RefundAmbiguous("provider outcome is ambiguous") from exc

    try:
        result = json.loads(raw.decode("utf-8"))
        refund_id = str(result.get("id") or "").strip()
        response_payment_id = str(result.get("payment_id") or "").strip()
        response_amount = int(result.get("amount"))
        status = str(result.get("status") or "").strip().lower()
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
        raise RefundAmbiguous("provider returned an unusable refund response") from exc

    if (
        not refund_id.startswith("rfnd_")
        or response_payment_id != payment_id
        or response_amount != amount_paise
    ):
        raise RefundAmbiguous("provider refund response did not match the requested payment")
    return RefundResult(
        refund_id=refund_id,
        payment_id=response_payment_id,
        amount_paise=response_amount,
        status=status,
    )


__all__ = [
    "RefundDisabled",
    "RefundRejected",
    "RefundAmbiguous",
    "RefundResult",
    "enabled",
    "create_full_refund",
    "create_partial_refund",
]
