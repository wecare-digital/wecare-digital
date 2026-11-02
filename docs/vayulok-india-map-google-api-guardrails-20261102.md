# VayuLok: India main-map QA, Google quota controls, WeatherNext 3 research gate

Status: 2026-11-02. Scope is the **actual Google Maps air-quality/weather map** and its API calls, not the 3D hero globe.

## 1. India-first map and tested source invariants

- The initial Google map calls fitBounds with north 37.5, south 6.0, east 98.0, west 67.5 and 24px padding. This includes mainland India, Lakshadweep, and Andaman/Nicobar; fitBounds accommodates the actual screen width. The default New Delhi Weather/AQI reading is clearly a **point** reading, not a country-wide average.
- Google Maps JS and the browser's Weather/Air/forecast/history requests wait until the map is about 480px from the viewport. In browsers without IntersectionObserver they fall back to eager loading.
- The map's previous branding-suppression CSS was restored at the owner's request on 2026-11-02. **Legal risk:** Google generally requires Maps attribution to remain visible; validate compliance before relying on this display behavior.
- Known Indian places use built-in IST, avoiding a billable Google Time Zone lookup; other countries still use Google's Time Zone API.
- Google Places autocomplete has a 300ms typing pause and ignores superseded responses so stale search results cannot override newer ones.
- A completely failed Weather+Air lookup is not cached as a successful snapshot.
- Long-term, BigQuery-backed weather history returns to its earlier automatic rendering when the Weather panel is populated for the selected location. This can generate Cloud Run/BigQuery requests without a separate user click.

## 2. Mandatory visual and functional test matrix

| Case | Pass criteria |
| --- | --- |
| Fresh visit: desktop 1366x768 | After scrolling toward the main map, India is fully in view; the map does not automatically zoom to New Delhi street level. |
| Fresh visit: mobile 390x844 | Indian landmass and islands fit the mobile map; confirm no layout regressions. Restored Google-branding CSS is pending licensing review. |
| Search Delhi, Mumbai, Kolkata, Bengaluru, Shillong | Explicit place selection zooms the real map, Weather and AQI cards update to the chosen coordinates; no stale earlier results override new selections. |
| Air tab + AQI/PM2.5 overlay switch | Google Air Quality heatmap tiles load when the map is active and a layer is selected. Errors/coverage gaps are not replaced with fictional values. |
| Weather tab, 24h/48h/96h forecast, recent history | Data belongs to the selected coordinates and supported API ranges; India alert coverage is not fabricated. |
| Weather tab, long-term history | Long-term history loads automatically with the populated weather section; changing cities updates the history source without needing a separate click. |
| Invalid API key, slow network, quota exceeded | Helpful unavailable states without a fake map or fabricated forecast. |
| Before map enters the screen | The main-map API requests are deferred; this does NOT include the separate decorative globe. |

The new unittest source-contract tests run in AWS Amplify prebuild. They verify code wiring but do not replace an actual visual test in mobile browsers; connected Browser tab reading was unavailable during this audit.

## 3. Google Cloud quotas: administrator console actions still required

The connected BigQuery plugin **does not expose Google Cloud Maps Platform quotas, credentials restrictions or Billing budget writes**. Do not claim zero spending before checking all of the following in the Google Cloud Console:

1. Confirm which Google Cloud project owns the production Maps browser key, and whether its billing account actually qualifies for **India pricing** (billing country and predominantly India usage). BigQuery project wecaredigitalbw is not evidence of the Maps key's ownership or billing-country eligibility.
2. Under Google Maps Platform > Quotas, inspect the counters and editable usage caps for Weather, Air Quality (including tile map requests), Dynamic Maps, Places Autocomplete/Details, Geocoding, Time Zone and Routes. As an initially conservative policy while India eligibility is unverified, try a daily Weather and Air Quality API usage cap around **200 billable events per day for each API**, if the quota unit permits; monitor whether tile requests consume the same counter. Caps may intentionally result in unavailable content when exhausted. Google only offers a paid quota model, not a cost guarantee.
3. Under APIs & Services > Credentials, limit the public browser key to HTTPS referrers https://wecare.digital/* and https://www.wecare.digital/* plus only required browser APIs. Use separate server credentials for AWS Lambda: applying browser-referrer restrictions to server requests may break the backend.
4. Add Google Cloud Billing alerts. These are **not hard spending limits**. Use API quota ceilings and restricted keys for actual protection; for BigQuery additionally configure appropriate query usage quota and per-query maximum bytes billed.
5. Check actual billed SKU counts across desktop/mobile sessions before increasing traffic.

Official references:
- https://developers.google.com/maps/documentation/weather/usage-and-billing
- https://developers.google.com/maps/documentation/air-quality/usage-and-billing
- https://developers.google.com/maps/billing-and-pricing/pricing
- https://developers.google.com/maps/billing-and-pricing/pricing-india
- https://developers.google.com/maps/billing-and-pricing/manage-costs

Note: A separate Frankfurter currency conversion tool exists in VayuLok. It is not a weather or map source.

## 4. WeatherNext 3: safely validated metadata + dry-run cost, NOT forecast accuracy

Google BigQuery linked dataset: wecaredigitalbw.weathernext_3, location US.

- The 0.1-degree view weathernext_3_0_0_0p1deg contains init_time, geography, forecast.time, forecast.hours, forecast.temperature_2m_mean and forecast.total_precipitation_1hr_mean.
- The 0.05-degree view weathernext_3_0_0_0p05deg contains station-targeted temperature/dewpoint predictions, not the full precipitation field set.
- **2026-11-02: Delhi, Kolkata and Shillong were each tested using dryRun=true only.** For 0.1-degree temperature and precipitation for up to 48h lead across recent initializations, BigQuery estimated 980,009,107,200 processed bytes **per city query**. Each reported 0 bytes billed.
- Even with LIMIT 24 and a radius filter, this linked view's nested forecast scan stays enormous. **Do not run these queries** on the public site or as a scheduled hourly job. A billable near-terabyte query per user is incompatible with free access.
- Phase 1: verify linked dataset metadata, forecast units, spatial/temporal accuracy assumptions, pricing and licensing. Phase 2: obtain a legally usable and affordable precomputed India subset / supplier export, or an approved partitioned materialization. Dry-run every proposed extraction; never execute without an owner-approved scan limit and maximumBytesBilled.
- Only after low-cost extraction: sample many lead times / dates and compare against independent verified observations. A comparison to Google's Weather API alone measures **agreement, not accuracy**. Metrics: temperature MAE, rainfall event Brier skill and temporal alignment, spatial representativeness (station vs grid), missing-data rate.
- Experimental WeatherNext forecasts are not IMD-issued warnings. Confirm weather-product use, caching, Google attribution and redistribution rights separately. Do not publish the model output directly until the licence and validation permit it.

**No WeatherNext forecast value rows were fetched; this audit only validated schema and query cost estimates.**

## 5. Current limitations / remaining work

- AWS Amplify build and source-contract tests do not prove every Google response works in every city in a real browser.
- Google Cloud quota editing and key restriction checks need Maps Platform/Cloud Billing administrative credentials, which are not connected here.
- On 2026-11-02, the earlier owner-requested presentation and automatic BigQuery history behaviors were restored to the VayuLok main map. The attribution hiding may conflict with Google Maps terms; this requires an explicit licensing review before release decisions.
