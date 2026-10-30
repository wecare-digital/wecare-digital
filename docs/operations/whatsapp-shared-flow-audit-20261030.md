# Fresh WhatsApp Flow + template audit — 30 October 2026

Scope: all seven retained Flow JSON assets in
`amplify/functions/messaging/whatsapp-business-api/flows/published/`,
the fifteen current WhatsApp templates, the Python Flow router, paid
post-invoice launcher, inbound `nfm_reply` savers, and the published
FlowRegistry records.

## Evidence and the correction to the previous audit

The shared screen contract is **intentional**:

- Submit Request, Request Amendment, Pickup Request, Track Shipping:
  `SELECT_TARGET -> NOTE -> CONFIRMATION`.
- Drop Docs: `SELECT_TARGET -> NOTE -> UPLOAD -> CONFIRMATION`.
- Subscribe: `PROFILE -> ADDRESS -> REVIEW -> COMPLETE`.
- Leave Review: `FEEDBACK -> REVIEW`.

The older tracked `request-pickup.json` had
`SELECT_ORDER -> PICKUP_DETAILS -> REVIEW`, but the owner-supplied
Pickup JSON uses the shared three-screen layout with pickup-specific
fields **inside NOTE**. This change retains that intended shared layout.

The supplied Pickup completion incorrectly used
`flow_key=wd_f004_submit_request` and omitted
`pickup_address`, `preferred_date`, `pickup_window`,
`package_description`. Those fields are now carried from NOTE to
CONFIRMATION and into the terminal `nfm_reply`; the marker is
`wd_f005_request_pickup`.

## Current Meta templates (verified against the company account)

All nine Flow-button template versions are **APPROVED** and their
button action is **DATA_EXCHANGE**:

| Existing template | Status/category | Canonical target | Assessment |
|---|---|---|---|
| `service_details` | APPROVED / MARKETING | F001 | Direct authenticated website session and INIT present |
| `wecare_pdf_direct_download` | APPROVED / UTILITY | F001 | Manual sender must mint authorized F001 session; otherwise INIT refuses |
| `wecare_default_invoice_image_template` | APPROVED / UTILITY | F002 | Review token uses `review-...`; add FEEDBACK INIT for DATA_EXCHANGE |
| `wecare_leave_review` | APPROVED / UTILITY | F002 | Manual sender needs compatible review token or switch back to NAVIGATE after review |
| `_dropdoc_flow` | APPROVED / UTILITY | **mismatch** | Template 39581903361452880 vs canonical 39581903361452878; correct in Meta separately |
| `submit_request_flow` | APPROVED / MARKETING | F004 | Existing paid INIT returned retired ORDER_SELECT; now returns common SELECT_TARGET |
| `request_amendment_flow` | APPROVED / UTILITY | F005 amendment | Existing paid INIT returned retired SELECT_ORDER; now returns common SELECT_TARGET |
| `pickup_request_flow` | APPROVED / UTILITY | F005 pickup | Correct template action; completion previously cloned F004 and had no pickup saver |
| `track_ship_flow` | APPROVED / UTILITY | F006 | Existing shipped INIT returns common SELECT_TARGET; completion still uses F004 marker with guarded `shipments-` token |

Other six templates have no Flow button; no data-exchange action is needed.

## Backend changes proposed in this branch

1. `flows/paid_service_targets.py` verifies a server-issued 24-hour
   session, paid PaymentAttempt, existing OrderTable owner, and
   `serviceActivities` binding, then populates the **single paid order**
   in `SELECT_TARGET`. It does not trust submitted target IDs for INIT.
2. `flows/router.py` routes `srpaid-`, `amendpaid-`, and
   `request_pickup-` sessions to this shared INIT, without removing
   legacy handlers. It recognizes invoice `review-` token on INIT
   and returns F002's static FEEDBACK screen; F002's signed inbound saver
   remains authoritative at completion.
3. `pickup_request_response.py` accepts a **full** Pickup payload
   from an issued Pickup session, verifies the paid attempt/order again
   before persistence, validates pickup fields, writes one durable
   `WD-PU` FlowSubmission per payment attempt, marks session consumed,
   and returns `pending_confirmation` (NOT a courier booking).
4. The inbound WhatsApp handler routes Pickup before the generic Submit
   Request parser and projects a structured Pickup Inbox card.
5. The repository's Pickup JSON now matches the owner-supplied
   `SELECT_TARGET -> NOTE -> CONFIRMATION` layout, includes the four
   pickup fields on each transport hop, and emits an unambiguous F005
   completion marker. All images and content of the supplied form are
   preserved.
6. Regression tests verify routing, order/payment ownership, terminal
   payload fields, schema, strict parser, and duplicate-write prevention.

## Production gates; no automatic activation

**Do not remove the Pickup UI, pre-checkout or sender fail-closed guards
yet.** The tools in this session can read/update WhatsApp *templates*
but do not expose Meta's current **published Flow JSON** or publish
Flow definitions. An APPROVED DATA_EXCHANGE template is not proof that
the underlying published Flow contains the new completion schema.

Before enabling Pickup:

- Publish the updated **Pickup** JSON against Flow ID
  `2988393421499259` (NOT the Amendment ID
  `2408621596338289`). Confirm it is PUBLISHED, decryptable and
  answers INIT with `SELECT_TARGET/targets`; independently inspect
  the actual Meta revision.
- Run automated tests, then deploy and publish the updated inbound
  WhatsApp Lambda and the WhatsApp Business Flow Lambda, and move only
  their verified `live` aliases.
- Test with an authorized account and finalized **test** purchase:
  Meta template received -> Flow INIT -> bound order shown -> pickup
  inputs -> complete -> signed `nfm_reply` -> exactly one `WD-PU`
  FlowSubmission and one structured Inbox card; test retries and
  another customer's order refusal.
- Only after passing this end-to-end gate should checkout,
  service-launch and website blocks be removed together.
- Separately repair the Drop Docs template Flow ID and decide how the
  manual Subscribe and Leave Review templates mint valid Flow tokens.

The Meta template state is an observed state as of the audit; do not
mistake the repo's proposed asset for a live Meta publication.
