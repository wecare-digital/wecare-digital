# Secure file sharing — wecare.digital/get

Two tiers on one bucket. The open one is a plain CDN path; the gated one requires a
verified customer and a paid, single-use grant.

Status verified live 2026-09-25. Re-derive rather than trusting these numbers —
`.kiro/steering/00-current-owner-overrides.md` (retired 2026-10-09, af7858fa) requires rediscovery per phase.

## Tiers

| Tier | Prefix | Gate | URL |
|---|---|---|---|
| Open | `o/` | none | `wecare.digital/get/o/<file>` |
| Gated | `secure/` | WhatsApp OTP, then ₹49 per download | `wecare.digital/files/` |

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
      Lambda@Edge origin-response v4:
        URI under secure/   -> 302 apex   (checked BEFORE status)
        status >= 400       -> 302 apex
      OAC EWEJQDZIBHRZU -> S3 wecare-digital-get (private, BPA on, AES256, versioned)

    wecare.digital/api (HTTP API zllr9lrg7j) -> wecare-secure-files:live

The prefix deny is checked before the response status deliberately: a gated object
that exists returns 200 from S3, so keying only off errors would serve it.

## Paid download flow

    GET  /secure-files/mine                  customer's own files
    POST /secure-files/{fileId}/whatsapp-pay PRIMARY: sends the wecare_whatapp_native_pay_template template
    POST /secure-files/{fileId}/order        FALLBACK: Razorpay Checkout on the web
    GET  /secure-files/{fileId}/download     FALLBACK: redeems a grant -> presigned URL

### Why the web payment path is kept

`/order` and `/download` are live and tested, and **nothing in the UI calls them** — the
page uses `/whatsapp-pay`. That looks like dead code and is not.

They are the only route by which a customer who has already paid can obtain a file when
WhatsApp delivery keeps failing. `reconcile_file_deliveries.py` retries the send, but if
a number is permanently unreachable — blocked, ported away, WhatsApp uninstalled — retry
cannot help and the customer is owed a file with no way to collect it. Deleting these
would mean the only recovery path is a manual S3 presign by an operator.

So they stay, deliberately, as a documented fallback rather than an accident. If they are
ever removed, a replacement recovery path has to exist first.

Entitlement is never taken from the browser. Razorpay Checkout's success callback is
forgeable, so it only stops the spinner.

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

Redemption is a conditional write on `paid = true AND consumed = false`, so a
forwarded link is dead on second use and two concurrent requests cannot both win. The
grant write requires `paid = false`, so a replayed capture cannot revive a spent grant.

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
first write. `tests/test_secure_files.py` now pins both the module default and the
IAM grant.

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
    python scripts/provision_secure_files_api.py --verify        # lambda, routes, flag
    python scripts/provision_secure_file_sharing.py --verify     # tables, GSIs, TTL
    python scripts/provision_customer_whatsapp_auth.py --verify  # pool, client, triggers
    python -m pytest tests/test_secure_files.py                  # 72 invariants

`provision_customer_whatsapp_auth.py --verify` checks the env on the **`live` alias**, not
`$LATEST`. The three Cognito triggers invoke the alias, so a published version freezes the
config a caller actually sees and `update_function_configuration` alone changes nothing.
It reported "verified" once against a stale alias; it now fails and names the fix.

## Enabling paid downloads

    python scripts/provision_secure_files_api.py --enable-payment

Three steps in one, and skipping any leaves a misleading state: write the **whole**
env map (a partial map deletes every variable not mentioned), publish a version (a
version freezes its environment), and move the `live` alias (the API invokes the
alias, so until this runs the change is real on `$LATEST` and invisible to every
request).

The flag is **sticky**. `provision_secure_files_api.py` reads the current value off
the live alias and preserves it, so re-provisioning cannot silently switch payments
back off. `deploy_all_lambdas.py` never touches configuration, so code deploys are
safe too. A brand-new function still starts off.

Rollback: `--disable-payment`, or the alias move the enable step prints.

## WhatsApp delivery

Payment request and file both go out as approved templates.

| Template | Components | Role |
|---|---|---|
| `wecare_whatapp_native_pay_template` | IMAGE, BODY, FOOTER, BUTTONS(`ORDER_DETAILS`) | ₹49 request |
| `wd_file_delivery` | DOCUMENT, BODY({{1}} name, {{2}} file), FOOTER, no buttons | delivery, **current default, APPROVED** |
| `01_wecare_doc` | DOCUMENT, BODY, FOOTER, BUTTONS(`FLOW`) | delivery, rollback only |

`wecare_whatapp_native_pay_template`'s button is `ORDER_DETAILS`, i.e. WhatsApp Pay's native checkout, not a URL
button — which is why a Razorpay payment link was never an option for it. The amount
travels in the `order_details` payload rather than the message text, because that BODY
has no variables.

`wd_file_delivery` was submitted to replace the reuse of `01_wecare_doc`, which cannot
name the file or the customer and carries a leftover `FLOW` button labelled "Subscribe" —
an upsell attached to something already paid for. `WA_DOC_TEMPLATE` still defaults to the
older template so delivery never depends on an approval that has not landed. Flip it once
Meta approves:

    python scripts/provision_file_delivery_template.py --verify   # check approval
    # then set WA_DOC_TEMPLATE=wd_file_delivery

Body parameters are keyed on the template **name** (`TEMPLATES_WITH_BODY_VARS`), not a
separate flag, because sending parameters to a template without placeholders is a Meta
parameter mismatch — the two must move together.

`wecare_whatapp_native_pay_template` is deliberately not recreated. Its gap is cosmetic, and its `ORDER_DETAILS`
button is coupled to the account payment configuration, so hand-rolling a replacement
risks breaking a working checkout to fix wording.

### The document travels as a media id

Meta must be able to fetch what it attaches, and the whole `secure/` prefix is refused at
the edge, so there is no URL to hand it. Bytes go to `/wa-business/media` with `s3Key` +
`s3Bucket` and the returned media id becomes the template header.

Passing bytes inline as base64 was the obvious alternative and is wrong: a synchronous
Lambda invoke payload caps at 6MB and base64 adds about a third, so anything over roughly
4.4MB fails — well under the 100MB Meta accepts for documents.

`s3Bucket` is guarded by `MEDIA_SOURCE_BUCKETS`, an allowlist. `whatsapp-business-api` is
invoked by several other Lambdas, and an open bucket parameter would have handed every one
of them a read-any-object primitive.

### Delivery is findable when it fails

A failed send used to be a log line while the customer had already been charged, so
nothing could answer "who is owed a file". Delivery now writes `delivered`,
`deliveryDetail`, `deliveryAttempts` and `deliveryAttemptedAt` onto the grant:

    python scripts/reconcile_file_deliveries.py --report
    python scripts/reconcile_file_deliveries.py --retry

It ignores `consumed` on purpose — a web redeem does not discharge a WhatsApp delivery the
customer also paid for — and skips the `otpprobe#` rows that share the grants table.

### Two TTLs, not one

    DOWNLOAD_URL_TTL_SECONDS   60      web redeem; a browser follows it instantly
    WHATSAPP_LINK_TTL_SECONDS  21600   link delivery; a person taps when they read it

A `deliverable=link` file goes out as a message containing a URL. At 60 seconds that URL
is usually expired before it is read, after the customer has paid. Capped below 24h
because a SigV4 URL signed with temporary Lambda credentials cannot outlive the role
session.

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
| Paid downloads | ⚠️ **DISABLED** | `SECURE_FILES_PAYMENT_ENABLED=false`. Owner action; enabling payment capture is outside agent authority, and so is making it default-on |
| `verified -> list files` hop | ⏳ **UNPROVEN** | Needs a customer token, which needs the OTP from the handset. The handler deliberately never logs the code, so this cannot be closed from the code side |
| `payment.captured` subscription | ➖ **NO LONGER LOAD-BEARING** | Was ⏳ UNCONFIRMED. The webhook is now only a hint, so whether the subscription exists changes *latency*, not *entitlement* — a missing subscription means the reconcile sweep grants instead of the webhook. 316 webhook events were received 2026-09-24/25 and every one was `payment.downtime.*` |
| Webhook secret in public git history | ➖ **NEUTRALISED, not removed** | Still in history (69 blobs). It can no longer grant anything: signature verification is not entitlement. The history itself is unchanged — that needs a rewrite, which the owner has deferred |
| Test leftovers | ➖ **INTENTIONAL** | A QA Cognito customer (`+918100640044`) and two seeded files. Harmless, useful for testing, removable on request |

## Four things that are easy to misread

`deploy_all_lambdas.py --dry-run` **always** reports `unchanged`, regardless of what
would change — the dry-run branch increments that tally unconditionally without
comparing shas. A dry run tells you packaging succeeded, not what would deploy.

`wecare-get-miss-redirect` has **no `live` alias**, and that is correct. Lambda@Edge
associations must name a published version; an alias is not permitted. Do not "fix"
it by adding one.

`userName` on a Cognito trigger event is **top-level**, not inside `request`. Reading it
from `request` yields an empty string silently — which is how the probe budget shipped
doing nothing at all and eight consecutive probes got the reveal.

`/order` and `/download` look like dead routes and are not. See the fallback note above.

## Test links

| What | Link | Gate |
|---|---|---|
| Open sample | `https://wecare.digital/get/o/sample.txt` | none, downloads immediately |
| Open healthcheck | `https://wecare.digital/get/o/healthcheck.txt` | none |
| Gated sample | `https://wecare.digital/files/` → "Sample invoice.txt" | OTP to `+918100640044`, then ₹49 |
| Bad link | `https://wecare.digital/get/anything-else` | 302 to the apex |
