# Backup, disaster-recovery and cloud-portability plan

**Created:** 2026-10-16 · **Account:** `775261844268` · **Region:** `us-east-1`
· **Status:** living document — bump the date on any material change.

> Companion docs: [`architecture.md`](architecture.md) (what the platform is) and
> [`recovery-kit/README.md`](recovery-kit/README.md) (how to rebuild it).

> Scope: how to take a complete, restorable copy of the WECARE.DIGITAL platform,
> what protects it from accidental deletion or an AWS-side failure, and the exit
> path if the platform ever has to move off AWS (to Google Cloud or elsewhere).
>
> Account `775261844268`, region `us-east-1`. This document describes the plan and
> the exact commands; it does not itself run anything.

---

## 1. What actually makes up the platform

Before you can back something up you have to know what it is. The platform is
**not** a single app — it is five distinct layers, each with its own source of
truth and its own restore path.

| # | Layer | Where it lives | Source of truth | Lost if deleted? |
|---|-------|----------------|-----------------|------------------|
| 1 | Application code | this git repo (`src/`, `amplify/`, `scripts/`, `tests/`) | git | No — git has full history |
| 2 | Infrastructure definition | `amplify/*.ts` (CDK) + `scripts/provision_*.py` (boto3) | git | No — re-runnable |
| 3 | Runtime data | DynamoDB (~76 live tables), S3 (`wecare-digital-get`) | **AWS only** | **Yes — unrecoverable without a backup** |
| 4 | Secrets | AWS Secrets Manager (~28 secrets) | AWS, mirrored to GCP + encrypted file | Partially protected |
| 5 | Identity | Cognito user pool | **AWS only** | **Yes — users unrecoverable** |

The important truth: **layers 1 and 2 are already safe** (they are in git and are
reproducible). The risk is entirely in **layers 3, 4 and 5** — the live data,
secrets, and user identities that exist only inside AWS. A backup plan that only
protects the code is protecting the part that was never in danger.

A second truth worth stating plainly: `amplify/data/resource.ts` declares 58
models but **none are materialised** — the live tables were created by CDK and
`provision_*.py` scripts under the `stack-wecare-digital-*` naming scheme. So the
schema file is documentation, not an inventory. The authoritative list of what
exists comes from `scripts/aws_account_inventory.py`, not from reading the code.

---

## 2. Current state — what is already protected

This project already carries real backup machinery. The plan below builds on it
rather than replacing it.

| Asset | Mechanism already in place | Script |
|-------|---------------------------|--------|
| Account inventory | On-demand enumeration of Lambda/DDB/SQS/S3/Cognito/etc. | `scripts/aws_account_inventory.py` |
| Secrets | Encrypted (scrypt + AES-256-GCM) local file **and** SSE-KMS S3 copy; also mirrored one-way to GCP Secret Manager | `scripts/secrets_backup.py`, `scripts/google-cloud-setup.sh` |
| Secrets backup integrity | Independent decrypt + wrong-passphrase + no-plaintext check | `scripts/verify_backup_artifact.py` |
| Audit trail | CloudTrail management-event trail with log-file validation | `scripts/provision_cloudtrail.py` |
| Blog content | Export of blog corpus | `scripts/backup_blog_posts.py` |
| Credential backup bucket | Versioned, SSE-KMS, public-access-blocked, TLS-only | created by `secrets_backup.py` |

What is **not yet** systematically covered, and what this plan adds:

- DynamoDB point-in-time recovery (PITR) + on-demand backups on **all** live tables.
- S3 versioning + a cross-account/cross-region replica of the media bucket.
- A Cognito user-pool export (users cannot be recreated from code).
- AWS Backup as a single scheduled, auditable backup plan rather than ad-hoc scripts.
- A written, tested restore drill (a backup you have never restored is a guess).

---

## 3. Backup practice — the standard to hold

Follow **3-2-1**: at least **3** copies, on **2** different media/accounts, with
**1** off the primary account (or off AWS entirely). Concretely for this platform:

1. Primary: the live AWS resources.
2. Second copy: AWS Backup vault + DynamoDB PITR + S3 versioning, in-account.
3. Off-account/off-cloud copy: cross-account AWS Backup vault **or** the GCP mirror
   (secrets already go there) + an S3 replica.

Two independent safety properties you want on every destination:

- **Versioning** so an overwrite does not destroy the prior good copy.
- **Deletion protection / immutability** (S3 Object Lock, Backup Vault Lock) so a
  compromised or mistaken principal cannot delete the backups along with the data.
  This is what turns "we have backups" into "ransomware/fat-finger cannot erase
  them".

---

## 4. The backup plan, layer by layer

### 4.1 Code + infrastructure (layers 1–2) — already safe, keep it that way

- The repo is the backup. Ensure every provisioning change lands in
  `scripts/provision_*.py` or `amplify/*.ts` and is committed — an undocumented
  manual console change is the one thing git cannot restore.
- Mirror the git remote to a second host (a second remote push target) so loss of
  the primary git host is not loss of history.
- Keep `scripts/aws_account_inventory.py` output committed under
  `docs/execution/aws-inventory.{json,md}` so there is a dated manifest of what the
  live account contained, independent of the running account.

```bash
# Refresh the committed inventory snapshot
python scripts/aws_account_inventory.py
```

### 4.2 DynamoDB (layer 3) — the highest-value data

Two complementary mechanisms, both needed:

- **PITR** (continuous, 35-day rolling window, restores to any second). Protects
  against "something corrupted rows an hour ago".
- **On-demand / AWS Backup** (discrete snapshots retained for months/years).
  Protects against "we need the state from last quarter" and against a table being
  dropped entirely.

Enable PITR on every live table (idempotent — safe to re-run):

```bash
# For each live table name from the inventory:
aws dynamodb update-continuous-backups --region us-east-1 \
  --table-name stack-wecare-digital-<Table> \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true
```

Then put the tables under a single **AWS Backup** plan (daily + monthly, with
Vault Lock) so retention is scheduled and auditable instead of ad-hoc. Tag tables
with e.g. `backup=daily` and select by tag in the Backup plan, so a newly
provisioned table is covered the moment it carries the tag — no table silently
falls out of coverage.

> New-table discipline: every `scripts/provision_*_table.py` should set PITR and
> the `backup` tag at creation time, so coverage is a property of creating a table,
> not a thing someone remembers to do afterwards. This is the DynamoDB equivalent
> of the TTL discipline already enforced in `backend.ts`.

### 4.3 S3 media bucket `wecare-digital-get` (layer 3)

The bucket holds invoices, WhatsApp media, voice recordings, product images and
Meta-approved template media (`o/public/wa-tpl/` — **never move or rename those 61
objects**, Meta refetches them from the approved URL).

- **Enable versioning** (if not already) so an overwrite/delete is recoverable.
- **Lifecycle rule** to expire old noncurrent versions (cost control) but keep
  enough window to recover a mistake.
- **Replication** to a bucket in a **second account or second region** for the
  off-primary copy. Cross-account is stronger than cross-region alone, because it
  survives a compromise of the primary account.
- Respect the two roots: a "factory reset" wipes `o/stack/` only; `o/stream/`
  (static assets) and `o/public/wa-tpl/` must never be swept. The replica should
  copy everything, but any cleanup lifecycle must honour those boundaries.

### 4.4 Secrets (layer 4) — already strong, keep it fresh

The mechanism is sound (double-encrypted file + S3 + GCP mirror). The historical
failure was **staleness**, not weakness — the S3 copy was once 0 objects while the
local file was days old. So the rule is operational, not architectural:

```bash
python scripts/secrets_backup.py create    # rebuild from Secrets Manager (needs passphrase)
python scripts/secrets_backup.py upload     # push existing ciphertext to S3 (no passphrase)
python scripts/verify_backup_artifact.py    # prove it decrypts and leaks nothing
./scripts/google-cloud-setup.sh mirror-secrets   # refresh the one-way GCP mirror
```

Run `create` after any secret rotation; run `upload` + the verify on a schedule so
a stale cloud copy is caught by its `_generated` date, not discovered in an
incident.

### 4.5 Cognito user pool (layer 5) — the quiet gap

Users **cannot be recreated from code**. If the pool is deleted, identities are
gone. There is no native "export users" button, so:

- Enable **deletion protection** on the user pool (one setting — do this first; it
  is the cheapest, highest-value control here).
- Schedule a periodic export (`cognito-idp list-users`, paginated) of user
  attributes (never passwords — those are not exportable, by design) to the
  credential-backup bucket, encrypted. On restore, users re-verify; attributes and
  group membership are what you are protecting.
- Treat the pool as **referenced, not managed** (it already is — `referenceAuth`),
  so an Amplify redeploy can never recreate/replace it.

### 4.6 Put it under one scheduled plan

Ad-hoc scripts drift. Consolidate 4.2–4.5 into a single **AWS Backup** plan plus a
scheduled job (EventBridge → Lambda, or a CI cron) that:

1. Refreshes the inventory snapshot.
2. Confirms PITR is on for every table the inventory lists (fails loudly if a new
   table is uncovered).
3. Runs the secrets `upload` + verify.
4. Runs the Cognito export.
5. Reports success/failure to the existing SNS alarm topic
   (`stack-wecare-digital`), so a **failed backup pages you** the same way a failed
   deploy does.

A silent backup is the dangerous kind. Wire it to the alarms that already exist.

---

## 5. Restore drills — the part people skip

A backup is a hypothesis until you have restored from it. Schedule these:

- **DynamoDB**: quarterly, restore one table via PITR into a `*-restore-test` table,
  diff row counts, delete the test table. (Mirrors the Lightsail runbook pattern,
  which restores from a snapshot into a *new* instance rather than over the live
  one.)
- **S3**: confirm a deleted object can be recovered from a prior version and from
  the replica.
- **Secrets**: `verify_backup_artifact.py` already does the integrity half; once a
  quarter also do a real `restore` read to confirm field names are intact.
- **Cognito**: confirm the export parses and contains the expected user count.

Record each drill result (date, what was restored, time taken) under
`docs/execution/`. "Restores in N minutes, last proven on DATE" is the only backup
claim worth making.

---

## 6. Deletion / failure protection ("in case some delete or fails")

| Threat | Control |
|--------|---------|
| Someone deletes a DynamoDB table | PITR + AWS Backup snapshot + table deletion protection |
| Someone overwrites/deletes an S3 object | Versioning + replica + (optionally) Object Lock |
| Someone deletes the user pool | Cognito deletion protection + user export |
| Amplify redeploy replaces a resource | Reference existing resources (`referenceAuth`); CDK stacks are additive |
| Account compromise deletes backups too | Off-account vault + Vault Lock / Object Lock immutability |
| Region outage | Cross-region replica + Backup copy to a second region |
| Credentials lost | Encrypted secrets backup (file + S3 + GCP mirror) |

Note the existing guardrail scripts that already prevent whole classes of mistake:
`scripts/block_catastrophic.py`, `scripts/block_s3_bucket_creation.py`,
`scripts/block_broad_git_staging.py`, `scripts/block_inline_secrets.py`. These are
preventive controls — keep them wired as hooks; they stop the deletion before it
needs a restore.

---

## 7. Migration / exit plan — moving off AWS (Google Cloud or other)

The goal here is **portability as insurance**, not a committed migration. The
cleaner the exit path, the less locked-in you are, even if you never leave.

### 7.1 What is portable today vs what is sticky

| Component | Portability | Target on GCP (example) | Notes |
|-----------|-------------|-------------------------|-------|
| Next.js frontend | High | Cloud Run / Firebase Hosting | Framework-agnostic; it is a static/SSR app |
| Python Lambda functions | Medium | Cloud Functions / Cloud Run | Logic is portable; the AWS SDK calls and event shapes are not |
| DynamoDB | Low | Firestore / Bigtable / Spanner | No drop-in equivalent; needs a data-model mapping + migration |
| S3 | High | Google Cloud Storage | `gsutil`/Storage Transfer; object model is near-identical |
| Cognito | Low | Identity Platform / Firebase Auth | Users re-verify; password hashes do not transfer |
| SQS | Medium | Pub/Sub | Different delivery semantics (push/pull) |
| Secrets Manager | High | GCP Secret Manager | **Already mirrored** by `google-cloud-setup.sh` |
| Bedrock (AI) | Medium | Vertex AI | Model + prompt layer differs |
| SES / End User Messaging | Low | Provider-dependent | WhatsApp/SMS are provider integrations, re-point at the provider directly |

The honest read: **the frontend, S3 and secrets move easily; DynamoDB, Cognito and
the AWS-event-shaped Lambdas are the real migration work.** Any realistic exit is
driven by the data layer, not the code.

### 7.2 What already reduces lock-in

- **Secrets** already live in GCP Secret Manager as a one-way mirror
  (`google-cloud-setup.sh mirror-secrets`), so a fresh non-AWS machine can already
  bootstrap credentials.
- The Lambda fleet addresses tables by **physical name via `os.environ`**, not
  through an AppSync/Amplify binding — so repointing data access is an env-var +
  client-swap change per function, not a framework rewrite.
- Provider integrations (WhatsApp/Razorpay/Meta/Plivo) talk to the providers
  directly; they do not depend on AWS, so they survive a cloud move unchanged
  except for where the webhook lands. `scripts/check_live_provider_independence.py`
  and `scripts/provider_allowlist.py` already police this independence.

### 7.3 Phased migration approach (if ever triggered)

1. **Stand up the target in parallel.** Do not cut over anything. Create the GCP
   project, enable APIs (`google-cloud-setup.sh enable-apis`), confirm secrets
   mirror.
2. **Replicate storage first** (easiest, reversible): continuous S3 → GCS via
   Storage Transfer Service. Verify object counts + checksums.
3. **Export the data layer.** Snapshot DynamoDB → S3 (native export) → load into the
   chosen GCP store with an explicit key-mapping. This is where the model work is.
4. **Port compute.** Containerise the Python functions (they are already small,
   single-purpose handlers) and run on Cloud Run; swap `boto3` calls for the GCP
   client per data store. Do one non-critical function end-to-end first.
5. **Identity last.** Migrate Cognito users to Identity Platform; users re-verify.
   Run both auth systems in parallel during the window.
6. **Cut over by DNS/traffic**, keeping AWS warm and billable as the rollback target
   — exactly the pattern the Lightsail runbook uses (keep the old instance running,
   move a single routing lever, delete nothing until acceptance).
7. **Decommission only after a clean operating window** and a signed-off acceptance,
   never during the cutover.

### 7.4 The rule that makes migration safe

Mirror the Lightsail migration discipline that is already proven in this repo:

- The old environment **stays running and billable** throughout.
- Cutover is a **single reversible lever** (DNS / traffic split).
- **Nothing is deleted** until a multi-day clean window plus explicit acceptance.
- There is a written **rollback runbook** before the first cutover, not after.

---

## 8. Concrete next actions (in priority order)

1. **Cognito deletion protection** — one setting, highest value, do today.
2. **DynamoDB PITR on all live tables** + the per-table deletion protection, and bake
   it into every `provision_*_table.py`.
3. **S3 versioning + a lifecycle for noncurrent versions** on `wecare-digital-get`.
4. **One AWS Backup plan** (tag-selected, daily + monthly, Vault Lock) covering
   DynamoDB and S3, reporting to the existing SNS topic.
5. **Cognito user export** job to the encrypted backup bucket.
6. **Schedule** secrets `upload` + verify + GCP mirror refresh.
7. **Write and run the first restore drill**, record the result under `docs/execution/`.
8. **S3 → second account/region replication** for the off-primary copy.
9. Keep the GCP mirror current as standing exit insurance; re-run the independence
   checks in CI.

Items 1–3 are small, reversible, and remove most of the real risk. The rest hardens
and automates. The migration section (7) is insurance you keep warm, not a project
you have to run.
