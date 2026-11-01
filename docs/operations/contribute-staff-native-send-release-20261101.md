# Admin Contribute ₹300 native WhatsApp payment — release gate

**Stage:** Source implementation and focused tests. **No live customer send is authorized by this document.**

## Staff experience

Workspace **Pay & Flow → Contribute** provides customer lookup, an internal draft,
image inspection and exact-price review. The **Send ₹300 Review & Pay** action
becomes enabled only after:

- The selected ContactsTable row is active and linked to one verified customer.
- The fetched contribution catalog quote reads exactly 30000 paise (one
  `CNT5Q2M8` unit) with **zero** supply GST, Delight, added Express fee,
  convenience fee and GST on convenience fee.
- The existing native Meta payment template has been read back as APPROVED with
  its IMAGE header and native ORDER_DETAILS button.
- The Admin-only Commerce readiness action on the *deployed Lambda alias*
  reports `STAFF_CONTRIBUTE_READY`, `sendEnabled=true`, `amountPaise=30000`
  and `currency=INR`. Any unknown or failed read disables Send.
- Staff explicitly confirm the exact saved recipient and amount.

After confirmation the UI makes **one POST only**. A timeout, 502 or unknown
outcome is **never** automatically retried. The UI locks that attempt and
requires reconciliation against WhatsApp and the payment ledger.

## API contract

Endpoint: `POST /ecommerce/checkout` with Admin staff access token.

Read-only probe:
```json
{"action":"staff-contribute-readiness"}
```

Initiate one payment:
```json
{"action":"staff-contribute-send","contactId":"<canonical ContactsTable id>"}
```

The server **refuses all extra fields** on Send. Staff can never supply a
product id, price, amount, discount, phone, sender, payment configuration,
Meta template, or shipping address. The server reads the live SKU/price,
resolves permanent customer identity, verifies existing WhatsApp linking,
and re-prices again immediately before any reference/PaymentAttempt write.

The send reuses the canonical Meta ORDER_DETAILS payment sender and the
conditional `WACARTLIVE#` slot shared with inbound cart messages.
A second live request for the same customer and SKU is refused or must be
reconciled before a new send. The provider's accepted send is not proof that
the customer received it or paid.

The new SKU-first contribution settles through the **ordinary catalog
order + capture + receipt** path. Do NOT label the gateway request with
historical `notes.purpose=BLOG_CONTRIBUTION`; this would route the webhook
to the retired special-capture handler. Do NOT issue a Vault entitlement or
conflate this payment with a GST-taxable service.

## Production fail-closed feature switch

`STAFF_CONTRIBUTE_NATIVE_SEND_ENABLED` is read by `wecare-commerce` and
defaults to **OFF** (unset or any value other than the literal `true`).
The staff UI does not trust its own bundle version: it reads the protected
Commerce alias to determine whether sending is genuinely enabled. A merged
frontend or changed ProductsTable price alone cannot enable it.

Do not set the switch to true until all conditions are proven:
1. Finance approves how the internal **₹15 Express allocation** is booked
   from the customer's ₹300. There is no charged Express line and no GST,
   Delight or convenience fee under the current voluntary-contribution
   policy. The payment ledger currently represents a single ₹300 Contribute
   SKU; an internal ₹285/₹15 accounting split must not be claimed as a
   separately booked ledger allocation unless implemented and reconciled.
2. Review and deploy the exact checkout backend and packaged
   `staff_contribution.py` module to a **published, immutable Commerce
   version**, then point the `live` alias at it with a rollback version.
   Verify the release environment and IAM against the approved manifest.
3. Re-read the live `ProductsTable` row `CNT5Q2M8` at exactly
   30000 paise, and confirm the backend Admin readiness/quote response.
4. Independently verify the existing provider payment configuration,
   payment sender identity, Meta approval, header image, item thumbnail
   and verified customer identity. Do not invent a test number.
5. Perform authorized **QA-only** request with permitted recipient,
   exact Review & Pay order details, capture-to-ledger reconciliation,
   acknowledgement, duplicate/refusal behavior, and correct no-double-send
   treatment of timeouts. No unsolicited live customer payments.
6. Validate both desktop and mobile staff screens, authorized and
   unauthorized sessions, an old-alias mismatch, and a mid-send price
   change. Keep the feature flag off on any uncertainty.

**Rollback:** Disable the release flag / return the alias to the prior
published version and keep the UI send button blocked via readiness.

## CI checks

`tests/staff_contribute_native_send_contract.test.mjs`,
`tests/pay_contribute_staff_controls.test.mjs`,
`tests/pay_contribute_300_preview.test.mjs`,
`tests/contribution_checkout_300_contract.test.mjs`,
`tests/test_staff_contribution_guard.py`,
`python -m py_compile` and `npm run typecheck`.

These checks establish source correctness, **not** that a WhatsApp message
was delivered or a Razorpay payment was captured.
