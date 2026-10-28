# Secure file sharing — wecare.digital/get

Two tiers on one bucket. The open one is a plain CDN path; the gated one requires a
verified customer and a durable paid entitlement.

Status verified live 2026-09-25. Re-derive rather than trusting these numbers —
`.kiro/steering/00-current-owner-overrides.md` (retired 2026-10-09, af7858fa) requires rediscovery per phase.

## Tiers

| Tier | Prefix | Gate | URL |
|---|---|---|---|
| Open | `o/` | none | `wecare.digital/get/o/<file>` |
| Gated | `secure/` | WhatsApp OTP, then ₹49 per 24-hour access window | `wecare.digital/files/` |

A link that matches nothing, and anything under `secure/`, redirects to the apex.

## Why the object key is opaque

Every gated upload lands at:

    secure/wecare-digital-<uuid4hex>-<uuid4hex><ext>

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
      customRules, evaluated IN ORDER — /get/<*> must stay ABOVE the SPA catch-all
        /get            301 -> /
        /get/           301 -> /
        /get/<*>        200 rewrite -> d1kf2rchz7yras.cloudfront.net
        /files/         the app (must be in the _app.tsx public allowlist)
        /<*>            404-200 -> /index.html   <- catch-all, always last

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
the authenticated website Vault collection or WhatsApp catalog-service selection; this function
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

## Asking for ₹49, and renewals (2026-10-26)

A file is sold per document, one access window at a time, and every payment is the commerce
Review and Pay for that one file (server-priced, WABA1 only). **Vault has no WhatsApp Flow.**
ProductsTable is the only payment/display price authority: customer surfaces read
`GET /ecommerce/service-prices`, and checkout independently re-prices the exact Vault SKU from
ProductsTable before creating a payment attempt. Secure-files owns file identity, entitlement and
delivery only; it has no price environment variable or fallback amount. There are three ways in:

| Who | Where | What happens |
|---|---|---|
| Staff | Secure files → **Send Vault request-ready message** (or the upload checkbox) → `POST /secure-files/{fileId}/request-payment` | business-api `catalogService.sendOffer` sends template `wecare_vault_request_ready`: "📄 Your requested *{document}* is available in your Vault. Amount due for this request: *₹49*." with an **Unlock Vault** quick reply carrying an opaque offer token (`VAULTOFFER#<token>` in CommerceKeys, 7 days) |
| Customer | Taps **Unlock Vault** | inbound routes the tap to `catalogService.unlock`; the tap is the identity evidence, and the offer's file gets one Review and Pay (or Access Vault if already paid). An unknown, expired, revoked, reassigned or otherwise unusable offer stops with the single customer message "This document is not available right now." |
| Customer | WhatsApp "Vault" (keyword or Vault catalog item) | `catalogService.start` lists their documents as unpaid, **Paid** (free link) or **Renew**; picking one sends one Review and Pay |
| Customer | `/vault/?file=` or `/get/` | after WhatsApp-number verification, an unpaid/expired owned file creates a file-bound Vault service intent and enters the shared cart; `/checkout/` offers **Pay here** or **Pay on WhatsApp** |

The offer charges nothing and needs no linked WhatsApp contact beforehand: commerce's identity
bridge proves the customer from the tap, a signed inbound message, as it does for a cart. The
offer template is blocked in the Inbox template sender, because only Secure files can mint the
token that ties its button to a document.

Staff can also **Send Access Vault** (`POST /secure-files/{fileId}/send-access`) for a paid file; it
never charges and never opens a window.

Drop Docs (Service → Documents → **Add Document**) is a different store: managed document
records live in `DocumentTable` and are not billable merely because they exist there. Staff can
explicitly **Publish to Vault**, which verifies the customer identity and private object, creates an
owner-bound `SecureFilesTable` row for that immutable document version, and writes the resulting
`vaultFileId` back to the document. Repeating Publish for the same version is idempotent. A
confirmed replacement increments the document version and the next Publish gets a different Vault
file id, so an older paid entitlement can never authorize replacement bytes. Direct uploads through
**Secure files** remain the other supported Vault intake path.

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
