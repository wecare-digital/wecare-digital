# Verification — deep-integration-audit

## FEAT-003 (F-4, F-6) — owner-authorised deviation from acceptance criterion 9

### The decision, in one line

Three pre-existing test fixtures seeded values that **production can never produce**. The
validators FEAT-003 introduces correctly reject them, so the fixtures were corrected rather than
the validators weakened. Authorised by the owner before any edit was made.

### Why a decision was needed at all

FEAT-003 acceptance criterion 9 reads: *"Every pre-existing test in
`tests/test_paid_submit_request.py`, `tests/test_paid_vault.py` and
`tests/test_customer_orders_flow.py` still passes UNCHANGED."* F-6 makes that impossible for
`tests/test_paid_submit_request.py`. Two further files outside FEAT-003's declared file list were
also affected, and plan.md §0.3 forbids bundling unrelated repairs. The build loop **stopped and
asked** rather than quietly editing a test that had been declared off-limits, because editing a
protected test in order to make a new restriction pass is exactly the move that needs sign-off.

Three options were put to the owner. **A** — correct the fixtures. **B** — weaken the predicates
(for F-6, skip a row only when `orderNumber` is missing or equal to the internal `orderId` rather
than requiring `is_public_order_number`; for F-4, accept any non-empty subject). **C** — land F-4
only and defer F-6.

**Option A was approved. B and C were rejected on the record.** B contradicts design.md's binding
choice of `is_public_order_number` (plan.md item 6, FEAT-003 step F-6-4) and would leave a
malformed order number still offered to a customer — that is the *never weaken validation to make
a test pass* rule. C splits a coherent fix and only defers the same decision.

### The three fixtures: old value, why it was impossible, new value

| Test file | Field | Old value | Why it could never occur | New value |
|---|---|---|---|---|
| `tests/test_native_catalog_orchestration.py` | `checkoutCustomerId`, `ownerCustomerId`, the Cognito `sub` attribute | `'owner'` | A Cognito `sub` is a canonical lowercase UUID, assigned by the pool and not writable by the app client. `us-east-1_46ULYuukt` can never issue `'owner'`. | `11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa`, via a new `OWNER` constant — the same UUID the suite already uses as `ALICE` |
| `tests/test_paid_submit_request.py` | `orderNumber` (seed at the fixture, and the one assertion that echoes it) | `'WD-ORD-OLD'` | `mint_public_order_number` emits `WD-ORD-` plus **exactly 8** characters of `PUBLIC_ORDER_NUMBER_ALPHABET` (`23456789ABCDEFGHJKMNPQRSTVWXYZ`). The suffix `OLD` is three characters and `O` is not in the alphabet. | `'WD-ORD-HJKMNPQR'` |
| `tests/test_central_order_directory.py` | `orderNumber` | `'WD-ORD-' + kind` (`WD-ORD-PRODUCT`, `WD-ORD-VAULT`, …) | Same rule. Every one of the five is the wrong length and most contain characters outside the alphabet. | a distinct mintable number per kind, derived from `PUBLIC_ORDER_NUMBER_ALPHABET` so the realism rule is stated rather than copied |

Every new value was re-verified against `order_keys.is_public_order_number` /
`customer_auth.is_cognito_subject` before the commit.

### What was NOT changed

No assertion logic, no control flow, and no asserted behaviour. Only seed values and the echo
literals that must agree with them. Each test still checks exactly what it checked before:

- `test_missing_order_or_unpaid_file_never_requests_payment` — that an unfulfillable service never
  requests payment.
- `test_only_owned_earlier_orders_and_missing_orders_preserve_payment` — that only owned earlier
  orders are offered and that a missing order preserves the payment.
- `test_selector_includes_all_product_and_service_order_types` — that the selector covers every
  order **kind**. The number is incidental to that question.

### The evidence that this is fixture-only

The fixture edits were committed **separately and first**, and the commit is green against
**unchanged production code**: whole suite `1 failed, 10469 passed, 6 skipped, 3 xfailed`, the one
failure being the inherited `tests/test_github_oidc_trust_policy.py` OIDC-role failure that arrived
with upstream `4ee4c498` and is present at `origin/stack` independently of this branch. 10469 is
exactly the FEAT-002 baseline. A fixture change that altered behaviour could not have produced that
result.

Commit `d2d2f869` — *test: seed order numbers and Cognito subjects that production could actually
mint*. `tests/test_native_catalog_orchestration.py` and `tests/test_central_order_directory.py` are
touched for this fixture-realism reason **only**; they are a direct consequence of the restrictions
this FEAT introduces, not unrelated repairs.

### Whole-suite gate through FEAT-003

| Point | Result | Gate |
|---|---|---|
| FEAT-002 close (inherited baseline) | 10469 passed, 1 inherited failure | — |
| after `d2d2f869` (fixtures, production unchanged) | 10469 passed, 1 inherited failure | identical, as expected |
| after `24b6d2ec` (F-4) | 10495 passed, 1 inherited failure | ≥ 10469 ✔ |
| after `f96fca87` (F-6) | 10502 passed, 1 inherited failure | ≥ 10469 ✔ |

The single inherited failure is unchanged throughout and was deliberately not fixed: it is an
IAM-trust matter (an unregistered OIDC role), out of scope, and plan.md §0.3 forbids bundling it.

### Not done, and still owner-gated

No deploy, no Lambda version published, no alias moved, no production Lambda invoked, no feature
flag opened, no live WhatsApp send, no AWS call of any kind, no secret read, nothing pushed. The
deploy of `wecare-whatsapp-business-api` for F-4's live sites and F-6 remains **OWNER CONFIRM
(O10)**, blocked on **O11** and on the v89-vs-source certification — plan.md Part B rows B3/B4.

---

## FEAT-004 (F-9 copy, F-10) — owner-authorised deviation from step 8 / acceptance criterion 9

### The decision, in one line

One pre-existing test case asserted the **defect itself**, so its expected value was corrected
rather than F-10's fixed behaviour being narrowed to preserve it. Authorised by the owner
(**Option A**) before any edit to that file was made.

### Why a decision was needed at all

FEAT-004 step 8 reads *"confirm every pre-existing case in the latter still passes UNCHANGED"* and
acceptance criterion 9 requires *"all 13 pre-existing cases"* to pass. F-10 makes that impossible
for exactly one parametrization:

`tests/test_paid_vault.py::test_notification_document_and_review_sequence_is_once_only[False]`

That arm seeds `lastInboundMessageAt: 0` on the contact while the file has `deliverable: 'pdf'`
and a `deliveryKey`. `0 <= time.time() - 0 < 86400` is therefore false, the document branch is
skipped, nothing is delivered — and the test then asserted `outcome == 'VAULT_READY'`, twice. That
assertion **is** the defect F-10 was commissioned to remove, so the two instructions cannot both
hold. There is no third reading: the fixture passes clauses 1 and 2 of the reason enum, so
`window_closed` is the only reachable reason and deferral is unavoidable.

### Old vs new, and the blast radius

| | Value |
|---|---|
| Old (2 lines) | `assert module.prepare_and_send(event,client)['outcome']=='VAULT_READY'` ×2 |
| New (2 lines) | `assert module.prepare_and_send(event,client)['outcome']==('VAULT_READY' if open_window else 'VAULT_DELIVERY_DEFERRED')` ×2 |

`git diff --stat` for that file: **1 file changed, 2 insertions(+), 2 deletions(-)**. The `[True]`
arm, the template-order assertions, the `flowButton` index, `len(sent)==(3 if open_window else 2)`
and the document-payload assertion are all byte-identical. No other pre-existing test was touched
in this FEAT. The inline-conditional form matches the file's own existing idiom.

### Option B was put on the record and rejected

**B** — carve out `lastInboundMessageAt == 0` / absent (a contact that never sent an inbound
message) so it keeps returning `VAULT_READY`, leaving the `[False]` arm unmodified. Rejected: a
contact who never messaged in is the **most likely** paid-but-undelivered case and precisely the
population F-10 exists to make findable, so B would buy a green test by reintroducing the bug for
the highest-risk case. design.md's reason enum has no arm for it either.

### The fourth staged path

`tests/test_paid_vault.py` is **not** in FEAT-004 step 8's declared staging list
(`flows/paid_vault.py`, `docs/whatsapp/native-catalog-release-status.md`,
`tests/test_paid_vault_deferred_delivery.py`). It was staged in the F-10 commit by exact path under
this waiver and for this reason only, and the commit message records it as a defect-assertion
correction rather than an unrelated repair, which plan.md §0.3 forbids.

### An unexpected +1 in the suite count, explained

The whole suite went 10504 → **10509** across F-10 while only **4** new test functions were added.
The fifth is `tests/test_handler_import_isolation.py::test_no_module_level_bare_handler_import`,
which parametrizes over every file in `tests/`; the new
`tests/test_paid_vault_deferred_delivery.py` adds one case to it automatically, and it passes. No
pre-existing test changed status.
