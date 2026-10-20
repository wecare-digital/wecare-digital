# Operator runbook: safe re-drive of WD-PAY-C98523E305EE4747

Operational procedure for the **owner/operator** to run against live AWS **after**
the fixed `wecare-razorpay-webhook` package is merged and deployed. This document
describes steps; it does **not** execute any AWS mutation, deploy, or re-drive.

## Incident recap (owner-confirmed)

- **Reference:** `WD-PAY-C98523E305EE4747`
- **Payment is REAL and CAPTURED:** ₹2.24.
- **Razorpay order:** `order_Tq0ZgogHP8upGD`
- **Razorpay payment:** `pay_Tq0awsJn5nCvE8`
- At `03:08:35Z` Razorpay delivered `payment.captured` correctly.
- The **OLD** parser concluded `MetaBindingUnavailable` → `PROVIDER_UNAVAILABLE`
  → the capture was placed into `NEEDS_RECONCILIATION`.
- Consequence: the invoice stayed `pending_payment`, the order was **not**
  materialized/advanced, the paid invoice was **not** delivered, and the
  order-status WhatsApp message was **not** sent.

`MetaBindingUnavailable` never meant "not paid" — it meant "we do not know". The
money was captured the whole time.

## Root cause (one line)

The parser did not read `transactions[].pg_transaction_id` and did not treat the
`order_`-prefixed `transactions[].id` as the Razorpay order id, so it extracted no
gateway binding. Fixed in `meta_payment_binding.lookup_payment()` by FEAT-001.

## SAFE re-drive checklist (operator runs AFTER merge, against live AWS)

1. **Deploy** the fixed `wecare-razorpay-webhook` package.

2. **Trigger Razorpay's own redelivery** of the existing `payment.captured` event
   for `order_Tq0ZgogHP8upGD` from the Razorpay dashboard/API. This is the
   designed recovery path and replays the notification through the fixed webhook.
   With the FEAT-001 fix, the webhook now extracts the gateway binding from Meta
   via `meta_payment_binding.bind_attempt` (the second independent authority),
   writes the **write-once** binding + reverse-unique row + verified captured
   amount + the order/provider claim, and advances. The idempotent dedup key,
   monotonic status ladder, and write-once binding make the replay safe.
   **Explicitly: Razorpay redelivery REPLAYS a notification — it does NOT capture
   again (no re-charge) and does NOT send a new payment request.**

3. **Only if** projection still needs completing after the binding + claim exist
   (for example, the redelivery was interrupted after they were written), invoke
   the existing IAM-only `internalAction` by a **direct Lambda invoke** of
   `wecare-razorpay-webhook` with the payload below. This is IAM/direct-invoke
   only — any HTTP envelope (`requestContext`/`rawPath`/`path`/`httpMethod`/
   `headers`/`body`/`Records`) is refused with `403`. It is idempotent: it resumes
   projection from verified **stored** evidence, materializes/advances the order,
   links the invoice, and delivers the paid invoice + order-status WhatsApp
   message — with **no charge** and **no send of a new payment request**.

   ```json
   {"internalAction":"recoverPaidInvoiceOrder","referenceId":"WD-PAY-C98523E305EE4747"}
   ```

   Entrypoint: the recovery arm at the top of `handler()` in
   `amplify/functions/payments/razorpay-webhook/handler.py`, which calls
   `paid_invoice_order.materialize(..., reference_id=event['referenceId'], now=...)`.

## Ordering constraint (critical)

`paid_invoice_order.materialize()` (the `recoverPaidInvoiceOrder` target)
**requires** that the attempt already carries `verifiedProviderPaymentId` /
`verifiedCapturedPaise` **and** a matching existing order claim + provider claim.
It finishes projection from that verified stored evidence; it does **not** create
the gateway binding or verify the capture from scratch.

Therefore the binding-writing step — the redelivered `payment.captured` through
the **fixed** webhook (step 2) — **must happen first**. Invoking
`recoverPaidInvoiceOrder` before the binding exists raises
`ValueError('stored payment attempt required')` (no attempt id) or
`ValueError('matching existing order and provider claims required')` (claims
absent/mismatched) and is a **safe no-op that writes nothing**.

For `WD-PAY-C98523E305EE4747` the OLD webhook ended `NEEDS_RECONCILIATION` and
wrote **no** binding and **no** order/provider claim, so `recoverPaidInvoiceOrder`
alone cannot re-drive it from scratch — step 2 must run before step 3.

**Do NOT hand-write the binding.** The only designed way to write it is a real
`payment.captured` redelivery through the fixed webhook. If the operator finds the
redelivery cannot be re-triggered for this specific event, a fresh redelivery of
the existing captured event remains the only correct path to write the binding.

## Does a suitable entrypoint already exist?

**Yes.** The Razorpay `payment.captured` redelivery path plus the existing
`recoverPaidInvoiceOrder` `internalAction` are sufficient for this single
reference. **No new broad tool needs to be built.**

Adjacent sweeps exist but are not the right tool here:
`scripts/reconcile_file_deliveries.py` and the scheduled
`reconcileCustomerOrderLinks` action handle other reconciliation (customer-order
link promotion). For a single reference, `recoverPaidInvoiceOrder` is the correct
single-reference entrypoint.

## Safety note

Do **NOT** resend the payment request. Do **NOT** pay again. The payment was
captured at `03:08:35Z`; `MetaBindingUnavailable` was a read failure on our side,
never a "not paid" signal. Every step above is idempotent and side-effect-safe.
