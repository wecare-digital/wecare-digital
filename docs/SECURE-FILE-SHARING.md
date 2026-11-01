## Backend hardening

- **Two independent services:** Drop Docs accepts customer-supplied documents into the protected `secure/d/public/drop-docs/` prefix and records them in `DocumentTable`. Vault is a staff-managed file delivery service: authenticated staff upload directly to `s3://wecare-digital-get/secure/d/public/valut/`, with owner-bound rows in `SecureFilesTable`. A Drop Docs upload does not create a Vault file or a Vault payment request.
- Staff Vault uses `POST /secure-files/upload-init` for a short-lived, exact-key presigned S3 upload and `POST /secure-files/{fileId}/confirm` for server-side HEAD/size/MIME verification. `GET /secure-files/{fileId}/staff-download` is staff-only. The upload capability is gated by `VAULT_DIRECT_UPLOAD_ENABLED` and must not be enabled until the live private-CDN controls, API routes and reviewed backend package are verified.
- The old `POST /secure-files/publish-document` Drop Docs-to-Vault bridge returns `410 DROP_DOCS_VAULT_PUBLISH_RETIRED` after its backend release; previously linked Vault rows and entitlements remain intact. The API provisioner deliberately retains this route as a harmless tombstone for older clients.
- Drop Docs customer documents from the manual upload, WhatsApp F003 Flow and service-request attach paths all use `media_paths.DROP_DOCS_UPLOAD_PREFIX = secure/d/public/drop-docs/` for **new writes**. The prefix is private despite `public/`: live S3 policy `DenyCloudFrontReadPrivateDropDocs` denies CloudFront OAC `GetObject`, and new edge code carries an equivalent exact-prefix deny. Older `secure/u/dropdocs/` keys remain readable by their persisted `DocumentTable.storageKey`; never rewrite or delete them without a separate verified migration. The original Drop Docs upload is not automatically a Vault sale.
- Paid download `Content-Disposition` uses the system-owned `wecare-digital-...` filename, never the original customer/staff upload filename.
- `wecare-secure-files` is provisioned with Active X-Ray tracing under its dedicated role; the role receives only the X-Ray write/sampling actions required for tracing.
- Exhausted asynchronous paid-delivery invocations are sent to `wecare-lambda-async-dlq` after the normal two retries / six-hour event age; the existing DLQ-depth alarm makes the failure durable and visible.
- Existing payment/ownership controls remain unchanged: customer-pool issuer pin, exact owner subject + phone checks, durable exact-file entitlement, conditional access-window writes, short-lived download URLs, and idempotent paid delivery.

## Vault filenames and links

- Vault customer filenames are system-owned. Staff do not type or rename them.
- A new staff Vault upload gets a server-generated opaque `wecare-digital-<file-id>.<ext>` name. Historical Vault entries that originated from the retired document bridge retain their own immutable file IDs and entitlement history.
- The original upload filename remains internal metadata only.
- The **literal** S3 prefix is `secure/d/public/valut/` (intentional spelling). Despite the `public/` ancestor, these paid Vault objects must never be served by CloudFront. Production S3 bucket policy `DenyCloudFrontReadPrivateVaultValut` denies OAC `GetObject` to this prefix; the newer edge source also denies the prefix but its CloudFront version must be independently verified before removing the bucket-policy guard.
- After successful staff upload and S3 confirmation, `SecureFilesTable.s3Key` names only the private `valut/` object. Drop Docs `DocumentTable.storageKey` is independently managed in its own protected `drop-docs/` intake storage. Previously migrated Vault copies do not erase or overwrite Drop Docs customer-source records.
- Workspace Vault exposes a staff-authenticated **Download** action for its own file and a **Customer Vault link** at `/vault/?file=<fileId>`; raw S3 keys never reach the browser.
- A customer arriving through a one-file Vault link stays on the exact-file Vault surface; the download page does not expose **Back to all Vault files** or **Sign out** controls.

# Secure file sharing — media namespace and Vault delivery

Public media is served under `/get/<key>`. Customer file access is exposed only through
`/vault/?file=<fileId>`, after verified identity and a durable paid entitlement.

Status verified live 2026-09-25. Re-derive rather than trusting these numbers —
`.kiro/steering/00-current-owner-overrides.md` (retired 2026-10-09, af7858fa) requires rediscovery per phase.

## Tiers

| Tier | Prefix | Gate | URL |
|---|---|---|---|
| Open | `o/` | none | `wecare.digital/get/o/<file>` |
| Gated | `secure/` | verified customer + paid access window | `wecare.digital/vault/?file=<fileId>` |

A link that matches nothing, and anything under `secure/`, redirects to the apex.

## Why the object key is opaque

A new paid Vault publication is saved at:

    secure/d/public/valut/wecare-digital-<opaque-file-id><ext>

Historical file keys may remain in older private prefixes. Vault never exposes
either key as a public URL.

The key carries no customer name, no original filename and no sequence number, so it
cannot be guessed and one customer's key reveals nothing about another's. The
consequence is that the key is meaningless to a human, which is why
`SecureFilesTable` exists: it is the only place mapping an opaque key back to a
person and a readable name, and its `owner-created-index` GSI answers "which of these
files belongs to which customer" as a query rather than a scan.

**The unguessable key is a convenience, not the control.** CloudFront refuses the
whole `secure/` prefix, so these objects are reachable only through a presigned URL
issued after ownership and payment are both checked.

## Request path

    wecare.digital  (Amplify Hosting app d22dm4b0jn71jw)
      customer route
        /vault/?file=<fileId>  exact-file Vault UI (the only customer download surface)
        /get/                  legacy static signpost -> /vault/
      media namespace — /get/<*> must stay ABOVE the SPA catch-all
        /get/<*>               200 rewrite -> d1kf2rchz7yras.cloudfront.net
        /<*>                   404-200 -> /index.html   <- catch-all, always last

    CloudFront E2GP22R4BIFGQ3
      no alternate domain name, so no Route 53 record and no ACM certificate
      Lambda@Edge origin-response (wecare-get-miss-redirect, associated by version):
        decoded URI under secure/ (not secure/d/public/) -> 302 apex  (checked BEFORE status)
        decoded URI under secure/d/public/catalog-deploy/ -> 302 apex
        status >= 400                                     -> 302 apex
      OAC EWEJQDZIBHRZU -> S3 wecare-digital-get (private, BPA on, AES256, versioned)

    wecare.digital/api (HTTP API zllr9lrg7j) -> wecare-secure-files:live

The prefix deny is checked before the response status deliberately: a gated object
that exists returns 200 from S3, so keying only off errors would serve it.

It is matched on the percent-decoded key, because S3 decodes the request path once
before the key lookup. Matching the raw URI let `/get/secur%65/...` and
`/get/secure%2F...` through to gated objects until 2026-10-25.

`secure/d/public/catalog-deploy/` (catalog masters, manifest, QA and deploy evidence) is
not served here, except product-image-gen's draft previews under
`catalog-media/generated/`. Approved catalog artwork is public only through
`https://wecare.digital/api/catalog-media/<file>`, whose Lambda reads S3 directly.
Paths with a `.` or `..` segment are refused outright.

A refused path returns an empty-bodied 302: the origin body and the object's own headers
(ETag, Last-Modified, `x-amz-*`) are dropped, because Lambda@Edge passes the origin body
through unless the function replaces it.

## Paid download flow

    GET  /secure-files/mine                          customer's own files
    GET  /secure-files/{fileId}/download?grant=<id>  transport from the paid entitlement

The payment-initiation routes `/whatsapp-pay` and `/order` were removed on 2026-10-22
(bf90ff69a). Secure-file purchases go through the commerce checkout's PaymentAttempt from either
the exact-file website Vault route or WhatsApp service selection; this function
settles historical grants (`confirmAndDeliver`), keeps the durable entitlement and delivers.

### When WhatsApp delivery fails

`reconcile_file_deliveries.py` retries the send. A customer whose number cannot receive it
— blocked, ported away, WhatsApp uninstalled — still collects on the web: the Vault page
offers Download for a file whose row names an active entitlement, and `/download` issues
transport from that entitlement. Delivery establishes the entitlement and that pointer
before it sends.

Entitlement is never taken from the browser.

### Razorpay's API is the only thing that can set `paid`

Changed 2026-09-25. Previously the webhook set `paid` itself, treating a valid HMAC
signature as proof of payment. That was sound in principle and unsound here: the webhook
secret is present in this repository's **public** git history, so anyone who read it could
forge a `payment.captured` event and mint a free download.

Rotating the secret would close that. Taking the secret out of the decision closes it
without depending on a rotation, and does not reopen if the secret leaks again. So:

| Component | May assert | May write `paid` |
|---|---|---|
| Browser / Checkout callback | nothing | no |
| Webhook (`POST /razorpay-webhook`) | "order X changed" | **no** |
| `secure-files._confirm_with_razorpay` | — | **yes, only here** |

The webhook forwards **only** an `orderId` to `wecare-secure-files:live` as
`internalAction: confirmAndDeliver`. It cannot name a file, a recipient or an amount;
those are read from the grant this system wrote at order-creation time.
`_confirm_with_razorpay` then calls `GET /v1/orders/{id}/payments` and writes `paid` only
if Razorpay reports a captured payment. A forged event gets the same answer as not paying.

Enforced at the IAM layer too: `wecare-digital-lambda-role` no longer has
`dynamodb:UpdateItem` on the grants table, so even a future code regression could not
perform the write. `provision_secure_files_api.py --verify` asserts that absence.

Only `captured` counts. `authorized` means the money is held but not taken, and
granting on it would hand over the file for a payment that can still fail.

**The trade is availability for integrity.** If Razorpay's API is unreachable, a real
payment is not granted immediately. That is recoverable — `reconcile_file_deliveries.py`
re-runs the same path — whereas a forged grant is not, because the file has already left.

Redemption never consumes the purchase: `/download` issues a short-lived download session
from the durable paid entitlement. A successful WhatsApp delivery, or the first redeem,
opens a 24-hour access window (`VAULT_ACCESS_WINDOW_HOURS`); downloads inside it are free,
and once it closes access needs a renewal. The grant write requires
`paid = false`, so a replayed capture cannot revive a spent grant.

Both callers of the single writer record provenance: `paidVia=webhook` when the hint
arrived, `paidVia=reconcile` when the sweep got there first. The latter also logs
`WEBHOOK_MAY_NOT_BE_SUBSCRIBED`, which is the signal the webhook is not doing its job.

## Two Cognito pools, deliberately separate

| Pool | Id | Purpose |
|---|---|---|
| `WECARE.DIGITAL` | `us-east-1_cSx0RHCIR` | staff. Admin/Operator/Viewer |
| `WECARE.DIGITAL-CUSTOMERS` | `us-east-1_46ULYuukt` | customers. Phone-keyed, CUSTOM_AUTH |

Admin routes use `lambda_utils.middleware.require_auth`, which is hardcoded to the
staff pool. Customer routes must **not** reuse it: a customer token would pass
`get_user` and then silently degrade to role `Viewer` when its group lookup found
nothing. Instead `get_user` proves the token genuine (AWS checks signature and
expiry) and the `iss` claim is then pinned to the customer pool — sound precisely
because the token is already proven unmodified. No crypto dependency needed.

Customer users are created phone-keyed with `MessageAction='SUPPRESS'` and a
permanent random password that is never logged or returned, so they land `CONFIRMED`
and the only way in is a WhatsApp OTP. They are stamped with
`custom:partner_waba_id` because the OTP trigger refuses a user whose WABA scope does
not match.

## Two Razorpay secrets, not interchangeable

    wecare/razorpay/api        key_id + key_secret    API auth
    wecare/razorpay-webhook    webhook_secret only    signature verification

Conflating them has cost this codebase twice. `partner-onboarding` read the API pair
from the webhook secret and returned 501 on every top-up; this feature repeated it on
first write.

No Razorpay SDK is bundled. `razorpay==2.0.1` is in `requirements-dev.txt` only, so
it is absent from the Lambda runtime, and the Orders API is a single POST.

## Live state, 2026-09-25

| Resource | Value |
|---|---|
| `wecare-secure-files` | live **v13**, python3.12 |
| `wecare-customer-whatsapp-auth` | live **v9** |
| `wecare-razorpay-webhook` | live **v36** |
| `wecare-get-miss-redirect` | **v4**, origin-response. No `live` alias — Lambda@Edge associates by version |
| `SecureFilesTable` | ACTIVE, GSI `owner-created-index` |
| `DownloadGrantsTable` | ACTIVE, GSI `order-index`, TTL on `expiresAt` |
| API routes | 7, all targeting `:live`, all 401 anonymously |
| Amplify | job 863 SUCCEED on `cdb89e9f` |

## Verify

    python scripts/verify_file_sharing.py                        # both tiers, 30 checks
    python scripts/provision_secure_files_api.py --verify        # lambda, routes
    python scripts/provision_secure_file_sharing.py --verify     # tables, GSIs, TTL
    python scripts/provision_customer_whatsapp_auth.py --verify  # pool, client, triggers

`provision_customer_whatsapp_auth.py --verify` checks the env on the **`live` alias**, not
`$LATEST`. The three Cognito triggers invoke the alias, so a published version freezes the
config a caller actually sees and `update_function_configuration` alone changes nothing.
It reported "verified" once against a stale alias; it now fails and names the fix.

## Vault under Pay & Flow — direct payment and renewal (2026-10-31 update)

Vault staff operations now belong to **Workspace → Pay & Flow → Vault · Review & Pay**.
Old `/workspace/service?view=vault` bookmarks redirect there. The general invoice
builder remains available under **Collect** for other staff collections; it MUST NOT
generate a free-form invoice to unlock a Vault document. Vault uses an exact-file,
server-priced native WhatsApp payment request, not editable unit amounts or a
separate cart. The staff sees a read-only, dynamic item/taxes/Delight/fee preview.

The supported staff initiation is a **direct Vault S3 upload**, confirmed with a
HEAD on the exact private object and recorded in `SecureFilesTable` as an active,
owner-bound `fileId`. It does not pass through Drop Docs or `DocumentTable`.
The backend checks exact-file ownership, durable paid state and existence of the
nonempty private S3 object before invoking `POST /secure-files/{fileId}/request-payment`.
An unpaid or expired file may receive a native
`wecare_whatapp_native_pay_template` **Review & Pay** request; only the customer
can approve a charge. OPEN/READY may resend existing paid access for free.
PAID_UNVERIFIED must reconcile rather than charge again. For expired access, one
new verified capture buys one additional window for the same immutable document.

The **new Unlock Vault offer is retired**: `POST /secure-files/{fileId}/send-offer`
is a 410 tombstone in the reviewed handler and an explicitly retired API route in
the provisioner. Staff cannot schedule new offer templates, and the legacy
`sendVaultOffer` internal action refuses new sends. **Previously sent** signed
quick replies are still accepted through the existing owner-bound inbound
`catalogService.unlock` handler; history is not deleted or reassigned.

After authoritative capture, keep the already approved, noneditable Meta sequence:

1. `wecare_order_status_v3` processing
2. `wecare_order_status_v3` completed
3. **One** `wecare_default_invoice_image_template` using the actual issued,
   server-rendered paid PNG with Leave Review Flow button
4. **One** `wecare_default_download` with dynamic Access Vault URL
   `https://wecare.digital/vault/?file=<fileId>`, after verified entitlement

No raw PDF/document WhatsApp attachment is sent as additional fulfillment. The
Vault page proves customer login + exact ownership + paid access-window eligibility
and only then generates the short-lived private S3 download session.

### Bounded operator timing, read-only media verification

Workspace **Pay & Flow → Access delay** now edits only one field in the
SystemConfig record `vault_delivery_timing_v1` (staff Operator permission):
`postReceiptAccessGapSeconds`, a whole number from **0–5 seconds**, default
**4 seconds** if absent, invalid or unreadable. The previous
`orderStatusGapSeconds` field is ignored when reading historical records and
**rejected on new writes**. The webhook no longer reads status-spacing config.

There is **no application-imposed waiting** before native Review & Pay, between
captured payment and Processing, or between Completed and the paid invoice.
For an authoritative Vault native payment **only**, one fixed **1-second** gap
is applied after Meta accepts the Processing order-status update and before the
Completed update. The fixed 1-second gap is not editable; when the Processing
update was already current and is not resent, no extra pause is required.
After Completed, the paid invoice is sent as soon as its required workflow
conditions are satisfied, with **0 seconds** additional spacing. Only after the
accepted paid receipt does Vault apply the editable **0–5 seconds** access delay.
These gaps do not replace payment capture, Meta message acceptance, exact-file
entitlement, deduplication, or delivered/read status; uncertain messages must not
be resent blindly.

Approved customer templates (Meta ID from the canonical server allowlist):
- Review & Pay: `wecare_whatapp_native_pay_template`, `2714938845570815`
- Processing and Completed (same status template, distinct sends):
  `wecare_order_status_v3`, `1754227779211208`
- Paid invoice image: `wecare_default_invoice_image_template`, `1782246473079550`
- Dynamic Access Vault link: `wecare_default_download`, `1410998911012572`

The approved Access Vault URL button is
`https://wecare.digital/vault/?file={{1}}`, where the sender fills button
variable `{{1}}` using the exact server-bound `fileId`. Customers authenticate,
pass ownership and paid-entitlement checks on the Vault page, then receive a
separate 60-second private S3 download URL. Staff never insert a presigned
customer document URL into an outbound WhatsApp template.

### Exact-file 404 fallback, ₹49 one-line description and no-file WhatsApp reply

- `/vault/` with no document, an invalid `?file=` identifier, or an authenticated
  user with no matching **active** owner-bound file uses the site's existing
  `/404` → homepage redirect. A valid paid file is not redirected simply
  because its **24-hour access window** ended: the page may show expired access,
  but cannot issue a private URL or charge for an unauthorized file.
  A lookup error does not masquerade as a missing file; a 401 first allows
  customer authentication, and ownership is never inferred from the URL.
- The **only editable field** in the Vault payment/invoice workbench is the
  **name/description of exactly one ₹49 (`4900` paise) Vault service line**.
  Default: `Vault Access - Secure document download (24 hours)`.
  Operators may enter a **single line of 12–60 safe characters**. Server
  recomputes the price from ProductsTable and rechecks the one-line ₹49 SKU;
  quantity, GST, Delight, Express, convenience fees, total, owner and file ID
  remain non-editable. A mismatched price refuses custom wording.
  That exact validated description is frozen onto the native PaymentAttempt's
  `invoiceLines`, consumed by WhatsApp ORDER_DETAILS and reused by the paid
  GST invoice PNG; no one can modify an issued invoice's item price or label.
  Customer-initiated purchases cannot author the item wording.
  Scheduled manual Vault payment sends persist their chosen wording.
- **Customer WhatsApp Vault chooser retired (issue #2133).** The old catalog
  Vault item, `vault` / `my vault` keywords, tokenless Unlock Vault buttons,
  cached `vaultpick:` list rows and generic Vault menu leaf do not list files,
  select a target, solicit renewal or create a payment. An eligible signed
  inbound message receives one generic service-window notice: use the
  **staff-issued exact-file Access Vault link** or contact support. The response
  cannot identify an owned, missing, revoked or another customer's file and
  never links to the obsolete bare `/vault/` entry.
- The no-payment notice is reserved in CommerceKeys by the signed inbound
  message ID **before** sending. The send audit stores `replySendStatus`
  (`ACCEPTED`, `REJECTED`, `UNKNOWN`), the real
  `replyMessageId` when available, and whether reconciliation is needed;
  Meta acceptance alone does not prove handset delivery. Replays, timeouts,
  5xx and incomplete audit updates cause **no blind retry**.
- Previously issued signed `vaultoffer:` quick replies continue to use
  owner-bound validation, existing payment obligations and free paid-access
  refresh when eligible. Unknown/revoked/expired offers take the same generic
  one-shot refusal, **not** the removed Submit Request fallback. The staff
  `sendPayment` exact-file Review & Pay and Drop Docs native checkout are
  unchanged. This retirement does not alter invoices, pricing or money state.

Staff may request a **60-second presigned S3 GET preview** of two exact owner-approved,
non-customer PNG assets from `GET /secure-files/payment-media-preview`:
the native WhatsApp IMAGE header `whatsapp-header.png` and the original
`WECARE_ORDER_DETAILS_THUMBNAIL_ORIGINAL_ICON_2048.png` item thumbnail.
This Operator-only endpoint HEAD-checks and signs exactly those two allowlisted
`secure/d/public/whatsapp/wa-tpl/` objects. It accepts **no** S3 key, customer
file id, arbitrary URL or upload. The preview URLs are never sent to customers.
The actual sender uses its existing independently validated media constants.

**Release prerequisites:** verify the reviewed Git commit, frontend typecheck/build,
targeted tests and live template readiness, then release the affected Lambdas with
immutable versions/alias rollback evidence, followed by frontend and explicit
`provision_secure_files_api.py --verify`/route retirement. A merge or frontend
Amplify success alone is not a backend deployment. No live payment or customer
WhatsApp send is part of this refactor.

The browser never submits a trusted amount, SKU, customer id or payment state. For an EXPIRED file,
business-api reads the durable entitlement and allows a renewal only when every paid window has
been used. OPEN/READY and PAID_UNVERIFIED never create another payable request.

Staff can also **Send Access Vault** (`POST /secure-files/{fileId}/send-access`) for a paid file; it
never charges and never opens an unpaid window. Vault remains a secure-download fulfilment and has
no Meta Flow.

Drop Docs (Service → Documents) manages **customer uploads** and their request
attachments in `DocumentTable`, under the private Drop Docs storage prefix. It
does **not** publish new files to Vault, create Vault payment requests, or call the
Vault staff upload API. Existing historical `vaultFileId` links remain visible
for audit and earlier paid entitlements, but the retired cross-service publish
route rejects new requests. Staff create and manage new Vault documents directly
in **Workspace → Pay & Flow → Vault**, using the separate `valut/` prefix.

Windows are paid for one at a time. The durable entitlement counts `paidWindowCount` (a missing
counter is the one original purchase) and `accessWindowCount`. A window opens against an unused paid
one as soon as the Access Vault message is accepted (business-api `paid_vault`, after the send,
through secure-files `openVaultAccessWindow`), or on the first download if that call failed. Opening
it never holds back the message. A renewal adds one to `paidWindowCount` on the same entitlement
(`vault_access.grant_access`), and is sold only once every paid window has been used
(`service_request_store.request_intent`, `VAULT_ACCESS_ACTIVE` otherwise). A Vault intent with no
file is refused (`VAULT_FILE_REQUIRED`), because a payment bound to an order has nothing to unlock.

Internal invokes of `wecare-secure-files` name one of four actions: `openVaultAccessWindow`,
`deliverOverWhatsApp`, `confirmAndDeliver` and `provisionCustomerLogin`. Any other `internalAction`
gets `{"ok": false}`. It used to fall through to the HTTP router, where `require_auth` treats an
event with no API Gateway context as internal, and came back with the staff file list.

Every file carries `accessState`: `UNPAID`, `OPEN`, `READY` (paid, not opened), `EXPIRED` or
`PAID_UNVERIFIED` (a purchase is recorded but its entitlement could not be read: reconcile, never
charge again).

## Paid downloads have no switch

`SECURE_FILES_PAYMENT_ENABLED` and the provisioner's `--enable-payment`/`--disable-payment`
were retired on 2026-10-22 (27099fc3, e9a8c0db6) together with the payment routes. There is
nothing to enable here: purchases are taken by the commerce checkout, and this function's
part starts after payment.

## WhatsApp delivery

Every paid file is announced with `wecare_default_download`, the approved WABA1 template for
Vault delivery: a fixed IMAGE header and URL button 0 `https://wecare.digital/vault/?file={{1}}`,
of which only the file id travels. `whatsapp_delivery.send_vault_link` builds the send with
`lambda_utils.whatsapp_templates.download_send_fields`, the same builder paid Vault delivery
and the paid-file refresh use, so the three cannot drift. The customer signs in on the Vault
page and downloads through the durable paid entitlement.

The template carries no bearer link and can be delivered outside the 24-hour
customer-service window. It replaced two transports that could not work (e22243370,
2026-10-25): PDFs and images named the document-header template `wd_file_delivery`, which is
not on WABA1, so Meta refused every such send; other file types got a presigned S3 URL in a
free-form text, which Meta accepts only inside the window. Nothing sends `wd_file_delivery`
or its former rollback `01_wecare_doc` any more, and `WA_DOC_TEMPLATE`, `WA_MEDIA_FUNCTION`
and `WHATSAPP_LINK_TTL_SECONDS` were removed with their readers.

An outbound dry run answers 200 without sending, so it is recorded as not delivered.

### Delivery is findable when it fails

A failed send used to be a log line while the customer had already been charged, so
nothing could answer "who is owed a file". Delivery now writes `delivered`,
`deliveryDetail`, `deliveryAttempts` and `deliveryAttemptedAt` onto the grant:

    python scripts/reconcile_file_deliveries.py --report
    python scripts/reconcile_file_deliveries.py --retry

It ignores `consumed` on purpose — a web redeem does not discharge a WhatsApp delivery the
customer also paid for — and skips the `otpprobe#` rows that share the grants table.

### One download TTL

    DOWNLOAD_URL_TTL_SECONDS   60      web redeem; a browser follows it instantly

It is the only presigned link this function issues. WhatsApp delivery sends a Vault page
link instead, so the separate link TTL went with the link transport.

## OTP enumeration budget

Telling an unregistered caller `registered: "false"` fixed a real dead end — a mistyped
number produced a code screen and permanent silence, because Cognito issues a challenge
for an unknown user too. It also made the endpoint enumerable.

Bulk probing is capped at 5 reveals per number per hour, after which the answer becomes
`"unknown"` and stops distinguishing registered from not:

    OTP_PROBE_MAX_PER_WINDOW   5
    OTP_PROBE_WINDOW_SECONDS   3600

Counted per **number**, not per IP, because a Cognito trigger receives no source IP. Per
number is the right axis anyway: it bounds how fast one number can be tested, and
spreading across a list gains nothing since each number still comes back here.

It **fails open**. A counter that cannot be read must not lock a paying customer out of
their own files; not enforcing the budget during a DynamoDB problem is far smaller harm
than refusing legitimate verification.

Do not "fix" enumeration by re-hiding the flag — that restores the dead end. Tighten the
budget instead.

## Pending

| Item | Status | Note |
|---|---|---|
| Paid downloads | ➖ **NO SWITCH** | `SECURE_FILES_PAYMENT_ENABLED` was retired on 2026-10-22. Purchases go through the commerce checkout; this function settles historical grants and delivers |
| `verified -> list files` hop | ⏳ **UNPROVEN** | Needs a customer token, which needs the OTP from the handset. The handler deliberately never logs the code, so this cannot be closed from the code side |
| `payment.captured` subscription | ➖ **NO LONGER LOAD-BEARING** | Was ⏳ UNCONFIRMED. The webhook is now only a hint, so whether the subscription exists changes *latency*, not *entitlement* — a missing subscription means the reconcile sweep grants instead of the webhook. 316 webhook events were received 2026-09-24/25 and every one was `payment.downtime.*` |
| Webhook secret in public git history | ➖ **NEUTRALISED, not removed** | Still in history (69 blobs). It can no longer grant anything: signature verification is not entitlement. The history itself is unchanged — that needs a rewrite, which the owner has deferred |
| Test leftovers | ➖ **INTENTIONAL** | A QA Cognito customer (`+918100640044`) and two seeded files. Harmless, useful for testing, removable on request |

## Four things that are easy to misread

`deploy_all_lambdas.py --dry-run` compares each package's sha with the live `CodeSha256`,
and every package embeds `lambda_utils`, so one shared-module commit makes nearly every
function `WOULD UPDATE`. That says a shared module moved, not that each function runs stale
code; `scripts/check_deployed_source.py` answers that file by file.

`wecare-get-miss-redirect` has **no `live` alias**, and that is correct. Lambda@Edge
associations must name a published version; an alias is not permitted. Do not "fix"
it by adding one.

`userName` on a Cognito trigger event is **top-level**, not inside `request`. Reading it
from `request` yields an empty string silently — which is how the probe budget shipped
doing nothing at all and eight consecutive probes got the reveal.

`/download` is not a fallback any more; it is how the Vault page collects a paid file. See
"When WhatsApp delivery fails" above.

## Test links

| What | Link | Gate |
|---|---|---|
| Open sample | `https://wecare.digital/get/o/sample.txt` | none, downloads immediately |
| Open healthcheck | `https://wecare.digital/get/o/healthcheck.txt` | none |
| Gated sample | `https://wecare.digital/files/` → "Sample invoice.txt" | OTP to `+918100640044`, then ₹49 |
| Bad link | `https://wecare.digital/get/anything-else` | 302 to the apex |
