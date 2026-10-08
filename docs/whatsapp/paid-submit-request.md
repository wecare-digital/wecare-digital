# Paid Submit Request and the central customer order directory

Implemented 2026-10-08. Meta draft: `WD_Submit_Request_Paid_v1`, ID `1107164111921876`.

## Records and ownership

`stack-wecare-digital-OrderTable` is the central directory for all checkout order kinds, including products, Submit Request, Request Amendment, Drop Docs and Vault. New authenticated checkout attempts retain the verified profile phone; finalization copies it as `customerPhone` together with permanent `customerId`. CRM contact deletion does not delete this independent directory. Identity ownership, rather than an editable contact row or an unverified phone supplied in the Flow, authorizes access.

The order selector queries `customerId-createdAt-index`, reads each candidate consistently, and verifies exact owner identity. It offers the latest 100 earlier orders across all product and service types. The newly paid Submit Request purchase is excluded from the earlier-order list. The live central table and the Wix orders endpoint both returned zero orders during this inspection; there were no historical orders to import. Legacy records without a verified customer identity need an explicit ownership migration rather than an unsafe phone substring match.

| Record | Meaning | Relationship |
| --- | --- | --- |
| A | Earlier product or service order selected by customer | `parentOrderId` on the request |
| B | Newly purchased Submit Request service order | Request `orderId`; projection `serviceOrderId` |
| P | Verified payment and checkout attempt | Pays B, never implicitly pays A |
| R | Service request and submitted details | Links A, B, P and the permanent customer identity |

The request is authoritative in `stack-wecare-digital-ServiceRequestsTable`. After details are saved, `stack-wecare-digital-FlowSubmissionTable` receives a token-free workspace projection with the selected order, service purchase order, subject, description, request number and verified contact/phone when present. Missing optional GSI keys are omitted. The projection is retryable on reopen; successful saved details are idempotent.

## Payment then a separate details Flow

The existing Wix Submit Request variant is `e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b` under product `df976a0a-f582-4535-b2e1-d532f348bd27`. Pricing remains authoritative in the existing checkout path (verified live as INR 99); the Flow contains no charging code.

After verified payment and a matching order claim, the activation dispatch invokes the existing service activation handler and independently invokes an internal paid-Flow preparation action with only reference, attempt and order identifiers. The backend checks service variant, paid status, owner, payment reference, checkout claim and service purchase order before issuing an opaque capability.

Published-Flow invitations require an enabled Cognito customer with a unique verified phone, an active contact tied to the same permanent owner, and a last inbound WhatsApp message within 24 hours. The action is rejected through public HTTP-shaped calls. A conditional invitation claim prevents automatic duplicate sends. An ambiguous outbound result remains claimed for staff reconciliation; no blind retry is issued.

The catalog handoff continues through the website cart. A missing Submit Request intent is now created before checkout for an eligible one-unit service line; the basket is preserved. Direct native catalog payment-message checkout still refuses service products and is a separate integration gap.

## Screens and failure behavior

The draft contains Select order, Subject, Details, Review and saved confirmation, plus explicit unavailable/no-order screens. Submit performs a transactional owner check on the earlier order and a once-only update of the paid request. Back navigation does not save. If no earlier order is available, the paid request remains awaiting details; the customer is not charged again and can reopen after staff resolve the order directory. Capability tokens are redacted in logging and excluded from workspace projections.

## Deployment and validation

Live aliases after the scoped deployment: `wecare-checkout:live` 32; `wecare-whatsapp-business-api:live` 72; `wecare-razorpay-webhook:live` 53. Original rollback versions: checkout 31, business API 69, webhook 52. Packages were built by patching the preserved live archives rather than replacing unrelated concurrent changes. SnapStart remains off. Additive IAM is recorded in `scripts/iam-paid-submit-request.json`.

Validation covered all order types, verified-phone persistence, separate purchase/parent order IDs, foreign ownership rejection, payment proof, token tampering, once-only saves, Back behavior, missing orders, workspace projection, recipient validation and invitation claims. Exact checkout package: 98 passing tests; final Flow package: 15 focused passing tests after final recipient guards (72 passed before those guard additions). Frontend: 43 passing tests, typecheck and production build passed; ESLint had zero errors and existing warnings.

## Pending release work

- Meta Flow is DRAFT with zero validation errors. Draft status suppresses customer invitations; publication and an owner-supplied QA recipient remain required before claiming customer readiness.
- An approved utility template tied to this Submit Request Flow is needed for invitations outside the 24-hour window. Existing review/payment templates are not substituted.
- Native in-chat catalog service payment requires its own integration; the current working handoff is website checkout.
- Invitation failures or ambiguous accepted sends require staff reconciliation. No customer payment or live QA send was performed in this run.
