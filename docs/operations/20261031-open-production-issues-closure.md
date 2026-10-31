# Five production issues: evidence and safe closure plan (31 October 2026)

This is a **read-only release plan**, not production sign-off or permission to
charge customers. The issue bodies remain the authority on their acceptance
criteria. The script shipped with this plan makes the **new invoice template**
gate reproducible without editing or sending the existing approved template.

## Independent checks performed today

- Read-only AWS `us-east-1` alias readback: Commerce `live:173`,
  Checkout `live:293`, Inbound WhatsApp `live:196`, WhatsApp Business API
  `live:401`; unweighted, Active, Successful.
- The first three published receiver environments each report
  `SHORT_COMMERCE_PART1_ENABLED=true`. Their `PICKUP_SERVICE_ENABLED` is
  unset. The eight required payment alarms all show `OK`. Alarm state is NOT
  proof of a successful real-money or handset test.
- Amplify `wecare.digital`: latest successful production job is `407`.
  `NEXT_PUBLIC_WEBSITE_FULL_CART_QUOTE_ENABLED` is absent from both app and
  branch environment. **Full-cart Pay here remains deliberately gated.**
- FlowRegistry: Drop Docs `39581903361452878` is `PUBLISHED`;
  Pickup `2988393421499259` is PUBLISHED but
  `fulfillmentReadiness=BLOCKED_META_COMPLETION_PAYLOAD_INCOMPLETE`.
- Direct Meta template readbacks, on Wecare.Digital:
  - `_dropdoc_flow` `1041974032198332`: `APPROVED`,
    one `DATA_EXCHANGE` Drop Docs button targeting `39581903361452878`;
    IMAGE, body and footer retained
  - `wecare_default_invoice_image_template` `1782246473079550`:
    `APPROVED`, generic body "✅ Payment received. Your transaction has
    been confirmed.", IMAGE header and Leave Review `DATA_EXCHANGE`
    button for `993862443003108`. This **still duplicates** the order-status
    processing copy, without representing a failed payment.

These checks read current control-plane configuration only. They **do not**
prove which exact Git tree built each Lambda, that the Meta asset completes
successfully on a handset, that a captured payment settled to the bank, or that
staff finished authenticated UI acceptance.

## #2016: fix repeated invoice copy without touching the frozen rail

**Proposed NEW template, not an edit of the current approved one:**

| Component | Reviewed proposal |
| --- | --- |
| Name | `wecare_invoice_receipt_v2` |
| Category/language | `UTILITY` / `en` |
| Header | `IMAGE`, reuse the existing approved invoice-image sample |
| Body | 🧾 Your GST invoice is ready. The invoice image above contains your transaction details. |
| Footer | `WECARE.DIGITAL` |
| One FLOW button | `Leave Review`, `DATA_EXCHANGE`, `993862443003108` |

This copy refers to the actual issued invoice instead of repeating the payment
status. It preserves the review Flow and the paid invoice PNG. The existing
template remains active until Meta **approves a distinct, pinned template ID**
and the payment-rail owner approves a code release. The template submission
requires explicit user confirmation; preparing this Git change did not submit
it for review.

To audit a future single-template Meta GET export (without network access):

```sh
python scripts/check_invoice_copy_candidate.py \
  --file reviewed-invoice-template.json \
  --expected-id THE_NEW_META_TEMPLATE_ID
python -m unittest discover -s tests -p test_invoice_copy_candidate.py
```

A passing copy gate does **not** authorize a send. A separate reviewed
release must switch only the invoice template identity after capture and
invoice generation, retain processing -> completed state, owner-bound service
CTA, one-send idempotency and the existing refund/rollback behavior. Validate
on an owner-authorized handset with sent/delivered/read evidence. Never
retroactively resend completed transactions.

## #2008: Vault backend/settlement/Collect sign-off

The original Vault compatibility backend was already deployed and a paid
Vault invoice was observed. Current Commerce is now `live:173`, so do not
mistake the older v172 readback for current provenance.

Remain OPEN until the authorized merchant operator independently verifies
Razorpay **bank settlement**, exact captured payment `pay_TuNRncBsCxGWLC`,
settlement ID, net/fees, bank UTR and credit. A `payment.captured` or
unrelated `settlement.processed` event is not sufficient.

Run an **authenticated** Collect UI smoke test on a dedicated account, using
the existing settled request or isolated staging data when possible: success,
409 refusal, 502 ambiguous, duplicate request/double-submit and ledger
readback. Do not initiate a new real charge without payment-owner approval.
Preserve all issued GST invoices; separately reconcile historical
`WD/2627/00012` before numbering could repeat it.

## #1998: read-only full-cart checkout quote release

Do not set `NEXT_PUBLIC_WEBSITE_FULL_CART_QUOTE_ENABLED=true` yet.
Confirm exact Checkout `live:293` source package and read-only
`action=quote` arm **before any authenticated live request**. Stage multiple
SKU/quantity quotes and compare every paise against `prepare`, including
discount, shipping, convenience fee and taxes, with zero new provider orders
for read-only calls. Require frozen one-unit native policy reconciliation,
refund/replay checks and operator-approved real provider canary before
deploying the frontend switch. Keep old `/cart/` links reviewed.

## #1984: paid Drop Docs completion

The Meta template's Flow button points to the canonical F003 now; the
provider-published JSON's semantic parity was previously audited in the
issue. The remaining gap requires an explicitly authorized paid handset:
signed customer, captured invoice **before** Flow dispatch, exact owner-bound
SELECT_TARGET -> NOTE -> UPLOAD -> CONFIRMATION, one real upload,
FlowSubmission/Inbox and replay idempotency. Do not rewrite the live
template or pretend a PUBLISHED badge proves a successful upload.

## #1973: live Short Commerce release acceptance

Three current live receivers have the opt-in one-unit flag `true`, but that
does not supersede owner sign-off. Obtain approved exact hashes/source
manifest and evaluate with the existing
`scripts/check_short_commerce_live.py` tool and the eight named alarms.
Run the separately authorized negative-basket, native/website amount parity,
capture -> Order -> GST invoice, retry/refund, WhatsApp receipt and
SKU-specific fulfilment tests. Pickup is specifically blocked at the
published completion-payload gate; do not enable it from PUBLISHED alone.

## Closure rule

Do **not** close any issue solely because source was merged, CI passed, a
published Lambda alias is healthy, a template is APPROVED, or a FlowRegistry row
says PUBLISHED. Attach specific operator/provider/handset evidence to the
issue, then close only when every acceptance criterion is met. No payment,
invoice, user, customer message, Meta template, Flow publication, live Lambda
alias or production flag is modified by this PR.
