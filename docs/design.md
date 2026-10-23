# Design

How the requirements in [`docs/spec.md`](spec.md) (CI / OTP / ADR / SESS / ACC / PUB / VER)
and the native AWS commerce flow (catalog, cart, checkout, payment, billing) are actually
built, against the environment measured in [`docs/current-environment.md`](current-environment.md).

## The four constraints that shape everything below

Every design choice in this document traces back to one of these. They were measured, not
assumed, and none of them is negotiable without a separate decision.

1. **`output: 'export'` means there is no server.** No middleware, no route handlers, no
   `Set-Cookie` from the frontend, no server-side redirect. Anything requiring a secret or a
   trust decision happens in a Lambda. This is why a `middleware.js` visitor-session
   pattern cannot be used, and why a tracking token can never be validated in the browser.
2. **56 of 65 Lambdas sit behind a `live` alias.** `$LATEST` is not production. Deployment is
   `update-function-code` → publish → move the alias, or the API keeps serving old code.
3. **361 routes, 0 authorizers, every route `AuthorizationType=NONE`.** Authorisation is
   in-handler via `require_auth`. A route's `NONE` says nothing about whether it is protected,
   and it must be asserted per handler.
4. **The working tree is shared by several live sessions.** Ownership is by path; commits name
   paths explicitly.

## Architecture decision records

Numbered because later work will want to know why, and "it seemed obvious" is not a reason.

### ADR-1 — Next.js 16 stays; Astro is not adopted

The brief names Astro. This repo has 127 pages, a hardened public-route allowlist, an SEO and
JSON-LD convention, and a Capacitor 8 wrapper pointed at `out/`. A second framework would
split the build and duplicate the allowlist — the one file whose omission renders a public
page as an empty HTTP 200. **Cost accepted:** no server-rendered routes, so every dynamic
page is `getStaticPaths` or client-fetched.

### ADR-2 — The Contact is extended, not replaced

`ContactsTable` holds the live customer rows, keyed on `id` with `contactId` as an enforced
alias (`lambda_utils/contact_key.py`, 20 call sites, 3 GSIs). Repointing a live partition key
means recreating the table and its indexes to gain nothing.

So `customerId` is a **new** identity that links to the Contact rather than supplanting it:

```
CUSTOMER#<customerId>  PROFILE      contactId  -> the existing Contact row
                                    cognitoUsername -> "+<E164>" in us-east-1_46ULYuukt
```

**Cost accepted:** two identifiers for one human during the transition. Mitigated by a single
resolver, in the shape of `contact_key.py`, so no call site chooses.

### ADR-3 — OTP moves out of the Cognito session and into DynamoDB

Today the code lives only in Cognito's `privateChallengeParameters`: unhashed, with no
resend counter and no send-side limit. Cognito cannot provide what the spec needs — it has no
per-phone counter, and a Cognito trigger **receives no source IP**, so per-IP limiting is
impossible there.

The challenge therefore becomes a DynamoDB record with an HMAC, a TTL, and atomic counters.
Cognito remains the **session issuer**; it stops being the challenge store.

**Cost accepted:** one more round trip per verification, and the `CUSTOM_AUTH` trigger has to
consult the table rather than its own event. Worth it: it is the only way to get hashing,
resend limits and IP limits at all.

### ADR-4 — Limits fail closed here, unlike the existing probe counter

`_probe_budget_exhausted` fails **open** on any error, deliberately: it guards a
usability flag whose worst case is a customer stranded on a code screen. Locking someone out
of their own files because a counter could not be read is the greater harm there.

That reasoning does **not** transfer. A limiter guarding OTP *sends* protects against
unbounded messaging spend and a brute-force window. Those limiters fail **closed**. The
two behaviours are opposite on purpose and each is right for its own blast radius.

### ADR-5 — The registration surface does not expose `registered`

The existing trigger returns `registered: "false"` for an unknown number, with a long and
sound justification: every recipient is provisioned by hand, there is no self-signup, and
silence created a dead end where no code would ever arrive.

Public self-registration breaks that justification — the flag becomes a customer-list oracle.
So the registration endpoints omit it, and the dead end is solved differently: tell the user a
code is on its way if the number can receive one, offer resend, and offer a correction path.
The existing operator-provisioned `/get` flow keeps its current behaviour.

### ADR-6 — Bearer token retained for customer sessions, as a recorded decision

The spec requires `HttpOnly` cookies **or** a documented decision. Constraint 1 makes cookies
awkward: the frontend cannot set one, so it would have to be issued by a Lambda on a domain
that shares a cookie scope with the static site, and `api.wecare.digital` is a different host
from `wecare.digital`.

**Decision:** keep the bearer token, in `sessionStorage`, with a server-side session registry
so revocation is real.

**Blast radius, stated plainly:** the token is readable by script on the origin, so an XSS on
a public page can exfiltrate a customer session. Mitigations: `sessionStorage` dies with the
tab, the token is 60 minutes, `SESSION#` records make server-side revocation possible, and the
token grants only the customer's own data. **Revisit if** an API-Gateway custom domain under
`wecare.digital` is introduced, at which point the cookie becomes straightforward and should
be adopted.

### ADR-7 — Inventory is decremented exactly once, in one transaction

Stock must be decremented exactly once per order. **Decision:** `native_inventory_txn.reserve_basket`
writes the `CommerceKeys` claim and the `ProductsTable` stock decrement in a single
`TransactWriteItems`, keyed by payment attempt, so a retried checkout finds the existing
`RESERVED` claim and does not debit again. The reservation happens at checkout initiation,
before the Razorpay order is created.

### ADR-8 — Billing stays homegrown

A billing document must never become a second payable order. **Decision:** `wecare-invoice-engine` produces the
document (per-FY statutory sequence, GSTIN/HSN fields, 5 invoice tables) only for an order
that `OrderTable` already records as paid; it never creates anything payable.

### ADR-9 — Tracking tokens are hashed at rest

A token that can be read out of the database is a second credential store. **Decision:**
generate 256 bits from a CSPRNG, return it once in the URL, store only
`TRACKING#<sha256(token)>`. Lookup hashes the supplied token and does a point read. An
unknown token and an expired token produce a byte-identical response, following the
`_not_registered` precedent that returns one 403 for both wrong-owner and nonexistent-file so
ids cannot be probed.

---

## 1. Customer registration

```mermaid
stateDiagram-v2
    [*] --> STARTED
    STARTED --> PHONE_OTP_PENDING : phone submitted, normalised to E.164
    PHONE_OTP_PENDING --> PHONE_OTP_PENDING : resend within cooldown and budget
    PHONE_OTP_PENDING --> PHONE_VERIFIED : code correct, challenge consumed
    PHONE_OTP_PENDING --> ABANDONED : TTL elapsed
    PHONE_VERIFIED --> EXISTING_ACCOUNT : UNIQUE#PHONE marker already claimed
    PHONE_VERIFIED --> EMAIL_OTP_PENDING : email submitted
    EMAIL_OTP_PENDING --> EMAIL_VERIFIED : code correct, challenge consumed
    EMAIL_OTP_PENDING --> EMAIL_CONFLICT : UNIQUE#EMAIL claimed by another customer
    EMAIL_OTP_PENDING --> ABANDONED : TTL elapsed
    EMAIL_VERIFIED --> PROFILE_PENDING
    PROFILE_PENDING --> ADDRESS_PENDING : full name stored
    ADDRESS_PENDING --> ACTIVE : address confirmed, TransactWriteItems committed
    EXISTING_ACCOUNT --> [*] : hand off to sign-in
    EMAIL_CONFLICT --> [*] : explicit identity resolution, audited
    ABANDONED --> [*] : TTL reaped, no ghost account
    ACTIVE --> [*]
```

`ACTIVE` is unreachable without both `phoneVerifiedAt` and `emailVerifiedAt` — not by
convention but because the commit that writes the profile is the same transaction that
asserts them.

The commit is one `TransactWriteItems`:

| Item | Condition |
|---|---|
| `CUSTOMER#<customerId>` `PROFILE` | `attribute_not_exists(PK)` |
| `UNIQUE#PHONE#<normalisedPhone>` `CUSTOMER` | `attribute_not_exists(PK)` |
| `UNIQUE#EMAIL#<sha256(email)>` `CUSTOMER` | `attribute_not_exists(PK)` |
| `CUSTOMER#<customerId>` `ADDRESS#<addressId>` | — |
| `CUSTOMER#<customerId>` `EVENT#<ulid>` `CUSTOMER_ACTIVATED` | — |

All or nothing. `TransactionCanceledException` carries per-item reasons, so a
`ConditionalCheckFailed` on the phone marker routes to sign-in and one on the email marker
routes to conflict resolution — the two cases are distinguishable to us without being
distinguishable to the caller.

---

## 2. WhatsApp phone OTP

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant GW as API Gateway zllr9lrg7j
    participant OTP as OtpService Lambda
    participant DDB as DynamoDB
    participant COG as Cognito CUSTOM_AUTH
    participant WA as wecare-whatsapp-business-api live
    participant M as Meta Graph v25.0

    B->>GW: POST /customer/otp/phone/request
    GW->>OTP: invoke
    OTP->>OTP: normalise to E.164
    OTP->>DDB: ADD per-phone and per-IP counters, atomic
    alt over budget
        DDB-->>OTP: count over limit
        OTP-->>B: 429 RATE_LIMITED, fail closed
    else within budget
        OTP->>OTP: 6 digits from CSPRNG
        OTP->>DDB: put OTP#PHONE challenge, otpHash = HMAC code pepper, TTL
        OTP->>DDB: invalidate prior open challenges
        OTP->>WA: send template wecare_otp, url button param
        WA->>M: POST phone_number_id messages
        M-->>WA: message id
        OTP-->>B: 202 sent, masked destination, no registered flag
    end

    B->>GW: POST /customer/otp/phone/verify
    GW->>OTP: invoke
    OTP->>DDB: get challenge
    OTP->>OTP: compare_digest on HMAC, check expiresAt
    alt correct
        OTP->>DDB: conditional update, attribute_not_exists usedAt
        OTP->>COG: InitiateAuth then RespondToAuthChallenge
        COG-->>OTP: AccessToken
        OTP-->>B: 200 PHONE_VERIFIED plus session
    else wrong
        OTP->>DDB: ADD attemptCount
        OTP-->>B: 400 generic, attempts remaining
    end
```

Three details that are load-bearing:

- **`url`, not `copy_code`.** Meta materialises an `AUTHENTICATION` template's copy affordance
  as a real URL button, so the OTP substitutes into that URL. `copy_code` is rejected with
  `(#132018) buttons: Button at index 0 must be of type Url`, which surfaces only as
  "sender returned HTTP 400".
- **The sender Lambda is `wecare-whatsapp-business-api`, not `wecare-outbound-whatsapp`**, so
  verification traffic does not create CRM side effects.
- **The WABA isolation gate stays.** A user whose `custom:partner_waba_id` does not match the
  configured WABA is refused before any send.

## 3. Email OTP

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant OTP as OtpService Lambda
    participant DDB as DynamoDB
    participant SES as SESv2
    participant SNS as Bounce and complaint topic

    B->>OTP: POST /customer/otp/email/request
    OTP->>OTP: lowercase and trim, validate syntax
    OTP->>DDB: ADD per-email and per-IP counters
    OTP->>DDB: check suppression cache
    OTP->>OTP: 6 digits from CSPRNG
    OTP->>DDB: put OTP#EMAIL sha256 challenge, otpHash, TTL
    OTP->>SES: SendEmail from one@wecare.digital, ConfigurationSet wecare-digital
    SES-->>OTP: MessageId
    OTP-->>B: 202 sent

    SES->>SNS: Bounce or Complaint
    SNS->>OTP: event
    OTP->>DDB: record suppression, stop retrying this address

    B->>OTP: POST /customer/otp/email/verify
    OTP->>DDB: get, compare HMAC constant-time, check expiry
    OTP->>DDB: conditional update attribute_not_exists usedAt
    OTP-->>B: 200 EMAIL_VERIFIED
```

`one@wecare.digital` is already a verified SES identity with the domain DKIM-signed and
production access enabled — so there is **no provider work**, only the application path.

Two things that will bite if skipped. The identity carries **no default configuration set**,
so `ConfigurationSetName: wecare-digital` must be passed per send or reputation tracking and
suppression are silently skipped. And the domain is `DMARC p=reject` with MTA-STS `enforce`,
so an unaligned message **hard-bounces** rather than landing in spam; there is no soft-fail
state to catch a mistake.

`wecare-outbound-email` is not reused: it is SES v1, has no configuration set, and sends
`From: noreply@wecare.digital`.

## 4. Address capture

```mermaid
flowchart TD
    A[Customer types 3 or more characters] --> B[POST /customer/address/autocomplete]
    B --> C[AddressService Lambda]
    C --> D[Resolve backend Maps key by reference from Secrets Manager]
    D --> E[Places API New Autocomplete with session token]
    E --> F[Return suggestions: placeId plus text only]
    F --> G[Customer selects one]
    G --> H[POST /customer/address/details, same session token]
    H --> I[Places API New Place Details]
    I --> J[Split into structured components]
    J --> K{Address Validation enabled}
    K -- yes --> L[Call Address Validation v1, keep verdict as advisory]
    K -- no --> M[Skip]
    L --> N[Show normalised address back to the customer]
    M --> N
    N --> O[Customer adds flat, floor, landmark, instructions]
    O --> P{Customer confirms}
    P -- no --> N
    P -- yes --> Q[Persist CUSTOMER#id ADDRESS#addressId with googlePlaceId, lat, lng, verified true]
    Q --> R[Append ADDRESS_ADDED audit event]
    E -. Places unavailable .-> S[Fall back to manual structured entry, never block registration]
    S --> N
```

Delivery detail is stored **alongside** the canonical place reference, never merged into it,
so re-resolving the place later does not destroy "2nd floor, behind the temple".

**This flow is blocked on a key change, not on code.** `places.googleapis.com` is enabled on
project `wecaredigitalbw` but is absent from the unified key's `apiTargets`, so every New-API
call fails on key restriction until it is added. Enabling the service is not sufficient.

The key is also being split, per ADR in spec ADR-4: one browser key with referrer restrictions
limited to WECARE.DIGITAL domains, one backend key with server restrictions. The current single
key spans ~50 APIs and lists `places.googleapis.com` and `*.googleapis.com/*` as *referrers*,
which no browser ever sends — a restriction that does not restrict.

## 5. Session authentication

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser static export
    participant OTP as OtpService Lambda
    participant COG as Cognito us-east-1_46ULYuukt
    participant DDB as DynamoDB
    participant API as Any customer API Lambda

    B->>OTP: phone plus verified OTP
    OTP->>COG: InitiateAuth CUSTOM_AUTH then RespondToAuthChallenge
    COG-->>OTP: AccessToken, 60 minutes
    OTP->>DDB: put CUSTOMER#id SESSION#sessionId, device, ip, issuedAt, expiresAt
    OTP-->>B: AccessToken plus sessionId
    B->>B: store in sessionStorage, dies with the tab

    B->>API: Authorization Bearer token
    API->>COG: GetUser, proves signature and expiry
    API->>API: check iss equals customer pool issuer, rejects a staff token
    API->>DDB: session not revoked
    API->>DDB: resolve customerId from cognitoUsername
    API-->>B: data scoped to that customerId only

    B->>API: POST /customer/logout
    API->>DDB: mark SESSION#sessionId revoked
    API->>COG: GlobalSignOut
```

The `GetUser`-then-issuer-check ordering is the load-bearing part and is inherited from
`secure-files/handler.py::_customer_identity`. `GetUser` is pool-agnostic: it validates the
token against whichever pool issued it, which proves the token unmodified but is **not**
authorisation, because a staff token would also pass. Checking `iss` afterwards is sound
precisely *because* `GetUser` already proved integrity. Reversing the order would trust an
unverified claim.

Authorisation is always `session.customerId`, never an identifier from the request. That is
what closes IDOR on `/account/orders/[orderNumber]`.

## 6. Public content flow

```mermaid
flowchart LR
    subgraph AWS["AWS - canonical content"]
        PT[ProductsTable]
        ST[SeoToolsTable - blog posts]
        CA[wecare-native-catalog-admin<br/>/native-catalog/products]
        SEO[wecare-seo-tools<br/>/seo-tools/blog-public]
        MS[wecare-meta-catalog-sync]
    end
    subgraph Build["Amplify build - static export"]
        SNAP[scripts/build-catalog-snapshot.py]
        JSON[src/content/catalog-snapshot.json]
        SHOP[src/content/shop.ts]
    end
    subgraph FE["Browser"]
        PB[src/lib/public-blog.ts]
        PG[Page components]
    end

    CA --> PT
    PT --> SNAP --> JSON --> SHOP --> PG
    PT --> MS -->|every 6 h, gated| META[Meta catalog]
    SEO --> ST
    PB -->|GET /seo-tools/blog-public| SEO
    PG --> PB
```

Products are edited by staff through `wecare-native-catalog-admin` and live in
`ProductsTable` (prices as integer `priceMinor` paise). The storefront is generated from
`src/content/catalog-snapshot.json`, which `scripts/build-catalog-snapshot.py --live` writes
from `ProductsTable` in `.github/workflows/aws-native-catalog-publish.yml`.
`wecare-meta-catalog-sync` projects the same table one way to the Meta catalog, behind
`META_CATALOG_SYNC_ENABLED` and `META_CATALOG_SYNC_DRY_RUN`.

Blog posts live in `SeoToolsTable` and are served by `wecare-seo-tools` at
`/seo-tools/blog-public` and `/seo-tools/blog-public/{slug}`. Bulk intake uploads source files
with presigned PUTs to `wecare-digital-get` under `secure/blog-production/01-sources/`, then
`/seo-tools/blog-sources/confirm` hands them to an asynchronous worker.

The browser never holds a credential; every read and write goes through an AWS Lambda.

## 7. Page composition

```mermaid
flowchart TD
    A[Admin composes a page at [retired public path 84a04c24]/content/pages] --> B[PAGE#slug METADATA]
    A --> C[PAGE#slug SECTION#seq#sectionId]
    C --> D[Section holds a TYPE plus a product or post REFERENCE, never a copy]
    D --> E[Build or request time: GET /pages/slug]
    E --> F[PageComposer Lambda reads metadata plus ordered sections]
    F --> G[Batch-resolve referenced ids against ProductsTable and SeoToolsTable]
    G --> H[PageSectionRenderer maps type to component]
    H --> I1[HERO / RICH_TEXT / CTA / FAQ / TESTIMONIALS]
    H --> I2[PRODUCT_GRID / CAROUSEL / FEATURE / CATEGORY]
    H --> I3[BLOG_GRID / CAROUSEL / FEATURE / CATEGORY / TAG]
    H --> I4[CUSTOM]
    H --> J{Unknown type}
    J -- yes --> K[Render nothing, log once, do not break the page]
    G --> L{Referenced product or post deleted}
    L -- yes --> M[Drop that card, render the rest, never 500]
```

Storing a reference rather than a copy keeps one canonical record: an edit to a product or
post shows up without a republish, and there is no second copy to drift. The cost is a
fan-out read per page, which is why resolution is batched.

## 8. WhatsApp checkout

```mermaid
sequenceDiagram
    autonumber
    participant C as Customer on WhatsApp
    participant IN as wecare-inbound-whatsapp
    participant B as whatsapp_basket
    participant CO as wecare-checkout
    participant P as ProductsTable
    participant RZ as Razorpay Standard Checkout

    C->>IN: Send cart from the WhatsApp catalogue (message.type order)
    IN->>B: reduce to variants and integer quantities
    Note over IN,B: item_price from the client is ignored entirely
    B-->>IN: phone-bound basket hand-off, no total
    C->>CO: claim-basket (authenticated) merges it into the native cart (CartTable)
    CO->>P: catalog_pricing reads priceMinor per variant
    CO->>CO: checkout_pricing.compute_quote in integer paise
    CO->>P: reserve_basket, one TransactWriteItems with the CommerceKeys claim
    CO->>RZ: create the Razorpay order for the frozen payable
    RZ->>C: pay
```

Money is integer minor units throughout; floating-point money is prohibited.
`checkout_pricing.compute_quote` is the only calculator: goods from `ProductsTable`, a 2.5%
convenience fee plus 18% GST on that fee, `Decimal` with `ROUND_HALF_UP`. Currency is
compared explicitly rather than assumed INR.

On the native WhatsApp payment leg (`WHATSAPP_NATIVE_PG`) the customer pays inside WhatsApp
and Meta creates the Razorpay gateway order. `wa_payment_request.py` reserves the
`reference_id` before `order_details` is sent, so a retry reuses it instead of minting a second
reference. `reference_id` is a distinct identifier mapped to the order. It is never the order
number.

## 9. Payment reconciliation

```mermaid
flowchart TD
    A[wecare-razorpay-webhook POST] --> B{"X-Razorpay-Signature — HMAC-SHA256 over the RAW body, compare_digest"}
    B -- fail --> B1[Reject, record nothing]
    B -- pass --> C{Lease on WebhookDedup, keyed by the Razorpay event id}
    C -- already completed --> C1[Ack, resolve to the SAME existing order, no side effect]
    C -- leased now --> D[order_creation.reconcile_payment]
    D --> E[Authenticated Razorpay readback of the payment]
    E --> F[Resolve the payment attempt and its frozen payable]
    F --> H{currency, amount in paise and customer all match}
    H -- no --> H1[FAIL CLOSED, NEEDS_RECONCILIATION, raised for staff]
    H -- yes --> L{"PROVIDERPAYMENT# and PAYMENTATTEMPT# claims on CommerceKeys"}
    L -- already claimed --> L1[ORDER_ALREADY_EXISTS, same order, no double-record]
    L -- claimed now --> M[finalization.accept_paid writes OrderTable, INTERNAL_ORDER_CREATED]
    M --> M2[Tenders reconciled, ORDER_FINALIZED]
    M2 --> N[Generate the billing document once]
    N --> O[Send confirmation, expose in the account area]
    E -. provider unavailable .-> P[Recoverable state, retried to completion, never lost]
```

The rule that governs the whole diagram: **an order exists only after a verified capture.**
The browser verify path (`POST /ecommerce/verify-callback`) runs the same
`reconcile_payment`, and the `CommerceKeys` claims make whichever path arrives second a no-op.

Idempotency is a lease on `WebhookDedup`, closed only as the last step of the success path, so
a delivery that fails part-way is not permanently swallowed and a redelivery can complete it.

## 10. Order lifecycle

```mermaid
stateDiagram-v2
    [*] --> CART_OPEN
    CART_OPEN --> CART_EXPIRED : idle past TTL, no order created
    CART_OPEN --> CHECKOUT_CREATED
    CHECKOUT_CREATED --> PAYMENT_REQUESTED : totals matched exactly, order number reserved
    CHECKOUT_CREATED --> REJECTED_TOTAL_MISMATCH : any difference in amount or currency
    PAYMENT_REQUESTED --> PAYMENT_FAILED
    PAYMENT_REQUESTED --> PAYMENT_CAPTURED
    PAYMENT_FAILED --> PAYMENT_REQUESTED : customer retries
    PAYMENT_CAPTURED --> RECONCILING
    RECONCILING --> RECONCILE_FAILED : mismatch or provider unavailable
    RECONCILE_FAILED --> RECONCILING : automatic or staff retry, idempotent
    RECONCILING --> ORDER_CONFIRMED : internal order created or resolved exactly once
    ORDER_CONFIRMED --> BILLED : exactly one billing document
    BILLED --> FULFILLING
    FULFILLING --> SHIPPED
    SHIPPED --> DELIVERED
    DELIVERED --> [*]
    PAYMENT_CAPTURED --> STOCK_UNAVAILABLE : last unit sold concurrently
    STOCK_UNAVAILABLE --> REFUND_REQUIRED : surfaced to staff, no second charge
    REFUND_REQUIRED --> [*]
    CART_EXPIRED --> [*]
    REJECTED_TOTAL_MISMATCH --> [*]
```

Transitions are applied with conditional writes, so a concurrent duplicate cannot advance the
same order twice. An illegal transition fails safely rather than corrupting state. A terminal
state moves only through an explicit, audited staff action.

`STOCK_UNAVAILABLE` exists because payment-succeeded-but-stock-gone is a real case that must
not be papered over: the customer is not charged twice, and the case surfaces with a refund
path rather than silently failing.

## 11. Billing

```mermaid
flowchart TD
    A[ORDER_FINALIZED in OrderTable] --> B{Does a billing document already exist for this order}
    B -- yes --> B1[Return the existing one, never generate a second]
    B -- no --> E[invoice-engine: POST /invoices/from-payment]
    E --> F[POST /invoices/next-sequence, per-FY statutory sequence]
    F --> G[Generate PDF, and a POS thermal receipt PNG where relevant]
    G --> H[Store the asset privately in S3]
    H --> I[Persist billingDocumentType, invoiceId, invoiceNumber, receiptId, documentStatus, documentUrl, generatedAt, sentAt, viewedAt]
    I --> J[Deliver on WhatsApp, on email from one@wecare.digital, and in /account/billing]
    J --> K{Delivery failed}
    K -- yes --> L[Retry, without producing a duplicate customer-visible message]
    B1 --> J
```

A permanent unrestricted document URL is never exposed. The asset is a private S3 object in
`wecare-digital-get` under `secure/d/public/Invoice/customer_invoice/`, served through an authenticated API or a
short-lived signed URL.

One practical lesson already learned here and worth keeping: a link delivered over WhatsApp is
read when the person gets to it, not within 60 seconds, so its TTL is hours, not a minute —
while a browser redeem follows immediately and can be very short. And a SigV4 presigned URL
signed with temporary Lambda credentials cannot outlive the role session, which caps it.

## 12. Fulfillment

Not built. Native checkout ends at `ORDER_FINALIZED` plus the billing document; the
repository has no shipment table, carrier integration or tracking poller. When it is built,
the constraints are the ones the rest of the order path already follows: state changes are
conditional writes on the internal order, the timeline is append-only and backs **both** the
customer tracking page and the admin view, with the customer view *filtered* rather than
separately computed — two computations of the same history is how they disagree — and a
WhatsApp status update is marked sent so a retry does not duplicate it.

## 13. AWS architecture

```mermaid
flowchart TB
    subgraph Edge
        AMP[Amplify Hosting d22dm4b0jn71jw<br/>23 custom rules, 404-200 catch-all]
        CF[CloudFront: app.wecare.digital, mta-sts, /get origin]
    end
    subgraph API
        GW[HTTP API zllr9lrg7j<br/>361 routes, 0 authorizers, stage prod]
    end
    subgraph Identity
        CP[Cognito WECARE.DIGITAL-CUSTOMERS<br/>us-east-1_46ULYuukt, CUSTOM_AUTH]
        SP[Cognito WECARE.DIGITAL<br/>us-east-1_cSx0RHCIR, staff]
    end
    subgraph Compute["Lambda - 65 functions, python3.12 plus 1 image"]
        OTPL[OtpService NEW]
        CUST[CustomerIdentity NEW]
        ADDR[AddressService NEW]
        CART[wecare-checkout]
        RECON[wecare-razorpay-webhook]
        PAGE[PageComposer NEW]
        CAT[wecare-native-catalog-admin]
        INV[wecare-invoice-engine]
        INB[wecare-inbound-whatsapp]
        WAB[wecare-whatsapp-business-api]
        AUTH[wecare-customer-whatsapp-auth]
    end
    subgraph Data
        DDB[DynamoDB, 79 tables<br/>plus Customer, Otp, Cart, Tracking, Page]
        S3[S3 private billing assets]
        SQS[SQS: 4 work plus 4 DLQ]
        SM[Secrets Manager, 25 secrets]
        KMS[KMS wecare-secrets-manager]
    end
    subgraph External
        META[Meta Graph v25.0<br/>WABA 2094615664435155]
        RZP[Razorpay Standard Checkout]
        SES[SES one@wecare.digital verified]
        GMP[Google Places New plus Address Validation]
    end

    AMP --> GW
    CF --> AMP
    GW --> OTPL
    GW --> CUST
    GW --> ADDR
    GW --> CART
    GW --> PAGE
    GW --> CAT
    GW --> RECON
    GW --> INV
    OTPL --> CP
    AUTH --> CP
    OTPL --> WAB
    WAB --> META
    INB --> META
    INB --> SQS
    RECON --> INV
    CART --> RZP
    RECON --> RZP
    OTPL --> SES
    INV --> SES
    ADDR --> GMP
    OTPL --> DDB
    CUST --> DDB
    CART --> DDB
    RECON --> DDB
    PAGE --> DDB
    CAT --> DDB
    INV --> S3
    OTPL --> SM
    CART --> SM
    ADDR --> SM
    SM --> KMS
```

**There is no WAF node in this diagram, and that is current rather than an omission.**
Both web ACLs — `wecare-cognito-waf` (REGIONAL, both Cognito pools) and
`wecare-amplify-waf` (CLOUDFRONT, the Amplify app) — were deleted on 2026-09-28 by owner
cost decision, and `00-current-owner-overrides.md` withdrew "WAF must be implemented and
live-verified" as a required target at the same time. The diagram previously carried a
dashed `WAF -.-> GW` edge to mark the API's lack of coverage as a gap; that edge is gone
because the gap is no longer one the project intends to close. Edge filtering is now
absent everywhere, and the controls that remain are all in-handler. Restore path if the
decision reverses: `python3 scripts/provision_waf.py --apply`.

---

## Data model additions

All new items live in the existing single-table style, `stack-wecare-digital-*`.

| PK | SK | Notes |
|---|---|---|
| `CUSTOMER#<customerId>` | `PROFILE` | links `contactId` and `cognitoUsername` |
| `CUSTOMER#<customerId>` | `ADDRESS#<addressId>` | structured, `googlePlaceId`, lat/lng |
| `CUSTOMER#<customerId>` | `SESSION#<sessionId>` | revocable; TTL |
| `CUSTOMER#<customerId>` | `EVENT#<ulid>` | append-only audit |
| `UNIQUE#PHONE#<normalisedPhone>` | `CUSTOMER` | `attribute_not_exists` |
| `UNIQUE#EMAIL#<sha256(email)>` | `CUSTOMER` | hash, so the key space is not a harvestable list |
| `OTP#PHONE#<normalisedPhone>` | `CHALLENGE#<challengeId>` | `otpHash`, TTL, counters |
| `OTP#EMAIL#<sha256(email)>` | `CHALLENGE#<challengeId>` | same shape |
| `ORDER#<commerceOrderId>` | `METADATA` | |
| `ORDERNO#<commerceOrderNumber>` | `UNIQUE` | reserved **before** the number is accepted |
| `TRACKING#<sha256(token)>` | `ORDER` | token itself never stored |
| `PAGE#<slug>` | `METADATA` | |
| `PAGE#<slug>` | `SECTION#<sequence>#<sectionId>` | product or post reference, not a copy |

GSIs: `customerId` by normalised phone, by normalised-email hash, and by `contactId`; orders
by `customerId` and by `commerceOrderNumber`.

## Deployment

Per `.kiro/steering/lambda-snapstart-deploy.md`, and it is the `live` alias that makes this
mandatory, not SnapStart — which is `ApplyOn=None` on every function.

```
python scripts/deploy_all_lambdas.py <function>   # build, validate imports, upload
python scripts/snapstart_publish.py <function>    # publish version, wait Active, move live
```

A `$LATEST` update alone is not a deployment for any function carrying a `live` alias. There
is a second reason to move the alias: a function caches its secrets on first use, so replacing
a value in Secrets Manager does not change what a warm sandbox serves. A freshly published
version has no warm environments.

## What blocks what

```mermaid
flowchart LR
    BILL[Billing - DONE] --> TRACK[Fulfillment tracking, not built]
    GKEY[Add places.googleapis.com to the key<br/>then split browser and backend keys] --> ADR2[Autocomplete on the New API]
    ADR2 --> ADR3[Confirmation step]
    OTP1[OTP at rest, hashed] --> CI2[Transactional uniqueness]
    CI2 --> CI4[ACTIVE state]
    OTP1 --> SESS2[Session registry]
    CI4 --> ACC1[Account area]
    VER1[Version source - DONE] --> ALL[Everything Meta-facing]
```

One blocker is outside this repository's reach:

- **The Google key** — `places.googleapis.com` must be added to `apiTargets`, then the key
  split into browser and backend halves. Google-console and `gcloud` work.

Everything on the identity, OTP, email, session, account, composition, responsive and
accessibility tracks is buildable today, because SES and Meta are both verified live and
neither is blocked.
