# FINDINGS-06 — Requirement 06 (Google Photos attribution, Google name terms, metadata/EXIF)

Date: 2026-10-04
Feature: FEAT-003 (bounded, legally permissible subset the owner approved)
Component in scope: `src/components/VayuLokLive.tsx` (the `/vayulok/` live map/place card)

## 1. The literal request vs. what is legally permissible

The literal requirement 06 ("remove all attribution from Google Photos in the place
card and Google name terms, etc and metadata/exif data") is **not permissible in full**.
Two pieces are **mandatory** under the Google Maps Platform Terms of Service and the
Places API policies and MUST remain visible and legible:

- The **Google Maps attribution/logo and the `.gm-style-cc` legal notices** that Google
  paints into the map's bottom corners.
- The **Place Photo author attributions** (the `.vl-live-photo-credit` `<figcaption>` and
  its links to `credit.uri`) that accompany each Google Place photo.

Stripping or hiding either would violate Google's ToS. The owner approved the bounded
version of this requirement: do the parts that are permissible, keep the mandated
attribution intact. This feature therefore does **not** remove attribution.

## 2. EXIF / metadata finding (authoritative)

Re-ran the repo-wide search for any image-metadata or raster tooling:

```
grep -rniE "exif|piexif|\bsharp\b|image.?size|strip.*metadata" src/ scripts/
# -> NO MATCHES
```

Zero matches. There is **no project-owned image-generation, re-encoding, or EXIF
pipeline** anywhere in `src/` or `scripts/`.

The only image path in the repo is the presigned-S3 upload used by the WhatsApp sender,
in `src/api/client.ts`:

- `getMediaUploadUrl( mediaType, filename )` — asks the backend for a presigned URL.
- `uploadFileToS3( uploadUrl, file, contentType )` — `fetch(uploadUrl, { method:'PUT', body: file })`.
- `uploadFileViaPresignedPost( url, fields, file )` — `FormData` with the raw `file`.

Each of these forwards the user-provided `File | Blob` **as-is**. There is no canvas
redraw, no re-encode, no raster transform — so no step that would read, write, or strip
EXIF. The bytes S3 receives are exactly the bytes the browser was handed.

Google **Place Photos** (the photos shown in the place card) are fetched **live** from
Google photo URLs via `photo.getURI({ maxWidth, maxHeight })`. The app stores only the
resulting URL string (plus Google's author attributions); it **never holds the raw image
bytes**. There is therefore **no local EXIF to strip** on those photos, and nothing the
app could legally re-encode.

**Conclusion:** No project-owned image generation/upload path re-encodes rasters; Google
Place Photos are fetched live from Google URLs so the app never holds raw bytes — there
is NO local EXIF to strip and nothing to add. **No new dependency is introduced.**

No EXIF or technical photo metadata (resource IDs, raw URLs, dimensions, etc.) is
rendered to the user anywhere in the place card; only the human-readable author
attribution Google requires.

## 3. What this feature changed

- **No attribution removed or hidden.** The `.vl-live-photo-credit` `<figcaption>` and its
  `credit.uri` links stay. The attribution data capture (search `choose()` path, map-click
  enrichment, and the nearby-photo path) is unchanged. The Google Maps logo/legal
  (`.gm-style-cc`) is untouched; no CSS targets `.gm-style-cc`, `a[href*="google"]`, or
  `img[alt="Google"]`, and overlays stay inset from the map's bottom corners.
- **"Clean photo" preference kept as-is.** The existing logic that prefers photos with
  `attributions.length === 0` only *orders* photos; it never suppresses attribution on
  photos that carry it.
- **Presentation touch (Step 4): NO change made.** The `.vl-live-photo-credit` rule
  (`src/components/VayuLokLive.tsx` ~line 2445) is already minimal and ToS-safe: inset
  from all three edges, `font-size:8px`, single-line truncation with ellipsis, a ~76%
  translucent background, and `color:rgba(26,58,42,.78)`. Reducing it further would risk
  legibility/visibility and the ToS requirement that the attribution be readable, so no
  change was made. It is not reduced to `display:none`, zero opacity, or off-screen.
- **Guard test added.** `src/test/VayuLokLive.test.tsx` now supplies a Place photo with a
  non-empty `authorAttributions` through the existing Google stub path and asserts the
  `.vl-live-photo-credit` figcaption and its credit link render. This prevents a future
  accidental removal of the mandated attribution.

## 4. Verification

- `npm run typecheck` — pass
- `npm run lint` — pass
- `npm run test` (vitest run) — pass (all existing tests green + new attribution guard)
