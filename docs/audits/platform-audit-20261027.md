# WECARE.DIGITAL platform audit, 2026-10-27

Audited commit `2f7ca2979` (the tip of `wecare.digital` on 2026-10-27, after a fast-forward of 32
commits). Repository changes from this audit are on branch
`audit/platform-performance-cost-seo-20261027`; nothing was pushed, merged or deployed. The branch
has since absorbed the base up to `ddbacf8b5` (a merge into the audit branch, not into
`wecare.digital`; see section 12).

**Revision, evening of 2026-10-27.** A re-check of the earlier claims corrected five of them:

- The Public UI compliance workflow is one day old; it is not "200 runs red".
- Each "one-hour" access-log sample covered about two hours.
- Six of Compute Optimizer's 19 findings are under-provisioned memory; the earlier text said all
  19 were over-provisioned.
- The blog-fetch cost is now computed rather than given as a range.
- The cost plan's image saving fell from $9.99 to $2.63 a month.

The base also moved while this audit ran: another session's #1722 made part of the build fix and
the hashed-asset caching live. The branch now includes the base, and the cost plan's C1 and
scenarios account for it (section 12).

This revision also adds the dependency audit (section 8a) and the 27 October egress spike
(section 7a).

## How to read this document

Every claim carries one of these evidence levels:

| Level | Meaning |
|---|---|
| **Code** | Read in the repository at `2f7ca2979`. |
| **Local** | Built and exercised locally (static export, Chromium/WebKit, Lighthouse, unit tests). |
| **Cloud-read** | Read from account `775261844268` with read-only calls on 2026-10-27. |
| **Deployed / E2E** | Not reached by this audit for any change. |

Live evidence collection was read-only: List/Describe/Get calls, CloudWatch `GetMetricData`,
nine Cost Explorer requests (about $0.09), Amplify access logs for sampled windows aggregated in
memory (no client IPs stored; see section 3 for why each window is about two hours), the Amplify
job list, CloudTrail `LookupEvents` for KMS key usage, the GitHub Actions API for workflow runs,
the three Lambda layer archives (file names only, for package versions), and OSV.dev for
dependency advisories. No secret value was read;
environment variables were recorded by name only. Raw evidence stays in the gitignored
`.scratch/audit-2026-10-27/` tree.

## Priority summary

P0 = security, data loss or production break. P1 = major cost, performance or crawl failure.
P2 = meaningful reliability, UX or maintenance. P3 = cleanup.

| # | P | Finding | Evidence | Status |
|---|---|---|---|---|
| 1 | P0 | Short-link service: stored XSS on the apex origin (`iosUrl: "javascript:..."` written raw into an inline script), open redirect, and any staff role could overwrite any existing code | Code | Fixed on branch, needs deploy (owner) |
| 2 | P1 | Every public page downloaded the full Material Symbols variable font: **3,124,872 bytes** for about 17 icons, `display=block` | Local, Cloud-read | Fixed on branch: **15,788 bytes** |
| 3 | P1 | `/shop/` cards serve 4096×4096 PNG masters (2.0-2.6 MB each, 28 images, 72 MB total); Lighthouse counts 14.6 MB of images and a 27-45 s simulated LCP | Local, Cloud-read | Needs owner-approved derivative upload |
| 4 | P1 | Amplify builds are the largest technical cost: 5,683.8 build-minutes ($56.84) Oct 1-26; 55% of builds (140 of 256) changed no frontend file; ~94 s of each ~252 s build was fixed overhead | Cloud-read | Part live: #1722 on the base (npm download cache, −26 s measured). The branch removes 51 s more (nvm). Path-filtered triggers need owner |
| 5 | P1 | `aws-amplify`, the 285 KB staff API client and seven Capacitor plugins shipped in the bundle every public page shares | Local | Fixed on branch: −44.7 KB brotli JS per public page |
| 6 | P1 | Business Support+ is billed on two accounts ($29 minimum each); the backup account `…5408` started on Oct 17 | Cloud-read | Owner decision |
| 7 | P2 | Invoice HTML (a downloadable customer deliverable) interpolated customer name/address/item names unescaped | Code | Fixed on branch, needs deploy |
| 8 | P2 | `www.wecare.digital/<path>` 302s to the home page, dropping the path; the redirect script kept re-asserting an apex-to-apex "host" rule | Cloud-read, Code | Fixed in IaC on branch, needs owner publish |
| 9 | P2 | Test harnesses (CI and local) load production media and the blog API: in one sampled window (05:00-07:00 UTC on 10-27), headless Chromium caused 3.03 GB of catalog-media and 0.75 GB of `/get/` egress | Cloud-read | Recommendation |
| 10 | P2 | `/api/` Disallow in robots.txt hid every product image | Code | Fixed on branch |
| 11 | P2 | 85 CloudWatch alarms, 75 billable ($7.50/month), all OK | Cloud-read | Owner decision |
| 12 | P2 | Sinch RCS delivery webhook accepts unsigned `MESSAGE_DELIVERY` callbacks until a webhook secret exists | Code | Owner action (Sinch console) |
| 13 | P3 | Structured-data and metadata defects (Organization `geo`, hard-coded `InStock`, latent FAQPage, sitemap had no noindex filter, contradictory `googlebot` meta, 46-character `/blog/` description) | Code, Local | Fixed on branch |
| 14 | P3 | No AWS Budget exists in the account | Cloud-read | Owner decision |
| 15 | P1 | The Public UI compliance workflow, added on 2026-10-27, failed all 62 runs that had finished by 15:35 UTC that day (0 passed). Each run builds twice against the production blog API and loads production media: Amplify served 18.46 GB in the first 15 hours of 10-27, against 2.99 GB in the same hours on an average prior day (about 0.26 GB, $0.04, per run). Some CI builds fail on HTTP 429 from the blog API | Cloud-read | Recommendation; the harness is another workstream's active work |
| 16 | P2 | Bulk queue: visibility 2.5x the worker timeout (AWS guidance is at least 6x), maxReceiveCount 3 (guidance at least 5), and the worker swallows per-record errors, so its dead-letter queue can never receive a message | Cloud-read, Code | Owner decision (queue config + code together) |
| 17 | P1 | Production Lambda layers ship Pillow 12.1.1 (59 advisories, 5 critical, all fixed in 13.0.0) to `checkout`, `commerce`, `invoice-engine` and `product-image-gen`; `product-image-gen` gets it from a third-party public layer. The `cryptography` layer is 46.0.5 (3 high advisories); dev and CI pin Pillow 13.0.0 and cryptography 50.0.2 | Cloud-read, Code | Owner decision (layer rebuild + deploy) |
| 18 | P2 | Build-time blog fetches cost about $12.13 a month at the 14-26 October rate. DynamoDB reads rose 17.6x when `wecare-blog-public` took over the blog routes on 13 October; 56% of the blog table's reads now come from the five whole-corpus listing queries each build makes | Cloud-read, Code | Recommendation |

## 1. Architecture map

### Frontend (Code)

- Next.js 16 pages router, React 19, TypeScript 6, static export (`output: 'export'` in
  production, `trailingSlash: true`, `images.unoptimized`). 74 files under `src/pages`, 1,594
  exported pages, 1,523 sitemap URLs (1,424 blog posts).
- **Public routes** (30 in `config/public-pages.json`): `/`, product pages on the shared
  `ProductPage` template (Dastavez, Elsewhere, Hunar, Ritual Guru, Expo Week, Anew, Niji Setu,
  Shipments), bespoke pages (`/grahak-os`, `/sehat`, `/vayulok`, `/contact`, `/terms`, `/privacy`,
  `/orders`, `/shop`), the blog family (`/blog`, pagination, topic streams, `/post/[slug]`) and
  service-request pages.
- **Public noindex utilities**: `/404`, `/get`, `/cart`, `/checkout`, `/checkout/status`,
  `/checkout/success`.
- **Authenticated**: 31 files under `src/pages/workspace/**`, rendered inside the lazily loaded
  `AuthShell` (Amplify UI Authenticator, `ssr: false`).
- `_app.tsx` (1,232 lines) owns the public/authenticated split, the sitewide head and JSON-LD, and
  mounts `Header`, `Footer`, `PublicShare`, `PublicPolicyDetails` and `SupportWidget` on public
  routes. `_document.tsx` loads Inter and Material Symbols from Google Fonts, the GTM container
  (Consent Mode default **denied**) and the Meta Pixel on every route.
- Global CSS: 10 files imported by `_app` (456,652 bytes of source), shipped as 3 render-blocking
  chunks (33.7 KB brotli). Workspace-only rules (`.sidebar`, `.dashboard`, `.layout`) are part of
  that global bundle.
- Customer sign-in does not use Amplify: `src/lib/customerAuth.ts` talks to the customer Cognito
  pool's REST API directly. Staff sign-in uses Amplify Auth against the staff pool.
- Large components: `VayuLokLive` 5,290 lines, `CartPage` 2,105, `WorkflowTerminal` 1,432,
  `SupportWidget` 1,294, `Header` 1,273. `API_BASE` is declared in 19 files although
  `config/constants.ts` exports it.

### Backend (Code, Cloud-read)

- 74 live Lambda functions (73 `python3.12` zip, 1 container image), 75 source directories under
  `amplify/functions/{ai,auth,core,ecommerce,edge,messaging,operations,payments}` plus
  `shared/lambda_utils`. `auth/blog-subscribe` contains only `__pycache__` (dead).
- Deployment is script-driven: `scripts/deploy_all_lambdas.py` (publish + move `live` alias for
  70 aliased functions), with delegated owners for `wecare-seo-tools`, `wecare-mcp`,
  `wecare-blog-public`, `wecare-workspace-mcp` and `wecare-customer-commerce-mcp`. The Amplify Gen 2
  `backend.ts` imports only auth, data and storage; the seven `resource.ts` files under functions
  are not wired up. Memory, timeout and architecture for about 50 functions exist only in the live
  account (set at creation by provisioning scripts).
- One HTTP API (`wecare-digital-api`, 376 routes, stage `prod`, access logs on) behind
  `https://wecare.digital/api/*` (an Amplify rewrite), plus six single-purpose MCP HTTP APIs. 374
  routes use `AuthorizationType NONE` and authenticate inside the handler (`require_auth` for
  staff, `customer_auth` for customers).
- Triggers: 4 event-source mappings (ProductsTable stream to two `meta-catalog-sync` aliases,
  bulk queue, notification queue **Disabled** by design), 9 EventBridge rules, 1 Scheduler schedule
  (SEO freshness), Cognito triggers on both pools, one Lambda@Edge origin-response function on the
  `/get` distribution, one SNS subscription.

### Request paths (Cloud-read)

```text
Browser ── wecare.digital (Amplify Hosting, app d22dm4b0jn71jw, CloudFront managed by Amplify)
   ├── /_next/static/*, *.html ........ static export (no-store everywhere at audit time;
   │                                     /_next/static immutable since #1722)
   ├── /api/<*>  ── 200 rewrite ──► API Gateway zllr9lrg7j /prod ──► Lambda (`live` alias)
   ├── /get/<*>  ── 200 rewrite ──► CloudFront E2GP22R4BIFGQ3 ──► S3 wecare-digital-get
   │                                   └── Lambda@Edge wecare-get-miss-redirect (origin-response)
   ├── /r/<*>    ── 200 rewrite ──► API Gateway ──► stack-wecare-url-shortener
   ├── /auth     ── 200 rewrite ──► API Gateway mtx59syrt6 (customer-commerce MCP)
   └── /<*>      ── 404-200 ──────► /404.html (redirects home)
*.wecare.digital (incl. www) ──► CloudFront E1IY68ICLQP3PY ──► CloudFront function (302 home)
sip.wecare.digital ──► Lightsail nano (voice bot, SIP/RTP)
```

## 2. Live AWS inventory (Cloud-read, 2026-10-27)

| Service | Count | Notes |
|---|---:|---|
| Lambda | 74 | 73 x86_64, 1 arm64 (`wecare-workspace-mcp`); 0 VPC, 0 SnapStart, 0 provisioned concurrency, 0 function URLs; 70 with a `live` alias; 2 reserved-concurrency limits |
| DynamoDB | 76 | All on-demand, all PITR, 75 with deletion protection, 31 with TTL, 2 streams, 11.7 MB total, 38 empty |
| CloudWatch Logs | 90 | 72 at 30 days, 8 CodeBuild groups with no retention, 3.76 GB ingested in 30 days (inside the 5 GB free tier) |
| CloudWatch alarms | 85 | All `OK`, all with actions; 1 dashboard |
| API Gateway | 7 HTTP APIs, 0 REST | 406 routes |
| SQS / SNS | 8 / 2 | All queues empty; one alarm topic, one Lambda subscription |
| EventBridge / Scheduler / Step Functions | 10 rules / 1 / 0 | |
| Amplify | 1 app, 1 branch | `STANDARD_8GB` builds, auto-build on, no PR previews |
| CloudFront | 3 | `/get` media (407k requests, 12.1 GB / 30 d), wildcard fallback, MTA-STS |
| S3 | 8 | `wecare-digital-get` 1.56 GB with same-account (us-west-2) and cross-account replication |
| Secrets Manager | 17 active, 10 scheduled for deletion | |
| KMS | 4 customer-managed keys | All used in the last 30 days (CloudTrail) |
| Lightsail | 1 nano instance + static IP | Voice bot behind `sip.wecare.digital`; the micro standby was deleted mid-October |
| ECR | 2 repos | `wecare-docs-scraper`: 13 images, 12.0 GB, no lifecycle policy |
| Cognito | 2 pools (ESSENTIALS) | Staff (CustomMessage trigger), customers (3 custom-auth triggers) |
| Route 53 | 1 zone, 25 records | 0 health checks |
| Other | | 1 CloudTrail trail, 1 Backup plan, IAM Access Analyzer; **no** GuardDuty, Security Hub, AWS Config or AWS Budgets; 0 EC2, NAT, EIP, EBS, RDS, ELB, OpenSearch, AppSync |
| Organization | 2 accounts | This management account and `…5408` (cross-account backup) |

## 3. Cost baseline (Cloud-read, Cost Explorer)

All figures are gross charges before credits. **Credits netted every month to $0.00 cash**
(August, September and October to date). Credit balance and expiry are not exposed by the Cost
Explorer API; the owner must read them in the Billing console. Until credits run out, a saving
extends the credit runway rather than reducing cash spend.

| Month | Usage | Support | Gross total | Credits | Net |
|---|---:|---:|---:|---:|---:|
| 2026-08 | 32.73 | 29.00 | 61.73 | −61.73 | 0.00 |
| 2026-09 | 72.30 | 29.00 | 101.30 | −101.30 | 0.00 |
| 2026-10 (1-26) | 102.36 | 42.81 | 145.17 | −145.17 | 0.00 |

Cost Explorer forecasts $169.84 gross for October and $147.04 for November.

October to date by service and usage type:

| Service | Usage type | $ | Quantity | Classification |
|---|---|---:|---|---|
| Amplify | Build duration | 56.84 | 5,683.8 min | Optimizable (overhead + redundant builds) |
| Business Support+ | Fee | 42.81 | $29 (4268) + $13.81 (5408, from Oct 17) | Owner-controlled subscription |
| Amplify | Data transfer out | 13.32 | 88.8 GB | Optimizable (blog API about 20%, test traffic, oversized images; `no-store` on hashed assets until #1722) |
| Secrets Manager | Secrets | 7.43 | 18.6 secret-months | Production baseline (consolidation possible) |
| CloudWatch | Alarms | 5.00 | 60.0 alarm-months | Optimizable / owner decision |
| API Gateway | HTTP requests | 3.73 | 3.73 M | Variable; mostly build-time blog fetches |
| Lightsail | 1 GB + 0.5 GB bundles | 5.15 | 346.5 + 281.8 h | Baseline (micro already retired) |
| KMS | Keys | 3.24 | 3.24 key-months | Production baseline |
| End User Messaging | Toll-free number + SMS | 1.95 | | Baseline |
| DynamoDB | Read request units | 1.66 | 13.28 M RRU | Variable; mostly build-time blog reads |
| Lambda | GB-s + requests | 1.29 | 444k GB-s, 3.73 M requests | Variable |
| S3 | Tier-1 requests | 0.58 | 116k | Baseline (CloudTrail delivery, replication) |
| Route 53 | Zone + queries | 0.59 | | Baseline |
| Cost Explorer | API | 0.40 | 40 requests | Historical (September's 1,507-request storm is fixed) |
| ECR | Storage | 0.27 | 2.7 GB-month | Optimizable (no lifecycle) |

**Where the Amplify charge comes from.** Amplify's list price is $0.01 per build-minute on the
Standard instance and $0.15 per GB served ([pricing](https://aws.amazon.com/amplify/pricing/)).
Builds run on every push to `wecare.digital`; 24-26 October averaged 81 builds a day at a median
4.3 minutes. Diffing each successful build against the previous one: **116 changed a
frontend input, 136 changed only backend/docs/test paths, and 4 changed nothing**. Of each
~252 s BUILD step, ~51 s re-installed the image's 1,692 default global npm packages (`nvm install`)
and ~43 s retrieved, extracted, re-created and uploaded a `node_modules` cache that `npm ci`
deletes unread. Later on 27 October, #1722 on the base replaced that cache with npm's download
cache (`.npm`). Measured on Amplify: the BUILD step fell from a mean of 256.9 s (jobs 255-280, 24
builds, standard deviation 17.7 s) to 230.4 s (jobs 281-285), and the cache upload from about
35 s to about 12.5 s. The `nvm` re-install is still in every build until this branch merges.
The fetch of the blog corpus during the build (1,424 per-post requests plus 5
listing requests per build, through the apex `/api` rewrite; a sampled window of ten builds
measured 1,433 requests and 5.1 listing calls per build) is also what drives most API Gateway
requests, Lambda invocations (`wecare-blog-public`, 2.29 M in 30 days) and DynamoDB reads. Over
14-26 October, `wecare-blog-public` averaged 162,440 invocations a day, 90% of all API Gateway
requests. On 24-26 October, Amplify builds (81 a day) account for 77% of those invocations.

**How the access-log samples were read.** Amplify's `GenerateAccessLogs` returned about two hours
of rows for every one-hour request (for example, 05:00-06:00 UTC returned 05:00:10-06:59:59). In
the eight windows checked, the row count matched CloudWatch `Requests` for those two hours within
1%. The samples are therefore used for shares, not hourly rates.

**Where Amplify data transfer comes from.** The window requested as 05:00-06:00 UTC on 10-27
covered 05:00-07:00 UTC (95,210 requests). It attributed 3.03 GB to `/api/catalog-media/*` (4096 px
PNGs) and 0.75 GB to `/get/` logo/favicon, almost all from headless Chromium on `127.0.0.1`
referers, which is the browser test harness running against production media. 70% of requests in
that window were `/api/*` proxying. Over 14-26 October, blog-API responses were about 20% of
Amplify data transfer (0.64 of 3.18 GB a day: invocations × 3.92 KB per response).

## 4. Performance baseline and result

Measured with Lighthouse 13.5 (mobile, simulated throttling) against the static export served
locally with brotli and the production `no-store` headers, three runs each, median. Localhost
removes CDN latency, so absolute timings are optimistic; byte counts are exact.

| Route | Perf | LCP ms | TBT ms | CLS | Total KB | JS KB | CSS KB | Font KB | Img KB | Requests |
|---|---|---|---|---|---|---|---|---|---|---|
| `/` before | 93 | 2,867 | 90 | 0 | 4,018 | 805 | 38 | 3,099 | 31 | 33 |
| `/` after | 95 | 2,568 | 122 | 0 | 933 | 756 | 38 | 63 | 31 | 32 |
| `/post/…` before | 94 | 2,863 | 71 | 0 | 4,016 | 805 | 38 | 3,099 | 31 | 32 |
| `/post/…` after | 96 | 2,562 | 90 | 0 | 931 | 756 | 38 | 63 | 31 | 31 |
| `/grahak-os/` before | 93 | 2,865 | 93 | 0.002 | 4,109 | 811 | 38 | 3,183 | 31 | 36 |
| `/grahak-os/` after | 96 | 2,562 | 55 | 0.002 | 1,024 | 762 | 38 | 146 | 31 | 35 |
| `/shop/kiosk/` before | 94 | 2,861 | 59 | 0.002 | 4,117 | 821 | 38 | 3,183 | 31 | 40 |
| `/shop/kiosk/` after | 96 | 2,560 | 58 | 0.005 | 1,031 | 772 | 38 | 146 | 31 | 39 |
| `/shop/` before | 72 | 44,709 | 78 | 0.018 | 18,660 | 807 | 38 | 3,183 | 14,588 | 40 |
| `/shop/` after | 72 | 27,478 | 111 | 0.018 | 15,574 | 758 | 38 | 146 | 14,587 | 39 |

JS KB includes about 590 KB of third-party script (GTM, the Google Ads tag, the Meta Pixel and its
config). First-party JS per public page, measured on the export with brotli: **195.0 KB → 150.3 KB**
(744.4 KB → 578.7 KB uncompressed). Accessibility 100, SEO 100 and Best Practices 73 on every
public route before and after; Best Practices is held down by third-party cookies (Meta Pixel), a
localhost-only CORS console error, and inspector issues.

With DevTools-applied throttling (packet-level slow 4G) the same local comparison gives LCP
1,669 → 1,663 ms on `/` and 1,634 → 1,553 ms on a post, with Performance 96-98.

**Live production (before any deploy).** Simulated-throttling runs against `https://wecare.digital`
scored 55-59 with LCP between 9 and 24 s. The trace explains it: the 3,125 KB icon font is
requested at VeryHigh priority and competes with everything else on a 1.6 Mbps simulated link.
Blocking only that font in the live run brought a post's FCP from 20.1 s to 3.1 s and LCP from 23.2 s
to 8.2 s. The remaining live LCP drivers are the 590 KB of third-party script, render-blocking
cross-origin Google Fonts CSS, and `Cache-Control: no-store` on content-hashed assets (every
navigation re-downloads every chunk). The last of these was fixed on the base by #1722 on the
evening of 27 October; a live `/_next/static` chunk now returns
`public, max-age=31536000, immutable`, while HTML stays `no-store`. INP is not measurable in a
lab run; CrUX field data was not read.

Lighthouse targets: Performance ≥ 95 is met locally on the content and product routes after the
changes; it is **not** met live until (a) the branch is deployed, (b) the shop images are resized,
and (c) the third-party loading decision below is taken.

## 5. SEO baseline (Code, Local, Cloud-read)

- Crawlability: every sitemap URL (1,523) has an emitted page with exactly one self-referencing
  trailing-slash apex canonical, unique title and description, `og:url` matching the canonical,
  and Organization + WebSite with consistent `@id`s (`tools/audit/indexcheck.js`,
  `schemacheck.js`, `htmlcheck.js`, `tools/browser/seocheck.js` all pass after the changes).
- Sitemap `lastmod` is truthful (post JSON-LD dates, index pages from linked posts, static pages
  from git); no `priority` or `changefreq`. 10 shop URLs carry no `lastmod` because only their
  dynamic template has git history.
- `www`: `https://www.wecare.digital/blog/` answered **302 → `https://wecare.digital/`** (path
  dropped). `http://` → `https://` is a 301; slashless paths 301 to the trailing-slash form; unknown
  paths return a real 404.
- Robots: `/api/` and `/workspace/` disallowed for `*` and the named AI crawlers; the `/api/`
  rule also blocked product images (fixed).
- Content: a median of 256 words per post (`scripts/indexability_audit.py`), which is a content
  judgement rather than a markup defect.
- The SEO runtime (`wecare-seo-tools`) is **partially redundant**: its public blog branch has been
  dead since `GET /seo-tools/blog-public*` moved to `wecare-blog-public` on 13 October; it still
  owns the admin routes used by `/workspace/seo` and `/workspace/content`, the daily freshness
  schedule, and `SeoToolsTable`, which is the blog store the build reads. It writes none of the
  build artifacts (sitemap, RSS, search index, llms.txt). It must not be retired; its two routes
  still integrate `$LATEST` rather than an alias.

## 6. Mobile baseline (Local)

`tools/browser/devicecheck.js` covers 38 routes × 23 postures (320-1920 px, phones, keyboards up,
tablets, five foldable postures). Chromium: **835/874 clean before, 834/874 after**; the one
difference (`/grahak-os/` at 1280 px reporting a 44 px summary as below 44) passed on two reruns
and also fails intermittently on the baseline. Every remaining failure is pre-existing and
identical before and after:

- Home "Runtime" card: request line wraps to 2 lines on phones ≤ 767 px and on a folded 280 px
  posture its row is 435 px taller than the contract; also reported for `/404/` and
  `/account/sign-in/` (the harness still lists `/account/sign-in/`, deleted upstream by `5c57d4c5f`).
- `menucheck.js`: the menu's Home row is 17 px on narrow phones against a 19 px contract (fails
  identically on the baseline).
- `typecheck.js`: mobile section-h2 is 28 px on `/` and 30.23 px on `.pdp-h2` at 390 px; two 22 px
  h2s on `/vayulok/` (identical on the baseline).

WebKit (Safari's engine) home and menu: 13 identical failure lines before and after. Firefox
could not be exercised locally (navigation timeouts under the macOS 27 workaround), and
`menucheck.js` launches engines directly instead of through `lib/browser.js`, so it ignores the
repository's browser resolver. No physical device, installed Capacitor shell or in-app browser was
tested.

## 7. Backend findings (Code, Cloud-read)

Full per-function table: Appendix A. Every function was invoked in the last 30 days, so traffic
alone retires nothing. 63 KEEP, 10 OPTIMIZE, 1 RETIRE CANDIDATE, 0 MERGE.

- **`meta-catalog-sync`, two stream consumers**: intentional. `live` targets the WABA1 catalog,
  `waba2` the WABA2 catalog (Meta allows one WABA per catalog); routing is by invocation
  qualifier (`handler.py:75-96`). Writes are partitioned and approvals are keyed by catalog, so a
  product is never pushed twice to one catalog. Reads are duplicated: each stream record invokes
  each alias with BatchSize 1, and every invocation scans the whole ProductsTable and reads the
  Meta catalog. Two consumers is also the per-shard reader ceiling for DynamoDB Streams. Nothing in
  the repository provisions or moves the `waba2` alias, and `provision_meta_catalog_sync_waba2.py
  --verify` checks environment variables the code no longer reads.
- **`notification-worker` mapping Disabled**: intentional. `provision_notification_domain.py`
  creates it `Enabled=False` as an explicit cutover step, and `--verify` treats an enabled mapping
  as a problem while the domain flag is off.
- **Strangler cutover**: `wecare-checkout` has no routes since 25-26 October (23 routes now on
  `wecare-commerce`); its API Gateway resource policy remains. Retirement candidate after a soak.
- **Synchronous chains**: `razorpay-webhook` → `invoice-engine` → `outbound-whatsapp` (3 levels) and
  `inbound-whatsapp` → `ai-generate-response` → tool Lambdas. 88 invoke sites, mostly
  `RequestResponse`.
- **DynamoDB scans**: 103 `.scan(` sites. Unbounded whole-table loops on webhook or customer paths:
  `razorpay-webhook:2526`, `inbound-whatsapp:5225`, `checkout:292`, `meta-catalog-sync:537`,
  `invoice-engine` ×5. Tables are tiny today (largest 9.5 MB), so this is latency and future risk,
  not current cost.
- **Secrets** (corrected 2026-10-27 after re-reading the code): `razorpay-webhook` and
  `plivo-answer` do NOT fetch per call; both cache their signing secrets for the life of the
  execution environment once a lookup succeeds. The trade-off is rotation: a rotated secret takes
  effect only as warm environments recycle, which the shared `JsonSecretCache`
  (`lambda_utils/secrets_access.py`, 120 s TTL) would bound. Per-call reads remain in
  `workspace-mcp` (deliberate, documented for rotation), `ai-generate-response`'s template tool and
  `partner-onboarding`'s Razorpay credential lookup, all at low volume. The `razorpay-webhook`
  docstring says the function runs with SnapStart; the live configuration has SnapStart off on
  every function.
- **Clients per invocation**: 53 boto3 client constructions run on every call (for example
  `customer-session/handler.py:34-36`).
- **HTTP**: all 64 `urlopen` calls pass a timeout; no `requests` library is used.
- **arm64**: 70 of 74 functions are pure Python and arm64-eligible; Pillow (`checkout`,
  `commerce`, `invoice-engine`, `product-image-gen`), `cryptography` (`whatsapp-business-api`) and
  the docs-scraper image need arm64 layers or images first. Lambda compute is ~$1.3/month, so the
  20% GB-second saving is about $0.25/month; low priority. Those layers are also out of date; see
  section 8a.
- **Logging**: no whole-event dumps; default INFO. `whatsapp-calling` logged `str(event)[:300]` on a
  bad cert-check payload and the first 20 characters of a mismatched signature header; both now log
  shape only (commit on the audit branch).
  All 74 functions use the Text log format, so the platform `START/END/REPORT` lines (about 3 per
  invocation) cannot be filtered by level.

## 7a. CI, queues and other operational findings (Cloud-read, Code)

**The Public UI compliance workflow has not passed yet.** It was added on 2026-10-27 at 01:11 UTC
(`822a22c38`). By 15:35 UTC it had run 66 times (48 pull-request runs, 17 push runs and 1
scheduled run, across 25 branches): 62 failed, 4 were still running, none passed. Across the 62
failures the failing steps were `Full public device matrix` (61), `Firefox Home and menu
regression contract` (57) and `Build static public export` (4). The device matrix fails on the
Home "Runtime" request line wrapping on phones; that contract was added the same morning
(`4fc1f23aa`), the same day as `#1700` "maximize mobile Platform Runtime readability", so the CSS
and the harness disagree and someone has to decide which one is right. A gate that is always red
cannot show a new regression. These files belong to another active workstream, so this audit did
not change them.

**The workflow's first day multiplied Amplify data transfer.** Each run has two jobs. Each job runs
`npm run build`, which fetches the whole blog corpus through `https://wecare.digital/api`, then
runs browser checks against the export, which loads production media by absolute URL. Amplify
served 18.46 GB from 00:00 to 15:00 UTC on 10-27 ($2.77), against an average of 2.99 GB for the
same hours on the previous seven days. Hourly transfer tracks the number of runs started
(R² 0.98): about 0.27 GB per run by regression, or 0.25-0.26 GB per run from the excess, so each
run costs about $0.04 in transfer. Most of it is shop images: `wecare-catalog-media` served 5,706
requests by 15:00 UTC (about 13.7 GB at 2.4 MB each), 5,231 of them in the hours when runs
started, against 1,220 requests in the five days before. At 66 runs a day that would be about
$74-78 a month; at 10 runs a day, about $11-12 (ESTIMATE). This audit's own Lighthouse and
harness runs (about 09:00-10:19 UTC) fall in the 09:00 and 10:00 hours, when no workflow run
started and the whole site served 0.75 GB ($0.11), which bounds their share.

| 10-27, hour (UTC) | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Workflow runs started | 0 | 5 | 17 | 8 | 0 | 0 | 14 | 2 | 13 | 0 | 0 |
| Amplify GB served | 0.11 | 1.50 | 4.60 | 2.08 | 0.56 | 0.03 | 4.07 | 0.63 | 3.99 | 0.64 | 0.11 |

**Build-time blog fetches.** Classified by published IP ranges, in sampled windows (each about two
hours from the start shown):

| Window start (UTC) | GitHub Actions requests | MB | Amplify-build requests | MB |
|---|---:|---:|---:|---:|
| 10-19 15:00 | 66,993 | 261.7 | 7,192 | 28.2 |
| 10-20 07:00 | 94,404 | 365.8 | 14,432 | 56.5 |
| 10-21 10:00 | 91,843 | 359.1 | 17,231 | 67.6 |
| 10-26 14:00 | 0 | 0 | 14,327 | 59.5 |

The GitHub Actions traffic of 19-21 October came from earlier workflows that also ran
`npm run build` (`public-foundation.yml`, `menu-cross-browser.yml`, `mobile-build.yml`,
`deps-upgrade.yml`, `workspace-mcp-codechange.yml`), deleted on 22-23 October (`2ca67d446`,
`68d377555`), not from Public UI compliance. 99.5% of the sampled blog requests came from GitHub
Actions or AWS addresses; the other 0.5% includes local builds.

At the 14-26 October rate (162,440 requests a day), blog-API traffic costs about **$12.13 a
month** (ESTIMATE from measured unit rates): API Gateway $4.87, DynamoDB reads $3.42, Amplify
transfer $2.86, Lambda $0.97 (rounded). DynamoDB reads rose from 55,003 RRU a day (1-13 October) to
966,749 (14-26 October), 17.6x, when `wecare-blog-public` took over the blog routes on 13 October;
that step is the Cost Explorer DynamoDB anomaly of 14-20 October. CloudWatch splits the
SeoToolsTable reads after the cutover:

- 56% are listing queries on `recordType-createdAt-index`, which CloudWatch shows reading nothing
  before the cutover. Each listing call now reads the whole corpus (`storage.py:148`,
  `query_index` with `limit=0`), and a build makes five of them.
- 26% are strongly consistent `GetItem` reads of single posts.
- 18% are queries on `slug-createdAt-index`, which `get_blog_post` runs when the `BLOG#<slug>`
  `GetItem` misses (`storage.py:155-158`).

When CI and Amplify builds overlap, the stage's default route throttle (100 requests/second,
burst 200) answers 429, the build gives up after six attempts, and the run fails (seen in CI run
`40473775811`; none of the 17 failed Amplify builds below were 429s). Options, in order of effort:

1. Build once per CI run and share `out/` between jobs, which halves CI fetches.
2. Fetch the listing once per build and share it between the generators, which saves $1.64 a
   month of DynamoDB reads.
3. Cache the corpus in CI per hour.
4. Add a paginated bulk endpoint to `wecare-blog-public`, so a build makes about six requests
   instead of about 1,430. That removes most of the $5.84 a month that scales with request count
   (API Gateway and Lambda). DynamoDB and transfer ($6.28) scale with the number of corpus
   fetches, so only fewer fetches reduce them.

**Failed Amplify builds**: 17 of the 274 jobs listed on the morning of 10-27 failed. That is every
job since the branch was re-created on 24 October (job numbers restart at 1). 9 failed on
TypeScript errors and 3 on `npm error code EUSAGE`, which means commits reached the production
branch without passing `tsc`. They cost 41.4 build-minutes ($0.41).

**SQS** (AWS guidance: visibility at least 6x the function timeout, maxReceiveCount at least 5):

| Queue | Consumer timeout | Visibility | Ratio | maxReceiveCount | Partial batch failures |
|---|---:|---:|---:|---:|---|
| `stack-wecare-digital-bulk-queue` | 120 s | 300 s | 2.5x | 3 | not enabled |
| `stack-wecare-digital-notification-queue` (mapping Disabled) | 120 s | 300 s | 2.5x | 3 | enabled |

`bulk-worker` catches every per-record exception and returns success, so a failed record is
deleted rather than retried and the bulk DLQ can never receive anything. Enabling
`ReportBatchItemFailures` must ship together with code that returns `batchItemFailures`; either
alone is wrong (without the code nothing changes; without the mapping setting, returned failures
are ignored).

**Compute Optimizer** is active and has 19 Lambda findings, each with an estimated saving of
$0.00: 13 `MemoryOverprovisioned` and 6 `MemoryUnderprovisioned`. Five of the under-provisioned
findings are old `wecare-razorpay-webhook` versions (85, 88, 92, 94, 107; 256 → 320 MB), while the
`live` alias now serves version 199. The sixth is `wecare-wix-catalog-webhook:9` (128 → 160 MB), a
function that no longer exists, so that finding is stale. Cost Optimization Hub has none.

**S3**: three versioned buckets have no lifecycle rule, so noncurrent versions accumulate:
`wecare-digital-get-replica-usw2` (1.40 GB), `wecare-maintenance-reports-…` (12 MB) and
`wecare-credential-backups-…` (139 KB). The cost is cents a month; for the replica, keeping
noncurrent versions may be deliberate protection, so it is an owner decision.

**Corrected recommendation, `site-language`**: in the sampled window, 12,501 of 12,827
`/api/site-language` requests (97%) came from headless test browsers. Real-user volume is too
small for client-side caching of the language list to matter, so it was not changed.

## 8. Security findings (Code)

| Severity | Where | Issue | Status |
|---|---|---|---|
| High | `core/url-shortener/handler.py` | Stored XSS in the deep-link page, open redirect, unconditional overwrite of any code, creator taken from the request body, writes allowed for Viewer | **Fixed on branch** (validation on write and read, context encoding, CSP, conditional put, session actor, Operator floor; 8 unit tests). Needs deploy |
| Medium | `payments/invoice-engine/handler.py` `_build_invoice_html` | Customer and catalogue strings interpolated raw into a downloadable HTML receipt | **Fixed on branch**; needs deploy |
| Medium | `messaging/rcs-dlr` | Unsigned `MESSAGE_DELIVERY` callbacks processed while no Sinch webhook secret exists (other event types refused with 503) | Owner: configure the Sinch secret |
| Low | `lambda_utils/middleware.py` | Auth and signature checks skip any event without an API Gateway context; correct today, unsafe if a non-API-Gateway HTTP front end is ever added | Documented |
| Low | `lambda_utils/customer_auth.py` | Customer tokens pinned to the pool issuer but not to an app client (the staff path pins its client) | Recommendation |
| Low | `razorpay-webhook` | Dedupe key expires after 7 days and Razorpay signatures carry no timestamp | Recommendation |
| Low | `service-api`, `marketing-ads`, `meta-business-agent`, `push-notifications`, `url-shortener` | `Access-Control-Allow-Origin: *` on authenticated JSON; not exploitable (bearer tokens, no credentials) | Recommendation |
| Low | `plivo-answer` | Fallback credential accepted as a query-string token | Recommendation |
| Low | Main API CORS | `http://localhost:3000` is an allowed origin in production | Recommendation |
| Info | Account | No GuardDuty, Security Hub or AWS Config; WAF removed by owner decision on 2026-09-28 (public OTP sign-in has no per-IP edge protection) | Owner decision |

Verified OK (not re-audited): Meta/WhatsApp HMAC over the raw body with constant-time compare and
dual-secret support, verify-token challenge, message-id dedupe; Razorpay HMAC, lease-based dedupe
and amount binding; Plivo V3 signatures; Sinch HMAC with nonce and skew window; staff role from
Cognito groups server-side with Admin MFA enforcement; customer identity from the token `sub` with
identical 401s for missing and foreign resources; MCP OAuth redirect/PKCE checks; no `eval`,
`exec`, `shell=True` or unsafe subprocess use. Secret scans: no credential-shaped strings in the
tree (`scripts/verify_no_secrets_in_tree.py` PASS); `scripts/scan_repo_secrets.py` reports 7
issuer-shaped strings in git history, which is an owner-only rotation review per
`docs/CREDENTIAL-ROTATION-RUNBOOK.md`.

## 8a. Dependency audit (Cloud-read, Code)

| Surface | Check | Result |
|---|---|---|
| npm, repository root | `npm audit`, production and all dependencies | 0 vulnerabilities |
| npm, `tools/browser` | `npm audit` | 0 |
| npm, `amplify/` (deploy tooling; not shipped to the site or to Lambda) | `npm audit` | 22: 19 high (`zod` < 4.6.6, GHSA-mrhx-c7xc-m3w5) and 3 moderate (`@opentelemetry/core` < 2.8.0, GHSA-8988-4f7v-96qf). These are the two dismissed Dependabot alerts (#119, #120), and `scripts/check_bundled_advisories.py --gate` passes. npm's suggested fix, `@aws-amplify/backend@0.5.1`, is a downgrade and not usable |
| Dependabot | Repository alerts | 0 open, 2 dismissed (above), 130 fixed |
| Python pins | 76 pinned packages in the requirement files, against OSV.dev | 0 advisories. `docs-scraper` leaves `boto3>=1.43.116` unpinned |
| Lambda layers | Package versions read from the layer archives, against OSV.dev | Out of date; table below |

| Layer | Publisher | Created | Contents | Advisories (OSV.dev) | Attached to |
|---|---|---|---|---|---|
| `pillow-python312:2` | This account | 2026-02-17 | Pillow 12.1.1 | 59 (5 critical, 35 high, 19 moderate), all fixed by 13.0.0 | `checkout`, `commerce`, `invoice-engine` |
| `Klayers-p312-Pillow:10` | Third party (Klayers public layers, account `770693421928`) | 2026-02-17 | Pillow 12.1.1 | Same 59 | `product-image-gen` |
| `cryptography-python312:1` | This account | 2026-02-23 | cryptography 46.0.5, cffi 2.0.0, pycparser 3.0 | cryptography: 6, of which 3 high (bundled OpenSSL, fixed in 48.0.1; PKCS#7 decryption oracle, fixed in 50.0.0; X.509 path-building DoS, fixed in 49.0.0). cffi and pycparser: 0 | `whatsapp-business-api`, `marketing-ads`, `partner-onboarding`, `partner-token-refresh` |

**Exposure.** The five critical Pillow advisories are heap overflows in the JPEG and FlashPix
decoders and in the TIFF writer, reuse of stale storage in multi-frame loaders, and argument
injection into Ghostscript. `Image.open` picks a decoder from the bytes, so what matters is where
decoded images come from. `product-image-gen` decodes flag PNGs fetched from `flagcdn.com`
(`handler.py:169-177`, staff-only behind `require_auth` at :123). `invoice-engine` decodes the
company logo from its own media bucket (`handler.py:284-293`, decoded at :2969 and
`receipt_layout.py:143`). No customer-supplied image reaches Pillow on these paths, so an exploit
needs a compromised upstream such as the flag CDN. That makes this P1 rather than P0.
`receipt_layout.py:15` imports PIL at module level, so the layer loads on every `invoice-engine`
cold start.

For cryptography, `whatsapp-business-api` imports only RSA-OAEP, AES and PEM key loading, for
WhatsApp Flows decryption (`handler.py:4279-4282`). The PKCS#7 and X.509 advisories are in code it
does not call; the bundled-OpenSSL advisory applies to any use of the wheel. `marketing-ads`,
`partner-onboarding` and `partner-token-refresh` attach the layer but nothing they run imports
cryptography.

Dev and CI already pin the fixed versions (`requirements-dev.txt:39` cryptography 50.0.2,
`requirements-dev.txt:86` Pillow 13.0.0, `payment-rail-ci.yml:113` Pillow 13.0.0), so production
runs older libraries than the tests exercise.

Both of this account's layers were zipped with Windows path separators: all 238 and 251 entries
use `\`. They work today (a 30-day Logs Insights search over the seven functions that attach them
found no import errors), but a rebuilt layer should use forward slashes.

**Recommendation (owner: layer publish and function deploys).** Build `pillow-python312` at
13.0.0 and `cryptography-python312` at 50.0.2 from the pinned requirements for Linux x86_64 and
Python 3.12, publish them as new layer versions, move `product-image-gen` off the third-party layer
onto the account's own Pillow layer, detach cryptography from the three functions that do not use
it, and roll out through the normal `live` alias flow.

## 9. Dead code and retained history (Code)

| Item | Classification | Evidence |
|---|---|---|
| `amplify/functions/auth/blog-subscribe/` | Truly dead | Only `__pycache__`; no deploy entry |
| Seven `amplify/functions/**/resource.ts` | Dead IaC | Not imported by `amplify/backend.ts` |
| `seo-tools` public blog branch and `blog-public/faq.py` near-copy | Partially dead / duplicated | Route moved to `wecare-blog-public`; `faq.py` copies 0.99 similar |
| `customer-commerce-mcp` `index.py` vs `customer_oauth.py` | Duplicated | Same OAuth checks in two files |
| `seo/llm/llms-txt-draft.md`, `seo/schema/schema-templates.json` | Retained history | Not read by build or runtime |
| `/aws/lambda/wecare-coupons` log group | Orphan | Function no longer exists |
| `API_BASE` ×19, `formatDate` ×6, `isValidPhone`/`isValidEmail` re-implemented | Duplicated utilities | Consolidation is a refactor; not done |
| `tools/browser/devicecheck.js` route `/account/sign-in/` | Stale | Page deleted upstream |

Nothing was deleted in this audit.

## 10. Data and table candidates (Cloud-read)

Full table: Appendix B. On-demand tables cost nothing at rest beyond storage, so none of these
are cost items; they are hygiene and privacy items.

- **Retirement candidate (owner approval, data export first):** `AdClickAttributionTable`, 0 items,
  no Lambda code reads it (only the Amplify data model and the GDPR key map name it).
- **TTL candidate:** `LinkClicksTable` keeps source IP and user agent per click with no expiry
  (1,080 rows).
- **Deletion protection off:** `wecare-workspace-mcp` (the only table without it).
- 38 empty tables belong to dormant features (CRM, notifications, bulk, voice, partner billing)
  that code still references; keep.
- Streams: ProductsTable (two intended consumers) and VoiceCDRTable.

## 11. Drift

| Kind | Finding |
|---|---|
| Repo vs live | `blog-public/handler.py` sets `Cache-Control: public, max-age=60…`, but every live `/api` response carries `no-store`: `customHttp.yml`'s sitewide `**/*` block overrides proxied responses too |
| Repo vs live | Amplify rule `301 https://wecare.digital → https://wecare.digital` (a no-op self-redirect) was live and re-asserted by `provision_legacy_redirects.py` |
| Repo vs live | `provision_meta_catalog_sync_waba2.py --verify` checks env vars the handler ignores; the waba2 alias, mapping and schedule exist only live |
| Repo vs live | `docs/` recovery kit says 78 handlers; the tree has 74 (`scripts/check_recovery_kit_drift.py`) |
| Repo vs live | Memory/timeout/architecture for ~50 functions are not in any IaC |
| Live vs docs | `README.md` says "60 zip-packaged functions"; live has 73 zip + 1 image |
| Provider | Bing Webmaster property is recorded as `https://www.wecare.digital/` while the canonical origin is the apex (per the account registry this is expected) |
| Provider | GA4 receives nothing while Consent Mode defaults to denied and the site has no consent UI (documented in `_document.tsx`) |

Meta/WhatsApp provider state (app live on Graph v26.0, two webhook topics, compliant) was taken
from the brief and not re-read; no provider-side call was made.

## 12. Changes made in this audit

Branch `audit/platform-performance-cost-seo-20261027`, thirteen commits on `2f7ca2979` plus one
merge of the base:

1. `perf(web)`: Material Symbols subset with a compile-time ligature guard.
2. `perf(web)`: Amplify, the API client and Capacitor load only where used.
3. `fix(seo)`: robots image allowance, sitemap noindex filter, Organization `location`, no
   fabricated `InStock`, no invisible FAQPage, no contradictory `googlebot` meta, `/blog/`
   description.
4. `fix(seo)`: www path-preserving 301 in the wildcard function IaC; apex self-redirect removed
   from the redirect script.
5. `fix(security)`: short-link destination validation and encoding, no overwrites, session actor,
   Operator floor, plus tests.
6. `fix(security)`: invoice HTML escaping.
7. `perf(build)`: Amplify `nvm --skip-default-packages`, Node ≥ 24 assertion, cache removed. The
   cache removal was superseded at the merge (item 12) by the base's npm download cache.
8. `docs(audit)`: this document and the cost plan.
9. `fix(privacy)`: `whatsapp-calling` logs payload and signature shape only.
10. `docs(audit)`: CI, queue, S3 and Compute Optimizer findings; corrected secret-caching and
    `site-language` claims.
11. `docs(audit)`: dependency audit, the 27 October egress spike and the blog-fetch cost model;
    corrected the CI history, access-log window length and Compute Optimizer count.
12. Merge of `origin/wecare.digital` at `ddbacf8b5` into the branch (`485933cdb`). The base had
    moved 63 commits; the merge commit's message says 55, which was the count when the conflict
    was first found. They include remediation PRs from another session: #1722 (npm download cache
    in `amplify.yml`, immutable caching for `/_next/static`) and #1728 (SEO-table PITR
    reconciliation in `scripts/deploy_seo_tools.py`, plus
    `tests/test_platform_audit_remediations.py`, which pins both #1722 changes). #1731 has the
    same title and no file changes of its own.
    The one conflict, `amplify.yml`, keeps the base's `.npm` cache and this branch's `nvm` and
    Node assertion lines. The merged tree passes `npm run build`, `tsc --noEmit`, `eslint` (0
    errors), `compileall`, both Python test files (11 tests) and the index/schema/html checks.
13. `docs(audit)`, two commits: this account of the merge and the scenario figures it changes,
    then the corrected commit count in item 12.

Not done, though offered in an earlier reply: making `tools/browser/menucheck.js:40` and
`elsewherecheck.js:36`, which call `engine.launch()` directly, launch through `lib/browser.js`.
`lib/browser.js` changed today in another workstream's pull request (#1667), and the change only
helps local runs because CI installs its own browsers, so it is left to the harness workstream.



## 13. Research references

- AWS Amplify pricing: [aws.amazon.com/amplify/pricing](https://aws.amazon.com/amplify/pricing/)
- Amplify environment variables (`AMPLIFY_DIFF_DEPLOY` takes a single root, so it cannot express
  this repository's frontend inputs): [docs](https://docs.aws.amazon.com/amplify/latest/userguide/environment-variables.html);
  skipped diff builds failing on missing artifacts: [amplify-hosting#3268](https://github.com/aws-amplify/amplify-hosting/issues/3268)
- AWS Support plans (Business Support+ is $29/month minimum per account; Developer and Business
  end on 2027-01-01): [plans](https://docs.aws.amazon.com/awssupport/latest/user/aws-support-plans.html),
  [pricing](https://aws.amazon.com/premiumsupport/pricing/)
- nvm `--skip-default-packages`: [nvm CLI reference](https://www.nvmnode.com/cli/nvm-sh.html)
- Google Fonts `icon_names` subsetting for Material Symbols: verified by direct request (15,788-byte
  subset served with the same axes).
- OSV.dev advisory database, queried 2026-10-27 through its `query` and `querybatch` API:
  [osv.dev](https://osv.dev/). The critical Pillow advisories:
  [GHSA-332p-7hrc-92wf](https://github.com/advisories/GHSA-332p-7hrc-92wf),
  [GHSA-5x8w-8jj5-q52h](https://github.com/advisories/GHSA-5x8w-8jj5-q52h),
  [GHSA-8g5g-8vmr-9782](https://github.com/advisories/GHSA-8g5g-8vmr-9782),
  [GHSA-v9pv-5gc8-w2m6](https://github.com/advisories/GHSA-v9pv-5gc8-w2m6),
  [GHSA-w889-685w-c8fh](https://github.com/advisories/GHSA-w889-685w-c8fh).

## Appendix A. Lambda functions (74)

Costs are estimated from 30-day invocations × average duration × memory at us-east-1 list prices
($0.0000166667/GB-s x86, $0.0000133334 arm64, $0.20/M requests), before free tier.

| Function | Source | Trigger evidence | Arch | Mem/Timeout | Invocations 30 d | Errors | p50 / p95 / p99 ms | Est. compute $/30 d | Recommendation |
|---|---|---|---|---|---:|---:|---|---:|---|
| `wecare-blog-public` | `operations/blog-public` | API | x86_64 | 512 MB / 30 s | 2,291,364 | 1 | 18 / 37 / 653 | 1.69 | **OPTIMIZE** - 2.29M calls/30 d, almost all build-time fetches (Amplify + CI + local builds); 5.6 RRU per request, mostly whole-corpus listing reads (section 7a). Cut by path-filtered builds; 90-day log retention vs 30 elsewhere. |
| `wecare-seo-tools` | `operations/seo-tools` | API, Sched:ENABLED | x86_64 | 512 MB / 120 s | 1,738,588 | 0 | 40 / 896 / 14189 | 8.20 | **OPTIMIZE** - Public blog branch is dead since GET /seo-tools/blog-public moved to wecare-blog-public (13 Oct); admin routes and daily freshness schedule remain. Routes hit $LATEST (unqualified). |
| `wecare-site-language` | `core/site-language` | API | x86_64 | 512 MB / 30 s | 454,076 | 0 | 2 / 2 / 3 | 0.10 | **KEEP** - 454k calls/30 d, 97% of them from headless test browsers in the sampled window; client caching would not move real-user cost |
| `wecare-scheduled-messages` | `messaging/scheduled-messages` | API | x86_64 | 256 MB / 60 s | 8,652 | 0 | 150 / 181 / 204 | 0.01 | **KEEP** |
| `wecare-messages-read` | `core/messages-read` | API | x86_64 | 512 MB / 60 s | 6,776 | 0 | 671 / 1136 / 1324 | 0.04 | **KEEP** |
| `wecare-contacts` | `core/contacts` | API | x86_64 | 256 MB / 60 s | 6,496 | 0 | 364 / 526 / 645 | 0.01 | **KEEP** |
| `wecare-meta-catalog-sync` | `ecommerce/meta-catalog-sync` | ESM:10.307(Enabled) | x86_64 | 512 MB / 120 s | 5,868 | 0 | 590 / 1072 / 1974 | 0.03 | **OPTIMIZE** - Two aliases (live=WABA1, waba2=WABA2) by design; each stream record triggers a full ProductsTable scan + Meta read per alias (BatchSize 1, no window). Add a batching window. |
| `wecare-catalog-media` | `ecommerce/catalog-media` | API | x86_64 | 512 MB / 15 s | 5,402 | 31 | 171 / 332 / 403 | 0.01 | **KEEP** |
| `wecare-commerce` | `ecommerce/checkout` | API | x86_64 | 512 MB / 60 s | 4,860 | 0 | 21 / 44 / 665 | 0.00 | **KEEP** - Strangler target; now owns the checkout + invoice routes (23). Pillow layer is 12.1.1 (section 8a). |
| `wecare-inbound-whatsapp` | `messaging/inbound-whatsapp-handler` | API, SNS:stack-wecare-digital | x86_64 | 512 MB / 120 s | 3,494 | 0 | 29 / 1901 / 3474 | 0.01 | **KEEP** |
| `wecare-rcs-dlr` | `messaging/rcs-dlr` | API | x86_64 | 256 MB / 15 s | 3,468 | 0 | 18 / 350 / 381 | 0.00 | **KEEP** - Unsigned MESSAGE_DELIVERY accepted until a Sinch webhook secret exists (owner action). |
| `wecare-whatsapp-calling` | `messaging/whatsapp-calling` | API | x86_64 | 256 MB / 60 s | 3,172 | 0 | 154 / 328 / 359 | 0.00 | **KEEP** - Raw-event and signature-prefix logging removed on the audit branch (needs deploy) |
| `wecare-razorpay-webhook` | `payments/razorpay-webhook` | API | x86_64 | 256 MB / 60 s | 2,586 | 5 | 297 / 663 / 1008 | 0.00 | **OPTIMIZE** - Signing secret cached for the environment lifetime (rotation waits for recycling; a 120 s TTL cache would bound it); unbounded scan at handler :2526; 3-level synchronous chain |
| `wecare-outbound-whatsapp` | `messaging/outbound-whatsapp` | API | x86_64 | 512 MB / 60 s | 2,405 | 0 | 67 / 1869 / 3371 | 0.01 | **KEEP** |
| `wecare-rcs-send` | `messaging/rcs-send` | API | x86_64 | 256 MB / 30 s | 2,146 | 0 | 814 / 2193 / 2303 | 0.01 | **KEEP** |
| `wecare-checkout` | `ecommerce/checkout` | direct invoke / none found | x86_64 | 512 MB / 60 s | 2,028 | 0 | 56 / 1667 / 2723 | 0.01 | **RETIRE CANDIDATE** - No routes since the strangler cutover to wecare-commerce (25-26 Oct); resource policy still grants API GW. Retire after an owner-approved soak. Pillow layer is 12.1.1 (section 8a). |
| `wecare-whatsapp-business-api` | `messaging/whatsapp-business-api` | API | x86_64 | 256 MB / 30 s | 1,876 | 1 | 379 / 2901 / 5440 | 0.01 | **KEEP** - cryptography layer is 46.0.5; rebuild at 50.0.2 (section 8a). |
| `wecare-workspace-mcp` | `ai/workspace-mcp` | API wecare-chat-mcp, API | arm64 | 256 MB / 28 s | 847 | 0 | 297 / 2627 / 3341 | 0.00 | **KEEP** - Only arm64 function; secrets fetched per tool call. |
| `stack-wecare-url-shortener` | `core/url-shortener` | API | x86_64 | 256 MB / 10 s | 603 | 0 | 49 / 1813 / 1855 | 0.00 | **OPTIMIZE** - Security fix on audit branch (XSS / open redirect / overwrite); needs deploy. |
| `wecare-billing` | `operations/billing` | API | x86_64 | 256 MB / 30 s | 500 | 0 | 829 / 1179 / 1373 | 0.00 | **KEEP** |
| `wecare-mcp` | `ai/mcp` | API | x86_64 | 512 MB / 20 s | 444 | 0 | 2 / 5 / 365 | 0.00 | **KEEP** |
| `wecare-conversation-meta` | `core/conversation-meta` | API | x86_64 | 256 MB / 30 s | 406 | 0 | 358 / 589 / 648 | 0.00 | **KEEP** |
| `wecare-native-catalog-admin` | `ecommerce/native-catalog-admin` | API | x86_64 | 256 MB / 20 s | 393 | 0 | 462 / 702 / 842 | 0.00 | **KEEP** |
| `wecare-plivo-answer` | `messaging/plivo-answer` | API | x86_64 | 256 MB / 15 s | 389 | 0 | 297 / 923 / 950 | 0.00 | **KEEP** - Signing tokens cached after the first successful lookup; fallback token accepted in the query string |
| `wecare-invoice-engine` | `payments/invoice-engine` | direct invoke / none found | x86_64 | 512 MB / 60 s | 250 | 0 | 368 / 5985 / 9872 | 0.00 | **OPTIMIZE** - HTML-escaping fix on branch; unbounded scans (5 sites) on the webhook path; sync chain razorpay-webhook -> invoice-engine -> outbound-whatsapp; Pillow layer is 12.1.1 (section 8a). |
| `wecare-sms-aws` | `messaging/sms-aws` | API | x86_64 | 256 MB / 30 s | 200 | 0 | 880 / 955 / 983 | 0.00 | **KEEP** |
| `wecare-whatsapp-template-management` | `messaging/whatsapp-template-management` | API | x86_64 | 512 MB / 60 s | 194 | 0 | 154 / 801 / 3817 | 0.00 | **KEEP** |
| `wecare-customer-commerce-mcp` | `ai/customer-commerce-mcp` | API wecare-customer-commerce-mcp | x86_64 | 256 MB / 30 s | 181 | 0 | 2 / 3456 / 5882 | 0.00 | **KEEP** |
| `wecare-customer-whatsapp-auth` | `auth/customer-whatsapp-auth` | Cognito trigger | x86_64 | 256 MB / 15 s | 133 | 0 | 2 / 4486 / 4884 | 0.00 | **KEEP** - Cognito custom-auth triggers (customer pool); synchronous OTP send inside a 5 s trigger budget. |
| `wecare-service-api` | `core/service-api` | API | x86_64 | 256 MB / 30 s | 127 | 0 | 381 / 689 / 720 | 0.00 | **KEEP** |
| `wecare-catalog-management` | `ecommerce/catalog-management` | direct invoke / none found | x86_64 | 256 MB / 60 s | 123 | 0 | 686 / 1267 / 2121 | 0.00 | **KEEP** - No route/event trigger found; 123 direct invocations in 30 d. Confirm caller before any change. |
| `wecare-whatsapp-voice` | `messaging/whatsapp-voice` | API | x86_64 | 256 MB / 30 s | 115 | 0 | 436 / 521 / 539 | 0.00 | **KEEP** |
| `wecare-automation-rules` | `core/automation-rules` | API | x86_64 | 256 MB / 30 s | 107 | 0 | 569 / 646 / 670 | 0.00 | **KEEP** |
| `wecare-secure-files` | `core/secure-files` | API | x86_64 | 512 MB / 30 s | 89 | 1 | 3 / 1474 / 7171 | 0.00 | **KEEP** |
| `wecare-customer-session` | `ecommerce/customer-session` | API | x86_64 | 256 MB / 30 s | 81 | 0 | 1020 / 1398 / 1457 | 0.00 | **KEEP** |
| `wecare-auth-middleware` | `core/auth-middleware` | API | x86_64 | 256 MB / 30 s | 69 | 0 | 2 / 14 / 173 | 0.00 | **KEEP** |
| `wecare-email-verification` | `auth/email-verification` | API | x86_64 | 256 MB / 15 s | 58 | 0 | 33 / 725 / 810 | 0.00 | **KEEP** |
| `wecare-ai-config-management` | `ai/ai-config-management` | API | x86_64 | 256 MB / 30 s | 39 | 0 | 2 / 567 / 619 | 0.00 | **KEEP** |
| `wecare-docs-scraper` | `operations/docs-scraper` | API, EB:ENABLED | x86_64 | 2048 MB / 300 s | 36 | 0 | 869 / 7928 / 8822 | 0.00 | **OPTIMIZE** - Container image; ECR repo holds 13 images / 12.0 GB with no lifecycle policy. |
| `wecare-media-cleanup` | `messaging/media-cleanup` | API, EB:ENABLED | x86_64 | 256 MB / 60 s | 33 | 0 | 157 / 170 / 171 | 0.00 | **KEEP** |
| `wecare-service-requests` | `ecommerce/service-requests` | API | x86_64 | 512 MB / 15 s | 33 | 0 | 103 / 454 / 461 | 0.00 | **KEEP** |
| `wecare-ai-generate-response` | `ai/ai-generate-response` | API | x86_64 | 1024 MB / 120 s | 32 | 0 | 3 / 820 / 1442 | 0.00 | **KEEP** - 1024 MB; synchronous fan-out to tool Lambdas. |
| `wecare-customer-orders` | `ecommerce/customer-orders` | API | x86_64 | 512 MB / 15 s | 31 | 0 | 223 / 619 / 724 | 0.00 | **KEEP** |
| `wecare-get-miss-redirect` | `edge/get-miss-redirect` | Edge:origin-response | x86_64 | 128 MB / 5 s | 31 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** - Lambda@Edge origin-response on E2GP22R4BIFGQ3; no deploy script (by design, version-pinned). |
| `wecare-partner-token-refresh` | `messaging/partner-token-refresh` | EB:ENABLED | x86_64 | 256 MB / 120 s | 30 | 0 | 158 / 171 / 173 | 0.00 | **KEEP** |
| `wecare-system-cleanup` | `operations/system-cleanup` | API | x86_64 | 512 MB / 300 s | 29 | 0 | 1433 / 6159 / 9115 | 0.00 | **KEEP** |
| `wecare-product-image-gen` | `ecommerce/product-image-gen` | API | x86_64 | 512 MB / 60 s | 27 | 0 | 2 / 3 / 12 | 0.00 | **KEEP** - Pillow 12.1.1 from a third-party public layer (`Klayers-p312-Pillow:10`); move to the account's own layer at 13.0.0 (section 8a). |
| `wecare-bulk-worker` | `operations/bulk-worker` | API, ESM:stack-wecare-digital-bulk-qu(Enabled) | x86_64 | 512 MB / 120 s | 22 | 0 | 2 / 3 / 3 | 0.00 | **OPTIMIZE** - Swallows per-record errors and returns success, so the DLQ never fires; queue visibility 2.5x timeout (guidance 6x) |
| `wecare-waba-management` | `messaging/waba-management` | API | x86_64 | 256 MB / 30 s | 21 | 0 | 2 / 1532 / 2511 | 0.00 | **KEEP** |
| `wecare-crm` | `core/crm` | API | x86_64 | 256 MB / 30 s | 20 | 0 | 2 / 2 / 4 | 0.00 | **KEEP** |
| `wecare-customer-registration` | `auth/customer-registration` | API | x86_64 | 256 MB / 15 s | 18 | 0 | 2 / 657 / 660 | 0.00 | **KEEP** |
| `wecare-dlq-replay` | `operations/dlq-replay` | API | x86_64 | 256 MB / 60 s | 17 | 0 | 2 / 1064 / 1124 | 0.00 | **KEEP** |
| `wecare-partner-onboarding` | `messaging/partner-onboarding` | API | x86_64 | 256 MB / 30 s | 17 | 0 | 2 / 12 / 12 | 0.00 | **KEEP** |
| `wecare-payments-read` | `payments/payments-read` | API | x86_64 | 256 MB / 30 s | 17 | 0 | 2 / 569 / 587 | 0.00 | **KEEP** |
| `wecare-cognito-custom-message` | `auth/cognito-custom-message` | Cognito trigger | x86_64 | 256 MB / 10 s | 13 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** - Cognito CustomMessage trigger (staff pool). |
| `wecare-voice-aws` | `messaging/voice-aws` | API | x86_64 | 256 MB / 30 s | 13 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-pstn-softphone` | `messaging/pstn-softphone` | API | x86_64 | 256 MB / 30 s | 12 | 0 | 2 / 19 / 20 | 0.00 | **KEEP** |
| `wecare-customer-profile` | `auth/customer-profile` | API | x86_64 | 256 MB / 15 s | 11 | 0 | 2 / 808 / 827 | 0.00 | **KEEP** |
| `wecare-faq-handler` | `core/faq-handler` | API | x86_64 | 256 MB / 30 s | 10 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-template-analytics` | `messaging/template-analytics` | API | x86_64 | 256 MB / 30 s | 10 | 0 | 2 / 18 / 18 | 0.00 | **KEEP** |
| `wecare-bulk-job-control` | `operations/bulk-job-control` | API | x86_64 | 256 MB / 30 s | 9 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-customer-invoice` | `ecommerce/customer-invoice` | API | x86_64 | 512 MB / 15 s | 9 | 0 | 2 / 82 / 83 | 0.00 | **KEEP** |
| `wecare-marketing-ads` | `messaging/marketing-ads` | API | x86_64 | 256 MB / 45 s | 9 | 0 | 2 / 724 / 727 | 0.00 | **KEEP** |
| `wecare-messages-delete` | `core/messages-delete` | API | x86_64 | 256 MB / 30 s | 9 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-push-notifications` | `messaging/push-notifications` | API | x86_64 | 256 MB / 30 s | 9 | 0 | 2 / 23 / 23 | 0.00 | **KEEP** |
| `wecare-voice-cdr-read` | `messaging/voice-cdr-read` | API | x86_64 | 256 MB / 30 s | 9 | 0 | 2 / 2 / 3 | 0.00 | **KEEP** |
| `wecare-meta-business-agent` | `messaging/meta-business-agent` | API | x86_64 | 256 MB / 60 s | 8 | 0 | 2 / 1473 / 1514 | 0.00 | **KEEP** |
| `wecare-bulk-job-create` | `operations/bulk-job-create` | API | x86_64 | 512 MB / 60 s | 7 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-vayulok-environment` | `core/vayulok-environment` | API | x86_64 | 512 MB / 30 s | 7 | 0 | 911 / 1305 / 1311 | 0.00 | **KEEP** |
| `wecare-agent-action-group` | `ai/agent-action-group` | API | x86_64 | 512 MB / 60 s | 5 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-ai-query-kb` | `ai/ai-query-kb` | API | x86_64 | 256 MB / 30 s | 5 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-outbound-sms` | `messaging/outbound-sms` | API | x86_64 | 256 MB / 30 s | 5 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-outbound-email` | `messaging/outbound-email` | API | x86_64 | 256 MB / 30 s | 4 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** |
| `wecare-notification-worker` | `messaging/notification-worker` | ESM:stack-wecare-digital-notific(Disabled) | x86_64 | 512 MB / 120 s | 2 | 0 | 2 / 2 / 2 | 0.00 | **KEEP** - SQS mapping intentionally Disabled until the PSTN notification cutover (provision_notification_domain.py). |

## Appendix B. DynamoDB tables (76)

RCU/WCU are 30-day sums of base-table consumption (GSI consumption is reported separately by CloudWatch and is not included). "Code refs" counts files under `amplify/functions`, `amplify/infra` and `src` that name the table.

| Table | Keys | GSIs | Items | Size KB | TTL attr | Stream | RCU 30 d | WCU 30 d | Code refs | Recommendation |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---|
| `…-AIInteractionsTable` | id(HASH) | 0 | 0 | 0.0 | - | - | 52 | 0 | 4 | KEEP (dormant feature; empty, costs $0) |
| `…-AIProviderPolicyTable` | countryCode(HASH) | 0 | 0 | 0.0 | - | - | 34 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-AdClickAttributionTable` | id(HASH) | 2 | 0 | 0.0 | ttl | - | 44 | 0 | 0 | RETIRE CANDIDATE - 0 items, no Lambda code reads it (only the Amplify data model and the GDPR key map). |
| `…-AgentApprovalsTable` | planHash(HASH) | 0 | 7 | 105.1 | expiresTtl | - | 609 | 586 | 3 | KEEP |
| `…-AuditLogsTable` | id(HASH) | 0 | 1,869 | 1,395.5 | expiresAt | - | 4,010 | 16,720 | 7 | KEEP |
| `…-AutomationRulesTable` | id(HASH) | 0 | 0 | 0.0 | - | - | 416 | 0 | 2 | KEEP (dormant feature; empty, costs $0) |
| `…-BulkJobsTable` | id(HASH) | 0 | 0 | 0.0 | - | - | 58 | 0 | 6 | KEEP (dormant feature; empty, costs $0) |
| `…-BulkRecipientsTable` | id(HASH) | 0 | 0 | 0.0 | - | - | 52 | 0 | 5 | KEEP (dormant feature; empty, costs $0) |
| `…-CallNotificationsTable` | callId(HASH) | 0 | 0 | 0.0 | - | - | 44 | 2 | 2 | KEEP (dormant feature; empty, costs $0) |
| `…-CartTable` | cartId(HASH) | 1 | 0 | 0.0 | expiresTtl | - | 24 | 0 | 7 | KEEP (dormant feature; empty, costs $0) |
| `…-CatalogCacheTable` | id(HASH) | 0 | 0 | 0.0 | ttl | - | 50 | 0 | 2 | KEEP (dormant feature; empty, costs $0) |
| `…-CommerceKeys` | orderId(HASH) | 0 | 120 | 35.6 | - | - | 637 | 286 | 19 | KEEP |
| `…-ContactsTable` | id(HASH) | 3 | 43 | 22.2 | - | - | 19,454 | 914 | 48 | KEEP |
| `…-ConversationHistoryTable` | phoneHash(HASH) | 0 | 0 | 0.0 | expiresAt | - | 56 | 4 | 3 | KEEP (dormant feature; empty, costs $0) |
| `…-ConversationMetaTable` | conversationId(HASH) | 0 | 0 | 0.0 | - | - | 259 | 0 | 2 | KEEP (dormant feature; empty, costs $0) |
| `…-CrmActivities` | activityId(HASH) | 3 | 0 | 0.0 | - | - | 48 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-CrmLeads` | leadId(HASH) | 3 | 0 | 0.0 | - | - | 48 | 0 | 2 | KEEP (dormant feature; empty, costs $0) |
| `…-CrmOpportunities` | opportunityId(HASH) | 2 | 0 | 0.0 | - | - | 46 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-CrmPipelines` | pipelineId(HASH) | 1 | 0 | 0.0 | - | - | 32 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-CrmStages` | stageId(HASH) | 1 | 0 | 0.0 | - | - | 32 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-CustomerSessionsTable` | sidHash(HASH) | 0 | 5 | 14.9 | absoluteExpiresAt | - | 169 | 680 | 7 | KEEP |
| `…-DLQMessagesTable` | id(HASH) | 0 | 0 | 0.0 | expiresAt | - | 56 | 0 | 3 | KEEP (dormant feature; empty, costs $0) |
| `…-DLTTemplates` | templateId(HASH) | 0 | 0 | 0.0 | - | - | 4,078 | 0 | 6 | KEEP (dormant feature; empty, costs $0) |
| `…-DocumentHistoryTable` | historyId(HASH) | 0 | 6 | 0.8 | - | - | 44 | 6 | 1 | KEEP |
| `…-DocumentTable` | documentId(HASH) | 4 | 35 | 15.6 | - | - | 258 | 148 | 5 | KEEP |
| `…-DownloadGrantsTable` | grantId(HASH) | 1 | 0 | 0.0 | expiresAt | - | 115 | 80 | 6 | KEEP (dormant feature; empty, costs $0) |
| `…-FaqTable` | faqId(HASH) | 1 | 0 | 0.0 | - | - | 36 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-FlowDraftTable` | draftKey(HASH) | 0 | 0 | 0.0 | ttl | - | 50 | 0 | 3 | KEEP (dormant feature; empty, costs $0) |
| `…-FlowLogTable` | logId(HASH) | 3 | 1 | 0.2 | ttl | - | 68 | 1 | 4 | KEEP |
| `…-FlowRegistryTable` | flowId(HASH) | 4 | 15 | 14.7 | - | - | 289 | 65 | 2 | KEEP |
| `…-FlowSubmissionTable` | submissionId(HASH) | 8 | 2 | 1.9 | - | - | 2,842 | 19 | 14 | KEEP |
| `…-IdentityClaimsTable` | claimKey(HASH) | 0 | 46 | 4.3 | - | - | 138 | 72 | 1 | KEEP |
| `…-InvoiceAssetsTable` | invoiceId(HASH) assetType(RANGE) | 0 | 12 | 3.0 | - | - | 275 | 52 | 6 | KEEP |
| `…-InvoiceDeliveryLogTable` | invoiceId(HASH) timestamp(RANGE) | 0 | 26 | 8.5 | - | - | 160 | 80 | 4 | KEEP |
| `…-InvoiceItemsTable` | invoiceId(HASH) itemIndex(RANGE) | 0 | 9 | 1.1 | - | - | 136 | 45 | 4 | KEEP |
| `…-InvoiceSequenceTable` | fy(HASH) | 0 | 1 | 0.0 | - | - | 82 | 19 | 5 | KEEP |
| `…-InvoicesTable` | invoiceId(HASH) | 3 | 8 | 6.3 | - | - | 783 | 135 | 14 | KEEP |
| `…-LinkClicksTable` | shortCode(HASH) clickedAt(RANGE) | 0 | 1,080 | 192.7 | - | - | 68 | 266 | 2 | KEEP + TTL - click log stores source IP and user agent with no expiry. |
| `…-MediaFilesTable` | id(HASH) | 0 | 46 | 12.9 | - | - | 140 | 80 | 6 | KEEP |
| `…-MessagesTable` | id(HASH) | 5 | 278 | 130.5 | expiresAt | - | 1,463 | 27,888 | 36 | KEEP |
| `…-NotificationAttempts` | attemptId(HASH) | 1 | 0 | 0.0 | expiresAt | - | 44 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-NotificationDeliveries` | deliveryId(HASH) | 2 | 0 | 0.0 | expiresAt | - | 44 | 0 | 2 | KEEP (dormant feature; empty, costs $0) |
| `…-NotificationEvents` | eventClaimKey(HASH) | 1 | 0 | 0.0 | expiresAt | - | 44 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-NotificationOutbox` | jobId(HASH) | 1 | 0 | 0.0 | expiresAt | - | 44 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-OrderTable` | orderId(HASH) | 6 | 5 | 8.2 | - | - | 10,070 | 93 | 20 | KEEP |
| `…-PartnerLedger` | wabaId(HASH) ts(RANGE) | 0 | 0 | 0.0 | ttl | - | 32 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-PartnerWallet` | wabaId(HASH) | 0 | 0 | 0.0 | - | - | 69 | 0 | 3 | KEEP (dormant feature; empty, costs $0) |
| `…-PaymentAttemptsTable` | paymentAttemptId(HASH) | 3 | 7 | 4.8 | - | - | 410 | 142 | 7 | KEEP |
| `…-PaymentsTable` | id(HASH) | 2 | 9 | 3.6 | - | - | 182 | 47 | 10 | KEEP |
| `…-ProductsTable` | id(HASH) | 3 | 29 | 21.9 | - | NEW_AND_OLD_IMAGES | 24,449 | 418 | 37 | KEEP - stream feeds two meta-catalog-sync aliases (intended). |
| `…-PstnSoftphoneSessions` | sessionId(HASH) | 0 | 0 | 0.0 | expiresAt | - | 44 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-PushTokensTable` | id(HASH) | 0 | 0 | 0.0 | - | - | 44 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-RateLimitTable` | id(HASH) | 0 | 25 | 4.4 | lastUpdatedAt | - | 66 | 3,467 | 9 | KEEP |
| `…-RazorpayWebhookLogTable` | id(HASH) | 2 | 28 | 45.3 | expiresAt | - | 199 | 353 | 7 | KEEP |
| `…-RequestStatusHistoryTable` | historyId(HASH) | 2 | 1 | 0.2 | - | - | 56 | 1 | 2 | KEEP |
| `…-ScheduledMessagesTable` | id(HASH) | 1 | 0 | 0.0 | - | - | 58 | 0 | 3 | KEEP (dormant feature; empty, costs $0) |
| `…-SecureFilesTable` | fileId(HASH) | 1 | 2 | 1.2 | - | - | 119 | 6 | 2 | KEEP |
| `…-SeoToolsTable` | id(HASH) | 2 | 2,887 | 9,570.0 | - | - | 3,565,717 | 73,869 | 7 | KEEP - blog store; 3.57M RCU / 30 d driven by build-time fetches. |
| `…-ServiceRequestsTable` | requestId(HASH) | 2 | 0 | 0.0 | - | - | 189 | 0 | 7 | KEEP (dormant feature; empty, costs $0) |
| `…-ShortLinksTable` | shortCode(HASH) | 0 | 10 | 2.4 | - | - | 253 | 282 | 4 | KEEP |
| `…-SiteLanguageCache` | cacheKey(HASH) | 0 | 404 | 116.3 | expiresAt | - | 798 | 1,815 | 2 | KEEP |
| `…-SmsOutboundTable` | messageId(HASH) | 0 | 0 | 0.0 | - | - | 46 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-SystemConfigTable` | id(HASH) | 0 | 42 | 21.9 | - | - | 656 | 235 | 24 | KEEP |
| `…-SystemEventTable` | id(HASH) | 2 | 190 | 54.1 | ttl | - | 83 | 1,311 | 1 | KEEP |
| `…-TemplateAnalyticsTable` | id(HASH) | 1 | 0 | 0.0 | - | - | 42 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-ThreadOwnershipTable` | threadKey(HASH) recordType(RANGE) | 0 | 45 | 7.8 | expiresAt | - | 42 | 2,381 | 1 | KEEP |
| `…-VoiceAwsTable` | id(HASH) | 0 | 0 | 0.0 | expiresAt | - | 52 | 0 | 6 | KEEP (dormant feature; empty, costs $0) |
| `…-VoiceCDRTable` | id(HASH) | 0 | 31 | 20.8 | expiresAt | NEW_IMAGE | 117 | 351 | 8 | KEEP - stream enabled; confirm consumer. |
| `…-WebhookDedup` | eventId(HASH) | 0 | 234 | 30.5 | ttl | - | 76 | 1,320 | 7 | KEEP |
| `…-WhatsAppCallingTable` | id(HASH) | 1 | 0 | 0.0 | ttl | - | 60 | 18 | 6 | KEEP (dormant feature; empty, costs $0) |
| `…-WhatsAppGroupTable` | id(HASH) | 2 | 0 | 0.0 | - | - | 34 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-WhatsAppInboundTable` | id(HASH) | 2 | 119 | 68.0 | expiresAt | - | 314 | 641 | 18 | KEEP |
| `…-WhatsAppOutboundTable` | id(HASH) | 2 | 68 | 34.3 | expiresAt | - | 2,045 | 5,515 | 21 | KEEP |
| `…-WhatsAppPhonesTable` | displayPhoneNumber(HASH) | 0 | 0 | 0.0 | - | - | 34 | 0 | 1 | KEEP (dormant feature; empty, costs $0) |
| `…-WhatsAppVoiceTable` | messageId(HASH) | 0 | 0 | 0.0 | expiresAt | - | 54 | 0 | 7 | KEEP (dormant feature; empty, costs $0) |
| `wecare-workspace-mcp` | pk(HASH) | 0 | 19 | 7.6 | ttl | - | 1,731 | 273 | 2 | KEEP; deletion protection off |
