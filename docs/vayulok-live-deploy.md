# VayuLok live page: browser credential and interaction contract

VayuLok is intentionally a browser-driven Google Maps experience.

## One browser flow

`NEXT_PUBLIC_GOOGLE_BROWSER_KEY` is the credential used by the public VayuLok page for:

- Maps JavaScript API
- Places API (New)
- Geocoding API
- Time Zone API
- Air Quality API

The key is expected to be a website/browser key restricted to WECARE.DIGITAL origins. VayuLok must not depend on a separate `/vayulok/environment` gateway to render its core Air or Weather experience.

With Next static export the browser key is bundled into client JavaScript. Treat that as expected browser-key behavior: protect it with Google API restrictions and WECARE.DIGITAL website/referrer restrictions rather than by moving VayuLok's live reads behind an application gateway.

## Interaction contract

The map is a static visualization surface.

- Initial destination is Shillong.
- The initial camera is centered on India.
- Search/recent places are the only location-selection paths.
- Search/recent-place selection recenters the camera to the chosen destination.
- Direct drag, touch/pinch, wheel/zoom, double-click zoom and keyboard map movement are disabled.
- Direct canvas gestures never trigger geocoding or Air Quality refreshes.
- Air Quality refreshes for the selected search/recent-place destination.

## Failure behavior

Provider/API failures must remain visible as unavailable/error states; they must not be disguised as successful empty results.

## Deployment

Amplify reads the build-time browser key from the existing WECARE.DIGITAL Maps secret and exports it as `NEXT_PUBLIC_GOOGLE_BROWSER_KEY`.

Any Google Cloud key-policy change for this feature must keep the browser key enabled for the six APIs listed above. Do not reintroduce a mandatory VayuLok server relay without an explicit product decision, because that previously caused repeated live breakage.

## Acceptance

On a deployed `*.wecare.digital` origin:

1. Load `/vayulok/` and confirm Shillong Air quality appears.
2. Confirm the map is non-interactive: drag/pinch/wheel/keyboard input does not move it or trigger location lookup.
3. Search for a city and confirm the map recenters and refreshes Air Quality data.
4. Confirm the Air Quality card shows AQI, pollutants, forecast and history for the selected place.


## 2026-10-15 scope update

The live map surface is Air-only. Weather UI, Weather API calls, weather history/forecast state, alerts, and the local weather/storm atmosphere layer were removed to reduce page weight. Search/recent-place selection remains the only camera movement path, and the initial camera is centered on India.
