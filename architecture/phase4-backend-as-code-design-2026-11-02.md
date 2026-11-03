# Phase 4 backend-as-code design and migration runbook (2026-11-02)

Target-state design, drift-reconciliation approach, and operator runbook for
bringing the script-deployed WECARE.DIGITAL Lambda fleet under a single
reviewable source of truth. This is the written deliverable that a human
operator with live AWS access executes. It builds directly on the offline,
source-derived classification in
[`docs/ops/backend-classification-2026-11-02.md`](../docs/ops/backend-classification-2026-11-02.md)
and the offline inventory builder
[`scripts/ops/build_handler_inventory.py`](../scripts/ops/build_handler_inventory.py).

This phase corresponds to Section 6 "Phase 4 - Backend as code" of
[`architecture/workspace-audit-2026-11-02.md`](workspace-audit-2026-11-02.md),
which is flagged `[BLOCKED: AWS access]`. All guardrails in Section 7 of that
audit and the release standards in
[`docs/ops/backend-audit-2026-11-02.md`](../docs/ops/backend-audit-2026-11-02.md)
apply here and are enforced throughout this document.

NOTHING in this document runs a live AWS call or a pipeline deploy. The steps
that require live AWS credentials are enumerated, separately and explicitly, in
the "BLOCKED on AWS access (operator-only)" section at the end. No account IDs,
no ARNs, no IAM policy bodies, and no new live inventory are introduced here.

## 1. Current state (file-cited)

The backend today splits across two ownership models. Only the first is managed
as code in a pipeline; the second is deployed by imperative scripts, which is the
drift the audit flagged.

### 1a. Gen 2 IaC subset (pipeline-owned)

`amplify/backend.ts` declares `defineBackend({ auth, data, storage })` and then
calls `addBackendResources` and `addSeoResources`. This CDK stack owns:

- Auth (Cognito user pool) via `amplify/auth/resource.ts`, referenced with
  `referenceAuth` against an existing pool.
- Data (roughly 58 DynamoDB models exposed through AppSync) via
  `amplify/data/resource.ts`.
- Storage (S3 bucket) via `amplify/storage/resource.ts`.
- Four SQS queues (inbound-dlq, bulk-queue, bulk-dlq, outbound-dlq) and the
  CloudWatch alarms, dashboard, and log-retention resources, via
  `amplify/backend-resources.ts`.
- The SEO audit/log table and its Lambda, via `amplify/seo-resources.ts`.

Separately, `infra/cloudwatch-retention-enforcer.yml` is a standalone
CloudFormation stack (`wecare-cloudwatch-retention-enforcer`) that owns the
`wecare-log-retention-enforcer` function, its role, and its log group. It is not
in the script-deploy map.

### 1b. Script-managed Lambda fleet (not pipeline-owned)

`scripts/deploy_all_lambdas.py` is the canonical packer and deployer. It holds a
`SPECS` table of about 63 `Spec("wecare-<name>", "<domain>/<dir>", ...)` entries
that map a live function name to its handler source under `amplify/functions/**`
plus packaging metadata (standalone, extra_dirs, extra_files, required_layers,
required_memory, required_timeout). Its `build_zip` routine copies
`amplify/functions/shared/lambda_utils` into every non-standalone zip. Per-function
`provision_*.py` scripts carry their own `FUNCTION_NAME` and `FUNCTION_DIR` (for
example `provision_checkout.py` maps `wecare-checkout` to
`amplify/functions/ecommerce/checkout`). A pipeline deploy does not own any of
these functions.

### 1c. Env source of truth

`config/lambda-env-manifest.json` records the committed live function to env-key
map (72 functions). `scripts/env_manifest.py` verifies and exports it. Handlers
read configuration with `os.environ.get("KEY")`. Running `scripts/env_manifest.py`
with no arguments reads from live AWS, so it is an operator-only step; `--export`
rewrites the manifest from live AWS. Only KEY names are ever treated as reviewable
data; recorded values are sensitive.

### 1d. Classification already produced (Phase 4 prerequisite)

[`docs/ops/backend-classification-2026-11-02.md`](../docs/ops/backend-classification-2026-11-02.md)
(feature FEAT-001) labelled every resource CDK/CloudFormation-owned or
script-managed from committed data, before any pipeline change, per the audit
Section 7 release standards. The offline inventory builder
[`scripts/ops/build_handler_inventory.py`](../scripts/ops/build_handler_inventory.py)
reproduces the counts (318 total `.py`, 190 shared modules, 73 standalone
handlers resolved on disk, 63 `SPECS` entries, 72 manifest functions) and writes
only to the gitignored `.scratch/` path. That classification is the input to this
design; this document does not repeat the per-domain table.

## 2. Target state options and recommendation

The goal (audit Section 6, Phase 4) is to kill drift by bringing the
script-deployed functions under a single reviewable source. Three options:

### Option A: import live functions into CDK/CloudFormation

Import the existing live functions into the Amplify Gen 2 CDK stack (or a sibling
CloudFormation stack), reusing the pattern `amplify/backend.ts` already applies to
the SEO table/Lambda, the SQS queues, and the CloudWatch alarms. Deploy then flows
through the pipeline for those resources.

- Pro: one authoritative, diffable, reviewable definition per resource; drift is
  caught by a stack diff.
- Con: high blast radius. A careless import or a Gen 2 pipeline deploy over a
  manually managed resource violates audit Section 7 guardrail 4 and the release
  standards. It also risks the live `live` aliases, canary checks, rollback
  capture, and payment gates that the script fleet currently preserves.

### Option B: committed inventory-of-record, deploy stays script-driven

Keep deploy script-driven, but make a committed, non-sensitive
inventory-of-record the single reviewable source: function name, source path,
deploy script, and env KEY names only, with NO ARNs and NO account IDs. The
offline builder
[`scripts/ops/build_handler_inventory.py`](../scripts/ops/build_handler_inventory.py)
is the generator for this record; a non-sensitive, reviewed subset of its fields
(name, source_path, domain, classification, deploy owner, env KEY names) is what
would be committed, never the raw `.scratch/` output.

- Pro: safe to land now with no AWS access; makes ownership reviewable in the
  public repo without leaking ARNs or account IDs; no change to the live deploy
  path, so aliases, canary, rollback, and payment gates are untouched.
- Con: deploy is still imperative, so this reduces drift visibility but does not
  by itself make the pipeline authoritative.

### Option C (recommended): hybrid, inventory-of-record now, incremental CDK import later

Land the inventory-of-record (Option B) immediately as the single reviewable
source, then import resources into CDK/CloudFormation (Option A) incrementally,
lowest-risk-first, one classified resource at a time.

Recommendation: adopt Option C. The reason is the audit Section 7 guardrails and
the [`docs/ops/backend-audit-2026-11-02.md`](../docs/ops/backend-audit-2026-11-02.md)
release standards: never run a Gen 2 pipeline deploy over a manually managed
resource, and classify each resource before changing its deployment pipeline. A
wholesale Option A import is therefore not permitted in one move. The
inventory-of-record gives an immediate, safe, reviewable source of truth with no
AWS access, and the incremental import then proceeds only after each resource is
classified and signed off, preserving the live aliases, canary, rollback, and
payment gates at every step.

## 3. Drift reconciliation (318 repo `.py` vs roughly 76 live functions)

### 3a. Why the gap exists

The 318 `.py` files under `amplify/functions/**` are not 318 Lambdas:

- 190 of them live under `amplify/functions/shared/**` (the `lambda_utils`
  package). `scripts/deploy_all_lambdas.py` packages these INTO function zips, so
  they ship as dependencies, not as standalone Lambdas.
- Retired resources inflate the repo side. `config/backend-retirement.json` lists
  functions, routes, and a table that were removed from live AWS but whose source
  or references may still exist in the tree.
- Shared source closures: two `SPECS` entries can package the same source
  directory as a strangler pair, so function names outnumber source directories.
  The live example today is `wecare-checkout` and `wecare-commerce`, both
  packaging `ecommerce/checkout`.
- Delegated and image-package functions are deployed outside the `SPECS` map (for
  example the MCP functions via CloudFormation, and the image-package
  `wecare-docs-scraper`), so they do not line up one-to-one with `SPECS` rows.

The approximately 76 live functions (quoted in
[`docs/ops/backend-audit-2026-11-02.md`](../docs/ops/backend-audit-2026-11-02.md))
is therefore smaller than the repo `.py` count by construction, not purely by
drift.

### 3b. Reconciliation procedure (operator runs the live half)

1. Generate the PRIVATE live registry (operator-only, live AWS):
   `scripts/ops/generate_backend_registry.py --expected-account <ACCOUNT_ID>`,
   redirecting stdout into a restricted, encrypted, gitignored path (for example
   under `.scratch/`). This output is sensitive and must never be committed
   (audit Section 7 guardrail 2; backend-audit "Private inventory"). The
   generator leaves `source_path`, `deployment_script`, `business_owner`, and the
   table `consumers` fields null, for assignment by code review.
2. Generate the OFFLINE repo inventory (safe, no AWS):
   `python3 scripts/ops/build_handler_inventory.py` (default output
   `.scratch/backend-handler-inventory.json`, gitignored).
3. Diff the two into three sets:
   - (a) in-repo-and-live: reconcile `source_path` and deploy owner; this is the
     healthy, mapped fleet.
   - (b) in-repo-not-live: candidate dead code or an undeployed function; confirm
     before any removal, do not assume dead.
   - (c) live-not-in-repo: untracked drift or a manually created resource; this
     is the highest-attention set.
4. Check env drift with `config/lambda-env-manifest.json` plus
   `scripts/env_manifest.py`. The committed manifest holds the expected
   function-to-env-KEY map; `scripts/env_manifest.py` (live, operator-only)
   verifies it against AWS. Compare by KEY name only.

Forbidden during reconciliation: resurrecting any entry in
`config/backend-retirement.json`. The retired functions
(`wecare-ai-generate-response`, `wecare-meta-catalog-sync`), the retired routes
(`GET` and `POST /wa-business/catalog-sync`), and the retired table
(`stack-wecare-digital-SmsOutboundTable`) must not be re-added. The shared module
`amplify/functions/shared/lambda_utils/ecommerce/meta_catalog_sync.py` is retained
on purpose and is not a resurrection. The offline builder already asserts no
retired function leaks into an active set, so a diff that re-activates one is a
defect.

## 4. Migration runbook (ordered, operator-executable)

### 4a. Pre-flight checklist

- [ ] On production branch context `wecare.digital` (audit Section 7 guardrail 1);
      Phase 4 work branch cut from it.
- [ ] Classification signed off from
      [`docs/ops/backend-classification-2026-11-02.md`](../docs/ops/backend-classification-2026-11-02.md);
      every candidate resource is labelled CDK/CloudFormation or script-managed.
- [ ] Live `live` Lambda aliases, canary checks, rollback capture, and payment
      gates confirmed present and understood (backend-audit release standards).
- [ ] Rollback snapshot available per the `docs/execution/snapshots` convention:
      the pre-deploy code zips are gitignored (`docs/execution/snapshots/*.zip`)
      while the config JSON carrying `CodeSha256` is tracked. Confirm a current
      snapshot exists for any function about to be touched.
- [ ] Two npm roots kept separate; `amplify/` root is NOT installed (audit
      Section 7 guardrail 6). Braces/minimatch guard scripts and `package.json`
      overrides preserved (guardrail 5).
- [ ] `npm audit` is NOT declared clean (guardrail 3).

### 4b. Ordered steps

1. Classification sign-off (done offline in FEAT-001; re-confirm it still matches
   the tree if the tree changed).
2. Generate the private live registry (operator-only; see step 1 of 3b).
3. Diff the live registry against the offline inventory (step 3 of 3b) into the
   three sets.
4. For each live function, assign deploy owner, source path, and (for tables)
   DynamoDB consumers via code review. These are the fields
   `scripts/ops/generate_backend_registry.py` leaves null.
5. Pick a per-resource target: CDK/CloudFormation import, or stays-script-managed
   but recorded in the inventory-of-record.
6. Import lowest-risk resources FIRST: no HTTP route, non-payment, no customer
   data path. Keep the live `live` aliases, canary checks, rollback capture, and
   payment gates intact at every import. Never run a Gen 2 pipeline deploy over a
   resource still classified as manually managed (audit Section 7 guardrail 4;
   release standards).
7. After each import, re-run `scripts/env_manifest.py` (operator-only, live) to
   confirm no env drift was introduced, comparing by KEY name against
   `config/lambda-env-manifest.json`.
8. Repeat for the next lowest-risk resource. Payment, auth, and WhatsApp
   functions (and any with an HTTP route) are imported LAST, each with its own
   sign-off.

### 4c. Rollback note

If an import or env change regresses a function, roll back using the pre-deploy
snapshot under the `docs/execution/snapshots` convention: restore the gitignored
code zip whose tracked config JSON `CodeSha256` matches the last-known-good
version, and re-point the `live` alias at that version. Do not delete backups or
edit customer/product data during rollback (backend-audit release standards).

## 5. BLOCKED on AWS access (operator-only)

Every step below requires live AWS credentials or deploy access that this phase
does NOT have. The orchestrator or a human operator runs these, not this
offline phase. Each item lists the exact command or action and the
credential/permission it needs.

1. Live registry generation.
   - Command: `scripts/ops/generate_backend_registry.py --expected-account <ACCOUNT_ID>`
     with stdout redirected to a restricted, encrypted, gitignored path.
   - Needs: read credentials for STS, Lambda, DynamoDB, apigatewayv2, events, and
     cloudformation in the production account.
   - Why blocked here: no live AWS credentials; output is sensitive and must never
     be committed to this public repo (audit Section 7 guardrail 2; backend-audit
     "Private inventory").

2. The 318-vs-roughly-76 reconciliation diff.
   - Action: diff the private live registry against
     `.scratch/backend-handler-inventory.json` into the three sets (3b step 3).
   - Needs: the live registry produced by item 1.
   - Why blocked here: depends on item 1.

3. Any CDK/CloudFormation import or Gen 2 pipeline deploy.
   - Action: import a classified resource, or deploy the stack that now owns it.
   - Needs: the production deployment role.
   - Why blocked here: no deploy role; and it is explicitly forbidden over any
     manually managed resource until that resource is classified (audit Section 7
     guardrail 4; release standards).

4. IAM least-privilege review of the shared execution role.
   - Action: run IAM Access Analyzer plus CloudTrail access-evidence review and
     source-code-based policy generation over the shared Lambda execution role
     used by 54 functions, covering its 16 inline policies and 6 attached
     policies.
   - Needs: IAM read, Access Analyzer, and CloudTrail read credentials.
   - Why blocked here: no live AWS credentials. Do not blindly remove shared
     permissions or create incomplete least-privilege roles (backend-audit).

5. Live env-drift verification.
   - Command: `scripts/env_manifest.py` (no args reads live AWS; `--export`
     rewrites `config/lambda-env-manifest.json` from live AWS).
   - Needs: Lambda read (and, for `--export`, the right to rewrite the committed
     manifest after review).
   - Why blocked here: it hits live AWS.

6. CloudWatch retention-enforcer first live invocation test.
   - Action: invoke the `wecare-log-retention-enforcer` function (owned by
     `infra/cloudwatch-retention-enforcer.yml`) once and confirm it applies
     retention as expected.
   - Needs: Lambda invoke and CloudWatch Logs read credentials.
   - Why blocked here: no live AWS credentials.

## 6. Phase 4 artifacts and references

The three Phase 4 artifacts, cross-linked:

- This design and runbook:
  `architecture/phase4-backend-as-code-design-2026-11-02.md`.
- Offline, source-derived classification:
  [`docs/ops/backend-classification-2026-11-02.md`](../docs/ops/backend-classification-2026-11-02.md).
- Offline inventory builder (generator for the inventory-of-record):
  [`scripts/ops/build_handler_inventory.py`](../scripts/ops/build_handler_inventory.py).

Governing references:

- [`architecture/workspace-audit-2026-11-02.md`](workspace-audit-2026-11-02.md)
  Section 6 "Phase 4 - Backend as code" and Section 7 "Constraints and
  guardrails".
- [`docs/ops/backend-audit-2026-11-02.md`](../docs/ops/backend-audit-2026-11-02.md)
  "Release standards" and "Private inventory" rule.

The live-AWS registry generator
[`scripts/ops/generate_backend_registry.py`](../scripts/ops/generate_backend_registry.py)
stays BLOCKED and is referenced, not run, here.
