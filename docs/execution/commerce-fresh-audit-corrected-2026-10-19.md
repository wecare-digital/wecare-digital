# Commerce fresh audit (corrected) — 2026-10-19

Supersedes the earlier `commerce-fresh-audit-2026-10-19.md`. That report was an accurate snapshot
at the time it was written, but it predated the observability/acceptance/quarantine work that has
since merged. This version reflects the **current live + merged state**, verified read-only
against AWS `us-east-1` and the `origin/stack` head at audit time.

## Verdict

The payment → order → customer backend is complete, merged, and deployed, and the acceptance-
review gaps that were code or tooling are now **closed, merged, and verified against live AWS**.
Three items remain, and all three are irreducible: a dependency *decision*, a live customer
*click-through*, and owner-gated irreversible `--apply` writes. None is a code gap.

- Live `commerce_health.py`: **GREEN** — every signal healthy.
- Live `commerce_acceptance_check.py WD-ORD-TJMG7G4N`: **ALL PASS** on all three surfaces.
- Focused commerce suite: **337 passed**.

## What the earlier report listed as pending, and its current state

| Earlier report | Status now |
|---|---|
| Medium: no error alarms for checkout / customer-orders / customer-profile | **DONE** — added to the always-alarmed set in `provision_lambda_alarms.py` (PR #914, merged). customer-profile is alarmed at any volume precisely because its zero-datapoint window makes a volume-floor rule blind to it. |
| Medium: reconciliation visibility limited | **DONE** — `customer_order_link.reconcile_metrics()` emits `PromotedThisRun`, `PendingRemaining`, `OldestPendingAgeSeconds`, `ReconciliationFailures` to CloudWatch `WeCare/CustomerOrderLink`; alarms in `provision_reconciliation_alarms.py` (PRs #914, #916, merged). |
| Low: recovered invoice image/PDF not refreshed | **DONE** — the stored PNG predated the `customerUuid` enrichment, so the Customer ID row was blank; regenerated via the live invoice-engine. Fresh `image#v2` + `pdf` assets now render the enriched id; original retained. |
| Low: quarantine says UNRESOLVED despite acknowledgement/resolution | **DONE** — explicit lifecycle (`UNRESOLVED → ACKNOWLEDGED → RESOLVED`) in `order_keys.py` (PR #916, merged). The real ₹4.67 quarantine row — which already carried resolution evidence and the finalized order but a never-flipped status — is now `RESOLVED`. Live health shows `quarantineUnresolved: 0`. |
| Improvement: business payment-health view | **DONE** — `scripts/commerce_health.py`, live result GREEN. |
| Improvement: controlled acceptance-test kit | **DONE** — `scripts/commerce_acceptance_check.py`, read-only per-order surface check, live ALL PASS. Keeps non-financial checks separate from anything that creates a payment. |
| Improvement: automated deployment-consistency checks | **DONE** — folded into `commerce_health.py`: serving index == v2 and ACTIVE, reconciliation rule ENABLED and targeting the webhook `:live` alias. |

## Current live evidence (read-only, this audit)

Payment health (`WeCare/CustomerOrderLink` + table reads):
- paid attempts **1**, missing an order **0**
- orders total **1**, finalized **1**, pending customer link **0** (oldest 0s)
- quarantined captures **1** — unresolved **0**, unacknowledged **0**

Deployment consistency:
- serving index `customerId-createdAt-v2-index`, matches intended, status **ACTIVE**
- reconciliation rule `rate(5 minutes)`, **ENABLED**, targets `wecare-razorpay-webhook:live`

Acceptance (`WD-ORD-TJMG7G4N`), all PASS:
- staff order present; paid + finalized
- website history: on the v2 index, owned by a Cognito sub, carrying channel + customerUuid
- Flow picker: on the phone index

## The three remaining items — each irreducible, none a code gap

| Item | Why it cannot be auto-completed | State / mechanism |
|---|---|---|
| **braces #61 (High)** | GitHub reports no first patched version; the only npm remediation is a breaking `@aws-amplify/backend` major upgrade. Accept-mitigation vs. schedule-the-upgrade is an owner decision. It is **build-time JS tooling** (Amplify CDK synth/deploy); the Lambda runtime is Python, so runtime reachability is nil. | Alert still `open`. Mitigation present and green: `scripts/guard_braces_depth.cjs` bounds parser depth on the build host, `check_braces_advisory.py` keeps the advisory tracked (not falsely closed). |
| **Fresh live customer journey (High for acceptance)** | A real authenticated website checkout + real WhatsApp Flow necessarily **creates a payment and sends messages** — it cannot run unattended, and automatic approval review rejects production mutations. | The **data** is proven on every surface (acceptance kit, ALL PASS). The remaining step is a human confirming **presentation** in the browser and the real Flow. |
| **Owner-gated `--apply` writes** | Live/irreversible: the coupon teardown deletes production infra; the alarm `--apply` writes CloudWatch; live POST access-control probes mutate production. Automatic approval rejected these. | All tooling built, gated, dry-run-verified. Coupon drain gate still refuses (1 invocation in the last 7 days; the gate clears once that ages out, ~Oct 23). `provision_reconciliation_alarms.py --apply` and `provision_lambda_alarms.py --apply` are additive one-command operator actions. |

## Merge/CI note

All commerce work is merged to `stack` (PRs #909 coupon-teardown tooling, #913 unification, #914
alarms+metrics, #916 quarantine-lifecycle + health/acceptance/alarm tooling). A follow-up
maintainer PR #919 fixed a reconciliation test double that stalled the Python suite — unrelated to
behaviour, and the focused commerce suite (337 tests) passes.

## Recommended next sequence (unchanged in spirit, corrected in status)

The earlier report's sequence — dependency alert → acceptance checks → alarms/metrics — is right,
but the alarms/metrics and the health/acceptance tooling it recommended building are **already
merged and verified GREEN**. What remains for an operator:
1. Decide braces #61 (accept the mitigation, or schedule the Amplify Gen2 major upgrade with full backend deploy testing).
2. Run the controlled live customer-journey acceptance test (the one step that creates a payment / sends messages).
3. Run the additive `--apply` for the new alarms, and the coupon teardown once its drain gate clears.
