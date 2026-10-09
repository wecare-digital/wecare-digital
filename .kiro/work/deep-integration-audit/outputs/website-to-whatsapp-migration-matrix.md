# Website → WhatsApp migration matrix

Companion to `../design.md` §4 and `../answers.md`. Evidence-based; every "current" column cites
real source. Design/audit only — nothing here was built, enabled or published.

**Standing rule for this matrix.** A WhatsApp path is *additive*. No website action is recommended
for removal merely because a WhatsApp equivalent exists; removal requires proven equivalent
security, reliability **and recovery**, and the recovery leg is where WhatsApp cannot currently
match the website (24-hour messaging window, template approval, provider-side enforcement).

Identity requirement vocabulary:

- **VERIFIED** — `catalog_service_checkout.verified_identity` must pass: contact
  `checkoutCustomerId` present, exactly one `Enabled` Cognito user in `us-east-1_46ULYuukt` whose
  `sub` equals it, `phone_number` equal to the normalised sender, `phone_number_verified == 'true'`,
  contact not soft-deleted, contact `phone` matching, sender not the business number.
- **COGNITO SESSION** — an authenticated website session.
- **NONE** — public.

Implementation state vocabulary: **LIVE** / **BUILT-GATED** (code exists, flag closed) /
**DRAFT** (Meta asset not published) / **NOT BUILT**.

---

| Current website action | Current backend / API | Current WhatsApp capability | Required Flow / template / message | Identity requirement | Security risk | Payment requirement | Recommended destination | Implementation state |
|---|---|---|---|---|---|---|---|---|
| **Sign in** — `src/pages/account/sign-in.tsx`; linked from `src/pages/orders.tsx:680` | Cognito customer pool `us-east-1_46ULYuukt` | None, and none possible | Link only — no Flow | COGNITO SESSION | Moving auth into chat would remove the only phone-verification root `verified_identity` depends on | — | **WEBSITE ONLY** | LIVE |
| **Link WhatsApp ↔ customer** (profile save) | `POST /customer/profile` → `auth/customer-profile/handler.py:287-289` writes `checkoutCustomerId` | None | Link only | COGNITO SESSION | **Must never be writable from chat.** Writing this attribute from an unauthenticated surface would forge the exact proof `verified_identity` exists to establish | — | **WEBSITE ONLY** | LIVE |
| **Customer ID** (public UUID) | `customer_uuid.ATTRIBUTE`, minted once via `if_not_exists` at `customer-profile/handler.py:290-296` | `Customer ID` keyword → `flows/customer_commands.reply` → `customer_uuid.from_contact` | Plain text reply | VERIFIED | Low. Returns the stored public UUID; never mints one, never exposes the Cognito subject or the `uuid5` row id | — | **WHATSAPP NATIVE** | LIVE |
| **Orders list** | `src/pages/orders.tsx:62` → `GET /ecommerce/my-orders` | `Orders` / `Orders page N` → `customer_commands.order_page` | Plain text; interactive list once `WD_Orders_v1` exists | VERIFIED | Low. Customer-partition query on `customerId-createdAt-index`, 10 rows/page, 10-page ceiling, no scan, public order numbers only, internal UUID fallback explicitly refused | — | **WHATSAPP NATIVE** | LIVE |
| **Order detail** | same endpoint, rendered client-side | None per-order today | `WD_Orders_v1` Order Detail screen (**not created**) | VERIFIED | Full line items, addresses and tax breakdown in a thread is persistent private data on the handset | — | **WHATSAPP + SECURE WEB FALLBACK** — summary in chat, full detail on the authenticated page | NOT BUILT |
| **Payment status** | order row status; workspace maps `PAYMENT_PAID` → paid | None | Status label in Order Detail | VERIFIED | Low if label-only. Must read the authoritative row, not a cached projection | — | **WHATSAPP NATIVE** | NOT BUILT |
| **Invoice / receipt download** | `orders.tsx:479` `downloadInvoice` → `:262` `fetchInvoiceUrl` → `GET /ecommerce/my-invoice`; URL checked by `isSignedHttpsUrl` at `:299` before `createElement` | WhatsApp document send exists on the paid path: `razorpay-webhook/handler.py:2440-2470`, claimed `INVOICEDELIVERY#<invoiceId>#whatsapp` | Document message; `wecarepay_wa` already APPROVED for the pay step | VERIFIED | **Must reuse the authoritative invoice.** Creation consumes a GST sequence (`invoice-engine/handler.py:829-852`); a second artifact is a compliance defect, not a duplicate message | Paid | **WHATSAPP + SECURE WEB FALLBACK** | LIVE (send) / web for retrieval |
| **Profile view** — name, email, phone, address, status | contact row + Cognito, read server-side | None | Masked plain text (see `../design.md` §4.5) | VERIFIED | Full address or full email in a thread is avoidable disclosure; the instruction is explicit — do not dump a full address into a chat message | — | **WHATSAPP + SECURE WEB FALLBACK**, masked | NOT BUILT |
| **Profile edit** | `POST /customer/profile` | None | — | COGNITO SESSION | Identity mutation with no second factor; the same handler writes `checkoutCustomerId` and the public UUID | — | **WEBSITE ONLY** | LIVE |
| **Address add / edit** | `contact_address.ATTRIBUTE`; a supplied address overwrites wholesale, no partial merge (`customer-profile/handler.py:280-285`) | None | — | COGNITO SESSION | "A half-merged address is a wrong place of supply" — the handler's own words. Chat-driven partial edits are exactly that risk | — | **WEBSITE ONLY** | LIVE |
| **Email add / verify** | `emailVerifiedAt` set only on `proof_validated` | None | — | COGNITO SESSION | Credential-recovery identifier | — | **WEBSITE ONLY** | LIVE |
| **Phone** | Cognito `phone_number_verified` | Implicit — it is the channel | — | VERIFIED | Echoing in full adds nothing; confirmation-only (last 4) | — | **WHATSAPP NATIVE** (confirmation-only) | LIVE |
| **Submit Request** — `Header.tsx:171` `/submit-request/` | `POST /ecommerce/prepare-checkout`; `src/components/ServiceRequestPurchase.tsx` | Full native path: `flows/catalog_services.py` → `catalog_service_checkout.py` → `wecarepay_wa` → `razorpay-webhook` → `flows/paid_submit_request.py` | Flow `1107164111921876` must be PUBLISHED with no validation errors (`catalog_service_checkout.py:100-103`); `wecarepay_wa` APPROVED | VERIFIED **+ at least one earlier owned order** (`catalog_services.py:63-70`) | Parent-order confusion — mitigated: `paid_submit_request.list_orders` excludes `row['orderId']` and re-reads each base row with `ConsistentRead=True` to recheck `customerId` | ₹99 base (9900 paise) + convenience fee + GST on the fee; server-side price from Wix, quote frozen | **WHATSAPP NATIVE (gated)** | BUILT-GATED — `WHATSAPP_CATALOG_SERVICES_ENABLED` absent |
| **Request Amendment** — `Header.tsx:172` | same checkout path | Keyword routes to the authenticated web experience | Flow `3678132465672138` — **DRAFT**, legacy phone lookup unrepaired (README §8) | VERIFIED | Legacy phone-based lookup is the same class of defect as F-3: phone alone must not resolve ownership | ₹99 (9900 paise) | **NOT YET SUPPORTED natively** → website | DRAFT |
| **Drop Docs** — `Header.tsx:173` | checkout + `wecare-secure-files` | Keyword routes to the authenticated web experience | Flow `1211063631104445` — **DRAFT**, same legacy lookup | VERIFIED | Upload path must be private from the first S3 write; live `DROPDOCS_ATTACH_ENABLED='false'` | ₹350 (35000 paise) | **NOT YET SUPPORTED natively** → website | DRAFT |
| **Vault** — `Header.tsx:182` `/vault/`; `src/pages/vault.tsx` | `wecare-secure-files` (`SECURE_FILES_TABLE`, `DOWNLOAD_GRANTS_TABLE`) | Native selection + grant: `catalog_services.py:88-105` → `flows/paid_vault.py` | No extra Flow (owner decision). `wecare_default_download` APPROVED but flag-gated by `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` (default `'false'`); `wecare_share_pdf` is the live path | VERIFIED **+ positive file ownership** | **FINDING F-3**: selection currently admits `ownerCustomerId == None` on a phone match alone (`catalog_services.py:94`) — a reassigned number could reach a prior holder's document. Must be fixed before enabling | ₹49 (4900 paise); already-unlocked files excluded (`vaultAccessGrantId` / `vaultPaymentStatus != 'PAID'`) | **WHATSAPP + SECURE WEB FALLBACK (gated)** — entitlement in chat, download through the authenticated link | BUILT-GATED, **blocked on F-3** |
| **Shipments** — `Header.tsx:198`; `src/pages/shipments.tsx` | order history read | `Shipments` keyword → order lookup | Plain text / list | VERIFIED | Low | **None — utility entry, NOT a priced SKU. Do not invent a price.** | **WHATSAPP NATIVE** | LIVE |
| **Leave Review** — `Header.tsx:199`; `src/pages/leave-review.tsx` | `ReviewTable`; `src/lib/reviewEntry.ts:36` | Flow `1578178897413815` PUBLISHED; `wecare_leave_review` APPROVED | Existing published Flow | VERIFIED for attributed reviews | **FINDING F-2**: three senders, three unrelated claim namespaces → a native purchase can be invited twice | **None — utility entry, NOT a priced SKU** | **WHATSAPP NATIVE** | LIVE, **blocked on F-2 for the native case** |
| **Customer ideas** | `ReviewTable` authoritative (`docs/kiro-handoff.md` 2026-10-08) | `flows/customer_ideas` via the review Flow | Existing Flow | VERIFIED | Low. Trusted webhook sender resolves the contact; handset-supplied IDs never used; no invented rating | None | **WHATSAPP NATIVE** | LIVE |
| **Contact / support** — `Header.tsx:226` `/contact/`; `src/pages/index.tsx:583`; `src/components/SupportWidget.tsx` | contact form | Free text to a human | None | NONE to start; VERIFIED before any private data | Live `STANDBY_REPLY_ENABLED='false'` — standby messages are stored as context (`ThreadOwnershipTable`, `SB#<epoch>#<wamid>`, 7-day TTL) but not auto-replied | None | **WHATSAPP NATIVE** | LIVE |
| **Service prices** | `GET /ecommerce/service-prices` → `src/lib/servicePricing.ts`; Wix is the authority | Quoted inside the native pay message | `wecarepay_wa` itemises convenience fee + GST | NONE to read | Price must come from Wix server-side; `src/config/services.ts` declares **no price** by design so no amount is re-typed | — | **BOTH** | LIVE |
| **Cart / checkout / payment** — `src/pages/cart.tsx` | `POST /ecommerce/prepare-checkout`, `POST /ecommerce/verify-callback` | Order-details message + Review & Pay (`catalog_service_checkout.py:78-88`) | `wecarepay_wa` APPROVED with **ORDER_DETAILS** button | VERIFIED | Readiness is fail-closed: `PAYMENT_READY` only on a successful live readback with a matching `provider_mid` (`payment_readiness.py:68,80-96,168-169,244-248`) | Yes — owner completes real payments personally | **BOTH**; WhatsApp gated | BUILT-GATED |
| **Service fulfilment notifications** | workspace projection + order row | Template sends on the paid path | Approved templates only; no substitution outside the 24-hour window — handler returns `AWAITING_CUSTOMER_MESSAGE` | VERIFIED | Fulfilment failure after payment must never re-charge; see `whatsapp-payment-state-machine.md` | Paid | **WHATSAPP + SECURE WEB FALLBACK** | BUILT-GATED |
| **Workspace order view** (staff) | `/workspace/engage/service-ops` (`src/config/navigation.ts:124`) | n/a — operator surface | — | Cognito group `Admin`/`Operator` | Per `docs/kiro-handoff.md` the pool's only user is in **no** group, so Admin-authenticated verification is itself blocked (owner item O7) | — | **WEBSITE ONLY** | LIVE, verification blocked |

---

## Entry-point inventory (WhatsApp side, as it exists today)

`src/config/whatsappServiceEntries.ts` is canonical — eight keyword entries, with
`whatsappKeywordLink` at `:14-15` building `https://wa.me/919330994400?text=<keyword>`:

| Slug | Keyword | Flow | Recorded state |
|---|---|---|---|
| `submit-request` | Submit Request | `1107164111921876` | Published; opens after verified payment |
| `request-amendment` | Request Amendment | `3678132465672138` | Existing draft; publication pending |
| `drop-docs` | Drop Docs | `1211063631104445` | Existing draft; publication pending |
| `vault` | Vault | — | Secure file selection and delivery; no extra Flow |
| `shipments` | Shipments | — | Verified order history; carrier booking is separate |
| `leave-review` | Leave Review | `1578178897413815` | Published |
| `orders` | Orders | — | Canonical customer order numbers; paginated |
| `customer-id` | Customer ID | — | Stored public customer UUID |

Using `+919330994400` as the **deep-link target** is correct: the customer initiates to the
business. It is never used as a customer identity, and `whatsapp_basket.is_business_sender` refuses
it inside `verified_identity`.

A **staff** "Customer Service Hub" already exists at `/workspace/forms/selfservice`
(`src/config/navigation.ts:167`) with per-topic `wa.me/message/...` short links
(`src/pages/workspace/forms/selfservice.tsx:32-39`). It is an operator page, not the customer hub.

## Migration summary

| Destination | Count | Entries |
|---|---|---|
| WHATSAPP NATIVE | 8 | Customer ID, Orders list, Payment status, Phone (confirm-only), Shipments, Leave Review, Customer ideas, Contact/support |
| WHATSAPP + SECURE WEB FALLBACK | 5 | Order detail, Invoice/receipt, Profile view (masked), Vault, Service fulfilment |
| WEBSITE ONLY | 6 | Sign in, WhatsApp↔customer link, Profile edit, Address, Email, Workspace |
| NOT YET SUPPORTED natively | 2 | Request Amendment, Drop Docs (both DRAFT + legacy lookup) |

Nothing is marked for removal from the website.
