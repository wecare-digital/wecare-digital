# Wix code-removal map (post-cutover structural refactor)

Runtime is now AWS-native (ProductsTable seeded; `BLOG_SOURCE=aws`,
`CATALOG_SOURCE=aws`, `CHECKOUT_MODE=AWS_NATIVE`, Wix cart/writeback off; Wix admin
secrets force-deleted). The Wix code still *compiles and imports* but its branches
are no longer *executed* — imports ≠ execution. This map is the exact order to
remove the code safely. The naive `rm` is wrong: several `wix_*` modules carry
provider-neutral logic the native path still needs.

## Classification (from the live import graph)

### A. DELETE NOW — zero importers, dead at runtime
| Module | Why safe |
|---|---|
| `ecommerce/wix_gift_cards.py` | 0 runtime importers (structural test asserted it stays unwired). PR #434 removes it + its demo/tests. |

### B. GUARD THE CALL SITE, THEN DELETE — imported, but the Wix branch is already dead under current flags
| Module | Importer / call site | Status under live flags | Action |
|---|---|---|---|
| `wix_ecom.py` (`create_checkout`, `authoritative_total_paise`) | `checkout/handler.py:859-876` | DEAD — `_supply_mode()==AWS_NATIVE` takes the native branch at :797 | remove the V1 Wix branch, then drop the import |
| `cart_v2.py` | `checkout/handler.py:505-509` (service prices), `wix-store/handler.py` | DEAD for service prices (native branch at :487); `wix-store` Lambda is being retired | remove dead branches; delete with `wecare-wix-store` |
| `wix_writeback.py` | `finalization.py:287` | DEAD — `wix_writeback.is_enabled()` is false (`WIX_WRITEBACK_ENABLED=false`) | remove the writeback block, then drop import |
| `wix_coupons.py` | `coupons/handler.py:231` `_wix().create()` | **NOT guarded** — still mirrors to Wix on every coupon create; now FAILS (admin key gone) but degrades gracefully (local row authoritative, logs `coupon_mirror_pending`) | add a `CATALOG_SOURCE=aws` guard to skip the mirror, then delete `wix_coupons` |
| `wix_webhook.py` | `wix-catalog-webhook/handler.py` | the whole Lambda is a Wix inbound webhook, now orphaned (catalog source is AWS) | delete with `wecare-wix-catalog-webhook` |
| `operations/seo-tools/wix.py` + `wix_guard.py` | `seo-tools/handler.py`, `blog_publish.py` | DEAD — `BLOG_SOURCE=aws` routes reads+publish to the native store | remove the Wix read/publish branches, drop `wix`/`wix_guard` imports |

### C. EXTRACT NEUTRAL LOGIC FIRST — the module name says "wix" but it carries load-bearing provider-neutral code
| Module | Neutral symbol still needed | Consumer | Action |
|---|---|---|---|
| `wix_domain.py` | `_generate_wd_order_number` (WD-prefixed, date-based order number — NOT Wix-specific) | `order_keys.py:679` | move it to a neutral `ecommerce/order_number.py`, repoint `order_keys`, then delete the Wix-shaped remainder of `wix_domain` |
| `wix_address.py` | `india_subdivision`, `gst_state_code`, `UnmappableAddress` (India GST place-of-supply logic — provider-neutral, still used by native pricing) | `payment_address.py` | rename to `ecommerce/india_address.py` keeping those; drop only `to_wix_address` |

### D. AWS resources to retire (after B/C land)
- Lambdas: `wecare-wix-store`, `wecare-wix-catalog-webhook` (delete function + API Gateway routes `GET/POST /wix-store/{proxy+}`, `POST /wix-catalog-webhook`).
- Secrets: the 3 Wix secrets are already force-deleted; verify no restore and purge the gift-card SPI secret only AFTER migrating `code_pepper` to `wecare/prod/security/giftcard-pepper` (the pepper is the HMAC key for every gift-card lookup — see wix-subsystem-deep-audit.md).
- IAM: remove the now-unused Wix GetSecretValue grants from `wecare-checkout-role`, `wecare-meta-catalog-sync-role`, `wecare-wix-catalog-webhook-role` (keep the ProductsTable grants added at cutover).
- EventBridge: `wecare-meta-catalog-sync-schedule` can stay (it re-reads the AWS catalog now); the `catalogue-sync.yml` Wix fetch workflow is retired.
- Frontend: `src/config/wix.ts`, repoint `src/content/shop.ts` from `wix-catalog.json` to the generated `catalog-snapshot.json`, remove Wix mentions in dashboard/analytics pages.

## Removal order (each a reviewable PR; CI gate flips to blocking at the end)
1. **PR-1 (safe now):** delete `wix_gift_cards` (A). → PR #434, open.
2. **PR-2:** guard the coupon mirror on `CATALOG_SOURCE` (stops the only unguarded live Wix call).
3. **PR-3:** extract `_generate_wd_order_number` → `order_number.py`; rename `wix_address` → `india_address` (C). Pure moves + repoints; tests stay green.
4. **PR-4:** remove the dead Wix branches in `checkout`/`finalization`/`seo-tools` and drop the `wix_ecom`/`cart_v2`/`wix_writeback`/`wix.py`/`wix_guard` imports (B).
5. **PR-5:** delete the Wix modules themselves + the 2 Wix Lambdas + routes + IAM grants (D). `check-wix-policy.sh` reaches 0 → drop `--expect-fail`, gate goes blocking.
6. Owner: cancel/delete the Wix site in the console.

## Guardrail
`check-wix-policy.sh` currently reports ~204 findings. After PR-5 it must reach 0;
that is the acceptance signal to flip `.github/workflows/wix-exit-policy.yml` to a
blocking gate so Wix can never be reintroduced.
