# F001 Subscribe (WD-F001-SUBSCRIBE-PROFILE)

One WECARE.DIGITAL capability: a WhatsApp Flow that lets a customer save and update their own
profile and one structured address on their contact record. It is a profile/data-collection
Flow, not a marketing subscription, and it never grants consent.

| Item | Value |
|---|---|
| Flow number / code | F001 / `WD-F001-SUBSCRIBE-PROFILE` |
| Customer-facing name | Subscribe |
| Meta Flow ID / name | `2413873616105042` / `WD-F001-SUBSCRIBE-PROFILE` (PUBLISHED in Meta, immutable) |
| WABA | WABA 1 (`2094615664435155`, +91 93309 94400) only. A WABA 2 (+91 99033 00044) customer gets a button to `https://wa.me/919330994400?text=subscribe`, which opens WABA 1 with the keyword typed. (`/r/sub` was a ShortLinksTable recovery row redirecting to google.com; on 2026-10-25 it and `sr`, `ar`, `rx`, `ea`, `lr` were repointed through the shortener's `PUT /links/{code}`.) |
| Definition | `amplify/functions/messaging/whatsapp-business-api/flows/published/subscribe.json` (Flow JSON 7.3, data API 3.0) |
| Endpoint | `https://wecare.digital/api/wa-business/flow-data` |
| Handler | `flows/subscribe_profile.py` (the only handler for `subscribe*` tokens) |
| Contract | `CANONICAL_CONTRACTS['subscribe']` in `lambda_utils/canonical_flows.py`, twin in `src/lib/canonicalFlows.ts` |
| Workspace | Communications → Manage → WhatsApp → Auto response → Subscribe (control surface); Flow Hub (`?view=manage&section=flows`) for history |
| Verification | `python3 scripts/check_f001_subscribe.py` (59 offline checks) and `python3 scripts/validate_flow_json.py` |

## Entry model

Primary entry is `keyword_interactive`: inside the open customer-service window the customer
types one exact keyword (default `subscribe`, `signup`, `sign up`, `register`, `join`,
`/subscribe`; matching is the whole message, case-insensitive), and the inbound Lambda sends a
native Flow message. No template, no payment, no internal event. The contract rejects any
registry row that says otherwise, and the generic keyword loop refuses to open F001 under any
other trigger key. The previous generic `feedback_survey_form_1` template was deleted on 2026-10-25 because its
NAVIGATE button bypassed INIT and had no verified Flow session. Its definition is preserved in
`docs/execution/snapshots/whatsapp-template-feedback_survey_form_1-20261025.json`.
The former authenticated Orders-page profile icon was retired from the customer UI on
2026-10-31. Customers now use the canonical Subscribe WhatsApp destination from the public
navigation or their Orders actions menu. The backend's session-backed profile-update action
remains implemented for controlled callers; it must not bypass INIT.

A staff send is the controlled QA/support door, not a second entry mode: Operator or Admin,
one customer at a time, recorded with the sender's identity, available before keyword launch
is switched on. It uses the same published Flow, copy and session rules.

## Former authenticated Orders-page profile update (legacy backend action)

Before the icon was removed from `/orders/` on 2026-10-31, its authenticated button invoked
`POST /customer/profile` with `action: sendProfileUpdate`. The profile Lambda passed only
the session-owned phone to the internal WhatsApp sender. The sender checks that F001 is
PUBLISHED, mints a 24-hour one-use F001 session, and sends the approved Utility template
with a Flow button. That backend action remains available but the Orders page no longer
invokes it or shows the old lime response toast; the customer-facing Subscribe entry now
uses the verified WhatsApp link. Message acceptance never proves a saved profile.

The existing `service_details` template (Utility, English, image header,
"View Details" button) was originally approved with a `NAVIGATE` action. The
`flow_action_data` sent alongside that action has not reliably populated optional
fields on the handset, even though the customer record contains them. On 2026-10-30
the owner requested **editing this existing template in place**, not switching to a
new template. In-place edits require an explicit Meta confirmation and are
re-submitted for review; the category may change after review.

**Meta-only button change:** retain the original template ID and name, image,
body text, footer, and button label/Flow ID. Change only the FLOW button
from `NAVIGATE` (screen `PROFILE`) to `DATA_EXCHANGE` (omit
`navigate_screen`). On tap Meta must call `INIT` on
`/wa-business/flow-data`; `flows/subscribe_profile.py` validates the session,
reads the canonical contact and returns PROFILE and ADDRESS values, including
optional username, organization, job title and address fields. The published Flow
already has the required `init-values` bindings.

**Production send mismatch observed 2026-10-31:** The existing `service_details` template was read live and is APPROVED / UTILITY with a `DATA_EXCHANGE` Flow button. At 02:08:15 and 02:08:24 UTC, Meta rejected the Orders-triggered send with 400 / 131009. The website sender had been adding `flow_action_data` for an existing contact; this is incompatible with the template's DATA_EXCHANGE entry behavior, where INIT owns prefill. The draft fix retains only the one-use `flow_token` in the outgoing template button and keeps the identity-conflict guard. Verify a controlled send and F001 INIT after deployment before claiming resolution.

**Activation gate:** inspect `service_details` again in Meta after approval:
the template must be APPROVED and its FLOW button must use
`DATA_EXCHANGE`. Review its category; a separate test template was reclassified
as MARKETING despite using the same body text. Do not route or send a pending
or rejected template. No Lambda template-name switch is needed. Verify a signed
`flow_endpoint_signature`, a `flow_funnel init_received` and `init_success`,
optional-value prefill, and a successful REVIEW save from a controlled handset.
If it fails, inspect the Data Exchange logs before changing any customer data.
The former Orders-page success toast confirmed message acceptance, not completion of
the customer's profile update.

## Launch controls

A customer can open F001 only when every control agrees (`lambda_utils/flow_launch.py`):

1. Canonical record (code) is `PUBLISHED`.
2. FlowRegistry row exists, is `PUBLISHED` and matches the contract (Admin changes it).
3. Meta status from the last "Sync from Meta" is `PUBLISHED` or `THROTTLED` (sync writes
   `metaStatus` and never the registry `status`).
4. For keyword launch only: the Workspace keyword switch (`flow_triggers_config.subscribe.enabled`) is ON.

Every Flow message carries a server-issued session (`lambda_utils/flow_sessions.py`): 128-bit
token, recorded in FlowDraftTable as a digest before the message is sent, valid 24 hours and
for one save. INIT and REVIEW verify it. An unknown, edited, expired, other-capability, WABA 2
or already-used token is answered with HTTP 427, which shows a message on the handset and
disables that message's button.

## Screens

| Screen | Title / heading | Fields | Action |
|---|---|---|---|
| PROFILE | Subscribe | Full name (required, 200), WhatsApp username (optional, 50), Organization (optional, 200), Job title (optional, 200); shows the linked WhatsApp number | navigate → ADDRESS |
| ADDRESS | Address / Your address | Street address (required, 200), Apartment / suite / unit (200), Landmark / neighborhood (100), City (required, 100), State / region (required, 100), Postal code (required, 100), Country (required, 195 options, India first) | navigate → REVIEW |
| REVIEW | Review | Read-only summary; `error_message` shows corrections | data_exchange (save) |
| COMPLETE | Subscribed (terminal) | Confirmation and Customer ID | complete |

The opening message, button and confirmation are the New / Returning customer copy in
`subscribe_messages_config` (returning = a saved address exists). Validation never returns
COMPLETE; it returns REVIEW with copy that names the field and the screen, for example
"Please keep your WhatsApp username within 50 characters. Go back to Subscribe to correct it."

## Field contract

| Flow field | Backend key | Contact field | Prefill | Customer edits | Owner |
|---|---|---|---|---|---|
| Full name | `full_name` | `name` | contact row | yes | customer-declared |
| WhatsApp username | `username` | `profileUsername` | contact row | yes | customer-declared; never the Meta `username` |
| Organization | `company_name` | `companyName` | contact row | yes | customer-declared |
| Job title | `designation` | `designation` | contact row | yes | customer-declared |
| Address fields | `address_line1` … `postal_code`, `country` | `checkoutDeliveryAddress` (+ derived flat columns) | saved address; India for new | yes | customer-declared; website validator; any country |
| Linked WhatsApp number | `phone_number` | `phone` | session | no | WhatsApp-verified identity |
| Customer ID | `customer_id` | `customerUuid` (shown as `C-…`) | contact row | no | server-minted once |
| Revision guard | `profile_revision`, `updated_at` | `subscribeProfileRevision`, `updatedAt` | contact row | no | system |

Never written by F001: `username`, `bsuid`, `parentBsuid`, `customerUuid` (except minting once
when absent), `subscriberId`, `locked*`, merge state, `optIn*`, `allowlist*`, `consentLedger`.
Written fields get `fieldSources = FLOW_SUBMISSION` provenance.

A retention lock (`locked`) protects a contact from deletion and merging; it is not an edit
freeze. Locked and paid customers can still keep their own name and address current. No field
in F001 needs human approval, so there is no approval queue.

## Save rules

- Identity is the session's phone, never a phone or Customer ID in the form.
- Existing contact: conditional update on `updatedAt` and `subscribeProfileRevision`; a profile
  edited elsewhere since INIT is refused ("Your profile changed…").
- New contact: phone claimed in IdentityClaimsTable, then one `wa{digits}` row created with
  server-minted `customerUuid`, `subscriberId` and creation lock. A phone claimed by another
  profile, or a soft-deleted row, is refused, never duplicated or resurrected.
- Retry of the same session never repeats the mutation. If the save succeeded but history did
  not, the customer is asked to tap Save again and the retry only writes history.
- History: one FlowSubmission row (`flowCode WD-F001-SUBSCRIBE-PROFILE`, reference `WD-SUB-…`,
  `status completed`, `paymentRequired false`, `channel whatsapp`, `launchChannel`, `requestId`,
  `completedAt`, sanitized form), one Inbox `flow_response` with explicit labels, one CRM lead.
  Rows before this release used `WD_SUBSCRIBE`. ContactsTable stays the current profile;
  history is never used to prefill.

## Observability

FlowLogTable holds a per-day funnel row per Flow (`funnel#WD-F001-SUBSCRIBE-PROFILE#YYYY-MM-DD`):
launch attempted / blocked / redirected / sent / failed, INIT received / success / rejected /
failed, review rejected, validation failed, stale write refused, save refused, save success,
history failed, COMPLETE returned, client error reports. Counters only; each event also logs
one `flow_funnel` JSON line without customer data. Flow-log breadcrumbs now keep field shapes,
not values, and mask the token.

Every `/flow-data` request also logs one `flow_endpoint_signature` line (`verified`, `reason`):
whether Meta's `X-Hub-Signature-256` matched either WABA app secret. It is observe-only and
never changes the answer. Enforce it (HTTP 432) only after real traffic shows every genuine
request as `verified: true`.

### When "subscribe" gets no Flow

- `unsupported_or_new_message_type` with error 131051: WhatsApp delivered the message without
  its content, most often because disappearing messages are on for that chat (also polls and
  some GIFs). Keyword routing never sees text, so no Flow can open. The customer now gets one
  `unreadable_hint_sent` reply a day asking them to turn disappearing messages off and resend
  as text; such messages are no longer marked read or reacted to (Meta refuses both).
- `generic_flow_phone2_cta_sent` with `flowKey: subscribe`: the message reached WABA 2, which
  has no F001 Flow; the customer gets the WABA 1 link above.
- `flow_funnel` `launch_blocked` with a `reason`: a launch control said no (see Launch controls).

Other keyword doors use the same rule: a Flow is sent only when FlowRegistry shows it live on
Meta (`metaStatus` PUBLISHED or THROTTLED, from Sync from Meta). Otherwise the door answers
with its `FLOW_LINKS` website link (`keyword_flow_link_fallback`) instead of a Flow that Meta
would refuse after the handoff.

## Who can change what

| Change | Minimum role | Enforced in |
|---|---|---|
| Keyword switch and keywords (`flow_triggers_config`), Subscribe copy (`subscribe_messages_config`) | Operator | `ai-config-management` (`OPERATOR_WRITE_KEYS`) |
| Staff send to one customer | Operator | business API `/messages/send/flow` |
| FlowRegistry row, publish/deprecate, Flow metadata update (`PUT /flows`) | Admin | business API |
| Sync from Meta (writes `metaStatus` only) | Operator | business API `/flows/sync` |
| WhatsApp webhook subscription change (`POST`/`DELETE /webhooks`) | Admin | business API |
| Read launch status, funnel, Flow metadata and assets | Viewer | business API |

## Activation runbook

1. Validate locally: `python3 scripts/validate_flow_json.py` and `python3 scripts/check_f001_subscribe.py`.
2. Confirm the published Meta asset equals `published/subscribe.json` (`GET /wa-business/flows/assets?flowId=2413873616105042`
   returns Meta's short-lived download link) and Meta validation errors = 0 (`GET /wa-business/flows?flowId=…`).
3. Deploy `wecare-whatsapp-business-api` and `wecare-inbound-whatsapp` with `scripts/deploy_all_lambdas.py`
   (publishes versions and moves `live`), then `scripts/check_deployed_source.py` for both functions.
4. Run "Sync from Meta" so the registry row records `metaStatus` (existing rows are updated;
   a Flow first seen as DEPRECATED is not registered).
5. In the Subscribe panel: Register F001 in FlowRegistry (DRAFT), check the contract shows "Consistent", then Mark registry PUBLISHED (Admin).
6. Controlled QA with "Send to a customer" on a test number: open, prefill, a validation error, a save, a retry, and a reopen (expect the expired-link message).
7. Turn customer keyword launch ON and test one keyword from a handset.
8. Watch the funnel; turn the switch OFF or return the registry to DRAFT to stop launches without a deploy.

Deploy note: Subscribe messages sent before this release carry tokens without a session and
will be answered with the expired-link message; the customer simply asks again.
