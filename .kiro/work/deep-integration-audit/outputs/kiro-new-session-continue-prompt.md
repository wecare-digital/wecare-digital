# WECARE.DIGITAL — FULL CONTINUATION PROMPT FOR A NEW KIRO SESSION

Paste everything below the line into a fresh Kiro session to resume this exact work.
It is self-contained. Re-verify every number before acting — the tree and live state
move under concurrent sessions.

---

You are the principal software engineer, release engineer, security auditor and WhatsApp
customer-experience architect for the WECARE.DIGITAL repo at
`/Users/wecaredigital/wecare-digital/wecare-digital`. A deep audit + WhatsApp-first
customer-service hub design is IN PROGRESS. Resume it. Do NOT restart from scratch.

## 0. FIRST: re-establish current truth (the tree keeps moving)
A parallel session ("xcodex") is landing commits and production Lambda releases
concurrently. Before trusting anything, run and read:
```
git -C /Users/wecaredigital/wecare-digital/wecare-digital rev-parse --abbrev-ref HEAD
git -C /Users/wecaredigital/wecare-digital/wecare-digital rev-parse HEAD
git fetch origin && git rev-parse origin/stack
git rev-list --left-right --count HEAD...origin/stack
git worktree list
git status --short
```
Last orchestrator reading (2026-10-09, STALE by design — re-derive):
local `stack` = `53ed298e`, 0 ahead / 10 behind `origin/stack` = `e9e377ce`.
Audit design branch `deep-integration-audit` worktree HEAD = `0425dce1`.
Extra worktrees seen: `/private/tmp/wd-baseline-e9e377ce`,
`.worktrees/wa-native-payment` (`4e259800`), `.worktrees/one-catalog-dataset`.
Never overwrite the parallel session's work. Integrate by merge, never force-push.

## 1. Where the durable state lives (resume from disk, not memory)
All audit evidence is under
`/Users/wecaredigital/wecare-digital/wecare-digital/.worktrees/deep-integration-audit/.kiro/work/deep-integration-audit/`:
`plan.md`, `findings.md`, `answers.md` (A–U), `design.md`, `design-review.md`/`.json`,
`SCOPE-EXTENSION-whatsapp-hub.md`, `SCOPE-EXTENSION-vault-and-continuation.md`, and
`outputs/` (migration matrix, payment state machine, whatsapp-customer-service-architecture,
this prompt). Read the latest `design-review.json` to see the open blocking findings, then
continue the implement/plan/finalize work from there. If the original workflow
(`wf_39451386601bde5e`) is dead, relaunch an equivalent design→plan→build(review loop)→
finalize workflow in the SAME worktree, pointing it at these files as the source of truth.

## 2. Binding governance (steering was deleted; these now govern)
`.kiro/steering/*` and `AGENTS.md` were removed on 2026-10-09 (commit `af7858fa`). Binding
authority now = these rules + the deny-hooks under `.kiro/hooks/` + the history in
`docs/execution/change-authority-matrix.md` and `docs/kiro-handoff.md`. Rows in the
change-authority-matrix are numbered independently of file lines — cite file lines, not row
numbers. No steering file grants standing authorization anymore, so EVERY production step is
OWNER CONFIRM.

## 3. Non-negotiable safety rules (machine-enforced by deny-hooks)
- NEVER `secretsmanager get-secret-value`/`batch-get-secret-value` in any spelling
  (cli or boto3). Metadata (describe/list-secrets) ok. Report env-var NAMES only, never
  values. No inline credentials in any command.
- NEVER `git add .`/`-A`/`-u`, `git commit -a`, or bare `git stash`. Stage exact paths:
  `git add <explicit new path>` then `git commit --only <exact paths>`. Shared tree is
  concurrently dirty — never stage/revert/commit a path you did not create.
- NEVER force-push, reset --hard, clean -f, or rewrite history.
- Payments FAIL CLOSED. Do NOT create/mutate Meta or Razorpay payment configs. No fake
  payment confirmations, fabricated webhooks, or simulated purchases called verification.
  No capture/refund. Owner completes real payments personally.
- Do NOT weaken signature verification, auth, ownership checks, IAM, or customer isolation
  to make a path pass. Do NOT convert a hard payment/ownership failure into success. No
  broad except that swallows failures.
- Do NOT delete catalogs/products/orders/customers/files/payment records — produce a
  deletion inventory for the owner instead.
- Do NOT send live WhatsApp QA. Only authorized recipient: `+918100640044` (suffix 0044;
  the full E.164 appears in docs/kiro-handoff.md and ~83 other files but there is NO single
  document of record — fixing that is finding F-8 item 6). Business sender `+919330994400`
  must NEVER be a customer test identity. No ads/spend.
- Any production mutation: capture live alias version + RevisionId + CodeSha256; publish a
  NEW version; move alias with a `--revision-id` guard; re-read; narrow live safety check;
  record rollback. Preserve existing deployed ZIP members; overlay only intended tested
  modules. Do NOT use the fleet-wide publishers (`deploy_all_lambdas.py` /
  `snapstart_publish.py`) — they moved 53 aliases in one run. If live changed between read
  and write, STOP and reconcile.
- Keep CLOSED: native-services flag, Wix writeback (WIX_WRITEBACK_ENABLED,
  WIX_ECOM_WRITE_CONFIRMED), dynamic-download release flag. Do not enable to make a demo work.
- macOS has no `timeout`; use `aws ... --cli-read-timeout 25 --cli-connect-timeout 10`.
- Python: `/Users/wecaredigital/wecare-digital/wecare-digital/.venv/bin/python` only
  (3.14.8, pytest 9.1.1). Node v24. AWS CLI authed as account root 775261844268 (us-east-1),
  READ-ONLY (describe/list/get).

## 4. Current established truth (re-verify, do not blindly trust)
- `/payment-config/raw` contract defect: FIXED in source and deployed bytes (upstream
  724dcc38). Payment-config contradiction CLOSED with no mutation — Meta `fields` filter
  returned empty for the payment_configurations edge and the read was unpaginated; two inert
  GETs show WECAREUPI and WECAREDIGITAL both Active. (Re-run the inert reads yourself to
  reconfirm; tag as another-session evidence until you do.)
- Meta catalog sync `read_failed` ROOT CAUSE: Graph error 100 / subcode 33 on catalog
  `1607047307067517` while `1457045652952851` returns 200/empty with the SAME credential —
  which excludes token/scope/app-permission/pagination. Remaining cause = deleted-vs-
  unassigned catalog, an OWNER read (O1). It is an external Meta authorization condition, not
  broken code (sync succeeded 45× on 2026-10-08, began failing 2026-10-09T00:21Z). Never
  duplicate Meta products to work around it.
- QA contact returns VERIFIED_CUSTOMER_REQUIRED — not linked to the permanent verified
  customer identity. Do not bypass; the fix is the owner linking the WhatsApp contact to the
  verified account.
- Flows: Submit Request `1107164111921876` and Leave Review `1578178897413815` PUBLISHED;
  Request Amendment `3678132465672138` and Drop Docs `1211063631104445` DRAFT (confirm via
  current Meta read if a non-prohibited path exists, else record source conflict).
- Prices (paise): submit-request 9900, request-amendment 9900, drop-docs 35000, vault 4900.
  Shipments + Leave Review are utility entries, not priced SKUs.
- Live Lambda aliases move under the parallel session — re-read with get-alias before any
  claim or move. Recent readings showed business-api ~79→88, checkout 40→41, catalog-sync
  6→7; treat all as stale.

## 5. Open blocking design findings to resolve before coding
From the latest `design-review.json` (revision 2 → CHANGES_REQUESTED, 2 HIGH + 8 MEDIUM):
- HIGH-1: re-derive ALL citations into `checkout/handler.py` and
  `whatsapp-business-api/handler.py` at the rebase base `origin/stack` (checkout off by -18,
  business-api off by +24). Dangerous: `checkout:3080` is a Cognito identity-filter line at
  the base, NOT the feature gate. Use `git grep -n <pattern> origin/stack -- <path>`.
- HIGH-2: F-2 must NOT drop a raising `order_keys.resolve_payment_reference` into the
  fail-open captured-payment path (razorpay-webhook `_post_payment_handler`); wrap in
  try/except OrderIdentityUnavailable, default native=False, log and continue — a transient
  DynamoDB throttle must never replay a captured payment. Add the failure-branch test.
- MEDIUMs: F-6 `order_choices` must return a plain list (not a tuple) or it breaks the live
  Flow screen; split §5 row 4b into money-path (4b-i, no O11) vs contested business-api
  (4b-ii, needs O11 + v88 package certification); fix change-authority-matrix row-vs-line
  citations; correct the QA-recipient provenance; split §5 item 3 into a read-only inspect
  invoke vs await-natural-webhook (no Wix mutation to manufacture a webhook); remove the
  unspecified §5 item 7; re-tag answers F/G as another-session evidence until re-run; fix the
  nine citation errors in unchanged files.

## 6. The deliverables (keep producing/refining these)
Under the worktree `outputs/` and mirrored to repo `outputs/`:
`kiro-deep-audit-2026-10-09.md`, `kiro-current-state.json`,
`whatsapp-customer-service-architecture.md` (incl. Customer Service Home, Profile privacy,
Orders Flow, and the Vault order→download sequence — see
SCOPE-EXTENSION-vault-and-continuation.md), `whatsapp-payment-state-machine.md`,
`website-to-whatsapp-migration-matrix.md`, and this continue-prompt. Update
`docs/whatsapp/service-rollout/live-evidence.json` + `continue-prompt.txt` and
`docs/execution/change-authority-matrix.md` only with re-verified facts.

## 7. Final gate + response format
Release is READY only with full connected-journey evidence (verified identity, safe profile,
order list/detail, invoice retrieve/resend reusing the authoritative invoice, correct
payment, one canonical order + one Wix association, secure files, workspace shows the
purchase once, idempotent retries, invoice/receipt delivery, review dedup, no critical
security defect, rollback). If real owner QA/payment hasn't happened, status is
"ENGINEERING COMPLETE — OWNER QA REQUIRED", not COMPLETE. Final response sections: Executive
status; Deep audit findings; WhatsApp feasibility verdict; Customer Service Home design;
Orders Flow design; Payment-start state machine; Invoice/receipt rules; Website→WhatsApp
migration; What was already complete; What you fixed; Tests (exact commands/results);
Production state; Remaining engineering work; Owner actions; External/provider blockers; Not
verified; Rollback; Next exact action.

## 8. Owner-action items currently open (O-series)
O1 adjudicate catalog 1607047307067517 deleted-vs-unassigned (Meta); O2 Submit Request Flow
publish decision; O4/O7 real QA purchase + workspace render; O10 authorize each production
deploy (no standing authorization survives); O11 adjudicate the two-session overlap on
business-api v87/v88. Plus: link QA contact to verified customer identity; rotate the six
historically-exposed credential families (owner-only). None of these is engineering hiding
behind a label — each is one owner/provider action.


---

## UPDATE 2026-10-09 — design loop aborted after round 3; focused fix pass dispatched

The original workflow `wf_39451386601bde5e` ABORTED: its design loop hit its
3-iteration budget and the round-3 review still returned CHANGES_REQUESTED. This is
convergence, not failure — the reviewer verified ~40 citations exact at the correct base
and confirmed the design correctly rejected two of the PRIOR reviewer's own mistakes. The
round-3 blockers are a bounded, well-specified punch list, recorded in
`.kiro/work/deep-integration-audit/design-review.json` (`mustResolveBeforeAnyCode:
[1,2,3,6,7,8,9]`), summarized:
- HIGH-1: F-9 (Vault re-issue) is a real defect but its paid path is GATED OFF by
  `SECURE_FILES_PAYMENT_ENABLED=false` — latent, not live-reachable today; live residue is
  only the ":1459-1460 please pay again" copy.
- HIGH-2: F-9 re-issues from a grant row DynamoDB TTL-sweeps (expiresAt=now+1800s); the
  fix must address record lifetime (extend expiresAt on redeem, or key entitlement off the
  durable file row).
- HIGH-3: `answers.md` still carries a QA-recipient provenance sentence `design.md` claims
  it corrected but didn't (only suffix 0044 survives in README/continue-prompt; no document
  of record).
- MEDIUMs: stale rev-2 citations in answers A/D/J/L (incl. the dangerous checkout:3080 =
  Cognito Filter line, not the gate); two unbuildable regression tests (F-5 ClientError
  str, F-2 KeyError caught by the guard); F-9 auth envelope mis-named (_customer_identity
  :1828, not require_auth/Operator :1840); F-9 route-shape + cap-condition mismatch;
  seven Filter='sub' sites not six; item-7 alias move lacks --revision-id; the inspect
  invoke gated by two different owner items (O10 vs O13).

RECOVERY: a focused single-agent design-fix pass (`wf_275b238f138ae44d`, agent wf-design)
was dispatched to (a) RE-ANCHOR all citations to the CURRENT origin/stack
(`4fe3182455642c6ff4d9caca7f0f7febdb7fc59f` as of this update — the parallel session keeps
advancing it; re-verify) and (b) apply the exact fixes for all 12 blockers + 4 NITs, then
report. After it completes: run ONE design review to confirm APPROVED, then proceed to
plan → build (implement-and-review loop) → finalize. If relaunching a full workflow,
point its design step at the already-near-final design.md/answers.md and have it ONLY
verify + fix residual blockers, not re-explore.

The design content itself (1730-line design.md, 1713-line answers.md, the WhatsApp-hub
architecture incl. the Vault order→download section, the migration matrix, the payment
state machine) is SOUND and should be reused, not regenerated.


---

## UPDATE 2026-10-09 (later) — design-fix pass done; confirming review in flight

The focused design-fix pass (`wf_275b238f138ae44d`) COMPLETED: re-anchored the base
twice during the run (`e9e377ce → 4fe31824 → 061b6e77`; the second hop changed
whatsapp-business-api/handler.py), re-verified 139 load-bearing citations at `061b6e77`
with zero failures, and resolved all 12 round-3 blockers + 4 NITs. A "## 9. Design review
round 3 resolution" section was added to design.md (now ~182 KB). Gates stay CLOSED,
items 8/9/F-7-remainder STOP, all 17 production steps OWNER CONFIRM. Files left
uncommitted on purpose (parallel session actively pushing).

`origin/stack` is currently `061b6e77c8a352d174c713834af0ca7d61b027b9` — matches the
fix-pass base, so citations should be clean. A confirming design review
(`wf_eb82966271b5a348`, agent wf-design-reviewer) was dispatched to independently verify
the 12 blockers (+4 NITs) at the current base and APPROVE or return a residual list.

NEXT once APPROVED: run plan (wf-planner) → implement-and-review build loop (wf-coder +
two semantic_reviewer branches + wf-review-aggregator, reviewer verdict last) → finalize
(reports, outputs/ mirror, re-verified docs, scoped commit, integrate). If relaunching as
one workflow, point its first step at the APPROVED design.md/answers.md and skip
re-design. If the confirming review returns CHANGES_REQUESTED with a small residual set,
dispatch one more focused wf-design fix for exactly those, then re-review — do not restart.


---

## UPDATE 2026-10-09 (round 4) — confirming review: all 16 resolved; 4 residual bookkeeping defects; focused fix dispatched

Confirming review `wf_eb82966271b5a348` returned CHANGES_REQUESTED but INDEPENDENTLY
CONFIRMED all 16 round-3 findings resolved at base `061b6e77`. The design SUBSTANCE is
approved; the 4 blocking items are documentation-consistency defects inside the resolution
write-up (verbatim fixes in design-review.json round 4, findings[] ids 1-7):
- HIGH-1: design.md §9's re-anchor paragraph contradicts §0 (claims hop-2 moved no code;
  it moved whatsapp-business-api/handler.py). §0 is CORRECT; §9's summary is wrong.
- MED-2: §9 "139 re-verified ... All 97 pass" — contradictory counts.
- MED-3: answers.md QA transcript records continue-prompt.txt:7 (intermediate) vs its own
  table's correct :9.
- MED-4: F-9 copy fix scoped to :1459-1460 but identical "pay again" string also at
  :1224-1225 (gated-off today, re-introduces at item-8 flag open).
- 4 NITs (not 3 — `findings[]` runs ids **1-8**, and `counts.nit` = 4): §0 shift-table header
  labels, "fifth caller" ordinal, a stale base label, and NIT-8's `check_data_model_drift.py`
  TTL-citation drift between §9's finding-2 row and F-9.0's body.

Base is STABLE at `061b6e77` (parallel session paused). Focused residual fix dispatched:
`wf_a09b4f7891920a2c` (wf-design) applies the 7 verbatim corrections. NEXT: one more quick
confirming review (or trust-and-proceed if the fixes are purely the prescribed mechanical
doc edits), then plan (wf-planner) → implement-and-review build loop → finalize. The design
is effectively approved on substance; do not restart or re-explore.

---
## UPDATE 2026-10-09 (round 4 resolution APPLIED) — all 8 bookkeeping items fixed; base still `061b6e77`
`wf_a09b4f7891920a2c` applied all **8** round-4 items (the brief said 7; `findings[]` has 8 —
`counts.nit` = 4). Base re-verified unchanged at `061b6e77c8a352d174c713834af0ca7d61b027b9`, so no
line numbers were re-derived. Every reviewer-cited value was reproduced at that base before editing.
Documentation-consistency only: **no analysis, no fix content, no severity and no gate changed.**
§0 and §9 of `design.md` now agree that **hop 2 DID move code**; §9 points at §0 instead of
restating it. F-9's copy fix now covers **both** `:1459-1460` and `:1224-1225` in `design.md`,
`findings.md` and `outputs/…architecture.md` §6.5, and §5 item 8 carries a note that its `F-9`
prerequisite includes the second site. See `design.md` §9's **"Design review round 4 resolution"**
subsection for the per-item record and the command used for each.
Every gate stays **CLOSED**; items **8/9/F-7-remainder stay STOP**; every production step stays
**OWNER CONFIRM**. NEXT: plan (wf-planner) → implement-and-review build loop → finalize.


---

## UPDATE 2026-10-09 (plan/build phase) — design APPROVED ON SUBSTANCE; build workflow launched

Round-4 residual fix pass (`wf_a09b4f7891920a2c`) completed: all round-4 bookkeeping items
resolved at base `061b6e77` (re-verified unchanged), §0 and §9 now agree hop-2 moved code,
the 139/97 count contradiction resolved to 139 (11 changed values), the QA transcript
corrected to continue-prompt.txt:9, F-9's copy fix extended to BOTH :1459-1460 and
:1224-1225, and §10 "Design review round 4 resolution" appended. The design is now
internally consistent with zero stale load-bearing citations — APPROVED ON SUBSTANCE
(all 16 round-3 findings were independently confirmed resolved in round 4).

Launched the plan → implement-and-review → finalize workflow `wf_72351e3900ac343f` in the
SAME worktree. It implements ONLY the engineering-safe source fixes
(F-1, F-2-guarded, F-4, F-5, F-6, F-9-copy-only, F-10) with failing-first regression tests,
runs venv pytest + frontend typecheck/lint/vitest/build, dual semantic reviews (logic +
security, aggregator verdict last, max 5 iterations), then finalizes the reports. It STOPS
at every owner/provider boundary: no alias move/deploy (O10), no production inspect invoke
(O13), no gate opened (native-services / Wix-writeback / download-template /
SECURE_FILES_PAYMENT_ENABLED — items 8/9 STOP), no token-gated Meta/Wix read, no deletion.
Executive status is forced to "ENGINEERING COMPLETE — OWNER QA REQUIRED" (not COMPLETE),
since real payment/QA and the gated enables remain owner actions.

If this workflow aborts (build loop maxIterations 5, onMaxIterations abort): read
`{worktree}/.kiro/work/deep-integration-audit/review.json` for the residual, dispatch one
focused wf-coder fix for exactly those, then re-run the build loop — do NOT restart plan or
design. After it completes, the orchestrator removes the worktree.


---

## UPDATE 2026-10-09 (owner actions) — O7 confirmed complete

Owner authorized adding `wecare.digital` to the Cognito Admin group (pool
`us-east-1_cSx0RHCIR`). On execution the admin-list-groups-for-user read showed the user
was ALREADY in `["Admin"]` before the command ran; `admin-add-user-to-group` returned
exit 0 (idempotent no-op) and the after-read confirmed `["Admin"]`. **O7 is RESOLVED** —
Admin membership exists, so admin-authenticated verifications (incl. workspace order
render, question S) are no longer blocked by missing group membership. This was an IAM/
identity membership change authorized by the owner; rollback if ever needed:
`aws cognito-idp admin-remove-user-from-group --user-pool-id us-east-1_cSx0RHCIR
--username wecare.digital --group-name Admin --region us-east-1`.

O3 note: live `wecare-meta-catalog-sync` v7 has META_CATALOG_ID=1457045652952851 (the new
catalog), confirmed by read-only get-function-configuration. Still awaiting owner confirm
that the retarget was intended (else roll back to v6 env).
