# WhatsApp experience — full structure, and the single-menu redesign

Written 2026-09-26. Everything in the CURRENT STATE sections was read out of the tree
or measured live against Meta; where something could not be verified it says so.
The TARGET sections are a proposal to build from.

Two owner instructions drive the redesign:

1. **There will be only ONE menu.** Today there are five interactive lists.
2. **The word "appointment" comes out of customer-facing copy.**

---

## STATUS — the one menu is BUILT (2026-09-26)

Build-order steps 1, 2 and 3 in §11 are done, plus the copy half of step 4. The
CURRENT STATE sections below describe the state **before** this change and are kept
because the retired ids in them are still tappable on handsets; read §11 for what
customers see now.

| What | Before | After |
|---|---:|---:|
| Interactive lists a customer can reach | 2 | **1** |
| List configs defined in the inbound handler | 5 | 5 (3 unreachable, 2 retired-in-place) |
| Rival menu in `ai-generate-response` | 1 | **0 — deleted** |
| `MENU_TO_KEYWORD` entries | 40 | 59 |
| Row ids mapping to `None` (silent tap) | 9 | **0** |
| Rendered row ids absent from the table | 19 | **0** |

What moved:

- `DEFAULT_ONE_MENU` (10 rows, 5 sections) is served by `_get_welcome_config()`,
  still overridable from `welcome_message_config`, still with no phone argument —
  so both WABAs render the identical menu.
- `[retired public path b180810d]`, `[retired public path 6b3a02b3]`, the `Selfservice` ice breaker and the
  `menu_customerservice` row all open **that** menu. The keywords stayed; only the
  second list went. `customerservice` also joined `BUTTON_MENU_TRIGGERS`, because an
  ice-breaker tap can arrive as `button`, which skips the text block entirely —
  that was a silent tap before.
- `_send_help_about()` is the `menu_help` row and the `help & about` keyword. It is
  the only place the eight rows that came off the menu are named, so it is
  load-bearing, not decoration.
- Every row title is typeable: `book a visit`, `track a request`,
  `change a request`, `book an rx slot`, `send documents`, `business enquiry`,
  `get updates`, `pay a bill`, `help & about` were **added** to the existing sets.
  No `appointment` keyword was removed — same precedent as Bharat Stack in §10.
- `DEFAULT_BOT_FLOW['mainMenu']` and `['subMenus']` are deleted from
  `ai-generate-response`. Both were unreachable (`flowConfig` was never returned,
  and `_process_ai_automation` has no caller), but 22 of their row ids answered
  with silence. Those ids are now all registered.
- `menu_language` reopens the one menu instead of the region picker. The picker's
  own four rows resolved to nothing, so tapping it produced a list where every
  option was silent. One line to reverse once §9 #13 is settled.

Pinned by `tests/test_one_menu.py` (29 cases): 10-row cap and every Meta character
limit, no id mapping to `None`, no id opening a second list, every retired and
AI-era id still resolving, every row title typeable, and the Help reply naming each
dropped row. Full suite 3525 passed.

`DEFAULT_MAIN_MENU`, `DEFAULT_CUSTOMERSERVICE_MENU` and their getters are still in the
tree, unreferenced by any row id, so reverting to two menus is a one-line change in
`MENU_TO_KEYWORD`. Step 6 deletes them.

Two supporting changes already applied and verified in production.

**1. Business-profile `description`, both numbers** (346/512 chars, no "appointment",
byte-exact on WABA1 and WABA2 with paragraph breaks preserved):

> WECARE.DIGITAL builds Everyday AI and everyday services for Bharat — for people,
> businesses, climate tech, and emerging technology.
>
> Transparent pricing. One guided path through every request. Support that follows
> through.
>
> Send "menu" for everything in one place: place a request, track progress, share
> documents, make payments, and get answers.

**2. Our own QR and widget prefills now open the menu** — defect #1 in §9, fixed and
live-verified in two stages.

*Stage 1 (the symptoms):* `get help` and `hi 👋` added to `HI_KEYWORDS`,
`BUTTON_MENU_TRIGGERS`, `_DETERMINISTIC_KEYWORDS`, `_STANDBY_TEXT_TRIGGERS` and
`DEFAULT_AI_ROUTING.keywords`.

*Stage 2 (the reason):* both strings failed for the **same** underlying cause — every
keyword set in the handler is exact-match, so any decoration around a keyword misses,
and `Hi 👋🏽`, `menu 🙏` or the next prefill anyone sets on Meta would have failed
identically. `strip_decorative_edges()` now trims emoji, variation selectors, ZWJ and
whitespace off both ends, and the greeting / customer-service / commands checks consult the
stripped form as a **fallback** after the raw form misses.

Scope is deliberately narrow, and the narrowness is the design:

- **Explicit codepoint ranges, not Unicode categories.** `So`/`Mn` would be shorter and
  would also strip Devanagari combining marks off the edges of Hindi input —
  `PAY_KEYWORDS` carries `भुगतान`, `बिल`, `पेमेंट` and `बाकी`, and silently truncating a
  customer's Hindi payment request would be worse than the bug being fixed.
- **ASCII punctuation is untouched**, so `/menu` survives.
- **Applied only where a false positive is harmless** — the menu sets. Explicitly *not*
  `PAY_KEYWORDS` (money), `DEFAULT_FLOW_TRIGGERS` (creates records, one of them charges
  ₹49) or `MY_ID_KEYWORDS` (discloses subscriber details). A test asserts the fallback is
  absent from those.

Pinned by `tests/test_own_prefill_triggers_menu.py` (33 cases, including the Devanagari
guard and a check that the match sites actually consult the helper).

---

## 0. The constraint that decides the whole design

Meta's [interactive list reference](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/interactive-list-messages)
(updated 2 Jul 2026) caps a list message at:

| Element | Limit |
|---|---|
| **Rows, all sections combined** | **10** |
| Sections | 10 |
| Row title | 24 chars |
| Row description | 72 chars |
| Section title | 24 chars |
| Header (text only) | 60 chars |
| Body | 4096 chars |
| Footer | 60 chars |
| Button label | 20 chars |

Today's main menu has 9 rows and the customer-service menu has 9 more. **18 rows cannot
become one menu.** One menu means choosing 10 and demoting the rest to keyword and
slash-command access. Section 11 is that choice.

Also note: interactive messages can only be sent inside the 24-hour customer service
window. Outside it, a template is required. The menu is therefore a *reply* surface,
never a cold-open surface.

---

## 1. Channel topology — two numbers, and they are not equivalent

| | WABA1 | WABA2 |
|---|---|---|
| WABA id | `2094615664435155` | `2513394156072604` |
| Display | +91 93309 94400 | +91 99033 00044 |
| Meta phone id | `1016149501586345` | `1055232054343117` |
| Internal phone id | `phone-number-id-waba1-direct-1016149501586345` | `phone-number-id-waba-t-direct-1055232054343117` |
| Verified name | WECARE.DIGITAL | Manish Agarwal |
| Quality / status | GREEN · CONNECTED · OBA | GREEN · CONNECTED · OBA |
| Throughput | STANDARD, 80 mps | STANDARD, 80 mps |
| Template language for `wecare_pay` | `en` | `en_US` |
| Native WhatsApp Pay | **yes** | **no** — sends a CTA to `wecare.digital/r/pay` |
| WhatsApp Flows | 10 of 10 | **1 of 10** (`subscribe` only, via `flowId2`) |
| QR deep link | `wa.me/message/APDM5HUWH26SG1` → "Get Help" | `wa.me/message/DPESCFW7U4FXO1` → "Hi 👋" |

Two asymmetries matter more than anything else in this document:

- **Flows are WABA-scoped.** `_send_generic_flow` (`inbound-whatsapp-handler/handler.py:4692`)
  checks for `flowId2`; only `subscribe` has one. For the other nine, WABA2 customers get
  a **CTA URL button instead of a form** — a link out to `wecare.digital/r/{sr,tr,ar,sa,rx,dd,ea,lr,on}`.
  So a menu row that opens a form on WABA1 opens a web link on WABA2.
- **Payment is WABA1-only in practice.** `PAY_MSG`, `PAYMENT_PHONE_NUMBER_ID` and both pay
  branches (`handler.py:1741` and `:6551`) route WABA2 to a web link. The invoice engine and
  the Razorpay webhook both default to WABA1 when the originating phone cannot be resolved,
  deliberately, because WABA2 is `paymentProtected` in `src/config/constants.ts`.

**Design consequence:** one menu, two capability tiers. Either publish the nine missing
flows on WABA2, or accept that the menu degrades to links there. Do not paper over it.

---

## 2. Every entry point

| Entry | Mechanism | Arrives as | Lands on |
|---|---|---|---|
| Ice breaker tap | Conversational components: `Get Started`, `Subscribe`, `Selfservice` | `text` (or `button`) | keyword routing |
| Slash command | Commands: `/menu` `/subscribe` `[retired public path b180810d]` `[retired public path 47a81ed9]` | `text` starting `/` | normalised, then keyword routing |
| Typed keyword | free text | `text` | keyword routing (§4) |
| QR / `wa.me/message/*` | prefilled message | `text` | keyword routing. **Dismisses ice breakers** |
| Site widget | `SupportWidget.tsx`, `wecare-wa-widget.js` → `wa.me/message/APDM5HUWH26SG1` | `text` "Get Help" | main menu (fixed 2026-09-26) |
| Menu row tap | interactive list | `interactive.list_reply` | `_handle_list_reply` (`:6384`) |
| Reply button tap | `followup_explore` / `followup_done`, `ivr_*`, `opt_*`, `rate_*` | `interactive.button_reply` | `:1337` |
| Flow submission | Flows data exchange | `nfm_reply` / encrypted POST | `/wa-business/flow-data` |
| Address message | native India address | `nfm_reply` name=`address_message` | `_handle_address_submission` |
| Catalog cart | native checkout | `order` | `_handle_cart_order` (`:5154`) |
| New-thread open | `request_welcome` webhook | `request_welcome` | main menu — **currently never fires**, `enable_welcome_message: false` on both numbers |
| Brand-new contact | first ever text/media | any | main menu, once, then `welcomeSent` |
| Post-payment | Razorpay `payment.captured` | flow message or `postpay_request_v1` template | post-pay flow |

---

## 3. CURRENT STATE — all five menus

All five live in `amplify/functions/messaging/inbound-whatsapp-handler/handler.py` and
each can be overridden by a `SystemConfigTable` row. **Verified live: all override rows are
absent, so the code defaults below are what customers see.**

### 3.1 Main menu — `DEFAULT_MAIN_MENU` (`:6629`), override `welcome_message_config`

Header `Welcome to WECARE.DIGITAL` · Button `Get Started` · Footer `Tap an option to continue.`
Body: *Choose what you'd like to do — get started, explore our services, or find quick answers.*

| Section | Row id | Title | Description | Action |
|---|---|---|---|---|
| Start Here | `menu_customerservice` | 🚀 Selfservice | Requests, **appointments**, documents, and support | opens menu 3.2 |
| | `menu_subscribe` | 🔔 Subscribe for Updates | Get updates, offers, and service news | `subscribe` flow |
| | `menu_find_id` | 🆔 Find Profile ID | Locate your subscription or profile ID | `find id` lookup |
| | `menu_pay` | 💳 Make a Payment | Pay an invoice or complete a pending payment | pay path |
| Explore WECARE | `menu_store` | 🛍️ Explore Store | Browse services, brands, and offers | CTA `wecare.digital` |
| | `menu_gift_card` | 🎁 Gift Cards | Send a digital gift card | CTA `/gift-card` |
| | `menu_bharat_stack` | 🇮🇳 Bharat Stack | Discover Bharat Stack and services | CTA `wecare.digital` |
| Help & Answers | `menu_faq` | ❓ FAQs | Find answers to common questions | CTA `[retired public path 1965ee0f]` |
| | `menu_about` | 💛 About WECARE.DIGITAL | Learn more about WECARE.DIGITAL | text block |

### 3.2 Self-service menu — `DEFAULT_CUSTOMERSERVICE_MENU` (`:6797`), override `customerservice_menu_config`

Header `Selfservice` · Button `Browse Services` · nine sections of one row each.

| Section | Row id | Title | Description | Action |
|---|---|---|---|---|
| New Request | `ss_submit_request` | 📋 Submit Request | Start a new support request | `submit_request` flow, ₹49 |
| Request Status | `ss_track_request` | 🔍 Track Request | Check the status of your request | `track_request` flow |
| Existing Request | `ss_amend_request` | ✏️ Amend Request | Edit or correct a submitted request | `amend_request` flow |
| **Schedule Appointments** | `ss_schedule_appointment` | 📅 **Appointment** | Schedule a consultation or service visit | `schedule_appointment` flow |
| Medical Tourism | `ss_rx_slot` | 🩺 RX Slot | Schedule a medical tourism or prescription-related visit | `rx_slot` flow |
| Documents | `ss_drop_docs` | 📄 Drop Docs | Send supporting documents for your request | `drop_docs` flow |
| Business Support | `ss_enterprise_assist` | 🏢 Enterprise Assist | Corporate, B2B, and bulk enquiries | `enterprise_assist` flow |
| Feedback | `ss_leave_review` | ⭐ Leave Review | Share your experience with our service | `leave_review` flow |
| Help | `ss_faq` | ❓ FAQ | View frequently asked questions | CTA `[retired public path 1965ee0f]` |

### 3.3 Bharat Stack menu — `DEFAULT_BHARAT_STACK_MENU` (`:6759`) — **DEAD**

Six rows (`bs_aadhaar`, `bs_upi`, `bs_digilocker`, `bs_esign`, `bs_ondc`, `bs_account_aggregator`).
Every one maps to `None` in `MENU_TO_KEYWORD`, so a tap logs `list_reply_unhandled` and the
customer gets **no reply at all**. And no row id anywhere maps to `_bharat_stack_menu`, so the
menu is never sent. Delete it in the redesign.

### 3.4 / 3.5 Language region picker + four region lists (`:6662`, `:6681`)

`DEFAULT_LANGUAGE_PICKER` (4 region rows) and `REGION_LANGUAGE_LISTS` (10 + 7 + 5 + 3 language
rows). Reached only via `menu_language`, a **legacy** id not present in the current main menu.
`region_*` and `lang_*` ids are not in `MENU_TO_KEYWORD`. **Unverified:** whether the AI path
(`ai-generate-response` returning `regionLanguages`) handles them before `_handle_list_reply`
returns; it appears not to, which would make language selection dead too. Confirm before
deciding whether to keep language switching.

---

## 4. CURRENT STATE — text routing, in evaluation order

This is the part a redesign is most likely to break. Inside `msg_type == 'text'`, matched
against `content.strip().lower()`. **Every step returns** — first match wins.

| # | Set (line) | Members (abridged) | Effect |
|---|---|---|---|
| 0 | `_KNOWN_SLASH_COMMANDS` `:1601` | `/menu /subscribe /bharatstack [retired public path b180810d] [retired public path 6b3a02b3] [retired public path 47a81ed9] /help /commands` | rewrite only: `"[retired public path 47a81ed9] 500"` → `[retired public path 47a81ed9]`. Unknown `/foo` passes through |
| 1 | `MY_ID_KEYWORDS` `:1615` | `my id, sub id, subscriber id, /myid, /id, profile id, …` | subscriber lookup, text reply |
| 2 | **`DEFAULT_FLOW_TRIGGERS`** `:6044` | 10 flows, exact match on any keyword | sends that flow (or WABA2 CTA) |
| 3 | `PAY_KEYWORDS` + `PAY_FUZZY` `:1695` | `pay, payment, invoice, [retired public path 47a81ed9], baaki, भुगतान, …` + substrings | pay path |
| 4 | `HI_KEYWORDS` `:1802` | `hi, hello, hey, menu, main menu, show menu, start, browse menu, /menu, need help!, get started` | **main menu** |
| 5 | `BHARAT_KEYWORDS` `:1834` | `bharat stack, /bharatstack, bharat, aadhaar, upi, digilocker` | CTA `wecare.digital` |
| 6 | `CUSTOMERSERVICE_KEYWORDS` `:1849` | `customerservice, customer-service, customer service, [retired public path b180810d], [retired public path 6b3a02b3]` | **customer-service menu** |
| 7 | `COMMANDS_KEYWORDS` `:1866` | `commands, /commands, /help, help` | text list of commands |
| 8 | `STORE_KEYWORDS` | `store, shop, brands, marketplace` | CTA |
| 9 | `GIFT_KEYWORDS` | `gift card, gift, buy gift card` | CTA |
| 10 | `FAQ_KEYWORDS` | `faq, faqs, help, questions` | CTA `[retired public path 1965ee0f]` |
| 11 | `ABOUT_KEYWORDS` | `about, about us, about wecare` | text |
| — | no match | | message stored, **no reply sent** (`:1945`) |

Two separate gates sit above this, both configurable via `ai_hybrid_routing` (also absent live,
so defaults apply): `_DETERMINISTIC_KEYWORDS`/`_DETERMINISTIC_CONTAINS` (`:127`) and
`_STANDBY_TEXT_TRIGGERS` (`:199`) decide whether our bot or the Meta AI agent handles a
standby message. **Both contain the literal `appointment`.**

### Flow trigger keywords — the precedence hazard

Step 2 runs before pay and before the menu, and several of its keywords are single common words:

| Flow | Dangerously generic keywords |
|---|---|
| `submit_request` | `submit`, `request`, `sr` |
| `track_request` | `track`, `status` |
| `schedule_appointment` | `schedule`, `meeting`, `consultation` |
| `rx_slot` | `rx`, `medicine`, `pharmacy`, `chemist` |
| `leave_review` | `review`, `rate`, `rating`, `feedback` |
| `enterprise_assist` | `enterprise`, `corporate`, `b2b`, `bulk` |

A customer typing `status` gets a form, not an answer. Worth tightening as part of the redesign,
but see §10 — do not simply delete keywords customers were told to send.

---

## 5. CURRENT STATE — every form

10 keyword-triggered Flows plus 2 post-payment Flows. JSON lives in
`amplify/functions/messaging/whatsapp-business-api/flows/` (15 files, design-time only — nothing
reads them at runtime). Server handlers are `flows/*.py`, dispatched by `flows/router.py` on the
**flow-token prefix**, not the flow id. Token shape: `{flow_key}-{uuid}-waba-{1|2}-ph-{phone}`.

| Flow key | flowId (WABA1) | flowId2 | JSON | Screens | flowCode | Paid |
|---|---|---|---|---|---|---|
| `submit_request` | `1469093721293830` | — | submit-request-flow-v3 | ORDER_SELECT → SUBMIT_REQUEST_FORM → TERMS → REVIEW → THANK_YOU | `01.WD_SR` | **₹49** |
| `track_request` | `1486454129852338` | — | track-request-flow-v1 | ORDER_SELECT → STATUS | `02.WD_TR` | free |
| `amend_request` | `3678132465672138` | — | amend-request-flow-v1 | ORDER_SELECT → SELECT_REQUEST → AMEND_FORM → CONFIRM | *(none)* | free |
| `schedule_appointment` | `26575380852083467` | — | appointment-flow-v1 | BOOKING_FORM → REVIEW → CONFIRM | `WD_APPT` | free |
| `rx_slot` | `895208030185211` | — | rx-slot-flow-v1 | SLOT_FORM → REVIEW → CONFIRM | `WD_RX` | free |
| `drop_docs` | `1211063631104445` | — | drop-docs-flow-v1 | DOC_FORM → REVIEW → CONFIRM | `WD_DOCS` | free |
| `enterprise_assist` | `1707170524029465` | — | enterprise-assist-flow-v1 | INTAKE_FORM → CONFIRM | `WD_ENT` | free |
| `leave_review` | `4423166114671543` | — | leave-review-flow-v1 | REVIEW_FORM → CONFIRM | `WD_REV` | free |
| `subscribe` | `1262971692700761` | `951987930811295` | **profile-flow** | PERSONAL_INFO → SHIPPING_ADDRESS → REVIEW → COMPLETE | `WD_SUBSCRIBE` | free |
| `order_notes` | `1434731571172691` | — | order-notes-flow-v1 | ORDER_SELECT → NOTES_FORM → CONFIRM | `WD_NOTE` | free |
| *(post-pay)* | env `POST_PAYMENT_FLOW_WABA1/2` | | postpay-request-flow-v2 | SUMMARY → ADDRESS → DETAILS → SUCCESS | `03.WD_POSTPAY_REQUEST` | after payment |
| *(post-pay v1)* | — | | postpay-flow-v1 | DETAILS only | `02.WD_POSTPAY` | after payment |

### Fields collected

- **submit_request** — `order_id`, `subject`, `description`, `accept_terms`, `confirm_submit`
  ("I confirm the details are correct and agree to pay ₹49")
- **track_request** — `order_id`; returns `order_ref, order_status, payment_info, items_info, requests_summary, requests_count`
- **amend_request** — `order_id`, `request_id`, `amendment`
- **schedule_appointment** — `appointment_type` ⚠️, `location`, `slot_date`, `slot_time`, `notes`
- **rx_slot** — `slot_type` (Prescription Pickup / Medical Tourism / Lab Test / Pharmacy Visit), `slot_date`, `slot_time`, `facility_name`, `prescription_notes`
- **drop_docs** — `doc_type`, `order_id` (opt), `description`. **No file picker** — the customer sends media as a normal message and `_link_media_to_service_request` (`:6193`) attaches it to the open request for 14 days
- **enterprise_assist** — `account_name`, `contact_name`, `contact_email`, `subject`, `description`, `priority`
- **leave_review** — `rating`, `category`, `review_text`
- **subscribe** — `full_name`, `phone_number`, `wa_username`, `email_address`, `company_name`, `designation`, then delivery address, then confirm
- **order_notes** — `order_id`, `notes`
- **post-pay v2** — `name`, `address`, `landmark`, `city`, `state`, `pin`, `description`, `preferred_time`

### Form storage

`FlowSubmissionTable` (PK `submissionId`; GSIs `phone, flowCode, paymentStatus, paymentRefId,
submissionNumber, status, orderId, flowId`). Single safe writer is
`lambda_utils/flow_completion.claim_completion` — conditional put, so a Meta retry cannot
double-submit or double-charge. `_handle_postpay_submission` writes directly with its own
`attribute_not_exists` guard. `FlowLog` (90-day TTL) records every non-ping interaction;
`FlowDraft` (`{phone}#{flowCode}`, 7-day TTL) holds interrupted flows.

### Web forms

`src/pages/forms/` holds **no customer data-entry form**. `[retired public path 169e0fd8]` redirects to
`[retired public path 169e0fd8]/responses` (operator queue); `[retired public path 169e0fd8][retired public path b180810d]` is an admin catalogue whose only
customer-facing element is the `MESSAGE_LINKS` map of 12 `wa.me/message/*` codes. See §9 —
11 of those 12 codes do not exist on either number.

---

## 6. CURRENT STATE — the payment path

Four entry points converge on one pipeline:

```
[retired public path 47a81ed9] · "pay" keyword · menu_pay row · catalog cart · dashboard
   └─► inbound-whatsapp-handler
         ├─ WABA2 → CTA button "Pay Now" → wecare.digital/r/pay   [no native pay]
         └─ WABA1 → "👀 Pulling your pending invoice..."
               └─► wecare-invoice-engine  /invoices/send-pending-by-phone
                     • scans InvoicesTable for created|pending_payment|sent
                     • strict 10-digit phone match
                     • SEQUENTIAL: sends the OLDEST invoice only
                     └─► send_payment_link
                           • ownership check → 403 if invoice ≠ this customer
                           • items + GST + 2% convenience fee (+18% GST on the fee)
                           • digital-goods unless goodsType == physical-goods
                           └─► wecare-outbound-whatsapp
                                 • template wecare_pay (en on WABA1, en_US on WABA2)
                                 • IMAGE header, no body vars, ORDER_DETAILS button
                                 • payment_settings → Razorpay WECAREDIGITAL
                                 └─► customer taps → WhatsApp Pay → Razorpay
                                       └─► razorpay-webhook  payment.captured
                                             • HMAC verify, fails closed
                                             • mark invoice paid
                                             • order_status message
                                             • post-payment Flow (if configured)
                                             • receipt PNG with PAID stamp
```

| Fact | Value |
|---|---|
| Gateway | Razorpay only. PayU removed from both WABAs 2026-08-23 |
| Payment configs | `WECAREDIGITAL` (PG) and `WECAREUPI` (VPA) — identical names on both WABAs |
| Razorpay MID / MCC / purpose | `acc_TTFSyolquKEZEy` / `7392` / `03` |
| GSTIN | `19AAFFW7196L1Z8` (PAN `AAFFW7196L`, WB) |
| Convenience fee | 2% of subtotal + 18% GST on the fee, shown as a line item |
| Amount cap | ₹10,00,000 |
| Order expiry | 24 hours |
| Tables | Invoices, InvoiceItems, InvoiceSequence, InvoiceAssets, InvoiceDeliveryLog, Payments, RazorpayWebhookLog |

Customer-visible payment copy (`PAY_MSG`, `:538`): `👀 Pulling your pending invoice...` ·
`✅ No pending dues!` · `✅ Paid successfully.` · `❌ Payment failed. Please try again.` ·
`⚠️ You have unpaid invoice of ₹{total}.` · `❌ Could not send payment link. Please try again.` ·
`⚠️ Something went wrong. Please try again.`

Kill switches, both **default OFF**: `whatsapp_inbound_order_status` (would double-send the
confirmation) and `whatsapp_auto_next_due` (post-payment next-invoice nag).
`POST_PAYMENT_FLOW_WABA1` / `POST_PAYMENT_FLOW_WABA2` unset means no post-payment flow at all.

---

## 7. CURRENT STATE — auto-responses and CTAs

| Trigger | Response | Type |
|---|---|---|
| `hi` / `menu` / `get started` / `/menu` | main menu | interactive list |
| `customerservice` / `[retired public path b180810d]` | customer-service menu | interactive list |
| `commands` / `/commands` / `/help` / `help` | 6-line text list of commands | text |
| `my id` / `profile id` | subscriber details, or "No subscription found" | text |
| `store` / `shop` | CTA "Visit Store" → wecare.digital | cta_url |
| `gift card` | CTA "View Gift Cards" → /gift-card | cta_url |
| `faq` | CTA "Open FAQs" → /faq. Body mentions **appointments** | cta_url |
| `about` | 5-paragraph brand text, names 7 sub-brands | text |
| `bharat stack` / `aadhaar` / `upi` | CTA "Explore WECARE.DIGITAL" | cta_url |
| after any CTA | `🧭 Explore More` / `🫶 All Set` | reply buttons |
| `followup_explore` | main menu | interactive list |
| `followup_done` | "Awesome — you're all set for now 💛 … Type *hi* anytime" | text |
| brand-new contact, any message | main menu, once | interactive list |
| `request_welcome` | main menu | ⚠️ never fires today |
| automation rules match | `evaluate_rules(content,'whatsapp')` reply | text, async |
| AI blank-response safety net | "Hi! 👋 I'm here to help. Type *menu*…" | text |
| AI circuit breaker (5 failures) | "…brief delay… call us at +91 9330994400" | text |
| no match | **nothing** | — |
| `wa_auto_response.fallbackMessage` | configured, but the no-match path never calls it | dead |

Post-flow actions the AI layer can return: `showOptions`, `showMainMenu`, `showSubMenu`,
`showRating` (`🙌 Great` / `😐 Just okay` / `🥲 Could be better`), `sendPayment`,
`sendPendingPayments`, `humanHandoff`, `end`.

Outbound templates: `wecare_pay` (checkout), `postpay_request_v1` (post-pay flow outside 24h),
`wd_file_delivery` (secure file), `01_wecare_doc` (rollback predecessor), `wecare_otp` (auth),
`wd_call_permission` (calling). `postpay_details_v1` is approved on Meta but has **no code
reference**. There is no code-level template registry.

---

## 8. Configuration surface

Every override is a `SystemConfigTable` row keyed on `id`. **All verified absent live**, so code
defaults are authoritative today.

| Key | Controls |
|---|---|
| `welcome_message_config` | main menu |
| `customerservice_menu_config` | customer-service menu |
| `bharat_stack_menu_config` | Bharat Stack menu (dead) |
| `bot_language_picker_config` | language picker + region lists |
| `flow_triggers_config` | all 10 flows: keywords, flowId, flowId2, message, enabled |
| `ai_hybrid_routing` | bot-vs-AI trigger sets |
| `wa_auto_response` | fallback message (currently unreachable) |
| `catalog_flow_map` | catalog product → post-payment flow |
| `whatsapp_inbound_order_status` | duplicate payment confirmation (off) |
| `whatsapp_auto_next_due` | next-due nag (off) |
| `whatsapp_auto_thumb` | auto 👍 reaction (on) |

⚠️ `flow_triggers_config` merges **per key with `entry.update()`**, so writing a partial
`keywords` list for a flow *replaces* the whole list. That is how `/subscribe` would silently
break. Always write the full list.

---

## 9. Defects found while mapping this

Ordered by customer impact. None of these are introduced by the redesign; they are present now.

| # | Severity | Defect |
|---|---|---|
| 1 | ~~HIGH~~ **FIXED 2026-09-26** | Both numbers' QR prefills matched no keyword set: WABA1 sends `Get Help`, WABA2 sends `Hi 👋`. First-time contacts got the menu from the brand-new-contact path, so it looked fine; **returning** visitors tapping the same widget got silence. The root cause is that every keyword set is exact-match, so the two literals were added *and* `strip_decorative_edges()` was introduced so future variants cannot fail the same way (see §0 preamble). Fixed on the inbound side rather than by editing the QRs, because the QRs are printed and the links shared — only the inbound side reaches messages already in the wild. `wecare-inbound-whatsapp` v51→v52→v53, `wecare-whatsapp-business-api` v42→v43. Live-verified on the QA handset: `Get Help`, `Hi 👋`, and the never-listed variants `Hi 👋🏽` and `menu 🙏` all log `hi_keyword_triggered` → `interactive_list_sent` (Meta 202) → `delivered` |
| 2 | **HIGH** | 11 of the 12 `wa.me/message/*` codes in `src/pages/forms/customerservice.tsx` do not exist on either number. Meta's `message_qrdls` returns exactly one code per number (`APDM5HUWH26SG1`, `DPESCFW7U4FXO1`), no paging. Not verified by opening each link, but they are not registered Cloud API QRs |
| 3 | ~~MEDIUM~~ **FIXED 2026-09-26** | Bharat Stack submenu is unreachable, and all six of its rows mapped to `None` → silent no-reply if ever sent. All six now answer with the WECARE.DIGITAL CTA. The menu itself is still unreachable, which is now correct rather than accidental |
| 4 | MEDIUM | `order_notes` flow has no row in any menu — keyword-only. Unchanged by the redesign: it lost the 10-row cut, and the Help reply names `order notes` so it is at least discoverable |
| 5 | ~~MEDIUM~~ **MOOT 2026-09-26** | `ss_main_menu` had no row rendering it, so there was no "back" out of the customer-service menu. There is no submenu to come back from now. `ss_main_menu`, `menu_back` and the two `menu_customerservice` spellings all reopen the one menu |
| 6 | MEDIUM | `FAQ_KEYWORDS` contains `help`, but `COMMANDS_KEYWORDS` (evaluated first) also contains `help`. The FAQ entry is dead |
| 7 | MEDIUM | `enable_welcome_message: false` on both numbers, so `request_welcome` never arrives and the handler branch at `:1534` is dead. A new visitor arriving from a prefilled link sees no ice breakers *and* no greeting until they type |
| 8 | MEDIUM | `wa_auto_response.fallbackMessage` is loadable but the unmatched-text path sends nothing, so the configured fallback can never appear |
| 9 | LOW | `_handle_list_reply`'s pay branch (`:6551`) omits the `sent == 0` failure message the text path has — a failed send is silent |
| 10 | LOW | `customerservice.tsx:110` hardcodes `flow.key === 'submit_request' ? 'Published' : 'Draft'`, ignoring the `status` field two lines above |
| 11 | LOW | `code-repo.tsx` and `system-architecture.tsx` still name `submit-request-flow.json` v1 and `subscribe-flow.json`; runtime uses v3 and `profile-flow.json` |
| 12 | LOW | Two functions named `_is_deterministic_trigger` are defined in the same module (`:170` and `:206`); the second shadows the first, so the `ai_hybrid_routing` config the first one reads is ignored |
| 13 | **CONFIRMED 2026-09-26** | `region_*` / `lang_*` list ids appear in no dispatch table — measured, 4 region ids and 25 language ids all absent from `MENU_TO_KEYWORD`. Language switching via the picker was dead: the picker opened and every row was silent. `menu_language` now reopens the one menu instead of that trap. The picker code and `bot_language_picker_config` are untouched, so restoring it is one line **plus** registering the 29 ids |
| 14 | MEDIUM | `menu_find_id` → `'find id'`, but `_handle_list_reply` has no subscriber-lookup branch, so a tap falls through to the generic `"You selected: Find Id. Processing..."` and nothing follows. Pre-existing; the row is off the one menu but stays tappable on handsets. Fixing it means extracting the my-id lookup out of the text path into a function both paths call |
| 15 | LOW | Only `menu`, `subscribe`, `customerservice` and `pay` are registered as tappable commands on Meta (both numbers). `/bharatstack` and `/help` are normalised by `_KNOWN_SLASH_COMMANDS` and advertised in the commands reply, but cannot be tapped. The reply now lists them last and says so |

---

## 10. Removing the word "appointment"

**Change the copy. Keep the trigger keywords. Do not rename identifiers.**

The codebase already set this precedent for "Bharat Stack" (`handler.py:1827`): the reply copy
was rebranded while the inbound keywords were deliberately left intact, because those words are
printed in already-delivered messages and in the Meta-side ice-breaker config, and dropping them
would silently stop answering a message a customer was invited to send. The same reasoning
applies here: `appointment` is live in ice breakers, in a `wa.me` link and in customers' habits.

Replacement term: **Visit**.

### Change — customer-facing copy

| File:line | Current | Change to |
|---|---|---|
| `inbound…/handler.py:6638` | `Requests, appointments, documents, and support` | *(row is removed in the single menu)* |
| `:6822` | section title `Schedule Appointments` | `Book a Visit` |
| `:6823` | row title `📅 Appointment` | `📅 Book a Visit` |
| `:6823` | desc `Schedule a consultation or service visit` | `Consultation or service visit, at your time` |
| `:6488` | FAQ body `…requests, payments, appointments, business hours…` | `…requests, payments, visits, business hours…` |
| `:6104` | `flowCta: 'Appointment'` | `'Book a Visit'` (≤20 chars) |
| `appointment-flow-v1.json:11` | screen title `Book Appointment` | `Book a Visit` |
| `appointment-flow-v1.json` | field label `Appointment Type` | `Visit Type` |
| `src/pages/forms/customerservice.tsx:21` | label `Appointment` | `Book a Visit` |

### Keep — inbound triggers (no change)

`DEFAULT_FLOW_TRIGGERS['schedule_appointment'].keywords` keeps `appointment`,
`schedule appointment`, `book appointment`, `📅 appointment`. Same for `appointment` in
`_DETERMINISTIC_CONTAINS` (`:132`), `_STANDBY_TEXT_TRIGGERS` (`:202`) and
`DEFAULT_AI_ROUTING.contains` in `whatsapp-business-api/handler.py:137`. **Add** the new
aliases: `book a visit`, `visit`, `book visit`, `📅 book a visit`.

### Do not rename

`schedule_appointment` (flow key, and the router matches on the token prefix `schedule_a`),
`ss_schedule_appointment` (row id — cached in menus already on handsets), `WD_APPT` (flowCode,
in stored rows), `WD-APT` (reference prefix), `AppointmentTable`, `/appointments` API routes,
`flows/appointment.py`. Renaming any of these breaks stored data or in-flight menus for no
customer-visible gain.

Changing the flow JSON requires a **new Meta asset upload and publish** — the screen title and
field label live on Meta, not in our tree.

---

## 11. THE single menu — BUILT 2026-09-26

This section is no longer a proposal. It is what `DEFAULT_ONE_MENU` contains.

Header `WECARE.DIGITAL` · Button `Open Menu` · Footer `Tap an option to continue.`
Body: *What would you like to do? Everything is in this one menu — or just type what you need.*

Exactly 10 rows, 5 sections. All titles ≤24 chars, descriptions ≤72.

| Section | Row id | Title | Description | Action |
|---|---|---|---|---|
| Requests | `menu_request_new` | 📋 New Request | Start a request. ₹49 processing fee | `submit_request` |
| | `menu_request_track` | 🔍 Track a Request | Check status with your reference id | `track_request` |
| | `menu_request_change` | ✏️ Change a Request | Edit or correct a submitted request | `amend_request` |
| Visits | `menu_visit_book` | 📅 Book a Visit | Consultation or service visit, at your time | `schedule_appointment` |
| | `menu_visit_rx` | 🩺 Book an RX Slot | Prescription, pharmacy or medical travel visit | `rx_slot` |
| Documents & Payment | `menu_docs_send` | 📄 Send Documents | Share files for an open request | `drop_docs` |
| | `menu_pay` | 💳 Pay a Bill | Pay an invoice or clear a pending due | pay path |
| Business & Account | `menu_business` | 🏢 Business Enquiry | Corporate, B2B and bulk enquiries | `enterprise_assist` |
| | `menu_subscribe` | 🔔 Get Updates | Offers, service news and order updates | `subscribe` |
| Help | `menu_help` | ❓ Help & About | FAQs, business info and what we do | new combined reply |

`menu_pay` and `menu_subscribe` keep their existing ids on purpose — they are already in
`MENU_TO_KEYWORD` and already sitting in menus on customers' handsets.

### Not on the menu, still reachable

Nothing is deleted; these move to keyword, slash command and web access. State this in the
`menu_help` reply so it is discoverable.

| Dropped | Still reachable by |
|---|---|
| Find Profile ID | `my id`, `/id`, `/myid`, and inside the Help reply |
| Explore Store | `store`, `shop`, and the website |
| Gift Cards | `gift card` |
| Bharat Stack | `bharat stack`, `/bharatstack` |
| Leave Review | `review`, `feedback` — and better placed in a post-completion prompt than a menu |
| Order Notes | `order notes` |
| About | folded into `menu_help` |
| Language | pending the §9 #13 verification |

### Everything else that must move with it

1. **Delete** `DEFAULT_CUSTOMERSERVICE_MENU`, `DEFAULT_BHARAT_STACK_MENU`, `_get_customerservice_menu`,
   `_get_bharat_stack_menu`, and the `customerservice_menu_config` / `bharat_stack_menu_config` keys.
2. **Keep** `CUSTOMERSERVICE_KEYWORDS` and `[retired public path b180810d]` as triggers — they are live ice breakers
   and a live slash command — but point them at **the one menu**.
3. **Retarget legacy ids** in `MENU_TO_KEYWORD` so handsets holding the old menus still work:
   `menu_customerservice`, `menu_customer_service` → the one menu (not a submenu);
   all nine `ss_*` ids → their same actions; `ss_faq` → `menu_help`; `ss_main_menu` → the one menu;
   `menu_store`, `menu_gift_card`, `menu_bharat_stack`, `menu_faq`, `menu_about`,
   `menu_find_id` → their same actions. **Never delete a row id from the dispatch table** —
   an old menu can be tapped months later.
4. **Retire** the Bharat Stack row ids to a real reply instead of `None`.
5. `followup_explore` already reopens the menu — correct, no change.
6. Set `enable_welcome_message: true` on both numbers so `request_welcome` delivers the menu on
   a fresh thread (defect #7).
7. ~~Fix the widget's prefilled text.~~ **Done 2026-09-26** — the keyword sets now accept
   both QR prefills, so no QR or widget edit is needed. Keep `get help` and `hi 👋` in
   `HI_KEYWORDS` through the redesign: they are the entry point for every printed QR.
8. Add a **back-to-menu** affordance after every terminal reply, now that there is no submenu.

### Build order

| Step | Change | Risk | Status |
|---|---|---|---|
| 1 | Add the 10 new row ids to `MENU_TO_KEYWORD`, keep all legacy ids | none — additive | ✅ done — 59 entries, 0 map to `None` |
| 2 | Add `DEFAULT_ONE_MENU`, keep old menus in place | none | ✅ done — served by `_get_welcome_config()` |
| 3 | Point `HI_KEYWORDS` + `CUSTOMERSERVICE_KEYWORDS` + `followup_explore` + welcome paths at the one menu | medium | ✅ done — all six live send sites resolve to one config |
| 4 | Copy changes for "appointment"; add `book a visit` aliases | low | 🟡 aliases + menu copy done; `customerservice.tsx` label and the FAQ body still say "appointment" |
| 5 | Upload + publish the revised `appointment-flow-v1` asset to Meta | medium — Meta publish | ⏳ not started — the flow screen still reads "Book Appointment" on Meta while the menu row says "Book a Visit" |
| 6 | Delete the dead menus and their config keys | low | ⏳ deliberately deferred — they are the one-line revert for step 3 |
| 7 | Set `enable_welcome_message: true` (widget prefill already fixed) | low | ⏳ not started — still `false` on both numbers (re-verified 2026-09-26) |
| 8 | Publish the nine missing flows on WABA2, or accept link degradation | **high** — Meta publish ×9 | ⏳ owner decision 2 below |

Steps 1–4 changed no Meta-side asset, so they carry no Meta publish risk. Steps 5
and 8 do, which is why they are separate.

Every step is verifiable against the QA recipient `+918100640044` (see
`.kiro/steering/02-qa-recipient.md`). Nothing here requires a customer send.

### Open decisions for the owner

1. Is the 10-row cut in §11 the right 10? Leave Review and Explore Store are the closest calls.
2. Should the nine missing flows be published on WABA2 (step 8), or is link degradation there
   acceptable? This is the single largest piece of work implied by "one menu".
3. Keep or drop language switching, pending the §9 #13 check.
4. "Visit" as the replacement for "appointment" — confirm, since it will appear in the flow
   title and cannot be changed again without another Meta publish.
