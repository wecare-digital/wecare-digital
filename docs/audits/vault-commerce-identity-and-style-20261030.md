# Vault commerce, identity, messaging and UI audit — 30 October 2026

## Release status (verified against connected GitHub and AWS)

- AWS Amplify **#390**: Build, Deploy, Verify succeeded on 30 October 2026 at 11:14:51 UTC. This is the **website/frontend** release, not a backend-Lambda release.
- The latest production aliases inspected immediately after #390 were:
  - `wecare-checkout:live` **286** (last updated 03:28 UTC)
  - `wecare-service-requests:live` **28** (last updated 29 October 07:26 UTC)
  - `wecare-whatsapp-business-api:live` **396** (last updated 10:02 UTC)
  - `wecare-customer-profile:live` **41** (last updated 03:28 UTC)
  - `wecare-secure-files:live` **179** (last updated 10:14 UTC)
- These backend versions predate the later Vault website payment, file renewal, and supporting sender commits. **Do not describe Vault payment or download as E2E verified on production.**
- WhatsApp Business manager read: WECARE.DIGITAL app published; messaging webhook subscription present; messaging billing method present. The templates `wecare_whatapp_native_pay_template`, `wecare_vault_request_ready`, and `wecare_default_download` are approved. These prove template/account setup, **not** a successful Vault-specific payment send. The feature flag and recent business-API outcome remain unverified.

## Root causes / risks located in source

1. The checkout profile lookup in `amplify/functions/ecommerce/checkout/handler.py` previously required a nonempty email despite `CheckoutProfile.tsx` intentionally using verified phone identity and not collecting email. This made owned, phone-verified customers appear profile-less. PR #1957 removed the unnecessary email requirement but continues to require exact `checkoutCustomerId` ownership. A separate name gate prevents phone-only bootstrap from being treated as a complete checkout profile.
2. `CartPage.tsx` previously read only the in-memory/session-storage customer token on mount; it did not restore a valid persistent customer session before requesting profile. PR #1957 adds restore and makes the identity card visible for a valid name/phone when the basket needs no shipping. It preserves the address gate for physical products.
3. The customer Vault page previously disabled both pay options if the live pricing **preview** was missing. WhatsApp payment actually re-prices on the server and should remain independently usable. PR #1957 removes that frontend-only block for WhatsApp; website cart still needs an available live service line display price, and the backend always decides payable amounts.
4. Vault and Drop Docs have their own supply GST, Delight, Express and convenience-fee quote. A basket with ordinary products would apply those terms to unrelated items. PR #1957 refuses mixed Vault/Drop Docs service baskets before payment at the backend and declines to overwrite unrelated browser-cart items.
5. A verified handset does not establish ownership of an arbitrary CRM row. `customer-profile` still refuses ambiguous/foreign/ownerless-without-evidence contacts, and native WhatsApp needs an exact owner-bound contact. `CONTACT_IDENTITY_CONFLICT`, `CONTACT_AMBIGUOUS` and `WHATSAPP_IDENTITY_REQUIRED` must trigger **staff reconciliation**, not a silent ownership bypass.
6. The shared dropdown CSS `src/styles/form-controls.css` still styles hovered/keyboard-active options with `var(--bg-hover)` (grey). PR #1957 adjusts the local staff Vault customer picker, reused-file list and document-source toggle to home lime tokens and canonical Inter typography, **but the shared Select dropdown change remains open**.
7. Production release mismatches must be resolved before reproducing a real transaction: frontend #390 succeeded, backend aliases still run earlier code. The backend activation is an independent release with a separate audit and rollback.

## Payment and private-download contract to preserve

- Staff upload is not a send. Drop Docs stores the private object, explicit Publish to Vault produces the exact-file identifier; staff review/send is separate.
- `/vault/?file=<opaque-fileId>` provides routing, not authorization. The server rechecks verified customer subject, phone, file ownership, active object, and a paid durable entitlement before issuing a short-lived S3 GET signed URL. Never embed a public S3 URL or payment credential in the WhatsApp template.
- `UNPAID` and `EXPIRED` allow a new *authorized* purchase (after independent payment checks); `OPEN` and `READY` must **never** charge; `PAID_UNVERIFIED` must reconcile rather than charge again.
- First verified paid file delivery/download starts a 24-hour window. Every download inside the window is free; resale creates one new **paid window on the same entitlement** once the previous one is exhausted. Re-sent links never reset or extend the original clock.
- S3 object existence (HEAD), strict file and owner checks, exact expiry, ASCII sanitized download filename, short-lived signed URL and allow-listed S3 hostname remain mandatory. If storage is unavailable, refuse the download and tell the customer not to pay again.
- WhatsApp API acceptance is not delivered/read evidence; use actual provider webhooks. An uncertain send must not be automatically repeated, and a duplicate payment must not be minted to work around uncertain status.
- No shipping address required for Vault-only website payment. ProductsTable and server frozen snapshot set amount, GST, charges and invoice, never the browser.

## Safe release and verification gates — NOT YET COMPLETE

- [ ] Run offline targeted tests: `pytest -q tests/test_vault_commerce_readiness_20261030.py tests/test_request_service_contracts.py` plus existing Vault window, ownership, checkout, webhook, payment-attempt and invoice suites.
- [ ] Run `npm run typecheck` and production build; review React and narrow-phone mobile views; check dropdown selection keyboard/a11y.
- [ ] Review latest mainline changes and synchronize all related backend bundles/layers; do **not** ship only one Lambda when its caller/callee contract changed.
- [ ] Deploy payment-sensitive Lambdas through the canonical verified release procedure with captured previous alias versions, readiness guards, and rollback. Ensure exact-file website checkout + payment-request routes and IAM permissions match the code being published.
- [ ] Verify live API routes and payment readiness using read-only inspection first; no synthetic order to a real customer.
- [ ] On an explicitly authorized test customer and non-sensitive test file, verify (a) profile without optional email, (b) exact-file Vault cart, (c) WhatsApp approved payment, (d) authoritative captured payment, (e) one access window, (f) actual private file download bytes, (g) second free download before expiry and refusal after expiry, (h) renewed 24 hours only after new captured payment, (i) invoice, status timestamps, and provider acceptance/delivery distinction.
- [ ] Never run live customer payment/message traffic solely to make a CI test green.
- [ ] Separate pending shared dropdown styling into its own tested patch if broader than the Vault staff picker.

## Evidence and code

- Commerce/UI fixes merged: [GitHub PR #1957](https://github.com/wecare-digital/wecare-digital/pull/1957).
- Offline regression suite (draft, not CI-green): [GitHub PR #1958](https://github.com/wecare-digital/wecare-digital/pull/1958).
- Build syntax correction: [GitHub PR #1959](https://github.com/wecare-digital/wecare-digital/pull/1959).
- Production frontend build: AWS Amplify #390 (Build/Deploy/Verify all succeeded). Backend aliases listed above were independently inspected after the build.
