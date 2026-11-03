# Shop text-only + checkout price breakdown (2026-11-02)

This note records the two-feature change set on branch
`feat/shop-textonly-and-checkout-breakdown-20261102` (cut from `wecare.digital`).

## Scope

- FEAT-001: make the WECARE Shop image-free (committed as `c20b86f8b`).
- FEAT-002: verify and surface the full server-quote price breakdown on the
  one-page checkout, add an offline regression test, and write this note.

The pricing-model change (the exact per-item fee line items in the user's
mockup) and the checkout-failure repair are explicitly OUT OF SCOPE here; they
await user sign-off and AWS access.

## Files changed

### FEAT-001 (image-free Shop)

- `src/content/shopProducts.ts`: removed the product image URL values from
  `SHOP_LISTINGS` and dropped the dead `image?` field from `ShopListing`.
- `src/components/ShopProductHead.tsx`: removed the `product.image`-gated
  JSON-LD Product/Offer node and its `mainEntity` reference; the page emits only
  the image-free `ItemPage` node. The brand social-card `og:image` /
  `twitter:image` is intentionally kept.
- `src/content/shop.ts`: removed `image?` from `ShopProduct` / `RawProduct` and
  the `project()` image spread.
- `src/content/catalogSnapshot.ts`: removed `image?` from
  `CatalogSnapshotProduct`.

### FEAT-002 (checkout breakdown display + test + docs)

- `src/components/CheckoutIdentityCard.tsx`: added optional `email?` and
  `customerId?` fields to the `CheckoutIdentity` interface and two display-only
  rows (Email, Customer ID) that render only when present. No payment logic.
- `src/components/cart/CartPage.tsx`: the single `CheckoutIdentityCard` usage now
  passes `identity={ { ...profile, customerId: profile.contactId } }` so the
  Customer summary surfaces the customer id and email the profile already
  carries. Display only; no change to quote fetch/parse, prepare/verify payload,
  Razorpay wiring, or any amount.
- `tests/checkout-receipt.test.mjs`: new offline regression test (see below).
- `docs/ops/2026-11-02-shop-textonly-and-checkout-breakdown.md`: this note.

`src/components/cart/CheckoutReceipt.tsx` was reviewed and already renders every
breakdown row from the validated server quote, so no change was required there.
`src/lib/checkoutQuote.ts` (quote parse/validate) and `src/lib/money.ts`
(`formatPaiseINR`) were read only and left untouched.

## Image references: removed vs deferred

FEAT-001 removed all product image URL data and the image-gated JSON-LD Product
node. There are no deferrals: the Shop renders no product image anywhere, the
`image?` type field was dropped from every catalogue interface that carried it,
and the only live consumer (the JSON-LD Product node) was removed. The brand
social card used for `og:image` / `twitter:image` is a brand asset, not a
product image, and is deliberately kept.

## Mockup row to quote field mapping

The checkout breakup is a DISPLAY of the validated server quote only. Every row
is rendered through `formatPaiseINR(paise, quote.currency)`; no money is
computed in the browser and no arithmetic is performed on amounts.

| Mockup row | Quote field | Sign / label |
| --- | --- | --- |
| Item name | `quote.items[].name` | with qty and per-item `unitPricePaise` base each |
| Base price | `charges.merchandisePaise` | subtotal (aggregate) |
| Supply GST (18%) | `charges.supplyGstPaise` | `+` |
| Delight (0.5%) | `charges.discountPaise` | `-`, label from `charges.discountLabel` |
| Express | `charges.deliveryPaise` | `+` when > 0, labelled from `charges.deliveryLabel` (`Express` or `Delivery`) |
| Convenience fee (2.5%) | `charges.convenienceFeePaise` | `+` |
| GST on convenience fee (18%) | `charges.convenienceGstPaise` | `+` |
| Illustrative customer total / Final total | `charges.totalPaise` | prominent Amount payable |

### Noted gap: aggregate vs per-item

The server quote exposes only AGGREGATE charge fields
(`merchandisePaise`, `supplyGstPaise`, `deliveryPaise`, `discountPaise`,
`convenienceFeePaise`, `convenienceGstPaise`, `totalPaise`), not a per-item tax
or fee split. The user's mockup shows the fee lines beside a single item, which
reads as an itemised-per-item breakdown. Those mockup lines therefore map to the
aggregate charge rows. We render only what the quote provides and do NOT invent
a per-item tax split. Delivering a true per-item fee breakdown would require a
backend change to the quote shape, which is out of scope for this phase.

## Customer summary: email / customer id

Added. `CheckoutIdentityCard` now renders an Email row and a Customer ID row
when those values are present on the identity. `profile.email` flows through
structurally and `profile.contactId` is passed explicitly as `customerId`. This
is a pure display addition; it kept `tsc` at 0 errors and touched no payment
logic. No deferral was needed.

## No pricing or payment behaviour changed

No pricing math or payment behaviour was changed. The quote is still computed,
fetched, parsed, and validated exactly as before; `src/lib/checkoutQuote.ts`
validation is unchanged; the prepare/verify/checkout request payloads, the
`expectedTotalPaise` comparison, and the Razorpay wiring in `CartPage` are
unchanged. No `amplify/functions/**` code was touched. The breakup remains a
display of server-provided integer paise only.

## Regression test

`tests/checkout-receipt.test.mjs` compiles the real `CheckoutReceipt.tsx` with
the offline TSX harness (`tests/helpers/loadTsx.mjs`, esbuild transform in a
`node:vm` sandbox, network stubbed), renders it with a minimal
`React.createElement` stub, and asserts that every charge row's formatted paise
amount and label appear, that the item name / qty / base-each appear, and that
the Final total equals `formatPaiseINR(charges.totalPaise, 'INR')`
(`300.00` rupees for the representative quote). The representative quote includes
`deliveryLabel:'Express'` and `discountLabel:'Delight'`. The test FAILS if any
breakup row is removed (verified by temporarily deleting a row).

## Verification

- `npx tsc --noEmit`: 0 errors.
- `npm test`: 64 passing subtests (baseline was 61; grew by 3).
- `npx eslint .`: 0 errors (warning count advisory).
