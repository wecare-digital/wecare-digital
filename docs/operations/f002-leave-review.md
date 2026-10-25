# F002 — Leave Review / Customer Idea

## Product contract

| Field | Value |
|---|---|
| Flow number | F002 |
| Customer-facing name | Leave Review |
| Internal Flow code | WD-F002-LEAVE-REVIEW |
| Meta Flow ID | 993862443003108 |
| Meta name | WD-F002-LEAVE-REVIEW |
| Purpose | Let a WhatsApp customer send one private idea or piece of feedback to WECARE.DIGITAL. |
| Type | feedback |
| WABA | WABA 1 — 2094615664435155 |
| Primary entry model | keyword_interactive |
| Entry template | none |
| Payment required | no |
| Submission prefix | WD-IDEA |
| Legacy history codes | WD_IDEA, WD_REV |

The live FlowRegistry readback on 2026-10-25 shows this Flow PUBLISHED, Meta status
PUBLISHED, zero validation errors and sendable health. Historical files naming
1578178897413815 describe an older retained Flow snapshot and are not launch authority.

## Entry and launch authority

F002 has exactly one primary entry model: `keyword_interactive`.

The configured exact-match defaults are:

`leave review`, `leave a review`, `review`, `reviews`, `feedback`,
`leave feedback`, `give feedback`, `share feedback`, `rate`, `rate us`,
`rate service`, `rating`, `ratings`, `testimonial`, `write a review`,
`give a review`, `share your experience`, `how was it`, `⭐ leave review`.

The launch is allowed only when all four controls agree:

1. canonical flow status is PUBLISHED;
2. FlowRegistry status is PUBLISHED and its Meta sync is sendable;
3. FlowRegistry matches the F002 contract: keyword_interactive, no template, no payment,
   flow code WD-F002-LEAVE-REVIEW and prefix WD-IDEA;
4. the runtime SystemConfig trigger is explicitly enabled.

Meta publication alone does not activate the keyword door.

The commerce invoice journey is separate. An approved invoice template may contain its own
Leave Review Flow button. F002 does not send `wecare_leave_review` as a standalone
post-payment message and does not become payment-gated because commerce can link to it.

## Meta Flow

Source: `amplify/functions/messaging/whatsapp-business-api/flows/leave-review-flow-v2.json`.

| Screen | Purpose | Fields/data | Navigation | Terminal |
|---|---|---|---|---|
| FEEDBACK | Collect one private thought and its topic. | topic, idea | Next to REVIEW | no |
| REVIEW | Show the customer's thought and explain that submission is private. | topic, idea | Complete | yes |

The completion payload contains `flow_key=wd_leave_review_v2`, `schema_version=4`,
`topic` and `idea`. Visible and accessibility branding uses WECARE.DIGITAL.

This Flow is endpointless. It opens with `navigate`, not `data_exchange`; there is no
customer profile prefill step and no Contacts mutation.

## Data contract

| Flow field | Backend key | Canonical storage | Prefill | Write policy | Validation / trust | Workspace |
|---|---|---|---|---|---|---|
| Topic | topic | FlowSubmission.formData.topic + category | none | customer-owned | accepted topic enum; unknown values normalize to other | Reviews / Flow responses |
| Idea | idea | FlowSubmission.formData.idea + reviewText/description | none | customer-owned | required non-empty string | Reviews / Flow responses |
| Flow key | flow_key | routing only | Flow JSON constant | read-only | system-defined | not editable |
| Schema version | schema_version | schemaVersion | Flow JSON constant | read-only | system-defined | diagnostic metadata |
| Phone | phone/customerPhone | FlowSubmission top-level | trusted inbound sender | protected | never accepted from Flow payload | Inbox / customer timeline |
| Contact ID | contactId | FlowSubmission top-level | trusted contact resolution | protected | server-owned | customer timeline |
| Customer UUID | customerUuid | FlowSubmission top-level when available | trusted identity | protected | server-owned | customer timeline |
| WhatsApp message ID | whatsappMessageId | FlowSubmission top-level | inbound webhook | protected | server-owned; retry identity | operational history |

No consent field exists. F002 never manufactures marketing consent.

## Save, retry and identity behavior

The inbound handler recognizes only an interactive `nfm_reply` whose
`flow_key` is `wd_leave_review_v2`. It resolves the trusted sender before saving.

The submission ID is derived from the trusted contact ID and WhatsApp message ID.
`flow_completion.claim_completion` performs the conditional claim, so webhook replay does
not create a second review or overwrite the first review. New rows use
`WD-F002-LEAVE-REVIEW`; readers continue accepting legacy `WD_IDEA` and `WD_REV`
rows.

F002 does not update Contacts, protected identity, payment state or consent. There is
therefore no stale-profile write problem and no approval queue.

## Completion and Workspace

FlowSubmission is event/history truth for F002. The current contact remains Contacts truth.

The record includes the submission/reference ID, F002 flow code, customer_idea flow type,
trusted contact and phone, submitted status, timestamps, sanitized topic/idea data, channel,
request ID and WhatsApp message ID where available.

Workspace already exposes this capability in:
- Flow Hub / flow responses;
- Customer Service Hub, marked Published;
- Inbox as a Leave Review Flow response;
- Reviews/customer timeline, where the feedback is explicitly private.

Moderation/status controls do not publish the review, send a reply or create consent.

## Observability

Required launch controls and history are available through the unified Flow Hub. Operational
logs must not log raw idea text, phone numbers or other personal data. The submission write is
idempotent; retry safety is part of the data contract rather than a best-effort UI behavior.

## Deployment sequence

1. Land the F002 canonical contract and compatibility readers.
2. Deploy backend/frontend and verify the live aliases.
3. Sync the live FlowRegistry row from Meta.
4. Change the FlowRegistry row to the canonical F002 flow code/prefix and
   `entryMode=keyword_interactive`, with no template and `requiresPayment=false`.
5. Verify registry validation passes and Meta still reports PUBLISHED/sendable.
6. Add/enable the F002 entry in `flow_triggers_config`.
7. Perform a controlled WABA 1 keyword QA.
8. Verify one FlowSubmission row, one Inbox projection and no duplicate on webhook replay.
9. Broaden availability.

Do not enable step 6 before steps 1–5 are live.

## QA matrix

| Component | Status | Evidence | Remaining risk |
|---|---|---|---|
| Meta Flow | READY | Live registry sync: 993862443003108, PUBLISHED, zero validation errors | Real handset QA still required after runtime enable |
| Canonical registry | READY IN CODE | F002 contract added to Python + TypeScript twins | Must deploy |
| FlowRegistry | BLOCKED | Live row exists and is healthy but still uses legacy flowCode WD_IDEA and lacks the F002 entry contract | Canonicalize after deploy |
| SystemConfig/runtime | BLOCKED | flow_triggers_config currently contains only F001 Subscribe | Enable F002 only after registry canonicalization |
| Backend completion | READY IN CODE | customer_ideas writes through claim_completion | Must deploy |
| Data exchange | N/A | Endpointless Flow; static navigate entry | Do not change to data_exchange |
| Contacts | READY | No Contacts mutation; trusted contact ID/phone are attached server-side | none |
| Identity protection | READY | Sender identity comes from inbound webhook/contact resolution | none |
| Consent | READY | No consent field or consent write | none |
| Payment gate | READY | requiresPayment=false; no payment mutation | none |
| Template | READY | No entry template for primary entry; no standalone review template send | Keep commerce invoice behavior separate |
| Inbound routing | READY IN CODE | Exact-match F002 keyword contract | Runtime switch still off |
| Outbound sender | READY | Native interactive Flow after customer keyword within service window | WABA 1 only |
| Workspace | READY IN CODE | Customer Service Hub corrected to Published; Flow Hub registry-driven | Must deploy |
| Inbox | READY IN CODE | F002 and legacy codes render as Leave Review | Must deploy |
| Submissions | READY IN CODE | New canonical code + legacy read compatibility | Must deploy |
| Analytics | READY | Unified FlowSubmission/Flow Hub path | Historical WD_IDEA remains separate code unless aggregated |
| Tests | READY IN CODE | Focused F002 checker added with contract and JSON guards | Run in deployment pipeline |
| Deployment | BLOCKED | Branch is not yet merged/deployed | Merge/deploy required |
| Live alias | BLOCKED | Current live aliases predate this F002 contract | Verify after deployment |

Production verdict: **BLOCKED** until the branch is deployed, the live FlowRegistry row is
canonicalized, the runtime trigger is enabled, and controlled handset QA succeeds.
