# Design — AWS-Native Consolidation & Cost Optimization

This design is grounded in the live account (775261844268 / us-east-1) and the
real repository at `/Users/wecaredigital/wecare-digital`. It reuses existing
infrastructure and the project's actual provisioning pattern.

## Grounding facts that shape every decision

1. **`amplify/data/resource.ts` is inert.** It declares 58 `a.model()` models but
   0 AppSync APIs exist and none were ever materialised. The 77 live DynamoDB
   tables are created by **CDK** (`amplify/seo-resources.ts`,
   `backend-resources.ts`, `link-resources.ts`) and `scripts/provision_*.py`
   under the `stack-wecare-digital-*` scheme, and Python Lambdas address them by
   name through `os.environ`. **New native stores MUST follow this CDK/provision
   pattern — not `a.model()`** — or Amplify would create empty parallel tables.

2. **Wix is still authoritative at runtime** for blog (anonymous visitor-token
   reads through `wecare-seo-tools` `/blog-public`) and for the shop display
   catalog (6-hourly `fetch-wix-catalog.js` → `src/content/wix-catalog.json`) and
   for the checkout authoritative total (`wix_ecom.authoritative_total_paise`).

3. **The commerce transaction backend is already AWS-native and verified**
   (`payment_attempt`, `order_keys`, `order_creation`, `razorpay-webhook`,
   `OrderTable`, `InvoicesTable` family). It must be *reused*, not rebuilt. Only
   the price/total source and the Wix order writeback are Wix-coupled.

4. **The kill switch is read-only-safe by design.** `wix_guard.py` deliberately
   does NOT block anonymous visitor reads, so disabling admin creds does not take
   the blog off Wix. True independence requires replacing the read path, not just
   flipping the flag.

5. The static-export build fails if the blog API returns empty — so the native
   read path MUST fail safe (serve last-known-good), never emit an empty blog.

---

## A. Native CMS (blog) architecture

### Store
Reuse the existing CDK provisioning pattern (mirrors `seo-resources.ts`). Add a
dedicated table (new, provisioned via CDK with `RETAIN` + PITR):

- **`stack-wecare-digital-BlogPostsTable`**
  - PK `id` (string, immutable Wix post id preserved as `sourceId`).
  - GSI `slug-updatedAt-index` (public detail lookup by slug).
  - GSI `status-publishedAt-index` (list published, newest first; `status` ∈
    `draft|scheduled|published|archived`).
  - GSI `category-publishedAt-index` (category/tag listing).
  - Attributes: `title`, `slug`, `status`, `publishedAt`, `updatedAt`,
    `authorId`, `authorName`, `categories[]`, `tags[]`, `excerpt`,
    `contentRef` (S3 key for rich body), `coverImageRef`, `seoTitle`,
    `seoDescription`, `canonicalUrl`, `redirectFrom[]`, `faqRef`.
- Rich body + media: existing **S3** (`wecare-digital-get`) under
  `blog/content/<id>.json` (Wix Ricos/rich JSON) and `blog/media/...`.
- Authors/categories/tags: small items in the same table under a `recordType`
  discriminator reusing the existing `recordType-createdAt-index` convention.

Why a new table rather than overloading `SeoToolsTable`: `SeoToolsTable` is the
*audit/draft* pipeline (SEO audits, QA runs). Mixing the published corpus of
~1,300 posts into it would blur the audit retention model and the GSIs. A
separate table keeps blog-as-content and SEO-as-audit cleanly separated, both
PAY_PER_REQUEST (negligible cost).

### Public read API (replaces the Wix path)
Extend `wecare-seo-tools` (already serves `/blog-public`): add a native read
behind a flag so cutover is reversible.

- New env flag **`BLOG_SOURCE`** ∈ `wix | aws` (default `wix` until cutover).
- `/seo-tools/blog-public` and `/blog-public/{slug}`:
  - `BLOG_SOURCE=aws` → read `BlogPostsTable` + S3 body (no Wix call).
  - `BLOG_SOURCE=wix` → current behaviour (unchanged).
- `src/lib/public-blog.ts` is unchanged — it already calls the AWS endpoint; only
  the Lambda's data source flips. This is the key reversibility lever.

### Admin (Blog Studio)
`blog-studio.tsx` / `blog-manager.tsx` already talk to authenticated seo-tools
routes. Add native create/edit/delete/publish/schedule/approve routes writing to
`BlogPostsTable` + S3, behind the same `BLOG_SOURCE` flag, preserving all current
UI functionality and SEO fields.

### Build-time fail-safe
`generate-public-pages.js` / blog generators read the native endpoint; on a
read failure they reuse the last successful snapshot committed under
`src/content/blog-snapshot.json` (provider-independent artifact) rather than
emitting an empty blog (satisfies A5.3 and the build-fail-safe requirement).

---

## B. Native catalog & commerce architecture

### Catalog store (provider-independent)
Add via CDK (mirrors the pattern), reusing `CatalogCacheTable` only as a *cache*,
not the source of truth:

- **`stack-wecare-digital-ProductsTable`**
  - PK `id`; GSI `slug-updatedAt-index`, `status-updatedAt-index`
    (`draft|active|archived`), `category-updatedAt-index`.
  - Attributes: `title`, `slug`, `sku`, `priceMinor` (integer paise),
    `currency` (`INR`), `variants[]` (each with `sku`, `priceMinor`,
    `inventory`, `options{}`), `inventory`, `categories[]`, `imageRefs[]`
    (S3), `taxClass`, `seoTitle`, `seoDescription`, `canonicalUrl`, `status`,
    lifecycle timestamps.
- Images in existing S3; the committed `wix-catalog.json` is replaced by a
  generated **`src/content/catalog-snapshot.json`** built from `ProductsTable`.

### Static generation
`scripts/fetch-wix-catalog.js` / `refresh-wix-catalog-safe.js` are replaced by
`scripts/build-catalog-snapshot.py` that reads `ProductsTable` and writes
`catalog-snapshot.json`. `src/content/shop.ts` imports the new snapshot. Routine
catalog edits publish via a product-change event (below) and only trigger a
rebuild when a published field changes — not on every poll.

### Commerce (reuse, don't rebuild)
- Authoritative total: new `catalog_pricing.authoritative_total_paise(cart)` that
  computes server-side from `ProductsTable` in integer paise, replacing
  `wix_ecom.authoritative_total_paise`. Selected by **`CHECKOUT_MODE`** ∈
  `WIX_HEADLESS | AWS_NATIVE` (default `WIX_HEADLESS` until cutover).
- Cart: AWS-native cart in a `stack-wecare-digital-CartTable` (CDK), replacing
  `cart_v2.py`'s Wix Cart V2 when `CHECKOUT_MODE=AWS_NATIVE`.
- Discounts/taxes/shipping/inventory/reservation: native modules under
  `amplify/functions/shared/lambda_utils/ecommerce/native/`.
- Payment (**unchanged**): Razorpay Standard Checkout + `razorpay-webhook`
  signature verification; order created only after verified capture
  (idempotent via existing `order_keys`/`payment_attempt`). No second settlement
  flow. Wix order writeback (`wix_writeback.py`) is disabled when
  `CHECKOUT_MODE=AWS_NATIVE`; internal `OrderTable` + `InvoicesTable` remain the
  record of truth.
- Historical orders: `OrderTable`, `WixOrdersCache`, `InvoicesTable` family are
  preserved read-only for history.

### Meta/WhatsApp catalog sync
`meta-catalog-sync` reads `ProductsTable` when `CATALOG_SOURCE=aws` (new flag),
preserving catalog identity, approvals, dry-run gates, and inventory correctness.
Product-change events: a DynamoDB Stream on `ProductsTable` → existing EventBridge
→ `meta-catalog-sync`, replacing the Wix webhook. The Wix webhook
(`wecare-wix-catalog-webhook`) stays until the native event path is proven.

---

## C. Lightsail design

- **No in-place downgrade** (Lightsail cannot restore a 40GB micro snapshot onto a
  20GB nano). Provision a **fresh nano**, migrate Asterisk/SIP config + certs +
  required data, verify passive SIP/TLS, then (gated) move the static IP.
- Scripts in `scripts/lightsail-nano-migration/`: `preflight.sh`,
  `bootstrap-nano.sh`, `migrate-workload.sh`, `verify-nano.sh`, plus a
  `ROLLBACK.md` runbook. Dry-run by default, no embedded secrets, account/region
  verification, checksums on transfer.
- Capacity verdict depends on in-guest `free -m`/`df -h`/swap/OOM evidence. If
  host access is unavailable, the verdict is **INCOMPLETE** and defaults to
  **NO-GO / keep Micro** until measured. Low CPU alone is insufficient.
- Retirement is tied to removing the Airtel `:8899` proxy and the Meta SIP media
  leg (see `docs/migration-plan.md` deferred items) — a separate, approved
  program, not this one.

---

## Secret-management architecture (B)

- **Standard, not mega-secret.** Keep one access helper + naming convention.
  Verify whether `amplify/functions/shared/lambda_utils/` already provides a
  compliant helper (it does: runtime fetch + in-memory cache, masking, fail-closed
  per `docs/SECURITY_AND_SECRETS.md`); avoid broad refactor if so.
- **Namespaces (target):** `wecare/prod/payments/*`, `/communications/*`,
  `/seo/*`, `/integrations/*`, `/security/*`. Group only within a security domain
  where every consuming role needs every field and rotation lifecycles match.
- **Keep isolated:** Razorpay API + webhook (`wecare/razorpay/*`), OTP pepper
  (`wecare/otp/pepper`), flow private key (`wecare/flow-private-key`), backup
  passphrase (`wecare/backup/recovery-passphrase`), admin/IAM keys
  (`wecare/aws/iam-access-keys`), GitHub PAT (`wecare/github-pat`),
  Meta token (`wecare/meta-system-user-token`).
- **Parameter Store (Standard, free):** only confirmed NON-secret config, e.g.
  non-secret parts of `wecare/config/webhook-registry` and provider IDs. Never
  move an actual secret to plaintext SSM.
- **Wix secrets** (`wecare/wix/headless-api-key`, `/catalog-webhook`,
  `/app-oauth`): `RETIRE_AFTER_CUTOVER`. `app-oauth` is flagged exposed
  (2026-10-02) → `ROTATE`/retire with the Wix cutover. All use the AWS-managed KMS
  key (no CMK cost).
- IAM: remove Wix GetSecretValue grants via IaC after cutover; never touch the
  shared execution role's non-Wix grants.

---

## Shared-infra invariants (must hold across all workstreams)

Reuse Amplify app `d22dm4b0jn71jw` + `stack`. Preserve: Cognito users, existing
DynamoDB data, S3 data, API Gateway routes until new consumers verified, Meta/
WhatsApp identity, historical orders/invoices, payment verification/reconciliation
behaviour, `wecare.digital` hosting, recovery backups within retention.

## Reversibility levers (every production change is flag-gated)

| Flag | wix → aws | Reverts by |
|---|---|---|
| `BLOG_SOURCE` | blog read/write source | setting back to `wix` |
| `CHECKOUT_MODE` | pricing/cart/writeback source | setting back to `WIX_HEADLESS` |
| `CATALOG_SOURCE` | meta-sync + snapshot source | setting back to `wix` |

No flag flip is a production change until the owner approves it; code ships
defaulting to the Wix path so merging is non-mutating.

## Testing strategy

- Python: `.venv/bin/python -m pytest -q` scoped to touched handlers with
  synthetic DynamoDB (moto/stubs already used in `tests/`).
- Build gate: `npm run build` must produce a non-empty blog with `BLOG_SOURCE=aws`
  and Wix hosts blocked (the Gate-4 independence proof).
- Cost: `scripts/aws_cost_model.py --live`.
- Secrets helper: unit tests with synthetic secret fixtures; assert no value is
  logged.
