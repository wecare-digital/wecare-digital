# Meta response-parsing audit — "same class of bug as WD-PAY-C98523E305EE4747"

> Read-only audit (2026-10-20) prompted by the native-payment settlement failure
> where `meta_payment_binding.lookup_payment()` could not parse Meta's live
> response shape (order id at `transactions[].id` `order_`-prefixed; payment id at
> `transactions[].pg_transaction_id` `pay_`-prefixed). Goal: find every other
> place we parse a Meta response with a brittle assumption that could silently
> misread live data the same way.
>
> Scope: all ~20 Python handlers that call the Meta Graph API or parse Meta
> webhook/response bodies. No live AWS/Meta calls were made; findings are from
> code only. Severity is about *likelihood × money/delivery impact*.

## The transport layer is sound (not a finding)

`shared/lambda_utils/meta_client.py` + `graph_errors.py` are well built: normalized
error envelope, retry on transient/5xx only, cursor pagination, masked logging,
per-WABA token/appsecret. The risk is **not** the transport — it is **per-handler
response parsing**, exactly where the payment-binding bug lived.

---

## FINDING 1 — HIGH — Inbound payment webhook reads singular `transaction`, not the live plural `transactions[]`

**File:** `amplify/functions/messaging/inbound-whatsapp-handler/handler.py`
**Functions:** `_process_payment_status` (~L4431) and `_store_payment_record` (~L5189–5210)

This is the **same class of bug** as the webhook incident, in the *inbound* path.

- `_process_payment_status` extracts:
  ```python
  transaction = payment_data.get('transaction', {})   # SINGULAR
  transaction_id   = transaction.get('id', '')
  transaction_type = transaction.get('type', '')
  transaction_status = transaction.get('status', '')   # L4516, drives FAILED detection
  ```
- `_store_payment_record` reads `transaction.get('pg_transaction_id', '')` — again
  under a **singular** `transaction` key.

But the live Meta shape captured in the `WD-PAY-C98523E305EE4747` incident is
**plural**: `transactions` is a *list*, with `id` (`order_…`) and
`pg_transaction_id` (`pay_…`) inside each element, and a top-level `status`.
`meta_payment_binding` was fixed to read exactly that. **This inbound handler was
not.**

**Impact if Meta delivers the plural shape here (same payment product/WABA that
produced the capture):** `transaction` resolves to `{}` →
- `transaction_id = ''`, `pg_transaction_id` lost (stored payment record missing
  its gateway ids — the join evidence);
- `transaction_status = ''` → `canonical('') != FAILED`, so a genuinely **failed**
  payment is not detected as failed (L4516–4520);
- the status *decision* itself is salvaged because the top-level
  `status`/`payment_status` is canonicalised (good — see Finding 5), but the
  **evidence ids** and the **failed-branch** are shape-dependent.

**Note:** this file already learned the *status-spelling* half of the lesson
(explicit comment at ~L4387 about `paid` vs `captured`), so canonicalisation is
present — but the *shape* half (singular vs plural `transaction(s)`) was not
applied here.

**Recommendation:** make both functions accept either shape — prefer a
`transactions` list element, fall back to singular `transaction` — and reuse the
same prefix-classification (`order_`→order id, `pay_`→payment id,
`pg_transaction_id`) now living in `meta_payment_binding`. Add a regression
fixture using the live plural shape. Keep canonical status + fail-closed.

---

## FINDING 2 — MEDIUM — `res.get('success', True)` defaults a missing field to success (fail-OPEN)

**Files:**
- `amplify/functions/messaging/partner-onboarding/handler.py` (L160 `subscribe_app`, L172 `register_phone`)
- `amplify/functions/messaging/whatsapp-business-api/handler.py` (L623, 894, 954, 2110, 3284, 3449, 4494)

Meta Graph success responses generally return **data** (or `{"success": true}`
on *some* edges, but not all) and failures return an `error` envelope — they do
**not** reliably carry `success: false`. `result.get('success', True)` therefore
**reports success whenever the key is absent**, which is the fail-*open*
direction: a response whose shape we didn't expect reads as "it worked."

**Impact:** onboarding steps (app-subscribe, phone-register) and various WA admin
mutations can report `ok/success: True` to the caller/UI even when Meta did not
actually confirm. Not a money path, but it can mask real failures and present a
false-healthy state (the kind of thing the steering files call out: "no fake
success states").

**Recommendation:** decide success from the **presence of expected data or the
absence of an `error` envelope** (use `meta_client.is_error()` /
`graph_errors.is_error()`), not from `get('success', True)`. Default the unknown
case to **False** (fail-closed), and surface Meta's `error`/`fbtrace_id`.

---

## FINDING 3 — LOW/MEDIUM — Template-status surfaced as a single raw field, no canonicalisation

**File:** `amplify/functions/messaging/whatsapp-template-management/handler.py`
(`_list_templates` L259, `_get_template_details` L291)

`templateStatus: t.get('status')` is passed through raw. Callers elsewhere compare
it with brittle equality (e.g. `customer_invoice.py` L43
`t.get('status') == 'APPROVED'`; `whatsapp-business-api` L3850 `== 'DEPRECATED'`,
L3884 `== 'PUBLISHED'`). Meta template status vocabulary includes `APPROVED`,
`PENDING`, `REJECTED`, `PAUSED`, `DISABLED`, `IN_APPEAL`, `PENDING_DELETION`,
`FLAGGED` — a `== 'APPROVED'` check is fine for the positive case but any
send-eligibility decision that is `!= 'REJECTED'` or similar would misclassify
`PAUSED`/`DISABLED`/`FLAGGED` as usable.

**Impact:** a `PAUSED`/`FLAGGED` template could be treated as sendable (or a
transient `PENDING` as permanently bad). This is adjacent to the original
incident's *symptom* (a paid-invoice template send that didn't deliver).

**Recommendation:** centralise a `template_status` helper (sendable vs
pending vs blocked) mirroring `payment_status.canonical`, and route all template
send-eligibility decisions through it rather than scattered string equality.

---

## FINDING 4 — LOW — Catalog-sync visibility/status defaults to `active`/visible on unknown

**File:** `amplify/functions/ecommerce/meta-catalog-sync/handler.py` (L519, L543)

`"visible": str(item.get("status") or "active") == "active"` and the archived
check default a **missing** status to `active`. For our own `ProductsTable` rows
this is intentional (documented default), but if any of these defaults are ever
applied to a *Meta*-returned item shape, an unknown/missing status would read as
visible/active. Low risk today because the authority is our table, not Meta —
flagged for consistency with the fail-closed principle.

**Recommendation:** keep the ProductsTable default, but if Meta-returned item
status is ever consulted for a visibility decision, treat unknown as **not
visible** (fail-closed).

---

## FINDING 5 — GOOD (no action) — Patterns that already handle Meta's shape correctly

- **Inbound payment status decision** canonicalises Meta's raw word
  (`pay_status.canonical(...)`) with an explicit comment about the `paid` vs
  `captured` bug — the status-spelling half is handled (see Finding 1 for the
  remaining shape half).
- **`meta_payment_binding.lookup_payment`** now reads both explicit fields and the
  prefix-classified `id`/`pg_transaction_id`, de-dupes, and refuses ambiguity —
  fixed in the WD-PAY-C98523E305EE4747 PR.
- **`graph_errors.normalize` / `meta_client.is_error`** give a consistent
  fail-closed error envelope — the right tool for Finding 2.
- **Amount parsing** inbound uses `value/offset` with an offset default and a
  zero-amount DynamoDB fallback — resilient.

---

## Suggested remediation order

1. **Finding 1 (HIGH)** — inbound `transactions[]` shape + failed-branch, with a
   live-shape regression fixture. Mirror the `meta_payment_binding` fix; reuse its
   prefix classification. (Money/delivery evidence path.)
2. **Finding 2 (MEDIUM)** — replace `get('success', True)` with
   `is_error()`-based, fail-closed success detection across partner-onboarding and
   whatsapp-business-api.
3. **Finding 3 (LOW/MED)** — a canonical `template_status` helper + route
   send-eligibility through it.
4. **Finding 4 (LOW)** — fail-closed on Meta-sourced catalog visibility if ever
   consulted.

Each should ship with a fixture capturing the real Meta shape it defends against,
following the regression-fixture precedent set by the payment-binding fix. None of
these should relax the `razorpay_verify` / webhook-as-authority money invariants.
