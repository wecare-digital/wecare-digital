# WECARE.DIGITAL 360° platform audit and lightweight-integration plan

**Audit date:** 28 October 2026  
**Repository:** `wecare-digital/wecare-digital`  
**Production branch audited:** `wecare.digital` at `bb4c310be4c2bc05a8c00fce6ad1c4e1a632699f`  
**AWS account/region sampled:** `775261844268` / `us-east-1`

## 1. Purpose

This audit looks at the platform as one system rather than as separate frontend, Lambda, or design tasks. It covers:

- customer experience and shared public UI;
- frontend architecture and bundle discipline;
- authentication and authorization;
- APIs, Lambdas, queues and event paths;
- persistence and data lifecycle;
- payment, invoice and WhatsApp paths;
- deployment, release and rollback;
- security and privacy;
- observability and operational ownership;
- repository weight, documentation and generated artifacts;
- mobile packaging;
- governance and change control.

The cleanup rule is conservative: **delete immediately only when the item is outside production, has no active verifier or runtime owner, and is superseded.** Live AWS resources are not deleted from visual similarity or naming alone.

## 2. Evidence snapshot

### Repository and build

- Next.js `16.4.2`, React `19.3.1`, TypeScript `6.0.3`, Node `>=24`, npm `11.6.2`.
- Capacitor Android and iOS dependencies and native directories are present; mobile support is active, not dead weight.
- Root GitHub Actions workflows and the old root test suite have been retired.
- Amplify remains the production frontend gate. Its build performs deterministic `npm ci`, TypeScript checking, the Next export, checkout release verification, FAQ consistency verification and public-bundle secret scanning.
- Amplify automatic builds are disabled; releases are explicitly started.
- Repository rulesets were removed. The production branch still reports as protected, but required status checks are off.

### Live AWS shape sampled during this audit

- **76** `wecare-*` Lambda functions.
- **7** HTTP APIs.
- **374** routes on the main `wecare-digital-api`, plus 41 routes across six MCP APIs.
- **76** DynamoDB tables in the WECARE namespace.
- One Amplify app and one production branch.

These counts show a broad, functional platform, but also a high operational surface. They are inventory facts, not a deletion list.

## 3. Executive scorecard

| Area | Rating | Audit view |
|---|---:|---|
| Public UX consistency | **B+** | `/auth` now renders inside the real shared public shell. Header, searchable navigation, cart, hero, Stay connected, footer and support/language widget are shared. |
| Frontend architecture | **B** | Public/authenticated bundles are intentionally separated and Amplify UI is lazy-loaded. The remaining concern is accumulated historical mock/document weight. |
| Customer authentication | **B+** | PKCE, CSRF, one-use records, KMS custody, Cognito validation, redirect allowlists and no-store/noindex headers are strong. A legacy backend-rendered `/auth` page still duplicates the React page and should be retired after compatibility verification. |
| API architecture | **C+** | 7 APIs and 415 total routes create ownership and drift risk. The main API contains 374 routes across many domains. |
| Lambda architecture | **C+** | 76 functions enable clear domain isolation but create deployment, IAM, version and observability overhead. Similar package sizes do not by themselves prove duplicates. |
| Data architecture | **C+** | 76 DynamoDB tables give strong domain separation but need a central owner/retention/TTL/PITR register before any consolidation. |
| Payments/invoices | **B** | Payment and invoice paths are explicit and receipt rendering is centralized. The live renderer changed during the audit, so visual sign-off must be tied to a specific deployed version. |
| WhatsApp/communications | **B-** | Functional breadth is high, but route/function/table count indicates several control planes and adapters that need an ownership map. |
| Security/privacy | **B-** | Auth controls and private invoice delivery are strong. All seven API Gateway default execute-api endpoints remain enabled; disable only after confirming every required custom-domain/direct-client dependency. |
| Release operations | **C+** | Frontend validation is strong once a build runs, but frontend and backend releases are split and there is no single release manifest joining commit, Lambda versions, API routes and Amplify job. |
| Automated quality | **C-** | Old CI loops and stale required checks are gone, but there is now no PR-level automated gate. The production Amplify build is the main executable gate. |
| Repository/governance | **C+** | The repo is active and documented, but documentation and mock history are spread across many files. No current ruleset means governance depends on operator discipline. |

## 4. What is already working well

### 4.1 Shared public composition

The correct architectural direction is now in place: `/auth` is a Next.js route wrapped by the same public shell as other public pages. Only the OTP card is auth-specific. This eliminates the visible menu/cart/footer drift that existed when the backend generated a copied page.

### 4.2 Frontend release gate

`amplify.yml` is stronger than a plain `npm run build`:

1. pins Node and npm;
2. uses `npm ci` against the committed lockfile;
3. runs `tsc --noEmit`;
4. generates and exports the Next site;
5. verifies checkout release output;
6. verifies FAQ synchronization;
7. scans the exported public bundle for server-side secrets.

This gate should remain.

### 4.3 Customer OAuth controls

The customer-commerce adapter uses:

- exact redirect registration;
- PKCE S256;
- scoped, resource-bound access tokens;
- one-use authorization codes and refresh records;
- KMS-encrypted Cognito custody;
- Cognito `GetUser` validation before authority is granted;
- strict return-path allowlisting;
- no-store, anti-framing and noindex response headers.

These are retention items, not cleanup targets.

## 5. Priority findings

### P0 — Restore a minimal change-quality contract without recreating CI loops

The old workflow/test deadlock is gone, but so is PR-level executable validation. Keep the repository lightweight by using one contract rather than many workflows:

- required local command: `npm run typecheck && npm run lint && npm run build`;
- production release gate: existing Amplify build plus release checks;
- pull-request checklist records the command result and the Amplify job used for production;
- do not recreate four payment-only required checks unless their workflows exist and are maintained.

### P1 — Retire the duplicate backend `/auth` page

The main website now owns `/auth`, but `customer_oauth.py`, the generated runtime and API Gateway still retain `GET /auth` and `POST /auth` plus a large copied header/menu/footer/form renderer.

Target state:

- Next.js owns `GET /auth` and all presentation;
- backend owns only `/auth/state`, `/auth/step`, `/oauth/authorize`, `/oauth/token` and `/oauth/revoke`;
- direct OAuth compatibility remains on `/oauth/authorize`;
- remove the backend form renderer, copied public shell, assets used only by it, and the two obsolete API routes;
- update `prepare_release.py` and OAuth verification before deployment.

This is the highest-value integration cleanup because it reduces code weight, UI drift and exposed route surface at once. It must be a separate compatibility-tested change, not mixed with document deletion.

### P1 — Build a single release manifest

Frontend, generated static pages, Python Lambdas and API routes are deployed through different mechanisms. Add one generated release manifest containing:

- Git commit;
- Amplify app/branch/job and result;
- Lambda name, published version, alias and code hash;
- API route count/hash;
- migration or table-schema change identifiers;
- verification timestamp and operator.

This prevents “website build succeeded” from being mistaken for “all backend changes deployed.”

### P1 — Usage-based AWS consolidation

Inventory size alone does not justify deletion. Before retiring a Lambda, route or table, require:

1. 30/90-day invocation or request metrics;
2. API/EventBridge/SQS/Lambda-invoke dependency map;
3. source/deploy owner;
4. data retention and rollback plan;
5. alias/version and IAM cleanup;
6. post-delete verification.

Likely consolidation reviews, not immediate deletions:

- commerce/checkout functions with identical package sizes;
- provider MCP functions that may share one framework but represent distinct credentials/scopes;
- the 374-route main API, which should be split or at least generated from domain-owned route manifests;
- tables that represent event/outbox/delivery stages and may intentionally be separate.

### P1 — Default API Gateway endpoints

Every sampled HTTP API had `disableExecuteApiEndpoint=false`. A direct execute-api endpoint can bypass custom-domain policy assumptions. For each API:

- identify direct clients and OAuth issuer/audience dependencies;
- verify custom domain coverage;
- then disable the default endpoint where no direct dependency remains.

Do not bulk-disable all seven without that compatibility check.

### P2 — Documentation and mock sprawl

The repository contains multiple generations of audits, visual alternatives and historical snapshots. They do not affect the deployed Next bundle, but they increase checkout/search/review noise.

Policy introduced by this cleanup:

- keep only canonical mocks that have an active browser verifier;
- keep one current 360° audit and an index to domain-specific audits;
- move superseded evidence to an archive only when it remains legally or operationally useful;
- do not commit one-off screenshots after a design decision is made;
- delete empty/orphaned Kiro spec metadata when the spec body is gone.

### P2 — Data governance register

Create one generated register for all 76 DynamoDB tables with:

- domain owner;
- keys and GSIs;
- producers/consumers;
- encryption/PITR/backup state;
- TTL attribute and retention rule;
- PII/payment classification;
- deletion/export procedure;
- last observed traffic.

No table should be deleted before that register is populated.

### P2 — Observability ownership

Standardize one structured envelope across APIs and workers:

- request/correlation ID;
- domain/action/outcome;
- latency and dependency status;
- redacted subject/customer identifiers;
- retryability classification;
- deployment version.

Create domain dashboards rather than one dashboard per Lambda.

## 6. Safe cleanup applied with this audit

The branch containing this report removes only non-production, superseded artifacts:

- an orphaned Kiro spec config whose specification files no longer exist;
- the unverified VayuLok app-shell prototype and its stale screenshot;
- earlier VayuLok gap, globe and hero exploration variants;
- two standalone WECARE globe alternatives.

Retained deliberately:

- `docs/mocks/home-hero/`;
- `docs/mocks/vayulok-live-mock.html`;
- `docs/mocks/vayulok-final-v3.html`;
- `tools/browser/vayuloksubcheck.js`, which actively verifies the two VayuLok canonical mocks;
- all production `src/`, mobile, backend, payment and infrastructure sources.

## 7. Do not delete without additional evidence

| Item | Why it stays |
|---|---|
| `bw-crm.md` | Large, but referenced by requirement, evidence and coverage documents. Removing it now would create broken governance references. |
| `@aws-amplify/ui-react` | Still used by authenticated UI and deliberately lazy-loaded. |
| `android/`, `ios/`, `native/` and Capacitor packages | Native packaging is present for both platforms. |
| `customer_oauth.py` security/session logic | Strong active auth implementation. Only its obsolete HTML presentation layer is a retirement candidate. |
| Any Lambda/API/table | No complete usage and dependency evidence was available in this audit. |
| Invoice/receipt history | Issued customer documents and rendering evidence can have legal and support value. |

## 8. Target architecture

### Presentation

- One public shell: Header/search/cart → page/hero → Stay connected → Footer → widget.
- One auth page component for phone and OTP states.
- No backend-generated public-site markup.

### Backend

- Domain route manifests generate API routes and deployment maps.
- Shared libraries own auth, identity, money, address and provider policies.
- Generated runtime files are verified against source and never edited manually.

### Release

- One release manifest links website and backend versions.
- One production verification report confirms routes, Lambda aliases, auth, payments and key public journeys.

### Repository

- Production source and live runbooks remain first-class.
- Canonical visual fixtures are tested.
- Historical experiments live outside the active tree or in a clearly labelled archive.

## 9. Recommended execution order

1. **Merge this safe repository cleanup.**
2. **Auth integration PR:** remove backend HTML `/auth` and the two obsolete API routes; run focused OAuth tests; deploy a new Lambda version; verify website and direct OAuth flows.
3. **Release-manifest PR:** generate and store a machine-readable deployment record.
4. **AWS usage audit:** collect 30/90-day metrics and dependency maps; produce a decommission candidate list.
5. **API consolidation:** domain route manifests and default-endpoint review.
6. **Data governance:** table owner/TTL/PITR/PII register.
7. **Documentation pass:** index current runbooks and archive superseded audits without breaking references.

## 10. Definition of done

The platform is “light and fully integrated” when:

- `/auth` has one presentation owner and no copied backend shell;
- every deployed function/route/table has an owner and measured use;
- frontend and backend releases are joined by one manifest;
- the active repository contains only production source, maintained runbooks and tested canonical fixtures;
- obsolete required checks and workflow loops do not return;
- a production build and focused backend verification can be tied to the exact commit and deployed versions;
- removal decisions are reversible and evidence-backed.
