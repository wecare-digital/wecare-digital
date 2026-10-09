# WhatsApp Customer Service Architecture — design and feasibility

Scope-extension deliverable **D4**, carrying **D5** (profile privacy) and **D6** (Orders Flow)
inside it, as `SCOPE-EXTENSION-whatsapp-hub.md:39-59` requires.

**Nothing in this document is created, uploaded, published or enabled.** No Flow is created or
modified. No feature flag is opened. Candidate asset names below are planning labels only.

Companion deliverables: `website-to-whatsapp-migration-matrix.md` (D3, nine-column matrix) and
`whatsapp-payment-state-machine.md` (D7, fourteen branches). Together with this file that is
**three** output documents, which is the full set named in `SCOPE-EXTENSION-whatsapp-hub.md:103-107`.

A parallel session published an overlapping architecture document at
`docs/execution/xcodex-20261009/whatsapp-customer-service-architecture.md` (commit `e006b5f3`,
on `origin/stack`). Its conclusion is compatible with this one — "adopt a hybrid architecture …
a whole customer-service replacement cannot currently be certified as native". Where the two
differ in detail, the file:line evidence below governs, and the overlap is recorded as conflict
**C12** in `answers.md`.

---

## 1. The identity rule that governs every classification

One already-implemented rule decides everything below: **a WhatsApp phone number alone never
authorizes private data.**

The enforcement point is
`amplify/functions/shared/lambda_utils/ecommerce/catalog_service_checkout.verified_identity`,
which requires all of: a parsable E.164 sender; that it is not the business sender; a
`checkoutCustomerId` on the contact row; a non-soft-deleted contact whose own `phone` equals the
sender; **exactly one** `Enabled` Cognito user in pool `us-east-1_46ULYuukt` whose `sub` equals
that `checkoutCustomerId`; `phone_number` equal to the sender; and `phone_number_verified ==
'true'`. Anything else raises `CustomerNotAuthorized`.

Call sites, **re-derived at `061b6e77`** with `git grep -n "verified_identity" origin/stack -- amplify`
(this table was stale in two ways — see the notes):

| Caller of `catalog_service_checkout.verified_identity` (def `:35`) | Line |
|---|---|
| `flows/customer_commands.py` | `:84` (guard `:80`, refusal `:81`, `list_users` `:83`) |
| `flows/customer_orders.py` | **`:61`** (guard `:57`, `raise` `:58`, `list_users` `:60`) — **previously omitted** |
| `flows/catalog_services.py` | `:56` (`list_users` `:55`) |
| `ecommerce/checkout/handler.py` | **`:3081`** (owner check `:3076-3077`, refusal `:3078`, `list_users` `:3080`) — was cited `:3099` with `:3095-3096`/`:3098` |

**`flows/paid_submit_request.py` and `flows/paid_vault.py` do NOT call `verified_identity`** — the
previous rows (`:84-102`, `:141-150`, `:43-62`) were wrong; `git grep` returns no match in either
file. Those three sites run their **own inline** check, `if len(users) != 1 or not
users[0].get('Enabled', True)`, at `paid_submit_request.py:91`, `:143` and `paid_vault.py:70`. That is
weaker than `verified_identity` — it omits the business-sender refusal, the soft-delete test, the
phone round-trip and the `sub`/`phone_number_verified` re-derivation. Recorded as an observation; they
are live paid paths and tightening them is outside this pass's scope.

Three corollaries the hub must respect.

**Server-side fetch only.** Private data is read from the authoritative store *after* the identity
check, never from a handset-submitted Flow field. The existing code already does this:
`flows/catalog_services.py:46` reads the contact with `ConsistentRead=True` and never trusts an id
from the payload, and `docs/kiro-handoff.md` records the same rule for the review Flow ("Trusted
webhook sender resolves the contact, never handset-supplied IDs").

**Internal entry points refuse HTTP shaping.** `flows/customer_commands.py:70-71` and
`flows/catalog_services.py:40-41` both return `403 Internal invocation required` when the event
carries `requestContext` / `rawPath` / `path` / `httpMethod`. Any new hub arm must do the same, in
its own first statement.

**Phone-only adoption is now refused repository-wide — except at one surviving site.** Commit
`724dcc38` on `origin/stack` changed `vault_access.bind_file:16` from
`ownerCustomerId not in (None, identity.customer_id)` to
`not identity.customer_id or row.get('ownerCustomerId') != identity.customer_id`, and tightened
its `ConditionExpression` to a bare `ownerCustomerId=:owner`. The same commit applied the
equivalent tightening across `core/secure-files/handler.py`. The **only** remaining
`in (None, …)` ownership acceptance in `amplify/` is
`flows/catalog_services.py:94` — verified by
`git grep -n "ownerCustomerId') in (None" origin/stack -- amplify`, which returns exactly that one
line. Closing it is design item **F-3**.

---

## 2. Reuse before creation — the recommendation is reuse

Three existing resources were evaluated as the main entry point.

1. **Keyword routing** — `src/config/whatsappServiceEntries.ts` (eight keyword entries, with
   `whatsappKeywordLink` at `:14-15` building `https://wa.me/919330994400?text=<keyword>`) plus
   `flows/customer_commands.command` and the inbound handler's keyword block. Already live,
   already identity-gated, needs no Meta approval, and already covers `Orders`, `Orders page N`,
   `Customer ID` and all six service doors. **This is the recommended main entry point today.**
   The gap is discoverability, not capability.

   Using the business number `+919330994400` as the deep-link *target* is correct: the customer
   initiates to the business. It is never used as a customer identity, and must not be.

2. **An interactive list/button menu** from the inbound handler. Already supported — the handler
   has list-reply and button-reply routes and a `request_welcome` menu — and needs **no new Flow**.
   **Recommended as the discoverability layer**: one `Menu` / `Help` keyword returning an
   interactive list of the ten destinations. This is the smallest change that produces a "home".

3. **`WD_Leave_Review_v2` (`1578178897413815`)** — **rejected as a host.** It is a published
   review Flow with its own schema and `ReviewTable` semantics; overloading it would couple
   unrelated journeys and put a published customer-facing asset at risk.

**A new Flow is NOT yet warranted.** It becomes warranted only when a journey needs multi-screen
state an interactive list cannot carry — the Orders selector in §4 is the first genuine candidate.
If the owner later approves, the candidate name is **`WD_Customer_Service_Hub_v1`**. Named for
planning only; nothing in this plan creates, uploads or publishes it.

A **staff** "Customer Service Hub" already exists at `/workspace/forms/selfservice`
(`src/config/navigation.ts:167`) with per-topic `wa.me/message/...` short links. It is an internal
operator page, not a customer-facing hub, and must not be confused with this design.

### Recommended menu

```
Profile · Orders · Submit Request · Request Amendment · Drop Docs
Vault · Shipments · Invoices & Receipts · Leave Review · Contact Support
```

### Navigation contract, binding on whichever surface hosts it

- Every arm re-runs `verified_identity` on its own. The menu carries **no** identity assertion
  between turns and nothing is cached across messages.
- Unverified callers get exactly one reply: the sign-in link
  `https://wecare.digital/account/sign-in/`, as `flows/customer_commands.py:81` already does.
- Arms whose feature is gated return their existing disabled outcome
  (`NATIVE_SERVICE_ROLLOUT_DISABLED` from `flows/catalog_services.py:43`, `VAULT_FILE_NOT_READY`)
  rather than a generic error. A customer must not be offered something the gate will refuse.
- The menu is sent only inside the 24-hour window or as an approved template. Outside it the
  existing `AWAITING_CUSTOMER_MESSAGE` behaviour stands
  (`flows/paid_submit_request.py:160-161`): no unapproved invitation, and no substitution of a
  different template.

---

## 3. Profile in WhatsApp — privacy decision (D5)

Source of truth is the backend contact row plus Cognito, read **after** `verified_identity`. No
field is ever taken from a handset-submitted Flow payload.

| Field | Decision | Justification |
|---|---|---|
| Customer ID (public UUID) | **Fully displayed** | Already live and intended for customer use; printed on invoices. It is neither the Cognito subject nor the row `id` (which is a `uuid5` of the subject and deliberately unpublishable — `auth/customer-profile/handler.py:291-295`). |
| Name | **Fully displayed** | Low sensitivity; the customer supplied it, and WhatsApp already shows their own profile name. |
| Email | **Partially masked** — `f••••@domain.tld` | Chat history is readable by anyone holding the handset. Masking answers "is this the right account?" without re-disclosing a credential-recovery identifier. |
| Phone | **Confirmation-only** — last 4 digits | It is the channel itself; echoing it in full adds nothing and widens the blast radius of a shared or lost device. |
| Billing / shipping address | **Confirmation-only** — city + PIN, never the full address | Per explicit instruction: do not dump a full address into a chat message. Full address on the authenticated page only. |
| Account status | **Fully displayed** | Non-sensitive and operationally useful (verified / unverified / needs profile). |
| Any field — **edit** | **WEB ONLY** | Identity mutation with no second factor. `auth/customer-profile/handler.py` is the sole writer of `checkoutCustomerId`; a chat-driven edit would mutate identity bindings from an unauthenticated surface. Commit `e006b5f3` hardened this further: `_owned_contact` now returns a row only when `checkoutCustomerId == customer_id`, `_upsert_contact` raises `CONTACT_IDENTITY_CONFLICT` on a mismatch, and the update carries `ConditionExpression="attribute_exists(id) AND checkoutCustomerId=:customer"`. Every edit arm therefore replies with a deep link to the authenticated page. |

**Flow screens vs plain chat, decided.** Flow screens are **safer for input**, because the data
travels through Meta's encrypted Flow endpoint rather than sitting in the thread, and the endpoint
is already wired (`FLOW_PRIVATE_KEY_SECRET` / `FLOW_PRIVATE_KEY_PASSPHRASE` on live
`wecare-whatsapp-business-api`; endpoint `https://wecare.digital/api/wa-business/flow-data`, the
single member of `AUTH_SKIP_PATHS` because RSA+AES-GCM decryption is itself the authentication —
`messaging/whatsapp-business-api/handler.py:5981-6000`). They are **not safer for display**: a Flow
screen still renders on the handset and its contents are not durable protection.

So: **Flow screens for anything the customer types; masked chat text for anything we display; the
authenticated website for anything unmasked.** That is why profile *view* is chat-with-masking and
profile *edit* is web-only rather than a Flow.

---

## 4. Orders Flow design — candidate `WD_Orders_v1` (NOT created) (D6)

Today's `Orders` keyword returns a flat text page of public order numbers
(`flows/customer_commands.reply`), with no per-order actions. A multi-screen selector is the first
genuine case for a Flow.

**Screens.** `My Orders` (paginated list) → select → `Order Detail` → action.

**The list screen** must reuse `flows/customer_commands.order_page` unchanged: customer-partition
query on `customerId-createdAt-index`, `Limit: 10`, forward-paged by repeated query with
`ExclusiveStartKey` (never a scan), a 10-page ceiling, public order numbers only, internal-UUID
fallback explicitly refused. Beyond page 10 the reply is the authenticated-website link, as it is
now (`:61-64`).

### Per-order actions, gated on actual order and service state

This is the part that must be **state-driven rather than always-on**.

| Action | Shown only when | Enforcement |
|---|---|---|
| View detail | always | summary fields only; full detail → web |
| Get / resend invoice | an invoice exists for the order | reuse the authoritative invoice; **never** mint a second — `payments/invoice-engine/handler.py:843-852` consumes a GST sequence on creation. Resend is claimed per channel (`INVOICEDELIVERY#<invoiceId>#whatsapp`) |
| Get receipt | payment is confirmed paid | same artifact as above |
| **Pay** | **the order is genuinely unpaid** | read the authoritative order/payment row; a `PAYMENT_PAID` order must **never** show Pay. The monotonic rank guard (`payment_status.condition_expression()`, used at `payments/razorpay-webhook/handler.py:2027-2031`) means a stale read cannot resurrect an unpaid state |
| Submit request | the order exists and is owned | the new service order must not become the parent — `ecommerce/paid_submit_request.list_orders:91` already excludes `row['orderId']` |
| Request amendment | amendment Flow published | Flow `3678132465672138` is DRAFT with an unrepaired legacy phone lookup → action **hidden**, not shown-and-failing |
| Upload documents | Drop Docs enabled | `DROPDOCS_ATTACH_ENABLED='false'` on live `wecare-secure-files` → hidden |
| Open Vault | the customer holds a Vault entitlement for a file on this order | **F-3**'s `ownerCustomerId == identity.customer_id` is the test. No entitlement → the action **does not exist**, not "exists and refuses" |
| Track shipment | a shipment record exists | utility; no SKU, no price |
| Leave review | service delivered and not already invited | must consult the same claim **F-2** unifies, or it reintroduces R-1 |
| Contact support | always | free text to a human. Note `STANDBY_REPLY_ENABLED='false'` on live `wecare-inbound-whatsapp`: standby messages are stored as context but not auto-replied |

### Identifier discipline

The Flow's internal navigation may carry the internal `orderId` as an opaque token, because the
Flow payload is server-verified on every turn — but it must never be **displayed**. The display
label is always the public order number. **F-6** makes `list_orders` agree with `order_page` on
this. The internal UUID ↔ public order number ↔ `customerUuid` relationships stay intact in the
backend and are never surfaced together in one customer message.

### Testability

The list query, the action-gating predicate and the label rules are pure functions over a fake
table and are unit-testable with no network — the same shape `tests/test_graft_money_correctness.py`
already uses (a rig whose `_lambda_client` raises on any call), and the same shape
`tests/test_meta_catalog_sync_handler.py` uses via its `run(wix, graph, reader)` helper at
`:180-184`. Only the Flow render and the Meta round-trip are integration-level, and neither can be
exercised without the owner's QA recipient. That split is exactly why this design puts all gating
logic in a pure predicate rather than inside the Flow JSON.

---

## 5. Feasibility verdict

**Mostly WhatsApp-native with secure web fallbacks. Not fully WhatsApp-native, and the blockers
are structural rather than schedule.**

Four reasons, each grounded in current code or current provider behaviour.

1. **Authentication cannot move.** Cognito hosted sign-in and phone verification are the root of
   `verified_identity`, and the one write that links a WhatsApp contact to a customer
   (`checkoutCustomerId`) happens only on an authenticated profile save — now additionally
   conditional on already owning the row (`e006b5f3`). A WhatsApp-only customer can never become
   verified. That is a correct design, and it means the website is load-bearing, not legacy.
2. **Documents and full addresses must stay off the thread.** Signed-URL delivery with short TTLs
   through an authenticated page is strictly safer than any chat-resident link, and the tree has
   just moved further in that direction: `724dcc38` reduced the WhatsApp link TTL from a 6-hour
   default to `max(60, min(900, …))` — a hard 15-minute ceiling — with the rationale "direct links
   are bearer capabilities". The website already validates `isSignedHttpsUrl` before DOM insertion
   (`src/pages/orders.tsx:299`).
3. **The 24-hour window and template approval are provider-controlled.** The handler already
   returns `AWAITING_CUSTOMER_MESSAGE` outside the window and refuses to substitute another
   template. Recovery for a customer outside the window is the website. There is no WhatsApp-only
   recovery path, and inventing one would mean sending unapproved content.
4. **Four of the six service doors are not natively available today.** Request Amendment
   (`3678132465672138`) and Drop Docs (`1211063631104445`) are DRAFT with an unrepaired legacy
   lookup; Submit Request and Vault are gated behind `WHATSAPP_CATALOG_SERVICES_ENABLED` with
   their catalog items forced out of stock (`META_CATALOG_SYNC_FORCE_OUT_OF_STOCK=true` on live
   `wecare-meta-catalog-sync` v7).

**No website functionality is recommended for removal.** Every WhatsApp path above is additive.
Removal would require proven equivalent security, reliability *and recovery*, and recovery is the
leg WhatsApp cannot match: a 24-hour messaging window, template approval dependencies and
provider-side enforcement are failure modes the website does not have.

### Embedded Flow-payment: NOT supported, and not claimed

The repository implements the historical, approved pattern and nothing else. Traced end to end:
`flows/catalog_services.py` (service selection from a catalog message) →
`catalog_service_checkout.py:78-88` builds an **order-details** payload with
`payment_settings: [{type: 'payment_gateway', payment_gateway: {type: 'razorpay',
configuration_name: …, razorpay: {receipt: reference_id, notes: {referenceId, source}}}}]` and a
15-minute `order.expiration` → the approved `wecarepay_wa` template (APPROVED, image header,
**ORDER_DETAILS button**) → customer Review & Pay → provider confirm via the signature-verified
`razorpay-webhook` → the paid Flow invitation.

There is no in-Flow payment component anywhere in the tree. Any claim of embedded Flow-payment
would be unfounded, and whether the account could support it is
**NOT VERIFIED — requires a Meta component/payment-capability read the owner must perform.**

---

## 6. Vault order + download message sequence (owner requirement, added revision 3)

**Citation base: `origin/stack` `e9e377ce`.** Every line below was re-derived with
`git grep -n <pattern> origin/stack -- <path>` at that commit. This section documents the
**intended and actual** flow. It enables nothing: `WHATSAPP_CATALOG_SERVICES_ENABLED`,
`VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED`, `SECURE_FILES_PAYMENT_ENABLED` and
`DROPDOCS_ATTACH_ENABLED` all stay closed. Live values read 2026-10-09T04:39:21Z:
`SECURE_FILES_PAYMENT_ENABLED=false`, `DROPDOCS_ATTACH_ENABLED=false`.

There are **two** Vault delivery paths in the tree, and they are not variants of one design. They
have different senders, different ownership checks, different link lifetimes and different
failure postures. Conflating them is the main reason prior handoffs disagreed about Vault.

| | Path A — native WhatsApp Vault | Path B — web / secure-files Vault |
|---|---|---|
| Entry | catalog service message → `flows/catalog_services.py` | `wecare.digital/vault/` page + `/whatsapp-pay` |
| Sender | `flows/paid_vault.py` → `wecare-outbound-whatsapp:live` | `core/secure-files/handler.py` → `whatsapp_delivery` |
| Gate | `WHATSAPP_CATALOG_SERVICES_ENABLED` (`catalog_services.py:42`) — **absent, so latent** | `SECURE_FILES_PAYMENT_ENABLED` — **`false` live** |
| Deployed in | `wecare-whatsapp-business-api` (live **89**) | `wecare-secure-files` (live **34**) |

### 6.1 Order confirmation → download template: the actual ordering and guards

**Path A, `amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py`.** The whole
function is 114 lines and the sequence is strictly linear; each step returns a distinct outcome
rather than continuing on failure.

**Precondition — the grant must exist before any message is sent.** `prepare_and_send` (`:60`)
calls `vault_access.grant_access(...)` at `:63-64` as its **first** action and returns
`VAULT_ACCESS_UNAVAILABLE` at `:66` when it yields nothing. So there is no state in which a Vault
message is sent before a file-access grant exists. Payment verification is upstream of this:
`grant_access` is reached only from the paid branch, and its own transaction carries
`ConditionExpression='ownerCustomerId=:owner AND #s=:active'`
(`shared/lambda_utils/ecommerce/vault_access.py:71`) plus the
`file.get('ownerCustomerId') != row.get('customerId')` refusal at `:51-52`.

**Identity re-verification, between the grant and the first send** (`:68-86`) — five independent
conditions, any of which stops the sequence:

| Line | Condition | Outcome on failure |
|---|---|---|
| `:68-69` | Cognito `list_users` by `Filter='sub = "' + row['customerId'] + '"'`, `Limit=2` | — |
| `:70` | exactly **one** user, and `Enabled` | `VERIFIED_RECIPIENT_UNAVAILABLE` (`:71`) |
| `:74` | `phone_number_verified == 'true'` **and** `phone == '+' + grant['ownerPhone']` | `VERIFIED_RECIPIENT_UNAVAILABLE` (`:75`) |
| `:77-84` | `ContactsTable` `phone-index` query, then a per-row `ConsistentRead=True` re-read requiring `checkoutCustomerId == row['customerId']` and not deleted | — |
| `:85` | exactly **one** surviving contact | `CONTACT_LINK_UNAVAILABLE` (`:86`) |

`:68-69` is one of the five unguarded `Filter='sub` concatenation sites — design item **F-4**.

**Message 1 — the Vault "ready" / order message** (`:88-97`). The base payload is built at
`:88-90` with `isTemplate: True`, `phoneNumberId: '1016149501586345'` and an image header
(`HEADER_IMAGE`, `:10`). Then:

```python
ready = dict(base, templateName='wecare_share_pdf')                                    # :91
# Enable only after live Meta readback confirms this exact template is approved.        # :92
if os.environ.get('VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED', 'false').lower() == 'true':  # :93
    ready = dict(base, templateName='wecare_default_download',                          # :94
                 templateUrlButton={'index': 0, 'suffix': file['fileId']})              # :95
if not _send_once(requests, row, 'vaultNotificationStatus', lambda_client, ready):      # :96
    return {'outcome': 'VAULT_NOTIFICATION_PENDING'}                                    # :97
```

**This is the single most important fact in this section, and it contradicts the usual description
of the flow.** With `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` absent — which it is — the customer
receives **`wecare_share_pdf`**, whose header is an IMAGE and which carries **no URL button and no
file parameter**. The `wecare_default_download` template and its
`https://wecare.digital/vault/?file={{1}}` button are **not sent at all on Path A today**. So the
sequence is not "order message, then download template"; it is "one share template, then possibly
an attachment". The download-template message is designed, wired and gated off.

The template is nonetheless *required to be approved* before native checkout may proceed:
`shared/lambda_utils/ecommerce/catalog_service_checkout.py:91-106` (`meta_ready`) demands all three
of `wecarepay_wa`, `wecare_leave_review`, `wecare_default_download` be `APPROVED` and `en` (`:93-96`),
and specifically that the download template's first button be `type: 'URL'` with
`url == 'https://wecare.digital/vault/?file={{1}}'` (`:98-101`). That is a coherent fail-closed
staging posture — readiness is proven before the flag opens — but it means readiness and use are
decoupled, and only readiness is currently true.

**Message 2 — the PDF attachment, conditional on the 24-hour window** (`:100-109`):

```python
last = contact.get('lastInboundMessageAt', 0)                                            # :100
if file.get('deliverable') == 'pdf' and file.get('deliveryKey') \
        and 0 <= time.time() - float(last or 0) < 86400:                                 # :103
    ...
    if not _send_once(requests, row, 'vaultDocumentStatus', lambda_client, document):    # :108
        return {'outcome': 'VAULT_DOCUMENT_PENDING'}                                     # :109
```

An attachment is an ordinary (non-template) message, so it is only permissible inside the 24-hour
customer-service window — `86400` at `:103` is that window, measured from
`contact.lastInboundMessageAt`. The comment at `:98-99` records why it must be separate: the
approved share template has an IMAGE header and cannot carry the document itself. **Consequence:
if the customer has not messaged in 24 hours, Message 2 does not happen either** — and with the
download-template flag off, the customer has then paid and received a template with neither a link
nor a file. See GAP **V-2**.

**Message 3 — the review invitation** (`:110-112`), `wecare_leave_review` with a Flow button,
claimed under `vaultReviewStatus`, returning `VAULT_READY` or `VAULT_REVIEW_PENDING` (`:113-114`).
This is one of the three review senders design item **F-2** de-duplicates.

**Ordering is enforced by early return, and each send is claimed exactly once.** `_send_once`
(`:13-57`) is the mechanism: it reads the claim with `ConsistentRead=True` (`:15`), returns
immediately if already `ACCEPTED` (`:16-17`), refuses to retry an uncertain or exhausted send
(`:21-24`, three attempts, 30-second backoff at `:55`), and takes the claim with
`ConditionExpression='attribute_not_exists(<key>)'` (`:25`) or a `SEND_REJECTED`-to-retry
transition (`:28-29`). A `ConditionalCheckFailedException` returns `False` rather than raising
(`:35-36`). On the outbound invoke (`:40-41`) only `2xx` becomes `ACCEPTED` (`:45-46`); the
enumerated client errors become `SEND_REJECTED` (`:47-48`); **anything else stays `SEND_UNKNOWN`**,
with the comment at `:49-51`: "Failure may occur after Meta accepted the message. Never blindly
retry it." That is the correct posture for a money-adjacent send and must not be relaxed.

**Path B, `amplify/functions/core/secure-files/handler.py`.** Delivery is at `:1358-1379`.
Ownership is re-checked **before** any URL is generated — `status == 'active'` (`:1358`),
`ownerPhone` agreement between file and grant (`:1360`), and positive permanent-owner agreement
`not grant.get('customerId') or item.get('ownerCustomerId') != grant['customerId']` (`:1362-1363`,
the `724dcc38` tightening). Then a `pdf`/`image` goes as an inline document via `send_document`
(`:1368-1369`); anything else goes as a link via `send_download_link` with
`_download_url(item, ttl=WHATSAPP_LINK_TTL)` (`:1375-1379`). The outcome is recorded **on the
grant** (`:1384-1392`, `delivered` / `deliveryDetail` / `deliveryAttemptedAt` / `ADD
deliveryAttempts`) so an undelivered paid file is findable; `scripts/reconcile_file_deliveries.py`
sweeps exactly those attributes (`:1381-1383`).

### 6.2 File origin: private S3 object, ownership-checked before any signed URL

The document is served from S3 and the link is time-limited. The object is private from the first
write, and **authorization is established before a URL is minted, not by the URL**.

`_download_url` (`:1240-1257`) is the only presigner on the download side:

```python
return _s3_client().generate_presigned_url(
    "get_object",
    Params={"Bucket": BUCKET, "Key": item["s3Key"],
            "ResponseContentDisposition":
                f'attachment; filename="{item.get("originalFilename", "download")}"'},   # :1252-1254
    ExpiresIn=int(ttl or DOWNLOAD_URL_TTL),                                              # :1256
)
```

`ResponseContentDisposition` is why the file arrives under its readable name rather than the opaque
key (`:1241`, `:1465`).

**The actual TTL constants** (`:212-219`) — and a live/source conflict:

| Constant | Line | Code default | Live value (v34, read 04:39:21Z) | Effective |
|---|---|---|---|---|
| `UPLOAD_URL_TTL` | `:213` | 900 | `UPLOAD_URL_TTL_SECONDS=900` | 900 s |
| `DOWNLOAD_URL_TTL` | `:215` | **60** | `DOWNLOAD_URL_TTL_SECONDS=60` | **60 s** |
| `WHATSAPP_LINK_TTL` | `:218` | `max(60, min(900, 900))` | `WHATSAPP_LINK_TTL_SECONDS=`**`21600`** | **900 s** (clamped) |
| `GRANT_TTL` | `:219` | 1800 | `GRANT_TTL_SECONDS=1800` | 1800 s |

Two things to record rather than gloss:

1. **The "300 seconds" figure in prior handoff material is not in the code and not in the live
   environment.** The web redeem TTL is **60** seconds — `:214` explains why: "Web redeem: the
   browser follows this immediately, so it can be very short." The WhatsApp link TTL is **900**
   seconds, with the rationale at `:216-217`. **Conflict recorded; the code and live env agree with
   each other and disagree with the prose.**
2. **Live `WHATSAPP_LINK_TTL_SECONDS` is `21600` (6 hours) and is silently clamped to 900 by the
   `max(60, min(900, …))` at `:218`.** Behaviour is safe — the clamp is the `724dcc38` hardening —
   but an operator reading the environment would conclude the bearer window is six hours when it is
   fifteen minutes. See GAP **V-3**.

**Ownership precedes the URL, in all three callers.** `_owned_active_file` (`:948-960`) is the
gate, and it is positive-attribution only:

```python
if item.get("ownerPhone") != identity["phone"]: return None                              # :956-957
if not identity.get('subject') or item.get('ownerCustomerId') != identity['subject']:    # :958
    return None                                                                          # :959
```

Its docstring states the discipline that makes it safe to expose: "Every failure mode returns None
so callers cannot tell them apart" (`:951`). A caller therefore cannot distinguish "no such file"
from "not yours". `_redeem` calls it at `:1417` **before** touching the grant, and additionally
requires `grant.get('customerId') == identity['subject']` at `:1421`. `_customer_list` applies the
same three conditions per row after a `ConsistentRead=True` re-read (`:926-929`), so a GSI
projection can never widen the result set.

**Knowledge of a file ID is not authorization, and a signed URL is not the access control.** Both
statements are true of this code: the file id is the path parameter and is useless without a
Cognito session whose `sub` equals `ownerCustomerId`; and the presigned URL is minted only on the
far side of `_owned_active_file`. The URL *is* a bearer capability once minted — `:216` says so
("Direct links are bearer capabilities") — which is why the window is bounded and why `consumed` is
flipped on redeem.

### 6.3 Customer delay and link expiry — the real gap

The code states an intent at `:216-217`: *"a customer can use authenticated Vault access after the
delivery link expires."* **That intent is only half-true against the current code.** Two cases
behave very differently, and only the first works.

**Case 1 — the WhatsApp link expires, grant NOT consumed. Recoverable, no second charge.**
Delivery deliberately does not spend the grant. The comment at `:1371-1374` is explicit:
*"Generated here rather than reusing the redeem route so delivery does not consume the grant the
customer may still redeem on the web."* So after the 900-second link dies, `GET /files/mine`
(`:1800-1804` → `_customer_list`) still surfaces the grant, because `:933` requires
`grant.get('paid') and not grant.get('consumed')` and sets `view['paidGrantId']` and
`deliveryStatus: 'READY'` (`:934-935`). The customer redeems once on the web via
`GET /files/{id}/download?grant=…` (`:1835-1836` → `_redeem`). **This path is correct.**

**Case 2 — the grant was consumed and the 60-second presigned URL then expired.
NOT recoverable. The product tells a customer who has already paid to pay again.** GAP **V-1**.

`_redeem` is single-use by construction (`:1405-1441`). The conditional update requires
`consumed = :false` and sets `consumed = True`:

```python
ConditionExpression=("attribute_exists(grantId) AND fileId = :fid AND ownerPhone = :p "
                     "AND customerId = :owner AND paid = :true AND consumed = :false")   # :1428-1431
```

with the rationale at `:1408-1410`: *"it flips `consumed` only if it is currently false, so two
concurrent requests cannot both win and a forwarded link is dead on second use."* On the
`ConditionalCheckFailedException` arm it first tries `_reconcile_grant` (`:1453`, which asks
Razorpay directly for the never-arrived-webhook case — a genuinely good recovery), and otherwise
returns:

```python
return cors_response(403, {"error": "GRANT_NOT_REDEEMABLE",
    "message": "This download link is not valid. Please pay again to download."}, origin)  # :1456-1462
```

And `_customer_list:933` no longer offers a `paidGrantId` once `consumed` is true, so the UI has
nothing to retry with. The only remaining route is `_create_order` (`:963`), **a second ₹49
charge** — and its own docstring (`:966-972`) frames it as the recovery path for "a customer who
has already paid [to] collect a file when WhatsApp delivery keeps failing", which is exactly the
situation in which charging again is wrong.

Sixty seconds is a narrow window for a mobile download. A suspended tab, a tunnel, or a user who
taps and then reads a message is enough to lose it.

**Root cause.** `consumed` is doing two jobs: (a) defeating a **forwarded** link used by a third
party, and (b) capping the **owner's own** re-downloads. Job (a) is essential. Job (b) is an
accident of sharing one flag. A forwarded link carries no Cognito session, so it can never satisfy
`_owned_active_file` (`:948-960`) or `grant['customerId'] == identity['subject']` (`:1421`) — which
means re-issuing to the **authenticated owner** does not weaken the forwarded-link defence at all.

### 6.4 Catalog description and availability stay current through Wix → AWS → Meta

The Vault catalog item's name, description, price, image and availability are not maintained by
hand. They are projected from Wix:

Wix product change → `wix.stores.catalog.v3.product_updated` webhook → `wecare-wix-catalog-webhook`
(live **9**) verifies the signature and invokes `wecare-meta-catalog-sync:live` →
`meta_catalog_sync.desired_items` builds the Meta payload → `diff` → `items_batch`.

Independently verified from CloudWatch, `/aws/lambda/wecare-wix-catalog-webhook`, read
2026-10-09T04:36:35Z — the chain works and is signature-verified:

```
00:21:58.206Z {"event":"wix_webhook_verified","eventType":"wix.stores.catalog.v3.product_updated", …}
00:21:58.927Z {"event":"meta_catalog_sync_invoked","function":"wecare-meta-catalog-sync:live", …}
```

The join key is identical on both sides, which is what makes the projection and the browser
tracking events refer to the same object: `meta_catalog_sync.retailer_id` builds
`wix:<productId>:<variantId>` lowercased (`:182-205`, `RETAILER_PREFIX` at `:50`, assembly at
`:199`), `catalog_service_checkout.payment_details` builds `'wix:' + row['productId'] + ':' +
row['variantId']` for the order-details line (`:73`), and the browser builds
`wix:${SERVICES_PRODUCT_ID}:${variantId}` (`src/lib/metaCatalogAnalytics.ts:64-67`).

**Availability is force-held out of stock while the gates are shut.** Live
`wecare-meta-catalog-sync` v7 (read 2026-10-09T04:36:05Z) carries
`META_CATALOG_SYNC_FORCE_OUT_OF_STOCK=true`, applied at `handler.py:550-552`, so every desired item
is published `availability: out of stock` until the owner opens the rollout. The staged proposal in
`docs/whatsapp/service-flow-drafts/catalog-proposals-20261009.json` confirms it: all four items,
including Vault at `price: "49.00"`, carry `"availability": "out of stock"`.

**A vanished item is retired, never deleted** — `meta_catalog_sync.diff` has no delete path at all.
The guarantee is declared in its docstring at `:562-567` ("A VANISHED WIX VARIANT IS RETIRED, NEVER
DELETED… There is no code path in this module that can produce a delete, which is a structural
guarantee rather than a convention") and enforced by the retire loop at `:606-620`, which only ever
appends `{"retailer_id", "availability": OUT_OF_STOCK, "product_name"}`. The reason is a Vault
customer's in-flight cart: it holds a `product_retailer_id`, and a deleted item fails at checkout
rather than at browse time.

**Cross-reference — this pipeline's write half is currently blocked, for an external reason.** The
sync's Meta read failed continuously from 2026-10-09T00:21:01Z against catalog
`1607047307067517`, independently confirmed in CloudWatch (see `answers.md` **G**, **H**). The live
target has since moved to `1457045652952851`, which reads successfully and is **empty** — so today
the Vault catalog item's description and availability are *computed* correctly and *not yet
present* in the targeted catalog. Four `create` proposals are staged and unapplied
(`applied: 0`, `enabled: false`, `dryRun: true`). Nothing in this design applies them.

### 6.5 GAP register for the Vault sequence

Same contract as the `design.md` F-items: severity, smallest safe change, and the regression test
that fails first. **None of these is implemented in this phase.**

| ID | Gap | Severity | Live or latent |
|---|---|---|---|
| **V-1** | A paid customer whose grant is consumed and whose 60-second URL expired cannot re-download, and is told to pay again | **HIGH** | **LIVE via the native path.** `_redeem` (`secure-files/handler.py:1405`) is **not** gated by `_payment_enabled` (whose only four sites are `:981`, `:1058`, `:1156`, `:1272`), and the native minter `vault_access.grant_access` runs in `wecare-whatsapp-business-api` with no payment gate, writing **durable** grants with no `expiresAt` (`vault_access.py:64-67`). The gated `secure-files` origins are also affected but their grants are TTL-swept, so for them the residue is the `:1459-1460` copy alone. The identical string also exists at **`:1224-1225`** (`_redeem_after_reconcile`), unreachable while the flag is off but reachable the moment `design.md` §5 item 8 opens it — **both sites are in the copy fix** |
| **V-2** | With the download-template flag off, a native Vault purchase outside the 24-hour window yields neither a link nor a document | MEDIUM | latent (native gate shut) |
| **V-3** | Live `WHATSAPP_LINK_TTL_SECONDS=21600` is clamped to 900; environment and behaviour disagree by 23× | LOW | LIVE config, safe behaviour |

**V-1 — smallest safe change.** Separate the two jobs `consumed` is doing. Add a bounded,
authenticated **re-issue** that does not create a charge and does not weaken the forwarded-link
defence:

> **`design.md` F-9 is BINDING for this item. This section is subordinate to it and must not be
> implemented from on its own.** Review 3 finding 9 found this section disagreeing with `design.md`
> on the route shape and giving a cap condition that can never succeed on a first re-issue. Both are
> corrected below; where any residual difference remains, **`design.md` F-9 wins.**

- **One route shape: `GET /files/{id}/download?reissue=1`** — a `reissue=1` parameter on the
  **existing** `download` route. The previously-offered alternative `GET
  /files/{id}/download/reissue` is **deleted**; there is no separate route. Because the parameter
  leaves `tail` unchanged, the route lands in the existing customer block with no dispatcher edit.
- **Auth envelope, exactly:** inside the customer block at **`:1827-1836`**, via
  `_customer_identity(event)` at **`:1828`**, returning `401 "Verification required"` on `None` —
  the same envelope `_redeem` uses at `:1836`. **NOT `require_auth`.**
  `require_auth(event, "Operator")` at **`:1840`** is the **admin** surface and must not host this
  route; the handler's own docstring at `:40-44` records that `require_auth` validates against the
  **admin** pool and that customer routes must not use it.
- It calls `_owned_active_file(file_id, identity)` **first** (`:948-960`) and returns
  `_not_registered(origin)` on `None`, exactly as `_redeem` does at `:1417-1419`.
- **Entitlement comes from the durable FILE row, not the grant row:**
  `vaultPaymentStatus == 'PAID'` and `vaultAccessGrantId` present (written by `vault_access.py:71`
  onto `SecureFilesTable`, whose TTL is **DISABLED**). The grant row is TTL-swept for two of its
  three origins, so **a missing grant row is not evidence of non-payment.**
- **The cap and counter live on the FILE row**, cap **5**, in one atomic conditional update with
  `UpdateExpression='ADD reissueCount :one SET lastReissuedAt = :now'` and the condition including
  **`(attribute_not_exists(reissueCount) OR reissueCount < :cap)`**.

  > **The `OR attribute_not_exists` arm is mandatory.** This section previously specified
  > `ConditionExpression='reissueCount < :cap'` alone, which evaluates **false** on a row that has
  > never been re-issued — so the *first* re-issue, the only one that matters for the live
  > population, would always have been refused. `ADD` initialises a missing numeric attribute to the
  > operand, so no separate initialisation write is needed.

- **`ConditionalCheckFailedException` is mapped by re-reading the row** (`ConsistentRead=True`),
  first match wins: at cap → `GRANT_REISSUE_EXHAUSTED`; grant row present and **not** consumed →
  **fall through to `_redeem`** (so there stays exactly one way to first-redeem); otherwise →
  `_not_registered(origin)`.
- It mints `_download_url(item)` on the ordinary 60-second `DOWNLOAD_URL_TTL` (`:215`). **No TTL is
  created, lengthened or touched**, and `consumed` is never modified by this route.
- Correct the refusal copy at **`:1459-1460`** (`_redeem`) **and at `:1224-1225`
  (`_redeem_after_reconcile`, the identical string)** so a paid-and-consumed grant is never told to
  pay again. `:1225` is **not** live-reachable today — `_redeem_after_reconcile` is entered only when
  `_reconcile_grant` returns True (`:1453-1454`) and that function returns False while
  `_payment_enabled()` is false (`:1156-1157`) — but it becomes reachable the moment `design.md` §5
  item 8 opens the flag, and item 8 lists F-9 as satisfied. **Fixing one site and not the other would
  re-introduce the defect at the gate opening.** **This copy correction ships independently of the
  route.**
- `_customer_list:931-935` surfaces `deliveryStatus: 'REDEEMED_REISSUABLE'` when the file row is
  `PAID` and under the cap, so the UI has something to offer. It **must not** require the grant row
  to exist.

Why this is safe: no new ownership model, no IAM change, no weakening. The forwarded link still
dies on second use, because re-issue requires a Cognito session whose `sub` equals the file's
`ownerCustomerId`. No payment object is created, mutated or read. Fails closed in every arm.

**V-1 — failing regression tests** (`tests/test_vault_download_reissue.py`, **six** cases; the list
in `design.md` F-9 is authoritative):

1. `test_a_consumed_grant_can_be_reissued_to_the_owner_without_a_new_charge` — fake files/grants
   tables with an active file (`ownerCustomerId == identity['subject']`, `vaultPaymentStatus='PAID'`,
   `vaultAccessGrantId` set) and a `paid`, `consumed` grant; assert HTTP 200 with a `downloadUrl`,
   `expiresInSeconds == 60`, that `reissueCount` became 1, and that **no** Razorpay client method and
   no `_create_order` was called. **Fails today with 403 `GRANT_NOT_REDEEMABLE`.**
2. **`test_a_swept_grant_does_not_tell_a_paid_customer_to_pay_again`** — **the finding-2 case.**
   Same file row, **grants table empty** (the TTL sweep has removed the row). Assert HTTP 200 with a
   URL, and that the body contains neither `"pay again"` nor `GRANT_NOT_REDEEMABLE`. **Fails
   today.** This is the test that proves entitlement does not depend on a swept record.
3. **`test_the_first_reissue_succeeds_on_a_row_with_no_reissue_count`** — file row with **no**
   `reissueCount` attribute; assert HTTP 200. **Fails today**, and would have failed against this
   section's previous `reissueCount < :cap` condition even after the fix.
4. `test_reissue_is_refused_at_the_cap` — `reissueCount == 5`; assert `GRANT_REISSUE_EXHAUSTED` and
   that the body does **not** contain "pay again". Proves case 3's `OR` arm did not disable the bound.
5. `test_a_consumed_grant_is_never_reissued_to_a_different_customer` — same rows, a different
   `identity['subject']`; assert `_not_registered` and that `reissueCount` is unchanged.
   **Sensitivity proof — passes before and after.**
6. `test_the_forwarded_link_defence_survives` — call `_redeem` twice on a fresh unconsumed grant and
   assert the second is refused, unchanged, and that a caller with no session gets `401` /
   `_not_registered`. **Sensitivity proof — passes before and after.**

A change that makes case 5 or 6 fail is rejected regardless of the others: those two are what would
catch this fix becoming a loosening. (The former `test_an_unpaid_grant_is_never_reissued` is
subsumed — an unpaid file row fails the `vaultPaymentStatus = :paid` clause of the same single
condition, and is covered by the error table in `design.md` F-9.)

**V-2 — smallest safe change.** Two parts, neither of which opens a gate. (a) When
`VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` is off **and** the 24-hour window is shut, do not report
`VAULT_READY`: emit a distinct `VAULT_DELIVERY_DEFERRED` outcome and a count-only
`vault_delivery_deferred` log line, so the reconciliation sweep can find a paid customer who
received nothing actionable. (b) Record in `docs/whatsapp/native-catalog-release-status.md` that
opening the native Vault gate **requires** `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` in the same
change, because `wecare_share_pdf` carries no link — making it a documented precondition of
`design.md` §5 item 8 rather than a discovery made after the first live purchase.
Test: `test_a_paid_vault_purchase_outside_the_window_is_not_reported_ready` — `deliverable: 'pdf'`,
`deliveryKey` set, `lastInboundMessageAt` 25 hours old, flag off; assert the outcome is
`VAULT_DELIVERY_DEFERRED` and that exactly one template send occurred. Today it returns
`VAULT_READY` with no document sent.

**The reason enum needs a stated order**, because `paid_vault.py:103` is one compound condition and
the logged reason would otherwise be non-deterministic when two sub-conditions fail together.
**Binding, first match wins: `not_deliverable` → `no_delivery_key` → `window_closed`** — mirroring
`:103`'s own left-to-right evaluation, so the reported reason is the first clause that actually
failed. This makes the test's `reason == 'window_closed'` assertion deterministic rather than
accidental.

**V-3 — smallest safe change.** Set `WHATSAPP_LINK_TTL_SECONDS=900` on `wecare-secure-files` so the
environment states the effective value. This is an environment write on a production function —
`A3_PRODUCTION`, **OWNER CONFIRM (O10)**, and it publishes a version and moves the `live` alias, so
it is a deploy.

> **Mechanism, binding** (review 3 finding 11): run `scripts/set_lambda_env_flag.py` with
> **`--no-publish`** (`:71`, tested at `:145`) so it performs only the environment write, keeping its
> snapshot-before-write and post-write LOST check — then publish and move the alias **manually with
> `--revision-id`** plus an independent `get-alias` read-back. The script's own alias move at
> `:147-148` passes **no `RevisionId`**, so it cannot satisfy `design.md` §5's binding concurrency
> rule on a function whose live alias moved 31 → 34 during this audit.

Do **not** change the clamp at `:218`. Test:
`test_the_whatsapp_link_ttl_is_clamped_to_fifteen_minutes` — set the variable to `21600` and assert
the module constant resolves to `900`. Passes today; it pins the clamp against a future "fix" that
removes it.

**Owner / provider / engineering split for this section.** V-1 and V-2(a) are **engineering,
permitted** (no gate, no payment object, no weakening). V-2(b) and V-3 need **OWNER CONFIRM**
(a documentation decision and a production environment write). Confirming that
`wecare_default_download` is still APPROVED with the exact
`https://wecare.digital/vault/?file={{1}}` button is a **provider read** the owner must perform in
WhatsApp Manager — `meta_ready` enforces it at `catalog_service_checkout.py:98-101`, but nothing in
this audit has read Meta to confirm it. **NOT VERIFIED.**
