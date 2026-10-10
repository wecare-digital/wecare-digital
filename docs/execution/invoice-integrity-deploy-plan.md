# Deploy plan — invoice integrity (`fix/invoice-integrity`)

Authored 2026-10-10 on branch `fix/invoice-integrity`, head `0e2e3cb2`, base `f87ea643`.
**No deploy step below was executed.** The only AWS calls made while writing this document were
`aws lambda get-alias` reads, which is why the version table carries real captured values rather
than placeholders. Nothing was written to AWS, no environment variable was set, and
`scripts/reconcile_invoice_sequence.py` was **not** run.

No credential, key id, secret value or customer detail appears in this file. Invoice numbers are
shown in the `WD/2627/00001` series shape only.

---

## 1. What is being deployed

Four fixes, all already committed and all green against the measured baseline (§7).

| Commit | Fix | What changes at runtime |
|---|---|---|
| `b186a006` | **C2** — a GST invoice number is never reused | `_get_next_invoice_number` now confirms the counter's output with an immutable `INVOICENO#` reservation row on `COMMERCE_KEYS_TABLE` before handing the number out. A reset counter self-heals by walking past the reserved candidates; exhausting `_INVOICE_NUMBER_ATTEMPTS` (25) raises `503 INVOICE_SEQUENCE_UNAVAILABLE` and writes no document |
| `99f6ecd7` | **H1** — an invoice from a capture totals exactly the capture | New opt-in `amountIsTaxInclusive` + `expectedTotalPaise` on `create_invoice`; GST is back-calculated and the tax is the **remainder**, so `taxable + tax == total` exactly. `create_invoice_from_payment` reads the integer paise amount instead of the `amountInRupees` display string. Five new refusals, every one raised before a number is consumed |
| `e99619cb` | **H2** — a rejected payment request is never reported as sent | `send_payment_link` now has three explicit outcomes (rejected / ambiguous / accepted). A downstream `409` holds the claim and answers `409 … retryable: false`; any other rejection releases the claim and answers `502 … retryable: true`. Delivery-log statuses on this path are `rejected` / `unknown` / `accepted`. The Pay Flow UI now defaults the sender to the WABA1 number |
| `0e2e3cb2` | **H3** — an issued invoice is not rewritten in place | `status` and `paymentStatus` are no longer client-writable on any row state; financial fields are immutable once issued; a re-render writes `…-v2.png` and a new `image#v2` asset row instead of overwriting the document of record; a remark's author comes from the token; a refund needs a provider refund id proven against `PaymentsTable` |

### Files changed

```
amplify/functions/payments/invoice-engine/handler.py                      +1012 / -114
amplify/functions/shared/lambda_utils/ecommerce/order_keys.py               +82 / -0
amplify/functions/shared/lambda_utils/ecommerce/wa_payment_request.py       +69 / -0
scripts/reconcile_invoice_sequence.py                                      +207  (new)
src/api/client.ts                                                           +14 / -8
src/pages/workspace/pay/flow/index.tsx                                      +46 / -18
tests/ (5 files, 1 extended)                                              +2489 / -0
```

**The two shared-module diffs are purely additive — zero deleted lines, verified with
`git diff f87ea643..HEAD`.** `order_keys` gained `reserve_invoice_number` /
`resolve_invoice_number` and their constants; `wa_payment_request` gained `release_send_claim` /
`record_send_rejected`. No existing signature, constant or code path in either module was
touched. That single fact is what keeps the blast radius in §2 a *packaging* problem rather than a
*behaviour* problem.

---

## 2. Blast radius — every affected Lambda

`scripts/deploy_all_lambdas.py:build_zip` bundles **the entire `lambda_utils` tree** into every
non-`standalone` spec (`for path in _iter_dir(LAMBDA_UTILS)`), not just the modules a handler
imports. Two files in that tree changed, so **every one of the 73 bundled functions now packages
different bytes and will produce a new `CodeSha256`.** The spec list has 77 entries; 4 are
`standalone` (handler.py only) and are untouched.

Measured, not guessed: the lists below come from reading `SPECS` out of
`scripts/deploy_all_lambdas.py` directly and from grepping each spec's own packaged sources
(`handler.py`, `modules/`, `extra_dirs`, `extra_files`) for the two module names.

### Tier 1 — behaviour changed. Must deploy. (1 function)

| Function | Source | Why |
|---|---|---|
| `wecare-invoice-engine` | `payments/invoice-engine` `[dirs=fonts files=receipt_layout.py]` | the only `handler.py` that changed; carries all four fixes |

### Tier 2 — names a changed module directly. Deploy for source parity. (9 functions)

These import `order_keys` and/or `wa_payment_request` in their own code. Because both diffs are
additive, **no behaviour change is expected on any of them** — they gain unused symbols. Deploy
them so the live package matches the branch; a stale zip here is a future debugging trap, not a
present defect.

| Function | Source | Imports |
|---|---|---|
| `wecare-razorpay-webhook` | `payments/razorpay-webhook` | `order_keys`, `wa_payment_request` |
| `wecare-checkout` | `ecommerce/checkout` | `order_keys`, `wa_payment_request` |
| `wecare-inbound-whatsapp` | `messaging/inbound-whatsapp-handler` | `order_keys`, `wa_payment_request` |
| `wecare-outbound-whatsapp` | `messaging/outbound-whatsapp` | `order_keys`, `wa_payment_request` |
| `wecare-whatsapp-business-api` | `messaging/whatsapp-business-api` | `order_keys` (via `flows/paid_submit_request.py`) |
| `wecare-service-api` | `core/service-api` | `order_keys` |
| `wecare-service-requests` | `ecommerce/service-requests` | `order_keys` |
| `wecare-wix-store` | `ecommerce/wix-store` | `order_keys` |
| `wecare-partner-onboarding` | `messaging/partner-onboarding` | `order_keys` |

`wecare-razorpay-webhook` is in this tier on packaging grounds only. **FEAT-002 did not change its
caller contract** — `create_invoice_from_payment` lives inside `invoice-engine` and reads the
`PaymentsTable` row the webhook already writes (`razorpay-webhook/handler.py:1978` writes
`Decimal(amount_paise)`), so the webhook's own code is unmodified.

### Tier 3 — zip differs by the same additive shared tree only. (63 functions)

Deploying these is a **parity choice, not a requirement of this PR.** Each one's new bytes are the
two additive shared files and nothing else. Listed in full because the acceptance criterion is
that every affected function is named, and because a later `deploy_all_lambdas.py` run with no
arguments *will* pick all of them up.

```
wecare-customer-session          wecare-auth-middleware           wecare-automation-rules
wecare-contacts                  wecare-conversation-meta         wecare-secure-files
wecare-crm                       wecare-faq-handler               wecare-messages-delete
wecare-messages-read             wecare-email-verification        wecare-customer-profile
wecare-blog-subscribe            wecare-customer-registration     wecare-customer-orders
wecare-customer-invoice          wecare-coupons                   wecare-gift-cards
wecare-wix-giftcard-spi          wecare-wix-catalog-webhook       wecare-meta-catalog-sync
wecare-url-shortener             stack-wecare-url-shortener       wecare-whatsapp-voice
wecare-whatsapp-calling          wecare-whatsapp-templates        wecare-whatsapp-template-management
wecare-waba-management           wecare-media-cleanup             wecare-template-analytics
wecare-partner-token-refresh     wecare-outbound-sms              wecare-outbound-email
wecare-sms-aws                   wecare-voice-aws                 wecare-voice-in-c2c
wecare-voice-in-obd              wecare-voice-cdr-read            wecare-notification-worker
wecare-plivo-answer              wecare-pstn-softphone            wecare-rcs-send
wecare-rcs-dlr                   wecare-push-notifications        wecare-scheduled-messages
wecare-meta-analytics            wecare-ad-attribution            wecare-marketing-ads
wecare-meta-business-agent       wecare-ai-query-kb               wecare-ai-generate-response
wecare-ai-config-management      wecare-agent-action-group         wecare-billing
wecare-bulk-job-create           wecare-bulk-job-control          wecare-bulk-worker
wecare-dlq-replay                wecare-sla-engine                wecare-system-cleanup
wecare-payments-read             wecare-product-image-gen         wecare-catalog-management
```

### Explicitly OUT of the radius

| Function | Why |
|---|---|
| `wecare-site-language`, `wecare-vayulok-environment`, `wecare-customer-whatsapp-auth`, `wecare-cognito-custom-message` | `standalone=True` — the package is `handler.py` alone, no `lambda_utils`, so nothing in this PR reaches them |
| `wecare-seo-tools`, `wecare-mcp`, `wecare-workspace-mcp` | `DELEGATED` — they have their own deploy scripts and are not in `SPECS` |
| `wecare-docs-scraper` | `SKIPPED` — `PackageType=Image`, ships via GitHub Actions |

**Recommended deploy set for this PR: Tier 1 + Tier 2 (10 functions).** Tier 3 is a separate,
no-behaviour-change parity pass if the owner wants the whole fleet byte-identical to the branch.

---

## 3. Deploy path

`update-function-code` alone **does not reach production.** The API invokes `:live`, and
`deploy_all_lambdas.py` publishes a version and then shells out to
`scripts/snapstart_publish.py --only-stale <deployed…>` to move the alias. Of the 73 bundled
functions, **64 carry a `live` alias** and 9 do not (§4) — measured 2026-10-10, superseding the
plan-era "53 of 62" figure for this set.

### Step 1 — dry run first, always

```bash
cd /Users/wecaredigital/wecare-digital/.worktrees/invoice-integrity
python scripts/deploy_all_lambdas.py --dry-run \
  wecare-invoice-engine \
  wecare-razorpay-webhook wecare-checkout wecare-inbound-whatsapp wecare-outbound-whatsapp \
  wecare-whatsapp-business-api wecare-service-api wecare-service-requests \
  wecare-wix-store wecare-partner-onboarding
```

The dry run is not cosmetic. It:

- AST-walks every top-level import in the packaged zip against the function's **live layer
  contents** (`layer_modules` downloads and reads the layer zip) and fails the function if an
  unguarded import resolves nowhere;
- checks the **configured `Handler` symbol actually exists** in the package — two functions in
  this fleet define `lambda_handler` rather than `handler`, and a rename would otherwise deploy
  clean and die on first invoke with `Runtime.HandlerNotFound`;
- compares `base64(sha256(zip))` against the live `CodeSha256` and reports `would_update=` vs
  `unchanged=` honestly, so the count is evidence rather than an assumption;
- uploads nothing and exits non-zero only on a real failure.

**Expected:** `would_update=10 unchanged=0 failed=0`. If any function reports `failed`, stop —
do not proceed to step 2 for any of them.

### Step 2 — the real run

Record the rollback versions (§4) **before** this command.

```bash
python scripts/deploy_all_lambdas.py \
  wecare-invoice-engine \
  wecare-razorpay-webhook wecare-checkout wecare-inbound-whatsapp wecare-outbound-whatsapp \
  wecare-whatsapp-business-api wecare-service-api wecare-service-requests \
  wecare-wix-store wecare-partner-onboarding
```

It updates `$LATEST`, waits on the `function_updated_v2` waiter, then publishes and moves `live`
via `snapstart_publish.py --only-stale`. `--no-publish` is available and leaves `live` on the old
code — useful only if the alias move is to be staged deliberately.

If only `wecare-invoice-engine` is to ship, run it alone; the nine parity functions are
independent of it.

---

## 4. Live / rollback versions — captured 2026-10-10

Lookup command, per function:

```bash
aws lambda get-alias --function-name <fn> --name live --region us-east-1
```

Real output for the primary function, pasted verbatim:

```json
{
    "AliasArn": "arn:aws:lambda:us-east-1:775261844268:function:wecare-invoice-engine:live",
    "Name": "live",
    "FunctionVersion": "53",
    "Description": "",
    "RevisionId": "921c307c-05a2-40b0-aa9b-f24179d5acfe"
}
```

Rollback, per function:

```bash
aws lambda update-alias --function-name <fn> --name live \
  --function-version <recorded-version> --region us-east-1
```

> The plan-era note in `.agents/tasks/invoice-integrity-plan.md` §6.2 said this lookup could not be
> run because the `wecare-prod` session was expired. **It ran cleanly on 2026-10-10** and the table
> below is captured, not invented. The versions are still a snapshot: **re-run `get-alias`
> immediately before deploying** and use those numbers, because any deploy between now and then
> moves the alias.

### Recommended deploy set

| Function | `live` version now | Rollback command |
|---|---|---|
| `wecare-invoice-engine` | **53** | `aws lambda update-alias --function-name wecare-invoice-engine --name live --function-version 53 --region us-east-1` |
| `wecare-razorpay-webhook` | 57 | `… --function-name wecare-razorpay-webhook --function-version 57 …` |
| `wecare-checkout` | 43 | `… --function-name wecare-checkout --function-version 43 …` |
| `wecare-inbound-whatsapp` | 92 | `… --function-name wecare-inbound-whatsapp --function-version 92 …` |
| `wecare-outbound-whatsapp` | 56 | `… --function-name wecare-outbound-whatsapp --function-version 56 …` |
| `wecare-whatsapp-business-api` | 97 | `… --function-name wecare-whatsapp-business-api --function-version 97 …` |
| `wecare-service-api` | 24 | `… --function-name wecare-service-api --function-version 24 …` |
| `wecare-service-requests` | 5 | `… --function-name wecare-service-requests --function-version 5 …` |
| `wecare-wix-store` | 38 | `… --function-name wecare-wix-store --function-version 38 …` |
| `wecare-partner-onboarding` | 27 | `… --function-name wecare-partner-onboarding --function-version 27 …` |

### Tier 3 parity set, same snapshot

| Function | `live` | Function | `live` |
|---|---|---|---|
| `wecare-customer-session` | 7 | `wecare-auth-middleware` | 22 |
| `wecare-automation-rules` | 20 | `wecare-contacts` | 34 |
| `wecare-conversation-meta` | 20 | `wecare-secure-files` | 37 |
| `wecare-crm` | 17 | `wecare-faq-handler` | 25 |
| `wecare-messages-delete` | 28 | `wecare-messages-read` | 29 |
| `wecare-email-verification` | 5 | `wecare-customer-profile` | 11 |
| `wecare-customer-orders` | 7 | `wecare-coupons` | 1 |
| `wecare-wix-catalog-webhook` | 9 | `wecare-meta-catalog-sync` | 9 |
| `stack-wecare-url-shortener` | 20 | `wecare-whatsapp-voice` | 31 |
| `wecare-whatsapp-calling` | 43 | `wecare-whatsapp-templates` | 30 |
| `wecare-whatsapp-template-management` | 29 | `wecare-waba-management` | 31 |
| `wecare-media-cleanup` | 23 | `wecare-template-analytics` | 24 |
| `wecare-outbound-sms` | 25 | `wecare-outbound-email` | 25 |
| `wecare-sms-aws` | 28 | `wecare-voice-aws` | 24 |
| `wecare-voice-in-c2c` | 29 | `wecare-voice-in-obd` | 30 |
| `wecare-voice-cdr-read` | 24 | `wecare-notification-worker` | 18 |
| `wecare-plivo-answer` | 32 | `wecare-pstn-softphone` | 10 |
| `wecare-rcs-send` | 28 | `wecare-rcs-dlr` | 28 |
| `wecare-push-notifications` | 23 | `wecare-scheduled-messages` | 25 |
| `wecare-meta-analytics` | 20 | `wecare-marketing-ads` | 25 |
| `wecare-meta-business-agent` | 38 | `wecare-ai-query-kb` | 26 |
| `wecare-ai-generate-response` | 39 | `wecare-ai-config-management` | 28 |
| `wecare-agent-action-group` | 28 | `wecare-billing` | 25 |
| `wecare-bulk-job-create` | 24 | `wecare-bulk-job-control` | 26 |
| `wecare-bulk-worker` | 24 | `wecare-dlq-replay` | 23 |
| `wecare-system-cleanup` | 33 | `wecare-payments-read` | 27 |
| `wecare-product-image-gen` | 28 | `wecare-catalog-management` | 20 |

### Nine functions have no `live` alias

`get-alias` answered `ResourceNotFoundException: Cannot find alias arn: …:<fn>:live` for:

```
wecare-blog-subscribe            wecare-customer-registration     wecare-customer-invoice
wecare-gift-cards                wecare-wix-giftcard-spi          wecare-url-shortener
wecare-partner-token-refresh     wecare-ad-attribution            wecare-sla-engine
```

All nine are Tier 3, so none of them is in the recommended deploy set. **For these the alias
rollback does not exist**: they serve `$LATEST`, so the only way back is to repackage and upload
the previous code (`git checkout f87ea643 -- amplify/functions/shared/lambda_utils` in a scratch
checkout, then `deploy_all_lambdas.py <fn>`). That asymmetry is a reason to leave Tier 3 alone in
this PR. `wecare-customer-invoice` is worth a second look if Tier 3 is ever deployed — it is the
customer-facing invoice read and it point-reads the base `image`/`pdf` asset rows that FEAT-004
deliberately left as the document of record.

---

## 5. Environment variables — required, and **not set by this PR**

Nothing below was changed, added or set. `config/lambda-env-manifest.json` already declares all of
them on `wecare-invoice-engine` except `EXPECTED_CONFIGURATION_NAME`, which is optional.

| Variable | Status in the manifest | What depends on it |
|---|---|---|
| `COMMERCE_KEYS_TABLE` | set — `stack-wecare-digital-WixOrderIds` | **This is the single most important line in this section.** It was "used by the WhatsApp payment-request send path". It is now **required by every invoice issue**: `_get_next_invoice_number` writes the `INVOICENO#` reservation there before returning a number. If it is wrong, empty or unwritable, invoice creation answers `503 INVOICE_SEQUENCE_UNAVAILABLE` and no invoice is issued at all. Confirm its value before deploy, not after |
| `INVOICE_SEQ_TABLE` | set — `stack-wecare-digital-InvoiceSequenceTable` | the atomic counter `_get_next_invoice_number` advances |
| `INVOICES_TABLE` | set — `stack-wecare-digital-InvoicesTable` | the invoice rows; also the issued-state read behind `409 INVOICE_ISSUED_IMMUTABLE` and the fail-closed `503 INVOICE_STATE_UNREADABLE` |
| `PAYMENT_ATTEMPTS_TABLE` | set — `stack-wecare-digital-PaymentAttemptsTable` | the `sendStatus` claim that `release_send_claim` / `record_send_rejected` move |
| `WA_PAY_CONFIG_NAME` | set — `WECAREDIGITAL` | the Razorpay/WhatsApp payment configuration name |
| `EXPECTED_CONFIGURATION_NAME` | **not set, and that is correct** | `handler.py:159` reads `EXPECTED_CONFIGURATION_NAME` first and falls back to `WA_PAY_CONFIG_NAME`. The chain resolves on the fallback today. Setting it is only needed if the two must diverge |
| `EXPECTED_PROVIDER_MID` | set | the provider merchant id the outbound gate proves against |

Also already set and relied on by the changed paths, listed so nobody reads this section as the
complete environment: `PAYMENTS_TABLE` (the refund-evidence point read), `INVOICE_ASSETS_TABLE`
(the `image#v2` version query), `INVOICE_DELIVERY_TABLE`, `INVOICE_ITEMS_TABLE`, `MEDIA_BUCKET`,
`CONTACTS_TABLE`, `CDN_DOMAIN`.

An environment change does **not** reach the alias until a new version is published. If a variable
ever is changed, publish and move `live` again afterwards.

---

## 6. IAM — no new grant

`wecare-invoice-engine` **already writes `stack-wecare-digital-WixOrderIds`** on the existing
payment-request path: `wa_payment_request.reserve` (`wa_payment_request.py:406`) claims identity
rows there through `order_keys._claim_row`, and the handler opens
`dynamodb.Table(COMMERCE_KEYS_TABLE)` at six existing call sites. FEAT-001's
`reserve_invoice_number` is another `put_item` with `attribute_not_exists` against **the same
table with the same key attribute (`orderId`)**.

**So this change adds no new table grant, no new table, and no manifest change.** FEAT-004's
additions are likewise already-granted reads: a `Query` on `InvoiceAssetsTable` by `invoiceId`
(which `get_invoice` already performs) and a point read of `PaymentsTable` by `id`.

**This must still be re-confirmed against the live execution role before deploy.** The claim above
is derived from source, not from reading the deployed policy. Confirm that the role attached to
`wecare-invoice-engine` carries `dynamodb:PutItem` on `stack-wecare-digital-WixOrderIds` — if it
somehow carries only `UpdateItem`/`GetItem` there, every invoice issue fails closed with
`503 INVOICE_SEQUENCE_UNAVAILABLE`. That is a safe failure, but a total one.

---

## 7. Gates — measured on `0e2e3cb2`

Baseline is `f87ea643` from `.agents/tasks/task-invoice-integrity/context.json`. Every command
carries the dummy-credential prefix, because several test files otherwise make real AWS calls with
the ambient root session.

| Gate | Baseline | This branch | Delta |
|---|---|---|---|
| pytest | 1 failed, 10648 passed, 6 skipped, 3 xfailed | 1 failed, 10865 passed, 6 skipped, 3 xfailed | **+217 passed**, same single failure |
| vitest | 126 files / 1584 tests passed, 11 skipped | identical | none |
| `tsc --noEmit` | clean | clean | none |
| `compileall` | clean | clean | none |
| control-skin census | matches fixture | matches fixture | **empty diff** — the fixture did not need regenerating |

The one failure is the **pre-existing, unrelated**
`tests/test_checkout_handler.py::test_waba2_cannot_prepare_a_native_service_payment_and_leaves_no_claim`
— a fixture gap where `tests/crm_fake_dynamo.py` does not declare `ContactsTable`, which
`checkout/handler.py:3156` reads. It was failing before this branch existed and was deliberately
not fixed here. **Nothing was skipped, weakened or deleted.**

### The #266 payment gate: verified healthy, no change required

```
tests/test_outbound_payment_gate.py
tests/test_payment_readiness.py
tests/test_payment_key_table_is_one_name.py
tests/test_partner_razorpay_canonical_secret.py
tests/test_razorpay_binding.py
→ 146 passed in 0.64s
```

The config chain resolves as the static read predicted: `handler.py:159` tries
`EXPECTED_CONFIGURATION_NAME`, falls back to `WA_PAY_CONFIG_NAME=WECAREDIGITAL`, and
`EXPECTED_PROVIDER_MID` is set in the manifest. **No source file was touched for this gate, no new
environment variable was introduced, and no refusal was weakened.**

---

## 8. Reconciliation runbook — `scripts/reconcile_invoice_sequence.py`

**THIS PR DOES NOT RUN IT.** The script ships unexecuted. It exists because a counter that was
reset below the issued series now self-heals by walking past the reserved numbers, and that walk
is bounded and costs a wasted counter advance per already-issued number — fine as a safety net,
wrong as a steady state. Realigning the counter once is an operator action.

`--fy` is **required** (there is no zero-flag invocation). The default is report-only: it prints,
writes nothing, and exits `0` when the counter is at or above the floor, `1` when it is behind.

### Step 1 — dry run, writes nothing

```bash
python scripts/reconcile_invoice_sequence.py --fy 2026-2027
```

### Step 2 — read the three independent figures it reports

| Source | What it means | Blind spot |
|---|---|---|
| highest `invoiceNumber` on `InvoicesTable` | what we issued and still hold a row for | silent if the invoice rows were wiped |
| highest `INVOICENO#` on `WixOrderIds` | what we recorded as issued, surviving an invoice-table wipe | silent if a **full system reset** cleared the keys table (§9) |
| operator `--floor WD/2627/00004` | what a human knows went out | the **only** source for erased history |

The proposed floor is the maximum of the three.

### Step 3 — agree the floor with the accountant

The duplicate-`WD/2627/00001` question (§10) must be answered first. Do not pick a floor to make
the script exit `0`.

### Step 4 — apply, only then

```bash
python scripts/reconcile_invoice_sequence.py --fy 2026-2027 --floor WD/2627/00004 --apply
```

`--apply` issues one conditional `SET last_seq = :floor` guarded on
`attribute_not_exists(last_seq) OR last_seq < :floor`, so it is **forward-only and idempotent**,
and two concurrent runs cannot move the counter backwards. It never deletes a row, never issues an
invoice number, never writes a reservation row and never touches an invoice.

---

## 9. Cross-PR flag — a full system reset still erases the reservations

`amplify/functions/operations/system-cleanup/handler.py:261` includes `WixOrderIds` in its reset
list. **A full system reset therefore still wipes the `INVOICENO#` reservation rows**, which is the
second of the three reconciliation sources. The counter would restart and the keys table would be
empty, leaving the operator `--floor` as the only record of what went out.

That surface belongs to **`fix/staff-auth-and-cleanup-guard`** and is deliberately untouched here.
Until it is protected, `reconcile_invoice_sequence.py --floor` is the recovery path. Do not read
the C2 fix as making a reset safe — it makes a *counter reset* safe, not a *table wipe*.

---

## 10. Open questions this deploy does not answer

1. **Duplicate `WD/2627/00001`** — issued 2026-10-04 and again 2026-10-08, with `00002`–`00004`
   erased. Which document is the invoice of record, and whether a credit note is required, is an
   **accountant/owner** call. The code stops recurrence; it rewrites no history.
2. **D3 — a captured amount is GST-inclusive** — shipped as an **owner-changeable default**. If the
   owner rules it tax-exclusive, the capture must be refused as under-collected rather than billed
   higher, and `_back_calculate_inclusive` plus the two request flags are the only places that
   change.
3. **D4 — the immutability model** — also an owner-changeable default for the *financial* half
   (`_is_issued` alone decides it). The *payment-state* half should not be softened: it is the path
   by which an invoice could read as paid with no money behind it.
4. **The Edit Invoice button is effectively gone from Pay Flow**, because every invoice carries a
   number at creation and is therefore issued from birth. The server still allows contact / address
   / notes edits after issue; restoring a contact-only edit surface is a one-screen follow-up.
5. **The Refund button now always refuses** until the follow-up UI sends a provider refund id. A
   refund recorded in Razorpay today cannot be reflected on the invoice from that screen. The
   credit-note / revision surface is the stated follow-up.
6. **Nothing retro-fixes history** — rows marked paid or refunded under the old rules, invoices
   written at the additive 118-for-100 figures, the three 2026-10-07 invoices logged as sent, and
   renditions already overwritten in S3 (those bytes are gone). All of it is the same
   accountant/owner question as item 1.
