# Invoice layout - website and WhatsApp

What a WECARE.DIGITAL invoice looks like when it is SHOWN on the website (Download receipt,
`/orders`) and SENT on WhatsApp (image + caption). One design serves both: the website receipt
(`lambda_utils/ecommerce/customer_receipt.py`) calls the invoice engine's own
`_build_invoice_html`, and the WhatsApp image is the engine's `_generate_receipt_png`
(`amplify/functions/payments/invoice-engine/handler.py`).

Legend used in the diagrams:

    [P]  PROPOSAL - the engine does NOT render this today. It is a design, not a claim.
    [~]  rendered today, but differently from what is shown (see the notes under the diagram).
         Everything unmarked is rendered by the engine today.

Measured 2026-10-06 against `stack` HEAD `3bd88d53`. Amounts were computed with the real
`checkout_pricing.compute_quote`, not by hand.

## 1. Worked example - mixed basket (Rs1 test product + Rs100 Contribute)

All money is integer paise; rupees are only how it is printed.

    Line items                      paise
      Rs1 test product  x1            100
      Contribute (Rs100) x1         10000
    collection before convenience   10100   (Wix total: goods + delivery - discount;
                                             delivery assumed Rs0 in this example)

    convenience fee  = round_half_up(10100 * 250 / 10000)  = round_half_up(252.5)  =   253
    GST on fee       = round_half_up(  253 * 1800 / 10000) = round_half_up(45.54)  =    46
      intra-state (buyer in WB, state 19 = seller state 19):
        SGST = floor(46 / 2) = 23
        CGST = 46 - 23       = 23            CGST + SGST = 46  (reconciles exactly)
    total payable    = 10100 + 253 + 46                                         = 10399
                                                                       = Rs 103.99

A mixed basket pays the fee on the whole collection (owner decision 2026-10-06, commit
`f2840cff`). A contribution-only basket would use `exempt_quote`: fee 0, GST 0, total = collection.
Goods prices are GST-inclusive; GST is added only to the convenience fee.

## 2. The invoice (website download and WhatsApp image share this layout)

    +--------------------------------------------------------------+
    | [logo]            WECARE.DIGITAL                             |
    |              GSTIN: 19AAFFW7196L1Z8                          |
    |         The W.B.S.I.D.C. Building, Unit 1/20,                |
    |         81/2/7, Phears Ln, Kolkata, WB 700012                |
    |         one@wecare.digital | +91 93309 94400                 |
    |              PAN: AAFFW7196L                            [P]  |
    +==============================================================+
    |                       TAX INVOICE                            |
    +--------------------------------------------------------------+
    | Invoice No: WD/2627/00001                               [P]  |
    | Date: 06-10-2026                                  14:05 IST  |
    | Order:  WD-ORD-XXXXXXXX                                 [P]  |
    | Ref:    WD-PAY-XXXXXXXX                                 [~]  |
    | Source: WhatsApp            (or: Website)               [P]  |
    | Place of supply: West Bengal (19)                       [P]  |
    | PAID: 06-10-2026 14:07 IST                                   |
    +--------------------------------------------------------------+
    | Seller: WECARE.DIGITAL, GSTIN 19AAFFW7196L1Z8 (header)       |
    +--------------------------------------------------------------+
    | Bill To:                                                     |
    |   A. Customer                                                |
    |   +91 ******0044 | customer@example.com                 [~]  |
    |   Buyer GSTIN: 19ABCDE1234F1Z5   (only if supplied)     [P]  |
    | Address:                                                     |
    |   12 Example Road, Kolkata, West Bengal 700012               |
    +--------------------------------------------------------------+
    | #  Item              Variant      Qty    Rate      Amt   [~] |
    +--------------------------------------------------------------+
    | 1  Rs1 test product  Standard       1    1.00     1.00       |
    | 2  Contribute        Rs100          1  100.00   100.00       |
    +--------------------------------------------------------------+
    | Subtotal (collection)                             101.00     |
    | Coupon SAVE10                       (none here)    -0.00 [~] |
    | Gift card ****1234                  (none here)    -0.00 [P] |
    | Delivery                                            0.00 [~] |
    | Convenience fee @2.5%                               2.53 [P] |
    | CGST @9% on convenience fee                         0.23 [P] |
    | SGST @9% on convenience fee                         0.23 [P] |
    |   (inter-state instead: IGST @18% on fee  0.46)          [P] |
    +==============================================================+
    | TOTAL (2 items)                               Rs 103.99      |
    |   Rupees One Hundred Three and Ninety-Nine Paise Only        |
    +==============================================================+
    | GST Summary                                                  |
    |   Taxable value (convenience fee)                   2.53 [~] |
    |   CGST @9%                                          0.23     |
    |   SGST @9%                                          0.23     |
    |   Total Tax                                         0.46     |
    +--------------------------------------------------------------+
    | Amount paid                                   Rs 103.99  [P] |
    | Payment: Razorpay, UPI       Status: PAID                [P] |
    |                 * * *  PAID  * * *                           |
    |              Paid on: 06-10-2026 14:07 IST                   |
    +--------------------------------------------------------------+
    |                   [QR code 80x80]                            |
    |                     Thank You!                               |
    |                    Visit Again!                              |
    |            wecare.digital/customerservice                    |
    +==============================================================+

Notes on the [~] and [P] lines, measured in the engine:

- Invoice number. Issued as `WD/<fy-short>/<5-digit seq>` by `_get_next_invoice_number`
  (`handler.py:282-322`), e.g. `WD/2627/00001` for FY 2026-2027. It is printed **nowhere**: the
  PNG never reads it and the HTML/PDF assigns `inv_num` (`:889`) without rendering it. Required by
  GST Rule 46(b); this is the first fix to make.
- Order and Ref. Only `Ref: <referenceId>` is printed. The website receipt passes
  `referenceId = order_number` (`customer_receipt.py`), so on the website "Ref" shows `WD-ORD-...`
  and the `WD-PAY-...` payment reference is absent. Proposal: print both, labelled.
- Source. Not stored on orders today. Proposal: `channel` on the order row, printed here.
  The engine prints `Brand: Pay | Customer service` from `entryPoint` instead.
- Phone. The engine prints the full phone. The masked form is a proposal for the WhatsApp image
  only; the downloaded tax invoice may keep the full number since only its owner can fetch it.
- Variant. The item table has `# Item Qty Rate Amt`, name truncated to 20 characters. No variant
  column; a variant would have to be folded into the name today.
- Coupon. Rendered today as `Promo  -x.xx` from the invoice's `discount` field. Gift card has no
  line at all.
- Delivery. Rendered today as `Express` (plus optional `Green Packing`, `Notification Fee`).
- Convenience fee. Rendered today as one line `Conv Fee` = fee + GST combined
  (`customer_receipt.py` sets `convenienceFee = fee + gst`). GST on the fee is never itemised.
- GST lines. The engine always splits the invoice's supply `tax` into CGST/SGST at `gstRate/2`; it
  has no IGST path and no notion of GST-on-fee. On a website receipt `tax` is 0, so the HTML/PDF
  prints `CGST @0.0% 0.00` and `SGST @0.0% 0.00` rows and omits the GST Summary. The split shown
  above is `checkout_pricing.split_gst` (odd paise goes to CGST).
- Amount paid / payment method. Not rendered; only the PAID stamp and "Paid on" are.
- Rounding of percentages. The PNG prints `CGST @9%` (`:.0f`); the HTML prints `CGST @9.0%`.

## 3. Second worked example - same basket with a Rs10 coupon

    collection = 10100 - 1000 (coupon, applied by Wix Calculate Cart)  =  9100
    fee  = round_half_up(9100 * 250 / 10000) = round_half_up(227.5)    =   228
    GST  = round_half_up( 228 * 1800 / 10000) = round_half_up(41.04)   =    41
           SGST = floor(41 / 2) = 20,  CGST = 41 - 20 = 21
    total = 9100 + 228 + 41                                            =  9369  = Rs 93.69

    | Subtotal (items)                                  101.00     |
    | Coupon SAVE10                                     -10.00     |
    | Collection                                         91.00 [P] |
    | Convenience fee @2.5%                               2.28 [P] |
    | CGST @9% on convenience fee                         0.21 [P] |
    | SGST @9% on convenience fee                         0.20 [P] |
    | TOTAL (2 items)                                Rs 93.69      |

The fee is charged on the discounted collection, never on the pre-coupon subtotal
(`redemption.py` feeds `discounted_collection_paise` to `compute_quote`).

## 4. The WhatsApp version - what the customer sees in the chat

Today `send_invoice_whatsapp` (`handler.py:2567-2687`) sends the PNG above as an image with a
short caption. The 2x-scaled PNG has a paper-tear zigzag top and bottom, and sits on a solid
**grey `(200, 200, 200)`** backdrop saved as RGB with no alpha - see the subsection below, which
is the approved replacement for that grey and is currently switched OFF.

    +--------------------------------------------------+
    | WECARE.DIGITAL                          (chat)   |
    +--------------------------------------------------+
    |                                                  |
    |   +------------------------------------------+   |
    |   | /\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\ |   |
    |   |            WECARE.DIGITAL                |   |
    |   |         GSTIN: 19AAFFW7196L1Z8           |   |
    |   |             TAX INVOICE                  |   |
    |   |  Invoice No: WD/2627/00001          [P]  |   |
    |   |  Order: WD-ORD-XXXXXXXX             [P]  |   |
    |   |  Source: WhatsApp                   [P]  |   |
    |   |  1 Rs1 test product        1     1.00    |   |
    |   |  2 Contribute Rs100        1   100.00    |   |
    |   |  Convenience fee @2.5%           2.53[P] |   |
    |   |  GST on fee (CGST+SGST)          0.46[P] |   |
    |   |  TOTAL (2 items)          Rs 103.99      |   |
    |   |          * * *  PAID  * * *              |   |
    |   | \/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/\/ |   |
    |   +------------------------------------------+   |
    |   Invoice Rs103.99                               |
    |   Order: WD-ORD-XXXXXXXX                         |
    |   Ref: WD-PAY-XXXXXXXX                           |
    |   Thank you for your payment!                    |
    |                                         14:08 vv |
    +--------------------------------------------------+

Caption today, verbatim shape (`handler.py:2609-2612`):

    Invoice <Rs-symbol><total>
    Order: <orderId>          (omitted when empty or "Offline")
    Ref: <referenceId>        (omitted when empty)
    Thank you for your payment!

Proposed caption [P], adding the invoice number and the source, still free of any personal data:

    Payment received - Rs103.99
    Invoice: WD/2627/00001
    Order: WD-ORD-XXXXXXXX
    Ref: WD-PAY-XXXXXXXX
    Ordered on: WhatsApp
    Your receipt is also on wecare.digital/orders

Delivery constraints that apply to the WhatsApp version:

- It is a free-form media message, so it only sends inside the 24-hour service window. Outside it
  an owner-approved UTILITY template with an IMAGE or DOCUMENT header is needed; none exists today
  (only `wecare_otp` is approved, per Phase P findings).
- The image is uploaded to Meta as a media id from the secure `secure/stack/invoices/...` key, so no
  public URL is created.
- No live send is enabled by this document. QA sends go only to the owner-nominated QA recipient.

### 4.1 The approved transparent background - `RECEIPT_TRANSPARENT_BG`, default OFF

The owner reviewed the receipt in a chat, objected to the grey, and approved a specimen rendered
as torn paper on a **transparent** background. It is promoted to a stable public asset:

| | |
|---|---|
| URL | `https://wecare.digital/get/o/public/wa-tpl/img/invoice-receipt.png` |
| S3 | `s3://wecare-digital-get/o/public/wa-tpl/img/invoice-receipt.png` |
| Verified | 2026-10-08: HTTP 200, `image/png`, 510158 bytes, `ssl_verify_result=0` |
| Measured | corner alpha **0**; paper **RGBA (252, 252, 250, 255)** |

**The specimen is a reference, not a payload.** It was rendered from hardcoded fixture data - a
fixture customer name, phone and order number under the heading `TAX INVOICE` - so attaching the
file to the send path would deliver one stranger's fixture invoice to every paying customer. What
the owner approved is the *appearance*, so the renderer produces it and the specimen's two
measured numbers above are the acceptance criteria. They are asserted in
`tests/test_receipt_transparent_background.py`, which is the only reader of the URL.

The flag:

| | |
|---|---|
| Name | `RECEIPT_TRANSPARENT_BG` |
| Function | `wecare-invoice-engine` only |
| Default | **OFF** - absent means off, so live output is unchanged |
| Read | at call time in `_generate_receipt_png`, never at module scope |

With it on, `_generate_receipt_png` returns **RGBA**: the paper is `(252, 252, 250)`, and the
alpha channel is an irregular torn edge (seeded, so one invoice re-renders identically). With it
off the existing grey-zigzag code runs unchanged. `generate_invoice_pdf` composites the PNG onto
white via `_flatten_onto_white` rather than calling `convert('RGB')`, because `convert` discards
alpha and keeps the RGB underneath it - which for a transparent pixel is **black**, i.e. it would
have given the PDF a black border.

Two deliberate fidelity gaps against the specimen, neither worth its cost yet:

- **Typography.** The specimen uses DotGothic16 at 3x supersample over 46 columns. That font is
  not in S3, so matching it means uploading a font and re-tuning the layout. The flag covers
  background and edge, not type.
- **Drop shadow.** The specimen composites a 35%-alpha blurred shadow. Omitted: against a chat
  background it reads as a grey halo, which is the thing being removed.

**Unresolved, and the reason the flag is off.** WhatsApp re-encodes image messages, and the
reports are consistent that a PNG sent as an *image* is converted to JPEG, which flattens alpha -
plausibly to black, which would be worse than the grey. That cannot be settled from this
repository; it needs one real send. So before flipping the flag, send one receipt to the
owner-nominated QA recipient and look at it on a handset. If the alpha does not survive, the fix
is **not** this flag - it is `mediaType: 'document'` in `send_invoice_whatsapp`, which Meta does
not re-encode and `outbound-whatsapp` already supports.

To make it live: set the flag on `wecare-invoice-engine`, then publish a version and move the
`live` alias (`python scripts/snapstart_publish.py wecare-invoice-engine`) - `$LATEST` does not
serve production - then re-export the env record with `python scripts/env_manifest.py --export`.

The fixed payment-template header `wecarepay-header.png` is a **separate** artifact and is not
touched by any of this. Meta refetches an approved template's header from its URL at send time
and an approved body cannot be edited in place, so that URL stays exactly as it is.


## 2026-10-08 current owner approval and release decision

The owner explicitly selected invoice-sample-real-v6.png as the invoice appearance.
That supersedes section 4.1's default-OFF proposal and its deferred typography.
The single wecare-invoice-engine renderer now uses the packaged DotGothic16 font,
monochrome torn-paper layout, transparent PNG, and PDF composited onto white.
Invoice number and source remain printed; customer identifiers are validated and
never minted by rendering. All figures come from the stored invoice, not the sample.
RECEIPT_TRANSPARENT_BG defaults to true; an explicit false is an appearance rollback.
WhatsApp receives the same-engine PDF as a document to avoid image re-encoding
flattening transparency into a black border. The fixed payment-template header is unchanged.
Native invoice collection remains single-tender: a verified gift-card balance is
not a debit. Split-tender native sends refuse before reserving or sending until an
authoritative gift-card settlement producer is implemented. No live-send flag is enabled.
