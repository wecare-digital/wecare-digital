# Short Commerce Part 1 — unified single-item checkout audit, change contract and rollout

Date: 2026-10-30. Owner request: one product per transaction, quantity one, fewer
website screens, both native WhatsApp/catalog and website payment choices, a single
server-authoritative final payable, and verified payment -> order -> invoice/fulfilment.

**State:** implementation is in a review branch, **NOT deployed** by this document.
The payment rail is signed-off/frozen: see
[`docs/operations/whatsapp-payment-collection-stack.md`](../operations/whatsapp-payment-collection-stack.md)
and [`docs/execution/payment-order-customer-unification-runbook-20261019.md`](payment-order-customer-unification-runbook-20261019.md).
This is an explicit contract-change proposal/RFC for review; do not silently push
any payment Lambda, alter live aliases, or enable the flag merely because this PR merges.

## Verified findings

- GitHub: `wecare-digital/wecare-digital`, production branch `wecare.digital`.
- AWS read-only check, account `775261844268`, `us-east-1`, 2026-10-30:
  `wecare-commerce:live`, `wecare-checkout:live`,
  `wecare-razorpay-webhook:live`, `wecare-inbound-whatsapp:live`,
  `wecare-outbound-whatsapp:live`, `wecare-invoice-engine:live` all active.
  `WA_CATALOG_ORDERS_ENABLED=true` and `WHATSAPP_CATALOG_SERVICES_ENABLED=true`
  on the active commerce and checkout Lambdas. Eight inspected payment CloudWatch
  alarms were `OK` at read time; this does **not** replace transaction reconciliation.
- Meta app `2238810740192680`: live, compliant, with WhatsApp messaging,
  management and event privileges. **`catalog_management` was rejected** in the
  app privilege read: do not promise new Meta catalog write automation until
  permission is granted, or rely on the existing catalog's purchase capability
  as proof of that separate permission.
- Wecare.Digital verified WhatsApp business: active phone +91 93309 94400, webhook
  subscription configured, app published, messaging billing method present.
  Approved utility templates include
  `wecare_whatapp_native_pay_template` with native `ORDER_DETAILS` /
  **Review and Pay**, and `wecare_default_invoice_image_template`.
  A WhatsApp **messaging billing method is not evidence of buyer payment settlement**.
- Existing production payment runbook records a successful real-money payment
  and invoice/message path on 2026-10-26. Do not construe that historical test
  as a new end-to-end checkout test on this branch.
- Existing frontend sends catalog reference + quantity, never client price.
  Python `catalog_pricing` and `checkout_pricing.compute_quote` supply the
  approved INR paise total AFTER policy discounts and supply tax/delivery and
  ADD convenience fee and its GST as applicable; both rails retain their own
  provider identity and readback/capture verification.
- Current customer journey before this proposal:
  product -> /cart/ -> /checkout/ payment chooser -> /cart/ payment initiation ->
  /checkout/status/ -> owned order. This duplicates the cart step.
- Existing native catalog parser permits several lines and quantity >1, even
  though individual website product lines already fix their quantity to one.

## Part 1 change boundary

1. **Single selection, no silent conversion.**
   The website browser cart selects exactly one product/variant. Selecting a new
   product, contribution or service replaces the unpaid selection, never increments
   quantity. Existing legacy multi-line localStorage carts remain visible until
   the customer removes lines; they are never truncated during payment.
   A multi-line WhatsApp hand-off is not silently converted to a different order.
2. **Short checkout.** The /cart/ review now shows both **Pay on WhatsApp** and
   **Pay on website**. No redirect through /checkout/ for the ordinary journey.
   /checkout/ is retained for old deep links/bookmarks and uses the existing
   `takePendingAction` channel-return contract.
3. **One authoritative payable.** Both buttons call the existing
   `prepare-checkout` path with an explicit channel. No checkout amount,
   tax rate, discount or gateway reference is generated in JavaScript.
   Provider/native ORDER_DETAILS uses the frozen backend quote; Razorpay
   Standard Checkout uses the same backend calculated integer-paise total.
   The catalog list price is explicitly **not** a guaranteed final total.
4. **Native short purchase safeguard (opt-in):**
   `SHORT_COMMERCE_PART1_ENABLED` defaults OFF.
   When enabled on the corresponding published Lambda versions:
   - Meta order input with more than one item, quantity other than one, malformed,
     partially unresolved or clamped items receives a clear refusal, before a
     message index, payment attempt, quote or order is created.
   - Native cart invoke with a multi/quantity basket refuses before its live slot.
   - Browser website prepare refuses multi/quantity before pricing or writes.
   - A historical WhatsApp basket claim refuses before modifying the saved cart
     or consuming the one-time hand-off, returning `BASKET_SHORT_ONLY`.
   - A pre-existing pending WhatsApp address-confirmation cart is rechecked
     before sending a native payment request.
   - These are *preconditions* only, not a second payment system.
5. **Payment outcomes and fulfilment remain authoritative.**
   The existing /checkout/status/ is the primary paid/pending/failed customer
   screen and checks the signed-in customer's attempt. /checkout/success/
   is retained for compatibility and checks an authenticated paid status.
   The website cart is cleared **only** on verified capture for the owned attempt.
   A pending, ambiguous or delayed send must NEVER show success or ask for an
   immediate second payment. Server-side verified payment proceeds through
   the existing one-order, invoice asset, WhatsApp status and utility invoice
   template pipeline. Product/service-specific *offline fulfilment* still
   requires an operator/workflow assignment: do not confuse invoice delivery
   with goods/service fulfilment. A new fulfilment Flow is **not activated** here.
6. **No multi-bag UI.** Meta's catalog interface may still display the
   platform-provided cart/multi-quantity controls; this proposal can reject
   those selections server-side but cannot remove native Meta client controls.

## Acceptance checks before flipping the backend flag

- Execute `python -m unittest discover -s tests -p test_short_commerce_part1.py`
  and full existing checkout, catalog-service, WhatsApp inbound and frontend
  release checks in CI with the approved Node/Python toolchain.
- Check legacy cart A+B shows both lines, no amount is sent and a clear refusal
  appears. Selecting C produces exactly one line. Existing single-item SKU,
  merchandise variant, contribution and service intent remain payable.
- Website /cart/ shows two real working buttons; after an OTP sign-in or saved
  address it continues with the chosen channel and does not initiate twice.
- Native Meta catalog sends: (1) single product/one unit -> existing
  ORDER_DETAILS; (2) two products -> refusal/no PaymentAttempt; (3) quantity
  two -> refusal/no PaymentAttempt; (4) duplicate SKU -> refusal; (5)
  partially unresolved item -> refusal; (6) replayed webhooks -> one attempt.
  Test WhatsApp number/country eligibility and the actual native provider
  payment options before claiming every option is available to every customer.
- For BOTH rails, compare stored checkout quote, payment request, captured
  provider amount, final order amount, invoice total and any discount/fee/GST
  split exactly in integer paise. Include fully discounted/zero-total orders.
- Validate all outcomes: captured+paid; provider rejected; user cancelled;
  timeout/ambiguous; late webhook; repeated callback; paid invoice send failed;
  manual re-drive; refund. No double charge, no unpaid success screen.
- Verify fulfilment choices per product/variant: physical order to offline
  fulfilment queue with status tracking; service/digital to approved delivery
  Flow when applicable; invoice-only when no Flow is required. Invoice sending
  must remain idempotent and message templates approved. Do not send test
  messages to real customers without explicit approval.
- Read back Lambda aliases and environment variables on *every* receiver,
  exercise staging with non-customer test data, verify alarm state,
  and perform operator-approved canary real payment with readback.
  No production alias updates/flag flips until owner sign-off.

## Rollout and rollback

1. Approve contract change to the previously frozen mixed-basket behavior,
   including contribution/service purchasing, WhatsApp catalog refusal copy,
   and the business impact of refusing baskets >1.
2. CI/staging deploy with `SHORT_COMMERCE_PART1_ENABLED=false` on
   `wecare-checkout`, `wecare-commerce`, and `wecare-inbound-whatsapp`.
   Confirm the new code is present on staged aliases and that disabled
   mode matches the legacy server behavior.
3. Rehearse enabled mode in isolated staging, confirm exact pricing parity
   and post-paid invoice/fulfilment outcomes. Explicitly verify native catalog
   actions for India and Meta account entitlement.
4. Only after payment-rail owner approval, enable one common flag on the
   vetted published Lambdas and canary customer access. Monitor existing
   payment, reconciliation, delivery and API 4xx/5xx alarms and metrics.
5. Rollback the new backend guard by restoring the flag to false on the
   vetted versions; for the website review screen, revert the frontend
   release through the normal static publish/rollback pipeline. Do not
   delete payments, rewrite paid attempts, or disable signed webhook receipts.

## Known gaps / outside Part 1

- **Not yet deployed, no new live payment executed in this PR.** No native
  payment or template message sent by this work.
- Meta `catalog_management` rejected; separate permission work required to
  modify/sync catalogs through that privilege. Existing connected catalog may
  still work.
- Native Meta catalog controls are outside the website's UI: their
  multi-quantity controls cannot be hidden from this code, only refused.
- Individual service/physical/digital fulfilment Flow mapping, operator
  hand-off, stock reservations and courier integrations are not automatically
  completed by a checkout UI change. Preserve invoice delivery but verify
  each SKU's fulfilment contract before launching it as automatic.
- Customer-facing exact net payable is shown through the provider's hosted
  or native payment presentation; the static cart intentionally does not
  invent a quote. A separately requested server quote preview would need a
  read-only authenticated quote endpoint, checksum and expiry contract.
- The repository's referenced `.kiro/steering/00-common.md` was unavailable
  during connector fetch; reviewers must apply any separately maintained
  organization rules before merge.
