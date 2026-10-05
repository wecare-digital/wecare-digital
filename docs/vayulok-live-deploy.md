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

That Lambda reads `wecare/google/cloud` from AWS Secrets Manager at request time and
sends the key to Google in `X-Goog-Api-Key`, never in a browser bundle or URL query string.
The server key is provisioned by `scripts/provision_maps_server_key.py`; its API target list
contains the existing server address-capture and Translate services plus:

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
2. **Teach the public-bundle gate the new key, in the same change.** Step 1 prints a
   copy-pasteable entry for `FORBIDDEN_FINGERPRINTS` in
   `scripts/verify_public_bundle_secrets.py`, where a commented placeholder slot is
   already waiting for it. Paste it **verbatim** — the printed block is a complete,
   valid dict entry (two adjacent string literals relying on implicit concatenation),
   and `tests/test_vayulok_server_key_provisioning.py` `ast.parse`s what the script
   prints so a reflow that breaks the paste fails in CI rather than here. Then commit.

   After pasting, confirm the gate sees it:
   `python scripts/verify_public_bundle_secrets.py --list-fingerprints`
   must report the new entry instead of none.

   This is not bookkeeping. The key step 1 mints carries **no application restriction**
   — deliberate, because Lambda has no stable egress IP to allowlist — so unlike the
   referrer-restricted browser key it must never be inlined into a public JS chunk.
   `output: 'export'` inlines every `NEXT_PUBLIC_*` value, and that gate is the only
   automated thing that would notice. Until the fingerprint is pasted, the gate is blind
   to the one key it was written for. The fingerprint is a one-way sha256 prefix and is
   safe to commit; the value itself is never printed.
3. Provision the gateway:
   `python scripts/provision_vayulok_environment.py`
4. Read back the route/alias:
   `python scripts/provision_vayulok_environment.py --verify`
5. Smoke `POST /vayulok/environment` from an allowed deployed WECARE origin.
6. Only after that evidence is green, change `VayuLokLive.tsx` from direct
   `weather.googleapis.com` / `airquality.googleapis.com` calls to this gateway.
7. Then remove Weather/Air Quality from the browser key's API restrictions and redeploy
   `stack`.

Do not perform step 6 before steps 1-5. The canonical `wecare/google/cloud` secret currently holds the referrer-restricted browser
key until the server-key provisioning step replaces only its key fields while preserving project
metadata. Cutting the browser over before that key and gateway are verified would turn credential
hardening into a VayuLok outage.

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
