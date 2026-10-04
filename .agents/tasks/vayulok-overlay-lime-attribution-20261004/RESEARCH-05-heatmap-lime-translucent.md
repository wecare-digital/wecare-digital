# Requirement 05 research — recoloring the AQI / PM2.5 heatmap to the site lime, fully translucent

> The owner asked for the AQI and PM2.5 heatmap indicators to render in **the same lime
> green as the site** and to be **fully translucent so the geo-tagging map stays clearly
> visible**, and explicitly asked for the options to be researched and the choice justified.
> This document is that research. The coder implements the chosen option; this file is the
> deliverable the orchestrator relays back to the owner.

## The hard technical constraint that frames every option

The overlay today is a `google.maps.ImageMapType` whose `getTileUrl` points at
`https://airquality.googleapis.com/v1/mapTypes/{mapType}/heatmapTiles/{z}/{x}/{y}?key=...`
(VayuLokLive.tsx ~1200-1221). Those tiles are **raster PNGs rendered server-side by Google's
Air Quality API with a fixed colormap already baked into the pixels**. The endpoint exposes
only a closed set of enumerated colormaps (`UAQI_RED_GREEN`, `US_AQI`, `PM25_INDIGO_PERSIAN`,
etc.). None of them is a single-hue lime ramp, and there is **no color/tint request parameter**
to make Google emit lime pixels. So "same lime as the site" is physically impossible to obtain
from the tile endpoint itself — it must be achieved on the client, after the pixels arrive, or
by not using the baked-colormap tiles at all.

A second framing fact: `overlayMapTypes` tiles are injected into the DOM as ordinary `<img>`
elements inside the map's overlay pane. That means both the Maps-API `opacity` surface **and**
plain CSS (`filter`, `mix-blend-mode`, `opacity`) are available to act on them.

A third framing fact already in the repo: the page carries a hard **"NO RED anywhere"** owner
constraint (design-tokens.md, owner-constraints.md). The current AQI layer uses
`UAQI_RED_GREEN`, whose ramp is literally red→green — it arguably already violates that
constraint. That strengthens the case for recoloring/retinting rather than merely dimming the
existing red-green tiles.

Site lime token (reused, not invented): `--lime:#d1f470` — defined in VayuLokLive.tsx (~2180)
and traceable to the home page (`index.tsx`), per design-tokens.md.

## Options considered

### Option A — `ImageMapType` opacity only (`opacity` option / `setOpacity()`)
Set the overlay's opacity low so the base map shows through.
- Translucency: YES, this is exactly what the Maps API `opacity` surface is for.
- "Same lime": NO. Opacity only fades the existing red→green / indigo→persian pixels; it does
  not change their hue. A faded red is still red, just paler — this keeps a red cast on the page
  and does not satisfy "lime".
- ToS/attribution: safe (acts only on the overlay pane; touches nothing in `.gm-style-cc`).
- Verdict: satisfies translucency, fails "same lime" and fails "no red". **Rejected alone.**

### Option B — CSS `filter` + `mix-blend-mode` on the overlay `<img>` tiles, plus reduced opacity
Target the overlay tile images with a CSS filter chain that collapses Google's multi-hue ramp
toward a single lime hue and lightens it, combined with low opacity for translucency. In
practice: a `hue-rotate`/`saturate`/`sepia`+`hue-rotate` chain (or a `brightness`/`contrast`
pre-step) to push the baked colors toward `#d1f470`, plus `opacity` so the base map reads
through, and optionally `mix-blend-mode:multiply|screen` so the lime sits over the map legibly.
- Translucency: YES (opacity + blend mode).
- "Same lime": APPROXIMATE. A filter chain cannot pin every input pixel to exactly `#d1f470`
  because the source is a multi-hue gradient, but it can drive the whole overlay into a lime-ish
  single-hue family and kill the red, which is the owner's intent ("same lime as the site",
  "no red"). This is the closest match achievable without re-rendering tiles.
- ToS/attribution: safe **if and only if** the selector is scoped to the overlay tile pane and
  never touches `.gm-style-cc`, `a[href*="google"]`, or `img[alt="Google"]`. The styled-jsx
  scope (`.vl-live-...`) plus the map canvas container keeps it contained. CSS filters applied
  to a parent must NOT cascade onto the Google logo/legal — scope to the overlay images only.
- Performance/billing: zero extra network cost; still one tile request per tile, same SKU.
- Fidelity: good — single-hue lime, translucent, red removed.
- Verdict: **best balance.** It is the only option that delivers all four of translucent +
  lime + no-red + no extra billing without re-architecting the overlay, provided the selector
  stays off the attribution nodes.

### Option C — pick the greenest enumerated colormap + a lime tint layer on top
Switch the mapType to the Google colormap whose ramp is closest to green, then overlay a
semi-transparent lime tint.
- "Same lime": still a multi-hue baked ramp underneath; the tint muddies rather than unifies.
- No-red: only helps if a non-red colormap exists for BOTH AQI and PM2.5; `UAQI_RED_GREEN`'s
  only AQI sibling is `US_AQI` (also warm/red at the top), so AQI cannot escape red this way.
- Verdict: does not reliably remove red for AQI; weaker fidelity than B. **Rejected.**

### Option D — custom client-side tile layer: fetch Air Quality data and render a single-hue
lime translucent heatmap ourselves
Highest fidelity: we control every pixel, so we can paint exactly `#d1f470` at chosen alpha.
- "Same lime" + translucency + no-red: PERFECT.
- Cost/complexity: HIGH. Requires a different Air Quality API surface (per-cell data, not
  prebuilt tiles), a canvas tile renderer, interpolation, and new tests. More network calls,
  more billing, more surface area, and it cannot be verified in sandbox (referrer-restricted
  key) any better than B can.
- Risk: large new code path for a marketing page; disproportionate to the ask.
- Verdict: correct in theory, over-engineered for this requirement. **Rejected for this cycle;
  noted as the future high-fidelity path if the owner ever wants pixel-exact lime.**

## Decision

**Option B — CSS filter + blend + reduced opacity on the overlay tile images, scoped under the
component's styled-jsx map-canvas scope.** It is the only approach that satisfies all of:
"same lime as the site", "fully translucent so the geo map stays visible", the page-wide
"no red" constraint, and zero added billing/complexity — while keeping Google's logo and legal
attribution untouched (the selector targets only the overlay tile pane, never `.gm-style-cc`,
`a[href*="google"]`, or `img[alt="Google"]`).

Reuse the existing `--lime` (`#d1f470`) token; do not introduce a new hue. The opacity must be
low enough that road geometry and labels remain clearly readable underneath (the owner's
"fully translucent" / "map clearly visible" requirement), and the result must carry no red
tone (satisfying "no red anywhere").

## Why this is honest about its limits
A CSS filter cannot force a multi-hue baked ramp to a single exact `#d1f470` on every pixel; it
unifies toward lime and removes red. If the owner later needs pixel-exact lime, Option D (custom
client renderer) is the path, at materially higher cost. This trade-off is recorded here so the
choice is auditable.

## Verification note
The browser Maps key is referrer-restricted to `*.wecare.digital/*`, so the live overlay cannot
render in sandbox/CI. Verification is via `typecheck` + `lint` + `vitest`, the existing
on-user-action + honest-degradation tests, and (where asserted) that the overlay styling/opacity
is wired. A blank/absent map in sandbox is expected, not a failure.
