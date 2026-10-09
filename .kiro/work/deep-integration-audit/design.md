# Deep Integration Audit — Design and Plan of Attack

**Revision 3**, after design review 2 (`design-review.json`, verdict `CHANGES_REQUESTED`: 2 HIGH,
8 MEDIUM, 4 NIT). Every finding is answered in **§8**, which records what was addressed, what was
backlogged with a reason, and where the review itself was wrong.

Companion to `answers.md` (evidence for A–U). This document is what the planner and coders
execute. It is binding on technology choice: **every stack decision below is locked once this
design is approved.**

Scope of this phase: investigation and design only. No application code, infrastructure or
external-service state was changed. No gate was enabled. No Flow was created. No secret value was
read, printed or logged. No payment configuration was created, mutated or probed.

---

## 0. CITATION BASE — read this before acting on any `file:line` below

> **All `file:line` references in this document and in `answers.md` are relative to
> `origin/stack` = `061b6e77c8a352d174c713834af0ca7d61b027b9` (`061b6e77`, "fix: retire obsolete
> Meta Flows with WABA-aware lifecycle API", 2026-10-09T11:02:30+05:30), re-derived on 2026-10-09
> with `git grep -n '<pattern>' origin/stack -- '<path>'`.**
>
> **Divergence at re-derivation:** `git rev-list --left-right --count HEAD...origin/stack` →
> `1  12` — the audit worktree (`0425dce1`, branch `deep-integration-audit`) is **1 ahead, 12
> behind**. Merge base `53ed298e`. **Rebase target = `061b6e77`.**

**Revision 3 re-anchoring (round-3 review resolution). The base moved TWICE during this one
resolution pass** — `e9e377ce` → `4fe31824` → `061b6e77` — exactly as §0 predicted, and the second
hop **changed code**. Commands used:

```
git fetch origin && git rev-parse origin/stack          ->  061b6e77c8a352d174c713834af0ca7d61b027b9
git rev-list --left-right --count HEAD...origin/stack   ->  1  12
git merge-base --is-ancestor e9e377ce origin/stack      ->  YES (fast-forward)
git diff e9e377ce..4fe31824 --stat                      ->  12 files, +2121/-1, DOCS AND OUTPUTS ONLY
git diff 4fe31824..origin/stack --stat                  ->  11 files, +1784/-13, INCLUDING CODE
git diff 4fe31824..origin/stack --name-only | grep -E '^(amplify|scripts|src|tests)/'
    ->  amplify/functions/messaging/whatsapp-business-api/handler.py
    ->  tests/test_audit_payment_diagnostic.py
```

**Hop 1 (`e9e377ce` → `4fe31824`) touched no code** — only
`docs/execution/change-authority-matrix.md`, `docs/whatsapp/service-rollout/{README.md,
continue-prompt.txt,live-evidence.json}` and seven `outputs/*` files.

**Hop 2 (`4fe31824` → `061b6e77`) DID touch code, in one of the two handlers the step prompt
named.** `amplify/functions/messaging/whatsapp-business-api/handler.py` gained 12 lines in a hunk at
`@@ -310,11 +310,23 @@` (`_update_business_profile`) plus one line at `@@ -6094,7 +6106,8 @@`, so
**every citation into that file below line 321 shifted by +12, and below 6106 by +13.** All were
re-derived individually:

| Citation | At `4fe31824` | **At `061b6e77`** | Shift |
|---|---|---|---|
| `preparePaidSubmitRequest` arm (F-9's native reach-path) | `:5984-5988` | **`:5996-6000`** | +12 |
| `internalAction` dispatch arms (the `customerCommand`/`catalogService` neighbourhood) | `:5969-5988` | **`:5981-6000`** | +12 |
| `auth_result = require_auth(event)` | `:6022` | **`:6034`** | +12 |
| `_read_payment_configurations` | `:3523` | **`:3535`** | +12 |
| `_payment_readiness_for` | `:3552` | **`:3564`** | +12 |
| `_check_payment_gateway` | `:3608` | **`:3620`** | +12 |
| `/payment-config/raw` → 410 (answer **E**) | `:6386-6391` | **`:6399-6404`** | +13 |
| `_list_orders as _svc_list_orders` import | (cited `:5875`, already stale) | **`:5912`** | re-derived |
| `return _svc_list_orders(params)` | (cited `:6519-6521`, already stale) | **`:6574`** | re-derived |

> **Two of these were stale *before* hop 2** — `answers.md` **S1** cited `:5875` and `:6519-6521`,
> which review 3 did not flag and which no shift explains. They are corrected by direct
> re-derivation, not by arithmetic. This is why §0 forbids trusting a number: an offset is not a
> substitute for `git grep`.

**`amplify/functions/ecommerce/checkout/handler.py` — the other file the step prompt named — was
NOT touched by either hop**, so `:3062`, `:3063`, `:3064`, `:3065`, `:3076-3077`, `:3078`, `:3080`
and `:3081` are confirmed unchanged and were each re-verified anyway.

**Two document citations shifted in hop 1, and both were load-bearing for the QA-send authority
chain:**

| Citation | At `e9e377ce` | At `061b6e77` | Command |
|---|---|---|---|
| `docs/whatsapp/service-rollout/README.md` suffix `0044` | `:57` | **`:59`** | `git grep -n "0044" origin/stack -- docs/whatsapp/service-rollout/README.md` |
| `docs/whatsapp/service-rollout/continue-prompt.txt` suffix `0044` | `:5` | **`:9`** — **moved in BOTH hops** (`:5` → `:7` → `:9`) | `git grep -n "0044" origin/stack -- docs/whatsapp/service-rollout/continue-prompt.txt` |
| Tracked files containing the full E.164 | 88 | **90** | `git grep -l "918100640044" origin/stack \| wc -l` |

This is the live demonstration of why §0 is binding: the two lines carrying the only surviving trace
of the QA-recipient nomination moved within one review cycle, and a code file the plan edits moved
within one *resolution pass*. See §8 finding 6 and F-8 item 6.

**Unaffected, re-confirmed at `061b6e77`:** `docs/execution/change-authority-matrix.md` `:1154` (the
`A3_PRODUCTION` row), `:1458` (table row 231, the 53-alias sweep) and `:246-254`
(`set_standby_reply_flag.py`). Both hops appended to that file **after** every citation this plan
uses, so review 2's finding 5 stays rejected on the merits for the reason §8 gives.
>
> **Rows in `docs/execution/change-authority-matrix.md` are numbered independently of file lines.
> Citations below are FILE LINES.** The matrix's own row 231 is at file line `:1458`, for example.

**Why this header exists, and why it is the most important paragraph in the document.** Review 2's
HIGH finding 1 was that revision 2's citations were derived at the worktree HEAD (`0425dce1`) while
Step 0 mandates implementing on `origin/stack`. That was correct. But the correction it supplied is
*also* stale, because `origin/stack` moved again during the review:

| Tree | Commit | Role |
|---|---|---|
| Main checkout | `53ed298e` | **what review 2 actually measured** for the `change-authority-matrix.md` citations (finding 5) |
| Audit worktree HEAD | `0425dce1` | where revision 2's citations were derived |
| Rebase base at review 2 | `4e259800` | where review 2 derived its corrections for findings 1, 3, 6, 10 |
| Rebase base at review 3 | `e9e377ce` | the base revision 3 declared and review 3 verified against |
| **Rebase base now** | **`061b6e77`** | **the only base this revision cites**, 12 commits ahead of the worktree |

Four trees have now been in play and the citation errors in both revision 2 and review 2 are
explained by which tree each read. Review 2's finding 5 is a clean example: it corrected
`change-authority-matrix.md:1154` → `:1110` and reported verifying `:1110` verbatim. Both are
reproducible, at different commits:

```
git show 53ed298e:docs/execution/change-authority-matrix.md | grep -n 'Explicit owner approval'  -> 1110
git show 4e259800:docs/execution/change-authority-matrix.md | grep -n 'Explicit owner approval'  -> 1154
git show origin/stack:docs/execution/change-authority-matrix.md | grep -n 'Explicit owner approval' -> 1154
```

So **revision 2 was right and review 2's finding 5 is rejected on the merits**: `:1154` is correct
at both the review's stated base and the current one. The same applies to the other two pointers in
that finding (`:1458` for the 53-alias sweep, `:246-254` for `set_standby_reply_flag.py`). Details
in §8.

**The structural lesson, which is binding on the planner.** A line number is a fact about a commit,
not about the repository. `origin/stack` moved three times across two review cycles and the
production fleet moved four times. Revision 3's re-anchor is itself the third data point: two
document line numbers shifted by two while this document sat in review. Therefore:

> **Every citation in this plan must be re-derived at the actual rebase base immediately before the
> commit that uses it, with `git grep -n`, not trusted from this document.** Where a line number is
> load-bearing for a *fix*, this revision also gives an **anchor pattern** so the coder can
> re-locate it mechanically. Prefer the anchor over the number.

---

## 1. Overview

### What changed between revision 2 and revision 3

**1. The rebase base moved from `4e259800` to `e9e377ce`: six more commits, re-verified this pass.**

```
git fetch origin   ->  4e259800..e9e377ce  stack -> origin/stack   (revision 3, first derivation)
git fetch origin   ->  e9e377ce..4fe31824  stack -> origin/stack   (revision 3, re-anchored; docs only)
git rev-list --left-right --count HEAD...origin/stack  ->  1  12
```

The six new ones, and what each does to this plan:

| Commit | Effect on this design |
|---|---|
| `87859dbc` Build owner-scoped Orders draft and protect paid Vault and private uploads | Touches `flows/paid_vault.py`; **moves every F-4 live-site line** |
| `ceb469fc` Merge latest stack safeguards before customer service rollout | merge |
| `4a3c4251` Build verified Orders invoice action and stage fresh catalog proposals | New `flows/customer_invoice.py`, `flows/customer_orders.py`; stages `catalog-proposals-20261009.json` — **first-party proof for G/H/I** |
| `0075d086` Merge remote-tracking branch | merge |
| `d03ac81d` Record merged customer-service release gates and remaining work | docs |
| **`e9e377ce`** audit: reconcile customer-service rollout and **retire raw payment diagnostic** | **Closes answer E by construction.** Adds a dedicated `/payment-config/raw` arm at `handler.py:6399-6404` plus a committed regression test. See below. |

**2. Answer E is now closed by committed source and a committed test, not by arm ordering.**
Revision 2 retired the historical `/payment-config/raw` defect by arguing that the dispatcher's
`/payment-config/list` arm precedes the bare `/payment-config` arm that requires `phoneId`. That
argument was sound but indirect. `e9e377ce` makes it direct:

```python
elif path.rstrip('/').endswith('/payment-config/raw'):                       # :6386
    # Retired diagnostics must not fall through to phone-level settings.     # :6387
    # Native readiness consumes the normalized list; this route never writes. # :6388
    return _resp(410, {'error': 'Payment configuration raw endpoint retired',
        'replacement': '/wa-business/payment-config/list',                   # :6390
        'diagnostic': '/wa-business/payment-config/check'})                  # :6391
```

pinned by `tests/test_audit_payment_diagnostic.py::test_retired_raw_diagnostic_has_explicit_replacement_without_provider_call`,
parametrised over `GET` and `POST`, which asserts `410`, both pointer fields, and
`graph.assert_not_called()`. The arm sits **before** `/payment-config/list` (`:6393`) and the bare
`/payment-config` (`:6400`, which is the `phoneId`-requiring handler at `:6402-6403`), so the
historical fall-through is structurally impossible. **No work remains on E.**

**3. The test baseline is re-captured at the real base, by measurement.** Review 2's NIT 12 was
that revision 2's "129 passed" was a pre-rebase number offered as the post-rebase comparator. Both
numbers are now measured at `e9e377ce` in a throwaway read-only worktree:

```
# focused set, incl. the two test files that exist only upstream
pytest tests/test_meta_catalog_sync_handler.py tests/test_meta_catalog_sync.py \
       tests/test_paid_vault.py tests/test_audit_customer_file_ownership.py \
       tests/test_audit_payment_diagnostic.py
  -> 157 passed in 0.64s
# whole suite
pytest tests/   -> 10394 passed, 6 skipped, 3 xfailed in 118.64s
```

**This is the pass/fail gate.** The pre-rebase 129 is provenance only. Note the conflict: the
parallel session's own checkpoint in `docs/whatsapp/service-rollout/README.md` claims "Backend
10334/7 skipped/3 xfailed" — measured at its stated baseline `d03ac81d`, already stale at
`e9e377ce`. Recorded in `answers.md` as conflict **C14**; not an error by either party, an
illustration of why counts are timestamps.

**4. Review 2's HIGH finding 2 is accepted in full and F-2 is rewritten.** The fix as specified in
revision 2 would have converted a transient DynamoDB throttle into a webhook `500` and a full
replay of a captured payment. The guarded form is now specified, with a table handle, a stated
fallback posture and a failure-branch test. This was the most serious defect in revision 2 and the
review was right to block on it.

**5. Three new Vault findings (V-1 HIGH live, V-2, V-3) arrived with an owner requirement** to
document the Vault order → download message sequence. They are specified in
`outputs/whatsapp-customer-service-architecture.md` §6 and scheduled here as **F-9**, **F-10**,
**F-11**. **V-1 is the most customer-damaging finding in the whole audit**: a customer who has paid
₹49 and whose 60-second presigned URL expires after the grant was consumed is told, in product
copy, to pay again.

**6. First-party telemetry now corroborates the catalog-sync root cause, and exposes a worse
observability defect than revision 2 described.** Independently read from CloudWatch this pass —
not taken from the parallel session's prose. See §1.1 and answers **G**.

### What carried forward from revision 2

**First, review 1 was right about the execution half.** Revision 1 classified five fix items as
"all latent" with "no cloud state to restore". Three of them touch live, unflagged paths — the
captured-payment money path, the live paid Submit Request Flow, and the Vault delivery chain. §5
and §6 now separate gated from live work and give the live work the same publish / conditional
alias move / independent read-back / named-rollback contract as everything else.

**Second, the review was right that the one scheduled production deploy had no cited
authorization, and wrong about where to find one.** No steering file granting standing
authorization survives `af7858fa`. `docs/execution/change-authority-matrix.md:1154` defines
`A3_PRODUCTION` as requiring "Explicit owner approval for the exact target **and** rollback,
immediately before acting". The historical "owner blanket" rows are historical and their granting
document is deleted. So §5 carries an **Authorization** column and every production step is
`OWNER CONFIRM`. Nothing auto-deploys.

**Third, and this reframes everything: a parallel session landed four commits on `origin/stack`
and nine production Lambda releases while revision 1 was being written.** It fixed three things
this audit had queued, answered one question this audit had marked unverifiable, and moved the
fleet underneath the evidence. Concretely:

- `724dcc38` fixed `vault_access.bind_file` to require positive attribution — **resolving review
  finding 2 in the tree, in the direction the review preferred.** `flows/catalog_services.py:94` is
  now the *only* `in (None, …)` ownership acceptance left in `amplify/`, which both shrinks **F-3**
  and reduces its severity from "foreign-document disclosure" to "offered-then-refused dead end".
- `724dcc38` also root-caused the payment-config contradiction that has produced conflicting
  evidence for weeks: **Meta's `fields` filter returns an empty collection for the
  `payment_configurations` edge, and the read was unpaginated.** Two inert GETs on v86 now show two
  configurations, both Active. **Answer F is closed with no mutation.**
- An independent Graph read established the catalog refusal: `1607047307067517` returns
  **error 100 / subcode 33**, while `1457045652952851` returns **HTTP 200 with an empty product
  list**, using the same credential. That excludes every token, scope, app-permission, endpoint,
  pagination and request-construction hypothesis in one stroke, and leaves exactly two: the object
  is deleted, or it is unassigned. **Answer G's root cause is established** — and **F-1 is therefore
  demoted from "the thing that makes O1 verifiable" to diagnostic hygiene.**
- Live `wecare-meta-catalog-sync` v7 (03:30:32Z) now sets `META_CATALOG_ID=1457045652952851` with
  `ENABLED=false` and `DRY_RUN=true`. **The catalog half of F-7 has been executed as an environment
  change.** The sync will no longer fail its read; it will return the `:599-601` arm —
  `ok:True, dryRun:True, applied:0`, **with no `reason` field.** So F-1's `reason`-totality half
  becomes *more* valuable, not less.

The net effect on the fix register: F-1 shrinks in urgency and grows in scope, F-3 halves, F-7 is
half-overtaken, and two new owner items appear — **O10** (authorize these deploys) and **O11**
(adjudicate the two-session overlap before touching `messaging/whatsapp-business-api`).

What stands unchanged from revision 1: the `/payment-config/list` routing is correct and the
historical `raw` defect is retired; payment readiness is genuinely fail-closed by enumeration
rather than by negation; order, invoice and payment idempotency are enforced by conditional writes
at every step rather than hoped for; and `verified_identity` is a correctly-placed, correctly-strict
gate that must not be weakened to make a test pass.

**Technology stack — locked.** Python 3.12 Lambda handlers under `amplify/functions/**`; shared
code via `amplify/functions/shared/lambda_utils/**`; `urllib` for outbound HTTP (**no new HTTP
dependency**); `boto3` for AWS; DynamoDB single-key conditional writes via
`lambda_utils.ecommerce.order_keys` for all idempotency; `pytest` for Python tests;
`vitest` + TypeScript/Next.js for the website; `fbq` for browser pixel events. **No new runtime
dependency is introduced by any item in this plan.** No new table, bucket, queue, API or IAM
statement is required by F-1 through F-8.

**Step 0, mandatory and non-negotiable: rebase onto the then-current `origin/stack` before writing
any code — and re-fetch first, because it has moved on every single check.** At this writing that
is `e9e377ce`; by the time the planner acts it may not be. Several files this plan touches were
modified upstream (`shared/lambda_utils/ecommerce/vault_access.py`,
`messaging/whatsapp-business-api/handler.py`, `flows/paid_vault.py`, `core/secure-files/handler.py`),
and `tests/test_audit_customer_file_ownership.py` / `tests/test_audit_payment_diagnostic.py` exist
only upstream. The gate after rebasing is the measured baseline in item 3 above: **157 focused /
10394 whole-suite**, re-captured immediately after the rebase and compared, not assumed.

### 1.1 First-party telemetry read this pass — and a worse defect than revision 2 found

Revision 2's answer **G** rested on a prose sentence in another session's markdown. Review 2's
finding 9 was right to down-rate that. This pass read the system's own telemetry directly.

**Independent capture, `/aws/lambda/wecare-meta-catalog-sync`, read 2026-10-09T04:33:06Z:**

```
23:07:47.607Z {"event":"meta_catalog_sync_planned","catalogId":"1607047307067517","enabled":true,
               "dryRun":false,"desired":2,"existing":3,"create":0,"update":0,"retire":0,
               "foreign":1,"foreignRetailerIds":["WD-APPREVIEW-TEST"]}
23:28:48.242Z {"event":"meta_catalog_sync_planned","catalogId":"1607047307067517","enabled":true,
               "dryRun":false,"desired":2,"existing":2,"update":2,"foreign":0}
00:21:01.427Z {"event":"meta_catalog_sync_read_failed","errorType":"RuntimeError",
               "catalogId":"1607047307067517","source":"wix-webhook"}
   ... 14 further read_failed records, 00:21:01Z through 02:13:22Z, all the same catalogId ...
```

This is the sharp edge of **F-1**: fifteen consecutive production failures and the telemetry cannot
say whether the cause was 403, 429, 500 or DNS. Everything downstream — the whole deletion-vs-
permission ambiguity in **O1** — follows from that one missing integer.

**And then this, which revision 2 did not have.** Two invocations of the retargeted v7:

```
2026-10-09T03:31:28.595Z  START RequestId d5873a76-…  Version: 7   END  (904.58 ms)
2026-10-09T04:03:42.687Z  START RequestId 3887e848-…  Version: 7   END  (776.98 ms)
```

**Neither emitted a single application log line.** No `meta_catalog_sync_planned`, no
`read_failed`, no `unconfigured`. Reading the handler explains it exactly: the one and only
`logger.info` is at `:577-594`, and **two return arms precede it** — the `batchHandle` readback at
`:531-534` and the `inspect` readback at `:565-572`. Both return before any logging. (The
`unconfigured` arm at `:528-529` does log, at `:525-527`, so it is excluded.)

So the live catalog sync has an **unobservable mode**: a production invocation that completes
successfully, performs a real Meta read, and leaves no evidence of what it saw. From telemetry
alone it is not possible to determine which of the two silent arms ran. **This upgrades F-1 from
"three arms lack a `reason` field" to "two arms produce no telemetry at all", and it is the
justification for F-1 regardless of what happens with O1.**

What the two silent runs almost certainly were: the parallel session's post-deploy `inspect` check
(v7 was published at 03:30:32Z, 56 seconds before the first one), and its artifact is committed at
`docs/whatsapp/service-flow-drafts/catalog-proposals-20261009.json` — an exact `:568-572` response
shape, `"catalogId": "1457045652952851"`, `"readOnly": true`, `counts.create: 4`, `"existingItems":
[]`, `"applied": 0`, four items each `"availability": "out of stock"` at ₹99 / ₹99 / ₹350 / ₹49.
**That is a structured artifact, and it is first-party: the handler's own serialised return value.**
It independently corroborates that the retarget fixed the read — the `:565` arm is reachable only
*after* the `try` block at `:536-552` completed, which contains the Meta read. It is nonetheless
**INFERRED, not PROVEN, that these two invocations produced that file**, because the silent arms
make the link unverifiable. That inference is exactly the cost of the defect F-1 fixes.

**Also read this pass, `/aws/lambda/wecare-wix-catalog-webhook` at 2026-10-09T04:36:35Z:** the Wix
webhook chain is verified and working end to end —
`{"event":"wix_webhook_verified","eventType":"wix.stores.catalog.v3.product_updated"}` →
`{"event":"catalogue_dispatch_sent","status":204}` →
`{"event":"meta_catalog_sync_invoked","function":"wecare-meta-catalog-sync:live"}`. **But the last
delivery was 2026-10-09T00:24:18Z — nothing in the four hours before the read.** Revision 2 said
"the Wix webhook is still firing"; that is **no longer true at this read** and the correction
matters, because it means **§5 item 3b cannot be scheduled with any expectation of firing on its
own**. Recorded as conflict **C15**.

---

## 2. Fix register

Each item gives the evidence, the smallest safe root-cause fix, the regression test that fails
*before* it, and whether it is permitted or must stop at a boundary. **Every `file:line` below was
re-derived mechanically this revision** (review finding 13); the derivation table is in §8.

### F-1 — `read_failed` destroys the Graph status, and `reason` is absent on three of five `applied:0` arms. PERMITTED (code), OWNER CONFIRM (deploy).

**Severity: MEDIUM, diagnostic.** Demoted from revision 1's HIGH because answer **G** no longer
depends on it: the Graph refusal (100/33) was obtained out-of-band. It is still worth doing,
because that answer came from a human-driven manual read rather than from the system's own
telemetry, and the next occurrence would be just as opaque.

**Evidence — the status is captured and then discarded.**
`amplify/functions/ecommerce/meta-catalog-sync/handler.py:209-211` returns
`{"error": {"status": int(error.code)}}`. `:233` raises `raise RuntimeError("the Meta catalogue
could not be read")` — a **bare** `RuntimeError`, and `grep -n 'raise '` on that file returns it as
the only one, which is what makes `errorType` a reliable localiser (answer **G3**). The `except`
arm logs at `:554-557`:

```json
{"event":"meta_catalog_sync_read_failed","errorType":"RuntimeError",
 "catalogId":"1607047307067517","source":"codex-audit"}
```

live at 2026-10-09T02:13:22.575Z, `/aws/lambda/wecare-meta-catalog-sync`. A 403, 400, 429, 500 and
a DNS failure are indistinguishable. 403 means "ask the owner to re-grant an asset"; 429 means
"back off and retry".

**Evidence — five `applied: 0` arms, three without `reason`** (review finding 5, accepted):

| Lines | Shape | `reason`? |
|---|---|---|
| `:528-529` | `ok:False, reason:"unconfigured"` | yes |
| `:558-559` | `ok:False, reason:"read_failed"` | yes |
| `:568-572` | `ok:True, readOnly:True` — the `inspect` readback | **no** |
| `:599-601` | `ok:True, dryRun:True` — **disabled OR dry-run, not distinguished** | **no** |
| `:604-606` | `ok:True, enabled:True, dryRun:False` — empty plan | **no** |

A sixth return at `:534` (`{"readOnly": True, "batchStatus": status}`, the `batchHandle` arm) has no
`applied` key at all and is out of scope.

This matters operationally right now: live v7 has `ENABLED=false, DRY_RUN=true`, so the **next
invocation takes the unreasoned `:599-601` arm.**

**Root-cause fix, part 1 — carry the status structurally.** Introduce a module-level exception in
`meta-catalog-sync/handler.py`, mirroring the pattern `wix_ecom.http_error` already establishes at
`amplify/functions/shared/lambda_utils/wix_ecom.py:59-75` (status readable as `.status`, never
parsed out of prose; the "one constructor … so a fake transport produces the identical shape"
rationale is at `:69-70`; and note the module is at `lambda_utils/wix_ecom.py`, **not** under
`lambda_utils/ecommerce/`):

```python
class MetaCatalogReadError(RuntimeError):
    """The Meta catalogue read failed. Carries the Graph status structurally, never a body."""
```

`_existing_items:233` raises `MetaCatalogReadError` with `.status` from
`result["error"].get("status")` and `.errorKind` from `result["error"].get("type")` when the failure
was not an `HTTPError`. The `except` arm at `:554-557` adds `graphStatus` and `graphErrorKind` to
the existing log line and nothing else.

**Root-cause fix, part 2 — make `reason` total over the return surface.** Add `reason` to all three
unreasoned arms, so `applied: 0` is never read alone:

- `:568-572` → `"reason": "read_only_inspect"`
- `:599-601` → `"reason": "disabled" if not enabled else "dry_run"` (the arm covers both, so it
  must be derived, not hard-coded)
- `:604-606` → `"reason": "nothing_to_apply"`

**What must NOT change.** The Graph **response body** must still never be logged — `:208-209`
records why (the body echoes the request, whose one header is a credential). Only the integer status
and the exception class name may be added. The fail-closed behaviour is unchanged: a read failure
still returns `read_failed` and still constructs no write request. `errorType` stays, because
`MetaCatalogReadError` subclassing `RuntimeError` keeps `type(e).__name__` a reliable localiser —
and the new name is *more* specific than `RuntimeError`, so **G3**'s taxonomy argument strengthens.

**Regression test — the rig already exists** (review finding 6 is accepted in direction and wrong
in premise: it prescribed creating `tests/test_meta_catalog_sync_handler.py`; that file **exists**,
with 29 tests). It already injects all three points via its `run()` helper at
`tests/test_meta_catalog_sync_handler.py`, the `run()` helper (`:180` at `e9e377ce`; **anchor on the name `def run(`, not the line** — review 2 finding 10):

```python
def run(wix, graph, reader=None, event=None):
    return receiver.handler(
        event if event is not None else {"source": "wix-webhook", "entityId": "prod-1"},
        None, wix_requester=wix, graph_requester=graph,
        secret_reader=reader or reader_for())
```

and `FakeGraph(error={"status": 500})` is already the idiom, used by
`test_a_META_read_failure_does_not_become_a_write` at `:446`. So the new tests go in that file
and reuse that rig. Four cases:

1. `test_a_read_failure_reports_the_graph_status` — `FakeGraph(error={"status": 403})`; assert the
   captured `meta_catalog_sync_read_failed` record has `graphStatus == 403`, `out["reason"] ==
   "read_failed"`, `graph.writes == []`, and that **no** value in the record contains `Bearer` or
   `FAKE_TOKEN`. Fails today: `graphStatus` does not exist.
2. `test_a_transport_failure_reports_the_kind_and_no_status` — `FakeGraph(error={"type":
   "URLError"})`; assert `graphErrorKind` present and `graphStatus is None`.
3. `test_every_applied_zero_arm_states_its_reason` — parametrised over all five arms, asserting
   `reason` is present and equal to `unconfigured` / `read_failed` / `read_only_inspect` /
   `disabled` / `dry_run` / `nothing_to_apply` as appropriate. Fails today on three.
4. Sensitivity: the existing `test_a_META_read_failure_does_not_become_a_write` must still pass
   unchanged.

**The log-capture mechanism, because this file has no precedent for it** (review 3 nit 15, accepted).
Tests 1-3 assert on log-record *contents*, while all 29 existing tests in
`tests/test_meta_catalog_sync_handler.py` assert on return values only and **none uses `caplog`**
(`git grep -c caplog origin/stack -- tests/test_meta_catalog_sync_handler.py` → no matches). The
mechanism is sound and here is why: the handler binds `logger = get_logger(__name__)` at
`meta-catalog-sync/handler.py:57`, and `lambda_utils.logging.get_logger` (`:17`) is a thin wrapper —
it calls `logging.getLogger(name)` (`:22`) and `setLevel` (`:24`) and **returns that plain stdlib
logger**, adding no handler and never setting `propagate = False`. Records therefore reach the root
logger, which is what `caplog` attaches to. Concretely:

```python
caplog.set_level(logging.ERROR, logger='handler')   # the handler module's __name__ under its sys.path
```

Two cautions for the implementer. The logger name is the handler module's `__name__` as imported by
the existing rig, so take it from the module object rather than hardcoding a guess
(`caplog.set_level(logging.ERROR, logger=handler_module.logger.name)` is the robust form). And
`get_logger` applies `LOG_LEVEL` (default `INFO`) at `setLevel`, so a test asserting on an `INFO`
record must either leave `LOG_LEVEL` unset or set `caplog.set_level` on the same logger — the level
on the logger, not the handler, is what filters.

**Do not** put these in
`tests/test_meta_catalog_sync.py`: that file exercises only the pure
`lambda_utils.ecommerce.meta_catalog_sync` module across its 40 tests, two of which
(`test_the_module_is_pure_at_import` `:519`, `test_the_module_logs_nothing_at_all` `:536`) assert
properties a handler-driving, log-capturing test would sit badly beside.

**Deployment — single function, owner-confirmed, concurrency-safe.** Target
`wecare-meta-catalog-sync` only. Pre-capture `live` version **and** `RevisionId` immediately before
acting (currently **7** / `dc895968-c89d-4a3b-9da3-2e366fb1465f`, but **re-read**: this alias moved
6 → 7 during the audit). The F-1 commit must be the **only** change in the tree at publish time —
it touches no shared module, so there is no `lambda_utils` delta and no fleet fan-out; **F-4 and
F-5 must land after**, never before. Publish a new version from the rebased tree, move the alias
with `--revision-id` set to the captured value so a concurrent move fails the call instead of being
overwritten, then verify with an **independent** `get-alias` read rather than the command's exit
code. Do **not** use `scripts/deploy_all_lambdas.py` or `scripts/snapstart_publish.py`: both are
fleet-wide — `change-authority-matrix.md:1458` (table **row** 231) records one shared-`lambda_utils` change producing
"57 updated … publisher moved 53 aliases", which would republish functions this audit uses as
evidence.

### F-2 — duplicate review invitation across the webhook and native paths (MEDIUM, latent). PERMITTED.

**Evidence.** Three senders of `wecare_leave_review`, three unrelated claim namespaces:

| Sender | Guard | Claim |
|---|---|---|
| `payments/razorpay-webhook/handler.py:2468` → `_request_review_on_whatsapp` (`:2593`) | `if contact and invoice_id:` | `INVOICEDELIVERY#<invoiceId>#review` via `order_keys.claim_invoice_delivery(..., channel='review')` at `:2622-2624` |
| `messaging/whatsapp-business-api/flows/paid_submit_request.py:96-101` | `detailsSubmittedAt` present | `requestReviewStatus` attribute on the ServiceRequests row |
| `messaging/whatsapp-business-api/flows/paid_vault.py:87` | ready notification claimed, document send claimed if a PDF is deliverable | `vaultReviewStatus` attribute on the ServiceRequests row |

The webhook's comment block runs `:2454-2467`, with the sentence "So **BOTH legs ask** - WhatsApp
and website - which is deliberate and is the one place this differs from step 4" at `:2458-2459`
and the guard at `:2468`. That reasoning is correct for the website/WhatsApp split it was written
for and predates the native service paths. Nothing correlates the two claim spaces.

**Root-cause fix — the webhook arm yields, not the native ones.** The native trigger is the better
one: it asks after the service has actually been delivered, and `paid_submit_request.py:81-95`
re-verifies the recipient from Cognito and the contact row before sending. The webhook asks at
capture, before any fulfilment.

So: in `razorpay-webhook/handler.py`, before calling `_request_review_on_whatsapp`, resolve the
payment reference through the existing `order_keys.resolve_payment_reference` and **skip** when the
resolved `PAYREF#` row carries `nativeCatalogService` truthy. That field already exists and is
already read for exactly this kind of branch at `flows/paid_submit_request.py:108`
(`if payref.get('nativeCatalogService'):`), and it is written at
`ecommerce/checkout/handler.py:2803` into the `extra` passed to
`order_keys.allocate_payment_reference(..., extra=extra)` at `:2807`. So this reuses an established
marker rather than inventing one. `reference_id` is already in scope at the call site and already
passed to `_request_review_on_whatsapp` (`:2469-2470`), so no new plumbing is needed.

#### The call MUST be guarded. Review 2's HIGH finding 2, accepted in full.

Revision 2 specified this as a drop-in call. It is not one, and inserting it unguarded would be the
most dangerous change in this plan. The chain, re-verified at `e9e377ce`:

- `order_keys.resolve_payment_reference` (`order_keys.py:380-396`) reads through `_read_row`
  (`:335-347`), which **raises `OrderIdentityUnavailable` on any storage error by deliberate
  design**. Its docstring at `:336-341`: *"A read failure must not be reported as absence: callers
  treat absence as 'no order exists for this reference', and a throttle answering 'absent' would
  let a payment event be discarded as unknown."* That is correct and must not be changed.
- The insertion point is inside `_post_payment_handler` (`:2326`), whose own comment block
  (`:2454-2467`) declares this arm **FAIL-OPEN**: *"it is FAIL-OPEN because a feedback send is the
  least important thing on this path: it must never block or reverse the invoice or the paid
  state."*
- `_post_payment_handler` is called **unguarded** at `:1408` from `_handle_payment_captured`
  (`:1227`), itself called at `:183` inside the handler's one top-level `try`. Its
  `except Exception` at `:311-315` returns `_response(500, …)` and comments: *"The lease is
  deliberately NOT completed here. Letting it lapse is what allows Razorpay's retry to be processed
  instead of dismissed as a duplicate, which is the entire fix."*

So an unguarded raising call here turns a transient DynamoDB throttle into **a webhook 500 plus a
deliberate full replay of a captured-payment event** — injected into the one block the code
documents as never permitted to affect the paid state. **Specified form, binding:**

```python
# Step 5 is FAIL-OPEN by contract (:2454-2467). It must never raise, because a raise
# reaches the handler's except at :311-315, returns 500, and lets the idempotency lease
# lapse so Razorpay REPLAYS a captured payment. An unreadable PAYREF# row therefore falls
# back to the pre-existing website behaviour: ask for the review.
native = False
try:
    payref = order_keys.resolve_payment_reference(
        dynamodb.Table(COMMERCE_KEYS_TABLE), reference_id) or {}
    native = bool(payref.get('nativeCatalogService'))
except order_keys.OrderIdentityUnavailable:
    logger.warning(json.dumps({'event': 'review_native_check_unavailable',
                               'referenceId': reference_id, 'requestId': request_id}))

if contact and invoice_id:
    if native:
        logger.info(json.dumps({'event': 'review_request_skipped_native',
                                'referenceId': reference_id, 'requestId': request_id}))
    else:
        _request_review_on_whatsapp(invoice_id, contact, originating_phone_id,
                                    reference_id, request_id)
```

**The table handle.** `COMMERCE_KEYS_TABLE` is module-level at `:101`
(`order_keys.commerce_keys_table_name()`), and `dynamodb.Table(COMMERCE_KEYS_TABLE)` is already the
established idiom at `:2555` and `:2621` in this same file. No new plumbing, no new import.

**The fallback posture, stated as a product decision rather than left implicit.**

> On an unreadable `PAYREF#` row we default to `native = False`, i.e. **we send the review
> invitation**. A duplicate review nudge during a storage outage is strictly preferable to replaying
> a captured payment. Never invert this default to "skip on error": that would make a transient
> throttle silently suppress a legitimate website review request, which is a silent partial success
> — the exact class this audit is hunting.

**Catch `OrderIdentityUnavailable` specifically, not bare `Exception`.** `_read_row` wraps every
storage error into that one type (`:344-347`), so the specific catch covers the whole failure
surface. A bare `except Exception` here would also swallow a genuine programming error (a bad table
name, a missing attribute) and turn it into a permanently invisible duplicate-review bug.

Add the `review_request_skipped_native` line at **info** so the suppression is greppable rather than
silent — the same posture `post_payment_flow_skipped` already uses at `:1703`, `:1720`, `:1731`.

**The decision this fix must own explicitly** (review finding 9, accepted). The native senders are
conditional: `send_review` returns `REVIEW_NOT_DUE` (`paid_submit_request.py:81-83`) unless
`kind == 'SUBMIT_REQUEST'` **and** `detailsSubmittedAt` **and** `flowContactId` **and**
`flowPhone`, then `VERIFIED_RECIPIENT_UNAVAILABLE` on any identity mismatch; `paid_vault` reaches
its review send only after `grant_access` succeeded, the identity chain held and the notification
claim was won (`:71-72`), returning `VAULT_DOCUMENT_PENDING` at `:84` if a deliverable PDF's send
claim is lost. Therefore:

> **No fulfilment implies no review invitation.** A native purchase that is paid but never
> fulfilled receives none, deliberately; the reconciliation surface is the workspace, not a review
> nudge.

**Rejected alternative, and why.** A shared cross-path claim key (e.g. claiming
`REVIEW#<customerId>#<orderId>` from all three senders) would also work and is more general. It is
rejected for this pass: it changes the claim key of a **live** website leg that works today, for the
benefit of a path that is switched off, and a claim-key migration has no safe rollback once rows
exist under the old key. The targeted skip touches only the native case and leaves the live website
behaviour byte-identical. Revisit the general form only if a fourth sender appears.

**Regression tests (the first fails before the fix).**
`tests/test_native_service_review_dedup.py` — drive the real `razorpay-webhook` post-payment
function and the real `paid_submit_request.review(...)` against one shared fake
commerce-keys/ServiceRequests pair, with both outbound boundaries spied (`lambda_client.invoke` and
`urllib.request.urlopen`):

1. `test_one_native_purchase_asks_for_a_review_once` — one `referenceId` with
   `nativeCatalogService: True` and `detailsSubmittedAt` set; assert exactly **one** invoke carries
   `templateName == 'wecare_leave_review'`. Two are sent today.
2. `test_a_website_purchase_still_asks_once` — `nativeCatalogService` absent; assert the website leg
   still sends exactly one. This is the sensitivity proof that the fix did not simply disable the
   webhook arm.
3. `test_a_paid_native_purchase_with_no_details_asks_for_no_review` — one `referenceId` with
   `nativeCatalogService: True` and **no** `detailsSubmittedAt`; assert **zero** invokes carry
   `templateName == 'wecare_leave_review'`. This pins the decision above so it cannot regress
   silently.
4. **`test_an_unreadable_payment_reference_does_not_fail_the_capture`** (review 2 finding 2 — the
   failure branch, which revision 2 had no test for). Make the fake commerce-keys table raise
   `botocore.exceptions.ClientError` with
   `{'Error': {'Code': 'ProvisionedThroughputExceededException'}}` on `get_item`. Assert, in this
   order of importance: the post-payment function **returns normally and does not raise**; the
   handler does **not** return 500; **exactly one** invoke carries
   `templateName == 'wecare_leave_review'` (the fail-open default); and
   `review_native_check_unavailable` was logged at `WARNING`. Fails today, because revision 2's
   unguarded form propagates the `OrderIdentityUnavailable`.
5. **`test_an_error_outside_the_storage_wrapper_is_not_swallowed`** (renamed and re-specified;
   review 3 finding 7 accepted). Revision 3 specified "make the fake table raise a bare `KeyError`
   and assert it propagates" — **that test would fail after the fix.** `order_keys._read_row`
   (`:335-347`) wraps *every* storage exception:

   ```python
   try:
       return table.get_item(Key={key_attr: key}, ConsistentRead=True).get("Item")   # :343
   except Exception as error:  # noqa: BLE001                                        # :344
       raise OrderIdentityUnavailable(                                               # :345-347
           "could not read %r: %s" % (key, type(error).__name__)) from error
   ```

   A `KeyError` raised by `table.get_item` therefore arrives at the guard **as
   `OrderIdentityUnavailable`** and is caught — which is correct behaviour, but means the test
   proves nothing and reports red on the plan's most dangerous change.

   **Inject outside `_read_row`'s `try` instead.** Both of these are inside the F-2 guard's `try`
   but outside `_read_row`'s, so neither can be converted into `OrderIdentityUnavailable`:

   | Injection point | Mechanism | Exception seen by the guard |
   |---|---|---|
   | **Preferred** — `dynamodb.Table(COMMERCE_KEYS_TABLE)` | monkeypatch the module's `dynamodb` resource so `.Table()` raises `KeyError('COMMERCE_KEYS_TABLE')`. It is evaluated *before* `resolve_payment_reference` is entered | `KeyError` |
   | Alternative | stub `resolve_payment_reference` to return a **non-mapping truthy** value (e.g. `[1]`), so `or {}` passes it through and `payref.get('nativeCatalogService')` raises | `AttributeError` |

   Assert the exception **propagates** out of the post-payment function rather than being absorbed
   into the fail-open default, and that **no** review invite was sent on that call. This pins the
   narrow-catch choice so a later "tidy-up" to `except Exception` fails the suite.

   > **Why the narrow catch is nevertheless total over storage.** Every storage failure reaching
   > this block is an `OrderIdentityUnavailable` **by construction** at `_read_row:344-347`, so
   > `except order_keys.OrderIdentityUnavailable` has no storage blind spot. It is deliberately
   > *not* total over programming errors raised elsewhere in the block — a bad table name, a
   > non-mapping result, a missing module attribute — and that asymmetry is the whole point: a
   > storage outage must fail open on a captured payment, a logic bug must be loud.

**Deployment: live path, money path.** `wecare-razorpay-webhook` (live **56**, `RevisionId`
`06eb2a78-f73d-4dd8-ab8d-efd4c2f9ef07`, re-read 2026-10-09T04:32:07Z). Customer-visible.
See §5 row 4b-i and §6.

### F-3 — Vault selection admits a file with no customer attribution (MEDIUM, latent). PERMITTED.

**The decision, stated up front** (review finding 2, accepted — and partly executed upstream).
Option (a), "remove phone-only adoption", is the chosen direction, and **the parallel session
already applied it to `vault_access.bind_file` in commit `724dcc38`.** This item is now only the
unconverted half.

**What `724dcc38` did**, to `amplify/functions/shared/lambda_utils/ecommerce/vault_access.py`:

```diff
-            or row.get('ownerCustomerId') not in (None, identity.customer_id)):
+            or not identity.customer_id or row.get('ownerCustomerId') != identity.customer_id):
         raise customer_auth.CustomerNotAuthorized('file unavailable')
-    # Adopt legacy phone-owned files only after an authenticated verified session.
+    # A phone can be reassigned. Legacy ownerless files require explicit staff
+    # reconciliation; a matching verified phone never establishes their original owner.
     files.update_item(Key={'fileId': row['fileId']},
         UpdateExpression='SET ownerCustomerId=:owner',
         ConditionExpression='ownerPhone=:phone AND #s=:active AND '
-                            '(attribute_not_exists(ownerCustomerId) OR ownerCustomerId=:owner)',
+                            'ownerCustomerId=:owner',
```

So `bind_file` is now a pure verifier whose `update_item` rewrites a value that already equals the
owner. The review's suggestion to drop that `update_item` is **backlogged, not done** — it is a
dead-store cleanup in a file another session is actively editing (**O11**), and removing it buys
nothing while risking a merge conflict on a money-adjacent module. Recorded here so it is not lost.

**Evidence — the one site left.** `amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py:93-95`:

```python
if (file.get('status') == 'active' and file.get('ownerPhone') == identity.phone.lstrip('+')
        and file.get('ownerCustomerId') in (None, identity.customer_id)      # :94
        and not file.get('vaultAccessGrantId') and file.get('vaultPaymentStatus') != 'PAID'):
```

Proven to be the last one:

```
git grep -n "ownerCustomerId') in (None" origin/stack -- amplify
-> amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py:94
```

**Severity reduced, honestly.** Revision 1 claimed such a file "would be offered, charged for and
delivered". That was true against `53ed298e` and is **false against `4e259800`**: `bind_file` is
called at `catalog_services.py:119` (the `select` action) and `:152` (before checkout), both
*before* the native checkout invoke at `:157`, and both now raise `CustomerNotAuthorized`. So
the real defect today is that the selector **offers a document it cannot deliver** — an
offered-then-refused dead end, not a disclosure. No money moves. Latent in any case because
`WHATSAPP_CATALOG_SERVICES_ENABLED` is absent.

It remains a hard prerequisite for **L**: a selector listing undeliverable documents is a
customer-visible defect, and the two written invariants
(`native-catalog-release-status.md` "matching a phone alone never grants ownership";
`service-rollout/README.md` §4 "a matching phone is not sufficient to transfer ownership") are now
true of the code everywhere except this line.

**Root-cause fix.** Require positive attribution and nothing else:

```python
and file.get('ownerCustomerId') == identity.customer_id
```

Files with an absent `ownerCustomerId` are then neither offered nor charged for. They must not be
silently dropped either — that would hide the reconciliation debt README §4 already names. So count
them and, when the eligible list is empty but the unattributed count is not, send the existing
non-committal copy (ending `:100`, "No new payment has been requested") and log
`vault_files_unattributed` with the **count only** — never a `fileId`, phone or filename, per the
secret/PII posture the surrounding code keeps.

**Product consequence, stated.** Legacy Vault files with no `ownerCustomerId` become unpurchasable
until an owner-run reconciliation attributes them. That is the same consequence `724dcc38` already
accepted for `bind_file` and `secure-files`, so F-3 makes the selector consistent with a decision
the repository has already taken, rather than taking a new one.

**What must NOT change.** Every other condition stays, including the delivery-time re-verification
chain in `flows/paid_vault.py:68-86` (exactly one `Enabled` Cognito user, `phone_number_verified`,
`phone == '+' + grant['ownerPhone']` at `:74`, contact re-read with `ConsistentRead=True`,
`checkoutCustomerId == row['customerId']`, exactly one surviving contact at `:85-86`) and
`vault_access.grant_access`'s own `file.get('ownerCustomerId') != row.get('customerId')` check at
`:51-52` plus the grant transaction's `ConditionExpression='ownerCustomerId=:owner AND #s=:active'`
at `:71`. That chain is correct and is defence in depth, not a substitute for this fix.

**Ownership of the invariant.** "A WhatsApp phone number alone never grants access to a customer's
private data" is owned by the **selection layer** (`catalog_services.py`), not the delivery layer.
Delivery re-derives from a grant that selection already created; by then the entitlement decision
has been made. Enforcing it at delivery only means offering first and refusing after — which is
precisely the current state. That is why F-3 belongs at `:94`.

**Regression tests (the first fails before the fix).**
`tests/test_vault_file_ownership.py`:

1. `test_a_file_without_a_customer_id_is_never_eligible` — a fake files table holding one
   `status: active` row with `ownerPhone` matching the verified identity and **no**
   `ownerCustomerId`; assert the outcome is `VAULT_FILE_NOT_READY`, that no payment reference was
   minted, and that the spied outbound sender received the no-new-payment copy. Today the file is
   eligible, a list is sent, and the test fails.
2. `test_a_file_owned_by_another_customer_is_refused` — `ownerCustomerId` set to a **different**
   customer; assert refusal. Passes today; it pins that the fix did not loosen the foreign case.
3. `test_a_correctly_owned_file_is_still_eligible` — `ownerCustomerId == identity.customer_id`;
   assert eligibility survives.
4. `test_bind_file_refuses_a_file_with_no_customer_id` — the review's requested `bind_file`-level
   test (fake files table, one active `ownerPhone`-matching row with no `ownerCustomerId`; assert
   `CustomerNotAuthorized` and `update_item` never called). **This should pass on arrival**, because
   `724dcc38` already fixed it. Include it anyway: it pins the upstream fix against regression from
   either session, which is exactly the risk **O11** describes.

**Deployment: gated path.** `flows/catalog_services.py` ships in
`wecare-whatsapp-business-api`, but the arm is behind `WHATSAPP_CATALOG_SERVICES_ENABLED` (checked
at `:42-43`), which is absent everywhere. Code + tests only; deploy rides with §5 item 8.

### F-4 — Cognito `list_users` Filter built by string concatenation (LOW). PERMITTED.

**Evidence — SEVEN sites: two guarded, five unguarded.** Revision 2 said four, revision 3 said six,
and **review 3 finding 10 is accepted: the true count at the base is seven.** Re-derived at
`061b6e77`:

```
git grep -n "Filter='sub" origin/stack -- amplify     ->  7 sites
git grep -n "is_cognito_subject" origin/stack -- amplify  ->  no matches (the helper does not exist yet)
```

The seventh is `flows/customer_orders.py:60`, added upstream by `4a3c4251` (a commit §1 already
lists). It carries its **own** inline `re.fullmatch` guard, so the five-site *fix set* is unchanged —
but the count, and the claim "exactly one copy of the pattern", were both wrong. Anchor patterns are
given because these numbers have moved in every revision so far.

| File:line (`061b6e77`) | Anchor to re-locate it | Guarded? | rev-2 | rev-3 |
|---|---|---|---|---|
| `flows/customer_commands.py:83` | the only `Filter='sub` in the file | **yes** — inline `re.fullmatch` at `:80`, refusal at `:81`. **The model.** | `:83` ✓ | ✓ |
| `flows/customer_orders.py:60` | the only `Filter='sub` in the file; inside `def _verified` at `:53` | **yes** — inline `re.fullmatch` at **`:57`**, `raise customer_auth.CustomerNotAuthorized('account unavailable')` at `:58` | — **missed** | — **missed** |
| `flows/catalog_services.py:55` | the only `Filter='sub` in the file | no | `:55` ✓ | ✓ |
| `ecommerce/checkout/handler.py:**3080**` | the only `Filter='sub` in the file; `verified_identity` caller is the next line (`:3081`) | no | `:3098` ✗ | ✓ |
| `flows/paid_submit_request.py:90` | **first** of two in the file | no | `:90` ✓ | ✓ |
| `flows/paid_submit_request.py:142` | **second** of two in the file | no | `:142` ✓ | ✓ |
| `flows/paid_vault.py:**69**` | the only `Filter='sub` in the file | no | `:44` ✗ | ✓ |

> **Note on review 3's own citation.** Finding 10 placed `customer_orders.py`'s inline guard at
> `:58-60`. The `re.fullmatch` is at **`:57`** and `:58` is the `raise`; `git grep -n "re.fullmatch"
> origin/stack -- amplify/functions/messaging/whatsapp-business-api/flows/customer_orders.py` → `57`.
> Corrected here rather than carried forward.

The gate lines quoted elsewhere in this document also moved and are corrected here once:
`WHATSAPP_CATALOG_SERVICES_ENABLED` in checkout is at **`:3062`** (was cited `:3080` — which is now
the Cognito `Filter` line, the single most dangerous stale citation review 2 found);
`NATIVE_SERVICE_ROLLOUT_DISABLED` **`:3063`**; `NATIVE_SERVICE_WRITEBACK_NOT_READY` **`:3065`**;
`VERIFIED_CUSTOMER_REQUIRED` in checkout **`:3078`** with its `owner != row['customerId']` test at
`:3076-3077`.

The model, `customer_commands.py:78-83`:

```python
owner = str(contact.get('checkoutCustomerId') or '')
# Cognito sub is canonical UUID. Refuse malformed filter inputs before ListUsers.
if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', owner):
    return {'outcome': 'VERIFIED_CUSTOMER_REQUIRED', 'reply': '...'}
users = boto3.client('cognito-idp', ...).list_users(
    UserPoolId=customer_auth.CUSTOMER_POOL_ID, Filter='sub = "' + owner + '"', Limit=2)...
```

Four sites interpolate `owner` from `contact['checkoutCustomerId']` (`customer_commands.py:83`,
`customer_orders.py:60`, `catalog_services.py:55`, `checkout/handler.py:3080`); the remaining three
interpolate `row['customerId']` (`paid_submit_request.py:90`, `:142`, `paid_vault.py:69`). Both
originate from stored attributes rather than handset input, so this is second-order and requires an
already-poisoned row; a `"` would break the filter syntax into a `ClientError`, not a disclosure.
It is an inconsistency in a defence-in-depth control on an identity path, which is where
inconsistencies should not be left.

**Root-cause fix.** Add one definition —
`amplify/functions/shared/lambda_utils/customer_auth.py` as `is_cognito_subject(value) -> bool`
(**verified absent today**: `git grep -n "is_cognito_subject" origin/stack -- amplify` → no matches).
The module is the right home: it already owns `CUSTOMER_POOL_ID` (`:48`), `CustomerNotAuthorized`
(`:72`) and `customer_id_from_attributes` (`:136`), and every one of the seven sites already imports
it to read `CUSTOMER_POOL_ID`.

Then:

- **Guard the five unguarded sites** so each refuses before calling `list_users`.
- **Convert BOTH inline regexes** to the shared helper — `customer_commands.py:80` *and*
  `customer_orders.py:57`. Converting only the first, as revision 3 specified, would leave two copies
  of the pattern and leave the stated goal unmet. With both converted, the literal regex appears
  **exactly once in the tree**, which is the actual invariant this fix is for.
- No behaviour change on well-formed input: `is_cognito_subject` is the same
  `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}` full-match, so each converted site keeps its existing
  refusal — `customer_commands.py` keeps returning `VERIFIED_CUSTOMER_REQUIRED` with its sign-in
  reply, and `customer_orders.py` keeps **raising** `CustomerNotAuthorized('account unavailable')`.
  The two guarded sites differ in refusal *mechanism* (return vs raise) and that difference is
  preserved; only the predicate is shared.

**Regression test (fails before the fix).** `tests/test_customer_identity_filter_guard.py` —
parametrised over the **five** unguarded sites, with a `cognito-idp` double that **raises** on any
call; feed `'" or sub = "x'`, `''`, `'not-a-uuid'` and an uppercase UUID, and assert each returns its
verified-customer refusal (`VERIFIED_CUSTOMER_REQUIRED` for `catalog_services` / `checkout`,
`VERIFIED_RECIPIENT_UNAVAILABLE` for the three flow sites) with the client **never invoked**. All
five fail today.

Plus **two pin cases** for the already-guarded sites, which must pass before *and* after — they exist
so the conversion cannot silently change a working refusal:

| Pin | Asserts |
|---|---|
| `test_customer_commands_still_refuses_a_malformed_subject` | returns `{'outcome': 'VERIFIED_CUSTOMER_REQUIRED'}` with the sign-in reply, `cognito-idp` double **never invoked** |
| `test_customer_orders_still_refuses_a_malformed_subject` | **raises** `customer_auth.CustomerNotAuthorized`, `cognito-idp` double **never invoked** (review 3 finding 10's required addition) |

Seven sites, seven assertions, one regex.

**Deployment: mixed.** `catalog_services.py:55` is gated at `:42`; `checkout/handler.py:3080` sits
inside `prepareNativeCatalogService`, itself gated at `:3062-3063`. But **`paid_vault.py:69` and
`paid_submit_request.py:90`, `:142` are live-path** — the paid Vault delivery chain and the live
paid Submit Request Flow. `customer_commands.py:80` and `customer_orders.py:57` are **also
live-path** and are now in scope for the conversion, so they deploy with the same group; their two
pin tests are the evidence that the conversion was behaviour-preserving. Split accordingly in §5.
Note this item adds a helper to
`shared/lambda_utils/customer_auth.py`, so it is a **shared-package change**: it must land *after*
F-1's single-function deploy, never before, or a fleet-wide publisher would sweep F-1's target.

### F-5 — conditional-failure detection by exception-message substring (LOW). PERMITTED.

**Evidence.** `amplify/functions/shared/lambda_utils/ecommerce/order_keys.py:177` already provides a
structural `is_conditional_failure(error)`:

```python
def is_conditional_failure(error: Exception) -> bool:          # :177
    """A DynamoDB ConditionalCheckFailedException, as opposed to any other failure.
    ...The tree already held three inline copies of this check..."""   # :178-185
    response = getattr(error, "response", None) or {}
    return response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
```

(**The review's `:174` is wrong**; `grep -n "def is_conditional_failure"` returns `177`. Revision 1
was right. See §8 finding 13.)

The money path does not use it. Six sites, and **the sixth is negated** (review finding 7,
accepted — a mechanical "replace each" would invert it):

| Site | Current form |
|---|---|
| `payments/razorpay-webhook/handler.py:1719` | `if 'ConditionalCheckFailedException' in str(guard_err):` |
| `payments/razorpay-webhook/handler.py:2036` | `if 'ConditionalCheckFailedException' in str(e):` |
| `payments/razorpay-webhook/handler.py:2149` | `if 'ConditionalCheckFailedException' in str(cond_err):` |
| `payments/razorpay-webhook/handler.py:2746` | `if 'ConditionalCheckFailedException' in str(e):` |
| `payments/razorpay-webhook/handler.py:2866` | `if 'ConditionalCheckFailedException' in str(e):` |
| `payments/invoice-engine/handler.py:853` | `if 'ConditionalCheckFailedException' **not** in str(claim_err):` |

**Root-cause fix — per site, not mechanical:**

- the five `razorpay-webhook` sites become `if order_keys.is_conditional_failure(<err>):`
- `invoice-engine/handler.py:853` becomes `if not order_keys.is_conditional_failure(claim_err):`

Inverting `:853` would turn an expected duplicate-invoice race into a 500 and a real storage failure
into a silent dedup hit — on the GST-sequence path (`invoice-engine/handler.py:843-852`), which is
the most consequential of the six.

**Why the import is available** (review finding 14, accepted): the **module-scope** imports at
`payments/razorpay-webhook/handler.py:37` (with the comment at `:36`, "Import-safe: `order_keys`
creates no client and reads no secret at import") and `payments/invoice-engine/handler.py:48`. The
five function-local re-imports in the webhook (`:479`, `:814`, `:974`, `:1020`, `:2553`) are
redundant and irrelevant to this fix; revision 1's claim that the
`_request_review_on_whatsapp`-site import is what makes it work was wrong.

**Eight further substring sites exist and are deliberately OUT OF SCOPE**, so the six are not read
as exhaustive: `core/contacts/handler.py:527`, `:589`, `:617`;
`messaging/inbound-whatsapp-handler/handler.py:3280`, `:7858`;
`messaging/outbound-whatsapp/handler.py:4078`;
`messaging/whatsapp-business-api/flows/postpay.py:169`;
`shared/lambda_utils/flow_completion.py:242` (which is itself a helper returning the substring
test). They are not on the captured-payment path and sweeping them in would widen a LOW-severity
change across five more functions.

**Regression test (fails before the fix).** `tests/test_conditional_failure_detection.py`.

**Review 3 finding 6 is accepted: a *plain* `ClientError` cannot carry the code with the substring
absent.** `botocore`'s `ClientError.__init__` formats `MSG_TEMPLATE` with
`error_response['Error']['Code']`, so `str(err)` *always* contains the code. Revision 3's
"rendered message has been changed" was not constructible, which would have made the "fails before
the fix" half of the primary test impossible to write.

**The fixture is a test-local subclass that keeps `.response` and overrides `__str__`:**

```python
from botocore.exceptions import ClientError

class OpaqueConditionalFailure(ClientError):
    """Carries the structural code while rendering a message that lacks it.

    Not a hypothetical: boto3 wrappers, retry shims and re-raises routinely replace the
    rendered message while preserving `.response`. The substring test is what breaks then.
    """
    def __str__(self) -> str:
        return 'storage error'

OPAQUE = OpaqueConditionalFailure(
    {'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'storage error'}},
    'UpdateItem',
)
assert 'ConditionalCheckFailedException' not in str(OPAQUE)   # the premise of the test
assert order_keys.is_conditional_failure(OPAQUE)              # the structural read still works
```

Two halves, both failing today in opposite directions:

| Half | Fixture | Assertion |
|---|---|---|
| **Code present, substring absent** | `OPAQUE` above | the five webhook sites take the **idempotent** branch (info log, no duplicate side effect); `invoice-engine:853` takes the **dedup-hit** branch (info `invoice_dedup_hit_atomic`, no 500) |
| **Code absent, substring present** | a plain `ClientError` with `Code='ValidationException'` and `Message='... ConditionalCheckFailedException ...'` | every site takes the **error** branch. This half needs no subclass — `ClientError` interpolates `Code`, and the substring is supplied in `Message` |

> **The invariant this test pins, binding on every site:** conditional-failure detection reads
> `error.response['Error']['Code']` through `order_keys.is_conditional_failure`
> (`order_keys.py:177`) and **never** inspects `str(error)`. A message is a presentation artefact
> and any layer may rewrite it; the `response` dict is the structured contract. New code that
> re-introduces a substring test on this path is rejected on this rule alone.

The subclass lives in the test module only — **no production subclass of `ClientError` is
introduced**, and `is_conditional_failure` itself is unchanged.

**Deployment: live money path.** `wecare-razorpay-webhook` (live **56**) and
`wecare-invoice-engine` (live **49**). `order_keys` is a shared module, so this is a
**shared-package change** — same ordering constraint as F-4.

### F-6 — internal `orderId` can surface as a customer-facing label, and the same call doubles as an eligibility gate (LOW). PERMITTED.

**Evidence.** `amplify/functions/shared/lambda_utils/ecommerce/paid_submit_request.py:96-97`
(corrected from revision 2's `:93-94`; review 2 finding 10, accepted):

```python
label = str(current.get('orderNumber') or oid)     # :96
result.append({'id': oid, 'title': label[:60]})    # :97
```

falling back to the internal order UUID. `flows/customer_commands.order_page` refuses exactly that,
with the comment "Never fall back to internal UUIDs as customer-facing order numbers", keeping only
values that are non-empty, `<= 80` chars and newline-free. Two paths, one product, opposite rules.

**The consequence revision 1 missed** (review finding 8, accepted). `list_orders`' return value is
**also** a boolean eligibility gate, at `flows/catalog_services.py:64-69`:

```python
from lambda_utils.ecommerce.paid_submit_request import list_orders
if not list_orders(db.Table('stack-wecare-digital-OrderTable'),
                   {'customerId': identity.customer_id, 'orderId': ''}):
    _send(... 'We could not find an earlier order linked to your verified account...')
    return {'outcome': 'SUBMIT_REQUEST_PARENT_ORDER_REQUIRED'}
```

Naively skipping rows without `orderNumber` would flip a customer whose prior orders are all legacy
from **eligible to refused** — a purchase-blocking behaviour change, not a label change, landing on
the gated native path where it is hardest to notice.

**Root-cause fix — separate the two concerns. Review 2's blocking finding 3 is accepted; the
design now chooses, where revision 2 left two incompatible options.**

Revision 2 declared `def order_choices(orders: list[dict]) -> list[dict]` and then described it as
"returning the skipped count alongside". Those are two different shapes, and the ambiguity was
load-bearing: at `flows/paid_submit_request.py:28-36` the result feeds `if not choices:` and then
`{'orders': choices}`. **A tuple is always truthy**, so a 2-tuple return would make the `NO_ORDERS`
screen (`:34`) unreachable and would serialise a tuple into the live paid Submit Request Flow.
Neither of revision 2's two tests would have caught it. Two decisions, both binding:

**Decision 1 — the return value is a plain `list[dict]`. The skipped count is logged, never
returned.**

**Decision 2 — the display rule is applied inside `list_orders`' loop, not in a separate pass over
its output.** Review 2 correctly observed that revision 2's `order_choices` *cannot be implemented
from its own inputs*: `list_orders:96` collapses `orderNumber` and `oid` into a single `title`, so
by the time a caller sees `{'id', 'title'}` the public-number-vs-UUID distinction is gone. The
review offered two remedies — carry `orderNumber` through as a separate key, or apply the rule
inside the loop. **We apply it inside the loop**, because:

- both values are already in scope at `:96` (`current.get('orderNumber')` and `oid`), so no new
  field, no second traversal and no change to the dict shape the Flow consumes;
- adding a third key to the returned dicts would change the payload serialised into a **live** Flow
  screen, which is a larger blast radius than the defect being fixed;
- the predicate already exists and is already the repository's answer to this exact question:
  `order_keys.is_public_order_number` (`order_keys.py:222-235`), which deliberately accepts **both**
  the current `WD-ORD-XXXXXXXX` form and the bare 12-character legacy form, with the docstring
  rationale at `:223-231` ("refusing a historical number would break every order placed before the
  change"). Using it means F-6 cannot accidentally exclude pre-prefix orders.

So `list_orders` keeps its name, its signature and its ownership semantics, and gains one branch:

```python
            label = current.get('orderNumber')
            if not order_keys.is_public_order_number(label):
                # Display rule: a public order number or nothing, never an internal UUID.
                # `flows/customer_commands.order_page` already refuses exactly this.
                skipped += 1
                continue
            result.append({'id': oid, 'title': str(label)[:60]})
```

with `skipped = 0` initialised beside `result` at `:86` and, after the loop and before the `return`
at `:104`, a count-only log line:

```python
    if skipped:
        logger.info(json.dumps({'event': 'order_choices_unnumbered', 'skipped': skipped}))
```

**The eligibility gate is preserved by a separate, explicit helper — this is the part that must not
be got wrong.** `list_orders`' return value is *also* a boolean eligibility test at
`flows/catalog_services.py:64-70`. Narrowing `list_orders` therefore **would** flip a legacy-only
customer from eligible to refused — the purchase-blocking regression revision 1 missed and revision
2 identified. The fix must not reintroduce it. So add, beside `list_orders`:

```python
def has_prior_order(orders: Any, row: dict) -> bool:
    """Eligibility only: does a DIFFERENT order exist under this verified customer?

    Deliberately does NOT apply the display rule. A customer whose only prior orders are
    legacy and unnumbered is still entitled to buy Submit Request; they simply see a
    shorter selector. Keeping these two questions in one function is what made the naive
    version of this fix purchase-blocking.
    """
```

implemented as the same `customerId=:owner` query and `ConsistentRead=True` ownership recheck,
short-circuiting `True` on the first qualifying row. `flows/catalog_services.py:65` switches from
`if not list_orders(...)` to `if not has_prior_order(...)`. That is a two-line call-site change and
it makes the two concerns separately testable, which is the real point.

**The logging imports — two are needed, not one** (review 3 nit 16, accepted). Re-derived at
`061b6e77`, `shared/lambda_utils/ecommerce/paid_submit_request.py` imports exactly `hashlib` (`:8`),
`hmac` (`:9`), `secrets` (`:10`), `time` (`:11`), `typing.Any` (`:12`) and
`order_keys, service_request_store as store` (`:13`). It has **no `logger` and no `json`**, so the
snippet above needs both — and rather than add a hand-rolled `json.dumps`, **use the house helper**,
which is what the rest of the tree uses:

```python
from lambda_utils.logging import get_logger, log_event    # add beside the :13 import

logger = get_logger(__name__)                             # module scope
...
    if skipped:
        log_event(logger, 'order_choices_unnumbered', skipped=skipped)
```

`log_event` (`lambda_utils/logging.py:28`) takes `(logger, event_name, level='info', **kwargs)` and
emits the structured JSON itself, so this drops the `json` import entirely and keeps one line instead
of two. `get_logger` (`:17`) is import-safe here — it creates no client and reads no secret, only
`logging.getLogger` and `setLevel` — which matters because this module is imported on the paid path.

The count is the **only** field — never a `fileId`, an `orderId`, a phone or a filename, per the
posture the surrounding modules keep. `log_event`'s `**kwargs` makes that posture explicit at the
call site: there is exactly one keyword and it is a number.

**Trade-off, stated.** A customer with legacy rows sees a shorter selector in the Flow but is still
*eligible* to purchase. That is the correct trade: an internal UUID in a WhatsApp selector is both
useless to the customer and an avoidable internal-identifier disclosure, while refusing the purchase
outright would be a regression. If the owner later wants legacy-only customers refused, that is a
separate, deliberate product change with its own test.

**Regression tests.** `tests/test_paid_submit_request_order_labels.py`:

1. `test_orders_without_a_public_number_are_not_offered` — a fake orders table with one
   `orderNumber`-bearing row and one without; assert `list_orders(...)` has length **1** and that no
   returned `title` matches the UUID regex. **Fails today**: both rows are offered, one with a UUID
   title.
2. **`test_list_orders_returns_a_plain_list`** (review 2 finding 3) — assert
   `isinstance(result, list)`, and that an input whose rows **all** lack `orderNumber` yields `[]`,
   so `flows/paid_submit_request.py:34`'s `NO_ORDERS` screen actually fires. This is the test that
   catches the tuple mistake; it is the reason the shape decision is recorded above rather than left
   to the coder.
3. `test_a_legacy_only_customer_is_still_eligible` — a fake orders table whose only rows lack
   `orderNumber`; assert `has_prior_order(...)` is `True` so `catalog_services.py:65` does **not**
   emit `SUBMIT_REQUEST_PARENT_ORDER_REQUIRED`, **while** `list_orders(...)` returns `[]`. One test,
   both halves of the separation, asserted together. This is the test that would have caught the
   naive version of this fix.
4. `test_a_legacy_bare_twelve_character_number_is_still_offered` — a row whose `orderNumber` is the
   pre-prefix bare 12-character form; assert it **is** offered. Pins the choice of
   `is_public_order_number` over `is_current_public_order_number`
   (`order_keys.py:222` vs `:238`); the stricter predicate would silently drop every order placed
   before the `WD-ORD-` prefix existed.
5. `test_the_skipped_count_is_logged_without_identifiers` — one numbered and two unnumbered rows;
   assert the `order_choices_unnumbered` record has `skipped == 2` and that **no** value in it
   contains any `orderId` from the fixture. Pins the PII posture.
6. `test_the_parent_order_is_still_excluded` — `row['orderId']` present among the queried rows;
   assert it is absent from the result. Sensitivity proof that the new `continue` at the label
   branch did not disturb the existing self-exclusion at `:91-92`.

**Deployment: live path.** `flows/paid_submit_request.py:32` is the **live** paid Submit Request
Flow's `INIT`/`BACK` screen, reached for website-origin paid Submit Request purchases too —
`prepare_and_send` only *branches* on `payref.get('nativeCatalogService')` at `:108`, it does not
require the native flag. So this is customer-visible and ships in `wecare-whatsapp-business-api`.
It also edits a shared module (`shared/lambda_utils/ecommerce/paid_submit_request.py`).

### F-7 — the shared-catalog / fixed-dataset commit `a739d016`. **OWNER-GATED — STOP. Half overtaken.**

**What changed since revision 1.** Revision 1 proposed deploying `a739d016` to stop live drifting
from source, gated on **O1** + **O3**. The parallel session has since achieved the **catalog half
by environment change instead of code deploy**: live `wecare-meta-catalog-sync` v7 (03:30:32Z) sets
`META_CATALOG_ID=1457045652952851` with `ENABLED=false`, `DRY_RUN=true`,
`FORCE_OUT_OF_STOCK=true`, and v7's `CodeSha256` is **identical to v6's** (`9Nrpq65Z…`) — so the
code is unchanged and only the configuration moved.

Current live-vs-source position:

| Artifact | Live | Source |
|---|---|---|
| `wecare-meta-catalog-sync` v7 `handler.py` | code = v6; `META_CATALOG_ID` default still `"1607047307067517"`; old docstring. **Env explicitly sets `1457045652952851`**, so the default is moot | `:73` default `"1457045652952851"`; "OWNER-AUTHORIZED SCOPED ROLLOUT, 2026-10-08" docstring |
| `wecare-meta-catalog-sync` v7 `meta_catalog_sync.py` | identical to source (diff 0 at v6; code unchanged at v7) | — |
| `wecare-whatsapp-business-api` v88 | **UNCERTIFIED.** The parallel session certifies v86 for five named functions and records `allOtherChangesCertified: false`; v87 and v88 are certified by nobody. Live is also **ahead** of source on the outbound delivery contract (their AUD-018: "502 is `SEND_UNKNOWN`") | `CAPI_FIXED_DATASET_ID = os.environ.get('META_CAPI_DATASET_ID', '4554612361454941')` returned for both WABAs; plus an `internalAction == 'serviceDesignDrafts'` arm |

**Why this must still stop.** The remaining half of `a739d016` changes which Conversions API dataset
events land in. That is customer-facing and is **not reversible by a code revert alone** once events
have been written to a different dataset. It requires owner decision **O3** (confirm the catalog
choice that was already executed) and is downstream of **O1** (deletion-vs-permission on the old
catalog). It now also requires **O11**, because drift on `wecare-whatsapp-business-api` runs in both
directions and another session owns the forward half. **Nothing in this plan deploys it.**

**When it is unblocked**, the sequence is fixed and non-negotiable: publish a **new** version from
the rebased-onto-`stack` tree and move the alias to that — never promote an existing version, and
never publish from a `$LATEST` that was not rebuilt. `change-authority-matrix.md`'s 2026-10-07 entry
records exactly this instruction and the incident that produced it. Any provisioning script runs
bare (dry run is the default) and the printed delta is read before `--apply`.

**Rollback** is the alias move back to the captured version, verified by an independent API read
rather than the command's exit code, **with the environment restored in the same step** — a
published version freezes its environment, so the alias move alone does not restore configuration.
For the catalog sync specifically, rolling back to v6 also reverts the target to
`1607047307067517`, which is the unreadable one; so a rollback of the *code* must not silently
revert the *target*. Capture both.

### F-8 — documentation reconciliation (MEDIUM). PERMITTED.

Record, in the repository rather than only in this audit:

1. `docs/whatsapp/native-catalog-release-status.md` — strike the closing reference to
   `native-catalog-integration-evidence.json`; **the file does not exist** (conflict C1, and the
   brief asked for this conflict to be recorded). Removing the claim is preferred to generating the
   file: a machine-readable evidence file that is absent is worse than no claim.
2. The same document's alias table (checkout 36 / business-api 76 / inbound 88 / outbound 55) is
   stale, **and so is revision 1's correction of it**. Record the two timestamped captures from
   `answers.md` **C** and state plainly that the fleet moved twice during a single audit, so any
   alias number in a document is a timestamp, not a fact.
3. `docs/whatsapp/service-rollout/README.md` — correct "catalog sync returns `read_failed` with
   `applied=0`; propagation into Meta remains unverified" to the measured truth: the sync succeeded
   45 times through 2026-10-08T23:28:48Z with an **empty** plan (so Meta already matched Wix for the
   two in-scope items); a **different** failure began at 2026-10-09T00:21:01Z; its cause is
   **Graph 100 / subcode 33** on `1607047307067517`; and live has since been retargeted to
   `1457045652952851`, which reads 200 but is **empty**.
4. **Corrected from revision 1** (review finding 5): record the **five** `applied: 0` return arms
   (`:528-529`, `:558-559`, `:568-572`, `:599-601`, `:604-606`) and that after F-1 `reason` is
   always present, so **`applied: 0` is never read alone**. Do **not** write "two meanings" — that
   was wrong.
5. Record the Wix revision 4-vs-5 discrepancy as **NOT VERIFIED** rather than leaving two numbers.
6. **CORRECTED and made concrete** (review 2 finding 6, accepted). Record that `.kiro/steering/*`
   was intentionally deleted in `af7858fa`, that `af7858fa` is an ancestor of `origin/stack`, and
   that this removed `02-qa-recipient.md`, **the document of record for the only number authorized
   to receive a live WhatsApp QA send.** Revision 2 claimed the nomination "survives in
   `service-rollout/README.md` §9 and `continue-prompt.txt`". **That is wrong.** Re-verified at
   `061b6e77`:

   ```
   git grep -n "918100640044" origin/stack -- docs/whatsapp/service-rollout/  -> (no matches)
   git grep -l "918100640044" origin/stack | wc -l                           -> 90
   ```

   Those two documents preserve only the **four-digit suffix** — **`README.md:59`** ("owner
   authorized personal number **ending 0044** for customer QA. Business number ending 4400 is
   deliberately excluded from checkout") and **`continue-prompt.txt:9`** ("The owner supplied QA
   customer number **ending 0044**"). **Both line numbers moved by two between `e9e377ce` and
   `061b6e77`** — they were `:57` and `:5` — because `4fe31824` and `061b6e77` both edited these files. The full E.164
   appears in `docs/kiro-handoff.md` and **89 other tracked files** (88 at `e9e377ce`), but in **no
   document of record.** That is the worst of both arrangements: ninety scattered copies and no
   authority. **A suffix cannot authorize a send.**

   > **This item is IMPERATIVE and UNAPPLIED.** `docs/execution/qa-recipient.md` **does not exist**
   > at `061b6e77` (`git ls-tree -r --name-only origin/stack | grep -i qa-recipient` → no match).
   > Nothing in §8 or `answers.md` should be read as saying this has been done; what has been done
   > is the *retraction of the false provenance claim* in `answers.md`. **Creating the file is work
   > still owed, scheduled as §5 row 5.**

   So: create `docs/execution/qa-recipient.md` as the single authority, recording `+918100640044`
   with its authority chain (owner nomination → `02-qa-recipient.md`, deleted in `af7858fa` → this
   file), the explicit exclusion of the business sender `+919330994400` as a customer identity
   (already enforced in code at `catalog_service_checkout.verified_identity:38` via
   `whatsapp_basket.is_business_sender`, checked *before* every other condition), and a statement
   that the suffix-only form is **not sufficient** to authorize a send. Reference it from
   `README.md` work-list item 9 rather than duplicating the number again.

   Record also that **no surviving document grants standing production authorization**, and that
   `change-authority-matrix.md:1154` requires explicit per-target owner approval. (Note: the `§N`
   notation in the rollout documents means *numbered work-list item N*, not a section — review 2
   confirmed this and it is worth stating, because it reads as a section reference.)
7. **NEW** — record the payment-config root cause permanently: Meta's `fields` filter returns an
   empty collection for the `payment_configurations` edge, and the old read was unpaginated. Both
   fixed in `724dcc38`. Two inert GETs on v86 show `WECAREUPI` and `WECAREDIGITAL`, both `Active`.
   This retires a contradiction that has produced conflicting handoffs repeatedly, so it belongs in
   the repository, not only in an audit file.
8. **NEW** — record the two-session overlap (conflict C12): `docs/execution/xcodex-20261009/`
   contains an architecture document, migration matrix and payment state machine with the same
   names as this audit's `outputs/`. Both exist, conclusions are compatible. Record which is
   canonical so neither is deleted as a duplicate.
9. **NEW** — record the dual `PAYMENT_PAID` normalisation: server-side at
   `messaging/whatsapp-business-api/service_api.py:129-130` and again client-side at
   `src/api/client.ts:5789` in `getOrder` but **not** in `listOrders`. Two normalisation points for
   one concept.
10. **NEW** — record the two workspace-orders defects found while answering **S**, as backlog items
    rather than fixes in this plan: the unfiltered `table.scan()` at `service_api.py:121`, and
    the **silent** truncation to 200 rows at `:137-138` which gives an operator no indication that
    orders are missing.

### F-9 — a paid Vault customer whose download link expires after redeeming is told to pay again (HIGH, **LIVE via the native path**). PERMITTED.

**This is the most customer-damaging finding in the audit.** It arrived with the owner's revision-3
requirement to document the Vault order → download sequence, and it was found by tracing that
sequence rather than by inspecting a filename. Full derivation, with the whole message chain and
the TTL table, is in `outputs/whatsapp-customer-service-architecture.md` §6; this entry is the
executable contract.

#### F-9.0 Exactly what is live, what is gated, and what the record's lifetime is (review 3, findings 1 and 2)

Review 3 finding 1 held that F-9 is unreachable because `SECURE_FILES_PAYMENT_ENABLED=false`. **That
is correct for the `secure-files` paid routes and wrong for the path that actually mints Vault
grants in production.** The gate is a local environment read in one function, so it governs only the
four call sites inside that function. Re-derived at `061b6e77`:

```
git grep -n "_payment_enabled\|SECURE_FILES_PAYMENT_ENABLED" origin/stack -- amplify/functions/core/secure-files/handler.py
git grep -rn "SECURE_FILES_PAYMENT_ENABLED" origin/stack -- amplify scripts | grep -v core/secure-files
git grep -n "grant_access" origin/stack -- amplify
```

| Fact | Evidence at `061b6e77` |
|---|---|
| `_payment_enabled` definition | `secure-files/handler.py:255`, reads `SECURE_FILES_PAYMENT_ENABLED` at `:261` |
| Its **only** four refusal sites | `:981` (`_create_order` → 503 `PAYMENT_DISABLED` `:987`), `:1058`, `:1156` (`_reconcile_grant`), `:1272` (`_send_whatsapp_payment` → `:1276`) |
| **`_redeem` (`:1405`) is NOT gated** | not among the four sites — the redeem route runs regardless of the flag |
| The flag exists nowhere else in `amplify/` | only in `scripts/provision_secure_files_api.py:349,360,370,682` (the provisioner) |
| **The native grant minter is in a different Lambda** | `flows/paid_vault.py:63` → `vault_access.grant_access` (`vault_access.py:30`), in `wecare-whatsapp-business-api`, **with no payment gate of any kind** |
| Its reach-path has no rollout flag either | `handler.py:5996-6000` (`internalAction == 'preparePaidSubmitRequest'`) → `paid_submit_request.py:104` → `:127` `kind == 'VAULT'` → `:128-129` `vault_send`. The only flag in `paid_vault.py` is `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` at `:93`, which selects a template, not a gate |

**So the live chain is the native one, and it is open today:** a native Vault purchase mints a grant
at `vault_access.py:64-67`, the customer redeems once on the web through the ungated `_redeem`
(`:1405`), `consumed` flips at `:1427`, the 60-second URL (`DOWNLOAD_URL_TTL`, `:215`) expires, and
the retry lands on `:1459-1460` *"This download link is not valid. Please pay again to download."*
No `_payment_enabled()` check stands anywhere on that path. **F-9 stays HIGH.**

**Record lifetime — the two grant kinds have two different lifetimes, and the live one is durable.**
Review 3 finding 2 is right that this was never analysed, and the analysis reverses its conclusion:

| Grant origin | `expiresAt` written? | Lifetime | Evidence |
|---|---|---|---|
| `secure-files` `_create_order` | **yes**, `now + GRANT_TTL` (1800 s) | TTL-swept | `handler.py:1016`, `GRANT_TTL` `:219` |
| `secure-files` `_reconcile_grant` | **yes**, `now + GRANT_TTL` | TTL-swept | `handler.py:1306` |
| **native `vault_access.grant_access`** | **NO `expiresAt` attribute at all** | **durable** | `vault_access.py:64-67` — the item is `grantId, fileId, ownerPhone, customerId, orderId, reference, requestId, source, paid, consumed, createdAt`; `git grep -n expiresAt origin/stack -- .../vault_access.py` returns **nothing** |

`DownloadGrantsTable` has TTL **enabled on `expiresAt`** (`scripts/check_data_model_drift.py:191-196`
— the `DownloadGrantsTable` entry; the TTL sentence is on `:193-194`),
and DynamoDB TTL only sweeps items that **have** the attribute. The native grant has none, so it is
never swept. The two TTL-swept origins are precisely the two that `SECURE_FILES_PAYMENT_ENABLED=false`
refuses. **The gated grants are ephemeral; the live grants are durable.**

**Decision on finding 2, explicit: entitlement derives from the durable FILE row, option (b). No TTL
is created, extended or touched anywhere.** Reasons, in order of weight:

1. **It is already durable and already authoritative.** `vault_access.py:71` writes
   `vaultAccessGrantId`, `vaultPaymentStatus='PAID'`, `vaultOrderNumber` and `vaultRequestNumber`
   onto the `SecureFilesTable` row, under `ConditionExpression='ownerCustomerId=:owner AND #s=:active'`.
   `SecureFilesTable` TTL is **DISABLED** by deliberate design — *"a shared file outlives any session
   and must not be swept"* (`check_data_model_drift.py:189-190`). The proof of payment therefore
   already lives on a record that cannot expire.
2. **It needs no new write to a swept record.** Option (a) would `SET expiresAt` to a longer
   retention on the grant row. Even restricted to the redeem path that is a TTL extension, and §5's
   safety rules forbid lengthening any TTL. Option (b) writes no `expiresAt` at all.
3. **The existing UI already reads exactly this attribute.** `_customer_list:931` branches on
   `i.get('vaultAccessGrantId')` from the file row before it ever loads the grant. The re-issue
   route reuses that same traversal.

**Binding consequence for the implementer.** The re-issue entitlement predicate is
`file['vaultPaymentStatus'] == 'PAID'` **and** `file['vaultAccessGrantId']` present, read from the
row `_owned_active_file` already returned. **The `reissueCount` cap lives on the FILE row, not the
grant row**, so the cap cannot evaporate with a swept grant. The grant row is still read and still
conditionally updated when it exists — that is what keeps first-redeem single-use — but a **missing**
grant row is no longer evidence of non-payment.

**Read item added to justify §5 row 4c (finding 1's requirement).** Before deploying the route,
count the affected population. `A0_READ`, no mutation, no `secretsmanager` call:

```
aws --cli-read-timeout 25 --cli-connect-timeout 10 dynamodb scan \
  --table-name stack-wecare-digital-DownloadGrantsTable \
  --filter-expression 'paid = :t AND consumed = :t AND attribute_not_exists(expiresAt)' \
  --expression-attribute-values '{":t":{"BOOL":true}}' \
  --select COUNT
```

`attribute_not_exists(expiresAt)` isolates the **durable native** grants — the ones that are both
live-reachable and still present. A second COUNT without that clause gives the swept-origin total for
contrast. §5 row 4c is justified if the durable count is **≥ 1**; if it is `0`, F-9 drops to
MEDIUM-latent and ships the copy correction only — at **both** `:1459-1460` and `:1224-1225` — with
the route deferred behind §5 item 8's gate sequence. **This read is a prerequisite of row 4c, not of
the copy fix.** The `:1224-1225` half is required even in the `0` case, precisely because item 8 is
the event that makes that site reachable.

**Evidence.** `amplify/functions/core/secure-files/handler.py`, live in `wecare-secure-files`
(live **34**, `RevisionId` `01e8e9ef-f514-4829-9dc5-7299321465ab`, read 2026-10-09T04:32:07Z).

`_redeem` (`:1405`) is single-use by construction. Its conditional update requires
`consumed = :false` and sets `consumed = True`:

```python
UpdateExpression="SET consumed = :true, consumedAt = :now",                              # :1427
ConditionExpression=("attribute_exists(grantId) AND fileId = :fid AND ownerPhone = :p "
                     "AND customerId = :owner AND paid = :true AND consumed = :false")   # :1428-1431
```

(the `consumed = :false` clause itself is on `:1430`; the enclosing `ConditionExpression=(...)` spans
`:1428-1431`.)

docstring rationale at `:1408-1410`: *"it flips `consumed` only if it is currently false, so two
concurrent requests cannot both win and a forwarded link is dead on second use."* On the
`ConditionalCheckFailedException` arm it correctly tries `_reconcile_grant` first (`:1453`, asking
Razorpay directly for the never-arrived-webhook case), and otherwise returns:

```python
return cors_response(403, {"error": "GRANT_NOT_REDEEMABLE",
    "message": "This download link is not valid. Please pay again to download."}, origin)  # :1456-1463
```

The minted URL lives **60 seconds** — `DOWNLOAD_URL_TTL` at `:215`, default `60`, and live
`DOWNLOAD_URL_TTL_SECONDS=60` confirmed at 04:39:21Z. And `_customer_list:931-935` only surfaces a
`paidGrantId` while `grant.get('paid') and not grant.get('consumed')` (`:933`), so once consumed the
UI has nothing to retry with. The only remaining route is `_create_order` (`:963`) — **a second ₹49
charge**, whose own docstring (`:966-972`) describes it as the recovery path for "a customer who has
already paid [to] collect a file when WhatsApp delivery keeps failing".

The code also **states an intent it does not deliver**, at `:216-217`: *"Direct links are bearer
capabilities. Keep the read window bounded; a customer can use authenticated Vault access after the
delivery link expires."* True for an unredeemed grant; **false once consumed.**

**Scope boundary, stated honestly.** The WhatsApp delivery leg is **not** affected: `:1371-1374`
records that it deliberately mints its URL outside the redeem route *"so delivery does not consume
the grant the customer may still redeem on the web"*. So a customer who misses the 900-second
WhatsApp link can still redeem once on the web. **The unrecoverable case is specifically: web redeem
consumed the grant, then the 60-second URL expired before the download finished.** On a mobile
connection — a suspended tab, a tunnel, a user who taps and then reads a message — that is an
ordinary occurrence, not an edge case.

**Root cause.** `consumed` is doing two unrelated jobs: (a) defeating a **forwarded** link used by a
third party, and (b) capping the **owner's own** re-downloads. Job (a) is essential. Job (b) is an
accident of sharing one flag, and it is the whole defect.

**Root-cause fix — separate the two jobs. The ownership check already distinguishes them.** A
forwarded link carries no Cognito session, so it can never satisfy `_owned_active_file`
(`:948-960`, which requires `item['ownerCustomerId'] == identity['subject']` at `:958`) or
`grant['customerId'] == identity['subject']` (`:1421`). **Therefore re-issuing to the authenticated
owner does not weaken the forwarded-link defence at all.** That is what makes this fix safe rather
than a loosening, and it is the reason the fix is permitted under the "do not weaken ownership
checks" rule: it adds a path that is *more* strongly authenticated than the one it supplements.

**The auth envelope, stated exactly (review 3 finding 8).** Revision 2's phrase "the same
`require_auth` identity envelope" was **wrong and dangerous**, because `require_auth` is the *admin*
surface. Re-derived at `061b6e77` with
`git grep -n "_customer_identity\|require_auth" origin/stack -- amplify/functions/core/secure-files/handler.py`:

| Line | What is there |
|---|---|
| `:1827` | `if len(tail) == 2 and tail[1] in ("order", "download", "whatsapp-pay"):` — **the customer block opens here** |
| `:1828` | `identity = _customer_identity(event)` |
| `:1829-1830` | `if not identity: return cors_response(401, {"error": "Verification required"}, origin)` |
| `:1836` | `if tail[1] == "download" and method == "GET": return _redeem(tail[0], event, identity, origin)` |
| `:1840` | `denied = require_auth(event, "Operator")` — **the admin surface begins here** |

> **BINDING: the re-issue route is hosted inside the customer envelope at `:1827-1836`, reached
> through `_customer_identity(event)` at `:1828`, returning `401 "Verification required"` on `None`
> — the identical envelope `_redeem` already sits in. It MUST NOT be placed in or after the
> `require_auth(event, "Operator")` block at `:1840`, and no staff/role check may be added to the
> customer route.** The handler's own module docstring says why: `:40-44` records that admin routes
> use `require_auth` which *"validates against the **admin** pool"*, and that customer routes must
> not, because *"`require_auth` hardcodes the admin"* pool — with the inline warning repeated at
> `:1806-1807` that using it here *"would let a customer token fall through to role Viewer"*.

Because `reissue=1` is a query parameter on the **existing** `download` route, `tail` is unchanged,
so the route lands in the `:1827` block with no routing edit at all: the only change inside the
dispatcher is that `_redeem` (or a `_reissue` helper it delegates to) inspects the parameter. The
existing auth and CORS wiring is reused verbatim.

**Route shape and the single conditional update (review 3 finding 9).** `design.md` is **binding**
and the alternative shape in `outputs/whatsapp-customer-service-architecture.md` §6.5 is deleted.
One shape only:

> **`GET /files/{id}/download?reissue=1`** — a parameter on the existing route. There is no
> `/download/reissue` route.

Order of operations, and where each condition is enforced:

- Call `_owned_active_file(file_id, identity)` **first** and return `_not_registered(origin)` on
  `None`, exactly as `_redeem` does at `:1417-1419`. Ownership precedes everything. This returns the
  durable file row, which carries `vaultAccessGrantId` and `vaultPaymentStatus`.
- Require `item.get('vaultPaymentStatus') == 'PAID'` and `item.get('vaultAccessGrantId')` on that
  row. This is the entitlement, and it is durable. Absent either → `_not_registered(origin)`.
- The **cap and the counter live on the FILE row** (`SecureFilesTable`, TTL disabled), so the cap
  survives a swept grant. Cap **5**, named `REISSUE_CAP`. One atomic conditional update:

```python
REISSUE_CAP = 5

_table(FILES_TABLE).update_item(
    Key={"fileId": file_id},
    UpdateExpression="ADD reissueCount :one SET lastReissuedAt = :now",
    ConditionExpression=(
        "attribute_exists(fileId) AND #s = :active "
        "AND ownerCustomerId = :owner AND ownerPhone = :p "
        "AND vaultPaymentStatus = :paid AND vaultAccessGrantId = :gid "
        "AND (attribute_not_exists(reissueCount) OR reissueCount < :cap)"
    ),
    ExpressionAttributeNames={"#s": "status"},
    ExpressionAttributeValues={
        ":one": 1, ":now": int(time.time()), ":active": "active",
        ":owner": identity["subject"], ":p": identity["phone"],
        ":paid": "PAID", ":gid": item["vaultAccessGrantId"],
        ":cap": REISSUE_CAP,
    },
    ReturnValues="ALL_NEW",
)
```

  **`attribute_not_exists(reissueCount) OR reissueCount < :cap` is mandatory and is the half §6.5
  omitted.** A bare `reissueCount < :cap` is `false` on a row that has never been re-issued, so the
  *first* re-issue — the only one that matters for the live population — would always be refused.
  The `OR` arm is what makes the first call succeed. `ADD` on a missing numeric attribute initialises
  it to the operand, so no separate initialisation write is needed.

- **Mapping `ConditionalCheckFailedException` — by re-reading the row, because the condition cannot
  say which clause failed.** Re-read with `ConsistentRead=True`, then, first match wins:

  | Re-read state | Response |
  |---|---|
  | `reissueCount >= REISSUE_CAP` | `403 GRANT_REISSUE_EXHAUSTED` |
  | grant row exists and `consumed` is false | **fall through to `_redeem`** — this is a first redeem, not a re-issue, so there stays exactly one way to first-redeem |
  | anything else (not active, not owned, not `PAID`, row gone) | `_not_registered(origin)` |

- Mint `_download_url(item)` on the ordinary 60-second `DOWNLOAD_URL_TTL` (`:215`). **Do not lengthen
  any TTL** — the fix is re-issuability, not a longer bearer window.
- Correct the refusal copy at **`:1459-1460`** (`_redeem`) **and at `:1224-1225`
  (`_redeem_after_reconcile`, the identical string)** so a paid-and-consumed grant is never told to
  pay again. `:1225` is **not** live-reachable today — `_redeem_after_reconcile` is entered only when
  `_reconcile_grant` returns True (`:1453-1454`) and that function returns False while
  `_payment_enabled()` is false (`:1156-1157`) — but it becomes reachable the moment §5 item 8 opens
  the flag, and item 8 lists F-9 as satisfied. **Fixing one site and not the other would re-introduce
  the defect at the gate opening.** **This copy correction is the one piece that ships independently
  of the route and independently of the row count**, because `:1459-1460` is the only live residue on
  the gated `secure-files` origins as well.
- `_customer_list:931-935` gains `deliveryStatus: 'REDEEMED_REISSUABLE'` when the file row is `PAID`
  and under the cap, so the UI has something to render. Note the existing `:933` predicate requires
  `not grant.get('consumed')` for `READY`; the new arm is evaluated when that one does not match, and
  **must not require the grant row to exist**.

**Error handling, per failure condition.**

| Condition | Recoverable? | Caller receives | Logged |
|---|---|---|---|
| File absent, inactive, or not this caller's | n/a — refusal is correct | `_not_registered(origin)` (indistinguishable by design, `:951`) | no (enumeration defence) |
| File row lacks `vaultPaymentStatus == 'PAID'` or `vaultAccessGrantId` | n/a — not an entitled file | `_not_registered(origin)` | no |
| **Grant row absent (swept or never existed) but file row is `PAID`** | **yes — re-issue proceeds** | `200` + fresh 60 s URL | `info`, file id + `reissueCount`. This is the finding-2 case: a missing grant row is **not** evidence of non-payment |
| Grant row present, `customerId` mismatch | n/a | `_not_registered(origin)` | no |
| Grant row present and not yet consumed | n/a — wrong route | fall through to `_redeem` | no |
| `reissueCount >= REISSUE_CAP` (5) | no | `403 GRANT_REISSUE_EXHAUSTED`, copy directs to support | `warning`, file id + count |
| DynamoDB error on the counter update | **fatal for this request** | `500` | `error`. **Must not mint the URL** — unlike `:1474-1475`'s download-counter, which may fail silently because it is only a metric, this counter is the cap and failing open would make the cap unenforceable |
| S3 presign failure | fatal | `500` | `error`. The counter has already incremented; this is accepted — the cap is a safety bound, not a billing meter, and over-counting fails *closed* |

**Validation of the one external input.** `file_id` is a path parameter: required, string, and never
trusted — it is used only as a DynamoDB partition key via `_owned_active_file` and is never
interpolated into a query, a filter or an S3 key the caller controls. `reissue` is an optional query
parameter compared literally to `'1'`; any other value takes the normal `_redeem` path.

**Which layer owns the invariant, and why that layer.**

| Invariant | Owning layer | Why there |
|---|---|---|
| "Only the permanently-attributed owner may obtain a URL for a private file" | `_owned_active_file` (`:948-960`), which checks `status == 'active'` (`:954`), `ownerPhone` (`:956`) and `ownerCustomerId == identity['subject']` (`:958`) | It is the single chokepoint all existing callers pass through (`:977`, `:1268`, `:1417`). F-9 adds a fourth caller to the *same* chokepoint rather than writing a parallel check — the only way to add a route here without creating a second, divergent definition of ownership |
| "A first redeem happens at most once" | the **grant row** conditional update at `:1427-1431` (`consumed = :false` → `consumed = True`) | Unchanged by F-9. It is the only atomic single-use mechanism, and re-issue deliberately does not touch `consumed` |
| "Re-issues are bounded" | the **FILE row** conditional update (`reissueCount`), enforced in the same atomic call that authorises the re-issue | Must be on the durable record, or the bound disappears with the TTL sweep (finding 2). Enforcing it in the *same* conditional update is what makes concurrent re-issues unable to both win |
| "A paid customer is never told to pay again" | the copy at **`:1459-1460`** (`_redeem`) **and at `:1224-1225`** (`_redeem_after_reconcile`) — **both** ranges, because the string is identical and duplicated | Presentation-layer defect, fixed at the presentation layer; it is the only change that is correct regardless of whether the route ships. `:1224-1225` is unreachable today (`_reconcile_grant` returns False while `_payment_enabled()` is false, `:1156-1157`) but becomes reachable when §5 item 8 opens the flag — and item 8 lists F-9 as satisfied, so the invariant is only genuinely owned if both sites are corrected |

**Regression tests.** `tests/test_vault_download_reissue.py`, **six** cases. The specification in
`outputs/whatsapp-customer-service-architecture.md` §6.5 is subordinate to this entry wherever the
two differ.

| Test | Before fix | Purpose |
|---|---|---|
| `test_a_consumed_grant_can_be_reissued_to_the_owner_without_a_new_charge` | **fails** (`403 GRANT_NOT_REDEEMABLE`) | the primary defect |
| `test_a_swept_grant_does_not_tell_a_paid_customer_to_pay_again` | **fails** | **finding 2.** Fixture: file row `status='active'`, owned, `vaultPaymentStatus='PAID'`, `vaultAccessGrantId='vault-abc'`; grants table **empty** (the TTL sweep). Asserts `200` with a URL, and asserts the body contains neither `"pay again"` nor `GRANT_NOT_REDEEMABLE` |
| `test_reissue_is_refused_at_the_cap` | fails | fixture `reissueCount = 5` → `403 GRANT_REISSUE_EXHAUSTED`; proves the `OR attribute_not_exists` arm did not disable the bound |
| `test_the_first_reissue_succeeds_on_a_row_with_no_reissue_count` | fails | the §6.5 cap-condition bug specifically: absent `reissueCount` must **not** refuse |
| `test_a_consumed_grant_is_never_reissued_to_a_different_customer` | **passes before and after** | sensitivity proof |
| `test_the_forwarded_link_defence_survives` | **passes before and after** | sensitivity proof — an unconsumed grant still first-redeems exactly once, and a caller with no session gets `401`/`_not_registered` |

The two sensitivity proofs are the ones that would catch this fix becoming a loosening; a change that
makes either of them fail is rejected regardless of the others.

**Testability.** Unit-testable in full with fake tables and a stubbed presigner: the route is pure
request → DynamoDB → presign, with no cross-service orchestration. Integration-only: whether S3
honours the presigned URL (AWS behaviour, not ours), and whether DynamoDB TTL has actually swept a
given row — which is exactly why the swept case is tested by an **empty grants table** rather than by
waiting on a real TTL. **No live payment, send or purchase is involved in any test.**

**Deployment: live path.** `wecare-secure-files` (live **34**). Customer-visible. §5 row 4c, §6.
**Re-read the alias, version and `RevisionId` immediately before acting** — the values in this
document are a 2026-10-09T04:32:07Z read and the fleet moved four times during the audit.

### F-10 — a native Vault purchase outside the 24-hour window is reported `VAULT_READY` having delivered nothing (MEDIUM, latent). PERMITTED.

**Evidence.** `flows/paid_vault.py`. With `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` absent — which
it is everywhere — the ready message is `wecare_share_pdf` (`:91`), **not** the
`wecare_default_download` template with the `https://wecare.digital/vault/?file={{1}}` button
(`:93-95`). `wecare_share_pdf` has an IMAGE header and carries no URL button and no file parameter.
The document itself is a separate, non-template message, gated on the 24-hour customer-service
window at `:103` (`0 <= time.time() - float(last or 0) < 86400`) **and** on
`deliverable == 'pdf'` **and** `deliveryKey`. If that condition is false the branch is skipped
entirely and execution falls to the review send at `:110-112`, returning **`VAULT_READY`**
(`:113`) — a success outcome for a purchase that delivered neither a link nor a file.

**Root-cause fix, part (a) — tell the truth in the outcome.** When the download-template flag is off
and the document branch was not taken, return a distinct `VAULT_DELIVERY_DEFERRED` instead of
`VAULT_READY`, and log `vault_delivery_deferred` with the `requestId` and a reason enum — **no
filename, no phone, no fileId**. That makes the paid-but-undelivered population findable, which is
the same posture
`secure-files:1381-1383` already takes by recording delivery outcomes on the grant for
`scripts/reconcile_file_deliveries.py` to sweep.

**The reason enum needs a stated evaluation order** (review 3 nit 13, accepted). `:103` is a single
compound condition — `file.get('deliverable') == 'pdf' and file.get('deliveryKey') and 0 <=
time.time() - float(last or 0) < 86400` — so when two sub-conditions fail together, "the reason" is
undefined and the regression test's `reason == 'window_closed'` assertion would be only accidentally
stable. **Binding order, first match wins:**

```python
if file.get('deliverable') != 'pdf':        reason = 'not_deliverable'
elif not file.get('deliveryKey'):           reason = 'no_delivery_key'
else:                                       reason = 'window_closed'
```

1. `not_deliverable` — 2. `no_delivery_key` — 3. `window_closed`.

The order mirrors `:103`'s own left-to-right evaluation, so the reported reason is always the
*first* clause that actually failed, and it degrades usefully: the two file-shape reasons are
permanent data problems needing a fix, while `window_closed` is a timing problem that a re-send can
resolve. Reporting a permanent problem as a timing one would send an operator down the wrong path.
`window_closed` is last because it is the only one that can be true while the file is perfectly
deliverable.

The review send at `:110-112` still happens: the customer did buy something, and suppressing the
review nudge would hide the problem further. The *outcome* is what changes.

**Root-cause fix, part (b) — make the coupling a documented precondition, not a discovery.** Record
in `docs/whatsapp/native-catalog-release-status.md` that opening
`WHATSAPP_CATALOG_SERVICES_ENABLED` for Vault **requires** `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED`
in the same change, because `wecare_share_pdf` carries no link. This is added to §5 item 8's
dependency list rather than left to be found after the first live purchase. Note the staging posture
is otherwise coherent and must not be disturbed: `catalog_service_checkout.meta_ready:91-106`
already refuses native checkout unless `wecare_default_download` is `APPROVED` with that exact
button (`:98-101`), so readiness is proven before the flag can open — readiness and *use* are simply
decoupled today, and only readiness is true.

**Regression test (fails before the fix).**
`tests/test_paid_vault_deferred_delivery.py::test_a_paid_vault_purchase_outside_the_window_is_not_reported_ready`
— `deliverable: 'pdf'`, `deliveryKey` set, `contact['lastInboundMessageAt']` 25 hours old, flag
absent; assert the outcome is `VAULT_DELIVERY_DEFERRED`, that **exactly one** template send
occurred (the share template) plus the review send, that **no** document message was sent, and that
`vault_delivery_deferred` was logged with `reason == 'window_closed'` and no filename. Today it
returns `VAULT_READY`. With the order above this assertion is now **deterministic rather than
accidental**: the fixture sets `deliverable: 'pdf'` and a `deliveryKey`, so clauses 1 and 2 pass and
`window_closed` is the only reachable reason.

Plus `test_a_purchase_inside_the_window_is_still_ready` as the sensitivity proof, and two cheap cases
pinning the order so it cannot drift — `reason == 'not_deliverable'` for `deliverable: 'docx'` with a
**stale** window (proving the file-shape reason wins over the timing one), and
`reason == 'no_delivery_key'` for `deliverable: 'pdf'` with `deliveryKey` absent and a stale window.

**Deployment: gated path.** `flows/paid_vault.py` ships in `wecare-whatsapp-business-api`, but this
arm is reachable only behind `WHATSAPP_CATALOG_SERVICES_ENABLED`. Code + tests only; **the deploy
rides with item 8 (STOP)**, so there is no cloud state to restore. Note it edits a file the parallel
session is actively changing (`87859dbc`, `4a3c4251`, `e9e377ce` all touched it) — so it inherits
**O11**.

### F-11 — live `WHATSAPP_LINK_TTL_SECONDS=21600` is silently clamped to 900 (LOW, config). OWNER CONFIRM.

**Evidence.** `core/secure-files/handler.py:218`:

```python
WHATSAPP_LINK_TTL = max(60, min(900, int(os.environ.get("WHATSAPP_LINK_TTL_SECONDS", "900"))))
```

Live `wecare-secure-files` v34, read 2026-10-09T04:39:21Z: `WHATSAPP_LINK_TTL_SECONDS=21600`.
`max(60, min(900, 21600))` = **900**. Behaviour is safe — the clamp is the `724dcc38` hardening and
is doing exactly its job — but an operator reading the environment would conclude the bearer window
is **six hours** when it is **fifteen minutes**, a 23× discrepancy between stated configuration and
actual behaviour on a security-relevant value.

**Root-cause fix.** Set `WHATSAPP_LINK_TTL_SECONDS=900` so the environment states its effective
value. **Do not touch the clamp at `:218`** — removing it is what the stale value is protecting
against.

**This is a production environment write, so it is `A3_PRODUCTION` and needs OWNER CONFIRM**, and
`scripts/set_lambda_env_flag.py` publishes a version and moves the `live` alias itself (`:146-148`)
unless `--no-publish` is passed — so it is a deploy, not a configuration tweak. Run bare first (dry
run is the default), read the printed delta and the `preserving N var(s)` line, confirm the `LOST`
line is absent, then `--apply`. §6 carries the rollback row.

**Regression test (passes today — it is a guard, not a repair).**
`tests/test_secure_files_link_ttl.py::test_the_whatsapp_link_ttl_is_clamped_to_fifteen_minutes` —
set `WHATSAPP_LINK_TTL_SECONDS=21600`, reload the module, assert the constant resolves to `900`;
and a second case asserting a value below 60 resolves to `60`. This pins the clamp against a future
change that "fixes" the env/behaviour mismatch by removing the clamp instead of the stale value —
which is the wrong half to delete.

### Explicitly NOT doing

- Not creating, mutating or probing any Meta or Razorpay payment configuration. Answer **F** was
  closed by two inert GETs performed by another session plus a source diff — no mutation.
- Not creating or publishing any Flow, including the hub Flow designed in `outputs/`.
- Not enabling `WHATSAPP_CATALOG_SERVICES_ENABLED`, `WIX_WRITEBACK_ENABLED`,
  `WIX_ECOM_WRITE_CONFIRMED`, `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED`,
  `SECURE_FILES_PAYMENT_ENABLED` or `DROPDOCS_ATTACH_ENABLED`. Not opening
  `META_CATALOG_SYNC_ENABLED` or closing `META_CATALOG_SYNC_FORCE_OUT_OF_STOCK`.
- Not deleting any catalog, product, order, customer, file or payment record. The old-catalog
  cleanup deliverable is an **inventory** (§3), not a deletion.
- Not sending any live WhatsApp message. Not simulating a purchase or a webhook and calling it
  verification. Not capturing or refunding. The only authorized QA recipient remains
  `+918100640044`; the business sender `+919330994400` is never used as a customer identity.
- Not running ads or creating spend.
- **No Wix product, variant, price or media is modified to manufacture a webhook delivery.**
  (Review 2 finding 7. The only on-demand way to produce a genuinely webhook-driven sync run is to
  mutate a live Wix product; §5 item 3a uses the handler's own write-free `inspect` arm instead.)
- **Not lengthening any download, upload, grant or link TTL.** F-9 adds re-issuability; the bearer
  window stays at 60 seconds, and F-11 corrects the *stated* value downwards to match the enforced
  one rather than raising the enforced one.
- **Not removing the `max(60, min(900, …))` clamp at `secure-files:218`**, nor the `consumed` flag
  written at `:1427`, nor the single-use `_redeem` semantics at `:1428-1431`. F-9 adds an
  owner-authenticated path beside them; it does not relax them.
- Not implementing the `Menu`/`Help` interactive-list arm. It was scheduled without a specification
  in revision 2 and is **removed from §5** (review 2 finding 8); it stays a recommendation in
  `outputs/whatsapp-customer-service-architecture.md` §2.
- Not weakening any signature check, auth check, ownership check, IAM policy or isolation control.
  `razorpay-webhook/handler.py` `_verify_signature` (fail-closed on a missing secret, fail-closed on
  a missing header, `hmac.compare_digest`, and a mismatch log carrying only `bodyLen`) stays exactly
  as it is. `require_auth` at `messaging/whatsapp-business-api/handler.py:6034` stays, and
  `AUTH_SKIP_PATHS` keeps its single member.
- Not reverting, reworking or "cleaning up" the parallel session's four commits or nine releases.
  Where this plan disagrees with them it says so and stops at **O11**.

---

## 3. Old-catalog deletion inventory (deliverable, not an action)

Before any permanent deletion is even proposed, the following must be enumerated for each candidate
catalog (`1088514403989109`, `1607047307067517`, and `1457045652952851` if it is **not** confirmed
canonical). **Every row is a read.**

A new complication: `1607047307067517` returns **Graph 100 / subcode 33**, which means it may
**already be deleted**. An inventory of a possibly-deleted object is still required — if it was
deleted, the question becomes what referenced it and is now dangling, which is the same inventory
read from the other direction.

| Dimension | Source of truth | Status |
|---|---|---|
| Owning business and asset assignments | Meta Business Settings | **Blocked on O1** |
| Whether `1607047307067517` exists at all | Business Settings → Assets → Catalogues | **Blocked on O1** — this is the deletion-vs-permission question |
| Connected WABAs | `GET /{waba}/product_catalogs` | Blocked on O1 |
| Connected datasets / pixels | Events Manager | Blocked on O1 / P2 |
| Product sets, Shops, carts | Commerce Manager | Blocked on O1 |
| Live ad sets referencing the catalog | Ads Manager | Blocked on O1; **no ads may be created or run** |
| Open WhatsApp carts holding a `product_retailer_id` | `MessagesTable` / cart rows | **Readable now** |
| Order history referencing retailer ids | `OrderTable`, `WixOrderIds` | **Readable now** |
| Foreign (hand-made) items the sync must never touch | the sync logs already report them: `foreignRetailerIds: ["WD-APPREVIEW-TEST"]` | **Readable now, 1 known** |
| Items present in `1457045652952851` | `GET /1457045652952851/products` | **Read: HTTP 200, empty.** So nothing has been migrated in |

Two standing constraints the design fixes in place.

**First, `meta_catalog_sync.diff` cannot emit a delete.** A vanished Wix variant becomes
`availability: out of stock`, never a deletion (guarantee declared in the `diff` docstring at `meta_catalog_sync.py:562-567`, enforced by the retire loop at `:606-620`, which only ever appends `availability: out of stock`), because a
customer's in-flight WhatsApp cart holds a `product_retailer_id` and a missing item fails at
checkout rather than at browse time. That is a structural guarantee and must survive any cleanup.

**Second, do not delete the active source while a recurring writer still targets it.**
`service-rollout/README.md` §3 says so, and the Wix webhook is still firing
(`/aws/lambda/wecare-wix-catalog-webhook`, streams through 2026-10-09). Note that the writer's
*target* has moved to `1457045652952851`, so the old catalog no longer has a live writer — which
removes one objection to its eventual cleanup but does not authorize it.

---

## 4. WhatsApp-first customer service hub

This section's content lives in **three** companion deliverables under `outputs/` (corrected from
revision 1's "two" — review finding 12):

1. **`outputs/whatsapp-customer-service-architecture.md`** — scope-extension **D4**, carrying **D5**
   (profile privacy decision) and **D6** (`WD_Orders_v1` screens and per-order action gating)
   inside it, as `SCOPE-EXTENSION-whatsapp-hub.md:39-59` requires. Created revision 2.
   **Revision 3 adds §6, "Vault order + download message sequence"** (owner requirement): both
   delivery paths side by side, every message with its guard, the identity re-verification table,
   the real TTL constants against the live environment, the ownership-before-presign chain, the
   delay/expiry analysis, the Wix→AWS→Meta availability projection, and the **V-1 / V-2 / V-3** GAP
   register with smallest-safe-changes and failing-test specs. **F-9, F-10 and F-11 are the
   executable form of that register**; answers **P4** carries the evidence.
2. **`outputs/website-to-whatsapp-migration-matrix.md`** — **D3**, the nine-column migration matrix
   (`:25`), the WhatsApp entry-point inventory, and the per-experience destination summary.
3. **`outputs/whatsapp-payment-state-machine.md`** — **D7**, the full ENTRY → PAYMENT_PENDING path
   and all fourteen branches (`:348` carries the consolidated GAP list), each with its authoritative
   record, retry rule, customer-facing message, whether a new reference is allowed, whether payment
   is resendable, whether the customer is charged again, the reconciliation action and the
   idempotency key.

It is design and feasibility only: **no Flow is created or published, and no existing Flow is
modified.** The verdict is **mostly WhatsApp-native with secure web fallbacks — not fully native**,
for four structural reasons (authentication cannot move; documents and full addresses must stay off
the thread; the 24-hour window and template approval are provider-controlled; four of six service
doors are not natively available). **No website functionality is recommended for removal.**
Embedded Flow-payment is **not supported and not claimed**. Full reasoning, with `file:line`
citations, is in deliverable 1.

Note conflict **C12**: the parallel session published documents with the same three names under
`docs/execution/xcodex-20261009/`. Both sets exist and their conclusions are compatible. **F-8**
item 8 records which is canonical so neither is deleted as a duplicate.

---

## 5. Execution order

Sequenced so nothing customer-visible moves before the owner authorizes, and so the shared-package
items land after the single-function one.

**Authorization column** (review finding 3). No surviving steering file grants standing
authorization: `.kiro/steering/*` was deleted in `af7858fa`, an ancestor of `origin/stack`, and
`AGENTS.md` is absent — both confirmed absent from the worktree.
`docs/execution/change-authority-matrix.md:1154` defines `A3_PRODUCTION` as requiring "Explicit
owner approval for the exact target **and** rollback, immediately before acting". Historical rows
log "owner blanket" / "standing grant" for single-Lambda deploys (`:1183`, `:1184`), but **the
document that granted that is deleted, so the grant is historical.** Therefore every production step
below is owner-confirmed.

> **Which owner item gates which production step** (review 3 finding 12). Two distinct items were
> being used interchangeably, which is the exact failure the owner/engineering separation exists to
> prevent — an owner approving "the deploys" could not tell whether a production *invoke* was
> included.
>
> | Item | Scope | §5 rows it gates |
> |---|---|---|
> | **O10** | "authorize or refuse this audit's **deploys**" — code shipped to a live alias | **2, 4b-i, 4b-ii, 4c, 7** |
> | **O13** | "authorize or refuse the single **production inspect invoke**" of `wecare-meta-catalog-sync:live` (`design.md` §5 item 3a) | **3a only** |
>
> O13 is narrower and separately refusable: the owner may authorize every deploy and still refuse the
> invoke, or the reverse. **Row 3a cites O13 and never O10**, and O10 never covers an invoke.
> Definitions are in `answers.md` **U**; §7 names both.

| # | Item | Depends on | Scope | Customer-visible | Authorization |
|---|---|---|---|---|---|
| 0 | **Re-fetch, then rebase onto the then-current `origin/stack`** (`061b6e77` at this writing, 1 ahead / 12 behind); **re-derive every citation used by the commits below**; capture the focused + whole-suite baseline (**157 / 10394**) | — | local | No | `A1_LOCAL` — none needed |
| 1 | **F-1** code + 5 tests | 0 | single function, no shared module | No | `A1_LOCAL` for the commit |
| 2 | **Deploy F-1** to `wecare-meta-catalog-sync` only | 1 | production alias move | No | **OWNER CONFIRM (O10)** |
| 3a | Invoke `wecare-meta-catalog-sync:live` **once** with `{"inspect": true, "source": "audit"}`; read `reason`, `graphStatus`, `counts`. **A production Lambda invoke, not a read** — but it constructs no write (`handler.py:565-572`, which returns before `_batch_requests` is reachable) | 2 | **production invoke**, no write constructed | No | **OWNER CONFIRM (O13)** — the invoke item, *not* O10 |
| 3b | **Await** a naturally-occurring Wix-webhook invocation and read the same fields from CloudWatch. **Note: no webhook has fired since 2026-10-09T00:24:18Z** (§1.1), so this may not arrive; it is not a substitute for 3a | 2 | read-only | No | `A0_READ` |
| 4a | **F-3** (`catalog_services.py:94`), **F-4** gated sites (`catalog_services.py:55`, `checkout/handler.py:3080`) | 0 | **gated** behind `WHATSAPP_CATALOG_SERVICES_ENABLED` | No — latent | `A1_LOCAL`; **not deployed** — rides with item 8 (STOP) |
| **4b-i** | **F-2** (guarded webhook arm), **F-5** (all six sites) | 0; after item 2 | **LIVE money path.** Targets `wecare-razorpay-webhook`, `wecare-invoice-engine` — **neither touched by the parallel session**, so no O11 dependency | **YES** | `A1_LOCAL` for commits; **OWNER CONFIRM (O10)** per function for any deploy |
| **4b-ii** | **F-4** live sites (`paid_vault.py:69`, `paid_submit_request.py:90`, `:142`), **F-6** (`list_orders` + `has_prior_order` + call site) | 0; after item 2; **O11**; **v89-vs-source certification by package extraction** | **LIVE.** Targets `wecare-whatsapp-business-api` — the contested function | **YES** | `A1_LOCAL` for commits; **OWNER CONFIRM (O10)**, and **blocked** until O11 and the certification clear |
| **4c-read** | **F-9 population count** (`A0_READ`): two `dynamodb scan --select COUNT` calls on `DownloadGrantsTable` — `paid AND consumed AND attribute_not_exists(expiresAt)` (durable native grants) and the same without the `expiresAt` clause. **Prerequisite of 4c's route half**; justifies or demotes it | 0 | read-only, no mutation | No | `A0_READ` |
| **4c** | **F-9** (V-1, the Vault re-issue gap) + **F-10** (V-2(a), deferred-delivery outcome). **Two separable halves:** (i) the copy correction at **both** `:1459-1460` and `:1224-1225`, which ships regardless of the count; (ii) the re-issue route, which ships only if **4c-read** returns ≥ 1 durable grant, else defers behind item 8 | 0; **4c-read** for half (ii) | **LIVE** (`wecare-secure-files`) and latent (`paid_vault.py`) | **YES** for F-9 | `A1_LOCAL` for commits; **OWNER CONFIRM (O10)** for any deploy |
| 5 | **F-8** documentation reconciliation | 3a (**O13**) or 3b | docs only | No | `A1_LOCAL` |
| 6 | §3 deletion **inventory** — the rows readable now; the rest stays blocked | — | read-only | No | `A0_READ` |
| 7 | **F-11** (V-3): set `WHATSAPP_LINK_TTL_SECONDS=900` so the env states its effective value. **Run `set_lambda_env_flag.py --no-publish`, then publish and move the alias manually with `--revision-id`** — see the mechanism note below; the script's own alias move cannot satisfy the concurrency rule | — | **production env write + publish + alias move** | No (behaviour unchanged — already clamped) | **OWNER CONFIRM (O10)** |
| 8 | Enable native checkout | **O1, O2, O3, F-2, F-3, F-9, F-10, O4, O5, O11, O12** | live | **YES** | **STOP** |
| 9 | Enable Wix writeback | **O6 + 8** | live | **YES** | **STOP** |
| — | **F-7** remaining (CAPI dataset half) | **O1 + O3 + O11** | live | **YES** | **STOP** |

> **Item 8's `F-9` prerequisite means F-9 *including* the `:1224-1225` copy site.** Opening
> `SECURE_FILES_PAYMENT_ENABLED` is the event that makes `_redeem_after_reconcile` reachable
> (`_reconcile_grant` returns False while the flag is off, `:1156-1157`). If only `:1459-1460` were
> corrected, item 8 would open the gate onto the identical "pay again" sentence at `:1225` with F-9
> recorded as satisfied. Both sites are in scope for row 4c half (i); item 8 stays **STOP**.

**Three scheduling defects review 2 found in this table, all fixed above.**

*Finding 4 — 4b's real prerequisites were missing.* §7 declares the v88-vs-source certification "a
prerequisite for any change to that function", and §6 marks that function "Blocked on O11", but §5
row 4b named neither. A planner executing the table would have put the deploy to the owner without
the adjudication the design calls mandatory. Fixed by splitting on the blocker, as the review
suggested: **4b-i** is the money path and has no O11 dependency (answers **D** confirms neither
`wecare-razorpay-webhook` nor `wecare-invoice-engine` was touched by the parallel session, and both
show live SHA == `$LATEST` SHA at 04:37:14Z); **4b-ii** is the contested function and waits. The
money-path fixes are the more urgent half, so this ordering is also the right one on merit. Note
the certification target is now **v89**, not v88 — the alias moved again.

*Finding 7 — item 3 was an ambiguous action mis-classified as a read.* "Trigger-or-await" was two
actions with different risk under one row, and `A0_READ` was wrong for either, since
`change-authority-matrix.md:1154` classes production Lambda action as `A3_PRODUCTION`. Worse, the
*mechanism* was unstated, and the only way to produce a genuinely webhook-driven run on demand is
to **mutate a live Wix product**, which the row's "read-only" scope concealed. Split into **3a**
(production invoke, owner-confirmed, provably write-free at `handler.py:565-572`) and **3b**
(genuinely read-only, and now known to be unreliable because the webhook has stopped firing). The
prohibition is added to "Explicitly NOT doing".

*Finding 8 — item 7 was scheduled executable work with no fix specification.* The old row 7
(a `Menu`/`Help` interactive-list arm) had no F-item, no root cause, no test, no rollback row and no
target function, while its authorization cell both ordered "OWNER CONFIRM" and disclaimed "design
only in this phase". **Removed from §5.** The recommendation lives in
`outputs/whatsapp-customer-service-architecture.md` §2 "Reuse before creation", which is where a
design-phase recommendation belongs. It is not promoted to an F-item, because
`SCOPE-EXTENSION-whatsapp-hub.md` scopes this phase to design and the arm would alter live keyword
routing. The new row 7 is F-11, which does have the full contract.

**Item 4b-i is the one review 1 correctly flagged.** Revision 1 classified it "No (all latent)" with
"no cloud state to restore". That was wrong: **F-5** edits the captured-payment path in
`wecare-razorpay-webhook` and `wecare-invoice-engine` with no flag anywhere; **F-6** edits
`paid_submit_request.list_orders`, consumed by the live paid Submit Request Flow at
`flows/paid_submit_request.py:32` (and `prepare_and_send` only *branches* on
`nativeCatalogService` at `:108`, it does not require the native flag); **F-4**'s
`paid_vault.py:69` and `paid_submit_request.py:90`, `:142` are on the live paid-service path.

**Ordering constraint, binding.** Items 4a and 4b add a helper to
`shared/lambda_utils/customer_auth.py` (F-4) and change `shared/lambda_utils/ecommerce/paid_submit_request.py`
(F-6) and `order_keys` usage (F-5). Those are **shared-package** changes. An unscoped deploy taken
after them would republish the fleet — `change-authority-matrix.md:1458` (table **row** 231) records one shared
`lambda_utils` change producing "57 updated, 3 unchanged, 0 failed, publisher moved **53** aliases".
So **F-1 deploys alone, first, with no `lambda_utils` delta in the tree**, and every later deploy
names its function explicitly. `scripts/deploy_all_lambdas.py` and `scripts/snapstart_publish.py`
are fleet-wide and **must not be used for any item here**.

**Concurrency constraint, binding.** Another session is deploying the same functions right now:
between two reads seven minutes apart, `wecare-meta-catalog-sync` live moved 6 → 7 and `wecare-whatsapp-business-api` live moved 87 → 88 — and by 04:32:07Z it was **89**, with `wecare-secure-files` at **34**. Four observed fleet movements inside one audit. So every alias move must: (i) re-read
`get-alias` immediately before acting; (ii) pass `--revision-id` with the just-captured value so a
concurrent move fails the call rather than being silently overwritten; (iii) verify with an
independent `get-alias` read afterwards. Never move an alias blindly, and never restore an older
version from a stale record.

**Reconciling that rule with item 7's mechanism** (review 3 finding 11). The rule and the chosen
script contradicted each other. `scripts/set_lambda_env_flag.py` publishes and moves the alias
**without** `RevisionId`, re-derived at `061b6e77`:

```
git grep -n "update_alias\|publish_version\|no-publish" origin/stack -- scripts/set_lambda_env_flag.py
```

```python
    published = None
    if before[name]["live"] and not args.no_publish:        # :145
        published = lam.publish_version(FunctionName=name)["Version"]   # :146
        lam.update_alias(FunctionName=name, Name="live",                # :147
                         FunctionVersion=published)                     # :148  <- no RevisionId
```

So the one item scheduled under the rule could not satisfy it — on a function the audit records as
having moved live 31 → 34 during the audit.

> **Resolution, binding on item 7: take the conditional route.** The script already has the flag that
> makes this possible — `--no-publish` at `:71`, tested at `:145`. Run it with `--no-publish` so it
> performs **only** the environment write (keeping its snapshot-before-write and post-write LOST
> check, which are the reasons to use it at all), then do the publish and the alias move by hand:
>
> 1. `get-alias` → capture `FunctionVersion` **and** `RevisionId` (this is the pre-change rollback
>    record §6 requires).
> 2. `set_lambda_env_flag.py --set WHATSAPP_LINK_TTL_SECONDS=900 --no-publish --apply` — env only, no
>    version published, alias untouched.
> 3. `publish-version` → note the new version.
> 4. `update-alias --revision-id <the RevisionId from step 1>` — **fails loudly if the parallel
>    session moved the alias in between**, which is the entire point.
> 5. An **independent** `get-alias` read-back confirming the new `FunctionVersion` and a changed
>    `RevisionId`.
>
> One extra command versus the script's built-in path, and the alias move becomes conditional. The
> alternative — an explicit owner-visible exception recording that the move is unconditional, with
> `live` and `RevisionId` captured immediately before and re-read immediately after — is **rejected**
> while a conditional route exists at the cost of one command. An unconditional move during a known
> concurrent deployment is precisely the failure the rule was written for, and "we wrote the old
> value down first" detects the clash only after it has already overwritten the other session.
>
> This applies to **every** alias move in §5, not just item 7: no item may use the script's internal
> publish/alias path while the parallel session is active.

Commits stay small and scoped: one commit per F-item, tests in the same commit as the fix, no
unrelated repairs bundled. Before any push, re-fetch and integrate `origin/stack` safely; no force
push; no broad `git add`.

---

## 6. Rollback

One row per affected function, with the pre-change `live` version and `RevisionId` to capture
**first** (review 1 finding 1). **All values re-read 2026-10-09T04:32:07Z** and they **must be
re-read immediately before acting** — the fleet moved four times during this audit.

**Authoritative alias capture, 2026-10-09T04:32:07Z** (and `$LATEST` SHA compared at 04:37:14Z):

| Function | `live` | `RevisionId` | live SHA vs `$LATEST` | Movement during the audit |
|---|---|---|---|---|
| `wecare-whatsapp-business-api` | **89** | `766722c7-05d8-4664-ab37-5be8c38d9f57` | **SAME** | 79 → 87 → 88 → **89** |
| `wecare-secure-files` | **34** | `01e8e9ef-f514-4829-9dc5-7299321465ab` | **SAME** | 31 → **34** |
| `wecare-meta-catalog-sync` | **7** | `dc895968-c89d-4a3b-9da3-2e366fb1465f` | **SAME** | 6 → **7** |
| `wecare-checkout` | 41 | `10b82920-f493-4e19-acdf-5200899a9ce5` | SAME | 40 → **41** |
| `wecare-razorpay-webhook` | 56 | `06eb2a78-f73d-4dd8-ab8d-efd4c2f9ef07` | SAME | unchanged |
| `wecare-invoice-engine` | 49 | `460d1d6f-b0fb-4fcc-a85d-b4d9b5a7bfe8` | SAME | unchanged |
| `wecare-outbound-whatsapp` | 56 | `6307da00-d3c1-48ef-be5a-02ba740c36a3` | SAME | unchanged |
| `wecare-inbound-whatsapp` | 92 | `54c18149-cef0-4ea2-b6be-ac7d784bf80f` | SAME | unchanged |
| `wecare-messages-read` | 29 | `a3e12e61-34e5-45ac-b285-8f4a6e3e6153` | — | unchanged |
| `wecare-wix-catalog-webhook` | 9 | `f24b0e2b-762a-4cf6-9951-9ca7fdb459fc` | — | unchanged |

**`live` SHA equals `$LATEST` SHA on all eight functions checked.** So there is no pending
unpublished package anywhere in scope at this read — which retires conflict **C13** again, for the
second time in two revisions. It became true, then false, then true. Re-check it rather than citing
this line.

| Change | Function | Pre-change `live` | `RevisionId` to capture | Rollback |
|---|---|---|---|---|
| F-1 | `wecare-meta-catalog-sync` | **7** (was 6 seven minutes earlier) | `dc895968-c89d-4a3b-9da3-2e366fb1465f` | `aws lambda update-alias --function-name wecare-meta-catalog-sync --name live --function-version 7 --revision-id <captured>`, verified by an **independent** `get-alias` read, not the command's exit code. **Also capture the env**: v7 sets `META_CATALOG_ID=1457045652952851`, `ENABLED=false`, `DRY_RUN=true`, `FORCE_OUT_OF_STOCK=true`. A published version freezes its environment, so reverting to v6 would silently revert the target to the unreadable `1607047307067517`. |
| F-2, F-5 (item 4b-i) | `wecare-razorpay-webhook` | **56** | `06eb2a78-f73d-4dd8-ab8d-efd4c2f9ef07` | alias move back to 56, conditional on the captured revision, independently read back |
| F-5 (item 4b-i) | `wecare-invoice-engine` | **49** | `460d1d6f-b0fb-4fcc-a85d-b4d9b5a7bfe8` | alias move back to 49, same contract |
| F-4 (live sites), F-6 (item **4b-ii**) | `wecare-whatsapp-business-api` | **89** (79 → 87 → 88 → 89 during this audit) | `766722c7-05d8-4664-ab37-5be8c38d9f57` (04:32:07Z) | alias move back to the captured version, same contract. **Additional hazard:** v86–v88 are uncertified against source and live is **ahead** of source on the outbound delivery contract (the parallel session's AUD-018), so a rollback could remove behaviour that session shipped. **Blocked on O11.** |
| F-4 (gated site) | `wecare-checkout` | **41** | `10b82920-f493-4e19-acdf-5200899a9ce5` | **NOT SCHEDULED — rides with item 8, which is STOP** (review 2 finding 13). Row retained only so the target is known; **re-read before any future move.** |
| **F-9** (V-1 Vault re-issue) | `wecare-secure-files` | **34** | `01e8e9ef-f514-4829-9dc5-7299321465ab` | alias move back to 34, conditional on the captured revision, independently read back. **Also capture the env**: `DOWNLOAD_URL_TTL_SECONDS=60`, `WHATSAPP_LINK_TTL_SECONDS=21600`, `GRANT_TTL_SECONDS=1800`, `SECURE_FILES_PAYMENT_ENABLED=false`, `DROPDOCS_ATTACH_ENABLED=false` — a published version freezes its environment |
| **F-10** (V-2 deferred outcome) | — | — | — | code-only, gated; **not deployed** — rides with item 8 (STOP). `git revert` of the single commit |
| **F-11** (V-3 TTL env) | `wecare-secure-files` | **34** | `01e8e9ef-f514-4829-9dc5-7299321465ab` | `set_lambda_env_flag.py` publishes and moves the alias, so rollback is **both** the alias move back to 34 **and** restoring `WHATSAPP_LINK_TTL_SECONDS=21600`. Behaviour is identical either way (the clamp makes both resolve to 900), so this rollback is cosmetic — which is the point: the change is safe |
| F-3, F-4 gated, code-only items not deployed | — | — | — | `git revert` of the single scoped commit. No cloud state to restore **because they are not deployed** — which is true only for item 4a, not 4b |
| **Any feature flag** | — | — | — | See below. |

**Flag rollback — what is actually executable** (review finding 10, accepted; revision 1 described
a guarantee that does not exist in this script).

`scripts/set_lambda_env_flag.py` accepts only `--set KEY=VALUE` and `--list KEY` (`:67-68`, `:70-71`) and writes `merged = dict(before[name]["env"]); merged[key] = value` (`:125`). **There
is no unset path**, so "unset the variable" cannot be performed with it. Its loss check is a
**post-write** read-back (`lost = sorted(set(before[name]["env"]) - set(after))`, `:134`), not
the pre-write refusal revision 1 described. The pre-write refusal revision 1 was thinking of belongs
to a **different, single-purpose script**, `scripts/set_standby_reply_flag.py`, which
`change-authority-matrix.md:246-254` documents and `tests/test_set_standby_reply_flag.py` pins.

So the executable procedure is:

> **Set the flag to `false` rather than removing it.** Every gate reads
> `os.environ.get(FLAG, 'false').lower() != 'true'` — `ecommerce/checkout/handler.py:3062`,
> `flows/catalog_services.py:42`, `flows/paid_vault.py:93` — so `false` and absent are equivalent.
> Run `python scripts/set_lambda_env_flag.py --functions <one function> --set FLAG=false` **bare**
> first (dry run is the default, `--apply` is required, `:110-114`), read the printed delta and the
> `preserving N var(s), live=V` line, then re-run with `--apply`. The script snapshots the prior
> environment to `SNAPSHOT_DIR` before writing (`:117-120`) and reports any lost key **after** the
> write, so confirm the `LOST` line is **absent** and the `N var(s) kept` count matches the
> snapshot. **Note the script also publishes a version and moves the `live` alias itself**
> (`:146-148`) unless `--no-publish` is passed — so it is a production deploy and needs
> **OWNER CONFIRM**. True key removal is unsupported and needs a separate reviewed change.
> `UpdateFunctionConfiguration` **replaces** the environment wholesale, so a partial
> `--environment` must never be hand-built.

---

## 7. Open items this design deliberately does not resolve

- **Deletion versus permission on `1607047307067517`.** The refusal is **Graph 100 / subcode 33**,
  which Meta makes deliberately ambiguous. **NOT VERIFIED — requires an owner read in Business
  Settings (O1).** F-1 does not resolve this and is no longer claimed to.
- **The effect of the v7 retarget — PARTIALLY RESOLVED this pass, and the resolution exposed F-1's
  real severity.** Revision 2 said "no sync invocation has occurred since 03:30:32Z". **No longer
  true.** Two v7 invocations ran, at 03:31:28.595Z and 04:03:42.687Z, and **both emitted no
  application log line at all** (§1.1) because `:531-534` and `:565-572` return before the only
  `logger.info` at `:577-594`. Their likely artifact is committed at
  `docs/whatsapp/service-flow-drafts/catalog-proposals-20261009.json` — an exact `:568-572` response
  shape showing `1457045652952851`, `counts.create: 4`, `existingItems: []`, `applied: 0`. **That
  the two invocations produced that file is INFERRED, not PROVEN**, and it is unprovable from
  telemetry precisely because of the defect F-1 fixes. §5 item **3a** is the next action and it is
  **OWNER CONFIRM (O13)**, not a read.
- **Whether the credential holds `items_batch` WRITE authority on `1457045652952851`.** It holds
  read (HTTP 200). No write has been attempted and none may be. **NOT VERIFIED.**
- **Whether a CAPI dataset id is a valid `fbq` browser target (T-1).** Events Manager read; owner.
  **NOT VERIFIED.** Compounded by the retarget: the targeted catalog is empty, so every
  catalog-matched event is currently unmatched regardless.
- **Submit Request Flow DRAFT-vs-PUBLISHED (C2).** Self-enforcing in `meta_ready`
  (`catalog_service_checkout.py:104`), so it blocks nothing silently, but the document conflict
  stands. **NOT VERIFIED.**
- **Wix product revision 4 vs 5 (C4).** Needs a credentialed Wix read. **NOT VERIFIED.**
- **NEW — whether `wecare_default_download` is still APPROVED with the exact
  `https://wecare.digital/vault/?file={{1}}` button (O12).** `catalog_service_checkout.meta_ready`
  enforces it at `:93-101`, so it is self-enforcing and blocks nothing silently — but nothing in
  this audit read Meta to confirm it, and **F-10 makes it a hard precondition of opening the native
  Vault gate.** Provider read, owner-performed. **NOT VERIFIED.**
- **NEW — the new Orders Flow `2167802357142172`.** The parallel session's checkpoint records an
  eight-screen **DRAFT** with zero validation errors (`native-catalog-release-status.md`, added by
  `e9e377ce`). It was not in this audit's known-state list and its screens were not audited. **Out
  of scope this pass; flagged so the planner does not treat it as covered.**
- **NEW — whether the two silent v7 invocations took the `batchHandle` arm (`:531-534`) or the
  `inspect` arm (`:565-572`).** Not determinable from telemetry. This *is* F-1.
- **O2 — one self-service save; linking is the expected outcome** (review 3 finding 5; this bullet
  previously carried the stale pessimistic reading and is corrected to match `answers.md` **J** and
  **U** word for word). `wa918100640044` has `checkoutCustomerId = null`, so `_claimable`
  (`auth/customer-profile/handler.py:143`, returning at `:168`) **is satisfied** and the save is
  expected to **link the existing contact row**. **INFERRED** — the audit did not execute the
  handler. The **failure mode** is a second contact row or a `409 CONTACT_IDENTITY_CONFLICT`
  (`:299`, `:309`, `:508-509`); **if that occurs**, the owner chooses between staff reconciliation
  and accepting the second row. The result is read after the save. **No agent writes
  `checkoutCustomerId`.** O2 is therefore a single owner action with one contingency, not a decision
  that must be made before acting.
- **O13 — the single production inspect invoke** (§5 row 3a). Distinct from O10 ("authorize or refuse
  this audit's deploys") and separately refusable: it authorizes exactly one
  `{"inspect": true, "source": "audit"}` invoke of `wecare-meta-catalog-sync:live`, which constructs
  no write (`handler.py:565-572` returns before `_batch_requests` is reachable). §5 row 5 depends on
  it (or on the unreliable 3b). Defined in `answers.md` **U**.
- **Whether live `wecare-whatsapp-business-api` v89 matches any committed source.** v86 is certified
  for five named functions with `allOtherChangesCertified: false`; **v87, v88 and now v89 are
  certified by nobody.** `live` SHA does equal `$LATEST` SHA at 04:37:14Z, which proves no
  *unpublished* drift but says nothing about whether the deployed package matches committed source.
  Re-establishing this needs a package extraction after rebasing, and it is a **prerequisite for any
  change to that function** — which gates F-4's live sites and F-6.
- **Workspace rendering of a real purchase row (S).** Needs **O2**, **O4** and **O7**. The backend
  behaviour is now read from source; only the rendered result is pending.
- **The two workspace-orders defects** found while answering **S**: the unfiltered `table.scan()`
  at `service_api.py:121` and the silent 200-row truncation at `:137-138`. Recorded in F-8
  item 10 as backlog, deliberately not fixed here — they are outside this audit's critical path and
  would widen the change surface on a function another session is deploying.

---

## 8. Responses to design review 2

Review 2's verdict was `CHANGES_REQUESTED` — 2 HIGH, 8 MEDIUM, 4 NIT, 10 blocking, with
`mustResolveBeforeAnyCode: [1, 2, 3, 7]`. **All fourteen are answered below: eleven addressed, two
rejected on reproducible evidence, one backlogged with a reason.** The review was a good one; its
HIGH finding 2 caught a change that would have replayed captured payments, and that alone justified
the cycle.

**One structural complication colours several responses.** `origin/stack` moved from `4e259800` to
`e9e377ce` between the review and this revision, and the review itself measured some citations at a
third tree (`53ed298e`, the main checkout). See §0. Where a correction was tree-dependent, this
revision re-derived at `e9e377ce` and says which tree each party was reading, with a reproducible
command, rather than asserting a winner.

| # | Sev | Finding | Response |
|---|---|---|---|
| 1 | HIGH | Citations into the two upstream-modified handlers are stale at the mandated rebase base | **ADDRESSED, and generalised.** §0 declares the base. All eleven listed citations re-derived at `e9e377ce` — where **four differ from the review's own corrections**, because the tree moved again. Anchor patterns added so they can be re-located mechanically. |
| 2 | HIGH | F-2 inserts an unguarded raising call on the live captured-payment path | **ADDRESSED IN FULL.** Guarded form specified with the table handle, the stated fail-open posture, the specific-exception rationale, and two new failure-branch tests. **This was the correct call and the most valuable finding in the review.** |
| 3 | MED | F-6's `order_choices` has two incompatible return shapes and is not implementable from its inputs | **ADDRESSED.** Two explicit decisions recorded: a plain `list`, and the rule applied inside `list_orders`' loop. Eligibility split into a new `has_prior_order`. Six tests, including `test_list_orders_returns_a_plain_list`. |
| 4 | MED | §5 row 4b omits the O11 + certification prerequisites | **ADDRESSED as the review suggested.** Split into **4b-i** (money path, no O11) and **4b-ii** (contested function, blocked on O11 + certification). Certification target corrected to **v89**. |
| 5 | MED | `change-authority-matrix.md` row numbers read as line numbers; `:1154`, `:231`, `:252-256` wrong | **REJECTED on the merits for `:1154`; partially accepted for the other two.** See below. |
| 6 | MED | The QA-recipient provenance claim is wrong and the gap is larger than stated | **ADDRESSED, and the review's own numbers updated.** See below. |
| 7 | MED | §5 item 3 is an ambiguous action mis-classified as a read, with an unstated Wix-mutation route | **ADDRESSED as the review suggested**, plus new evidence that **3b cannot be relied on at all**: no Wix webhook has fired since 00:24:18Z. |
| 8 | MED | §5 item 7 is scheduled executable work with no fix specification | **ADDRESSED — row removed.** Not promoted to an F-item; it would alter live keyword routing and this phase is design. The new row 7 is F-11, which carries the full contract. |
| 9 | MED | Answers F and G are closed on another session's unreproduced artifacts | **ADDRESSED, and G is now independently corroborated — but by a different and better route than the review prescribed.** See below. |
| 10 | MED | Nine further citation errors in files no upstream commit touched | **EIGHT ACCEPTED, ONE REJECTED.** All eight corrected. The retire-not-delete citation is defended. §8's over-broad claim is softened as asked. |
| 11 | NIT | `service_api.py` scan cited three inconsistent ways | **ACCEPTED.** `:121` in all three places. |
| 12 | NIT | The test baseline is pre-rebase and not comparable | **ACCEPTED and superseded by measurement**: 157 focused / 10394 whole-suite at `e9e377ce`. |
| 13 | NIT | §6 carries a rollback row for a deploy §5 does not schedule | **ACCEPTED.** Marked "NOT SCHEDULED — rides with item 8, which is STOP". |
| 14 | NIT | Residual range slips | **ACCEPTED**, all five adopted. |

### Detail on the four that are not a plain acceptance

**Finding 5 — rejected for `:1154`, which is the one cited five times.** The review corrected
`change-authority-matrix.md:1154` → `:1110` and reported verifying `:1110` verbatim. Both readings
are reproducible, at different commits:

```
git show 53ed298e:docs/execution/change-authority-matrix.md | grep -n 'Explicit owner approval' -> 1110
git show 4e259800:docs/execution/change-authority-matrix.md | grep -n 'Explicit owner approval' -> 1154
git show e9e377ce:docs/execution/change-authority-matrix.md | grep -n 'Explicit owner approval' -> 1154
```

The review states its method as checking "at **both** the worktree HEAD (`0425dce1`) and the rebase
base (`origin/stack` `4e259800`)". At `4e259800` the answer is `:1154`. The `:1110` value is the
**main checkout** `53ed298e`, which is a *third* tree and the one this audit's worktree was branched
from. So the finding is an artifact of tree confusion in the opposite direction from finding 1, and
**revision 2's `:1154` is correct at both the review's stated base and the current one.** Retained.

The other two pointers in the finding are **accepted in substance**, with values re-derived at
`e9e377ce`: the 53-alias sweep is at file line **`:1458`** (it is table **row** 231, which is where
revision 2's `:231` came from — the review's diagnosis of the row-vs-line confusion is exactly
right, only its corrected number was from the wrong tree), and `set_standby_reply_flag.py` is
documented at **`:246-254`**. The review's requested clarifying sentence is added to §0, because
the row-vs-line hazard is real even though this instance of it was mis-attributed.

**Finding 6 — accepted, and the review's own figures have moved.** Re-verified at `e9e377ce`:

```
git grep -n "918100640044" origin/stack -- docs/whatsapp/service-rollout/   ->  (no matches)
git grep -l "918100640044" origin/stack | wc -l                            ->  90
```

So the review is **right**: the full E.164 appears in **neither** `README.md` nor
`continue-prompt.txt`. Only the suffix survives, and both lines have now moved **twice** — the
review read `:46`, revision 3 derived `:57`/`:5` at `e9e377ce`, and at `4fe31824` they are
**`README.md:59`** ("owner authorized personal number **ending 0044** for customer QA") and
**`continue-prompt.txt:9`** ("The owner supplied QA customer number **ending 0044**"). The count is
now **90** tracked files (84 at the review, 88 at `e9e377ce`).

**Review 3 finding 3 is accepted in full, and the two halves are separated here, because conflating
them is what let the gap persist through a whole cycle:**

| Half | State |
|---|---|
| (a) Retract the false provenance sentence in `answers.md` | **DONE.** Revision 3 said it was "corrected in `answers.md`" while the sentence was still there — review 3 caught that. `answers.md` "Binding authority re-established" now carries the suffix-only finding, the four re-derived commands, the 90-file count and a pointer to F-8 item 6 |
| (b) Create `docs/execution/qa-recipient.md` | **NOT DONE — imperative, scheduled as §5 row 5.** `git ls-tree -r --name-only origin/stack \| grep -i qa-recipient` → no match. F-8 item 6 states it in the imperative and labels it unapplied, so the past-tense reading that made "nobody will look again" true cannot recur |

The review is right that this is safety-relevant: ninety scattered copies and no document of record
is the worst of both arrangements, and **a four-digit suffix cannot authorize a send** — it cannot be
compared mechanically, cannot distinguish two numbers sharing a suffix, and cannot be audited after
the fact. This is the authority chain for the only rule governing live WhatsApp sends.

**Finding 9 — accepted, and G is now corroborated independently, though not the way the review
specified.** The review asked the investigate step to re-run three inert reads itself:
`/wa-business/payment-config/check`, `/wa-business/payment-config/list`, and
`GET /1607047307067517/products`. **Two of the three are not available to this agent, and saying so
plainly is more useful than appearing to comply:**

- The two `/wa-business/...` routes sit behind `require_auth` (`handler.py:6034`, before any route
  dispatch, with `AUTH_SKIP_PATHS` holding a single unrelated member). This agent has no Cognito
  session and must not create one.
- The Graph read needs the Meta token, which lives in Secrets Manager. **The binding rules forbid
  `get-secret-value`/`batch-get-secret-value` in any spelling.** So an independent Graph read is
  *structurally* unavailable, not merely inconvenient. Any claim to have performed one should be
  disbelieved.

So the re-tagging the review asked for is applied, verbatim in intent: **F** → "PROVEN BY ANOTHER
SESSION'S STRUCTURED ARTIFACT (v86, 2 inert GETs) — not reproduced this pass", **G1** → "REPORTED BY
ANOTHER SESSION (prose summary, no structured capture) — NOT INDEPENDENTLY VERIFIED".

**But a better route existed and was taken: the system's own telemetry, which is read-only and
needs no credential.** §1.1 has the capture. It yields three things the review could not have known
were available:

1. **Fifteen `read_failed` records**, 00:21:01Z → 02:13:22Z, all `catalogId 1607047307067517`,
   independently read from CloudWatch at 04:33:06Z. The failure is real, sustained, and first-party.
2. **Two successful `inspect`-arm invocations of the retargeted v7**, whose committed response
   artifact (`catalog-proposals-20261009.json`) shows `catalogId 1457045652952851`, `readOnly: true`,
   `counts.create: 4`, `existingItems: []`, `applied: 0`. That is the handler's own serialised
   return value — structured, not prose. It corroborates "old target unreadable, new target readable
   and empty" from first-party data.
3. **A worse defect than revision 2 described.** Those two invocations emitted **no application log
   line at all**, because `:531-534` and `:565-572` both return before the single `logger.info` at
   `:577-594`. The live sync has an unobservable success mode. **This is now F-1's primary
   justification and it is independent of O1.**

On the review's conditional — "the F-1 severity demotion holds only if the 100/33 result reproduces,
and F-1 returns to HIGH if it does not" — the honest answer is that **the 100/33 subcode was not
reproduced and cannot be by this agent.** What reproduced is the *failure* and the *asymmetry*. On
F-1's severity: the demotion is **withdrawn in substance**. F-1 is retained at MEDIUM *as a
diagnostic repair*, but §1.1 shows the diagnostic gap is wider than either revision thought, and
§5 keeps F-1 as items 1–2, before everything else. The practical scheduling is what the review
wanted; the label is less important than the ordering, and the ordering is unchanged.

**Finding 10 — eight of nine accepted; the retire-not-delete citation is defended.** Accepted and
corrected: `shared/.../paid_submit_request.py:96-97`; answers **O**'s `:82-84`, `:91-92`, `:93-95`,
`:100-103`; `src/config/services.ts:49`; `src/lib/metaCatalogAnalytics.ts:6-8` (and `:3-5` for the
comment); the F-1 test anchor, now anchored on the **name** `def run(` as the review asked rather
than on `:178-182`/`:180-184`.

**Rejected: the ninth.** Revision 2 cited `meta_catalog_sync.py:558-572` for the retire-not-delete
*structural guarantee*. The review said the logic is at `:606-620` and `:558` is merely the `def
diff(` line. Both are true and they are about different things:

```
:558-559  def diff(desired, existing) -> SyncPlan:
:562-567  "A VANISHED WIX VARIANT IS RETIRED, NEVER DELETED. ... There is no code path in this
           module that can produce a delete, which is a structural guarantee rather than a
           convention."
:606-620  the retire loop, which only ever appends {retailer_id, availability: OUT_OF_STOCK,
           product_name}
```

The *guarantee* is declared in the docstring at `:562-567`, inside the range revision 2 cited; the
*enforcement* is the loop at `:606-620`. §3 now cites **both**, which is strictly better than
either. The review's finding was reasonable and the resolution is additive, not a correction.

**And the requested softening, applied.** Revision 2's finding-13 table claimed "every citation was
re-derived". That claim was false and the review was right to say so. Revision 3 makes no such
claim. It states instead: **§0 declares one base; the citations load-bearing for a fix carry an
anchor pattern; and the planner is instructed in §5 item 0 to re-derive rather than trust this
document.** That is a weaker promise and a more useful one.

### What this revision adds that no review asked for

- **F-9 (HIGH, live), F-10, F-11** — the Vault order → download sequence, documented to the owner's
  revision-3 requirement and audited while being documented. F-9 is the only HIGH-severity finding
  in the audit that is reachable by a real customer on a live, unflagged path today.
- **§1.1's silent-arm finding**, which changes what F-1 is for.
- **The measured test baseline**, 157 / 10394 at `e9e377ce`.
- **Conflicts C14 (test-count drift) and C15 (the Wix webhook has stopped firing)**, both of which
  invalidate a statement revision 2 made.

### Gate criteria, re-assessed

Against review 2's five stated criteria.

| # | Criterion | Rev 2 | Rev 3 | Basis |
|---|---|---|---|---|
| 1 | Every answer A–U has concrete evidence | FAIL | **PASS** | E is now closed by committed source (`handler.py:6399-6404`) **and** a committed test; G is corroborated by a first-party CloudWatch read and the handler's own serialised `inspect` output; C/D re-captured at 04:32:07Z with `$LATEST` comparison; the test baseline is measured, not asserted |
| 2 | Each fix states root cause, smallest change, and a test that fails first | FAIL | **PASS** | F-2 rewritten with the guarded form and two failure-branch tests; F-6's two shape/placement decisions made explicitly with six tests; the unspecified row 7 removed; F-9/F-10/F-11 added with the full contract including per-condition error handling and input validation |
| 3 | Checked against the binding safety rules | PARTIAL | **PASS** | The one concealed mutation route (Wix product edit to force a webhook) is named and forbidden; item 3 reclassified from `A0_READ` to OWNER CONFIRM; F-9 argued as *strengthening* rather than relaxing ownership, with the forwarded-link defence shown to be untouched; no TTL lengthened; no gate opened; no payment object read, created or mutated; no secret value read — and §8 finding 9 states plainly which reads were **structurally unavailable** rather than implying they were done |
| 4 | Owner / provider / engineering separated | PASS | **PASS** | O1–O12, P1–P6, F-1–F-11; every production step is OWNER CONFIRM; items 8, 9 and F-7's remainder are STOP; F-11 is explicitly flagged as a deploy despite looking like a config tweak |
| 5 | No unverified historical claim carried as fact | FAIL | **PASS** | F and G1 re-tagged exactly as the review asked; the 100/33 subcode recorded as **not reproduced and not reproducible by this agent**; conflicts C14 and C15 added where revision 2's own statements went stale; §0 records that three different trees were in play and which party read which |

**Known residual risk, stated rather than hidden.** Every `file:line` in this document was derived at
**`061b6e77`**. `origin/stack` has moved on every check so far — including once more *during review
3* — and the fleet moved four times during the audit. **Several of these citations will be wrong by
the time anyone acts on them.** That is why §0 makes re-derivation a binding step rather than a
recommendation, why load-bearing citations carry anchor patterns, and why §6 requires every alias and
`RevisionId` to be re-read immediately before the move with `--revision-id` passed so a concurrent
move fails loudly instead of being overwritten.

---

## 9. Design review round 3 resolution

Review 3 verdict: `CHANGES_REQUESTED` — **3 HIGH / 9 MEDIUM / 4 NIT, 12 blocking**,
`mustResolveBeforeAnyCode: [1, 2, 3, 6, 7, 8, 9]`. **All 16 are resolved below.** The review was
accurate on 15 of 16; finding 1's premise was incomplete and the correction is stated as such with
evidence rather than as a disagreement.

**Base re-anchored first, before any finding was touched.** The review verified against `e9e377ce`;
`origin/stack` is now `061b6e77` — **1 ahead / 12 behind**. The base moved **twice** during this
resolution pass and **hop 2 changed code**. See §0 for the per-citation re-derivation; the summary is:
hop 1 (`e9e377ce`→`4fe31824`) was docs-and-outputs only; hop 2 (`4fe31824`→`061b6e77`) edited
`amplify/functions/messaging/whatsapp-business-api/handler.py` and
`tests/test_audit_payment_diagnostic.py`, shifting every citation in that handler below line 321 by
**+12** and below 6106 by **+13**. Two document citations in the QA-send authority chain also moved.

```
git diff e9e377ce..4fe31824 --stat      -> 12 files, +2121/-1,  docs/outputs only
git diff 4fe31824..origin/stack --stat  -> 11 files, +1784/-13, INCLUDES CODE
git diff e9e377ce..origin/stack --stat  -> 16 files, +3905/-14, INCLUDES CODE
```

**139 load-bearing citations were individually re-verified** at `061b6e77` with
`git grep -n '<pattern>' origin/stack -- '<path>'` and a per-line `git show origin/stack:<path> | sed -n '<n>p'`
substring assertion. **All 139 reproduce; exactly 11 carried changed values** — the nine
`whatsapp-business-api/handler.py` re-derivations enumerated in §0's shift table, plus the two
document citations `README.md:59` and `continue-prompt.txt:9`. Each changed value is named in §0's
table or in the row below that uses it. (Revision 3 printed a second, smaller figure here against the
same set; it was a drafting artefact of an earlier partial pass and is **withdrawn** — the set size
is 139 and the changed-value count is 11. Set size and changed-value count are different quantities
and are stated separately from here on.)

| # | Sev | Finding | Resolution | Command / evidence |
|---|---|---|---|---|
| **1** | HIGH | F-9's "LIVE, reachable today" contradicted by `SECURE_FILES_PAYMENT_ENABLED=false` | **RESOLVED — kept HIGH, with the review's premise corrected and the read item added.** The flag is a *local* env read whose only four refusal sites are `:981`, `:1058`, `:1156`, `:1272`; **`_redeem` (`:1405`) is not among them**, the flag exists nowhere in `amplify/` outside that one file, and the native minter `vault_access.grant_access` runs in a **different Lambda** (`paid_vault.py:63`) reached via `handler.py:5996-6000` → `paid_submit_request.py:127-129` with **no payment gate**. So the native chain is open today. Added the `A0_READ` grant-count item as **§5 row 4c-read** and split row 4c into the copy fix (ships regardless) and the route (needs count ≥ 1, else demotes to MEDIUM-latent behind item 8) | `git grep -n "_payment_enabled\|SECURE_FILES_PAYMENT_ENABLED" origin/stack -- .../secure-files/handler.py`; `git grep -rn SECURE_FILES_PAYMENT_ENABLED origin/stack -- amplify scripts \| grep -v core/secure-files`; `git grep -n grant_access origin/stack -- amplify` |
| **2** | HIGH | F-9 re-issues from a TTL-swept row; record lifetime never analysed | **RESOLVED — option (b), entitlement from the durable FILE row. No TTL created, extended or touched.** Three origins, two lifetimes: `_create_order:1016` and `_reconcile_grant:1306` write `expiresAt = now + GRANT_TTL`; **native `vault_access.py:64-67` writes NO `expiresAt`** and is never swept. The two swept origins are exactly the two the flag refuses. `vault_access.py:71` writes `vaultAccessGrantId` + `vaultPaymentStatus='PAID'` onto `SecureFilesTable`, whose **TTL is DISABLED** (`check_data_model_drift.py:186-190`, the `SecureFilesTable` entry; the TTL sentence is on `:189`) against `DownloadGrantsTable`'s **ENABLED** (`:191-196`, the entry; the TTL sentence is on `:193-194`) — the same phrasing F-9.0's body uses, so the two no longer appear to disagree. **The cap and counter moved to the FILE row** so they cannot evaporate. Option (a) rejected: it is a TTL extension, which §5's rules forbid. Added `test_a_swept_grant_does_not_tell_a_paid_customer_to_pay_again` (fixture: file row `PAID`, **grants table empty**) | `git grep -n expiresAt origin/stack -- .../vault_access.py` → **no matches**; `git show origin/stack:scripts/check_data_model_drift.py \| sed -n '186,196p'` |
| **3** | HIGH | False QA-recipient provenance in `answers.md`; `design.md` §8 claims a correction never applied | **RESOLVED — both halves, separated so they cannot be conflated again.** (a) `answers.md` "Binding authority re-established" now **retracts** the "survives in README §9 and `continue-prompt.txt`" sentence and states the suffix-only finding with four commands, a pointer to **F-8 item 6**, the `+919330994400` exclusion and *"a suffix cannot authorize a send"*. (b) `design.md` §8 finding 6 and F-8 item 6 are now **imperative and explicitly labelled UNAPPLIED**, with a blockquote stating `docs/execution/qa-recipient.md` does not exist. **Both line numbers moved:** `README.md:57` → **`:59`**, `continue-prompt.txt:5` → **`:9`** (it moved in *both* upstream hops); count 88 → **90** | `git grep -n "918100640044" origin/stack -- docs/whatsapp/service-rollout/` → none; `git grep -l … \| wc -l` → 90; `git grep -n "0044" origin/stack -- <both files>` → 59, 9; `git ls-tree -r --name-only origin/stack \| grep -i qa-recipient` → none |
| **4** | MED | `answers.md` A, D, J, L still at revision-2 values | **RESOLVED — all four re-derived, plus the header softened.** **A**: base `061b6e77`, 1/12, merge base `53ed298e`, rebase target `061b6e77`, with both hops characterised — hop 1 docs-only, hop 2 code-changing. **D**: live **89** (was 88); **v87, v88 and v89 uncertified by anyone**; rebase target updated; tied to O11. **L**: the dangerous pair fixed — gate `:3062`, `NATIVE_SERVICE_ROLLOUT_DISABLED` **`:3063`**, `is_enabled()` `:3064`, `NATIVE_SERVICE_WRITEBACK_NOT_READY` **`:3065`**, `VERIFIED_CUSTOMER_REQUIRED` `:3078`, with a table naming **why `:3080`/`:3081` were the worst possible wrong lines** (Cognito `Filter` and the `verified_identity` call). **J**: `verified_identity` caller is **`:3081`** not `:3099`; `customer_orders.py:61` added as a **fourth caller revision 3 omitted** (four call sites; the fifth `git grep` match is the **definition** at `catalog_service_checkout.py:35`, not a caller); revision 3's claim that the paid flows call it is **false** (they use inline `len(users) != 1` at `paid_submit_request.py:91`, `:143`, `paid_vault.py:70`). Header now promises only what §0 promises | `git grep -n "NATIVE_SERVICE_ROLLOUT_DISABLED\|NATIVE_SERVICE_WRITEBACK_NOT_READY" origin/stack -- .../checkout/handler.py`; `git grep -n verified_identity origin/stack -- amplify` |
| **5** | MED | Answer J specifies O2 two incompatible ways | **RESOLVED — stale pessimistic block deleted; one statement, identical in three places.** `answers.md` **J**, `answers.md` **U** O2 row and `design.md` **§7** now all read: `checkoutCustomerId` is null so `_claimable` (`:143`, returning at `:168`) is satisfied and **linking is the expected outcome (INFERRED)**; a second row / `409 CONTACT_IDENTITY_CONFLICT` (`:299`, `:309`, `:508-509`) is the **failure mode**, at which point the owner chooses reconciliation; the result is read after the save; **no agent writes `checkoutCustomerId`**. Also corrected `_claimable` `:147-168` → **`:143-168`** and its docstring rules `:158-160` → **`:158-163`** | `git grep -n "def _claimable\|def _owned_contact\|CONTACT_IDENTITY_CONFLICT" origin/stack -- .../customer-profile/handler.py` |
| **6** | MED | F-5's test unbuildable — `ClientError` always renders its code | **RESOLVED — test-local subclass specified, plus the invariant.** `botocore` interpolates `Error.Code` into `MSG_TEMPLATE`, so the "fails before fix" half was impossible. Now specifies `class OpaqueConditionalFailure(ClientError)` overriding `__str__` while preserving `.response`, with both premise assertions written out, and a two-row table for the two halves (the mirror half needs no subclass). **Binding invariant added:** every site branches on `error.response['Error']['Code']` via `order_keys.is_conditional_failure` (`:177`) and **never** on `str(error)`. No production subclass introduced | `git grep -n "def is_conditional_failure" origin/stack -- .../order_keys.py` → 177 |
| **7** | MED | F-2 test 5 contradicts the behaviour F-2 verified | **RESOLVED — renamed and re-specified.** `_read_row:342-347` wraps **every** storage exception into `OrderIdentityUnavailable`, so a bare `KeyError` arrives caught and the test would have failed *after* the fix, on the plan's most dangerous change. Now **`test_an_error_outside_the_storage_wrapper_is_not_swallowed`**, with two injection points outside `_read_row`'s `try` in a table: **preferred** — monkeypatch `dynamodb.Table` to raise `KeyError` (evaluated before `resolve_payment_reference` is entered); **alternative** — stub a non-mapping truthy return so `payref.get` raises `AttributeError`. Added the note that the narrow catch is **total over storage by construction** and deliberately not over programming errors | `git show origin/stack:.../order_keys.py \| sed -n '335,350p'` |
| **8** | MED | F-9 mis-names the auth envelope as `require_auth` | **RESOLVED — envelope stated exactly, with a BINDING blockquote.** A five-row table pins `:1827` (customer block opens), **`:1828` `_customer_identity(event)`**, `:1829-1830` `401 "Verification required"`, `:1836` `_redeem`, **`:1840` `require_auth(event, "Operator")` = the ADMIN surface.** The route is hosted at **`:1827-1836`** and must **not** go in or after the `:1840` block, and no staff/role check may be added to a customer route. Backed by the handler's own docstring at `:40-44` (*"`require_auth` … validates against the **admin** pool"*) and the inline warning at `:1806-1807` (*"would let a customer token fall through to role Viewer"*). Corrected in `outputs` §6.5 too | `git grep -n "_customer_identity\|require_auth" origin/stack -- .../secure-files/handler.py` |
| **9** | MED | `design.md` F-9 and `outputs` §6.5 disagree; §6.5's cap condition can never succeed | **RESOLVED — `design.md` made binding, §6.5's alternative deleted, full update given.** One shape: **`GET /files/{id}/download?reissue=1`** (no `/download/reissue` route). Full single conditional update written out with `attribute_exists(fileId) AND #s = :active AND ownerCustomerId = :owner AND ownerPhone = :p AND vaultPaymentStatus = :paid AND vaultAccessGrantId = :gid AND (attribute_not_exists(reissueCount) OR reissueCount < :cap)` and `ADD reissueCount :one`. **The `OR attribute_not_exists` arm is marked mandatory** — a bare `reissueCount < :cap` is false on a fresh row, so the first re-issue would always have been refused. `ConditionalCheckFailedException` mapped **by re-reading** (`ConsistentRead=True`), first match wins: at cap → `GRANT_REISSUE_EXHAUSTED`; not consumed → **fall through to `_redeem`**; else → `_not_registered`. §6.5 now opens with a subordination blockquote | `git show origin/stack:.../secure-files/handler.py \| sed -n '1424,1441p'` (`consumed = :false` on `:1430`, `ConditionExpression=(` spanning `:1428-1431`) |
| **10** | MED | F-4 inventory incomplete: seven sites, not six | **RESOLVED — seven stated (two guarded, five unguarded), BOTH regexes converted.** `git grep` returns **7**. The seventh, `customer_orders.py:60`, is guarded by its own inline `re.fullmatch` — **at `:57`, not `:58` as the review stated** (`:58` is the `raise`); corrected rather than carried forward. The five-unguarded fix set is unchanged. **Both** inline regexes are now converted to `customer_auth.is_cognito_subject` (`customer_commands.py:80` *and* `customer_orders.py:57`) so the literal pattern appears **exactly once in the tree** — converting only one would have left the stated goal unmet. Added **`test_customer_orders_still_refuses_a_malformed_subject`** asserting `CustomerNotAuthorized` **raised** with the `cognito-idp` double never invoked, alongside the `customer_commands` pin. Deployment widened: both guarded files are live-path | `git grep -n "Filter='sub" origin/stack -- amplify` → 7; `git grep -n is_cognito_subject origin/stack -- amplify` → **absent**; `git grep -n re.fullmatch origin/stack -- .../customer_orders.py` → 57 |
| **11** | MED | §5's `--revision-id` rule vs item 7's script, which moves the alias with no `RevisionId` | **RESOLVED — the conditional route, written into row 7 and generalised to every alias move.** `set_lambda_env_flag.py:147-148` calls `update_alias` with **no `RevisionId`**, so the one item scheduled under the rule could not satisfy it. Row 7 now runs the script with **`--no-publish`** (`:71`, tested at `:145`) for the env write only — keeping its snapshot-before-write and LOST check — then performs publish and a **conditional** alias move manually: `get-alias` capture → env write → `publish-version` → `update-alias --revision-id <captured>` → **independent** `get-alias` read-back. Five numbered steps, one extra command. The unconditional-move exception is **rejected** with the reason stated (it detects a clash only after overwriting the other session). Applies to **every** §5 alias move while the parallel session is active | `git grep -n "update_alias\|publish_version\|no-publish" origin/stack -- scripts/set_lambda_env_flag.py` |
| **12** | MED | The one production invoke gated by O10 in `design.md`, O13 in `answers.md` | **RESOLVED — O13 everywhere 3a appears; O10 reserved for deploys.** A scope table added to §5 above the execution table: **O10 = deploys, rows 2, 4b-i, 4b-ii, 4c, 7**; **O13 = the production inspect invoke, row 3a only**, separately refusable. Row 3a now reads `OWNER CONFIRM (O13)`, row 5's dependency reads `3a (O13)`, **§7 gained an O13 bullet**, the §7 v7-invocation bullet now says `OWNER CONFIRM (O13)`, and `answers.md` **U** narrows O10's scope explicitly and states that row 3a, row 5's dependency and §7 all cite O13 | `design.md` §5 / §7 vs `answers.md` **U** O10/O13 rows |
| **13** | NIT | F-10's reason enum not derivable | **RESOLVED.** `:103` is one compound condition, so the reason was non-deterministic. Order stated as code, first match wins: **`not_deliverable` → `no_delivery_key` → `window_closed`**, mirroring `:103`'s left-to-right evaluation, with the rationale that the two file-shape reasons are permanent data problems while `window_closed` is a timing problem a re-send fixes. The existing test's `reason == 'window_closed'` is now **deterministic rather than accidental**, and two cheap order-pinning cases were added | `git show origin/stack:.../paid_vault.py \| sed -n '103p'` |
| **14** | NIT | Off-by-one `metaCatalogAnalytics.ts` ranges in T and P4 | **RESOLVED.** Content-id builder `:11-12` → **`:12-13`** (`:11` is `PURCHASE_KEY`); `Purchase` `:102` → **`:101`** (three sites); the pixel comment `:2-4` → **`:3-5`**; `catalogContentId` `:64` and `META_DATASET_ID`/`META_PIXEL_ID` `:6`/`:8` confirmed correct as cited | `git grep -n "META_DATASET_ID\|catalogContentId\|Purchase" origin/stack -- src/lib/metaCatalogAnalytics.ts` |
| **15** | NIT | F-1's `caplog` mechanism has no precedent in the file | **RESOLVED.** Added the mechanism paragraph: the handler binds `logger = get_logger(__name__)` at `meta-catalog-sync/handler.py:57`, and `lambda_utils.logging.get_logger` (`:17`) returns a **plain stdlib logger** — `logging.getLogger` (`:22`) + `setLevel` (`:24`), **no handler added, `propagate` never disabled** — so records reach root and `caplog` captures them. States that this file has **no existing `caplog` precedent** (0 matches), gives the robust `logger=handler_module.logger.name` form rather than a hardcoded guess, and warns that `get_logger` applies `LOG_LEVEL` at `setLevel` | `git grep -c caplog origin/stack -- tests/test_meta_catalog_sync_handler.py` → none; `git show origin/stack:.../logging.py \| sed -n '14,32p'` |
| **16** | NIT | F-6's snippet needs two imports, not one | **RESOLVED, and switched to the house helper.** `paid_submit_request.py` imports only `hashlib` `:8`, `hmac` `:9`, `secrets` `:10`, `time` `:11`, `typing.Any` `:12`, `order_keys`/`store` `:13` — **no `logger`, no `json`**. Now specifies `from lambda_utils.logging import get_logger, log_event` plus `logger = get_logger(__name__)`, and replaces the hand-rolled `json.dumps` with `log_event(logger, 'order_choices_unnumbered', skipped=skipped)` (`logging.py:28`), which **drops the `json` import entirely**. Notes `get_logger` is import-safe on a paid path, and that `**kwargs` makes the count-only PII posture explicit at the call site | `git show origin/stack:.../paid_submit_request.py \| sed -n '1,30p'` |

### Gate criteria, re-assessed against review 3's five

| # | Criterion | Rev 3 | **Rev 3.1** | Basis |
|---|---|---|---|---|
| 1 | Every answer A–U backed by concrete evidence | FAIL | **PASS** | A, D, J, L re-derived at `061b6e77`; the `:3080`/`:3081` gate citations — review 3's named worst case — replaced with `:3062`/`:3063`/`:3065` and a table explaining the hazard; the header no longer claims more than §0 promises (findings 4, 14) |
| 2 | Each fix names root cause, smallest change, and a test that fails first | FAIL | **PASS** | All three unbuildable tests fixed: F-5's opaque `ClientError` subclass, F-2's injection moved outside `_read_row`'s `try` and renamed, F-9's cap condition given its mandatory `OR attribute_not_exists` arm. F-9's root cause now includes the full TTL analysis and the three-origin lifetime table (findings 2, 6, 7, 9) |
| 3 | Checked against the binding safety rules | PARTIAL | **PASS** | F-9's envelope corrected to `_customer_identity` at `:1828` with a BINDING prohibition on the `:1840` Operator block; §5's `--revision-id` rule reconciled with item 7 via `--no-publish` + manual conditional move + independent read-back, generalised to every alias move. **No TTL lengthened** — finding 2 resolved by reading the already-durable FILE row rather than extending any expiry (findings 8, 11) |
| 4 | Owner / provider / engineering separated | PARTIAL | **PASS** | O10 (deploys: rows 2, 4b-i, 4b-ii, 4c, 7) and O13 (the row-3a invoke) now disjoint and cited consistently in §5, §7 and `answers.md` **U**; answer J's two incompatible O2 instructions collapsed to one statement repeated identically in three places (findings 5, 12) |
| 5 | No unverified historical claim carried forward as fact | FAIL | **PASS** | The QA-provenance claim is retracted in `answers.md` and the F-8 item is marked **imperative and unapplied**, with the two shifted line numbers as the evidence that §0's re-derivation rule is not theoretical. F-9's reachability is now argued from the four `_payment_enabled` sites and the ungated native path rather than asserted (findings 1, 3) |

### What survives unresolved, stated plainly

**Nothing among the 16 is left open.** Two items are *conditional* by design rather than unresolved:

1. **F-9's re-issue route is contingent on §5 row 4c-read.** If the durable-grant count is `0`, F-9
   demotes to MEDIUM-latent and only the copy correction — at **both** `:1459-1460` and
   `:1224-1225` — ships now. That is finding 1's
   own offered alternative, and the branch is written into the table rather than decided here —
   because the count is a live read this design phase does not perform.
2. **`docs/execution/qa-recipient.md` does not exist yet.** Finding 3(b) is resolved in the sense
   the review asked for — the claim is now imperative rather than falsely past-tense — but the file
   itself is work owed, scheduled as §5 row 5. This is stated in three places so it cannot be read
   as done.

**Unchanged by this revision, deliberately:** every gate stays **CLOSED**; items 8, 9 and F-7's
remainder stay **STOP**; every production step stays **OWNER CONFIRM**; the owner/provider/engineering
separation (O-, P-, F-items) is intact; and nothing weakens auth, ownership, signature verification,
IAM or isolation. F-9 and F-4 both *add* checks — F-9 to the existing `_owned_active_file` chokepoint,
F-4 to five sites that have none — and F-9's two sensitivity tests exist precisely to fail if it ever
becomes a loosening.

---

## 10. Design review round 4 resolution

Review 4 was a **focused confirmation** of round 3's sixteen findings, not a fresh review. It
**independently confirmed all 16 as RESOLVED** at `061b6e77` and re-confirmed every safety invariant
as holding. The verdict is `CHANGES_REQUESTED` solely because of residual **bookkeeping** defects
*inside the round-3 resolution write-up* — **1 HIGH, 3 MEDIUM, 4 NIT**, `mustResolveBeforeAnyCode:
[1, 3, 4]`. None of them is a defect in the analysis, in a fix, or in a control.

**Scope of this pass, stated as a limit.** Documentation-consistency only. **No finding was
re-opened, no analysis or fix content was changed, no severity was moved, no gate was opened and no
control was weakened.** Items **8**, **9** and **F-7's remainder** remain **STOP**; every production
step remains **OWNER CONFIRM**; every flag remains read-only.

**Base re-verified before editing, and it had not moved.**

```
git fetch origin && git rev-parse origin/stack  ->  061b6e77c8a352d174c713834af0ca7d61b027b9
```

Because the base is unchanged from the one §0 declares, **no citation needed re-deriving in this
pass**. Every value the review cited was reproduced at `061b6e77` before the corresponding edit was
made; the commands are in each row below.

| # | Sev | Item | How it was fixed | Command used to verify |
|---|---|---|---|---|
| **1** | HIGH | §9's re-anchor paragraph contradicted §0: claimed one docs-only intervening commit and "no code citation moved", and pasted the hop-1 `--stat` against the full range | **FIXED with the reviewer's exact replacement.** §9's opening now states the base moved **twice** and that **hop 2 changed code**, names `whatsapp-business-api/handler.py` and `tests/test_audit_payment_diagnostic.py` and the `+12`/`+13` shifts, and **points at §0 for the per-citation re-derivation instead of restating it**. The command block now records all **three** diffs with their true figures. §0 was already correct and is unchanged | `git diff e9e377ce..4fe31824 --stat` → 12 files, +2121/-1; `git diff 4fe31824..origin/stack --stat` → 11 files, +1784/-13; `git diff e9e377ce..origin/stack --stat` → **16 files, +3905/-14**; `git diff e9e377ce..origin/stack --name-only \| grep -E '^(amplify\|scripts\|src\|tests)/'` → the two code files; `git log --oneline e9e377ce..origin/stack` → **two** commits (`4fe31824`, `061b6e77`) |
| **2** | MED | §9 claimed "139 … re-verified … **All 97 pass**" — the two counts cannot both be the set size | **FIXED, one number, the two concepts kept separate.** Now: **139** citations re-verified, **all 139 reproduce, exactly 11 carried changed values** — the nine handler re-derivations in §0's shift table plus `README.md:59` and `continue-prompt.txt:9`. The `97` is **explicitly withdrawn** as a drafting artefact of an earlier partial pass rather than given an invented provenance, and the set-size-vs-changed-count distinction is now stated. Auditable because the 11 are enumerated, not asserted | `findings.md:125-126` independently records "**139 … all 139 pass**", corroborating 139 as the set size; the 11 changed values are each listed in §0's table or the §9 row that uses them |
| **3** | MED | `answers.md`'s QA-authority transcript recorded `continue-prompt.txt -> 7`, the intermediate `4fe31824` value, four lines above its own table's correct `:9` | **FIXED.** Transcript line now reads `-> 9` with the drift annotated inline: `# :5 at e9e377ce, :7 at 4fe31824 — moved in BOTH hops`. The block now agrees with its own table, with `design.md` §0 and with §9 finding 3 | `git grep -n "0044" origin/stack -- docs/whatsapp/service-rollout/continue-prompt.txt` → **9**; same at `4fe31824` → 7, at `e9e377ce` → 5; `git show origin/stack:…/continue-prompt.txt \| sed -n '7p'` → *"HISTORICAL CONTINUATION BELOW — overridden by the current checkpoint above:"* (a different line entirely, which is why this mattered for F-8 item 6's prose edit) |
| **4** | MED | F-9's copy fix was scoped to `:1459-1460` only; the identical string exists again at `:1224-1225`, while F-9's invariant table claimed the single-site fix **owns** the invariant | **FIXED on the completeness claim, in all four places, with the reachability reasoning the reviewer prescribed.** The copy half now covers **both** `:1459-1460` (`_redeem`) **and** `:1224-1225` (`_redeem_after_reconcile`) in: F-9's copy bullet, F-9's invariant-table row (which now **names both ranges**), §5 row **4c** half (i), §5 row 4c-read's `0`-case, §9's conditional-items list, `findings.md`'s BLOCKED item 1, and `outputs/…architecture.md` §6.5's V-1 copy bullet **and** V-1 severity row. Each states that `:1225` is **not live-reachable today** — `_redeem_after_reconcile` is entered only when `_reconcile_grant` returns True (`:1453-1454`), and that function returns False while `_payment_enabled()` is false (`:1156-1157`) — **but becomes reachable the moment §5 item 8 opens the flag, and item 8 lists F-9 as satisfied**. §5 item 8 additionally carries a blockquote recording that its `F-9` prerequisite means F-9 **including** `:1224-1225`, so the gate cannot be opened onto the defect with F-9 marked done. The reviewer's "explicit exception" alternative was **not** taken: the exception would have left F-9 failing its own invariant at the gate opening, and correcting a duplicated string is strictly smaller than documenting why it was left wrong. **No behaviour, route, condition or control changed — this is copy text at two sites instead of one** | `git grep -n 'Please pay again' origin/stack -- amplify/functions/core/secure-files/handler.py` → **1225, 1460**; `git show origin/stack:…/secure-files/handler.py \| sed -n '1191p;1220p;1224,1225p'` → `def _redeem_after_reconcile(` / `except ClientError:` / the identical copy; `\| sed -n '1150,1158p'` → `if not _payment_enabled(): return False` at `:1156-1157`; `\| sed -n '1452,1455p'` → `if _reconcile_grant(...)` `:1453` → `return _redeem_after_reconcile(...)` `:1454` |
| **5** | NIT | §0's nine-row shift table labelled **both** value columns `061b6e77`, and row 1 showed `:5996-6000 \| :5996-6000 \| +12` — arithmetically impossible | **FIXED.** Header relabelled `\| Citation \| At 4fe31824 \| **At 061b6e77** \| Shift \|`; row 1's pre-hop cell set to **`:5984-5988`**. The table can now sanity-check itself. The other eight rows already carried correct pre-hop values and are unchanged | `git grep -n preparePaidSubmitRequest 4fe31824 -- …/whatsapp-business-api/handler.py` → **5984**; same at `origin/stack` → **5996** (difference **+12**, matching the stated shift) |
| **6** | NIT | `answers.md` **J** called `customer_orders.py:61` "a fifth caller" in a four-row table; the fifth `git grep` match is the **definition** | **FIXED in both places.** `answers.md` **J** now says "**a fourth caller** revision 3 omitted entirely" and carries the caption **"Four call sites; the definition is at `catalog_service_checkout.py:35`."** `design.md` §9 finding 4's row mirrors the wording and names the definition explicitly. The line number `:61` was right and is unchanged | `git grep -n verified_identity origin/stack -- amplify` → **5** matches: four call sites (`checkout/handler.py:3081`, `flows/catalog_services.py:56`, `flows/customer_commands.py:84`, `flows/customer_orders.py:61`) + the `def` at `shared/lambda_utils/ecommerce/catalog_service_checkout.py:35` |
| **7** | NIT | `answers.md` **J** labelled the `_claimable` re-derivation "Re-verified at `e9e377ce`" under a header declaring `061b6e77` | **FIXED, label only.** Now "Re-verified at `061b6e77` (file untouched by both upstream hops, so these are unchanged since `e9e377ce`)". The values were already correct and **none was altered** | `git diff e9e377ce..origin/stack --name-only \| grep -c customer-profile` → **0** (untouched by either hop); `git grep -n "def _claimable\|def _owned_contact\|def _upsert_contact" origin/stack -- …/customer-profile/handler.py` → **143, 171, 280** as cited |
| **8** | NIT | The `DownloadGrantsTable` TTL citation differed between §9's finding-2 row (`:193-194`, and `:189-190` for `SecureFilesTable`) and F-9.0's body (`:191-196`) | **FIXED with the reviewer's second option — one phrasing, reused in both places**, so the entry range and the sentence line are both preserved rather than one being discarded: `:191-196` (the `DownloadGrantsTable` entry; the TTL sentence is on `:193-194`), and correspondingly `:186-190` for `SecureFilesTable` with its sentence on `:189`. Neither citation was misleading before; they now read identically | `git show origin/stack:scripts/check_data_model_drift.py \| sed -n '186,196p'` → `"SecureFilesTable":` `:186`, `TTL DISABLED` `:189`, `"DownloadGrantsTable":` `:191`, `TTL ENABLED on` `:193`, `` `expiresAt` `` `:194` |

> **A note on the item count.** The dispatching brief described "7 items (1 HIGH, 3 MEDIUM, 3 NIT)"
> and `findings[] ids 1-7`. The review's `findings` array actually holds **8** entries and its own
> `counts.nit` is **4**. Item **8** — the TTL-citation drift — is the same class of
> citation-consistency defect as items 5-7 and is non-blocking, so it was fixed in this pass rather
> than carried as a known inconsistency. Leaving it would have left §9 claiming to have corrected a
> citation that the section it summarises still stated the old way, which is precisely the
> §9-vs-body contradiction item 1 exists to eliminate.

### Round-4 gate re-assessment

| Check | Result | Basis |
|---|---|---|
| §0 and §9 agree on whether hop 2 moved code | **PASS** | Both now state hop 2 **DID** change code, in the same two files, with the same `+12`/`+13` shifts. §9 defers to §0 for the per-citation table rather than paraphrasing it, so the two cannot drift apart again (item 1) |
| No stale load-bearing citation remains | **PASS** | The four reviewer-identified stale values (`continue-prompt.txt:7`, §0 row 1's `:5996` pre-hop cell, the `e9e377ce` base label, the hop-1 `--stat`) are corrected and each was reproduced at `061b6e77` first (items 1, 3, 5, 7) |
| No internal contradiction remains | **PASS** | The 139/97 count, the fifth-vs-fourth caller ordinal, and the `:191-196`/`:193-194` TTL split are each stated one way in every place they appear (items 2, 6, 8) |
| Every fix's completeness claim is true | **PASS** | F-9 no longer claims a single-site copy change owns "a paid customer is never told to pay again"; both duplicate sites are in scope and item 8's prerequisite says so (item 4) |
| Controls unchanged | **PASS** | Gates **CLOSED**; items 8, 9, F-7-remainder **STOP**; production steps **OWNER CONFIRM**; no TTL touched; no payment object created or read; no live send; read-only AWS throughout this pass and no secret value read |

**Ready for the planner.** The substance was confirmed at round 4; this pass removed the write-up's
remaining bookkeeping contradictions. `design.md` F-9 remains **BINDING** over
`outputs/…architecture.md` §6.5, and §0 remains the single source of truth for every `file:line`.
