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

Validation: 116 catalog projection, handler and exclusion-parity tests passed with offline fixtures. No customer payment or WhatsApp send was performed.

## Existing automation and remaining live verification

Code already connects verified Wix catalog webhooks to the Meta sync Lambda. A six-hour EventBridge backstop is defined by the provisioning script; GitHub's catalogue workflow refreshes the website snapshot on events and every six hours.

The checked-in manifest still has `META_CATALOG_SYNC_ENABLED=false`, `META_CATALOG_SYNC_DRY_RUN=true`, and `WA_CATALOG_ORDERS_ENABLED=false`. These are repository values, not a fresh AWS runtime reading.

The shared payment finalizer contains canonical order creation, Wix order creation, payment recording and completion tracking. The workspace orders page calls its order-list API. This is source-level evidence only; the complete native WhatsApp purchase, Wix writeback and workspace listing have not been live-verified in this turn.

The earlier AWS MCP action was not executed because automatic approval review could not complete: workspace credits were exhausted. Do not bypass that block using another AWS execution route. AWS runtime inspection, deployment, catalog API upsert and end-to-end order verification remain pending until that access is restored.

## Rollback

Revert the catalog projection commit for code rollback. For Wix media rollback, read the current product revision, remove the two newly added media references and restore empty linked media on Submit Request and Vault while preserving the complete four-option and four-variant arrays. Do not reuse the old revision or recreate variants.
