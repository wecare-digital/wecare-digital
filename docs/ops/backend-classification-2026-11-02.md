# Backend handler classification (2026-11-02)

Offline, source-derived classification of the WECARE.DIGITAL backend. This
document is produced BEFORE any pipeline change, per the audit section 7 release
standards: every resource is labelled CDK/CloudFormation-owned or script-managed
from committed repository data, so that a later pipeline decision never runs a
Gen 2 deploy over a manually managed resource by accident.

It was built entirely from committed repository files. NO live AWS inventory was
enumerated: no account IDs, no ARNs, no IAM roles, and no live resource values
were read from AWS. The companion live-AWS registry generator
(`scripts/ops/generate_backend_registry.py`) stays blocked and was not run.

## Sources this classification was derived from

All of these are committed in the repository:

- `scripts/deploy_all_lambdas.py` (the authoritative `SPECS` table mapping a live
  function name to its handler source under `amplify/functions/**` plus packaging
  flags).
- `amplify/functions/**` (the full Python handler and shared-module tree).
- `config/lambda-env-manifest.json` (the recorded live function to env-key map;
  only KEY names are used, never the recorded values).
- `config/backend-retirement.json` (retired functions, routes, and tables, plus
  the one retained shared module).
- `amplify/backend.ts` (the Amplify Gen 2 CDK subset: auth, data, storage, SQS,
  CloudWatch, and the SEO resources).
- `infra/cloudwatch-retention-enforcer.yml` (a standalone CloudFormation stack).

The inventory generator `scripts/ops/build_handler_inventory.py` reproduces these
counts offline and writes its JSON report only to `.scratch/` (gitignored). That
report is an operational artifact and is never committed.

## The 318 versus roughly 76 relationship

`amplify/functions/**` holds 318 `.py` files, which is NOT the number of
standalone Lambdas. The breakdown, measured directly from the tree, is:

| Measure | Count | What it is |
| --- | --- | --- |
| Total `.py` files under `amplify/functions/**` | 318 | Every handler plus every shared module |
| `amplify/functions/shared/**` (lambda_utils) | 190 | Shared MODULES packaged INTO functions, not standalone Lambdas |
| `SPECS` entries in `deploy_all_lambdas.py` | 63 | Zip-packaged standalone Lambdas with a deploy mapping |
| Functions in `config/lambda-env-manifest.json` | 72 | Recorded live functions with env-key maps |

The large majority of the 318 files (190 under `shared/`) are the `lambda_utils`
package. `scripts/deploy_all_lambdas.py` copies `amplify/functions/shared/lambda_utils`
into every non-`standalone` function zip (see its `build_zip` routine), so these
files ship as dependencies of many Lambdas rather than as Lambdas themselves. The
inventory builder classifies all 190 as shared modules and emits zero standalone
handler entries for them.

The remaining gap between the 63 `SPECS` entries, the 72 manifest functions, and
any live count is expected drift. Some functions are deployed by dedicated scripts
or CloudFormation rather than by the `SPECS` map (see the `DELEGATED` and `SKIPPED`
tables in `scripts/deploy_all_lambdas.py`): examples include `wecare-seo-tools`
(`scripts/deploy_seo_tools.py`), `wecare-mcp` (`scripts/deploy_mcp_server.py`),
`wecare-workspace-mcp` and `wecare-customer-commerce-mcp` (CloudFormation), and
`wecare-docs-scraper` (an image-package function). A few `SPECS` entries also share
one source directory as a strangler pair, so the number of source directories is
smaller than the number of function names. One such pair is visible today:
`wecare-checkout` and `wecare-commerce` both package `ecommerce/checkout`.

Because of that strangler pair, the inventory reports two deliberately distinct
SPECS counts rather than one that could read as drift: `summary.specs_total_names`
is 63 (the count of distinct `SPECS` function names, which includes the
`wecare-commerce` alias held in `spec_aliases`), while
`summary.emitted_spec_mapped_handlers` is 62 (the count of emitted handler entries
that resolved to a `SPECS` source on disk). The difference of 1 is exactly
`summary.strangler_alias_specs`, not an unexplained gap. The legacy
`summary.specs_mapped_functions` field is kept as an alias of `specs_total_names`
for earlier consumers.

## CDK/CloudFormation-owned versus script-managed

Two ownership classes exist, and the distinction is about WHICH tool owns the
resource shell (function configuration, role, table, queue), not about who edits
the Python:

- cdk-cloudformation: the resource shell is declared in `amplify/backend.ts`
  (Amplify Gen 2 CDK) or in `infra/*.yml` (CloudFormation). A pipeline deploy of
  that stack is authoritative for these.
- script-managed: the function is created and updated by imperative `scripts/`
  tooling (the `SPECS` table in `deploy_all_lambdas.py`, or a dedicated
  `provision_*`/`deploy_*` script). A Gen 2 pipeline deploy must NOT be pointed at
  these, because it does not own them.

### CDK/CloudFormation-owned subset

From `amplify/backend.ts` (`defineBackend({ auth, data, storage })` plus
`addBackendResources` and `addSeoResources`):

| Resource group | Owner file | Notes |
| --- | --- | --- |
| Auth (Cognito user pool) | `amplify/backend.ts` via `amplify/auth/resource.ts` | Existing pool referenced with `referenceAuth` |
| Data (DynamoDB models via AppSync) | `amplify/backend.ts` via `amplify/data/resource.ts` | Roughly 58 models |
| Storage (S3 bucket) | `amplify/backend.ts` via `amplify/storage/resource.ts` | Existing bucket, gated and public prefixes |
| SQS queues (4) | `amplify/backend.ts` via `amplify/backend-resources.ts` | inbound-dlq, bulk-queue, bulk-dlq, outbound-dlq |
| CloudWatch alarms, dashboard, log retention | `amplify/backend.ts` via `amplify/backend-resources.ts` | Observability resources |
| SEO audit/log table plus Lambda | `amplify/backend.ts` via `amplify/seo-resources.ts` | Durable admin SEO storage and function |

Separately, `infra/cloudwatch-retention-enforcer.yml` is a standalone
CloudFormation stack (`wecare-cloudwatch-retention-enforcer`) that owns the
`wecare-log-retention-enforcer` function, its role, and its log group. This
function has no `handler.py` under `amplify/functions/` and no `SPECS` row, so the
inventory builder emits it as a synthetic entry (outside the handler walk) labelled
`cdk-cloudformation` with `cdk_source` set to `infra/cloudwatch-retention-enforcer.yml`.
That is the one `cdk-cloudformation` entry in the report
(`summary.cdk_cloudformation_functions` is 1), so the CDK/CloudFormation subset is
represented in the inventory rather than only described here.

### Script-managed standalone handlers by domain

Every entry below is a standalone handler whose shell is created and updated by
imperative `scripts/` tooling (the `SPECS` table or a dedicated provisioning
script), not by a Gen 2 or CloudFormation stack. Counts are the standalone
handlers the inventory builder resolved per domain from `SPECS`.

| Domain | Script-managed standalone handlers (from `SPECS`) |
| --- | --- |
| ai | `wecare-agent-action-group`, `wecare-ai-config-management`, `wecare-ai-query-kb` |
| auth | `wecare-cognito-custom-message`, `wecare-customer-profile`, `wecare-customer-registration`, `wecare-customer-whatsapp-auth`, `wecare-email-verification` |
| core | `wecare-auth-middleware`, `wecare-automation-rules`, `wecare-contacts`, `wecare-conversation-meta`, `wecare-crm`, `wecare-faq-handler`, `wecare-messages-delete`, `wecare-messages-read`, `wecare-secure-files`, `wecare-service-api`, `wecare-site-language`, `stack-wecare-url-shortener`, `wecare-vayulok-environment` |
| ecommerce | `wecare-catalog-management`, `wecare-checkout`, `wecare-commerce` (strangler alias sharing `ecommerce/checkout`), `wecare-customer-invoice`, `wecare-customer-orders`, `wecare-customer-session`, `wecare-product-image-gen`, `wecare-service-requests` |
| edge | none mapped by `SPECS` (edge holds a non-`SPECS` handler) |
| messaging | `wecare-inbound-whatsapp`, `wecare-outbound-whatsapp`, `wecare-whatsapp-voice`, `wecare-whatsapp-calling`, `wecare-whatsapp-template-management`, `wecare-whatsapp-business-api`, `wecare-waba-management`, `wecare-media-cleanup`, `wecare-template-analytics`, `wecare-partner-onboarding`, `wecare-partner-token-refresh`, `wecare-outbound-sms`, `wecare-outbound-email`, `wecare-sms-aws`, `wecare-voice-aws`, `wecare-voice-cdr-read`, `wecare-notification-worker`, `wecare-plivo-answer`, `wecare-pstn-softphone`, `wecare-rcs-send`, `wecare-rcs-dlr`, `wecare-push-notifications`, `wecare-scheduled-messages`, `wecare-marketing-ads`, `wecare-meta-business-agent` |
| operations | `wecare-billing`, `wecare-bulk-job-create`, `wecare-bulk-job-control`, `wecare-bulk-worker`, `wecare-dlq-replay`, `wecare-system-cleanup` |
| payments | `wecare-razorpay-webhook`, `wecare-payments-read`, `wecare-invoice-engine` |

Domains also contain handler directories that have no `SPECS` mapping because a
dedicated script or a CloudFormation stack owns them (for example the MCP and SEO
functions, and the image-package `wecare-docs-scraper`). Those are listed as
delegated in `scripts/deploy_all_lambdas.py`. The inventory builder does NOT
assert an ownership class for them: because several are CloudFormation-owned (the
MCP functions `wecare-workspace-mcp` and `wecare-customer-commerce-mcp`) or
image-package (`wecare-docs-scraper`), calling them script-managed would risk
authorizing the wrong deploy path later, which is exactly what audit section 7
guardrail 4 guards against. The builder therefore emits these eleven handlers
(`ai/customer-commerce-mcp`, `ai/mcp`, `ai/workspace-mcp`,
`ecommerce/catalog-media`, `ecommerce/native-catalog-admin`,
`edge/get-miss-redirect`, `operations/blog-auto-audit`, `operations/blog-public`,
`operations/docs-scraper`, `operations/seo-tools`,
`operations/whatsapp-analytics-export`) with `classification: "unclassified"` and
a null name, leaving the owning script or stack for code-review assignment during
reconciliation (mirroring the null fields the live registry generator leaves).

## Retired entries (not resurrected)

From `config/backend-retirement.json`. These are flagged as retired by the
inventory builder and are deliberately kept out of the active set:

- Retired functions: `wecare-ai-generate-response`, `wecare-meta-catalog-sync`.
- Retired routes: `GET /wa-business/catalog-sync`, `POST /wa-business/catalog-sync`.
- Retired table: `stack-wecare-digital-SmsOutboundTable`.
- Retained shared module (kept on purpose, not retired):
  `amplify/functions/shared/lambda_utils/ecommerce/meta_catalog_sync.py`.

The builder asserts that no retired function appears in any active domain list or
strangler alias, so a future edit that accidentally re-activated one would be
caught by the test suite.

## Guardrails honoured

- No live ARNs, account IDs, IAM policies, or secrets are enumerated or recorded
  in this document.
- Env data is referenced by KEY name only; recorded values from
  `config/lambda-env-manifest.json` are never copied here.
- Classification precedes any pipeline change, so the CDK/CloudFormation-owned
  subset and the script-managed subset are separated before a deploy decision.

## Phase 4 artifacts

This classification is one of three Phase 4 artifacts:

- `scripts/ops/build_handler_inventory.py` (the offline generator that reproduces
  these counts into a gitignored report).
- `docs/ops/backend-classification-2026-11-02.md` (this document).
- `architecture/phase4-backend-as-code-design-2026-11-02.md` (the target-state
  design, migration runbook, and the operator-only "BLOCKED on AWS access" list
  that builds on this classification).
