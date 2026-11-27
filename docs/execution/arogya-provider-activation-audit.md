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
- Use the existing KMS key, registry, Google OAuth secret and Apollo service secret.
  The runtime has no provider permissions by default. Opt-in IAM is restricted to
  the exact service session key, one chosen OAuth grant and the two exact secret ARNs.
  The password is never copied into the DynamoDB session registry. No new key,
  database, worker or scheduler is created.
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
3. An authorized AWS administrator configures the existing
   `wecare/arogya/apollo` secret in Secrets Manager. Do not duplicate the
   password in DynamoDB. Run the updated interactive script:
   `python3 scripts/configure_arogya_provider.py --grant-owner OWNER_HASH --key-arn APPROVED_KEY_ARN`.
   It checks the exact account, verified grant and key; requires provider approval
   and rotation of the previously exposed password; and securely prompts for the
   provider-issued application header and exact OTP sender. The new secret version
   is promoted with a version fence. Run the same command with `--check` for
   read-only readiness verification. Never place credentials on command lines or
   in repository files. Rotate with catalogue disabled; review and reset any old
   provider session before re-enabling.
4. Review the CloudFormation change set. Set ApolloAutomationEnabled=true only
   with the exact verified ApolloGmailGrantOwner, ApolloRegistryTableName,
   ApolloTokenKeyArn, ApolloGoogleOAuthSecretArn and ApolloServiceSecretArn.
   Validate the key policy and grant context first. With any missing input the
   default is no provider access. The provider-approved service secret must pass
   the readiness check before enabling the conditional IAM permissions.
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


## Reproducible release artifact

GitHub CI stages the appointment bundle with the current commit, exact template,
ZIP digest, expected destination and explicit provider-disabled parameters.
`python3 scripts/build_arogya_booking.py --output /absolute/release/path` builds
from committed source; repeat with `--verify` to check the staged files without
rebuilding. This step performs no network requests or deployment. The manifest
must not be edited to enable provider access. A separate approved CloudFormation
change set and the live integration checklist are required for provider activation.

Production Amplify builds now retain the verified ZIP, exact template and manifest
at `customer-commerce/arogya-booking-release/<production commit>/` in the existing
private asset bucket after the exact-commit CI gate. This is staging only. Review
and execute the provider-disabled change set separately; keep the previous
content-addressed S3 key for rollback. Compare the deployed Lambda CodeSha256 with
the manifest before testing the authenticated form.

## Secrets Manager credential handoff

The production service secret was created separately at `wecare/arogya/apollo`.
The earlier DynamoDB credential provisioner did not consume this secret. The
updated runtime and stack pin its exact ARN, read only AWSCURRENT, validate
approved service metadata, and remove the legacy credential-row read permission.
The base disabled artifact never grants access to that secret. Stored login
credentials alone do not establish an approved or working provider session.


## Public directory fallback — separate from booking

The official public directory exposes hospital and doctor-profile links:
- https://www.apollohospitals.com/facilities/hospitals
- https://www.apollohospitals.com/doctors

Apollo's public-site disclaimer restricts commercial reuse and retention:
https://www.apollohospitals.com/corporate/disclaimer/. A public URL, a staff IC
account and a robots allowance do not establish permission to republish a directory.

The authenticated planner offers direct official-directory links independent of
live IC availability. These do not forward patient data, use an IC login token,
take payment or claim booking confirmation. Customers use Apollo's own website
for availability, verification and booking.

The operator-only `scripts/apollo_public_directory.py` discovers first-page
hospital and doctor profile links when explicitly approved by Apollo. It reads
the current robots policy, uses a named user agent, fetches a fixed public page
with strict size and time bounds, refuses redirects and noncanonical links,
and returns minimal directory-only JSON. The specialty and city slugs are
public URL components, NOT IC identifiers. It does not follow profiles or
pagination, collect patient data, bypass verification, submit bookings or
persist snapshots. Never enable it as a commercial catalogue feed until written
permission and the actual response contract have been reviewed. With that
approval, an administrator may run:

`python3 scripts/apollo_public_directory.py --kind hospitals --approved-by-provider`

`python3 scripts/apollo_public_directory.py --kind doctors --approved-by-provider`

Do not cache or republish its results outside the approved scope. Test coverage
uses synthetic HTML, not copied profiles. No authorized live automated scrape
or slot reservation has been verified. IC integration and checkout remain
separately gated.

## Verified booking destination and release recovery (27 November 2026)

The Apollo public appointment finder is https://www.apollohospitals.com/book-doctor-appointment (specialty/city filters and doctor search). The older AskApollo hostname redirects to the Apollo 24/7 AI assistant and should not be the primary booking destination. The Apollo hospital directory, doctor directory and international patient services pages were separately checked. Public directory URLs and the first-page profile-path format are supported by the observed public pages; the IC service's slot and booking response contract is still not established by those pages. A filtered directory request returned HTTP 403, so do not attempt to bypass it or use an undocumented search endpoint.

Offer the primary direct Apollo booking link within the phone-verified planner regardless of IC catalogue availability. International patient services are a separate optional handoff. Do not pass customer identity or patient details in outbound links. Provider availability, confirmation and charges are controlled by Apollo, and the WECARE checkout remains disabled. A lack of local choices is not evidence that Apollo has no hospitals. The earlier deployment was blocked by an unescaped JSX apostrophe; the escaped copy and regression tests preserve the release gate.

No commercial directory dataset has been retained or published. Public robots rules are not a license; the published disclaimer restricts commercial reuse and retention. An approved partner interface and a genuine authorized transaction test are still required for an integrated booking release.
