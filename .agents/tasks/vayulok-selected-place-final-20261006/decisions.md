# VayuLok selected-place final - decisions

## FEAT-002

### Selected marker API (section 13): choice B - styled classic Marker with an SVG data-URI icon

We replaced the plain `new maps.Marker({ position, map, title })` default RED pin with a
no-red brand marker built as a classic `google.maps.Marker` carrying a custom `icon`:

- The icon is an inline SVG teardrop encoded as a `data:image/svg+xml` URI (no asset fetch).
- Palette: dark-green `#1a3a2a` body, lime `#d1f470` inner dot, white `#ffffff` ring. No red.
- Size 36x48 with the anchor at the pin tip, deliberately larger than the small filled AQ
  sample dots so it reads as the selection, not as a data point.

Choice B over choice A (`google.maps.marker.AdvancedMarkerElement`) because:

- B keeps working under the existing `FakeMarker` test stub (the stub records the `icon`
  opt, so matrix K can assert the brand icon directly), while A would need DOM content and
  a `mapId`, neither of which the stub or the referrer-restricted sandbox key provides.
- B needs no `mapId` and no extra `importLibrary('marker')` DOM wiring.
- The marker is created LAZILY on first real selection (not on load) by the recenter
  effect, so the neutral initial map opens with no pin.

### Open / closed metadata audit (section 22): OMIT the line

Decision: OMIT the "Open now" / "Closed now" line entirely.

Rationale: on the modern `google.maps.places.Place` class, open-now status is time
dependent and is exposed through the ASYNC `Place.isOpen()` method, NOT as a reliably
populated static boolean on `regularOpeningHours`. The legacy `open_now` field was
deprecated. Rendering a static "Open now/Closed now" line from a field the real API does
not deliver as a static value would be dishonest, so:

- `regularOpeningHours` was removed from `PLACE_META_FIELDS` (no longer requested).
- `openNow` was removed from `PlaceState`, `GooglePlaceLike`, and `metaFromGooglePlace`.
- The open/closed attribute line was removed from the left-card render.

The existing metadata test was updated to assert the line is absent and that
`regularOpeningHours` is not among the requested fields.

### Other FEAT-002 notes

- `DEFAULT_PLACE` (Dawki) was replaced by a neutral `INITIAL_CAMERA` (central-India centre
  22.9734, 78.6569 at zoom 5). `place` state starts `null`; the map opens with no card,
  no marker, no destination bar, and no environmental fetch until a real selection.
- Hard India country gate `isIndiaResult()` inspects the country address component and
  accepts only `short_name`/`shortText === 'IN'`. Applied to the map-click reverse-geocode
  (iterate rows, first IN wins, else keep previous selection + honest "outside India"
  status), the geocoding search fallback (India-only + require a real location, never a
  default coordinate), and softly to the autocomplete `toPlace()` path (reject only when a
  country component is present and non-IN; this branch is only live on *.wecare.digital).
- Photo-fallback fix: ANY exact photo with a non-empty url is used (attribution rides with
  it); `searchNearby` runs only when there is NO usable exact photo.

## FEAT-003

### Map-panel border (section 23): normalize to the homepage hairline

Decision: change `.vl-live-map-stage` border from `1px solid rgba(209,244,112,.92)` (lime)
to the homepage hairline `1px solid #e5e7eb`. Box-shadow stays `none`.

Rationale: the design tokens reserve lime (#d1f470) as punctuation / active colour (number
pill, active pill, chevron accent, 3px accent rules), never as a general resting panel
border. A lime hairline around the whole map read as a decorative frame rather than a
structural boundary, so the map panel now matches every other panel on the page with the
neutral hairline. No stronger boundary is justified: the map already reads as its own
surface via the search field, the pills, and the destination bar, so a louder border would
be redundant. Matrix J asserts the stage rule contains `border:1px solid #e5e7eb`, no
`rgba(209,244,112,.92)`, and `box-shadow:none`.

### Destination-bar shadow (section 04): reduce resting elevation, normalize hover token

Decision: the floating `.vl-live-map-destbar` keeps a light resting elevation because it
sits OVER the map and needs to separate from the roads beneath it, but it is reduced from
`0 2px 10px rgba(26,58,42,.12)` to `0 1px 4px rgba(26,58,42,.08)` so it reads as a hairline
lift rather than a heavy card shadow, honouring the homepage "no heavy resting shadow"
rule. The hover shadow is normalized to the homepage hover token
`0 4px 12px rgba(26,58,42,.12)` (was `0 4px 14px rgba(26,58,42,.16)`).

### Active pill (sections 11/23): rgba(209,244,112,.6)

Changed `.vl-live-layer[aria-pressed="true"]` fill from `rgba(209,244,112,.55)` to the
spec target `rgba(209,244,112,.6)` (translucent lime, dark-green #1a3a2a text + border,
never opaque var(--lime)). Inactive pill verified fully transparent, no backdrop blur, no
resting shadow, dark-green text + 1.5px border. Focus ring `outline:3px solid var(--green)`
offset 3px kept. Matrix J reads these from the rendered styled-jsx CSS.

### Left-card hero + notch (sections 15/17)

- Section 15: the left card now leads with ONE LARGE primary hero photo
  (`.vl-live-photo-hero`, 232px tall, object-fit:cover) carrying its own author
  attribution figcaption. The additional photos stay in the existing horizontal pager/rail
  (`.vl-live-place-photos` + `.vl-live-photo-tabs`); nothing floats on the map (there is no
  on-map gallery and none was added). The number-only referee-SVG lime pill is preserved
  byte-identical (path, aria-label `N place photos`, fill via --lime #d1f470).
- Section 17: the card is wrapped in an OUTER `.vl-live-place-cardwrap` (overflow:visible,
  11px bottom padding) while the inner `.vl-live-place-card` keeps border-radius:14px +
  overflow:hidden. A centred bottom notch (`.vl-live-place-notch`, a 16px square rotated
  45deg with the two outward borders as the hairline edges) is drawn from the outer wrapper
  so it escapes the clipped inner corner. All markup stays INLINE in the component return
  so styled-jsx keeps the vl-live- scope on the notch (the critical styled-jsx gotcha).

### Destination-bar chevron behaviour (section 04)

The destbar onClick now scrolls the LEFT selected-place card into view and moves focus to
it (via a `placeCardRef` on the outer wrapper, which is `tabIndex={-1}` + a focus-visible
ring). The recenter (setCenter + setZoom + marker) is kept as a secondary convenience. The
`scrollIntoView` call is guarded with a typeof check because jsdom does not implement it;
matrix F stubs `Element.prototype.scrollIntoView` and asserts both the scroll call and that
focus lands on the card.

### Section 03/14 (verified, not rebuilt)

The hybrid SearchDestinations path still draws the building outline (displayPolygon) and
entrance markers ONLY when Google actually returns them, in no-red styling (dark-green
#1a3a2a strokes, low-opacity lime #d1f470 fill at .18, lime entrance dots), and fabricates
no geometry for localities (area-like primaryTypes short-circuit before the lookup). The
FEAT-002 India gate `isIndiaResult()` is applied upstream on the autocomplete toPlace and
geocoding paths that resolve the location this branch runs on. This branch is only
exercisable on a live *.wecare.digital origin (referrer-restricted key, experimental Maps
capability), so it is documented, never faked, and the degraded-path test asserts no
polygon is drawn when the capability is absent.
