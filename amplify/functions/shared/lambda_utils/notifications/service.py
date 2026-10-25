"""The single entry point producers call. One dispatch owner, by construction.

    handle_connected_call(params_or_event) -> dict

Everything a producer needs is behind this one function, and the only way to reach
it with a Plivo callback is through the adapter in ``events.py``. That is what makes
"exactly one dispatch owner" a property of the code rather than a rule somebody has
to remember: a handler cannot invent a trigger, cannot choose a recipient, and
cannot skip the claim, because it never touches any of those steps.

Order of operations, and why this order
---------------------------------------
::

    1. verify the provider signature        caller's job, before reaching here
    2. normalize + validate the trigger     events.py, fail closed
    3. suppression / watermark check        suppression.py, fail closed
    4. feature flag                          here, default OFF
    5. decide eligibility per channel        policy.py
    6. claim the call + publish the jobs     store.py, ONE transaction
    7. return; workers do the sending

Step 3 precedes step 6 so a suppressed call leaves no rows behind. Step 4 precedes
step 6 for the same reason: with the flag off nothing is written at all, so the
tables describe what the domain really did rather than what it would have done.

Step 6 being one transaction is the whole exactly-once story. The retired design
claimed, then dispatched, and if the process died between the two the claim survived
as a permanent ``PENDING`` that nothing owned - a notification silently lost, with
the provider's redelivery finding the claim taken and doing nothing. Here the claim
and the job are written together or not at all.

Nothing is sent from this call path
-----------------------------------
`handle_connected_call` publishes work and returns. No provider is contacted inside
the webhook, which matters for two reasons: a synchronous send adds provider latency
to the callback the provider is timing, and a timeout mid-send is the one case where
the claim cannot record what happened. The old RCS path had exactly that problem and
"solved" it by never sending at all.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from lambda_utils.logging import get_logger, log_event

from . import events as events_mod
from . import keys as keys_mod
from . import policy as policy_mod
from . import states as states_mod
from . import store as store_mod
from . import suppression as suppression_mod

logger = get_logger(__name__)

#: OFF by default. Enabling it is a production decision with its own approval, never
#: a deployment side effect.
#:
#: Read at call time, not at import. The module-scope pattern used by the retired
#: `pstn/notifications` froze the value into a warm sandbox, so flipping the variable
#: did not take effect until a new version was published - see
#: `.kiro/steering/lambda-snapstart-deploy.md` (retired 2026-10-09, af7858fa).
FLAG_ENV = "PSTN_CONNECTED_NOTIFICATIONS_ENABLED"


def is_enabled() -> bool:
    """Exact, case-insensitive `'true'` only.

    Strict on purpose: `'1'` and `'yes'` do not enable a path that messages real
    customers.
    """
    return os.environ.get(FLAG_ENV, "").strip().lower() == "true"


def _outcome(claimed: bool, reason: str, event=None, **extra) -> Dict[str, Any]:
    out: Dict[str, Any] = {"claimed": claimed, "reason": reason}
    if event is not None:
        out["event"] = event.as_dict()
    out.update(extra)
    return out


def handle_connected_call(params: Dict[str, Any], *, provider: str = keys_mod.PROVIDER_PLIVO,
                          request_id: str = "",
                          sender_phone_id: str = "") -> Dict[str, Any]:
    """Claim a verified connected call and publish one job per eligible channel.

    `params` is the raw, already-signature-verified provider callback body.

    Returns a dict that always carries `claimed` and `reason`. It raises only
    `store.NotificationStoreUnavailable`, which the caller MUST convert into a
    retryable 5xx without sending anything - the provider will redeliver, so the cost
    of refusing to guess is latency.
    """
    if provider == keys_mod.PROVIDER_PLIVO:
        event, reason = events_mod.from_plivo_dial_callback(params)
    elif provider == keys_mod.PROVIDER_META:
        event, reason = events_mod.from_meta_call_event(params)
    else:
        return _outcome(False, f"unsupported_provider_{provider}")

    if event is None:
        # The overwhelmingly common case: a callback for a state that is not a
        # connection. Logged at info because it is normal traffic, not a fault.
        log_event(logger, "notif_trigger_rejected", provider=provider,
                  reason=reason, requestId=request_id)
        return _outcome(False, reason)

    suppress, suppress_reason = suppression_mod.should_suppress(
        event, request_id=request_id)
    if suppress:
        log_event(logger, "notif_suppressed", reason=suppress_reason,
                  canonicalCallId=event.canonical_call_id, requestId=request_id)
        return _outcome(False, f"suppressed_{suppress_reason}", event)

    if not is_enabled():
        log_event(logger, "notif_domain_disabled",
                  canonicalCallId=event.canonical_call_id, requestId=request_id)
        return _outcome(False, "feature_disabled", event)

    decisions = policy_mod.decide_all(event.external_party,
                                      sender_phone_id=sender_phone_id)

    result = store_mod.claim_event_and_publish(event, decisions,
                                              request_id=request_id)
    if not result.get("claimed"):
        return _outcome(False, result.get("reason", "not_claimed"), event,
                        eventClaimKey=result.get("eventClaimKey"))

    return _outcome(True, "claimed", event,
                    eventClaimKey=result.get("eventClaimKey"),
                    published=result.get("published", []),
                    skipped=result.get("skipped", []),
                    channels={ch: d.as_dict() for ch, d in decisions.items()})


def classify_provider_error(error: Optional[str], error_code: str = "") -> tuple:
    """`(category, is_permanent)` for a send failure.

    Permanent means a retry cannot succeed, so the attempt budget should not be spent
    and the dead-letter signal should be immediate. DLT, destination, validation and
    permission failures are permanent by nature; throttling and timeouts are not.

    An unknown error is classified **transient**. The claim already prevents a retry
    from duplicating a completed send, so the cost of being wrong here is a wasted
    attempt - whereas treating an unknown transient fault as permanent silently drops
    a real notification.
    """
    code = str(error_code or "").strip()
    text = f"{code} {error or ''}".lower()

    permanent_markers = (
        "missing_dlt_template", "unapproved_dlt", "invalid_phone", "invalid phone",
        "validationexception", "accessdenied", "unauthorized", "forbidden",
        "not_registered", "opted_out", "destination", "blocked",
        "prohibited_provider", "template_unverified", "unsupported",
    )
    for marker in permanent_markers:
        if marker in text:
            return (code or marker).upper()[:60], True

    transient_markers = ("throttl", "timeout", "timed out", "unavailable",
                         "serviceexception", "internalserver", "5xx",
                         "connectionerror", "endpointconnectionerror")
    for marker in transient_markers:
        if marker in text:
            return (code or marker).upper()[:60], False

    return (code or "UNKNOWN").upper()[:60], False


def reconciliation_state() -> str:
    """The state to record when a provider may have accepted a send but the response
    was lost.

    Exposed as a function rather than inlined at call sites so that the brief's rule -
    record ``RECONCILIATION_REQUIRED`` and reconcile before resending, never assert
    exactly-once where the provider offers no idempotent send contract - has one
    obvious place to be found.
    """
    return states_mod.RECONCILIATION_REQUIRED


def describe() -> Dict[str, Any]:
    """Configuration summary, safe for a status endpoint. No recipient data."""
    return {
        "enabled": is_enabled(),
        "claimVersion": keys_mod.CONNECTED_NOTIFICATIONS_VERSION,
        "channels": list(keys_mod.SUPPORTED_CHANNELS),
        "tables": store_mod.table_names(),
        "suppression": suppression_mod.describe(),
        "whatsappVerifiedSenders": sorted(policy_mod.wa_verified_senders()),
        "metaTriggerNote": events_mod.META_TRIGGER_NOTE,
    }
