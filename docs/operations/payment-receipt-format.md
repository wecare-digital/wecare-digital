# WECARE.DIGITAL Payment Receipt Format

Current owner-approved customer receipt contract: **v8, 2026-10-27**.

This document is the maintenance authority for the PNG sent to customers after payment. Historical invoice-layout notes may describe older appearances; when they conflict with this file, this file wins.

## Runtime ownership

- Renderer: `amplify/functions/payments/invoice-engine/receipt_layout.py`
- Engine/wiring: `amplify/functions/payments/invoice-engine/handler.py`
- Seller identity: `amplify/functions/shared/lambda_utils/ecommerce/business_identity.py`
- Canonical pricing calculator: `amplify/functions/shared/lambda_utils/ecommerce/checkout_pricing.py`
- Customer PNGs: `secure/d/public/Invoice/customer_invoice/` (edge-gated; use S3/presigned access)
- Canonical brand SVG: `o/stream/media/m/wecare-digital.svg`
- Receipt brand mark (immutable v2): `secure/d/public/Invoice/brand/wecare-digital-receipt-mark-v2.png`
- Invoice font prefix: `secure/d/public/Invoice/fonts/`

The renderer is presentation-only. It MUST render stored invoice figures and MUST NOT calculate or change a charge.

## Approved visual contract

- Document title: **PAYMENT RECEIPT**
- Paper: off-white `rgb(252,252,250)`
- Pixels outside the torn paper: transparent, stored as transparent white so a viewer that drops alpha (a JPEG conversion) shows white rather than a black frame
- Four-sided scalloped/torn edge: WECARE lime `#d1f470`
- Structural green: `#1a3a2a`
- Lime is used for the receipt-title bar and Amount Paid bar.
- The receipt masthead uses the immutable official transparent bag mark plus the canonical stacked `WECARE.` / `DIGITAL` wordmark construction from `src/components/BrandLockup.tsx`; do not substitute the generic opaque square logo or a marketing card.
- Typography should use Inter when the invoice font assets are available. The renderer must retain a packaged-font fallback so a missing optional asset cannot prevent a paid receipt from being generated. Inter 4.1 (SIL OFL 1.1, from the rsms/inter v4.1 release) is in the font prefix as `Inter-Regular.otf`, `Inter-SemiBold.otf` and `Inter-Bold.otf`, with its licence as `Inter-LICENSE.txt`. The packaged fallback has no ₹ glyph, so amounts print as `Rs.` whenever it is in use.
- Keep the image compact and WhatsApp-readable; do not add a drop shadow.
- Customer PNG width: **1024 px**, matching the approved owner reference.
- Preserve the approved hierarchy: centered brand block, lime PAYMENT RECEIPT bar, split receipt facts, slim pale BILL TO header with two white columns and a vertical divider, pale/green item header, compact totals, lime AMOUNT PAID bar, PAID stamp + trace block, and Thank You / Visit Again footer.
- The approved mock is a visual/layout reference only. Its old Taxable Value / CGST / SGST / Total Tax rows are retired for the compact customer copy; v8 accounting rows remain authoritative.

## Seller identity

Print:

- WECARE.DIGITAL BHARATWORKS
- WECARE.DIGITAL
- GSTIN: 19AAFFW7196L1Z8
- PAN: AAFFW7196L
- The W.B.S.I.D.C. Building, Unit No. 1/20,
- 81/2/7 Phears Lane,
- Kolkata, West Bengal - 700012, India
- one@wecare.digital
- +91 93309 94400
- https://wecare.digital

Change seller identity only in `business_identity.py`; do not duplicate a second legal identity in the renderer.

## Purchase-surface invariant

There is one customer receipt renderer for website checkout, WhatsApp catalog/cart, staff Pay, Inbox/manual collection, paid WhatsApp Flows, modern paid-service/Vault checkout, and the ChatGPT connector's guarded Pay on WhatsApp handoff. Entry-point UIs and connectors must not implement their own receipt arithmetic or alternate layout. After provider-verified capture, the payment webhook asks the canonical invoice engine to `ensure-image`: reuse a rendition only when it was generated at/after `paidAt`; a pre-payment preview is preserved but a new paid rendition is created. If no PNG exists, render it once. Website/customer download remains read-only.

## Customer-visible fields

Show when present:

- Receipt Ref: the WECARE payment reference with `WD-PAY-` removed for display
- paid/capture date and time in IST
- payment status, with captured payments shown as a lime `PAID` pill
- Channel
- provider transaction id as `Txn` / `Txn ID` without naming the gateway
- customer name, phone, email and address
- Buyer GSTIN only when a real buyer GSTIN is stored; never label the seller GSTIN as the buyer's
- Place of Supply when the stored address supplies a state
- line description, quantity, rate and amount
- **Items Subtotal**
- **Delight** only when non-zero
- **Express** / Handling only when non-zero
- **Convenience Fee** as the net fee only when non-zero
- one compact seller-GSTIN row (for example `19AAFFW7196L1Z8`) whose amount is the stored **total GST** for the collection: supply GST + convenience-fee GST
- Amount Paid for captured payments; Amount Payable otherwise
- amount in words
- PAID stamp and paid timestamp when captured

## Fields intentionally hidden from the customer PNG

Do not show:

- statutory sequential `invoiceNumber`
- internal `invoiceId`
- internal `orderId`
- internal customer UUID / Customer ID
- provider order id
- HSN/SAC (stored internally when explicitly supplied by staff/catalogue; never guessed and not printed on the compact customer receipt)
- Taxable Value
- CGST/SGST/IGST detail rows
- per-item GST amounts/rates
- convenience-fee GST as a separate customer row
- a duplicate GST Summary
- Razorpay or bank branding

These values may remain stored internally for statutory records, reconciliation and support.

## Convenience fee

Customer label: **Convenience Fee**.

New invoices persist the convenience fee as three exact facts: net fee, GST on fee, and their combined total. The **customer receipt shows only the net Convenience Fee**, then includes fee GST in the single compact GSTIN row together with supply GST. Legacy invoices that predate the split retain their stored combined amount without reverse-engineering a tax component. Pricing has one authority: `checkout_pricing.compute_quote`.

Current policy:

```text
convenience fee = round-half-up(approved collection x 2.5%)
GST on fee      = round-half-up(convenience fee x 18%)
total payable   = approved collection + convenience fee + GST on fee
```

The approved collection is after supply GST, discount and delivery and before the convenience fee. Never re-derive this formula in the renderer.

## Internal GST/accounting contract

Customer simplicity must never delete filing facts. New invoice rows persist `gstAccounting` with supply GST, convenience-fee GST, total GST, seller GSTIN, resolved place-of-supply state/code/subdivision and the explicit Delight tax treatment. Invoice-item rows persist each line's `gstRate`, `taxAmount` and optional operator/catalog supplied `hsnSac`. HSN/SAC is never guessed from the description.

The full invoice-detail API additionally returns `gstWorkpaper` (`schemaVersion=wecare-gst-workpaper-v1`). It is a backend-generated accounting/export workpaper and explicitly carries `portalUploadFormat=false`; adapters may map it to a validated filing format later. The workspace may download this JSON. Missing HSN/SAC or an unresolved place of supply remains visibly incomplete instead of being fabricated.

Delight is recorded as `POST_TAX_COMMERCIAL_DISCOUNT`: it is computed from eligible GST-inclusive goods, reduces the amount collected and therefore the convenience-fee base, but does not silently rewrite supply GST already computed from the item rates. A statutory GST-invoice renderer/export must consume the stored accounting facts rather than infer them from the compact receipt.

## Future-change prompt

Use this prompt when changing the receipt:

> Update the WECARE.DIGITAL customer PAYMENT RECEIPT only through the invoice-engine renderer. Preserve the v8 customer/privacy contract and render stored figures without pricing anything. Keep the official S3 logo, formal seller identity, lime #d1f470 edge, forest #1a3a2a structure, off-white paper with transparent outside, optional rows only when values exist, the compact Items Subtotal / Delight / Express / Convenience Fee / seller-GSTIN total-GST summary, and Amount Paid for captured payments. Never expose invoiceNumber, invoiceId, orderId, customer UUID or provider order id. Do not introduce HSN/SAC until an authoritative source field exists. Check fonts/logo assets, compile the payment Python, run payment-rail verification, build deterministic packages, publish immutable Lambda versions, move the live aliases with revision guards, and verify the live code hashes and one rendered PNG before closing the change. Update this document if the approved contract changes.

## Change procedure

1. Change `receipt_layout.py`; keep pricing out of it.
2. If legal identity changes, edit `business_identity.py` instead of hardcoding a second copy.
3. Confirm the immutable receipt brand mark exists in S3 and visually verify the rendered bag + wordmark lockup.
4. Confirm the preferred Inter font objects exist; if they do not, verify the packaged fallback still renders.
5. Compile the payments/shared Python and run the payment-rail verification.
6. Inspect a local/QA PNG for clipping, transparent outside pixels, lime edge, readable totals, optional-row behavior and long customer/item text.
7. Push through `.github/workflows/payment-rail-ci.yml`. Production is the `live` alias, not `$LATEST`.
8. Verify the `wecare-commerce`, `wecare-checkout` and `wecare-invoice-engine` live aliases/code hashes.
9. Generate a new versioned receipt asset for QA rather than destructively replacing an issued customer's historical rendition unless the owner explicitly requests a rerender.
