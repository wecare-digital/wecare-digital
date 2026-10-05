# VayuLok live page: Google credential and deploy contract

The approved v8 UI has two different Google trust boundaries. Do not put them back on one key.

## Browser key: Maps UI only

`NEXT_PUBLIC_GOOGLE_MAPS_KEY` is a public browser key. With Next static export it is
inlined into JavaScript by design, so its protection is restriction, not secrecy.

Use Google Cloud Website / HTTP referrer application restrictions:

- `https://wecare.digital/*`
- `https://*.wecare.digital/*`

Do not put `*.googleapis.com/*`, `places.googleapis.com`, or other Google API hosts in
the website allow-list. Those are destinations, not the referring WECARE website.

Restrict this browser key to the APIs the approved browser UI needs:

- Maps JavaScript API
- Places API (New)
- Geocoding API
- Maps Elevation API

Do not add Weather, Air Quality, Pollen, Solar, Translate, Vision, YouTube, Business Profile,
Routes, or unrelated APIs simply because they are enabled in the project.

## Server key: Weather + Air Quality

Weather and Air Quality web-service requests belong behind
`POST /vayulok/environment`, implemented by
`amplify/functions/core/vayulok-environment/handler.py`.

That Lambda reads `wecare/google-maps-server` from AWS Secrets Manager at request time and
sends the key to Google in `X-Goog-Api-Key`, never in a browser bundle or URL query string.
The server key is provisioned by `scripts/provision_maps_server_key.py`; its API target list
contains the existing server address-capture services plus:

- `airquality.googleapis.com`
- `weather.googleapis.com`

The public gateway is deliberately narrow: WECARE HTTPS Origin check before the secret read,
India coordinate bounds, fixed operation names, fixed Weather/Air request shapes, bounded
history ranges, a server-generated 3x3/5x5 AQ grid capped at 25 samples, and an API Gateway
per-route throttle. Origin is cost-friction, not authentication; provider quotas and budgets
remain necessary.

## Safe rollout order

The repository change is intentionally staged so production does not lose environmental data.

1. Recreate/verify the server key without printing it:
   `python scripts/provision_maps_server_key.py --create`
   (or `--status` / `--verify` when it already exists).
2. Provision the gateway:
   `python scripts/provision_vayulok_environment.py`
3. Read back the route/alias:
   `python scripts/provision_vayulok_environment.py --verify`
4. Smoke `POST /vayulok/environment` from an allowed deployed WECARE origin.
5. Only after that evidence is green, change `VayuLokLive.tsx` from direct
   `weather.googleapis.com` / `airquality.googleapis.com` calls to this gateway.
6. Then remove Weather/Air Quality from the browser key's API restrictions and redeploy
   `stack`.

Do not perform step 5 before steps 1-4. The historical
`wecare/google-maps-server` secret has previously held a deleted key; cutting the browser
over to an unverified gateway would turn a credential hardening change into a VayuLok outage.

## Unsupported India calls

The approved v8 implementation does not call Google Pollen for India and does not request
Google Weather public alerts for India. Do not enable those APIs on either key to compensate
for absent UI data.

## Validation

- `tests/test_vayulok_environment.py` pins the server boundary.
- `src/test/VayuLokLive.test.tsx` pins the approved v8 browser DOM/data behavior.
- `.github/workflows/build-test.yml` runs build, TypeScript, Vitest, browser harness and lint.

The final acceptance step remains a live rendered comparison of `/vayulok/` against
`vayulok-local-prototype-wecare-v8(1).html` on a `*.wecare.digital` origin.
