# Deep Integration Audit — Findings

Evidence log for the WECARE.DIGITAL deep audit / reconciliation / release pass.
Entries are append-only. Each entry is tagged INFO, FINDING, FIX, CONFLICT or BLOCKED.

---

## INFO — Pre-loop setup: worktree created and remote integrated

- **Recorded (UTC):** 2026-10-09T02:16:55Z
- **Repo root (re-derived):** `/Users/wecaredigital/wecare-digital/wecare-digital` (confirmed via `git rev-parse --show-toplevel`)
- **Worktree path:** `/Users/wecaredigital/wecare-digital/wecare-digital/.worktrees/deep-integration-audit`
- **Branch:** `deep-integration-audit`, created fresh from local `stack` HEAD `53ed298e`
- **HEAD:** `53ed298e422ac7694acc19bee91551169a7fe042`

### `git status --short` (in worktree)

```
(empty — clean working tree, no staged, modified or untracked files)
```

### `git log --oneline -8` (in worktree)

```
53ed298e (HEAD -> deep-integration-audit, origin/stack, origin/HEAD, stack) fix: label the shared CAPI dataset as configured, not verified
65d57de4 fix: describe the CAPI dataset escape hatch honestly and re-capture test counts
a739d016 feat: one shared Meta catalog and one fixed CAPI dataset for both WABAs
7a1e1e44 Merge remote-tracking branch 'origin/stack' into HEAD
f21671b1 Document verified service payment gaps and use Vault without a Flow
92975806 docs(resolution): preserve wix/dependabot review artifacts and work plans
1b3055d3 Merge remote-tracking branch 'origin/stack' into HEAD
0359fefe Merge remote-tracking branch 'origin/stack' into HEAD
```

### Merge result — `git fetch origin` then `git merge origin/stack`

- `git fetch origin` → exit 0, no new refs fetched.
- `git merge origin/stack` → **`Already up to date.`** (exit 0)
- No merge commit was created. No conflicts. No files touched.
- `git rev-list --left-right --count HEAD...origin/stack` → `0  0` (zero divergence in both directions).

### CONFLICT WITH BRIEF — divergence described in the step brief no longer exists

The step brief anticipated two divergent commit sets to reconcile: a local branch
3 commits ahead carrying the "one catalog / one dataset" work, and `origin/stack`
2 commits ahead carrying "service-flow-draft" docs. **That divergence is already
resolved in the current repository state** and is therefore stale information:

- `origin/stack` and local `stack` both point at `53ed298e`.
- The one-catalog/one-dataset work is already merged and pushed — it is commits
  `a739d016`, `65d57de4`, `53ed298e`, all reachable from `origin/stack`.
- Merge commit `7a1e1e44` already integrated the prior `origin/stack` docs work.

Per the standing rule that current repository and current `origin/stack` are the
sources of truth over historical handoffs, no reconciliation merge was required.

### Pre-existing work left untouched (as instructed)

- `/Users/wecaredigital/wecare-digital/wecare-digital/.kiro/work/deep-repository-audit/`
  — untracked prior-audit directory in the main worktree. Left in place, not read, not removed.
- `.worktrees/one-catalog-dataset` — **does not exist.** `git worktree list` reports only
  the main worktree and this new audit worktree; `.worktrees/` was an empty directory
  before this step. Nothing to preserve. (Consistent with that branch's work already
  being merged into `origin/stack`.)

### Registered worktrees after setup

```
/Users/wecaredigital/wecare-digital/wecare-digital                                   53ed298e [stack]
/Users/wecaredigital/wecare-digital/wecare-digital/.worktrees/deep-integration-audit 53ed298e [deep-integration-audit]
```

### Evidence directory

Created: `.kiro/work/deep-integration-audit/` (inside the audit worktree). This file
is the audit's running evidence log.

### Scope note

This entry covers pre-loop setup only. No application code, configuration,
infrastructure or external-service state was inspected or modified in this step.

---

## INFO — Design review round 3 resolved; citation base re-anchored to `061b6e77`

- **Recorded (UTC):** 2026-10-09, design/audit phase only. **No live code, infrastructure, gate or
  flag was changed. No payment, send or deletion. All AWS reads were `describe`/`list`/`get`.
  No `secretsmanager` call of any kind was made.**
- **Previous declared base:** `e9e377ce` (what review 3 verified against)
- **Current base:** `061b6e77c8a352d174c713834af0ca7d61b027b9` (`061b6e77`, "fix: retire obsolete
  Meta Flows with WABA-aware lifecycle API", 2026-10-09T11:02:30+05:30)
- **Divergence:** `git rev-list --left-right --count HEAD...origin/stack` → `1  12`
  (1 ahead, 11 behind). Merge base `53ed298e`. Worktree HEAD `0425dce1`.
- **Rebase target:** `061b6e77`

### Re-anchor commands

```
git fetch origin && git rev-parse origin/stack        -> 061b6e77c8a352d174c713834af0ca7d61b027b9
git rev-list --left-right --count HEAD...origin/stack -> 1  12
git merge-base --is-ancestor e9e377ce origin/stack    -> YES (fast-forward)
git diff e9e377ce..4fe31824 --stat                    -> 12 files, +2121/-1   (docs/outputs only)
git diff 4fe31824..origin/stack --stat                -> 11 files, +1784/-13  (INCLUDES CODE)
git diff 4fe31824..origin/stack --name-only | grep -E '^(amplify|scripts|src|tests)/'
    -> amplify/functions/messaging/whatsapp-business-api/handler.py
    -> tests/test_audit_payment_diagnostic.py
```

**The base moved TWICE during this one resolution pass.** Hop 1 (`e9e377ce` → `4fe31824`, "docs:
specify renewable Vault access and complete session handoff") touched **docs and outputs only**.
**Hop 2 (`4fe31824` → `061b6e77`, "fix: retire obsolete Meta Flows with WABA-aware lifecycle API")
CHANGED CODE** in `amplify/functions/messaging/whatsapp-business-api/handler.py` (+12 lines at
`@@ -310 @@`, +1 at `@@ -6094 @@`) and `tests/test_audit_payment_diagnostic.py`.

**Every citation into that handler shifted** — `+12` below line 321, `+13` below 6106 — and all were
re-derived individually rather than by applying the offset. Per-line table in `design.md` §0. Two of
them (`:5875`, `:6519-6521` in answer **S1**) were **already stale before hop 2** and no offset
explains them; they were corrected by direct re-derivation to `:5912` and `:6574`.

**`amplify/functions/ecommerce/checkout/handler.py`** — the other file the step prompt named — **was
touched by neither hop**, so the re-derived gate lines `:3062`/`:3063`/`:3064`/`:3065`/`:3078` and
the `verified_identity` caller `:3081` hold.

**139 load-bearing citations were re-verified individually** with `git grep -n` plus a per-line
`git show origin/stack:<path> | sed -n '<n>p'` substring assertion; **all 139 pass.**

### CONFLICT — two load-bearing DOCUMENT citations shifted inside one review cycle

| Citation | `e9e377ce` | **`061b6e77`** |
|---|---|---|
| `docs/whatsapp/service-rollout/README.md` suffix `0044` | `:57` | **`:59`** |
| `docs/whatsapp/service-rollout/continue-prompt.txt` suffix `0044` | `:5` | **`:9`** |
| Tracked files containing the full QA E.164 | 88 | **90** |

Both lines carry the only surviving trace of the QA-recipient nomination. Recorded because it is the
concrete demonstration that `design.md` §0's re-derivation rule is operational, not theoretical.
`docs/execution/change-authority-matrix.md:1154`, `:1458` and `:246-254` are **unaffected** —
Both hops appended to that file after every citation this plan uses.

### FINDING severities and states after round 3

| ID | Title | Severity | State | Change this round |
|---|---|---|---|---|
| F-1 | `read_failed` destroys Graph status; `reason` absent on 3 of 5 `applied:0` arms | MEDIUM | PERMITTED (code), OWNER CONFIRM (O10) to deploy | `caplog` mechanism documented (nit 15) |
| F-2 | Duplicate review invitation across webhook and native paths | MEDIUM, latent | PERMITTED | Test 5 renamed `test_an_error_outside_the_storage_wrapper_is_not_swallowed`; injection moved outside `_read_row`'s `try` (finding 7) |
| F-3 | Vault selection admits a file with no customer attribution | MEDIUM, latent | PERMITTED | unchanged |
| F-4 | Cognito `list_users` Filter by string concatenation | LOW | PERMITTED | **SEVEN sites, not six** (2 guarded, 5 unguarded); **both** inline regexes converted; `customer_orders` pin test added (finding 10) |
| F-5 | Conditional-failure detection by message substring | LOW | PERMITTED | Test fixture replaced with a `ClientError` subclass overriding `__str__`; structural-read invariant stated (finding 6) |
| F-6 | Internal `orderId` surfaces as a customer label; call doubles as eligibility gate | LOW | PERMITTED | `get_logger` + `log_event` imports named; hand-rolled `json.dumps` dropped (nit 16) |
| F-7 | Shared-catalog / fixed-dataset commit `a739d016` | — | **OWNER-GATED — STOP.** Half overtaken | unchanged; remainder stays STOP |
| F-8 | Documentation reconciliation | MEDIUM | PERMITTED | Item 6 (`docs/execution/qa-recipient.md`) re-stated **IMPERATIVE and UNAPPLIED**; file confirmed absent (finding 3) |
| F-9 | Paid Vault customer whose link expires after redeeming is told to pay again | **HIGH** | PERMITTED, **route contingent on §5 row 4c-read** | Reachability re-argued: **LIVE via the ungated NATIVE path**, not the gated `secure-files` one (finding 1). Entitlement moved to the **durable FILE row**; cap/counter moved with it; **no TTL touched** (finding 2). Auth envelope corrected to `_customer_identity:1828`, **not** `require_auth` (finding 8). One route shape, full conditional update with the mandatory `OR attribute_not_exists` arm, `ConditionalCheckFailedException` mapped by re-read (finding 9). Six tests |
| F-10 | Native Vault purchase outside the 24-hour window reports `VAULT_READY` having delivered nothing | MEDIUM, latent | PERMITTED | Reason enum order fixed: `not_deliverable` → `no_delivery_key` → `window_closed` (nit 13) |
| F-11 | Live `WHATSAPP_LINK_TTL_SECONDS=21600` silently clamped to 900 | LOW, config | OWNER CONFIRM (O10) | Mechanism rewritten: `--no-publish` + manual publish + **conditional** alias move with `--revision-id` + independent read-back (finding 11) |

### Owner-item boundary corrected

| Item | Scope | Gates |
|---|---|---|
| **O10** | authorize/refuse this audit's **deploys** | §5 rows 2, 4b-i, 4b-ii, 4c, 7 |
| **O13** | authorize/refuse the single **production inspect invoke** | §5 row 3a **only** (and row 5's dependency on it) |

Previously row 3a cited O10 while `answers.md` **U** defined O13 — an owner approving "the deploys"
could not tell whether a production invoke was included. Now disjoint and cited consistently in
`design.md` §5, `design.md` §7 and `answers.md` **U** (finding 12).

### Round-3 outcome

**16 of 16 review findings resolved** (3 HIGH, 9 MEDIUM, 4 NIT). Full per-finding resolution with
commands in `design.md` §9 "Design review round 3 resolution".

**Unchanged deliberately:** every gate stays **CLOSED**; items 8, 9 and F-7's remainder stay
**STOP**; every production step stays **OWNER CONFIRM**; owner/provider/engineering separation
intact; nothing weakens auth, ownership, signature verification, IAM or isolation.

### BLOCKED — two items conditional by design, not unresolved

1. **F-9's re-issue route** awaits §5 row **4c-read** (`A0_READ` COUNT of `DownloadGrantsTable` rows
   with `paid AND consumed AND attribute_not_exists(expiresAt)`). ≥ 1 justifies the route; `0`
   demotes F-9 to MEDIUM-latent and ships only the copy correction — at **both** `:1459-1460`
   (`_redeem`) and `:1224-1225` (`_redeem_after_reconcile`, the identical string, unreachable while
   `SECURE_FILES_PAYMENT_ENABLED` is false but reachable the moment §5 item 8 opens it).
2. **`docs/execution/qa-recipient.md` does not exist.** Work owed, scheduled as §5 row 5. Until it
   exists the QA nomination rests on the task prompt and on nothing in the repository, and
   **no live send may be justified by a suffix match.**

---

## FIX — Part A items 1-8 committed; cross-item integration verified; per-finding state transitions

- **Recorded (UTC):** 2026-10-09T11:11:56Z
- **Worktree:** `/Users/wecaredigital/wecare-digital/wecare-digital/.worktrees/deep-integration-audit`
- **Branch:** `deep-integration-audit`, HEAD `5042bd48863edf14c90d113230d0296d7b295955`
- **Nothing pushed. No deploy, no Lambda version published, no alias moved, no production Lambda
  invoked, no feature flag opened, no live WhatsApp send, no `secretsmanager` call, no AWS call of
  any kind, no record deleted.** Every mutation is a local commit on this branch.

This entry closes **plan.md Part A item 9**. It records the seven source fixes, the cross-item
integration verification, and the per-finding state transition for each. **No severity is changed
and no finding is marked resolved** — the source half is done, the deploy half is not.

### Commits — one per F-item, each staged by exact path

Merge base for this set is `bc4fcf724d24e816fa05dc958ec082832875914f` (FEAT-001's
`git merge origin/stack`, clean, zero conflicts, no rebase).

| F-item | Commit SHA | Subject |
|---|---|---|
| F-1 | `f1926b4e4549e69e59a973fc99720c2c839267ae` | report the Graph status on a catalogue read failure and give every `applied:0` arm a reason |
| F-5 | `aca7fdd4ec506090bd9d33dc64ff6f1f1e4f40e0` | decide a conditional failure on the money path from the error code, never the message |
| F-2 | `2d1c7953a7fd6ddd7d93786269ba71c8ee39a2a6` | the webhook review arm yields to the native one, through a guarded payment-reference read |
| — | `d2d2f8697b05219d0cf7a451cb90636d85850d0e` | **test fixtures only**, owner-authorised and deliberately separate: seed order numbers and Cognito subjects that production could actually mint. No production file. Whole suite after it was *exactly* the FEAT-002 baseline, which is the proof it altered no behaviour. |
| F-4 | `24b6d2ecc6f6853b81cad1cf12b32b2a50aab1fc` | one Cognito-subject predicate for all seven ListUsers filter sites |
| F-6 | `f96fca877b1d087044b0df4a350cde0c2031bc87` | offer only public order numbers, and ask eligibility as its own question |
| F-9 (copy only) | `338b2a336a41f7355e9407c11dc8f47d7c81bd51` | a paid customer is never told to pay again, at both redeem refusal sites |
| F-10 | `5042bd48863edf14c90d113230d0296d7b295955` | a Vault purchase that delivered neither link nor file is not `VAULT_READY` |

`git log --oneline bc4fcf72..HEAD` → exactly these eight, in this order. No commit touches a file
outside its own item's list; verified per commit with `git show --name-only`.
`git diff --stat bc4fcf72..HEAD` → 24 files, +1873/-34 (12 production files, 1 doc, 11 test files).

### Per-finding state transition — all seven are **source fixed + tests green, deploy owner-gated**

| ID | Severity | Previous state | **New state** | Commit |
|---|---|---|---|---|
| F-1 | MEDIUM *(unchanged)* | PERMITTED (code), OWNER CONFIRM (O10) to deploy | **source fixed + tests green, deploy owner-gated** | `f1926b4e` |
| F-2 | MEDIUM, latent *(unchanged)* | PERMITTED | **source fixed + tests green, deploy owner-gated** | `2d1c7953` |
| F-4 | LOW *(unchanged)* | PERMITTED | **source fixed + tests green, deploy owner-gated** | `24b6d2ec` |
| F-5 | LOW *(unchanged)* | PERMITTED | **source fixed + tests green, deploy owner-gated** | `aca7fdd4` |
| F-6 | LOW *(unchanged)* | PERMITTED | **source fixed + tests green, deploy owner-gated** | `f96fca87` |
| F-9 **(copy correction only)** | **HIGH** *(unchanged)* | PERMITTED, route contingent on §5 row 4c-read | **source fixed + tests green, deploy owner-gated** — *the copy half only* | `338b2a33` |
| F-10 | MEDIUM, latent *(unchanged)* | PERMITTED | **source fixed + tests green, deploy owner-gated** | `5042bd48` |

**None of these is resolved.** Each needs its Lambda deployed, and every deploy in this audit is
**OWNER CONFIRM (O10)** per `docs/execution/change-authority-matrix.md:1154` (A3_PRODUCTION requires
explicit owner approval for the exact target *and* rollback immediately before acting). Part B rows
B1-B5 carry the deploy half. F-3, F-7, F-8 and F-11 are untouched by this build and keep the state
round 3 left them in.

**F-9 is the one to read carefully.** Only the customer-facing copy was corrected, at both refusal
sites — `amplify/functions/core/secure-files/handler.py:1225` (`_redeem_after_reconcile`) and
`:1460` (`_redeem`). The **re-issue route is Part B row B8 (STOP) and was not implemented, tested or
stubbed**, because it depends on the B7 population count that has not been taken.
`git grep -n 'reissueCount\|REISSUE_CAP' -- amplify` → **no matches**, so the boundary held in the
tree and not merely in intent. F-9 therefore stays **HIGH**: the misleading sentence is gone, the
customer still has no self-service way back to a file they paid for. `SECURE_FILES_PAYMENT_ENABLED`
remains closed, which is why the `:1225` assertion is source-level rather than behavioural.

### Cross-item integration verification — four shared files, no interaction found

Four files were edited by more than one item. Each seam was inspected in the final tree, by anchor
rather than by line number. **No cross-item defect was found and no repair was needed.**

1. **`amplify/functions/payments/razorpay-webhook/handler.py` — F-5 and F-2.** All five F-5
   conversions are present and none is negated (`:1719`, `:2036`, `:2149`, `:2775`, `:2895`); the
   sixth call at `:640` is the pre-existing structural one, correctly still `not
   is_conditional_failure(...)`. The F-2 Step-5 guard sits at `:2484-2499` with `native = False` as
   the default on an unreadable row (fail open: we send the review), catching
   `order_keys.OrderIdentityUnavailable` and **not** bare `Exception`.
   `git grep -n "ConditionalCheckFailedException' in str" -- amplify/functions/payments` → **no
   matches**: no substring check survives on the money path. The F-5 negation in
   `invoice-engine/handler.py:889` is still `if not order_keys.is_conditional_failure(claim_err):`
   — not inverted.
2. **`flows/catalog_services.py` — F-4 and F-6.** Disjoint regions, both intact. F-4's
   `is_cognito_subject(owner)` guard at `:50`; F-6's function-local `has_prior_order` import and
   call at `:65-67`. The `_send` body and the `SUBMIT_REQUEST_PARENT_ORDER_REQUIRED` outcome are
   unchanged.
3. **`flows/paid_vault.py` — F-4 and F-10. The import-duplication risk was checked explicitly and is
   absent.** `from lambda_utils.logging import get_logger, log_event` appears **exactly once**
   (`:9`) and `logger = get_logger(__name__)` **exactly once** (`:11`); `log_event` is called once,
   at `:138`. F-4's guard at `:72-73` and F-10's deferred-outcome block at `:125-140` do not overlap.
   The `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` env read is byte-identical and its default is still
   `'false'`.
4. **`paid_submit_request.py` — the two are different files with the same basename, which is the
   thing to not get wrong.** F-4 edited
   `amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py` (guards at `:90`
   and `:144`); F-6 edited
   `amplify/functions/shared/lambda_utils/ecommerce/paid_submit_request.py` (`list_orders` /
   `has_prior_order`). There is no shared line between them, so plan.md item 9's anticipated
   `flows/paid_submit_request.py` collision does not exist in fact.

Two tree-wide invariants also still hold: `git grep -l '0-9a-f]{8}(?:-' -- amplify` returns exactly
one path (`shared/lambda_utils/customer_auth.py`), and
`git grep -n 'Please pay again to download' -- amplify` returns **no matches**.

### Whole-suite and focused results

**Whole suite** (`$PY -m pytest -q` from the worktree root):
`1 failed, 10509 passed, 6 skipped, 3 xfailed in 109.64s`.

The count gate is met with room to spare: FEAT-001's post-merge baseline was **10432**, items 2-8
were planned to add ~30 tests, so the floor is ~10462 — and the suite reports **10509**. The rise is
monotonic across the build: 10432 → 10460 (F-5) → 10469 (F-2) → 10469 (fixtures, flat by design) →
10495 (F-4) → 10502 (F-6) → 10504 (F-9) → **10509** (F-10).

**Focused set, all fifteen files in one run: 375 passed, 0 failed.** That is every test file any
item created or touched, run together so a cross-item interaction would surface as a collision:
`test_meta_catalog_sync_handler.py`, `test_meta_catalog_sync.py`,
`test_conditional_failure_detection.py`, `test_native_service_review_dedup.py`,
`test_customer_identity_filter_guard.py`, `test_paid_submit_request_order_labels.py`,
`test_secure_files.py`, `test_paid_vault_deferred_delivery.py`, `test_paid_vault.py`,
`test_paid_submit_request.py`, `test_customer_orders_flow.py`,
`test_service_lines_dropdocs_vault.py`, `test_dropdocs_vault_no_second_charge.py`,
`test_central_order_directory.py`, `test_native_catalog_orchestration.py`.

### INFO — the one failure is inherited, is not ours, and was deliberately not fixed

`tests/test_github_oidc_trust_policy.py::test_fixer_covers_every_oidc_role_the_repository_declares`.
It is the same single failure FEAT-001 recorded immediately after the merge and FEAT-002 through
FEAT-004 each carried. Upstream `4ee4c498` ("Run one-shot payment Lambda deployment") added
`.github/workflows/payment-lambda-deploy-once.yml`, declaring OIDC role
`GitHubActions-wecare-digital-payment-deploy-temp-20261009`, which is not registered in
`scripts/fix_github_oidc_trust.ROLES`. Two facts place it outside this build:
`git diff --name-only bc4fcf72..HEAD -- .github scripts` is **empty** (not one of our eight commits
touches either tree), and `git grep -n payment-deploy-temp origin/stack -- scripts/` returns nothing,
so the role is unregistered on the remote independently of this branch. It is an **IAM-TRUST** matter;
plan.md 0.3 forbids unrelated repairs and `contribution_requirements` forbids touching IAM, so it was
left alone.

### CONFLICT — `origin/stack` moved a third time, after the build. NOT integrated.

`origin/stack` is now **`0a59ecf8a19498741a4787e3ad90c113ff79683b`** — no longer FEAT-001's build-time
`1102da71`. Divergence is `git rev-list --left-right --count HEAD...origin/stack` → **`10  22`**
(10 ahead, 22 behind). The parallel `xcodex` session is still pushing.

**No merge was performed in this step**, because integrating 22 new upstream commits is not part of
item 9 and would change the tree the 10509-passing run certifies. Consequences to carry forward:

- **The inherited OIDC failure appears to be fixed upstream by deletion, not by registration.**
  `git diff --stat origin/stack..HEAD -- .github/workflows/payment-lambda-deploy-once.yml` shows
  `+48` in our direction, i.e. the workflow **exists at HEAD and not at the new `origin/stack`** —
  upstream removed the one-shot workflow, which removes the unregistered role with it. Whoever
  merges next should expect that single failure to disappear on its own and must **not** read its
  disappearance as evidence of a fix made here.
- **Every line number in this file and in `design.md` / `plan.md` is a fact about a commit, not about
  the repository.** They are valid against `bc4fcf72..5042bd48`. Re-derive with
  `git grep -n '<anchor>'` after the next merge and prefer the anchor over the number.
- **`git merge origin/stack` only — never a rebase, never a force-push.** FEAT-001's merge was clean;
  this one has not been attempted and is not predicted.

### `git status --porcelain` — no unintended file

```
 M .kiro/work/deep-integration-audit/findings.md      <- this entry, committed by item 9
?? .kiro/work/deep-integration-audit/SCOPE-EXTENSION-order-number-format.md
?? .kiro/work/deep-integration-audit/SCOPE-EXTENSION-vault-and-continuation.md
?? .kiro/work/deep-integration-audit/SCOPE-EXTENSION-whatsapp-hub.md
?? .kiro/work/deep-integration-audit/answers.md
?? .kiro/work/deep-integration-audit/design-review.json
?? .kiro/work/deep-integration-audit/design-review.md
?? .kiro/work/deep-integration-audit/design.md
?? .kiro/work/deep-integration-audit/outputs/
?? .kiro/work/deep-integration-audit/plan.md
?? .kiro/work/deep-integration-audit/task-deep-integration-audit/
?? .kiro/work/deep-integration-audit/verification.md
```

No production, test, script, infrastructure or configuration file is modified or untracked. Every
untracked path is this audit's own evidence under `.kiro/work/deep-integration-audit/`, produced by
the design and planning phases and left untracked as those phases left it — item 9's file list is
`findings.md` alone, so only `findings.md` is staged, by exact path.

### Scope boundary at the end of Part A

Part A is complete: seven source fixes committed, one commit per F-item, tests green, plus the one
owner-authorised fixture commit. **Part B remains entirely unimplemented** — no deploy, no published
version, no alias move, no production invoke, no gate opened, and no F-9 re-issue route.
`WHATSAPP_CATALOG_SERVICES_ENABLED`, `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED`,
`SECURE_FILES_PAYMENT_ENABLED` and Wix writeback are all **still closed**; no flag line was added or
removed anywhere in the production diff (`git diff bc4fcf72..HEAD -- amplify` matches no flag
name). Payments still fail closed. Nothing weakens signature, auth, ownership, IAM or isolation.
