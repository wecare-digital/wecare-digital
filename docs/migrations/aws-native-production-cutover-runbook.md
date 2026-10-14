# AWS-native production cutover runbook (backlog items 1–7)

Owner-approval-gated production steps that unblock the remaining Wix-exit backlog. Every step is
a production mutation (🔒) and must be run with explicit owner approval. Each has a verification
and a rollback. Nothing here runs automatically.

## Verified live state (us-east-1, acct 775261844268) — captured 2026-10-14

| Resource | State | Implication |
|---|---|---|
| `wecare-checkout` live alias | **v49** (`CHECKOUT_MODE=AWS_NATIVE`, `CATALOG_SOURCE=aws`, `WIX_CART_V2_ENABLED=false`) | Native supply path is live; the "v48" in the audit is stale. |
| `stack-wecare-digital-ProductsTable` | **ACTIVE, 0 items**, stream `NEW_AND_OLD_IMAGES` enabled | Exists and stream-ready; **empty** — the storefront/catalog serve nothing until seeded. |
| `stack-wecare-digital-CartTable` | **ACTIVE** | Native cart store ready (claim-basket/customer-cart adapter backs onto it). |
| `wecare-wix-store`, `wecare-wix-catalog-webhook` | **still deployed** | Item 7 retirement pending. |
| `wecare-meta-catalog-sync-schedule` | EventBridge rule present (6h backstop) | Keep as backstop; the stream trigger makes sync near-instant. |
| `outputs/products-seed.json` | 10 products / 23 variants, production-quality copy | Ready to load into ProductsTable. |

---

## GATE A — Seed the live ProductsTable (unblocks items 1, 3, 4-data) 🔒

**Why:** ProductsTable is ACTIVE but empty, so `/shop` and native checkout read an empty catalog.
**Prerequisite:** confirm the seed is the reconciled production copy (not the thin stub):
```sh
.venv/bin/python -c "import json;d=json.load(open('outputs/products-seed.json'));print(len(d),'products',sum(len(p.get('variants') or []) for p in d),'variants')"
# expect: 10 products 23 variants
```
**Apply (🔒 writes to the live table):**
```sh
CONFIRM=I-APPROVE-seed-products \
PRODUCTS_TABLE=stack-wecare-digital-ProductsTable \
  .venv/bin/python scripts/seed_products_from_wix.py --apply   # loads outputs/products-seed.json shape
```
> NOTE: `seed_products_from_wix.py --apply` reads live Wix (now gone). Prefer loading the
> committed reconciled seed directly instead — a one-off `batch_write_item` of
> `outputs/products-seed.json`, Decimal-encoded, keyed on `id`. (Add `--from-file
> outputs/products-seed.json` support if not present.)
**Verify:**
```sh
AWS_PAGER="" aws dynamodb describe-table --region us-east-1 \
  --table-name stack-wecare-digital-ProductsTable --query 'Table.ItemCount'   # expect ~10
```
**Rollback:** delete the 10 seeded items by `id` (recorded in the seed file). The table is RETAIN;
seeding is additive and reversible per-item.

## GATE B — Generate + commit the native catalog snapshot, rebuild /shop (item 1 frontend)

**Why:** the static export reads `src/content/catalog-snapshot.json`.
```sh
PRODUCTS_TABLE=stack-wecare-digital-ProductsTable \
  .venv/bin/python scripts/build-catalog-snapshot.py --live       # reads the now-seeded table
.venv/bin/python scripts/check_native_catalog_snapshot.py          # count/slug parity gate
git add src/content/catalog-snapshot.json && git commit -m "chore(catalog): snapshot from seeded ProductsTable"
```
**Verify:** `/shop/<slug>` builds for all 10 slugs; `aws-native-catalog-publish.yml` run is green.
**Rollback:** revert the snapshot commit (restores the prior committed snapshot).

## GATE C — Wire + deploy the native catalog-change stream trigger (unblocks item 6) 🔒

**Why:** replaces the retired Wix catalog webhook — a ProductsTable write fans out to meta-sync.
**Prereq:** `amplify/catalog-resources.ts` `addCatalogStreamTrigger()` is prepared but NOT called in
`amplify/backend.ts` (grep returns 0). Wiring it creates a live event-source mapping.
```sh
# 1. In amplify/backend.ts, import and call addCatalogStreamTrigger(dataStack, productsTable).
# 2. Deploy the Amplify backend (creates the DynamoDB-stream -> wecare-meta-catalog-sync:live mapping).
npx ampx pipeline-deploy --branch stack   # or the repo's standard deploy path
```
**Verify:**
```sh
AWS_PAGER="" aws lambda list-event-source-mappings --region us-east-1 \
  --function-name wecare-meta-catalog-sync:live \
  --query "EventSourceMappings[?contains(EventSourceArn,'ProductsTable')].State"   # expect Enabled
# then: edit one product in ProductsTable -> confirm a meta-catalog-sync invocation logs source=ddb-stream
```
**Keep** `wecare-meta-catalog-sync-schedule` as the 6h backstop (idempotent full re-read).
**Rollback:** disable/delete the event-source mapping; the schedule still keeps Meta in sync.

## GATE D — Confirm checkout release (item 2)

v49 is already live and native. No action unless a newer build is pending; if so:
```sh
.venv/bin/python scripts/deploy_all_lambdas.py --dry-run   # validate imports/handlers
# then deploy wecare-checkout and move the live alias (snapstart_publish.py).
```
**Verify:** a native website prepare + a WhatsApp claim-basket both price from ProductsTable with
no Wix call (the `test_whatsapp_order_cannot_charge_twice` guarantee holds in prod logs).

## GATE E — Product media migration (item 4) 🔒

Nine products reference `static.wixstatic.com` images.
```sh
.venv/bin/python scripts/migrate_catalog_media_to_s3.py --dry        # list the 9, no writes
CONFIRM=... .venv/bin/python scripts/migrate_catalog_media_to_s3.py --apply   # copy to S3, repoint imageRefs
```
**Verify:** no ProductsTable `imageRefs` contains `wixstatic.com`; `/shop` images load from `wecare.digital/get/...`.
**Rollback:** imageRefs are per-item; restore the prior Wix URL per product (recorded by the script).

## GATE F — Retire the Wix cloud surface (item 7) 🔒 — LAST, after A–E verified

Only after native catalog + checkout + meta-sync are proven live:
1. Remove the API Gateway routes `GET/POST /wix-store/{proxy+}` and `POST /wix-catalog-webhook`.
2. Delete (or repurpose) the Lambdas `wecare-wix-store`, `wecare-wix-catalog-webhook` — confirm no
   remaining callers first (`aws lambda get-policy`, CloudWatch invocation count = 0 for 7 days).
3. Do NOT touch unrelated ecommerce/WhatsApp APIs.
**Verify:** production operates with the Wix routes/functions gone; no 5xx on `/shop`, `/blog`,
checkout, or meta-sync.
**Rollback:** the functions/routes are redeployable from this repo; keep the last snapshot/zip.

---

## Sequence & dependencies
A (seed) → B (snapshot/rebuild) → C (stream trigger) → D (confirm checkout) → E (media) → **F (retire Wix) last**.
Secrets/IAM cleanup (items 11–12) and the final savings measurement (item 14) follow F and are in
`secrets-consolidation.md` / `aws-cost-optimization.md`.

## What is NOT in this runbook (and why)
- **Items 8** (remaining `cart_v2`/`wix_ecom`/`wix_guard` code removal) — pure code, tracked
  separately; does not require a production gate until the modules are deleted.
- **Item 13** (Lightsail capacity) — needs guest SSH access; see `lightsail-nano-feasibility.md`.
- **Item 10** (historical data reconciliation) — needs the Wix export report; see
  `wix-data-reconciliation.md`.
