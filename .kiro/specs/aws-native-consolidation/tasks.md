# Tasks — AWS-Native Consolidation & Cost Optimization

## Fresh reconciliation — 2026-10-16

Live metadata: 74 Lambda functions, 76 DynamoDB tables (all ACTIVE), 375 HTTP routes,
7 S3 buckets, 20 active and 8 pending-deletion secrets, one running Nano. ProductsTable,
CommerceKeys and CartTable have deletion protection enabled. The Meta product-stream
mapping is enabled; the approved 21-item branded migration and strict consumer rollout
are complete. One historical Contribute item remains a separate publication decision.
The blog-ingest DLQ has one message; recent failures identify missing `blog_pipeline`.

The record below is historical evidence from October 14/15. It must not be used as a
current inventory or to rerun already completed cutovers. `requirements.md` and
`design.md` now describe the current architecture.

## Historical execution record

Status as of 2026-10-15 06:05 IST (owner-approved changes applied 05:47-06:00 IST), measured against the live account (775261844268 / us-east-1)
and `origin/stack` 4ee023cc. The tool-neutral plan with approval commands and rollback is
`docs/migrations/aws-native-consolidation-plan.md` (Codex reads that one); keep both in sync.

Legend: `[x]` done and verified · `[~]` implemented, not deployed · `[ ]` not started ·
🔒 production-mutating, owner approval required · ⛔ blocked.

## Gate 1 — Audit

- [x] 1.1 Live inventory: 76 Lambda (68 aliases), 84 DynamoDB tables, 7 S3 buckets, 375 routes,
      19 active + 9 scheduled secrets, 1 Lightsail instance (`docs/execution/aws-inventory.md`).
- [x] 1.2 Live Wix dependency check: `scripts/check_live_provider_independence.py`
      (`docs/migrations/evidence/live-provider-independence-20261014.md`).
- [x] 1.3 Secret-to-consumer map from IAM metadata: `scripts/secrets_access_matrix.py`.
- [x] 1.4 Cost baseline from Cost Explorer evidence: `scripts/aws_cost_model.py`.
- [x] 1.5 Lightsail capacity and dependency report (guest memory still unmeasured).

## P0 — Commerce-key IAM drift (found 2026-10-14, blocks checkout)

- [x] P0.1 IaC homes point at `CommerceKeys`; `ReserveNativeInventory` grants `UpdateItem` on
      ProductsTable (`provision_checkout.py`, `provision_service_requests.py`,
      `iam-native-catalog-checkout.json`, `amplify/infra/checkout.json`) + alignment tests.
- [x] P0.2 `scripts/remediate_commerce_keys_iam.py`: plan mode run live (3 policies drift,
      Access Analyzer clean, 17/17 simulated cases pass on the targets).
- [x] P0.3 🔒 Applied 2026-10-15 00:17Z with owner approval; verified with SimulatePrincipalPolicy.
      Rollback file: `.scratch/iam-rollback/commerce-keys-iam-20261015T001739Z.json`.
- [x] P0.4 Live check: `commerce-key-access` PASS (6 of 6 functions), see
      `docs/migrations/evidence/live-provider-independence-20261015.md`.
- [ ] P0.5 Owner QA checkout of the ₹1 test product (needs a customer login and a real payment;
      a 2026-10-15 probe showed the routes answer 401 without a session and 0 AccessDenied).

## Workstream A — Wix exit

- [x] A.1 Blog served natively: `BLOG_SOURCE=aws`; 1,421 posts reconciled with per-row
      SHA-256 provenance (`final-wix-retained-evidence-reconciliation-20261014.md`).
- [x] A.2 Catalog native: ProductsTable 10 products / 23 variants = retained snapshot IDs;
      media on CloudFront; storefront reads `catalog-snapshot.json`.
- [x] A.3 Checkout native: `CHECKOUT_MODE=AWS_NATIVE`, Wix cart/writeback removed, live v53.
- [x] A.4 Wix Lambdas, routes, cache tables and the `WixOrderIds` table deleted (live check PASS
      for names, routes, tables, secrets).
- [x] A.5 Source policy gate blocking with 0 runtime findings (`check-wix-policy.sh`).
- [x] A.6 🔒 Deleted the `wecare-seo-tools:blog-rollback-20261014` alias (last invoked 10-14 10:49 IST,
      no route, rule or mapping used it). Version 1 is kept; alias and policy saved in `.scratch/iam-rollback/`.
- [x] A.7 `WIX_ORDER_IDS_TABLE` dropped from `wecare-whatsapp-business-api` by another session
      (v116, 2026-10-15 00:17Z); live check `lambda-env-keys` PASS.
- [x] A.8 🔒 Removed `NativeCommerceCatalogRead` from `wecare-meta-catalog-sync-role`; meta-sync
      still reads ProductsTable (simulated). Document saved in `.scratch/iam-rollback/`.
- [x] A.8b Deletion protection enabled on ProductsTable and CommerceKeys (CartTable already had it).
- [ ] A.9 Meta catalog sync is DISABLED (`META_CATALOG_SYNC_ENABLED=false`) and the ProductsTable
      stream trigger is not wired; enabling Meta writes is a separate 🔒 decision.
- [x] A.10 Frontend build: production Amplify builds failed from #476 to #478 (TypeScript);
      after #479 the `stack` builds at 05:18, 05:22 and 05:25 IST on 10-15 succeeded.
- [x] A.11 DNS: none of the 25 Route 53 records names `wix`, `xout` or `ascendbywix`.

## Workstream B — Secrets

- [x] B.1 Access matrix and findings (`secrets-consolidation.md`).
- [x] B.2 Shared helper meets B5 (`lambda_utils/secrets_access.py`, 12 tests); no refactor.
- [ ] B.3 🔒 B-0 stop using root access keys for automation. Live-confirmed 2026-10-16:
      `AccountAccessKeysPresent=1` and `wecare-prod` resolves to `:root`. Owner runbook with
      verify + rollback: `docs/migrations/b0-retire-root-access-keys.md` (Plan A recommended).
- [~] B.4 🔒 B-1a applied: managed policy `wecare-shared-role-secret-guard` denies `github-pat`,
      `backup/recovery-passphrase` and `aws/iam-access-keys` to the shared role (CloudTrail: no
      shared-role reader in 90 days). The full allow-list rewrite (B-1b) is still open; the role's
      inline policies are at IAM's 10,240-byte limit.
- [ ] B.5 🔒 B-2 replace and revoke the exposed classic GitHub PAT.
- [~] B.6 🔒 B-3 `aws/iam-access-keys`: repo consumers removed; scheduled for deletion with recovery window;
      `config/webhook-registry` remains a separate SSM-migration cleanup.
      `meta/payments` stays: `.env.local.example` names it as the config-to-MID mapping
      (deletion was scheduled at 05:58 IST and restored at once). `bing/api` stays (registry reads it).
- [ ] B.7 🔒 B-5 fresh encrypted backup, then owner retention decision on the two old versions.
- [x] B.8 Wix secrets retired (force-deleted 2026-10-14; recovery window was bypassed).

## Workstream C — Lightsail

- [x] C.1 Toolkit repaired and tested (`tests/test_lightsail_nano_scripts.py`, 19 tests).
- [x] C.2 Verdict NO-GO, keep Micro, now MEASURED: 273 MB used, 491 MB available of 916 MB, and
      571 MB already in swap; disk 14 GB of 40 GB (`docs/migrations/evidence/lightsail-preflight-20261015.txt`).
- [x] C.3 🔒 Approved host-access session ran `preflight.sh` 2026-10-15 01:00 UTC (port 22 for one IP,
      short-lived certificate, closed afterwards).
- [x] C.4 🔒 Stopped and disabled `sms-proxy.service` and Docker/containerd (2026-10-15 02:39 UTC,
      owner-approved); 228 MB used after, Asterisk and 5061 unaffected.
- [x] C.5 Verdict corrected: swap was idle (si/so 0). CONDITIONAL GO for a fresh Nano build,
      NO-GO for copying the box.
- [x] C.6 Owner chose: fresh Nano + copy only the voice bot.
- [x] C.7 🔒 Nano `wecare-voice-bot-nano` created and the voice bot copied (2026-10-15 03:25 UTC):
      3,235 files, identical SHA-256 digest, 0 missing libraries, Asterisk 22.8.2 running, TLS CN
      `sip.wecare.digital`, 171 MB used of 419 MB. See `docs/migrations/lightsail-nano-cutover.md`.
- [x] C.8 🔒 Cutover done 2026-10-15 03:39 UTC: static IP on the Nano in 8 s, timers moved,
      verify-nano.sh PASS, 0 calling errors. Micro on standby for rollback.
- [x] C.8a 🔒 Post-cutover fixes 2026-10-15: cert-check log file, IVR key rotated on the Nano
      (old key kept for the Micro), certbot dry-run OK, IVR S3 moved to `wecare-digital-get`
      `secure/` with least-privilege IAM, post-call hook proven by loopback. Cost model reads all
      Lightsail instances. See `docs/migrations/lightsail-nano-cutover.md`.
- [x] C.8b Owner real WhatsApp calls 2026-10-15 10:21 UTC, one per business number: IVR played,
      recordings complete, post-call text and SMS sent.
- [x] C.9 🔒 Retired 2026-10-15 about 10:30 UTC (owner-approved, no new backup): Micro, its
      2026-10-07 snapshot, the old IVR key and the 57 old recordings deleted. Call recording
      stopped 11:24 UTC (owner decision). The Nano has no backup.

## Gate 7 — Cost

- [x] 7.1 Measured baseline and levers (`aws-cost-optimization.md`).
- [ ] 7.2 Owner decisions: Support plan, Amplify build cadence, egress investigation.
- [ ] 7.3 Re-measure at month end; report REALISED separately.
