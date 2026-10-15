# VayuLok live page: browser credential and interaction contract

VayuLok is intentionally a browser-driven Google Maps experience.

## One browser flow

`NEXT_PUBLIC_GOOGLE_BROWSER_KEY` is the credential used by the public VayuLok page for:

- Maps JavaScript API
- Places API (New)
- Geocoding API
- Time Zone API
- Air Quality API
- Weather API

The key is expected to be a website/browser key restricted to WECARE.DIGITAL origins. VayuLok must not depend on a separate `/vayulok/environment` gateway to render its core Air or Weather experience.

With Next static export the browser key is bundled into client JavaScript. Treat that as expected browser-key behavior: protect it with Google API restrictions and WECARE.DIGITAL website/referrer restrictions rather than by moving VayuLok's live reads behind an application gateway.

## Interaction contract

The map is a static visualization surface.

- Initial destination is Shillong.
- The initial camera is centered on India.
- Search/recent places are the only location-selection paths.
- Search/recent-place selection recenters the camera to the chosen destination.
- Direct drag, touch/pinch, wheel/zoom, double-click zoom and keyboard map movement are disabled.
- Direct canvas gestures never trigger geocoding, Air Quality, or Weather refreshes.
- Air Quality and Weather refresh for the selected search/recent-place destination.

## Failure behavior

Provider/API failures must remain visible as unavailable/error states; they must not be disguised as successful empty results.

## Deployment

Amplify reads the build-time browser key from the existing WECARE.DIGITAL Maps secret and exports it as `NEXT_PUBLIC_GOOGLE_BROWSER_KEY`.

Any Google Cloud key-policy change for this feature must keep the browser key enabled for the six APIs listed above. Do not reintroduce a mandatory VayuLok server relay without an explicit product decision, because that previously caused repeated live breakage.

## Acceptance

On a deployed `*.wecare.digital` origin:

1. Load `/vayulok/` and confirm Shillong Air quality and Weather appear.
2. Confirm the map is non-interactive: drag/pinch/wheel/keyboard input does not move it or trigger location lookup.
3. Search for a city and confirm the map recenters and refreshes Air Quality and Weather data.
4. Confirm the Air and Weather tabs show their live current conditions, forecasts and history for the selected place.


## 2026-10-16 scope update

Weather remains a first-class VayuLok section. Current Weather, hourly/daily forecast, recent history and public alerts are restored. The heavy local storm/cloud atmosphere overlay remains removed to keep the map lighter. Search/recent-place selection remains the only camera movement path, and the initial camera is centered on India.
