# Specification — customer identity, verification, address, account and public web

Spec-Driven Development artifact. This is the document the brief calls `spec.md`.

## Read these first, and in this order

| Document | What it holds | Do not duplicate it here |
|---|---|---|
| [`docs/current-environment.md`](current-environment.md) | Phase 0 read-only inventory: 65 Lambdas, 79 tables, 361 routes, live Meta/SES/Google state, 19 gaps | the inventory |
| [`docs/compatibility.md`](compatibility.md) | vendor capability and version matrix | the version matrix |
| [`docs/design.md`](design.md) | how these requirements and the native AWS commerce flow (catalog, cart, checkout, payment, billing) are built | the design |
| **this file** | **CI / OTP / ADR / SESS / ACC / PUB / VER**: customer identity, phone and email verification, address capture, sessions, account area, public web and page composition, version and test strategy | — |

Requirement state is tracked in [`docs/execution/requirement-registry.md`](execution/requirement-registry.md),
which remains the one place state changes.

## Scope

Let a person arrive at `wecare.digital` on a phone, register with a WhatsApp number and an
email address, prove control of both, give a real deliverable address, and end up with
exactly one account — then browse the native catalog, buy, pay inside WhatsApp, and track the
order from either the website or the chat thread. Staff see every one of those steps.

## Non-goals

- A second frontend framework. Next.js 16 static export is the storefront and the admin
  shell. The brief names Astro; adding it would split a 127-page build for no gain.
- A utility-CSS retrofit. Tailwind is **not installed** (verified). Mobile-first work is
  CSS in the existing hand-written token system.
- Replacing the invoice engine. 16 routes, 5 tables, a per-FY statutory sequence and
  GSTIN/HSN fields.
- Rebuilding the WhatsApp OTP transport. Cognito `CUSTOM_AUTH` against
  `us-east-1_46ULYuukt` already works against a live APPROVED template.
- Rotating, reading or revoking any provider credential. `MANUAL_OWNER_ACTION`.
- Any WhatsApp number, WABA, phone-number-id or business-portfolio mutation. Prohibited.
- Enabling any live-send flag. Prohibited.
- Native packaging. Post-project per owner overrides.

## Baseline corrections carried forward

Verified, not assumed. Four of the brief's stated baselines did not survive Phase 0.

| Brief says | Verified position |
|---|---|
| `META_GRAPH_API_VERSION=v26.0` | **`v25.0`**. v26.0 blocked commerce calls when last attempted; the upgrade is gated on a contract test, not a date. Now enforced from `packages/config/vendorVersions.ts`. |
| Astro | **Next.js 16.2.9**, Pages Router, `output: 'export'` |
| Google Places assists address capture | The key **cannot call** Places API (New): `places.googleapis.com` is enabled on the project but absent from the unified key's `apiTargets`, and the code calls the **deprecated** legacy web service |
| `one@wecare.digital` "must be verified before production use" | **Already verified**: SES `EMAIL_ADDRESS` identity, sending enabled, domain DKIM `SUCCESS`, production access, 50k/day, not suppressed |

---

# CI — Canonical customer identity

Today there is no customer entity. `ContactsTable` (PK `id`, alias `contactId`, 3 GSIs) is
the de-facto record, and the Cognito customer username (`+E164`) is the other half. Nothing
links them, and `UNIQUE#`/`CUSTOMER#`/ULID/`TransactWriteItems` return **zero matches**
repo-wide.

## CI-1 — One immutable customer id

**Story.** As the business, I need one identifier per customer that never changes, so that
a phone or email change does not orphan their orders.

1. The system SHALL issue an immutable `customerId` of the form `CUS_<ULID>`.
2. `customerId` SHALL NOT be derived from phone, email or name.
3. Phone and email SHALL be **attributes** of the customer, never the primary identity.
4. WHEN a customer changes phone or email THEN `customerId` SHALL be unchanged and all
   orders SHALL remain resolvable.
5. The new entity SHALL be linked to the existing `ContactsTable` row and to the Cognito
   username, and that mapping SHALL be recorded, not inferred at read time.
6. Reads SHALL go through a resolver in the shape of `lambda_utils/contact_key.py` so no new
   call site has to know which spelling is physical.

## CI-2 — Transactional uniqueness on phone and email

**Story.** As the business, I need it to be impossible for two accounts to exist for one
WhatsApp number, even under concurrent submission.

1. Normalised phone SHALL be unique. Normalised email SHALL be unique.
2. Uniqueness SHALL be enforced by `TransactWriteItems` writing the profile item **and**
   `UNIQUE#PHONE#<normalisedPhone>` / `UNIQUE#EMAIL#<sha256(normalisedEmail)>` markers,
   each with `ConditionExpression: attribute_not_exists(PK)`.
3. The system SHALL NOT use read-then-write as the uniqueness mechanism.
4. WHEN the transaction is cancelled THEN no partial customer SHALL remain.
5. WHEN two registrations for the same number are submitted concurrently THEN exactly one
   SHALL succeed and the other SHALL receive the existing-account path, not an error that
   discloses existence.
6. The email marker SHALL store a **hash**, not the address, so the key space does not
   become a harvestable address list.

`AgentApprovalsTable` is the working precedent in this repo for a conditional single-use
write (`attribute_not_exists(consumedAt) AND expiresAt > :now`). Follow it.

## CI-3 — Normalisation is the uniqueness boundary

1. Phone SHALL be normalised to E.164 before any uniqueness check. `+91 93309 94400`,
   `09330994400`, `9330994400` and `919330994400` SHALL resolve to one identity.
2. Email SHALL be lowercased and trimmed. The local part SHALL NOT otherwise be rewritten —
   stripping dots or `+tags` would merge addresses that are genuinely distinct at some
   providers.
3. The TypeScript and Python normalisers SHALL remain byte-identical in behaviour and SHALL
   be covered by a shared fixture table. If they diverge, a customer signs in successfully
   and owns nothing.

## CI-4 — Registration state machine

1. State SHALL be explicit: `STARTED → PHONE_OTP_PENDING → PHONE_VERIFIED →
   EMAIL_OTP_PENDING → EMAIL_VERIFIED → PROFILE_PENDING → ADDRESS_PENDING → ACTIVE`.
2. The account SHALL NOT reach `ACTIVE` until **both** `phoneVerifiedAt` and
   `emailVerifiedAt` are set.
3. UX MAY reorder or combine steps; the backend states SHALL remain explicit and SHALL be
   advanced by conditional write.
4. An illegal transition SHALL fail safely without corrupting state.
5. A partially registered customer SHALL be resumable and SHALL expire without becoming a
   ghost account.

## CI-5 — Duplicate and conflicting identity

1. WHEN a verified phone already belongs to an account THEN the system SHALL NOT create a
   second account and SHALL move to sign-in.
2. WHEN a verified email already belongs to a **different** account THEN identities SHALL
   NOT be silently merged; the case SHALL require explicit resolution and SHALL raise an
   audit event.
3. Every successful customer SHALL resolve to exactly one `customerId`.

## CI-6 — Profile

1. Stored: `customerId`, `fullName`, `normalizedPhone`, `phoneVerifiedAt`, `email`,
   `normalizedEmail`, `emailVerifiedAt`, `defaultAddressId`, `createdAt`, `updatedAt`,
   `status`.
2. Optional: `preferredName`, `marketingConsent`, `preferredLanguage`, `timezone`.
3. `marketingConsent` SHALL default to **false**. No consent field SHALL default to granted.
4. Per-field provenance SHALL follow the existing trust model in
   `lambda_utils/identity/provenance.py`, where `phone` is a locked field once `VERIFIED`.

## CI-7 — Audit events

1. Append-only, never mutated or deleted:
   `CUSTOMER_REGISTRATION_STARTED`, `PHONE_VERIFIED`, `EMAIL_VERIFIED`,
   `CUSTOMER_ACTIVATED`, `FULL_NAME_UPDATED`, `ADDRESS_ADDED`, `ADDRESS_UPDATED`,
   `ADDRESS_REMOVED`, `DEFAULT_ADDRESS_CHANGED`, `PHONE_CHANGE_REQUESTED`, `PHONE_CHANGED`,
   `EMAIL_CHANGE_REQUESTED`, `EMAIL_CHANGED`, `SESSION_CREATED`, `SESSION_REVOKED`.
2. Each event SHALL carry timestamp, actor, source and correlation id.
3. No event SHALL contain an OTP, a token, or a full phone number or email address.

---

# OTP — Phone and email verification

The single OTP implementation today lives in
`amplify/functions/auth/customer-whatsapp-auth/handler.py`. It generates a 6-digit CSPRNG
code, holds it in Cognito's `privateChallengeParameters`, compares with
`secrets.compare_digest`, expires at 600s and allows 3 attempts. It has **no persistence,
no hashing, no resend counter and no send-side rate limit**. Its only limiter counts
unregistered-number probes and **fails open by design**.

## OTP-1 — Challenges are stored hashed, with a TTL

1. A plaintext OTP SHALL NEVER be written to a database, a log, a metric, a report or a
   response body.
2. The stored value SHALL be an HMAC of the code under a server-side pepper from Secrets
   Manager, resolved lazily at request time and never at import scope.
3. Entities:
   `PK=OTP#PHONE#<normalisedPhone>` / `PK=OTP#EMAIL#<sha256(normalisedEmail)>`,
   `SK=CHALLENGE#<challengeId>`.
4. Fields: `otpHash`, `createdAt`, `expiresAt`, `attemptCount`, `maxAttempts`,
   `resendCount`, `usedAt`, `status`, `correlationId`.
5. DynamoDB TTL SHALL reap expired challenges; expiry SHALL NOT rely on the reaper for
   correctness — verification SHALL check `expiresAt` itself.
6. The code SHALL be ≥6 digits, generated with a CSPRNG. `random` SHALL NOT be used.

## OTP-2 — One-time use and constant-time comparison

1. A challenge SHALL be consumable exactly once, enforced by a conditional write on
   `attribute_not_exists(usedAt)`.
2. Comparison SHALL be constant-time.
3. WHEN a new challenge is issued for the same subject THEN prior open challenges SHALL be
   invalidated.
4. A correct code for an already-consumed challenge SHALL fail.

## OTP-3 — Attempt, resend and rate limits

1. Enforced: max attempts per challenge, max resends per window, resend cooldown, per-phone
   rate limit, per-email rate limit, per-IP rate limit.
2. Counters SHALL be incremented atomically (`ADD`), not read-modify-written.
3. Limits SHALL **fail closed**. This is a deliberate reversal of the existing probe
   counter, which fails open — that choice is defensible for a reveal flag whose worst case
   is a usability dead end, and is not defensible for a limiter guarding OTP sends, whose
   worst case is unbounded messaging cost and a brute-force window.
4. Per-IP limiting SHALL be applied at the API Gateway boundary or in the handler, because a
   Cognito trigger receives no source IP and therefore cannot do it.
5. `RateLimitTable` already exists and SHALL be reused rather than duplicated.

## OTP-4 — Failure taxonomy without enumeration

1. Handled distinctly internally: `INVALID_OTP`, `EXPIRED_OTP`, `TOO_MANY_ATTEMPTS`,
   `TOO_MANY_RESENDS`, `RATE_LIMITED`, `WHATSAPP_DELIVERY_FAILED`,
   `NUMBER_NOT_WHATSAPP_ENABLED`, `TEMPLATE_REJECTED`, `META_API_FAILURE`.
2. Public responses SHALL NOT reveal whether a phone or email belongs to an existing
   account.
3. **This changes existing behaviour and the change is intentional.** The current trigger
   returns `registered: "false"` to avoid stranding a mistyped number on a code screen that
   no code will satisfy. That trade is defensible where every recipient is registered by
   hand by an operator. It is **not** defensible on a public self-registration endpoint,
   where it becomes a customer-list oracle. The registration surface SHALL therefore not
   expose the flag, and SHALL solve the dead end instead by telling the user plainly that a
   code was sent *if the number can receive one* and offering resend plus a correction path.
4. Timing and response shape SHALL not differ measurably between existing and unknown
   subjects on the registration surface.

## OTP-5 — WhatsApp delivery

1. Phone OTP SHALL be delivered only through WABA `2094615664435155`, phone-number-id
   `1016149501586345` = **`+91 93309 94400`**, using the APPROVED `AUTHENTICATION` template
   `wecare_otp`/`en` (verified live 2026-09-26).
2. The code SHALL be passed as the `url` button parameter. `copy_code` SHALL NOT be used —
   Meta rejects it with `(#132018) buttons: Button at index 0 must be of type Url`.
3. The WABA isolation gate SHALL be retained: a customer whose `custom:partner_waba_id`
   does not match SHALL be refused before any send.
4. Production OTP SHALL NOT be sent from any other number without an explicit authorised
   configuration change.
5. Template name, language and Graph version SHALL be read from
   `packages/config/vendorVersions.ts` / `config/vendor-versions.json`, not hard-coded.

## OTP-6 — Email delivery

1. Email OTP SHALL be sent from `one@wecare.digital`, which is already a verified SES
   identity. The From address SHALL NOT be spoofed.
2. Sends SHALL use **SESv2** with `ConfigurationSetName: wecare-digital`. The identity
   itself has no default configuration set, so it must be passed per send or reputation
   tracking and suppression are silently skipped.
3. `wecare-outbound-email` SHALL NOT be reused as-is: it is SES v1, has no configuration
   set, and sends `From: noreply@wecare.digital`.
4. The domain runs `DMARC p=reject; sp=reject` with MTA-STS `enforce`. Any new sender SHALL
   have DKIM live **before** its first send, because an unaligned message hard-bounces
   rather than landing in spam.
5. Content SHALL state the brand, the code, that it expires shortly, and what to do if it
   was not requested. It SHALL NOT contain a password, payment data, an internal id, an API
   key, or a tracking pixel.
6. Bounce and complaint events SHALL be consumed; a hard-bouncing address SHALL NOT be
   retried into a suppression penalty.

## OTP-7 — Observability without disclosure

1. Recorded: `PHONE_OTP_REQUESTED`, `PHONE_OTP_DELIVERED`, `PHONE_OTP_FAILED`,
   `PHONE_OTP_VERIFIED`, `EMAIL_OTP_REQUESTED`, `EMAIL_OTP_DELIVERED`, `EMAIL_OTP_FAILED`,
   `EMAIL_OTP_VERIFIED`, `OTP_EXPIRED`, `OTP_RATE_LIMITED`, `OTP_MAX_ATTEMPTS`.
2. Never logged: the OTP, the pepper, the Meta token, SES credentials, a full phone number,
   a full email address.
3. A secret SHALL NOT appear in a logging **expression** at all — including a ternary on its
   truthiness or a boolean derived from it. CodeQL tracks taint across function boundaries
   and has failed this build twice on exactly that pattern; reducing a secret to a bool does
   not launder it. Remove the log or derive the value from something that never touched the
   secret. Do not suppress the alert.
4. Phone masking SHALL keep the last four digits, and the known ambiguity SHALL be respected:
   the QA recipient `+918100640044` and the secondary business number `+919903300044` both
   mask to `…0044`. Disambiguate on direction, channel or delivery id. Masking SHALL NOT be
   widened to resolve it.

---

# ADR — Address capture

No address entity exists. Addresses are flat strings on Contact and Order. The only Places
integration is a proxy inside `whatsapp-templates/handler.py` that exists to fill WhatsApp
location-template parameters, returns `{description, placeId}` and
`{latitude, longitude, name, address}`, and calls the **deprecated** legacy web service.

## ADR-1 — Structured, not free-form

1. Persisted per address: `addressId`, `label`, `fullAddress`, `addressLine1`,
   `addressLine2`, `locality`, `city`, `state`, `postalCode`, `country`, `countryCode`,
   `latitude`, `longitude`, `googlePlaceId`, `verified`.
2. A single free-form string SHALL NOT be the only representation.
3. `PK=CUSTOMER#<customerId>`, `SK=ADDRESS#<addressId>`.

## ADR-2 — Autocomplete on the new API

1. Autocomplete SHALL be offered as the customer types, minimum 3 characters.
2. It SHALL use **Places API (New)**. The legacy endpoints are deprecated.
3. Session tokens SHALL bundle keystrokes plus the final details call into one billable
   session.
4. **Prerequisite, and it is a hard one:** `places.googleapis.com` must be added to the
   unified key's `apiTargets`, or every New-API call fails on key restriction. Enabling the
   service on the project — already done — is not sufficient.
5. Autocomplete SHALL degrade to manual entry, not block registration, when Places is
   unavailable. An address the customer cannot type is a lost customer.

## ADR-3 — The customer confirms

1. After selection the normalised address SHALL be shown back for explicit confirmation
   before being stored as the default delivery address.
2. Delivery detail — flat/unit, building, floor, landmark, instructions — SHALL be capturable
   **without** altering the canonical Google place reference.
3. `verified` SHALL mean the address was confirmed by the customer, and SHALL be recorded
   separately from any provider-side validation verdict.
4. Where Address Validation is used (enabled on the project and on the key), its verdict
   SHALL inform but SHALL NOT override the customer's confirmation.

## ADR-4 — Key separation

1. Browser and backend SHALL use **separate** keys. One key across both cannot satisfy both
   restriction models, which is the current state.
2. The browser key SHALL carry HTTP-referrer restrictions limited to WECARE.DIGITAL domains
   and the minimum Maps APIs.
3. The backend key SHALL carry server-side restrictions and least privilege.
4. The current unified key spans ~50 APIs and lists `places.googleapis.com` and
   `*.googleapis.com/*` as **referrers**, which no browser sends — a restriction that does
   not restrict. It SHALL be replaced, not extended.
5. No Google credential SHALL be committed or shipped to the browser as a secret.
6. Backend key resolution SHALL be by reference. The existing `_get_gmaps_key()` calls
   `get_secret_value` directly and logs `str(e)`; both conflict with steering and SHALL NOT
   be copied into new code.

---

# SESS — Sessions

Customer sessions today are a 60-minute Cognito access token in `sessionStorage`, validated
server-side by `get_user` followed by an issuer-pin check. There is no cookie, no CSRF
token, no session table, no rotation and no revocation.

## SESS-1 — Passwordless sign-in

1. Primary sign-in SHALL be WhatsApp number → OTP → verified session, reusing the live
   `CUSTOM_AUTH` flow.
2. Verified email OTP MAY serve as a recovery or secondary route.
3. Passwords SHALL NOT be introduced.

## SESS-2 — Session security under a static export

1. Sessions SHALL expire, SHALL be revocable, SHALL rotate on privilege change, and logout
   SHALL invalidate server-side.
2. A session registry SHALL exist at `PK=CUSTOMER#<customerId>`, `SK=SESSION#<sessionId>`
   so that revocation is real rather than client-side forgetting.
3. Sensitive mutations SHALL carry CSRF protection.
4. **The constraint that shapes this:** `output: 'export'` means there is no server and no
   middleware, so a `Set-Cookie`-based session cannot be issued or read by the frontend.
   Either sessions move behind a Lambda that sets an `HttpOnly; Secure; SameSite` cookie on
   an API-Gateway-backed domain, or the bearer-token model is retained.
5. WHERE a bearer token in browser storage is retained THEN that SHALL be a recorded
   architecture decision in `docs/design.md` with its rationale and its blast radius — not
   an unexamined default. The brief permits this only as a documented decision.
6. `sessionStorage` SHALL be preferred over `localStorage` if the bearer model is kept, so a
   shared browser does not retain a usable session after the tab closes.

## SESS-3 — Recovery and identity change

1. Supported: lost session, changed device, email recovery, WhatsApp re-authentication,
   email change, phone change, address change.
2. Changing phone SHALL require OTP verification of the **new** number.
3. Changing email SHALL require OTP verification of the **new** address.
4. A phone or email change SHALL move the corresponding `UNIQUE#` marker transactionally, so
   the old value is released and the new one claimed atomically. A change that leaves both
   markers, or neither, is a corruption.
5. Every sensitive identity change SHALL emit an audit event and notify the customer on the
   channel **not** being changed.

---

# ACC — Customer account area

None of `/account*` exists.

## ACC-1 — Routes and capability

1. Routes: `/account`, `/account/profile`, `/account/addresses`, `/account/orders`,
   `/account/orders/[orderNumber]`, `/account/billing`, `/account/security`.
2. The customer SHALL be able to view and update their full name; add, edit, remove and
   default their addresses; list and track orders; view and download receipts and invoices;
   see which of phone and email are verified; and manage active sessions where implemented.
3. An authenticated customer SHALL reach their own order at
   `/account/orders/[orderNumber]`, independently of any tracking token.
4. A customer SHALL NOT be able to read another customer's order, address, invoice or
   session by changing an identifier in a URL. Every read SHALL be authorised against the
   session's `customerId`, not against the identifier supplied.
5. Refusals SHALL be indistinguishable between "not yours" and "does not exist", following
   the existing `_not_registered` precedent in `secure-files/handler.py`, which returns one
   byte-identical 403 for both so file ids cannot be probed.
6. Dynamic account routes SHALL fetch client-side against API Gateway. `getStaticPaths`
   cannot enumerate per-customer paths, and `fallback: false` is mandatory under
   `output: 'export'`.

---

# PUB — Public web, content and composition

3 of the brief's 23 public routes exist (`/`, `/blog`, `/contact`), 1 exists at a different
path (`/post/[slug]`), 19 do not. There is no page-composition system.

## PUB-1 — AWS is canonical

1. `ProductsTable` SHALL be the source of truth for products and variants (prices as integer
   `priceMinor` paise); `SeoToolsTable` SHALL be the source of truth for blog posts,
   categories and tags.
2. AWS SHALL own customer identity, OTP challenges, WhatsApp orchestration, payment
   reconciliation, page composition, tracking authorisation, audit events and operational
   state.
3. Page composition SHALL store **references** to products and posts, never copies. A cached
   copy is a cache and SHALL be labelled and invalidated as one.

## PUB-2 — Read boundaries

1. The storefront SHALL read products from `src/content/catalog-snapshot.json`, generated
   from `ProductsTable` by `scripts/build-catalog-snapshot.py`; staff edits SHALL go through
   `wecare-native-catalog-admin` (`/native-catalog/products`).
2. Public blog reads SHALL go through `wecare-seo-tools` at `/seo-tools/blog-public` and
   `/seo-tools/blog-public/{slug}` (`src/lib/public-blog.ts`).
3. No page component SHALL hold a credential or call a datastore directly.
4. Prices SHALL be computed server-side only, by `catalog_pricing` and
   `checkout_pricing.compute_quote`; a client-supplied price SHALL be ignored.
5. Only published, public blog posts SHALL appear publicly.

## PUB-3 — Dynamic page composition

1. Products and posts SHALL be placeable on any public page without code changes.
2. Entities: `PK=PAGE#<slug>` `SK=METADATA`, and
   `PK=PAGE#<slug>` `SK=SECTION#<sequence>#<sectionId>`.
3. Section types: `HERO`, `RICH_TEXT`, `PRODUCT_GRID`, `PRODUCT_CAROUSEL`,
   `PRODUCT_FEATURE`, `PRODUCT_CATEGORY`, `BLOG_GRID`, `BLOG_CAROUSEL`, `BLOG_FEATURE`,
   `BLOG_CATEGORY`, `BLOG_TAG`, `CTA`, `FAQ`, `TESTIMONIALS`, `CUSTOM`.
4. An unknown section type SHALL render nothing and SHALL NOT break the page.
5. A section referencing a deleted product or post SHALL degrade gracefully, not 500.

## PUB-4 — Routes

1. New: `/register`, `/verify/phone`, `/verify/email`, `/profile/setup`, `/address/setup`,
   `/account*`, `/shop`, `/shop/[category]`, `/product/[slug]`, `/blog/category/[slug]`,
   `/blog/tag/[slug]`, `/cart`, `/checkout`, `/orders/[orderNumber]`,
   `[retired public path 282d0fd5]/[trackingToken]`, `/billing/[trackingToken]`.
2. **Every new public route SHALL be added to the allowlist in `src/pages/_app.tsx`.** A
   public page absent from it renders an empty body with HTTP 200 — a 404 that does not look
   like one. `src/test/PublicRouteRegistration.test.ts` SHALL be extended to cover each.
3. No public route SHALL import the authenticated `Layout`. That combination previously
   served the entire staff sidebar publicly at HTTP 200; the existing test SHALL keep
   failing it.
4. `/blog/[slug]` SHALL be reconciled with the live `/post/[slug]`. Whichever becomes
   canonical, the other SHALL 301 via an Amplify custom rule — redirects live there, not in
   `next.config.js`, because a static export emits no server redirects.
5. Token-bearing routes (`[retired public path 282d0fd5]/*`, `/billing/*`) SHALL be `noindex` and SHALL NOT appear in
   the sitemap.

## PUB-5 — Mobile-first, responsive

1. Layout SHALL be authored mobile-first. The current CSS is **desktop-first**: `max-width`
   queries dominate and `src/styles/tokens.css` defines no breakpoints.
2. A breakpoint scale SHALL be added to `tokens.css` and SHALL be the only source of
   breakpoints.
3. Verified at 320, 360, 375, 390, 412, 768, 1024, 1280 and 1440 px, and SHALL adapt
   fluidly between them rather than snapping at those widths.
4. No horizontal overflow at any tested width.
5. Touch-friendly targets, readable type, responsive images, responsive product grids and
   blog cards, mobile navigation, accessible forms, and mobile-workable cart, checkout, OTP
   entry, address autocomplete, tracking and account dashboard.
6. OTP entry SHALL offer a numeric keyboard, accept paste of the whole code, auto-advance
   without trapping focus, handle backspace across boxes, and expose a single labelled field
   to assistive technology.
7. The existing foldable query (`vertical-viewport-segments: 2`) SHALL be preserved.

## PUB-6 — Accessibility

1. Target WCAG 2.2 AA practice: semantic HTML, keyboard operability, visible focus, labelled
   fields, accessible OTP entry, ARIA only where necessary, sufficient contrast, meaningful
   alt text, reduced-motion support, programmatically associated validation messages.
2. Verification state SHALL NOT be conveyed by colour alone.
3. Automated checks SHALL run in CI, and the report SHALL state plainly that full WCAG
   conformance needs manual assistive-technology testing and expert review, which automated
   tooling cannot establish.

## PUB-7 — Performance

1. Optimise Core Web Vitals, image and font loading, JS payload, caching, lazy loading and
   route-level code splitting.
2. No admin or backend SDK SHALL be shipped to the public browser. `aws-amplify` and the
   Amplify Authenticator SHALL NOT load on public routes.
3. Public pages SHALL remain functional with JavaScript degraded where the content is static.

## PUB-8 — Browsers and devices

1. Chrome, Safari, Firefox and Edge, including Android Chrome, iPhone Safari and iPad Safari.
2. Critical flows SHALL pass automated Chromium, WebKit and Firefox runs.
3. The experience SHALL remain WebView/WKWebView-ready for the existing Capacitor 8 wrapper.

---

# VER — Versions and verification

## VER-1 — One version source

1. Vendor and runtime versions SHALL come from `packages/config/vendorVersions.ts`, mirrored
   to `config/vendor-versions.json` for the Python fleet. **Implemented.**
2. No request URL SHALL contain a hard-coded version literal. Three such literals exist
   today, including the payment-lookup call in `inbound-whatsapp-handler`, and a grep for
   the constant name does not find them.
3. A malformed Graph version SHALL fail validation rather than produce a Meta 404 that looks
   like a missing resource. **Implemented** as `graphApiVersion()`.
4. Preview and deprecated production runtimes SHALL be rejected. **Implemented** as
   `REJECTED_RUNTIMES`.
5. `node scripts/check-versions.ts` SHALL fail on any error finding, and a lag SHALL be
   allowed only with a written reason. **Implemented.**
6. Configured-vs-latest SHALL be visible on an authenticated admin surface.

## VER-2 — Test environments

1. `UNIT`, `INTEGRATION`, `SANDBOX/STAGING` and `PRODUCTION` SHALL be separated.
2. A production customer SHALL NEVER be routed through a test OTP bypass.
3. Any deterministic test OTP SHALL be environment-gated, disabled in production, and
   unreachable from a public production endpoint. Its absence in production SHALL be
   asserted by a test, not assumed from configuration.
4. Live sends SHALL go only to the owner-nominated QA recipient `+918100640044` until
   production sending is separately authorised. `WA_LIVE_SMOKE_TEST` is a **lockdown, not a
   permission**: enabling it narrows sending to that number and halts customer messaging, so
   it SHALL NOT be left on.

## VER-3 — Test coverage

1. **Phone OTP:** valid, wrong, expired, already-used, resend, resend cooldown, max attempts,
   max resends, concurrent requests, Meta delivery failure, duplicate verification callback,
   formatting variants, E.164 normalisation, existing customer, new customer.
2. **Email OTP:** valid, invalid, expired, already-used, resend, rate limit, normalisation,
   existing email, delivery failure, duplicate verification, sender identity, SPF/DKIM
   configuration, production sender `one@wecare.digital`.
3. **Duplicate customer:** parallel registrations with the same phone and the same email
   SHALL yield exactly one canonical identity, asserted against a real conditional-write
   path rather than a mock that cannot fail.
4. **Registration E2E:** homepage → register → phone OTP → verify → name → email → email OTP
   → verify → Places search → select → unit/landmark → confirm → account created → sign in →
   account → browse → add to cart → checkout.
5. **Responsive E2E:** homepage, registration, both OTP screens, address autocomplete,
   account, shop, product detail, blog, cart, checkout and tracking, at mobile, tablet and
   desktop widths.
6. **Cross-browser:** Chromium, WebKit and Firefox over registration, OTP entry, Places,
   cart, checkout and tracking.
7. **Security:** OTP brute force, rate limits, session fixation, CSRF, XSS, IDOR,
   account enumeration, duplicate-registration race, tracking-token authorisation, and
   secret exposure in the built bundle.
8. `@playwright/test` is **not installed**; the E2E work introduces it. `tools/browser/`
   vendors `playwright-core` as a measurement harness and is deliberately outside the app
   package — it SHALL NOT be repurposed as the test runner.
9. A command exiting zero SHALL NOT be reported as verification of intended behaviour.

## VER-4 — Deployment gates

1. Lint, typecheck and tests SHALL pass before any deployment.
2. Deployment SHALL be `update-function-code` → publish version → move the `live` alias. A
   `$LATEST` update alone SHALL NOT be treated as deployed for any function carrying a
   `live` alias.
3. A function's secrets SHALL be fetched lazily, so a rotation takes effect when a sandbox
   recycles rather than being frozen into a warm environment.

---

## Traceability to the brief's 56 acceptance criteria

| Brief §66 | Requirement |
|---|---|
| 1, 2 | PUB-4, CI-4 |
| 3 | CI-3 |
| 4, 5 | OTP-5, OTP-2 |
| 6, 7 | CI-6 |
| 8, 9 | OTP-6, OTP-2 |
| 10 | CI-4 |
| 11, 12, 13 | CI-2 |
| 14, 15, 16, 17 | OTP-1, OTP-2, OTP-3, OTP-7 |
| 18, 19, 20 | ADR-1, ADR-2, ADR-3 |
| 21 | ADR-4 |
| 22 | SESS-1 |
| 23, 24, 25, 26 | ACC-1 |
| 27, 28 | PUB-2 |
| 29, 30 | PUB-3, PUB-1 |
| 31, 32, 33 | `docs/design.md` §8 checkout, §9 payment reconciliation |
| 34 | `docs/design.md` ADR-7 inventory |
| 35 | `docs/design.md` ADR-8, §11 billing |
| 36 | `docs/design.md` §12 fulfillment (not built) |
| 37–44 | PUB-5 |
| 45, 46 | PUB-8 |
| 47 | PUB-6 |
| 48 | PUB-7 |
| 49 | `docs/current-environment.md` |
| 50, 51 | VER-1 |
| 52, 53, 54, 55 | VER-3 |
| 56 | VER-4 |

Criteria **19 and 21** cannot be satisfied until `places.googleapis.com` is added to the
Google key and the key is split. Criterion **4** is
satisfied at the provider today and verified live. Criterion **8**'s sender is verified
today; only the application path is missing.
