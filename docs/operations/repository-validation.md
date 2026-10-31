# Repository validation after CI/test retirement

As of 2026-10-28, owner direction is to keep this repository without GitHub Actions workflows and
without the root Python `tests/` regression suite. Standalone CI-focused test scripts,
Android sample tests, and the defunct `npm test` invocation are also retired.

Manual domain checks, typecheck/build, browser measurements, and guarded deployment
verification remain available; do not bypass them for security-sensitive changes.

## Customer Orders history-only build invariant

The customer `/orders/` route has **no** expandable item/receipt/GST/delivery-address
section or per-order page. The order number is static text, with separate invoice
download, ID copy and More actions. Staff-only order details and statutory payment
records remain available through their existing authorized paths.

`next.config.js` invokes the read-only
`scripts/guard_customer_orders_history_only.mjs` during **every Next build**,
including direct `next build`, `npm run build` and Amplify production builds.
The guard fails when a customer detail component, expandable/clickable order row,
deep-link order selector, alternate Orders route, itemized fields or the backend's
retired `action="order"` HTTP 410 boundary is reintroduced. Run it manually before
a release with `node scripts/guard_customer_orders_history_only.mjs`.
Keep this build invariant active even while the root `tests/` suite and GitHub
Actions workflows remain retired.

A source/build safeguard does not replace deployment verification. Explicitly
release an approved frontend build with immutable evidence and validate a signed-in
production `/orders/` on desktop/mobile; old Amplify releases or deliberate rollbacks
can otherwise continue serving the prior expandable UI. Checkout Lambda publication
and its alias promotion are independently approved payment-rail operations.

Validation is explicit and release-scoped:

1. Build and typecheck the affected application surface.
2. Run the domain verification scripts that exercise the changed behavior.
3. Use dry-run packaging or provisioning before any production write.
4. Review the exact package and configuration delta.
5. Publish immutable Lambda versions and verify `live` alias/code hashes after deployment.
6. For public UI changes, run the browser harnesses against the build under review.

Historical audit documents and snapshots may mention retired workflows or tests and remain as
historical evidence. Active operational documentation and scripts must not depend on those retired
paths.

The GitHub production ruleset must not require status-check contexts produced only by deleted
workflows. Repository administrators must update that ruleset after this retirement change is
merged; do not fabricate commit statuses to bypass it.
