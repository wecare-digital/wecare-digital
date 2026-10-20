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

1. **Deploy** the fixed `wecare-razorpay-webhook` package and verify the `:live`
   alias serves the latest package.

2. **Direct-invoke the IAM-only quarantine redrive** on the existing captured
   reference/payment:

   ```json
   {"internalAction":"redriveQuarantinedCapture","referenceId":"WD-PAY-C98523E305EE4747","paymentId":"pay_Tq0awsJn5nCvE8"}
   ```

   This action is deliberately narrower than an arbitrary replay. It refuses HTTP
   envelopes, requires the existing unresolved `CAPTUREQUARANTINE#<paymentId>`
   row, requires the matching `PAYREF#<referenceId>` reservation, and loads the
   original `payment.captured` body only from the durable Razorpay webhook audit
   table. The caller cannot supply or alter the webhook body.

   The stored audit receipt is still **not financial authority**. The ordinary
   captured-payment handler runs unchanged and re-reads both authorities before
   accepting paid state: Meta supplies the native payment binding and Razorpay is
   queried for the captured payment/amount. The action marks the quarantine
   `RESOLVED` only after the provider payment claim/order exists, the payment
   attempt carries `PAYMENT_PAID` + the matching provider payment id, and the
   linked invoice reads `paymentStatus=paid`.

3. **If** the redrive wrote the binding/order claims but projection was interrupted
   afterward, the older projection-only action remains valid:

   ```json
   {"internalAction":"recoverPaidInvoiceOrder","referenceId":"WD-PAY-C98523E305EE4747"}
   ```

   It resumes from already verified stored evidence. It cannot bind an unverified
   capture from scratch.

## Why provider redelivery is no longer the operator procedure

The original version of this runbook said to request Razorpay redelivery first.
That was incomplete: the old quarantining path returned normally, so the webhook
dedup lease was completed. A later delivery of the same
`pay_Tq0awsJn5nCvE8:payment.captured` event can therefore be acknowledged as
`already_processed` before reaching the repaired parser.

The IAM-only `redriveQuarantinedCapture` action closes that gap without deleting
or weakening the webhook dedup marker. It reuses only a payload that already
passed the production webhook signature check and was stored in the audit table,
then re-runs current provider verification. No new payment request is sent and no
new capture is initiated.

## Ordering constraint (critical)

`recoverPaidInvoiceOrder` still requires a stored verified provider payment id /
captured amount and matching order/provider claims. For this incident those did
not exist after the old parser failure, so the new quarantine redrive is the
correct first recovery action. Do **not** hand-write bindings, provider claims, or
invoice paid state.

## Recovery entrypoints

- `redriveQuarantinedCapture`: authoritative single-capture recovery from
  durable quarantine + stored signed audit receipt; performs current Meta +
  Razorpay re-verification.
- `recoverPaidInvoiceOrder`: projection-only recovery after verified paid
  evidence and claims already exist.
- `reconcileCustomerOrderLinks`: unrelated broader customer/order-link sweep.

## Safety note

Do **NOT** resend the payment request. Do **NOT** pay again. The payment was
captured at `03:08:35Z`; `MetaBindingUnavailable` was a read failure on our side,
never a "not paid" signal. Every step above is idempotent and side-effect-safe.
