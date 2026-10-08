# Wix to WhatsApp catalog connection - 2026-10-08

The owner requires an automatic Wix product projection and linked order records. Manual Meta product entries were prepared but never submitted and are not the integration.

## Verified through the connected Wix API

- Site: `c993128b-26be-41cd-9fcd-904abe23462f`.
- Services product: `df976a0a-f582-4535-b2e1-d532f348bd27`, updated from revision 1 to 2.
- Submit Request: `e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b`, INR 99.00.
- Vault: `dcff995e-448c-493a-9259-f6a82ccdc2b4`, INR 49.00.
- Both approved images uploaded to Wix Media Manager at 4096 x 4096 and assigned to their existing option choices.
- All four variant IDs, SKUs, prices and option identities retained.

Submit image: https://static.wixstatic.com/media/478bf9_0e3248f1367e43c4825acfeb4cb6f5f7~mv2.png

Vault image: https://static.wixstatic.com/media/478bf9_27b898b513ac4b508409202446818341~mv2.png

## Repository changes

The Meta projection now includes the public website URL. Services use their existing dedicated variant routes (`/submit-request/`, `/request-amendment/`, `/drop-docs/`, `/vault/`), because the Services product is excluded from the shop. Ordinary products use `https://wecare.digital/shop/<Wix slug>/`, matching the existing website route. The internal Wix storefront URL is not used as the customer-facing link. URL changes participate in the diff.

The live variant reader preserves variant artwork. Explicit linked option-choice media takes precedence when it identifies one unambiguous image, protecting against a stale variant index returning the product's shared image.

Retailer IDs remain `wix:<productId>:<variantId>`, the existing join used by WhatsApp basket resolution and Wix catalog references.

## Live deployment verified 2026-10-08

AWS MCP access now succeeds in account 775261844268, us-east-1. The prior workspace credit rejection no longer blocks this work. The sync is deployed on live version 5 (code SHA v4uxaXl+7L52ZCN1ZxkblU3RHnfnp06jhZ07c3i195s=).

Meta catalog 1607047307067517 contains both existing Wix variant identities, correct INR 99/49 prices, separate Wix-hosted 4096px images and WECARE product URLs. Readback through the live alias returns create=0, update=0, retire=0, foreign=1. The foreign test item was preserved. The original items_batch payload used Graph product fields; corrected feed fields are id/title/image_link/link and currency-bearing price. Validation responses without batch handles now fail rather than reporting success.

The live manifest/provisioner record enabled=true, dryRun=false, the two exact variant IDs, and forceOutOfStock=true. These products remain out of stock pending purchase QA. Variant scope applies to retirement too.

EventBridge schedule is ENABLED with cron(25 */6 * * ? *) and invokes the live alias. The Wix webhook role has the exact live-alias invoke grant; a last-hour CloudWatch read found one meta_catalog_sync_invoked event. Fresh Wix change-to-Meta propagation remains a separate QA check; the six-hour reconciliation is active.

Validation: 134 catalog projection, handler and exclusion-parity tests passed. No customer payment or WhatsApp send was performed. Evidence: catalog-live-evidence.json.

## Order path still pending

Live checkout and Razorpay webhook configurations do not enable the site-bound Wix external-order writeback contract. Native catalog-service checkout changes are unfinished local source and have not been deployed by this catalog release. Paid purchase -> one Wix order -> one workspace order -> Submit Request/Vault fulfillment therefore remains unverified. Owner QA WhatsApp recipient requested; no real customer used as a substitute.

## Rollback

Revert the catalog projection commit for code rollback. For Wix media rollback, read the current product revision, remove the two newly added media references and restore empty linked media on Submit Request and Vault while preserving the complete four-option and four-variant arrays. Do not reuse the old revision or recreate variants.

## Order-association hardening

The finalizer now binds Wix order IDs to the canonical internal UUID/public number on the main OrderTable and reverse WixOrderIds record. Conditional writes refuse a changed association and recover from a partial failure. Wix sync resolves that association before legacy-number allocation, avoiding a duplicate workspace order. Six regression tests include syncing the same paid-order fixture twice. Checkout/writeback/package tests: 83 passed (82 before the extra replay regression).

Native service finalization also now requires the persisted PAYMENT_PAID state, Wix order ID and WIX_CART_COMPLETED stage before unlocking fulfillment. This change belongs to the unfinished local native checkout implementation and is not included in the association-only production patch. Five boundary tests plus existing paid Submit Request/Vault tests passed (36 total).

Production association patch: checkout live 33 (rollback 32), Wix store live 37 (rollback 36). Both published versions Active and both OPTIONS smoke invocations returned 200 without FunctionError. Deployments retain existing package contents except the exact tested association modules. Evidence: order-link-live-evidence.json. The Wix writeback and native live-send flags remain unenabled.
