# Proposed GST invoice receipt v2 — Meta approval and controlled release

**Status: proposal only — NOT Meta-submitted, approved, activated, or deployed.**
**Tracking:** [#2016](https://github.com/wecare-digital/wecare-digital/issues/2016).
**Reviewed baseline:** 31 October 2026, WABA1 `2094615664435155`, account `775261844268`, `us-east-1`.

## Reason for the change

During paid Vault QA, WhatsApp displayed:

1. Approved `wecare_order_status_v3` **processing** — "Payment received."
2. Approved `wecare_order_status_v3` **completed** — "Payment complete."
3. Approved GST invoice template `wecare_default_invoice_image_template` — "✅ Payment received. Your transaction has been confirmed."
4. A generic Orders CTA and the service-specific Vault CTA.

The two ORDER_STATUS transitions and one statutory invoice **must remain**; they are not duplicate payments or safe-to-delete notifications. The third message's *body copy* repeats the first status. Merged [PR #2018](https://github.com/wecare-digital/wecare-digital/pull/2018) suppresses the unrelated Orders CTA for verified paid request/Vault/Drop Docs services, and merged [PR #2019](https://github.com/wecare-digital/wecare-digital/pull/2019) extends the source-level check to verified paid Track Shipping; ordinary WhatsApp carts retain their canonical Orders CTA. The source merge alone does not prove the new invoice-engine bytes are deployed; compare the exact `:live` ZIP before making that claim.

## Provider-verified existing approved template (do not edit or withdraw)

Read-only WABA1 template management response on 31 October 2026:

| Field | Existing APPROVED Meta asset |
| --- | --- |
| Name / Meta ID | `wecare_default_invoice_image_template` / `1782246473079550` |
| Language / category | `en` / `UTILITY` |
| Header | Dynamic `IMAGE` — the issued GST invoice PNG |
| Body | `✅ Payment received. Your transaction has been confirmed.` |
| Footer | `WECARE.DIGITAL` |
| Button index 0 | `FLOW`, label `Leave Review`, icon `REVIEW` |
| Flow target / action | F002 `993862443003108`, `DATA_EXCHANGE` |
| State | `APPROVED` |

The existing send uses a signed order-bound review Flow token. Merely including a Flow ID in a new template is not proof that the token, INIT and signed completion work.

## Proposed separate template — exact editorial copy for approval

**Candidate name:** `wecare_invoice_receipt_v2` (new template; not present in the verified approved list).

Keep the *same intent and component shapes*, changing only the body text to remove a redundant payment confirmation:

| Component | Proposed content |
| --- | --- |
| Language | `en` |
| Category | `UTILITY` |
| HEADER | `IMAGE` — the existing generated paid-invoice PNG |
| BODY | **Your GST invoice is attached. Please keep it for your records.** |
| FOOTER | `WECARE.DIGITAL` |
| BUTTONS | One `FLOW` at index 0, label **Leave Review**, icon `REVIEW`, `flow_action=DATA_EXCHANGE`, `flow_id=993862443003108` |

This copy is deliberately generic: it remains true for both orders and paid services, without claiming that a document was uploaded, a shipment dispatched, or a provider payment settled to the bank. **Do not add a variable, a new CTA, a second invoice, or service-specific promises to the invoice template.** The distinct post-invoice launcher owns the purchased service's specific action and replay protection.

Meta may reject or reclassify a proposal. The name and copy are *candidates* until an operator approves the exact text and submits it through the authorized WABA1 account. Retain the existing approved asset and current send path throughout review.

## Required gates for implementing, activating, or closing #2016

- [ ] Editorial/payment owner approves the exact new body and confirms that the provider accepts it as a `UTILITY` receipt.
- [ ] Authorized Meta operator creates the **separate** template (do not mutate the existing approved template), retains the exact header/footer/F002 button contract, and records the actual new Meta template ID and APPROVED state.
- [ ] Read back the approved live Meta component definition: `IMAGE` header, exact body/footer, exactly one F002 `FLOW` button at index 0, `DATA_EXCHANGE`, language `en`, category `UTILITY`; compare actual Meta IDs rather than source-only names.
- [ ] Prepare a separate reviewed code PR updating the invoice template registry/approved-ID audit and required sender configuration. **Do not** set `WA_INVOICE_TEMPLATE` to a name that Meta has not approved. Keep the old template as rollback.
- [ ] Build the exact reviewed source into a reproducible invoice-engine artifact, pin `CodeSha256` and previous `:live` version, run hermetic payment/invoice/WhatsApp replay tests, then perform an operator-authorized guarded immutable version + alias rollout.
- [ ] With authorized handset/recipient and an approved non-duplicating test, observe ORDER_STATUS processing → completed → **one** paid-invoice image/Leave Review Flow → **one** service-specific next action, and verify delivered/read and completion separately from Meta acceptance.
- [ ] Verify ordinary WhatsApp cart still gets its canonical `/orders/` CTA, and paid Vault, Drop Docs, Request, Amendment and Pickup never receive a second unrelated CTA.
- [ ] Test idempotent retry/replay, rejected invoice send, withheld service action until invoice acceptance, F002 review token and signed owner-bound completion. Preserve existing payment provider amount and invoice numbering.
- [ ] Record provider approval, actual deployed ZIP hash/version, release owner, CloudWatch alarms, rollback and handset evidence in #2016 **before closing**.

## What this document does *not* do

This proposal does not create or edit a Meta template, change `WA_INVOICE_TEMPLATE`, invoke customer messaging, publish a Lambda, alter a payment, modify statutory invoices, or enable any checkout/Short Commerce flag. It also does not authorize a production handset test or create a new charge.

References: [Service-specific post-payment journeys](service-specific-post-payment-journeys-20261031.md), [canonical WhatsApp template registry](../../amplify/functions/shared/lambda_utils/whatsapp_templates.py), [Short Commerce payment runbook](whatsapp-payment-collection-stack.md).
