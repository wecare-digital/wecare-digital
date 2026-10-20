# WhatsApp / Meta Business Platform — coverage map (built vs. not built)

> Prompted by: *"deep fetch all links [Overview + Flows] … see what we have built,
> what not … list all next links from both in an md file."*
>
> **Honesty note on the crawl:** the two Meta doc roots
> ([Overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/overview)
> and [Flows](https://developers.facebook.com/documentation/business-messaging/whatsapp/flows))
> render their navigation/link tree **client-side (JavaScript)**. A server-side
> fetch returns only prose, not the anchor list — so the "next links" below are the
> **canonical, well-known section structure** of the WhatsApp Business Platform
> docs, **not** a scrape of every live `<a href>`. Where a URL is given it is the
> stable documented path; treat any that 404 as "Meta moved it" and search the
> current nav. The **built / not-built** column is verified against THIS repo's
> code (file paths cited), which is the authoritative half of this document.
>
> Updated: 2026-10-20. Repo evidence from `amplify/functions/messaging/*`,
> `amplify/functions/ecommerce/*`, `amplify/functions/shared/lambda_utils/*`.

Legend: ✅ built · 🟡 partial / gated · ❌ not built · ⛔ intentionally retired

---

## 1. Cloud API — messaging core

| Capability | Status | Evidence / note |
| --- | --- | --- |
| Send text | ✅ | `outbound-whatsapp/handler.py` (`type: text`) |
| Send image / video / document | ✅ | `outbound-whatsapp` (`image`/`video`/`document`) |
| Send audio / sticker | 🟡 | media pipeline exists (`/media` ×51); audio/sticker not explicit send types |
| Send location | ✅ | `type: location` |
| Send contacts | ❌ | not emitted |
| Reactions | ✅ | `type: reaction` (auto-thumb) |
| Typing indicator | ✅ | `_send_typing_indicator` (fresh inbound wamid) |
| Template messages | ✅ | `type: template`; `whatsapp-template-management`, `whatsapp-templates` |
| Interactive — buttons / list | ✅ | `button`, `list` |
| Interactive — CTA URL | ✅ | `cta_url` |
| Interactive — location request | ✅ | `location_request` |
| Interactive — address message | ✅ | `address_message` |
| Interactive — **Flow** | ✅ | `flow` (see §4) |
| Interactive — **product / product_list** | ✅ | `product`, `product_list` (catalog §5) |
| **order_details** (WhatsApp Pay / native checkout) | 🟡 gated | `order_details`; native in-chat pay is **not live** (`CHECKOUT_INITIATION_ENABLED` off; website Razorpay is the money path) |
| **order_status** (post-pay fulfilment) | ✅ | `order_status` (`wecare_order_status` template APPROVED) |
| Mark as read | 🟡 | inbound handler tracks read; verify explicit read-receipt POST |
| Media upload / download / resumable | ✅ | `/media` edge, `meta_client.upload_multipart`/`download_file` |

**Canonical next links (Cloud API):** `/messages`, `/media`, message-types
(text, media, location, contacts, reaction, interactive), templates reference,
`/phone_numbers`, business profile, webhooks, error codes, rate limits,
messaging limits & quality rating, conversation-based pricing.

---

## 2. Registration, phone numbers, business profile

| Capability | Status | Evidence |
| --- | --- | --- |
| Register / deregister phone | ✅ | `/register` ×6, `whatsapp-business-api` |
| Request/verify code | ✅ | `/request_code`, `/verify_code` |
| Phone-number list / settings | ✅ | `/phone_numbers`; `waba-management` |
| Business profile read/update | ✅ | `/whatsapp_business_profile` |
| Subscribed apps (webhook subscribe) | ✅ | `/subscribed_apps` ×14 |
| Two-step PIN | ❌ | not managed in code |
| Display-name / quality / messaging tier | 🟡 | quality surfaced; tier management partial |

**Canonical next links:** Phone Numbers, Register Phone, Business Profile,
Two-Step Verification, Display Name, Quality Rating & Messaging Limits.

---

## 3. Templates

| Capability | Status | Evidence |
| --- | --- | --- |
| Create / update / delete templates | ✅ | `whatsapp-template-management` (`/message_templates`) |
| List + live status refresh | ✅ | `_list_templates`, `templates/{id}/refresh` |
| Category / TTL validation | ✅ | `_validate_template_ttl`, `_validate_template_definition` |
| Canonical send-eligibility (APPROVED vs PAUSED/REJECTED/…) | ✅ | `shared/lambda_utils/template_status.py` (upstream) |
| Template analytics | ✅ | `template-analytics` |
| Authentication / OTP templates | 🟡 | category validated; OTP autofill/copy-code not confirmed |
| Media / LTO / carousel / MPM templates | 🟡 | header media yes; LTO/carousel/MPM not confirmed |

**Canonical next links:** Create Templates, Template Components, Categorization,
Template Pacing, Analytics, Authentication Templates, Media-Card/Carousel/MPM.

---

## 4. WhatsApp Flows — the Flows doc tree (deep)

Our Flows surface is **large and real** — endpoint data-exchange router +
per-use-case modules + published Flow JSON:
`amplify/functions/messaging/whatsapp-business-api/flows/`.

| Flows doc section | Status | Evidence |
| --- | --- | --- |
| Flows overview / use cases | ✅ | many real flows (below) |
| Get started / first Flow | ✅ | `subscribe.py` + `subscribe-flow.json` |
| **Flow JSON** (screens/components/layout) | ✅ | `*-flow-v*.json` (submit-request v1/v2/v3, appointment, rx-slot, postpay v1/v2, order-notes, leave-review v1/v2, drop-docs, enterprise-assist, amend-request, track-request, profile) |
| **Flows REST API** (create/update/publish/deprecate/clone/migrate) | ✅ | `/flows` ×21; `whatsapp-business-api` Flows CRUD |
| **Endpoint / data_exchange** (data-channel) | ✅ | `flows/router.py` routes decrypted payloads to modules |
| Data-exchange encryption (RSA/AES) | ✅ | router decrypts request / encrypts response |
| Preview | ✅ | Flows preview in `whatsapp-business-api` |
| Flow metrics / submissions | ✅ | submission registry + stats + export |
| Health-check / ping | 🟡 | data-exchange present; explicit `ping`/health_check action — verify |
| Error codes | ✅ | handled in router/common |
| Versioning / changelog | 🟡 | tracked informally |

**Use-case modules built:** subscribe, submit_request, paid_submit_request,
track_request, amend_request, appointment, rx_slot, drop_docs, enterprise_assist,
leave_review, order_notes, orders, customer_orders, catalog_lifecycle,
catalog_services, customer_commands, customer_invoice, service_design_drafts,
postpay, paid_vault, generic.

**Canonical next links (Flows):** Flows Overview, Get Started, Flow JSON
(Components, Screens, Layout, Dynamic/Data-bound), Flows API (Create/Update/
Publish/Deprecate/Metrics/Assets), Endpoint (Data Exchange, Encryption,
Request/Response, Health Check, Error Codes), Preview, Examples, Versioning &
Changelog, Troubleshooting.

---

## 5. Catalog & Commerce

| Capability | Status | Evidence |
| --- | --- | --- |
| Manage Meta catalog (products CRUD) | ✅ | `ecommerce/catalog-management` (Graph) |
| AWS → Meta catalog sync / feed | ✅ | `ecommerce/meta-catalog-sync` (stream-driven) |
| Native product authority (ProductsTable) | ✅ | `ecommerce/native-catalog-admin` |
| Single / multi-product messages | ✅ | `product`, `product_list` |
| Cart / `order` inbound (native catalog order) | 🟡 gated | `inbound-whatsapp-handler`; `WA_CATALOG_ORDERS_ENABLED=false` |
| WhatsApp Pay (order_details) | 🟡 gated | not live; website Razorpay is the money path |

**Canonical next links:** Catalog, Products, Sell Products & Services,
Single/Multi-Product Messages, Order Details / Payments (India), Cart.

---

## 6. Webhooks

| Capability | Status | Evidence |
| --- | --- | --- |
| Inbound messages webhook | ✅ | `inbound-whatsapp-handler` (SNS/Meta) |
| Message status (sent/delivered/read/failed) | ✅ | `value.statuses[]` processing |
| **Payment status webhook** (plural `transactions[]`) | ✅ | `_process_payment_status` / `_select_payment_transaction` (fixed #1076) |
| Template status / quality webhooks | 🟡 | partial |
| Account / phone / BSUID system events | ✅ | `user_changed_user_id` handling |
| Signature verification (X-Hub-Signature-256) | ✅ | canonical `/whatsapp` ingress |

**Canonical next links:** Webhooks Setup, Components (messages, statuses,
payments, account_update, template_status, phone_number_quality_update),
Payload Reference, Security.

---

## 7. Calling, voice, groups, block

| Capability | Status | Evidence |
| --- | --- | --- |
| WhatsApp Calling API | ✅ | `whatsapp-calling` (`/calls` ×12), `whatsapp-voice`, `voice-aws`, `voice-cdr-read` |
| Conversational automation / ice-breakers / commands | ✅ | `/conversational_automation` ×4 |
| Block users | ✅ | `/block_users` ×10 |
| Groups | 🟡 | referenced "where usable"; not a core surface |

**Canonical next links:** Calling API, Conversational Components (ice-breakers,
commands), Block Users, Typing Indicators.

---

## 8. Marketing, analytics, partner/onboarding

| Capability | Status | Evidence |
| --- | --- | --- |
| Marketing Messages / ads that click to WhatsApp | ✅ | `marketing-ads`, `messaging/ad-attribution` |
| Meta analytics / conversation analytics | ✅ | `meta-analytics` |
| Embedded Signup / partner onboarding | ✅ | `partner-onboarding`, `partner-token-refresh` |
| Meta success detection fail-closed | ✅ | `mutation_succeeded()` (upstream #1078) |
| Solution Partner / Tech Provider mgmt | 🟡 | onboarding yes; full BSP mgmt partial |

**Canonical next links:** Marketing Messages, CTWA, Analytics, Embedded Signup,
Business Management API, System Users & Tokens.

---

## Gaps worth a decision (not yet built / gated)

1. **Native WhatsApp Pay (order_details)** — 🟡 gated off; website Razorpay is the
   live money path. (Templates `wecarepay_wa` + config are APPROVED/Active, but
   `CHECKOUT_INITIATION_ENABLED` is off and the binding/reconcile path is the one
   under active repair — see `meta-payment-binding-redrive-*.md`.)
2. **Native catalog `order` inbound** — 🟡 `WA_CATALOG_ORDERS_ENABLED=false`;
   backend exists, gated pending end-to-end verification.
3. **Send contacts message** — ❌.
4. **Authentication/OTP templates** (one-tap autofill / copy-code) — 🟡 verify.
5. **Advanced template types** (carousel, LTO, MPM) — 🟡 not confirmed.
6. **Two-step PIN management**, **messaging-tier automation** — 🟡/❌.
7. **Flows health-check/ping action** and formal **version/changelog tracking** — 🟡.

## How to complete the link scrape properly (next step if you want the full href list)

Server-side fetch can't read Meta's JS-rendered nav. To capture every literal
"next link" from both pages, drive a headless browser (the repo has
`chrome-headless-shell` + `playwright-core` under `tools/browser/`, per the device
audit) to load each URL, wait for nav render, and extract all
`a[href^="/documentation/"]` — then diff that set against this coverage table.
That is a separate, browser-driven task; flag it if you want it run.
