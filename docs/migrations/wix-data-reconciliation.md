# Wix data reconciliation

How we prove the AWS-native stores hold everything Wix held, before cutover
(Gate 2 / Gate 3). The export is the input; this doc defines the proof.

## Source identity must be verified separately (A4)
There may be multiple Wix identities. Verify the owning site/account per data
class before trusting a count — do NOT assume blog, store, customers, orders,
invoices and media share one site. Current live config
(`src/config/wix.ts`, `seo-resources.ts`): account `478bf907-…`, site
`c993128b-…`, client `42b3cdbf-…`. The blog app measured `total=1323` posts on
the new site under the storefront client (recorded in `seo-tools/wix.py`).
`docs/wix-headless.md`'s identifier table is STALE (shows the retired
`fcd82f0c`/`15f02319`); use the live config, not that doc.

## Authoritative fresh counts (read-only, before export)
Blog: `GET /blog/v3/posts/query` (published) + draft query → record totals.
Store: `GET /stores/v3/products/search` → product + variant totals;
`/query-variants` for variant counts; inventory, categories, orders, refunds.
Check whether Wix Hotels / Wix Invoices are ACTUALLY used (bookings/invoices
exist), not merely installed.

## Reconciliation rules
1. **Counts match:** exported published+draft posts == fresh Wix counts;
   exported products+variants == fresh Wix counts (±0, not "about").
2. **Immutable IDs preserved:** every AWS item keeps the Wix id as `sourceId`.
3. **Checksums:** per-item content checksum in the export manifest; re-checked
   after load into DynamoDB/S3.
4. **Slug + canonical crosswalk:** every public URL (`/post/<slug>`,
   `/shop/<slug>`) resolves to the same content; redirects preserved.
5. **Media:** every referenced image resolves to a migrated S3 object (no
   hot-linking to Wix media after cutover).
6. **Historical accounting:** orders, refunds, invoices preserved read-only per
   retention; no cardholder data, passwords, or non-exportable PII exported.
7. **Idempotent + repeatable:** re-running the export/load converges (upsert by
   `sourceId`), produces an identical reconciliation report.

## Reconciliation report (artifact)
`outputs/wix-reconciliation-<timestamp>.json`:
```
{ "blog": {"wix_published": N, "wix_draft": M, "aws_loaded": N+M, "checksum_mismatches": 0,
            "missing_media": 0, "slug_crosswalk_ok": true },
  "store": {"wix_products": P, "wix_variants": V, "aws_products": P, "aws_variants": V,
            "price_mismatches_paise": 0, "inventory_mismatches": 0 },
  "verdict": "RECONCILED" | "DISCREPANCY" }
```
Cutover (Phase 6) is blocked unless `verdict == RECONCILED`.

## Why counts alone are not enough
Prior observations (~1,323 posts, 10-product committed snapshot) are starting
points, not proof. The committed `wix-catalog.json` is a display snapshot, not the
full catalog; orders/refunds/invoices are not in it at all. Only the fresh
authoritative API counts + checksums + media resolution together prove completeness.
