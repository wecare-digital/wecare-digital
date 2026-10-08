# Reconciliation of pasted investigation, 7 October 2026

The owner supplied a prior Kiro investigation transcript covering public/workspace pages and AWS. Its investigation goals match PR #244. Recommendations and questions written by another assistant are research inputs, not authorization to delete infrastructure or change authentication. This addendum checks the material claims against current stack source and live AWS reads.

## What agrees

- 149 page patterns: 113 workspace and 36 public. No registered sidebar/settings destination points to a missing page. Repeated Inbox channel filters are one page, not separate route files. `tests/test_module_homes.py`: **31 passed**.
- Eight external-client SEO page patterns are configuration-blocked; the separate Cognito-authenticated `seo-tools` client exists. API availability does not certify every editorial action/provider read end to end.
- Common and WhatsApp inboxes are distinct large implementations with substantial shared functionality. Consolidation requires capability parity, redirects and an explicit canonical implementation.
- Current live infrastructure includes 74 functions, 374 routes, 67 `live` aliases and **73 metric alarms / 0 composite alarms**. Counts are a snapshot, not a source of truth for future work.

## Corrections to the pasted conclusions

| Pasted claim | Current evidence | Consequence |
|---|---|---|
| `wecare-service-requests` exists only in an isolated worktree and cannot be rebuilt | Current `origin/stack` is a82ff4c9. `git ls-tree` confirms `amplify/functions/ecommerce/service-requests/handler.py`; `scripts/deploy_all_lambdas.py:249–250` registers the function/source. | The source/deployment-registry gap is resolved. The **staff management UI gap** for the new service records remains. |
| Five working Blog Production pages are reachable only by typing URLs | `src/pages/workspace/seo/index.tsx:20–23` links production, review, QA and publish. Batch detail is contextual. These routes are absent from the central navigation registry, which affects palette discoverability. | Improve registry/search entry points; do not describe the whole workflow as unreachable or add every detail step to the sidebar. |
| Commerce, CTWA Ads, Internal Agent and Embedded Signup are stubs | Commerce calls deployed `/payments` and native commerce APIs; CTWA uses `marketingAdsApi`; Internal Agent uses authenticated `/ai/internal/config`; EmbeddedSignupPanel posts `/partners/embedded-signup`. | Classify as implemented/wired with runtime/provider-readiness checks outstanding. A blocked Meta grant is not proof of a missing backend. |
| `wecare-payments-read` is an orphan to retire | Live GET `/payments` and GET `/payments/{paymentId}` target it; `engage/commerce/index.tsx:112` calls `/payments`. CloudWatch records 3 invocations in the inspected seven days. | Preserve. Retirement would break an existing contract. Invocation count does not establish which caller produced those three events. |
| `wecare-faq-handler` can be retired with orphaned backends | Live GET `/faq` still targets it. Main staff FAQ UI uses the separate `/wa-business/faq` implementation. Zero invocations observed in the inspected seven days. | Legacy route/implementation candidate, not a proven safe deletion. FAQ data may be shared with active paths; never retire a shared table based on this observation. |
| `wecare-service-api` is unused | No current HTTP API route target was found, but it recorded 1 invocation in the inspected seven days. Duplicate-looking source alone does not identify that caller. | Candidate for indirect caller/event-source investigation. No deletion readiness established. |
| `wecare-crm` is fully orphaned with zero callers | Twelve routes remain deployed; no workspace CRM consumer was found in the source scan; no invocation datapoints were returned in the inspected seven days. Five-table emptiness was **not independently rechecked** here. | Backend-only/low-use candidate. Require data, indirect caller and dependency checks; decide whether the business needs a staff funnel. Preserve the deliberate removal of the public CRM route. |
| URL-shortener twin should be retired | Six link routes target `stack-wecare-url-shortener`, which recorded 141 invocations. `wecare-url-shortener` has no mapped gateway route and no invocation datapoints in this window. | Keep the active function. Inspect the unprefixed twin's other triggers/callers before retirement. |
| Both newly gated routes are JWT-protected | Actual totals: **372 NONE, 1 JWT, 1 AWS_IAM**. ANY `/workspace/mcp` uses `workspace-mcp-staff` JWT; POST `/workspace/mcp-iam` uses AWS_IAM. | Report each route's actual strategy. NONE does not imply missing handler auth or webhook signature checks. |
| Staff MFA OFF is an unmet target to fix automatically | Both pools currently report OFF. The owner explicitly requested password-only staff testing in this session. Customer pool retains DefineAuthChallenge, CreateAuthChallenge and VerifyAuthChallengeResponse. | Preserve the owner-authorized staff testing setting and customer WhatsApp OTP. Mark the security page's “Pool-level TOTP is on” docblock as stale; this is not authorization to enable MFA. |

## Invocation evidence

CloudWatch `AWS/Lambda`, `Invocations`, FunctionName dimension; UTC window **2026-09-30 02:46:17 to 2026-10-07 02:46:17**. Six GetMetricStatistics calls succeeded. Missing datapoints are reported as no observed invocations in this window, not lifetime non-use or proof of healthy operation.

| Function | Observed invocation sum | Current HTTP API target |
|---|---:|---|
| wecare-crm | 0; no datapoints | 12 routes |
| wecare-service-api | 1 | none found |
| wecare-faq-handler | 0; no datapoints | GET /faq |
| wecare-payments-read | 3 | 2 routes |
| wecare-url-shortener | 0; no datapoints | none found |
| stack-wecare-url-shortener | 141 | 6 routes |

Evidence is retained in `workspace-report-reconciliation-aws-20261007.json` and `workspace-retirement-candidates-20261007.json`. AWS API call records report zero failures. Scope remains account 775261844268/us-east-1. This addendum is not a new all-service IAM/security certification: event mappings, Function URLs, schedules, indirect invocation policies, all table contents and provider grants are not proven absent.

## Revised execution basis

1. Keep PR #244 as the audit/design review. Fix connection/error-state contracts and create the staff service-request management contract before reshaping those screens.
2. Register the Content/Blog Production entry in role-filtered discovery; keep batch/review/QA/publish as contextual resource workflow routes.
3. Consolidate inboxes only after feature parity; do not delete backend-wired pages because OAuth/provider access is blocked.
4. Keep payments and active short links. Treat CRM, standalone service API, legacy FAQ route and unprefixed short-link twin as **retirement candidates requiring evidence**, not approved deletions.
5. Keep staff password-only testing and customer WhatsApp OTP as explicitly requested. Correct outdated documentation and display real connection/feature states in the redesign.

No source behavior, tests, AWS resources, credentials, MFA configuration or providers were changed by this reconciliation. Only research documents/evidence and the review report were updated on the separate research branch.
