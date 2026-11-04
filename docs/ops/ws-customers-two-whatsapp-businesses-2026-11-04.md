# Customers: two WhatsApp businesses, phone-required website identity

Date: 2026-11-04. Scope: /ws/customers, inbound contact identity and customer
registration boundaries. The inbox/send/payment/commerce implementations are
separate release gates, not silently changed by this branch.

## Business requirements

1. The two registered WhatsApp business senders, WECARE.DIGITAL and Manish Agarwal,
   both belong in the customer directory. Meta assigns BSUIDs per business
   *portfolio*, not globally.
2. The customer-facing WECARE.DIGITAL website requires a valid phone and proof
   of possession by OTP for Cognito registration/sign-in and checkout. Possession
   of a BSUID or @username is NEVER equivalent to phone verification and
   NEVER authorizes a purchase, refund, card, invoice, or payment.
3. A WhatsApp user may send a message while hiding their phone. Preserve that
   message under an explicitly provisional WhatsApp contact and leave phone
   absent. Staff may edit non-identity profile fields. They may not fabricate a
   phone, verify a phone, mark marketing consent, or grant shopping eligibility.
4. A phone from a signed contact-request payload is still subject to canonical
   phone uniqueness and strong IdentityClaims checks before association. If it
   belongs to someone else, refuse automatically linking and reconcile.
5. No cross-business BSUID lookup, cross-customer merge, or auto-erasure.

## Verified business mapping (read-only lookup 2026-11-04)

| Business portfolio | WhatsApp Messaging Account | Live sending phone ID | Number |
| --- | --- | --- | --- |
| Wecare.Digital (382642103987922) | 2094615664435155 | 1016149501586345 | +919330994400 |
| Manish Agarwal (125951953587391) | 2513394156072604 | 1055232054343117 | +919903300044 |

The second business also has a distinct messaging account without a registered
sending phone. It is NOT included in the sender-ID mapping. A new sender is added
only after verifying the business portfolio and deploying a reviewed mapping.

The customer registration Lambda and the standalone Cognito WhatsApp OTP sender
are currently pinned to WECARE.DIGITAL's registered number, intentionally.
This change does not authorize OTP sends from the Manish Agarwal number or
change Cognito's `custom:partner_waba_id` binding. Customers from the Manish
WhatsApp channel can become website customers only through the independently
verified WECARE.DIGITAL phone registration route.

## New inbound data contract (additive, no backfill)

Contact stores `whatsappIdentities` as a map keyed by Meta business-portfolio
ID, each value containing `bsuid` and optional `username`, `parentBsuid`,
`contactBookName`. Legacy `bsuid`/username fields remain untouched for old
readers and are never written from the second business.

`IdentityClaimsTable` holds a unique conditional claim keyed by
`WHATSAPP_BSUID#{portfolio_id}#{bsuid}` -> canonical `contactId`.
Unknown sender/account combinations are refused rather than assuming a default
business. A legacy unscoped BSUID may be reattached only if Meta's signed
sender phone matches the existing Contact's canonical phone. Missing or
conflicting evidence routes to the existing replay/reconciliation path; it does
not pick the oldest record. A phone-hidden provisional row's deterministic key
includes the portfolio ID and BSUID, preventing cross-portfolio collisions.

IdentityClaims and Contact profile updates are two DynamoDB operations, not an
atomic cross-table transaction. A retry can repair a claim whose Contact
projection failed; do not claim they are fully atomic. Existing financial data,
orders, messages, contact UUIDs and consent ledgers are never rewritten.

## Quarantined conflicts and replay policy

If a legacy unscoped BSUID is ambiguous or conflicts with a different phone,
the system deliberately refuses automatic identity assignment and places the
exact webhook message in the inbound dead-letter queue. There is **no event
source mapping automatically consuming this inbound DLQ** (verified read-only
in the live AWS account on 2026-11-04). A manual operator must first reconcile
the conflicting contact/identity claim; replaying without correcting ownership
will reproduce the same refusal. The correct remediation is an audited,
authorized identity reconciliation, **never** silently choosing an old row,
returning an unrelated phone owner or reclassifying a payment as a new customer.

The global BSUID fields in historic contacts may originate from either
business. A row without positive provenance must not be assumed to belong to
Wecare.Digital just because it has a BSUID. This can reduce automatic
reconciliation of historical customers, which is intentional until per-business
evidence exists. No bulk backfill or automatic merge is authorized.

This first migration covers only the two known registered business senders.
Unknown Embedded-Signup/partner tenant phone-hidden events are quarantined
pending verified tenant-to-portfolio mapping, not assigned a default
portfolio. Before deploying, confirm partner traffic impact and provide a
separate correctly scoped mapping/reconciliation strategy.

The inbound worker now uses `claim_event_with_lease` and calls
`complete_event` only when a full message processing call returns successfully.
If customer identity resolution fails, the claim remains temporarily leased,
then becomes eligible for retry. It must not be marked completed on the
exception path. Live-layer compatibility, actual DLQ replay after the lease
expires and the existing legacy permanent claims still require staging review.
Events already claimed permanently by earlier deployments are not automatically
migrated or reprocessed.


## Production gate

- Verify final code against **both** signed WhatsApp webhooks, including
  phone-shared, phone-hidden, contact-request, username change and
  previous-user-id system events.
- Exercise (in staging only) the same customer phone across both businesses
  with DIFFERENT BSUIDs, two different people with identical opaque BSUID text
  in separate portfolios, an existing legacy unscoped BSUID, provider phone
  change, duplicate phone, a registry outage and replay idempotency.
- Verify an anonymous/BSUID-only contact is not an authenticated website
  customer, has no phone-verification stamp, cannot enter OTP/checkout by
  BSUID and does not acquire SMS/email/WhatsApp marketing consent.
- Verify both frontend and inbound Lambda code reach the live aliases;
  Amplify's frontend SUCCEED status does NOT deploy Lambda code.
- Do not modify production Contacts/IdentityClaims while validating; read-only
  aggregates are sufficient. No live OTP to real customers, no trial purchases.
- Do not auto-merge old legacy identities, switch the OTP sender, release
  phone claims or delete any DynamoDB/S3 data during rollout.

Open scope after this PR: portfolio-aware outbound send resolution, calling,
Inbox conversation grouping/status mapping and payment-specific routes. Those
cannot inherit a global legacy BSUID and must be independently reviewed.
