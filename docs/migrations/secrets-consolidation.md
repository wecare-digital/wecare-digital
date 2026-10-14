# Secrets Manager consolidation

Companion to `secrets-access-matrix.md`. Region us-east-1 · 22 active secrets ·
13 scheduled for deletion. No secret values were read.

## Objective (B1)
One secret-management STANDARD — not one mega-secret. A Lambda allowed to read a
Secrets Manager JSON object reads the whole object, so bundling unrelated
credentials into one record would widen blast radius. Optimise cost only where it
does not weaken least-privilege, isolation, rotation, or auditability.

## Finding: there is little to consolidate, and that is the right answer
On this inventory, security domains are already cleanly separated and each secret
costs ~$0.40/mo. Grouping two secrets saves $0.40/mo but only if every consuming
role already needs every field and rotation lifecycles match — which none of them
do strongly enough to justify over the isolation they currently have. **Security
isolation wins over marginal savings** (task B10). So consolidation here means:
standardise access + naming, retire the 3 Wix secrets after cutover, and move the
*non-secret* config out of Secrets Manager — not merging credentials.

## Centralized access helper (B3)
The repo already loads secrets at runtime with in-memory caching, masking, and
fail-closed behaviour (`docs/SECURITY_AND_SECRETS.md`;
`lambda_utils/masking.py`). That satisfies B5's requirements (logical naming,
cached retrieval, no values in logs, explicit failure, no hardcoded fallback), so
**no broad refactor is warranted**. The only standardisation to add:
- A single documented naming convention `wecare/prod/<domain>/<name>` for any NEW
  secret (existing names are grandfathered to avoid churn + re-grant risk).
- Synthetic-fixture unit tests asserting the loader never logs a value (task 8.2).

## Parameter Store moves (B4) — non-secret config only
Candidate: the NON-secret portion of `wecare/config/webhook-registry` (provider
ids, non-secret webhook routing config). Split it: keep any secret field in
Secrets Manager, move the non-secret registry to **SSM Parameter Store Standard
(free)**. Never move an actual secret to plaintext SSM. Prefer runtime IAM roles
over the stored long-lived `wecare/aws/iam-access-keys` where a consumer can use
the execution role instead (NEEDS_OWNER_REVIEW).

## Wix secret retirement (B6) — gated, after Workstream A acceptance
`wecare/wix/headless-api-key` (accessed 2026-10-14), `/catalog-webhook`
(2026-10-13), `/app-oauth` (exposed 2026-10-02). Sequence (each 🔒):
1. Confirm Phase-6 cutover live and stable; `check-wix-policy.sh` → 0 findings;
   `check_secrets_live.py`-style estate check shows no Wix secret reads.
2. Remove Wix env vars + IAM GetSecretValue grants via IaC (never the shared role).
3. Disable Wix OAuth/API at the provider; rotate the exposed `app-oauth`.
4. `aws secretsmanager delete-secret --recovery-window-in-days 30` for each (never
   `--force-delete-without-recovery` unless separately approved).
5. Access-failure monitoring: SystemEvent on any attempted Wix secret read.

## §PAT — GitHub PAT remediation (B9) — URGENT, gated
VERIFIED finding still valid (metadata, no value read):
`wecare/github-pat` is a **classic token, near-full scopes, EXPOSED 2026-08-25**,
unchanged since 2026-08-26, last accessed 2026-10-13 (actively used). The exposed
token is still live.

Recommended remediation (requires explicit approval + workflow coordination):
1. Mint a **fine-grained PAT** (or a **GitHub App** installation token) scoped to
   only the repos + permissions the Actions workflows actually use (contents,
   pull-requests, and the Amplify push trigger — audit `conversations-publish.yml`,
   `catalogue-sync.yml`, `deps-upgrade.yml` for the real scope used).
2. Store under `wecare/github-pat` (same name → no consumer change) or a new
   `wecare/prod/security/github-app`.
3. Rotate in Secrets Manager; redeploy / clear caches; update any GitHub Actions
   secret/variable mirror.
4. **Revoke the old classic token in GitHub** so the exposed copy (including any
   in the encrypted backup archive) can no longer authenticate.
Do not print or retrieve the token at any step.

## Backup hygiene (B6) — residual exposure is real
`wecare-credential-backups-775261844268` has **2 encrypted versions** of
`credential-backups/current/wecare-secrets-backup.txt.enc` (2026-09-25 and
2026-09-26, versioning on). These predate any Wix removal and still contain the
Wix + GitHub + other credentials. Deleting the live secrets does NOT purge these.
Plan (🔒, no deletion without authorization):
1. Rebuild future archives with `scripts/secrets_backup.py` EXCLUDING retired
   credentials.
2. Review the 2 old S3 versions + any local `.enc` copies under an approved
   retention policy.
3. The real mitigation is **key revocation at the provider** (step above): once
   the old Wix/GitHub keys are revoked, the historical encrypted copies cannot
   authenticate even if they persist for retention.
4. Do not delete the shared backup bucket or unrelated secrets.

## Cost (B10)
From `scripts/aws_cost_model.py --live`: baseline $8.80/mo storage (22×$0.40) +
~$2.50/mo request (at 500k calls). After Wix retirement: 19 secrets → $7.60/mo
storage (POTENTIAL −$1.20/mo). SSM Standard move: free. No CMK cost change (Wix
secrets use the AWS-managed key). Security requirements take precedence over the
sub-dollar savings.
