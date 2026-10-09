# Project completion and deep cleanup

Acceptance criteria (owner): "we will use root for the project now and comelet rest of the think make repo light + orginazsed inategrated and cdo deepl clean up".

Root use is directly authorized for this project as of 2026-10-09. Account775261844268, regionus-east-1, existing authentication. Preserve guards, foreign edits, provider credentials, customer/payment state, capability boundaries and retained artifacts. Do not infer product removal intent from root authorization.

| ID | Outcome | Owned paths / scope | Verification | Dependencies | Status |
|---|---|---|---|---|---|
| P1 | Apply two guarded customer log retention settings | Exact customer-profile/session CloudWatch groups; output retention evidence | Fresh identity, age/conflict guard, readback30days | None | done |
| P2 | Deploy source truth fixes without unrelated archive changes | Exact ai-config-management, ai-generate-response, invoice-engine deployed packages; scratch/outputs | Preserved archive diff, exact-package tests, revision/hash/version/alias guards, inert auth probes | P1 | in-progress |
| P3 | Resolve five substantive handler candidates | Exact template/customer-orders/customer-profile/service-api handler scopes; workspace MCP separately | Current archive, intent tests/dependency closure; no provider policy broadening | P2 | pending |
| P4 | Review lightweight organization and remove proven unused tracked artifacts | Worker proposes exact clean paths before edits; no foreign .gitignore/hooks/inventory/lock paths | Reference/runtime/package/build checks; file-by-file manifest | None | in-progress |
| P5 | Align project root authority and retention tooling | .kiro/steering/aws-agent-rules.md, new root-authority note, scripts/configure_customer_log_retention.py, tests/test_customer_log_retention.py | Account/root explicitopt-in guard tests; no global bypass | None | pending |
| P6 | Final dependency/infrastructure/contracts integration | Exact paths assigned only after evidence; no broad IAM revocation | Generated policy review, compatible advisory remediation, offline/provider contract checks | P2/P4 | pending |
| P7 | Run final gates and publish explicit-path commits/evidence | New scoped docs and source paths only | Git foreign hashes, tests appropriate to changes, current CI and deployed evidence | P2-P6 | pending |

Owner-only boundaries remaining: Wix12product removal intent; nominated QA recipient/live payment actions; definitive provider active/standby receipt typing contract; credential rotation. Continue unaffected work.
