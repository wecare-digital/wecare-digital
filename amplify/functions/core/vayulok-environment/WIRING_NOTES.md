# VayuLok environment proxy — frontend wiring status & plan

## Why this exists

`handler.py` is a hardened server-side proxy (`POST /vayulok/environment`) that reads the
Google key from Secrets Manager, checks a `*.wecare.digital` HTTPS Origin, clamps coordinates
to India bounds, and forwards to Google's Air Quality / Weather APIs. Its intent is to stop the
browser needing `NEXT_PUBLIC_GOOGLE_MAPS_KEY` for the data calls, so the key is not inlined into
the public `output: 'export'` bundle.

## Current reality

`src/components/VayuLokLive.tsx` does **not** call `/vayulok/environment`. It calls Google
directly from the browser with `NEXT_PUBLIC_GOOGLE_MAPS_KEY`. So the proxy is, today, unused by
the shipping frontend.

## Why we did NOT blindly wire it (would regress the product)

Routing the current browser calls through this proxy as-is would break real behaviour:

1. **Worldwide destinations.** `_location()` rejects any coordinate outside India bounds
   (`INDIA_BOUNDS`). The frontend supports worldwide search (e.g. the London marker, non-India
   regionCode handling). Proxying every call would 400 for any place outside India.
2. **Timezone.** The frontend calls `maps.googleapis.com/maps/api/timezone/json` for the
   selected place's local clock. The proxy has no `timezone` operation.
3. **Heatmap tiles.** AQI/PM2.5 heatmaps are Google `ImageMapType` tiles fetched as `<img>`
   URLs with the key in the query string. These cannot go through a JSON proxy without a
   dedicated tile-proxy route.
4. **Pollutant additional info** (fixed in this change). The proxy's `air_current` previously
   omitted `POLLUTANT_ADDITIONAL_INFO`, which the frontend's pollutant popovers render
   (sources/effects). That computation is now included so a future wiring keeps the popovers.

Because the key is still required for (2) and (3), wiring only (1) would not remove the key from
the bundle — so it would add a dual code path and a region restriction for no security win yet.

## Path to actually removing the browser key (future work)

To make the proxy the sole data path and drop the key from the bundle, the Lambda needs to first
match the frontend's real contract:

- [ ] Relax / parameterise the India-bounds clamp to support worldwide destinations (or add a
      separate worldwide operation), keeping a sane abuse guard.
- [ ] Add a `timezone` operation forwarding to the Time Zone API.
- [ ] Add a tile-proxy route for the AQI/PM2.5 heatmap `ImageMapType` tiles (or sign tile URLs
      server-side) so the `<img>` tiles no longer carry the browser key.
- [x] Include `POLLUTANT_ADDITIONAL_INFO` in `air_current` so proxied current conditions keep
      the pollutant sources/effects popovers. (done in this change)

Once those land, switch each `fetch(...)` in `VayuLokLive.tsx` to POST `/vayulok/environment`
with the matching `operation`, parse the same Google-shaped JSON the proxy passes through, and
remove `NEXT_PUBLIC_GOOGLE_MAPS_KEY` from the public env. Verify with
`scripts/verify_public_bundle_secrets.py` that the key no longer appears in `out/`.
