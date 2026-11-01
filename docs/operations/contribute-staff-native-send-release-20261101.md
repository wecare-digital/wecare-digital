# Contribute ₹300 native WhatsApp payment — CURRENT production release gate

**As of 1 November 2026:** the Pay & Flow → Contribute → Display/Create/Ledger interface
is deployed, but **the staff payment send is NOT live-enabled**. This document is the
operator release checklist, not permission to take payments or override Finance.

## Source of truth: six-line taxable ₹300 quote

The current checkout and pricing code is
`amplify/functions/shared/lambda_utils/ecommerce/contribute_taxable.py`,
`staff_contribution.py`, and
`amplify/functions/ecommerce/checkout/handler.py`.
The user-facing illustration and `ContributeStaffControls.tsx` expect precisely:

| Server-owned field | Rupees | Paise |
| --- | ---: | ---: |
| Contribute item base | ₹235.41 | 23541 |
| Supply GST at 18% | +₹42.37 | 4237 |
| Delight | −₹1.38 | 138 |
| Express | +₹15.00 | 1500 |
| Convenience | +₹7.29 | 729 |
| GST on convenience | +₹1.31 | 131 |
| **Exact customer payable** | **₹300.00** | **30000** |

The entire breakdown must match the immutable server-side policy
`contribute-taxable-review-2026-11-01`. The old interpretation of a
**zero-GST voluntary contribution with an uncharged ₹15 internal allocation**
is **not compatible with the current checkout**. Do not activate an outdated
voluntary-contribution policy or claim this pricing is Finance-approved.
Finance/tax must approve the actual classification, GST receipt and accounting
before anyone changes production send flags.

## Production switches — both required, both default OFF

`wecare-checkout:live` version 300 currently has neither:
- `STAFF_CONTRIBUTE_NATIVE_SEND_ENABLED=true`
- `CONTRIBUTE_TAXABLE_NATIVE_PAYMENT_ENABLED=true`

`_staff_contribution_readiness` requires **both**, a fresh strongly
consistent canonical ProductsTable read of the ₹300 `CNT5Q2M8` SKU and
exact taxable breakdown, verified WhatsApp template/order configuration,
recipient identity and authenticated Admin. If either switch is absent or
policy arithmetic drifts, the backend refuses `staff-contribute-send` and
the UI remains locked. A React UI deployment cannot enable this rail.

## Staff contract

Read-only: `POST /ecommerce/checkout`
```json
{"action":"staff-contribute-readiness"}
```

Send **once**, only after owner-approved release and explicit staff confirmation:
```json
{"action":"staff-contribute-send","contactId":"<canonical ContactsTable id>"}
```

The backend refuses any caller-supplied amount, SKU, phone, discount, sender
or Meta template. The order is one frozen catalog SKU with one native Review
& Pay, not a Vault entitlement, substitute payment template, or a free-form
staff invoice. Use `wecare_whatapp_native_pay_template`, Meta ID
`2714938845570815`, subject to live approved readback. Reuse approved
header PNG and ORDER_DETAILS thumbnail from the existing canonical media.

Meta **accepted** is not WhatsApp **delivered**, and neither is payment
**captured**. Any uncertain/timeout/5xx outcome locks the draft and requires
ledger/provider reconciliation before any later request. No blind retry.

## Release checklist — not satisfied solely by a merge

1. Finance/tax owner signs off the **six taxable line items**, Express,
   Delight and ledger/GST invoice treatment, with evidence and approver.
2. Independent review validates the exact live ProductsTable record,
   Contacts verification, native Meta template and payment configuration.
   Distinguish the separate unresolved Meta product inventory incident
   [#2152](https://github.com/wecare-digital/wecare-digital/issues/2152);
   an unexpectedly empty Meta catalog must not be treated as a reason to
   create duplicate products or override Meta permissions.
3. Verify current checkout package includes the reviewed shared code and
   all requested functionality; publish immutable `wecare-checkout` version.
   Record alias/revision/code SHA and rollback. No `$LATEST` production flip.
4. After approvals, enable **both** switches through a controlled
   configuration change on a reviewed immutable backend release. Re-read
   `staff-contribute-readiness` and require exact `sendEnabled=true` and
   `amountPaise=30000`. No unauthorised test number or customer payment.
5. With an **approved QA recipient**, test one ₹300 native Review & Pay,
   order capture, invoice/GST, WhatsApp provider acceptance vs delivery,
   refunds/failed/unknown sends and duplicate refusal. Record order/payment
   references securely; do not disclose private customer data in GitHub.
6. Test desktop/mobile Pay & Flow → Contribute → Create/Display/Ledger,
   inactive staff identity, price drift and rollback. Finance or any
   uncertain payment behavior must keep the sender disabled.

**Rollback:** restore the previous immutable alias and disable either
release flag. Never retry ambiguous sends or re-create paid orders.

## CI

Keep source checks in
`tests/staff_contribute_native_send_contract.test.mjs`,
`tests/pay_contribute_staff_controls.test.mjs`,
`tests/pay_contribute_300_preview.test.mjs`,
`tests/contribution_checkout_300_contract.test.mjs`, and
`tests/test_staff_contribution_guard.py`, alongside Lambda Python syntax
and TypeScript gates. None substitutes for an authorized payment acceptance test.
