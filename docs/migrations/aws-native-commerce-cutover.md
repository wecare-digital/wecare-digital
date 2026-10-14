# AWS-native commerce cutover

Covers the store/catalog/checkout move (Gate 3 → Gate 4). The commerce
*transaction* backend is already AWS-native and verified; this is about moving
the price/catalog SOURCE off Wix without touching payment safety.

## What is already AWS-native (reuse, do not rebuild)
`payment_attempt.py`, `order_keys.py`, `order_creation.py`, `razorpay-webhook`,
`OrderTable`, `InvoicesTable` family. "Order only after verified payment" is
implemented, idempotent, and tested (`docs/commerce-implementation-audit.md`).
Razorpay acquiring stays — AWS does not provide card acquiring.

## What is still Wix-coupled (the cutover surface)
- Authoritative total: `wix_ecom.authoritative_total_paise` (live Wix cart).
- Cart ops: `cart_v2.py` (Wix Cart V2, `WIX_CART_V2_ENABLED=true`).
- Order writeback: `wix_writeback.py` (`WIX_WRITEBACK_ENABLED=true`).
- Display catalog: `fetch-wix-catalog.js` → `wix-catalog.json` → `shop.ts`.
- Service prices: live Wix reads in `checkout/handler.py`.
- Meta sync: `meta-catalog-sync` reads live Wix.

## Native replacements (flag-gated, default = Wix)
| Concern | Native component | Flag |
|---|---|---|
| Pricing authority | `catalog_pricing.authoritative_total_paise` (reads `ProductsTable`, integer paise) | `CHECKOUT_MODE=AWS_NATIVE` |
| Cart | `CartTable` + native cart module | `CHECKOUT_MODE` |
| Discounts/tax/shipping/inventory/reservation | `ecommerce/native/*` | `CHECKOUT_MODE` |
| Display catalog | `build-catalog-snapshot.py` → `catalog-snapshot.json` | `CATALOG_SOURCE=aws` |
| Meta sync source | `meta-catalog-sync` reads `ProductsTable`; DDB-stream event | `CATALOG_SOURCE=aws` |
| Order record | internal `OrderTable`/`InvoicesTable` only; writeback OFF | `CHECKOUT_MODE` |

## Payment-safety invariants (must hold on the native path)
- Amount from server-side `ProductsTable`/cart in integer paise; NEVER
  client-supplied prices.
- Razorpay signature verification unchanged; order finalized only after verified
  capture; idempotent via existing `order_keys`/`payment_attempt`.
- No second settlement flow. No duplicate charges/orders. Safe retries.
- Inventory consistency + reservation on the native path mirrors current guarantees.

## Cutover sequence (Phase 6, each 🔒)
1. Seed `ProductsTable` from reconciled export (Gate 2/3).
2. Shadow-run: compute native total alongside Wix total for live carts; assert
   paise-for-paise equality in logs (no customer impact) until confidence.
3. Flip `CATALOG_SOURCE=aws` (snapshot + meta-sync read AWS). Verify Meta catalog
   parity + approvals/dry-run gates intact.
4. Flip `CHECKOUT_MODE=AWS_NATIVE` (pricing/cart native, writeback OFF). Place a
   real test order; verify payment verification + order/invoice creation.
5. Decommission `catalogue-sync.yml` Wix fetch; retire `wecare-wix-store` routes
   after confirming no callers.
6. Gate 4: run checkout e2e with Wix hosts blocked.

## Rollback
Set `CHECKOUT_MODE=WIX_HEADLESS` and `CATALOG_SOURCE=wix`. Because writeback was
OFF on the native path, no Wix order drift accumulated; internal orders remain the
record of truth either way. Re-enable `catalogue-sync.yml` if needed.
