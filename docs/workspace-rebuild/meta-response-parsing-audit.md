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

---

# Round 2 — adjacent money/reconciliation robustness (same investigation, wider net)

A second pass beyond pure Meta-shape parsing, into the classes of defect this
incident exposed: silent paid-state writers, float money math, unbounded scans on
hot paths, and inbound↔webhook consistency. Same read-only, code-only basis.

## FINDING 6 — MEDIUM — Dead-but-callable financial writers (unverified paid state)

**File:** `amplify/functions/messaging/inbound-whatsapp-handler/handler.py`
**Functions:** `_mark_invoice_paid_by_reference` (~L4714),
`_generate_invoice_for_captured_payment` (~L4778)

**Good:** the in-WhatsApp CAPTURED branch is correctly **retired** to a type-only
audit record with **no** financial side effects, and the docstrings explain the
single-authority (webhook) design well. The decision itself is sound.

**But:** both helpers still **exist and still work** — `_mark_invoice_paid_by_reference`
writes `status=paid, paymentStatus=captured` directly to InvoicesTable, and
`_generate_invoice_for_captured_payment` mints an invoice — and grepping confirms
**neither has any caller**. Per steering `50-coding-style.md`: *"Delete dead code,
don't gate it. Remove a disabled capability rather than leaving it behind… Dead
code that still works is how a removed power comes back."* A fully-functional,
unverified paid-state writer sitting one call away from reinstatement is exactly
the hazard that rule targets — and exactly the fail-open path the comments say was
retired because *"an unverified webhook body could… mint paid invoices/orders."*

**Recommendation:** **delete** both functions (and any now-unused helpers they
alone call), keeping only the type-only SUPERSEDED audit record. If any audit
value is needed, it is already emitted. Confirm the Razorpay webhook has its own
`_mark_invoice_paid_by_reference` (it does) so nothing real is lost.

## FINDING 7 — MEDIUM — Unbounded `while True` full-table scan on an inbound hot path

**File:** `amplify/functions/messaging/inbound-whatsapp-handler/handler.py` (~L5066)

A `while True:` loop over `invoices_table.scan(FilterExpression=status in
['created','pending_payment','sent'], ConsistentRead=True)` paginates the **entire
InvoicesTable**, filtering after read, to find a contact's remaining pending
invoices. This runs on inbound-message handling. Steering `50-coding-style.md`
explicitly forbids it: *"Avoid unbounded `while True` on DynamoDB
`LastEvaluatedKey`; paginate with a bound or a query, not an exhaustive table
scan."*

**Impact:** cost and latency grow with total invoice count (not with the
customer's own invoices), on a hot path, forever. Other `.scan()` sites in the
same file (≈L2818, L3253, L3335, L4120, L4489, L4825) are worth the same review;
the L4489 outbound lookup at least prefers a GSI query and only *falls back* to
scan "if GSI missing".

**Recommendation:** query by a customer/phone key (a GSI such as the
`customerPhone`/contact index) instead of a full scan, bound the pages, and drop
`ConsistentRead` unless strictly required. Where a scan is unavoidable, add an
explicit page bound rather than `while True`.

## FINDING 8 — LOW — Float money math in receipt/PDF rendering

**File:** `amplify/functions/payments/invoice-engine/handler.py` (receipt/HTML/PDF
builders, e.g. ~L1999–2060, L2478–2538, L2762; `float(item.get('amount'))` with
`:,.2f`)

**Not on the authoritative path:** `_validate_invoice_amounts` (~L795) correctly
uses `Decimal` and enforces whole-paise, and the stored totals are the authority.
The `float()` usage is confined to **rendering** a receipt/PDF. Still, float
accumulation (`amt * qty`, summed line totals) can produce a one-paise display
drift between a rendered line breakdown and the stored total — a cosmetic but
customer-visible discrepancy on a financial document.

**Recommendation:** render from `Decimal` (quantize to 2 dp) and derive printed
line/breakdown figures from the stored authoritative fields, as the tax-halves
code (`_tax_halves_rupees`) already does. Low priority; correctness of the charged
amount is not affected.

## FINDING 9 — GOOD (no action) — Reference-id normalisation is defensive

`_sanitize_reference_id` (~L4282) documents and defends a previously-fixed
join-breaking bug: it no longer upper-cases or strips a value that is already
valid (Meta reference ids are case-sensitive and may contain dots), running legacy
upgrades only for non-acceptable values. This is the *correct* posture for a join
key and a good template for the shape fixes above.

## Updated remediation order

1. **Finding 1 (HIGH)** — inbound `transactions[]` shape + failed-branch (money/
   delivery evidence; same class as the incident).
2. **Finding 6 (MEDIUM)** — delete the dead-but-callable paid-state writers.
3. **Finding 7 (MEDIUM)** — replace the unbounded InvoicesTable scan with a bounded
   query on the inbound hot path.
4. **Finding 2 (MEDIUM)** — fail-closed success detection (`is_error()` not
   `get('success', True)`).
5. **Finding 3 (LOW/MED)** — canonical `template_status` helper.
6. **Finding 8 (LOW)** — Decimal-render receipt/PDF figures.
7. **Finding 4 (LOW)** — fail-closed Meta-sourced catalog visibility.

---

# Round 3 — the Payments → Ledger error-banner surface (from the screenshot)

The reported screenshot shows the **Payments → Ledger** view with a persistent red
banner: *"Sending is not confirmed. Check this invoice before retrying."* Traced
to `src/components/workspace/pay/PayFlow.tsx` `doSendPaymentLink` (~L432–440):
`showMsg(r.ok ? 'Sending is not confirmed. Check this invoice before retrying.'
: r.failure.message, 'error')`.

## FINDING 10 — NOT A BUG (the message is honest) — but three real UX defects around it

**The banner itself is correct.** It fires when the resend returned `r.ok` with a
status other than `payment_link_sent` — i.e. the WhatsApp payment-link/`wecarepay_wa`
send came back **unconfirmed**, the same "not confirmed" family as the native
binding/template issues. It is not a leak from another tab and not a false alarm.

Three genuine surface defects, though:

### 10a — MEDIUM — The read-only Ledger exposes a mutating send action
`src/pages/workspace/payments/index.tsx` renders the Ledger → Invoices view as
`<PayFlowPage embedded mode="invoices" />` — the **same `PayFlow` component**, which
at `activeTab === 'invoices'` (L827) renders **"Retry payment request" / "Send"**
buttons (L934–935, L1037) calling `doSendPaymentLink` (a send/mutation). Yet the
page subtitle and the standalone `InvoiceRecords.tsx` both advertise the ledger as
**read-only** ("one ledger for invoices, delivery evidence and payment state";
*"Read-only: sending, cancelling and renumbering stay on the screens built for
them"*). The contract and the behaviour disagree.
**Recommendation:** either (a) honour read-only on Ledger and move resend to
Collect only, or (b) update the ledger contract/subtitle to say it supports
resend. Pick one; today it claims read-only while offering a send.

### 10b — MEDIUM — The failure message is generic; it hides the real reason
"Sending is not confirmed. Check this invoice before retrying." does not surface
the delivery-log reason, Meta error code, or template status — the very fields that
distinguish a native-binding failure from a template/`PAUSED` problem from an
ambiguous send. The operator is told to "check this invoice" but the same screen
does not show the decisive `deliveryLogs[].error`/status inline near the banner.
**Recommendation:** on a non-`payment_link_sent` result, surface the server's
`sendStatus`/`downstreamStatusCode`/delivery-log `error` in (or beneath) the banner,
and auto-open the invoice's Delivery Logs. Tie into audit Findings 1/3.

### 10c — LOW — Money/delivery errors auto-dismiss after 4s
`showMsg` sets `setTimeout(() => setMsg(null), 4000)` for **all** messages,
including financial/delivery failures. A "payment not confirmed" error vanishing
in 4 seconds is easy to miss (and is likely why the screenshot had to be caught
quickly).
**Recommendation:** make `error`-type banners sticky (no auto-dismiss; require the
existing ✕), or extend their timeout substantially; keep the 4s auto-dismiss for
`success` only.

**Note:** `doSendPaymentLink` (L432) is a THIRD send path alongside the
`createdDelivery` state machine (L377–391) and `sendPaymentLinkResult`. All three
should converge on one helper that renders the same rich, non-auto-dismissing
failure detail, so the "why" is consistent wherever a send is attempted.

## FINDING 11 — MEDIUM/HIGH (UX correctness) — "Check this invoice before retrying" is the WRONG advice for terminal/in-progress states

**File:** `src/components/workspace/pay/PayFlow.tsx` `doSendPaymentLink` (~L439)
**Server:** `payments/invoice-engine/handler.py` `send_payment_link` (~L3756+)

The server returns **distinct, actionable** send states:
- `payment_link_sent` — sent (the only success).
- `payment_link_rejected` — **409, TERMINAL**: *"This payment request was refused
  and was not sent. Cancel and raise the collection again."* A re-invoke is refused
  identically. **Retrying cannot succeed.**
- `send_in_progress` + `deduplicated` — **200**: the reservation's send claim is
  already held; a second invoke is intentionally a **no-op**. **Retrying does
  nothing.**
- `PENDING` / `unknown` (502) — ambiguous; **reconcile before any retry**.

The UI collapses **all** of these into one line:
```js
r.ok && status === 'payment_link_sent'
  ? 'Sent …'
  : (r.ok ? 'Sending is not confirmed. Check this invoice before retrying.'
          : r.failure.message)
```
So a **terminal REJECTED** (surfaced as `r.failure.message` on a 409) and an
**already-claimed `send_in_progress`** (a 200, `r.ok` true, status not
`payment_link_sent`) both tell the operator to **retry** — which is exactly what
the server says NOT to do. This is almost certainly why the banner recurs on
repeated attempts: each "retry" re-hits an already-claimed/rejected reservation and
returns the same non-sent status, so the loop never resolves. The correct guidance
differs per state (cancel & re-raise; wait for the in-flight send; or reconcile a
captured-but-unbound payment — the `WD-PAY-C98523E305EE4747` case).

**Recommendation:** branch the UI on the server `status`/`sendStatus`:
- `payment_link_rejected` → "Refused and not sent. **Cancel and raise the
  collection again** — do not retry." (offer Cancel, not Retry)
- `send_in_progress`/`deduplicated` → "A send is already in progress; **don't
  resend**. Refresh to see its delivery status."
- `PENDING`/`unknown` → "Outcome unknown. **Reconcile in the ledger/webhook before
  retrying** — nothing has been charged."
- only a transient/network failure should offer a plain Retry.
Surface the delivery-log `error`/Meta code (Finding 10b) alongside. This removes
the misleading "retry" advice and the apparent retry loop.
