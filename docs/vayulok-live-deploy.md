# VayuLok live page: browser credential and interaction contract

VayuLok is intentionally a browser-driven Google Maps experience.

## One browser flow

`NEXT_PUBLIC_GOOGLE_BROWSER_KEY` is the credential used by the public VayuLok page for:

- Maps JavaScript API
- Places API (New)
- Geocoding API
- Time Zone API
- Weather API
- Air Quality API

The key is expected to be a website/browser key restricted to WECARE.DIGITAL origins. VayuLok must not depend on a separate `/vayulok/environment` gateway to render its core Air or Weather experience.

With Next static export the browser key is bundled into client JavaScript. Treat that as expected browser-key behavior: protect it with Google API restrictions and WECARE.DIGITAL website/referrer restrictions rather than by moving VayuLok's live reads behind an application gateway.

## Interaction contract

The map itself is a location picker.

- Initial destination is Shillong.
- Search/recent places can jump the camera to a destination.
- Direct drag, touch/pinch, wheel/zoom and keyboard map movement are enabled.
- After direct map movement settles, the visible map center becomes the selected destination.
- VayuLok reverse-geocodes that center when Geocoding is available.
- Air Quality and Weather refresh automatically for the newly selected center.
- A map-originated selection must not snap the camera back to the search zoom.

The default information cards therefore always follow the current selected map location, whether it came from search or from direct map interaction.

## Failure behavior

A failed optional reverse-geocode must not block environmental refresh. In that case VayuLok keeps the selected coordinates and labels the point generically.

Provider/API failures must remain visible as unavailable/error states; they must not be disguised as successful empty results.

## Deployment

Amplify reads the build-time browser key from the existing WECARE.DIGITAL Maps secret and exports it as `NEXT_PUBLIC_GOOGLE_BROWSER_KEY`.

Any Google Cloud key-policy change for this feature must keep the browser key enabled for the six APIs listed above. Do not reintroduce a mandatory VayuLok server relay without an explicit product decision, because that previously caused repeated live breakage.

## Acceptance

On a deployed `*.wecare.digital` origin:

1. Load `/vayulok/` and confirm Shillong Air/Weather appears.
2. Drag or rotate/pan the map to a visibly different location.
3. Release the map and confirm the displayed location/default information changes.
4. Confirm Weather and Air Quality requests use the new center coordinates.
5. Search for a city and confirm search still recenters and refreshes the same data.


<!-- Rebuild trigger: 2026-10-15 VayuLok browser-key redeploy -->
