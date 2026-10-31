# Five production issues: evidence and safe closure plan (31 October 2026)

This is a **read-only release plan**, not production sign-off or permission to
charge customers. The issue bodies remain the authority on their acceptance
criteria. The owner has chosen the **existing approved English invoice template
only**; no new Meta invoice template is proposed or authorized.

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

## #2016: retain approved invoice, remove unrelated generic follow-up

**Owner decision:** use `wecare_default_invoice_image_template` (English
`en`, Meta template ID `1782246473079550`, APPROVED) unchanged. The
invoice retains its dynamic PNG IMAGE header, approved body, business footer
and Leave Review F002 `DATA_EXCHANGE` Flow button `993862443003108`.

Do not create, edit, submit, or configure a `wecare_invoice_receipt_v2`
template. The prior proposal/checker was superseded and was never approved by
Meta. The current approved body ("Payment received") necessarily repeats
the processing ORDER_STATUS wording; do not claim this exact copy can be
changed without a Meta template edit.

Merged source PR [#2033](https://github.com/wecare-digital/wecare-digital/pull/2033)
removes the separate free-form "View your order" message from automatic
post-invoice WhatsApp delivery; customers still have the authenticated
`/orders/` page. Required ORDER_DETAILS Review & Pay, processing →
completed ORDER_STATUS, one signed GST invoice IMAGE/Leave Review template,
and the one owner-bound service-specific next action are unchanged.
The source merge needs a reviewed production ZIP/alias release before this
can be called live. No new customer payment or message is authorized by
this checklist.

Verify on an authorized handset that invoice accepted/sent/delivered/read
evidence is distinct, that only the purchased service template arrives after
the invoice, and that replay cannot duplicate invoice or service action.

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
