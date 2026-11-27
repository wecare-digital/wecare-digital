# Nano Climate (VayuLok) Technical Audit

Audit date: 2026-11-27 (UTC, per system and AWS clocks). Branch audited: `wecare.digital` at `62b1c01a2`. Audit branch: `audit/nano-climate-vayulok`.
Read-only audit. No production resource was changed. Evidence labels: **implemented** (code in repo), **merged** (on production branch), **deployed** (running in AWS/Amplify), **configured** (env, secret, IAM, cloud enablement present), **activated** (source enabled in the live flag set), **e2e verified** (observed in the live site with real data).

## 1. Executive summary

- Of the nine integrations, **two are end to end verified in production**: PVGIS and SPARTAN (live response for New Delhi observed in the browser, with the matching UI cards).
- The five Google/CPCB adapters in PR #2489 are all implemented, merged and deployed, but only `pvgis,spartan` are activated. **Elevation, Google Solar Building Insights are disabled by the env flag. CPCB is disabled and also not configured**: the secret `wecare/nano-climate/cpcb` does not exist and `VAYULOK_CPCB_SECRET` is not set.
- Google Weather, Air Quality, Maps JS and Places run from the browser with a public browser key and return 200. They do not go through the Lambda.
- Historical Weather (BigQuery table `weather_insights.weather_history_in`) is deployed on Cloud Run and its status endpoint reports `ready`. WeatherNext 3 and Sentinel-5P have no code, no config and no data path. They are research items only, as the repo docs also state.
- The briefing's last-reported state is stale in two places: the Lambda `live` alias is **version 8** (not 7), and production Amplify build is **#799** at `62b1c01a2` (not #789). The deployed handler code is byte-identical to the repo.
- Open risks: (a) the Google server key and billing/quota/API-enablement could not be verified because no GCP credentials exist in this sandbox; (b) the live browser key restriction is unverified; (c) the briefing URL `/vayulok/` returns 404, the page is `/atmos/nano-climate/`; (d) the API Gateway route throttle for `POST /vayulok/environment` is 2 rps / burst 4, with the 3 Lambda daily budgets enforced in DynamoDB.

## 2. Verified current deployment status

| Item | Finding | Evidence |
|---|---|---|
| Amplify app | `d22dm4b0jn71jw`, repo wecare-digital/wecare-digital, branch `wecare.digital` | `aws amplify get-app` |
| Latest builds | #799 SUCCEED `62b1c01a2` (2026-11-27 23:26Z), #798 `b076492be`, #797 `994b53f27` | `aws amplify list-jobs` |
| Build #789 | SUCCEED, commit `8719620a2`, 2026-11-27 16:07Z. Superseded by #790-#799 | `aws amplify get-job --job-id 789` |
| PR #2489 | merged 2026-11-27T14:54Z, merge commit `a8f3fe944`, ancestor of current HEAD | `gh api repos/wecare-digital/wecare-digital/pulls/2489` and `git merge-base --is-ancestor` |
| CI | `CI` and `Push on wecare.digital` success at `62b1c01a2` | `gh api .../actions/runs` |
| Lambda | `wecare-vayulok-environment`, runtime python3.14, role `wecare-vayulok-environment-role`, 512 MB | `aws lambda get-function-configuration` |
| Alias | `live` points to **version 8** (published 2026-11-27 22:55Z). Versions 6, 7, 8 and `$LATEST` all share CodeSha256 `kcpFcPrSNO18/...` | `aws lambda list-aliases`, `list-versions-by-function` |
| Deployed code vs repo | `handler.py` from the `live` code package has sha256 `8e25003b...55c7`, identical to repo `amplify/functions/core/vayulok-environment/handler.py` | `aws lambda get-function` + download + `sha256sum` |
| Lambda env (non-secret) | `VAYULOK_EXTENDED_SOURCES=pvgis,spartan`, `VAYULOK_EXTENDED_BUDGET_TABLE=stack-wecare-digital-RateLimitTable`, `VAYULOK_KEY_CACHE_TTL=300`, `VAYULOK_MAX_REQUEST_BYTES=8192`, `VAYULOK_MAX_UPSTREAM_BYTES=6291456`, `VAYULOK_GOOGLE_TIMEOUT=10`; secret name and field vars present. `VAYULOK_CPCB_SECRET` **absent** | `get-function-configuration` (secret names masked) |
| Amplify branch env | `NEXT_PUBLIC_VAYULOK_EXTENDED=true` (only VayuLok-related variable on the branch) | `aws amplify get-branch` |
| Frontend bundle | Live JS chunk contains `location_context`, `PVGIS` and `SPARTAN` strings, so the extended UI is deployed with the flag on | curl of `/_next/static/chunks/...` |
| API Gateway | `wecare-digital-api` (`zllr9lrg7j`), stage `prod`, `POST` and `OPTIONS /vayulok/environment`, auth NONE, integration to `...:function:wecare-vayulok-environment:live`, timeout 29000 ms; CORS origin `https://wecare.digital` only | `aws apigatewayv2 get-routes/get-integrations/get-api` |
| Lambda resource policy | invoke allowed only from `zllr9lrg7j/*/*/vayulok/environment` | `aws lambda get-policy` |
| Cloud Run weather insights | `https://wecare-digital-hrkl3sncxq-el.a.run.app/v1/weather-insights/status` returns `ok:true`, project `wecaredigitalbw`, dataset `weather_insights`, location US, table `weather_history_in`, `missing: []` | HTTP GET |

Distinction summary: deployed code = merged code (hash match). Activated subset = pvgis, spartan.

## 3. Integration status matrix

Legend: I=implemented, M=merged, D=deployed, C=configured, A=activated, E=e2e verified in production. Y/N/? (? = could not verify).

| # | Integration | I | M | D | C | A | E | Notes |
|---|---|---|---|---|---|---|---|---|
| 1a | Google Weather API (browser) | Y | Y | Y | ? | Y | Y | Browser `GET weather.googleapis.com/v1/currentConditions:lookup` returned 200 for Delhi and Bengaluru; page shows readings |
| 1b | Google Air Quality API (browser and Lambda `air_current`) | Y | Y | Y | ? | Y | Y | Browser `POST airquality.googleapis.com/v1/currentConditions:lookup` 200; `forecast:lookup` and `history:lookup` requests issued; page shows NAQI(IN) AQI 241 for Jaipur and a 24h history slider |
| 1c | Google Maps JS | Y | Y | Y | ? | Y | Y | Map tiles load (`gen_204` 200), no console errors |
| 1d | Google Places (Autocomplete) | Y | Y | Y | ? | Y | Y | `AutocompletePlaces` 200; search for "Jaipur" returned suggestions |
| 2 | Google Elevation | Y | Y | Y | ? | **N** | N | Not in `VAYULOK_EXTENDED_SOURCES`. Live response: `"elevation":{"status":"disabled"}` |
| 3 | CPCB (data.gov.in) | Y | Y | Y | **N** | **N** | N | Live response `"cpcb":{"status":"disabled"}`. Secret `wecare/nano-climate/cpcb` returns ResourceNotFoundException; env var absent |
| 4 | PVGIS | Y | Y | Y | Y | Y | **Y** | Live: 4,867.94 kWh/yr, 2,163.68 kWh/m2/yr, grid 28.61/77.21, 3 kWp, 14% loss; UI card "Regional solar potential" rendered |
| 5 | Google Solar Building Insights | Y | Y | Y | ? | **N** | N | `"solar":{"status":"disabled"}`; also only called when `buildingCandidate` is true |
| 6 | Historical Weather (BigQuery) | Y | Y | Y | Y | ? | Partial | Cloud Run status `ready`, table found with all columns. No data query was run (cost rule). UI path through `VayuLokWeatherInsights.tsx` not exercised |
| 7 | WeatherNext 3 | N | N | N | N | N | N | Only mentioned in docs as remaining work |
| 8 | SPARTAN | Y | Y | Y | Y | Y | **Y** | Live: site Delhi/INDH, 7.83 km, PM2.5 44.03 ug/m3, 2026-07-19 to 2026-07-20, 12 h, method filter. Card text states historical, not live AQI |
| 9 | Sentinel-5P | N | N | N | N | N | N | Docs only; no processing workflow |

## 4. Source vs production discrepancies

1. Lambda alias is version 8 in production; the briefing and prior reports say 7. Versions 6, 7, 8 are the same code (hash `kcpFcPrSNO18/...`). Version 8 runs on python3.14, version 7 ran on python3.12 (CloudWatch INIT lines), consistent with the later CloudFormation runtime change (#2513, `994b53f27`). Harmless, but the handoff note is outdated.
2. Production Amplify build is #799, not #789; HEAD is 10 builds past the activation build.
3. The page is `https://wecare.digital/atmos/nano-climate/`. `https://wecare.digital/vayulok/` and `/vayulok` return 404. The repo comments in `src/pages/_document.tsx` and `src/pages/index.tsx` still reference `/vayulok/` (stale comments, not functional).
4. Code and env: `handler.py` hard-codes `RATE_TABLE`, and the env var must match it exactly; it does. `VAYULOK_CPCB_SECRET` is required to equal `wecare/nano-climate/cpcb`; it is unset and the secret does not exist, so CPCB cannot work even if added to the source list.
5. No deployed-versus-repo drift in `handler.py`. The frontend chunk matches the repo feature set; a full bundle diff was not done.
6. `docs/nano-climate-environment-data.md` says `configure_nano_climate_sources.py` configures `$LATEST` only and the alias is moved afterwards. Observed: `$LATEST` and version 8 are identical. No drift.

## 5. Security and credential audit

- No secret values were read. `secretsmanager describe-secret` only. Secrets observed (names): `wecare/google/cloud` (server key, last changed 2026-10-03, last accessed 2026-10-26 per Secrets Manager date granularity), `wecare/google-maps` (browser key, changed 2026-10-14), `wecare/google/ads`, `wecare/seo/google-oauth`.
- Lambda IAM (inline): `ReadVayuLokGoogleServerKey` allows `secretsmanager:GetSecretValue` on `wecare/google/cloud-*` only, and `kms:Decrypt` restricted by `kms:ViaService=secretsmanager`. `NanoClimateExtendedSources` allows only `dynamodb:UpdateItem` on `stack-wecare-digital-RateLimitTable` with `LeadingKeys` limited to `nano-climate:environment:*`. Managed policy: `AWSLambdaBasicExecutionRole`. Least privilege holds. There is no CPCB secret permission yet (will need adding when CPCB is configured).
- API Gateway route auth is NONE (public by design), CORS limited to `https://wecare.digital`, invoke permission scoped to the route. Request size capped at 8192 bytes; upstream response capped at 6 MiB; handler validates field allow-lists.
- **Browser key exposure (by design, needs verification)**: the browser sends the Google browser key in request URLs to Google (visible in network traffic). This is the standard public browser-key model and the build reads it from `wecare/google-maps`. Its HTTP referrer and API restrictions could **not** be verified (no GCP credentials). The value is intentionally not reproduced in this report. Recommendation: confirm in the Cloud Console that it is restricted to `https://wecare.digital/*` and to the Maps JS, Places, Weather and Air Quality APIs only.
- The server key is separate from the browser key. Whether it is restricted to Elevation and Solar APIs and to AWS egress cannot be checked from here.
- The sandbox contains a file `/tmp/access_token` that was not created by this audit; it was not opened or used.
- No secret values appear in this report (pattern grep for key prefixes returned nothing).

## 6. API usage, quota and billing audit

Budget guard (code `handler.py` `_reserve_extra`): one DynamoDB `TransactWriteItems` with two conditional updates (daily UTC and monthly), `attribute_not_exists OR count < cap`, fail closed on any error, no refunds. Caps in code match the required values exactly: elevation 100/3100, cpcb 24/744, pvgis 250/7750, solar 250/7750, spartan 12/372.

Live counters (table `stack-wecare-digital-RateLimitTable`, 77 items, 4 with prefix `nano-climate:environment:`), scanned before the browser test:

| Key | providerAttempts |
|---|---|
| pvgis day 2026-11-27 | 2 |
| pvgis month 2026-11 | 2 |
| spartan day 2026-11-27 | 2 |
| spartan month 2026-11 | 2 |

The audit's browser sessions each caused roughly one more attempt per active source (the Delhi default selection). Counters are far below caps (SPARTAN daily cap 12 is the tightest). Note the Lambda uses a 300 s result cache, which limits repeats.

Other guards: API Gateway stage `prod` route `POST /vayulok/environment` throttle rate 2.0, burst 4; `OPTIONS` rate 3, burst 10. Cloud Run `HARD_MAX_BYTES_PER_QUERY = 1073741824` (1 GiB) enforced via `maximumBytesBilled` per range in `gcp/vayulok-weather-insights/server.mjs`. The frontend debounces 350 ms, aborts previous requests, no polling.

Not verifiable (no GCP credentials; `gcloud` and `bq` absent, no ADC, metadata server unreachable): Service Usage API enablement, key restrictions, billing account status, Google quota values (Elevation, Solar, BigQuery 10 GiB/day project quota), BigQuery table sizes and dry runs. These remain **blocked** and no BigQuery query was attempted.

## 7. Data accuracy, coverage and freshness

- PVGIS (Delhi 28.6139, 77.209): values are internally consistent: monthly sum approx 4,868 kWh, peak month March (476.9), trough July (297.2) matching monsoon. Result is a long-term regional model (the card says so). Coverage is global where PVGIS has data; the adapter returns `no_data` on 404.
- SPARTAN: three India sites verified in code (Delhi, Jaipur filter data; Kanpur estimated). The Delhi observation is from July 2026 (about four months old), shown with explicit dates and a "historical, not live" caption. Max distance 50 km. This is correct labelling, not stale live data.
- Google AQ: Jaipur AQI 241 (NAQI IN, PM2.5 192, PM10 270); the history slider shows readings with IST times. A discrepancy to note: the on-globe label for Bengaluru showed "AQI 41 Moderate" and Jaipur earlier "AQI 76 Good" on the globe while the same page's detail panel shows 225 to 241 Poor for the selected place. Those are different places and times, so this is not proven wrong, but the globe label wording ("Moderate" for 41, "Good" for 76) was not cross-checked against the NAQI band tables. Recommend a spot check.
- CPCB, Elevation, Solar: no data (disabled). Not fabricated: the UI simply omits the cards.
- Historical weather: table exists with the expected columns. Row counts, date range and freshness not checked (would need BigQuery metadata access).

## 8. Frontend and browser verification

Tool: Playwright MCP (Chromium). URL: `https://wecare.digital/atmos/nano-climate/`.
- Desktop 1440x900: title "Nano Climate, Bharat air and weather insights | WECARE.DIGITAL", 0 console errors, 4 to 5 warnings (WebGL "GPU stall due to ReadPixels" performance messages from the globe iframe, benign).
- Network on load: `POST airquality.googleapis.com/v1/currentConditions:lookup` 200, `GET weather.googleapis.com/v1/currentConditions:lookup` 200 (Delhi and Bengaluru), `GET wecare.digital/api/site-language/languages` 200, `POST wecare.digital/api/vayulok/environment` 200, Places `AutocompletePlaces` 200. No 4xx or 5xx seen.
- `POST /api/vayulok/environment` response (`operation: location_context`): elevation disabled, cpcb disabled, solar disabled, pvgis ok, spartan ok (full payload recorded in section 3).
- UI: "Environmental insights" region shows "Regional solar potential" and "SPARTAN research observations" with attribution links and disclaimers.
- Mobile 390x844: layout renders (header, hero, globe, search box, results list) with no overflow visible in the screenshot and 0 console errors. Only the first viewport was inspected on mobile; the extended cards were not scrolled on mobile.
- Not tested: the Weather tab, route/world-time tools, language switch, WhatsApp/contribute buttons.
- Searching "Jaipur" updated the detail panel AQI to Jaipur values, but the extended cards still displayed Delhi coordinates (28.61, 77.21) and the Delhi SPARTAN site in the captured snapshot. This may be a snapshot timing issue (the cards request is debounced 350 ms and requires the viewport gate) or a stale-card bug. **Needs a retest with an explicit wait**; it is not claimed as a defect.

## 9. Root causes

1. Elevation, Solar and CPCB are inactive because the activation script was applied with only `pvgis,spartan` (Lambda env). The code and budgets for all five exist. This matches the documented rule that Google sources require `--confirm-google-key-and-billing`, which has not been done or could not be confirmed.
2. CPCB additionally lacks its secret `wecare/nano-climate/cpcb`, its env var, and an IAM statement to read it. Needs a real data.gov.in API key supplied by the owner.
3. Stale handoff facts (alias 7, build #789, `/vayulok/` URL) come from reporting at activation time (2026-11-27 16:07Z); later pushes created version 8 and builds #790 to #799 after the python runtime change.
4. WeatherNext 3 and Sentinel-5P have no integration because licensing, access and a bounded read plan are unverified (per docs), not because of a defect.
5. GCP-side items are unverified because the sandbox has no Google credentials.

## 10. Prioritized remediation plan with blockers

| Priority | Action | Blocker / needs |
|---|---|---|
| P0 | Provide GCP read-only access (service account or Workload Identity) for Service Usage, API Keys, Billing and BigQuery metadata, then verify key restrictions, billing and quotas | Owner credential not available in sandbox |
| P0 | Confirm browser key restriction to `https://wecare.digital/*` and the four browser APIs; confirm server key restricted to Elevation and Solar APIs | Needs P0 access |
| P1 | Activate Elevation (100/3100): add `elevation` to `VAYULOK_EXTENDED_SOURCES` through `scripts/configure_nano_climate_sources.py` with `--confirm-google-key-and-billing`, validate on `$LATEST`, then move alias through the normal workflow, then one browser check | Needs P0 confirmation that Elevation API is enabled and billed |
| P1 | Activate Solar Building Insights (250/7750) the same way; only triggers on building-sized viewports | Needs Solar API enabled; note Solar returns coverage only for mapped buildings |
| P1 | CPCB: obtain data.gov.in key, create secret `wecare/nano-climate/cpcb` with `api_key`, extend Lambda IAM, set `VAYULOK_CPCB_SECRET`, add `cpcb` to sources (24/744 is very tight: 24 calls a day total, so rely on the snapshot cache) | Needs owner to supply the key and registration |
| P2 | Retest the extended cards after changing place (section 8 observation), including on mobile scroll | None |
| P2 | Update stale `/vayulok/` mentions in comments and the handoff docs; record alias version 8 and build #799 | None |
| P2 | Historical weather: with BigQuery access, run metadata-only checks (table size, date range) and dry runs for the 30d/1y/5y queries to confirm each stays under 1 GiB | Needs P0 access |
| P3 | WeatherNext 3: confirm Earth Engine or BigQuery access terms, licensing and a bounded read plan before any code | Licensing and access decision |
| P3 | Sentinel-5P: choose a permitted L2/derived product, processing path and quality flags before any code | Product and cost decision |

## Appendix A. Baseline (branch `audit/nano-climate-vayulok`, node 22.23.4)

- `npm ci`: success.
- `npm test`: 334 tests, 334 pass, 0 fail (exit 0).
- `npm run lint`: 0 errors, 243 warnings (exit 0, within the repo's warning budget ratchet).
- `npx tsc --noEmit`: exit 0, no output.

## Appendix B. Limits of this audit

- Official provider documentation (CPCB data.gov.in, PVGIS, Google Solar, WeatherNext 3, SPARTAN, Sentinel-5P) was not re-fetched during this run; only the repo's linked official URLs in `docs/nano-climate-environment-data.md` and the live provider responses were used. Provider terms and rate limits should be reconfirmed during the activation work.
- Live probing was limited to the normal page load and one place search, to preserve quotas. No direct curl to the production API was made.
- CloudWatch logs for the last 24 h show only INIT/START/END/REPORT lines and the "Found credentials" message; no budget or provider warnings were logged.
