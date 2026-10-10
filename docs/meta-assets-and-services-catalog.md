# Meta assets and the services catalogue

The canonical ids for every Meta asset WECARE.DIGITAL uses, and the catalogue they describe.
Written 2026-10-10 from the owner's own list and from a live read of the Wix storefront, so it
records what is live rather than what was planned.

**Wix is the single source of truth for products, variants and prices.** Nothing in this
repository decides what a service costs: `src/content/wix-catalog.json` is a committed snapshot
written by `node scripts/fetch-wix-catalog.js`, and the live price a customer is charged comes
from `cart_v2.calculate` on the one checkout path. Re-run that script after any catalogue edit in
Wix. The Meta catalogue mirrors the same five variants, so Wix remains upstream of Meta too.

## Meta assets

| Asset | ID | What it is |
|-------|-----|------------|
| Meta Catalog | 1457045652952851 | The canonical WECARE.DIGITAL service catalogue |
| Meta Pixel | 3411484995761247 | Website / browser Pixel |
| Meta Dataset (CAPI) | 4554612361454941 | Server-side Dataset, the Conversions API event destination |
| Meta App | 2238810740192680 | The WABA1 app / source |
| WABA1 | 2094615664435155 | WhatsApp Business Account |
| WABA1 phone number | 1016149501586345 | +91 93309 94400 |

The Dataset id is **server-side only**: it is never sent to `fbq` in the browser. Both it and the
Pixel id are declared in `src/config/analytics.ts`; the Pixel is the only one the page loads
(`src/pages/_document.tsx`), and `NEXT_PUBLIC_META_PIXEL_ID` can override it per environment.

## The five paid services

One Wix product carries all five, as variants of its single `Service` option.

- Product: `Request` (slug `wecaredigital-services`), `df976a0a-f582-4535-b2e1-d532f348bd27`
- Option: `Service`, `aee30ab6-72bd-4a04-ac83-0234652ad0ee`
- Currency: INR, product type PHYSICAL, visible

| Service | Price | Variant ID | Choice ID | SKU | Page |
|---------|-------|------------|-----------|-----|------|
| Submit Request | ₹99 | e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b | 2af81a87-24a8-4729-80bf-1d967a637bc2 | SERVICE-SUBMIT-REQUEST | `/submit-request/` |
| Request Amendment | ₹350 | 864fc9a7-c326-4b4d-b0e5-6dc0ea5b764b | 7111e864-e789-4641-8f28-74240af61561 | SERVICE-REQUEST-AMENDMENT | `/request-amendment/` |
| Drop Docs | ₹350 | db166bc8-a763-41ec-9f65-0f718f18155a | f981b729-748a-48ee-93b9-54ecc543b617 | SERVICE-DROP-DOCS | `/drop-docs/` |
| Vault | ₹49 | dcff995e-448c-493a-9259-f6a82ccdc2b4 | bdaafdcf-7998-4d43-b7dd-1ab40cc6566c | SERVICE-VAULT | `/vault/` |
| Request Pickup | ₹350 | 8ee7e325-d772-4452-a993-5c79e927d42b | faa3b648-1fba-41ad-a5f2-f84bd2524070 | SERVICE-REQUEST-PICKUP | `/request-pickup/` |

The variant id is the only one of the three that travels in a cart line
(`catalogReference.options.variantId`) and the only one the server's allow-list keys on. The
choice id and SKU are reference metadata, carried so the declaration in `src/config/services.ts`
matches the snapshot without a second hand-typed copy of the catalogue. Prices are shown here for
reading; the pages read them live through `servicePricing`, so this table going stale cannot
change what a customer is charged.

Four of the five require a target Submit Request — an amendment amends one, Drop Docs sends
documents for one, Vault asks for a copy held against one, and a pickup collects paperwork for
one. The server owns that rule (`TARGET_REQUIRED_KINDS` in
`amplify/functions/shared/lambda_utils/ecommerce/service_requests.py`).

## Contribute

A separate product, and not a service: one variant, ₹250.

| Product | Product ID | Variant ID | Choice ID | Price |
|---------|-----------|------------|-----------|-------|
| Contribute | 8514c405-3971-4786-ad0d-15406ca23407 | 8ad6f376-a526-4631-b510-0e047b33a5b9 | 616cbd34-a1ad-4fe7-82b5-1d28e901aebc | ₹250 |

It carried three variants — ₹100, ₹250, ₹500 — until the owner removed two in Wix on 2026-10-10.
The deleted ids (`ab4ee1a2-1568-4dc4-abe1-55e24fa51576` and
`19283bd8-a61d-455e-a992-79eb10b9228f`) are gone from the code as well as from the catalogue: a
variant Wix has deleted cannot be priced, so a button offering one would fail at checkout rather
than collect anything.

## The free flows are not catalogue products

These are **not purchasable and are not in the Meta catalogue**. They are ways to interact with
us, not things we sell, and nothing in them reaches a payment path:

Orders · Track Request · Shipments / Track Shipment · Scan Tracking · Leave Review ·
Subscribe / Profile · Pay / Check Dues

Adding one of them to the catalogue would advertise a price for something that has none.

## Owner action outstanding: per-variant artwork (Option A)

The snapshot is taken exactly as Wix returns it, with no images imported into this repository and
no artwork committed here. When the five service variants were first synced they all shared the
product's main image, which was accepted rather than treated as a blocker — the owner adds
artwork in Wix, and a re-run of `scripts/fetch-wix-catalog.js` picks it up. The 2026-10-10 refresh
shows each variant now carrying its own image URL, so that action is in progress; any variant that
still shares the product image is a Wix-side edit, not a code change.
