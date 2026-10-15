# Required artifact index

`bw-crm.md` names a set of documents by exact filename. Several already existed under
different names, some are generated, and a few genuinely do not exist.

This index says which is which, so nobody hunts for a file that was never written and
nobody assumes a name implies content. It is a **map, not a second copy** — the brief
forbids maintaining two conflicting truths, so where content already lives somewhere
this points at it rather than duplicating it.

Last reconciled **2026-09-25**.

## Exists, and is generated

Regenerate rather than edit. Both derive from the live account plus the repository.

| Required name | State | Source of truth |
|---|---|---|
| `docs/service-implementation-matrix.md` | **generated** | `scripts/generate_service_matrix.py` ← `docs/execution/runtime-inventory.json` ← `scripts/generate_runtime_inventory.py`. 65 functions, 361 routes, the frontend-caller join, deploy owner per function |
| `docs/execution/runtime-inventory.md` / `.json` | **generated** | `scripts/generate_runtime_inventory.py` |

## Exists, written

| Required name | State |
|---|---|
| `docs/execution/requirement-registry.md` | 54 rows; the one place state changes |
| `docs/master-requirement-coverage.md` | reconciliation of the registry against the phase closure |
| `docs/execution/change-authority-matrix.md` | 277 entries |
| `docs/execution/evidence-index.md` | `EV-0001`…`EV-0041` |
| `docs/execution/dependency-graph.md`, `feature-flag-register.md`, `phase-XX-status.md` | present |
| `docs/kiro-handoff.md` | current position |
| `docs/frontend-route-retirement.md` | 23 Amplify rules, 18 of them 301, 4 probed live |
| `docs/prohibited-provider-retirement.md` | Sinch-SMS route retirement and orphaned integrations (appended by `scripts/retire_orphan_integrations.py`) |
| `docs/notification-retirement-manifest.md` | legacy notification domain |
| `docs/protected-resource-register.md` | protected Meta / Plivo / payment identifiers |

## Content exists under a different name

The brief's filename does not exist. The content does. Renaming would break inbound
links from the execution records for no gain, so these stay where they are.

| Required name | Where the content actually is |
|---|---|
| `docs/meta-whatsapp-audit.md` | `docs/meta-whatsapp/` — `FEATURE_BUILD_MATRIX.md`, `META_GATED_FEATURES.md`, `ENVIRONMENT_VARIABLES.md`, `SECURITY_CHECKLIST.md`, `LIVE_SMOKE_TEST_PLAN.md`; plus `docs/WHATSAPP_PLATFORM_MODULE_MAP.md`, `docs/WHATSAPP_FLOWS_IMPLEMENTATION.md`, `docs/WHATSAPP_TEMPLATE_BUILDER.md` |
| `docs/plivo-pstn-audit.md` | `docs/superpowers/specs/2026-09-19-plivo-pstn-browser-sdk-design.md`, plus `scripts/plivo-reconcile` and the `plivo-drift` / `plivo-verification` workflows |
| `docs/backend-function-data-map.md` | `docs/service-implementation-matrix.md` (generated) and `docs/BACKEND_FULL_AUDIT.md` |
| `docs/cleanup-and-storage-manifest.md` | `docs/AWS_CONSOLIDATION_AUDIT.md`, `docs/AWS_COST_CONTROL.md` |
| `docs/agent-tool-policy.md` | enforced in code: `governance.py` refuses 18 APPLY tools. The code is the policy; a prose copy would drift from it |

## Does not exist, and why

Naming these plainly is the point of this file. **None of them should be created as a
stub** — a document that looks like coverage but contains no measurement is worse than
its absence, because it stops the next person checking.

| Required name | Why not, and what it would take |
|---|---|
| `docs/plivo-documentation-coverage.md` | Requires actually crawling every page in the brief's Plivo queue and recording canonical URL, retrieval date, API version and per-page mapping. **That crawl has not been done.** Writing the file without it would be fabrication. The implementation-side facts live in the design spec above |
| `docs/meta-changelog-impact.md` | Same: needs the Graph API changelog reviewed release by release against this fleet. Not done |
| `docs/meta-mcp-capabilities.md`, `docs/mcp-capability-inventory.md` | Both require a **live MCP tool inventory**. Neither Meta MCP has ever authenticated: the owner must first add `http://localhost:7778/oauth/callback` and `http://localhost:7779/oauth/callback` to app `2238810740192680`. Razorpay MCP is blocked provider-side (`client_secret_post` only). So the tool lists cannot be discovered, and inventing them is exactly what the brief forbids |
| `docs/growth-integration-registry.md` | Partially blocked: 7 of 8 providers are `SCOPE_UNVERIFIED` pending owner access, so account ids, scopes and quotas cannot be read back. The fixture-driven contract tests (88) exist and pass; the registry would be mostly `WAITING_FOR_OWNER` rows |
| `docs/internal-chatbot-design.md`, `docs/wecare-operations-mcp.md`, `docs/connector-registry.md`, `docs/automation-workflows.md`, `docs/agent-client-compatibility.md` | The capability/tool/governance layer is implemented and tested, with every APPLY tool disabled. These design documents were never written. `agent-client-compatibility.md` in particular cannot be honest yet: it needs a real ChatGPT/Claude/Kiro round trip, and no remote MCP client has been connected |
| `docs/contacts-identity-audit.md` | Google People needs the owner's redirect URI plus `contacts.readonly` consent; Truecaller needs callback registration. Both `WAITING_FOR_OWNER`, so the per-page audit has no live account to audit |
| `docs/whatsapp-india-razorpay-audit.md` | The payment path is implemented and tested against fixtures with no live charge. The per-page documentation audit was not done, and the exposed Razorpay credential family remains `MANUAL_OWNER_ACTION` |
| `docs/screen-device-compatibility.md` | Requires a physical device matrix. Native packaging is **POST-PROJECT** by `00-current-owner-overrides.md`, so this is deferred by owner decision, not skipped |
| `docs/frontend-design-language.md` | Enforced by `check_design_drift.py` and `check_ui_labels.py`, both blocking. The prose document does not exist |
| `docs/plivo-documentation-coverage.md` companion (`docs/sdk-runtime-mcp-inventory.md`) | Same pattern: they are documentation-crawl deliverables, not implementation gaps |

## How to read this

The split matters. Everything in the first three sections is **evidenced**. Everything
in the last section is either a documentation-crawl task nobody has run, or blocked on
an owner action that is already listed in `docs/kiro-handoff.md`.

No row in the last section represents an unimplemented *feature*. The provider paths,
gates and governance they would describe are implemented, deployed and tested — what is
missing is the write-up.
