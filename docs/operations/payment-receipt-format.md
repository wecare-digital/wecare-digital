# WECARE.DIGITAL Payment Receipt Format

Current owner-approved customer receipt contract: **v7, 2026-10-26**.

This document is the maintenance authority for the PNG sent to customers after payment. Historical invoice-layout notes may describe older appearances; when they conflict with this file, this file wins.

## Runtime ownership

- Renderer: `amplify/functions/payments/invoice-engine/receipt_layout.py`
- Engine/wiring: `amplify/functions/payments/invoice-engine/handler.py`
- Seller identity: `amplify/functions/shared/lambda_utils/ecommerce/business_identity.py`
- Canonical pricing calculator: `amplify/functions/shared/lambda_utils/ecommerce/checkout_pricing.py`
- Customer PNGs: `secure/d/public/Invoice/customer_invoice/` (edge-gated; use S3/presigned access)
- Canonical brand SVG: `o/stream/media/m/wecare-digital.svg`
- Runtime raster logo: `o/stream/media/m/wecare-digital.png`
- Invoice font prefix: `secure/d/public/Invoice/fonts/`

The renderer is presentation-only. It MUST render stored invoice figures and MUST NOT calculate or change a charge.

## Approved visual contract

- Document title: **PAYMENT RECEIPT**
- Paper: off-white `rgb(252,252,250)`
- Pixels outside the torn paper: transparent
- Torn/zig-zag edge: WECARE lime `#d1f470`
- Structural green: `#1a3a2a`
- Lime is used for the receipt-title bar and Amount Paid bar.
- Official WECARE.DIGITAL artwork is used from the S3 brand asset; never recreate the logo by hand.
- Typography should use Inter when the invoice font assets are available. The renderer must retain a packaged-font fallback so a missing optional asset cannot prevent a paid receipt from being generated.
- Keep the image compact and WhatsApp-readable; do not add a drop shadow.

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

## Customer-visible fields

Show when present:

- Receipt Ref: the WECARE payment reference with `WD-PAY-` removed for display
- paid/capture date and time in IST
- payment status
- Channel
- provider transaction id as `Txn` / `Txn ID` without naming the gateway
- customer name, phone, email and address
- Buyer GSTIN only when a real buyer GSTIN is stored; never label the seller GSTIN as the buyer's
- Place of Supply when the stored address supplies a state
- line description, quantity, rate and amount
- Subtotal
- Discount only when non-zero
- Shipping/Handling only when non-zero
- Taxable Value
- one supply-tax breakdown: CGST + SGST for intra-state, or IGST for inter-state
- Total Tax
- Convenience Fee only when non-zero
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
- HSN/SAC unless the invoice engine later stores an authoritative HSN/SAC supplied by the collection/catalogue path
- a duplicate GST Summary
- Razorpay or bank branding

These values may remain stored internally for statutory records, reconciliation and support.

## Convenience fee

Customer label: **Convenience Fee**.

The customer receipt currently receives the combined convenience-fee amount already stored by the engine. Pricing has one authority: `checkout_pricing.compute_quote`.

Current policy:

```text
convenience fee = round-half-up(approved collection x 2.5%)
GST on fee      = round-half-up(convenience fee x 18%)
total payable   = approved collection + convenience fee + GST on fee
```

The approved collection is after supply GST, discount and delivery and before the convenience fee. Never re-derive this formula in the renderer.

## Future-change prompt

Use this prompt when changing the receipt:

> Update the WECARE.DIGITAL customer PAYMENT RECEIPT only through the invoice-engine renderer. Preserve the v7 customer/privacy contract and render stored figures without pricing anything. Keep the official S3 logo, formal seller identity, lime #d1f470 edge, forest #1a3a2a structure, off-white paper with transparent outside, optional rows only when values exist, one CGST/SGST-or-IGST tax breakdown, the exact label "Convenience Fee", and Amount Paid for captured payments. Never expose invoiceNumber, invoiceId, orderId, customer UUID or provider order id. Do not introduce HSN/SAC until an authoritative source field exists. Check fonts/logo assets, compile the payment Python, run payment-rail verification, build deterministic packages, publish immutable Lambda versions, move the live aliases with revision guards, and verify the live code hashes and one rendered PNG before closing the change. Update this document if the approved contract changes.

## Change procedure

1. Change `receipt_layout.py`; keep pricing out of it.
2. If legal identity changes, edit `business_identity.py` instead of hardcoding a second copy.
3. Confirm the official logo objects still exist in S3.
4. Confirm the preferred Inter font objects exist; if they do not, verify the packaged fallback still renders.
5. Compile the payments/shared Python and run the payment-rail verification.
6. Inspect a local/QA PNG for clipping, transparent outside pixels, lime edge, readable totals, optional-row behavior and long customer/item text.
7. Push through `.github/workflows/payment-rail-ci.yml`. Production is the `live` alias, not `$LATEST`.
8. Verify the `wecare-commerce`, `wecare-checkout` and `wecare-invoice-engine` live aliases/code hashes.
9. Generate a new versioned receipt asset for QA rather than destructively replacing an issued customer's historical rendition unless the owner explicitly requests a rerender.
