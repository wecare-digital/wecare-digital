# Wix removal — item-by-item resolution matrix

Re-audited against the branch head (post native-source build). The gate still
reports **203 runtime findings / 4 rules** because every native source is
additive and defaults to Wix — nothing is removed until cutover. This matrix is
the definitive "resolve each item" checklist to reach **zero Wix**.

Legend: ✅ native built · 🔁 needs native build · 🗑 dead/removable · ⚙ config ·
🔒 gated production step.

## Blog — ONE chokepoint, already seamed ✅
Every public blog read goes through the single `/seo-tools/blog-public` API:
- frontend pages `/blog`, `/blog/page/[page]`, `/blog/topic/[topic]`,
  `/blog/topic/[topic]/page/[page]`, `/post/[slug]` (via `src/lib/public-blog.ts`),
- build generators `generate-sitemap.js`, `generate-blog-rss.js`,
  `generate-blog-search-index.js`, `generate-llms-txt.js`,
- `scripts/blog_corpus_index.py`.
**None call Wix directly.** `blog_source.py` (`BLOG_SOURCE`) is the one switch;
flipping it to `aws` takes the entire blog surface off Wix. ✅ built.
Blog write path: ✅ `blog_publish.py` now has a `BLOG_SOURCE=aws` branch
(`_write_native` → `storage.create_blog_post`) that writes a published `blogPost`
record — the same record the native read path serves — and never calls Wix. The
Wix kill switch is correctly bypassed in native mode. Defaults to `wix`;
unit-tested. (`conversations-publish.yml` just invokes publish, so no workflow
change is needed for the native path.)

## Catalog / commerce — classified by importer count
| File | Importers | Role | Status |
|---|---|---|---|
| `wix_gift_cards.py` | **0** | outbound Wix gift-card REST | 🗑 dead — delete in final cleanup (has demo+tests) |
| `wix_ecom.py` | 10 | customer Wix cart/checkout + `authoritative_total_paise` | ✅ native equivalent built (`catalog_pricing`) — callers still to switch |
| `cart_v2.py` | 17 | Wix Cart V2 (the deepest knot) | 🔁 native cart ops behind `CHECKOUT_MODE` |
| `wix_writeback.py` | 3 | Wix order writeback | ⚙ already gated off-able (4 ANDed flags); disable at cutover |
| `wix_coupons.py` | 3 | outbound coupon mirror | ✅ native discount built (`coupon_discount_paise`); mirror removed after |
| `service_pricing.py` | 2 | 4 service-page prices via Wix cart | 🔁 native service pricing |
| `blog_contribution.py` | 3 | contribution product via Wix | 🔁 native contribution pricing |
| `meta_catalog_sync` read | 1 | catalogue read | ✅ `CATALOG_SOURCE=aws` built |
| `product-image-gen` | — | `WIX_CREDENTIALS_DISABLED=true` hardcoded | ⚙ Wix writes already off |
| `provider_adapters.py` (MCP) | — | thin adapter | 🔁 verify + repoint |

## The native supply total (keystone) — status ✅ mostly built
`catalog_pricing.build_price_summary`/`price_cart` produce the Wix `priceSummary`
identity and feed the unchanged `checkout_pricing.compute_quote`. Built + tested.
- ✅ **tax** — `supply_tax_paise`/`SupplyTax` (place-of-supply GST, CGST/SGST vs
  IGST), reusing `checkout_pricing.round_half_up`+`split_gst`; zero-bps path for
  GST-inclusive catalog prices (no double-tax). Built + tested.
- ✅ **service-page pricing** — `service_pricing_native.resolve_all` reads
  `ProductsTable` with the identical `{currency, prices{slug}}` contract,
  fail-closed per slug. Built + tested.
Replacing `cart_v2.calculate`:
- ✅ **inventory validation + atomic stock reservation** — `native_inventory`
  (conditional-decrement reserve, idempotent per attempt, release/rollback,
  oversell-proof). Built + tested.
- ✅ native **CartTable CRUD** — `native_cart` (create/add/set_quantity/remove/get,
  server-authoritative prices, merges lines, quotes through `price_cart`). Built +
  tested. Table CDK ✅.
- ✅ **shipping/delivery** resolver — `native_shipping` (policy-driven options +
  authoritative charge, digital-free, free-above-threshold, client can't pick a
  cheaper option). Built + tested.

**The native supply total is COMPLETE and WIRED behind the flag.** `native_cart`
(lines) + `native_inventory` (stock) + `coupon_discount_paise` (discount) +
`native_shipping` (delivery) + `supply_tax_paise` (GST) → `price_cart` → the exact
`collection_before_convenience_paise` the unchanged `checkout_pricing.compute_quote`
consumes. `native_checkout.quote_native_cart` packages this into the exact
`QuoteSnapshot` the live handler produces, and `checkout/handler.py` now calls it
when `CHECKOUT_MODE=AWS_NATIVE` (defaults to `WIX_HEADLESS`). Native blog publish
is also wired (`BLOG_SOURCE=aws`). All that remains is the owner-gated CUTOVER:
provision tables, seed from a live Wix export, shadow-run, flip the flags, then
delete the Wix modules and retire secrets/IAM/routes.

## Gift-card pepper migration — ✅ built (de-risks SPI retirement)
`gift_card_store.resolve_pepper_secret_id(env)` + `PEPPER_SECRET_ENV_KEY` let the
HMAC pepper move to `wecare/prod/security/giftcard-pepper` by CONFIG FLIP, with no
re-keying (identical value → identical `code_hash`). Handlers
(`invoice-engine`, `gift-cards`) + the redemption provider now follow it. The
store still imports no `os` (structural rule preserved). Built + tested. The 🔒
ops step is copying the pepper value to the new secret and setting the env.

## Gift-card SPI (inbound) — the one true hazard
- `GiftCardsTable` balances are AWS-authoritative; removing Wix loses no money.
- `wix-giftcard-spi` is INBOUND (Wix calls us), auth `wecare/wix/giftcard-spi`.
- 🔁 **`code_pepper` migration FIRST**: the pepper is the HMAC key for every card
  lookup and lives inside the Wix SPI secret. Migrate it to a non-Wix secret
  (`wecare/prod/security/giftcard-pepper`) and repoint `read_pepper` BEFORE
  retiring the SPI, or every card becomes unlookupable.
- 🔒 confirm Wix no longer calls the SPI (metric), then decommission.

## Frontend ⚙
`src/config/wix.ts` (public ids), `src/content/shop.ts` (imports `wix-catalog.json`),
`src/lib/cart.ts`, `src/api/client.ts`, dashboard architecture page. Switch
`shop.ts` to `catalog-snapshot.json` ✅ (generator built); remove `wix.ts` at the end.

## Resolution order (to zero Wix)
1. ✅ Native sources for all reads (blog, catalog, meta-sync) — DONE.
2. 🔁 Native supply tax/shipping/inventory + CartTable ops.
3. 🔁 Native service-page + contribution pricing (drop their `cart_v2` use).
4. 🔁 `code_pepper` migration out of the Wix SPI secret.
5. 🔁 Native blog publish (replace `blog_publish.py` Wix writes).
6. 🔒 Seed `ProductsTable`/`BlogPostsTable` from live Wix export; shadow-run.
7. 🔒 Flip `BLOG_SOURCE`/`CATALOG_SOURCE`/`CHECKOUT_MODE`; disable writeback.
8. 🗑 Delete dead `wix_gift_cards.py`, coupon mirror, `cart_v2`, `wix_ecom`,
   `wix_writeback`, `src/config/wix.ts`; retire Wix secrets/IAM/routes/workflows.
9. ✅ Gate flips to blocking (0 findings).
