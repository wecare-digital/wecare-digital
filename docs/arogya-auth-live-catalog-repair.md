# Arogya Yatra access and live catalogue repair

## Changes
- Gate the planner using the shared website WhatsApp authentication flow. A successful authenticated booking API quote (no charge, no patient record) confirms the customer is phone-verified before mounting patient fields.
- Preserve an exact Arogya Yatra return in the frontend and backend auth allowlists.
- Use the public site typography, underlined form controls, and action styling; remove the duplicate OTP form.
- Request hospitals, specialities, doctors, health checks and appointment dates from the authenticated catalogue API, using provider identifiers. Unknown, missing, stale or unavailable provider data must not fall back to a snapshot.
- Continue to label time and admission dates as preferences. The known provider API supplies appointment dates, not verified time-slot availability. Drafts remain drafts; no provider booking or payment is performed.

## Release and activation blockers

The AWS account was checked on 27 November 2026: the booking Lambda had only its original draft configuration, and the workspace registry had no Apollo Gmail OAuth authorization row. The catalogue cannot be activated until a staff administrator completes the approved Google OAuth flow for the intended business mailbox and the approved Apollo server-side integration has a verified, renewable session. No credentials from the build transcript are stored in this branch.

The read-only adapter uses the existing registry and KMS key, if explicitly enabled in the deployment. It reads exactly the Arogya provider record (key `arogya:provider:apollo`) with its `cipher` encrypted under KMS context `purpose=arogya-provider, record=arogya:provider:apollo`. The trusted session writer must establish a verified server session containing `stage: ready`, a provider-issued `token`, `expiresAt` (Unix seconds), and `applicationHeader`. Never export a browser session or reuse chat credentials; the adapter does not log in, refresh tokens, or read Gmail. The provider session writer and its consent/renewal bridge are still outstanding. Enable `ApolloRegistryTableName` and `ApolloTokenKeyArn` only after that bridge is implemented and its security approval is obtained; otherwise the Lambda returns 503 for catalogue requests. No new secret, database, KMS key, scheduled worker or payment operation is included.

The provider response field aliases in the normalizer are provisional and need verification against an authorized Apollo response before enabling live data. No patient lookup or booking submission was tested.

## Release order
1. Test the new frontend and backend, including the exact same-site return allowlist, negative auth cases, responsive design and provider response contract.
2. Deploy the customer-commerce auth backend with the new exact return path first.
3. Deploy the verified read-only booking API after the approved provider session integration and access scope are confirmed. Confirm unauthorized calls return 401 and provider failures return 503.
4. Deploy the website and verify logged-out navigation, WhatsApp sign-in, successful return, current choices, stale selection handling, and mobile layout. Keep this PR in draft until the authorized provider response and complete flow are verified.

No production deploy was performed by this repair.
