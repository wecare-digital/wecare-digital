# Recovery kit — rebuild the whole platform from git

> **Purpose.** If the AWS account is disabled, lost, or you need to stand the
> platform up somewhere else, this folder is the single entry point. It does not
> hold a second copy of the code — the code is already in this repo and that *is*
> the backup. It is the **index and the ordered runbook** that ties the committed
> source to the exact scripts that recreate every piece.
>
> Account `775261844268`, region `us-east-1`.

---

## Read this first: what is and isn't in git

A git folder is the right home for everything **reproducible**, and the wrong home
for anything **live or secret**. So this kit is split cleanly:

**In git (this repo) — the rebuild material:**

- All application code — `src/` (Next.js frontend).
- All **78 Lambda handlers** — `amplify/functions/**` across 9 domains.
- All infrastructure definitions — `amplify/*.ts` (CDK) and the
  `scripts/provision_*.py` fleet (boto3).
- The portable fleet deployer — `scripts/deploy_all_lambdas.py`.
- Every runbook under `docs/migrations/`.

**NOT in git, on purpose — restored from backup, never committed:**

- Secrets (AWS Secrets Manager) → encrypted backup file + S3 copy + GCP mirror.
- Runtime data (DynamoDB rows, S3 objects) → PITR / AWS Backup / S3 versioning.
- Cognito users → the periodic export in the credential-backup bucket.

Committing any of those three would be a security leak and git is the wrong tool
for them anyway. See `../backup-and-dr-plan.md` for how each is protected.

---

## The 78 Lambdas, and how each one is recreated

Every function's source lives under `amplify/functions/<domain>/<name>/handler.py`.
The authoritative map of **function name → source dir → the script that creates
it** is the `SPECS` list in `scripts/deploy_all_lambdas.py`. Two script roles:

- **`provisioned_by`** — the `provision_*.py` (or CloudFormation) script that must
  **create** the function the first time (role, env, routes, triggers).
- **`deploy_all_lambdas.py`** — updates the code of a function that already exists,
  for the whole fleet or a named subset, then publishes via `snapstart_publish.py`.

So "redeploy from scratch" = run each function's `provisioned_by` once, then
`deploy_all_lambdas.py` to push current code. The function domains:

| Domain | Dir | What it covers |
|--------|-----|----------------|
| `ai` | `amplify/functions/ai/` | KB query, response generation, config, agent action group, MCP |
| `auth` | `amplify/functions/auth/` | customer registration/profile, WhatsApp OTP, email verification, Cognito custom message |
| `core` | `amplify/functions/core/` | contacts, CRM, messages, service API, auth middleware, URL shortener, secure files |
| `ecommerce` | `amplify/functions/ecommerce/` | checkout, catalog, coupons, gift cards, invoices, orders, product image gen |
| `edge` | `amplify/functions/edge/` | Lambda@Edge get-miss redirect |
| `messaging` | `amplify/functions/messaging/` | WhatsApp in/out, SMS, email, voice, RCS, bulk, templates, Meta/Plivo integrations |
| `operations` | `amplify/functions/operations/` | billing, SLA, bulk workers, DLQ replay, SEO tools, system cleanup, docs scraper |
| `payments` | `amplify/functions/payments/` | Razorpay webhook, invoice engine, payments read |
| `shared` | `amplify/functions/shared/lambda_utils/` | shared library bundled into every function |

List the live map any time:

```bash
python scripts/deploy_all_lambdas.py --list
```

---

## Restore order (in-place: same AWS account recovered)

Dependencies run top-down. Do them in this order; each step is idempotent.

1. **Credentials.** Recover AWS access first (IAM console / SSO) — the secrets
   backup cannot bootstrap AWS auth because reading it needs AWS auth. Then confirm
   secrets exist, or restore them:
   ```bash
   python scripts/secrets_backup.py verify     # decrypt-check the local artifact
   python scripts/secrets_backup.py restore     # list field names (no values printed)
   ```
2. **Identity.** Cognito user pool. If deleted, recreate and import users from the
   export (users re-verify; passwords never transfer).
3. **Data stores.** DynamoDB tables + S3 bucket. Restore tables from PITR / AWS
   Backup; restore S3 objects from a version or the replica. The provision scripts
   create empty tables — the *data* comes from backup, not from code.
   ```bash
   python scripts/aws_account_inventory.py       # confirm what exists vs what should
   ```
4. **Infrastructure.** Queues, alarms, dashboard, URL shortener, SEO store — the CDK
   backend plus the provision scripts:
   ```bash
   python scripts/provision_*.py --apply          # run the ones your account is missing
   ```
5. **Lambda fleet.** Create any missing functions via their `provisioned_by`
   script, then push current code and publish:
   ```bash
   python scripts/deploy_all_lambdas.py           # whole fleet + publish aliases
   python scripts/deploy_all_lambdas.py wecare-contacts   # or a single function
   ```
6. **Routes / edge / DNS.** Re-register HTTP API routes and the edge redirect, then
   repoint DNS last so traffic only arrives once the stack is healthy.
7. **Verify.**
   ```bash
   python scripts/post_deploy_health.py
   python scripts/check_deployed_source.py
   ```

---

## Rebuild somewhere else (off-AWS migration)

The full phased approach is in `../backup-and-dr-plan.md` §7. The short version:

- **Frontend, S3, secrets** are the easy, portable parts — secrets already mirror
  to GCP (`scripts/google-cloud-setup.sh mirror-secrets`).
- **DynamoDB, Cognito, and AWS-event-shaped Lambdas** are the real work — they need
  a data-model mapping and a client swap, not just a lift.
- The Lambdas address tables by **physical name via `os.environ`**, so repointing
  data access is an env + client change per function, not a framework rewrite.
- Keep the old environment running and billable, cut over with one reversible
  lever, delete nothing until a clean window plus sign-off — the discipline already
  proven in the Lightsail runbooks here.

---

## Keeping this kit honest

This README names counts (78 handlers, 9 domains) that are true at the time of
writing but will drift. The living sources of truth are:

- `scripts/deploy_all_lambdas.py --list` — the real function map.
- `scripts/aws_account_inventory.py` — the real account contents.

Trust those two over any number written here. If you add a Lambda, it belongs in
the `SPECS` list with its `provisioned_by` script — that is what keeps it inside
the recovery path automatically, instead of being a function nobody can redeploy.
