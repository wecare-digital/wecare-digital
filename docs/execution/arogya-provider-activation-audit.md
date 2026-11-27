# Arogya Yatra deep activation audit — 27 November 2026

## Evidence and release decision

PR #2452 passed its initial CI run and was merged during this audit. The production
booking Lambda was still the 15-second draft-only release. Read-only AWS checks
confirmed the exact workspace registry has no Apollo Gmail grant, no Apollo
provider session, and no approved Apollo credential record. The deployed checkout
and native catalog admin both use stack-wecare-digital-ProductsTable; the table
reported zero items. Do not seed a single replacement product or turn on charging
in an otherwise empty commerce authority.

## Follow-up changes

- Separate authenticated access from price preview; validate the server's phone
  verification and use an opaque account key to clear prior-customer UI on account
  changes. Renew existing customer sessions; hide the planner on failed checks.
- Fetch dependent hospital, speciality, doctor, health-check, appointment type,
  salutation, available date and time preference metadata from the provider adapter.
  Unknown response schemas fail closed. Time components are not reserved time slots.
- Connect the existing encrypted session/renewal core to an exact administrator-bound
  staff Gmail grant. Use the same fenced OAuth refresh record as workspace MCP,
  retain exact Gmail read-only scope, validate the target mailbox, and never
  return OTPs, mail, provider credentials or access tokens. A single service
  renewal lease bounds concurrent login challenges. Do not bypass CAPTCHA or
  provider-required interactive checks. Renewal returns bounded 202 status; the
  active form polls only that status and cancels on unmount or selection change.
- Use the existing KMS key, registry and Google OAuth secret. The runtime has no
  provider permissions by default. Opt-in IAM is restricted to the exact service
  session key and one chosen OAuth grant; the encrypted credential row is read-only
  for the runtime. No new secret, key, database, worker or scheduler is created.
- Hide ordinary Arogya payment entry points and reject the unbound Arogya product/SKU
  in the common server-side cart and quote paths, including already-saved carts.
  Existing ₹550 pricing formula is an estimate (₹711.14 for one unit), not a
  payable quote or a confirmed booking. Other product checkout paths are unchanged.

## Secure activation checklist

1. Obtain explicit Apollo approval for the supported service-account interface,
   authorized application header, intended account and exact OTP sender. Rotate
   the password exposed in the previous transcript; never pass it in chat, CLI
   flags, browser storage, logs, code or GitHub. Do not use a copied browser token.
2. In Workspace → Platform → MCP Connections, connect the intended Apollo business
   Gmail account, grant the exact Gmail read-only scope, then Verify. The consent
   screen must be completed by the mailbox administrator. A verified staff grant
   alone does not delegate it to the customer-facing service.
3. An authorized AWS administrator selects the exact verified staff grant owner
   and existing KMS key, then runs the interactive provisioning script locally:
   `python3 scripts/configure_arogya_provider.py --grant-owner OWNER_HASH --key-arn APPROVED_KEY_ARN`.
   It requires an interactive approval statement, prompts for the rotated password
   and provider-issued header without echo, and conditionally encrypts a new
   credential row under the existing key. It refuses to overwrite an existing
   record. Rotation/reset needs a separate approved change with catalogue disabled.
4. Review the CloudFormation change set. Set ApolloAutomationEnabled=true only
   with the exact verified ApolloGmailGrantOwner, ApolloRegistryTableName,
   ApolloTokenKeyArn and ApolloGoogleOAuthSecretArn. Validate the key policy and
   grant context first. With any missing input the default is no provider access.
   No infrastructure was deployed or permission expanded during this audit.
5. Deploy the shared auth return allowlist and backend access action before the
   new frontend. Verify 401/403 without a verified customer and 503 with the
   provider disabled; then validate one authorized live renewal and provider
   response schema. Test live reads and mobile UI with synthetic/authorized data.
6. Resolve the empty live catalogue through its owner, without inventing a new
   product identity. Verify the committed Arogya SKU, ₹550 base, GST, Delight,
   Express, and convenience-fee calculation against a frozen authoritative quote.
7. Provider patient lookup, verified time-slot reservation, paid-order-to-draft
   atomic binding, provider submission and timeout reconciliation require the
   provider's authorized request/response contract and the live commerce authority.
   Do not expose arbitrary UHID/mobile search or claim a booking without that
   evidence. Keep ordinary Arogya checkout blocked until these are implemented
   and a genuine authorized end-to-end test passes. No live patient record, money,
   or appointment was created during the audit.

The source implementation is testable with synthetic provider responses. Real
provider response field aliases and the actual supported sign-in contract remain
unverified. Provider consent and official integration authorization are not
replaceable by successful unit tests. There is no guaranteed zero AWS bill;
this change reuses existing resources and does not add fixed paid capacity.


## Account isolation and retry repair

Every draft read, write, listing and deletion now requires the opaque verified
account binding from the access action. It is only compared against the identity
derived from Cognito, never used to choose an owner. Account changes unmount the
patient form; stale requests cannot save into a different account. A timed-out
save retains its draft ID, expected revision and exact request; an identical
already-committed replay returns the original revision. Draft APIs refuse to
read or delete non-DRAFT rows. Listing projects no patient fields and provides
bounded per-owner pagination.

**Coordinated release required:** old frontend versions do not send the account
binding. Deploy the matching backend and frontend together (backend first; old
clients fail closed until refreshed). Verify draft saves, account switching and
reload behavior before exposing the updated form. The old checkout protection
must be deployed through the common commerce release path, not merely the
Arogya Lambda.
