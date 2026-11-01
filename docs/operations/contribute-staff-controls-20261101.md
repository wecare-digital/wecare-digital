# Pay & Flow → Contribute staff-control checklist

**Status:** UI-only draft/review controls. No live native WhatsApp payment send is authorized by this feature.

## Staff workflow

1. Open `/workspace/payments?view=contribute`. The Contribute tab follows Vault.
2. Click **Refresh price, contacts & Meta**. The card reads the server's
   current Contribute price, loads staff Contacts and queries the registered
   native Meta payment template by its server-listed template ID.
3. Search Contacts and select a saved, active recipient. The client shows
   its stored phone and any phone-verification timestamp, but this is **not**
   proof of sender-side identity verification.
4. Set an optional **internal draft reference** and **internal note**.
   Neither edits the catalog item name nor the approved WhatsApp body.
   These draft fields exist only in browser memory; reloading loses them.
5. Click **Review draft** to inspect the intended recipient, fixed Meta
   body/button, proposed ₹300 total, ₹15 internal Express allocation,
   server quote match and the status of provider template verification.
6. Open **View shared payment header and order-item image**, then use the
   optional 60-second S3 GET preview to inspect the actual retained PNGs.
   Header and ORDER_DETAILS thumbnail have distinct sources.
7. Optionally **Copy internal review draft** for staff review only. This is
   explicitly marked not sendable as a customer payment request.
8. Use **Clear draft** to reset all local draft fields. Send remains
   disabled until a reviewed, purpose-specific backend exists.

## Immutable payment data

The current Contribute payment contract is `BLOG_CONTRIBUTION` with a
fee-exempt settlement. There is no additional Express line in the checkout.
The planning allocation is `₹285 contribution + ₹15 allocated internally`,
*within* the customer's proposed ₹300 total. This does not modify the real
catalog item, backend quote, receipt or accounting ledger.

The alternative Vault-style example, `₹235.41 + ₹42.37 − ₹1.38 + ₹15
+ ₹7.29 + ₹1.31 = ₹300`, is **not** a sendable contribution quote unless
Finance changes the legal/tax treatment and the canonical backend.

The browser may inspect but **must never** manufacture or override the
native Meta ORDER_DETAILS, provider payment configuration, settled amount,
shipping/tax/Delight values, or recipient.

## Last audited release state (read-only 2026-11-01)

- Frontend source PR #2092 now says ₹300. Amplify production website
  build #428 at commit `7367737af451cdebbfe10bbd38ef1ead9669c1a7` **SUCCEEDED**.
- The live DynamoDB `ProductsTable` row, product
  `24fa0f39-330b-5365-b7eb-9caf27ad37f1`, variant `CNT5Q2M8`,
  now reads `priceMinor = 30000` paise, updated
  `2026-11-01T00:44:47Z`. An earlier audit read ₹250 before that cutover.
- Production `wecare-commerce:live` remains version 178, published
  2026-11-01 00:10 UTC, before PR #2092 merged at 00:41 UTC.
  Its packaged contribution preset has not been independently verified
  against the new ₹300 source. Website and catalog synchronization alone
  do not authorize a native WhatsApp contribution payment.
- Source media keys were verified present in S3 and the payment template
  was independently read as APPROVED with an IMAGE header and ORDER_DETAILS.
  These facts do **not** establish readiness for a new ₹300 send.
- A completed front-end deployment or staff preview is not evidence that
  the production backend can safely create a purpose-bound ₹300 payment.

## Required server release before staff can send

1. Finance decides that ₹15 is an internal allocation or approves an
   explicit billed Express charge and associated taxes/Delight treatment.
2. Synchronize and read back the live Contribute variant to exactly 30000
   paise with a conditionally guarded update and a reviewed backend release.
3. Implement an authenticated, role-authorized **Contribute-specific**
   draft/prepare/send API that freezes one server-issued ₹300 immutable quote,
   verifies the customer phone, and locks one idempotent payment attempt.
4. Reuse the approved `wecare_whatapp_native_pay_template` through the
   canonical sender and permitted sender number, with provider status,
   media shape and order_details button validated at send time.
5. Implement and verify safe send ambiguity resolution, captured-payment
   settlement, internal Express allocation accounting and any legally
   required contribution acknowledgment. Do not attach Vault access or
   pretend every contribution has a paid GST invoice.
6. Release only after authorized QA, mobile-browser, delivery-status and
   duplicate-send refusal tests. A missing/unknown response must be
   reconciled before re-send.

**Do not use** generic `sendWhatsAppTemplateMessage`, staff invoices,
or Vault `requestSecureFilePayment` to bypass the unavailable Contribute
server-authorized payment operation.
