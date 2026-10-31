# Historical invoice-v2 proposal — SUPERSEDED

**Current owner decision (31 October 2026): use the existing Meta-approved
`wecare_default_invoice_image_template` English (`en`) only.**

Do **not** create, submit, activate, edit, or replace an invoice template.
The abandoned `wecare_invoice_receipt_v2` proposal in earlier commits was
never Meta-approved. Its sample copy and candidate audit script were not
production payment behavior and are no longer release instructions.

The existing approved template has Meta ID `1782246473079550`, a GST
invoice PNG IMAGE header, body "✅ Payment received. Your transaction has
been confirmed.", footer `WECARE.DIGITAL`, and exactly one Leave Review
F002 Flow button (`993862443003108`, `DATA_EXCHANGE`). The wording remains
unchanged, even though it overlaps with the required processing status.

The approved payment chain remains: `wecare_whatapp_native_pay_template`
ORDER_DETAILS → `wecare_order_status_v3` processing → completed → **one**
`wecare_default_invoice_image_template` receipt → one owner-bound approved
service-specific action if applicable. No standalone duplicate review
message or extra generic free-form "View your order" CTA.

See [#2016](https://github.com/wecare-digital/wecare-digital/issues/2016),
[merged #2033](https://github.com/wecare-digital/wecare-digital/pull/2033)
and the [canonical payment runbook](whatsapp-payment-collection-stack.md).
Release-owner attestation and authorized handset/replay evidence are
still required before calling the source change live.
