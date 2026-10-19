# Payment → Order → Customer unification: production runbook

The code in PR #903 (and the hardening in #900) is the reversible, tested half. This runbook is
the half that touches live infrastructure and a real production payment, so it is executed by an
operator with AWS access, not on autopilot. Each step is idempotent or gated; do them in order.

Context: an order has ONE identity namespace across channels (the `order_keys` CommerceKeys chain
mints `orderId`/`orderNumber` once), and both order-creation paths now write `contactId` and the
public `customerUuid`. What remains is making the live index carry those fields, deploying the
handlers, and recovering the one stranded paid order.

## Step 3 — create and backfill the v2 customer-history index

The website `/my-orders` query is served from `customerId-createdAt-index` (v1), whose projection
is immutable and does not carry `channel`/`customerUuid`. `customerId-createdAt-v2-index` adds
both. A GSI projection cannot be edited in place, so v2 is a NEW index created beside v1 while v1
keeps serving.

```sh
# Preview the index + IAM changes without mutating anything:
python scripts/provision_customer_orders.py --dry-run

# Create the v2 index (one GSI op at a time; the script waits for ACTIVE):
python scripts/provision_customer_orders.py --create-v2-index
```

- Only ONE GSI operation may be in flight on a table; the script polls `describe_table` for
  ACTIVE (`INDEX_POLL_SECONDS`/`INDEX_POLL_ATTEMPTS`).
- Until v2 is serving, `channel` reads as `website` and `customerUuid` as `''` off v1 — the page
  is correct, not broken.
- DynamoDB backfills a new GSI automatically; wait until `describe_table` reports the index
  `Backfilling: false` and `IndexStatus: ACTIVE` before the repoint below.

## Step 3b — repoint the serving index (GATED on ACTIVE)

```sh
# Refuses unless describe_table reports v2 ACTIVE; nothing else moves the serving index.
python scripts/provision_customer_orders.py --repoint-serving-index
```

This sets the live `customer-orders` function's `ORDERS_BY_CUSTOMER_INDEX` env to the v2 name. A
Query against a CREATING index raises `ResourceNotFoundException` → the handler returns 503, so
repointing early would take every order history down for the backfill. The gate prevents that.

## Step 4 — deploy the handlers and move the :live aliases

The PRs change three runtime functions: `wecare-invoice-engine` (#900), `wecare-outbound`/
`wecare-plivo-answer` (#900), and `wecare-customer-profile` + `wecare-customer-orders` (#903).

```sh
# Validate packages + config sync WITHOUT mutating (dry run first):
python scripts/deploy_all_lambdas.py --dry-run \
  wecare-invoice-engine wecare-razorpay-webhook wecare-plivo-answer \
  wecare-customer-profile wecare-customer-orders

# In an authorized rollout, run the same command without --dry-run. Publication detects
# changed code even when the hash is unchanged, and moves the :live alias per function.
```

Confirm each function's published version and that `:live` points at it before customer traffic
exercises the new paths.

## Step 5 — recover the existing ₹4.67 paid attempt

A native-leg paid attempt (`verifiedCapturedPaise == 467`) whose projection did not complete is
either quarantined (`PAID_ORDER_PROJECTION_FAILED` in CommerceKeys) or projected but stranded at
`finalizationStage == NEEDS_CUSTOMER_LINK` (visible in the phone-keyed Flow picker, invisible to
website history until linked).

1. **Locate it.** Find the paid `PaymentAttempt` with `amountPaise == 467` /
   `verifiedCapturedPaise == 467` in `stack-wecare-digital-PaymentAttemptsTable`; note its
   `referenceId`, `verifiedProviderPaymentId`, and whether it already carries `orderId`.
2. **Resolve its claimed order.** `order_keys.resolve_order_for_payment(CommerceKeys, attemptId)`
   (or `resolve_order_for_provider_payment` by the provider payment id) gives the claimed
   `orderId`/`orderNumber`. The claim is immutable and already minted.
3. **Re-drive the capture.** Replay the original Razorpay `payment.captured` webhook event for
   that payment (or re-invoke the webhook with the reconstructed `outcome` carrying
   `hasOrder=True`, the claimed `orderId`/`orderNumber`, `providerPaymentId`,
   `checkoutMode == WA_NATIVE_CHECKOUT_MODE`, `customerUuid`, `invoiceId`). This runs
   `_materialize_paid_invoice_order → paid_invoice_order.build/store`, which is idempotent on
   `orderId`: it projects the order (now WITH `customerUuid`) or promotes it if the contact has
   since linked. Re-driving cannot double-create or double-charge — the claim and the
   `attribute_not_exists(orderId)` put are the guards.
4. **Verify** in three places:
   - **Staff orders**: the order appears in the OrderTable-backed staff/CRM surface.
   - **Website history**: after the contact verifies its website account (which now runs the
     link-time promotion sweep from PR #903), the order appears in `/my-orders`.
   - **Flow picker**: `fetch_orders_for_flow(phone)` lists it by phone (it already did if the
     order was projected at all).

## Rollback notes

- The v2 index is additive; deleting it reverts to v1 with no data loss (the serving-index env
  must be pointed back to v1 first).
- The handler deploys are version-published; moving `:live` back to the prior version reverts
  behaviour.
- Nothing in step 5 deletes or mutates money state — it only completes order/attribution links a
  capture already earned.
