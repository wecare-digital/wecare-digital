# WECARE.DIGITAL — Short Commerce Part 1 (30 October 2026)

## Purpose

One reviewed product, quantity one, paid through an existing website or WhatsApp
rail. A single ProductsTable-authoritative amount and verified payment continue
through the existing PaymentAttempt → Order → Invoice/fulfillment workflow.

**Bounded change:** storefront/client cart, its two buttons and the old chooser
route. This change does **not** touch, redeploy or migrate the frozen WhatsApp
native-payment, Razorpay, capture verification, reconciliation or invoice rail.

## Findings

- The browser cart already forces an individual product line's quantity to 1.
  But `addItem`, `setContribution` and `setServiceLine` could preserve multiple
  different lines in one browser cart.
- `/cart/` could route via `/checkout/` to choose a rail and return to `/cart/`.
  The checkout already supported both actions: `prepare` for website and
  `create` for WhatsApp. The extra page was navigation, not a payment necessity.
- Prices shown in the browser are display-only. Outgoing checkout lines contain
  catalog item/variant references and quantity only. The backend is unchanged.

## Part 1 behavior

1. A product, contribution or service entry point chooses exactly **one**
   unpaid browser cart line with **quantity 1**, replacing earlier browser
   selections. The cart shows the new selection for review before payment.
   Service intents remain stored separately; checkout only sends an intent
   matching the selected service variant.
2. A legitimate older browser cart with multiple lines stays **visible**.
   The two payment buttons are disabled and the customer is told to remove
   extra lines; no item is arbitrarily dropped or priced during checkout.
3. A WhatsApp basket claim containing **more than one line** or any line whose
   quantity is not exactly 1 is not partially imported into browser checkout.
   Existing claim-recovery copy is displayed. The server's existing claim
   evidence is not rewritten by this UI change.
4. On `/cart/`, customers explicitly select **Pay here** (unchanged website
   `prepare` → Razorpay Standard Checkout) or **Pay on WhatsApp**
   (unchanged `create` path). There is no second payment-method page.
   The existing WhatsApp OTP sign-in, address/profile readiness,
   idempotency key, retry/rotation guard, verified-capture flow and status
   handoff remain as they were.
5. Legacy `/checkout/` navigation returns to `/cart/` without starting a
   payment. The fallback text link works when JavaScript navigation fails.

## Acceptance and release-scoped validation

The historical JavaScript and Python test suites were retired. Do not restore them
or their workflows. Follow `docs/operations/repository-validation.md`:

```sh
npm run typecheck
npm run build
python3 scripts/checkout_release_check.py --export-dir out
```

Manually review single-product selection, fixed quantity, service flows,
WhatsApp claims, legacy cart handling, server-authoritative pricing and
the existing payment refusal/authorization boundaries before release.

## Explicit non-goals / remaining go-live gates

- **Not a global server-side single-product rule.** The signed-off inbound
  WhatsApp catalog/cart rail and checkout server currently retain their
  existing basket contract. Any global authoritative rejection of multi-line
  or multi-unit paid intents requires a **separately reviewed, provider-tested
  commerce-boundary change**, not a silent modification to the frozen
  payment path.
- No amount is calculated from the client display string. ProductsTable
  remains the price authority; taxes, adjustments and provider capture are
  unchanged.
- No real-money E2E test, customer message, invoice or deployment is part of
  this PR. Before website release: stage on an authenticated test customer,
  verify each channel's payment initiation, provider-captured amount,
  PaymentAttempt, order status, invoice, retries and missing-address refusal.
- The previously identified published Pickup Flow completion payload is
  missing required pickup fields. This Part 1 storefront simplification
  does not override that fulfillment block.

## Rollback

Revert the frontend commit(s) or PR; `/checkout/` may be restored as a
chooser. No database migrations, schema changes, payment-provider changes or
new AWS resources are required.
