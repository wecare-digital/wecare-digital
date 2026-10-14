# AWS-Native Wix Exit — master plan

Account 775261844268 · us-east-1 · Amplify `d22dm4b0jn71jw` · branch `stack`
Working branch: `feat/aws-native-consolidation`. Spec:
`.kiro/specs/aws-native-consolidation/`.

## What is true today (verified 2026-10-14)

Wix is still the **authoritative runtime backend** for both blog and commerce.
There is no AWS-native blog store or product catalog-of-record. Evidence:

- `wecare/wix/headless-api-key` last-accessed **2026-10-14** (live).
- Public blog reads go `src/lib/public-blog.ts` → `wecare-seo-tools`
  `/blog-public` → `seo-tools/wix.py` anonymous **visitor token** → Wix Blog V3.
  `wix_guard.py` deliberately does NOT block this, so disabling admin creds does
  not take the blog off Wix.
- Shop display catalog: `catalogue-sync.yml` (6-hourly) + `refresh-wix-catalog-safe.js`
  → `scripts/fetch-wix-catalog.js` → `src/content/wix-catalog.json` →
  `src/content/shop.ts`.
- Checkout authoritative total: `wix_ecom.authoritative_total_paise`
  (`CHECKOUT_MODE=WIX_HEADLESS`), Razorpay for payment.
- `meta-catalog-sync` reads live Wix `/stores/v3/products/search`.
- The **commerce transaction backend is already AWS-native and verified**
  (`payment_attempt`, `order_keys`, `order_creation`, `razorpay-webhook`,
  `OrderTable`, `InvoicesTable` family) — reuse, do not rebuild.

`amplify/data/resource.ts` is **inert** (0 AppSync APIs; 58 declared models never
materialised). Live tables are CDK/`provision_*.py` under `stack-wecare-digital-*`
and addressed by Python Lambdas via `os.environ`. New native stores MUST follow
that pattern.

## Active Wix runtime touch-points to replace (the exit surface)

1. Public blog LIST + SINGLE POST (seo-tools → wix.py).
2. Visitor-token mint (`_load_visitor_access_token`).
3. Blog category/tag labels.
4. Blog PUBLISH (`scripts/wix_blog_migrate.py` via `conversations-publish.yml`).
5. Shop display catalog (`fetch-wix-catalog.js`).
6. Checkout authoritative total (`wix_ecom`).
7. Cart ops (`cart_v2.py`, `WIX_CART_V2_ENABLED=true`).
8. Order writeback (`wix_writeback.py`, `WIX_WRITEBACK_ENABLED=true`).
9. `wecare-wix-store` Catalog/Inventory/Orders V3.
10. Service prices (`checkout/handler.py` live Wix reads).
11. `meta-catalog-sync` live Wix reads + `wix-catalog-webhook` trigger.

## Reversibility: everything flips on a flag

| Flag | Default (safe) | Cutover value |
|---|---|---|
| `BLOG_SOURCE` | `wix` | `aws` |
| `CHECKOUT_MODE` | `WIX_HEADLESS` | `AWS_NATIVE` |
| `CATALOG_SOURCE` | `wix` | `aws` |

Code ships defaulting to the Wix path, so merging to `stack` is **non-mutating**.
A production change happens only when the owner flips a flag (Phase 6, gated).

## Phased plan (see tasks.md for the checklist)

0. Audit & baseline (DONE — this doc + cost model + access matrix).
1. CI guardrail against NEW Wix runtime deps.
2. Idempotent Wix export + encrypted S3 archive 🔒.
3. Native blog store + read path behind `BLOG_SOURCE`.
4. Native catalog + commerce behind `CHECKOUT_MODE`/`CATALOG_SOURCE`.
5. e2e Gate-4 proof (build with Wix blocked).
6. 🔒 Flip flags in production.
7. 🔒 Wix secret + IAM cleanup.

## Acceptance gates
Gate 1 audit → Gate 2 CMS → Gate 3 commerce → Gate 4 independence → Gate 5
secret retirement. Full criteria in `.kiro/specs/aws-native-consolidation/requirements.md`.

## Non-goals / guardrails
No WordPress/WooCommerce/Strapi/Directus/Shopify or replacement commerce SaaS.
Keep Amplify + `stack`. Preserve Cognito users, existing DynamoDB/S3 data, API
Gateway routes until new consumers verified, Meta/WhatsApp identity, historical
orders/invoices, payment verification behaviour, `wecare.digital` hosting, and
recovery backups within retention.
