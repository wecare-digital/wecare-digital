# Phase 1 — discovery

Status: **🟡 IN PROGRESS** · Date: 2026-09-21
Entry gate: Phase 0 complete, security remediation live and verified.

## What is done

The joined runtime inventory the phase requires now exists and is **generated, not
written**: `scripts/generate_runtime_inventory.py` → `runtime-inventory.json` plus a
reviewable `runtime-inventory.md`. It joins, per function: source path, deploy-map
membership, runtime, package type, memory, timeout, code sha, layers, role, DLQ,
aliases, routes, integration qualifier, environment variable **names**, event source
mappings, log retention, and 24-hour and 7-day invocations and errors. Per route it
records api, route key, authorization type, target function and qualifier. Frontend
callers are joined by scanning `src/**/*.ts(x)` for each route path.

Regenerating is one command, which is the point: every count in this programme was
stale in the brief, and a hand-written inventory is stale the day after it is
written.

Three audits now cover the estate from different angles, each proven against a
seeded failure rather than assumed:

| Tool | Question it answers |
|---|---|
| `audit_route_auth.py` | does every route authenticate its caller? |
| `audit_data_model_drift.py` | does every table name in code exist? |
| `generate_runtime_inventory.py` | what is actually deployed, and what does not line up? |

## Measured state

| Metric | Value |
|---|---:|
| Lambda functions | 58 |
| with a `live` alias | 49 |
| HTTP APIs | 1 |
| Routes | 326 |
| DynamoDB tables | 66 |
| Routes OPEN at both layers | **0** |
| Routes to an absent function | **0** |
| Lambda errors, 7 days | **0** |
| Functions with zero invocations, 7 days | **0** |

## Findings

**`DEPLOY-003` — three functions serve routes with no `live` alias.**
`wecare-partner-onboarding` (21 routes), `wecare-marketing-ads` (2) and
`wecare-seo-tools` (2) account for all 25 unqualified integrations. This is not 25
defects; it is three functions that never adopted the publish-and-move-alias model,
and their routes necessarily point at `$LATEST`. Consequence:
`update-function-code` reaches production the instant it returns, with no published
version to roll back to and no staged step. `partner-onboarding` is the one that
matters most — it is the partner/tenant control plane, including billing top-up.

**`OPS-001` — nine log groups have no retention.** Unbounded cost, and unbounded
retention of whatever those logs contain. `plivo-answer` and `service-api` are on
that list.

**`OPS-002` — 95 route paths are mentioned by no frontend file.** Expected for
provider webhooks and internal-only routes, but it is also where dead surface
hides. Each needs a classification before any retirement decision, exactly as the
five dangling routes showed.

Two live functions sit outside the deploy map and both are documented exceptions:
`wecare-docs-scraper` is `PackageType=Image` shipped by GitHub Actions, and
`wecare-seo-tools` has its own deploy script. The generator annotates them as
expected so the anomaly list keeps its signal.

## Still to do in this phase

- Provider documentation queues: Plivo, Meta, Razorpay, Google, Bing, each
  with the per-page result fields the brief specifies.
- MCP schema inventory — both Meta servers remain unauthenticated pending the
  owner adding the OAuth redirect URIs.
- SDK and packaged-runtime matrix: declared vs lockfile vs what is actually inside
  each deployed artifact.
- Browser and device matrix.
- Cleanup dry-run with before/after byte measurements.
- `NOTIF-STORE-003`: whether the 65 declared Amplify models are deployed at all, or
  whether the live tables predate this Amplify app. Until that is settled,
  `amplify/data/resource.ts` is not a description of production.
- Triage the 48 Dependabot alerts now reported on the default branch (1 critical,
  26 high, 19 moderate, 2 low). The brief recorded Dependabot as unavailable, so
  this is new.
