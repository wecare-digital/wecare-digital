# Vault: one verified purchase, one selected file

Owner request, 2026-10-08: connect Vault's Wix purchase to a backend-uploaded file, send `wecare_share_pdf`, then `wecare_leave_review`, and align customer and workspace surfaces. Working assumption: one selected file per purchase. An optional clarification was presented; no alternative was supplied during implementation.

## Live template facts

Meta API verified `wecare_share_pdf` (4286155041519312, en, UTILITY, APPROVED): IMAGE header, no body variables, static Access Vault URL `https://wecare.digital/vault`. It cannot attach a PDF in its header. `wecare_leave_review` (1801972550682516, en, UTILITY, APPROVED) opens published review Flow1578178897413815 on FEEDBACK. Only these approved templates are used by the new notification sequence.

## Customer journey

1. Staff upload and confirm a private file in workspace Secure Files. Incomplete uploads are not purchasable.
2. Customer signs in with the existing WhatsApp session and selects an active owned file on `/vault/`.
3. `/services/request-intent` accepts VAULT plus fileId. It verifies Cognito's phone verification and exact subject, adopts a legacy phone-owned file only through that verified session, and rejects a conflicting permanent owner.
4. Existing Wix checkout charges the Vault variant (`dcff995e-448c-493a-9259-f6a82ccdc2b4`) of WECARE.DIGITAL Services. The page and checkout use live Wix pricing, currently described by the owner as INR49, plus the existing checkout convenience fee. There is no second secure-file payment.
5. Verified payment/order reconciliation activates a file-bound Vault request. The backend re-reads PAYREF, PAYMENTATTEMPT, request and private file ownership before committing one deterministic paid access grant for that request.
6. The backend sends the approved file-ready image template. If a confirmed PDF rendition exists and the linked customer's last inbound message is within 24 hours, it also sends a separate ordinary PDF document message. Outside that window the approved Access Vault button leads to the authenticated download. The backend then sends the approved review template.
7. `/vault/` displays the paid grant as Download your file. The existing single-use download endpoint issues the private 60-second download URL. A forwarded link cannot authorize a different permanent owner. Every new Vault purchase remains an ordinary order in the central all-order directory.

This is one guided purchase/access/review journey. File-ready notification, PDF attachment and review invitation are separate WhatsApp messages. This implementation does not claim to embed all of them inside one Meta Flow screen or to add native in-chat catalog payment for services; checkout remains the established Wix website path.

## Records and UI

| Table | Authoritative purpose |
| --- | --- |
| OrderTable | All product and service orders; permanent customer ID and profile WhatsApp phone; Vault purchase order number |
| WixOrderIds | Verified payment reference and matching checkout/order claim |
| ServiceRequestsTable | File-bound Vault intent and paid request; selected file, request number, purchase order, READY/FILE_UNAVAILABLE, notification/document/review claims |
| SecureFilesTable | Private upload, active status, permanent owner adoption, latest paid grant and purchase/request numbers |
| DownloadGrantsTable | One paid grant per request/file, customer ID, owner phone, purchase order, consumed state |

The public Vault page uses the current site typography, green/lime pill button, rounded file cards and responsive layout. Existing paid access gets a Download CTA rather than checkout. Workspace Secure Files gains a Vault purchase column with payment status, order number and request number. Customer Orders request rows show the file and access status.

## Failure and replay behavior

No active owned file means no purchase CTA. Wrong owner, incomplete upload or unverified phone is refused before checkout. Missing payment proof, incorrect purchase order or a revoked/reassigned file grants no access. An unavailable file after payment leaves the paid request available for staff resolution; it does not collect another payment.

Grant commit checks file and request ownership transactionally. Payment replays reuse the same grant. Each WhatsApp step claims SENDING before send, then ACCEPTED or SEND_FAILED. ACCEPTED steps are skipped on replay; SENDING and failed claims require staff reconciliation, avoiding blind duplicates. Review is not sent after a rejected ready notification or failed eligible PDF send. ACCEPTED is API acceptance, not proof the handset delivered/read the message. Historical request-targeted Vault purchases remain supported by the original request store, but only newly file-bound purchases have automatic file access.

The older secure-file payment switch remains off and the older configured delivery template remains untouched; the new path uses the already verified Wix order and its own approved messages.

## Verification and deployment

16 new Vault tests passed. 109 focused tests passed against the exact patched business/service/secure-file handlers and packaged business shared helpers, including paid proof, ownership, file choice, one grant, template order, service-window behavior, duplicate suppression and permanent-owner download checks. Existing source suite: 193 tests including secure-files and IAM. Frontend: 40 focused tests; TypeScript and production build passed. An over-broad first exact-package test harness also tried unrelated historical static source assertions against a partial archive tree; those assertions lacked repository-only files and/or expected newer unrelated delivery-template source. The final focused package run checks changed behavior and preserves those unrelated baseline modules.

Deployment packages patch preserved live archives; service-requests' older shared pricing modules are aligned with the already committed live-Wix pricing source so the new intent/store imports remain compatible. Additive IAM grants only GetItem/UpdateItem on SecureFilesTable to the service-request role; the source provisioner and exact-resource policy file track it. Rollback baselines: business API72, service requests2, secure files30. Final aliases will be recorded after API verification.

No customer QA send, real capture or refund was performed. An owner-nominated recipient and an uploaded test file are still needed for a real payment-to-download-to-review acceptance test.

## Dynamic download button

Create a new utility template with button label `Download file`, URL type Dynamic, and URL:

`https://wecare.digital/vault/?file={{1}}`

The runtime button text parameter is ONLY the selected SecureFilesTable `fileId`. Example full URL for template setup: `https://wecare.digital/vault/?file=sample-file-id` (a format example, not a paid downloadable file). Never put a phone number, S3 key, session token or complete signed URL in this variable. Meta's official hosted ButtonParameterObject reference specifies a text suffix appended to the predefined URL prefix: https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/types/button_parameter_object/ . The SDK reference is archived; validate the newly created template in the current Manager before enabling it.

The page restricts the view to that customer's owned selected file, keeps a validated non-secret pointer in session storage through the existing canonical `/vault/` sign-in return, and requires an explicit Download click. Invalid pointers are discarded. A missing or foreign file exposes no file details and offers no purchase. The fixed existing template remains in use until the new template is approved and its exact name is configured in the sender; a new dynamic sender component is still pending.

A direct S3 URL would expire and is a bearer token reusable until expiry. The permanent Vault entry URL does not expire because of an S3 signature; the actual active file and unused paid grant still must exist. Current grant redemption consumes the grant before returning a 60-second S3 URL. If the customer waits too long or loses connectivity after redemption, staff must resolve access rather than requiring another payment. Automated safe retry/reissue is a follow-up improvement, not implemented in this change. AWS documentation: https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html .

Deployment API calls confirmed live aliases business API73, service requests3 and secure files31. Final independent alias/auth verification was not executed: automatic approval review failed because workspace credits were exhausted, not because the operation was found unsafe. No alternative AWS execution path was attempted. The additive `vault-file-selection` inline IAM policy is tracked separately from the canonical request policy to match the actual deployment. Updated frontend gates: 43 focused tests, typecheck; updated Vault/IAM source gate: 25 tests passed.
