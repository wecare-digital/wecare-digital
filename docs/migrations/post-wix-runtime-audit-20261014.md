# Post-Wix deletion: GitHub, AWS and runtime dependency audit

Date: 2026-10-14 UTC. Account: 775261844268. Region: us-east-1.
Scope: read-only AWS metadata, source code and public blog Lambda invocations.
The owner reports the Wix site has been deleted. Do not use Wix as a rollback.
Do not claim zero Wix dependencies until the live checklist below passes.

## Confirmed native state

| Area | Verified state |
| --- | --- |
| Public blog route | API Gateway `GET /seo-tools/blog-public` and proxy target `wecare-blog-public:live` v2 |
| Public blog content | 1,421 published items returned, with representative detail body and richContent |
| SEO authoring Lambda | `wecare-seo-tools` BLOG_SOURCE=aws; still retains obsolete WIX env names |
| Product database | `stack-wecare-digital-ProductsTable` ACTIVE; strong Scan 10 products / 23 variants |
| Product media | Nine product rows refer to `static.wixstatic.com` instead of S3 |
| Checkout Lambda | `wecare-checkout:live` v48, CHECKOUT_MODE=AWS_NATIVE, CATALOG_SOURCE=aws, WIX_CART_V2_ENABLED=false, WIX_WRITEBACK_ENABLED=false |
| Meta catalog sync | CATALOG_SOURCE=aws but META_CATALOG_SYNC_ENABLED=false and DRY_RUN=true; six-hour EventBridge rule remains enabled |
| Public storefront | `src/content/shop.ts` imports committed `src/content/wix-catalog.json`; not generated from live AWS catalog |
| Staff product editor | `src/pages/workspace/commerce/catalog.tsx` still uses Wix Store API from `src/api/client.ts` |
| Native cart storage | `stack-wecare-digital-CartTable` not found in live us-east-1 audit |
| Wix Lambda API | `wecare-wix-store:live` and `wecare-wix-catalog-webhook:live` still have exposed API Gateway integrations |
| Secrets | 3 Wix API secrets are scheduled for deletion; 19 non-Wix active entries remain |
| IAM | Checkout, Meta sync and Wix webhook roles retain permissions to the obsolete Wix secret ARNs |
| Website build | `npm run build` called anonymous Wix catalog refresher, silently fell back to stale snapshot |
| GitHub catalog sync | Every-six-hours workflow still called deleted Wix endpoint and committed catalog snapshot |

**Cloud resources and runtime flags are separate from GitHub.** A code merge
does not remove old Lambda versions/aliases, API routes, IAM grants or cloud
events. A green Wix-exit policy job still uses `--expect-fail` baseline mode.

## Production payment findings — treat as a safety gate

At audit time, `wecare-checkout:live` remains version 48. Source PR #438
contains safeguards, but a merged source commit alone is not proof this alias
was republished.

1. The website sends nested `catalogReference.catalogItemId` and
   `catalogReference.options.variantId` values. The original native
   `_website_snapshot` expected top-level `productId` and `variantId`.
2. Services are gated by `cart_v2.is_enabled()` but that Wix flag is false
   in live native mode; service purchases can refuse with 503.
3. Native quote returned `calculated=None`. The old service PAYREF adapter
   then recorded `serviceLine.paise=None`, risking unmatched paid services
   if the preflight gate were simply removed.
4. WhatsApp basket claiming and the separate catalog-service payment route
   still construct Wix CartV2 or Wix eCommerce adapters even in native mode.
5. `native_cart.py` requires a CartTable that was not present, and the
   `native_inventory` reservations must be verified end-to-end at gateway
   order creation, capture, cancellation and retries.
6. Existing `WixOrderIds` and order/payment tables may contain historical
   reconciliation keys. Never delete them by name alone.

**Payment release criteria:** a passing isolated test suite and confirmed
published live version; test Wix-denied checkout; authoritative product and
variant matching; correct PAID service PAYREF; idempotent Razorpay order and
webhook; stock reservation and release; successful invoice and fulfilled
service; explicit owner-approved payment initiation. No real payment tests
without designated owner/QA authorization.

## Source/build dependency cleanup

This branch contains only the safe build cleanup:

- Remove the attempted Wix visitor-token catalog fetch from the static
  `package.json` build chain; the current committed snapshot remains.
- Retire the schedule/dispatch workflow that wrote the obsolete Wix snapshot.

**Important limitation:** this is not a complete storefront cutover.
The shop keeps its last committed catalog until `build-catalog-snapshot.py`
is run against the AWS ProductsTable and `src/content/shop.ts` plus its
regression tests are changed together. The generator had needed a compatibility
fix for `descriptionHtml`, `visible` and UTC `fetchedAt`, merged in PR #439.
Implement an IAM-limited AWS catalog-to-build publishing workflow before
expecting automated product editing to update static pages.

## Remaining retirement in safe order

1. Confirm all product data/variants/retailer IDs and required descriptions.
   Import Wix-hosted images into S3; update ProductsTable imageRefs, static shop
   JSON and Meta catalog artwork after verifying object access and checksums.
2. Switch the staff product CRUD UI and `src/api/client.ts` to guarded
   AWS-native Lambda endpoints backed by ProductsTable; implement revisions,
   authorization, audit logs, and no client-supplied price authority.
3. Provision/validate CartTable or explicitly implement a tested cartless
   native alternative; migrate WhatsApp basket handoff and service payment
   paths. Preserve Razorpay and Meta/WhatsApp integrations.
4. Replace Wix-dependent product-image publishing and AI tool adapters.
   Retarget or retire event hooks without losing native Meta catalog sync.
5. Remove Wix Store API Gateway routes and old functions only after client
   dependency tests prove there are no consumers. Keep unrelated API routes.
6. Remove WIX env keys and obsolete IAM grants from live roles **and**
   from provisioning scripts/manifests; preserve Razorpay, Meta and shared IAM.
7. Update `.env.local.example`, `config/lambda-env-manifest.json`,
   `amplify/infra/checkout.json` and provision scripts so Wix access cannot be
   reintroduced by a future deployment.
8. Replace `.github/workflows/conversations-publish.yml` Wix blog writer
   with the existing AWS-native Blog Studio publishing path while retaining
   QA/approval gates. Keep draft/unpublished-revision policy explicit.
9. Remove unused Wix runtime modules, source clients and feature flags.
   Turn the Wix exit policy from expect-fail to blocking **only once clean**.
10. Audit residual Wix DNS, Lambda permissions, private S3 secret backups,
    retired secrets and historical order records. Preserve legal/audit data.

## Verification evidence and change boundaries

- Source: GitHub `stack` at latest relevant change, native PRs #435–#439.
- AWS: Lambda function/alias configuration, API Gateway routes/integrations,
  EventBridge rules/targets, IAM inline policy statements, Secrets Manager
  metadata only, and DynamoDB ConsistentRead Scan counts.
- Public API: Lambda invoke via `wecare-blog-public:live`, listing/detail
  returned HTTP 200 and 1,421 posts. This validates backend, not rendered
  browser SEO or media accessibility.

**No destructive infrastructure cleanup belongs in this branch.**
