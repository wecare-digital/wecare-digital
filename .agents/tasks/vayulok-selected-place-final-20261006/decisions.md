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
