# Contribute ₹300 approval-dependent activation proposal — NOT YET RELEASED

This branch removes the two temporary environment switches that currently block
Contribute payment quotes and staff-native Review & Pay sends. It must **not**
be merged or published to a payment Lambda until the Finance/tax approver has
recorded an approval of the taxable-supply classification, the six-line GST /
Express / Delight / convenience treatment, and invoice/ledger semantics.

The immutable catalog SKU remains 24fa0f39-330b-5365-b7eb-9caf27ad37f1 /
CNT5Q2M8, INR 30000 paise; the six lines remain 23541 + 4237 - 138 +
1500 + 729 + 131 = 30000. Customer, staff and provider-side amounts remain
server-derived. A different price or invalid snapshot is refused.

## Security and accounting mechanisms deliberately retained
- Admin Cognito authorization and MFA on staff routes; no public staff send
- Verified saved contact, owner identity and sender authorization
- Strongly-consistent canonical product read and latest exact ₹300 frozen quote
- Server-selected approved ORDER_DETAILS template and provider/payment readiness
- One live payment reservation, immutable attempt and idempotent send treatment
- Uncertain sends remain locked; gateway capture and paid GST invoice are distinct
- Existing paid/foreign/expired Vault protections remain independent

## Promotion requirements
1. Finance/tax sign-off with named approver, GST interpretation and invoice fields
2. Review and run the pure Python tests, backend syntax, TypeScript and Amplify QA
3. Check Meta native Pay template APPROVED and Razorpay gateway configuration
4. Build an immutable Commerce/Checkout backend package from the reviewed commit;
   do not overwrite live hotfixes or change `$LATEST` behind published aliases
5. Capture current alias versions, revisions and rollback targets, then publish
   only after sign-off. Re-read backend readiness; require amountPaise 30000
6. Use a specifically authorized QA recipient for ONE controlled order and verify
   Meta accepted vs delivered, Razorpay captured, paid GST invoice and duplicates
7. On any issue, restore prior immutable live aliases. Never blindly retry a
   network-ambiguous request.

**Status:** Code proposal only. No customer payment or WhatsApp send authorised.
