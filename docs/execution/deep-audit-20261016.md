# Deep audit — repo + AWS infra consolidation state (2026-10-16)

Read-only verification pass against the live account **775261844268 / us-east-1**
and branch `stack` (`c26b60fd`). No mutating action was taken. Every figure below
comes from a deterministic script re-run live on 2026-10-15/16, not from recorded
counts, except where marked. Raw outputs: `.scratch/audit/` (inventory,
provider-independence, cost-model, secrets-access-matrix).

This supersedes the dated counts in the `aws-native-consolidation` spec where
they differ; it does **not** replace that spec, which remains the system of
record for the three workstreams.

## TL;DR

The consolidation program is ~90% executed and well evidenced. Wix is fully
exited, Lightsail Micro→Nano is done and the Micro retired, commerce IAM drift is
fixed. What remains is a short list of **owner-gated, hard-to-reverse** items plus
a few **local, reversible cleanups** of stale IAM and one script bug.

The single highest-impact finding is live and unchanged: **automation
authenticates as account root** (`aws sts get-caller-identity` → `arn:...:root`).

---

## 1. Live inventory (re-measured 2026-10-15, 0 collector errors)

| Resource | Live now | Spec recorded | Note |
| --- | --- | --- | --- |
| Lambda functions | 74 (67 w/ live alias) | 76 (68) | drift from completed deletions |
| DynamoDB tables | 76 | 84 | down after Wix/stale table removal |
| HTTP API routes | 375 | 375 | — |
| Routes with no authorizer | **373 of 375** | — | see finding 4 |
| Authorizers (account-wide) | 1 | — | see finding 4 |
| S3 buckets | 7 | 7 | — |
| Secrets (active / sched-delete) | 20 / 8 | 19 / 9 | 4 new unclassified (finding 3) |
| CloudFront distributions | 3 | — | — |
| CloudWatch alarms | 72 | — | $6.30/mo after 10 free |
| Log groups | 119 | — | retention not audited here |
| CFN stacks | 4 | — | — |
| Lightsail instances | 1 (Nano) | 1 (Nano) | Micro retired ✓ |
| SQS queues / DLQ w/o alarm | 10 / 0 | — | DLQ alarm coverage clean |

---

## 2. 🔒 B-0 — automation runs as account root (HIGHEST PRIORITY, unchanged)

`get-caller-identity` on this machine returns
`arn:aws:iam::775261844268:root`. All the read-only audit calls in this pass used
root credentials. Root keys cannot be scoped, cannot be constrained by SCPs, and
their compromise is total-account compromise.

**Remediation (owner-gated, hard-to-reverse — not executed):**
1. Create a dedicated IAM principal for automation (user with access keys, or
   preferably a role assumed via short-lived credentials) with only the
   policies the tooling actually uses.
2. Repoint `~/.aws/credentials` / CI to the new principal and verify every audit
   and provisioning script still runs.
3. **Delete the root access keys** in IAM once the new principal is proven.
4. Enable MFA on the root login.

This is the one item worth doing first; everything else is lower blast-radius.

**Step-by-step owner runbook (with verify + rollback):**
`docs/migrations/b0-retire-root-access-keys.md`. Confirmed live 2026-10-16:
`AccountAccessKeysPresent=1`; the `wecare-prod` profile authenticates as root;
root login already has MFA. An IAM user (`wecare-admin`, AdministratorAccess)
already exists, so the fix is "repoint the profile to a dedicated IAM user,
verify, delete the root key" — not a from-scratch build.

---

## 3. Secrets — least privilege is the open theme (Workstream B)

Active 20 / scheduled-for-deletion 8. Full matrix:
`.scratch/audit/secrets-access-matrix.md`.

**3a. Shared-role over-grant (the core issue).** `wecare-digital-lambda-role`
(the shared execution role, 59 functions) can `GetSecretValue` on ~17 of 20
active secrets, including payment and security-domain secrets that only a handful
of functions need. This is Workstream B's **B-1b** (full allow-list rewrite),
blocked because the role's inline policies are already at IAM's 10,240-byte
limit. The guard policy `wecare-shared-role-secret-guard` (B-1a) already *denies*
the three most sensitive (`github-pat`, `backup/recovery-passphrase`,
`aws/iam-access-keys`); the positive allow-list is still owner-gated.
Fix path: move the shared role to **customer-managed** policies (not inline) to
escape the size limit, then scope per-function.

**3b. Four secrets not on the approved allow-list** (provider-independence FAIL,
`NEEDS_OWNER_REVIEW`): `wecare/ads/account-registry`,
`wecare/integrations/owner-input-20261001`, `wecare/plivo`, `wecare/sinch/sms`.
Three of these are already *scheduled for deletion* — classify or confirm the
deletion. `wecare/plivo` vs `wecare/plivo/api` looks like a duplicate; verify no
live reader before letting the deletion complete.

**3c. Standing 🔒 items (unchanged from spec, owner-gated):**
- `wecare/github-pat` — classic near-full-scope PAT, flagged EXPOSED 2026-08-25.
  Live-confirmed 2026-10-16: never rotated since (LastChanged 2026-08-26) and
  **still in use** (LastAccessed 2026-10-13). One reader (`wecare-workspace-mcp`,
  reads the `token` field at `handler.py:488`). ROTATE → fine-grained token or
  GitHub App. Owner runbook with verify + rollback:
  `docs/migrations/github-pat-rotation.md`.
- `wecare/aws/iam-access-keys` — stored long-lived keys, no measured reader;
  retire after confirming (ties to B-0).
- `wecare/config/webhook-registry` — MOVE_TO_PARAMETER_STORE only if the owner
  confirms no field is secret.

---

## 4. Route authorization — RESOLVED, posture is sound (verified 2026-10-16)

The raw inventory's "373/375 no authorizer" is **in-handler auth by design**, not
a gap. `scripts/audit_route_auth.py` run live against the HTTP API
(`zllr9lrg7j`, 375 routes) reports **0 OPEN** (no auth at either layer):

- **341** — gateway `NONE`, handler authenticates via
  `lambda_utils.middleware.require_auth`.
- **2** — gateway-authorized.
- **8** — intentionally public, each with a documented reason: `ANY /mcp`
  (read-only MCP over public content), `GET /ecommerce/service-prices`
  (anonymous price read, no input, cannot mutate), `GET /r/{code}` (short-link
  redirect), `GET|POST /webhook/sinch-rcs` (GET health probe; POST carries HMAC),
  `GET /workspace/mcp/oauth/callback` (PKCE + one-use state), `POST
  /auth/email-verification` (email-OTP door, no write), `POST /auth/validate`
  (token validation — authenticating it would be circular).
- **0 DANGLING**, **2 UNRESOLVED** — `GET /seo-tools/blog-public` and
  `/{proxy+}` → `wecare-blog-public`. Checked by hand: this is the AWS-native
  **public blog read** path (consolidation req A1 wants anonymous blog reads);
  the function is read-only and unauthenticated **by design**. The "unresolved"
  is only a source-path naming gap in the audit script (the deployed function's
  code isn't under a `blog_public`-named repo path), not a missing auth.

**Verdict:** no action needed on route auth. Keep `audit_route_auth.py` in CI
(it already runs in `.github/workflows/route-auth.yml`) so a future `NONE` route
without in-handler auth is caught the way the 2026-09-20 `voice-cdr-webhook`
hole was.

---

## 5. Stale IAM — two dangling-table grants (LOCAL-ish, but IAM = owner-gated)

Both confirmed live; both are exactly the "remove stale/unused" cleanup asked
for.

**5a. `wecare-email-verification-role` → `EmailVerificationLeastPrivilege`.**
The `OtpAndCustomerTables` statement grants
`stack-wecare-digital-CustomersTable`, which **does not exist** (live tables are
`ContactsTable` and `CustomerSessionsTable`). The statement legitimately keeps
`DownloadGrantsTable`. Fix: drop the dead ARN from the Resource list. Reversible,
narrow — but an IAM write, so owner-gated. Reconcile through IaC
(`scripts/provision_email_verification.py`) so it doesn't reappear on deploy.

**5b. `ContactIAMRole09bdb2-...-NONE` → `DynamoDBAccess`.** Grants
`Contact-...-NONE`, a deleted Amplify-sandbox table. The role is attached to
**zero** live Lambdas. The `-NONE` suffix marks an unmaterialized `a.model()`
sandbox deploy (consistent with design.md: `amplify/data/resource.ts` is inert).
Safe deletion candidate. Owner-gated because it's a role delete; verify once more
it's unreferenced, then remove.

---

## 5c. CloudWatch — one firing alarm, one dangling alarm

Surfaced by the fresh inventory crosschecks (`docs/execution/aws-inventory.json`):

- **`wecare-blog-ingest-dlq-depth` is in ALARM — DIAGNOSED 2026-10-16.** The DLQ
  holds **1 message** (threshold `>0`): source `blogsrc_b2b75d…` =
  `A New Model of Integrity … .pdf`, dead-lettered after 5 retries on 2026-10-15
  07:16–07:40 UTC. CloudWatch logs give the exact cause:
  `ModuleNotFoundError: No module named 'blog_pipeline'` at `blog_sources.py:689`
  (`import blog_pipeline as bp`).

  Root cause is a **stale deployment, not a code bug.** The live `wecare-seo-tools`
  bundle (deployed 2026-10-15 08:25 UTC, 339 KB) is missing `blog_pipeline.py`,
  `blog_quality_v2.py`, and vendored `pypdf` — it predates the #570 packaging fix.
  Verified by downloading the live code (only `seo_tools_handler.py` at root) and
  by building from current `stack`, which correctly yields a 1.5 MB zip with all
  three via `scripts/deploy_seo_tools.package()`. The source record is still
  `status=UPLOADED` with an empty `error` because the import failed before `_fail`
  could record it.

  **Resolution (🔒 owner — both are production mutations, low-risk, well-tested):**
  1. Redeploy `wecare-seo-tools` from current `stack` (the SEO-tools deploy
     workflow). `tests/test_seo_package_contract.py` gates this exact regression.
  2. Then redrive the one DLQ message (admin `blog_queue.redrive()` via the
     seo-tools route) so the PDF re-extracts. Do not redrive before the redeploy
     or it fails a 6th time.
- **`wecare-ddb-throttle-UsersTable` watches a deleted table.** Its dimension
  `TableName=stack-wecare-digital-UsersTable` points at a table that no longer
  exists, so the alarm can never evaluate meaningfully. Delete the alarm (same
  stale-cleanup theme as finding 5). Owner-gated as a CloudWatch mutation;
  reconcile through whatever provisions the alarm so it does not reappear.

## 6. Cost (credits still cover 100% of gross usage)

`.scratch/audit/cost-model.json`. Gross Aug/Sep/Oct = $61.72 / $101.30 / $72.48,
each fully offset by credits. October fixed-line run-rate ≈ **$125/mo**. No cash
saving until credits are exhausted — **owner must read the credit balance/expiry
in the Billing console** (the CE API does not expose it).

Levers, largest first (all POTENTIAL / owner-gated):
- Business Support plan — **$29/mo** (keep for SLAs, or drop to Basic).
- Amplify build minutes — **~$23–46/mo**; every merge to `stack` triggers a full
  build. Batch merges / skip docs-only builds.
- Hosting egress — **$15.61**; egress jumped 4.6 GB (Sep) → 49.1 GB (Oct 1-14).
  Investigate the cause before acting.
- CloudWatch 72 alarms — $6.30/mo; review only.

Already realised: Wix secret deletions (−$1.20), Lightsail Nano (−$2.00).

---

## 7. Repo-side cleanup candidates

- **`scripts/aws_cost_model.py` live-count bug — FIXED this pass.** `--live`
  crashed with `invalid literal for int(): '50\n22'` because `length(...)` queries
  on paginated ListSecrets/DescribeAlarms print one number per page. Now counts
  ARNs/names across pages; 6 tests pass. Committed.
- **Audit evidence sprawl — INDEXED this pass.** ~40 audit/inventory docs under
  `docs/`. Rather than delete measured evidence, built `docs/audit-doc-index.md`
  classifying each as CURRENT / SUPERSEDED (with its replacement) / POINT-IN-TIME.
  Superseded living docs flagged: `AWS_COST_CONTROL.md`,
  `AWS_CONSOLIDATION_AUDIT.md`, `FRONTEND_DUPLICATION_AUDIT.md`.
- **`.venv` absent on this host.** Steering `10-project.md` assumes a repo at
  `/Users/wecaredigital/wecare-digital` with a `.venv`; on this machine the git
  root is the workspace itself and no `.venv` exists. This audit used a throwaway
  `.venv-audit` (boto3 only). The steering path note is stale for this host.

---

## 8. What I did NOT touch (owner decisions, per safety rules)

Root-key retirement (B-0), GitHub PAT rotation, secret deletions/retention,
IAM edits (5a/5b), shared-role allow-list rewrite, Meta catalog-sync enable
(A.9), the ₹1 checkout QA (P0.5), and all cost levers (support plan, build
cadence, egress, Lightsail retire). Each is production-mutating or hard to
reverse and waits for explicit approval.

## Suggested order of attack

1. **B-0 root keys** — highest blast radius, do first.
2. Fix the cost-model live-count bug — **DONE in this pass** (local, reversible;
   `scripts/aws_cost_model.py`, 6 tests pass).
3. Firing `wecare-blog-ingest-dlq-depth` alarm (5c) — **DIAGNOSED**: stale
   `wecare-seo-tools` deploy missing `blog_pipeline`. Owner: redeploy, then
   redrive the 1 DLQ message.
4. Clean the stale IAM grants (5a/5b) and the dangling alarm (5c) via IaC —
   small, approve as a batch.
5. Classify / confirm-delete the 4 unlisted secrets (3b).
6. Route-auth intent (4) — **DONE**: verified 0 OPEN routes; posture sound.
7. Audit-doc sprawl — **DONE**: `docs/audit-doc-index.md` (current/superseded/
   point-in-time). Scripts dead-code: left to deliberate per-script owner review.
8. Owner cost decisions + credit-balance check (6).
9. Shared-role allow-list via customer-managed policies (3a / B-1b).

## Done autonomously this session (local, reversible)

- Fixed `scripts/aws_cost_model.py` pagination bug (6 tests pass).
- Diagnosed the blog-ingest DLQ alarm to root cause (stale deploy).
- Verified route-auth posture (0 OPEN) with `audit_route_auth.py`.
- Built `docs/audit-doc-index.md`.
- Wrote owner runbooks: B-0 root keys, GitHub PAT rotation.
- Refreshed `docs/execution/aws-inventory.json` from a live run.

Everything production-mutating or credential-related is left staged for owner
approval, per the safety rules — not auto-executed even in Autopilot.
