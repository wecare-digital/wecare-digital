# Phase 3 frontend decomposition (2026-11-02)

This note records the Phase 3 structural refactor of the frontend: splitting the
monolithic `src/api/client.ts` into a shared core plus domain modules behind a
stable re-export barrel, and splitting the two largest UI components into
co-located sibling modules. This was a **pure structural refactor with no
behaviour change**: code was moved verbatim (same bodies, signatures, names, and
comments) and only import/export wiring was adjusted. No runtime behaviour, no
Lambda packaging, and no deploy config was touched.

## 1. New `src/api` module layout

`src/api/client.ts` was 7,827 lines holding the shared failure-classification
engine, the pure normalizers, and ~30 section-bannered groups of request
wrappers. It is now a 32-line re-export barrel. The implementation moved to a
shared core module plus six domain modules.

### `src/api/core.ts` (488 lines)

The shared core engine moved here verbatim: connection-status helpers, the
`ApiFailureKind` / `ApiFailure` / `ApiResult` types, `RETRYABLE_KINDS`,
`lastApiFailure` / `getLastApiFailure`, the failure listeners and `recordFailure`,
`collectApiFailures`, `delay`, `getAuthToken`, `authFetch`, `verifyAdminAccess`,
`apiCall`, `apiCallResult`, and `testConnection`. Three shared declarations were
relocated here so every domain module can import them from one source:

- the `WA_BIZ_BASE` const,
- the `CheckoutDeliveryAddress` interface,
- the three pure normalizers (`normalizeCheckoutAddress`, `normalizeEpochSeconds`,
  `normalizeTimestamp`).

The core import header was trimmed to what it actually uses; imports consumed only
by code that moved into the domain modules were dropped from core. The
`RETRYABLE_KINDS`..`apiCallResult` span stays contiguous and intact (see the
test-coupling section).

### `src/api/domains/*.ts`

Each ~30 section-bannered wrapper group was moved verbatim into one of six domain
modules, grouped by contiguous banner ranges so the moves stay verbatim and the
dependency graph stays acyclic (`contacts` and `messaging` have no back-edges;
other modules import the handful of wrappers/types they reuse via explicit
imports).

| Domain module | Lines | Section banners landed in this module |
| --- | ---: | --- |
| `domains/contacts.ts` | 494 | CONTACTS, CONSENT EVIDENCE |
| `domains/messaging.ts` | 621 | MESSAGES, CAROUSEL TEMPLATE, BULK JOBS |
| `domains/telephony.ts` | 765 | AI AUTOMATION, SYSTEM HEALTH, VOICE CALLS, SMS AWS, SMS SENDING, SINCH RCS, VOICE AWS, WHATSAPP VOICE, DLQ, AWS BILLING, ADVANCED DELETE |
| `domains/whatsapp.ts` | 2,336 | WHATSAPP TEMPLATES, WABA MANAGEMENT, TEMPLATE MANAGEMENT, CORS, AI CONFIG, WABA ADVANCED, WABA SNS SUBSCRIPTION, WABA PHONE MIGRATION, TEMPLATE ANALYTICS, SCHEDULED MESSAGES, SEND CAROUSEL, WHATSAPP BUSINESS |
| `domains/commerce.ts` | 1,920 | INVOICE, REFUND INITIATION, SYSTEM CLEANUP, SUBMIT REQUESTS, FLOW MANAGEMENT ENGINE, ORDERS, DOCUMENTS, FAQ, APPOINTMENTS, SEHAT APPOINTMENTS, ENTERPRISE ASSIST, REVIEWS, SERVICE REQUEST |
| `domains/platform.ts` | 1,252 | AUTOMATION RULES, CONVERSATION META, WA GRAPH ADMIN, MARKETING ADS, CONVERSIONS API (CAPI) |

Cross-module references are satisfied with explicit imports: `telephony` imports
`deleteMessage` / `listMessages` from `messaging` and `deleteContact` from
`contacts`; `whatsapp` imports `createContact` / `listContacts` / `updateContact`
plus `type Contact` from `contacts` and `type Message` from `messaging`;
`commerce` imports `WA_BIZ_BASE` from `core`. `contacts` and `messaging` have no
back-edges, so the module graph is acyclic.

### `src/api/client.ts` (32-line barrel)

`client.ts` remains the single public entry point. It explicitly re-exports the
previously-public core names (`getConnectionStatus`, `getLastApiFailure`,
`collectApiFailures`, `authFetch`, `verifyAdminAccess`, `apiCallResult`,
`testConnection`) and the public types (`ApiFailureKind`, `ApiFailure`,
`ApiResult`, `CheckoutDeliveryAddress`) from `./core`, then `export *` from each of
the six domain modules. Internal-only helpers (`apiCall`, `delay`, `getAuthToken`,
`recordFailure`, `WA_BIZ_BASE`) stay internal to `./core` and are deliberately
**not** re-exported, so the public surface is unchanged.

## 2. Stable-export strategy

The decomposition is invisible to callers. `client.ts` re-exports the entire
previous public surface, so all **85 import sites** (mostly
`import * as api from '.../api/client'` and `import type {...} from '.../api/client'`)
resolve unchanged — no importer was edited.

The export surface was verified with the TypeScript checker's
`getExportsOfModule` on `src/api/client.ts`, comparing HEAD (before) to the
refactored tree (after):

| Export surface | Count |
| --- | ---: |
| Exports before | 546 |
| Exports after | 546 |
| Added | 0 |
| Removed | 0 |
| Renamed | 0 |

A clean typecheck against a byte-identical export set is the core correctness
signal for this refactor.

## 3. Phase 2 test-coupling resolution

The Phase 2 safety-net tests for `client.ts` use an extract-and-run-in-vm idiom:
they read the literal source text of a file named by a `CLIENT_FILE` constant and
slice symbol **bodies** out of that text by name. Moving a tested symbol out of
`client.ts`'s own text would break those tests on a "must exist" check.

We chose **Option B**: repoint `CLIENT_FILE` to whichever module now holds each
sliced symbol, leaving every assertion byte-for-byte unchanged. Only the
`CLIENT_FILE` constants and their explanatory comments changed in the test files;
no assertion was weakened, changed, or deleted.

| Test file | `CLIENT_FILE` before | `CLIENT_FILE` after | Symbols sliced |
| --- | --- | --- | --- |
| `tests/api-client-core.test.mjs` | `src/api/client.ts` | `src/api/core.ts` | `RETRYABLE_KINDS`, `apiCallResult` |
| `tests/api-client-normalizers.test.mjs` | `src/api/client.ts` | `src/api/core.ts` | `normalizeTimestamp`, `normalizeEpochSeconds`, `normalizeCheckoutAddress` |
| `tests/whatsapp-analytics.test.mjs` | `src/api/client.ts` | `src/api/domains/whatsapp.ts` | `getTemplateAnalyticsSummary` |

`tests/whatsapp-analytics.test.mjs` had the same coupling (not called out in the
original plan) and was repointed the same way. All three Phase 2 api-client tests
stay green with identical assertions.

## 4. Component work (§5b)

The two largest components were split into co-located sibling modules. Each split
is a pure structural refactor: the module-level preamble (types, constants, pure
helpers) was moved verbatim into siblings and the component file imports what it
uses. Each component keeps its default export identity and any named exports, so
no import site was edited.

### Split

- **`src/components/VayuLokLive.tsx`** (top offender): 5,444 -> 4,550 lines. The
  module-level helper/type preamble was extracted into two co-located siblings:
  - `VayuLokLive.types.ts` (306 lines): all interface/type declarations
    (place/search/severity, health, air and weather types, locations/routes/world/fx
    types, plus `VayuLokExternalLocation` and `VayuLokLiveProps`).
  - `VayuLokLive.helpers.ts` (677 lines): env/config consts, style and symbol
    maps, health personas, and all pure functions (AQI/severity mapping, air and
    weather shaping, formatters, distance/direction helpers).

  The component re-exports `VayuLokExternalLocation`
  (`export type { VayuLokExternalLocation }`) so its public surface (default export
  plus that named type) is unchanged. Two filter/find callbacks inside a helper got
  explicit param types to satisfy the isolated typecheck — no behaviour change. A
  new `tests/vayulok-live-helpers.test.mjs` (10 tests) exercises the extracted pure
  helpers via the offline `loadTsxModule` vm idiom.

- **`src/components/workspace/whatsapp/templates.tsx`**: 2,217 -> 2,151 lines. The
  static preamble (page-props type plus the `*_OPTIONS` select tables, `*_COLORS`
  maps, inline style objects, and operation-path table) was extracted into
  `templates.constants.ts` (99 lines). The sole export (default
  `TemplateManagement`) is unchanged; a now-unused `SelectOption` type import was
  removed from the component to avoid an unused-import warning. The pre-existing
  WhatsApp Business Account IDs were moved verbatim; no new secret was introduced
  (these are WhatsApp Business Account IDs, not AWS credentials).

### Deferred (with rationale and suggested follow-up)

- **`src/components/cart/CartPage.tsx`** (2,212 lines, #3 of the top three):
  deferred. Unlike VayuLokLive and templates, whose preambles are self-contained
  (helpers depend only on each other plus erasable type imports), CartPage's
  module-level helpers and consts are tightly coupled to a large runtime import
  graph (fixed-items data, cart-library functions, and
  checkout/quote/profile/Razorpay types) and are interleaved with its type blocks.
  A safe extraction would have to reproduce that fragile import graph into the
  sibling and risks subtle type churn around the checkout/quote/profile types — more
  risk and a less reviewable diff than the two completed splits. **Suggested
  follow-up:** give CartPage its own focused change that first untangles the
  cart-library and checkout-type imports before extracting helpers.

- **Remaining §5b components** — out of scope this run, deferred to follow-ups:
  `src/components/workspace/whatsapp/calling.tsx`,
  `src/pages/workspace/customers/index.tsx`,
  `src/pages/workspace/engage/inbox/index.tsx`,
  `src/components/TemplateSender.tsx`,
  `src/components/workspace/pay/PayFlow.tsx`,
  `src/components/workspace/platform/SystemArchitecture.tsx`. These were left for
  separate focused changes to keep this run a small, reviewable refactor (a smaller
  correct change beats a large risky one).

## 5. Before/after line counts

### `src/api`

| File | Before | After |
| --- | ---: | ---: |
| `src/api/client.ts` | 7,827 | 32 |
| `src/api/core.ts` | — (new) | 488 |
| `src/api/domains/contacts.ts` | — (new) | 494 |
| `src/api/domains/messaging.ts` | — (new) | 621 |
| `src/api/domains/telephony.ts` | — (new) | 765 |
| `src/api/domains/whatsapp.ts` | — (new) | 2,336 |
| `src/api/domains/commerce.ts` | — (new) | 1,920 |
| `src/api/domains/platform.ts` | — (new) | 1,252 |

### Touched components

| File | Before | After |
| --- | ---: | ---: |
| `src/components/VayuLokLive.tsx` | 5,444 | 4,550 |
| `src/components/VayuLokLive.types.ts` | — (new) | 306 |
| `src/components/VayuLokLive.helpers.ts` | — (new) | 677 |
| `src/components/workspace/whatsapp/templates.tsx` | 2,217 | 2,151 |
| `src/components/workspace/whatsapp/templates.constants.ts` | — (new) | 99 |

## 6. Verification results

This was a pure structural refactor with no behaviour change (verbatim moves;
only import/export wiring adjusted). Final state, run from the repo root:

- `npx tsc --noEmit`: **0 errors** (the single most important guard — a clean
  typecheck against a byte-identical export surface).
- `npx eslint .`: **0 errors / 218 warnings** — no delta versus the baseline, and
  0 warnings on any new `src/api` file.
- `npm test`: **55 pass / 0 fail** (up from 45 after Phase 2; +10 new VayuLokLive
  helper tests). Includes the three repointed Phase 2 api-client tests with
  identical assertions.
- Python suite: **57 passed**, unchanged (a frontend-only refactor does not touch
  the shared Lambda utils; run with
  `PYTHONPATH=amplify/functions/shared .venv/bin/python -m pytest tests/python -q`).

No deploy or `npm run build` was run. No AWS/ARN/IAM inventory, account IDs, or
secrets were added to this public repo. This note makes no claim about
`npm audit`.
