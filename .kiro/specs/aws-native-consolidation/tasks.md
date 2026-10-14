# Tasks — AWS-Native Consolidation & Cost Optimization

Legend: `[x]` done · `[~]` implemented, not deployed · `[ ]` not started.
🔒 = production-mutating, requires explicit owner approval (do NOT execute).

## Phase 0 — Audit & baseline (Gate 1)

- [x] 0.1 Confirm real repo root (parent) vs Kiro shell; use parent for all ops. (A, X1)
- [x] 0.2 Live AWS inventory: 77 Lambda, 85 DDB, 7 S3, 1 Amplify, 1 Lightsail,
      22 active + 13 scheduled secrets. (Gate 1)
- [x] 0.3 Active-vs-inert Wix dependency graph with file:line evidence. (A2, Gate 1)
- [x] 0.4 Secret → metadata inventory (names, last-access, KMS, rotation) without
      reading values. (B2)
- [x] 0.5 Lightsail bundle/snapshot/static-IP facts + bundle prices. (C1)
- [x] 0.6 Deterministic cost model script + run. (X2, B10, C8)
- [x] 0.7 Write migration docs under `docs/migrations/`. (Section 8)
- [x] 0.8 Deep per-subsystem Wix audit (checkout/cart/pricing, gift-card SPI,
      coupons, meta-sync, blog) with the money-authority map and removal order:
      `docs/migrations/wix-subsystem-deep-audit.md`.

## Phase 1 — CI guardrail (safe, non-mutating runtime)

- [x] 1.1 CI check that fails if a NEW active Wix runtime dependency is added to
      `amplify/functions/**` or `src/**` (excluding docs/tests), modelled on the
      existing provider-policy gate. `scripts/check-wix-policy.sh` (gate +
      `--expect-fail` modes). Measured baseline: 203 findings / 4 rules. (Gate 4)
- [x] 1.2 Wire 1.1 as `.github/workflows/wix-exit-policy.yml` in `--expect-fail`
      baseline mode (passes today while Wix is live; flips to blocking at Gate 4).

## Phase 2 — Wix data export & archive (read-only against Wix) (Gate 2)

- [x] 2.1 `scripts/wix_export/` idempotent exporter with pagination, immutable
      IDs (sourceId), retries, per-item sha256 checksums, reconciliation report,
      and a safe `--dry` default (no network/secrets). Blog + store queries wired;
      live run is 🔒 (reads Wix, needs creds). Unit-tested.
- [~] 2.2 Store export fields (variants, SKUs, prices, inventory, categories,
      images, orders/refunds, fulfillment) — base products/blog queries done;
      per-class field expansion + Hotels/Invoices usage check pending live run.
- [ ] 2.3 🔒 Write encrypted, access-controlled export archive to existing S3
      (creating/populating a storage prefix is billable write → approval).
- [ ] 2.4 Reconcile export counts vs fresh authoritative Wix counts.

## Phase 3 — AWS-native blog store + read path (Gate 2)

- [ ] 3.1 CDK `BlogPostsTable` (PAY_PER_REQUEST, PITR, RETAIN) + GSIs, mirroring
      `seo-resources.ts`. (A1) — NOTE: the native read currently reuses the
      existing `SeoToolsTable` `blogPost` records via `storage._blog_view`; a
      dedicated table is only needed if the published corpus outgrows that store.
- [x] 3.2 Native blog read in `wecare-seo-tools` behind `BLOG_SOURCE` (default
      `wix`): `blog_source.py` seam + handler wired + unit tests. IMPLEMENTED,
      NOT DEPLOYED (flag defaults to wix; flip is Phase 6). (A1)
- [~] 3.3 Native Blog publish: `blog_publish.py` `BLOG_SOURCE=aws` branch writes
      published `blogPost` records via `storage.create_blog_post` (no Wix, kill
      switch bypassed in native mode). Unit-tested. (Schedule/approve routes
      already exist in Blog Studio against the SEO store.) (A1)
- [ ] 3.4 Build-time fail-safe snapshot (`src/content/blog-snapshot.json`). (A5)
- [ ] 3.5 Seed `BlogPostsTable` from the Phase-2 export; reconcile. (A1, Gate 2)

## Phase 4 — AWS-native catalog + commerce (Gate 3)

- [~] 4.1 CDK `ProductsTable` (+ 3 GSIs + change stream) in
      `amplify/catalog-resources.ts`, mirroring `seo-resources.ts`. IMPLEMENTED,
      NOT WIRED into `backend.ts` (wiring creates a billable table → 🔒). `CartTable`
      still to add. (A2)
- [x] 4.2 `catalog_pricing.build_price_summary` + `authoritative_total_paise`
      (pure, integer paise, reuses `money.py`, enforces the Wix priceSummary
      identity, renders a Wix-shape that round-trips through
      `wix_ecom.authoritative_total_paise`). Unit-tested. NOT wired — the drop-in
      source for `compute_quote` when `CHECKOUT_MODE=AWS_NATIVE`. (A3)
- [~] 4.3 Native cart/discount/tax modules: `CartTable` CDK (TTL-reaped);
      `catalog_pricing.price_cart`/`coupon_discount_paise` (coupon discount from
      `coupon_store`, replaces Wix Calculate Cart); `supply_tax_paise`/`SupplyTax`
      (place-of-supply GST reusing `split_gst`); `service_pricing_native`
      (service-page prices from ProductsTable, same contract). All unit-tested
      end-to-end through `compute_quote`; not wired (CHECKOUT_MODE default
      WIX_HEADLESS). (A3)
- [x] 4.3c `native_cart` (CartTable CRUD, server-authoritative prices) +
      `native_inventory` (atomic reserve/release, oversell-proof, idempotent) +
      `native_shipping` (policy-driven delivery). The native supply total is
      COMPLETE: cart+stock+discount+shipping+GST → `price_cart` → `compute_quote`,
      end-to-end tested with no Wix. IMPLEMENTED, NOT WIRED. (A3)
- [x] 4.3d `native_checkout.quote_native_cart` — composition seam that turns a
      native cart into the exact `QuoteSnapshot` the handler produces (stock
      validate + shipping + coupon + GST + build_snapshot). Unit-tested with no Wix.
- [x] 4.3e Flag-gated branch in `checkout/handler.py`: `_supply_mode()` →
      `CHECKOUT_MODE=AWS_NATIVE` routes `_website_snapshot` through
      `native_checkout.quote_native_cart` (prices from ProductsTable, no Wix,
      ignores client prices). Defaults to WIX_HEADLESS. Unit-tested; existing
      checkout suite unchanged. (A3)
- [x] 4.3b Gift-card `code_pepper` de-Wix migration: `resolve_pepper_secret_id`
      + `PEPPER_SECRET_ENV_KEY`, config-flip with no re-keying; handlers +
      redemption provider follow it; store imports no `os`. Unit-tested. (B4 de-risk)
- [~] 4.4 `scripts/build-catalog-snapshot.py` writes `catalog-snapshot.json` in
      the SAME envelope as `wix-catalog.json` (ShopProduct shape, display-only
      prices, Indian grouping, archived excluded). Unit-tested. Repointing
      `src/content/shop.ts` to it is the 🔒 flip (needs a seeded ProductsTable +
      Amplify rebuild). (A2)
- [~] 4.5 `meta-catalog-sync` reads `ProductsTable` behind `CATALOG_SOURCE`
      (`_native_products` projects the exact slim shape `desired_items` consumes;
      defaults to `wix`). Unit-tested; preserves diff/approval/dry-run/retailer-id.
      DynamoDB-stream → EventBridge wiring + 🔂 flip still pending. Discovered
      requirement: ProductsTable ids/variant-skus MUST be UUIDs (retailer-id
      contract). (A4)
- [ ] 4.6 Idempotency/signature/reconciliation tests on the native path reusing
      existing `order_keys`/`payment_attempt`. (A3, Gate 3)

## Phase 5 — Independent e2e + Gate 4 proof

- [ ] 5.1 `npm run build` with `BLOG_SOURCE=aws`/`CATALOG_SOURCE=aws` and Wix
      hosts blocked → non-empty blog + sitemap, no `wixapis.com` calls. (Gate 4)
- [ ] 5.2 Old-vs-new URL diff: no mass 404s. (A5)

## Phase 6 — 🔒 Wix production cutover (Gate 4 → owner approval)

- [ ] 6.1 🔒 Flip `BLOG_SOURCE=aws`, `CHECKOUT_MODE=AWS_NATIVE`,
      `CATALOG_SOURCE=aws` in production env. (A6)
- [ ] 6.2 🔒 Decommission `fetch-wix-catalog.js` schedule / Wix publish workflow.
- [ ] 6.3 🔒 Verify production operates with Wix API access blocked. (Gate 4)

## Phase 7 — 🔒 Wix secret + IAM cleanup (Gate 5, after Phase 6)

- [ ] 7.1 Remove Wix env vars + IAM GetSecretValue grants via IaC. (B5)
- [ ] 7.2 🔒 Disable Wix OAuth/API at provider; verify no callers. (B4)
- [ ] 7.3 🔒 Schedule deletion of 3 Wix secrets WITH recovery window. (B4)
- [ ] 7.4 🔒 Rotate the exposed `wecare/wix/app-oauth` as part of retirement. (B4)
- [ ] 7.5 🔒 Rebuild backup archive excluding retired creds; review old S3
      versions under retention policy. (B6)
- [ ] 7.6 Access-failure monitoring (SystemEvent on Wix secret access). (Gate 5)

## Phase 8 — Secret consolidation (unrelated services) (B)

- [ ] 8.1 Build the full secret access matrix (`docs/migrations/secrets-access-matrix.md`).
- [ ] 8.2 Confirm/standardize the shared secrets helper; add synthetic-fixture
      unit tests. (B3)
- [ ] 8.3 Move only confirmed NON-secret config to Parameter Store Standard. (B4)
- [ ] 8.4 🔒 Verify + plan GitHub PAT remediation (narrower scope / GitHub App).
      No rotation without approval. (B7)

## Phase 9 — Lightsail (independent release)

- [ ] 9.1 Capacity audit (needs host access; else mark INCOMPLETE → NO-GO). (C1)
- [~] 9.1 Capacity audit: SSH (22) unreachable from here → in-guest audit NOT
      collected → verdict INCOMPLETE / default NO-GO. CPU avg ≈0.94% (measured).
      SIP/TLS 5061 OPEN (measured). (C1)
- [x] 9.2 `scripts/lightsail-nano-migration/` scripts (dry-run, no secrets,
      account/region verified, checksums, approval gates). (C2)
- [ ] 9.3 🔒 Provision fresh nano; migrate; verify; (gated) move static IP. (C3)

## Phase 10 — Final cost audit (Gate 7)

- [ ] 10.1 Re-run `aws_cost_model.py --live`; compare actual billing to baseline;
      report POTENTIAL vs REALISED separately. (X2)

---

### Approval gates summary (production-mutating, STOP here)
- Any `[~]`→deploy, env-flag flip in prod, S3 export write, secret deletion/
  rotation, IAM change on deployed roles, Wix provider changes, Lightsail
  provisioning / static-IP move. Each is prepared as an exact runbook in the
  `docs/migrations/*` files and executed only on explicit owner approval.
