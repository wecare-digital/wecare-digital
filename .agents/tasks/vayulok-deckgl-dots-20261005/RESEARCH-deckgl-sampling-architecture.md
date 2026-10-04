# VayuLok deck.gl dot visualization — sampling architecture decision

Date: 2026-10-05
Branch: `vayulok-finish-unmerged` (extends PR #221 → base `stack`)
Author: architect pass (pre-implementation research)

## Problem

The FINAL AGREED DESIGN replaces the Google Air Quality **raster heatmap tiles**
(`ImageMapType` → `/v1/mapTypes/{type}/heatmapTiles/{z}/{x}/{y}`) with a
**deck.gl `ScatterplotLayer`** of REAL Air Quality API point samples, rendered
over the Google roadmap through `GoogleMapsOverlay` (`@deck.gl/google-maps`).

Each dot = a REAL sample from the Air Quality API `currentConditions:lookup`
endpoint at a coordinate around the selected place. A ~5×5 grid is the starting
density, but it must be responsive / cost-aware (fewer dots on small screens).

Google's `currentConditions:lookup` is **one-location-per-request**. A grid of N
points therefore costs **N requests per layer activation**. The owner explicitly
warns against uncontrolled browser requests and asks that we "fetch/cache real
AQI samples". So we must choose a sampling architecture.

## Options evaluated

### Option A — Backend/cached endpoint (Amplify function)

A new Amplify function fans the grid out server-side, caches by
`area + grid + layer + time-bucket`, and returns a point array in one response.

**Pros**
- One browser request per layer activation regardless of grid size.
- Server-side cache shared across all users → lowest total Air Quality spend.
- Highest correctness; grid size and throttling controlled centrally.

**Cons — decisive against it for THIS increment**
- **Credential problem.** The only Maps/Air-Quality credential this project has
  is the **browser key**, which is HTTP-referrer-restricted to
  `*.wecare.digital/*`. A server-side call originates from a Lambda with **no
  Referer header**, so that key is **rejected**. A backend fan-out needs a
  **different credential** — a server/IP-restricted (or unrestricted) Air
  Quality key provisioned in Secrets Manager. Provisioning a new Google API
  credential is **owner/provider action** (steering `01-standing-authorization`:
  credential creation/rotation is `MANUAL_OWNER_ACTION`), so it cannot be landed
  unattended in this pass.
- **New backend surface.** `amplify/functions/...` + API Gateway route + IAM +
  deploy pipeline is a materially larger scope than the UI change, and the route
  surface already carries the `AuthorizationType=NONE` concern documented in the
  owner overrides. Adding a public fan-out endpoint without auth would widen that
  gap; adding it WITH auth is more scope again.
- **Static export.** The site ships `output:'export'` (static). The component
  already calls Google APIs **client-side** with the referrer key (exactly like
  `ContactLocation.tsx`). A backend endpoint diverges from that proven,
  deployed pattern.
- **Not verifiable in sandbox.** Network is restricted; a new endpoint cannot be
  exercised here either way.

### Option B — Client-side throttled + cached grid fetch (CHOSEN)

The component fetches the grid **client-side** from the browser, exactly as it
already fetches `currentConditions:lookup` for the single selected place, using
the same referrer-restricted key. It is:

- **Keyed cache** by `area(lat,lng rounded) + grid-size + layer + time-bucket`
  (reuse the existing `cache.useRef` pattern; a ~10 min time bucket mirrors the
  existing `CORE_TTL_MS`). Re-activating a layer on the same place/time bills
  nothing. Optionally mirror to `localStorage` for cross-reload reuse.
- **Capped & responsive.** Grid density derived from viewport width: e.g. 5×5
  (25) on wide screens, 3×3 (9) on narrow — never hard-coded 25 forever. A hard
  cap (e.g. ≤25) bounds worst-case spend.
- **Throttled & abortable.** Requests issued through a small concurrency limiter
  (e.g. ≤4 in flight) with a single `AbortController` cleared on layer-change /
  unmount, matching the existing effect-cleanup discipline.
- **Real values only.** Each point is parsed by the EXISTING `airPointFromApi`
  (reused), so dots carry real AQI/PM2.5; a point that fails to parse is dropped,
  never fabricated.

**Pros**
- Works with the **existing browser key** and the deployed referrer model — no
  new credential, no owner action.
- No new backend surface; consistent with the shipped client-side approach and
  static export.
- Cost bounded by cap + cache + throttle + the no-double-fetch rule (grid only on
  pill click, never on type/select).

**Cons (accepted, documented)**
- N requests per cold layer activation (bounded by the cap). Mitigated by cache,
  time-bucketing and responsive density.
- Browser key is public by design (already true for the single-point calls on
  this page); referrer restriction is the control, unchanged by this feature.

## Decision

**Ship Option B now.** It is the correct first increment under the honest
constraints: it reuses the existing browser-key client-side pattern, needs no new
Google credential and no new backend, keeps the static-export deployment intact,
and bounds cost through responsive density + a hard cap + keyed caching + request
throttling + the no-double-fetch rule.

**Document Option A as the follow-up.** If/when the owner provisions a
server/IP-restricted Air Quality key in Secrets Manager, a backend-cached
fan-out endpoint (Amplify function keyed by `area+grid+layer+time`) becomes the
cost-optimal path and should replace the client fan-out. That follow-up is
recorded here because it has a real credential/provider implication the owner
must action; it is out of scope for this unattended pass.

## Sandbox verifiability

The browser key is referrer-restricted to `*.wecare.digital/*`, so the live map,
Places, geocoding **and** the grid Air Quality calls **cannot run in
sandbox/CI** — a blank/absent map there is EXPECTED. We verify by:
`npm run typecheck`, `npm run lint`, `npm run test` (vitest) against stubbed
Google globals, and the honest-degradation path (no key → no map/overlay/fetch).
We do NOT fabricate dots, tiles, gradients, or values to make the map "look"
rendered.

## Palette / attribution constraints carried into implementation

- Dots use the **custom VayuLok no-red severity palette** (the existing
  `--aqi-good #1a3a2a → --aqi-sat #3da35a → --aqi-mod #d1f470 (lime) →
  --aqi-poor #e8c547 → --aqi-worst #c98a2e` ramp). Do NOT inherit Google's
  `UAQI_RED_GREEN` tile colors.
- `GoogleMapsOverlay` must NOT cover the Google logo / `.gm-style-cc` legal
  attribution. No CSS targets `.gm-style-cc`, `a[href*="google"]`,
  `img[alt="Google"]`. Place Photo author attributions stay with the photo.
