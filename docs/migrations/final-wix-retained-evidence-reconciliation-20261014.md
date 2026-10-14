# Final Wix → AWS retained-evidence reconciliation

Date: 2026-10-14 UTC  
Repository baseline at audit close: `stack` after `755625451437dc16d81dbe1f701167e63a28e898`.

## Verdict

**CLOSED — RECONCILED FROM RETAINED MIGRATION EVIDENCE.**

A fresh provider-side checksum cannot be recreated after Wix retirement, so this closure does
not pretend to be a new Wix API reconciliation. It proves preservation from the retained
production source snapshot, migration provenance stored with every migrated blog row, live AWS
counts/identities, and the absence of historical customer-order liability at cutover.

## Store catalog

Retained source: `src/content/wix-catalog.json`.  
Live target: `stack-wecare-digital-ProductsTable`.

Measured on 2026-10-14:

- retained products: **10**
- live ProductsTable products: **10**
- retained product IDs == live product IDs: **exact**
- retained variants: **23**
- live variants: **23**
- retained variant IDs == live variant `sku` identities: **exact**
- missing products: **0**
- extra products: **0**
- missing variants: **0**
- extra variants: **0**
- live Wix-hosted product media: **0**
- live CloudFront-backed product media rows: **9**

The retained Wix UUIDs therefore remain the native product/variant identities used by the AWS
catalog and downstream Meta retailer-ID contract.

## Blog

Live target: `stack-wecare-digital-SeoToolsTable` / public blog API.

Measured on 2026-10-14:

- public API posts: **1,421**
- unique public slugs: **1,421**
- duplicate public slugs: **0**
- missing slug/title: **0**
- published rows accounted for in the migration partitions: **1,421**
- rows carrying `migrationId = native-blog-20261014`: **1,421**
- rows carrying `migrationSha256`: **1,421**
- unique migration SHA-256 values: **1,421**

Partition accounting:
- 2025: **78**
- 2026 April: **24**
- 2026 July: **2**
- 2026 September 1–15: **5**
- 2026 September 25–30: **1,171**
- 2026 October: **141**
- total: **1,421**

The row-level migration checksums are retained inside AWS even though the original provider is
retired.

## Orders, payments and accounting liability

Fresh exact table scans on 2026-10-14:

- `OrderTable`: **0**
- `PaymentAttemptsTable`: **0**
- `PaymentsTable`: **1**, status `failed`
- `InvoicesTable`: **1**, status `created`
- `InvoiceItemsTable`: **3**
- `InvoiceSequenceTable`: **1**
- `WixOrderIds`: **5** records, consisting only of:
  - `SERVICEPRICECART#…`: **4**
  - `NATIVECATALOG#…`: **1**

There are no historical customer orders in the AWS order system requiring a missing Wix-order
migration. The surviving `WixOrderIds` table name is a legacy namespace; its current records are
native service-price/catalog keys, not customer orders.

## Retired cache/cloud resources

- `WixProductsCache`: empty before retirement, now deleted.
- `WixOrdersCache`: empty before retirement, now deleted.
- `wecare-wix-store`: deleted.
- `wecare-wix-catalog-webhook`: deleted.
- live Lambda environment references to the three retired Wix secrets/cache tables: **0**.

## Credential archive boundary

The shared encrypted credential backup bucket remains intentionally retained:

- bucket: `wecare-credential-backups-775261844268`
- versioning: **Enabled**
- KMS server-side encryption: **Enabled**
- archive object versions: **2**
  - 2026-09-26, 51,933 bytes
  - 2026-09-25, 51,706 bytes
- lifecycle policy: **none**

Those archives contain credentials unrelated to Wix as well, so deleting them solely to purge Wix
would destroy unrelated recovery material. Future backup generation excludes retired credentials.
The remaining risk-reduction step is provider-side revocation of the retired Wix credentials; that
requires Wix account access and cannot be performed through the current AWS/GitHub tool surface.

## Acceptance boundary

This document closes **historical data reconciliation** for the AWS migration using retained
evidence. It does **not** claim a post-retirement live Wix query occurred, and it does not treat
provider-side credential revocation as an AWS migration-data requirement.
