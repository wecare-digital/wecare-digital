# XCODEX current-state audit — 9 October 2026

Status: **PARTIALLY COMPLETE**. Initial audit established before implementation edits.

The clean worktree and origin/stack are both d03ac81dfda8d1a5da461f01b4005559b2a3ada4. The other local stack checkout is newer and is left untouched. Current provider readbacks confirm Business API live88, Secure Files34, Service Requests5, catalog sync7 and checkout41. Fresh catalog1457045652952851 reads successfully with four Wix proposals and zero existing items/applied writes. Submit Request1107164111921876 and Review1578178897413815 are PUBLISHED; Orders2167802357142172 is DRAFT with no validation errors. Native activation and Wix writeback flags remain off. QA contact has neither checkoutCustomerId nor customerUuid.

## Findings requiring current reconciliation

| ID | Severity | State | Component | Evidence | Impact and root cause | Fix and validation | Rollback |
|---|---|---|---|---|---|---|---|
| AUD-01 | P2 | FIXED | Rollout records | README and live-evidence still lead with business79/catalog6/old catalog and read_failed | Stale handoff can repeat repairs or overwrite newer deployments | Preserve snapshots; add fresh current section and machine-readable record | Revert only audit documentation commit |
| AUD-02 | P3 | FIXED | Retired payment diagnostic | IAM GET-shaped raw route on live88 returns400 phoneId required; supported check/list both200 with active configurations | Generic route masks the retired contract, although current checkout uses normalized list | Regression-test an explicit retired response directing callers to list/check; no provider/payment mutations | Restore live88 with a current alias revision guard |
| AUD-03 | P1 | CONFIRMED | Customer release | Native catalog/writeback/dynamic Vault flags off; encrypted picker and four-service checkout incomplete | Paid service rollout cannot be called ready | Complete target binding, provider terminal recovery, picker and writeback contracts; then customer QA | Keep gates off; preserve successful payment records |
| AUD-04 | P2 | CONFIRMED | Catalog availability | Four known paid proposals, no blocks; empty fresh catalog | Approval queue and item application remain engineering work, not a permission read failure | Durable per-revision approval and API apply/readback; verify both WABAs | Staged read-only config; never restore an obsolete writer without review |
| AUD-05 | P1 | CONFIRMED | QA identity | One undeleted nominated contact without permanent account link/public UUID | Cannot authenticate owner-scoped Orders/payment test | Supported sign-in/account verification and ownership reconciliation; never synthesize link | No identity write performed |
| AUD-06 | P2 | NOT VERIFIED | Customer delivery and events | No real paid QA, invoice send or handset interaction in this audit | Approval/API acceptance/build do not prove delivery, CAPI match or customer readiness | Owner-paid QA and delivery receipts; no fabricated Purchase | No financial/provider changes performed |

Superseded: catalog read_failed on old target, held business79 diagnostic deployment, missing native Orders adapter, missing invoice-copy source, Vault repayment/retry defects. Current private CDN probe returns302 to homepage without serving the file; bucket privacy is supported by the deployed edge prefix guard, not bucket policy alone. Comprehensive account-wide security and every provider-side connection are not certified by this scoped audit.

## Final repair and verification checkpoint

AUD-01: The authoritative rollout README, release-status entry, continuation prompt and live-evidence root now point to this fresh audit. Previous root evidence is retained as a historical snapshot. The user-provided master prompt is preserved verbatim beneath a new precedence checkpoint in xcodex-master-execution-prompt-updated-2026-10-09.md. No original attachment was overwritten.

AUD-02: Reproduced GET/POST legacy fallthrough in focused offline tests before repair. Added an explicit retired raw route before the generic payment-config handler, with410 and normalized list/check replacement paths. Exact deployment ZIP differs from verified live88 in handler.py only. Candidate89 readback: raw410, list200, check200, unauthenticated HTTP401, no FunctionError. Revision-guarded alias switched88→89 and live raw readback410. SHA256 r+k6k2WhMDaNbYzFfax39Zi/1e/ckqg8ad891fvCu3E=. No payment configuration mutation or messaging/financial operation. Immediate rollback: read current live alias, then guarded UpdateAlias to88; never overwrite a concurrent newer version blindly.

Final local gates: backend10,334 passed /7 skipped /3 expected failures; focused165 passed; frontend1,597 passed /2 skipped across125 files; TypeScript passes; ESLint0 errors and190 existing warnings. Production build initially failed closed on public blog HTTP503 and passed on retry. Nine public routes return200 HTML. This confirms reachability/build behavior, not authenticated account/payment journeys. No paid customer QA, captured charge, invoice creation, refund, test message or synthetic Purchase event was performed.

AUD-03 required tests: original A versus service B separation, stable P/reference, R ownership, frozen integer quote, definite-terminal retry with lineage, pending/unknown refusal to charge again, duplicate/delayed webhook convergence, paid downstream recovery, picker decrypt/register and writeback failure recovery. Live verification is NOT COMPLETE; keep flags closed. Rollback preserves paid records and disables new entry, never rolls back successful settlement.

AUD-04 required tests: per-revision proposal/approval persistence, stale-revision rejection, exact intended variant mapping, bounded apply/readback, image fetch and both-WABA attachment. No products applied. Existing catalog read failure is superseded; source is four variants with no blocks. Approval automation is unfinished. Desired dataset4554612361454941 is not proof of an actual provider connection or100% match rate.

AUD-05 required tests: supported account verification, own/foreign/missing identity, same-phone/new-sub, deleted/recreated contact, immutable UUID/phone. No identity writes occurred. The existing nominated test customer must establish a permanent account binding before owner-paid QA.

AUD-06: handset/customer delivery, secure downloads, invoice copy, real Orders rendering, automatic review deduplication, provider event delivery and catalog matching remain NOT VERIFIED. The approved template/readiness/provider checks alone do not establish these. Owner-paid QA must finish after engineering gates are complete.

## Boundaries and next execution

This scoped audit covers nine live Lambda configurations/hashes, seven table schemas/indexes, relevant IAM simulation, private bucket/CloudFront guard, real Meta Flow inventory (49), three approved template contracts, active payment configurations on both WABAs, read-only Wix/catalog proposals, QA contact linkage, source/tests and current Amplify deployment1502 at d03ac81d. It is not an all-region resource/cost audit, every CRM record inspection, whole-site signed-in certification or full provider security assessment. IAM simulation is not actual document delivery. A stale CloudFront distribution policy reference was observed; current private-prefix guard remains effective, so no broad infrastructure change was made.

Next bounded engineering action: implement durable per-revision catalog proposal/approval/apply/readback without enabling checkout; verify the new catalog/dataset/WABA connections. Then complete service target binding, native terminal recovery, encrypted upload ingestion and safe writeback, followed by owner-paid QA. Retain website fallbacks and reuse Orders draft rather than create overlapping hubs. Overall status remains **PARTIALLY COMPLETE**.

## Dependency security follow-up

AUD-07 — P1 / CONFIRMED / amplify/package-lock.json: GitHub currently reports two open high-severity Dependabot alerts:63 for @graphql-tools/utils (GHSA-7mx3-vvmw-hjmv, first patched12.0.1), and61 for braces (GHSA-vfj7-8cjw-p6xm, no patched version listed by the API). Alert presence is confirmed; exploitability of the deployed customer journey is NOT VERIFIED. Root cause is the retained Amplify transitive dependency graph. Repair requires parent-version compatibility analysis and a targeted lockfile update/removal path, then Amplify build/schema/deployment tests and alert readback. Do not invent a fix version or blanket override. No dependency changes were made in this diagnostic patch. Rollback any future dependency repair by its scoped source commit and exact validated package, preserving financial/customer state.
