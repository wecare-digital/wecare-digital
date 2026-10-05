# Security

Threat model and controls for the customer identity, verification, address, account and
public commerce surface. Companion to [`docs/spec.md`](spec.md) and
[`docs/design.md`](design.md); grounded in the measurements in
[`docs/current-environment.md`](current-environment.md).

Scope note: `R16` in
[`.kiro/specs/whatsapp-wix-commerce/requirements.md`](../.kiro/specs/whatsapp-wix-commerce/requirements.md)
owns the commerce threat list — forged and replayed webhooks, duplicate payment, amount and
currency manipulation, invoice duplication. This document owns identity, verification,
session, address, and the public web, and states the controls for the shared items rather
than restating the requirement.

## Current posture, measured

| Control | State | Note |
|---|---|---|
| API Gateway authorizers | **0** on 361 routes | every route reports `AuthorizationType=NONE`; authorisation is in-handler via `require_auth` |
| WAF on the API | **impossible, not missing** | WAFv2 cannot attach to an API Gateway **HTTP** API. Measured: `GetWebACLForResource` on the `zllr9lrg7j` stage ARN returns `WAFInvalidParameterException`. See T10 |
| WAF on Cognito | **none — deleted 2026-09-28** | `wecare-cognito-waf` was associated with `us-east-1_46ULYuukt` **and** `us-east-1_cSx0RHCIR`; both ACLs were deleted by owner cost decision. `get_web_acl_for_resource` now returns nothing for either pool. No per-IP limiting in front of public OTP sign-in |
| WAF on the Amplify app | **none — deleted 2026-09-28** | `wecare-amplify-waf` (blocking managed rule groups) is gone; `wafConfiguration` is `null` |
| Customer pool MFA | `OFF` | phone-keyed `CUSTOM_AUTH`; MFA is not the second factor here, possession of the WhatsApp number is |
| Customer pool deletion protection | `INACTIVE` | one accidental delete removes every customer login |
| Staff pool MFA | `OPTIONAL` | owner overrides make admin MFA a required target |
| Staff password minimum | **8** | weak for an account that can reach production data |
| Secrets | 25, in Secrets Manager, KMS-backed | `wecare/wix/headless-api-key` was empty at discovery and was **populated on 2026-09-26** (commit `82fa0d5a`), without the value entering argv |
| Email authentication | `DMARC p=reject; sp=reject`, MTA-STS `enforce`, DKIM `SUCCESS` | fail-closed: a misconfiguration bounces mail, it does not spam-folder it |
| OTP at rest | **none** | the only OTP lives unhashed inside a Cognito auth session |
| Tracking authorisation | **order id only** | guessable-adjacent; no token concept exists |
| Google API key | one key, ~50 APIs, browser+backend | referrer list contains entries no browser sends |

`AuthorizationType=NONE` must not be read as "unauthenticated". It means the gateway is not
deciding. Whether a route is protected has to be asserted **per handler** — and the reverse
error is just as real: the `route-auth` workflow exists because a substring match once let
`/wa-business/webhooks-anything` through an exemption intended for `/wa-business/webhooks`.

---

## T1 — Account enumeration

**Threat.** An attacker with a list of phone numbers or email addresses learns which belong
to customers, by response body, status code, or timing.

**Why this is live.** The existing `CUSTOM_AUTH` trigger returns `registered: "false"` for an
unknown number. That is a considered trade in its own context, documented at length in the
handler: every recipient is provisioned by hand, there is no self-signup, and hiding the flag
stranded real people on a code screen that no code would ever satisfy — a dead end reached
within a minute of the first real test.

**Public self-registration removes the justification.** The flag becomes a customer-list
oracle against an endpoint anyone can reach.

**Controls.**

- The registration and sign-in surfaces do not return `registered`.
- Responses for existing and unknown subjects are identical in body, status and shape.
- The work done before responding does not branch on existence in a way an attacker can time:
  the rate-limit write and the challenge write happen either way.
- The dead end is solved differently — the UI states that a code is on its way *if the number
  can receive one*, offers resend, and offers a correction path. Silence is not restored.
- Per-phone, per-email and per-IP budgets make sweeping a list expensive.
- The operator-provisioned `/get` flow keeps its current behaviour; it is a different
  population with a different threat profile.

**Residual.** A determined attacker still learns something from a slow, low-rate probe of a
single number. Accepted: the disclosure is "this number may be a customer" to someone who
already has the number.

## T2 — OTP brute force and replay

**Threat.** Guessing a 6-digit code, or reusing a code that already worked.

**Controls.**

- Max attempts per challenge; the counter is an atomic `ADD`, not read-modify-write.
- Constant-time comparison.
- Single use enforced by `ConditionExpression: attribute_not_exists(usedAt)`, so two
  concurrent submissions of the same correct code produce one success.
- Issuing a new challenge invalidates prior open challenges for the subject.
- Short TTL, checked in code as well as by the DynamoDB reaper — TTL deletion is
  best-effort and can lag by hours, so relying on it for expiry would leave a valid code
  alive well past `expiresAt`.
- Resend cooldown and a resend ceiling.

**Fail direction.** These limiters **fail closed**. This is deliberately the opposite of
`_probe_budget_exhausted`, which fails open. That function guards a usability flag where the
worst case of failing closed is locking a paying customer out of their own files; these guard
messaging spend and a brute-force window. Same mechanism, opposite default, each correct for
its own blast radius.

## T3 — OTP disclosure

**Threat.** The code reaches a log, a metric, a report, a response, or a transcript.

**Controls.**

- Only an HMAC of the code is stored, under a pepper read lazily from Secrets Manager.
- The plaintext exists in memory for the duration of one request and in the WhatsApp or email
  message. Nowhere else.
- No OTP in any log line, audit event, admin view, or maintenance report. The admin customer
  view shows verification *status*, never a code.
- **A secret must not appear in a logging expression at all** — not merely "must not be
  logged". CodeQL `py/clear-text-logging-sensitive-data` has failed this build twice on a line
  that could not leak anything: a ternary on a key's truthiness yielding a string literal.
  Moving the log to another function and reducing the value to a bool failed too, because taint
  is tracked across call boundaries. Reducing a secret to a boolean does not launder it. Remove
  the log or derive the value from something that never touched the secret. Do not suppress.
- Exception messages count. Log `type(exc).__name__`; log an exception's text only when your
  own code built that message from known-safe parts. The existing
  `logger.error(... 'error': str(e))` in the Places proxy is looser than this and is not a
  pattern to copy.

## T4 — Duplicate identity under concurrency

**Threat.** Two accounts for one human, created by a double-tap, a retry, or a race.

**Controls.** One `TransactWriteItems` writing the profile and both `UNIQUE#` markers, each
under `attribute_not_exists(PK)`. Read-then-write is prohibited — it has a window by
construction. `TransactionCanceledException` reasons distinguish a phone collision (route to
sign-in) from an email collision (route to audited conflict resolution) without that
distinction being visible to the caller.

**Verification.** Asserted by a concurrency test against a real conditional-write path. A mock
that cannot fail a condition proves nothing about the control.

## T5 — Session theft

**Threat.** An attacker obtains a customer access token and reads or mutates that customer's
data.

**Accepted design and its cost.** Per design ADR-6 the bearer token is retained in
`sessionStorage`, because `output: 'export'` means the frontend cannot set a cookie and
`api.wecare.digital` is a different host from `wecare.digital`.

**Blast radius, stated rather than implied.** An XSS on any public page can read the token and
exfiltrate a customer session.

**Controls.**

- `sessionStorage`, not `localStorage`: the session dies with the tab, so a shared or public
  browser does not retain it.
- 60-minute token, treated as expired 30 seconds early so a request cannot expire mid-flight
  and surface as a confusing 401.
- A `SESSION#` registry, so revocation is server-side and real rather than the client
  forgetting.
- Issuer pinning: `GetUser` first to prove signature and expiry, *then* the `iss` claim check
  to reject a staff-pool token. The order matters — checking an unverified claim first would
  trust attacker-supplied JSON.
- The token grants only that customer's own data.
- CSRF protection on sensitive mutations.

**Revisit trigger.** Introduce an API Gateway custom domain under `wecare.digital` and the
`HttpOnly; Secure; SameSite` cookie becomes straightforward; adopt it then.

## T6 — IDOR across customers

**Threat.** Changing an order number, address id, invoice id or session id in a URL to read
another customer's data.

**Controls.**

- Every read is authorised against `session.customerId`, never against the identifier in the
  request.
- Refusals are byte-identical between "not yours" and "does not exist", following the existing
  `_not_registered` precedent, which returns one 403 for both wrong-owner and nonexistent-file
  specifically so file ids cannot be probed. Returning 404 for one and 403 for the other is
  itself the disclosure.
- Order numbers are not capability tokens. `commerceOrderNumber` identifies; it does not
  authorise.

## T7 — Tracking token guessing

**Threat.** Reaching `[retired public path 282d0fd5]/...` or `/billing/...` for somebody else's order.

**Controls.**

- 256 bits from a CSPRNG. Not derived from the order number, the phone, or a timestamp.
- Stored only as `TRACKING#<sha256(token)>`; the token is unrecoverable from storage, so a
  database read does not yield working URLs.
- Invalid, expired and unknown tokens produce one indistinguishable response.
- Short-lived, and validated **in a Lambda** — the static export has no server and cannot
  validate anything.
- These routes are `noindex` and absent from the sitemap, so a token does not end up in a
  search index.
- `random` is never used for token generation. `secrets` / `os.urandom` only.

**Note on the existing surface.** `GET /wa-business/service/track/{orderId}` authorises on the
order id today. It is superseded, not extended.

## T8 — Credential exposure

**Threat.** A Meta token, Wix client secret, SES credential, Google key or OTP pepper reaches
source, a log, a bundle, a command line, or a permissions file.

**Controls.**

- Secrets Manager only, resolved **by reference**, lazily, at request time. Never at import
  scope — a module-scope read is cached for the life of the execution environment, so a
  rotation does not take effect until every warm sandbox recycles.
- `secretsmanager get-secret-value` is not called from a shell or from an agent script.
  `{{resolve:secretsmanager:...}}` for infrastructure.
- **No credential on a command line, in argv, or in an environment assignment on a command
  line.** This is not hypothetical here: on 2026-09-19 four live credentials were written into
  Kiro's own permissions file in cleartext, 141 copies across 6 files, because commands were
  run with the value inline and approved with "Always allow" — which records the entire
  command string permanently. `scripts/block_inline_secrets.py` runs as a PreToolUse hook and
  denies it.
- No secret in a maintenance report. `scripts/maintenance_report.py` refuses to write when
  credential-shaped material is detected.
- The browser receives no Wix credential, no Meta token, no Google server key, and no OTP
  pepper. Asserted by a test that greps the built bundle, because "we did not mean to" is not
  a control.
- `WIX_CLIENT_ID` and the Cognito public client id are *not* secrets and are safe to commit.

**Known open item, inherited.** `_get_gmaps_key()` in `whatsapp-templates/handler.py` calls
`get_secret_value` directly, against steering. Recorded as inventory, not carried into new
code; the new `AddressService` resolves by reference.

## T9 — The Google API key itself is the weakness

**Threat.** The unified key is usable from anywhere, for ~50 APIs, by anyone who obtains it.

**Measured.** One key, `WECARE Unified Google API Key`, 49 `apiTargets`, with
`browserKeyRestrictions` whose referrer list includes `places.googleapis.com` and
`*.googleapis.com/*`. Those are not referrers any browser sends; they read as an attempt to
make a server-side call satisfy a browser restriction. The result is a restriction that does
not restrict.

**The first diagnosis here was wrong, and the correction is the useful part.** This section
originally said the fix was to add `places.googleapis.com` to `apiTargets`. That target was
missing, it was added on 2026-09-26 — verified purely additive, 48 → 49, nothing lost — and
**the call still failed**, with `API_KEY_HTTP_REFERRER_BLOCKED`. Google refuses
referrer-restricted keys for server-side calls on both legacy Maps web services
(`REQUEST_DENIED: API keys with referer restrictions cannot be used with this API`) and
Places (New). The refusal is about the key's *type*, not its API list, so no edit to a browser
key could ever have fixed it. A configuration change is verified when the call succeeds, not
when the configuration reads as intended.

**Controls.**

- ✅ **A separate server key exists**, and **as of 2026-10-05 it lands in the canonical
  secret `wecare/google/cloud`**, not `wecare/google-maps-server`.
  `scripts/provision_maps_server_key.py --create` replaces only that secret's key fields
  (`api_key`, `unified_google_api_key`) through a read-merge-write, so the project metadata
  siblings survive; it now prints the preserved field **names** so the merge is checkable
  without reading the secret back. `apiTargets` is 7 services against the unified key's 49.
  The value never enters argv, a log, or an agent's context — the script captures it from
  `gcloud` in memory and writes it straight to Secrets Manager.

  **Dated correction.** This bullet previously named `wecare/google-maps-server` as the
  server-key store. That was true when the key was minted on 2026-09-26 and stopped being
  true on 2026-09-30, when the Google Cloud key behind it was deleted — see the BROKEN
  callout in `docs/operations.md`. The canonical id is the one every consumer already
  defaults to, which is what makes the owner's single rotation reach all of them.
- ✅ **Places calls are header-authenticated.** `whatsapp-templates/handler.py` calls Places
  API (New) on `places.googleapis.com` with the key in `X-Goog-Api-Key`. It no longer builds
  the key into a URL query string, which matters specifically because the server key carries
  no application restriction: a URL-borne key reaches provider access logs, request tracing,
  and — through the handler's own failure paths — a 502 body and a CloudWatch line.
  `tests/test_places_new_server_transport.py` pins both the header and the absence of any
  `key=` parameter.
- **It deliberately carries no application restriction**, and that is a considered trade, not
  an oversight. Lambda has no stable egress IP, so `--allowed-ips` is unavailable. A key with
  no application restriction is usable by anyone who holds it, which is exactly why it is
  narrow (4 services), separate from the browser key, and in Secrets Manager. Tightening it
  further needs a NAT gateway with an Elastic IP — a real cost decision, recorded rather than
  assumed away.
- ⏳ Still owed on the browser half: drop the pseudo-referrer entries and cut `apiTargets`
  from 49 to what the frontend actually needs.
- ✅ `whatsapp-templates/handler.py` now reads the canonical `wecare/google/cloud` rather
  than `wecare/google-maps`, and calls Places API (New) rather than the legacy
  `maps/api/place/*` endpoints. It still resolves the **browser** key until the server key is
  provisioned, so the path remains refused until then — but by the credential, not by the
  endpoint or the transport. Latent rather than harmful: zero invocations of
  `places-autocomplete` or `place-details` in the retained log window.
- Both keys are registered in `scripts/check_secrets_live.py`, so a browser key pointed at a
  server path says so on the next run instead of failing silently.
- Quota alerting, so a leaked key shows up as spend before it shows up as a bill.

## T10 — Abuse of the public verification endpoints

**Threat.** Someone drives WhatsApp and SES spend, or uses the endpoints as a messaging relay.

**Controls.**

- Per-IP, per-phone and per-email rate limits, failing closed.
- Per-IP limiting at the gateway or handler, **not** in the Cognito trigger — a trigger
  receives no source IP, which is exactly why the existing probe counter is per-number.
- **Not a WebACL on the API — that is not available.** An earlier draft of this document, and
  the brief itself, called for WAF in front of the API. It cannot be done as stated:
  **WAFv2 does not support API Gateway HTTP APIs.** Measured directly rather than inferred —
  `GetWebACLForResource` on `arn:aws:apigateway:us-east-1::/apis/zllr9lrg7j/stages/prod`
  returns `WAFInvalidParameterException: The ARN isn't valid`, and
  `ListResourcesForWebACL` returned the two Cognito pools and nothing else. Only REST APIs,
  ALB, CloudFront, AppSync, Cognito, App Runner and Verified Access are supported targets.
  So this is a **service limit, not an omission**, and recording it as a `HIGH` gap to be
  closed by "attach a WebACL" would send the next person after something that cannot be built.
- **Since 2026-09-28 there is no WebACL anywhere**, not just on the API. Both ACLs were
  deleted by owner cost decision, so the per-IP rate-based rule that used to sit in front of
  both Cognito pools is gone. Every "per-IP" control named below is now handler-side only.
  That makes the handler limits load-bearing in a stronger sense than when this section was
  written: there is no longer an edge control to fall back on.
- The replacement control set, which does exist:
  - **API Gateway throttling** at the stage and per route. The `prod` stage is currently
    100 rps / 200 burst *for everything*; the verification routes need their own, much lower,
    per-route limits so an OTP flood cannot consume the shared budget.
  - **Handler-level limits** on the existing `RateLimitTable`, which is where the per-phone,
    per-email and per-IP budgets actually live. This is the load-bearing control now, not a
    supplement to WAF.
  - **Reserved concurrency** on the OTP function, so a burst cannot consume account capacity.
  - **CloudFront in front of the API** would be the only way to obtain real WAF coverage for
    the API, since a distribution *can* carry a WebACL. `api.wecare.digital` is not behind
    CloudFront. Recorded as a decision to take rather than a task to tick — and note it is
    now moot while the owner's standing decision is that WAF costs more than it is worth
    here, since there would be no ACL to attach.
- Bot protection where justified. CAPTCHA is not the only protection, and invasive
  fingerprinting is not introduced without a security review.
- SES suppression consumed from bounce and complaint events, so a bouncing address is not
  retried into a reputation penalty under `p=reject`.
- Reserved concurrency on the OTP function, so a burst cannot consume the account's Lambda
  capacity. The `/plivo/answer` finding in `docs/WEBHOOK-INVENTORY.md` is the cautionary
  precedent: an unauthenticated endpoint that could send SMS, with no reserved concurrency,
  at a 100 rps stage throttle.

## T11 — XSS, and the allowlist failure mode that is worse

**Threat.** Script injection through product copy, blog content, an address line, or a
customer name.

**Controls.** React escapes by default; no `dangerouslySetInnerHTML` on customer-supplied or
Wix-supplied content without sanitisation. Wix rich text is sanitised server-side in the
adapter, not in the component. A strict CSP where the static export allows it.

**The adjacent failure, which has actually happened here.** Public route registration is an
exact-match allowlist in `src/pages/_app.tsx`, and a public page missing from it renders an
empty body with **HTTP 200** — a 404 that does not look like one. Worse, a route that is both
in the allowlist *and* wraps itself in the authenticated `Layout` leaks the dashboard into
public HTML: `/contact-test/` once returned 200 carrying the entire staff sidebar, because a
prerendered export has no session so `Layout` rendered in full. `PublicRouteRegistration.test.ts`
now fails any public route importing `Layout`, and every new public route in this build is
added to both the allowlist and that test.

## T12 — PII in logs and reports

**Controls.** Phone numbers masked to the last four digits; email addresses never logged in
full; addresses not logged. Admin views show masked phone and masked email.

**The masking ambiguity, and why it is not fixed by widening.** The QA recipient
`+918100640044` and the secondary business number `+919903300044` both mask to `…0044`. A log
line reading `…0044` is ambiguous between the two. Disambiguate on `direction`, `channel` or
delivery id. **Do not widen the masking** — a full number in a log is a disclosure, and the
ambiguity is cheaper than that.

## T13 — SSRF

**Threat.** A supplied URL causes a Lambda to fetch an internal endpoint or the instance
metadata service.

**Controls.** No user-supplied URL is fetched server-side. Outbound hosts are a fixed
allowlist: `graph.facebook.com`, `www.wixapis.com`, `places.googleapis.com`,
`addressvalidation.googleapis.com`, and AWS endpoints. Webhook payload URLs are stored and
displayed, never fetched. Billing document assets are fetched only from our own S3 bucket.

## T14 — Supply chain

**Controls.** Dependabot is configured; CodeQL runs in CI. Dependencies are added at pinned
or exact versions, from actively maintained packages. `package.json` already carries
deliberate `overrides` for `lodash`, `fast-xml-parser`, `immutable`, `mysql2` and `csv-parse`.
A new dependency whose name is a near-miss of a popular package is treated as typosquatting
until proven otherwise.

Note for anyone running CI: `npm ci` **cannot** install this repo, because of a bundled
`@opentelemetry/core@2.0.0` conflict. `build-test.yml` uses `npm install --no-audit --no-fund`
for that reason. That is a documented constraint, not an oversight to fix casually.

## T15 — Excessive IAM

**Controls.** Per-function roles, least privilege. A bucket ARN is distinguished from
`bucket/*` — they authorise different operations and conflating them is the common error.
Secrets Manager read is granted per secret, not by wildcard. No `iam:*`, no `*:*`. The
reconciliation worker can write orders and payments and cannot delete tables.

## T16 — Test bypasses reaching production

**Threat.** A deterministic test OTP, or a live-send switch, active in production.

**Controls.**

- Any deterministic OTP is environment-gated, disabled in production, and unreachable from a
  public production endpoint. **Its absence in production is asserted by a test**, not
  inferred from configuration.
- Live sends go only to the owner-nominated QA recipient `+918100640044` until production
  sending is separately authorised.
- `WA_LIVE_SMOKE_TEST` is a **lockdown, not a permission**: enabling it narrows sending to
  that one number and halts customer messaging. That is the right direction for a safety
  switch, and it is why it must not be left on.
- `PSTN_BROWSER_ROUTING_ENABLED` and every other live-send flag stay off.

---

## Gaps this document does not close

Honest list. Each is tracked in [`docs/tasks.md`](tasks.md).

| Gap | Severity | Why it is still open |
|---|---|---|
| No WAF coverage anywhere | `MEDIUM`, and **deliberately not being closed** | Was "not closable as stated" because WAFv2 cannot attach to an HTTP API (measured, see T10). As of 2026-09-28 it is broader and intentional: both web ACLs were deleted by owner cost decision, so Cognito and the Amplify app lost coverage they had. Not a defect to fix — a documented trade. Restore with `python3 scripts/provision_waf.py --apply` if the decision reverses |
| No per-IP throttling on public customer OTP sign-in | `HIGH` | The `wecare-cognito-waf` rate-based rule (1000/5min per IP) was the only per-IP control and was deleted 2026-09-28. The per-phone probe counter in the trigger remains, but a trigger receives no source IP, so a distributed enumeration across many numbers is now unthrottled at the edge. Was already noted as CGNAT-weakened; it is now absent rather than weak |
| Admin MFA not enforced | `HIGH` | owner overrides make it a required target while removing its blocking semantics |
| Staff password minimum 8 | `MEDIUM` | weak for production access |
| Customer pool deletion protection `INACTIVE` | `MEDIUM` | one delete removes every customer login |
| Google server key | ✅ CLOSED | `wecare/google-maps-server` minted and proven live against Places (New) and Geocoding. The Places migration is no longer credential-blocked |
| Browser key still over-broad | `MEDIUM` | 49 `apiTargets` and two pseudo-referrer entries. No longer blocking anything, so downgraded from `HIGH`, but a browser key usable for 49 services is a wide blast radius if it leaks |
| Places proxy reads the browser key server-side | `MEDIUM` | `whatsapp-templates/handler.py` cannot work as written. Latent: zero invocations in the retained log window |
| ~~Wix credential absent~~ | ✅ CLOSED | Owner supplied it; stored 2026-09-26 via the staging-file path so the value never reached argv, staging file shredded, encrypted local and S3 recovery copies refreshed and verified |
| Legacy Places still in use | `HIGH` | deprecated, so this has an expiry rather than an indefinite pass |
| `get_secret_value` in the Places proxy | `LOW` | pre-existing; superseded by `AddressService` |
| `/plivo/answer` unauthenticated and can send SMS | `HIGH` | pre-existing, outside this build; ordering matters — add `?token=` at Plivo **first**, set the Lambda variable **second**, or every inbound WhatsApp call 403s in between |

Security Hub stays excluded per owner overrides. GuardDuty is optional and does not block
closure.

## Verification

Security claims are asserted by tests, not by this document. `VER-3.7` in
[`docs/spec.md`](spec.md) enumerates them: OTP brute force, rate limits, session fixation,
CSRF, XSS, IDOR, account enumeration, the duplicate-registration race, tracking-token
authorisation, and secret exposure in the built bundle.

A command exiting zero is not evidence that a control works. Each control above needs a test
that **fails when the control is removed**; a test that passes either way measures nothing.
