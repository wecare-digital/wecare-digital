# Contribute ₹300 — native WhatsApp payment release gate

**Stage:** Source-only implementation under independent, default-OFF release gates.
**Do not enable live collection until Finance/tax approval and provider QA.**

## Scope and invariants

Contribute is its own ₹300 catalog SKU, **not Vault or Drop Docs**.
Preserve product `24fa0f39-330b-5365-b7eb-9caf27ad37f1`, variant
`CNT5Q2M8`, and live ProductsTable gross price **30000 paise**.
Do not revise, delete or replace the approved WhatsApp template
`wecare_whatapp_native_pay_template` (Meta **2714938845570815**),
its native `ORDER_DETAILS` Review and Pay button, or its body.
Preserve the **Stay connected** popup exactly as-is.

The server, not the browser, computes this owner-proposed taxable collection:

| Server item | Paise | INR |
| --- | ---: | ---: |
| Contribute base | 23541 | ₹235.41 |
| Supply GST, 18% | +4237 | +₹42.37 |
| Delight, 0.5% of GST-inclusive item | −138 | −₹1.38 |
| Express within customer total | +1500 | +₹15.00 |
| Convenience, 2.5% of pre-fee collection | +729 | +₹7.29 |
| GST on convenience, 18% | +131 | +₹1.31 |
| **Payable** | **30000** | **₹300.00** |

The six figures must reconcile in integer paise; the catalog's 30000
paise is the **gross order target**, not the net pre-GST base.
`lambda_utils.ecommerce.contribute_taxable.breakdown()` is the
purpose-specific arithmetic authority. A mismatch aborts the checkout.

## Sender and customer controls

* Staff Pay & Flow → Contribute requests a verified contact's exact
  `staff-contribute-send`; Admin/MFA and identity proof are server-side.
* A primary Stay connected → Checkout click writes a one-use tab-scoped
  intent. After customer OTP sign-in, Orders sends an authenticated,
  single-unit `action=create` native cart request. Neither public labels
  nor CSS nor the approved template text changes.
* Both paths use `wecare-commerce:live` → `wecare-outbound-whatsapp:live`
  → Meta template ORDER_DETAILS and verified Razorpay gateway configuration.
  No direct template-send or standalone payment link.
* The native order-details UI has one tax field (convenience GST), so its
  Contribute merchandise item is displayed **GST-inclusive ₹277.78**,
  Delight is discount, Express is shipping, convenience is a fee item,
  and fee GST is tax. The customer's total is exactly ₹300.00.
* The pinned approved WhatsApp header stays
  `https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/whatsapp-header.png`
  and its Contribute item keeps the approved thumbnail
  `https://wecare.digital/get/secure/d/public/whatsapp/wa-tpl/WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png`.
  The synthetic convenience-fee row has **no** product thumbnail.
* An accepted Meta send does not prove delivery or capture. Never retry
  a network-ambiguous payment send automatically.

## Fail-closed activation

Two separate environment switches on the **published Commerce live Lambda**
must be reviewed; both default to OFF:

1. `CONTRIBUTE_TAXABLE_NATIVE_PAYMENT_ENABLED=true` gates **all** new
   customer/staff Contribute money paths and the public payable quote.
2. `STAFF_CONTRIBUTE_NATIVE_SEND_ENABLED=true` additionally gates the
   staff Admin send action. Both must be enabled for staff sends.

Before enabling **either** flag:

1. Finance and tax review must confirm that this Contribute SKU should be
   treated as a taxable supply (rather than the historically exempt
   voluntary contribution), including GST invoice classification.
2. Verify the production frozen quote matches every paise above and the
   canonical attempt's `purchasedSnapshot` and `invoiceLines` preserve
   the base/GST/Delight/Express/fee/fee-GST breakdown. Confirm the
   invoice created after capture classifies GST correctly.
3. Review and deploy exact pinned Commerce and outbound Lambda packages.
   Do not overwrite unrelated production hotfixes or Lambda aliases.
   Check Admin MFA authorization and customer OTP ownership.
4. QA with a **specifically authorized recipient** and controlled
   payment configuration. Verify one approved image-header template,
   ORDER_DETAILS acceptance/delivery event, Razorpay verified capture,
   normal catalog-order finalization, receipt, duplicates/refusals,
   ambiguous send and cross-rail one-live-payment behavior.
5. Independently verify website quote, WhatsApp order details and invoice
   total 30000 paise; validate the customer Orders handoff and staff Pay
   UI, on desktop and mobile. Keep switches off on any mismatch.

**Rollback:** revert Commerce/outbound aliases to their recorded versions
and set both release flags to OFF on newly published versions. Never
change product price or convert existing paid contribution orders.

## Code QA

`PYTHONPATH=amplify/functions/shared python3 -m unittest discover -s tests -p test_contribute_taxable_300.py -v`

`python3 -m py_compile amplify/functions/ecommerce/checkout/handler.py amplify/functions/shared/lambda_utils/ecommerce/contribute_taxable.py amplify/functions/shared/lambda_utils/ecommerce/staff_contribution.py amplify/functions/shared/lambda_utils/ecommerce/service_pricing_native.py amplify/functions/messaging/outbound-whatsapp/handler.py`

Passing source tests is NOT evidence that real customer payments are enabled.
