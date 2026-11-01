# Authenticated home-menu WhatsApp template invitations

PR #2012 merged the authenticated sender and workspace logs into `wecare.digital`.
The exact template versions were independently confirmed APPROVED on 2026-10-31.
The original PR recorded production `wecare-customer-profile:live` v42 and
`wecare-whatsapp-business-api:live` v401. **Those were historical values, not the current release.**
On 2026-10-31, the corrected two-function deployment moved
`wecare-customer-profile:live` to **v45** and
`wecare-whatsapp-business-api:live` to **v405**; the sender now recognizes the
F002 internal action. The customer-profile invoke/audit IAM grants remain part
of the contract, and FlowRegistry marks F001/F002 PUBLISHED.
The customer-facing menu must be published through a separate pinned Amplify
release; automated source/registry checks are NOT a substitute for a handset QA send.

## User journey

The public **Subscribe**, **Leave Review** and **Referral** menu rows (plus the same three
per-order menu rows) use clean `/orders/` links, not WhatsApp deep links and
not phone numbers. Sending is a deliberate user-click effect, not a GET side effect.

1. An unmodified click on one of these three menu items stores its allowlisted
   action in same-tab sessionStorage for at most 10 minutes. A modified/new-tab
   navigation, blocked storage, reload, copied link or externally crafted
   `/orders/?service=...` URL **cannot queue a send**. The Orders route strips
   any such legacy parameter without acting on it.
2. If there is no valid customer Cognito session, the existing
   `/auth?return=/orders/` WhatsApp OTP sign-in runs first. The same-tab
   action survives the redirect, and is consumed **once** after sign-in.
3. The client POSTs only `{ "action": "sendProfileUpdate" }`,
   `{ "action": "sendLeaveReview" }` or `{ "action": "sendReferral" }`
   to `/customer/profile` with its access token.
   It never supplies a phone or selected recipient.
4. `customer-profile` verifies the customer session, uses
   `identity_session.phone`, refuses unexpected fields, writes a mandatory
   `customer.template_send.requested` audit event, then calls the existing
   `wecare-whatsapp-business-api:live` Lambda internally.
5. The WhatsApp sender checks the canonical published Flow and compatible
   FlowRegistry row before sending to the authenticated customer. All three approved
   templates use the shared IMAGE header, English language and one FLOW button.
6. Meta acceptance creates an outbound message row with status `pending`,
   WhatsApp message ID and template metadata in both
   `WhatsAppOutboundTable` and canonical `MessagesTable`. A success response
   says **accepted**, not delivered. The webhook progresses status using
   monotonic `sent/delivered/read/failed` transitions, and the Inbox reads the
   canonical MessagesTable.

The action is removed before the send. A network timeout is not automatically
retried, because Meta might have accepted the message. A new menu click is an
explicit retry, which leaves its own audit trail.

## Template mapping

| Menu action | Approved template | Template ID | Flow ID | Behavior |
|---|---|---|---|---|
| Subscribe | `service_details` | `2419125382263851` | `2413873616105042` | F001 profile/address INIT prefill, optimistic save to Contacts, FlowSubmission response |
| Leave Review | `wecare_leave_review` | `1801972550682516` | `993862443003108` | F002 FEEDBACK -> REVIEW, signed inbound `nfm_reply`, idempotent FlowSubmission |
| Referral | `wecare_referal_update` | `1596216325046969` | `1933489271340286` | F008 DATA_EXCHANGE INIT -> REFER, REVIEW -> CONFIRMATION; consent required before signed `nfm_reply` persists one private FlowSubmission |

Subscribe's “View Details” Flow updates profile details. **It is not
marketing subscription consent**, and no marketing opt-in should be inferred
from selecting it. Leave Review does not make an automatic post-purchase send
or alter payment state; it sends only after an explicit customer click.
Referral also requires the referrer's explicit click and never sends an invitation
or marketing message to the referred person. It does not create a contact, grant
marketing consent, or create a payment request.

## Where staff can see it

- **Workspace > Engage > Inbox** (`/workspace/engage/inbox?channel=whatsapp`):
  outbound template messages and provider delivery status; F001, F002 and F008
  `flow_response` messages show answer fields and attachments via
  `FlowResponseDetails`.
- **Workspace > Service > WhatsApp Logs** (`/workspace/service?view=whatsapp-logs`):
  read-only filtered delivery and response history for these three templates,
  including submitted form answers. This view reads the latest 2,000 WhatsApp
  messages and links back to the full Inbox.
- **Flow Hub**: submission status and existing launch funnel counters.
  The existing F002 review data stays private and can be inspected through
  its Flow response; no new public review publication is added.
- **Audit Logs**: `customer.template_send.requested`,
  `customer.template_send.accepted`, `customer.template_send.failed` on
  a customer ID/template ID, with non-PII status and Meta message ID.
  The configured audit retention remains 180 days.

A Meta API acknowledgment is not proof of WhatsApp delivery, nor proof that
the customer finished the Flow. Those are separate webhook/submission facts.


## 2026-10-31 release verification and stale-checkout incident

**Deployment confirmed:** an old CloudShell checkout at
`f2a9e8c3783754c385ea8f8a8798a7cfc61ac076` omitted both
`sendLeaveReview` and `customerLeaveReviewTemplate`. A fleet-wide
`deploy_all_lambdas.py` run restored old packages under new version numbers
(v44 for customer-profile and v404 for WhatsApp API). After a clean
fast-forward to reviewed source commit `8761328a1`, a **two-function-only**
deployment published customer-profile v45 (CodeSha256 beginning `U/cykcFF`)
and WhatsApp API v405 (beginning `QkAQ1kQC`). A no-recipient invoke returned
400 `Invalid customer phone` for both internal actions, proving dispatch
recognition without sending a WhatsApp message. The customer reported that
the Leave Review button works; **Meta delivery status, completion persistence
and replay/idempotency were not established by that report alone**.

**Read-only QA and release gate:**

1. Before packaging, require a clean worktree at a reviewed commit and verify
   `sendLeaveReview`, `customerLeaveReviewTemplate`, `includeTemplateMappings`,
   and `syncTemplateFlowMappings` are present. Compare to the intended reviewed
   commit; do not substitute a stale local branch for a newer approved release.
2. Run `node --test tests/customer_menu_notice_contract.test.mjs` for the
   synthetic one-use-intent, no-recipient-field, ambiguous-failure, exact-copy
   and sender-dispatch regression checks.
3. Run a **named-function** dry run, then a reviewed named-function deployment
   for only `wecare-customer-profile` and `wecare-whatsapp-business-api`.
   Never run the fleet-wide publisher merely to fix a customer-menu action.
   Deploy via a least-privilege release role, not everyday Root credentials.
4. Confirm `:live` aliases and code hashes after publication. Check the
   allowed F001/F002 FlowRegistry mappings and published Meta templates;
   don't relax canonical Flow publication checks.
5. With an authorized test account only, perform one intentional customer
   click and inspect the response, outbound record and webhook status.
   Complete and submit the F002 Flow to verify FlowSubmission/Reviews and Inbox.
   Replay a **captured test webhook in a controlled test harness**, not against
   live customer messaging, to verify idempotency. Do not resend invitations
   automatically after a timeout.
6. Report **accepted**, **sent/delivered/read** and **Flow submitted** as
   distinct states. Do not close the end-to-end QA item solely on an accepted
   send or Lambda dispatch probe.

**Orders toast copy:** Subscribe, Leave Review and Referral use the same three short
messages from `src/lib/customerMenuNotices.ts`: pending **Processing…**,
accepted **Sent to WhatsApp.**, and failed **Couldn't confirm. Check WhatsApp.**
“Sent” describes the provider's acceptance only, not confirmed delivery.
The other Orders menu actions (Submit Request, Request Amendment, Drop Docs,
Vault, Track, Pickup Request) currently navigate without sending an invitation;
they must not show the success toast until backed by an accepted send.
Shipped Orders is outside this toast-copy change. The historical
[`toast-message catalog`](../audits/toast-message-catalog-20261031.md) records
the earlier longer copy. Workspace notifications remain separate.

## Deployment and verification checklist

1. Deploy the clean-URL, explicit-click frontend from a green pinned commit.
   Do not redeploy the active backend Lambdas just to refresh the menu. Confirm
   the customer-profile and WhatsApp sender live aliases remain at the reviewed
   versions, audit/invoke IAM is intact, and both templates remain APPROVED.
2. Sync FlowRegistry with Meta. For F001/F002, the canonical flow contract,
   Meta publication state and Registry configuration must agree. Do **not**
   weaken the publication checks to force a send through a stale registry.
3. Test an unauthenticated menu click: OTP sign-in, exactly one template on
   the authenticated number, no phone in browser request or URL, and no resend
   on refresh/back. Repeat with an authenticated customer.
4. Verify F001's View Details opens PROFILE with prefill; save a harmless
   test edit; check Contacts, one FlowSubmission and Inbox response.
5. Verify F002's Leave Review opens FEEDBACK; submit one test response; check
   FlowSubmission, Reviews and Inbox; replay the inbound webhook and confirm
   no duplicate submission.
6. Confirm the audit request/accept records share the same attempt ID, and
   the provider message ID joins the legacy and canonical outbound rows.
   Observe a real status webhook (sent/delivered/read or failed), not just
   the provider's immediate acceptance.
7. Exercise unauthorized POST (401), extra recipient field (400),
   missing audit store (503 without sending), unavailable Meta/FlowRegistry
   (failure, no false success), and genuine network ambiguity (no auto retry).

No provider send, data migration, phone number change, template edit, Flow
publication or runtime webhook update is part of this PR.

## F008 Referral rollout gate (2026-11-01 proposed change)

The new Referral action uses the same explicit website-click, authenticated
`/customer/profile` action, fail-closed audit, internal Lambda, Meta send,
pending-Inbox and single-use notification contract as Subscribe / Leave Review.
It adds the exact Meta-approved English template spelling
`wecare_referal_update` without renaming it. The image is the existing
`SHARED_TEMPLATE_HEADER`, and the sole FLOW button is `Update Referral`.

The Meta-approved button declares `DATA_EXCHANGE` even though F008's published
REFER -> REVIEW -> CONFIRMATION JSON is otherwise endpointless. The new
`flows.router` route handles the provider's initial `INIT` by returning
`{ "screen": "REFER", "data": {} }`, as F002's authenticated launcher does for
FEEDBACK. **Production acceptance, handset opening, and submission delivery are
not yet verified.** Do not merge or deploy without a controlled test confirming
the F008 Flow opens, the explicit permission control is enforced, and one
signed `nfm_reply` generates a single referrer-owned submission even after replay.

**Copy mismatch to review:** the currently approved template states that a
referral request "has been received" before the customer has submitted F008.
This is Meta-controlled approved copy, so the integration does not silently edit
it. Content owners should consider a separately reviewed initial-referral
template if that wording cannot accurately describe the first click.

Only `wecare-customer-profile` and `wecare-whatsapp-business-api` need a
reviewed named-function release for the backend implementation, plus the pinned
frontend Amplify branch deployment. No registry migration or bulk sender,
post-payment message, unsolicited outreach or automatic retry is part of this
change. Verify current live aliases and hashes before a release, and report
"accepted", "delivered" and "Flow submitted" as separate statuses.
