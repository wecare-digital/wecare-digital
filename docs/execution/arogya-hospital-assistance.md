# Arogya Yatra hospital assistance requests

The public route now accepts coordination requests for any hospital. Apollo is
one preference, alongside another named hospital and help choosing. This flow
makes no provider catalogue, login, OTP, patient-lookup or booking-write call.
The existing provider adapter remains inactive and independent of request intake.

The full form and service information are visible without signing in. The existing
shared WhatsApp/Cognito customer session is checked only when Submit request or
View my submitted requests is pressed. A signed-out customer keeps the form open
while completing shared /auth in a separate tab, then returns and submits again.
Form details remain in component memory, not browser storage or URL parameters.
The server still requires a verified customer and account binding for every write
and history read. A changed authenticated owner cannot submit an earlier account’s
frozen request. No anonymous backend intake or inline OTP flow is introduced.
No payment is collected on submission. Existing Arogya checkout guards remain.

## Intake and review

`submitRequest` accepts an immutable client UUID and strict coordination fields.
It writes a customer-owned REQUESTED record and minimal operator queue pointer
in one DynamoDB transaction, using UpdateItem on the existing table and role.
No new resources, indexes, capacity, scheduled work or notification services are
created. The pointer contains no patient data. Both records expire after 30 days;
reads enforce expiry independently of DynamoDB TTL cleanup.

A lost-response retry sends the same UUID and frozen payload. The server returns
the original receipt only for the same owner and normalized payload; changes to
an already-used reference conflict. The form locks an ambiguous submission until
its same-reference retry completes. Receipts always say REQUESTED and explicitly
carry appointmentConfirmed=false. Customer history is owner-bound and paginated.

Authorized operations staff can review requests through the existing AWS IAM
Lambda Invoke surface. No public HTTP staff action or new staff permission is
created. Function URL requests always contain requestContext and cannot enter
these native actions, including through a crafted JSON body:

- `{"internalAction":"listAssistanceRequests"}` returns up to 20 unexpired queue
  pointers, newest first. Pass the returned nextAfter as `after` to continue.
- `{"internalAction":"getAssistanceRequest","customerId":"OWNER_FROM_QUEUE","requestId":"UUID_FROM_QUEUE"}`
  reads that request's coordination details for the authorized operator.

Use the configured AWS account 775261844268 / us-east-1 and function
wecare-arogya-booking. Direct Invoke requires genuine IAM authorization. Review
operators must handle patient details only for the requested coordination, and
must obtain the hospital's acceptance before communicating an appointment as
confirmed. The native queue is the review surface in this release; no staff web
inbox or automatic outbound notification is claimed.

## Customer information

The side panel describes hospital choice, coordination scope, follow-up, fee
policy and the distinction between receipt and hospital confirmation. On desktop
it stays beside the form with its own keyboard-scrollable vertical area. On
mobile it joins the normal page flow. Styling reuses the public Auth foundation.
Any hospital preference is an enquiry, not an asserted partnership or guaranteed
appointment. Provider and travel charges remain separate from the WECARE fee.

## Verification and release

Run focused assistance/ownership Python tests, the public Arogya Node contracts,
typecheck, lint and the production build. Deploy the verified merged Lambda bundle
before the matching website release, preserving ApolloAutomationEnabled=false.
Check native IAM queue access, unsigned HTTP rejection, the public form, service
information and submission-triggered shared WhatsApp sign-in. A genuine customer OTP is needed to exercise a
real customer submission; never fabricate a production customer identity.
