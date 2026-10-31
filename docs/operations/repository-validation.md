# Repository validation after CI/test retirement

As of 2026-10-28, owner direction is to keep this repository without GitHub Actions workflows and
without the root Python `tests/` regression suite. Standalone CI-focused test scripts,
offline fixture-based regression harnesses under `scripts/` and `tools/`,
Android sample tests, and the defunct `npm test` invocation are also retired.
As reaffirmed on 2026-10-31, do not recreate these suites or add automated
test runners to the production Amplify packaging build.

Manual domain checks, typecheck/build, browser measurements, and guarded deployment
verification remain available; do not bypass them for security-sensitive changes.

The retained **production export guard**, `scripts/checkout_release_check.py
--export-dir out`, runs in the existing Amplify build and now refuses customer
Orders regressions. `/orders/` must show only the compact five-column history
(Order #, Date, Amount, Status, Invoice; More actions shares the invoice cell).
The customer Order # is not a detail trigger, no expandable receipt/item/GST/
delivery-address panel or per-order URL can be added, and old `?o=` selectors
normalize back to history. The backend `action="order"` refusal (HTTP 410)
must stay ahead of any payment-creation fallback. Internal staff order detail
and paid statutory invoice data are unaffected.

This is a source/packaging rule inside an **already retained** operational
release guard, not a reinstated offline test runner or GitHub Actions workflow.
Only a separately reviewed Amplify production release and authenticated
desktop/mobile verification can remove the old detail UI from the live website.

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
