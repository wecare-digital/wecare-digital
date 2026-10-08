"""Whether this business can currently take a WhatsApp payment. Proven, never assumed.

Why this module exists
----------------------
On 2026-09-30 a live read returned the fact that motivates all of it::

    GET /{2094615664435155}/payment_configurations   ->  HTTP 200, ZERO configurations

Meanwhile the repository contained **four** payment-configuration names across three files -
`WECAREDIGITAL` and `WECAREUPI` in the handlers, `WECARE-RAZOR-PAY` and
`Razorpay_ManishAgarwal` in steering - and `docs/compatibility.md` recorded the first pair as
verified live on 2026-08-23. So the code was ready to send `order_details` naming a
configuration that does not exist at Meta, and Meta's own documentation warns that when
`configuration_name` is invalid *the customer is simply unable to pay*.

The lesson is narrow and worth stating plainly: **a constant in source code is not provider
state.** Nothing in this module will report readiness because a name appears in a file. Every
answer is derived from a live readback, and the absence of a readback is itself a refusal.

The MID question — RESOLVED 2026-09-30 by the owner, and the resolution reversed the guess
------------------------------------------------------------------------------------------
Two Razorpay merchant ids appeared in the repo. Earlier prose here reasoned that
`[retired Razorpay account]` was authoritative because it was in live env and carried by Razorpay
webhook payloads, and dismissed `acc_TTFSyolquKEZEy` as "prose and code comments only, no live
artefact". **That reasoning was wrong, and the owner confirmed it against the live Meta dashboard.**

  `acc_TTFSyolquKEZEy`   AUTHORITATIVE. It is the `Payment gateway MID` shown on both live Meta
                         payment configurations (`WECAREDIGITAL` on WABA 2094615664435155, and the
                         same on WABA 2513394156072604). This is the `provider_mid` Meta will
                         report, so it is what `expected_provider_mid` must equal.
  [retired Razorpay account]
                         RETIRED. It was the old `RAZORPAY_MID` environment value and appeared
                         as `account_id` in older webhook fixtures. The manifest and live
                         environment were corrected to `acc_TTFSyolquKEZEy`; the retired
                         identifier was purged from current source by owner instruction.

The lesson the module keeps: a webhook `account_id` is evidence of which account *sent* an event,
not proof of which account the *Meta configuration* settles into. This module still compares the
MID Meta reports against `expected_provider_mid` and refuses on disagreement — it does not pick a
winner from a file. What changed is only which value the deployment supplies as expected. A
mismatch still means the configuration points at a different merchant and money would land
somewhere unexpected.

The UPI VPA question — RESOLVED the same way
--------------------------------------------
`wecaredigitalbh511413.rzp@rxairtel` (the code fallback in `constants.ts`, and the `WECAREUPI`
handle on both live configs) is AUTHORITATIVE. The live-env `[retired UPI VPA]` was stale
and was corrected in the manifest. A stale VPA does not error — it silently collects elsewhere —
which is exactly why it is pinned to the value Meta reports.

Fail closed, and say why
------------------------
Every failure path returns a specific state rather than a bare False, because "payments are off"
and "payments are off because the configuration is on the wrong WABA" need different responses
from a human. The customer-facing surface must render none of that detail (see
`customer_message`) - a shopper should not learn our WABA id from an error.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── states ─────────────────────────────────────────────────────────────────────
PAYMENT_READY = "PAYMENT_READY"
PAYMENT_CONFIG_MISSING = "PAYMENT_CONFIG_MISSING"
PAYMENT_CONFIG_INACTIVE = "PAYMENT_CONFIG_INACTIVE"
PAYMENT_CONFIG_WABA_MISMATCH = "PAYMENT_CONFIG_WABA_MISMATCH"
PAYMENT_CONFIG_NAME_UNKNOWN = "PAYMENT_CONFIG_NAME_UNKNOWN"
RAZORPAY_MID_MISMATCH = "RAZORPAY_MID_MISMATCH"
RAZORPAY_ACCOUNT_UNVERIFIED = "RAZORPAY_ACCOUNT_UNVERIFIED"
PAYMENT_TEMPLATE_MISSING = "PAYMENT_TEMPLATE_MISSING"
META_UNAVAILABLE = "META_UNAVAILABLE"
RAZORPAY_UNAVAILABLE = "RAZORPAY_UNAVAILABLE"
CONFIGURATION_UNVERIFIED = "CONFIGURATION_UNVERIFIED"

#: Every state except PAYMENT_READY blocks a payment attempt. Enumerated rather than derived
#: from `!= PAYMENT_READY` so a new state cannot accidentally become permissive by being added
#: without being classified.
BLOCKING_STATES = frozenset({
    PAYMENT_CONFIG_MISSING,
    PAYMENT_CONFIG_INACTIVE,
    PAYMENT_CONFIG_WABA_MISMATCH,
    PAYMENT_CONFIG_NAME_UNKNOWN,
    RAZORPAY_MID_MISMATCH,
    RAZORPAY_ACCOUNT_UNVERIFIED,
    PAYMENT_TEMPLATE_MISSING,
    META_UNAVAILABLE,
    RAZORPAY_UNAVAILABLE,
    CONFIGURATION_UNVERIFIED,
})

ALL_STATES = frozenset({PAYMENT_READY}) | BLOCKING_STATES

#: Razorpay is the only gateway. PayU was removed from both WABAs at Meta and its secret is
#: permanently deleted; Billdesk and Zaakpay are supported by Meta but not by this business.
EXPECTED_GATEWAY = "razorpay"

#: Meta's customer service window. A free-form interactive `order_details` message is only
#: deliverable inside it; outside, the same payload has to travel in an approved template
#: carrying an ORDER_DETAILS button.
CUSTOMER_SERVICE_WINDOW_SECONDS = 24 * 60 * 60


def window_is_open(last_inbound_at: Optional[int], *,
                   now: Optional[int] = None) -> bool:
    """Whether the customer's 24-hour service window is still open.

    `last_inbound_at` is the epoch second of the customer's most recent inbound message, or
    None when they have never messaged us.

    **None means closed.** That is the conservative direction and it is the correct one: a
    free-form `order_details` sent outside the window is rejected by Meta, or billed as a new
    conversation, and either way the customer does not get a payment request. Assuming the
    window is open when we do not know would convert a missing record into a failed checkout.
    """
    if not last_inbound_at:
        return False
    import time as _time
    moment = int(_time.time()) if now is None else int(now)
    return (moment - int(last_inbound_at)) < CUSTOMER_SERVICE_WINDOW_SECONDS


def template_required(last_inbound_at: Optional[int], *,
                      now: Optional[int] = None) -> bool:
    """Whether this send needs an approved ORDER_DETAILS template rather than a free-form one.

    In the normal checkout flow the customer has just completed WhatsApp OTP, so they *may* be
    inside the window — but the OTP is delivered by a template and the code is typed on the web,
    which sends no inbound message and therefore opens no window. So this is not a formality:
    the common path may well need the template.
    """
    return not window_is_open(last_inbound_at, now=now)

#: Meta reports a configuration's status as a string. Only this one may take money.
_ACTIVE_STATUS = "active"

#: A single opt-out that can only ever tighten. There is deliberately no env var that can turn
#: readiness ON: the only route to PAYMENT_READY is a successful live readback.
_KILL_SWITCH = "WA_PAYMENTS_DISABLED"


class PaymentReadiness:
    """The verdict, with enough detail for an operator and none for a customer."""

    __slots__ = ("state", "reason", "configuration_name", "waba_id", "gateway",
                 "provider_mid", "checked_configurations")

    def __init__(self, state: str, reason: str = "", *,
                 configuration_name: str = "", waba_id: str = "",
                 gateway: str = "", provider_mid: str = "",
                 checked_configurations: Optional[List[str]] = None) -> None:
        if state not in ALL_STATES:
            raise ValueError(f"unknown readiness state {state!r}")
        self.state = state
        self.reason = reason
        self.configuration_name = configuration_name
        self.waba_id = waba_id
        self.gateway = gateway
        self.provider_mid = provider_mid
        self.checked_configurations = list(checked_configurations or [])

    @property
    def ready(self) -> bool:
        """True only for PAYMENT_READY. Nothing else is permissive."""
        return self.state == PAYMENT_READY

    def __bool__(self) -> bool:
        """So `if not readiness:` blocks. Guards against a caller forgetting `.ready`."""
        return self.ready

    def as_dict(self) -> Dict[str, Any]:
        """Operator-facing detail. Safe for a staff surface and a log; not for a customer.

        Contains no secret: a configuration name, a WABA id and a merchant id are identifiers,
        not credentials - the same reasoning steering applies to the Plivo auth id. It still
        does not belong in a customer response, because it describes our internals.
        """
        return {
            "state": self.state,
            "ready": self.ready,
            "reason": self.reason,
            "configurationName": self.configuration_name,
            "wabaId": self.waba_id,
            "gateway": self.gateway,
            "providerMid": self.provider_mid,
            "checkedConfigurations": self.checked_configurations,
        }

    def customer_message(self) -> str:
        """What a shopper may be told. One string for every blocking state, on purpose.

        Distinguishing the causes here would leak our configuration state to anyone who can
        open the checkout page, and none of the distinctions are actionable by a customer.
        """
        if self.ready:
            return ""
        return ("WhatsApp payment is temporarily unavailable. "
                "Please try again shortly or contact support.")

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"PaymentReadiness({self.state}, {self.reason!r})"


def _blocked(state: str, reason: str, **detail: Any) -> PaymentReadiness:
    logger.warning(
        '{"event":"payment_readiness_blocked","state":"%s","reason":"%s"}', state, reason
    )
    return PaymentReadiness(state, reason, **detail)


def evaluate(*,
             expected_waba_id: str,
             expected_configuration_name: str,
             expected_provider_mid: str,
             fetch_configurations: Callable[[str], Any],
             expected_gateway: str = EXPECTED_GATEWAY) -> PaymentReadiness:
    """Decide whether a payment may be initiated, from a live readback only.

    `fetch_configurations(waba_id)` must perform the live
    `GET /{waba-id}/payment_configurations` and return the parsed response. It is injected
    rather than called directly so this module holds no AWS or Meta client, stays unit-testable
    without network access, and cannot be tempted into reading a credential.

    Any exception from it yields `META_UNAVAILABLE`: an unreachable provider is indistinguishable
    from a misconfigured one from here, and both must block.

    `expected_provider_mid` is required. Passing an empty value yields
    `CONFIGURATION_UNVERIFIED` rather than skipping the check, because "we did not compare the
    merchant id" must never read the same as "the merchant id matched".
    """
    if str(os.environ.get(_KILL_SWITCH, "")).strip().lower() in ("1", "true", "yes", "on"):
        return _blocked(CONFIGURATION_UNVERIFIED,
                        f"{_KILL_SWITCH} is set; payments are administratively disabled")

    if not expected_waba_id:
        return _blocked(CONFIGURATION_UNVERIFIED, "no expected WABA id was supplied")
    if not expected_configuration_name:
        return _blocked(CONFIGURATION_UNVERIFIED,
                        "no expected payment configuration name was supplied")
    if not expected_provider_mid:
        # Deliberately not a pass. The MID is the only thing tying the Meta configuration to
        # the Razorpay account we hold credentials for; without it, a configuration could point
        # at a different merchant and the money would land there.
        return _blocked(CONFIGURATION_UNVERIFIED,
                        "no expected Razorpay merchant id was supplied, so the configuration "
                        "cannot be proven to point at our account")

    try:
        response = fetch_configurations(expected_waba_id)
    except Exception as error:  # noqa: BLE001 - any failure to read must block
        return _blocked(META_UNAVAILABLE,
                        f"could not read payment configurations: {type(error).__name__}")

    if not isinstance(response, dict):
        return _blocked(META_UNAVAILABLE, "payment configuration readback was not an object")
    if response.get("error"):
        return _blocked(META_UNAVAILABLE, "Meta returned an error for payment_configurations")

    configurations = response.get("data")
    if configurations is None:
        # An absent `data` key is not an empty list. One means Meta did not answer the question,
        # the other means it answered "none" - and reporting a missing key as MISSING would
        # claim knowledge we do not have.
        return _blocked(META_UNAVAILABLE,
                        "payment configuration readback carried no data field")
    if not isinstance(configurations, list):
        return _blocked(META_UNAVAILABLE, "payment configuration data was not a list")

    names = [str(c.get("configuration_name", "")) for c in configurations
             if isinstance(c, dict)]

    if not configurations:
        # The measured state on 2026-09-30. Restoring it is owner-administrative work in
        # WhatsApp Manager; no application code may create a payment configuration.
        return _blocked(
            PAYMENT_CONFIG_MISSING,
            f"WABA {expected_waba_id} reports zero payment configurations; the name "
            f"{expected_configuration_name!r} exists only in source",
            waba_id=expected_waba_id, checked_configurations=names,
        )

    match = next(
        (c for c in configurations
         if isinstance(c, dict)
         and str(c.get("configuration_name", "")) == expected_configuration_name),
        None,
    )
    if match is None:
        return _blocked(
            PAYMENT_CONFIG_NAME_UNKNOWN,
            f"{expected_configuration_name!r} is not among the configurations Meta reports",
            waba_id=expected_waba_id, checked_configurations=names,
        )

    # Meta returns configurations for the WABA that was asked, so a mismatch here means the
    # response described a different account than the one requested. Checked anyway: it is one
    # comparison, and sending a WABA1 message naming WABA2's configuration fails at Meta rather
    # than at our own validation, which is the expensive way to find out.
    reported_waba = str(match.get("waba_id") or match.get("wabaId") or expected_waba_id)
    if reported_waba != expected_waba_id:
        return _blocked(
            PAYMENT_CONFIG_WABA_MISMATCH,
            "the configuration belongs to a different WABA than the sender",
            configuration_name=expected_configuration_name,
            waba_id=reported_waba, checked_configurations=names,
        )

    status = str(match.get("status", "")).strip().lower()
    if status != _ACTIVE_STATUS:
        return _blocked(
            PAYMENT_CONFIG_INACTIVE,
            f"configuration status is {status or 'unknown'!r}, not {_ACTIVE_STATUS!r}",
            configuration_name=expected_configuration_name,
            waba_id=expected_waba_id, checked_configurations=names,
        )

    # Meta's live `payment_configurations` edge reports the gateway as flat sibling fields
    # `provider_name`/`provider_mid` on the configuration itself (measured 2026-10-08:
    # provider_name="Razorpay", provider_mid="acc_TTFSyolquKEZEy", status="Active"). The older
    # nested `payment_gateway: {type, merchant_id}` shape is still accepted as a fallback so a
    # future response shape change does not silently drop the MID check.
    gateway_block = match.get("payment_gateway")
    if match.get("provider_name") or match.get("provider_mid"):
        gateway = str(match.get("provider_name", "")).strip().lower()
        reported_mid = str(match.get("provider_mid", "")).strip()
    elif isinstance(gateway_block, dict):
        gateway = str(gateway_block.get("type", "")).strip().lower()
        reported_mid = str(gateway_block.get("merchant_id", "")).strip()
    else:
        gateway = str(gateway_block or "").strip().lower()
        reported_mid = ""

    if gateway != expected_gateway:
        return _blocked(
            PAYMENT_CONFIG_INACTIVE,
            f"gateway is {gateway or 'unknown'!r}, not {expected_gateway!r}",
            configuration_name=expected_configuration_name,
            waba_id=expected_waba_id, gateway=gateway, checked_configurations=names,
        )

    if not reported_mid:
        return _blocked(
            CONFIGURATION_UNVERIFIED,
            "Meta reported no merchant id for this configuration, so it cannot be proven to "
            "point at our Razorpay account",
            configuration_name=expected_configuration_name,
            waba_id=expected_waba_id, gateway=gateway, checked_configurations=names,
        )

    if reported_mid != expected_provider_mid:
        # The conflict this module was written for. Two MIDs appear in the repo; whichever is
        # correct, a disagreement between Meta's configuration and our credentialled account
        # means payments would settle into an account we are not reconciling against.
        return _blocked(
            RAZORPAY_MID_MISMATCH,
            "the configuration's merchant id does not match the Razorpay account this "
            "deployment holds credentials for",
            configuration_name=expected_configuration_name,
            waba_id=expected_waba_id, gateway=gateway,
            provider_mid=reported_mid, checked_configurations=names,
        )

    logger.info(
        '{"event":"payment_readiness_ready","wabaId":"%s","configuration":"%s"}',
        expected_waba_id, expected_configuration_name,
    )
    return PaymentReadiness(
        PAYMENT_READY, "live readback confirms an active Razorpay configuration",
        configuration_name=expected_configuration_name, waba_id=expected_waba_id,
        gateway=gateway, provider_mid=reported_mid, checked_configurations=names,
    )


def evaluate_for_delivery(*,
                          last_inbound_at: Optional[int],
                          payment_template_name: str = "",
                          fetch_templates: Optional[Callable[[str], Any]] = None,
                          now: Optional[int] = None,
                          **account) -> PaymentReadiness:
    """Account readiness **plus** whether a payment request can reach *this* customer.

    Split from `evaluate` deliberately, because the two answer different questions and merging
    them made one of them impossible to ask.

    `evaluate` is account-level: is the configuration present, active, on the right WABA, and
    pointing at our merchant account? Nothing about it depends on a customer.

    This is per-send: the customer's 24-hour service window may be shut, in which case a
    free-form `order_details` is undeliverable and an approved ORDER_DETAILS template is required
    instead. A closed window is not a misconfiguration — it is the normal state of most customers
    most of the time.

    The first attempt at this had `evaluate` take `last_inbound_at=None` as a default, which made
    "no window information supplied" indistinguishable from "window closed", and so made
    `PAYMENT_READY` unreachable for an account-level check. Two functions is the honest shape:
    neither can silently skip something that applies to it.

    `last_inbound_at` is required rather than defaulted, for the same reason.
    """
    verdict = evaluate(**account)
    if not verdict.ready:
        return verdict

    if not template_required(last_inbound_at, now=now):
        # Window open: a free-form interactive order_details is deliverable, no template needed.
        return verdict

    waba_id = verdict.waba_id

    if not payment_template_name:
        return _blocked(
            PAYMENT_TEMPLATE_MISSING,
            "the customer's 24-hour service window is closed and no ORDER_DETAILS template "
            "name is configured, so a payment request cannot be delivered",
            configuration_name=verdict.configuration_name, waba_id=waba_id,
            gateway=verdict.gateway, provider_mid=verdict.provider_mid,
        )

    if fetch_templates is None:
        # Not a pass. Measured live 2026-09-30, this WABA holds exactly one template —
        # `wecare_otp` — and no `wecare_pay`. A configured name proves nothing about what Meta
        # has approved, which is the same mistake as trusting a configuration constant.
        return _blocked(
            CONFIGURATION_UNVERIFIED,
            f"template {payment_template_name!r} is configured but was not verified against "
            "Meta; a configured name is not an approved template",
            configuration_name=verdict.configuration_name, waba_id=waba_id,
            gateway=verdict.gateway, provider_mid=verdict.provider_mid,
        )

    try:
        approved = _approved_template_names(fetch_templates(waba_id))
    except Exception as error:  # noqa: BLE001
        return _blocked(META_UNAVAILABLE,
                        f"could not read templates: {type(error).__name__}")

    if payment_template_name not in approved:
        return _blocked(
            PAYMENT_TEMPLATE_MISSING,
            f"template {payment_template_name!r} is not APPROVED on this WABA "
            f"(approved: {sorted(approved) or 'none'})",
            configuration_name=verdict.configuration_name, waba_id=waba_id,
            gateway=verdict.gateway, provider_mid=verdict.provider_mid,
        )

    return verdict


def _approved_template_names(response: Any) -> set:
    """The set of APPROVED template names from a Graph template readback.

    Only `APPROVED` counts. `PENDING`, `REJECTED`, `PAUSED` and `DISABLED` are all names that
    exist but cannot be sent, and treating "the name came back" as "the template works" is the
    same class of error as treating a local constant as provider state.
    """
    if isinstance(response, dict):
        items = response.get("templates") or response.get("data") or []
    elif isinstance(response, list):
        items = response
    else:
        raise ValueError("template readback was neither an object nor a list")

    return {
        str(item.get("name", ""))
        for item in items
        if isinstance(item, dict)
        and str(item.get("status", "")).strip().upper() == "APPROVED"
        and item.get("name")
    }


def require_ready(readiness: PaymentReadiness) -> None:
    """Raise unless payments may be initiated.

    For call sites that would otherwise write `if readiness.ready:` and forget the else. The
    exception carries the operator reason; the customer-facing string comes from
    `customer_message()` and is deliberately not in the message.
    """
    if not readiness.ready:
        raise PaymentNotReady(readiness)


class PaymentNotReady(RuntimeError):
    """Payments are not currently possible. Carries the verdict for logging."""

    def __init__(self, readiness: PaymentReadiness) -> None:
        super().__init__(f"{readiness.state}: {readiness.reason}")
        self.readiness = readiness


__all__ = [
    "PAYMENT_READY",
    "PAYMENT_CONFIG_MISSING",
    "PAYMENT_CONFIG_INACTIVE",
    "PAYMENT_CONFIG_WABA_MISMATCH",
    "PAYMENT_CONFIG_NAME_UNKNOWN",
    "RAZORPAY_MID_MISMATCH",
    "META_UNAVAILABLE",
    "RAZORPAY_UNAVAILABLE",
    "CONFIGURATION_UNVERIFIED",
    "BLOCKING_STATES",
    "ALL_STATES",
    "EXPECTED_GATEWAY",
    "RAZORPAY_ACCOUNT_UNVERIFIED",
    "PAYMENT_TEMPLATE_MISSING",
    "CUSTOMER_SERVICE_WINDOW_SECONDS",
    "PaymentReadiness",
    "PaymentNotReady",
    "evaluate",
    "evaluate_for_delivery",
    "window_is_open",
    "template_required",
    "require_ready",
]
