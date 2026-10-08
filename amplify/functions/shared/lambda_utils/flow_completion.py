"""One idempotent Flow completion writer. The claim is the row, and it gates the money.

What was measured, 2026-09-22
-----------------------------
Four separate writers into `FlowSubmissionTable`, in two different Lambdas, writing two
different row shapes, and only two of the four guarded:

    flows/common.save_flow_submission          put_item, no condition   9 flows use it
    whatsapp-business-api._save_flow_submission put_item, no condition
    flows/postpay.handle_submit                attribute_not_exists ✅  key from token
    inbound._handle_postpay_submission         attribute_not_exists ✅  key from request id

Update, 2026-09-24: three writers, all guarded. `flows/common.save_flow_submission`
now claims through `claim_completion` below. The second one in that table,
`whatsapp-business-api._save_flow_submission`, turned out to have **zero callers** -
verified with an AST pass over `amplify/`, not a grep - and was deleted rather than
guarded, because wiring it up would have been a two-line change reintroducing exactly
the duplicate-payment-link bug this module was written to prevent. It is still named
above because this table is the record of what was measured; the removal note lives at
its old site in that handler.

And the encrypted `/flow-data` endpoint - the transport for every one of those 9 flows -
has no deduplication of any kind. It cannot key on a `wamid` because the Meta Flows
data-exchange callback does not carry one. So:

* Meta retries a slow or non-200 `data_exchange` POST.
* `_handle_flow_data` catches a routing exception and returns **HTTP 200** with an error
  body, so a half-committed completion reports success - and a timeout *after* the writes
  landed reports failure and invites a retry.
* `flows/submit_request.py` self-invokes with `InvocationType='Event'`, whose own
  at-least-once retry can re-run payment independently of Meta.
* A handset re-tapping the terminal CTA re-enters the same completion handler.

What a single duplicated paid `submit_request` completion produced:

    2 FlowSubmission rows (different random ids)
    2 invoices
    2 payment links sent to the customer      <- money, and invisible to us
    2 confirmation messages
    2 flow_log rows, 2 status-history rows

The missing primitive was a **deterministic completion key**. Only postpay had one,
because the Razorpay webhook mints its token deterministically. Every other flow token is
`{prefix}-{uuid4}-waba-{n}-ph-{phone}` - minted at send time, never persisted, so there
was no stable value to key on.

The key: (flow_token, screen), deliberately coarse
--------------------------------------------------
A flow token is issued per Flow *message*. One token, one completion. That is the rule
this module enforces, and choosing it over a finer key is the central decision here.

The finer alternative was `(flow_token, screen, hash(form_data))`, which would treat a
re-submission with different answers as a new request. It was rejected on which error is
worse:

* **Merging two genuine submissions** loses the second request. The customer chases it, a
  human sees it, it gets fixed. Visible and recoverable.
* **Splitting one retry into two** sends a second invoice and a second payment link. That
  is money, and nothing in the system reports it - we would learn from the customer.

So the key is coarse on purpose. If a customer genuinely wants a second request they tap
the menu again and receive a **new flow token**, which is a new completion. Nothing is
permanently blocked; the second attempt simply has to come through the front door.

`screen` is part of the key because a multi-screen flow can have more than one terminal
screen, and a data-exchange on a different screen is a different event rather than a
replay. Meta's retry resends the same action and screen, so it still collapses.

Empty token: degrade, do not merge
----------------------------------
With no token, hashing `''` would give **every** tokenless completion the same key and
merge unrelated customers' submissions into one row. That is far worse than no
idempotency. So a missing token falls back to hashing the form data, which still collapses
a byte-identical retry, and the result is flagged `degraded` so it is visible in logs.
`lambda_utils.crm.keys` took the same decision for the same reason.

The reference number *is* the key
---------------------------------
`submissionId` doubles as the customer-facing reference ("Request No: WD-SR-A1B2C3D4"), so
it cannot become a hash. Instead the human-readable form is **derived** from the key:

    WD-SR-{key_digest[:8].upper()}

Deterministic, still readable, and it means the conditional put on `submissionId` is the
idempotency guard - no second table, no extra round trip, and the durable business row is
the arbiter rather than a TTL'd dedup entry.

Why not `webhook_dedup.claim_event` alone
-----------------------------------------
`claim_event` **fails open** by design: dropping a real inbound webhook is worse than
processing it twice. `lambda_utils/pstn/__init__.py` already records that this trade
inverts when the side effect is messaging a customer. A Flow completion creates invoices
and sends payment links, so a fail-open claim is a filter, not an arbiter. The
conditional put on the durable row is the arbiter; `claim_event` is not used here at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - present in every Lambda runtime
    boto3 = None
    ClientError = Exception

from lambda_utils.logging import get_logger

logger = get_logger(__name__)

FLOW_SUBMISSIONS_TABLE = os.environ.get(
    'FLOW_SUBMISSIONS_TABLE', 'stack-wecare-digital-FlowSubmissionTable')

#: 128 bits of SHA-256, hex. Not a secret - a collision-resistant identifier.
_DIGEST_CHARS = 32

#: The customer-facing reference keeps 8 hex characters, uppercased. 32 bits over the
#: submissions of one flow prefix. Confirmed collisions use the full digest below.
_REFERENCE_CHARS = 8

#: One year, matching what `save_flow_submission` already wrote. Long enough to answer a
#: dispute, and it is the transport record - the CRM lead created alongside never expires.
DEFAULT_TTL_SECONDS = 365 * 86400


class CompletionKeyDegraded(Warning):
    """Marker type for the no-token fallback. Never raised; used for grep-ability."""


@dataclass
class CompletionResult:
    """The outcome of claiming a completion.

    `created` is the only value on which a caller may fire a side effect. It is a separate
    field rather than something inferred from `item` because the previous
    `save_flow_submission` returned the item on success and `{}` on failure, which gave
    callers no way to distinguish "written" from "already there" - so all nine of them
    proceeded to send confirmations either way.
    """

    status: str                      # 'created' | 'duplicate' | 'error'
    submission_id: str
    reference: str
    key: str
    item: Dict[str, Any] = field(default_factory=dict)
    degraded: bool = False
    error: str = ''

    @property
    def created(self) -> bool:
        return self.status == 'created'

    @property
    def duplicate(self) -> bool:
        return self.status == 'duplicate'

    @property
    def should_fire_side_effects(self) -> bool:
        """Only a fresh claim may send a message, create an invoice or charge anything.

        `error` is included in the refusal deliberately. If the claim could not be written
        we do not know whether a previous attempt already fired, and sending a second
        payment link on a guess is the failure this module exists to prevent. A missing
        confirmation gets chased; a duplicate invoice does not.
        """
        return self.status == 'created'


def _digest(*parts: str) -> str:
    """Stable digest with a separator that cannot appear in the parts we hash.

    `\\x1f` rather than `:` or `-`: a flow token is full of hyphens, and joining on one
    would make ``('a-b', 'c')`` and ``('a', 'b-c')`` collide. Cheap to prevent.
    """
    joined = '\x1f'.join(str(p) for p in parts)
    return hashlib.sha256(joined.encode('utf-8')).hexdigest()[:_DIGEST_CHARS]


def _canonical(form_data: Optional[Mapping[str, Any]]) -> str:
    """Order-independent serialisation of a form payload.

    `sort_keys` matters: Python dict order follows insertion, and a retry deserialised from
    a differently-ordered JSON body would otherwise hash differently and defeat the
    fallback exactly when it is the only guard available.
    """
    if not form_data:
        return ''
    try:
        return json.dumps(form_data, sort_keys=True, default=str, separators=(',', ':'))
    except Exception:  # noqa: BLE001 - an unserialisable payload must not break the claim
        return repr(sorted((str(k), str(v)) for k, v in dict(form_data).items()))


def completion_key(flow_token: str, screen: str = '',
                   form_data: Optional[Mapping[str, Any]] = None) -> tuple:
    """`(key, degraded)` for one Flow completion.

    `degraded` is True when there was no token and the key had to fall back to the form
    payload. Returned rather than logged here so the caller can record it against its own
    request id, and so this function stays pure and testable.
    """
    token = (flow_token or '').strip()
    screen_name = (screen or '').strip().upper()
    if token:
        return _digest('flow-completion', token, screen_name), False
    return _digest('flow-completion-notoken', screen_name, _canonical(form_data)), True


def reference_for(key: str, prefix: str = 'WD') -> str:
    """The customer-facing reference derived from the key.

    Derived, not random, which is what makes a retry produce the *same* reference number.
    Under the old random scheme a retry gave the customer a second, different request
    number for the same request - so even the human-visible surface disagreed about how
    many requests existed.
    """
    clean = (prefix or 'WD').strip().upper().replace(' ', '')[:12] or 'WD'
    return f'{clean}-{key[:_REFERENCE_CHARS].upper()}'


def _table():
    if boto3 is None:  # pragma: no cover
        raise RuntimeError('boto3 unavailable')
    return boto3.resource(
        'dynamodb', region_name=os.environ.get('AWS_REGION', 'us-east-1')
    ).Table(FLOW_SUBMISSIONS_TABLE)


def _is_condition_failure(exc: Exception) -> bool:
    code = getattr(exc, 'response', {}).get('Error', {}).get('Code')
    if code == 'ConditionalCheckFailedException':
        return True
    # The legacy writers matched on the string, and botocore has been known to surface
    # this through a wrapper; checking both costs nothing and a false negative here means
    # a duplicate invoice.
    return 'ConditionalCheckFailedException' in str(exc)


def claim_completion(*, flow_token: str, screen: str = '',
                     flow_code: str = '', flow_type: str = '',
                     phone: str = '', contact_id: str = '',
                     sender_name: str = '', form_data: Optional[Mapping[str, Any]] = None,
                     reference_prefix: str = 'WD',
                     submission_id: Optional[str] = None,
                     requires_payment: bool = False,
                     payment_amount: int = 0,
                     payment_ref_id: str = '',
                     status: str = 'open',
                     extra: Optional[Mapping[str, Any]] = None,
                     ttl_seconds: int = DEFAULT_TTL_SECONDS,
                     request_id: str = '') -> CompletionResult:
    """Claim a Flow completion exactly once, and report whether this caller won.

    `submission_id` overrides the derived id, for the two postpay paths that already have a
    better key: a Razorpay reference or a service-request id identifies the completion more
    precisely than the token does, and those keys are shared across transports. Passing one
    keeps this the single writer without discarding a stronger key.

    A write failure returns `status='error'`, and `should_fire_side_effects` is False for
    it. The old code swallowed the exception and returned `{}`, and every caller carried on
    to send a payment link against a submission that had not been recorded.
    """
    key, degraded = completion_key(flow_token, screen, form_data)
    reference = reference_for(key, reference_prefix)
    sub_id = (submission_id or '').strip() or reference
    now = int(time.time())

    from decimal import Decimal

    fd = dict(form_data) if isinstance(form_data, Mapping) else {}
    item: Dict[str, Any] = {
        'submissionId': sub_id,
        'flowCode': flow_code,
        'flowType': flow_type,
        'phone': phone,
        'contactId': contact_id or '',
        'senderName': sender_name or '',
        'formData': json.dumps(fd, default=str) if fd else '',
        'submissionNumber': sub_id,
        'flowToken': flow_token,
        # The key is stored so an operator can reconcile a duplicate report against the
        # row that won, without recomputing a hash by hand.
        'completionKey': key,
        'completionKeyDegraded': degraded,
        # Promoted for the existing GSIs on this table.
        'orderId': fd.get('order_id', '') or fd.get('orderId', ''),
        'subject': fd.get('subject', ''),
        'description': fd.get('description', ''),
        'requestType': fd.get('request_type', '') or fd.get('requestType', ''),
        'status': status,
        'paymentRequired': requires_payment,
        'paymentAmount': payment_amount if requires_payment else 0,
        'paymentStatus': 'pending' if requires_payment else 'none',
        'paymentRefId': payment_ref_id if requires_payment else '',
        'createdAt': Decimal(str(now)),
        'updatedAt': Decimal(str(now)),
        'ttl': now + int(ttl_seconds),
    }
    if extra:
        for field_name, value in extra.items():
            if field_name not in ('submissionId', 'completionKey'):
                item[field_name] = value

    # `!= ''` matches what the legacy writers did, so the stored shape does not change for
    # any existing reader. `is not None` alone would start persisting empty strings that
    # readers currently treat as absent.
    payload = {k: v for k, v in item.items() if v is not None and v != ''}

    try:
        table = _table()
        table.put_item(
            Item=payload,
            ConditionExpression='attribute_not_exists(submissionId)',
        )
    except Exception as exc:  # noqa: BLE001 - classified immediately below
        if _is_condition_failure(exc):
            # Preserve the legacy ID for ordinary retries. Only a proven collision
            # between full keys gets a deterministic, longer ID. Never rewrite the
            # winner or split explicitly supplied postpay IDs across transports.
            if not submission_id:
                try:
                    existing = table.get_item(
                        Key={'submissionId': sub_id}, ConsistentRead=True,
                    ).get('Item') or {}
                    existing_key = existing.get('completionKey')
                    if existing_key and existing_key != key:
                        collision_id = f'{reference}-{key[_REFERENCE_CHARS:].upper()}'
                        collision = claim_completion(
                            flow_token=flow_token, screen=screen, flow_code=flow_code,
                            flow_type=flow_type, phone=phone, contact_id=contact_id,
                            sender_name=sender_name, form_data=form_data,
                            reference_prefix=reference_prefix, submission_id=collision_id,
                            requires_payment=requires_payment, payment_amount=payment_amount,
                            payment_ref_id=payment_ref_id, status=status, extra=extra,
                            ttl_seconds=ttl_seconds, request_id=request_id,
                        )
                        collision.reference = collision_id
                        return collision
                    if not existing:
                        raise RuntimeError('Completion winner unavailable after conditional failure')
                except Exception as read_error:  # fail closed on an uncertain claim
                    logger.error(json.dumps({'event': 'flow_completion_collision_check_failed',
                                             'submissionId': sub_id,
                                             'errorType': type(read_error).__name__}))
                    return CompletionResult(status='error', submission_id=sub_id,
                                            reference=reference, key=key, degraded=degraded,
                                            error='Completion collision check unavailable')
            logger.info(json.dumps({
                'event': 'flow_completion_duplicate',
                'submissionId': sub_id, 'flowCode': flow_code,
                'completionKey': key, 'degraded': degraded,
                'requestId': request_id,
            }))
            return CompletionResult(status='duplicate', submission_id=sub_id,
                                    reference=reference, key=key, degraded=degraded)
        logger.error(json.dumps({
            'event': 'flow_completion_claim_failed',
            'submissionId': sub_id, 'flowCode': flow_code,
            'error': str(exc)[:200], 'requestId': request_id,
        }))
        return CompletionResult(status='error', submission_id=sub_id, reference=reference,
                                key=key, degraded=degraded, error=str(exc)[:200])

    if degraded:
        # Worth a warning rather than an info: it means a flow reached completion with no
        # token, so idempotency is only as good as byte-identical retries.
        logger.warning(json.dumps({
            'event': 'flow_completion_key_degraded',
            'submissionId': sub_id, 'flowCode': flow_code, 'screen': screen,
            'requestId': request_id,
        }))

    logger.info(json.dumps({
        'event': 'flow_completion_claimed',
        'submissionId': sub_id, 'flowCode': flow_code,
        'completionKey': key, 'requiresPayment': requires_payment,
        'paymentAmount': payment_amount, 'requestId': request_id,
    }))
    return CompletionResult(status='created', submission_id=sub_id, reference=reference,
                            key=key, item=payload, degraded=degraded)


def capture_crm_lead(result: CompletionResult, *, contact_id: str,
                     flow_token: str = '', subject: str = '',
                     detail: str = '', phone: str = '', name: str = '',
                     email: str = '', amount_paise: Optional[int] = None,
                     channel: str = 'WHATSAPP',
                     request_id: str = '') -> Dict[str, Any]:
    """Mirror a fresh completion into the CRM as a lead. Best-effort, never fatal.

    Wrapped in a broad except on purpose. `crm.service.capture_lead` raises when no default
    pipeline has been provisioned, and a Flow completion must not fail because the CRM is
    not set up - the FlowSubmission row is the system of record for the submission itself.
    The lead is a projection of it and can be backfilled.

    Only called for `created`. A duplicate completion has already produced its lead, and
    `crm.store.capture_lead` would refuse it anyway - its `leadId` hashes the same
    `(SOURCE_FLOW, flow_token)`. Two independent guards pointing the same way, which is
    the intent, not redundancy: this one keeps the CRM clean if the submissions table is
    ever repaired or replayed by hand.
    """
    if not result.created or not contact_id:
        return {'outcome': 'skipped'}
    try:
        from lambda_utils.crm import keys as crm_keys
        from lambda_utils.crm import service as crm_service

        outcome = crm_service.capture_lead(
            contact_id=contact_id,
            source=crm_keys.SOURCE_FLOW,
            # The token, not the submission id: the token is what the CRM layer already
            # documents as single-use, and it keeps the lead's identity stable even if a
            # submission is re-keyed.
            source_ref=flow_token or result.key,
            subject=subject or None,
            detail=detail or None,
            phone=phone or None,
            name=name or None,
            email=email or None,
            amount_paise=amount_paise,
            channel=channel,
        )
        logger.info(json.dumps({
            'event': 'flow_completion_lead_captured',
            'outcome': outcome.get('outcome'),
            'leadId': (outcome.get('lead') or {}).get('leadId', ''),
            'submissionId': result.submission_id, 'requestId': request_id,
        }))
        return outcome
    except Exception as exc:  # noqa: BLE001 - CRM must never break a completion
        logger.warning(json.dumps({
            'event': 'flow_completion_lead_skipped',
            'reason': str(exc)[:200],
            'submissionId': result.submission_id, 'requestId': request_id,
        }))
        return {'outcome': 'error', 'reason': str(exc)[:200]}
