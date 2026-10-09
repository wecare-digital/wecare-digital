# xCodex expanded current-state audit — 9 October 2026

Status: **PARTIALLY COMPLETE**. This document extends the completed first audit in `codex-deep-audit-2026-10-09.md`; that document is the immutable pre-repair snapshot. Current production facts supersede its dated alias table. Source baseline for this extension: c24fab39fbcaa3f01024bf5adcba226453f3a8f8. No customer-service hub has been created or published.

## Additional identity findings, recorded before repairs

### AUD-016 — profile ownership replacement

- Severity: CRITICAL. State: CONFIRMED. Component: auth/customer-profile `_upsert_contact`.
- Evidence: source chooses a phone/email-index contact and writes `checkoutCustomerId` without verifying its current permanent owner. `_owned_contact` may reject another customer's row, but a full creation-shaped submission with valid email proof reaches the unguarded upsert. Both edit and deterministic-ID race updates lack ownership conditions.
- Impact: a verified phone match and fresh email proof can replace a pre-existing contact's permanent owner. Account recreation or number reassignment must not transfer another customer's profile/history.
- Root cause: lookup and creation validation were treated as write authorization; owner assignment remained unconditional.
- Recommended fix: require nonempty exact permanent owner for editing any existing row; refuse ownerless or foreign rows with CONTACT_IDENTITY_CONFLICT. Condition both update paths on the same owner atomically. Existing legacy contacts require explicit staff reconciliation supported by identity evidence.
- Tests needed: full valid submissions against absent, blank and foreign owners leave rows unchanged; normal owner edits and creation work; ownership change between lookup and update is refused.
- Live verification needed: captured exact ZIP, fresh alias/revision/hash guards and immutable readback. Never probe a potentially mutating production POST to prove an auth failure.
- Rollback: captured customer-profile9 plus conditional live alias restoration; no existing contact mutation or automatic adoption.

### AUD-017 — legacy profile data disclosed by phone

- Severity: HIGH. State: CONFIRMED. Components: customer-orders `_profile`, checkout `_checkout_profile`, customer-profile `_owned_contact`.
- Evidence: all three readers accept ownerless phone-index contacts. Order history returns their name/email/address; checkout can put an already verified legacy email/address into payment prefill.
- Impact: a current phone session can read a previous or ambiguous owner's personal information. A shared phone is a discovery key, not permanent authorization.
- Root cause: deliberate legacy adoption rule conflicts with the expanded permanent-identity requirement.
- Recommended fix: normalize phone for discovery, but require exact nonempty `checkoutCustomerId` before returning personal fields or allowing edits. Do not relax email verification, delete legacy rows or fabricate account links.
- Tests needed: absent/blank/foreign owner denied in both readers; own profile remains available and same-phone duplicates cannot substitute another row.
- Live verification needed: exact checkout40/customer-orders6 archives and guarded alias deployment; owner QA after explicit contact reconciliation.
- Rollback: immutable checkout40/customer-orders6 versions. Restoring old code restores the identified privacy risk.

## Reconciled prior findings

AUD-001 ownership and AUD-008 download TTL repairs are deployed on secure-files32; service-requests4 carries the shared ownership guard. AUD-003 payment diagnostics are now FIXED on business-api83: read-only check and list execute version83, and both WABA checks report two total/two active configurations. The initial business deployment hold is SUPERSEDED after pending `$LATEST` was downloaded and reconciled: its only extra code is the source-matching service design draft read route and seven source-matching draft members. Those members were preserved.

The published paid Flow and approved templates supersede older DRAFT/pending statements. They do not prove a completed payment journey. AUD-004 remains blocked: the nominated QA contact lacks a permanent owner link. The earlier recommendation to implicitly claim it through a phone-only save is superseded by AUD-016/017; staff reconciliation must establish the existing Cognito subject without exposing or transferring old data.

Current catalog source/live target drift, closed native gates, incomplete provider journeys, legacy object privacy inventory and dependency alerts remain unresolved. Detailed scope, evidence, state-machine and migration decisions are supplied in the companion architecture and migration artifacts.

## Repair verification — later same session

AUD-016 and AUD-017 are now **FIXED** for the reviewed paths. Regression tests first reproduced seven failures against old behavior, including a valid full submission overwriting another permanent owner. The repaired source passes10391 tests, with6 skipped and3 expected failures. Exact preserved archives pass checkout185, customer-orders123 and customer-profile38 checks. Each ZIP changes only handler.py, retaining every member and bundled shared dependency.

Guarded deployment and independent readback establish checkout41, customer-orders7 and customer-profile10 as live, Active/Successful, SnapStart=None. Role/runtime/memory/timeout/layers/architectures/environment/SnapStart and other configuration were compared with the old immutable version before publishing and remain unchanged. Code hash, fresh completion revision and conditional alias revisions guarded release. Checkout's inert unauthenticated GET returns401; the other two inert GETs return405 on their exact new versions. These probes are runtime/import/method evidence, not authenticated end-to-end QA.

The captured pre-change rollback versions are checkout40, customer-orders6 and customer-profile9. No contact records were reassigned. Restoring those old versions would restore the identified ownership weakness. Explicit legacy identity reconciliation remains required.

## Final concurrency reconciliation

A later independent read discovered concurrent releases secure-files34, service-requests5 and business-api86. They were preserved. Their immutable ZIP hashes were independently verified, and AST comparison confirms every reviewed permanent-owner/payment-reader repair remains present. Secure-files34 retains the missing delivery module and bounded60–900 second URL expression, with payment and Drop Docs attach flags false. Business86 read-only check/list still agree on two active configurations for both WABA checks. Other changes in these newer packages were not certified by this audit's earlier exact-package test counts.

The profile releases remain checkout41/customer-orders7/customer-profile10 at this final reconciliation. The complete latest-version/hash/alias comparison is `concurrent-release-reconciliation.json`. The earlier production-change record is this session's deployment history, not permission to roll back another session's newer aliases. Do not apply the recorded32/4/83 alias guards or old rollback targets to34/5/86; capture and review the newer release's own before/after state.

### AUD-018 — newer delivery uncertainty contract differs from source

- Severity: MEDIUM. State: CONFIRMED. Component: business86 flows/paid_vault `_send_once` versus source e006b5f3 and its tests.
- Evidence: existing test expects SEND_FAILED after502; current immutable86 writes SEND_UNKNOWN, qualifies outbound:live, and distinguishes SEND_REJECTED with up to3 attempts/backoff. The original141-check selection yields140 passes and1 compatibility mismatch. No production behavior was changed to satisfy the stale assertion.
- Impact: a future deployment from older source could replace the newer safer uncertainty/retry contract; accepted/unknown messages must not be blindly resent.
- Root cause: another session deployed code ahead of the reviewed source contract.
- Recommended fix: reconcile the owning session's scoped source/test change before rebuilding; preserve unknown reconciliation and bounded definite-rejection retry. Do not silently overwrite the newer live code or stage foreign edits.
- Tests needed:502 stays unknown/no duplicate send/payment stays paid; definite rejection waits and stops at3 attempts; successful acceptance, duplicate events and stalled claim recovery. Two independent verification-only tests against86 pass; the remaining focused selection passes142 checks with the1 obsolete expectation explicitly excluded.
- Live verification needed: provider read-only diagnostics execute86 successfully; no customer send occurred. Real delivery/window/unknown reconciliation remains owner/provider QA.
- Rollback: obtain the newer release's own before/after record. This session's83/79 record cannot undo86 safely.

Fresh exact concurrent-package checks: secure34 passes97 checks with3 unrelated Vault-helper cases deselected; service5 passes38; business86 passes140 compatible existing checks plus2 independently specified uncertainty/retry checks. Other newer code changes are not comprehensively certified. Source e006b5f3 CI independently completed all7 workflows successfully.
