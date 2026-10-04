# WECARE.DIGITAL checkout — dated findings and closure matrix

**Date:** 2026-10-01 (Asia/Kolkata)
**Mode:** read-only investigation. Nothing was modified, staged, committed or pushed.
**Repo:** `/projects/sandbox/wecare-digital` (`wecare-digital/wecare-digital`), branch `stack`
**HEAD:** `f7304eba16c76cd7beb5f6076e68709fd014340c` — identical to `origin/stack`, working tree clean.
**Handoff baseline `e5a92c3c` is stale by three merged PRs:** #175 (divided phone field), #176 (cart hover), #177 (M3 reference). Never reset to a historical SHA.

### ⚠ Baseline provenance — a concurrent session moved HEAD during this audit

**Every finding below is pinned to `f7304eba16c76cd7beb5f6076e68709fd014340c`**, which was HEAD with a clean tree when measurement began (the clone point, per `git reflog`: `f7304eba HEAD@{2}: clone`).

**While this audit was running, another session committed to `stack` in this shared worktree.** At the end of the audit, `git rev-parse HEAD` reported `39d846957d36a64ef759a82f0a6af3a14c76123c`:

| SHA | Author / time (UTC) | Subject | Files |
|---|---|---|---|
| `99eed122` | Kiro Agent, 08:34:53 | `feat: section 7 checkout pricing calculator and immutable quote snapshot` | `+ shared/lambda_utils/ecommerce/checkout_pricing.py` (464), `+ tests/test_checkout_pricing.py` (298) |
| `39d84695` | Kiro Agent, 08:41:50 | `fix: durable capture quarantine and bound idempotent wallet top-ups` | `payments/razorpay-webhook/handler.py` (+185), `shared/.../order_keys.py` (+180), `messaging/partner-onboarding/handler.py` (+25), `+ scripts/reconcile_captures.py` (131), `+ tests/test_quarantine_recovery.py` (300) |

Plus an uncommitted working tree from that session: `ecommerce/checkout/handler.py` (+33), `shared/.../order_keys.py` (+129), `src/pages/cart.tsx` (+20), `+ tests/test_razorpay_binding.py` (+328), and untracked `shared/lambda_utils/ecommerce/website_checkout.py`, `shared/lambda_utils/integrations/razorpay_orders.py`.

**I did not create, modify, revert, stage or stash any of it.** Per handoff §3 and `git-workflow.md`, that session's work is preserved untouched; no broad staging, reset, force push or blanket stash was performed. The only thing I wrote anywhere in the tree is this report under `.agents/`.

**Consequence for the reader, stated plainly.** Those commits appear, from their messages and file lists, to target several findings in this report — specifically **Group 2** (the 121481-paise calculator and the missing snapshot hash / policy version), **R3/N3** (durable quarantine, plus a `scripts/reconcile_captures.py` sweep), and **N2** (stored top-up intent, provider-verified amount, per-payment idempotency marker). Their commit message for `99eed122` even cites the exact fixture this audit identified as absent: "the mandatory 121481-paise fixture (collection 118000, fee 2950, gst 531, total 121481)."

**I have not audited them.** They landed after measurement and were not part of any suite run reported here. So:

- Rows **Group 2**, **R3/N3** and **N2** below describe the state at `f7304eba` and **must be re-verified against the new HEAD before being treated as open.** They may already be closed.
- The named "highest-risk correctness defect" in §5(c) is **N2**, which `39d84695` claims to fix. That claim is unverified by this audit. Re-run the gates against the new HEAD before acting on §5(c).
- All other rows — Groups 1 (R1, R2, N1, C4–C7), 3, 4, 5, 6, 7, 8, 9, 10 — are unaffected by those two commits on their face, but the uncommitted `website_checkout.py` / `razorpay_orders.py` drafts are plainly aimed at **Group 3**, so that group is also moving.

Anyone implementing from this report must `git fetch` and re-discover HEAD first, as `00-current-owner-overrides.md` requires, and must reconcile with that session rather than overwrite it.

---

## 1. Summary answer, highest-impact first

1. **The website Razorpay Standard Checkout that this handoff exists to deliver does not exist in any form.** There is no browser `checkout.razorpay.com` load, no `Razorpay()` instantiation, no server endpoint that creates a Razorpay order for a cart, and no callback verifying `razorpay_payment_id`/`razorpay_order_id`/`razorpay_signature`. The only Razorpay *order-create* code in the tree is in `amplify/functions/core/secure-files/razorpay_orders.py`, which serves paid file downloads, not commerce. The only checkout handler that exists, `amplify/functions/ecommerce/checkout/handler.py`, is explicitly a **WhatsApp in-chat `order_details`** flow (`CHECKOUT_MODE = "WIX_HEADLESS"`, `_send_order_details`) — precisely the flow the handoff says to remove from the active purchase path. Group 3 is OPEN, essentially in full.

2. **The repository's own approved spec contradicts the handoff on the central architectural decision, and it carries the same date.** `.kiro/specs/whatsapp-wix-commerce/requirements.md:5` records the owner decision as "WhatsApp/Razorpay collects payment externally" with "WhatsApp-only receipts", and statement 10 of its overriding list says "The final confirmation and the receipt are WhatsApp-only." The handoff requires website gateway payment and a downloadable paid receipt. **This is an owner decision that must be settled before implementation, not a gap to code around.**

3. **Highest-risk correctness defect: the wallet top-up path credits money from an unverified webhook body, with no stored intent, no provider readback and no idempotency.** `amplify/functions/payments/razorpay-webhook/handler.py:709-722` reads `notes.purpose`, `notes.wabaId` and `amount_rupees` straight off the event and calls `partner_billing.topup(...)`, which performs an unconditional `balance = balance + :a` (`amplify/functions/shared/lambda_utils/partner_billing.py:153-165`). This runs *before* every verification gate in the same function, and the codebase's own docstrings repeatedly state the webhook signing secret is in public git history, so the signature is not a trust boundary. Detail in R-N2.

4. **The C1 gate leaks.** `_handle_payment_captured` falls through to `_verified_legacy_invoice` on *every* non-order outcome, including the paid-but-blocked ones (`AMOUNT_MISMATCH`, `CURRENCY_MISMATCH`, `CUSTOMER_MISMATCH`, `PROVIDER_PAYMENT_CONFLICT`, `IDENTITY_UNAVAILABLE`), not merely on "no order". Detail in R1/C1.

5. **The legacy verifier has no payment-to-invoice binding and no one-time claim**, so one captured payment can settle more than one unrelated invoice. Detail in R2.

6. **The documented test environment is broken at HEAD.** `requirements-dev.txt` does not resolve: line 30 pins `aiohttp==3.14.3` (needs `multidict<7.0`) while line 65 pins `multidict==7.0.0`, which PR #173 introduced. The documented setup command fails with `ResolutionImpossible`. Detail in Group 10.

7. **`github.com/wecare-digital/material` does not exist.** The handoff's §14 "owner-selected Material ESM library" at `e9324f46` resolves only in the third-party `material-esm/material`. PR #177 is a comment-only change that cites that fork as a *specification* and states explicitly that nothing is installed from it. Detail in Group 8.

8. **What *is* genuinely solid:** the provider-verified reconciliation core (`order_creation.reconcile_payment`, `razorpay_verify.verifier_for_event`, `order_keys` conditional claims), the owned server cart with an exact integer-paise quote (`cart_v2.py` + `customer_cart.py`), the payment-attempt state machine with monotonic ranks, and the public order-number generator. These are well-built, heavily tested, and mostly **not wired to anything the customer can reach**.

### Verification baseline actually executed on this tree

| Gate | Command | Result |
|---|---|---|
| Python suite | `.venv/bin/python -m pytest -q` | **5607 passed, 1 skipped**, 41.49s wall (`real 0m42.579s`) |
| Targeted payment/commerce | `pytest -q tests/test_razorpay_webhook_captured_gating.py tests/test_razorpay_webhook_order_creation.py tests/test_payment_reconciliation_safety.py tests/test_cart_v2.py tests/test_order_keys.py tests/test_side_effect_guard.py tests/test_wix_writeback.py` | **210 passed**, 1.32s |
| TypeScript | `npx tsc --noEmit` | **clean, exit 0**, 12.4s |
| JS/TS suite | `npx vitest run` | **643 passed, 44 files**, 9.47s |
| Node install | `npm ci --no-audit --no-fund` | 782 packages, 10s. Warns `EBADENGINE` — package requires node `>=24.0.0`, sandbox has `v22.23.3` |
| Production build | `npm run build` | **FAILS, exit 1**, 41.2s — not a code defect; see Group 10 |
| AWS identity | `aws sts get-caller-identity` | **fails**, "Unable to locate credentials" |

Environment deviations that the report depends on, stated plainly:

- The suite requires Python ≥3.12 (`conftest.py:44-66` raises a `UsageError` otherwise). The sandbox default is **3.9.25** with no `pytest`. I built `.venv` from `/usr/bin/python3.12` (3.12.14) as `requirements-dev.txt` instructs. `.venv/` and `node_modules/` are both gitignored (`.gitignore:2,49,51`), so the tree stayed clean throughout — `git status --porcelain` reports only the untracked `.agents/` output directory.
- Because `requirements-dev.txt` is unresolvable (finding 6), I installed it with the single `multidict==7.0.0` line removed, which let pip settle on `multidict 6.9.1` alongside `aiohttp 3.14.3`. **The 5607-pass figure is therefore from a tree whose declared dev pins were deviated from in exactly one package.** It is not a clean reproduction of the documented environment, because the documented environment does not install.

---

## 2. Steering files: where they override the handoff

Read in full: `00-current-owner-overrides.md`, `01-standing-authorization.md`, `02-qa-recipient.md`, `secret-handling.md`, `aws-agent-rules.md`, `git-workflow.md`, `PAYMENT-AUDIT-REPORT.md`, `plaintext-source-policy.md`.

| Steering rule | Effect on this handoff |
|---|---|
| `00-current-owner-overrides.md` — "**DO NOT trust dated AWS/GitHub counts in the master prompt.** Before each phase, rediscover current Git HEAD, AWS resources, API routes, Lambda versions/aliases, DynamoDB, IAM, Cognito, provider state." | Binding. Every AWS row below is BLOCKED-ON-ENVIRONMENT rather than answered from a dated file. The same file's own inventory table is explicitly marked "a record of drift rather than a value to reuse" and prefixed "Do not quote counts from this file." |
| `00-...` — WAF **removed** 2026-09-28 by owner cost decision; its absence "is not a gap to close". | Overrides any handoff or audit text treating WAF as a required control. The file also records the live consequence: "there is **no per-IP protection in front of public customer OTP sign-in any more**". |
| `00-...` — Security Hub excluded; GuardDuty optional and non-blocking; admin MFA "not MANDATORY" but still a required target. | Overrides master-prompt blocking semantics. |
| `00-...` — "**Never reset to a historical SHA.**" | Confirms the handoff's own instruction; `e5a92c3c` must not be restored. |
| `git-workflow.md` — single branch `stack`; commit directly to it; never create feature branches; never force push. | Governs any implementation that follows. |
| `aws-agent-rules.md` — account `775261844268`, profile `wecare-prod`, `us-east-1`, key-based auth only, never browser login. **MUST NOT call `secretsmanager get-secret-value`**; use `{{resolve:secretsmanager:...}}` with `asm-exec`. | Honoured: no secret value was read or printed anywhere in this audit. |
| `aws-agent-rules.md` — "`UpdateUserPool` is a full replace, not a patch", with a recorded 2026-09-28 incident that silently deleted all three customer-pool `CUSTOM_AUTH` triggers and flipped `AllowAdminCreateUserOnly` to `false`. Use `scripts/cognito_pool_safe_update.py`. | Directly constrains §15-16 session/identity work. Any Cognito app-client change must go through that script. |
| `PAYMENT-AUDIT-REPORT.md` (`inclusion: manual`, dated **2026-03-30**) scores WhatsApp PG Deep Integration **9.9/10**, "Production-ready", with every validation box ticked. | **Must not be used as evidence for this release.** It audits the in-WhatsApp payment flow that this handoff *removes*, it predates HEAD by six months, its "✅" marks are self-assertions rather than reproducible gates, and it is superseded on the specific question of payment readiness by `docs/execution/headless-checkout-20261001.md` (see §3). It is also internally contradicted by the current tree: it states the convenience fee is "`(collection × 2%) × 1.18`", while the tree is 2.5%. |

`plaintext-source-policy.md` and `secret-handling.md` were observed throughout: the only secret material quoted anywhere in this report is the *reference* `wecare/razorpay/api` (names of secrets and JSON keys), never a value.

---

## 3. The spec contradicts the handoff

`.kiro/specs/whatsapp-wix-commerce/` — `requirements.md` (550 lines), `design.md` (495), `tasks.md` (463).

**`requirements.md:5`, under "Owner architecture decision — 2026-10-01":**

> Use the existing self-managed Next.js/AWS headless application. WhatsApp/Razorpay collects payment externally; create the internal order and Wix order only after authoritative verification, then record the external payment without charging again. Velo and external PSP onboarding are not dependencies. Retain admin-only Cognito and WhatsApp-only receipts.

Points of agreement with the handoff: reuse the existing app rather than rebuild; no Velo; no second PSP; **paid-only order creation**; no double charge. Those are genuinely aligned and the code reflects them.

Points of direct contradiction, all of which are owner decisions:

| Topic | Spec (`requirements.md`, 2026-10-01) | Handoff (2026-10-01) |
|---|---|---|
| Where payment is collected | "WhatsApp/Razorpay collects payment externally" — goal at line ~67: "pay inside WhatsApp" | Website Razorpay Standard Checkout; remove in-WhatsApp payment from the active purchase flow |
| Receipt delivery | Statement 10: "The final confirmation and the receipt are **WhatsApp-only**. No purchase-confirmation email is sent" | Downloadable paid receipt behind an authenticated owner-authorized link |
| Cognito scope | "Retain **admin-only** Cognito" | Complete customer authentication / profile / session ownership / remembered login (§15-16) |
| Payment readiness | Statement 8: "**The Meta payment configuration is currently absent.** A live read returns zero configurations on WABA `2094615664435155`, so payment is disabled until the owner restores it." | Assumes the gateway path can be completed and gated |

Spec statements that the handoff does **not** contradict and that constrain implementation regardless of how the above is settled: public Cognito self-signup stays disabled (statement 1); registration goes through a trusted backend front door, never browser `SignUp` (2); per-IP throttling belongs at the HTTP door because the Cognito trigger receives no client IP (3); a PaymentAttempt exists before payment and an order does not (4); the `reference_id` is minted once from `secrets` and sent byte-for-byte (5); order identity requires a provider readback (6); a failed/cancelled/expired/pending payment creates zero orders, numbers, Wix orders and receipts (7); readiness is provider-driven and no constant or environment variable may enable payment (9).

**`docs/execution/headless-checkout-20261001.md`** is the spec's cited current audit and is the most useful in-repo artifact for this task. Its own dated live-AWS read (2026-09-30 21:41 UTC) reports 66 Lambdas, 359 routes all `AuthorizationType NONE`, `PaymentsTable`/`InvoicesTable`/`OrderTable`/`WixOrderIds` each scanning **zero rows**, `CommerceKeys` absent, and Wix write-back flags unset. It states plainly: "Paid-order code still needs the complete commerce-order materialization and Wix/receipt/confirmation pipeline", and "No claim of full checkout completion, production deployment or current payment readiness." Those counts are **dated**, not current, and per `00-current-owner-overrides.md` must be re-measured; I record them as context, not as evidence.

---

## 4. Closure matrix

Status vocabulary: **MERGED SOURCE** (code exists at HEAD) · **TESTED** (an existing automated test exercises it *and* I ran it here) · **DEPLOYED** · **LIVE VERIFIED** · **OPEN** · **BLOCKED** · **SUPERSEDED**. One status per row. "Source exists" closes no deployment gate.

### Group 1 — payment integrity

#### R1/C1 — does `_handle_payment_captured` fall through to `_verified_legacy_invoice` on rejected/conflicting/unresolved, not merely "no order"?

**Status: OPEN** (the gate is real but its scope is wrong).

**Yes, it falls through on every non-order outcome.** The control flow, `amplify/functions/payments/razorpay-webhook/handler.py:783-800`:

```python
outcome = None
if reference_id:
    outcome = _create_order_for_captured_payment(payment, reference_id, request_id)

verified_paid = bool(outcome and outcome.get('hasOrder'))

legacy_invoice_verified = False
if reference_id and not verified_paid:
    legacy_invoice_verified = _verified_legacy_invoice(
        reference_id, payment, request_id)

financial_success = verified_paid or legacy_invoice_verified

if not financial_success:
    _quarantine_unverified_capture(reference_id, payment_id, outcome, request_id)
    return
```

The guard is `not verified_paid`. `has_order` is true only for `ORDER_CREATED` / `ORDER_ALREADY_EXISTS` (`order_creation.py:118-121`), so the fall-through is taken for **all** of: `NOT_PAID`, `UNKNOWN_REFERENCE`, `ATTEMPT_NOT_PAYABLE`, `PROVIDER_UNAVAILABLE`, `AMOUNT_MISMATCH`, `CURRENCY_MISMATCH`, `CUSTOMER_MISMATCH`, `IDENTITY_UNAVAILABLE`, `PROVIDER_PAYMENT_CONFLICT`, `NO_PROVIDER_ID`, `RECONCILIATION_ERROR`.

The module itself separates these into two sets for exactly this reason (`order_creation.py:86-97`): `NO_ORDER_OUTCOMES` (money did not move) versus `PAID_BUT_BLOCKED_OUTCOMES = {AMOUNT_MISMATCH, CURRENCY_MISMATCH, CUSTOMER_MISMATCH, IDENTITY_UNAVAILABLE, PROVIDER_PAYMENT_CONFLICT}`, documented as "the money DID move but we refused to proceed … the operational response is completely different." **The handler does not consult that distinction.** A `CUSTOMER_MISMATCH` — the attempt belongs to a different customer — or a `PROVIDER_PAYMENT_CONFLICT` — the provider payment is already bound to another attempt — is logged as `PAID_BUT_NO_ORDER` at `handler.py:491-499` and then handed to the legacy verifier anyway. If an invoice row happens to exist for that `referenceId` with a matching total, the capture is marked a financial success and `_store_payment_record` / `_mark_invoice_paid_by_reference` / `_post_payment_handler` / CTWA attribution / the customer `order_status` confirmation all run.

Aggravating factor: `reference_id` is derived from attacker-influenceable event fields — `notes.referenceId`, `notes.reference_id`, `notes.ref`, then `payment.description` if it starts with `WD` (`handler.py:744-762`).

**Fix direction:** branch on `outcome['outcome']`, and permit the legacy path only for `UNKNOWN_REFERENCE`. Every member of `PAID_BUT_BLOCKED_OUTCOMES` must go straight to durable quarantine.

**Partially TESTED:** `tests/test_razorpay_webhook_captured_gating.py` (ran here, part of the 210-pass targeted run) does gate the no-order case and asserts `_mark_invoice_paid_by_phone_and_amount` and `_post_payment_handler` are not reached (`:116-117`). It does **not** cover a paid-but-blocked outcome arriving at a reference that has an invoice row. Needs verification during implementation.

#### R2 — does the legacy helper enforce provider-order / account / payment-to-invoice binding and a unique one-time claim?

**Status: OPEN.** It enforces capture + INR + exact total only. **Yes, one same-price captured payment can settle two unrelated invoices.**

`_verified_legacy_invoice`, `handler.py:575-668`. What it checks: an `InvoicesTable` row exists for the `referenceId` via `referenceId-index`; the invoice total parses to whole paise; `razorpay_verify.payment_is_captured(payment_id)` returns captured; currency is exactly `INR`; `provider_paise == expected_paise`.

What it does **not** check:

- **No provider-order binding.** It calls `razorpay_verify.payment_is_captured(payment_id)` (`razorpay_verify.py:119-134`), which takes a bare payment id and returns `(captured, amount, currency)`. The binding-aware verifier in the same module, `verifier_for_event` (`:152-205`), is *not* used here. That function is the one that refuses when the attempt "has no verified provider binding", when "payment id disagrees with stored binding", and when a "payment belongs to another provider order" — and the commerce path does use it (`handler.py:478-481`). The legacy path bypasses all of it.
- **No account/MID binding.** Nothing compares the payment's Razorpay account against an expected MID on either path.
- **No payment-to-invoice binding.** The only link asserted between the payment and the invoice is *numeric equality of the amount*. The invoice row is not required to carry this `paymentId`, this `order_id`, or any provider identifier.
- **No one-time claim.** `_mark_invoice_paid_by_reference` (`handler.py:1435-1488`) queries the GSI, paginates, and loops `for inv in found: if inv.get('status') != 'paid': update_item(...)`. There is no `ConditionExpression` binding the write to a payment id, and no `PROVIDERPAYMENT#` style marker as used on the commerce path (`order_keys.claim_order_for_payment`). The loop writes to **every** matching row.

Two concrete ways one payment settles two invoices:

1. *Same reference.* Two `InvoicesTable` rows sharing a `referenceId` are both returned by the GSI query and both marked paid by the loop at `handler.py:1463-1480`, from one capture.
2. *Replay across references.* The idempotency key is the **event** key, not the payment id — `payment_status.dedup_key(payload)` consumed by `_is_duplicate_event` (`handler.py:383-412`). A second signature-valid event carrying the *same* `payment_id` but a *different* `notes.referenceId` yields a different dedup key, so it is processed. If the second reference names an unrelated invoice whose total matches to the paise, it is verified and marked paid. Nothing records that this payment id was already consumed. `_is_duplicate_event` additionally **fails open** on error (`:409-411`, "better to process twice than miss").

**Fix direction:** route the legacy path through `verifier_for_event` with a `load_attempt` that reads a stored invoice↔payment binding; add a conditional `PROVIDERPAYMENT#<payment_id>` claim before any invoice write; make `_mark_invoice_paid_by_reference` single-row and conditional on that claim.

**Partially TESTED.** `tests/test_payment_reconciliation_safety.py` covers the sibling `_mark_invoice_paid_by_phone_and_amount` (float-epsilon and multi-match defects, now fixed there). No test asserts single-settlement for `_mark_invoice_paid_by_reference` or cross-reference payment replay. Needs verification during implementation.

#### R3/N3 — is quarantine only an alert log, or durable unresolved intake with leases, retry policy and acknowledgment?

**Status: OPEN.** It is a single log line and nothing else.

`_quarantine_unverified_capture`, `handler.py:669-692`, in its entirety after the docstring:

```python
from lambda_utils.ecommerce import order_creation
category = (outcome or {}).get('outcome') or order_creation.NEEDS_RECONCILIATION
logger.error(json.dumps({
    'event': 'capture_needs_reconciliation',
    'alert': order_creation.NEEDS_RECONCILIATION,
    'outcome': category, 'paymentId': payment_id,
    'referenceId': reference_id or None,
    'stage': 'quarantine', 'requestId': request_id,
}))
```

Its own docstring confirms the scope: "it only emits a single staff alert." There is no intake table, no lease, no retry policy, no acknowledgment state, no owner, no age. I searched for a durable store: the only `NEEDS_RECONCILIATION` occurrences in `amplify/functions/` are the constant definition (`order_creation.py:80`) and these two log fields (`handler.py:682,685`).

**Recoverability after provider retries stop:** the only durable trace is the CloudWatch log line plus the raw `_log_webhook_event` audit row, which carries a **180-day TTL** (`handler.py:355`, `expiresAt = now + 180*24*60*60`). A capture quarantined and not noticed inside the alarm's retention window is recoverable only by a manual Razorpay-side reconciliation. The customer has paid, has no order, and nothing in the system is tracking that fact as open work.

Partial mitigation that does exist and should be preserved: `_dispatch_download_grant_confirmation` has a documented re-run path, `scripts/reconcile_file_deliveries.py` (`handler.py:548-551`). There is no equivalent for commerce captures.

#### N1 — every retained inbound WhatsApp payment producer, and whether each shares one authoritative verification boundary

**Status: OPEN.** There are **two** live producers and they do **not** share a boundary. The weaker one is fail-open by default.

| # | Producer | Entry point | Verification before financial side effects |
|---|---|---|---|
| 1 | **Razorpay direct webhook** | `POST /razorpay-webhook`, `POST /payments/webhook` → `payments/razorpay-webhook/handler.py:86` | HMAC-SHA256 over the raw body (`_verify_signature:293-328`), then `order_creation.reconcile_payment` with the binding-aware `razorpay_verify.verifier_for_event`. **Strongest boundary in the tree** — for the commerce branch only. The legacy branch (R2) and the wallet branch (N2) bypass it. |
| 2 | **Meta/WhatsApp `payment` status webhook** | `messaging/inbound-whatsapp-handler/handler.py:2949-2951` → `_process_payment_status:3212` | **Separate and weaker.** Meta Payment Lookup API only, never Razorpay's API. Reject happens only on an actively contradicting lookup; an *absent* confirmation rejects only when `PAYMENT_LOOKUP_REQUIRED` is truthy, and it is **off by default** (`:3406-3408`). |

Producer 2's own comment states the posture (`:3391-3402`): "Making this fail-closed would alter live payment acceptance, which is not a change to make silently … It is available as `PAYMENT_LOOKUP_REQUIRED`, default off." The consequence at `:3517-3537`: when `verification_outcome` is `UNVERIFIED_NO_CONFIG` or `UNVERIFIED_LOOKUP_FAILED` and the flag is off, it logs `payment_capture_accepted_unverified` at error level and **proceeds** to `_mark_invoice_paid_by_reference`, `_send_order_status_message` and `_generate_invoice_for_captured_payment`. Both no-config and lookup-failure are reachable without any attacker involvement — the former whenever the outbound row carries no `paymentConfigName`, which its own log message says is the case for catalog orders.

Producer 2 performs **no** Razorpay API readback, **no** commerce reconciliation, and **no** amount comparison against a stored authoritative total — `actual_amount` comes from the webhook's own `amount.value / amount.offset` (`:3283`), falling back to a DynamoDB lookup only when it is zero.

Also present but **not** financial-side-effect producers, checked and cleared: `messaging/outbound-whatsapp/handler.py` (composes `order_details`, sends only); `messaging/whatsapp-business-api/handler.py` (payment lookup + refund routes, admin-authenticated); `whatsapp-business-api/flows/postpay.py` (post-payment flow data). `payments/payments-read/handler.py` is read-only.

**SUPERSEDED (one item, proven):** `_mark_invoice_paid_by_phone_and_amount` (`handler.py:1489+`) has **no production caller**. `grep -rn "_mark_invoice_paid_by_phone_and_amount" --include=*.py .` returns the definition plus `tests/test_payment_reconciliation_safety.py` and `tests/test_razorpay_webhook_captured_gating.py` only. Absence of active callers is proven; it is retained dead code with tests pinning its hardened behaviour.

#### N2 — wallet top-up: is a stored intent plus exact captured-payment binding required before one idempotent credit?

**Status: OPEN. This is the highest-risk defect in the audit.** No stored intent, no binding, no idempotency.

The credit path, first branch of `_handle_payment_captured`, `handler.py:709-722`:

```python
if (notes or {}).get('purpose') == 'wallet_topup' and (notes or {}).get('wabaId'):
    try:
        from lambda_utils import partner_billing
        r = partner_billing.topup(notes['wabaId'], amount_rupees,
                                  note=f'Razorpay top-up {payment_id}', actor='customer-service')
        ...
    return
```

Four independent failures, compounding:

1. **It runs before every gate.** This branch is positioned ahead of the C1 reconciliation block (`:783`), so none of the verification added for commerce applies. It `return`s before reaching it.
2. **No provider readback.** `amount_rupees` is `int(payment.get('amount', 0)) / 100` from the event body (`:697-699`). `razorpay_verify` is never called. Which wallet to credit — `notes['wabaId']` — is also read from the event.
3. **No stored intent to bind against.** `_do_topup_order` (`messaging/partner-onboarding/handler.py:576-614`) creates a Razorpay payment link and persists **nothing locally**; the `wabaId` and purpose exist only inside `notes` sent to Razorpay (`:600`). There is no local row for the webhook to match a capture against, so there is nothing a binding check *could* consult.
4. **The credit is not idempotent.** `partner_billing.topup` (`shared/lambda_utils/partner_billing.py:153-165`) is an unconditional `SET balance = balance + :a` with no `ConditionExpression` and no payment-id claim. The only protection against replay is the webhook dedup lease, which keys on the event rather than the payment and **fails open on error** (`handler.py:409-411`).

The trust assumption this rests on is one the codebase itself rejects, in three separate docstrings. `razorpay_verify.py:19-21`: "the webhook signing secret is present in this repository's **public git history**. Anyone who read that history can forge a signature-valid `payment.captured`." `handler.py:531-540` and `order_creation.py:48-52` say the same. Every other branch of this function was hardened on that basis — the secure-file branch was explicitly demoted to "a hint" that "cannot name a file, a recipient, or an amount" (`handler.py:526-551`). **The wallet branch was left trusting the event body for both the amount and the beneficiary.**

Reachability: `POST /razorpay-webhook` is a registered public route (`_routes.json`), WAF is removed by owner decision (`00-current-owner-overrides.md`), and the handler's only pre-checks are the signature and the dedup lease.

**Not TESTED.** No test in the tree exercises the wallet branch of `_handle_payment_captured`; `tests/test_razorpay_webhook_captured_gating.py` covers the invoice/commerce branches.

**Fix direction:** persist a top-up intent at `_do_topup_order` time (waba, paise, status, a minted reference); in the webhook, verify with `verifier_for_event` against that stored intent; claim `PROVIDERPAYMENT#<payment_id>` conditionally; credit from the **stored** paise, never the event's.

#### C4–C7 — stored gateway binding, owned server cart, durable finalization, dependencies/routes/IAM, Wix writeback, recovery

| Row | Finding | Status |
|---|---|---|
| **C4 — stored gateway binding** | The *schema* exists and is correct: `payment_attempt.transition` writes `providerPaymentId` / `providerOrderId` on the `PAYMENT_PAID` transition (`payment_attempt.py:268-282`), `order_keys.resolve_payment_reference` returns `providerPaymentId`, `providerOrderId`, `amountPaise`, `currency`, `customerId` from the `PAYREF#` row (`handler.py:456-473`), and `verifier_for_event` refuses to verify without a binding. **But nothing writes a gateway binding for a website Standard Checkout, because no such initiation exists (Group 3).** The binding is populated today only from the WhatsApp/Meta path. No `mode` (test/live) and no provider **account/MID** is persisted on the attempt anywhere — `EXPECTED_PROVIDER_MID` is a readiness input (`ecommerce/checkout/handler.py:88`) and is not recorded on the attempt. | **OPEN** |
| **C5 — owned server cart** | Genuinely implemented and good. `cart_v2.py` (146 lines) + `customer_cart.py` (193). Identity from `customer_auth`, never the body; a browser cannot supply phone, customerId, Wix cart id or price (`customer_cart.py:57-60`). Commands restricted to an exact field set (`:67-70`). `CUSTOMERCART#<phone>` keying with a `version` + `busy` lock and conditional writes; ambiguous remote writes are never replayed. Wix `calculate` output is validated hard (`cart_v2.py:81-146`): currency all-INR, full quantity availability, blocking violations, catalog-only items, `FULL_PAYMENT_ONLINE`, line totals reconciled to subtotal, components summed against the total, `payNow == total`, no gift cards / memberships / subscriptions / deferred payment, demo carts refused. Exposed at `GET`/`POST /wix-store/cart` (`ecommerce/wix-store/handler.py:272,361-392`). **Two gaps:** gated off by `WIX_CART_V2_ENABLED` (503 when unset, `:371-372`), and **the frontend does not use it** — `src/pages/cart.tsx:59,132` still posts `{action:'create', lineItems}` to `{API_BASE}/ecommerce/checkout`, i.e. line references from the browser, bypassing the owned cart entirely. | **MERGED SOURCE**, not wired |
| **C5 — cart tests** | `tests/test_cart_v2.py` ran here as part of the 210-pass targeted run, against `tests/fixtures/wix_cart_v2_live_demo.json`. | **TESTED** |
| **C6 — Wix writeback** | `shared/lambda_utils/ecommerce/wix_writeback.py` (290 lines) and `side_effect_guard.py` (201) exist and are well-formed. **Neither has any production caller.** `grep -rn "wix_writeback\|side_effect_guard" --include=*.py .` excluding their own files returns only `tests/test_wix_writeback.py` and `tests/test_side_effect_guard.py`. No handler imports either. So no paid order is pushed to Wix, no Wix transaction is recorded, and no inventory is adjusted by the commerce path. | **OPEN** (library only) |
| **C6 — writeback tests** | Both test files ran here and pass — but they test a library no caller invokes. Source existence closes nothing. | **TESTED** (library), **OPEN** (integration) |
| **C7 — durable finalization** | The ordering primitive is correct and is the strongest part of the tree: `reconcile_payment` claims `PROVIDERPAYMENT#<txn>` then `PAYMENTATTEMPT#<id>`, both conditional, then reserves the public number, then records it on the claim, with `_finish_numbering` shared by the first-run and crash-recovery paths (`order_creation.py:270-335`). Forward-only progress is enforced by monotonic ranks (`payment_attempt.py:96-123`, `PAYMENT_PAID: 100` outranking every failure). **But finalization stops at order identity.** The docstring is explicit: "It does not create the Wix order, record the Wix transaction, generate the receipt or send the confirmation." Nothing downstream of identity exists as a wired, durable stage. | **OPEN** |
| **C7 — recovery** | Dedup is a **lease** rather than a permanent claim (`_is_duplicate_event:383-412`, `claim_event_with_lease`), and `_complete_event` is deliberately last on the success path so a crash lets Razorpay's retry through. That specific defect is genuinely fixed and I verified the ordering at `handler.py:271-277`. **But** there is no sweep for quarantined captures (R3), no reconciliation job for stalled attempts, and the lease fails open on error. | **OPEN** |
| **C7 — dependencies / routes / IAM** | Requires live AWS reads. `_routes.json` contains **zero** `ecommerce` entries, and nothing in the tree consumes that file (`grep -rln "_routes.json"` across `*.py`/`*.js`/`*.ts`/`*.yml` returns nothing) — it is a dated inventory snapshot, not configuration. The checkout route is provisioned by `scripts/provision_checkout.py` (`FUNCTION_DIR = amplify/functions/ecommerce/checkout`) and the Lambda is listed in `scripts/deploy_all_lambdas.py:211`. Whether the route, the function version/alias, the DynamoDB tables and the IAM policy actually exist is unverifiable here. | **BLOCKED-ON-ENVIRONMENT** |

Unblock for the C7 AWS row (authorized operator, profile `wecare-prod`, account `775261844268`, `us-east-1`):

```
aws sts get-caller-identity
aws apigatewayv2 get-routes --api-id <current-http-api-id>   # rediscover the id; do not reuse zllr9lrg7j
aws lambda get-function --function-name wecare-ecommerce-checkout
aws lambda get-alias    --function-name wecare-ecommerce-checkout --name live
aws lambda get-function-configuration --function-name wecare-ecommerce-checkout --query Environment.Variables
aws dynamodb describe-table --table-name <PaymentAttempts/CommerceKeys/WixOrderIds>
aws iam get-role-policy --role-name <checkout-exec-role> --policy-name <policy>
python scripts/aws_account_inventory.py    # then read its own error_count; non-zero means PARTIAL
```

### Group 2 — the financial calculation (§7)

**Status overall: OPEN.** The constants agree and the arithmetic reaches the right rupee figure, but there is no single end-to-end calculator producing 121481 integer paise, the one calculator that produces the right number uses floats, and no calculator in the *website checkout* path applies the fee at all.

#### Every active calculator

| # | Location | Rate source | Arithmetic |
|---|---|---|---|
| 1 | `amplify/functions/payments/invoice-engine/handler.py:582-594` | hardcoded `0.025` / `0.18` | **`float`** + `round(x, 2)`, stored in **rupees** via `_dec()` |
| 2 | `amplify/functions/messaging/outbound-whatsapp/handler.py:3081-3141` | `order_details.convenienceFeeRate` default `'0.025'`, `convenienceFeeGstRate` default `'0.18'` | `Decimal`, integer paise, `round_paise()` with `ROUND_HALF_UP` |
| 3 | `src/config/constants.ts:86-89` | `CONVENIENCE_FEE = { percent: 2.5, gstPercent: 18.0 }` | declaration only, no calculator |
| 4 | `src/components/RichTextEditor.tsx:776` | literal `0.18` (`convGst = convBase * 0.18`) | JS float, admin editor surface |
| — | `amplify/functions/ecommerce/checkout/handler.py` | **none** | Takes `wix_ecom.authoritative_total_paise(checkout)` and never adds a fee or GST |
| — | `shared/lambda_utils/ecommerce/cart_v2.py:120-146` | **none** | Consumes Wix `priceSummary` keys `subtotal, discount, delivery, additionalFees, tax, total` as exact paise |

PR #166's constants are present and the three copies now agree at 2.5% / 18%, as the comments claim (`constants.ts:79-85`, `invoice-engine:584-586`, `outbound-whatsapp:3084-3088`). The `constants.ts` comment is candid about the fragility: "no test pins the rate, so nothing else will tell you." I confirmed that — no test asserts 2.5% or 18% anywhere.

**Stale conflicting copy, OPEN:** `amplify/functions/core/faq-handler/handler.py:58,114` still tells customers "A 2% convenience fee + 18% GST applies to all payments" and "Total fee = (Cart × 2%) × 1.18". This is customer-facing FAQ content contradicting the 2.5% policy. `PAYMENT-AUDIT-REPORT.md` repeats the 2% figure too.

#### Does an end-to-end calculation produce 121481 paise for a tax-exclusive ₹1,000 supply?

**No single calculation produces it.** Calculator 1 reaches the right rupee total; nothing converts it to integer paise as a checkout amount.

Tracing calculator 1 with `subtotal=1000`, `gstRate=18`, everything else zero, `entry_point` in `('pay_flow','manual','whatsapp_payment')`:

| Step | Code | Value |
|---|---|---|
| supply GST | `tax = round(1000*1*18/100, 2)` | `180.00` ✓ matches brief's 180 |
| collection | `1000 - 0 + 0 + 0 + 0 + 0 + 180` | `1180.00` ✓ matches brief's 1180 |
| fee base | `conv_base = round(1180*0.025, 2)` | `29.50` ✓ matches brief's 29.50 |
| GST on fee | `conv_gst = round(29.50*0.18, 2)` | `5.31` ✓ matches brief's 5.31 |
| fee total | `round(29.50+5.31, 2)` | `34.81` |
| total | `1000 + 180 + 34.81` | `1214.81` → **121481 paise** ✓ |

So the **policy arithmetic is right** and every intermediate matches the brief. Three caveats that keep this OPEN:

1. **Not exact.** Every operand is a Python `float`; `_dec()` converts to `Decimal` only at the point of storage, after the float rounding has already happened. `round(1180*0.025, 2)` happens to land on 29.5 here, but the design is not exact and the module's own stored unit is **rupees**, not paise. By contrast the commerce path's `money.py` forbids exactly this: "Floats, fractional paise and implicit rounding are forbidden" (`money.py:11`), and `positive_paise` rejects any non-integral `Decimal`.
2. **Unreachable from the website checkout.** Calculator 1 is the invoice engine, driven by `entry_point` values `pay_flow` / `manual` / `whatsapp_payment`. `ecommerce/checkout/handler.py` never calls it and adds no fee; `cart_v2.calculate` takes Wix's totals as final. So the amount a web customer would be charged today contains **no convenience fee and no GST-on-fee**.
3. **No test pins the figure.** `grep -rn "121481\|1214.81"` over `*.py`/`*.ts` returns nothing. The only `5.31` hit is an unrelated collision-probability comment in `order_keys.py:117`.

#### Seller GSTIN, distinct from buyer

**MERGED SOURCE.** `19AAFFW7196L1Z8` is present as the seller GSTIN in six places: `ai/ai-generate-response/handler.py:444`, `inbound-whatsapp-handler/handler.py:5560,5569,5616,5986`, `outbound-whatsapp/handler.py:2116,3023,3286`, `whatsapp-business-api/handler.py:4952`, `whatsapp-business-api/flows/common.py:250`, and as `DEFAULT_GSTIN` in `src/config/constants.ts` (imported by `src/pages/workspace/engage/inbox/index.tsx:23`).

**It is distinct from the buyer GSTIN.** Buyer GSTIN is a separate per-contact field: `amplify/data/resource.ts:124,888` (`gstin: a.string()`), `core/contacts/handler.py:47,194` (writable contact attribute), and the customer-supplied `subscribe-flow.json` form field (`:498-502,561`). No path conflates them. **Concern, needs verification during implementation:** the seller value is a **hardcoded literal in nine locations** rather than one constant, and `outbound-whatsapp/handler.py:516` records that a previous version "carried a stale hardcoded GSTIN default" — the same failure mode the 2% / 2.5% fee divergence already produced.

#### Quote / immutable purchased snapshot with cart revision, expiry, snapshot hash, policy version

**Partially MERGED SOURCE, OPEN overall.** `customer_cart.py` + `cart_v2.py` deliver a real quote:

| Required | Present? | Evidence |
|---|---|---|
| cart revision | **yes** | `cartRevision` asserted equal to `cart["revision"]` and stored (`cart_v2.py:86,141`; `customer_cart.py:176`) |
| expiry | **yes** | `QUOTE_LIFETIME = 300` (5 min); `snapshot["expiresAt"] = self.now + QUOTE_LIFETIME` (`customer_cart.py:19,166`); re-checked on replay (`:101`) and invalidated if the cart moved (`:104-108`) |
| exact integer paise | **yes** | `Money.from_wix` + `positive_paise`; components re-summed against the total (`cart_v2.py:120-136`) |
| provider price binding | **yes** | `calculationId` + opaque `priceVerificationToken` + `purchaseFlowId` persisted (`cart_v2.py:141-146`) |
| **snapshot hash** | **no** | There is a *command* fingerprint — `hashlib.sha256(json.dumps(command, sort_keys=True))` (`customer_cart.py:88`) — which guards requestId reuse, **not** the snapshot contents. No hash is computed over the priced snapshot. |
| **policy version** | **no** | No fee-rate version, GST-policy version or pricing-policy identifier is stored on the snapshot or the attempt. A rate change would silently reinterpret an in-flight quote. |
| **immutable purchased snapshot** | **no** | The quote is a 5-minute pre-payment artifact. Nothing copies it into an immutable post-payment record at capture. `docs/execution/headless-checkout-20261001.md` states the gap itself: "The token is not a Create Order price lock; later paid-order mapping must explicitly verify the snapshot." |

### Group 3 — Razorpay website Standard Checkout (§8)

**Status: OPEN across every sub-item.** Named files follow.

| Sub-item | Finding | Status |
|---|---|---|
| **Browser Standard Checkout** | Absent. `grep -rn "checkout.razorpay.com\|Razorpay(\|razorpay_payment_id\|razorpay_order_id\|razorpay_signature"` across `*.ts`/`*.tsx`/`*.js`/`*.py` (excluding `node_modules`) yields **no** application code — only secret-scanner patterns (`scripts/block_inline_secrets.py:51-52`, `verify_no_secrets_in_tree.py:28`, `masking.py:40,76-77`) and one **negative assertion test**. | **OPEN** |
| **Negative assertion worth knowing** | `tests/test_secure_files.py:655-675`, `test_the_page_never_handles_payment_itself`, actively *enforces absence*: `for gone in ("checkout.razorpay.com", "window.Razorpay", "loadCheckout", "order_id"): assert gone not in source`. Its docstring: "Payment and delivery both happen on WhatsApp, so the browser is out of the loop … there is no callback, because the browser is no longer in the payment path." This test **ran and passed here**. Adding website Standard Checkout to `/get` would fail it; it is scoped to `src/pages/get.tsx`, so a `/cart` implementation need not break it — but it documents the deliberate current direction. | **TESTED** (as absence) |
| **Server initiation** | Only `amplify/functions/ecommerce/checkout/handler.py` (416 lines). It is a **WhatsApp in-chat** initiator: `CHECKOUT_MODE = "WIX_HEADLESS"` (`:78`), `_send_order_details` invokes `POST /wa-business/messages/send/interactive-payment` on `wecare-whatsapp-business-api:live` (`:349-383`). No Razorpay order is created and no browser-payable handoff is produced. | **OPEN** |
| **Server-enforced initiation gate — is it disabled, and where?** | **Yes, disabled, in two independent places.** (a) `INITIATION_ENABLED = str(os.environ.get("CHECKOUT_INITIATION_ENABLED","")).strip().lower() in ("1","true","yes","on")` — `handler.py:95-96`, default off; when off it returns HTTP 200 `PAYMENT_INITIATION_DISABLED` after storing the attempt (`:292-301`). (b) `payment_readiness.evaluate` must return `PAYMENT_READY` first (`:273-281`), and `EXPECTED_CONFIGURATION_NAME` / `EXPECTED_PROVIDER_MID` default to `""` (`:87-88`), which the module treats as `CONFIGURATION_UNVERIFIED`. The handoff's instruction to preserve the cart-preserving disabled response is **already honoured**: `src/pages/cart.tsx:162-178` answers `PAYMENT_INITIATION_DISABLED` inline and does not clear the cart. | **MERGED SOURCE** (correctly disabled) |
| **Durable customer-scoped request key** | Partially present, **not on the checkout path**. The owned cart requires a UUID `requestId` with a durable `CARTOP#<sha256(phone)>#<requestId>` operation record and fingerprint matching (`customer_cart.py:88-110`) — a genuine idempotency key. But `/ecommerce/checkout` `create` accepts **no** request key: `_create` reads only `lineItems` (`:218`), mints a fresh `attempt_id` per call (`:258`), and reserves a fresh `PAYREF#`. Two clicks produce two attempts. No durable browser request key or quote binding on the checkout path, exactly as the handoff states. | **OPEN** |
| **Persisted gateway-order / account / mode / amount binding** | `amountPaise` + `currency` + `customerId` + `wixCheckoutId` are persisted on the `PAYREF#` row and the attempt (`:263-267`, `:272-285`). `providerPaymentId` / `providerOrderId` are written only on the `PAYMENT_PAID` transition (`payment_attempt.py:268-282`), i.e. *after* the fact, never at initiation — because there is no gateway order to bind. **No `mode` (test/live) and no provider account/MID is persisted anywhere.** | **OPEN** |
| **Callback HMAC verified against the SERVER-STORED order id** | **Does not exist.** There is no callback endpoint. The relevant comparison — browser-returned `razorpay_order_id` against a server-stored order id — has no implementation. The closest existing primitive is `razorpay_verify.verifier_for_event`, which *does* refuse when "payment id disagrees with stored binding" and when a "payment belongs to another provider order" (`razorpay_verify.py:167-184`); it is the right building block and is currently used only by the webhook. | **OPEN** |
| **Raw-body webhook verification** | **MERGED SOURCE and correct.** `handler.py:95-103` base64-decodes when `isBase64Encoded`, then `_verify_signature(body, signature)` HMACs the exact body string with SHA-256 and `hmac.compare_digest` (`:293-328`). Fails closed when the secret is unavailable (`:296-300`) and when the header is absent (`:301-303`). Mismatch logging was correctly reduced to `bodyLen` only. | **MERGED SOURCE** |
| **Webhook signature tests** | `tests/test_webhook_signature.py` ran here and passes. | **TESTED** |
| **The old `PAYMENT_REQUEST_SENT` handoff in `/cart/`** | **Still present**, as the handoff states. `src/pages/cart.tsx:132` posts `{action:'create', lineItems}`; `:153-157` routes `PAYMENT_REQUEST_SENT` → `/checkout/status/?a=<paymentAttemptId>`; `src/pages/checkout/status.tsx:97` still treats `PAYMENT_REQUEST_SENT` as an in-flight state. | **OPEN** (to be replaced) |
| **Hosting already anticipates Checkout** | `customHttp.yml` CSP **report-only** already allows `https://checkout.razorpay.com` in `script-src` and `frame-src`, and `api.razorpay.com` / `lumberjack.razorpay.com` in `connect-src`. So the header work is pre-staged, but the enforced CSP is only `object-src 'none'; base-uri 'self'; frame-ancestors 'self'`. | **MERGED SOURCE** (config only) |
| **Deployment / live payment** | Unverifiable here. | **BLOCKED-ON-ENVIRONMENT** |

### Group 4 — order and receipt (§9)

| Sub-item | Finding | Status |
|---|---|---|
| **Public number format** | **Confirmed `WD-ORD-` + 8 CSPRNG chars.** `PUBLIC_ORDER_NUMBER_PREFIX = "WD-ORD-"` (`order_keys.py:108`), `PUBLIC_ORDER_NUMBER_ENTROPY = 8` (`:126`), alphabet `"23456789ABCDEFGHJKMNPQRSTVWXYZ"` — **30** symbols, excluding 0/1/I/L/O/U (`:134`). CSPRNG confirmed: `import secrets` (`:63`) and `secrets.choice(PUBLIC_ORDER_NUMBER_ALPHABET)` in `mint_public_order_number` (`:274,288`), with an explicit note that `random` is rejected because it is "seeded per execution environment" (`:265-270`). | **MERGED SOURCE** |
| **Conditional uniqueness** | **Yes.** `reserve_public_order_number` (`:415`) writes under `ConditionExpression="attribute_not_exists(<key>)"` (`:312`) with `_DEFAULT_ATTEMPTS = 5` regeneration, and `record_order_number_on_claim` uses `"attribute_exists(...) AND attribute_not_exists(orderNumber)"` (`:551`). Reservation, not generation, is what guarantees uniqueness — correctly documented at `:117-127`. | **MERGED SOURCE** |
| **Old 12-char ids still resolve** | **Yes, confirmed.** `LEGACY_PUBLIC_ORDER_NUMBER_LENGTH = 12` with `_LEGACY_PUBLIC_ORDER_NUMBER_RE` (`:155-158`), and the validator at `:213` "Accepts BOTH the current `WD-ORD-XXXXXXXX` form and the bare 12-character form". Nothing mints the legacy form any more (`:153`). A third pattern, `_WD_ORDER_NUMBER_RE` (`:167`), accepts both spaced (`WD-ORD - A1B2C3D4`) and compact Wix-synced forms. | **MERGED SOURCE** |
| **Stale comments describing the old generator** | **Yes, five of them, confirmed present.** `order_keys.py:28` ("12 characters, unambiguous alphabet"), `:164` ("**New checkout orders use the 12-character number instead**" — flatly wrong, they use 8), `:422` ("Generate and durably reserve a unique **12-character** public order number"), `:546` ("order_number is not a valid **12-character** public order number" — a `ValueError` message a developer would read), and `receipt_links.py:40` ("12 characters over a 30-symbol alphabet is guessable at scale"). Documentation-only; the code is correct. Low risk, but `:164` and `:546` actively mislead. | **OPEN** (comment cleanup) |
| **Forward-only finalization stages** | The *state machine* is forward-only and correct: `_RANK` with `PAYMENT_PAID: 100` above every failure state, `RANK_ATTRIBUTE = "attemptRank"`, and `condition_expression()` → `attribute_not_exists(attemptRank) OR attemptRank <= :rank` (`payment_attempt.py:96-123`), applied by `_mark_request_sent` (`checkout/handler.py:396-403`). **But the stages stop at order identity** — no Wix order, transaction, receipt or confirmation stage exists (C6/C7). | **MERGED SOURCE** (attempt states) / **OPEN** (finalization) |
| **Receipt from the immutable paid snapshot, reusing the WhatsApp invoice-engine HTML/PNG/PDF design** | **OPEN.** There is no immutable paid snapshot to generate from (Group 2). The existing generator is the invoice engine's, driven by `POST /invoices/{invoiceId}/generate-image` and `/generate-pdf` (`_routes.json`) off `InvoicesTable` rows — reusable, but not wired to a commerce order. `_post_payment_handler` (`handler.py:1637`) runs the legacy invoice/image path, not a commerce receipt. | **OPEN** |
| **Bounded-expiry private links** | **The primitive exists and is correct.** `shared/lambda_utils/receipt_links.py`: `DEFAULT_TTL_SECONDS` 24h with a checked hard ceiling (`:56-62`), presigned `signed_url`, and a documented 2026-09-30 fix moving receipts from `media_paths.public('stack/invoices/')` to `media_paths.secure(...)` — the prior state was "every receipt ever generated was fetchable forever by anyone holding its URL". Used by `invoice-engine/handler.py:1138-1139`, which "Returns `''` rather than falling back to a CDN URL". The module's reasoning is explicitly right: "A link must be either signed or gated behind a proven session — never derived from an identifier the customer is encouraged to share." | **MERGED SOURCE** |
| **Receipt-link tests** | `tests/test_receipt_links.py` and `tests/test_invoice_assets_are_gated.py` ran here and pass; the latter asserts the code path goes "through the shared signing primitive" (`:116`). | **TESTED** |
| **Authenticated owner-authorized "Download receipt"** | **OPEN, nothing exists.** `grep -rn "Download receipt\|download-receipt\|receipts/"` across `src/**/*.ts(x)` returns **no matches**. There is no receipt route, no receipt UI, and no order-lookup endpoint. `src/pages/orders.tsx:28-32` states it directly: "**NOT YET WIRED TO ANY DATA.** There is no order-lookup endpoint on the public site, and a page that asks for an order number and then cannot answer would be worse than an honest signpost." | **OPEN** |

### Group 5 — auth and session (§6, §16)

#### `src/lib/customerAuth.ts` — the reported behaviour is confirmed exactly

**Status: MERGED SOURCE** (works as designed) / **OPEN** (no backend-owned session).

| Reported | Confirmed | Evidence |
|---|---|---|
| Consumes `AccessToken` / `ExpiresIn` | **yes** | `submitOtp`: `result.AuthenticationResult?.AccessToken`, `expiresAt = Date.now() + (ExpiresIn \|\| 3600) * 1000` |
| Writes token + expiry to `sessionStorage` | **yes** | `storeSession`: `window.sessionStorage.setItem('wecare.customer.accessToken'/'wecare.customer.expiresAt', ...)` |
| Clears in the last 30 seconds | **yes** | `getSession`: `if (Date.now() > expiresAt - 30_000) { clearSession(); return null; }` |
| No refresh-token use | **yes** | The typed response destructures only `{ AccessToken, ExpiresIn }`. `RefreshToken` is never requested, stored or exchanged; no `REFRESH_TOKEN_AUTH` flow anywhere. A 60-minute session simply ends. |

The file is honest about the tradeoff: "It is still readable by script on this origin, which is the normal tradeoff for a browser SPA session." It talks to the Cognito IdP REST API directly because `aws-amplify/auth` is bound to the **staff** pool (`us-east-1_cSx0RHCIR`) while customers live in `us-east-1_46ULYuukt`; `CLIENT_ID` defaults to the public `4avmt9n4gpmkvkdk88qbtit33o` with `GenerateSecret: false`, so no `SECRET_HASH`.

#### Backend-owned session, HttpOnly cookie, CSRF, server-side Cognito token custody

**Status: OPEN — none of the four exist.**

`grep -rni "httponly|set-cookie|csrf|samesite"` across `amplify/functions` and `src/` returns **three** hits, all in `shared/lambda_utils/identity/oauth_pkce.py:32,121,165`, which is OAuth `state` CSRF binding for a provider authorization-code flow — unrelated to the customer session. There is **no** `Set-Cookie` anywhere, no HttpOnly cookie, no CSRF token on any customer mutation, and no server-side token custody. The customer bearer token lives in `sessionStorage` and is attached by the browser.

Mitigating facts that should be weighed rather than ignored: the backend never trusts a body-supplied identity (next row), and the enforced CSP sets `base-uri 'self'` and `frame-ancestors 'self'`. But `script-src` cannot be tightened — `customHttp.yml` explains why: "`next.config.js` sets `output: 'export'`, so there is no server to mint a per-request nonce … **CSP here is NOT meaningful XSS protection.**" With no HttpOnly cookie and no nonce-based CSP, any XSS on the origin yields the customer session.

#### API origins, and whether a same-origin/BFF path is available given static export

**Status: MERGED SOURCE** (a same-origin path already exists).

- **Production API origin is same-origin:** `API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'` (`src/config/constants.ts:20`). So first-party calls already go through the apex, not a raw `execute-api` host.
- **Cognito is cross-origin and unavoidable:** `customerAuth.ts` posts directly to `https://cognito-idp.us-east-1.amazonaws.com/`. CSP `connect-src` permits `'self'`, `https://wecare.digital`, `https://*.execute-api.us-east-1.amazonaws.com`, `cognito-idp`, `cognito-identity`, `api.razorpay.com`, `lumberjack.razorpay.com`, `*.plivo.com`, `*.cloudfront.net`.
- **A BFF is available, but not as Next.js middleware.** `next.config.js:13` sets `output: process.env.NODE_ENV === 'production' ? 'export' : undefined`, so **there is no always-running middleware, no API route and no server render in production**. I confirmed this from the build itself, which emitted: `⚠ Specified "headers" will not automatically work with "output: export"`. A BFF must therefore be an **AWS-side** path — the `/api` prefix already proxied at the apex. That is good news for §16: an HttpOnly-cookie session is achievable without adding a server runtime, by terminating the cookie at a Lambda behind `/api`. The constraint is purely that it cannot live in Next.
- **Corollary worth recording:** the five security headers declared in `next.config.js:28-37` are **inert** in production. `customHttp.yml` is the live source of truth and documents the history — `amplify.yml`'s old `customHeaders:` block was inert for its whole life, and on 2026-09-19 `next.config.js` and the deployed header disagreed about `Permissions-Policy`. Verify deployed headers with `python scripts/verify_deployed_headers.py`, never the file.

#### Phone uniqueness reservation

**Status: OPEN — and this is a second serious defect: the code does not do what its own docstring claims.**

`amplify/functions/auth/customer-registration/handler.py:232-264`. The docstring asserts: "Create an immutable `CUS_<ULID>` customer with a verified phone, **at most once per phone** … The write is conditional on **the phone not already existing** so a race between two verifications collapses to one customer."

The actual write:

```python
record = { "customerId": identity.new_customer_id(), "phone": e164,
           "normalizedPhone": e164, "phoneVerifiedAt": now, ... }
_customers_table().put_item(
    Item=record,
    ConditionExpression="attribute_not_exists(customerId)",
)
```

The table is keyed on `customerId`, and `customerId` is a **freshly minted ULID** on every call. `attribute_not_exists(customerId)` is therefore **always true** — it asserts nothing about the phone. There is no `PHONE#<e164>` reservation item and no conditional write on `normalizedPhone` (which is only a GSI key, and DynamoDB cannot enforce uniqueness on a GSI). Two concurrent OTP verifications for the same number mint two different `CUS_` ids and **both writes succeed**.

The pre-check `_resolve_customer` (`:206-229`) is a GSI query that is explicitly documented as non-authoritative — on failure it "Treat[s] as 'not found'; **the conditional create below is what actually guarantees one customer per phone**." That guarantee does not exist. The losing-race recovery at `:256-262` only triggers on a conditional failure, which cannot occur.

Consequence: one person, two customer records, split order history — precisely the outcome `identity/customer.py:11-16` warns about ("too lax and one person gets two"). By contrast `email-verification/handler.py:279-282` *does* use a real condition (`attribute_exists(customerId) AND attribute_not_exists(emailVerifiedAt)`), so the pattern is understood elsewhere in the same module family.

#### Session-derived customer identity vs body-selected customer id

**Status: MERGED SOURCE and correct. This is done properly.**

`shared/lambda_utils/customer_auth.py`: `authenticate` calls Cognito `GetUser` with the bearer token (proving it is live and unrevoked) **and then** pins the issuer — `if issuer != CUSTOMER_POOL_ISSUER` (`:156-157`) — with the ordering deliberately documented ("the issuer pin runs second to establish *which* pool vouched for it"). This closes the real hazard of a **staff** token being accepted as a customer. `authorize_resource` (`:181`) enforces ownership, and `checkout/handler.py` uses it for every attempt read, returning "Same opaque 401 as unauthenticated, so the endpoint is not an IDOR oracle" (`:211-213`). `customer_cart.execute` takes identity from `customer_auth` and rejects any body-supplied phone / customerId / Wix cart id / price (`customer_cart.py:57-60,67-70`). `_key(identity)` additionally requires a verified E.164 phone (`:76-79`).

**TESTED:** `tests/test_customer_auth_and_throttle.py`, `tests/test_customer_identity.py`, `tests/test_customer_registration_handler.py` all ran and pass here. Note they pass **without** catching the phone-uniqueness defect above, so that gap is also a test gap.

#### Email ownership

**Status: MERGED SOURCE.** `auth/email-verification/handler.py:266-282` stamps `emailVerifiedAt` "at most once" under a genuine `ConditionExpression="attribute_exists(customerId) AND attribute_not_exists(emailVerifiedAt)"`. `identity/customer.py:223,256` keep `phoneVerifiedAt` / `emailVerifiedAt` "deliberately absent rather than `None`" so absence is distinguishable. Normalisation is trim + lowercase only, with a documented refusal to strip dots or `+tags` because "The local part is owned by the receiving server" (`identity/customer.py:17-31`). Reasoning is sound.

#### Remembered login and URL cleanup (§16)

**Status: OPEN.** No refresh token, no remembered login, no device trust — a session ends at 60 minutes with no renewal path. URL cleanup is covered in Group 9.

### Group 6 — phone input and error copy (§6)

#### Actual current state of the phone input after PR #175

**Status: MERGED SOURCE — and it CONFLICTS with the handoff. Not changed. Owner must settle it.**

`src/components/PhoneField.tsx` renders **two focusable controls** inside one visual container: a `<select className="pf-code">` for the dial code, then an `<input className="pf-num" type="tel">` for the national number.

```jsx
<div className="pf">
  <select className="pf-code" aria-label="Country code" value={dialCode} ... >
    { DIAL_CODES.map( entry => (
      <option key={entry.code} value={entry.code}>{ entry.code } { entry.country }</option> ) ) }
  </select>
  <input id={id} className="pf-num" type="tel" inputMode="tel"
         autoComplete="tel-national" placeholder={placeholder} required ... />
</div>
```

The container owns the outline, the 10px radius and the 52px height; the segments own none, "that is what makes it read as one control rather than two boxes that happen to touch." Focus is **per segment**, inset at `outline-offset:-3px`, with a stated WCAG 2.4.7 rationale: a `:focus-within` ring on the container "tells a keyboard user that focus is somewhere in there without saying which half."

**The conflict, stated plainly.** The handoff's §2 table instructs: "#168 … one combined country-code/number input … **Preserve this newer merged UI baseline** instead of restoring the older visible label/separate selector." PR #175, titled "One divided phone field: code segment + number segment", is merged *on top of* #168 at `6a33dfcb` and **reverses** it — the selector is back as a separate `<select>`. So "preserve the newer merged baseline" and "the newest merged code" now point in opposite directions. #175 is the newer of the two and is what is live at HEAD.

This is a **decision the owner must settle**, not a defect to fix and not something this audit should pre-empt. I changed nothing. Note for whoever settles it: #175 carries a substantive accessibility argument (per-segment focus) and a correctness argument recorded in `PhoneField.tsx:17-18` — "the country code is SHOWN rather than inferred … so nobody is quietly signed in as Indian" — so reverting to #168 is not cost-free.

#### The seven required error strings

**Status: MERGED SOURCE — all seven exist verbatim.** `src/pages/account/sign-in.tsx:95-122`:

| # | Key | Verbatim string | Present |
|---|---|---|---|
| 1 | `BAD_NUMBER` | `Enter a valid number.` | ✓ |
| 2 | `NOT_ON_WHATSAPP` | `Use a WhatsApp number.` | ✓ |
| 3 | `CHECK_NUMBER` | `Couldn’t send a code. Check your number.` (U+2019 via `\u2019`) | ✓ |
| 4 | `TRY_LATER` | `Try again shortly.` | ✓ |
| 5 | `BAD_CODE` | `Check your code.` | ✓ |
| 6 | `CODE_EXPIRED` | `Code expired. Send a new one.` | ✓ |
| 7 | `RATE_LIMITED` | `Wait before trying again.` | ✓ |

**Two strings from the older §25 table are deliberately absent, with a documented reason** (`:96-107`): `MISSING_CODE` ("Include your country code, like +91.") and "Choose a country code." Both described states the divided field cannot produce — "there is no input that produces it", and "a `<select>` with a default always has a value." The comment's reasoning is good practice: "Kept out rather than kept dead. A message no code path can reach is one the next person wires to the wrong condition to make it appear." **Flagging because it interacts with the #175/#168 decision above:** if the owner reverts to a single combined input, `MISSING_CODE` becomes reachable again and must be restored.

`NOT_ON_WHATSAPP` is marked "Reserved for provider evidence this page does not yet receive" — the string exists but no current code path selects it. Mapping for the rest is in `messageForAuthError` (`:133-140`), which correctly distinguishes a dead challenge (send a new code) from a throttle (wait), noting that "telling someone who is rate-limited to request another code sends them straight back into the limit."

#### Does any touched validation state resolve to a red computed colour?

**Status: MERGED SOURCE — no. Verified.** `grep -n "#dc2626|#b00020|#ef4444|red|crimson"` over `PhoneField.tsx`, `sign-in.tsx` and `cart.tsx` returns **no colour declarations** — only the substring `red` inside the word `required` and prose in comments. The invalid state is carried by `aria-invalid` on both segments plus page-rendered message text. `PhoneField.tsx:71-74` records the standing instruction: "**NO RED, on standing owner instruction.** The invalid state is carried by aria-invalid and the message the page renders beneath - not by a colour. A control that only says 'wrong' in red says nothing to a colour-blind shopper either way."

### Group 7 — bag control (§10)

**Status: MERGED SOURCE on every sub-item, with one correction to the brief's expectation.**

`src/components/HeaderCart.tsx`:

| Sub-item | Finding |
|---|---|
| 36px glyph in a 44px target | ✓ `.hdr-cart{inline-size:44px;min-height:44px}`; `.hdr-cart-glyph{inline-size:36px;block-size:36px}`. Comment: "36 is the largest even step that keeps a 4px inset on each side"; the 44px target "does NOT grow: it is the WCAG 2.5.8 floor". |
| Quantity inside the bag | ✓ `.hdr-cart-n` is `position:absolute; inset-inline-start:50%; inset-block-start:60%; transform:translate(-50%,-50%)`. The 60% is derived, not guessed: viewBox `0 -960 960 960`, body spans y=-660→-140, centre y=-400 = 58.3%, rounded to the 0.36px step a 36px box can resolve. `font-size:12px`, `tabular-nums`; `99+` drops to 10px via `[data-wide]` because three chars measure 22.56px against a 19.5px hollow body. |
| Rest colour `#1a3a2a` | ✓ `.hdr-cart{color:#1a3a2a}`, glyph `fill:currentColor`, badge `color:currentColor`. |
| **Hover colour and background after #176** | ✓ present — **but the brief's expectation of a "transparent hover background" is now wrong.** `.hdr-cart:hover{background:#d1f470}` — a **lime surface**, with the glyph staying `#1a3a2a`. PR #170 removed the hover *disc*; PR #176 (`d158c652`, "Match the cart hover to the menu icon's hover") then added a lime **rounded square** to match `.nav-trigger`, and moved the radius 50% → 10px for the same reason. The component documents the distinction: the rejected thing was a round *circle* ("dont show back grund rounc cicilr"), and what ships is "the same shape and the same colour as that chip." Measured contrast: `#1a3a2a` on `#d1f470` = 10.03:1. Recording this as a correction rather than a defect. |
| Accessible name | ✓ `aria-label={accessibleName}` on the anchor, computed as `'Shopping Bag'` (count unread) / `'Shopping Bag, empty'` / `` `Shopping Bag, ${count} item(s)` ``. The cost is documented: attribute text is not translated by SupportWidget's text-node walker. |
| Absence of label spans | ✓ Confirmed. No `<span>` carrying label text; the only span is `.hdr-cart-glyph` (`aria-hidden="true"`) and the badge. Comment: "**NO LABEL RULES AT ALL ANY MORE.** The two clipped text nodes this component used to render are deleted." Matches PR #169 (remove hidden bag text nodes, retain accessible attribute name). |
| Focus ring retained | ✓ `.hdr-cart:focus-visible{box-shadow:0 0 0 2px #fff,0 0 0 5px #1a3a2a}` — two-tone, 12.48:1, with a note that a single translucent stop measured 1.44:1 and failed WCAG 1.4.11. |
| `prefers-reduced-motion` | ✓ transition disabled. |

**`public/icons/shopping-bag.svg` exists.** 1472 bytes.

```
sha256  e3e7925a7ba2449bd09d0f2b5be12926822c14ff705eaa25a698988a7ac14792
```

Provenance recorded in the component: Material Symbols Outlined "shopping_bag", 48px, FILL 0 / wght 400 / GRAD 0 / opsz 48, Apache-2.0, recoloured from `#1f1f1f` to `#1a3a2a`. The header renders **inline SVG**, not this file — deliberately: "nothing in the code points at a hosted URL, because a URL that 404s is worse than no URL." So the committed file is for media-prefix upload only, and no runtime behaviour depends on the upload.

**S3 upload status: BLOCKED-ON-ENVIRONMENT.** A local file is not deployment evidence. Unblock:

```
aws s3api head-object --bucket <media-bucket> --key <approved-public-prefix>/icons/shopping-bag.svg
aws s3api head-object --bucket <media-bucket> --key <approved-public-prefix>/icons/shopping-bag.svg \
  --query 'Metadata' --output json      # then compare against the sha256 above
```

Note the `media-prefixes.yml` workflow exists and reported **success** on HEAD, but the related check `Bucket and CDN drift (live AWS)` is **skipped** on HEAD — so no live S3 assertion was made by CI either. Receipts must stay on the `media_paths.secure(...)` prefix and out of this public media prefix (see Group 4).

### Group 8 — Material ESM (§14)

**Status: BLOCKED (owner) — the repository the handoff names does not exist.**

| Question | Answer | Evidence |
|---|---|---|
| Does `github.com/wecare-digital/material` exist / is it reachable? | **No. HTTP 404.** | `gh api repos/wecare-digital/material` → `{"message":"Github returned a client error."}` HTTP 404. `npm install github:wecare-digital/material#e9324f46...` → `git ls-remote ssh://git@github.com/wecare-digital/material.git` → `Permission denied (publickey) … make sure … the repository exists`. |
| Does `e9324f469a95433575e274b0402334076dd02324` resolve? | **Yes — but in `material-esm/material`, not under `wecare-digital`.** | `gh api repos/material-esm/material/commits/e9324f46...` → `{"sha":"e9324f46…","date":"2026-09-30T21:53:03Z","message":"[skip ci] 3.3.4"}` |
| Declared package metadata at that SHA | name `material`, version `3.3.4`, `"type": "module"`, license **Apache-2.0**, `publishConfig.access: public` | `gh api repos/material-esm/material/contents/package.json?ref=e9324f46...` |
| Lit range | **`"lit": "^3.3.1"`** as a regular `dependencies` entry; **no `peerDependencies`** | same |
| Repo identity | not a GitHub fork (`fork: false`, `parent: null`), default branch `main`, `pushed_at` 2026-09-30T21:53:42Z, Apache-2.0 | `gh api repos/material-esm/material` |
| Do `buttons/`, `text/`, `dialog/` exist? | **Yes**, among 34 top-level dirs: `app badge bottom-sheet buttons card carousel checkbox chips demo dialog divider docs icon indicators internal labs list menu nav pickers radio search select shared slider snackbar switch tabs tests text tooltip typography utils` | `gh api repos/material-esm/material/contents?ref=e9324f46...` |
| Directory contents | `buttons/`: `README.md button.js button-group.js fab.js icon-button.js split-button.js` · `text/`: `README.md text-field.js` · `dialog/`: `README.md dialog.js internal/` | same, per directory |
| Can `npm install github:…#<sha>` resolve from this sandbox? | **Under `material-esm`: yes.** `npm install github:material-esm/material#e9324f46...` → "added 7 packages in 6s" (one `npm warn skipping integrity check for git dependency`). Tested in a scratch dir outside the repo; the repo tree stayed clean. **Under `wecare-digital`: no**, as above. | — |

**Element names and APIs.** The authoritative API statement I can cite from source rather than inference is the one PR #177 itself extracted by reading `text/text-field.js`: the fork **collapsed filled and outlined into one element**, `<md-text-field color="outlined">`, replacing `<md-outlined-text-field>`, so the shape token is `--md-text-field-container-shape` and **`--md-outlined-text-field-container-shape` does not exist** in the maintained library. The fork also exposes per-corner logical shape tokens `container-shape-start-start / start-end / end-end / end-start`. Default still resolves `var(--md-text-field-container-shape, var(--md-sys-shape-corner-extra-small, 4px))`. I confirmed the files exist at the pinned SHA but did not transcribe the READMEs further; element-name inventory per directory is **needs verification during implementation** if components beyond the text field are adopted.

**What PR #177 actually changed.** `git show f7304eba --stat`: **one file, `src/components/PhoneField.tsx`, +33/−6, comment-only.** It repoints an M3 citation from `material-components/material-web` to `material-esm/material`, cites both (prose in Google's repo, current code in the fork), and corrects the wrong token name. Its commit message states, in capitals: "**NOTHING IS INSTALLED FROM EITHER REPO**, stated explicitly so a later reader does not mistake the citation for a dependency. Both ship Lit web components; this site is Next.js + styled-jsx with no Lit, so adopting them would add a runtime, a custom-element registry and a second styling system to a page that has none of the three. M3 is used as a spec to measure against." Its recorded gates: "tsc clean, vitest 37/37 in the two affected files, eslint 0 errors / 188 warnings."

**Existing material dependency in the app: none.** `grep -n "material|lit" package.json` → no matches. `grep -n "material-esm|node_modules/material\"|node_modules/lit\"" package-lock.json` → no matches.

**So §14's premise is wrong in two ways**, and both are owner decisions rather than implementable items: the named repository (`wecare-digital/material`) does not exist, and the library the SHA belongs to is cited in-tree as a *specification* with an explicit, reasoned decision **not** to install it. Adopting it would introduce Lit 3.3.1, a custom-element registry and a second styling system into a Next.js + styled-jsx static export. **Do not install it on the strength of the handoff alone.**

### Group 9 — URLs and routing (§15)

#### Is the app a production static export?

**Status: MERGED SOURCE — yes, confirmed from the config and from the build.**

`next.config.js:13`: `output: process.env.NODE_ENV === 'production' ? 'export' : undefined`, with `trailingSlash: true` and `images.unoptimized: true`. The build itself emitted `⚠ Specified "headers" will not automatically work with "output: export"` — twice. **There is therefore no always-running middleware, no API route and no server render in production.** Corollary already noted in Group 5: the `headers` block in `next.config.js` is inert; `customHttp.yml` is live.

#### Customer-facing links pointing at workspace/staff/admin/login surfaces

**Status: MERGED SOURCE — the public surface is clean. No customer-facing staff link found.**

| File:line | Link | Real consumer | Assessment |
|---|---|---|---|
| `src/components/Layout.tsx:275` | `<Link href="/workspace/dashboard">CRM</Link>` | **Staff shell only.** `Layout.tsx` is imported exclusively by `src/pages/workspace/**` (verified: every importer is under `src/pages/workspace/`). | Not customer-facing |
| `src/components/Layout.tsx:276` | `<Link href="/workspace/access">Sign in</Link>` | same — staff brand dropdown | Not customer-facing |
| `src/components/dashboard/tabs/OverviewTab.tsx:68,72,76,80,84,88,92,96,122` | nine `/workspace/*` action cards | staff dashboard tabs | Not customer-facing |
| `src/components/dashboard/tabs/PayTab.tsx:119,120` | `/workspace/contacts`, `/workspace/pay` | staff pay tab | Not customer-facing |
| `src/config/navigation.ts:69-97` (and throughout) | the entire `/workspace/*` nav tree | staff navigation config | Not customer-facing |

The **public** shell is `Header` + `Footer`, centrally inherited via `_app.tsx:32-33,737-742`:

- `src/components/Header.tsx` — the only hard-coded `href` is `"/"` (`:362`); the rest render from config (`:403,431,441`). **No `/workspace`, `/login`, `[retired public path 84a04c24]` or `sign-in` link.**
- `src/components/Footer.tsx` — `grep` for `workspace|/login|/admin|sign-in|Sign in` returns **one comment mention only** (`:6`), no link.
- `src/pages/404.tsx` — two `href`s total: `rel="canonical"` to `https://wecare.digital/` (`:55`) and one CTA `<a className="nf-cta" href="/">Go to WECARE.DIGITAL</a>` (`:66`). **Clean — no staff link, no login link.**

#### Route registration — the older blanket finding does not hold

The handoff is right to say the blanket "every shell is missing" finding should not be repeated. Verified at HEAD:

- All five checkout-relevant routes are in the `_app.tsx` EXACT-MATCH allowlist: `'/cart'` (`:971`), `'/account/sign-in'` (`:972`), `'/checkout/status'` (`:978`), `'/checkout/success'` (`:979`), plus `'/shop/[slug]'` handled as a dynamic route (`:894,899`).
- They render real content, not the empty-body HTTP 200 that a missing allowlist entry would produce. From `out/` after the build: `cart/index.html` 42,432 B · `checkout/status/index.html` 39,671 B · `checkout/success/index.html` 39,986 B · `account/sign-in/index.html` 44,954 B · `orders/index.html` 46,183 B.
- `PageTopBand` is present on exactly the five surfaces claimed: `src/pages/cart.tsx`, `account/sign-in.tsx`, `checkout/status.tsx`, `checkout/success.tsx`, `shop/[slug].tsx`.

**One real inventory gap, OPEN.** `config/public-pages.json` declares **24** public pages and **none of the checkout surfaces are among them**: `/`, `/contact`, `/blog`, `/shop`, `/orders`, `/grahak-os`, `/vayulok`, `/bharat-rx`, `/elsewhere`, `/expo-week`, `/dastavez`, `/clear-closure`, `/ritual-guru`, `/anew`, `/hunar`, `/niji-setu`, `/submit-request`, `/request-amendment`, `/drop-docs`, `/vault`, `/leave-review`, `/refer-and-earn`, `/privacy`, `/terms`. So `/cart`, `/account/sign-in`, `/checkout/status` and `/checkout/success` are absent from the machine-readable public-surface description that feeds `out/llms.txt`, `out/llms-full.txt` and the `/mcp` endpoint. The file warns "THE `pages` ARRAY IS GENERATED. DO NOT HAND-EDIT IT" — regenerate with `node scripts/generate-public-pages.js`. Whether their exclusion is deliberate (transactional pages kept out of AI-facing indexes) or an oversight is **a decision to confirm**, not something to change unilaterally. The build's own check passed: `public-pages: 24 pages — config/public-pages.json is current`.

#### `_routes.json`, hosting redirects, `amplify.yml`

- **`_routes.json`** is a **dated API-route inventory, not configuration.** Nothing in the tree reads it (`grep -rln "_routes.json"` over `*.py`/`*.js`/`*.ts`/`*.yml` → no results). It lists `POST /razorpay-webhook`, `POST /payments/webhook`, `POST /partners/billing/topup-order`, `GET|POST /wix-store/{proxy+}` — and **zero** `ecommerce/*` entries, so the `/ecommerce/checkout` route the cart page posts to is absent from this snapshot. Live route existence is **BLOCKED-ON-ENVIRONMENT** (unblock commands in the C7 row).
- **`amplify.yml`** — frontend-only, no `backend:` phase (the Lambdas are deployed by separate boto3 scripts). `npm ci --no-audit --no-fund` then `npm run build`, then `python3 scripts/verify_public_bundle_secrets.py` as the real credential gate, artifacts from `baseDirectory: out`. Contains **no** redirect/rewrite rules and a prominent instruction not to re-add a `customHeaders:` block.
- **Hosting redirects are NOT in the repo.** `src/pages/orders.tsx:8-13` records that `[retired public path aaee9dd4]` → `/orders` is a 301 from "the Amplify customRules written by `scripts/provision_legacy_redirects.py` (**RETIRED**)". So the live redirect set is Amplify app state with its generator retired — **BLOCKED-ON-ENVIRONMENT**. Unblock: `aws amplify get-app --app-id d22dm4b0jn71jw --query 'app.customRules'`.
- **URL cleanup (§15)** — no customer-facing leak found on the public shell, so the remaining §15 work is the Amplify `customRules` review above plus the `public-pages.json` decision. Nothing was changed.

### Group 10 — tests and checks

#### Suites found and run

| Suite | Runner | Command | Result |
|---|---|---|---|
| Python | pytest, `--import-mode=importlib`, `testpaths = tests amplify/functions` (`pytest.ini`) | `.venv/bin/python -m pytest -q` | **5607 passed, 1 skipped**, 41.49s (`real 0m42.579s`) |
| JS/TS | vitest + jsdom (`vitest.config.ts`) | `npx vitest run` | **643 passed, 44 files**, 9.47s |
| Typecheck | tsc | `npx tsc --noEmit` | **clean, exit 0**, 12.4s |
| Build | next (static export) | `npm run build` | **exit 1** — see below |

Dependencies **were** installable: the sandbox has network access. Nothing is reported as passing that did not run.

#### The documented Python environment does not install — OPEN

`conftest.py:44-66` hard-refuses Python < 3.12 with a `UsageError`. Sandbox default is **3.9.25** with no `pytest`; `/usr/bin/python3.12` (3.12.14) and pyenv 3.10–3.14 are available. Following `requirements-dev.txt`'s own instructions:

```
/usr/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
→ ERROR: Cannot install -r requirements-dev.txt (line 30) and multidict==7.0.0
  because these package versions have conflicting dependencies.
  The conflict is caused by:
      The user requested multidict==7.0.0
      aiohttp 3.14.3 depends on multidict<7.0 and >=4.5
  ERROR: ResolutionImpossible
```

`requirements-dev.txt:65` pins `multidict==7.0.0` (introduced by **PR #173**, "bump multidict from 6.9.0 to 7.0.0") while line 30 pins `aiohttp==3.14.3`, which caps `multidict<7.0`. The file calls itself a "Full freeze, so a rebuilt venv matches byte for byte" — it cannot be rebuilt at all. **This is a real defect at HEAD, and it is exactly the risk the handoff's §2 note about PRs #171-#174 warns against:** the dependency bumps must not be read as checkout progress, and here one of them broke the documented dev setup. I worked around it by dropping that single pin, which resolved `multidict 6.9.1` + `aiohttp 3.14.3`. **Fix:** bump `aiohttp` to a release accepting `multidict>=7`, or revert `multidict` to `6.9.x`. CI does not catch it — see below.

#### The production build fails, for an environmental reason — needs verification on a network-clean host

```
Running TypeScript ... Finished TypeScript in 15.7s      ✓
Compiled successfully in 8.0s                            ✓
Generating static pages using 7 workers (772/1545) ...
Error occurred prerendering page "/post/banana-walnut-loaf"
Error: post banana-walnut-loaf: gave up after 4 attempts (last: HTTP 429).
  at m (src/lib/public-blog.ts:260:9)
⨯ Next.js build worker exited with code: 1
BUILD_EXIT=1     real 0m41.186s
```

`npm run build` fetches **live blog content** at build time and fails closed on exhausted retries (`src/lib/public-blog.ts:255-263`), by design: "Failing the build on purpose - continuing would emit an index that links pages which were never generated." The failure is an upstream **HTTP 429**, not a code or type defect — TypeScript and compilation both succeeded inside the same run. **So the build is not offline-reproducible and is rate-limit-sensitive.** It did emit 1,528 HTML files / **140 MB** into `out/` before aborting, which is how I verified the checkout pages render (Group 9); treat `out/` as partial. Two other notes: `npm ci` warns `EBADENGINE` (package requires node `>=24.0.0`, sandbox has `v22.23.3`; `amplify.yml` does `nvm install 24`), and the static-export `headers` warning appears twice.

#### GitHub Actions — real conclusions

19 workflows in `.github/workflows/`. Checkout-relevant: `build-test.yml`, `codeql.yml`, `route-auth.yml`, `provider-policy.yml`, `media-prefixes.yml`, `ui-labels.yml`, `kiro-review.yml`.

**At HEAD `f7304eba`** (`gh api .../actions/runs?head_sha=f7304eba...` and `.../commits/f7304eba.../check-runs`):

| Conclusion | Check |
|---|---|
| success | Build and test · Build, typecheck and test |
| success | CodeQL Advanced · Analyze (actions) · Analyze (javascript-typescript) · Analyze (python) |
| success | Route auth · Route auth drift (live AWS) · Handler auth enforcement (source) · Key rooting and import order (source) |
| success | Provider policy · Provider policy gate · Product vocabulary gate · UI labels · Media prefixes · Sync Gastronomy quality branch · sync |
| **skipped** | **Bucket and CDN drift (live AWS)** |

**A skipped check is not a pass.** `Bucket and CDN drift (live AWS)` did not run on HEAD, so the S3/CDN state behind Group 7's icon upload and the receipt prefixes is unasserted by CI as well as by me. `Route auth drift (live AWS)` reports success on HEAD but was **skipped** on PR #166's head — worth confirming it genuinely performed live reads rather than short-circuiting, which I cannot determine from the conclusion alone. Also note CI's Python suite cannot be catching the `requirements-dev.txt` conflict, since `Build, typecheck and test` is green at HEAD while the file does not resolve — so CI installs differently from the documented path.

**The PR #166 `github-advanced-security` failure — found, and it WAS resolved afterwards.** PR #166 (`3edf5b436a4ddc89458891de0a796d8d19e5a14c`, merged 2026-10-01T02:51:36Z, "Public-page design compliance, Shopping Bag header cart, and the owner error-copy table"):

| Conclusion | Check |
|---|---|
| **failure** | **github-advanced-security** |
| neutral | CodeQL |
| **skipped** | Bucket and CDN drift (live AWS) · **Route auth drift (live AWS)** |
| success | Build, typecheck and test · Analyze (actions/javascript-typescript/python) · Handler auth enforcement · Key rooting and import order · plivo-tests · Product vocabulary gate · Provider policy gate · Review the diff |

So **#166 was merged with a failing security check and two skipped live-AWS checks.** Tracking that job forward across later PRs:

| PR | head sha | `github-advanced-security` |
|---|---|---|
| #166 | `3edf5b43` | **failure** |
| #170 | `2fe76518` | success |
| #175 | `72016a76` | success |
| #176 | `71b28d1d` | success |
| #177 | `c37c8e25` | success |
| #178 | `90629e82` | success |

It passes on every subsequent PR, so the finding was resolved rather than merely silenced — but **note it does not appear at all in HEAD's check-run list**, because it is a pull-request-scoped job. Branch-level green on `stack` therefore does not include it. Per the handoff's own caution: do not treat later success as proof that every earlier finding was remediated — I did not retrieve the specific #166 alert text, so **what it flagged is unverified**. Unblock: `gh api repos/wecare-digital/wecare-digital/code-scanning/alerts --jq '.[] | {number,state,rule:.rule.id,path:.most_recent_instance.location.path}'` with a token carrying `security_events`.

**Live PR activity during this audit:** PR #178 exists and runs were in flight at `43b26d4a`, `da17f91e`, `7795d5c1` (one `Build and test` **cancelled** at `da17f91e`). HEAD moved underneath the remote during the audit window; anyone implementing must re-fetch and re-discover rather than assume `f7304eba`.

---

## 5. Conclusions

### (a) Genuinely implementable in THIS sandbox, without AWS — in dependency order

1. **Fix the `requirements-dev.txt` resolution conflict** (Group 10). Bump `aiohttp` past the `multidict<7.0` cap or revert `multidict` to `6.9.x`. One-line change, verified by `python3.12 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q`. Do this first — it is the gate on every other item's verification being reproducible.
2. **Harden the wallet top-up credit path** (N2, the highest-risk defect). Persist a top-up intent in `_do_topup_order`; verify via `razorpay_verify.verifier_for_event` against that stored intent; add a conditional `PROVIDERPAYMENT#<payment_id>` claim; credit from stored paise. Pure-Python, fully unit-testable offline with injected fakes, as `tests/test_razorpay_webhook_order_creation.py` already demonstrates.
3. **Narrow the C1 fall-through** (R1). Branch on `outcome['outcome']` and allow `_verified_legacy_invoice` only for `UNKNOWN_REFERENCE`; route all of `PAID_BUT_BLOCKED_OUTCOMES` to quarantine. Add the missing test: paid-but-blocked outcome at a reference that has an invoice row.
4. **Bind and claim the legacy invoice path** (R2). Route it through `verifier_for_event`; add a one-time payment claim; make `_mark_invoice_paid_by_reference` single-row and conditional. Add tests for cross-reference payment replay and multi-row settlement.
5. **Fix phone uniqueness** (Group 5). Replace `attribute_not_exists(customerId)` with a real `PHONE#<e164>` reservation item under a conditional write, and correct the docstring that currently claims a guarantee the code lacks. Testable offline.
6. **Add durable unresolved-capture intake** (R3/N3). A table/row shape with lease, retry policy, acknowledgment and age, plus a sweep script modelled on the existing `scripts/reconcile_file_deliveries.py`. Table creation is AWS, but the module, its state machine and its tests are offline work.
7. **Unify the second WhatsApp payment producer onto one boundary** (N1). Make `PAYMENT_LOOKUP_REQUIRED` default-on, or better, route `_process_payment_status` through the same `reconcile_payment` boundary. **Behaviour-changing on live payment acceptance — needs owner sign-off before merge**, and the code itself says so.
8. **Add the exact-paise fee/GST calculator** (Group 2), as a new pure module using `Decimal`/integer paise in the style of `money.py`, with a test pinning the 121481-paise case and the 2.5%/18% rates. Remove the stale 2% FAQ copy at `core/faq-handler/handler.py:58,114`.
9. **Add snapshot hash + policy version to the quote, and an immutable paid snapshot** (Group 2). Extends `cart_v2.calculate` / `customer_cart`, both of which have strong existing test coverage.
10. **Wire `wix_writeback` and `side_effect_guard` into a guarded post-payment stage** (C6/C7). The libraries and their tests exist; only the caller and its sequencing are missing. Offline-testable with injected clients; activation stays flag-gated.
11. **Clean the five stale 12-character comments** (Group 4) at `order_keys.py:28,164,422,546` and `receipt_links.py:40`. Comment-only; `:546` is a user-visible `ValueError` message.
12. **Regenerate / decide `config/public-pages.json`** for the checkout surfaces (Group 9) via `node scripts/generate-public-pages.js` — after the owner confirms whether transactional pages belong in the AI-facing index.

Deliberately **not** on this list: website Standard Checkout initiation and callback (Group 3). It is mechanically implementable offline, but it is the single thing the spec contradicts (§3), so it must not start before the owner settles the architecture.

### (b) Blocked on AWS / provider / owner, with the exact unblock action

| # | Blocked item | Blocked on | Exact unblock action |
|---|---|---|---|
| 1 | **Website vs in-WhatsApp payment collection** — the central architecture | **Owner** | Settle `requirements.md:5` + statement 10 ("WhatsApp-only receipts") against the handoff's Standard Checkout requirement, and amend the spec. Everything in Group 3 and Group 4's receipt rows depends on this. |
| 2 | **Phone field: divided (#175) vs combined (#168)** | **Owner** | Choose. If combined, restore `MISSING_CODE` ("Include your country code, like +91.") and re-examine the per-segment focus rationale in `PhoneField.tsx:63-70`. |
| 3 | **Material ESM §14** | **Owner** | `wecare-digital/material` returns 404. Confirm whether `material-esm/material@e9324f46` is actually to be installed, against PR #177's explicit in-tree decision not to (adds Lit 3.3.1 + a custom-element registry + a second styling system). |
| 4 | **Meta payment configuration absent** | **Owner / Meta** | Spec statement 8: a live read returned zero configurations on WABA `2094615664435155`. Restore it, then re-read: `GET /{waba}/payment_configurations`. Until then `payment_readiness.evaluate` correctly refuses and no initiation can be enabled. |
| 5 | **Route / Lambda / table / IAM existence** | AWS | `aws sts get-caller-identity`; `aws apigatewayv2 get-routes --api-id <rediscovered-id>`; `aws lambda get-function --function-name wecare-ecommerce-checkout`; `aws lambda get-alias --function-name wecare-ecommerce-checkout --name live`; `aws dynamodb describe-table --table-name <PaymentAttempts/CommerceKeys/WixOrderIds>`; `aws iam get-role-policy --role-name <checkout-exec-role> --policy-name <policy>`; `python scripts/aws_account_inventory.py` (then check its `error_count`). |
| 6 | **Checkout env flags actually set in the deployed function** | AWS | `aws lambda get-function-configuration --function-name wecare-ecommerce-checkout --query Environment.Variables` — confirm `CHECKOUT_INITIATION_ENABLED`, `EXPECTED_CONFIGURATION_NAME`, `EXPECTED_PROVIDER_MID`, `WIX_CART_V2_ENABLED` are absent/false. |
| 7 | **`shopping-bag.svg` S3 upload** | AWS | `aws s3api head-object --bucket <media-bucket> --key <approved-prefix>/icons/shopping-bag.svg`, then compare against sha256 `e3e7925a7ba2449bd09d0f2b5be12926822c14ff705eaa25a698988a7ac14792`. |
| 8 | **Live hosting redirects / legacy URL rules** | AWS | `aws amplify get-app --app-id d22dm4b0jn71jw --query 'app.customRules'` — the generator `scripts/provision_legacy_redirects.py` is RETIRED, so app state is the only source. |
| 9 | **Deployed security headers** | AWS | `python scripts/verify_deployed_headers.py` — never trust `next.config.js` or the file. |
| 10 | **Cognito customer app-client / trigger configuration** | AWS | `aws cognito-idp describe-user-pool --user-pool-id us-east-1_46ULYuukt`; `describe-user-pool-client`. **Any change must go through `python scripts/cognito_pool_safe_update.py --pool-id <id> --set Field=Value --apply`** — never a partial `update-user-pool` (`aws-agent-rules.md` records the 2026-09-28 incident that deleted all three `CUSTOM_AUTH` triggers and opened self-signup). |
| 11 | **Razorpay secret presence/shape** | AWS | Confirm `wecare/razorpay/api` holds `key_id`/`key_secret` by reference only — `aws secretsmanager describe-secret --secret-id wecare/razorpay/api`. **MUST NOT** call `get-secret-value`. |
| 12 | **PR #166 security-alert content** | GitHub token scope | `gh api repos/wecare-digital/wecare-digital/code-scanning/alerts` with `security_events`. What it flagged remains unverified. |
| 13 | **Live payment / monetary test** | Owner + provider | Out of scope for this instruction. QA recipient `+918100640044` is nominated but a monetary test needs its own authorized scope. Payment capture/refund, provider config mutation, credential rotation, live-send enablement and publishing all remain outside. |
| 14 | **Offline-reproducible production build** | Upstream rate limit | `npm run build` fetches live blog content and failed on HTTP 429. Re-run on a host with unthrottled access, or add a build-time content cache. |

### (c) The single highest-risk correctness defect

**Unverified, unbound, non-idempotent wallet credit from a forgeable webhook body.**

**File and line:** `amplify/functions/payments/razorpay-webhook/handler.py:709-722`, with the credit executed at `amplify/functions/shared/lambda_utils/partner_billing.py:153-165`.

```python
# handler.py:709
if (notes or {}).get('purpose') == 'wallet_topup' and (notes or {}).get('wabaId'):
    r = partner_billing.topup(notes['wabaId'], amount_rupees,
                              note=f'Razorpay top-up {payment_id}', actor='customer-service')
    return
```

```python
# partner_billing.py:155
resp = _wallet_tbl().update_item(
    Key={'wabaId': waba_id},
    UpdateExpression='SET balance = balance + :a, #s = :active, updatedAt = :t',
    ...)
```

Why this one ranks above R1, R2 and the phone-uniqueness defect: it is the only path where a single unauthenticated request **creates monetary value directly**, and all four of its controls are missing at once rather than one. Both the *amount* (`amount_rupees`, from `payment.amount`) and the *beneficiary* (`notes.wabaId`) are read from the event body; `razorpay_verify` is never called on this branch; `_do_topup_order` persists **nothing locally**, so there is no stored intent a binding check could consult even in principle; and the credit is an unconditional increment with no payment-id claim, protected only by a dedup lease that keys on the event rather than the payment and **fails open on error** (`handler.py:409-411`).

The decisive aggravator is that the repository **already knows the signature is not a trust boundary** and says so three times — `razorpay_verify.py:19-21`, `handler.py:531-540`, `order_creation.py:48-52`: "the webhook signing secret is present in this repository's **public git history**. Anyone who read that history can forge a signature-valid `payment.captured`." Every sibling branch of this exact function was hardened on that basis; the secure-file branch was deliberately demoted to "a hint" that "cannot name a file, a recipient, or an amount." The wallet branch sits above all of that hardening, reached first, and `return`s before any of it runs. It also has **no test coverage**.

Runner-up, and the one to fix next: **R2** — `_verified_legacy_invoice` (`handler.py:575-668`) plus `_mark_invoice_paid_by_reference` (`handler.py:1435-1488`), where the absence of a payment-to-invoice binding and of a one-time claim lets one captured payment settle two unrelated invoices.

---

## 6. Standing caveats

- **Source existence closes no deployment gate.** Every row marked MERGED SOURCE means code is present at `f7304eba` and nothing more. DEPLOYED and LIVE VERIFIED are unobtainable in this sandbox and are recorded as BLOCKED-ON-ENVIRONMENT throughout.
- **No dated count from any steering file or execution doc is used as current evidence**, per `00-current-owner-overrides.md`. Where I cite `docs/execution/headless-checkout-20261001.md`, it is labelled as dated context.
- **Items I could not reproduce or fully verify** are named as such rather than dismissed: element-name/API inventory for `material-esm` components beyond the text field; whether `Route auth drift (live AWS)` performed genuine live reads on HEAD; what PR #166's `github-advanced-security` alert actually flagged; and whether the production build passes on an unthrottled host. Each is marked **needs verification during implementation**.
- **No defect was dismissed because the code "looks fine."** Where the code is genuinely strong — `order_creation`, `razorpay_verify.verifier_for_event`, `order_keys`, `cart_v2`, `payment_attempt`, `customer_auth`, `receipt_links` — I said so and then recorded that most of it is **not wired to a customer-reachable path**, which is the actual gap.
- **Findings are pinned to `f7304eba`.** A concurrent session advanced HEAD to `39d84695` mid-audit and left uncommitted work in the tree. See the baseline-provenance box at the top: Groups 2, 3 and rows R3/N3 and N2 are actively moving and must be re-verified against current HEAD. I audited none of that work and preserved all of it.
- **Read-only honoured.** I edited no code and staged, committed or pushed nothing; no payment was created, captured, refunded or mutated; no WhatsApp message sent; no secret value read or printed (`get-secret-value` never called); no server restarted. The only file I wrote in the tree is this report under `.agents/`. Build/test artifacts I created (`node_modules/`, `.venv/`, `out/`) are all gitignored (`.gitignore:2,49,51`) and left no tracked-file footprint; the scratch `npm install` test for Group 8 ran outside the repo. The modified and untracked source files now visible in `git status` belong to the concurrent session, not to me.

