# Authenticated home-menu WhatsApp template invitations

Feature branch: `feature/authenticated-service-menu-templates-20261031`.
This document describes source changes only. **Not production-deployed** until a
merged/released version and controlled WhatsApp handset QA are confirmed.

## User journey

The public **Subscribe** and **Leave Review** menu rows (plus the same two
per-order menu rows) now point to an internal Orders URL with an *allowlisted*
`service` action, not a WhatsApp deep link and not a phone number.

1. The Orders route reads `service=subscribe` or `service=leave-review`, stores
   that action in same-tab sessionStorage for at most 10 minutes, and removes it
   from the URL. No personal data appears in the URL/storage value.
2. If there is no valid customer Cognito session, the existing
   `/auth?return=/orders/` WhatsApp OTP sign-in runs first. The same-tab
   action survives the redirect, and is consumed **once** after sign-in.
3. The client POSTs only `{ "action": "sendProfileUpdate" }` or
   `{ "action": "sendLeaveReview" }` to `/customer/profile` with its access token.
   It never supplies a phone or selected recipient.
4. `customer-profile` verifies the customer session, uses
   `identity_session.phone`, refuses unexpected fields, writes a mandatory
   `customer.template_send.requested` audit event, then calls the existing
   `wecare-whatsapp-business-api:live` Lambda internally.
5. The WhatsApp sender checks the canonical published Flow and compatible
   FlowRegistry row before sending to the authenticated customer. Both approved
   templates use their actual IMAGE header, English language and one FLOW button.
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

Subscribe's “View Details” Flow updates profile details. **It is not
marketing subscription consent**, and no marketing opt-in should be inferred
from selecting it. Leave Review does not make an automatic post-purchase send
or alter payment state; it sends only after an explicit customer click.

## Where staff can see it

- **Workspace > Engage > Inbox** (`/workspace/engage/inbox?channel=whatsapp`):
  outbound template messages and provider delivery status; F001 and F002
  `flow_response` messages show answer fields and attachments via
  `FlowResponseDetails`.
- **Workspace > Service > Reviews**: private F002 feedback, moderation and
  customer history through existing service components.
- **Flow Hub**: submission status and existing launch funnel counters.
- **Audit Logs**: `customer.template_send.requested`,
  `customer.template_send.accepted`, `customer.template_send.failed` on
  a customer ID/template ID, with non-PII status and Meta message ID.
  The configured audit retention remains 180 days.

A Meta API acknowledgment is not proof of WhatsApp delivery, nor proof that
the customer finished the Flow. Those are separate webhook/submission facts.

## Deployment and verification checklist

1. Merge the feature branch; deploy the public site, the customer-profile
   Lambda and the WhatsApp Business API Lambda **with matching revisions**.
   Verify Lambda live aliases, permissions to audit/outbound/unified tables,
   and that service_details and wecare_leave_review remain APPROVED.
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
