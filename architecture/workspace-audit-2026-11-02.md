# WECARE.DIGITAL Workspace Audit (2026-11-02)

Scope: **everything in the workspace, audit only.** This document inventories every
subsystem, records measured health signals, identifies genuinely outdated versus
merely legacy-looking code and dependencies, and ends with a prioritized, phased
modernization plan. It makes **no code changes**: nothing was rebuilt, redeployed,
or refactored. Every finding below cites a concrete file, config, or command.

Branch audited: `wecare.digital` (the production branch; see Section 7). Node
present during the audit: v22.23.4. Repo requires Node `>=24` (`package.json`
`engines`, `.nvmrc`).

---

## 1. Executive summary

**The "mostly legacy and outdated" premise is only partly correct, and the evidence
contradicts it on the dependency axis.** The platform's runtime stack is current,
not legacy:

- **Next.js 16** (`next@^16.4.3`, `package.json`), **React 19** (`react@^19.3.1`),
  **TypeScript 6** (`typescript@6.0.3`; these are the toolchain's own current
  major version numbers as reported by `npm outdated`, i.e. `typescript 6.0.3 ->
  7.0.2`, not a typo), **Capacitor 8** (`@capacitor/core@^8.5.3`),
  **aws-amplify 6** (`aws-amplify@^6.22.2`), **Python 3.12** Lambda runtime.
- The React layer shows **no legacy patterns**: exactly **1** class component
  (`src/components/ErrorBoundary.tsx`, a legitimate error-boundary use) and
  **zero** `UNSAFE_`/`componentWill*` lifecycles across `src/**/*.tsx`.
- `npm outdated` shows only small gaps (one patch, two majors in the dev
  toolchain), not a stack frozen in the past.

What **is** real debt is **structural and organizational**, not version staleness:

1. A **7,827-line API god-module** (`src/api/client.ts`, ~300 request wrappers)
   plus a cluster of 1.7k-5.4k-line components.
2. **318 Python Lambda handlers** (`amplify/functions/**`) deployed **outside**
   infrastructure-as-code by ~260 imperative `scripts/` files, with no single
   reviewable source of truth and active manual-retirement work in flight.
3. **Thin automated test coverage** (4 JS test files; no in-repo Python unit
   tests) against a very large surface (350 `.ts/.tsx`, 546 `.py`).
4. **Multi-cloud sprawl** (AWS + a GCP Cloud Run service) and many bespoke
   guard/generator scripts that raise onboarding and bus-factor cost.

**Headline risks:** (a) backend configuration drift because the Lambda fleet is
script-deployed, not IaC-owned; (b) maintainability risk concentrated in a handful
of very large files; (c) a dev-toolchain security backlog (15 moderate advisories)
that is understood and mitigated but not yet cleared; (d) a local/CI Node version
mismatch (22 present vs `>=24` required).

**Genuinely outdated:** the ESLint/`typescript-eslint` dev chain (ESLint 9->10,
TypeScript 6->7 available) and the `eslint-config-next`/`next` 16.4.3->16.4.4 patch.
**Only *appears* legacy:** Next.js Pages Router (current on Next 16, deliberately
constrained by static `output: 'export'`); the `overrides`/guard-script machinery
(deliberate security mitigations, not accidental staleness); files mentioning
"legacy" (192 tracked files, per `git grep -li legacy`) that mostly describe
**retirement work already underway**, not unmanaged rot.

---

## 2. Subsystem inventory

### 2.1 Frontend (Next.js Pages Router, static export)
- `src/` totals: **69** top-level component dirs under `src/components`, **56**
  page files under `src/pages` (`find src/pages -name '*.tsx'`), **48** modules
  under `src/lib`, **2** files under `src/api`.
- **Pages Router confirmed**: `src/pages/_app.tsx` and `src/pages/_document.tsx`
  exist (not an `app/` directory). Build is a **static export** (`output: 'export'`
  in `next.config.js`), wrapped as iOS/Android via Capacitor.
- **API monolith**: `src/api/client.ts` = **7,827 lines** (`wc -l`), ~300 request
  wrappers; all frontend API access funnels through it.

### 2.2 Amplify Gen 2 definition (IaC subset)
- `amplify/backend.ts`, `amplify/backend-resources.ts`, `amplify/catalog-resources.ts`.
- `amplify/data/resource.ts` = **1,604 lines** (`wc -l`), ~58 DynamoDB table models.
- `amplify/auth/resource.ts` (Cognito). This Gen 2 definition owns the data/auth
  layer; it does **not** own the 318 handlers below.

### 2.3 Python Lambda fleet (deployed OUTSIDE Amplify)
- **318** `.py` handlers under `amplify/functions/**`
  (`find amplify/functions -name '*.py' | wc -l`), organized by domain:
  `ai/`, `auth/`, `core/`, `ecommerce/`, `edge/`, `messaging/`, plus shared
  `lambda_utils/`. Runtime: **python3.12**.
- Deployed by **imperative scripts**, not by the Amplify pipeline. The live
  deployed footprint differs from the repo count: `docs/ops/backend-audit-2026-11-02.md`
  reports **76 Lambdas and 77 DynamoDB tables** in `us-east-1` after recent
  retirement. The gap between 318 repo handlers and 76 live functions is itself a
  drift/inventory signal (see Section 5d).

### 2.4 Ops, build, and guard scripts
- `scripts/` holds ~260 files: Python `provision_*/audit_*/check_*/verify_*/reconcile_*`
  runtime probes, `.cjs` guards, and `.js` build generators. Repo total Python =
  **546** files (`.py`), total TypeScript = **350** files (`.ts/.tsx`).
- Build chains six generators (`package.json` `build`): `generate-public-pages.js`,
  `generate-vendor-css.js`, `next build`, `generate-sitemap.js`,
  `generate-blog-search-index.js`, `generate-blog-rss.js`, `generate-llms-txt.js`.
- Lifecycle guards (`package.json` `postinstall`/`prebuild`): `guard_braces_depth.cjs`,
  `guard_minimatch_preprocess.cjs`, `check-retired-public-pages.cjs`,
  `check_minimatch_preprocess.cjs` - these MUST pass.

### 2.5 Capacitor mobile
- `capacitor.config.ts`, `capacitor.public.config.ts`, and `android/`, `ios/`,
  `native/` directories. App id/name set via `cap:init` (`"Stack CRM"`,
  `digital.wecare.stackcrm`, web dir `out`).

### 2.6 Infra / deploy descriptors
- `amplify.yml`, `customHttp.yml`, `_routes.json` (331 lines),
  `infra/cloudwatch-retention-enforcer.yml` (CloudFormation stack
  `wecare-cloudwatch-retention-enforcer`).

### 2.7 GCP Cloud Run (secondary cloud)
- `gcp/vayulok-weather-insights/` with its own `Dockerfile` (`FROM node:24-alpine`).
  A second cloud provider outside the primary AWS footprint.

### 2.8 Tooling and config
- `tools/audit/*` (audit JS), `tools/customer-commerce/*` (Python).
- `config/lambda-env-manifest.json` (~28KB), `config/public-pages.json`,
  `config/backend-retirement.json`, `config/vendor-versions.json`,
  `config/workspace-mcp` JSON.

### 2.9 Two independent npm install roots (by design)
- **Root** `package.json` and **`amplify/package.json`** are separate install
  roots on purpose. `amplify/package.json`'s own description states OpenTelemetry
  version skew makes a unified lockfile un-CI-able. `docs/ops/dependency-mitigations-2026-11-02.txt`
  requires **both** roots be installed sequentially for the minimatch behavior
  check to cover both trees. The `amplify/` root was **not** installed for this
  audit (not needed for the report; its `npm ci` is known-problematic).

---

## 3. Measured health baseline

All commands were run from the repo root during this audit and confirmed the
pre-captured baseline. Raw summaries are in the Appendix (Section 8).

| Check | Command | Result | Severity |
|---|---|---|---|
| Typecheck | `npx tsc --noEmit` | **0 errors** (exit 0) | PASS |
| Lint | `npx eslint .` | **0 errors, 218 warnings** | PASS (warnings advisory) |
| Tests | `npm test` (`node --test "tests/**/*.test.mjs"`) | **26 pass / 0 fail** (4 files) | PASS |
| Install engine | `npm ci` | **EBADENGINE** (Node 22.23.4 vs `>=24`) | Low (non-fatal warning) |
| Peer deps | install resolution | `@xstate/react` peer conflict (wants React 16-18) | Low (transitive, pinned) |

**Lint warnings (218) are intentional.** `eslint.config.mjs` downgrades
`react-hooks/set-state-in-effect` to `'warn'` in the `wecare/react-compiler-advisory`
block (line 122). The inline rationale (lines 69-128) explains this rule belongs
to the **React Compiler** family and is advisory *in this codebase* because the
repo does not yet run the compiler; the comment states the block "should be deleted
rather than extended" once the compiler is enabled - i.e. **enabling React Compiler
is the condition that would flip these 218 warnings toward errors.** The measured
count is deterministic: the comment notes "removing the probes restored 0 errors /
182 warnings exactly" (line 51), and the current full-repo run is 0 errors / 218
warnings.

**EBADENGINE** is a warning, not a failure: `npm ci` still succeeds. The repo
requires Node `>=24` (`package.json` `engines`, `.nvmrc`); the audit host had
v22.23.4. CI runs on Node 24 (`.github/workflows/ci.yml`), so this is a
**local-environment** gap only.

**`@xstate/react` peer conflict**: pulled transitively via
`@aws-amplify/ui-react@^6.15.7`; it declares a React 16-18 peer range while the repo
is React 19. It resolves (pinned/deduped) and does not break typecheck, lint, or
tests. Track upstream rather than force-resolving.

---

## 4. Dependency findings

### 4a. `npm outdated` (root)
```
Package             Current  Wanted   Latest
eslint               9.39.5  9.39.5  10.14.0
eslint-config-next   16.4.3  16.4.4   16.4.4
next                 16.4.3  16.4.4   16.4.4
typescript            6.0.3   6.0.3    7.0.2
```
Only four packages drift: a **patch** available for `next`/`eslint-config-next`
(16.4.3->16.4.4) and two **major** dev-toolchain bumps (`eslint` 9->10,
`typescript` 6->7). The runtime stack (React, Amplify, Capacitor) is current.

### 4b. `npm audit` - 15 moderate, 0 high, 0 critical
`npm audit --json` metadata: `{info:0, low:0, moderate:15, high:0, critical:0,
total:15}`. **Every** advisory is in the **ESLint / typescript-eslint / minimatch
dev toolchain chain**, none in runtime code. The affected packages:
`eslint`, `@typescript-eslint/eslint-plugin`, `@typescript-eslint/parser`,
`@typescript-eslint/type-utils`, `@typescript-eslint/utils`, `typescript-eslint`,
`eslint-plugin-import`, `eslint-plugin-react`, `eslint-plugin-jsx-a11y`,
`@next/eslint-plugin-next`, `eslint-config-next`, `@eslint/config-array`,
`@eslint/eslintrc`, `@eslint-community/eslint-utils`, `minimatch`.

Per `docs/ops/dependency-mitigations-2026-11-02.txt`, the governing policy is:
**do not suppress/dismiss scanner alerts or claim `npm audit` is clean.** This
report honors that - the 15 moderate findings are reported as live, not resolved.

### 4c. Intentional `overrides` + guard scripts (deliberate mitigation)
Root `package.json` `overrides` pin: `lodash 4.18.1`, `fast-xml-parser 5.11.1`,
`immutable@3 3.8.4`, `mysql2 3.24.4`, `csv-parse 7.0.2`, `xcode>uuid 11.1.1`,
`glob@>=9 <14.0.2 -> 14.0.2`, `minimatch@>=9 -> 11.0.4`. The `amplify/` root adds
further pins (e.g. `handlebars`, `@graphql-tools/utils`).

Why they exist (`docs/ops/dependency-mitigations-2026-11-02.txt`): they address
**GHSA-g3hv-75wg-m249** (minimatch) and **GHSA-3g3m-2fjr-6pw4** (glob) in the
*replaceable* dependency paths. But `aws-cdk-lib 2.274.0` **bundles** minimatch
10.2.6, which npm `overrides` cannot reach; CDK 2.275.0 still declares `^10.2.6`,
so upgrading CDK does not fix it. `scripts/guard_minimatch_preprocess.cjs`
backports the maintainer's expansion-bound and large-set cutoff into the bundled
CommonJS/ESM copies, validating pristine source hashes and supporting `--check`.
A parallel `guard_braces_depth.cjs` applies the same convention for braces.

**These overrides and guards are deliberate risk mitigations, not accidental
staleness.** They must be preserved until the root causes are upstream-fixed
(Section 7). The doc also warns the backend install tree still reports ELSPROBLEMS
around bundled `archiver-utils`/`readdir-glob` and overridden glob ranges, so the
backend tree must **not** be described as warning-free.

### 4d. Python dependencies
`requirements-dev.txt` is a full freeze for the **dev venv only**; it explicitly
does **not** define the Lambda runtime. Lambda runtime dependencies come from the
`python3.12` runtime (boto3 provided) plus Lambda layers. So there is no single
checked-in manifest that pins the handlers' production dependency set - a gap for
reproducibility (feeds Section 5d/Phase 4).

---

## 5. Legacy / structural debt findings

### 5a. Pages Router on Next 16 (forward-looking, not a defect)
`src/pages/_app.tsx` + `_document.tsx` confirm the **Pages Router**. The ecosystem
default is now the App Router, but Pages Router remains fully supported on Next 16,
and the static `output: 'export'` (`next.config.js`) plus Capacitor packaging
**constrain** App Router adoption. This is a strategic migration *consideration*,
not current breakage.

### 5b. Oversized files (maintainability risk)
Confirmed by `wc -l`:
- `src/api/client.ts` - **7,827**
- `src/components/VayuLokLive.tsx` - **5,444**
- `src/components/workspace/whatsapp/templates.tsx` - **2,217**
- `src/components/cart/CartPage.tsx` - **2,212**
- `src/components/workspace/whatsapp/calling.tsx` - **2,169**
- `src/pages/workspace/customers/index.tsx` - **1,959**
- `src/pages/workspace/engage/inbox/index.tsx` - **1,867**
- `src/components/TemplateSender.tsx` - **1,763**
- `src/components/workspace/pay/PayFlow.tsx` - **1,743**
- `src/components/workspace/platform/SystemArchitecture.tsx` - **1,715**

These concentrate change risk and slow review; they are the prime decomposition
targets (Phase 3).

### 5c. `: any` usage
**94** source files under `src/` contain `: any`
(`grep -rl ": any" src --include=*.ts --include=*.tsx | wc -l`). Not a failure
(typecheck passes), but each `: any` is a type-safety escape hatch to tighten.

### 5d. 318 Lambdas deployed outside IaC (drift risk)
The handler fleet is deployed by imperative `scripts/` rather than through
reviewable IaC, so there is **no single source of truth** for what is live.
`docs/ops/backend-audit-2026-11-02.md` documents **active manual retirement**
(76 live Lambdas / 77 tables after cleanup) and `config/backend-retirement.json`
lists exactly what was retired:
- Retired functions: `wecare-ai-generate-response`, `wecare-meta-catalog-sync`.
- Retired routes: `GET`/`POST /wa-business/catalog-sync`.
- Retired table: `stack-wecare-digital-SmsOutboundTable`.
- Retained shared module: `amplify/functions/shared/lambda_utils/ecommerce/meta_catalog_sync.py`
  (native basket parsing/checkout analytics still depend on its retailer-ID contract).

The 318-vs-76 gap is the drift signal: repo handlers are not one-to-one with live
functions, and reconciliation is manual.

### 5e. Thin automated test coverage
Only **4** JS test files exist (`tests/elsewhere-travel`, `tests/rcs-send`,
`tests/smoke`, `tests/whatsapp-analytics`) via `tests/helpers/loadTsx.mjs`; 26
assertions total. There are **no in-repo Python unit tests** - the `scripts/`
`check_*/audit_*/verify_*` files are runtime probes, not unit tests. Coverage is
thin relative to 350 `.ts/.tsx` + 546 `.py` files.

### 5f. Multi-cloud + bespoke scripting (bus-factor cost)
AWS (Amplify + 318 script-deployed Lambdas) plus a GCP Cloud Run service
(`gcp/vayulok-weather-insights`), plus ~260 custom ops/guard/generator scripts,
raise onboarding cost and concentrate operational knowledge.

### 5g. "Retirement in progress" theme
**192** tracked files mention "legacy"
(`git grep -li legacy | wc -l`; a narrower `git grep -li legacy -- 'src/**/*.ts'
'src/**/*.tsx' | wc -l` scopes it to **47** TypeScript sources). Most describe
**managed retirement**, not rot: `config/backend-retirement.json`,
`scripts/check-retired-public-pages.cjs`, and the retirement narrative in
`docs/ops/backend-audit-2026-11-02.md` (Meta Commerce catalog sync + AI generation
Lambdas/routes + `SmsOutboundTable`). Surfacing *what* is retired matters so the
rebuild does not resurrect it.

### 5h. The React layer itself is NOT legacy
Exactly **1** class component (`src/components/ErrorBoundary.tsx`, a valid
error-boundary pattern React still requires as a class) and **zero**
`UNSAFE_`/`componentWill*` lifecycles across `src/**/*.tsx`. React 19 + hooks
throughout. Do not treat the React code as legacy; it is current.

---

## 6. Prioritized modernization plan (phased)

Ordering principle: **dependencies and hygiene first**, then safety nets (tests),
then structural refactors that those safety nets protect, then the highest-risk
backend/strategic moves. Items requiring cloud access this audit did not have are
flagged **[BLOCKED: AWS/GCP access]**.

### Phase 0 - Hygiene (low risk)
**Goal:** remove noise and version drift that costs nothing to fix.
- Align local/dev Node to **24** to clear the `EBADENGINE` warning (`.nvmrc`
  already pins it; only the local host was behind). First step: install Node 24
  locally / in devcontainers; re-run `npm ci`.
- Apply the **`eslint-config-next`/`next` 16.4.3 -> 16.4.4** patch (`npm outdated`).
  Low risk (patch release); re-run `npm run typecheck && npm run lint && npm test`.
- Document the **`@xstate/react` React-19 peer conflict** and open a tracking note
  against `@aws-amplify/ui-react`; do not force-resolve.
**Risk:** Low. **Why first:** removes false signals before any structural change.

### Phase 1 - Toolchain + security (low/medium risk)
**Goal:** clear the 15 moderate dev-chain advisories (Section 4b) without weakening
the minimatch/braces mitigations.
- Plan the **ESLint 9->10** and **typescript-eslint major** bumps (and evaluate
  **TypeScript 6->7**) in a branch; expect flat-config and rule changes.
- **Keep** the `overrides` and `guard_minimatch_preprocess.cjs` /
  `guard_braces_depth.cjs` scripts intact; re-run
  `node scripts/guard_minimatch_preprocess.cjs --check` and
  `node scripts/check_minimatch_preprocess.cjs` after upgrading.
- **Re-measure** `npm audit` afterward; report residual advisories honestly (do
  not declare clean - Section 7).
**Risk:** Medium (major bumps can shift lint results). **Why second:** a clean,
modern toolchain underpins every later refactor.

### Phase 2 - Test + CI depth (medium risk)
**Goal:** build the safety net before refactoring large files.
- Add unit tests around `src/api/client.ts` wrappers (start with the modules
  touched most) and the critical Python handlers (payment, auth, WhatsApp).
- Introduce a **Python unit-test harness** (none exists today) for
  `amplify/functions/**` shared utils.
- Keep the **production-data-safety guard**
  (`scripts/check_production_data_safety.cjs`, run in CI).
**Risk:** Medium (new infra, no behavior change). **Why third:** Phases 3-4 are
far safer with coverage in place.

### Phase 3 - Frontend structural (medium/high risk)
**Goal:** reduce maintainability risk in the largest files (Section 5b).
- Decompose `src/api/client.ts` (7,827 L) into domain modules
  (messaging / commerce / auth / crm) behind a stable export surface.
- Split the 1.7k-5.4k-line components (`VayuLokLive.tsx`,
  `whatsapp/templates.tsx`, `cart/CartPage.tsx`, `whatsapp/calling.tsx`,
  `workspace/customers/index.tsx`, `engage/inbox/index.tsx`).
- Incrementally reduce `: any` (94 files) as modules are touched.
**Risk:** Medium/High (broad surface). **Why fourth:** depends on Phase 2 tests.

### Phase 4 - Backend as code (high risk) **[BLOCKED: AWS access]**
**Goal:** kill drift by bringing the 318 script-deployed Lambdas under reviewable
IaC / a single inventory source.
- Classify each resource as **CDK/CloudFormation vs script-managed** (per
  `docs/ops/backend-audit-2026-11-02.md` release standards) before changing any
  pipeline.
- Generate the private inventory with
  `scripts/ops/generate_backend_registry.py --expected-account <ACCOUNT_ID>` into a
  restricted, encrypted location (never committed - Section 7), and reconcile the
  318-vs-76 gap.
**Risk:** High. **Blocked:** requires live AWS credentials/deploy access not
available to this audit. Do **not** run Gen2 pipeline-deploy over
manually-managed resources.

### Phase 5 - Strategic (evaluate only)
**Goal:** decide direction, do not commit yet.
- Evaluate (not commit to) an **App Router** migration, accounting for the static
  `output: 'export'` + Capacitor constraint (Section 5a).
- Evaluate **multi-cloud consolidation** of `gcp/vayulok-weather-insights`
  **[BLOCKED: GCP access]** against the AWS footprint.
**Risk:** Strategic. **Why last:** largest blast radius; depends on everything above.

---

## 7. Constraints & guardrails for any future rebuild

1. **Production branch is `wecare.digital`, NOT `stack`.** Older runbooks naming
   `stack` are stale. Source: `docs/ops/backend-audit-2026-11-02.md` ("Production
   remains on `wecare.digital`"); confirmed by `git branch --show-current`.
2. **Never commit AWS/ARN/IAM inventory to this PUBLIC repo.** Generate locally,
   redirect to a restricted encrypted location. Source:
   `docs/ops/backend-audit-2026-11-02.md` ("Private inventory"). This report
   contains no account IDs, ARNs, or IAM secrets beyond what is already committed.
3. **Do not suppress/dismiss scanner alerts or declare `npm audit` clean.** The 15
   moderate advisories stay visible. Source:
   `docs/ops/dependency-mitigations-2026-11-02.txt`.
4. **Do not run Gen2 pipeline-deploy over manually-managed resources.** Classify
   each resource first. Source: `docs/ops/backend-audit-2026-11-02.md` ("Release
   standards").
5. **Preserve the braces/minimatch guard scripts** (`guard_braces_depth.cjs`,
   `guard_minimatch_preprocess.cjs`) and the `overrides` until root causes are
   upstream-fixed. Source: `docs/ops/dependency-mitigations-2026-11-02.txt`,
   `package.json` lifecycle hooks.
6. **The two npm install roots (root + `amplify/`) must stay separate.** A unified
   lockfile is un-CI-able due to OpenTelemetry skew. Source: `amplify/package.json`
   description; `docs/ops/dependency-mitigations-2026-11-02.txt`.

---

## 8. Appendix - commands and raw summaries

Commands run from repo root on 2026-11-02 (Node v22.23.4):

```
$ npx tsc --noEmit
# (no output) exit 0  => 0 type errors

$ npx eslint .
✖ 218 problems (0 errors, 218 warnings)
  0 errors and 4 warnings potentially fixable with the `--fix` option.
# exit 0

$ npm test            # node --test "tests/**/*.test.mjs"
# tests 26
# pass 26
# fail 0
# duration_ms ~222

$ npm audit --json  (metadata.vulnerabilities)
{info:0, low:0, moderate:15, high:0, critical:0, total:15}
# advisory packages: eslint, @typescript-eslint/{eslint-plugin,parser,type-utils,utils},
#   typescript-eslint, eslint-plugin-{import,react,jsx-a11y}, @next/eslint-plugin-next,
#   eslint-config-next, @eslint/{config-array,eslintrc}, @eslint-community/eslint-utils, minimatch

$ npm outdated
Package             Current  Wanted   Latest
eslint               9.39.5  9.39.5  10.14.0
eslint-config-next   16.4.3  16.4.4   16.4.4
next                 16.4.3  16.4.4   16.4.4
typescript            6.0.3   6.0.3    7.0.2

$ wc -l (selected)
7827 src/api/client.ts
5444 src/components/VayuLokLive.tsx
2217 src/components/workspace/whatsapp/templates.tsx
2212 src/components/cart/CartPage.tsx
1604 amplify/data/resource.ts

$ find/grep counts
318  amplify/functions/**/*.py     (Lambda handlers)
546  *.py total (repo, excl node_modules)
350  *.ts/*.tsx total (repo, excl node_modules)
 94  src/ files containing ": any"
192  tracked files mentioning "legacy"  (git grep -li legacy | wc -l)
 47  of those scoped to src/**/*.ts(x)  (git grep -li legacy -- 'src/**/*.ts' 'src/**/*.tsx' | wc -l)
  1  class component (src/components/ErrorBoundary.tsx)
  0  UNSAFE_/componentWill* lifecycles
```

### What could NOT be verified (and why)
- **Live AWS 318-Lambda inventory** - no AWS credentials/deploy access in this
  audit; and committing that inventory to this public repo is forbidden (Section 7).
  The 76-live figure is quoted from `docs/ops/backend-audit-2026-11-02.md`, not
  re-measured here.
- **`amplify/` second install root** - intentionally not installed; its `npm ci`
  is known-problematic per its own `package.json` and the mitigations doc. The
  behavior check that needs both trees was therefore not run.
- **Actual `next build`** - skipped by design (audit-only; build is heavy and
  requires network + the six generators). Typecheck/lint/test stand in as cheap
  health signals.
- **GCP Cloud Run service** (`gcp/vayulok-weather-insights`) - no GCP access; only
  its source `Dockerfile` (`FROM node:24-alpine`) was inspected statically.

---

*Audit only. No source code, config, or infrastructure was modified to produce
this report. The sole new artifact is this file.*
