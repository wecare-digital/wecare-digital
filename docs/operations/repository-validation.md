# Repository validation after CI/test retirement

As of 2026-10-28, owner direction is to keep this repository without GitHub Actions workflows and
without the root Python `tests/` regression suite. Standalone CI-focused test scripts,
Android sample tests, and the defunct `npm test` invocation are also retired.

Manual domain checks, typecheck/build, browser measurements, and guarded deployment
verification remain available; do not bypass them for security-sensitive changes.

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
