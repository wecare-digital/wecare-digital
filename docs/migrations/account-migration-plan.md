# Account migration + DR-rebuild plan

**Created:** 2026-10-17 · **Status:** plan (not yet executed) · **Author:** DR effort

**Recovery-input update, 2026-10-19:** the latest owner instruction restores
wildcard forwarding with two exact hostname exclusions. The manual DNS export
retains its 23 service and validation records; the six fallback records belong
only to the `FallbackDns` CloudFormation RecordSetGroup. Together they form the
29-record restoration topology. See [the current configuration](../execution/wildcard-restoration-20261019.md).
Rediscover live resources before migration. Do not replay the deleted distribution's
aliases from historical snapshots or manually create the stack-owned records.

> Goal (as stated by the owner): migrate the entire platform from the current
> production account to the clean account `991322955408`, retire the old account
> `775261844268` afterward, and keep ongoing cost minimal — WITHOUT ending up with
> no disaster recovery.
>
> This document is the authoritative sequence. It is deliberately opinionated about
> ORDER, because the dangerous parts (DNS, email, payments, voice) fail if steps run
> out of order.

---

## 0. The accounts

| Role | Account | Notes |
|------|---------|-------|
| Current production | `775261844268` (WECARE.DIGITAL) | all live infra, domain, providers, data |
| Migration target → new primary | `991322955408` (WECARE DIGITAL BHARATWORKS) | clean org member of `o-plhlfh8drl` |
| New dedicated backup account | **to be created** | a fresh minimal org member, e.g. `wecare-backup` |

**Non-negotiable rule:** the platform must ALWAYS have two accounts — one running it,
one holding isolated backups. Retiring `775261844268` is only safe once a *new*
backup account exists and is receiving copies from the new primary. One account =
zero DR.

---

## 1. Why this is a project, not a script

The compute (50 Lambdas, 76 DynamoDB tables) is the easy part. The hard, live-traffic
parts, all currently in `775261844268`:

| Component | Live resource | Migration difficulty |
|-----------|---------------|----------------------|
| Domain `wecare.digital` | registrar + Route53 zone `Z03939753QJGZ6ZD6BXO8` | HIGH — registration transfer + zone recreate |
| DNS zone | 23 retained service/validation records + 6 stack-owned fallback records | HIGH — email + voice + cert trust; preserve ownership boundary |
| ACM certificate | `wecare.digital` ISSUED (us-east-1) | certs do NOT transfer — reissue + revalidate |
| Amplify Hosting | app `d22dm4b0jn71jw` serving `wecare.digital` | new app, reconnect repo, re-add domain |
| CloudFront | MTA-STS, media `E2GP22R4BIFGQ3`, and the restored home-fallback topology | rediscover current IDs before recreating services + new certs |
| HTTP API | `zllr9lrg7j` | new API id in the new account — all scripts hardcode the old one |
| Cognito | pool `us-east-1_cSx0RHCIR` + users | users re-verify; passwords do not transfer |
| Providers | WhatsApp/Meta WABA, Razorpay, Plivo (`sip`) | re-register webhook URLs; Meta has approval lead time |
| Data | 76 DynamoDB tables, S3 `wecare-digital-get`, Secrets Manager (~20) | zero-loss cutover |

**Blocker to resolve first:** the `provision_*.py` fleet hardcodes the old account id,
the API id `zllr9lrg7j`, the SNS alarm topic, and KMS principals. A plain replay into
a fresh account produces a PARTIAL, broken stack (proven by the 2026-10-17 test run in
`991322955408`). These scripts must be **parameterized by account / region / API-id /
SNS-topic / KMS-principal** before the new-account build works. This is the single
largest piece of engineering in the migration.

---

## 2. The ordered sequence (with rollback at every step)

### Phase A — Prepare the new primary (no customer impact; old account stays live)
1. **Parameterize the provision fleet** (account/API/SNS/KMS injectable). The real
   engineering gate. Verify by building into `991322955408` and getting a CLEAN run.
2. **Build compute** in `991322955408`: tables → IAM → Lambdas → HTTP API → routes →
   queues → schedules. Use `recover_into_account.py` once the scripts are portable.
3. **Secrets**: create the ~20 Secrets Manager entries in the new account (values set
   by the owner, never on a command line). The GCP mirror already holds copies.
4. **Stage the DNS zone** in the new account's Route53 — use the 23 retained records in
   `docs/migrations/domain/wecare-digital-zone-export.json` as the baseline. Refresh
   them against live Route53 and map service targets to the new account's resources
   before staging. Do not manually create any of the six fallback records; step 7
   creates them through their owning stack. DO NOT change the registrar's nameservers
   yet; the staged zone is inert until NS is pointed at it.
5. **Request a new ACM cert** for `wecare.digital` + `*.wecare.digital` in the new
   account; validate via DNS (add the validation CNAMEs to the staged zone).
   Preserve coverage for the apex, named services including MTA-STS, and one-label
   wildcard fallback. The hostname exclusions do not require another certificate.
6. **Create Amplify Hosting** app in the new account, connect the repo, build.
7. **Recreate active CloudFront services** with the new cert + origins: MTA-STS,
   file serving and home fallback. For fallback, use `amplify/infra/home-fallback.json`
   with the staged hosted-zone ID, a valid certificate ARN and an existing logging
   bucket domain in the target account. Its RecordSetGroup creates all six fallback
   records after the new distribution exists. Verify both excluded names remain
   TXT-only and all 23 baseline records are preserved. Rediscover before execution;
   never reuse the old deleted distribution ID or domain.
   - Rollback for Phase A: nothing to roll back — the old account is untouched and
     still serving all live traffic. The new account is a parallel, dark build.

### Phase B — Migrate data (old account still serving)
8. **DynamoDB**: restore from the cross-account backup copies already in the DR path,
   OR do a fresh export→import; then enable continuous sync for the final cutover
   delta. Verify row counts per table.
9. **S3**: the media already replicates cross-account; backfill any remainder.
10. **Cognito**: import users from the export (`export_cognito_users.py`); users will
    re-verify on first login (passwords cannot transfer).
    - Rollback: old account's data is untouched; the new account's data is additive.

### Phase C — Providers (the long-lead item; start early)
11. **Re-register webhook/endpoints** on each provider to the new account's API/URLs:
    WhatsApp/Meta (expect approval delay), Razorpay, Plivo (`sip` endpoint).
    - Keep the OLD provider registrations active in parallel until cutover.
    - Rollback: providers still point at the old account until you flip them.

### Phase D — Cutover (the one irreversible-feeling moment)
12. **Final data delta sync**, then freeze writes briefly if needed.
13. **Flip the registrar nameservers** (or Route53 account transfer) to the new
    account's zone. This is THE cutover lever. TTLs mean propagation is gradual.
14. **Flip provider webhooks** to the new account.
    - Rollback: point nameservers / providers back at the old account (kept warm).
      Keep the old account FULLY RUNNING through this phase — do not touch it.

### Phase E — Stabilize + the DR rebuild (do NOT skip)
15. Run end-to-end verification in the new account: web, API, a test WhatsApp
    message, a test payment, a voice call, email send/receive (MX + DKIM + MTA-STS).
16. **Create a fresh dedicated backup account** (new org member).
17. **Wire DR from the new primary → the new backup account**: reuse the existing
    `provision_cross_account_backup.py` / `provision_s3_replication_xacct.py` /
    `provision_backup_account_side.py`, swapping the account IDs. Apply Vault Lock.
18. **Only now**, after a multi-day clean operating window + the new DR verified,
    **retire `775261844268`** (close the account; 90-day window before permanent).

---

## 3. Cost minimization (the "near zero" goal, honestly)

- **The new PRIMARY account is not low-cost** — it runs the real workload (Lambda
  invocations, DynamoDB traffic, CloudFront, Amplify, data transfer). Production costs
  what the workload costs, regardless of account number. Migrating does not lower this.
- **The new BACKUP account CAN be minimal but not zero** — it stores backup copies +
  the S3 replica. Minimize with: S3 lifecycle (expire old noncurrent versions, move to
  Infrequent-Access / Glacier), and AWS Backup cold-storage tiering (already: cold
  after 90 days). Realistic floor: a few dollars/month.
- **"Zero-cost DR" means no DR.** Storage is not free; a backup account that holds
  nothing protects nothing. The right target is *cheapest real DR*, not zero.

---

## 4. What is already done toward this (not just planned)

- Retained DNS baseline exported and committed (`domain/wecare-digital-zone-export.json`):
  23 service/validation records, excluding all DNS names owned by the fallback stack.
- The fallback template separately defines four address aliases and two TXT-only
  exclusions. Its pure DNS validator and tests reject conflicts and duplicate ownership.
- Full infra snapshot committed (`docs/execution/infra-snapshot/`): the machine-
  readable definition of 75 Lambdas, 76 tables, the API, queues, roles, secret names.
- `recover_into_account.py` orchestrator (with the per-script apply-flag fix) — builds
  into a target account; honest about the portability gap it still has.
- The cross-account DR scripts (Backup copy, S3 replication, backup-account side) that
  will be reused to wire DR to the new backup account — just swap the account IDs.

---

## 5. The decision in one paragraph

Migrating to a clean account is legitimate, but it is a multi-week, customer-visible
project whose hard parts are the domain/email/cert/CloudFront/provider cutover, not the
compute. It does NOT reduce ongoing cost (the workload sets that). After migration you
MUST stand up a fresh backup account and wire DR to it before closing the old account —
otherwise you have a single point of failure, which is the opposite of where this
effort started. Sequence everything so the old account stays fully live and warm until
a clean window plus verified new-account DR, then retire it last.
