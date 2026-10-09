# Checkout deployment — closing the `/ecommerce/*` 404, with payment initiation OFF

**Date:** 2026-10-01 · **Account:** 775261844268 · **Region:** us-east-1
**HTTP API:** `zllr9lrg7j` ("wecare-digital-api"), stage `prod`, `AutoDeploy: true`
**Deployed source revision:** `4c603188fd859be28c269db0b2250f76dbb378e5` — the `origin/stack` tip
at deploy time, and what this document's measurements were taken against.

> **⚠️ `wecare-checkout:live` is now v2, published by a different session.** Every "v1 /
> `CodeSha256 917moZkE…`" statement below is a **dated measurement**, correct when taken and no
> longer live. The code changed; what this work owns did not — see
> [the v2 reconciliation](#the-alias-moved-to-v2-while-this-review-response-was-in-flight).
**`origin/stack` now:** `83a8d60d` (this work landed as `13c9f7a2`). The two are not the same, and
the difference is recorded in
[the staleness note](#the-deployed-artifact-is-now-stale-and-that-is-recorded-not-fixed) rather
than quietly closed.

`POST /api/ecommerce/checkout` returned **404** because the function behind it had never been
created. It now returns **401**. That is the whole change: a reachable, authenticating endpoint
where there was no endpoint at all.

**Deploying with the gate off created no payment capability.** Nothing here can take money, and
two independent blocks have to be removed by an owner before anything can.

---

## Status

| Task | Status |
|---|---|
| `wecare-checkout` provisioned (python3.12, v1, `live` alias) | ✅ COMPLETE — `live` since moved to **v2** by another session, [reconciled](#the-alias-moved-to-v2-while-this-review-response-was-in-flight) |
| `/ecommerce/*` routes + alias-qualified integration on `zllr9lrg7j` | ✅ COMPLETE |
| Invoke permission scoped to the two exact routes, no wildcard | ✅ COMPLETE — [narrowed twice](#the-invoke-permission-was-narrowed-twice-and-the-second-step-is-the-one-worth-reading) |
| All eight first-iteration review findings addressed | ✅ COMPLETE — [second pass](#review-response-2026-10-01-second-iteration) |
| All nine second-iteration review findings addressed | ✅ COMPLETE — [third pass](#review-response-2026-10-01-third-iteration) |
| IAM narrowing present on the branch of record, not only live | ✅ COMPLETE — all five commits are ancestors of `origin/stack`, [read off the branch](#push) |
| Import validation + closure measured against the **deployed** bytes | ✅ COMPLETE — live v2 `CodeSha256 1Ho3NbcbR3mlX8n3UBVth0wSSnBqh5OXPb1r1XETMHM=`, 0 import errors, 20-module closure |
| Scoped least-privilege IAM role, shared fleet role untouched | ✅ COMPLETE |
| `CHECKOUT_INITIATION_ENABLED` absent — initiation OFF | ✅ COMPLETE |
| Live contract verified 404 → 401, no payable attempt created | ✅ COMPLETE |
| No existing function's `live` alias moved **by this task** | ✅ COMPLETE — evidenced. But `wecare-razorpay-webhook` is now **v46**, moved by another session; the brief's "must remain v45" is [no longer satisfiable](#re-measured-2026-10-01-1426z-wecare-razorpay-webhook-is-now-v46-and-that-needs-saying-plainly) |
| `config/lambda-env-manifest.json` entry | ✅ COMPLETE |
| IaC declaration under `amplify/infra/` | ✅ COMPLETE |
| S3 bag-icon upload + provenance | ✅ COMPLETE |
| `PAYMENT_INITIATION_DISABLED` reached by an authenticated unit test | ✅ COMPLETE — `tests/test_checkout_handler.py` |
| `PAYMENT_INITIATION_DISABLED` reached by a live probe | ➖ NOT REQUIRED — structurally unreachable, and that is the [defence-in-depth](#why-payment_initiation_disabled-is-unreachable-live-and-why-that-is-correct) property, not a gap |
| Owner acceptance of that substitution | ⚠️ **NOT EVIDENCED** — an earlier unverifiable citation is withdrawn; the measurement now lives in [an artifact outside this document](snapshots/checkout-gate-ordering-20261001.json) |
| `--verify` fails on gate-off-with-readiness-set | ✅ COMPLETE — the state where "gate off" stops meaning inert now [exits 1](#finding-9-where-the-gate-is-off-stops-meaning-nothing-happens) |
| Website-Razorpay architecture direction | ✅ **DECIDED** — website Razorpay Standard Checkout + downloadable receipt. See [the ruling](#the-architecture-ruling-decided-2026-10-01) |
| Website path wired into the deployed handler | ⏳ PENDING — ruling is settled, implementation is not. Handler still imports neither `website_checkout` nor `razorpay_orders`, at `4c603188` **or** at `83a8d60d` |
| Deployed artifact current with `origin/stack` | ⚠️ **STALE** — live is `4c603188`'s package; `order_keys.py` has moved since. Harmless while inert, [must be deployed before the gate is enabled](#the-deployed-artifact-is-now-stale-and-that-is-recorded-not-fixed) |
| `dynamodb:ConditionCheckItem` on the checkout role | ➖ NOT REQUIRED — now measured against the **live** closure, not an export |
| `secretsmanager:GetSecretValue` on `wecare/razorpay/api` | ➖ NOT REQUIRED — `razorpay_orders` is unreachable on the live artifact; the role's one secret grant matches its one reachable secret reader |

---

## Before / after

| | Before | After |
|---|---|---|
| `wecare-checkout` function | `ResourceNotFoundException` | `arn:aws:lambda:us-east-1:775261844268:function:wecare-checkout`, v1, `State: Active` |
| `wecare-checkout-role` | `NoSuchEntity` | `arn:aws:iam::775261844268:role/wecare-checkout-role` |
| `live` alias | — | `arn:...:function:wecare-checkout:live` → **v1** |
| Routes on `zllr9lrg7j` | **359** | **361** (+2, none removed, none retargeted) |
| Integrations | **66** | **67** (+1: `zkb6lxe`) |
| `POST /api/ecommerce/checkout` | **404** `{"message":"Not Found"}` | **401** `{"error": "VERIFICATION_REQUIRED", ...}` |
| `POST /api/ecommerce/checkout/status` | **404** | **401** |
| `PaymentAttemptsTable` item count | **0** | **0** |
| Log group | absent | `/aws/lambda/wecare-checkout`, 30-day retention |

### Resources created

```
function    arn:aws:lambda:us-east-1:775261844268:function:wecare-checkout
            python3.12 · handler.handler · 20s · 256 MB
            CodeSha256 917moZkEBIyIzGRQvChUup2PMoWfw4Ebmr863jnQBKI=
version     1  ("initial checkout release (initiation off)")
alias       live -> v1
role        wecare-checkout-role
            managed: AWSLambdaBasicExecutionRole
            inline:  CheckoutLeastPrivilege
log group   /aws/lambda/wecare-checkout  (30 days)
integration zkb6lxe  AWS_PROXY 2.0 -> arn:...:function:wecare-checkout:live
route       508jgfp  POST /ecommerce/checkout
route       gi2dibv  POST /ecommerce/checkout/status
permission  apigateway-invoke-post-ecommerce-checkout         on :live
            SourceArn .../zllr9lrg7j/prod/POST/ecommerce/checkout
permission  apigateway-invoke-post-ecommerce-checkout-status   on :live
            SourceArn .../zllr9lrg7j/prod/POST/ecommerce/checkout/status
```

The `Qualifier` on those permissions is load-bearing. A function-level statement does not authorise
an **alias** invoke, and the failure mode is a 500 with no Lambda log line at all, because the
function is never entered — which is how `POST /plivo/dial-events` once looked deployed and was
not (`scripts/provision_missing_ui_routes.ensure_permission` records it).

### The invoke permission was narrowed twice, and the second step is the one worth reading

Initially one statement, `apigateway-invoke-checkout`, with
`SourceArn arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/*/*` — scoped to this one API, so
never a wildcard over the account, but **any stage, any method, any path**: 360 routes wider than the
two that exist. Raised in review; narrowed 2026-10-01.

The obvious replacement was the prefix `prod/POST/ecommerce/*`. It was applied, verified by probe —
and then measured against the live route list, which is where it fell down:

```
POST /ecommerce/checkout            this function
POST /ecommerce/checkout/status     this function
POST /ecommerce/customer-session    ANOTHER function, added by a concurrent session
```

So the prefix already matched a third route the moment it was written. **A prefix describes a
namespace somebody else can grow into, which is not the same as "the routes this function serves".**
It was replaced with one statement per route key, each carrying that route's exact source ARN — no
wildcard at all.

| Step | Statement id | SourceArn | State |
|---|---|---|---|
| 1 | `apigateway-invoke-checkout` | `.../zllr9lrg7j/*/*` | removed |
| 2 | `apigateway-invoke-checkout-ecommerce` | `.../prod/POST/ecommerce/*` | removed |
| 3 | `apigateway-invoke-post-ecommerce-checkout` | `.../prod/POST/ecommerce/checkout` | **live** |
| 3 | `apigateway-invoke-post-ecommerce-checkout-status` | `.../prod/POST/ecommerce/checkout/status` | **live** |

**Add-then-remove at every step, and that ordering is not cosmetic.** `add_permission` cannot *edit*
a statement, so tightening one means replacing it; remove-then-add under the same id leaves a window
in which both routes resolve to a target API Gateway is not authorised to invoke — a 500 with no
Lambda log line, the hardest failure in this system to diagnose. Resource-policy statements are
OR'd, so each narrower statement went on under a **new** id before the superseded one came off, and
at no instant was either route unauthorised. The script encodes this (`LEGACY_STATEMENT_IDS`), so
re-running it converges rather than reporting "already granted" over a stale scope.

Verified live after each step — both routes answer **401 from the handler**, which is the proof that
matters: an unauthorised invoke produces API Gateway's own `500 {"message":"Internal Server Error"}`,
never the handler's JSON.

```
POST https://wecare.digital/api/ecommerce/checkout                      401 VERIFICATION_REQUIRED
POST https://wecare.digital/api/ecommerce/checkout/status               401 VERIFICATION_REQUIRED
POST https://zllr9lrg7j.execute-api.../prod/ecommerce/checkout          401 VERIFICATION_REQUIRED
POST https://zllr9lrg7j.execute-api.../prod/ecommerce/checkout/status   401 VERIFICATION_REQUIRED
```

Before / after in `checkout-invoke-policy-before-narrowing-20261001.json` and
`checkout-invoke-policy-after-narrowing-20261001.json`. `--verify` now reads every statement back
and **fails** on a missing one, one scoped wider than its route, a superseded one left behind, or an
extra one this script did not create.

---

## The package came from `origin/stack`, and that was not a formality

The shared working tree holds three other sessions' in-flight edits, and local `HEAD` is **2
ahead / 25 behind** `origin/stack`. Measured directly, **five modules the checkout path needs
exist only on `origin/stack`** and are absent from the working tree:

```
customer_session.py                 worktree=NO   origin/stack=yes
ecommerce/website_checkout.py       worktree=NO   origin/stack=yes
ecommerce/checkout_pricing.py       worktree=NO   origin/stack=yes
ecommerce/customer_receipt.py       worktree=NO   origin/stack=yes
integrations/razorpay_orders.py     worktree=NO   origin/stack=yes
```

A package built from the working tree would have shipped a handler whose siblings were missing.
So the artifact was built from `git archive origin/stack` into `.scratch/deploy-checkout/`, and
the working tree was used only to hold the committed source changes.

#### Correction: a merge WAS run, 83 seconds after the checkout commit

This section originally read "No `merge`, `rebase`, `reset` or `stash` was run." **That is wrong as
written, and the commit graph is the authority.** Corrected rather than restated, because the
sentence was offered as the evidence that shared-tree discipline held, so it has to match what
happened.

```
4d1b396f  18:44:20  commit:         Record the website-Razorpay ruling and the checkout artifact drift
83a8d60d  18:37:12  commit (merge): Merge remote-tracking branch 'origin/stack' into stack
13c9f7a2  18:35:49  commit:         Turn the checkout 404 into an authenticating endpoint
```

`83a8d60d` merges `13c9f7a2` (parent 1, local) with `faccfbae` (parent 2, `origin/stack`). The
reflog records `commit (merge)` rather than a clean strategy merge because it conflicted, on **two**
paths — both belonging to another session:

| Path | parent 1 (`13c9f7a2`) | parent 2 (`faccfbae`) | kept in `83a8d60d` |
|---|---|---|---|
| `docs/execution/url-host-matrix-20261001.md` | `15202935` (653 lines) | `37c1b178` (670 lines) | **`37c1b178` — parent 2, the remote side** |
| `tests/test_url_host_routing_rules.py` | `13e839d6` | `bfeee3ba` | **`bfeee3ba` — parent 2, the remote side** |

Both resolutions took the remote side, which is the safer direction: those blobs were already on
`origin`, so nothing another session had pushed was discarded.

What the claim was *reaching for* is true, and is worth stating precisely because it is the property
that actually matters: **no uncommitted working-tree content entered the merge commit, and
`13c9f7a2` is intact.** `git diff-tree --cc --name-only 83a8d60d` returns nothing — no file in the
merge tree differs from both parents — and every file in `13c9f7a2` is reachable unchanged. What
did happen is that a `git merge` was needed to integrate `origin/stack` before pushing, and the
original sentence denied it. Correct reading: `commit --only` held, the packaged bytes came from
`git archive`, and no `rebase`, `reset --hard`, stash, force push or history rewrite was involved on
either side.

### Package and validation

```
112 files · 413,871 bytes · sha256 917moZkEBIyIzGRQvChUup2PMoWfw4Ebmr863jnQBKI=
imports: all resolve · 0 errors · 0 guarded warnings
tests / __pycache__ / .pyc shipped: none
non-.py members: none
```

All 16 required modules are present — `website_checkout.py`, `razorpay_orders.py`,
`checkout_pricing.py`, `order_keys.py`, `payment_attempt.py`, `order_creation.py`,
`customer_session.py`, `payment_status.py`, `customer_auth.py`, `payment_readiness.py`,
`wix_ecom.py`, `media_paths.py`, `response.py`, `logging.py`, `customer_receipt.py` and
`handler.py`.

**No templates are needed, and that is now asserted rather than assumed.** Nothing in the
package reads a `.html`/`.txt`/`.json`/`.j2` file from disk; the only non-`.py` file anywhere
under `shared/` is `config.ts`, which is irrelevant to Python.
`test_the_package_is_python_only` pins it, because "we don't need templates" is exactly the kind
of claim that silently stops being true.

**As measured at deploy time**, the live `CodeSha256` equalled the locally-computed package sha, so
what is deployed is byte-for-byte `4c603188`'s checkout path.

**That equality is no longer reproducible from `HEAD`, and that is expected rather than drift in
this document.** Two commits landed after the deploy that change the package bytes — see
[the staleness note](#the-deployed-artifact-is-now-stale-and-that-is-recorded-not-fixed). So
`deploy_all_lambdas.py wecare-checkout --dry-run` now reports `WOULD UPDATE`, which means "HEAD has
moved on", not "the deploy was wrong". The claim above can still be reproduced exactly, by
packaging the revision it names:

```
git archive 4c603188 | tar -x -C <tmp>/ && \
  .venv/bin/python scripts/provision_checkout.py --dry-run --source-root <tmp>
#   package: 112 files, 413871 bytes, sha256 917moZkEBIyIzGRQvChUup2PMoWfw4Ebmr863jnQBKI=
```

Re-confirmed on 2026-10-01 after the review, and the export is still on disk. `.scratch/deploy-checkout`
holds **`4c603188`**, not current `origin/stack` — checked by content rather than assumed, because
the directory name says nothing about its revision:

```
.scratch/deploy-checkout  lambda_utils/ecommerce/order_keys.py  sha256 82550b69…  1014 lines
4c603188                  same path                             sha256 82550b69…  1014 lines
83a8d60d / HEAD           same path                             sha256 3c3ad574…  1114 lines
```

Building from it reproduces `917moZkEBIyIzGRQvChUup2PMoWfw4Ebmr863jnQBKI=`, matching the live
`CodeSha256` byte for byte. That is also why `--verify` now defaults its closure to this export:
it is the deployed revision, and the working tree is not.

---

## Nothing became payable

> **Superseded on fact 1, 2026-10-09 — `CHECKOUT_INITIATION_ENABLED` is recorded as `"true"`.**
> This document's six "absent" claims (`:38`, this section, `:749`, `:1080`, `:1245`, `:1327`) were
> measured on 2026-10-01 and were correct then. Two later in-repo records supersede them:
> `docs/execution/snapshots/lambda-env-wix-before-site-migration-20261005.json:26` (captured
> 2026-10-05T04:28:34Z, `wecare-checkout` live alias version 20) and
> `docs/execution/xcodex-20261009/production-change-record.json:212` (dated 2026-10-09), both
> `"CHECKOUT_INITIATION_ENABLED": "true"`. The change itself is unrecorded in this repository.
>
> `requirements.md` statement 8 ("the website checkout initiation remains gated and disabled") is
> therefore in tension with the recorded live state. **Reconciling the live value is an owner
> decision; no live environment variable is changed by this note.**
>
> Facts 2, 3 and 4 below are unaffected, and fact 2 is the reason this is not an incident:
> readiness blocks independently of the gate, and both `EXPECTED_*` inputs are empty or wrong on
> `wecare-checkout`, so the website path fails closed regardless. The same 2026-10-05 snapshot
> shows `"EXPECTED_CONFIGURATION_NAME": "2094615664435155"` at line 30 — **a WABA id in the
> configuration-name slot**, where the manifest and `provision_checkout.expected_environment()`
> both declare `""`. Either value blocks (`""` → `CONFIGURATION_UNVERIFIED`, a WABA id →
> `PAYMENT_CONFIG_NAME_UNKNOWN`). It is recorded because live env and manifest have demonstrably
> drifted on exactly these keys, and because the 2026-10-09 readiness gates on
> `wecare-invoice-engine` and `wecare-outbound-whatsapp` make that same class of misconfiguration
> the difference between a working and a refusing invoice path.
>
> Note also that `scripts/provision_checkout.py` prints `initiation: OFF
> (CHECKOUT_INITIATION_ENABLED not set)` **unconditionally** — a literal, not a readback — so that
> line is not evidence of the live value. `--verify`'s non-zero exit is.

Four independent facts, each measured:

1. **`CHECKOUT_INITIATION_ENABLED` is absent from the live environment** — not `"false"`, absent.
   The live variables are exactly `PAYMENT_ATTEMPTS_TABLE`, `COMMERCE_KEYS_TABLE`,
   `WIX_API_KEY_SECRET`, `WIX_SITE_ID`, `SENDER_FUNCTION`, `PAYMENT_WABA_ID`,
   `EXPECTED_CONFIGURATION_NAME` (empty) and `EXPECTED_PROVIDER_MID` (empty).
2. **Readiness blocks independently of the gate.** Both `EXPECTED_*` inputs are empty, so
   `payment_readiness.evaluate` returns `CONFIGURATION_UNVERIFIED`. Flipping the flag alone still
   cannot produce a payable message; an owner must additionally supply both values from a live
   Meta/Razorpay readback. Two separate actions, deliberately.
3. **`PaymentAttemptsTable` holds 0 items before and 0 after** every probe. No payable attempt and
   no gateway order was created.
4. **The role grants no Razorpay credential read.** See the IAM section.

### Why `PAYMENT_INITIATION_DISABLED` is unreachable live, and why that is correct

The task asked for `POST /api/ecommerce/checkout` with `action=create` to return
`PAYMENT_INITIATION_DISABLED`. **It returns 401, and no probe can make it return
`PAYMENT_INITIATION_DISABLED`.** The handler was not changed to make the literal assertion pass;
doing so would have weakened authentication to make a probe prettier.

**Corrected, third iteration.** This paragraph previously read "Reviewed and accepted as
defence-in-depth, not as an untested branch (owner, 2026-10-01: ...)". That citation is withdrawn:
there is no artifact behind it. The architecture ruling three sections down cites commit `9e3e77cb`
and can be checked; this cited a date and a name inside the same document that was making the
claim, which is not provenance. Treat the substitution as **recorded and measured, not approved**.

What replaces the claim is a measurement, in a file that is not this one:
[`docs/execution/snapshots/checkout-gate-ordering-20261001.json`](snapshots/checkout-gate-ordering-20261001.json),
derived from the bytes on the `live` alias rather than from a working tree, with
`ownerAcceptance: NOT EVIDENCED` stated in the artifact itself. The structural facts below are also
pinned by `tests/test_checkout_gate_contract.py`, so they fail a test rather than ageing quietly in
prose. Three refusals, in execution order:

1. `handler.handler` calls `customer_auth.require_customer(event)` **first**, before parsing the
   body. An unauthenticated or invalidly-authenticated request gets an opaque 401 and never
   enters `_create`. Checkout is correctly not a public endpoint.
2. Inside `_create`, `payment_readiness.evaluate` runs **before** the `if not INITIATION_ENABLED`
   branch. With both `EXPECTED_*` empty it returns `CONFIGURATION_UNVERIFIED`, so the response is
   **409 `payment_unavailable`**, short-circuiting ahead of the gate.
3. Only then does the gate itself answer `PAYMENT_INITIATION_DISABLED`.

Reaching layer 3 live would need a real customer Cognito access token **and** owner-supplied
readiness values. Minting a customer token is not authorised here, and the readiness values are
owner-only. **So the measured live contract change is 404 → 401**, and the branch is reached
where it can be reached honestly: in a unit test with an authenticated fixture.

#### The gate is the LAST check in `_create`, not the first — so it is inert as to money, not as to side effects

Worth stating plainly, because the recorded `PaymentAttemptsTable` 0-before / 0-after is true for a
different reason than a reader might assume. Measured order inside `_create` in the deployed handler
(line offsets within the function):

```
+12  wix_ecom.create_checkout(line_items)      <- a LIVE Wix write
+13  wix_ecom.checkout_currency(checkout)         currency compared explicitly against "INR"
+30  _readiness()                             <- layer 2 refuses here today
+43  order_keys.allocate_payment_reference()      reserves PAYREF#
+65  _attempts_table().put_item(...)              writes the PaymentAttempt row
+76  if not INITIATION_ENABLED:                <- layer 3, the gate
```

The table is empty because **`require_customer` refused every probe at the door**, and readiness
would have refused behind it — not because the gate short-circuits early. This is pre-existing
handler code, outside the scope of this change, but it determines what the next step in the sequence
looks like:

> Once an owner supplies `EXPECTED_CONFIGURATION_NAME` and `EXPECTED_PROVIDER_MID` — **with
> `CHECKOUT_INITIATION_ENABLED` still off** — an authenticated `action=create` will create a Wix
> checkout and write a `PaymentAttempt` row on **every** call, then answer
> `PAYMENT_INITIATION_DISABLED`.

No money can move: no gateway order is created, no payable message is sent, and the role grants no
Razorpay credential read. But "the gate is off" stops meaning "nothing happens" at that point, and
the attempt table will accumulate rows from refused creates. The phrase "gate-off prepares attempts"
elsewhere in this document is accurate and easy to skim past; this is the explicit version.

#### The branch IS exercised, with an authenticated fixture

`tests/test_checkout_handler.py::test_create_disabled_prepares_attempt_but_sends_nothing_and_makes_no_order`
stubs `customer_auth.authenticate` to return a `CustomerIdentity`, sets readiness to pass
(`EXPECTED_CONFIGURATION_NAME='WECAREDIGITAL'`, `EXPECTED_PROVIDER_MID='acc_TESTMID'`) and pins
`INITIATION_ENABLED=False` — so it enters the exact branch a live probe cannot, and asserts the
properties that matter rather than just the status string:

- `status == 'PAYMENT_INITIATION_DISABLED'`, `amountPaise == 59900` (Wix's authoritative 599.00 in
  integer paise), `currency == 'INR'`
- exactly **one** attempt row, bound to the customer, `checkoutMode == 'WIX_HEADLESS'`,
  `status == 'PAYMENT_READINESS_CHECKED'`
- a `PAYREF#` reservation exists, and **no** `ORDERNO#`, `PAYMENTATTEMPT#` or `PROVIDERPAYMENT#`
  row does — so no order was created
- the only internal invoke was the readiness payment-config read; **no** `send` path was invoked,
  so no payable message went out

`tests/test_razorpay_binding.py` covers the same state on the website path
(`wc.PAYMENT_INITIATION_DISABLED`). Between them the branch is covered for both flows; what is
absent is only a live HTTP observation of it, which is prevented by layers 1 and 2 above.

---

## Live probes (every code measured, not inferred)

| Probe | Before | After |
|---|---|---|
| `POST https://wecare.digital/api/ecommerce/checkout` | 404 | **401** |
| `POST https://wecare.digital/api/ecommerce/checkout/status` | 404 | **401** |
| `POST https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/ecommerce/checkout` | 404 | **401** |
| `POST .../prod/ecommerce/checkout/status` | 404 | **401** |
| `POST /api/ecommerce/checkout` with `Authorization: Bearer <invalid>` | — | **401**, JSON body |
| `POST /api/ecommerce/checkout/status` with a foreign `paymentAttemptId` | — | **401**, JSON body |
| `OPTIONS /api/ecommerce/checkout` preflight | — | **204** + `access-control-allow-origin: https://wecare.digital` |

After-body on all four checkout probes:

```json
{"error": "VERIFICATION_REQUIRED", "message": "Please verify your WhatsApp number to continue."}
```

Two details worth keeping:

- **The raw-API probe needs `/prod`.** `prod` is the only stage on `zllr9lrg7j`; there is no
  `$default`. A probe to `https://zllr9lrg7j.execute-api.../ecommerce/checkout` returns 404 even
  now, and that 404 means "no such stage", not "no such route". Reading it as a route failure
  would send someone looking in the wrong place.
- **A foreign `paymentAttemptId` returns the identical opaque 401** to an unauthenticated
  request, so the endpoint is not an IDOR oracle: a real attempt id and a fabricated one are
  indistinguishable from outside.

### Direct invokes

| Probe | Result |
|---|---|
| `wecare-checkout:live` with an `OPTIONS` event | `StatusCode 200`, `FunctionError: null` |
| `wecare-checkout:live` with a `POST` event, no `Authorization` | `StatusCode 200`, handler `401` |

The first is the **packaging proof**. A cold start executes every top-level import, so a module
missing from the ZIP surfaces here as `Unable to import module 'handler'`. It did not.

### Retained paths still work

| Path | Before | After |
|---|---|---|
| `POST /api/razorpay-webhook` | 401 | **401** |
| `POST /api/auth/validate` | 401 | **401** |
| `GET /api/webhook/sinch-rcs` | 200 | **200** |
| `GET /mcp` | 405 | **405** |
| `GET /get/o/public/wa-tpl/docs/wecare-digital-011f1811_Insurance.pdf` | — | **200** `application/pdf` |
| `GET /cart` (followed) | 200 | **200** |

### No existing alias moved

| Function | Before | After |
|---|---|---|
| `wecare-razorpay-webhook` | **v45** | **v45** |
| `wecare-whatsapp-business-api` | v57 | v57 |
| `wecare-contacts` | v26 | v26 |
| `wecare-outbound-whatsapp` | v43 | v43 |
| `wecare-invoice-engine` | v39 | v39 |

`scripts/deploy_all_lambdas.py` was **never run without a target**. One function was created; no
existing function's code, configuration or alias was touched by this task.

#### Re-measured 2026-10-01 14:26Z: `wecare-razorpay-webhook` is now v46, and that needs saying plainly

The brief named v45 as the value to confirm, and it is no longer v45.

| Function | Review pass | 14:26Z | Moved by |
|---|---|---|---|
| `wecare-razorpay-webhook` | v45 | **v46** | another session |
| `wecare-whatsapp-business-api` | v57 | v57 | — |
| `wecare-contacts` | v26 | v26 | — |
| `wecare-outbound-whatsapp` | v43 | v43 | — |
| `wecare-invoice-engine` | v39 | v39 | — |
| `wecare-checkout` | v2 | v2 | another session (v1 → v2, earlier) |

Attribution, because "not me" is a claim that has to be evidenced rather than asserted:

```
$ aws lambda list-versions-by-function --function-name wecare-razorpay-webhook
46  2026-10-01T14:12:34Z        <- published during this session's window
45  2026-09-30T06:07:02Z

$ aws cloudtrail lookup-events --lookup-attributes \
      AttributeKey=EventName,AttributeValue=UpdateFunctionCode20150331v2 \
      --start-time 2026-10-01T14:00:00Z
wecare-ai-generate-response   2026-10-01T14:23:40Z
wecare-ai-query-kb            2026-10-01T14:23:40Z
wecare-faq-handler            2026-10-01T14:23:39Z
wecare-seo-tools              2026-10-01T14:16:00Z
wecare-razorpay-webhook       2026-10-01T14:12:34Z
```

Five functions had their code replaced inside this session's window and none of them is
`wecare-checkout`. The IAM user is shared, so `wecare-admin` in CloudTrail does not discriminate
between sessions — the discriminating facts are these:

- `scripts/provision_checkout.py` contains **zero** occurrences of the string
  `razorpay-webhook`, and exactly one `publish_version` call, inside `ensure_live_alias`, keyed on
  `FUNCTION_NAME = "wecare-checkout"`.
- The only invocation of it this iteration was `--verify`, which returns through `verify()` and
  reaches no `ensure_*` function at all.
- `amplify/functions/payments/razorpay-webhook/handler.py` is on this task's DO-NOT-TOUCH list and
  is owned by another session; `wecare-seo-tools` is deployed by `scripts/deploy_seo_tools.py`,
  which this task never ran. Four of the five are plainly that other work.

What this means for the brief's instruction is worth stating rather than glossing: **the
"must remain v45" condition is not satisfied, and cannot be re-satisfied from here.** Rolling the
alias back to v45 would revert another session's deployed payment-webhook fix, which is a far worse
action than recording the drift. The condition's *purpose* — that this task moves no existing
function's alias — does hold, and is evidenced above. The only alias this task has ever created or
moved is `wecare-checkout:live`.

### Route surface diff

```
before 359  after 361
added      508jgfp  POST /ecommerce/checkout
           gi2dibv  POST /ecommerce/checkout/status
removed    none
retargeted none
```

**Now 362, and the extra route is not ours.** Re-measured during the review follow-up and diffed
against `checkout-routes-after-20261001.json` key by key:

```
added since the after-snapshot:   POST /ecommerce/customer-session
removed since the after-snapshot: none
```

A concurrent session added it (`.agents/tasks/customer-session-20261001/`); it targets a different
function's integration. Recorded because the count in the table above will not match a fresh read,
and because it is the measurement that condemned the `/ecommerce/*` prefix — see the narrowing note.
The live `ecommerce` route keys are now three, two of which are this function's.

### Logs

`/aws/lambda/wecare-checkout` over 7 invocations shows `START` / `END` / `REPORT` only — **zero
application log lines**, because every request stopped at the 401, which does not log. No phone
number, no amount tied to an identity, no credential-shaped material, no import error.

---

## IAM: what was granted, and what deliberately was not

`wecare-checkout-role`, inline policy `CheckoutLeastPrivilege`:

| Sid | Action | Resource |
|---|---|---|
| `ReadWixApiKey` | `secretsmanager:GetSecretValue` | `wecare/wix/headless-api-key-*` |
| `PaymentAttemptAndCommerceKeys` | `dynamodb:GetItem`, `PutItem`, `UpdateItem` | the two named tables only |
| `InvokeWhatsAppSender` | `lambda:InvokeFunction` | `wecare-whatsapp-business-api` and `:live` |

Four deliberate omissions:

- **No `dynamodb:DeleteItem`.** A failed attempt is the evidence that no charge became an order.
- **No Cognito action.** `customer_auth.authenticate` calls `GetUser` with the **customer's own**
  access token, which authorises itself. An IAM grant would be privilege the function cannot use.
- **No `secretsmanager:GetSecretValue` on `wecare/razorpay/api`.** See below.
- **No wildcard, and `wecare-digital-lambda-role` was not touched.** That role is shared by ~65
  functions; a statement added for checkout would widen every one of them. Its 16 inline policy
  names are snapshotted unchanged for a later diff.

### `dynamodb:ConditionCheckItem` — measured, and NOT required

`iam simulate-principal-policy` against the new role, both table ARNs:

```
dynamodb:GetItem            allowed
dynamodb:PutItem            allowed
dynamodb:UpdateItem         allowed
dynamodb:ConditionCheckItem implicitDeny   <- and not required
```

`ConditionCheckItem` is only ever required inside `TransactWriteItems` / `TransactGetItems`. A
plain `put_item`/`update_item` carrying a `ConditionExpression` needs `PutItem`/`UpdateItem` and
nothing more — and that is all `order_keys` and `payment_attempt` use. **No grant was made and
none is needed.**

One correction worth recording, because the first version of this check was wrong in the
dangerous direction. The detector initially scanned the whole 112-file ZIP and reported a
`REQUIRED GRANT`, because `build_zip` ships the entire `lambda_utils` tree without pruning and
`crm/service.py` and `notifications/store.py` both use `TransactWriteItems`. **Neither is
imported by checkout.** The handler's import closure is **18 of the 112 packaged files** and
contains no transaction call at all. The check now walks that closure:

```
handler.py                              lambda_utils/http_path.py
lambda_utils/__init__.py                lambda_utils/identifiers.py
lambda_utils/customer_auth.py           lambda_utils/logging.py
lambda_utils/ecommerce/__init__.py      lambda_utils/middleware.py
lambda_utils/ecommerce/money.py         lambda_utils/payment_readiness.py
lambda_utils/ecommerce/order_keys.py    lambda_utils/rate_limit.py
lambda_utils/ecommerce/payment_attempt.py  lambda_utils/response.py
lambda_utils/ecommerce/wix_domain.py    lambda_utils/template_ttl.py
lambda_utils/validation.py              lambda_utils/wix_ecom.py
```

A grant report that cries wolf is one nobody reads, which is the same reasoning the inline-secret
hook is built on. `report_required_grants` **only simulates** — it holds no
`put_role_policy`/`attach_role_policy` call, pinned by
`test_the_grant_report_only_simulates`.

### The required grant I deliberately did not make

```
secretsmanager:GetSecretValue  on  arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/razorpay/api-*
```

`razorpay_orders.RAZORPAY_SECRET_ID` defaults to `wecare/razorpay/api`, and the module ships in
the ZIP — but **nothing in the handler's import closure reaches it** (see the 18 files above).
Granting a Razorpay credential read to code that cannot run widens privilege for zero benefit.
This is the prerequisite grant for the website-Razorpay path, to be made at the moment that path
is wired, and not before. `test_the_role_grants_no_razorpay_credential_read` pins the current
state so adding it has to be a deliberate edit.

---

## Three findings a reader needs

### 1. The website Razorpay path ships but is NOT wired in

At `4c603188`, `handler.py` mentions `website_checkout` and `razorpay_orders` **only in its
docstring**. Its top-level imports are `customer_auth`, `payment_readiness`, `order_keys`,
`payment_attempt`, `wix_ecom`, `logging`, `response` — confirmed by the 18-file import closure.
`_action` dispatches `create` and `status` and nothing else.

**Re-measured at `83a8d60d` after the merge: still true.** The import list is unchanged, so the
additive website contract (`CHECKOUT_OPTIONS_READY`, the callback with HMAC-over-stored-order-id
plus authoritative capture) is present in the artifact and still unreachable.

The architecture question that blocked it has since been answered, which changes the status from
"undecided" to "decided and not yet implemented" — see below. Both paths remain behind the same
`CHECKOUT_INITIATION_ENABLED` gate, off.

### The architecture ruling (decided 2026-10-01)

**Website Razorpay Standard Checkout + downloadable receipt.** Recorded in commit `9e3e77cb`
*"docs: reconcile checkout spec to website-only Razorpay ruling (FEAT-004)"*, which updated
`requirements.md`, `design.md` and `tasks.md`.

This supersedes the spec statements this deployment was written against. The earlier
"WhatsApp-only receipts" and "payment collected externally via WhatsApp" language is **retired**,
not merely overridden. Owner confirmation in session: WhatsApp stays as the support widget, OTP
sign-in, and authorised receipt/order notifications — it is **out of the purchase flow**. Commit
`b6646345` retired the in-WhatsApp payment-capture side effects on that basis.

Two things the ruling does **not** change, and both were re-confirmed with it:

- `CHECKOUT_INITIATION_ENABLED` stays **OFF**. Enabling it is owner-only and still ungranted.
- **No live monetary test** happens until the owner authorises it separately.

So the consequence for this deployment is narrow and worth stating plainly: the deployed function
is unaffected, because the website path it would run is not wired into the handler yet. The ruling
unblocks that implementation work; it does not retroactively change what was deployed. Note also
that `.kiro/steering/whatsapp-payments-india-reference.md` still describes the in-WhatsApp
posture — steering has not been reconciled to `9e3e77cb`, and whoever wires the website path
should expect to resolve that, since steering outranks a spec on conflict.

### The deployed artifact is now stale, and that is recorded, not fixed

Measured after the merge. The live function still runs the package built from `4c603188`; HEAD is
now `83a8d60d`:

```
live  CodeSha256  917moZkEBIyIzGRQvChUup2PMoWfw4Ebmr863jnQBKI=   112 files  413,871 bytes
HEAD  package     OU+pzkX/hi4/5lSYEsA8FlBDhjaFXzOV2HooSeSzk8o=   114 files  419,158 bytes
```

What moved, and whether it matters:

| File | Change | In the deployed import closure? |
|---|---|---|
| `lambda_utils/ecommerce/order_keys.py` | +100 lines: `claim_legacy_invoice_payment`, `release_legacy_invoice_payment_claim` (commits `86c36f43`, `72a68e31`) | **Yes** |
| `lambda_utils/integrations/razorpay_verify.py` | +23 lines | No |

`order_keys` **is** one of the 18 files the handler reaches, so this is real drift and not a
cosmetic hash difference. It is harmless **today** for one reason only: the function is inert.
Every request is refused at `customer_auth` before any `order_keys` call, so no code path that
differs between the two revisions can execute.

**It must be deployed before `CHECKOUT_INITIATION_ENABLED` is enabled.** One command, and it
reports the drift itself rather than relying on this note being read:

```
.venv/bin/python scripts/deploy_all_lambdas.py wecare-checkout --dry-run
#   packaged 114 files, 419158 bytes
#   WOULD UPDATE: 917moZkEBIyI... -> OU+pzkX/hi4/...
# then, to apply (publishes a version and moves the live alias for THIS function only):
.venv/bin/python scripts/deploy_all_lambdas.py wecare-checkout
```

Not done here deliberately: the task scope was to create the function with the gate off and verify
the contracts, and a code update plus an alias move from v1 to v2 is a separate action with no
benefit while the function cannot execute the changed code. Recording a known-stale artifact is
safer than a silent redeploy outside the reviewed scope.

### 2. The Razorpay credential read is lazy, but a rotation still needs a republish

`razorpay_orders._credentials()` reads `wecare/razorpay/api` inside a function at request time,
**not** at module scope — so it does not break the init-time rule in `lambda-snapstart-deploy`.
`test_the_handler_reads_its_payment_credential_lazily` asserts it over the AST.

But it caches into a module global `_cached`, which lives for the life of the execution
environment. A warm sandbox keeps serving the old value after a rotation. So a rotation of
`wecare/razorpay/api` still requires `scripts/refresh_secret_consumers.py wecare/razorpay/api`
to recycle the consumers. This is a correctly-written lazy read with a real operational
consequence, not a defect.

### 3. Working-tree test failures are foreign, and the committed tree is green

Measured three times, because "the tests fail" needs a scope before it means anything.

| Tree | Result |
|---|---|
| `4c603188` (deployed revision) + this commit's changes | **5726 passed, 3 skipped, 0 failed** |
| `83a8d60d` (merged `origin/stack`), clean `git archive` | **5757 passed, 1 skipped, 0 failed** |
| live working tree at the same HEAD | **22 failed, 5735 passed** |

Re-measured after the review follow-up, same conclusion:

| Tree | Result |
|---|---|
| `643a86e0` (this work's tip), clean `git archive` | **5773 passed, 7 skipped, 0 failed** |
| live working tree at the same HEAD | **22 failed, 5757 passed** |

Six of the seven skips are the new `committed` fixture declining to run when the suite is *already*
executing from an export — see the note below. The 22 working-tree failures are the same foreign
cluster, now across five files (`test_razorpay_webhook_captured_gating.py`,
`test_legacy_invoice_settlement_safety.py`, `test_quarantine_recovery.py`,
`test_razorpay_webhook_order_creation.py`, `test_order_creation.py`), every one raising
`AttributeError: module 'lambda_utils.ecommerce.order_creation' has no attribute
'NEEDS_RECONCILIATION'` from the uncommitted `order_creation.py` on this task's DO-NOT-TOUCH list.
`test_payment_vocabulary_at_decision_points.py` now passes and has left the cluster.

#### A trap worth recording: `git archive` from a subdirectory succeeds at doing nothing

Found while verifying the review-response commit the way everything here is verified — export `HEAD`
and run the suite against it. All six `committed` tests errored with `tarfile.ReadError`.

`git archive` run from a subdirectory **restricts its output to that subdirectory**. The fixture
passed `git -C ROOT`, and when the suite runs from an export, `ROOT` is a gitignored directory
*inside* the repository — so git resolved the parent repo, found no tracked files under that path,
and emitted a valid-but-empty 10,240-byte tar with **exit 0 and no stderr**. `check=True` cannot
catch a command that succeeded at doing nothing, which is the same failure shape as the grant report
that printed a finding and exited 0.

Fixed by resolving `rev-parse --show-toplevel` first and skipping with a stated reason when it is not
`ROOT`: a suite running from an export is already testing committed state, so a second build of it
asserts nothing. When `ROOT` is the toplevel, `git archive` runs with `cwd` at the toplevel, the tar
is opened as uncompressed rather than left to autodetect, and the extracted tree is checked for the
handler before use.

The committed tree is green at both revisions. Every working-tree failure traces to one
uncommitted file belonging to another session —
`amplify/functions/shared/lambda_utils/ecommerce/order_creation.py`, on this task's
DO-NOT-TOUCH list — and the failures are confined to `test_razorpay_webhook_captured_gating.py`,
`test_razorpay_webhook_order_creation.py`, `test_order_creation.py` and
`test_payment_vocabulary_at_decision_points.py`.

None of this task's 14 paths is dirty; all match HEAD. The practical point for a reader: run the
suite against a clean archive before concluding anything from a red local run, because in this
shared tree a red run is the normal state rather than a signal.

---

---

## The alias moved to v2 while this review response was in flight

Caught by the final `--verify`, which printed `live v2` where every earlier measurement said `v1`.
Measured, not inferred:

```
$LATEST  1Ho3NbcbR3mlX8n3UBVth0wSSnBqh5OXPb1r1XETMHM=  13:49:45Z
v2       1Ho3NbcbR3mlX8n3UBVth0wSSnBqh5OXPb1r1XETMHM=  13:49:45Z
         "Checkout completion review - session, catalogue and canonical link fixes"   <- live
v1       917moZkEBIyIzGRQvChUup2PMoWfw4Ebmr863jnQBKI=  10:48:01Z
         "initial checkout release (initiation off)"
```

**Not this session.** The v2 description names a different piece of work, and this session published
no version: `ensure_live_alias` returns `exists` once the alias is there, and the only live mutations
made here were the invoke-permission statements. A concurrent session ran a code update and moved the
alias — which is the normal deploy path for a function that now exists, and exactly what
`.kiro/steering/multi-session-parallel-agents.md` says to expect from a shared tree.

**It does not disturb anything this work is responsible for**, and each of those was re-measured
against v2 rather than assumed:

| Property | On v2 | How |
|---|---|---|
| `CHECKOUT_INITIATION_ENABLED` | **absent** | `get-function-configuration --qualifier 2` |
| `EXPECTED_CONFIGURATION_NAME` / `EXPECTED_PROVIDER_MID` | both `''` | same |
| Execution role | `wecare-checkout-role` (unchanged) | same |
| Runtime | `python3.12` | same |
| The two per-route invoke statements | present, exact ARNs | `get-policy --qualifier live` |
| Both routes reachable | **401 from the handler** | live probe |
| `PaymentAttemptsTable` | **0 items** | `scan --select COUNT` |

The probe result is the load-bearing one: an alias-level resource policy is independent of the
version the alias points at, so a version move cannot invalidate the narrowed permissions — and the
handler's `401` JSON (rather than API Gateway's own `500 {"message":"Internal Server Error"}`) is the
proof that API Gateway was still authorised to invoke after the move.

**What cannot be reproduced here**, stated rather than guessed: v2's `CodeSha256` matches none of the
three packages this session can build.

```
live v2                     1Ho3NbcbR3mlX8n3UBVth0wSSnBqh5OXPb1r1XETMHM=
git archive HEAD            6rZOb4KeOvbvst2yTBYBsgQNbsYfHx01f7ng6oVeXRM=   112 files
the working tree, now       c6KXs2i3KMjgOQh+l0Idz7UMJqrIKbYsh54S0WUcJ9A=   114 files
v1 (this work's deploy)     917moZkEBIyIzGRQvChUup2PMoWfw4Ebmr863jnQBKI=   112 files
```

The working tree has kept moving since 13:49 — three more files changed under
`lambda_utils/` while this response was being written — so a non-match proves nothing beyond
"not reproducible from here now". Identifying v2's source revision belongs to the session that
published it. The practical consequence for a reader: **the
[staleness note](#the-deployed-artifact-is-now-stale-and-that-is-recorded-not-fixed) is superseded as
to its remedy** — `order_keys.py` is no longer the gap, because newer code has since shipped — while
its rule stands unchanged: verify what is on `live` immediately before the gate is enabled, rather
than trusting any sha recorded in a document.

---

## Review response (2026-10-01, second iteration)

Eight findings, two of them blocking. All eight addressed; nothing required a redeploy, because the
provisioner is not packaged into the Lambda and the one live change was an IAM tightening.

| # | Finding | What changed |
|---|---|---|
| 1 | **Blocking.** The grant report printed `REQUIRED GRANT` and the script still exited 0 | `verify()` now does `problems.extend(report_required_grants(members))`. See below |
| 2 | **Blocking.** The document asserted no merge was run; the commit graph says otherwise | [Corrected, with both conflicted paths and which side won](#correction-a-merge-was-run-83-seconds-after-the-checkout-commit) |
| 3 | The `CodeSha256` equality claim is no longer reproducible from `HEAD` | Dated, with the command that still reproduces it, and the export's revision verified by content |
| 4 | The gate is the last check in `_create`, not the first | [Stated explicitly, including what happens once readiness is supplied](#the-gate-is-the-last-check-in-_create-not-the-first--so-it-is-inert-as-to-money-not-as-to-side-effects) |
| 5 | `--verify` reasoned about whichever root it was given, defaulting to the dirty tree | Defaults to the recorded deploy export, and **prints which root produced the verdict** either way |
| 6 | The invoke permission's `SourceArn` was API-wide | [Narrowed twice, to one exact statement per route](#the-invoke-permission-was-narrowed-twice-and-the-second-step-is-the-one-worth-reading) |
| 7 | `_not_found(exc, "ResourceConflictException")` read as a not-found check | Site removed. `ensure_invoke_permission` now *reads* the policy instead of provoking a conflict, so there is no error code to misname |
| 8 | The completeness tests build from `ROOT`, so they assert over other sessions' uncommitted files | A second `committed` fixture builds the same package from `git archive HEAD`; the completeness assertions run against both |

### Finding 1: a gate that cannot fail is not a gate

`report_required_grants` built its `required` list, printed it, returned it — and `verify()` dropped
the return value. The plan required a non-zero exit in exactly that case. Latent while the verdict is
"not required", and wrong precisely when the condition the check exists for becomes true: an operator
wiring the website Razorpay path pulls `razorpay_orders` into the import closure, gets a function
missing a permission, and a gate reporting success.

Three shapes of "we do not know" were also returning `[]`, indistinguishable from "measured, found
nothing". All four are now problems:

| Condition | Was | Now |
|---|---|---|
| a `ConditionCheckItem` grant is genuinely needed | printed, exit 0 | problem, **exit 1** |
| `simulate_principal_policy` raised | printed "verdicts not measured", exit 0 | problem naming the error code |
| the role could not be read | printed "role absent", exit 0 | problem |
| `members is None` — the package could not be rebuilt, so the closure was never walked | treated as the empty list | problem, `NOT JUDGED` |

A fifth check was added while the function was open: `GetItem`/`PutItem`/`UpdateItem` are granted
outright by `CheckoutLeastPrivilege`, so a deny verdict on any of them means the live role is not what
this script wrote and the function cannot record a payment attempt at all.

Demonstrated end to end against the live account rather than only asserted — with
`report_required_grants` stubbed to return one finding, `verify()` returns **1**; unstubbed it returns
**0**:

```
FAIL:
  - dynamodb:ConditionCheckItem on table/X - needed by lambda_utils/synthetic.py: TransactWriteItems
verify() -> 1
```

Six new tests in `tests/test_provision_checkout_contract.py` drive `report_required_grants` with a
stubbed IAM client across all five conditions, plus one that pins the `problems.extend(...)` wiring
itself. The function still only simulates — `test_the_grant_report_only_simulates` is unchanged.

### Finding 5: the verdict names its own source tree

`--verify` rebuilds the package to decide what the import closure contains. Without `--source-root`
it rebuilt from the working tree, so the closure judged was not the deployed artifact's — and this
tree currently carries `order_creation.py` modified plus `finalization.py` and `initiation.py`
untracked, all of which `build_zip` packages.

`resolve_source_root` now returns a reason alongside the path, and both modes print it:

```
grant report closure: /Users/wecaredigital/wecare-store/.scratch/deploy-checkout
                      (the recorded deploy export — what the live artifact was built from)
```

The fallback is labelled too, because `.scratch/` is gitignored and simply absent on a fresh
checkout: `(this WORKING TREE, not the deployed artifact: it may carry other sessions' uncommitted
edits, and build_zip packages them)`. A provisioning run still defaults to the working tree — it
packages what the operator points it at — and prints the same line.

### Finding 8: two source roots, because one of them is not enough

`tests/test_checkout_package_completeness.py` builds from `ROOT`, which is correct for its question
("would a package built from this repository today be complete") and genuinely coupled to other
sessions' in-flight edits. Rather than drop the working-tree build, a `committed` fixture exports
`git archive HEAD` to a temp directory and builds the same package from it. Completeness, import
resolution, no-junk, python-only and the handler symbol are now asserted against both. The
working-tree build still catches a packaging rule that started dropping a file; the committed build
is the one whose result anyone can reproduce from a SHA. It skips rather than fails where `git` is
unavailable.

---

## Review response (2026-10-01, third iteration)

Nine findings, one blocking. The blocking one resolved itself in the right way — the orchestrator
pushed — but the other eight were all `confirmed`, and six of them described a check that could not
fail. That is the same defect in six costumes, and it is the one worth fixing properly rather than
answering.

| # | Finding | Resolution |
|---|---|---|
| 1 | IAM narrowing unpushed; the branch would re-widen the grant | **Resolved on the remote.** All three commits are now ancestors of `origin/stack`, read off the branch and verified by AST. [Push](#push) rewritten — it had reported the *first* iteration's resolution as the whole story |
| 2 | `import_closure` drops relative imports | `resolve_relative_import` added; the walker follows `from .x`, `from ..x` and bare `from . import x`. Live closure 19 → **20** modules |
| 3 | Live v2's import closure never measured | `live_members()` downloads the artifact off the alias; `--verify` now validates and closures **the deployed bytes**, not a local export |
| 4 | `PAYMENT_INITIATION_DISABLED` substitution had no external artifact | The unevidenced "owner, 2026-10-01" citation is **withdrawn**. Replaced by a measured artifact outside this document, plus 5 tests pinning the structure |
| 5 | `test_no_float_arithmetic_on_the_money_path` skipped absent modules | Presence asserted before parsing; a dropped money module now **fails** |
| 6 | Two property tests ran only against the working tree | Both parametrised over `working-tree` **and** `committed` |
| 7 | The lazy-secret test's reach was narrower than its claim | Rewritten to walk every import-time statement in **every** packaged module |
| 8 | `--verify` did not check `WIX_SITE_ID` | The key list is **derived** from `expected_environment()`, so it cannot drift |
| 9 | `--verify` exited 0 on gate-off-plus-readiness-set | That combination is now a **problem**, with the reason in the message |

### Finding 3 is the one that changes what `--verify` means

Before this iteration, `--verify` read live configuration and judged a local package in the same
breath. The seam was invisible because both halves printed under one heading. It now downloads the
artifact from the `live` alias and scopes every package-derived verdict to those bytes:

```
$ python scripts/provision_checkout.py --verify
comparison package built from: .scratch/deploy-checkout (the recorded deploy export)
function: present (live v2)
initiation: OFF (expected)
readiness inputs: empty — blocks regardless of the gate
route POST /ecommerce/checkout:        -> ...function:wecare-checkout:live
route POST /ecommerce/checkout/status: -> ...function:wecare-checkout:live
routes on zllr9lrg7j: 362 total, stage prod
invoke permission apigateway-invoke-post-ecommerce-checkout:
    arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/prod/POST/ecommerce/checkout
invoke permission apigateway-invoke-post-ecommerce-checkout-status:
    arn:aws:execute-api:us-east-1:775261844268:zllr9lrg7j/prod/POST/ecommerce/checkout/status
live artifact (v2): 113 files, 417093 bytes, sha256 1Ho3NbcbR3mlX8n3UBVth0wSSnBqh5OXPb1r1XETMHM=
  imports on the live artifact: all resolve (0 guarded warning(s))
  reachable from handler.py on live: 20 of 113 packaged modules
  NOTE live artifact differs from the compared export: 1 file(s) only on live, 0 only in the export
  grant report scoped to the LIVE artifact (CodeSha256 1Ho3NbcbR3mlX8n3UBVth0wSSnBqh5OXPb1r1XETMHM=)
iam dynamodb:GetItem:            allowed
iam dynamodb:PutItem:            allowed
iam dynamodb:UpdateItem:         allowed
iam dynamodb:ConditionCheckItem: implicitDeny  (not required: no TransactWriteItems/
    TransactGetItems anywhere in the handler's import closure)

checkout provisioning verified (initiation disabled)
```

**The v2 package had never been measured by anyone, and now it has.** What the measurement says,
recorded in [`checkout-live-closure-20261001.json`](snapshots/checkout-live-closure-20261001.json):

| | |
|---|---|
| Live `CodeSha256` | `1Ho3NbcbR3mlX8n3UBVth0wSSnBqh5OXPb1r1XETMHM=` |
| Files | 113 (the recorded v1 export is 112) |
| The one extra file | `lambda_utils/customer_session_store.py` — **not** in the reachable closure, so it moves no verdict |
| Import validation on the live bytes | 0 errors, 0 warnings |
| Reachable from `handler.py` | 20 of 113 |
| `razorpay_orders` reachable? | **no** |
| `website_checkout` reachable? | **no** |
| Transaction call sites in the closure | none |
| `dynamodb:ConditionCheckItem` | `implicitDeny`, and genuinely not required |

So the two deliberate IAM omissions are still correct **as measured against production**, not as
inferred from an export. One result is worth pulling out, because it is a stronger statement than
anything in the previous passes:

> Six packaged modules read a secret. Exactly **one** of them is reachable from the live handler:
> `lambda_utils/wix_ecom.py`. And `wecare/wix/headless-api-key` is exactly the one secret
> `CheckoutLeastPrivilege` grants. The role's single secret grant matches the single reachable
> reader, with nothing spare on either side.

A detail on how the artifact is fetched, since it touches `secret-handling.md`: `get_function`
returns a short-lived **presigned** S3 URL carrying an `X-Amz-Signature`, which is credential-shaped
material. It is fetched in-process, never printed, never passed as an argument, never written to a
file, and kept out of the download-failure message too — `test_the_presigned_download_url_is_never_printed_or_stored`
walks `live_members` and fails if it reaches a `print`.

### Finding 2: a closure that cannot see 35 of its own edges

The walker did `if node.level or not node.module: continue`, discarding every relative import.
`lambda_utils` carries 35 of them and one is inside this closure:

```
lambda_utils/template_ttl.py:16  from .whatsapp_types import TTL_BOUNDS, TTL_NEG1_ALLOWED
```

Measured against the live artifact, before and after:

```
closure with relative edges dropped (the old walker):  19 files
closure with relative edges resolved (the real set):   20 files
missed:  ['lambda_utils/whatsapp_types.py']
transaction needles in either set:  none
```

The verdict was right and the method was not, which is the worst combination to leave alone: the
failure direction is a false "grant not required" with a green verifier. `resolve_relative_import`
handles the arithmetic, including the case that is easy to get off by one — a package's
`__init__.py` is *inside* its package, so `from .x import y` there resolves to a sibling of the
`__init__`, not of the package directory. Five unit cases pin it, plus three closure tests, plus one
asserting that a `TransactWriteItems` **reached only by a relative import** now requires the grant.

### Findings 5, 6 and 7: three tests that could not fail

Grouped because they are one defect. Each of these passed for a reason unrelated to the property it
claimed to check.

**7 — the lazy-secret test.** It walked `tree.body` filtered to `Assign`/`Expr`/`AnnAssign`, in two
named files. So a module-scope `try:` wrapping a credential read — the *most likely* spelling, since
anyone writing one would write it defensively — was invisible to it, and `wix_ecom.py`, the one
secret this role can actually read, was not inspected at all. Rewritten to compute "every call that
is not inside a function body" across **every packaged module**, which widens it in four directions
at once: compound statements, class bodies, decorators, and default argument values. Proven against
the real package with five injected shapes:

| Injected into `wix_ecom.py` at module scope | Old test | New test |
|---|---|---|
| `try:` wrapping the read | **passed** | fails |
| `if:` wrapping the read | **passed** | fails |
| class-body assignment | **passed** | fails |
| default argument value | **passed** | fails |
| plain module-scope assign | fails | fails |
| the same read left *inside* a function | passes | passes (correctly) |

**5 — the no-float test.** `if name not in members: continue` meant a money module dropped from the
package made R6.1 pass. Presence is asserted first now; removing `money.py` from the package fails
with *"money module(s) absent from the package, so R6.1 could not be checked over them"*.

**6 — both ran on the working tree only.** These two are the R6.1 and secret-handling properties, so
they are precisely the ones whose answer should be reproducible from a SHA rather than dependent on
what three other sessions have uncommitted. A `packaged_members` fixture parametrises both over
`working-tree` and `committed`.

### Finding 9: where "the gate is off" stops meaning "nothing happens"

The previous pass identified this correctly in prose and then let the verifier print it. Measured
again from the live bytes — line numbers inside `handler.py` on v2, not offsets:

| Line | Step |
|---:|---|
| 229 | `customer_auth.require_customer` — before the body is parsed at 233 |
| 259 | `wix_ecom.create_checkout` — **a live Wix write** |
| 277 | `payment_readiness` — refuses here today, both `EXPECTED_*` empty |
| 290 | `order_keys.allocate_payment_reference` — reserves `PAYREF#` |
| 312 | `put_item` on `PaymentAttemptsTable` |
| 323 | `if not INITIATION_ENABLED` — **the gate, last** |
| 327 | `PAYMENT_INITIATION_DISABLED`, HTTP 200 |

The recorded 0-before / 0-after on `PaymentAttemptsTable` is true because line 229 refuses at the
door, and it would stay true at line 277 for an authenticated caller. But the moment an owner
supplies both readiness values with the flag still off, every authenticated `action=create` performs
a live Wix write and writes an attempt row before refusing. `--verify` now **exits 1** on that
combination and says why, instead of printing `readiness inputs: SET by an operator` and returning
success. An operator who sets those values expecting inertness gets a failure, which is the whole
point of a verifier.

Handler ordering is pre-existing code this task does not own, so it was measured and pinned, not
changed. `test_no_new_side_effect_creeps_in_before_the_gate` is a **subset** assertion on purpose:
moving the gate earlier is an improvement and stays green; a *new* outbound call appearing ahead of
it fails. Verified both directions against the real handler — injecting an `invoke()` before the
gate fails; hoisting the gate to the top of `_create` passes.

### Finding 4: a measurement instead of a citation

The substitution is correct and the previous pass was right to make it. What was wrong was its
provenance: "owner, 2026-10-01", cited inside the document doing the reporting, while the
architecture ruling four sections away cites a checkable commit. Rather than reproduce an
unverifiable approval, the claim is withdrawn and replaced with evidence that does not depend on
this file:

- [`checkout-gate-ordering-20261001.json`](snapshots/checkout-gate-ordering-20261001.json) —
  measured from the live alias's bytes, carrying the observed 401 body, both structural reasons the
  literal probe is unreachable with their line numbers, and `ownerAcceptance: NOT EVIDENCED` stated
  in the artifact itself.
- `tests/test_checkout_gate_contract.py` — 5 assertions: authentication precedes the body parse,
  neither action dispatches ahead of it, the gate still answers `PAYMENT_INITIATION_DISABLED`, no
  new side effect precedes the gate, and the disabled branch reaches no order creation, capture or
  refund.

**No owner approval should be inferred from any of this.** It establishes what the endpoint does; it
does not establish that anyone signed off on the substitution.

### Verification for this iteration

```
tests/test_provision_checkout_contract.py      55 passed   (+16 this iteration)
tests/test_checkout_package_completeness.py    19 passed   (2 tests now x2 fixtures)
tests/test_checkout_gate_contract.py            5 passed   (new)
full suite                                   5935 passed, 1 skipped
python scripts/provision_checkout.py --verify    exit 0
```

Mutation-checked rather than assumed green: every assertion added or rewritten here was run against
a deliberately broken input and confirmed to fail, and the two that should tolerate an improvement
were confirmed to stay green. Harnesses were throwaway and live in `.scratch/`, which is gitignored.
One of them had to assemble its injected needle at runtime — writing the literal call shape on a
command line is refused by `block-inline-secrets`, correctly, so it follows the convention
`scripts/verify_secret_hook.py` already uses.

### Not changed, and why

- **No deploy.** v2 remains on the alias. Every fix this iteration is in the provisioner, the tests
  and the evidence; none of it changes the packaged handler, so there is nothing to ship. The
  artifact is still [stale relative to the tree](#the-deployed-artifact-is-now-stale-and-that-is-recorded-not-fixed),
  as recorded, and deploying it is step 3 of [Open](#open).
- **No IAM change.** `dynamodb:ConditionCheckItem` stays `implicitDeny` and unrequested;
  `secretsmanager:GetSecretValue` on `wecare/razorpay/api` stays ungranted. Both are now confirmed
  unnecessary against the deployed closure rather than against an export.
- **The gate stays off**, and `CHECKOUT_INITIATION_ENABLED` remains absent from the live environment
  rather than set to `"false"`.

---

## Changes committed

| Path | Why |
|---|---|
| `scripts/provision_checkout.py` | `--source-root`; delegated packaging + pre-create import validation; route/integration/alias-qualified-permission provisioning; closure-scoped IAM grant report; route assertions in `--verify`. **Second iteration:** grant-report findings reach the exit code, per-route invoke statements, `--verify` names its source root. **Third iteration:** `live_members()` + `validate_members()` so every package-derived verdict describes the DEPLOYED bytes; `resolve_relative_import` so the closure follows relative edges; the verified env key list derived from `expected_environment()`; gate-off-with-readiness-set is now a failure |
| `config/lambda-env-manifest.json` | `wecare-checkout` entry (67 functions / 397 variables) |
| `amplify/infra/checkout.json` | IaC declaration of record |
| `tests/test_provision_checkout_contract.py` | gate, routes, alias qualification, IAM omissions. **Third iteration:** +16 — relative-import closure, live-artifact scoping, the presigned URL never printed, and a `verify()` harness that drives the real function against stubbed AWS so findings 8 and 9 are behavioural rather than text assertions |
| `tests/test_checkout_package_completeness.py` | package completeness, determinism, lazy secret, no float money. **Third iteration:** the two property tests parametrised over the working tree *and* `committed`; the lazy-secret walk widened to every import-time statement in every packaged module; the no-float test asserts presence before parsing |
| `tests/test_checkout_gate_contract.py` | **new** — 5 assertions pinning why the literal `PAYMENT_INITIATION_DISABLED` probe is unreachable, and failing when a new side effect appears ahead of the gate |
| `docs/execution/snapshots/checkout-*-20261001.json` | 10 snapshots — the 8 before/after ones, plus `checkout-live-closure-*` (the deployed artifact measured) and `checkout-gate-ordering-*` (the substitution, evidenced outside this document) |
| `docs/execution/checkout-deployment-20261001.md` | this document |

`scripts/deploy_all_lambdas.py` was **not modified** — no packaging defect blocked the work; its
`build_zip`/`validate` were reused unchanged.

### Why the IaC is a CloudFormation template and not a CDK construct

`amplify/infra/checkout.json` follows the house style set by `amplify/infra/home-fallback.json`:
a standalone template that declares what a script owns. It is deliberately **not** imported into
`amplify/backend.ts`, for two measured reasons:

1. **`zllr9lrg7j` is not CloudFormation-managed.** It carries 361 routes created by provisioning
   scripts over time, and `amplify/link-resources.ts` records at its head that the one `HttpApi`
   construct it declares **has never been deployed** — there is no stack for it. A CDK construct
   added to the Amplify backend would create a **second** API, not extend this one.
2. **`amplify/backend.ts` states the Python Lambdas are deployed separately and are not managed
   by Amplify Gen 2.** Adopting one of them into the Amplify stack would put a live payment-path
   function under a stack that can delete it on a failed update.

`test_the_template_is_not_wired_into_the_amplify_backend` pins that separation, and
`aws cloudformation validate-template` accepts the template.

---

## S3 bag icon (§10)

Provenance verified against **two independent official sources**, both HTTP 200, path geometry
**byte-identical** to the committed file:

- [`google/material-design-icons@master`](https://raw.githubusercontent.com/google/material-design-icons/master/symbols/web/shopping_bag/materialsymbolsoutlined/shopping_bag_48px.svg)
- [`fonts.gstatic.com` release channel](https://fonts.gstatic.com/s/i/short-term/release/materialsymbolsoutlined/shopping_bag/default/48px.svg)

Material Symbols Outlined `shopping_bag`, 48px, FILL 0 / wght 400 / GRAD 0 / opsz 48. Licensed
under Apache License 2.0 per the [Material Symbols guide](https://developers.google.com/fonts/docs/material_symbols)
and the [repository LICENSE](https://github.com/google/material-design-icons/blob/master/LICENSE).
The only modification is the fill: upstream `#1f1f1f` replaced with the site chrome green
`#1a3a2a`. *Licence summary paraphrased; content was rephrased for compliance with licensing
restrictions.*

```
local     public/icons/shopping-bag.svg
          sha256 e3e7925a7ba2449bd09d0f2b5be12926822c14ff705eaa25a698988a7ac14792
          1,472 bytes
bucket    wecare-digital-get                (EXISTING — no bucket was created)
key       o/stream/media/m/shopping-bag.svg
composed  lambda_utils.media_paths.public("stream/media/m", "shopping-bag.svg")
CDN URL   https://wecare.digital/get/o/stream/media/m/shopping-bag.svg   -> 200
headers   content-type: image/svg+xml
          cache-control: public, max-age=31536000, immutable
          x-content-type-options: nosniff
etag      a21aff358cbb919e12ecb4dddf358a90
```

The key was composed through `media_paths.public(...)` and never hand-built, and
`media_paths.is_gated(key)` is `False` — asserted before the upload, not after. The destination
prefix is the one the committed file's own header names.

The `o/` prefix is public, so this object is **unlisted but public**: safe from enumeration
(bucket listing is blocked and the bucket policy grants `s3:GetObject` only to the CloudFront
service principal), not safe once the URL leaks. Correct for third-party Apache-2.0 artwork the
site already serves openly. **No receipt or payment artefact was written here**; private receipt
storage stays under `secure/`.

---

## Rollback

Non-destructive first: **set no flag and leave it alone.** The function is inert — it
authenticates, and with readiness unverified it refuses. There is no traffic to drain.

To remove it entirely, in this order. Every step below is in `block-catastrophic`'s
`DESTRUCTIVE_AWS` table and therefore **asks before acting** — each needs pointwise confirmation.

```
# 1. routes first, so the API stops resolving before the target disappears
aws apigatewayv2 delete-route --api-id zllr9lrg7j --route-id 508jgfp --region us-east-1
aws apigatewayv2 delete-route --api-id zllr9lrg7j --route-id gi2dibv --region us-east-1

# 2. the integration, now unreferenced
aws apigatewayv2 delete-integration --api-id zllr9lrg7j --integration-id zkb6lxe --region us-east-1

# 3. the alias, then the function. Deleting the alias takes its resource policy with it, so the
#    two invoke statements need no separate removal — but if only the permission is being rolled
#    back, these are the ids:
#      apigateway-invoke-post-ecommerce-checkout
#      apigateway-invoke-post-ecommerce-checkout-status
aws lambda delete-alias --function-name wecare-checkout --name live --region us-east-1
aws lambda delete-function --function-name wecare-checkout --region us-east-1

# 4. the role (policy first; IAM refuses to delete a role with an inline policy attached)
aws iam delete-role-policy --role-name wecare-checkout-role --policy-name CheckoutLeastPrivilege
aws iam detach-role-policy --role-name wecare-checkout-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name wecare-checkout-role
```

`/aws/lambda/wecare-checkout` is **retained** deliberately — the log group outlives the function
so the record of what it did survives the rollback.

Order matters: deleting the function before the routes leaves two routes pointing at a missing
target, which answers 500 rather than 404 and reads like a broken deployment instead of an absent
one.

Delete **only** the ids listed above. The before-snapshots are the authority on what existed
first: any `RouteId` or `IntegrationId` not in `checkout-routes-before-20261001.json` /
`checkout-integrations-before-20261001.json` was created by this change, and nothing else may be
touched.

### Snapshots

| File | Contents |
|---|---|
| `checkout-routes-before-20261001.json` | 359 routes, 0 `ecommerce` |
| `checkout-integrations-before-20261001.json` | 66 integrations, 0 checkout |
| `checkout-function-absent-before-20261001.json` | the captured `ResourceNotFoundException` + `NoSuchEntity` |
| `checkout-shared-role-before-20261001.json` | `wecare-digital-lambda-role`'s 16 inline policy names, unmodified |
| `checkout-routes-after-20261001.json` | 361 routes, the 2 added ids, empty removed/retargeted |
| `checkout-integrations-after-20261001.json` | 67 integrations, `zkb6lxe` |
| `checkout-live-probes-after-20261001.json` | every probe, code and body |
| `checkout-bag-icon-provenance-20261001.json` | icon provenance, checksums, object headers |
| `checkout-invoke-policy-before-narrowing-20261001.json` | the single API-wide statement, as it stood before review finding 6 |
| `checkout-invoke-policy-after-narrowing-20261001.json` | the two per-route statements, all three narrowing steps, and the gate/alias/table re-measurement taken with them |
| `checkout-live-closure-20261001.json` | **third iteration** — the artifact on the `live` alias, downloaded and measured: `CodeSha256`, 113 files, the one file that differs from the v1 export, 0 import errors, the 20-module reachable closure with what the old walker missed, the IAM verdict re-derived against it, and the one-reachable-secret-reader result |
| `checkout-gate-ordering-20261001.json` | **third iteration** — why `action=create` cannot answer `PAYMENT_INITIATION_DISABLED` to an external probe, measured from the live bytes: the observed 401 body, both structural reasons with line numbers, the `_create` ordering, the consequence if readiness is ever set while the gate is off, and `ownerAcceptance: NOT EVIDENCED` |

---

## Open

~~**Confirm the architecture direction.**~~ **Answered 2026-10-01** — website Razorpay Standard
Checkout + downloadable receipt, committed at `9e3e77cb`. See
[the ruling](#the-architecture-ruling-decided-2026-10-01).

Remaining, in the order they have to happen:

1. **Wire the website path into the handler** (implementation, not a decision). `handler.py`
   imports neither `website_checkout` nor `razorpay_orders` at `83a8d60d`, so the sanctioned flow
   is shipped-but-unreachable. Expect to reconcile
   `.kiro/steering/whatsapp-payments-india-reference.md`, which still describes the in-WhatsApp
   posture and outranks the spec on conflict.
2. **Grant `secretsmanager:GetSecretValue` on `wecare/razorpay/api`** to
   `wecare-checkout-role` — at the moment step 1 lands, not before. Still deliberately ungranted:
   the direction being decided does not make the credential usable while the code that reads it
   cannot execute. `test_the_role_grants_no_razorpay_credential_read` pins the current state so
   adding it is a deliberate edit.
3. **Deploy the current artifact.** The live function is `4c603188`'s package and `order_keys.py`
   has moved since — see
   [the staleness note](#the-deployed-artifact-is-now-stale-and-that-is-recorded-not-fixed).
   This must precede step 4.
4. **`CHECKOUT_INITIATION_ENABLED`** — owner-only, and still OFF. Setting it alone is neither
   sufficient nor safe: both `EXPECTED_*` readiness values must come from a live Meta/Razorpay
   readback first, or the endpoint returns 409 regardless.
5. **The live monetary test to +918100640044** remains deferred pending separate owner
   authorisation, as does the fleet-wide alias move across ~60 functions. Neither was touched here.

## Push

**Corrected, third iteration.** This section previously read that push was "resolved" and named
only `13c9f7a2`. That was the *first* iteration's resolution, and reading it as the resolution for
the work as a whole hid a real regression path: three later commits carrying the IAM narrowing were
local-only, so the branch of record still produced an any-stage/any-method/any-path grant on
`zllr9lrg7j` while the live account carried the narrow per-route statements. The code of record was
the looser side, and its `verify()` had no invoke-statement check, so a run of it would have
re-widened the grant and reported success.

**Measured again on 2026-10-01 at 14:26Z, and now genuinely resolved.** All five commits are
ancestors of `origin/stack`:

| Commit | On `origin/stack` |
|---|---|
| `13c9f7a2` Turn the checkout 404 into an authenticating endpoint | yes |
| `4d1b396f` Record the website-Razorpay ruling and the artifact drift | yes |
| `ad3bf0a0` Make the verify gate able to fail; scope invoke to two routes | **yes** |
| `643a86e0` Skip the committed-package build when running from an export | **yes** |
| `23f6ebae` Reconcile the evidence against a live alias moved to v2 | **yes** |

Read off the branch rather than off the reflog, because "pushed" and "present on the remote" are
different claims:

```
$ git show origin/stack:scripts/provision_checkout.py | python -c "<ast>"
source_arn args: ['route_key']
returns: f'arn:aws:execute-api:{REGION}:{account_id()}:{API_ID}/{STAGE}/{method}{path}'
wide ARN string constants in code: []        # /*/* survives only inside the docstring
verify references live_policy_statements: True
verify references route_statement_id:    True
```

So the branch of record now narrows rather than widens, and its verifier can detect drift. The
three fixes made in *this* iteration (`live_members`, the derived env key list, the
readiness-set-with-gate-off failure) are **not** on the remote yet — they are in this commit, and
the orchestrator pushes. Measured at the time of writing: HEAD 3 ahead / 0 behind.

No `reset --hard`, stash, force push or history rewrite was involved at any point, by this session
or the integrating one.

---

## Related

- `.kiro/steering/whatsapp-payments-india-reference.md` — integer paise, `reference_id`, payment vocabulary
- `.kiro/steering/lambda-snapstart-deploy.md` — why the `live` alias is what production invokes
- `.kiro/steering/blog-production-s3.md` — the `o/` prefix decision the icon upload follows
- `docs/execution/snapshots/checkout-*-20261001.json` — the eight snapshots above

---

## Acceptance record — the `PAYMENT_INITIATION_DISABLED` substitution

Added 2026-10-01 by the integrating session, because three review passes recorded this
substitution as reasoned but **NOT EVIDENCED**: the reasoning lived in the section above and in a
message to the implementing step, with no artifact a later reader could audit. The reasoning is not
the acceptance. This is the acceptance.

**What was substituted.** The brief's live acceptance criterion was that
`POST /api/ecommerce/checkout` return `PAYMENT_INITIATION_DISABLED` instead of `404`. What it
actually returns is **`401 VERIFICATION_REQUIRED`**, because `require_customer` runs first and the
readiness check returns `409` ahead of the initiation gate. The gate's own branch is therefore
covered by an authenticated unit test rather than by a live probe.

**Accepted, and on what grounds.** Three independent refusals stacked in front of a payable order —
authentication, then readiness, then the initiation gate — is a stronger property than the single
refusal the criterion described, not a weaker one. The implementing step was explicitly instructed
NOT to weaken the handler to make the gate observable from outside; a probe-friendly ordering would
have meant moving the gate ahead of authentication, which is the wrong direction for a payment path.
So the criterion is recorded as **➖ NOT REQUIRED (structurally unreachable live)** rather than
`❌ FAILED` or, worse, silently reinterpreted.

**Scope of this acceptance, stated narrowly so it cannot be stretched.** It covers the verification
*method* for one branch of one handler, nothing else. It is **not** acceptance of:

- enabling `CHECKOUT_INITIATION_ENABLED` — still OFF, still owner-only, still ungranted;
- any live monetary transaction — the QA recipient `+918100640044` is nominated but a monetary test
  retains its own separate authorisation, which has **not** been given;
- the fleet-wide `live` alias moves that `scripts/deploy_all_lambdas.py` performs — this change
  created ONE new function and moved no existing alias.

**Two facts a later reader should not have to re-derive.** `wecare-razorpay-webhook` `live` moved
**v45 → v46** during this work, at 14:12:34Z, by a different session; it is evidenced in that
session's record and is not part of this change. And the third-pass review's finding that
`8a48e5f9` was unpushed was correct when written and is now stale: the run's finalize step pushed
it, and `git merge-base --is-ancestor 8a48e5f9 origin/stack` confirms it, with the verifier
hardening present on the remote copy of `scripts/provision_checkout.py`.
