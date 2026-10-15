# Commerce implementation audit — order-after-payment architecture

Audited 2026-09-30 against branch `stack`. Required by §64–66 of the master prompt: audit before
code. Every count was measured; the commands are named so each can be re-run.

## The headline, and it changes what work remains

**The backend transaction model the prompt specifies is already implemented, and it already
enforces the non-negotiable rule.** §3's "there is no order until payment is confirmed" is not a
change to make — it is the current, tested behaviour. **What is missing is the customer-facing
frontend**, which does not exist at all.

So §65's "OLD BEHAVIOR TO REMOVE — do not create order identity before payment" has **nothing to
remove**. I looked for a pre-payment order number and there isn't one.

| Area | Status |
|---|---|
| Payment-attempt entity and state machine (§15, §24) | **IMPLEMENTED + VERIFIED** |
| Order-only-after-paid gate (§3, §19) | **IMPLEMENTED + VERIFIED** |
| `orderId` UUIDv7 + 12-char `orderNumber` (§20, §21) | **IMPLEMENTED + VERIFIED** |
| Provider-verified reconciliation (§33, §34) | **IMPLEMENTED + VERIFIED** |
| Amount/currency integrity in paise (§26) | **IMPLEMENTED + VERIFIED** |
| Meta `reference_id` model (§17) | **IMPLEMENTED + VERIFIED** |
| Razorpay webhook auth + dedupe (§30, §33) | **IMPLEMENTED + VERIFIED** |
| WhatsApp OTP (§8) | **IMPLEMENTED** (Cognito CUSTOM_AUTH) |
| OTP challenge store, hashed + peppered (§8) | **IMPLEMENTED** |
| Email OTP send from `one@wecare.digital` (§9) | **PARTIAL** — primitive exists, send path does not |
| Storefront cart/checkout API (§14) | **IMPLEMENTED** since this audit — native `wecare-checkout` (`/ecommerce/checkout`, `/ecommerce/prepare-checkout`, `/ecommerce/verify-callback`), `CartTable`, `ProductsTable` pricing |
| Customer checkout UI, 12 steps (§4, §12) | **NOT IMPLEMENTED** |
| Website payment states (§28) | **NOT IMPLEMENTED** |
| Retry UX (§29) | **NOT IMPLEMENTED** |
| Order tracking page (§42) | **NOT IMPLEMENTED** |
| Payment history vs order history (§43, §44) | **NOT IMPLEMENTED** (frontend) |

---

## 1. Existing reusable code — do not rebuild

### `amplify/functions/shared/lambda_utils/ecommerce/payment_attempt.py`

The entity §15 asks for, already built. Measured constants:

```python
CREATED, PAYMENT_READINESS_CHECKED, PAYMENT_REQUEST_SENT, PAYMENT_PENDING,
PAYMENT_PAID, PAYMENT_FAILED, PAYMENT_CANCELLED, PAYMENT_EXPIRED

ORDER_ELIGIBLE_STATES = frozenset({PAYMENT_PAID})          # §19, §24
RETRYABLE_STATES      = {PAYMENT_FAILED, PAYMENT_CANCELLED, PAYMENT_EXPIRED}   # §29
```

Functions to reuse rather than reimplement: `build()`, `next_retry(previous, reference_id=…)`
which carries `retryOf` lineage (§29), `may_create_order(attempt)`, `may_retry(attempt)`.

It also has something the prompt does not ask for and should keep: an `attemptRank` monotonic
guard where `PAYMENT_PAID: 100` outranks every failure, so a late-arriving `FAILED` webhook cannot
demote a paid attempt. That directly serves invariant §49.8.

### `.../ecommerce/order_keys.py`

§20 and §21, already built:

```python
PUBLIC_ORDER_NUMBER_LENGTH   = 12
PUBLIC_ORDER_NUMBER_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"   # excludes 0 O 1 I L exactly as §20 asks
ORDER_NUMBER_PREFIX          = "ORDERNO#"                          # §21's conditional reservation
META_REFERENCE_ID_MAX_LENGTH = 35
REFERENCE_ID_PREFIX          = "WD-PAY-"
```

Its own header already states the split the prompt specifies: `orderId (UUIDv7) + orderNumber
(12 chars, public)`, and notes the public number is "deliberately NOT time-ordered".

### `.../ecommerce/order_creation.py`

`reconcile_payment()` is §34, and the key design detail is that **provider verification is
injected**, with the docstring stating `verify_payment(reference_id)` "must ask the **provider** —
not a webhook body". Order of checks, measured: currency equality first (because "a mismatch makes
the amount comparison meaningless"), then integer-paise exact amount, then customer, then
`may_create_order` as the single decision point — "so this cannot drift from
`ORDER_ELIGIBLE_STATES` even if that set changes."

Non-integer stored amounts are rejected rather than coerced, which satisfies §26's fail-closed
requirement including the ₹0.01 case.

### `amplify/functions/payments/razorpay-webhook/handler.py`

§33 in order: `_verify_signature` (fail-closed), `_is_duplicate_event`, then
`_create_order_for_captured_payment` which calls
`razorpay_verify.verifier_for_event(...)` → `order_creation.reconcile_payment(...)`. The webhook is
a signal to verify, not proof — exactly §33.6.

### Other reusable pieces

| Need | Existing |
|---|---|
| OTP issue/verify, hashed + peppered, TTL, attempts | `lambda_utils/otp_challenge.py` |
| WhatsApp OTP delivery | `auth/customer-whatsapp-auth/` (Cognito CUSTOM_AUTH, `wecare_otp`) |
| Idempotency | `lambda_utils/idempotency.py`, `WebhookDedup` table |
| Amount readiness check | `lambda_utils/payment_readiness.py` |
| Payment status mapping | `lambda_utils/payment_status.py` |
| Invoice/receipt | `payments/invoice-engine/` |
| Receipt links | `lambda_utils/receipt_links.py` |
| Native pricing, cart and stock | `.../ecommerce/catalog_pricing.py`, `checkout_pricing.py`, `native_cart.py`, `native_inventory_txn.py` |
| Customer identity | `lambda_utils/customer_auth.py` |

### Test coverage already in place

`pytest --collect-only -k "payment or order or checkout or razorpay or otp"` selects the
payment and order suites. Named files include `test_order_creation.py`, `test_payment_attempt.py`,
`test_order_keys.py`, `test_payment_reconciliation_safety.py`,
`test_razorpay_webhook_order_creation.py`, `test_payment_readiness.py`, `test_otp_challenge.py`,
`test_payment_vocabulary_at_decision_points.py`.

**So most of §50–§59 already has coverage.** The audit's job is to find which invariants are *not*
asserted, not to write them all fresh.

---

## 2. What is genuinely missing

### a. The entire customer frontend (§4, §11, §12, §13, §27–§29, §42, §43)

Searched `src/pages` for checkout, cart, product and account routes. Found **none**. What exists:

- `src/pages/orders.tsx` — a public "check the status of an order" page
- `src/pages/workspace/**` — authenticated admin surfaces
- `src/pages/get.tsx` — verified-link file collection

There is no `/cart`, no `/checkout`, no `/product/[slug]`, no `/account/orders/[orderNumber]`.
**All twelve checkout steps in §12 are unbuilt**, as are the four website payment states in §28 and
the retry rules in §29.

### b. Email OTP send path (§9)

`otp_challenge.py` exists and its own docstring says: *"email verification has no implementation at
all, so it needs a store regardless."* So the **store and verify primitive exist**; what is missing
is the SESv2 send from `one@wecare.digital` with configuration set `wecare-digital`, and the branded
template.

### c. Legacy order numbers — §20's "exactly 12 characters" is true of new orders only

New, post-paid orders get a 12-character number from `order_keys.reserve_order_number` via
`order_creation` (alphabet `23456789ABCDEFGHJKMNPQRSTVWXYZ`), which matches §20.
`order_keys.is_wd_order_number()` still accepts the legacy `WD-ORD - XXXXXXXX - …` format —
note the space at index 6 — because historical orders carry it.

That is a deviation from §20's format contract that anyone writing §56's tests ("orderNumber is
exactly 12 characters, allowed alphabet only") will trip over immediately: those assertions will
fail against historical orders. Decide explicitly whether §56 applies to new orders only, or
whether legacy numbers are migrated. Do not "fix" it by loosening the 12-character rule.

### d. Storefront HTTP surface (§14) — closed since this audit

Native `wecare-checkout` now computes the authoritative total server-side from `ProductsTable`
(`catalog_pricing` → `checkout_pricing.compute_quote`, integer paise), which §13 and §26
depend on.

---

## 3. Stale spec material

`.kiro/steering/PAYMENT-AUDIT-REPORT.md` is dated **2026-03-30** and says "Razorpay + PayU Only".
§30 says **Razorpay only, do not restore PayU** — so that document is stale on gateway policy and
should be corrected rather than followed. It also pins Graph **v25.0**, which needs reverification
against current Meta docs before any payload change (§32).

---

## 4. Live prerequisites — blocking, and not code

From the spec's own open list plus this session's findings:

1. **Google Cloud production access** for `wecaredigitalbw` — unrelated to payments but blocks Ads/Search Console.
2. **Meta payment configuration must belong to the sending WABA** (§31) — verify live, do not take the value from the stale steering doc.

---

## 5. Recommended order of work

Smallest reviewable steps, reusing everything above.

1. **Assert the invariants that already hold** (§49.1–49.8) as explicit tests, before touching
   anything. If any fails, that is the real bug and it is cheaper to find now.
2. ~~Checkout read API~~ — done: native `wecare-checkout` exposes the authoritative total.
3. **Email OTP send** — wire `otp_challenge` to SESv2 from `one@wecare.digital`.
4. **Frontend, in slices**, following `.kiro/skills/new-public-page/SKILL.md` and the measured home
   design rungs: phone → OTP → name → email → OTP → address → review → pay → states → retry.
5. **Tracking and payment history pages** (§42, §43), with failed attempts never shown as orders.

## 6. Rollback

Backend changes are additive Lambda code behind existing versioned aliases — roll back by moving the
`live` alias, per `.kiro/steering/lambda-snapstart-deploy.md`. Frontend is a static export; roll back
by redeploying the previous Amplify build. No destructive vendor configuration is required for any of
the above, and none should be made to test code (§68).

---

## 7. What I have NOT changed

No code in this audit. §64 requires the audit first, and the most useful finding is that the
transaction model is already correct — so the next commit should be **tests that prove it**, not a
reimplementation of it.
