# Retired Razorpay merchant account purge — local `stack` reconciliation, 2026-10-02

Owner instruction, verbatim: *"keep acc_TTFSyolquKEZEy, purge acc_HDfub6wOfQybuH"* and *"remove old
from everywhere"*. This document records the **local `stack`** half of that purge and the evidence
for it, so a reviewer does not need to re-run anything.

## What this iteration actually had to fix

This is iteration 2. The review at `.agents/tasks/razorpay-account-purge-20261002/review.json`
returned `CHANGES_REQUESTED` with one blocking root cause: the purge was **absent from the reviewed
tree**. Commit `57f5b505` (a complete local purge) and `e61a49c4` (its full 11-path revert) cancel
exactly, so local `stack` still carried both retired identifiers in live Lambda source, both webhook
fixtures, the mismatch fixture, the spec, the dashboard component and — the dangerous one —
`docs/compatibility.md:80`, which asserted the retired account was *"strong — this is the account
that talks to us"* in a money-routing document.

The purge already exists on `origin/stack` (commits `863c6ebd` → `27a3fb5d` → `aa4b1c99`), which is
14 commits ahead. The review's prescribed unblock was a merge.

### Why this landed as a content adoption rather than a merge

`git merge origin/stack` is **blocked by a cross-session seam**, not by policy: `origin/stack`
rewrites `.kiro/steering/META-BETA-REQUEST-EMAIL.md:49,51`, and that file is modified-unstaged in the
working tree by another session (an unrelated 2026-09-30 MCC/PayU editor's note near line 6). Git
refuses a merge that would overwrite a dirty tracked file, and the alternatives — stash, reset,
committing another session's work — are all prohibited here.

So the purge was landed by adopting `origin/stack`'s **byte-identical** content for the nine
authorized paths:

```
git checkout origin/stack -- <the 9 paths below>
```

Byte-identical matters and is the whole point of the method. The first attempt (`57f5b505`) was
reverted precisely because two sessions had independently rewritten the same prose, which turned the
later merge into eight manual conflict resolutions. When both sides of a merge hold *identical*
content for a hunk, git auto-resolves it regardless of the base. Measured before and after:
`git merge-tree --write-tree origin/stack HEAD` returns a bare tree oid with no conflict section
both times, so **the orchestrator's eventual merge stays clean** and this iteration does not
recreate the condition that caused the revert.

Two facts were verified before adopting, so this is a purge and nothing else rode along:

- `git diff --stat c6fd53dc HEAD -- <the 9 paths>` was **empty** — local was identical to the merge
  base for every target, i.e. no local work was clobbered.
- `git diff --stat HEAD origin/stack -- <the 9 paths>` was **50 insertions / 20 deletions across 9
  files**, all of it Razorpay content. No unrelated commit from another session was imported.

## Paths changed

| Path | Class | Change |
|---|---|---|
| `docs/compatibility.md` | A | Retired row no longer claims authority; reads *"Retired; do not use for new payments"*. `acc_TTFSyolquKEZEy` row is now the authoritative one |
| `amplify/functions/messaging/whatsapp-business-api/handler.py` | A | Comment only, line ~3165. Placeholders replace the pair. **No code behaviour change; the no-hardcoded-fallback design is intact** |
| `src/pages/workspace/dashboard/system-architecture.tsx` | A | Retired-comment id replaced. Displayed values remain `acc_TTFSyolquKEZEy` / `wecaredigitalbh511413.rzp@rxairtel` |
| `amplify/functions/shared/lambda_utils/payment_readiness.py` | B | `STALE` → `RETIRED`, past tense; placeholder replaces the id. Module behaviour unchanged |
| `.kiro/specs/<retired commerce spec>/tasks.md` (spec since deleted) | E | Past tense, placeholders |
| `tests/test_payment_status.py` | D | Both fixtures → `acc_RETIRED_FIXTURE` |
| `tests/test_payment_readiness.py` | D | Mismatch fixture → `acc_RETIRED_FIXTURE`; test **kept** |
| `amplify/functions/messaging/partner-onboarding/handler.py` | — | Webhook-secret fallback removed |
| `tests/test_partner_razorpay_canonical_secret.py` | — | **New.** Pins the canonical-secret behaviour |

## Remaining `acc_HDfub6wOfQybuH` hits, with per-hit justification

```
.agents/tasks/deep-audit-20261001b.md                             Class C — immutable task history
.agents/tasks/phase-a-checkout-reconcile-2026-10-01/phase-a-plan.md  Class C
.agents/tasks/section68-current-state-audit-20261001.md           Class C
docs/execution/change-authority-matrix.md                         Class C — immutable audit trail
docs/execution/checkout-consolidation-findings-20261001.md        Class C
docs/execution/phase-04d-payment-audit.md                         Class C
.kiro/steering/META-BETA-REQUEST-EMAIL.md:49,51                   CROSS-SESSION SEAM — declined
```

Remaining `wecaredigital83.rzp@icici` hits are the same Class C set minus `phase-04d`. Every
non-Class-C occurrence of both identifiers is gone from tracked source **except the declined seam**.

### The one declined cross-session seam

`.kiro/steering/META-BETA-REQUEST-EMAIL.md` is modified-unstaged by another session and the brief is
explicit: do not edit a dirty target, report it. `origin/stack` already replaces both ids there with
`[retired Razorpay account]`, and the other session's edit is in a different region of the file, so
once that session commits, the merge resolves both edits without conflict. **No action is needed from
this session; the orchestrator should simply not be surprised that two identifiers survive in that
one file until the merge lands.**

## Class D — money-safety coverage impact

Preferred option taken: the guard **was kept**, not deleted. `test_a_mid_mismatch_blocks_payment`
still exists and still proves `RAZORPAY_MID_MISMATCH` fires; only the wrong-account fixture string
changed to the clearly-synthetic `acc_RETIRED_FIXTURE`. `MID = 'acc_TTFSyolquKEZEy'` remains the
authoritative constant.

**Coverage reduction, stated plainly:** the mismatch guard is no longer exercised against the
*literal* retired merchant id. It is exercised against a synthetic id instead. The property under
test — "a provider MID that is not the expected one blocks payment" — is unchanged, because the
guard compares for inequality and does not special-case any particular value. What is lost is the
narrow regression proof that *this specific* retired account would be refused if Razorpay ever
reported it again. That is a deliberate trade: the owner asked for the id removed from everywhere,
and keeping a real retired merchant id purely as a test literal is the kind of hit the purge exists
to eliminate.

`tests/test_payment_status.py` loses nothing measurable: no assertion in that file reads
`account_id`. The dedup keys are entity-id scoped and the Defect-2 regression proof asserts on key
*composition*, not on the account value.

## Partner-onboarding decision: fallback REMOVED, with a new test

```
before:  for secret_id in ('wecare/razorpay/api', 'wecare/razorpay-webhook'):
after:   for secret_id in ('wecare/razorpay/api',):
```

Removed rather than staged for owner gating, because it is provably **dead code from source alone**
and needed no credential verification:

1. `wecare/razorpay-webhook` holds exactly one field, `webhook_secret` — verified 2026-09-19 and
   recorded in the function's own docstring and in `whatsapp-payments-india-reference.md`.
2. The loop body returns only when `key_id` **and** `key_secret` are both non-empty.
3. So the second iteration could never satisfy the return condition. It always fell through to the
   same `return '', ''` the function now reaches directly.

Top-up credential loading is therefore unchanged in behaviour. `tests/test_partner_razorpay_canonical_secret.py`
pins it: it execs `_razorpay_creds` against a mocked client and asserts `get_secret_value` is called
**exactly once** with `SecretId='wecare/razorpay/api'`, on both the success and the failure path.
`wecare/razorpay-webhook` is retained — it is the signing secret for signature verification, not an
API credential, so its survival is not a missed purge target.

## VPA decision: deep link NOT touched

`payment_readiness.py` still records `wecaredigitalbh511413.rzp@rxairtel` as AUTHORITATIVE, and
`src/config/constants.ts:112` already holds exactly that value. There was no stale `@icici`
reference in `constants.ts` or in `src/pages/workspace/pay/link/` to remove, so **no edit was made to
the money-routing deep link** — correct under the brief's conditional, and matching `origin/stack`,
which also left it untouched. `rxairtel` remains byte-for-byte preserved per `bw-crm.md`: it is a
Razorpay payment-address suffix, not an Airtel messaging dependency.

## Verification — what was run, and the real results

```
$ .venv/bin/python -m pytest tests/ -q
6501 passed, 1 skipped, 5 xfailed in 56.34s          exit 0

$ npm run typecheck          (tsc --noEmit)
exit 0, no output

$ .venv/bin/python -m pytest tests/test_payment_readiness.py tests/test_payment_status.py \
      tests/test_partner_razorpay_canonical_secret.py -q
113 passed in 0.50s

$ .venv/bin/python -m pytest tests/test_payment_readiness.py::test_a_mid_mismatch_blocks_payment -q
1 passed in 0.11s
```

**Zero failures.** No pre-existing failure from another session remains: the `_variables`
manifest self-count assertion that `57f5b505`'s withdrawn evidence recorded as the single
pre-existing failure was fixed by `0bec35da` and the suite is now clean, so there is nothing to
exclude or attribute elsewhere.

```
$ git grep -l acc_HDfub6wOfQybuH          → 7 files, all Class C except the declined seam (listed above)
$ git grep -l 'wecaredigital83.rzp@icici' → 5 files, all Class C
$ git grep -n acc_RETIRED_FIXTURE         → tests/test_payment_readiness.py:23,79,82,84
                                            tests/test_payment_status.py:41,61
$ git diff origin/stack -- <the 9 paths>  → empty (byte-identical)
$ git merge-tree --write-tree origin/stack HEAD → bare tree oid, no conflict section
```

No Class C file was edited. `docs/execution/change-authority-matrix.md`,
`docs/execution/phase-04d-payment-audit.md`, `docs/execution/checkout-consolidation-findings-20261001.md`
and every `.agents/tasks/*.md` are byte-unchanged.

## Secret hygiene

No credential value appears in any edit, command, argv, log or logging expression. No
`secretsmanager get-secret-value` or `batch-get-secret-value` call was made in any spelling. The
merchant id and the UPI VPA are **non-secret identifiers** and may appear in source; the Razorpay key
pair is the secret and was never read, named by value, or touched. No money computation was altered —
integer paise arithmetic and the `payment_status` vocabulary are untouched by this change.

## Still required, and OWNER-GATED — do not run from this session

The live Lambda environment is the half of this purge that source cannot reach. Historical evidence
(`.agents/tasks/section68-current-state-audit-20261001.md:354`) records
`wecare-whatsapp-business-api` carrying `RAZORPAY_MID=acc_HDfub6wOfQybuH` and
`RAZORPAY_UPI_ID=wecaredigital83.rzp@icici`, served through `:live` at version 58.

The exact command, **described and not run**:

```
python scripts/set_lambda_env_flag.py --set RAZORPAY_MID=acc_TTFSyolquKEZEy \
    --functions wecare-whatsapp-business-api --apply
python scripts/set_lambda_env_flag.py --set RAZORPAY_UPI_ID=wecaredigitalbh511413.rzp@rxairtel \
    --functions wecare-whatsapp-business-api --apply
```

`set_lambda_env_flag.py` is **mandatory** here and a raw CLI call is not an acceptable substitute.
`aws lambda update-function-configuration --environment Variables={...}` **replaces the entire
variable map**, so writing one key the obvious way silently deletes the function's other ~15
variables — table names, secret pointers, phone-number ids, feature flags. It does not error; the
function just starts resolving defaults. That is the same replace-not-patch shape that wiped three
Cognito `CUSTOM_AUTH` triggers and opened self-signup on 2026-09-28. The helper reads, merges, writes
the whole map back, snapshots the before-state to disk, then publishes a version and moves the `live`
alias — the alias move being required because the HTTP API invokes `:live` and a `$LATEST` change does
not reach production (`lambda-snapstart-deploy.md`).

**Likely already done, and that needs independent confirmation rather than trust.**
`origin/stack`'s `docs/execution/razorpay-mid-vpa-purge-20261002.md` records
`wecare-whatsapp-business-api:live` moved to **version 60** with both environment values set to the
retained pair (release ZIP SHA256 `108228c9…`, Lambda `CodeSha256` `EIIoyRXB…`). This session is
source-only and did not probe AWS, so that is a documented claim, not a measurement made here. Review
finding 4 flags the same gap. Before treating the live surface as clean, confirm directly:

```
aws lambda get-alias --function-name wecare-whatsapp-business-api --name live
aws lambda get-function-configuration --function-name wecare-whatsapp-business-api:live \
    --query 'Environment.Variables.[RAZORPAY_MID,RAZORPAY_UPI_ID]'
```

## Note for the orchestrator

1. **Do not push without merging `origin/stack` first.** Local `stack` is 4 ahead / 14 behind. The
   merge is clean *except* for the dirty `META-BETA-REQUEST-EMAIL.md`, which belongs to another
   session and must be committed or resolved by its owner before the merge can proceed.
2. **CI trigger.** `.github/workflows/seo-tools-deploy.yml` push-triggers on
   `amplify/functions/shared/lambda_utils/**`. The `payment_readiness.py` edit matches that path, so
   the eventual push fires a `seo-tools` CI deploy. Expected, not incidental.
3. **Evidence doc naming.** Review finding 3 noted the brief's artifacts had been deleted by the
   revert. This file restores the brief's path; the superseding remote evidence is
   `docs/execution/razorpay-mid-vpa-purge-20261002.md`, which arrives with the merge. The two are
   complementary — that one covers the live deploy, this one covers the local reconciliation.
4. **Accepted deviation from the brief (review finding 5, non-blocking).** The brief's Class B asked
   that the retired id *survive* in `payment_readiness.py` as the thing being corrected. The adopted
   content substitutes `[retired Razorpay account]` instead. This is deliberate: the owner's verbatim
   *"remove old from everywhere"* outranks the brief, the review explicitly accepted it, and matching
   `origin/stack` byte-for-byte is what keeps the merge clean. The past-tense correction narrative and
   the RETIRED / AUTHORITATIVE distinction are both preserved, so the module still teaches why the
   earlier reasoning was wrong. Recorded here so a later reader does not read the brief as unmet.
5. **Residual prose nit, deliberately not fixed.** `docs/compatibility.md:87` and
   `payment_readiness.py:47` still say the live env *"says"* / *"was"* the retired VPA in present-ish
   framing, which is stale now that live v60 carries the retained pair. Correcting the wording would
   diverge from `origin/stack` and reintroduce a merge conflict for no safety gain. Fix it after the
   merge, in one place, if it is worth fixing.
