# Wix subsystem deep audit — what each system actually needs

Evidence-backed trace of every active Wix-coupled subsystem (read-only,
2026-10-14). This is the "what we have" map that the complete removal builds on.
Surface size: **~65 runtime files**, **203 Wix references** (`check-wix-policy.sh`),
~20k lines in the `ecommerce/` library.

## Headline: the money is already AWS-native. Wix owns pricing arithmetic + 2 I/O seams.

| Subsystem | Source of truth | Wix role today | Direction | Removal risk |
|---|---|---|---|---|
| Blog | Wix (visitor-token reads) | authoritative content | outbound (us→Wix) | content export + reconcile |
| Catalog display | Wix snapshot | authoritative product data | outbound | export + native snapshot |
| Checkout supply total | **Wix** (`cart_v2.calculate`) | computes subtotal/discount/delivery/tax | outbound | **build native supply engine** |
| Convenience fee + GST | **AWS** (`checkout_pricing.py`) | none | — | none — already native |
| Payment amount | **AWS** (`CheckoutQuote`) | none (Wix total is only an input) | — | none |
| Orders/invoices | **AWS** (`OrderTable`/`InvoicesTable`) | optional writeback (gated off-able) | outbound | none — AWS is record of truth |
| Gift-card balances | **AWS** (`GiftCardsTable`) | inbound SPI (Wix calls us) + dead outbound client | **inbound** | pepper + SPI order |
| Coupons | **AWS** (`CouponsTable`) | website pricing (Calculate Cart) + outbound mirror | outbound | native discount pricing first |
| Meta catalog sync | Wix catalog | reads live Wix | outbound + webhook trigger | native product events |

## 1. Checkout / cart / pricing (the real work)
- `checkout_pricing.compute_quote(collection_before_convenience_paise)` is a
  **complete, float-free native calculator** (2.5% fee + 18% GST-on-fee,
  CGST/SGST vs IGST, policy `checkout-pricing-2026-10-01`). It takes the supply
  total as an **input** and never computes supply.
- The ONLY Wix dependency in the money path is the **supply total**:
  `wix_ecom.authoritative_total_paise(checkout)` reads
  `checkout["priceSummary"]["total"]["amount"]`; `cart_v2.calculate` asserts the
  identity `subtotal − discount + delivery + additionalFees + tax == total` and
  `sum(line.totalPrice) == subtotal`.
- **Razorpay amount = native `CheckoutQuote.total_payable_paise`** (supply total +
  fee + GST), never the raw Wix total; gift card is subtracted as tender.
- **Writeback is gated behind 4 ANDed flags** (`WIX_WRITEBACK_ENABLED`,
  `WIX_ECOM_WRITE_CONFIRMED`, `WIX_SITE_ID==CONFIRMED_SITE_ID`,
  `WIX_CART_V2_WRITE_CONTRACT=="cart-v2-external-v1"`), defaults off; when off the
  internal order is retained in `NEEDS_RECONCILIATION`, never half-written.
- **What to build:** a native supply engine over `ProductsTable` that produces
  `collection_before_convenience_paise` (the one integer `compute_quote` needs).
  Nothing in `checkout_pricing`/`website_checkout`/`order_creation`/`finalization`
  needs to change — only the *source* of that integer. This is the keystone and
  it is small in surface, large in care (tax/discount/delivery correctness).

## 2. Gift cards (inbound SPI — order matters most here)
- `GiftCardsTable` is the **authoritative liability ledger** (balancePaise, HMAC
  code keying, conditional/transactional moves, disable-not-delete, TTL off).
  Removing Wix loses **no** balance.
- Wix coupling is **INBOUND**: `wix-giftcard-spi` Lambda exposes
  `/wix-giftcards/v1/{balance,redeem,void}` that **Wix calls into us**,
  authenticated by the `wecare/wix/giftcard-spi` secret (RSA public key, app_id,
  instance_id — and `code_pepper`).
- **Trap:** `code_pepper` is NOT a Wix credential — it is the HMAC key for every
  gift-card row lookup. Deleting the secret wholesale makes every existing gift
  card unlookupable. **Migrate `code_pepper` to a non-Wix secret FIRST**, repoint
  `read_pepper`/`SECRET_ID`, THEN retire the SPI auth + handler.
- `wix_gift_cards.py` (outbound REST client) is **dead code** (no importer; a
  structural test asserts it) — safe to delete anytime.
- Design note: the handler says "Wix SHOULD NEVER call /redeem" and alarms on it,
  so the inbound surface may be effectively idle — confirm via the metric before
  decommissioning.

## 3. Coupons (outbound only — lower risk)
- `CouponsTable` owns definitions/usage/limits/holds (AWS authoritative). Wix is
  only the **website discount arithmetic** (Calculate Cart) + an outbound mirror
  (`wix_coupons.py` → `/stores/v2/coupons`, secret `wecare/wix/headless-api-key`,
  never reads a number back).
- Native `coupon_store.discount_paise` + `redemption.apply_coupon` already price a
  coupon from the definition (used for invoices today).
- **Build order:** wire native discount pricing into the website checkout path
  (so the discount materializes without Wix Calculate Cart) BEFORE removing the
  mirror — else coupons validate but don't discount.

## 4. Meta catalog sync (outbound + webhook trigger)
- `meta-catalog-sync` reads live Wix `/stores/v3/products/search` +
  `/query-variants`, projects onto Meta catalog `1457045652952851` (shared by both
  WABAs), behind approval + dry-run gates (owner-scoped rollout 2026-10-08: only
  Submit Request + Vault enabled, held out of stock).
- Trigger is content-free: webhook or EventBridge both mean "re-read the whole
  catalogue". Replace the Wix read with a `ProductsTable` read and the webhook
  trigger with a DynamoDB-stream product-change event. Preserve catalog id,
  approvals, dry-run, retailer-id contract (all in the pure
  `lambda_utils/ecommerce/meta_catalog_sync.py`).
- **BUILT:** `_native_products()` + `CATALOG_SOURCE` gate in the sync handler
  project `ProductsTable` onto the exact slim shape `desired_items` consumes
  (defaults to `wix`). Unit-tested.
- **HARD REQUIREMENT discovered:** `desired_items` enforces the retailer-id
  contract `wix:<productUUID>:<variantUUID>` (RetailerIdError otherwise) — it is
  the Meta↔catalog join key. So **`ProductsTable` MUST mint RFC-4122 UUIDs for
  product ids AND variant skus/ids**. The Wix export preserves the existing Wix
  UUIDs as `sourceId`/`id`, so seeded products satisfy this; net-new native
  products must generate UUIDs. (A product/variant id that is not a UUID fails
  closed at sync time, which is the correct, visible failure.)

## 5. Blog (outbound reads)
- Covered in `aws-native-wix-exit.md`; the `BLOG_SOURCE` seam
  (`blog_source.py`) is built and defaults to Wix. Native branch reads published
  `blogPost` records from `SeoToolsTable` via `storage._blog_view`.

## Removal order (derived from the above)
1. Build native supply pricing (`catalog_pricing`) + `ProductsTable`; shadow-run
   against Wix totals (paise-for-paise) — no customer impact.
2. Wire native coupon discount into website checkout; keep mirror.
3. Flip `CATALOG_SOURCE=aws` (snapshot + meta-sync read AWS).
4. Flip `CHECKOUT_MODE=AWS_NATIVE` (supply total native, writeback off).
5. Flip `BLOG_SOURCE=aws`.
6. **Migrate `code_pepper` out of the Wix SPI secret** (gift-card lookups keep
   working).
7. Confirm Wix no longer calls the gift-card SPI (metric); decommission SPI.
8. Remove coupon mirror + `wix_coupons`; delete dead `wix_gift_cards.py`.
9. Retire Wix secrets (except the migrated pepper), IAM, routes, workflows.

Each of steps 3–9 is production-mutating → owner approval.
