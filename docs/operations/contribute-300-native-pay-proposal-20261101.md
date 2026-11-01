# Pay & Flow → Contribute: ₹300 native payment proposal (1 November 2026)

## Owner request

Place Contribute immediately after Vault in Workspace Pay & Flow.
The customer must pay exactly **₹300**, not ₹3,000. Express is **₹15** and
should not silently increase the final amount. Show where Delight and other
adjustments fit before enabling an approved WhatsApp native payment request.

## Grounded live baseline

- ProductsTable Contribute product `24fa0f39-330b-5365-b7eb-9caf27ad37f1`,
  variant `CNT5Q2M8`, currently contains **₹250** (25000 paise).
- `blog_contribution.CONTRIBUTION_PRESETS_PAISE` and
  `CONTRIBUTION_CHOICES_PAISE` recognize ₹250. Browser
  `src/config/contribution.ts` also recognizes ₹250.
- `_contribution_breakdown` deliberately uses an exempt quote: supply GST,
  Delight, Express, convenience and GST-on-convenience are all zero. This
  is a separate `BLOG_CONTRIBUTION` purpose with its own settlement and
  gateway-order binding, **not** a request-service invoice.
- Approved native Meta `ORDER_DETAILS` message
  `wecare_whatapp_native_pay_template` already exists. Reuse the
  canonical payment template only through the approved, server-owned
  payment sender; do **not** register a duplicate template for every amount.

## Two exact ₹300 reconciliation examples

### A. Preserve existing voluntary-contribution fee exemption (preferred pending accounting review)

| Internal allocation | Paise | Rupees |
| --- | ---: | ---: |
| Net voluntary contribution | 28500 | ₹285.00 |
| Express cost allocated **within** the customer total | 1500 | ₹15.00 |
| Delight, convenience, supply GST, fee GST | 0 | ₹0.00 |
| **Customer pays** | **30000** | **₹300.00** |

Express here is an **internal allocation**, not a separately added
customer-facing convenience fee or taxable invoice line.
If Finance instead wants an explicit Express charge or customer discount,
the back-end contract and invoice classification must change.

### B. Alternative if Finance confirms it is a taxable supply, using Vault/Collect policy

| Component | Paise | Rupees |
| --- | ---: | ---: |
| Base item | 23541 | ₹235.41 |
| Supply GST at 18% | +4237 | +₹42.37 |
| Delight at 0.5% of GST-inclusive eligible item | −138 | −₹1.38 |
| Express | +1500 | +₹15.00 |
| Pre-convenience collection | 29140 | ₹291.40 |
| Convenience at 2.5% of pre-convenience collection | +729 | +₹7.29 |
| GST at 18% on convenience | +131 | +₹1.31 |
| **Customer pays** | **30000** | **₹300.00** |

These are *demonstration* figures from existing integer-paise rounding
rules. B changes the legal/tax character of the existing voluntary
Contribute product and **must not** be promoted to live without
Finance/tax approval, separate canonical backend computation,
payment-attempt snapshot and invoice consistency.

## Implementation boundary in this PR

- Adds a staff-only **Contribute** Pay tab after **Vault**.
- Shows the two *read-only* reconciliation examples, live existing
  catalog price and shared Meta payment template/media reference.
- Includes no Send, Create invoice, Checkout, reprice, direct Meta, Razorpay,
  product mutation, new approval, or test charge.
- No price or accounting state is changed in DynamoDB, and no backend code is changed.

## Required before a live Send action

1. Finance decides whether Express is an *internal allocation* or a billed
   fee, and whether Contribute remains a voluntary contribution or is a
   taxable sale. Keep Delight **zero** in the existing exempt contribution
   model; don't replace its fixed 0.5% policy with an arbitrary balancing
   discount to disguise a mismatch.
2. Implement a purpose-specific **server** quote, price authority and
   checkout before changing `CNT5Q2M8`. Freeze the exact ₹300 gross amount
   and its components on the same durable order/payment identity used by
   the Meta `ORDER_DETAILS` action and contribution settlement.
3. Preserve owner/recipient verification, idempotent reservation, ambiguity
   resolution and the existing approved payment sender. A template-preview
   response alone may never authorize a send.
4. Verify read-only previews and server price match across Pay, customer
   checkout and approved Meta item; run QA with a test-only permitted number
   and payment configuration, never an unsolicited real customer request.
5. Confirm Razorpay capture, ledger, and any legally required invoice/
   acknowledgement reconcile to exactly 30000 paise without cross-labeling
   a donation as a paid fulfilment service.

This document is a release proposal, **not** a production activation.
