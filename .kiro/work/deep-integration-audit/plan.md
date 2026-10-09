# Implementation Plan — Deep Integration Audit (safe-engineering set)

Derived from the **APPROVED ON SUBSTANCE** design (`design.md` revision 3, `design-review.json`
round 4). This plan does **not** re-design anything. It sequences `design.md` §5 and the F-1…F-11
fix specs into ordered, individually verifiable work items, and it separates the implementable
set from the owner/provider/STOP set.

Where this plan and `design.md` differ on a *number*, `design.md` §0 governs the method
(re-derive, never trust) and this plan carries the re-derived value. Where they differ on
*substance*, `design.md` wins and this plan is wrong.

---

## 0. Base state — did `origin/stack` move?

**`origin/stack` did NOT move.** Verified as the first action of this planning step:

```
git -C <worktree> fetch origin && git rev-parse origin/stack
  -> 061b6e77c8a352d174c713834af0ca7d61b027b9
```

That is **exactly** the SHA `design.md` §0 anchors every `file:line` to
(`061b6e77`, "fix: retire obsolete Meta Flows with WABA-aware lifecycle API"). No re-anchoring
of the design was required, and no merge of a *newer* remote tip is needed.

**But the worktree branch is still behind that anchor, and this is load-bearific.**

| Tree | SHA | Relationship |
|---|---|---|
| `origin/stack` (the citation anchor) | `061b6e77` | unchanged since the design was written |
| worktree `deep-integration-audit` HEAD | `0425dce1` | **1 ahead, 12 behind** `origin/stack` |
| merge base | `53ed298e` | — |

```
git rev-list --left-right --count HEAD...origin/stack   ->  1  12
git merge-base --is-ancestor 061b6e77 HEAD              ->  NO
```

So the design's line numbers are correct **for `origin/stack`** and **wrong for the tree as it
stands**. Measured drift on the exact files this plan edits:

| Citation | At worktree HEAD `0425dce1` | At anchor `061b6e77` (what this plan uses) |
|---|---|---|
| F-4 `flows/customer_orders.py` `Filter='sub` | **does not exist** (the 7th site is upstream-only) | `:60` |
| F-4 `flows/paid_vault.py` `Filter='sub` | `:44` | `:69` |
| F-4 `ecommerce/checkout/handler.py` `Filter='sub` | `:3098` | `:3080` |
| F-9 "Please pay again to download" | `:1210`, `:1441` | `:1225`, `:1460` |
| F-10 `paid_vault.py` 24-hour condition | `:78` | `:103` |
| F-10 `paid_vault.py` `VAULT_READY` return | `:88` | `:113` |
| `tests/test_customer_orders_flow.py` | **absent** | present |

Four of the twelve target files differ (`flows/customer_orders.py`, `flows/paid_vault.py`,
`core/secure-files/handler.py`, `ecommerce/checkout/handler.py`); the other eight
(`meta-catalog-sync/handler.py`, `razorpay-webhook/handler.py`, `invoice-engine/handler.py`,
`customer_auth.py`, `order_keys.py`, `paid_submit_request.py`, `customer_commands.py`,
`catalog_services.py`) are byte-identical at both commits.

**Consequence, binding: item 1 (integrate `origin/stack`) is a hard prerequisite of every other
item.** Without it F-4 has six sites instead of seven and its seventh pin test has no module to
import. **Integrate by `git merge`, never `git rebase` and never `--force`** — the design's §5 item 0
says "rebase", the step authorization for this build says merge; merge is the safe reading of both
and preserves the parallel session's history. The merge is **clean**:
`git merge-tree --write-tree HEAD origin/stack` produces a tree with no conflict (exit 0), because
our one commit touches only `.kiro/work/deep-integration-audit/findings.md`, which does not exist
at `origin/stack`.

---

## 0.0 POST-MERGE BASELINE — written by item 1 (FEAT-001). **This supersedes §0 and §0.1.**

**`origin/stack` MOVED between planning and the build.** It is no longer `061b6e77`:

| Thing | Value |
|---|---|
| `origin/stack` at planning (the design's citation anchor) | `061b6e77c8a352d174c713834af0ca7d61b027b9` |
| `origin/stack` at build time | **`1102da71b0eddb704dcb9486ddf54059c1c75c80`** — 25 commits further on |
| divergence before the merge | HEAD `0425dce1` was **1 ahead / 37 behind** |
| merge commit | `bc4fcf72` — `git merge origin/stack`, clean, no conflict, no rebase, no force |
| anchor still in history | `git merge-base --is-ancestor 061b6e77… HEAD` → exit 0 (it is an ancestor of the new tip) |

The 25 new commits are almost entirely the parallel session's payment work ("Remove obsolete
WhatsApp payment kill switch", "Move commerce payment bills to invoice engine", "Make checkout
payment initiation on by default", "Run one-shot payment Lambda deployment"). Of the files this
plan edits, **only two** changed between `061b6e77` and `1102da71`:
`ecommerce/checkout/handler.py` and `payments/invoice-engine/handler.py`.

**Post-merge baselines, measured on `bc4fcf72`:**

| Measurement | Pre-merge (`0425dce1`) | **Post-merge (`bc4fcf72`)** |
|---|---|---|
| Whole suite | `10342 passed, 6 skipped, 3 xfailed` green | **`10432 passed, 6 skipped, 3 xfailed` + 1 FAILED** (113.29s) |
| Focused 5-file set | `161 passed` | **`166 passed`** |
| F-1 pair (`test_meta_catalog_sync_handler.py` + `test_meta_catalog_sync.py`) | — | **`113 passed`** (41 + 72) |

**One inherited failure arrived with the merge and is NOT ours:**
`tests/test_github_oidc_trust_policy.py::test_fixer_covers_every_oidc_role_the_repository_declares`.
Upstream commit `4ee4c498` ("Run one-shot payment Lambda deployment") added
`.github/workflows/payment-lambda-deploy-once.yml`, which declares the OIDC role
`GitHubActions-wecare-digital-payment-deploy-temp-20261009`; that role is not registered in
`scripts/fix_github_oidc_trust.ROLES` at `origin/stack` either, so the failure is present on the
remote tip independently of this branch. It is an **IAM-trust** matter and therefore **not** a
repair this plan may bundle (§0.3, and it is out of scope besides). **Every later item's gate is
therefore: `>= 10432 passed` with that ONE failure and no other.**

**Re-derived anchors on the merged tree** (mandatory, because `origin/stack` moved — item 1's own
instruction). Every anchor in items 2-8 was re-run with `git grep -n`. **Three numbers drifted**;
all three are now corrected here and the drifted plan text below is superseded by this table:

| Item | Citation in the plan text below | **Actual on `bc4fcf72`** |
|---|---|---|
| 3 (F-5) | `invoice-engine/handler.py:853` — the **negated** `not in str(claim_err)` | **`:889`** |
| 5 (F-4) | `ecommerce/checkout/handler.py:3076-3077` guard, `Filter='sub` at `:3080` | guard **`:3073`**, `Filter` **`:3076`** |
| 5 (F-4) | `flows/catalog_services.py:50` — `if not owner:` | **`:49`** (the `Filter` it guards is still `:55`) |

Everything else verified unchanged: item 2 (F-1) `raise RuntimeError` `:233` — still the only
`raise` in the file, `meta_catalog_sync_read_failed` `:554`, `"applied": 0` at
`:529/:559/:572/:601/:606`, `logger = get_logger` `:57`; item 3's five webhook sites
`:1719/:2036/:2149/:2746/:2866` and both module-scope imports (`razorpay:37`, `invoice-engine:48`)
and all eight out-of-scope substring sites; item 4's `:2469`, `:2458`, `:101`, `:2555/:2621`,
`:22`, `:39`, `:1703/:1720/:1731`, `order_keys._read_row:335`; item 5's **seven** `Filter='sub`
sites, the two `re.fullmatch` guards (`customer_commands:80`, `customer_orders:57`),
`customer_auth.py` `:39-41/:48/:72/:136/:280`, and `is_cognito_subject` still **absent**; item 6's
`:96`, `def list_orders:80`, `catalog_services:64/:65`, `order_keys:177/:222/:238/:380`, the
`:8-13` imports and `NO_ORDERS` at `:33/:34`; item 7's **exactly two** `Please pay again to
download` hits at `:1225` and `:1460`, `_redeem_after_reconcile:1191`, `_redeem:1405`,
`_reconcile_grant:1144`, `DOWNLOAD_URL_TTL:215`, test idioms at `:196`/`:860`, and **no** existing
test asserting the old string or `GRANT_NOT_REDEEMABLE`; item 8's `86400` at `:103`, `VAULT_READY`
at `:113`, `wecare_share_pdf` at `:91`, the download-template flag at `:93-94`, and
`vault_env` at `tests/test_paid_vault.py:22`.

One path correction, not a line drift: `meta_ready` is at
`amplify/functions/shared/lambda_utils/ecommerce/catalog_service_checkout.py:91`, under
`shared/lambda_utils/ecommerce/` — **not** under `flows/`.

Item 1 and item 2 (F-1) are complete. Item 2's tests took the F-1 pair from **113 → 121** and the
whole suite to **10440 passed** with the same single inherited failure.

---

## 0.1 Toolchain, baselines and verification commands

| Thing | Value |
|---|---|
| Python | `/Users/wecaredigital/wecare-digital/wecare-digital/.venv/bin/python` **only** (3.14.8, pytest 9.1.1). The root `conftest.py` hard-fails below 3.12. |
| Node | v24 — `export PATH="/opt/homebrew/opt/node@24/bin:$PATH"` if `node` is not found. Not needed for any item in Part A. |
| pytest config | `pytest.ini`: `--import-mode=importlib`, `testpaths = tests amplify/functions` |
| **Whole-suite baseline, measured at `0425dce1`** | **`10342 passed, 6 skipped, 3 xfailed` in 114.78s** — green |
| Focused baseline, measured at `0425dce1` | `161 passed` over `tests/test_meta_catalog_sync_handler.py tests/test_meta_catalog_sync.py tests/test_paid_vault.py tests/test_paid_submit_request.py tests/test_dropdocs_vault_no_second_charge.py` |
| macOS | **no `timeout`** — any AWS read uses `aws --cli-read-timeout 25 --cli-connect-timeout 10` |

`design.md` §5 item 0 cites `157 / 10394`; those were taken at the anchor, which has 12 more
commits of tests. **Re-capture both baselines after item 1** and use the post-merge numbers as the
reference for every later item. A later count that is *lower* than the post-merge baseline is a
regression even if the run is green.

Canonical commands, used verbatim by the Verify lines below:

```
PY=/Users/wecaredigital/wecare-digital/wecare-digital/.venv/bin/python
WT=/Users/wecaredigital/wecare-digital/wecare-digital/.worktrees/deep-integration-audit

# focused
cd $WT && $PY -m pytest -q <files>
# whole suite
cd $WT && $PY -m pytest -q
```

## 0.2 Authorization legend

| Tag | Meaning |
|---|---|
| **SAFE-ENGINEERING** | source + tests in the worktree, local commit, no cloud call. `A1_LOCAL`. Implement now. |
| **OWNER CONFIRM** | needs an explicit owner authorization for the exact target *and* rollback immediately before acting (`docs/execution/change-authority-matrix.md:1154`, `A3_PRODUCTION`). **Do not implement.** |
| **STOP** | a gate opening or a provider/owner action. **Do not implement, do not open, do not test through.** |

`.kiro/steering/*` was deleted in `af7858fa` and `AGENTS.md` is absent, both confirmed absent from
the worktree. **No standing authorization survives**, so every production mutation is OWNER CONFIRM.

## 0.3 Binding safety rules for every item below

- **Never** `secretsmanager get-secret-value` / `batch-get-secret-value` in any spelling. Env-var
  **names** only, never values. No inline credentials.
- **Never** `git add .` / `-A` / `-u`, `git commit -a`, or bare `git stash`. **Stage exact paths only.**
- **Never** force-push, `reset --hard`, `clean -f`, or rewrite history. Commit locally; do not push.
- Payments **fail closed**. Do not weaken signature, auth, ownership, IAM or isolation checks, and
  do not swallow failures.
- Do not delete catalogs, products, orders, customers, files or payment records.
- Do not send live WhatsApp. Do not invoke a production Lambda.
- Keep **CLOSED**: `WHATSAPP_CATALOG_SERVICES_ENABLED`, Wix writeback,
  `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED`, `SECURE_FILES_PAYMENT_ENABLED`.
- **If a fix can only be verified by crossing a STOP boundary, ship the source + the unit tests
  that run without the boundary and record the live verification in Part B.** Never open a gate to
  make a test pass.
- One commit per F-item, fix and its tests in the same commit, no unrelated repairs bundled.

---

# PART A — SAFE-ENGINEERING (implement these)

Ordered by dependency and by blast radius. Item 1 gates everything. Item 2 (F-1) must land with
**no `lambda_utils` delta in the tree**, per `design.md` §5's binding ordering constraint, so every
shared-package item (F-4, F-5, F-6) lands after it.

- [ ] 1. **Integrate the citation anchor and re-capture the baseline.**
      `git -C $WT fetch origin`, confirm `git rev-parse origin/stack` is still
      `061b6e77c8a352d174c713834af0ca7d61b027b9`, then `git -C $WT merge origin/stack` (a merge —
      **never** `rebase`, **never** `--force`). The merge is clean; if git nevertheless reports a
      conflict, resolve it **in favour of `origin/stack` for every file outside
      `.kiro/work/deep-integration-audit/`** and never discard the parallel session's content. Then
      re-run both baselines and record the post-merge numbers at the top of this file under
      "post-merge baseline". If `origin/stack` has moved since this plan was written, merge the new
      tip and re-derive every `git grep -n` anchor in items 2-8 before touching code.
      Files: no source file is edited. Working-tree-only: the merge commit, plus the
      post-merge-baseline note appended to
      `.kiro/work/deep-integration-audit/plan.md`.
      Verify: `git -C $WT merge-base --is-ancestor 061b6e77c8a352d174c713834af0ca7d61b027b9 HEAD`
      exits 0; `git -C $WT grep -c "Filter='sub" HEAD -- amplify` reports **7** files-worth of
      sites (7 total); `cd $WT && $PY -m pytest -q` is green and reports **at least** `10342 passed`.
      Authorization: **SAFE-ENGINEERING**.

- [ ] 2. **F-1 — meta-catalog-sync diagnostic hygiene: carry the Graph status structurally and make
      `reason` total over all five `applied:0` arms.**
      In `amplify/functions/ecommerce/meta-catalog-sync/handler.py`: add a module-level
      `class MetaCatalogReadError(RuntimeError)` (docstring: carries the Graph status structurally,
      never a body), modelled on `amplify/functions/shared/lambda_utils/wix_ecom.py:59-75`. Raise it
      at `:233` in place of the bare `RuntimeError`, setting `.status` from
      `result["error"].get("status")` and `.errorKind` from `result["error"].get("type")`. Add
      `graphStatus` and `graphErrorKind` to the existing `meta_catalog_sync_read_failed` log at
      `:554-557` **and nothing else** — the Graph **response body must still never be logged**
      (`:208-209` records why: the body echoes the request, whose one header is a credential). Then
      add `reason` to the three unreasoned `applied:0` arms: `:568-572` → `"read_only_inspect"`;
      `:599-601` → `"disabled" if not enabled else "dry_run"` (**derived, not hard-coded** — the arm
      covers both); `:604-606` → `"nothing_to_apply"`. Leave `:528-529` (`unconfigured`) and
      `:558-559` (`read_failed`) as they are, and leave the `:534` `batchHandle` arm (no `applied`
      key) alone. Fail-closed behaviour is unchanged: a read failure still returns `read_failed` and
      still constructs no write. `errorType` stays — `MetaCatalogReadError` subclassing
      `RuntimeError` keeps `type(e).__name__` a reliable localiser and makes it *more* specific.
      Anchors (prefer these over the numbers): `git grep -n 'raise RuntimeError' <file>` — it is the
      **only** one in the file; `git grep -n 'meta_catalog_sync_read_failed' <file>`;
      `git grep -n '"applied": 0' <file>`.
      Failing-first tests, all four in the **existing** `tests/test_meta_catalog_sync_handler.py`
      (29 tests today), reusing its `run()` helper — anchor on `def run(` (currently `:180`), its
      `FakeGraph` (`:139`) and `reader_for` (`:168`), not on the line numbers:
      (a) `test_a_read_failure_reports_the_graph_status` — `FakeGraph(error={"status": 403})`;
      assert the captured `meta_catalog_sync_read_failed` record has `graphStatus == 403`,
      `out["reason"] == "read_failed"`, `graph.writes == []`, and that **no** value in the record
      contains `Bearer` or `FAKE_TOKEN`. Fails today: `graphStatus` does not exist.
      (b) `test_a_transport_failure_reports_the_kind_and_no_status` —
      `FakeGraph(error={"type": "URLError"})`; assert `graphErrorKind` present, `graphStatus is None`.
      (c) `test_every_applied_zero_arm_states_its_reason` — parametrised over all five arms;
      assert `reason` present and equal to `unconfigured` / `read_failed` / `read_only_inspect` /
      `disabled` / `dry_run` / `nothing_to_apply`. Fails today on three.
      (d) sensitivity: the existing `test_a_META_read_failure_does_not_become_a_write` must still
      pass **unchanged**.
      **Log-capture mechanism — this file has no `caplog` precedent, so use exactly this.** The
      handler binds `logger = get_logger(__name__)` at `:57`; `lambda_utils.logging.get_logger`
      (`logging.py:17`) only calls `logging.getLogger(name)` and `setLevel`, adds no handler and
      never sets `propagate = False`, so records reach the root logger `caplog` attaches to. Take the
      logger name from the module object, never a hardcoded guess — the rig loads the handler by
      path under `MODULE_NAME = "wecare_meta_catalog_sync_handler"`:
      `caplog.set_level(logging.ERROR, logger=handler_module.logger.name)`. `get_logger` applies
      `LOG_LEVEL` (default `INFO`) at `setLevel`, so a test asserting on an `INFO` record must either
      leave `LOG_LEVEL` unset or set `caplog.set_level` **on the same logger** — the level on the
      logger, not the handler, is what filters.
      **Do NOT** put these in `tests/test_meta_catalog_sync.py`: that file's
      `test_the_module_is_pure_at_import` and `test_the_module_logs_nothing_at_all` assert properties
      a log-capturing, handler-driving test sits badly beside.
      Files: `amplify/functions/ecommerce/meta-catalog-sync/handler.py`,
      `tests/test_meta_catalog_sync_handler.py`
      Verify: `cd $WT && $PY -m pytest -q tests/test_meta_catalog_sync_handler.py tests/test_meta_catalog_sync.py`
      — all pass, count is `29 + 4 + 40` minus any parametrisation collapse and **strictly greater**
      than before. Then `cd $WT && $PY -m pytest -q` green at or above the post-merge baseline.
      Authorization: **SAFE-ENGINEERING** for the commit. The **deploy is OWNER CONFIRM (O10)** —
      Part B row B1. **This commit must be the only change in the tree at any publish time**, so
      items 4-8 land after it.

- [ ] 3. **F-5 — conditional-failure detection reads `.response['Error']['Code']`, never `str(err)`.**
      `order_keys.is_conditional_failure` already exists at
      `amplify/functions/shared/lambda_utils/ecommerce/order_keys.py:177` and is **unchanged** by
      this item. Convert six sites, **per site, not mechanically**:
      the five in `amplify/functions/payments/razorpay-webhook/handler.py` — `:1719`
      (`guard_err`), `:2036` (`e`), `:2149` (`cond_err`), `:2746` (`e`), `:2866` (`e`) — become
      `if order_keys.is_conditional_failure(<err>):`; and
      `amplify/functions/payments/invoice-engine/handler.py:853`, which is **negated**
      (`if 'ConditionalCheckFailedException' **not** in str(claim_err):`), becomes
      `if not order_keys.is_conditional_failure(claim_err):`. **Do not invert `:853`.** Inverting it
      turns an expected duplicate-invoice race into a 500 and a real storage failure into a silent
      dedup hit, on the GST-sequence path (`:843-852`) — the most consequential of the six.
      The import is already module-scope and needs no change: `razorpay-webhook/handler.py:37` and
      `invoice-engine/handler.py:48`. The five function-local re-imports in the webhook (`:479`,
      `:814`, `:974`, `:1020`, `:2553`) are redundant and irrelevant — leave them.
      **Eight further substring sites are deliberately OUT OF SCOPE** and must not be touched:
      `core/contacts/handler.py:527,:589,:617`;
      `messaging/inbound-whatsapp-handler/handler.py:3280,:7858`;
      `messaging/outbound-whatsapp/handler.py:4078`;
      `messaging/whatsapp-business-api/flows/postpay.py:169`;
      `shared/lambda_utils/flow_completion.py:242`.
      Anchors: `git grep -n "ConditionalCheckFailedException' in str" origin/stack -- amplify/functions/payments`
      (5 hits) and `git grep -n "ConditionalCheckFailedException' not in str" origin/stack -- amplify/functions/payments`
      (1 hit, `invoice-engine:853`).
      Failing-first test: new `tests/test_conditional_failure_detection.py`, two halves failing
      today in **opposite** directions. Half 1 uses a **test-local** subclass that keeps `.response`
      and overrides `__str__` (a plain `ClientError` cannot carry the code with the substring absent,
      because `botocore` interpolates `Error.Code` into `MSG_TEMPLATE`):
      `class OpaqueConditionalFailure(ClientError): def __str__(self): return 'storage error'`,
      instantiated with `{'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'storage error'}}`
      and `'UpdateItem'`; assert the premise (`'ConditionalCheckFailedException' not in str(OPAQUE)`)
      and that `order_keys.is_conditional_failure(OPAQUE)` is True; then assert the five webhook
      sites take the **idempotent** branch (info log, no duplicate side effect) and
      `invoice-engine:853` takes the **dedup-hit** branch (info `invoice_dedup_hit_atomic`, no 500).
      Half 2 needs no subclass: a plain `ClientError` with `Code='ValidationException'` and
      `Message='... ConditionalCheckFailedException ...'`; assert **every** site takes the **error**
      branch. **No production subclass of `ClientError` is introduced** — the subclass lives in the
      test module only.
      Files: `amplify/functions/payments/razorpay-webhook/handler.py`,
      `amplify/functions/payments/invoice-engine/handler.py`,
      `tests/test_conditional_failure_detection.py`
      Verify: `cd $WT && $PY -m pytest -q tests/test_conditional_failure_detection.py` — all pass;
      then the full razorpay/invoice regression set
      `cd $WT && $PY -m pytest -q -k "razorpay or invoice or webhook"` green; then
      `cd $WT && $PY -m pytest -q` green at or above the post-merge baseline.
      Authorization: **SAFE-ENGINEERING** for the commit. Deploy to `wecare-razorpay-webhook` /
      `wecare-invoice-engine` is **OWNER CONFIRM (O10)** — Part B row B2.

- [ ] 4. **F-2 — the webhook review arm yields to the native one, through a GUARDED
      `resolve_payment_reference` that can never replay a captured payment.**
      In `amplify/functions/payments/razorpay-webhook/handler.py`, replace the unguarded Step-5 block
      at `:2468-2470` with **exactly** this shape (the comment is part of the specification — it is
      the only record of why the guard exists):
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
      No new plumbing and no new import: `COMMERCE_KEYS_TABLE` is module-level at `:101`,
      `dynamodb.Table(COMMERCE_KEYS_TABLE)` is already the idiom at `:2555` and `:2621`,
      `json` is imported at `:22` and `logger = get_logger(__name__)` at `:39`, and `reference_id`
      and `request_id` are already in scope and already passed to `_request_review_on_whatsapp`.
      **Three things are binding and must not be "tidied".** (i) The default on an unreadable row is
      `native = False`, i.e. **we send the review**. A duplicate nudge during a storage outage is
      strictly preferable to replaying a captured payment; **never invert this to "skip on error"**.
      (ii) Catch `order_keys.OrderIdentityUnavailable` **specifically, not bare `Exception`** —
      `order_keys._read_row:344-347` wraps every storage error into that one type, so the narrow
      catch has no storage blind spot, while a bare catch would also swallow a genuine programming
      error and turn it into a permanently invisible duplicate-review bug. (iii) The
      `review_request_skipped_native` line is at **info** so the suppression is greppable, matching
      `post_payment_flow_skipped` at `:1703`, `:1720`, `:1731`.
      Do **not** change `order_keys._read_row` or its raise-on-storage-error contract
      (`order_keys.py:335-347`), and do not change the native senders.
      Anchors: `git grep -n '_request_review_on_whatsapp(invoice_id, contact' <file>` (the call site,
      `:2469`), `git grep -n 'BOTH legs ask' <file>` (the comment block, `:2458`).
      Failing-first tests: new `tests/test_native_service_review_dedup.py`, driving the real
      `razorpay-webhook` post-payment function and the real `paid_submit_request.review(...)` against
      one shared fake commerce-keys/ServiceRequests pair, with both outbound boundaries spied
      (`lambda_client.invoke` and `urllib.request.urlopen`):
      (a) `test_one_native_purchase_asks_for_a_review_once` — one `referenceId` with
      `nativeCatalogService: True` and `detailsSubmittedAt` set; assert **exactly one** invoke carries
      `templateName == 'wecare_leave_review'`. Two are sent today.
      (b) `test_a_website_purchase_still_asks_once` — `nativeCatalogService` absent; the website leg
      still sends exactly one. Sensitivity proof that the fix did not simply disable the webhook arm.
      (c) `test_a_paid_native_purchase_with_no_details_asks_for_no_review` —
      `nativeCatalogService: True`, **no** `detailsSubmittedAt`; assert **zero** review invokes. Pins
      the design's decision that **no fulfilment implies no review invitation**.
      (d) `test_an_unreadable_payment_reference_does_not_fail_the_capture` — fake commerce-keys table
      raises `botocore.exceptions.ClientError` with
      `{'Error': {'Code': 'ProvisionedThroughputExceededException'}}` on `get_item`. Assert, in this
      order of importance: the post-payment function **returns normally and does not raise**; the
      handler does **not** return 500; **exactly one** review invoke (the fail-open default); and
      `review_native_check_unavailable` was logged at `WARNING`.
      (e) `test_an_error_outside_the_storage_wrapper_is_not_swallowed` — **inject outside
      `_read_row`'s `try`**, or the test proves nothing: monkeypatch the module's `dynamodb` resource
      so `.Table()` raises `KeyError('COMMERCE_KEYS_TABLE')` (it is evaluated *before*
      `resolve_payment_reference` is entered). Assert the exception **propagates** out of the
      post-payment function rather than being absorbed into the fail-open default, and that **no**
      review invite was sent on that call. This pins the narrow-catch choice so a later tidy-up to
      `except Exception` fails the suite.
      Files: `amplify/functions/payments/razorpay-webhook/handler.py`,
      `tests/test_native_service_review_dedup.py`
      Verify: `cd $WT && $PY -m pytest -q tests/test_native_service_review_dedup.py` — all five pass;
      then `cd $WT && $PY -m pytest -q -k "razorpay or webhook or payment"` green; then
      `cd $WT && $PY -m pytest -q` green at or above the post-merge baseline.
      Authorization: **SAFE-ENGINEERING** for the commit. Deploy is **OWNER CONFIRM (O10)** — Part B
      row B2. Depends on item 3 only for commit ordering (same function, same §5 row 4b-i); it does
      not depend on item 3's content.

- [ ] 5. **F-4 — one Cognito-subject predicate, seven sites, and the literal regex appears exactly
      once in the tree.**
      Add **one** definition to `amplify/functions/shared/lambda_utils/customer_auth.py`:
      `def is_cognito_subject(value) -> bool` returning a full match of
      `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}` — the same pattern, so **no behaviour change on
      well-formed input**. The module needs `import re` added (it currently imports `json`, `logging`,
      `os` at `:39-41`); add `"is_cognito_subject"` to `__all__` at `:280-292`. The module is the
      right home: it already owns `CUSTOMER_POOL_ID` (`:48`), `CustomerNotAuthorized` (`:72`) and
      `customer_id_from_attributes` (`:136`), and all seven sites already import it. Verified absent
      today: `git grep -n "is_cognito_subject" origin/stack -- amplify` → no matches.
      Then the **seven** sites. **Each site keeps its existing refusal mechanism** — only the
      predicate is shared:
      | Site at `061b6e77` | Change | Refusal (unchanged) |
      |---|---|---|
      | `flows/customer_commands.py:80` | **convert** the inline `re.fullmatch` to `customer_auth.is_cognito_subject(owner)` | `return {'outcome': 'VERIFIED_CUSTOMER_REQUIRED', 'reply': <sign-in text>}` |
      | `flows/customer_orders.py:57` | **convert** the inline `re.fullmatch` to the helper | `raise customer_auth.CustomerNotAuthorized('account unavailable')` |
      | `flows/catalog_services.py:50` | widen the existing `if not owner:` to `if not customer_auth.is_cognito_subject(owner):` — this guards `:55` | existing `_send(...)` + `return {'outcome': 'VERIFIED_CUSTOMER_REQUIRED'}` |
      | `ecommerce/checkout/handler.py:3076-3077` | widen `if not owner or owner != row.get('customerId'):` to `if not customer_auth.is_cognito_subject(owner) or owner != row.get('customerId'):` — this guards `:3080` | `return {'outcome': 'VERIFIED_CUSTOMER_REQUIRED'}` (`:3078`) |
      | `flows/paid_submit_request.py:90` | insert, immediately before: `if not customer_auth.is_cognito_subject(row['customerId']): return {'outcome': 'VERIFIED_RECIPIENT_UNAVAILABLE'}` | `VERIFIED_RECIPIENT_UNAVAILABLE` |
      | `flows/paid_submit_request.py:142` | same insertion before the second `list_users` | `VERIFIED_RECIPIENT_UNAVAILABLE` |
      | `flows/paid_vault.py:69` | same insertion before the `list_users` | `VERIFIED_RECIPIENT_UNAVAILABLE` |
      Widening the two existing truthiness guards (`catalog_services`, `checkout`) rather than adding
      a second `if` is the smallest change that covers all four malformed inputs with the *same*
      refusal the site already returns, and it keeps the number of refusal paths unchanged.
      `re` must stay imported in `flows/customer_orders.py` — `TOKEN_PATTERN` at `:16` still uses it.
      After this item, `git grep -c "0-9a-f]{8}(?:-\[0-9a-f]{4}){3}" -- amplify` must find the
      literal **exactly once**, in `customer_auth.py`.
      Anchors: `git grep -n "Filter='sub" origin/stack -- amplify` → the seven sites;
      `git grep -n "re.fullmatch" origin/stack -- amplify/functions/messaging/whatsapp-business-api/flows/customer_commands.py amplify/functions/messaging/whatsapp-business-api/flows/customer_orders.py`
      → the two inline guards (`:80`, `:57`).
      Failing-first test: new `tests/test_customer_identity_filter_guard.py`, parametrised over the
      **five** previously-unguarded sites with a `cognito-idp` double that **raises** on any call.
      Feed `'" or sub = "x'`, `''`, `'not-a-uuid'` and an **uppercase** UUID; assert each returns its
      verified-customer refusal (`VERIFIED_CUSTOMER_REQUIRED` for `catalog_services` and `checkout`,
      `VERIFIED_RECIPIENT_UNAVAILABLE` for the three flow sites) with the client **never invoked**.
      All five fail today. Plus the **two pin cases** that must pass **before and after**, so the
      conversion cannot silently change a working refusal:
      `test_customer_commands_still_refuses_a_malformed_subject` — returns
      `{'outcome': 'VERIFIED_CUSTOMER_REQUIRED'}` with the sign-in reply, double never invoked; and
      `test_customer_orders_still_refuses_a_malformed_subject` — **raises**
      `customer_auth.CustomerNotAuthorized`, double never invoked.
      Files: `amplify/functions/shared/lambda_utils/customer_auth.py`,
      `amplify/functions/messaging/whatsapp-business-api/flows/customer_commands.py`,
      `amplify/functions/messaging/whatsapp-business-api/flows/customer_orders.py`,
      `amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py`,
      `amplify/functions/messaging/whatsapp-business-api/flows/paid_submit_request.py`,
      `amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py`,
      `amplify/functions/ecommerce/checkout/handler.py`,
      `tests/test_customer_identity_filter_guard.py`
      Verify: `cd $WT && $PY -m pytest -q tests/test_customer_identity_filter_guard.py` — all seven
      pass. Then the owning suites:
      `cd $WT && $PY -m pytest -q tests/test_customer_orders_flow.py tests/test_paid_vault.py tests/test_paid_submit_request.py tests/test_customer_auth*.py tests/test_checkout*.py`
      green (substitute the actual filenames `ls tests | grep -E 'customer_auth|checkout'` reports).
      Then `cd $WT && $PY -m pytest -q` green at or above the post-merge baseline.
      Authorization: **SAFE-ENGINEERING** for the commit. **Shared-package change** — must land
      after item 2 (F-1), never before, or a fleet-wide publisher would sweep F-1's target. Deploy
      of the live sites is **OWNER CONFIRM (O10)** and the `wecare-whatsapp-business-api` half is
      additionally **blocked on O11** — Part B rows B3/B4.

- [ ] 6. **F-6 — `list_orders` never offers an internal UUID as a customer-facing label, returns a
      PLAIN LIST, and eligibility moves to a separate `has_prior_order`.**
      In `amplify/functions/shared/lambda_utils/ecommerce/paid_submit_request.py`:
      **Decision 1, binding — the return value stays `list[dict]`. The skipped count is LOGGED,
      never returned.** A 2-tuple is always truthy, which would make
      `flows/paid_submit_request.py:33`'s `if not choices:` never fire, the `NO_ORDERS` screen at
      `:34` unreachable, and would serialise a tuple into a **live** Flow screen.
      **Decision 2, binding — the display rule is applied INSIDE `list_orders`' loop**, where both
      values are already in scope at `:96`. Replace `:96-97`:
      ```python
      label = current.get('orderNumber')
      if not order_keys.is_public_order_number(label):
          # Display rule: a public order number or nothing, never an internal UUID.
          # `flows/customer_commands.order_page` already refuses exactly this.
          skipped += 1
          continue
      result.append({'id': oid, 'title': str(label)[:60]})
      ```
      with `skipped = 0` initialised beside `result = []` at `:86`, and after the loop / before the
      `return` at `:104`: `if skipped: log_event(logger, 'order_choices_unnumbered', skipped=skipped)`.
      Use **`order_keys.is_public_order_number`** (`order_keys.py:222`), **not**
      `is_current_public_order_number` (`:238`) — the former deliberately accepts both the current
      `WD-ORD-XXXXXXXX` form and the bare 12-character legacy form, and the stricter one would
      silently drop every order placed before the prefix existed. `list_orders` keeps its name,
      signature, dict shape and ownership semantics; **do not add a third key** to the returned
      dicts — that payload is serialised into a live Flow screen.
      **Logging imports — two are needed.** The module imports only `hashlib` (`:8`), `hmac` (`:9`),
      `secrets` (`:10`), `time` (`:11`), `typing.Any` (`:12`) and
      `order_keys, service_request_store as store` (`:13`). Add
      `from lambda_utils.logging import get_logger, log_event` beside `:13` and
      `logger = get_logger(__name__)` at module scope. Use `log_event` (`logging.py:28`,
      `(logger, event_name, level='info', **kwargs)`) rather than a hand-rolled `json.dumps` — it is
      the house helper and it drops the `json` import entirely. `get_logger` (`:17`) is import-safe
      here: it creates no client and reads no secret, which matters because this module is imported
      on the paid path. **The count is the ONLY field** — never a `fileId`, `orderId`, phone or
      filename.
      **Then add `has_prior_order`, which is the part that must not be got wrong.** `list_orders`'
      return value also serves as a boolean eligibility gate at `flows/catalog_services.py:64-70`;
      narrowing `list_orders` without this would flip a legacy-only customer from **eligible to
      refused** — a purchase-blocking regression. Add beside `list_orders`:
      ```python
      def has_prior_order(orders: Any, row: dict) -> bool:
          """Eligibility only: does a DIFFERENT order exist under this verified customer?

          Deliberately does NOT apply the display rule. A customer whose only prior orders are
          legacy and unnumbered is still entitled to buy Submit Request; they simply see a
          shorter selector. Keeping these two questions in one function is what made the naive
          version of this fix purchase-blocking.
          """
      ```
      implemented as the same `customerId=:owner` query with the same `ConsistentRead=True`
      ownership recheck and the same `oid == row['orderId']` self-exclusion, short-circuiting `True`
      on the first qualifying row. Then switch the call site:
      `flows/catalog_services.py:64` imports `has_prior_order` alongside (or instead of)
      `list_orders`, and `:65` becomes `if not has_prior_order(...)`. Two lines.
      Anchors: `git grep -n "orderNumber') or oid" <file>` (`:96`); `git grep -n "^def list_orders" <file>`
      (`:80`); `git grep -n "list_orders" -- amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py`
      (`:64`, `:65`).
      Failing-first tests: new `tests/test_paid_submit_request_order_labels.py`, six cases:
      (1) `test_orders_without_a_public_number_are_not_offered` — one `orderNumber`-bearing row and
      one without; `list_orders(...)` has length **1** and no returned `title` matches the UUID
      regex. Fails today: both offered, one with a UUID title.
      (2) `test_list_orders_returns_a_plain_list` — `isinstance(result, list)`, and an input whose
      rows **all** lack `orderNumber` yields `[]` so `flows/paid_submit_request.py:34`'s `NO_ORDERS`
      screen actually fires. This is the test that catches the tuple mistake.
      (3) `test_a_legacy_only_customer_is_still_eligible` — a fake table whose only rows lack
      `orderNumber`; `has_prior_order(...)` is `True` so `catalog_services.py:65` does **not** emit
      `SUBMIT_REQUEST_PARENT_ORDER_REQUIRED`, **while** `list_orders(...)` returns `[]`. Both halves
      of the separation asserted together.
      (4) `test_a_legacy_bare_twelve_character_number_is_still_offered` — a pre-prefix bare
      12-character `orderNumber` **is** offered. Pins `is_public_order_number` over
      `is_current_public_order_number`.
      (5) `test_the_skipped_count_is_logged_without_identifiers` — one numbered, two unnumbered rows;
      the `order_choices_unnumbered` record has `skipped == 2` and **no** value in it contains any
      `orderId` from the fixture.
      (6) `test_the_parent_order_is_still_excluded` — `row['orderId']` present among the queried
      rows; absent from the result. Sensitivity proof that the new `continue` did not disturb the
      existing self-exclusion at `:91-92`.
      Files: `amplify/functions/shared/lambda_utils/ecommerce/paid_submit_request.py`,
      `amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py`,
      `tests/test_paid_submit_request_order_labels.py`
      Verify: `cd $WT && $PY -m pytest -q tests/test_paid_submit_request_order_labels.py` — all six
      pass; then `cd $WT && $PY -m pytest -q tests/test_paid_submit_request.py tests/test_paid_vault.py tests/test_service_lines_dropdocs_vault.py`
      green (the `NO_ORDERS` / selector paths); then `cd $WT && $PY -m pytest -q` green at or above
      the post-merge baseline.
      Authorization: **SAFE-ENGINEERING** for the commit. **Shared-package change**, same ordering
      constraint as item 5: after item 2. Deploy is **OWNER CONFIRM (O10)** and **blocked on O11** —
      Part B row B4.

- [ ] 7. **F-9 copy correction ONLY — a paid customer is never told to pay again. The re-issue ROUTE
      is NOT in this item.**
      In `amplify/functions/core/secure-files/handler.py`, replace the **identical** refusal message
      at **both** sites — `:1460` inside `_redeem` (`def _redeem` at `:1405`) and `:1225` inside
      `_redeem_after_reconcile` (`def _redeem_after_reconcile` at `:1191`):
      - from: `"This download link is not valid. Please pay again to download."`
      - to: `"This download link is no longer valid. If you have already paid, do not pay again; contact us to restore access."`
      **The replacement wording is decided here, not left open**, and it follows the repository's
      established house copy for exactly this situation — `src/components/VaultFilePurchase.tsx:59`
      ("This file is already paid. Contact us to restore access; please do not pay again.") and
      `src/pages/checkout/success.tsx:61` ("If you have paid, do not pay again."), with
      `src/pages/checkout/status.tsx:47` recording that *"Do not pay again" is load-bearing*.
      **Nothing else changes.** The HTTP status stays **403**, the error code stays
      **`GRANT_NOT_REDEEMABLE`**, the `ConditionalCheckFailedException` arms, the `_reconcile_grant`
      attempt at `:1453`, the `consumed = :false` single-use condition at `:1428-1431` and the
      60-second `DOWNLOAD_URL_TTL` (`:215`) are all untouched. No route, no parameter, no
      `reissueCount`, no cap, no `_customer_list` arm, no TTL.
      **Why both sites.** `:1225` is **not** live-reachable today — `_redeem_after_reconcile` is
      entered only when `_reconcile_grant` returns True (`:1453-1454`) and that function returns
      False while `_payment_enabled()` is false (`:1156-1157`) — but it becomes reachable the moment
      §5 item 8 opens `SECURE_FILES_PAYMENT_ENABLED`, and item 8 lists F-9 as satisfied. Fixing one
      site only would re-introduce the defect at the gate opening.
      Anchor: `git grep -n 'Please pay again to download' -- amplify/functions/core/secure-files/handler.py`
      → must return **exactly two** hits before the change and **zero** after.
      Failing-first tests, added to the existing `tests/test_secure_files.py` (1371 lines), following
      that file's established per-function source-body idiom — see
      `test_redeem_after_reconcile_is_still_single_use` (`:860-863`) and
      `test_redeem_requires_paid_and_unconsumed` (`:196-200`), both of which slice the handler source
      with `source.split("def _redeem_after_reconcile")[1].split("\ndef ")[0]`:
      (a) `test_a_paid_customer_is_never_told_to_pay_again` — assert
      `"Please pay again to download" not in source` **and** `"do not pay again" in body` for the
      `_redeem` body **and** the `_redeem_after_reconcile` body independently. Totality over both
      sites, which is the invariant; fails today at both.
      (b) `test_the_redeem_refusal_contract_is_unchanged` — sensitivity proof that this was copy and
      nothing else: for each of the two bodies assert `"GRANT_NOT_REDEEMABLE" in body`,
      `"403" in body`, and that `"consumed = :false"` and `"paid = :true"` still appear in the
      `_redeem_after_reconcile` body (i.e. the existing
      `test_redeem_after_reconcile_is_still_single_use` still passes unchanged).
      No existing test asserts the old string — verified: `git grep -n "pay again" origin/stack -- tests`
      returns no assertion on it, and `git grep -ln "GRANT_NOT_REDEEMABLE" origin/stack -- tests`
      returns nothing — so this item breaks no test and adds the first pin on the invariant.
      Files: `amplify/functions/core/secure-files/handler.py`, `tests/test_secure_files.py`
      Verify: `cd $WT && $PY -m pytest -q tests/test_secure_files.py tests/test_dropdocs_vault_no_second_charge.py`
      — green, count strictly greater than before; then
      `git -C $WT grep -c 'Please pay again to download' -- amplify/functions/core/secure-files/handler.py`
      → **0**; then `cd $WT && $PY -m pytest -q` green at or above the post-merge baseline.
      Authorization: **SAFE-ENGINEERING** for the commit. Deploy to `wecare-secure-files` is
      **OWNER CONFIRM (O10)** — Part B row B5. **The F-9 re-issue route is Part B row B8 (STOP) and
      must not be implemented, tested or stubbed in this item.**

- [ ] 8. **F-10 — a native Vault purchase that delivered nothing stops reporting `VAULT_READY`.**
      In `amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py`, the document branch
      at `:103-109` is skipped whenever its compound condition is false, and execution falls through
      to the review send at `:110-112` and returns **`VAULT_READY`** at `:113` — a success outcome
      for a purchase that delivered neither a link nor a file (the ready template at `:91` is
      `wecare_share_pdf`, which has an IMAGE header and carries no URL button and no file parameter;
      the link-bearing `wecare_default_download` at `:93-95` is behind
      `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED`, which stays **CLOSED**).
      Change: track whether the document branch was taken; when the download-template flag is off
      **and** the branch was not taken, return **`VAULT_DELIVERY_DEFERRED`** instead of
      `VAULT_READY`, and log `vault_delivery_deferred` with the `requestId` and a `reason` —
      **no filename, no phone, no fileId**. The review send at `:110-112` **still happens**: the
      customer did buy something and suppressing the nudge would hide the problem further. Only the
      *outcome* changes. `VAULT_REVIEW_PENDING` (returned when `accepted` is false) is unchanged.
      **The reason enum has a binding evaluation order, first match wins**, mirroring `:103`'s own
      left-to-right evaluation so the reported reason is always the *first* clause that actually
      failed:
      ```python
      if file.get('deliverable') != 'pdf':        reason = 'not_deliverable'
      elif not file.get('deliveryKey'):           reason = 'no_delivery_key'
      else:                                       reason = 'window_closed'
      ```
      `not_deliverable` → `no_delivery_key` → `window_closed`. The two file-shape reasons are
      permanent data problems; `window_closed` is a timing problem a re-send can resolve, and is last
      because it is the only one that can be true while the file is perfectly deliverable.
      `paid_vault.py` has no logger today (it imports `os`, `json`, `time`, `datetime`, `boto3`,
      `customer_auth`, `vault_access`), so add
      `from lambda_utils.logging import get_logger, log_event` and `logger = get_logger(__name__)`
      at module scope and emit via `log_event` — the same house helper item 6 adopts.
      Also, part (b): record in `docs/whatsapp/native-catalog-release-status.md` that opening
      `WHATSAPP_CATALOG_SERVICES_ENABLED` for Vault **requires**
      `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` in the same change, because `wecare_share_pdf`
      carries no link. **Documentation only — do not open either flag.** Do not disturb
      `catalog_service_checkout.meta_ready:91-106`, which already refuses native checkout unless
      `wecare_default_download` is `APPROVED` with that exact button (`:98-101`).
      Anchors: `git grep -n "86400" -- amplify/.../flows/paid_vault.py` (the condition, `:103`);
      `git grep -n "VAULT_READY" -- amplify/.../flows/paid_vault.py` (the return, `:113`).
      Failing-first tests: new `tests/test_paid_vault_deferred_delivery.py`, reusing
      `tests/test_paid_vault.py`'s `vault_env` fixture (which already seeds a file with
      `deliverable: 'pdf'` and `deliveryKey`):
      (a) `test_a_paid_vault_purchase_outside_the_window_is_not_reported_ready` —
      `deliverable: 'pdf'`, `deliveryKey` set, `contact['lastInboundMessageAt']` **25 hours** old,
      flag absent; assert the outcome is `VAULT_DELIVERY_DEFERRED`, that **exactly one** template
      send occurred (the share template) plus the review send, that **no** document message was
      sent, and that `vault_delivery_deferred` was logged with `reason == 'window_closed'` and no
      filename. Today it returns `VAULT_READY`.
      (b) `test_a_purchase_inside_the_window_is_still_ready` — sensitivity proof.
      (c) `test_a_non_pdf_reports_not_deliverable` — `deliverable: 'docx'` with a **stale** window;
      `reason == 'not_deliverable'`, proving the file-shape reason wins over the timing one.
      (d) `test_a_missing_delivery_key_reports_no_delivery_key` — `deliverable: 'pdf'`,
      `deliveryKey` absent, stale window; `reason == 'no_delivery_key'`.
      Files: `amplify/functions/messaging/whatsapp-business-api/flows/paid_vault.py`,
      `docs/whatsapp/native-catalog-release-status.md`,
      `tests/test_paid_vault_deferred_delivery.py`
      Verify: `cd $WT && $PY -m pytest -q tests/test_paid_vault_deferred_delivery.py tests/test_paid_vault.py`
      — all pass, including every existing `test_paid_vault.py` case **unchanged**; then
      `cd $WT && $PY -m pytest -q` green at or above the post-merge baseline.
      Authorization: **SAFE-ENGINEERING** for the commit. **Gated path** —
      `VAULT_DELIVERY_DEFERRED` is reachable only behind `WHATSAPP_CATALOG_SERVICES_ENABLED`, which
      stays CLOSED. **The deploy rides with §5 item 8 (STOP)**, so there is no cloud state to
      restore and `git revert` of the single commit is the whole rollback. Inherits **O11** because
      the parallel session is actively changing this file (`87859dbc`, `4a3c4251`, `e9e377ce`).

- [ ] 9. **Integration verification across all seven fixes, and the evidence record.**
      With items 1-8 committed, run the whole suite and the focused set together, confirm no
      cross-item interaction (F-4 and F-6 both edit `flows/paid_submit_request.py` and
      `flows/catalog_services.py`; F-4 and F-10 both edit `flows/paid_vault.py`; F-2 and F-5 both
      edit `razorpay-webhook/handler.py`), and append to
      `.kiro/work/deep-integration-audit/findings.md` the per-finding state transition for F-1, F-2,
      F-4, F-5, F-6, F-9(copy) and F-10 — each as **source fixed + tests green, deploy owner-gated**,
      with the commit SHA. Do not change any finding's severity and do not mark any F-item
      "resolved": the source half is done, the deploy half is not.
      Files: `.kiro/work/deep-integration-audit/findings.md`
      Verify: `cd $WT && $PY -m pytest -q` green, `passed` count **>=** the post-merge baseline plus
      the ~30 tests items 2-8 add; `git -C $WT status --porcelain` shows no unintended file; and
      `git -C $WT log --oneline origin/stack..HEAD` shows **one commit per F-item**, each touching
      only that item's listed files.
      Authorization: **SAFE-ENGINEERING**.

---

# PART B — OWNER CONFIRM / STOP / PROVIDER-BLOCKED (do NOT implement)

Every row below is **out of scope for the build loop**. They are recorded so the owner can
authorize or refuse each one explicitly, and so no coder mistakes an unshipped fix for an
unfinished one. Pre-change `live` version and `RevisionId` values are a 2026-10-09T04:32:07Z read
and **must be re-read immediately before any action** — the fleet moved four times during the audit.

| # | Item | Design ref | Target | Authorization | Why it is not implementable here |
|---|---|---|---|---|---|
| **B1** | Deploy F-1 | §5 row 2, §6 | `wecare-meta-catalog-sync` (live **7**, `dc895968-…`) | **OWNER CONFIRM (O10)** | Production alias move. Also capture v7's env (`META_CATALOG_ID=1457045652952851`, `ENABLED=false`, `DRY_RUN=true`, `FORCE_OUT_OF_STOCK=true`) — a published version freezes its environment, so reverting to v6 would silently revert the catalog target. |
| **B2** | Deploy F-2 + F-5 | §5 row 4b-i, §6 | `wecare-razorpay-webhook` (live **56**), `wecare-invoice-engine` (live **49**) | **OWNER CONFIRM (O10)** per function | **Live money path.** No O11 dependency (neither function was touched by the parallel session), but still a production alias move. |
| **B3** | Deploy F-4's gated sites | §5 row 4a, §6 | `wecare-checkout` (live **41**) | **STOP** | Rides with §5 item 8. Row retained only so the target is known. |
| **B4** | Deploy F-4's live sites + F-6 | §5 row 4b-ii, §6 | `wecare-whatsapp-business-api` (live **89**, `766722c7-…`) | **OWNER CONFIRM (O10)** **and blocked on O11** **and** blocked on the **v89-vs-source certification by package extraction** | The contested function. v86-v88 are uncertified against source and live is **ahead** of source on the outbound delivery contract (the parallel session's AUD-018), so a rollback could remove behaviour that session shipped. |
| **B5** | Deploy F-9's copy fix | §5 row 4c half (i), §6 | `wecare-secure-files` (live **34**, `01e8e9ef-…`) | **OWNER CONFIRM (O10)** | Production alias move. Also capture the env (`DOWNLOAD_URL_TTL_SECONDS=60`, `WHATSAPP_LINK_TTL_SECONDS=21600`, `GRANT_TTL_SECONDS=1800`, `SECURE_FILES_PAYMENT_ENABLED=false`, `DROPDOCS_ATTACH_ENABLED=false`). |
| **B6** | The single production **inspect invoke** of `wecare-meta-catalog-sync:live` with `{"inspect": true, "source": "audit"}` | §5 row 3a | `wecare-meta-catalog-sync:live` | **OWNER CONFIRM (O13)** — the invoke item, **never O10** | A production Lambda invoke, not a read. Provably write-free at `handler.py:565-572`, but O13 is narrower than O10 and **separately refusable**: the owner may authorize every deploy and still refuse this. |
| **B7** | **F-9 population count** — two `dynamodb scan --select COUNT` on `DownloadGrantsTable` (`paid AND consumed AND attribute_not_exists(expiresAt)`, and the same without the `expiresAt` clause) | §5 row 4c-read, F-9.0 | `stack-wecare-digital-DownloadGrantsTable` | `A0_READ` — **but it is a prerequisite of B8 only, not of Part A item 7** | Read-only, no mutation, no `secretsmanager`. Use `aws --cli-read-timeout 25 --cli-connect-timeout 10`. Justifies B8 if the durable count is **>= 1**; if `0`, F-9 drops to MEDIUM-latent and the copy fix (Part A item 7) is the whole of F-9 for now. |
| **B8** | **F-9 re-issue ROUTE** — `GET /files/{id}/download?reissue=1`, `REISSUE_CAP = 5` on the FILE row, the single atomic conditional update, the `ConditionalCheckFailedException` re-read mapping, and `_customer_list`'s `REDEEMED_REISSUABLE` arm | F-9, §5 row 4c half (ii) | `core/secure-files/handler.py` | **STOP** | Ships only if B7 returns >= 1 durable grant, else defers behind §5 item 8. Its six specified tests (`tests/test_vault_download_reissue.py`) belong with the route, not with the copy fix. **If it is later authorized:** the route is hosted inside the **customer** envelope at `:1827-1836` via `_customer_identity(event)` at `:1828`, and **MUST NOT** be placed in or after the `require_auth(event, "Operator")` block at `:1840`; no staff/role check may be added to a customer route. |
| **B9** | **F-11** — set `WHATSAPP_LINK_TTL_SECONDS=900` so the env states its effective value | §5 row 7, §6 | `wecare-secure-files` | **OWNER CONFIRM (O10)** | Production env write + publish + alias move. Behaviour is unchanged (`handler.py:218` already clamps 21600 → 900). Mechanism is binding: `set_lambda_env_flag.py --set … --no-publish --apply` for the env write only, then `get-alias` (capture `FunctionVersion` **and** `RevisionId`), `publish-version`, `update-alias --revision-id <captured>` so a concurrent move **fails the call**, then an **independent** `get-alias` read-back. The script's own publish/alias path (`:145-148`) passes no `RevisionId` and must not be used while the parallel session is active. |
| **B10** | **§5 item 8** — enable native checkout (`WHATSAPP_CATALOG_SERVICES_ENABLED`) | §5 row 8 | live | **STOP** | Depends on O1, O2, O3, F-2, F-3, F-9, F-10, O4, O5, O11, O12. Its F-9 prerequisite means F-9 **including** the `:1224-1225` copy site — which Part A item 7 delivers, so that one precondition is met by this plan and **no other**. F-10 additionally requires `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` in the **same** change. |
| **B11** | **§5 item 9** — enable Wix writeback | §5 row 9 | live | **STOP** | Depends on O6 + item 8. |
| **B12** | `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` and `SECURE_FILES_PAYMENT_ENABLED` | F-9.0, F-10 | live env | **STOP** | Both stay **CLOSED**. Never open a flag to make a test pass. |
| **B13** | **F-7 remainder** — the CAPI dataset half of `a739d016` | F-7 | live | **STOP** | Depends on O1 + O3 + O11. The catalog half was overtaken by the parallel session's env change (live v7, `CodeSha256` identical to v6). |
| **B14** | Meta / Wix **live reads** needing a Secrets-Manager token | §7, O1/O11/O12 | Meta Graph, Wix | **PROVIDER-BLOCKED / OWNER** | `secretsmanager get-secret-value` is denied by hook and by this plan. Includes the Graph 100/subcode-33 deletion-versus-permission question on catalog `1607047307067517`, which **requires an owner read in Business Settings (O1)**. F-1 does not resolve it and no longer claims to. |
| **B15** | **F-8** documentation reconciliation | §5 row 5 | docs | **blocked** | Gated on B6 (O13) or on a naturally-occurring Wix webhook (§5 row 3b), and **no webhook has fired since 2026-10-09T00:24:18Z**, so 3b may never arrive. Not implementable until one of the two produces the `reason`/`graphStatus`/`counts` readback. |
| **B16** | **§3 old-catalog deletion** | §3, §5 row 6 | Meta catalogs | **INVENTORY ONLY** | The inventory rows readable now are a deliverable; **no catalog, product, order, customer, file or payment record may be deleted.** |
| **B17** | **F-3** — Vault phone-only adoption | F-3 | `shared/lambda_utils/ecommerce/vault_access.py` | **follow the design's disposition — do not re-open** | Option (a) is the chosen direction and the parallel session **already applied it** to `vault_access.bind_file` in `724dcc38`. Offered-then-refused / already-upstream per the design. The unconverted half rides with §5 item 8 (STOP). |
| **B18** | Any fleet-wide deploy | §5 ordering constraint | — | **FORBIDDEN** | `scripts/deploy_all_lambdas.py` and `scripts/snapstart_publish.py` must **not** be used for any item here: `change-authority-matrix.md:1458` (table row 231) records one shared-`lambda_utils` change producing "57 updated, 3 unchanged, 0 failed, publisher moved **53** aliases", which would republish functions this audit uses as evidence. |

**Concurrency rule, binding on every B-row that moves an alias.** Another session deploys the same
functions. So every alias move must (i) re-read `get-alias` immediately before acting, (ii) pass
`--revision-id` with the just-captured value so a concurrent move **fails the call** rather than
being silently overwritten, and (iii) verify with an **independent** `get-alias` read afterwards —
not the command's exit code. Never move an alias blindly and never restore an older version from a
stale record.

---

## Stop contract for the build loop that follows

Unchanged from the design, and preserved verbatim:

> The loop stops when
> `/Users/wecaredigital/wecare-digital/wecare-digital/.worktrees/deep-integration-audit/.kiro/work/deep-integration-audit/review.json`
> has jsonPath **`verdict`** == **`APPROVED`**.

The reviewer writes that file on **every** iteration, with `"verdict": "APPROVED"` or
`"verdict": "CHANGES_REQUESTED"`, and is always the loop's last child.

## What "done" means for this plan

Part A complete = seven source fixes committed on `deep-integration-audit` with one commit per
F-item, ~30 new tests green, the whole suite green at or above the post-merge baseline, nothing
pushed, no gate opened, no production call made, and Part B recorded for the owner. The deploy half
of F-1, F-2, F-4, F-5, F-6 and F-9 is **deliberately unfinished** and owner-gated; that is the
designed end state of this phase, not a shortfall.

---

# CLOSING RECORD — Part A is complete and the branch is handed over

Written as the final action of the build. `task-deep-integration-audit/task.json` `status` is now
`completed`; all four FEAT files are `completed`.

## Final commit SHAs per F-item

Branch `deep-integration-audit`, tip **`f958c657509d3b9029a21fe62cf15e409f2451cd`**. Eleven commits
sit in `origin/stack..HEAD`: the merge, one per F-item, one owner-authorised test-fixture commit,
and two evidence commits. Verified with
`git log --format='%H %s' --name-only origin/stack..HEAD` — every commit touches only its own
item's files, and no commit bundles an unrelated repair.

| F-item | Commit | Subject | Files |
|---|---|---|---|
| — (item 1, the merge) | `bc4fcf724d24e816fa05dc958ec082832875914f` | `Merge remote-tracking branch 'origin/stack' into deep-integration-audit` — clean, no rebase, no force; brought `origin/stack` `1102da71` in and kept the design's citation anchor `061b6e77` as an ancestor of HEAD | none (merge) |
| **F-1** | `f1926b4e4549e69e59a973fc99720c2c839267ae` | `fix: report the Graph status on a catalogue read failure and give every applied:0 arm a reason` | `ecommerce/meta-catalog-sync/handler.py`, `tests/test_meta_catalog_sync_handler.py` |
| **F-5** | `aca7fdd4ec506090bd9d33dc64ff6f1f1e4f40e0` | `fix: decide a conditional failure on the money path from the error code, never the message` | `payments/invoice-engine/handler.py`, `payments/razorpay-webhook/handler.py`, `tests/test_conditional_failure_detection.py` |
| **F-2** | `2d1c7953a7fd6ddd7d93786269ba71c8ee39a2a6` | `fix: the webhook review arm yields to the native one, through a guarded payment-reference read` | `payments/razorpay-webhook/handler.py`, `tests/test_native_service_review_dedup.py` |
| — (test-fixture realism, owner-authorised as its own commit) | `d2d2f8697b05219d0cf7a451cb90636d85850d0e` | `test: seed order numbers and Cognito subjects that production could actually mint` | `tests/test_central_order_directory.py`, `tests/test_native_catalog_orchestration.py`, `tests/test_paid_submit_request.py` — tests only, measured at the unchanged-source count `10469`, so it altered no behaviour |
| **F-4** | `24b6d2ecc6f6853b81cad1cf12b32b2a50aab1fc` | `fix: one Cognito-subject predicate for all seven ListUsers filter sites` | `shared/lambda_utils/customer_auth.py`, `ecommerce/checkout/handler.py`, `flows/{catalog_services,customer_commands,customer_orders,paid_submit_request,paid_vault}.py`, `tests/test_customer_identity_filter_guard.py` |
| **F-6** | `f96fca877b1d087044b0df4a350cde0c2031bc87` | `fix: offer only public order numbers, and ask eligibility as its own question` | `shared/lambda_utils/ecommerce/paid_submit_request.py`, `flows/catalog_services.py`, `tests/test_paid_submit_request_order_labels.py` |
| **F-9 (copy half only)** | `338b2a336a41f7355e9407c11dc8f47d7c81bd51` | `fix: a paid customer is never told to pay again, at both redeem refusal sites` | `core/secure-files/handler.py`, `tests/test_secure_files.py` |
| **F-10** | `5042bd48863edf14c90d113230d0296d7b295955` | `fix: a Vault purchase that delivered neither link nor file is not VAULT_READY` | `flows/paid_vault.py`, `docs/whatsapp/native-catalog-release-status.md`, `tests/test_paid_vault_deferred_delivery.py`, `tests/test_paid_vault.py` |
| — (evidence) | `0425dce158f87a4cfb22932e20079293fc597e07`, `f958c657509d3b9029a21fe62cf15e409f2451cd` | the audit evidence log and the per-finding state record | `.kiro/work/deep-integration-audit/findings.md` |

## Final whole-suite count

```
cd /Users/wecaredigital/wecare-digital/wecare-digital/.worktrees/deep-integration-audit \
  && /Users/wecaredigital/wecare-digital/wecare-digital/.venv/bin/python -m pytest -q
```

**`1 failed, 10509 passed, 6 skipped, 3 xfailed in 112.86s`**, measured on the branch tip
`f958c657`. That reproduces the reviewer's independent run exactly and clears every gate:
`10509` ≥ FEAT-004's `10509` ≥ FEAT-003's `10502` ≥ FEAT-002's `10469` ≥ FEAT-001's post-merge
baseline `10432` ≥ the pre-merge `10342`.

**The one failure is inherited and is not ours.**
`tests/test_github_oidc_trust_policy.py::test_fixer_covers_every_oidc_role_the_repository_declares`
objects to the OIDC role `GitHubActions-wecare-digital-payment-deploy-temp-20261009`, declared by
`.github/workflows/payment-lambda-deploy-once.yml`, which arrived with upstream `4ee4c498` and is
unregistered in `scripts/fix_github_oidc_trust.ROLES` at `origin/stack` too. It is an **IAM-trust**
matter, out of scope here, and §0.3 forbids bundling an unrelated repair — so it was deliberately
**not** fixed. Confirmed again at close: this branch's post-merge diff touches **no** path under
`.github/` or `scripts/`, and upstream has since deleted the offending workflow — the file is
absent at the current `origin/stack` tip `0a59ecf8a19498741a4787e3ad90c113ff79683b`, so the failure
disappears on its own at the next integration. No action is owed here.

## Review verdict

`.kiro/work/deep-integration-audit/review.json` → **`verdict: "APPROVED"`**, `findings: []`
(full analysis in `2026-10-09-165134-review.md`). The reviewer reproduced the test numbers
independently, checked every F-item against the settled design, and confirmed the boundaries held:
nothing pushed, no deploy, no published version, no alias move, no production invoke, every named
flag still reading `false` and byte-identical, no secret value read, no broad staging, no history
rewrite, no record deleted, and no auth/ownership/isolation check weakened. The stop contract in
§"Stop contract for the build loop" is therefore satisfied and the loop is closed.

## What was deliberately NOT done — stated plainly

**The DEPLOY half of F-1, F-2, F-4, F-5, F-6 and F-9, and the whole of Part B, remain OWNER CONFIRM
or STOP and were not performed.** Specifically: no Lambda deploy, no published version, no alias
move, no production invoke, no feature flag opened (`WHATSAPP_CATALOG_SERVICES_ENABLED`, Wix
writeback, `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` and `SECURE_FILES_PAYMENT_ENABLED` all stay
**CLOSED**), no secret value read, no provider read, no F-9 re-issue route (B8), no catalog
deletion, and no push and no pull request — the branch is handed to the owner as a **local** branch
with no upstream configured.

Every fix therefore exists as **source + tests only**. The behaviour change reaches customers only
when the owner authorises the matching Part B row, each of which needs an explicit approval for the
exact target **and** its rollback immediately before acting
(`docs/execution/change-authority-matrix.md:1154`, `A3_PRODUCTION`).

**This is the designed end state of this phase, not a shortfall.** The split was decided in
`design.md` and re-affirmed in §0.2 here: the loop ships what can be verified without crossing a
production boundary, and records what cannot so that no later reader mistakes an unshipped fix for
an unfinished one. Part B rows **B1-B18** are the owner's queue, with their pre-change `live`
versions and `RevisionId` values and the binding concurrency rule (re-read `get-alias`, pass
`--revision-id`, verify with an independent read) already written down. Those version numbers are a
2026-10-09T04:32:07Z read and **must be re-read immediately before any action** — a parallel
session deploys the same functions.
