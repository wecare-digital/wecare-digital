# VayuLok India 2D Map + Free-Tier Safeguards (2026-11-02)

## Scope and strict preservation
- Only the **main Google Maps 2D Air/Weather map**, frontend weather-history caching and the separate Cloud Run history service are in scope.
- The decorative globe and its assets remain untouched.
- Preserve the previously user-restored Google Maps attribution CSS behavior. **This is not evidence of licence compliance**; Google's branding requirements still need independent review.
- Leave WeatherNext 3 linked datasets, source values, and the existing automatic weather-history component in place. Do not mistake Google Weather API predictions for standalone WeatherNext 3 ensemble data.

## Frontend changes (AWS Amplify / Next.js)
- In the revised layout, wide screens give the full 2D India map its own sticky column alongside the complete Air/Weather card. The card scrolls with the page, not inside a cropped overlay; Google attribution stays unobscured.
- At 1050px and below, display a full-size India map (tablet height 460–720px, phone height 440–640px), followed by the full Air/Weather card. Hide the duplicate floating mobile summary and preserve India-wide fitBounds until an explicit city is selected.
- Keep AQI readings/forecast automatic but start with the **paid AQI/PM2.5 heatmap tile overlay off**. The user can still switch it on intentionally. Map JS and other provider requests remain lazy near the viewport.
- The long-term history remains automatic when Weather is displayed, but **every uncached request including 30D first checks the deployed Cloud Run 1 GiB guard** and fails closed if it is not verified. Requests use the ~0.1-degree grid; browser history summaries persist for 24 hours (up to 48 entries), with a seven-day stale fallback.
- Show actual history coverage dates and grid distance when present. If the server enforces budget, display an honest unavailable message rather than fabricated readings.

## Cloud Run history service code (separate deployment required)
- Enforce an absolute **1 GiB maximum BigQuery billed bytes per query**, even if older environment settings request 15 GB for 1Y or 40 GB for 5Y. Cost-unsafe 1Y and 5Y uncached scans will fail closed **until precomputed low-cost summaries exist**; the 30D tab remains automatic.
- Allow at most eight fresh query attempts per UTC day **per Cloud Run process**, bounded at twelve even if environment settings request more. This is defence in depth, **not a project-level cap**; several instances, restarts, and other project users can exceed it.
- Coalesce in-flight requests for the same 0.1-degree grid/range, use aligned rounded coordinates for BigQuery result cache, bound in-memory entries, and label expired cache results as stale.
- The Cloud Run service must be **deployed independently** using the existing gcp/vayulok-weather-insights/cloudbuild.yaml pipeline. Merging to AWS Amplify alone does **not** deploy this service.

## Still required in Google Cloud Console before claiming zero overage risk
1. Project wecaredigitalbw: configure a custom **BigQuery daily query usage quota** around **10 GiB/day** or lower as an initial conservative value, validate it applies to all relevant workloads/users, and monitor the actual project-billed bytes. The current connector cannot write service quotas. As a comparison, the monthly BigQuery free allowance is 1 TiB of on-demand query processing subject to eligibility/pricing conditions.
2. Confirm the production Maps browser key's **owning Google Cloud project and India-pricing eligibility**. BigQuery project identity does not prove either.
3. Set Google Maps Platform API SKU daily quotas that, across 30–31 days and all usage, stay within the relevant monthly per-SKU allowances. Include Air Quality tiles, current/history/forecast, Weather, Places Autocomplete, Dynamic Maps, Geocoding, Time Zone and Routes, with budget for other pages sharing the key. Some quota units and dimensions differ: verify actual billable units rather than assuming one page view = one event.
4. Restrict browser-key HTTP referrers to approved web origins, restrict permitted APIs, keep server keys separated, and add billing alerts. Alerts are **not hard spend ceilings**.
5. Verify whether Cloud Run instance scaling and billed BigQuery statistics match assumed usage. Consider a genuinely shared persistent precomputed history cache; browser localStorage and Cloud Run's in-memory cache are **not** cross-user/cross-instance shared persistence.
6. Review Maps/Weather/Air Quality and WeatherNext commercial licensing and attribution compliance before commercial release.

## Verification matrix
- Build TypeScript, execute scripts/check_vayulok_cost_and_map.cjs in the production gate and check Cloud Run server.mjs syntax.
- Review responsive viewports at 390x844, 768x1024, 1024x768 and 1366x768; inspect India, islands, attribution, page-scrolling card, correct narrow-screen stacking, and city-search recentering.
- In a browser, check initial Air view makes zero **heatmap tile** requests until switching on Heatmap; regular weather/AQI calls may still occur. On desktop, scroll the whole card and confirm map stickiness does not obscure controls or provider attribution.
- In Weather mode, verify history attempts are automatic, cached data survives reload and **30D/1Y/5Y all fail closed with an honest budget message** if the live Cloud Run guard is absent or unsafe.
- For Cloud Run, deploy separately and verify actual service revision; do not conflate AWS Amplify success with GCP Cloud Run. Do not run unbounded WeatherNext 3 BigQuery queries.

## Remaining limitation
The frontend changes reduce unnecessary event consumption, and the backend code has extra query caps. **No frontend-only safeguard guarantees the Google Maps Platform or BigQuery monthly free limits.** Only actual project-level quota and billing controls plus licensing verification can support that claim. Google Weather API terms also restrict weather-first products; obtain written permission before relying on it as the public product's primary data engine.

## Long-range production fail-closed bridge
- Before the Google Cloud Run server revision is deployed and verified, the public website **does not send any uncached 30D/1Y/5Y queries** to the older 1.2GB/15GB/40GB-budget backend. It first checks the separate Cloud Run status endpoint for an active maximum of <=1 GiB; otherwise it uses saved browser results or shows the budget-protection message.
- The Cloud Run `/v1/weather-insights/status` response must include CORS for the approved VayuLok origin as well as `costGuard` metadata. The static website can check the guard on each longer-range selection without any billable BigQuery query.
- This protection is deliberately consistent across all ranges: the automatic 30D history component remains mounted, but no uncached BigQuery history request is sent until the independently deployed Cloud Run revision passes the guard check.
