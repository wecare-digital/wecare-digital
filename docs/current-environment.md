# Current environment — read-only discovery

Phase 0 inventory for the WECARE.DIGITAL commerce / identity / verification / tracking
platform. Measured against account `775261844268` in `us-east-1` on **2026-09-26**, plus
Google Cloud project `wecaredigitalbw` and the live Meta WABA.

**Nothing was created, changed, deleted or deployed to produce this document.** Every AWS
call was a `Get*`/`List*`/`Describe*`; the two Meta facts were obtained by invoking
existing read-only Lambda routes, which hold their own credential and return no token.
No secret value was read, and `secretsmanager get-secret-value` was never called.

## Current provider architecture

The measured tables below are dated; this summary is the current architecture every section
is read against:

| Capability | Current implementation |
|---|---|
| Commerce | native AWS: `ProductsTable` catalogue, `CartTable`, the `CommerceKeys` table, `OrderTable`, and native checkout (`wecare-checkout`) paid through Razorpay |
| Blog | native: posts live in `SeoToolsTable` and are served by `wecare-blog-public` |
| Voice | Plivo PSTN, AWS End User Messaging voice, and Meta WhatsApp calling |
| SMS | AWS End User Messaging, registered under TRAI DLT |
| RCS | Sinch India |

## Relationship to the other Phase 0 document

`docs/compatibility.md` records vendor capability and versions. This document **does not
restate, re-rule or overwrite** it. It closes three rows that document had to leave
`⛔ BLOCKED` or unmeasured — live Meta WABA and template state, the Amazon SES sender
identity, and the Google Maps Platform key. Where the two documents agree, this one cites
theirs rather than duplicating it.

## Evidence classes

Same vocabulary as `docs/compatibility.md`, deliberately, so the two can be read together.

| Class | Meaning |
|---|---|
| `LIVE` | measured against the account or the provider during this session |
| `DOC` | read from current official vendor documentation during this session |
| `REPO` | asserted by this repository's code or docs; dated, not re-measured |
| `BLOCKED` | could not be established, with the blocker named |

Per `.kiro/steering/00-current-owner-overrides.md` (retired 2026-10-09, af7858fa), every count below is a **dated
snapshot**. Re-derive at the start of each phase using §9; do not carry these numbers
forward on trust.

---

## 1. Identity and boundary

| RESOURCE | REGION | NAME | PURPOSE | REUSABLE? | ACTION REQUIRED |
|---|---|---|---|---|---|
| AWS account | `us-east-1` | `775261844268` | the only account for this project | YES | none |
| IAM principal | global | `AWSReservedSSO_AdministratorAccess_39eb59d8bf7f2071` (Identity Center user `wecare-user`) | `AWS_PROFILE=wecare-prod` through sso-session `wecare`, since 2026-10-25 | YES | the root access key is Inactive since 2026-10-25 10:02 UTC; the owner removes its `~/.aws/credentials` entry, then deletes it after the soak — `docs/migrations/b0-retire-root-access-keys.md` |
| Google Cloud project | global | `wecaredigitalbw` (`756034744787`) | Maps / Places / Translate / Vision | YES | see §6 — key restrictions are wrong |
| Meta WABA | n/a | `2094615664435155` "WECARE.DIGITAL" | WhatsApp sender + payments | YES | none |

`AWS_INVENTORY_REQUIRES_RUNTIME_VERIFICATION` is **not** raised: the connector enumerated
every service asked of it.

---

## 2. AWS compute, API and data

| RESOURCE | REGION | NAME | PURPOSE | REUSABLE? | ACTION REQUIRED |
|---|---|---|---|---|---|
| Lambda | `us-east-1` | 65 functions | whole platform backend | YES | 64 `Zip`/`python3.12`, 1 `Image` (`wecare-docs-scraper`). No Node.js function exists |
| Lambda alias | `us-east-1` | `live` on the 6 audited functions | production traffic target | YES | new code must publish a version and move `live` |
| HTTP API | `us-east-1` | `zllr9lrg7j` `wecare-digital-api` | the single API front door | YES | **361 routes, 0 authorizers, 361 × `AuthorizationType=NONE`** |
| HTTP API stage | `us-east-1` | `prod`, `AutoDeploy=true`, access logging on | n/a | YES | none |
| DynamoDB | `us-east-1` | **79 tables**, all `stack-wecare-digital-*` | all application state | PARTIALLY | no customer/OTP/cart/checkout/tracking table exists |
| SQS | `us-east-1` | 8 queues (4 work + 4 DLQ) | bulk, inbound, outbound, notification | YES | reuse; do not add a parallel queue family |
| EventBridge | `us-east-1` | 6 rules (4 scheduled, 2 event) | cleanup, token refresh, scheduler | YES | `wecare-scheduled-messages-trigger` runs `rate(5 minutes)` |
| S3 | `us-east-1` | `wecare-digital-get`, `wecare-digital-mta-sts`, `wecare-credential-backups-…`, `wecare-maintenance-reports-…`, CDK assets | media, file delivery, MTA-STS, backups | YES | no billing-document bucket yet. **`wecare-digital-get` is gone** — `HeadBucket` returns 404, confirmed 2026-09-29; a deleted bucket has no undelete, and its contents survive only in `wecare-digital-get` thanks to the 2026-09-28 parity sync |
| CloudFront | global | **2 distributions**: `E1SZBXLQ4XNLJ7` (`mta-sts.wecare.digital`), `E2GP22R4BIFGQ3` (`/get` origin, no alias, default CloudFront cert) | MTA-STS, file origin | YES | re-measured 2026-09-29. `ERCXSFDL0VM8X` and its 2026-09-28 replacement `E1DP37QIS4G0T4` are both **gone** (`NoSuchDistribution`) and `wecare-digital-get` is **NXDOMAIN** again, so the row-374 recovery has been undone — see the ACM row and matrix row 410 |
| ACM | `us-east-1` | **exactly 1 cert**, `f75d0db0-d476-443a-b787-96c4931862d2`, SANs `wecare.digital` + `*.wecare.digital`, expires 2027-03-12 | TLS for the Amplify domain **and** `E1SZBXLQ4XNLJ7` | YES | consolidated 2026-09-29; the single-name `mta-sts` cert was retired. 0 certs in `us-east-2/us-west-1/us-west-2/ap-south-1/eu-west-1/eu-central-1` across all 7 statuses. No IaC declares a cert, so this ARN lives only on the live resources |
| Route 53 | global | `Z03939753QJGZ6ZD6BXO8` `wecare.digital.` (42 records) | DNS | YES | fail-closed email posture — read `email-auth-dns` steering first |
| KMS | `us-east-1` | `alias/wecare-secrets-manager`, `alias/wecaredigital` | secret + backup encryption | YES | none |
| Amplify Hosting | `us-east-1` | `d22dm4b0jn71jw` `wecare.digital`, repo `wecare-digital/wecare-digital`, **23 custom rules** | public site hosting | YES | redirects/headers live here, not in `next.config.js` |
| Cognito | `us-east-1` | `us-east-1_cSx0RHCIR` `WECARE.DIGITAL` | staff/admin | YES | MFA `OPTIONAL`, password min **8**, deletion protection ON |
| Cognito | `us-east-1` | `us-east-1_46ULYuukt` `WECARE.DIGITAL-CUSTOMERS` | customers, phone-keyed `CUSTOM_AUTH` | YES | MFA `OFF`, password min 16, **deletion protection INACTIVE**, 1 user |
| WAFv2 | `us-east-1` | **none** | n/a | NO | `wecare-cognito-waf` (REGIONAL, both pools) and `wecare-amplify-waf` (CLOUDFRONT) were **deleted 2026-09-28** by owner cost decision. 0 web ACLs in either scope |
| Secrets Manager | `us-east-1` | 25 secrets | all provider credentials | YES | none |
| CloudFormation | `us-east-1` | no stacks in a live state | n/a | n/a | infrastructure is Amplify Gen 2 + scripts, not CFN stacks |

Two `⚠️` corrections to the owner-overrides snapshot in
`.kiro/steering/00-current-owner-overrides.md` (retired 2026-10-09, af7858fa), which is exactly why that file says to
rediscover: **routes are 361, not 332** (still 0 authorizers, still all `NONE`), and
**regional WebACLs are 1, not 0**.

### What is reusable for this build, and what is genuinely absent

Reusable as-is — do not rebuild:

- The Cognito `CUSTOM_AUTH` WhatsApp OTP path
  (`amplify/functions/auth/customer-whatsapp-auth/handler.py`), including the WABA
  isolation gate and the `MAX_ATTEMPTS=3` / `OTP_TTL_SECONDS=600` challenge.
- The two-pool staff/customer separation and the issuer-pinned customer token check in
  `amplify/functions/core/secure-files/handler.py::_customer_identity`.
- The phone-normalisation pair (`normaliseMobile` in TS, `_normalise_phone` in Python) —
  they must stay byte-identical.
- Real webhook idempotency (`lambda_utils/webhook_dedup.py`, `idempotency.py`) and the
  `WebhookDedup` table's atomic conditional claim.
- The invoice engine: 16 `/invoices*` routes, 5 tables, per-FY statutory sequence.
- `AgentApprovalsTable` as the working precedent for single-use compare-and-swap
  (`attribute_not_exists(consumedAt) AND expiresAt > :now`).

Absent, confirmed by grep returning zero and by the 79-table list:

- Any canonical `customerId`, `CUSTOMER#`/`UNIQUE#PHONE#`/`UNIQUE#EMAIL#` key, ULID
  generation, or `TransactWriteItems` anywhere in application code. The de-facto customer
  record is `ContactsTable` keyed on `id` with a `contactId` alias
  (`lambda_utils/contact_key.py`).
- OTP **at rest**. The only OTP that exists lives inside a Cognito auth session, unhashed;
  there is no `otpHash`, no resend counter and no send-side rate limit. The one limiter
  present counts unregistered-number *probes* and **fails open** by design.
- Email verification of any kind.
- Cookie/CSRF sessions. Customer sessions are a 60-minute Cognito access token in
  `sessionStorage`; there is no session table and no rotation.
- `trackingToken` — zero matches repo-wide at this snapshot. Order tracking was keyed on a
  guessable `orderId`. (Cart and checkout have since been built natively — see the current
  provider architecture above.)
- Any structured address entity. Addresses are flat strings on Contact/Order; no
  `googlePlaceId`, no lat/lng, no verification state.
- Any page-composition system. `PageSectionRenderer`/`sectionType` return zero matches.

---

## 3. Frontend and public surface

| RESOURCE | REGION | NAME | PURPOSE | REUSABLE? | ACTION REQUIRED |
|---|---|---|---|---|---|
| Web app | n/a | Next.js `16.2.9` + React `19.2.7`, Pages Router, `output: 'export'` | public site + 118-page admin | YES | **no server at runtime**: no middleware, no route handlers |
| Styling | n/a | hand-written global CSS + CSS Modules + styled-jsx; `src/styles/tokens.css` | design system | PARTIALLY | **no Tailwind**; breakpoints are inline and **desktop-first** (`max-width` dominates) |
| Public routes | n/a | 9 of 127 pages public, via exact-match allowlist in `src/pages/_app.tsx` | public site | YES | a public page missing from `PUBLIC_PAGE_META` renders an **empty body with HTTP 200** |
| Admin | n/a | `[retired public path 2de923b8]/*` (71), `[retired public path 89347bb2]/*`, `[retired public path 9463c8d8]/*`, … behind Amplify Authenticator | staff console | YES | `[retired public path 84a04c24]` is a 10-line redirect stub, not an app |
| Blog | n/a | `/blog` + `/post/[slug]`, `getStaticPaths` + `fallback:false` | publishing | YES | path is `/post/[slug]`, **not** `/blog/[slug]` |
| Test suite | n/a | intentionally removed | n/a | NO | Validate with build, typecheck, lint and targeted operational verification scripts |
| Deployment | n/a | Amplify Hosting on `wecare.digital` | production auto-build | YES | No `.github/workflows` automation or GitHub Actions OIDC path remains |

Two structural constraints that shape every customer-facing requirement in the brief:

- **`output: 'export'` means there is no server.** Every dynamic path needs
  `getStaticPaths` or client-side fetch against API Gateway. A `trackingToken` can never be
  validated in the frontend.
- **Redirects and headers live in Amplify `customRules`** (23 of them), not
  `next.config.js`. The catch-all is `404-200`, which is why `_app.tsx` corrects the
  address bar with `history.replaceState`.

Of the **23** public routes the brief lists in §34, **3 exist** (`/`, `/blog`, `/contact`),
**1 exists at a different path** (`/blog/[slug]` is served as `/post/[slug]`), and **19 do
not exist**. Verified by directory listing: there is no `src/pages/register`, `verify`,
`profile`, `address`, `account`, `shop`, `product`, `cart`, `checkout`, `orders`, `track` or
`billing`. The three further account routes in §22 (`/account/orders/[orderNumber]`,
`/account/billing`, `/account/security`) are also absent, so 22 of 26 named customer routes
are greenfield.

---

## 4. Meta / WhatsApp — measured live, closes a `BLOCKED` row

`docs/compatibility.md` §2 records this as `⛔ BLOCKED` because a direct HTTPS probe
returned `No authorization token provided`. That is avoidable: `require_auth` exempts
Lambda-to-Lambda invokes, so the existing read-only routes can be called internally and
the Meta token never enters context. Measured that way, 2026-09-26:

| Item | Value | Evidence |
|---|---|---|
| WABA | `2094615664435155` "WECARE.DIGITAL", currency `INR`, timezone id `71` | `LIVE` `GET /waba/{id}` |
| Account review | `accountReviewStatus: APPROVED` | `LIVE` |
| Registration | `registrationStatus: COMPLETE` | `LIVE` |
| Sending / receiving | `enableSending: true`, `enableReceiving: true` | `LIVE` |
| Business | `Wecare.Digital` `382642103987922`, `status: APPROVED`, `type: SELF` | `LIVE` |
| Template namespace | `dc7ae993_4e97_4046_81f8_1454d729b8f2` | `LIVE` |
| Sender phone | id `1016149501586345` = **`+91 93309 94400`**, name `WECARE.DIGITAL` | `LIVE` |
| Quality | `qualityRating: GREEN` | `LIVE` |
| Platform | `platformType: CLOUD_API`, `isOfficialBusinessAccount: true` | `LIVE` |
| Code verification | **`codeVerificationStatus: EXPIRED`** | `LIVE` |
| OTP template | `wecare_otp`, `AUTHENTICATION`, `en`, **`APPROVED`** | `LIVE` re-measured 2026-09-30 ✅ |
| Payment template | `wecare_pay`, `UTILITY`, `APPROVED` | ⛔ **HISTORICALLY VERIFIED — NOT CURRENT.** Re-measured 2026-09-30: the WABA returns **only `wecare_otp`**. See the correction below |
| Templates total | 12 | ⚠️ **HISTORICAL.** The 2026-09-30 read returned **1** |
| Graph version | `v25.0` fleet-wide | `LIVE` env + `REPO` |

**Brief §4 and §66.4 are therefore satisfied at the provider**: the configured sender
identity really is `+91 93309 94400`, on the right WABA, with an APPROVED
`AUTHENTICATION` template, and the live Lambda env already points at exactly those ids.

### ⛔ Correction, 2026-09-30 — the payment template is not present

A live template read for WABA `2094615664435155` returned **exactly one** template, `wecare_otp`.
No `wecare_pay`, no `postpay_request_v1`, no `postpay_details_v1`. The rows above are left in place
with a date rather than deleted, because knowing the template *used* to exist is useful — but they
must not be read as current.

Why it matters rather than being tidy-up: a free-form interactive `order_details` message is only
deliverable inside the customer's 24-hour service window, and the OTP is delivered by a template
while the code is typed on the web — which sends no inbound message and therefore opens no window.
So the common checkout path may well need the template, and sending a template that does not exist
fails at Meta.

`lambda_utils/payment_readiness.evaluate_for_delivery()` now checks this: outside the window it
requires a template name **and** verifies it is `APPROVED` against a live read. A configured name
is not an approved template, which is the same mistake as trusting a configuration constant.

Creating and submitting the template is an owner action; no code here may do it.

### ⚠️ Correction, 2026-09-30 — the route count

The **361** figure recorded in this file is superseded: a paginated read returns **359**. Note that
an *unpaginated* `get_routes` returns 25, which looks like a mass deletion and is not — any future
count must paginate and say so. Authorizers remain 0 and all routes remain `AuthorizationType=NONE`.

Two qualifications, stated rather than smoothed over:

- `codeVerificationStatus: EXPIRED` is **not** currently blocking. The number is registered
  (`registrationStatus: COMPLETE`), sending is enabled and quality is GREEN, and a real
  round trip succeeded on 2026-09-25. It matters only if the number ever has to be
  re-registered or its display name re-verified, at which point it becomes owner-only work.
  Recording it as a blocker would be wrong; recording it as fine would be incomplete.
- `eventDestinations` came back empty from this endpoint, so **webhook subscription state is
  not verified here**. `docs/WEBHOOK-INVENTORY.md` is the record for that, and it carries
  its own open finding: `POST /plivo/answer` is unauthenticated and can send SMS.

`docs/compatibility.md` notes `inbound-whatsapp-handler:7309` carries
`if False:  # Phone 1 DISCONNECTED`. The live account contradicts the comment, not the
code path — the phone is connected and GREEN. That dead branch should be read as stale, and
resolved in the owning session's spec rather than here.

Payment capability is **not** re-measured. `wecare/meta/payments` exists,
`PAYMENT_WABA_ID=2094615664435155`, and `WECAREDIGITAL`/`WECAREUPI` are config names in
`src/config/constants.ts`, but `/{waba}/payment_configurations` was last read 2026-08-23.
`DOC` confirms the India surface the repo implements (`order_details`, `reference_id`,
per-WABA payment configuration, `GET /{phone_id}/payments/{config}/{reference_id}`,
webhook status notifications) is current.

---

## 5. Email — brief §8 is already largely satisfied

Absent from `docs/compatibility.md` entirely. Measured live:

| RESOURCE | REGION | NAME | PURPOSE | REUSABLE? | ACTION REQUIRED |
|---|---|---|---|---|---|
| SES identity | `us-east-1` | **`one@wecare.digital`** — `EMAIL_ADDRESS`, verified, sending enabled | the brief's verification sender | **YES** | attach the config set explicitly at send time (identity has none) |
| SES identity | `us-east-1` | `wecare.digital` — `DOMAIN`, verified, DKIM `SUCCESS`, signing on, 3 tokens | domain authentication | YES | none |
| SES identity | `us-east-1` | `wecare-digital.awsapps.com` — verified | WorkMail | YES | not for customer mail |
| SES config set | `us-east-1` | `wecare-digital` — TLS `REQUIRE`, reputation metrics on, suppression on `BOUNCE`+`COMPLAINT`, pool `ses-shared-pool` | deliverability | YES | pass `ConfigurationSetName` on every send |
| SES account | `us-east-1` | production access **enabled**, 50,000/24h, 14/s, `EnforcementStatus: HEALTHY` | quota | YES | none |
| Lambda | `us-east-1` | `wecare-cognito-custom-message` — `SENDER_ADDRESS=one@wecare.digital` | Cognito mail | YES | precedent already uses the brief's sender |
| Lambda | `us-east-1` | `wecare-outbound-email` — SES **v1** `send_email`, `FROM_EMAIL=noreply@wecare.digital` | CRM outbound | PARTIALLY | v1 API, no config set, wrong From for verification mail |

So `one@wecare.digital` needs **no provider work** — it is verified, sending-enabled, and
not on the suppression list. What is missing is application-side: there is no email OTP
code path, and the one SES client in the repo is classic v1 with no configuration set.

The domain runs **fail-closed** email (`DMARC p=reject; sp=reject`, MTA-STS `enforce`).
Read `.kiro/steering/email-auth-dns.md` (retired 2026-10-09, af7858fa) before touching MX or adding a sender: under
`p=reject` an unaligned message hard-bounces rather than landing in spam.

---

## 6. Google Maps Platform — one over-broad key, pointed at a deprecated API

Absent from `docs/compatibility.md`. This is the most actionable finding in this document.

| Item | Measured | Evidence |
|---|---|---|
| Key | **one** key, `WECARE Unified Google API Key`, uid `1febded3-…`, created 2026-08-17 | `LIVE` `api-keys list` |
| API targets on that key | **~50 services**, incl. `places-backend.googleapis.com` (legacy Places), `addressvalidation`, `geocoding-backend`, `maps-backend`, `translate`, `vision`, `youtube` | `LIVE` |
| `places.googleapis.com` in the key's API targets | **NO** | `LIVE` |
| `places.googleapis.com` enabled on the project | **YES** | `LIVE` `services list --enabled` |
| `addressvalidation.googleapis.com` enabled | **YES** | `LIVE` |
| Key restriction type | `browserKeyRestrictions`, referrers `https://wecare.digital/*`, `https://*.wecare.digital/*`, **`places.googleapis.com`**, **`*.googleapis.com/*`** | `LIVE` |
| Repo usage | server-side only, via the canonical `wecare/google/cloud` → Places API (New) `places.googleapis.com/v1/places:autocomplete` and `/v1/places/{placeId}`, key in the `X-Goog-Api-Key` header (migrated off legacy `maps/api/place/*` and off URL-borne keys, 2026-10-05) | `REPO` `whatsapp-templates/handler.py` |
| Legacy Places status | **deprecated**; Google directs migration to Autocomplete (New) / Places API (New) | `DOC` |

Four distinct defects, each against a specific clause of the brief:

1. **One key spans browser and backend across ~50 APIs.** Brief §17 requires separate
   restricted keys with least privilege. A single key used both ways cannot satisfy both
   restriction models.
2. **The restrictions are browser-type but the only consumer is a Lambda.** The two
   referrer entries `places.googleapis.com` and `*.googleapis.com/*` are not referrers a
   browser would ever send; they read as an attempt to make a server-side call pass a
   browser restriction. That is a restriction that does not restrict.
3. **The key cannot call the new Places API.** `places.googleapis.com` is enabled on the
   project but is not in the key's `apiTargets`, so a migration to Autocomplete (New) will
   fail with a key-restriction error until that target is added.
4. **The code calls the deprecated legacy endpoints**, and the existing Places proxy exists
   only to fill WhatsApp location-template parameters — not to capture a customer address.
   Brief §15/§16 need structured components, `googlePlaceId`, lat/lng and a confirmation
   step; the current proxy returns only `{description, placeId}` and
   `{latitude, longitude, name, address}`.

Also noted, not recommended: `_get_gmaps_key()` calls `secretsmanager.get_secret_value`
directly, which `.kiro/steering/aws-agent-rules.md` (retired; now .kiro/steering/00-common.md) forbids, and logs `str(e)` on failure,
which is looser than the secret-handling rule. Both are **pre-existing**, recorded here as
inventory, not as a pattern to copy.

---

## 7. Commerce and blog — native AWS

Commerce and the blog run entirely on AWS. There is no third-party commerce or blog backend,
and no Lambda, route, secret or table for one.

| RESOURCE | REGION | NAME | PURPOSE |
|---|---|---|---|
| DynamoDB | `us-east-1` | `stack-wecare-digital-ProductsTable` | product catalogue (products, variants, prices, media refs) |
| DynamoDB | `us-east-1` | `stack-wecare-digital-CartTable` | customer carts |
| DynamoDB | `us-east-1` | `stack-wecare-digital-CommerceKeys` | commerce idempotency and order-number keys |
| DynamoDB | `us-east-1` | `stack-wecare-digital-OrderTable` | orders, created only after verified payment |
| Lambda | `us-east-1` | `wecare-checkout` (`live`) | native checkout; payment through Razorpay |
| DynamoDB | `us-east-1` | `stack-wecare-digital-SeoToolsTable` | blog posts |
| Lambda | `us-east-1` | `wecare-blog-public` (`live`) | public blog read API |

---

## 8. Gaps

Severity per `.kiro/steering/maintenance-reporting.md` (retired 2026-10-09, af7858fa). Not inflated: several brief clauses
turned out to be already satisfied, and they are recorded as such.

| # | Gap | Sev | Current | Desired | Auto-fixable |
|---|---|---|---|---|---|
| G3 | Single Google key spans browser + backend + ~50 APIs, with non-referrer referrer entries | `HIGH` | one unified browser key | separate browser and server keys, least privilege | Partly — key work is Google-console + gcloud |
| G4 | Key omits `places.googleapis.com`; code calls deprecated legacy Places | `HIGH` | legacy Autocomplete | Places API (New) + Address Validation | YES once G3 lands |
| G5 | No OTP at rest: unhashed, in-session only; no resend counter, no send-side rate limit; the one limiter fails open | `HIGH` | Cognito-session OTP | `otpHash`, TTL, attempt/resend counters, per-phone and per-IP limits | YES |
| G6 | No canonical customer identity; no uniqueness enforcement | `HIGH` | `ContactsTable.id` + Cognito username | `customerId` + `UNIQUE#` markers under `TransactWriteItems` | YES |
| G7 | No email verification path | `HIGH` | none | email OTP from the already-verified `one@wecare.digital` | YES |
| G8 | 361 routes, 0 authorizers, all `NONE`; **no WebACL anywhere** since 2026-09-28 | `HIGH` | handler-level auth only | explicit auth strategy. **WAF is no longer part of the target** — the owner deleted both ACLs and withdrew the requirement | Partly |
| G9 | Tracking authorised by guessable `orderId`; no `trackingToken` | `HIGH` | `[retired public path 282d0fd5]/{orderId}` | high-entropy opaque token, hash at rest | YES |
| G10 | No cart or checkout at this snapshot | `HIGH` | greenfield | native cart and checkout | **CLOSED** — native `CartTable`, `CommerceKeys`, `OrderTable` and `wecare-checkout` (§7) |
| G11 | Customer session is a 60-min token in `sessionStorage`; no CSRF, rotation or revocation | `MEDIUM` | bearer token in tab storage | documented decision or HttpOnly cookie + CSRF | YES — but `output:'export'` constrains it |
| G12 | Graph version reaches runtime 3 ways (env default, module constant, URL literal) | `MEDIUM` | `v25.0`, uncentralised | one configurable source | YES |
| G13 | No structured address entity | `MEDIUM` | flat strings | `CustomerAddress` with `googlePlaceId` + lat/lng + confirmation | YES |
| G14 | No page-composition system | `MEDIUM` | hard-coded components | typed page sections | YES |
| G15 | Frontend is desktop-first (`max-width` queries), no breakpoint tokens | `MEDIUM` | ad-hoc queries | mobile-first scale per brief §30-31 | YES |
| G17 | Customer pool deletion protection `INACTIVE`; staff password min 8 | `LOW` | as measured | protection on; stronger policy | YES |
| G18 | `codeVerificationStatus: EXPIRED` on the sender | `INFORMATIONAL` | not blocking; sending enabled, GREEN | re-verify only if re-registration is needed | NO — owner-only |
| G19 | Places proxy calls `get_secret_value` directly and logs `str(e)` | `LOW` | pre-existing | by-reference resolution; log exception type | YES |

### Brief clauses already satisfied

Worth stating so nobody rebuilds them: §4 canonical WhatsApp sender (live, APPROVED,
GREEN), the §5 approved `AUTHENTICATION` template, §8's authorised `one@wecare.digital`
sender (verified, DKIM `SUCCESS`, production access, correct SPF/DKIM/DMARC posture), §19
passwordless WhatsApp sign-in (live via `CUSTOM_AUTH`), §37's webhook idempotency
primitives, and §38's invoice/receipt generation.

### Brief baselines that did not survive verification

Two were already recorded and this run agrees: `v26.0` (rejected in favour of `v25.0`) and
Astro (the storefront is Next.js 16). One more, from §31/§62: **Tailwind is not installed**,
so the responsive rebuild is CSS work in the existing hand-written system, not a
utility-class retrofit.

Latest published versions checked this session, for the compatibility matrix the brief §60
asks for: `next 16.3.6` (repo `^16.2.9`), `typescript 7.0.2` (repo `^6.0.3`, a **major**
behind), `aws-cdk-lib 2.271.0` (repo pinned `2.270.0`),
`@playwright/test 1.63.0`. Local toolchain: Node `v24.21.0` (`.nvmrc` `24`), npm `11.19.0`.

---

## 9. Re-derivation commands

Per the owner-overrides execution rule, run these at the start of each phase instead of
trusting §1-§8.

```bash
aws sts get-caller-identity
aws lambda list-functions --query 'length(Functions)'
aws lambda list-functions --query 'Functions[].Runtime' | sort -u
aws apigatewayv2 get-apis --query 'Items[].[ApiId,Name]'
aws apigatewayv2 get-routes --api-id zllr9lrg7j --query 'length(Items)'
aws apigatewayv2 get-authorizers --api-id zllr9lrg7j --query 'length(Items)'
aws dynamodb list-tables --query 'length(TableNames)'
aws cognito-idp list-user-pools --max-results 60 --query 'UserPools[].[Id,Name]'
aws wafv2 list-web-acls --scope REGIONAL --query 'WebACLs[].Name'
aws sesv2 list-email-identities
aws sesv2 get-account --query '[ProductionAccessEnabled,SendQuota]'
aws secretsmanager list-secrets --query 'length(SecretList)'
aws amplify list-apps --query 'apps[].[appId,name]'

# Google key restrictions, without reading the key string
gcloud services api-keys list --format='json(displayName,restrictions)'

# Meta WABA + templates, live, token stays inside the Lambda
aws lambda invoke --function-name wecare-waba-management:live \
  --payload '{"httpMethod":"GET","path":"/waba/2094615664435155",
              "pathParameters":{"wabaId":"2094615664435155"}}' \
  --cli-binary-format raw-in-base64-out .scratch/waba.json
```

Graph version drift: `grep -rn "v25\.0" amplify/ src/ scripts/ config/` — expect hits in
all three shapes (env default, module constant, URL literal) until G12 is closed.
