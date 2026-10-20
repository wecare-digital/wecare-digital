# WhatsApp / payment RE-AUDIT — against current `stack` (2026-10-20, head 8bfb19f1)

> Re-run of the WhatsApp/Meta/payment audit after a lot merged since the first
> pass: binding live-shape (#1076), fail-closed Meta success (#1078), and the new
> **image-only invoice delivery** (#1089 + deploy #1090/#1091). This re-audit
> (a) re-checks every prior finding's CURRENT state, and (b) audits the
> newly-merged code. Read-only, code-only; no live AWS/Meta calls.

Legend: ✅ fixed/clean · 🟡 partial/gated · ❌ still open · 🆕 new finding

---

## A. Status of prior findings on current `stack`

| # | Finding | Current state | Where |
| --- | --- | --- | --- |
| 1 | Inbound plural `transactions[]` parsing | ✅ **FIXED upstream** | `_select_payment_transaction` (L4349) reads `transactions[]`, falls back to singular |
| 2 | Fail-open `get('success', True)` | ✅ **FIXED upstream** (#1078 `mutation_succeeded`) | partner-onboarding / whatsapp-business-api |
| 3 | Template-status canonicalisation | ✅ **FIXED upstream** | `shared/lambda_utils/template_status.py` |
| 6 | Dead-but-callable paid-state writers | ❌ **STILL OPEN** | `_mark_invoice_paid_by_reference`, `_generate_invoice_for_captured_payment`, `_check_and_notify_balance_due` still defined in inbound-whatsapp-handler |
| 7 | Unbounded `while True` scan | ❌ **STILL OPEN** | inbound-whatsapp-handler **L5087** |
| 8 | Float receipt money | ❌ **STILL OPEN** | 6 `float(invoice.get('subtotal'/'total'))` sites in invoice-engine |
| 10/11 | State-aware send guidance + read-only Ledger | 🟡 **PARTIAL** | PayFlow still has only the inline `send_in_progress` branch (L406/L480); the single `describeSendOutcome` interpreter + sticky errors + read-only Ledger are **not** on stack |

**Why 6/7/8/10/11 are still open:** they are exactly the fixes sitting in **open
PR #1087** (`fix/meta-whatsapp-audit-reconciled-20261020`), not yet merged. No new
work needed — **merging #1087 closes all five.** Re-verified the PR still applies
cleanly on current stack head (it was cut from the latest stack).

---

## B. New findings from the image-only invoice delivery (#1089)

#1089 retired PDF generation and fail-closes the PDF route (`410 INVOICE_IMAGE_ONLY`).
Mostly clean — customer-invoice (`ecommerce/customer-invoice`) correctly defaults
`format=png` and rejects anything outside `ALLOWED_FORMATS = {png}` with
`UNSUPPORTED_FORMAT`. Two residues:

### 🆕 FINDING 12 — LOW/MED — Dead PDF path still invokes the retired route (inside an already-dead function)
`inbound-whatsapp-handler.py` ~L5006–5024 ("Step 4: Generate PDF (async)") still
`lambda_client.invoke`s `wecare-invoice-engine` with
`rawPath: /invoices/{id}/generate-pdf` — which now returns `410
INVOICE_IMAGE_ONLY`. **However**, this block lives *inside*
`_generate_invoice_for_captured_payment`, which is one of the **dead zero-caller
functions from Finding 6**. So it won't actually fire today — but it is a perfect
illustration of the Finding-6 hazard: *a retired function still contains a call to
a now-retired endpoint; if anything ever re-wires that function back in, it
immediately errors.* 
**Recommendation:** closed by **Finding 6's deletion** (PR #1087 removes the
whole function). No separate fix needed — but it raises Finding 6 from "tidy-up"
to "actively stale/broken code," so **merge #1087.**

### 🆕 FINDING 13 — LOW — `generate_invoice_pdf` is now dead code
`invoice-engine/handler.py` L3055 `generate_invoice_pdf(...)` is unreachable: the
route guard at L391 returns `410` before it, and there is no other caller (only a
docstring reference at L1714). Per steering *delete dead code, don't gate it*, the
function body (and any PDF-only helpers/deps it alone used, e.g. reportlab-style
rendering) should be removed, not left behind the fail-closed route.
**Recommendation:** delete `generate_invoice_pdf` and its PDF-only helpers; keep
the `410 INVOICE_IMAGE_ONLY` route guard (it is the correct fail-closed shim for
old clients). Scope: invoice-engine only; do not touch the PNG/image path.

### Clean (no action) — things #1089 did right
- Customer invoice download is image-only and fail-closed on format.
- The retired route returns a clear, machine-readable `INVOICE_IMAGE_ONLY` code,
  not a silent success — good.

---

## C. Nothing new broken in the deploy commits
#1090/#1091 (runtime deploy triggers for invoice-engine + Razorpay webhook) and
#1089's client/UI PDF-action removal are deploy/UX plumbing; no money-authority or
parsing logic changed. No new finding.

---

## D. Net: what to do now

1. **Merge PR #1087** — closes Findings 6, 7, 8, 10/11 (and neutralises Finding 12
   by deleting the dead function). This is the single highest-value action; the
   code is written, reviewed, and green.
2. **Finding 13** (small) — delete the now-dead `generate_invoice_pdf` body +
   PDF-only helpers in invoice-engine. Can fold into #1087 or ship as a tiny
   follow-up.
3. Prior findings 1/2/3 are confirmed **closed** on stack — no action.
4. The native-payment **re-drive** of the stuck captured references
   (`WD-PAY-C98523E305EE4747`, `WD-PAY-9B6BA71755A74E0A`) remains an **operator**
   step (live creds) now that the binding fix #1076 is deployed — see
   `meta-payment-binding-redrive-*.md`. Not a code finding.

**One-line summary:** the re-audit found **no new money-authority defect**; the
open items are the already-written fixes in **PR #1087** plus one small dead-PDF
cleanup (Finding 13). The image-only change (#1089) landed cleanly apart from dead
residue that #1087's Finding-6 deletion removes.
