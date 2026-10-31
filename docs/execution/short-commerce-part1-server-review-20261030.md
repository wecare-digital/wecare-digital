# Short Commerce Part 1 — opt-in server boundary guard (PR #1965)

**Status: review only. Not deployed; default OFF.** This document is an addendum to
`docs/execution/short-commerce-part1-20261030.md`, the already-integrated
storefront implementation from PR #1964. The storefront's single product selection,
direct cart payment options, and comprehensive browser/runtime tests are kept as-is.

PR #1965 intentionally adds **only** a proposed server-side safeguard, an OTP
payment-choice continuity fix, customer copy for refused WhatsApp handoffs, and tests.
It does not replace the frozen payment calculation, provider capture, order finalization,
invoice engine, catalog sync or native Meta templates.

## Why the split matters

- The existing storefront already limits a reviewable cart to a single catalog
  product with quantity one. Meta's own catalog app, however, can still send
  multi-product and multi-quantity native order messages.
- Enforcing a global single-product rule changes the payment contract. PR #1964
  deliberately did not make that change. This separate backend policy must pass
  payment-rail owner review, Meta/provider tests, and customer-message tests
  before it is enabled.
- The native and website rails continue using `ProductsTable` ->
  `catalog_pricing` -> `checkout_pricing`; amounts are calculated in integer
  paise after permitted discounts, shipping and taxes. The same frozen amount
  must be used in WhatsApp `ORDER_DETAILS` or Razorpay, payment capture, order
  total and invoice. This PR adds **no client-side calculator**.

## Opt-in policy

Configuration name: `SHORT_COMMERCE_PART1_ENABLED`. Unset, `false`, and all
non-enabling strings are OFF. No production environment variable is changed.

In a reviewed and enabled environment:

1. `inbound-whatsapp-handler/handler.py::_handle_cart_order` refuses a raw
   Meta catalog order with more than one item, quantity other than one, unknown,
   truncated or partly parsed selections. It answers in the existing WhatsApp
   customer-reply channel **before** any money-path invocation.
2. `ecommerce/checkout/handler.py::_native_cart` independently refuses
   multi-item/quantity internal invocations before creating its payment slot,
   quote, `PaymentAttempt` or `ORDER_DETAILS`. Pending address/resume carts
   are also checked before their payment request.
3. `_website_prepare` rejects unsupported lineItems before pricing or cart
   reconciliation, with `SHORT_CHECKOUT_ONE_ITEM`. Browser selection checks
   remain first-line defense.
4. `_claim_basket` rejects an older incompatible WhatsApp basket with
   `BASKET_SHORT_ONLY` **before** a server-cart write or consuming its
   single-use claim. `src/lib/whatsappBasket.ts` displays an explicit
   retry-with-one-item instruction.
5. The storefront retains the latest base implementation. The only additional
   cart-page change persists the explicitly selected website/WhatsApp channel
   through OTP or an expired session using the existing out-of-band
   `stashPendingAction` / `takePendingAction` contract.

## Safety and validation

- Leave the flag **OFF** on all affected deployed Lambdas until the
  payment-system owner has approved the change to the signed-off native
  catalog/cart contract. Do not deploy code by updating live aliases as part
  of resolving a GitHub PR conflict.
- Follow the manual release-scoped policy in
  `docs/operations/repository-validation.md`. Run `npm run typecheck` and
  `npm run build`, then review native payment, WhatsApp inbound and invoice
  evidence through an approved non-CI verification plan. Do not recreate the
  deleted automated tests or workflows.
- Validate single item/one unit, multi-product, quantity two, duplicate SKU,
  unknown SKU, a saved pending cart, one-time handoff, expired session, and
  WhatsApp OTP channel persistence.
- Stage and verify both payment routes, including India-specific native
  payment eligibility; equal signed quote, provider amount, captured amount,
  order and invoice; zero-payable refusal, delayed webhooks, failed sends,
  idempotent replay, refund and paid-but-not-fulfilled orders.
- The eight production payment CloudWatch alarms being OK at an earlier read
  does **not** constitute proof of this release. Recheck on the actual staged
  build, and complete operator-authorized real-payment reconciliation before
  production activation.

## Fulfillment caveat

One final paid order may require physical/offline fulfillment, a service Flow,
or only an invoice WhatsApp template. The existing invoice path is preserved
but this PR does **not** create or approve SKU-to-Flow mappings or guarantee
offline fulfillment completion. The separately identified Pickup Flow payload
gap remains a launch blocker for that fulfillment path.

## Rollback

Restore the `SHORT_COMMERCE_PART1_ENABLED` flag to `false` on each reviewed
Lambda version, or redeploy its previous signed-off `live` alias after
normal release checks. Revert the extra OTP page fix independently if needed.
Do not alter captured payments, idempotency keys or paid invoice records.

No production payments, messages, AWS env settings, or Meta resources are
changed by this merge-conflict resolution.
