# Payment-integrity closure — technical design

**Produced 2026-10-01 (Asia/Kolkata). First draft; no `design-review.json` existed when this was
written.** Basis: `.agents/tasks/payment-integrity-closure-2026-10-01/audit-reconcile.md` and every
source file it cites, re-read at the baseline below. No credential value, key id or secret appears
in this document. Nothing here deploys.

## 0. Baseline, re-measured for this design

| Item | Value |
|---|---|
| Branch | `stack` |
| HEAD | `43b26d4a5cbec0e62bb3982b67ef4540072929d1` — "Vendor Material ESM components in existing application", 2026-10-01 13:56 +0530 |
| `wecare-razorpay-webhook` `live` alias | **v45** — unchanged, none of this is deployed |
| Focused suite now | `.venv/bin/python -m pytest tests/ -q -k "razorpay or order_creation or order_keys or payment_attempt or payment_vocabulary or payment_reconciliation"` → **20 failed, 295 passed** |
| Index | clean. Every dirty path is unstaged (`git status --short` column 1 is a space) |

**HEAD has moved twice since the audit** (`f7304eba` → `43b26d4a`). The audit's line numbers were
re-derived against this tree before being used below; where they moved, the number in this document
is the current one. Two of the audit's findings are **already closed at HEAD** and are reported as
`SUPERSEDED` in §10 rather than silently re-fixed.

Owned paths (write): `amplify/functions/payments/razorpay-webhook/handler.py`,
`amplify/functions/shared/lambda_utils/ecommerce/{order_creation,finalization,initiation,order_keys,payment_attempt,side_effect_guard}.py`,
`amplify/functions/shared/lambda_utils/integrations/razorpay_verify.py`,
`amplify/functions/shared/lambda_utils/partner_billing.py`,
`amplify/functions/messaging/{inbound-whatsapp-handler,partner-onboarding}/handler.py`,
`amplify/functions/payments/invoice-engine/handler.py` (one line, §R3/N3-b),
`amplify/functions/ecommerce/wix-store/handler.py` (comments only),
new `amplify/functions/shared/lambda_utils/ecommerce/{capture_authority,recovery}.py`,
new `scripts/provision_payment_recovery_table.py`, `scripts/recover_unresolved_payments.py`,
`tests/**`, `config/lambda-env-manifest.json`,
`.kiro/specs/whatsapp-wix-commerce/requirements.md` (one edit, §PON-7).

Never touched: `amplify/functions/ecommerce/checkout/handler.py`, `amplify/functions/auth/**`,
`src/**`, `_routes.json`, `docs/execution/checkout-c1-c7-closure-matrix-20261001.md`,
`docs/execution/change-authority-matrix.md` (append only, at landing time),
`.kiro/steering/META-BETA-REQUEST-EMAIL.md`.

## 1. The invariant, and the one structural idea

Everything below serves one invariant:

> A captured Razorpay payment produces **exactly one** paid internal order and **exactly one** set
> of purchase side effects. No unverified, rejected, ambiguous or unknown event may ever produce a
> financial side effect, and no paid event may ever be lost.

The structural idea is a **three-layer separation** that the current code mixes:

1. **Verification** — did money move, for this amount, bound to this subject? One boundary
   (`capture_authority`), one implementation of each predicate, injected provider reader.
2. **Disposition** — given the verdict, what should the transport do? A closed enumeration
   (`MATERIALIZED` · `NOT_OURS` · `NO_MONEY` · `TRANSIENT` · `PERMANENT`) that decides the HTTP
   status, the dedup lease, the alarm level and whether a recovery row is written. The transport
   never inspects an outcome *name*.
3. **Materialization** — the ordered, individually-guarded, forward-only side effects.

Today layer 2 does not exist: `razorpay-webhook/handler.py:704` routes on the raw string
`'UNKNOWN_REFERENCE'`, and every non-`hasOrder` outcome raises the same exception at `:706`, which
returns 500 and leaves the lease open. That single conflation is the root of §4.2, §4.3 and §4.4 of
the audit. Introducing layer 2 closes all three with one mechanism rather than three patches.

Technology stack is **locked and unchanged**: Python 3.12 Lambda, `boto3` DynamoDB resource API,
`urllib.request` for Razorpay, `pytest` offline with the existing `tests/crm_fake_dynamo.FakeDynamo`.
No new runtime, no new SDK, no new service. This honours decision `D1`.

## 2. Module map

| Module | Change | Why here |
|---|---|---|
| `lambda_utils/ecommerce/capture_authority.py` | **NEW** | The single verification boundary (N1). Pure predicates + one `authorize()`; injected `verify` and injected table, so it holds no AWS client and no credential |
| `lambda_utils/ecommerce/recovery.py` | **NEW** | Durable unresolved intake and the recoverable job (R3/N3). Injected table |
| `lambda_utils/integrations/razorpay_verify.py` | binding becomes mandatory and server-only; new `RazorpayBindingMissing`; status via `payment_status` | C4, R1/C1 classification |
| `lambda_utils/ecommerce/order_creation.py` | outcome taxonomy split; `disposition()`; `BINDING_MISSING`; delegate status/amount predicates | R1/C1, C4 |
| `lambda_utils/ecommerce/payment_attempt.py` | gateway-binding **contract** (names + validator + condition) | C4 |
| `lambda_utils/ecommerce/initiation.py` | `bind_gateway_order()` — the documented seam for the checkout workstream | C4 |
| `lambda_utils/ecommerce/finalization.py` | forward-only stage ladder; stage/blocked split; `record_paid` uses the rank primitive; `side_effect_guard` on every external effect | forward-only-stages |
| `lambda_utils/ecommerce/order_keys.py` | one writer of `PROVIDERPAYMENT#`; stale 12-char comments | R2, public-order-number |
| `lambda_utils/ecommerce/side_effect_guard.py` | two new effects in `KNOWN_EFFECTS` | forward-only-stages, N2 |
| `lambda_utils/partner_billing.py` | `credit_topup_once()` — one atomic, idempotent credit | N2 |
| `payments/razorpay-webhook/handler.py` | disposition routing; legacy provenance; wallet path; recovery intake; internal recovery action | R1/C1, R2, N2, R3/N3 |
| `messaging/inbound-whatsapp-handler/handler.py` | `_process_payment_status` routes through `capture_authority` | N1 |
| `messaging/partner-onboarding/handler.py` | writes the top-up intent before returning a payment link | N2 |
| `payments/invoice-engine/handler.py` | one `in (...)` status gate → rank comparison | R3/N3 gate blind spot |

## 3. R1/C1 — bind the verdict, gate every side effect, classify honestly

### 3.1 The outcome taxonomy, corrected

`order_creation.py` currently returns `UNKNOWN_REFERENCE` for three different facts and uses it as
the legacy-routing signal, and maps a storage failure onto `PROVIDER_UNAVAILABLE`. Both are
corrected by splitting the enumeration. New and changed constants in `order_creation.py`:

```python
# existing, unchanged
ORDER_CREATED = "ORDER_CREATED"
ORDER_ALREADY_EXISTS = "ORDER_ALREADY_EXISTS"
NOT_PAID = "NOT_PAID"
AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
CUSTOMER_MISMATCH = "CUSTOMER_MISMATCH"
ATTEMPT_NOT_PAYABLE = "ATTEMPT_NOT_PAYABLE"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"
PROVIDER_PAYMENT_CONFLICT = "PROVIDER_PAYMENT_CONFLICT"

# NEW — each one is a fact the old UNKNOWN_REFERENCE could not express
NO_REFERENCE_ON_EVENT    = "NO_REFERENCE_ON_EVENT"      # event carries no reference at all
NOT_A_COMMERCE_REFERENCE = "NOT_A_COMMERCE_REFERENCE"   # clean read, no PAYREF row: not ours
UNKNOWN_REFERENCE        = "UNKNOWN_REFERENCE"          # PAYREF row exists but is unusable
ATTEMPT_STORE_UNAVAILABLE = "ATTEMPT_STORE_UNAVAILABLE" # our storage failed, not the provider
BINDING_MISSING          = "BINDING_MISSING"            # structural: no server-stored binding
```

Where each is returned in `reconcile_payment`:

| Condition | Outcome |
|---|---|
| `not reference_id` | `NO_REFERENCE_ON_EVENT` |
| `load_attempt` raises | `ATTEMPT_STORE_UNAVAILABLE` (was `PROVIDER_UNAVAILABLE`) |
| `load_attempt` returns `None` — a clean read, no row | `NOT_A_COMMERCE_REFERENCE` |
| the stored attempt carries no `paymentAttemptId` | `UNKNOWN_REFERENCE` |
| `verify_payment` raises `RazorpayBindingMissing` | `BINDING_MISSING` |
| `verify_payment` raises any other exception | `PROVIDER_UNAVAILABLE` |

`NOT_A_COMMERCE_REFERENCE` is the only outcome that means *not ours*, and it is the only one the
handler may use to consider the legacy path. That single change closes audit §4.2: a lost or lagging
`PAYREF#` row now produces `ATTEMPT_STORE_UNAVAILABLE` or `UNKNOWN_REFERENCE`, both paid-but-blocked,
and can no longer be mistaken for "this is a legacy invoice".

Set membership:

```python
NO_ORDER_OUTCOMES = frozenset({NOT_PAID, ATTEMPT_NOT_PAYABLE})          # money did not move

PAID_BUT_BLOCKED_OUTCOMES = frozenset({                                  # money moved, we refused
    AMOUNT_MISMATCH, CURRENCY_MISMATCH, CUSTOMER_MISMATCH, IDENTITY_UNAVAILABLE,
    PROVIDER_PAYMENT_CONFLICT, UNKNOWN_REFERENCE, NO_REFERENCE_ON_EVENT,
    PROVIDER_UNAVAILABLE, ATTEMPT_STORE_UNAVAILABLE, BINDING_MISSING,
})

#: Can never resolve by retrying. Retrying them is the unbounded-retry defect (audit §4.3).
PERMANENT_OUTCOMES = frozenset({
    AMOUNT_MISMATCH, CURRENCY_MISMATCH, CUSTOMER_MISMATCH,
    PROVIDER_PAYMENT_CONFLICT, UNKNOWN_REFERENCE, NO_REFERENCE_ON_EVENT, BINDING_MISSING,
})

#: Might resolve on its own. Worth a provider retry and an automatic sweep.
TRANSIENT_OUTCOMES = frozenset({
    PROVIDER_UNAVAILABLE, ATTEMPT_STORE_UNAVAILABLE, IDENTITY_UNAVAILABLE,
})
```

`BINDING_MISSING` is in `PAID_BUT_BLOCKED_OUTCOMES`, so `needs_human` is `True`. This is the specific
correction the brief demands: a structural verification failure after a capture is **not** "no money
moved". It is also in `PERMANENT_OUTCOMES`, because no number of retries will make a binding appear.

### 3.2 `disposition()` — the closed enumeration the transport routes on

```python
MATERIALIZED = "MATERIALIZED"   # an order exists. Proceed to finalization.
NOT_OURS     = "NOT_OURS"       # positively not a commerce reference. Legacy MAY be considered.
NO_MONEY     = "NO_MONEY"       # the provider says nothing was captured. Nothing owed.
TRANSIENT    = "TRANSIENT"      # unknown. Retry is correct.
PERMANENT    = "PERMANENT"      # paid and refused, permanently. A human must act.

def disposition(outcome: str) -> str:
    """The transport's routing decision. Total over the outcome enumeration, and it RAISES on an
    unknown outcome rather than defaulting — a new outcome must be classified deliberately, because
    the default would otherwise silently become one of these five.
    """
```

`disposition` raises `ValueError` for an unrecognised outcome, and `tests/test_order_creation.py`
asserts the function is total over every `*_OUTCOMES` member plus `ORDER_CREATED` /
`ORDER_ALREADY_EXISTS` / `RECONCILIATION_ERROR`. A future outcome that nobody classified fails a test
instead of falling through to legacy success.

### 3.3 The call site

`_create_order_for_captured_payment` keeps its current shape (it already binds the outcome at
`handler.py:471` and already returns `outcome.as_dict()`), with one addition: the dict gains
`"disposition": order_creation.disposition(outcome.outcome)` and
`"classification"` (`STRUCTURAL` when `BINDING_MISSING`, else `PERMANENT`/`TRANSIENT`/`NONE`).
Its `except Exception` fallback returns `{'outcome': 'RECONCILIATION_ERROR', 'hasOrder': False,
'disposition': TRANSIENT, 'needsHuman': True}` — a reconciliation we could not even complete is
unknown, not resolved.

`_handle_payment_captured` is restructured so that **no financial side effect is lexically reachable
without a materialized order**. Replacing `handler.py:703-760`:

```python
    verdict = _create_order_for_captured_payment(payment, reference_id, request_id)
    disp = verdict.get('disposition')

    if disp == order_creation.MATERIALIZED:
        _persist_commerce_paid(payment, verdict, request_id)   # the ONLY commerce success path
        return

    if disp == order_creation.NOT_OURS:
        _handle_legacy_capture(payment, reference_id, request_id)
        return

    if disp == order_creation.NO_MONEY:
        logger.info(json.dumps({'event': 'capture_not_paid', 'outcome': verdict['outcome'],
                                'referenceId': reference_id, 'requestId': request_id}))
        return                                   # 200, lease closes, nothing owed, no alarm

    # Paid and refused. Persist BEFORE alarming, so the record survives a crash in the alarm path.
    _record_unresolved(verdict, payment, reference_id, request_id)

    if disp == order_creation.PERMANENT:
        return                                   # 200, lease CLOSES: retrying cannot help

    raise CaptureUnresolved(verdict['outcome'])  # TRANSIENT: 500, lease stays open, provider retries
```

Four properties this buys, each of which was a named finding:

- Every one of `_mark_invoice_paid_by_reference`, `_post_payment_handler` (the GST document),
  `_log_ctwa_purchase` (the Meta Purchase conversion), the `order_status` WhatsApp message and
  `_trigger_post_payment_flow` now lives inside `_handle_legacy_capture`, which is only reachable
  from `NOT_OURS`. The commerce path reaches none of them; it reaches `_persist_commerce_paid` and
  returns. **R1/C1's central requirement is structural, not conditional.**
- `PERMANENT` closes the lease and returns 200, ending the unbounded retry loop of audit §4.3. The
  raw audit row is already written by `_log_webhook_event` (`handler.py:~310`) before any of this, so
  closing the lease loses no evidence.
- `TRANSIENT` keeps today's behaviour, which is correct for it.
- `NO_MONEY` no longer raises. A forged, signature-valid `payment.captured` that the provider
  disowns currently returns 500 and is retried forever; it now returns 200 with one INFO line.

### 3.4 Alarm shape

`PAID_BUT_NO_ORDER` stays as the single staff alarm string, emitted once per delivery from
`_create_order_for_captured_payment` (already at `handler.py:493-495`), with `classification` added so a
CloudWatch metric filter can separate `STRUCTURAL` from `TRANSIENT`. `_record_unresolved` emits a
second, distinct line `payment_recovery_recorded` carrying `recoveryId`, `state` and
`nextAttemptAt` — one alarm, one receipt, no duplication.
`tests/test_razorpay_webhook_captured_gating.py::test_quarantine_emits_a_single_staff_alert` is
updated to assert exactly one alarm **and** exactly one receipt.

Logged fields: `referenceId`, `contactId`, `recoveryId`, `outcome`, `disposition`,
`classification`, `amountPaise`, `requestId`, `type(exc).__name__`. Never: `contact`, `email`,
`description`, `notes`, a provider error body, or any secret. Phone numbers, where a line needs one
at all, go through `lambda_utils.privacy.mask_phone` (last four only, not widened).

## 4. C4 — the stored gateway-binding contract and its seam

### 4.1 Scope, stated plainly

The brief fixes the scope: this workstream owns **the contract, the storage shape in
`payment_attempt.py`, and the verifier**. It does **not** own
`amplify/functions/ecommerce/checkout/handler.py`, which is where a binding must be written at
payment-creation time. So C4 is closed on the storage-and-verifier side and left open on the
caller side by design, with a documented, unit-tested seam for the concurrent workstream.

**Consequence, stated rather than papered over.** Until that workstream calls the seam, every real
capture reaches `BINDING_MISSING` → `PERMANENT` → one `PAID_BUT_NO_ORDER` alarm with
`classification: STRUCTURAL`, a durable recovery row, a closed lease and **no order**. That is
paid-and-loud, which is the correct fail-closed state and strictly better than today's
paid-and-retried-forever, but it is not a working checkout. R3/N3 is therefore not optional
alongside C4: the recovery row is the only thing that makes the gap survivable.

### 4.2 The contract (in `payment_attempt.py`)

```python
#: The pre-capture gateway binding. Written ONCE, at payment creation, by the initiation caller.
#: These are the verifier's INPUT. They are never derived from a webhook body or a browser.
GATEWAY_BINDING_ATTRIBUTES = (
    "providerOrderId",       # Razorpay order id (`order_...`). The authoritative selector.
    "providerPaymentId",     # optional at creation; present only when the flow mints one up front
    "providerAccountId",     # Razorpay account the order was created under
    "providerMode",          # "live" | "test". A test capture must never fund a live order.
    "providerAmountPaise",   # the amount the gateway order was created FOR, integer paise
)

LIVE = "live"
TEST = "test"
_MODES = frozenset({LIVE, TEST})


def gateway_binding(*, provider_order_id: str, provider_account_id: str,
                    provider_mode: str, provider_amount_paise: int,
                    provider_payment_id: str = "") -> Dict[str, Any]:
    """Validate and return the exact attribute map for a gateway binding. Pure.

    Raises `ValueError` on anything that is not a usable binding. The validation is strict at the
    boundary for the same reason `build()` refuses a float amount: a binding that is wrong is worse
    than one that is absent, because an absent binding fails closed and a wrong one verifies the
    wrong payment.

      provider_order_id      non-empty str, <= 64 chars, [A-Za-z0-9_-]
      provider_account_id    non-empty str, <= 64 chars, [A-Za-z0-9_-]
      provider_mode          exactly "live" or "test"
      provider_amount_paise  positive int paise, via money.positive_paise (refuses bool, float,
                             negative, zero, fractional Decimal and > 2**53-1)
      provider_payment_id    optional; same charset rule when present
    """


def binding_condition_expression() -> str:
    """Write-once guard for the binding.

    `attribute_not_exists(providerOrderId) OR providerOrderId = :providerOrderId`

    Idempotent rather than exclusive on purpose: the initiation caller may legitimately retry its
    own write after an uncertain response, and that retry carries the same order id. A DIFFERENT
    order id on an attempt that already has one is a conflict and must fail, because it would
    re-point a payment attempt at another gateway order.
    """
```

**Deliberate divergence from the audit's recommendation.** The audit (§3, `finalization.py` rework 1)
says to unify `verifiedProviderPaymentId` with `providerPaymentId` — "one name only". This design
keeps both, because they are two different facts and collapsing them would be circular:

| Attribute | Written by | Means |
|---|---|---|
| `providerOrderId` / `providerPaymentId` | the initiation caller, **before** capture | what we asked the gateway to charge. Verification **input** |
| `verifiedProviderPaymentId` | `finalization.record_paid`, **after** an authenticated readback | what the gateway confirmed it charged. Verification **output** |

If the verifier read `verifiedProviderPaymentId`, it would be using its own output as its input, and
a single unverified write to that attribute would authorise every subsequent capture. So the two names
stay, the asymmetry is documented in both files, and
`tests/test_razorpay_binding.py::test_the_verifier_never_reads_its_own_output` pins it by AST:
`razorpay_verify.py` must contain no reference to the string `verifiedProviderPaymentId`.

### 4.3 The seam (in `initiation.py`)

```python
def bind_gateway_order(attempts, *, payment_attempt_id: str, reference_id: str,
                       provider_order_id: str, provider_account_id: str,
                       provider_mode: str, provider_amount_paise: int,
                       provider_payment_id: str = "", now=None) -> None:
    """Record the gateway binding on an existing payment attempt. Call this IMMEDIATELY after the
    gateway accepts the order and BEFORE any payable message or redirect reaches the customer.

    This is the only supported writer of `payment_attempt.GATEWAY_BINDING_ATTRIBUTES`. Nothing
    verifies a capture without it: `razorpay_verify.verifier_for_event` raises
    `RazorpayBindingMissing` when the attempt carries no `providerOrderId`, which classifies as
    BINDING_MISSING / STRUCTURAL and produces a paid-but-no-order alarm. So an initiation path that
    skips this call does not fail at initiation — it fails after the customer has paid, which is the
    expensive place to find out.

    Idempotent for the same order id; raises `InitiationConflict` for a different one.

    Args:
      attempts: a DynamoDB Table resource for `payment_attempt.table_name()`. Injected, so this
        module still holds no AWS client.
      payment_attempt_id: the attempt created by `reserve()` or by the checkout handler.
      reference_id: asserted in the ConditionExpression, so a mismatched pair cannot bind.
      provider_order_id: the gateway's own order id, from the gateway's response. NOT from a
        request body, a query string or a webhook.
      provider_amount_paise: integer paise, as sent to the gateway. Compared exactly at capture.

    Raises:
      ValueError            the binding failed `payment_attempt.gateway_binding` validation
      InitiationConflict    the attempt already carries a DIFFERENT provider order id
      InitiationUnavailable the attempt does not exist, the reference disagrees, or storage failed
    """
```

Implementation: one `update_item` with
`ConditionExpression = 'attribute_exists(paymentAttemptId) AND referenceId = :ref AND (' +
payment_attempt.binding_condition_expression() + ')'`. On `ConditionalCheckFailedException` it
re-reads with `ConsistentRead=True` and distinguishes the three causes, so the caller receives the
right exception rather than a generic failure. **No `ConditionCheck` transaction item** — the audit
measured `dynamodb:ConditionCheckItem` as `implicitDeny` on `wecare-digital-lambda-role`, and a
denial there would surface as a transaction failure nobody was expecting.

Not wired into any initiation path by this workstream. Tested by
`tests/test_gateway_binding_seam.py` against `FakeDynamo`: first write succeeds; identical replay is
a no-op; different order id raises `InitiationConflict`; missing attempt raises
`InitiationUnavailable`; a float / negative / zero / fractional amount raises `ValueError`; a
mismatched `reference_id` raises `InitiationUnavailable`. The fixture doubles as the caller's
reference example.

### 4.4 The verifier

`razorpay_verify.verifier_for_event` changes in four ways:

```python
class RazorpayBindingMissing(RazorpayUnavailable):
    """The attempt carries no server-stored gateway binding, so there is nothing to verify AGAINST.

    A subclass of RazorpayUnavailable so every existing `except RazorpayUnavailable` site keeps
    behaving, while `order_creation` can classify this one as STRUCTURAL rather than as an outage.
    """
```

1. **Only a server-stored id may select the payment.** The current `target = bound_payment or
   payment_id` lets an event-supplied payment id select the payment whenever the attempt has no
   stored payment id. That line goes. The selector is `bound_payment or bound_order`, and
   `providerOrderId` is required — `bound_payment` alone is not sufficient, because the order id is
   what the gateway binds an account and an amount to.
2. `RazorpayBindingMissing` replaces the generic raise at the no-binding branch.
3. **Account, mode and amount are compared** against the stored binding, in that order, before the
   capture is accepted: `payment['account_id']` vs `providerAccountId` (skipped with an INFO line if
   the provider response omits the field — see §11 U-3), `payment` liveness vs `providerMode`, and
   `positive_paise(payment['amount'])` vs `providerAmountPaise`. Any mismatch raises
   `RazorpayUnavailable` with a reason naming the field and no value.
4. **Status goes through the vocabulary.** `status == CAPTURED` becomes
   `payment_status.canonical(payment.get('status')) == payment_status.CAPTURED`, and a status whose
   rank *exceeds* `CAPTURED` (`refunded`, `disputed`) raises rather than reporting paid — a refunded
   payment was captured, and treating it as fundable is how a refund becomes an order.

`payment_is_captured` and `order_is_paid` get the same `canonical()` treatment. The module constant
`CAPTURED = "captured"` is retained for back-compatibility but is redefined as
`CAPTURED = payment_status.CAPTURED`, so there is one source of the word.

## 5. N1 — one verification boundary, and the retained producers that must use it

### 5.1 The boundary module

`lambda_utils/ecommerce/capture_authority.py`. It holds no AWS client, no credential, and no provider
knowledge: the authenticated read is injected, the claim table is injected.

```python
STRUCTURAL = "STRUCTURAL"   # no server-stored binding. Retrying cannot help.
VERIFIED   = "VERIFIED"
NOT_PAID   = "NOT_PAID"
MISMATCH   = "MISMATCH"     # paid, but not for this subject/amount/currency
CONFLICT   = "CONFLICT"     # this provider payment already funds a different subject
UNAVAILABLE = "UNAVAILABLE" # we could not ask, or could not claim. Unknown.

#: A payment may fund at most one of these, ever, across all channels.
SUBJECT_COMMERCE_ORDER = "COMMERCE_ORDER"
SUBJECT_LEGACY_INVOICE = "LEGACY_INVOICE"
SUBJECT_WALLET_TOPUP   = "WALLET_TOPUP"
SUBJECT_KINDS = frozenset({SUBJECT_COMMERCE_ORDER, SUBJECT_LEGACY_INVOICE, SUBJECT_WALLET_TOPUP})


class CaptureAuthority:
    """The verdict. `allowed` is True only when all five obligations below were met."""
    __slots__ = ("allowed", "classification", "provider_payment_id", "amount_paise",
                 "currency", "reason", "claim_owner")


def status_is_captured(raw_status) -> bool:
    """Captured, and not past it. The ONE implementation of this question.

    `payment_status.canonical(raw) == payment_status.CAPTURED`. Deliberately an equality on the
    canonical form and not `rank >= CAPTURED`: `refunded` and `disputed` outrank `captured`, and
    both mean the money is not ours to fund anything with.
    """


def amounts_match(provider_amount, expected_amount) -> bool:
    """Exact equality of two integer-paise values, both through `money.positive_paise`.

    One paise is a mismatch and fails closed. No float, no epsilon, no rounding. Raises ValueError
    if either side is not usable integer paise — an uncomparable amount is a refusal, never a pass.
    """


def authorize(*, channel: str, subject_kind: str, subject_id: str,
              stored_binding: Dict[str, Any], verify: Callable[[], Dict[str, Any]],
              expected_amount_paise: Any, expected_currency: str,
              claim_table: Any, key_attr: str = "orderId") -> CaptureAuthority:
    """The single authoritative gate. Five obligations, in this fixed order:

      1. A server-stored binding exists. `stored_binding` must carry a provider order id (or, for a
         channel that has none, the channel's own stored binding token). Absent -> STRUCTURAL.
         Browser-supplied, event-supplied and `notes`-supplied values are NOT a binding; a caller
         passing one is a bug the docstring names so a reviewer can see it.
      2. `verify()` is called. It must perform an AUTHENTICATED read from the provider and return
         the provider's own record. Any exception -> UNAVAILABLE (unknown, retry).
      3. `status_is_captured` on the provider's status -> else NOT_PAID.
      4. `expected_currency` compared explicitly (`"INR"`, never inferred from an amount), then
         `amounts_match` -> else MISMATCH.
      5. `order_keys.claim_provider_payment` for (subject_kind, subject_id). Lost to a DIFFERENT
         subject -> CONFLICT. Lost to the SAME subject -> allowed (idempotent re-entry).
         A storage error -> UNAVAILABLE: "I cannot prove this has not already been funded" must
         mean "do not fund it".

    Ordered so the cheapest refusals come first and the claim — the only write — comes last, after
    every reason to refuse has been exhausted.
    """
```

The claim is the mechanism that makes the guarantee cross-channel: one `PROVIDERPAYMENT#<id>` key
namespace on the commerce-keys table, so a payment cannot fund a commerce order **and** a legacy
invoice **and** a wallet top-up. To keep that to one writer, `order_keys` gains:

```python
def claim_provider_payment(table, *, provider_payment_id: str, subject_kind: str, subject_id: str,
                           key_attr: str = "orderId", extra=None) -> Tuple[Dict[str, Any], bool]:
    """Claim `PROVIDERPAYMENT#<id>` for exactly one subject. Returns (row, won).

    The single writer of this prefix. `claim_order_for_payment` is refactored to call it, so there is
    one place that decides what "this payment is already spoken for" means.
    """
```

`claim_order_for_payment` keeps its signature and behaviour (its tests in `tests/test_order_keys.py`
must stay green untouched) and delegates its `PROVIDERPAYMENT#` write to this function with
`subject_kind=SUBJECT_COMMERCE_ORDER`.

### 5.2 The four retained producers, and how each is migrated

Measured: these are every path in the tree that can turn an inbound payment signal into a financial
side effect. None is deleted.

| Producer | Today | After |
|---|---|---|
| `payments/razorpay-webhook._handle_payment_captured` → commerce | `order_creation.reconcile_payment` | unchanged pipeline; delegates obligations 3 and 4 to `capture_authority.status_is_captured` / `amounts_match`, and obligation 5 is its existing `claim_order_for_payment` → now the same writer. **It is the reference implementation, not a second one** |
| `payments/razorpay-webhook._verify_legacy_invoice_capture` | own ad-hoc checks, raw `'captured'` at `:595`, no claim | calls `capture_authority.authorize(subject_kind=SUBJECT_LEGACY_INVOICE, subject_id=invoiceId)`; see §6 |
| `payments/razorpay-webhook` wallet top-up branch (`:639-651`) | credits a float straight off `notes`, no verification, no claim, not idempotent | calls `authorize(subject_kind=SUBJECT_WALLET_TOPUP, ...)`; see §7 |
| `messaging/inbound-whatsapp-handler._process_payment_status` | Meta Payment Lookup is **optional** (`PAYMENT_LOOKUP_REQUIRED` default off); accepts unverified captures and then marks the invoice paid, sends `order_status`, generates the GST invoice and notifies balance due | calls `authorize(channel="whatsapp_meta", ...)` with a Meta-lookup `verify`; see §5.3 |

Two paths are **examined and deliberately unchanged**, with a test recording why:

- `core/secure-files` / `_dispatch_download_grant_confirmation` (`handler.py:~500`). It grants
  nothing, passes only an order id, and `secure-files._confirm_with_razorpay` is already the single
  authenticated writer of `paid`. It is already behind an authoritative boundary; routing it through
  a second one would create the duplication N1 exists to remove.
- `messaging/whatsapp-business-api/flows/track_request.py`. A reader. It renders a decided value and
  takes no financial action.

`tests/test_one_verification_boundary.py` walks the AST of each producer file and asserts that the
function containing the financial side effects also contains a call to `capture_authority.authorize`
or (for the commerce path) to `order_creation.reconcile_payment`, and that no other function in those
files calls `_mark_invoice_paid_by_reference`, `partner_billing.topup` or the order_status sender. The
test is a structural assertion, which is what makes "one boundary" checkable rather than aspirational.

### 5.3 The inbound-WhatsApp migration, and the behaviour change it carries

`_process_payment_status` currently decides with:

```python
reject = (verification_outcome == REJECTED_MISMATCH
          or (lookup_required and verification_outcome != VERIFIED))
```

so `UNVERIFIED_NO_CONFIG` and `UNVERIFIED_LOOKUP_FAILED` **accept** the capture by default and then
run four financial side effects. The existing comment says this was left permissive on purpose
because making it fail closed "would alter live payment acceptance".

The migration makes it fail closed. The Meta lookup becomes an obligation, not an option:
`capture_authority.authorize` is called with `stored_binding` = the outbound row's
`{paymentConfigName, awsPhoneNumberId, referenceId}` (server-written at send time, which is what makes
it a binding) and `verify` = a closure performing the Meta Payment Lookup GET. `UNVERIFIED_NO_CONFIG`
becomes `STRUCTURAL`; `UNVERIFIED_LOOKUP_FAILED` becomes `UNAVAILABLE`; `REJECTED_MISMATCH` becomes
`NOT_PAID` or `MISMATCH`. Only `VERIFIED` reaches a side effect. `PAYMENT_LOOKUP_REQUIRED` is removed
along with the branch that read it, because an optional verification is not a boundary.

**This is a behaviour change on a money path and must be called out rather than buried.** The
evidence that it breaks no measured traffic: `lambda_utils/payment_status.py`'s measured header
records `PaymentsTable` 0 rows, `InvoicesTable` 0 rows, `OrderTable` 0 rows at 2026-09-23, and
"no payment has ever been captured through this webhook". The audit did not re-measure those counts.
**Implementation precondition:** re-run a read-only `Scan ... --select COUNT` on `PaymentsTable`,
`InvoicesTable` and `OrderTable` before landing this file, and record the numbers in the change
ledger. If any is non-zero, the fail-closed switch needs a migration decision from the owner rather
than this design's assumption. That is an explicit gate, not a hope.

Each of the four side effects in that handler also becomes individually guarded by
`side_effect_guard` keyed on the invoice id, so a Meta redelivery converges on one of each.

## 6. R2 — legacy invoice binding and unique claim

Two independent failures must both be closed: a captured payment paying an invoice it was never
bound to, and one captured payment paying two invoices.

### 6.1 Binding: server-stored only

`_verify_legacy_invoice_capture` (`handler.py:574-600`) is already far better than what it replaced —
it demands exactly one invoice row for the reference, refuses a row carrying `paymentAttemptId` or
`checkoutMode`, and reads Razorpay over authenticated HTTP. Three things make it insufficient:

1. **Its binding authority is `notes`.** `handler.py:589-593` accepts the capture when the provider's
   `notes.referenceId` (or `reference_id`, or `ref`, or a `WD`-prefixed `description`) equals the
   stored reference. Those fields are set by whoever created the gateway order. They are an
   *assertion travelling with the payment*, not a fact the server recorded, so they cannot be the
   authority. The brief is explicit: only server-stored binding is binding.
2. **Absence of commerce markers is not presence of legacy provenance.** `not
   invoice.get('paymentAttemptId') and not invoice.get('checkoutMode')` is satisfied by a
   half-written row, a hand-created row and a row from a future flow nobody thought about.
3. **No unique claim.** Nothing stops the same provider payment id from being accepted against a
   second invoice on a second delivery with a different reference.

The redesign:

```python
LEGACY_BINDING_ATTRIBUTES = ("providerOrderId", "providerAccountId", "providerMode", "amountPaise")

def _legacy_binding(invoice: Dict) -> Dict[str, Any]:
    """The invoice's own server-stored gateway binding, or raise CaptureUnresolved.

    POSITIVE provenance, three parts, all required:
      * `invoice['provenance'] == 'LEGACY_WHATSAPP_INVOICE'` — an explicit marker written by the
        creator, so legacy-ness is asserted by the writer rather than inferred from what is absent
      * a stored `providerOrderId` (+ account, mode) recorded when the gateway order was created
      * `amountPaise`, integer, authoritative. NOT `Decimal(invoice['total']) * 100` computed at
        read time, because `total` is a display field a staff edit can move
    Absence of ANY part -> CaptureUnresolved('LEGACY_BINDING_ABSENT'), classified PERMANENT.
    """
```

The provider's `notes.referenceId` is still read, still compared, and a disagreement still refuses —
but it is now a **consistency check logged as `legacy_notes_disagree`**, downgraded from authority to
corroboration. The authority is `providerOrderId` compared against the authenticated payment's
`order_id`.

`_handle_legacy_capture` then becomes:

```python
    invoice = _sole_legacy_invoice(reference_id)       # exactly one row, else PERMANENT
    binding = _legacy_binding(invoice)                 # positive provenance, else PERMANENT
    authority = capture_authority.authorize(
        channel="razorpay_legacy_invoice",
        subject_kind=capture_authority.SUBJECT_LEGACY_INVOICE,
        subject_id=invoice["invoiceId"],
        stored_binding=binding,
        verify=lambda: razorpay_verify.payment_for_order(binding["providerOrderId"], payment_id),
        expected_amount_paise=binding["amountPaise"],
        expected_currency="INR",
        claim_table=dynamodb.Table(order_keys.commerce_keys_table_name()))
    if not authority.allowed:
        _record_unresolved(...); return        # no invoice write, no GST doc, no message
    # only here: _store_payment_record, _mark_invoice_paid_by_reference, _post_payment_handler,
    # _log_ctwa_purchase, order_status send, _trigger_post_payment_flow — each behind
    # side_effect_guard keyed on (invoiceId, effect)
```

`razorpay_verify.payment_for_order(order_id, payment_id)` is a new thin reader: it fetches
`/orders/<stored order id>/payments`, finds the payment whose `id` equals the event's `payment_id`,
and raises if that payment's `order_id` is not the stored one. The event id is a *lookup key inside a
server-selected set*, never a selector of the set — the same discipline
`verifier_for_event` already uses.

### 6.2 The unique claim closes the two-invoice case

Obligation 5 of `authorize` claims `PROVIDERPAYMENT#<paymentId>` for
`LEGACY_INVOICE#<invoiceId>`. A second delivery naming a different invoice loses the claim, reads back
a row naming the first invoice, and returns `CONFLICT` → no side effect, one recovery row. Because the
prefix is shared with the commerce claim, the same payment also cannot fund an order *and* an invoice.

### 6.3 The amount-matching fallback

`_mark_invoice_paid_by_phone_and_amount` (`handler.py:1406`) matches an invoice on phone + amount — the
literal "one same-price captured payment pays two unrelated invoices" shape. It is called once, at
`handler.py:732`, inside `if reference_id: ... else:`. **That branch is already dead** in this tree:
`_verify_legacy_invoice_capture` raises `CaptureUnresolved('UNKNOWN_REFERENCE')` at `:580` when
`reference_id` is falsy, so `:732` is unreachable.

Decision: **delete the dead call site, keep the function.** It has eight direct tests in
`tests/test_payment_reconciliation_safety.py` that pin its hard-won properties (exact integer paise,
no epsilon, refuse on ambiguity) and those tests stay green. Its docstring gains a line stating it is
not a reconciliation authority and must not be reattached to a capture path. A new
`tests/test_one_verification_boundary.py` case asserts by AST that `_handle_payment_captured` and
`_handle_legacy_capture` contain no call to it. Deleting the function instead would discard a tested
utility and lose the record of why it is dangerous; leaving the dead branch would invite its revival.

## 7. N2 — wallet top-ups: stored intent, exact binding, exactly one credit

Today: `handler.py:639` reads `notes.purpose == 'wallet_topup'` and `notes.wabaId` straight off the
event, converts with `amount_rupees = amount_paise / 100` (a **float**, `handler.py:628`), and calls
`partner_billing.topup`, which is an unconditional `balance = balance + :a`. The producer,
`partner-onboarding._do_topup_order` (`handler.py:~575-614`), creates a Razorpay payment link whose
only binding is those same notes and **stores nothing server-side**. So a signature-valid replay
credits twice, and a forged event credits an arbitrary WABA an arbitrary amount.

Both ends are in owned scope (`partner-onboarding/handler.py` is neither dirty nor on the never-touch
list), so unlike C4 this closes end to end.

### 7.1 Producer: reserve the intent before returning a link

In `_do_topup_order`, after the Razorpay payment-link call succeeds and before the 200 is returned:

```python
    intent_id = order_keys.mint_payment_reference(prefix="WD-TOP-")   # CSPRNG, Meta-safe charset
    amount_paise = money.positive_paise(int(Decimal(str(body["amount"])) * 100))
```

`amount` arrives from a request body, so it is validated at the boundary: required, a decimal string
or number, `> 0`, `<= 10_000_000_00` paise (₹10,00,000 — a stated cap, so an input typo cannot create
a ten-crore intent), and converted through `Decimal(str(value))` then `positive_paise`. The existing
`float(body.get('amount'))` goes. A fractional-paise amount is rejected with 400, not rounded.

The intent is then written with a conditional put on the commerce-keys table under a new prefix:

```python
TOPUP_INTENT_PREFIX = "TOPUPINTENT#"      # in order_keys, beside PAYREF#/ORDERNO#/PROVIDERPAYMENT#

{   "orderId": "TOPUPINTENT#<intentId>", "kind": "WALLET_TOPUP_INTENT",
    "intentId": ..., "wabaId": ..., "amountPaise": <int>, "currency": "INR",
    "providerLinkId": "<plink id from the response>", "providerMode": "live"|"test",
    "providerAccountId": ..., "createdBy": "<actor>", "createdAt": <int>   }
```

plus a reverse-index row `TOPUPLINK#<plinkId>` → `intentId`, written in the same
`TransactWriteItems` (two `Put`s, both `attribute_not_exists`; **no `ConditionCheck`**, per the IAM
measurement). `intentId` goes into the link as both `reference_id` and `notes.topupIntentId`, and
`notes.wabaId` is **kept** so nothing about the existing link shape regresses — but the webhook no
longer treats either note as authority.

If the intent write fails, the handler returns 503 and does **not** return the link. A link a customer
can pay with no server record of what it is for is the defect, so the ordering is: create link →
record intent → hand out link. A link created-but-unrecorded is a cost of one orphan link and is
recorded at error level with the plink id (not a secret).

### 7.2 Consumer: resolve the intent server-side

The notes value is a **lookup key only**. In the webhook:

```python
    intent = _resolve_topup_intent(notes, payment_id)
```

which tries, in order, and takes the first that resolves:

1. `TOPUPINTENT#<notes['topupIntentId']>` — the normal path.
2. `TOPUPLINK#<link id>` → intent, where the link id comes from a `payment_link.*` event payload or
   from the authenticated payment read's `invoice_id`. This is the fallback for the uncertainty in
   §11 U-4.
3. Nothing resolves → `STRUCTURAL`, recovery row, **no credit**.

`notes['wabaId']` is never used to select the wallet. The wallet is `intent['wabaId']`.

Then `capture_authority.authorize(subject_kind=SUBJECT_WALLET_TOPUP, subject_id=intent['intentId'],
stored_binding=intent, verify=..., expected_amount_paise=intent['amountPaise'],
expected_currency="INR")`. Only `allowed` reaches the credit.

### 7.3 Exactly one credit, atomically

New in `partner_billing.py`:

```python
def credit_topup_once(waba_id: str, amount_paise: int, *, idempotency_key: str,
                      note: str = "", actor: str = "customer-service") -> Dict[str, Any]:
    """Credit a verified top-up at most once, in ONE conditional UpdateItem.

        UpdateExpression:  SET balance = balance + :amount, updatedAt = :now
                           ADD appliedTopups :keyset
        ConditionExpression: attribute_exists(wabaId)
                             AND (attribute_not_exists(appliedTopups)
                                  OR NOT contains(appliedTopups, :key))

    One operation, so there is no window between "decide to credit" and "credit". A
    ConditionalCheckFailedException on the `contains` arm means ALREADY CREDITED and is returned as
    success with `credited: False` — that is what makes a duplicate webhook, a lease salvage and a
    manual recovery run all converge on one credit.

    `amount_paise` is integer paise. The rupee value written to `balance` is
    `Decimal(amount_paise) / Decimal(100)` — exact, never a float, never `amount_paise / 100`.

    `idempotency_key` is the top-up intent id. Not the payment id: a gateway that split one intent
    across two payments must still credit the intent once.
    """
```

`appliedTopups` is a DynamoDB String Set. Bound, stated: ~40 bytes per key against the 400 KB item
limit is roughly 10,000 top-ups per wallet. Recorded as a known limit with an archival follow-up
(severity LOW, not a blocker) rather than discovered later. The alternative — a separate claim row
plus a two-phase credit — reintroduces the crash window this avoids, so the set is the better trade.

`topup()` is **kept unchanged** for the admin path (`actor='admin'`), which is a human action with no
provider event to be idempotent against, and its tests stay green. A ledger row is written after the
credit with sort key `TOPUP#<intentId>` and a conditional put, so the audit trail is also once-only
and a ledger failure cannot double the balance.

## 8. R3/N3 — durable unresolved intake and a recoverable job

### 8.1 Why a new store

Today an unresolved capture produces `logger.error(... 'alert': 'PAID_BUT_NO_ORDER' ...)` and nothing
else. A log line is not recoverable: it cannot be leased, retried, acknowledged or closed, and once
Razorpay stops retrying (and the `WebhookDedup` row's 7-day TTL lapses) the only trace is CloudWatch.
`RazorpayWebhookLogTable` holds the raw delivery but has no state, no queue and a 180-day TTL.

### 8.2 The table

`scripts/provision_payment_recovery_table.py` creates
**`stack-wecare-digital-PaymentRecoveryTable`**, on-demand billing, **TTL DISABLED and asserted
disabled by `--verify`** (a recovery row that expires is a paid payment that stops being recoverable).
The `stack-wecare-digital-*` name keeps it inside the existing
`wecare-digital-lambda-role` grant, so no IAM change is needed — confirmed against the audit's
measured policy.

| Key / index | Shape | For |
|---|---|---|
| PK `recoveryId` (S) | `"<channel>#<dedupKey>"` | deterministic, so a redelivery converges on one row |
| GSI `state-nextAttempt-index` | HASH `state`, RANGE `nextAttemptAt` | the worker's due queue |
| GSI `referenceId-index` | HASH `referenceId` | staff lookup by reference |

### 8.3 State is monotonic; the lease is not a state

This is the central decision, and it is what makes "an ACKNOWLEDGED event must remain recoverable"
expressible. If a lease were a state, `ACKNOWLEDGED → LEASED` would be a backward move and a
monotonic guard would forbid the very recovery the requirement demands. So:

```python
STATE_RANK = {
    "OPEN":         10,   # persisted, eligible for automatic retry
    "NEEDS_HUMAN":  20,   # permanent, or automatic attempts exhausted. No automatic retry.
    "ACKNOWLEDGED": 30,   # a human has seen it. STILL RECOVERABLE, by design.
    "ABANDONED":    90,   # closed with no effect, by explicit staff decision + reason
    "RESOLVED":    100,   # the intended effect exists, or was positively established as not owed
}
STATE_RANK_ATTRIBUTE = "stateRank"
```

`ABANDONED`(90) ranks below `RESOLVED`(100) deliberately: an abandoned row may still later resolve if
the effect turns out to be owed, but a resolved row can never be abandoned — an effect that happened
cannot be un-happened. `RESOLVED` and `ABANDONED` are the only terminals.

The lease is two ordinary attributes, `leaseOwner` (S) and `leaseExpiresAt` (N), guarded by
compare-and-swap on the value just read — the same mechanism
`webhook_dedup.claim_event_with_lease` uses, which is already proven here and avoids inventing a
second leasing idea.

### 8.4 The API (`lambda_utils/ecommerce/recovery.py`, injected table)

```python
def record(table, *, recovery_id, channel, classification, outcome, reference_id="",
           contact_id="", provider_payment_id="", provider_order_id="", subject_kind="",
           subject_id="", amount_paise=None, currency="", webhook_log_id="", now=None) -> Dict:
    """Persist (or forward-update) one unresolved payment event. Idempotent on `recovery_id`.

    STRUCTURAL / PERMANENT -> state OPEN is skipped; the row lands at NEEDS_HUMAN with
    `nextAttemptAt` absent, because no automatic retry can help it.
    TRANSIENT -> OPEN with `nextAttemptAt = now + backoff(attemptCount)`.

    A row that already exists is updated forward only, under the monotonic condition. A redelivery
    therefore increments `attemptCount` and refreshes `lastOutcome` without ever moving an
    ACKNOWLEDGED or RESOLVED row backwards to OPEN.

    Raises `RecoveryIntakeUnavailable` on a storage failure. The caller MUST treat that as
    TRANSIENT and keep the dedup lease open: an unresolved capture we could not even record is the
    one case where losing the provider's retry would lose the payment.
    """

def lease(table, *, recovery_id, owner, seconds=900, now=None) -> bool:
    """Take the lease. CAS on the `leaseExpiresAt` just read; False if someone else holds it."""

def release(table, *, recovery_id, owner, error_type="", now=None) -> None:
    """Give the lease back and schedule the next attempt. `error_type` is `type(exc).__name__`."""

def acknowledge(table, *, recovery_id, actor, note="", now=None) -> Dict:
    """NEEDS_HUMAN -> ACKNOWLEDGED. Records `acknowledgedAt`/`acknowledgedBy`/`ackNote`.

    Explicitly NOT a resolution and NOT a deletion. The row stays in the staff queue and stays
    recoverable: `recover()` may be invoked on it at any time, including long after the provider has
    stopped retrying. That is the whole point of the state existing.
    """

def resolve(table, *, recovery_id, order_id="", order_number="", effect="", now=None) -> Dict
def abandon(table, *, recovery_id, actor, reason, now=None) -> Dict   # reason REQUIRED
def due(table, *, now=None, limit=25) -> List[Dict]                  # state-nextAttempt-index
def backoff(attempt_count: int) -> int
```

Retry policy, in one place:

```python
BASE_BACKOFF_SECONDS = 60
MAX_BACKOFF_SECONDS  = 3600
MAX_AUTO_ATTEMPTS    = 8        # ~4.5 hours of doubling, then a human owns it

def backoff(attempt_count):
    """min(MAX, BASE * 2**n) plus deterministic jitter from the recovery id, so a burst of rows
    created in the same second does not retry in lockstep and re-create the thundering herd the
    backoff exists to prevent."""
```

On the 8th failed automatic attempt, `release()` moves the row to `NEEDS_HUMAN` and clears
`nextAttemptAt`, so the sweep stops picking it up. Manual recovery is still available.

### 8.5 The job

No new Lambda and no new API route, for two reasons: the standing grant would allow one, but a new
public route is a new unauthenticated surface on an API where every route already reports
`AuthorizationType=NONE`, and `wecare-razorpay-webhook` already has the Razorpay credential, the three
tables and the IAM this work needs.

So the sweep is an **internal action on the existing function**, reachable only by direct Lambda
invoke:

```python
    # top of handler(), before any HTTP parsing
    if not event.get('requestContext') and event.get('internalAction') == 'recoverPayments':
        return _recover_unresolved(limit=int(event.get('limit') or 10),
                                   request_id=request_id)
```

`_recover_unresolved` for each due row: `lease` → re-run the same authoritative path the original
delivery would have taken (`_create_order_for_captured_payment` for commerce, `_handle_legacy_capture`
for legacy, the top-up path for a top-up) → `resolve` on `MATERIALIZED`/`VERIFIED`, `release` with
backoff on `TRANSIENT`, `NEEDS_HUMAN` on `PERMANENT`. It re-verifies with the provider every time; it
never trusts the stored row's own amount as evidence. Because every downstream write is conditional
and every stage is forward-only, a recovery run on an already-finished row is a no-op.

**No EventBridge schedule is created by this design.** The sweep runs only when invoked, by
`scripts/recover_unresolved_payments.py` (dry-run by default, `--apply` to invoke, `--limit`,
`--recovery-id` for one row). Scheduling it is a separate, reviewable step; nothing should start
re-driving payment events unattended on the same change that introduces the mechanism.

### 8.6 The enumerated edge cases

| Case | Mechanism | Outcome |
|---|---|---|
| **Held lease** | `lease()` CAS on observed `leaseExpiresAt` | second worker gets `False`, skips. No double processing |
| **Lease expiry** | `now >= leaseExpiresAt` and no terminal state | a later worker salvages. `attemptCount` already incremented at `lease()` time, so a crash loop still backs off |
| **Crash between stages** | `record_paid` persists PAID **before** the order claim (`order_creation.py:284-289`); `finalizationStage` is forward-only; each external effect has a `side_effect_guard` claim | re-entry resumes at the first unreached stage. Never an order with no paid attempt, never a repeated external effect |
| **Recovery after acknowledgment** | `ACKNOWLEDGED`(30) is non-terminal; `resolve()` requires only `stateRank <= 100` | works unchanged after the provider has stopped retrying. Pinned by `test_an_acknowledged_event_is_still_recoverable` |
| **Out-of-order events** | `payment_status.condition_expression()` on `PaymentsTable`; `payment_attempt.condition_expression()` on the attempt; `STATE_RANK` on the recovery row; `finalizationStageRank` on the stage | a late `authorized` or `failed` cannot overwrite a capture; a late `NEEDS_HUMAN` cannot overwrite `RESOLVED` |
| **Late capture** | the capture arrives after the attempt was marked failed/expired. `payment_attempt._RANK` puts `PAYMENT_PAID` at 100, above every failure | the attempt moves forward to paid and the order is created. The customer is not told their payment failed |
| **Duplicate callback / webhook race** | `PROVIDERPAYMENT#` claim (one writer, cross-channel) + `PAYMENTATTEMPT#` claim + `attribute_not_exists(orderId)` on the order row + `side_effect_guard` per effect + `appliedTopups` set for a credit | one captured-payment claim, one internal order, one Wix association, one purchase effect. Pinned by `test_a_redelivery_does_not_create_a_second_order` and new `test_concurrent_deliveries_converge_on_one_order` |

## 9. Forward-only stages

### 9.1 Two axes, both monotonic, never the same field

| Axis | Field | Ladder | Owner |
|---|---|---|---|
| Financial state | `status` + `attemptRank` on the attempt | `payment_attempt._RANK`, `CREATED`(10) … `PAYMENT_PAID`(100) | `payment_attempt` |
| Finalization stage | `finalizationStage` + `finalizationStageRank` on the attempt | the ladder below | `finalization` |

```python
STAGE_RANK = {
    "NOT_STARTED":               0,
    "PAYMENT_VERIFIED":         10,   # a provider readback confirmed capture; paid state persisted
    "INTERNAL_ORDER_CREATED":   20,   # the OrderTable row has actually committed
    "WIX_ORDER_CREATED":        30,
    "EXTERNAL_PAYMENT_RECORDED":40,
    "CART_COMPLETED":           50,
    "RECEIPT_ISSUED":           60,
    "NOTIFIED":                 70,
    "COMPLETE":                100,
}
STAGE_RANK_ATTRIBUTE = "finalizationStageRank"
```

**`NEEDS_RECONCILIATION` is removed from the stage ladder.** It is currently written *into*
`finalizationStage` (`finalization.py:80-82`, `:93-95`), which is precisely why a redelivery can move
an order from `EXTERNAL_PAYMENT_RECORDED` back to `NEEDS_RECONCILIATION` — audit §4.4. Parking is not
a position on the ladder; it is a flag beside it:

```python
    finalizationBlocked = True | False      # BOOL
    finalizationReason  = "WIX_WRITE_CONTRACT_REQUIRED" | "PURCHASED_SNAPSHOT_MISSING"
                        | "WIX_READBACK_REQUIRED"
    finalizationBlockedAt = <int>
```

so the row says both "I reached stage 40" and "I am parked for reason X", which are two different
facts about one order. Ranking a non-stage would have lost one of them.

### 9.2 `_stage` becomes a forward-only write with an idempotent no-op

```python
def _stage(attempts, attempt_id, stage, **fields):
    """Advance the finalization stage. Forward only; an at-or-past target is a no-op.

    The guard is a ConditionExpression and not a read-then-write, because two deliveries can be in
    flight at once and a read-then-write lets both through — which is how `accept_paid` re-staged
    INTERNAL_ORDER_CREATED on every delivery.
    """
    rank = STAGE_RANK[stage]            # KeyError on an unknown stage: a typo is not a new stage
    ...
    ConditionExpression = ('#s = :paid AND (attribute_not_exists(#rank) OR #rank <= :rank)')
    # ConditionalCheckFailedException -> read back with ConsistentRead.
    #   stored rank >= rank  -> already there or past it. Log info, return. NOT an error.
    #   status not paid      -> raise FinalizationNotPaid. A stage on an unpaid attempt is a bug.
```

`#s = :paid` is retained from the current code and is correct: a finalization stage may only exist on
an attempt whose financial state is paid, which is the "authorized is not paid" rule expressed as a
condition rather than a comment.

### 9.3 `record_paid`

Three corrections, all from the audit:

```python
def record_paid(attempts, attempt, provider_payment_id):
    attempts.update_item(
        Key={'paymentAttemptId': attempt['paymentAttemptId']},
        UpdateExpression=('SET #s = :paid, attemptRank = :rank, '
                          'paidAt = if_not_exists(paidAt, :now), updatedAt = :now, '
                          'verifiedProviderPaymentId = :provider'),
        ConditionExpression=('attribute_exists(paymentAttemptId) AND referenceId = :ref '
                             'AND (attribute_not_exists(verifiedProviderPaymentId) '
                             '     OR verifiedProviderPaymentId = :provider) '
                             'AND (' + payment_attempt.condition_expression() + ')'),
        ...
        ExpressionAttributeValues={':rank': payment_attempt.rank(payment_attempt.PAYMENT_PAID), ...})
```

1. `:rank` comes from `payment_attempt.rank(PAYMENT_PAID)`, not the literal `100`. The literal is
   benign only while `PAYMENT_PAID` is the maximum; it diverges silently the moment `_RANK` changes.
2. `payment_attempt.condition_expression()` is included, parenthesised (it contains a bare `OR`, so
   ANDing it unparenthesised would change the meaning).
3. A `ConditionalCheckFailedException` is no longer allowed to propagate as an opaque error: it is
   read back and distinguished — same provider id and already paid is an idempotent success; a
   *different* `verifiedProviderPaymentId` raises `ProviderPaymentConflict`, which maps to
   `PROVIDER_PAYMENT_CONFLICT` / `PERMANENT`.

### 9.4 `accept_paid` becomes resumable and guards each external effect

```python
def accept_paid(*, attempts, orders, keys, attempt, outcome):
    reached = int(attempt.get(STAGE_RANK_ATTRIBUTE) or 0)
    ...
    record_paid(...)                                        # idempotent
    if reached < STAGE_RANK["PAYMENT_VERIFIED"]:
        _stage(..., "PAYMENT_VERIFIED")
    if reached < STAGE_RANK["INTERNAL_ORDER_CREATED"]:
        orders.put_item(..., ConditionExpression='attribute_not_exists(orderId)')
        # the existing five-field comparison on conditional failure is KEPT verbatim
        _stage(..., "INTERNAL_ORDER_CREATED", orderId=..., orderNumber=...)
    for effect, stage, run in (
            (side_effect_guard.WIX_ORDER,   "WIX_ORDER_CREATED",         _create_wix),
            (side_effect_guard.WIX_PAYMENT, "EXTERNAL_PAYMENT_RECORDED", _record_external),
            (side_effect_guard.CART_COMPLETION, "CART_COMPLETED",        _complete_cart),
            (side_effect_guard.RECEIPT,     "RECEIPT_ISSUED",            _issue_receipt),
            (side_effect_guard.NOTIFICATION,"NOTIFIED",                  _notify)):
        if reached >= STAGE_RANK[stage]:
            continue
        if not side_effect_guard.claim(keys, order_id=order['orderId'], effect=effect):
            marker = side_effect_guard.resolve(keys, order_id=..., effect=effect)
            if marker and marker.get('state') == side_effect_guard.DONE:
                _stage(..., stage); continue
            _park("SIDE_EFFECT_PENDING_READBACK"); return   # never repeat an external mutation
        result = run(...)                                   # may raise WixWritebackPending
        side_effect_guard.confirm(keys, order_id=..., effect=effect, result=result)
        _stage(..., stage)
```

Two properties this preserves from the current code and must not lose: the Wix write still only runs
when `wix_writeback.is_enabled()` **and** `attempt['wixOrderPayload']` exists, and an unavailable Wix
contract still **parks a paid order** rather than losing it. `KNOWN_EFFECTS` in `side_effect_guard`
gains `CART_COMPLETION = "cart_completion"` and `NOTIFICATION = "notification"` (and
`WALLET_CREDIT = "wallet_credit"` for §7), added deliberately — the module's closed-set rule is the
point.

**Receipt and notification remain gated off.** `_issue_receipt` and `_notify` are wired into the
ladder but their runners raise `EffectNotAttested` unless their contract flags are set, matching
`accept_paid`'s existing docstring ("Receipts/notifications have their own guarded adapters and must
be enabled only after their contracts are attested"). The stage ladder is complete; two of its rungs
are deliberately unreachable until attested. Enabling them is not this change, and enabling any
live-send flag is prohibited outright.

### 9.5 The redelivery that re-entered finalization

`handler.py:703-709` calls `_persist_commerce_paid` whenever `hasOrder` is true, which includes
`ORDER_ALREADY_EXISTS`. That stays — re-entry is how a crash mid-finalization is recovered — but it is
now safe, because `accept_paid` reads `finalizationStageRank` first and skips every stage already
reached, and every external effect is additionally behind a `side_effect_guard` claim. Audit §4.4 is
closed by making re-entry idempotent rather than by refusing it.

## 10. Public order number

The brief lists six obligations. Two are already satisfied at HEAD and are reported as such rather
than re-fixed.

| # | Obligation | Status at HEAD | Work |
|---|---|---|---|
| PON-1 | Preserve `WD-ORD-` + 8 CSPRNG chars | **satisfied** — `order_keys.py:109` prefix, `:128` `ENTROPY = 8`, `:131` length 15, `:274` `mint_public_order_number` uses `secrets.choice` over the 30-symbol alphabet | add `test_the_minted_format_is_prefix_plus_eight` asserting `is_current_public_order_number` on 1,000 mints |
| PON-2 | Conditional uniqueness, no expiring reservation | **satisfied** — `reserve_public_order_number` (`:415`) claims `ORDERNO#<number>` via `_claim_row`'s `attribute_not_exists`, 5 attempts, raises rather than falling back | add `test_a_reservation_row_carries_no_ttl` asserting the item has no `ttl`/`expiresAt`/`expiry` attribute, and a `--verify` assertion that the commerce-keys table has TTL disabled |
| PON-3 | Lookup compatibility for old 12-char / historical ids | **satisfied** — `is_public_order_number` (`:210`) accepts both regexes; `is_wd_order_number` (`:236`) accepts both spaced and compact legacy forms | add `test_every_historical_form_still_resolves` over the three shapes |
| PON-4 | Do **not** restore the 12-char minting requirement; do not derive from time or PII | **satisfied in code** | see PON-7 for the spec |
| PON-5 | Remove stale generator comments | **three stale sites** | below |
| PON-6 | Fix `_get_or_create_wd_order_number`'s unstored-number exception path | **SUPERSEDED — already fixed** at `wix-store/handler.py:788-876`: the read failure raises `OrderIdentityUnavailable` (`:822`), the number is reserved by `order_keys.reserve_order_number` *before* return (`:834`), and a store failure raises (`:866`). Nothing returns an unstored number | add a regression test; correct the two documents that still describe the old behaviour |

**PON-5, the three stale sites:**

| Site | Says | Should say |
|---|---|---|
| `order_keys.py:415` docstring | "a unique **12-character** public order number" | `WD-ORD-` + 8 CSPRNG symbols (15 characters) |
| `order_keys.py:530` `record_order_number_on_claim` `ValueError` text | "not a valid **12-character** public order number" | "not a public order number this system issues or has issued" |
| `order_keys.py:160-166` comment above `_WD_ORDER_NUMBER_RE` | "New checkout orders use the **12-character number** instead" | new checkout orders use `reserve_public_order_number`; this pattern serves only Wix-synced orders |

**PON-7, the spec drift.** `.kiro/specs/whatsapp-wix-commerce/requirements.md:196` ("12 characters")
and `:211` ("The 12-character order number SHALL be reserved…") describe a format the code does not
produce and the brief forbids restoring. The **spec** is the thing that is wrong, so those two lines
are edited to the shipped format with a one-line note that historical 12-character numbers remain
valid for lookup. That file is modified by another session; the edit is staged and committed with
`git commit --only .kiro/specs/whatsapp-wix-commerce/requirements.md <owned paths>` so nothing
foreign rides along.

**PON-6's documentation debt.** `.kiro/steering/whatsapp-payments-india-reference.md:88-91` and
`.kiro/specs/whatsapp-wix-commerce/design.md:176-179` both still state that the exception path
"currently returns an **unstored** number". It does not. The steering line is corrected to record the
fix and its date, because a steering file asserting a live defect that no longer exists sends the next
reader to patch working code.

**PON-4 test.** `test_the_number_encodes_no_time_and_no_identity`: with `time.time` patched to a
constant, 1,000 mints are all distinct (so nothing is time-derived); the symbol distribution across
positions is within a chi-square bound of uniform (so nothing is structurally seeded); and the
generated tail shares no substring of length ≥ 4 with a fixture phone number, email or customer id.

## 11. Hard constraints — how each is honoured, and where it is enforced

### 11.1 Money

- **Integer paise only, no float.** Every comparison goes through `money.positive_paise`, which
  already refuses `bool`, non-integer `Decimal`, non-`int`, `<= 0` and `> 2**53-1`. Conversions use
  `Decimal(str(value))` and never `/ 100` on a float. `Money.from_wix` stays the only reader of a Wix
  decimal string and already refuses anything not matching `[0-9]{1,14}(\.[0-9]{1,2})?`.
- **Three live float sites are removed**, all `amount_paise / 100`:
  - `handler.py:628` — feeds the wallet credit (§7). Becomes `Decimal(amount_paise) / Decimal(100)`,
    used for **display and message text only**; after §7 no decision reads it.
  - `handler.py:1264` in `_store_payment_record` — the float is then re-wrapped as
    `Decimal(str(amount_rupees))` and **stored** as `amountInRupees` (`:1280`), so a float artefact
    lands in a money field in `PaymentsTable`. Becomes `Decimal(amount_paise) / Decimal(100)`
    directly. `amount` (`:1279`) is already exact integer paise and is unchanged.
  - `partner-onboarding` `float(body.get('amount'))` → `Decimal(str(...))` + `positive_paise` (§7.1).

  `_log_ctwa_purchase`'s `round(float(amount_rupees), 2)` is a Meta Conversions payload field, not a
  decision, and is left as the one documented display float with a comment saying so.
- **One paise fails closed.** `order_creation` compares `provider_amount != expected_amount` on two
  ints; `capture_authority.amounts_match` is the same equality for every other channel. An amount
  that cannot be coerced is a refusal (`AMOUNT_MISMATCH` / `MISMATCH`), never a pass.
- **Overflow / negative / fractional** are rejected by `positive_paise`. New boundary validation on
  the top-up amount adds an explicit upper cap (§7.1).
- **`_money_amount` latent defect: SUPERSEDED.** `wix_domain.py:61-88` no longer ends in
  `str(value)`; it validates with `Decimal(text)` and returns `''` on anything that is not a decimal
  string. The steering file's "known latent defect" note is stale. Recorded here; a test
  (`test_money_amount_refuses_a_non_numeric_price`) pins it so it cannot regress. Wix writes remain
  switched off regardless.

### 11.2 Payment vocabulary

- **No decision compares a payment status raw.** Every one goes through
  `lambda_utils/payment_status.py`. The raw `'captured'` at `handler.py:595` is replaced by
  `pay_status.canonical(actual.get('status')) == pay_status.CAPTURED` — canonical on the left, a
  module constant on the right, so there is no string literal in the comparison at all and the AST
  gate's `is_canonicalised` check passes for the right reason.
- **`captured` stays the only banned literal.** `FORBIDDEN_RAW == {"captured"}` is unchanged, and
  `test_paid_is_deliberately_not_in_the_forbidden_set` stays exactly as written.
- **`InvoicesTable.status` is not touched.** `inv.get('status') != 'paid'` in
  `_mark_invoice_paid_by_reference` is a document lifecycle and is correct.
  `test_the_invoice_document_lifecycle_is_deliberately_left_raw` keeps passing unmodified. The
  design does not canonicalise that field anywhere.
- **The gate's blind spot is closed.** `test_no_decision_compares_a_payment_word_raw` currently
  filters to `ast.Eq`/`ast.NotEq` (`:263`), so a raw-word decision written as `in (...)` is invisible.
  The walk is extended to `ast.In`/`ast.NotIn` and inspects the literals inside a `Tuple`/`List`/`Set`
  comparator. The one live offender it then finds, `invoice-engine/handler.py:766`
  `ex_ps in ('captured', 'refunded')`, is rewritten as
  `pay_status.rank(ex_ps) >= pay_status.STATUS_RANK[pay_status.CAPTURED]` — which also fixes the
  substantive bug the audit named: that comparison misses `disputed`.
  `invoice-engine/handler.py:2010` `status in ('paid', 'cancelled')` is the document lifecycle and is
  left alone; the extended gate does not flag it, because `paid` is not in `FORBIDDEN_RAW`.
- **The gate's file list grows** by the three shared modules that now make payment decisions:
  `shared/lambda_utils/integrations/razorpay_verify.py`,
  `shared/lambda_utils/ecommerce/order_creation.py`,
  `shared/lambda_utils/ecommerce/capture_authority.py`.
- **Authorized is not paid.** `payment_attempt.ORDER_ELIGIBLE_STATES == {PAYMENT_PAID}` and
  `payment_status.AUTHORIZED` ranks 30, below `CAPTURED` 50. `capture_authority.status_is_captured`
  accepts only canonical `captured`. Nothing in this design treats `authorized` as fundable.

### 11.3 Credentials, secrets and logging

- Razorpay API credentials are read **lazily, at request time**, from Secrets Manager id
  `wecare/razorpay/api` (fields `key_id`, `key_secret`) by `razorpay_verify._credentials()`, which is
  already correct and is not changed. The legacy id `wecare/razorpay-webhook` holds only
  `webhook_secret` and is read only by `_get_webhook_secret`, which is also already lazy.
- No new secret read is introduced anywhere. No `secretsmanager get-secret-value` from a shell or a
  script. No credential value in a command, argv, env assignment, log or logging expression.
- **No secret-derived value appears in any logging expression**, not even reduced to a bool or a
  ternary — CodeQL `py/clear-text-logging-sensitive-data` tracks taint across function boundaries, and
  this repository has failed that check twice on exactly that pattern. New log lines carry only:
  `referenceId`, `contactId`, `recoveryId`, `orderNumber`, `invoiceId`, `paymentAttemptId`,
  `providerPaymentId`, `providerOrderId`, `amountPaise`, `outcome`, `disposition`, `classification`,
  `state`, `attemptCount`, `effect`, `requestId`, `type(exc).__name__`.
- `referenceId` and `contactId` are **not** secrets and are logged in full — that is deliberate, and
  it is why a payment log line needs no masked field to be traceable.
- Phone numbers go through `lambda_utils.privacy.mask_phone` (last four). Not widened. The known
  ambiguity between the QA recipient's `...0044` and the WABA2 business number is disambiguated on
  `direction`/`channel`/delivery id, never by widening the mask.
- Exception text from an untrusted source is never logged: `type(exc).__name__` only. The one
  exception is a message this code constructed itself from known-safe parts (e.g.
  `f"Razorpay returned HTTP {exc.code}"`, already the existing pattern).
- **Webhook signatures are verified over the original raw body**, before any parse. Already true:
  `_verify_signature` runs at `handler.py:119` before `json.loads`, HMACs the bytes, uses
  `hmac.compare_digest`, and a failed base64 decode leaves the body undecoded so the HMAC cannot
  match — fail closed. A new `test_the_signature_is_computed_over_the_delivered_bytes` pins
  byte-exactness for a base64-encoded delivery and pins that a decode failure rejects. One
  `INFORMATIONAL` note for the record: after a successful decode the body is a `str` re-encoded as
  UTF-8, which is byte-identical for JSON but would not be for a non-UTF-8 body. Not changed, because
  changing the verifier's byte handling without live payment traffic to validate against is a worse
  risk than the theoretical one.

### 11.4 Prohibited, and not done

No payment capture. No refund. No payment-configuration mutation. No live-send flag enabled (receipt
and notification stages ship deliberately unreachable). No standalone Wix invoice — the commerce path
returns before `_post_payment_handler`, which is the only creator of a payable invoice, and
`accept_paid`'s "never creates a payable invoice" docstring stays true. No second charge: the
`PROVIDERPAYMENT#` claim is now a single cross-channel writer, and
`tests/test_order_creation.py::test_reconciliation_cannot_charge_the_customer` — the R7.4 outbound-call
allowlist — is extended to cover `capture_authority` and the recovery sweep. No credential rotation
and no credential value read. **No deploy:** `live` stays at v45.

## 12. Error handling, per operation

Every operation that can fail, what it does, and what the caller sees. "Lease" means the
`WebhookDedup` lease: *open* lets Razorpay retry, *closed* does not.

| Operation | Failure | Recoverable? | Caller receives | Logged | HTTP / lease |
|---|---|---|---|---|---|
| `_verify_signature` | no secret, missing header, mismatch | n/a | `False` | `error` (no secret) / `warning` + `bodyLen` only | 401, no lease taken |
| `json.loads(body)` | malformed | no | exception | `error`, `JSONDecodeError` name | 400, lease open |
| `_log_webhook_event` | PutItem fails | yes (audit only) | `None`, swallowed | `warning` | processing continues — the audit row is not a gate |
| `order_keys.resolve_payment_reference` | read error | yes | `OrderIdentityUnavailable` → `ATTEMPT_STORE_UNAVAILABLE` | `error` via `_blocked` | 500, lease open |
| `_load_attempt` index inconsistency | `referenceId`/`customerId` disagree | no | `CaptureUnresolved('ATTEMPT_INDEX_INCONSISTENT')` → `ATTEMPT_STORE_UNAVAILABLE` | `error` | 500, lease open. **Deliberate:** an inconsistent index may be replication lag |
| `razorpay_verify` no stored binding | structural | **no** | `RazorpayBindingMissing` → `BINDING_MISSING` | `error`, `classification: STRUCTURAL`, `PAID_BUT_NO_ORDER` | 200, lease **closed**, recovery row `NEEDS_HUMAN` |
| `razorpay_verify` HTTP/URL error | transient | yes | `RazorpayUnavailable` → `PROVIDER_UNAVAILABLE` | `error`, status code only | 500, lease open, recovery row `OPEN` |
| `razorpay_verify` multiple captures | ambiguous | no | `RazorpayUnavailable` → `PROVIDER_UNAVAILABLE`¹ | `error` | 500, lease open |
| amount / currency / customer mismatch | permanent | **no** | `AMOUNT_MISMATCH` etc. | `error`, `PAID_BUT_NO_ORDER` | 200, lease **closed**, `NEEDS_HUMAN` |
| `claim_provider_payment` lost to another subject | permanent | no | `PROVIDER_PAYMENT_CONFLICT` | `error` | 200, lease closed, `NEEDS_HUMAN` |
| `claim_provider_payment` storage error | transient | yes | `OrderIdentityUnavailable` → `IDENTITY_UNAVAILABLE` | `error` | 500, lease open |
| `reserve_public_order_number` exhausted / storage | transient | yes | `IDENTITY_UNAVAILABLE`; the claim already exists so re-entry finishes it | `error` | 500, lease open. A burned number is invisible; a reissued one is not |
| `record_paid` conditional failure, same provider id | not a failure | — | idempotent success | `info` | continue |
| `record_paid` conditional failure, different provider id | permanent | no | `ProviderPaymentConflict` → `PROVIDER_PAYMENT_CONFLICT` | `error` | 200, lease closed, `NEEDS_HUMAN` |
| `orders.put_item` conditional failure, 5 fields agree | not a failure | — | adopt the existing order | `info` | continue |
| `orders.put_item` conditional failure, a field disagrees | permanent | no | `ValueError('internal order association conflict')` | `error` | 200, lease closed, `NEEDS_HUMAN` |
| `_stage` at-or-past target | not a failure | — | no-op | `info` | continue |
| `_stage` on an unpaid attempt | bug | no | `FinalizationNotPaid` | `error` | 500, lease open |
| `side_effect_guard.claim` lost, marker `done` | not a failure | — | advance the stage | `info` | continue |
| `side_effect_guard.claim` lost, marker `pending` | needs readback | yes, **manually** | park `SIDE_EFFECT_PENDING_READBACK` | `error` | 200, lease closed, `NEEDS_HUMAN`. A pending marker is never permission to repeat an external mutation |
| `side_effect_guard` storage error | fail closed | yes | `SideEffectGuardUnavailable` | `error` | 500, lease open |
| Wix writeback disabled / no payload | expected today | yes | park `WIX_WRITE_CONTRACT_REQUIRED`, paid order retained | `warning` | 200, lease closed, `NEEDS_HUMAN` |
| `WixWritebackPending` | uncertain external write | yes, manually | park `WIX_READBACK_REQUIRED` | `error` | 200, lease closed, `NEEDS_HUMAN`. Never retried automatically |
| `recovery.record` storage error | **the one that must not be swallowed** | yes | `RecoveryIntakeUnavailable` | `error`, `RECOVERY_INTAKE_UNAVAILABLE` | **500, lease open** — losing the retry would lose the payment |
| `recovery.lease` lost | not a failure | — | `False`, skip the row | `info` | sweep continues |
| `credit_topup_once` conditional failure on `contains` | already credited | — | `{credited: False}` | `info` | success |
| `credit_topup_once` other error | transient | yes | exception → recovery row `OPEN` | `error` | 500, lease open |
| ledger row conditional failure | already recorded | — | ignored | `info` | continue. A ledger failure must never double a balance |
| Meta Payment Lookup non-2xx / empty | transient / structural | depends | `UNAVAILABLE` / `STRUCTURAL` | `error` | no side effect; recovery row |

¹ `PROVIDER_UNAVAILABLE` classifies as `TRANSIENT`, so multiple captures on one order retries. That is
deliberate but imperfect — see §13 U-6.

## 13. Validation of every external input

| Input | Source | Required | Type / limits | On failure |
|---|---|---|---|---|
| `x-razorpay-signature` | webhook header | yes | ASCII hex; `hmac.compare_digest` | 401, `warning`, `bodyLen` only |
| webhook body | webhook | yes | valid JSON after optional base64 decode; signature verified over the delivered bytes first | 400 / 401 |
| `payload.payment.entity.id` | webhook | yes for a capture | non-empty str; used **only** as a lookup key | `NO_PROVIDER_ID`, no order |
| `notes.referenceId` / `reference_id` / `ref` / `description` | webhook | no | lookup key only; `order_keys.assert_valid_meta_reference_id` charset, **never truncated** | `NO_REFERENCE_ON_EVENT` → `PERMANENT` |
| `notes.purpose`, `notes.wabaId`, `notes.topupIntentId` | webhook | no | lookup keys only; the wallet is chosen from the **stored intent** | `STRUCTURAL`, no credit |
| provider `amount` | authenticated Razorpay read | yes | `money.positive_paise`: int paise, `0 < v <= 2**53-1`, no bool, no float, no fractional `Decimal` | `AMOUNT_MISMATCH` / `MISMATCH` |
| provider `currency` | authenticated read | yes | exact `"INR"`, compared explicitly, never inferred | `CURRENCY_MISMATCH` |
| provider `status` | authenticated read | yes | `payment_status.canonical(...) == CAPTURED`; a rank above `CAPTURED` refuses | `NOT_PAID` / refuse |
| provider `order_id`, `account_id`, mode | authenticated read | yes | equal to the stored binding | `RazorpayUnavailable`, field named, no value |
| `providerOrderId`, `providerAccountId` (seam) | the gateway's response, server side | yes | non-empty, `<= 64`, `[A-Za-z0-9_-]` | `ValueError` |
| `providerMode` (seam) | server | yes | exactly `"live"` or `"test"` | `ValueError` |
| `providerAmountPaise` (seam) | server | yes | `money.positive_paise` | `ValueError` |
| top-up `amount` | HTTP body | yes | `Decimal(str(v))`, `> 0`, integral paise, `<= 10_000_000_00` paise | 400 |
| top-up `wabaId` | HTTP body | yes | non-admin callers are forced to their own `ctx['wabaId']` (existing rule, kept) | 400 |
| `recoveryId`, `limit` (sweep) | internal invoke | `limit` no | `limit` int, `1 <= n <= 100`; `recoveryId` must exist | 400 / skip |
| `actor`, `reason` (`acknowledge`/`abandon`) | operator script | `reason` yes for `abandon` | non-empty str, `<= 500` chars | `ValueError` |
| Meta lookup response | Meta Graph | yes | `payments[0].status` through `canonical` | `UNAVAILABLE` |

## 14. Invariants and the layer that owns each

| Invariant | Owner | Mechanism | Why there |
|---|---|---|---|
| One provider payment funds at most one subject, across all channels | `order_keys.claim_provider_payment` | conditional `attribute_not_exists` on `PROVIDERPAYMENT#` | the only cross-channel chokepoint; a GSI cannot enforce it and application code cannot win a race |
| One payment attempt yields at most one order | `order_keys.claim_order_for_payment` | conditional `PAYMENTATTEMPT#` | same |
| An order exists only after a verified capture | `order_creation.reconcile_payment` ordering | the provider call precedes the claim; `may_create_order` re-checks `ORDER_ELIGIBLE_STATES` | ordering is the guarantee; a flag would drift |
| A public order number is never reissued | `order_keys.reserve_public_order_number` | conditional `ORDERNO#`, reserved before return, TTL disabled | storage, not code |
| Financial state never moves backwards | `payment_attempt.condition_expression()` | persisted `attemptRank` | a ConditionExpression, not a read-then-write: two deliveries can be concurrent |
| Finalization never moves backwards | `finalization._stage` | persisted `finalizationStageRank` | same |
| A recovery row never moves backwards | `recovery` | persisted `stateRank` | same |
| Each external side effect runs at most once | `side_effect_guard` | conditional claim + confirm, per `(orderId, effect)` | per-effect granularity; event-level dedup is all-or-nothing |
| A wallet is credited at most once per intent | `partner_billing.credit_topup_once` | `NOT contains(appliedTopups, :key)` in the same UpdateItem as the increment | one atomic op removes the crash window entirely |
| Payment status has one vocabulary | `lambda_utils/payment_status.py` + the AST gate | `canonical`/`rank`/`for_storage`; `tests/test_payment_vocabulary_at_decision_points.py` | a module nobody imports cannot be the vocabulary — the test is the enforcement |
| Money is integer paise | `money.positive_paise` / `Money` | type refusal at the boundary | cheaper to refuse the type than to find a one-paise mismatch later |
| A paid payment is never lost | `recovery` + the lease | durable intake written before the alarm; `record` failure keeps the lease open | the only state where losing a provider retry costs money |

## 15. Testability

Unit-testable offline, no network, no AWS, against `tests/crm_fake_dynamo.FakeDynamo`:
`capture_authority` (every obligation, every classification), `recovery` (every state transition,
lease CAS, backoff, acknowledge-then-recover), `payment_attempt.gateway_binding`,
`initiation.bind_gateway_order`, `finalization` stage monotonicity, `order_keys.claim_provider_payment`,
`partner_billing.credit_topup_once`, `order_creation.disposition` totality, `money`, the AST gates.

Integration-testable only against live AWS and a real provider, and therefore **out of scope**: that a
real Razorpay capture reaches `MATERIALIZED`; that the recovery sweep runs under the real IAM role;
that `PaymentRecoveryTable` exists. Each is named in §16 as `NOT VERIFIED` rather than assumed.

### 15.1 The 20 failing tests: a required fixture rework, not a workaround

19 of the 20 share one root cause, and it is a data-model change rather than a typo. The fixtures
encode the **old** model, in which the authoritative amount and currency lived on the `PAYREF#` row:
`tests/test_razorpay_webhook_order_creation.py:41-46` seeds exactly that and `:49-57` patches
`dynamodb` so every `Table(...)` returns the one keys table. The working tree's `_load_attempt`
(`handler.py:460-469`) now does a second hop — `resolve_payment_reference` →
`PaymentAttemptsTable.get_item(Key={'paymentAttemptId': ...})` — against a fake keyed on `orderId`,
which raises `KeyError`. `initiation.py:75` states the new rule outright: *"PAYREF is an index only;
all authoritative financial fields live on the attempt."*

So the fixtures become **two-table**: a `PAYREF#` index row carrying only
`{referenceId, paymentAttemptId, customerId, checkoutMode}`, plus an attempt row in
`PaymentAttemptsTable` keyed on `paymentAttemptId` carrying `amountPaise`, `currency`, `customerId`,
`referenceId`, `checkoutMode` **and the gateway binding**. A shared helper
`tests/payment_fixtures.py::seed_commerce_attempt(ddb, **overrides)` is added so the shape lives in
one place and the two existing test modules stop drifting apart.

**The 20th failure is the AST gate** (`test_no_decision_compares_a_payment_word_raw`), failing on the
raw `'captured'` at `handler.py:595`. §11.2 fixes the source, not the test.

**And the fixtures must stop hiding C4.** `tests/test_razorpay_webhook_order_creation.py:51-52`
patches `razorpay_verify.verifier_for_event` and returns a stub, so
`razorpay_verify.py:159-178` — the binding requirement — never executes. A green suite is therefore not
evidence against C4, by construction. Two changes: the stub seeds a real gateway binding on the attempt
so the fixture reflects production, and a **new unstubbed test**
`tests/test_razorpay_binding.py::test_a_capture_with_no_stored_binding_is_structural` drives the real
verifier end to end with `_get` patched at the HTTP boundary only, asserting `BINDING_MISSING` /
`STRUCTURAL` / a recovery row / no order.

`test_reconciliation_cannot_charge_the_customer` (the R7.4 outbound-call allowlist) fails for the same
fixture reason. After the rework it must be **re-confirmed green, not assumed**: its entire job is to
notice a new outbound call, and this change adds call sites.

### 15.2 Test inventory

| File | New / changed | Pins |
|---|---|---|
| `tests/payment_fixtures.py` | **new** | the two-table seed, in one place |
| `tests/test_capture_authority.py` | **new** | five obligations in order; `STRUCTURAL` on no binding; `CONFLICT` on a second subject; same-subject re-entry allowed; one-paise mismatch refused; `refunded`/`disputed` refused; a `notes`-only binding refused |
| `tests/test_payment_recovery.py` | **new** | every transition; backward moves refused; lease CAS; expiry salvage; backoff + jitter; `MAX_AUTO_ATTEMPTS` → `NEEDS_HUMAN`; **acknowledge then recover**; `abandon` requires a reason; `ABANDONED → RESOLVED` allowed, `RESOLVED → ABANDONED` refused |
| `tests/test_gateway_binding_seam.py` | **new** | `bind_gateway_order` idempotent / conflicting / missing attempt / bad amount / mismatched reference; the docstring example runs |
| `tests/test_finalization_stages.py` | **new** | forward-only; at-or-past is a no-op; `NEEDS_RECONCILIATION` is not a stage; crash-between-stages resume; `record_paid` uses the rank primitive; a redelivery re-stages nothing |
| `tests/test_wallet_topup_integrity.py` | **new** | no intent → no credit; `notes.wabaId` ignored; amount mismatch → no credit; duplicate delivery → exactly one credit; float input refused; ledger failure does not double |
| `tests/test_one_verification_boundary.py` | **new** | AST: each retained producer's effect function reaches the boundary; `_mark_invoice_paid_by_phone_and_amount` has no capture-path caller; the two examined-and-unchanged paths are recorded |
| `tests/test_legacy_invoice_binding.py` | **new** | positive provenance required; `notes` are corroboration only; two invoices cannot share one payment; ambiguous reference refused |
| `tests/test_razorpay_webhook_captured_gating.py` | changed | fixtures; per-disposition lease/status assertions; one alarm **and** one receipt |
| `tests/test_razorpay_webhook_order_creation.py` | changed | fixtures; binding seeded |
| `tests/test_razorpay_binding.py` | changed | the unstubbed structural test; the verifier never reads its own output |
| `tests/test_order_creation.py` | changed | `disposition` totality; the outbound allowlist re-confirmed |
| `tests/test_order_keys.py` | changed | `claim_provider_payment` as the single writer; reservation carries no TTL; historical forms resolve; the minted format |
| `tests/test_payment_vocabulary_at_decision_points.py` | changed | `in (...)` walk; three files added to `CONSULTING_FILES`; `FORBIDDEN_RAW` and the two boundary tests unchanged |
| `tests/test_payment_reconciliation_safety.py` | unchanged | must stay green — the phone/amount matcher keeps its properties |

Gate before any commit: `.venv/bin/python -m pytest tests/ -q` fully green (not just the focused
subset), plus `npm run typecheck`. `python scripts/verify_secret_hook.py` and
`python scripts/verify_razorpay_secret_path.py` are run because this change touches the payment path.

## 16. Ambiguities and unverified assumptions

Stated rather than papered over. Each names what would settle it.

- **U-1 — `R1` does not resolve to a payment requirement.** `requirements.md:151` R1 is "Configurable
  vendor versions". The brief's `R1/C1` is the closure matrix's `C1`, and the requirement it actually
  serves is `R2` (`requirements.md:172`, order only after verified capture) plus `R7.8`
  (`:328-329`, mismatch fails closed and raises for staff). Carried as `R1/C1` for traceability with
  the mislabel recorded, not silently re-keyed.
- **U-2 — C4 is not closed end to end, by design.** The brief assigns the initiation-side write to a
  concurrent workstream. Until `bind_gateway_order` has a caller, every real capture is
  `BINDING_MISSING`. This design's job is to make that state loud, durable and recoverable; it does
  not make checkout work. Settled by that workstream calling the seam.
- **U-3 — `account_id` on a Razorpay payment response is not confirmed.** The mode/account comparison
  in §4.4 assumes the payment object carries an account identifier. If it does not, that obligation
  degrades to an INFO line naming the absent field and the remaining four obligations still hold.
  Settled by one authenticated read of a real payment object, which requires live traffic this design
  does not create.
- **U-4 — which event carries a payment-link id is not confirmed.** §7.2's resolution order exists
  precisely because it is unverified whether `payment.captured` for a payment-link payment carries the
  link id, the backing `invoice_id`, or neither. The design fails closed if none resolves. Settled by
  one real `payment_link.paid` delivery, or by Razorpay's current API reference.
- **U-5 — the zero-row measurements are dated.** `PaymentsTable` / `InvoicesTable` / `OrderTable` at 0
  rows is from 2026-09-23 and was not re-measured by the audit or by this design. §5.3 makes a
  read-only `--select COUNT` on all three a **precondition** for the fail-closed switch on the inbound
  WhatsApp path, because that is the one change here that could alter the handling of existing data.
- **U-6 — multiple captures on one order classify as `TRANSIENT`.** `razorpay_verify` raises
  `RazorpayUnavailable("multiple captures require reconciliation")`, which maps to
  `PROVIDER_UNAVAILABLE` and therefore retries. That is wrong in kind — two captures will not become
  one — but giving it its own outcome means a new constant and a new classification, and the
  consequence today is bounded by `MAX_AUTO_ATTEMPTS` before it reaches a human. Recorded as a
  deliberate deferral, severity LOW. The clean fix is a `MULTIPLE_CAPTURES` outcome in
  `PERMANENT_OUTCOMES`; a reviewer may reasonably ask for it now.
- **U-7 — `appliedTopups` grows without bound.** ~10,000 top-ups per wallet against the 400 KB item
  limit. Known, stated, archival deferred. Severity LOW.
- **U-8 — no live verification of anything here is possible within this instruction.** No live payment
  is taken, no deploy happens, `live` stays at v45. Every claim in this design is `SOURCE` or
  `TESTED_OFFLINE` at best. In particular, `PaymentRecoveryTable` does not exist until
  `provision_payment_recovery_table.py` runs, and creating it is an additive change a later step
  performs and verifies.
- **U-9 — the `requirements.md` edit touches a file another session is modifying.** §PON-7 is one
  edit to two lines. It must be committed with `git commit --only` on explicitly named paths, after
  re-reading `git status --short`, per the parallel-sessions rule that was proved twice.
- **U-10 — the inbound WhatsApp fail-closed switch is a behaviour change on a money path.** Called out
  in §5.3 rather than buried. It removes `PAYMENT_LOOKUP_REQUIRED` and its default-permissive branch.
  If the owner wants that staged behind a flag instead, this is the decision to revisit, and it is the
  only item in this design where an owner preference could reasonably override the brief.

## 17. Out of scope

Not touched by this design, and listed so a later step does not claim them: the website Razorpay
initiation and callback (the checkout workstream), customer authentication / profile / session
ownership, the GST and convenience-fee calculation and the immutable purchased snapshot's *contents*,
Wix order writeback being *enabled*, cart completion's Wix contract, receipt generation and delivery,
the Material ESM component work, `/cart/` and `/account/sign-in/` serving 200 against 404 APIs
(audit N1 — frontend/auth workstreams), the public-page UI, deployment, and the EventBridge schedule
for the recovery sweep.

## 18. Landing sequence

Ordered so the tree is green at each step and nothing foreign is ever staged.

1. `money` / `payment_attempt` / `order_keys` contract additions + their tests.
2. `capture_authority` + `recovery` modules + their tests (pure, offline, no caller yet).
3. `razorpay_verify` binding and vocabulary changes + `tests/test_razorpay_binding.py`.
4. `order_creation` taxonomy + `disposition` + tests.
5. `finalization` stage ladder + `side_effect_guard` effects + tests.
6. `initiation.bind_gateway_order` seam + its fixture test.
7. `tests/payment_fixtures.py` + the two-table rework of the two failing modules. **Full suite green
   here, including `test_reconciliation_cannot_charge_the_customer`, before step 8.**
8. `razorpay-webhook/handler.py` disposition routing, legacy provenance, wallet path, recovery intake,
   internal sweep action.
9. `partner-onboarding` intent write + `partner_billing.credit_topup_once` + tests.
10. `inbound-whatsapp-handler` migration — **only after** the U-5 row counts are measured and recorded.
11. `invoice-engine` one-line gate + the extended AST gate.
12. Comment and spec corrections (PON-5, PON-6, PON-7), `config/lambda-env-manifest.json` entries for
    `ORDERS_TABLE`, `COMMERCE_KEYS_TABLE`, `PAYMENT_ATTEMPTS_TABLE`, `PAYMENT_RECOVERY_TABLE`,
    `RAZORPAY_SECRET_ID` (names only, never a value), and an **appended** row in
    `docs/execution/change-authority-matrix.md`.
13. `scripts/provision_payment_recovery_table.py --verify`. No deploy.

Rollback at any step: the change is additive and gated. The new table is empty, the seam has no
caller, the sweep has no schedule, and `live` is still v45 — so reverting the owned files restores the
previous behaviour exactly. Any later rollback must preserve verified paid evidence and disable new
initiation first, never the other way round.




