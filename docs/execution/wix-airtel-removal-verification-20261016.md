# Deep Audit #7 — Wix/Airtel removal: VERIFICATION (2026-10-16)

Re-audited from scratch against current `stack` (`35f8cc6d`) and the live account
`775261844268`, as the program document requires ("do not trust the old audit").

## Result: COMPLETE

Wix and Airtel are absent as current application/provider concepts. PR #519
("remove Wix and Airtel across the stack") is merged; this confirms the end state
holds and identifies the only remaining matches as justified false positives.

## Evidence

**Source (`src/` + `amplify/functions/`), case-insensitive:**
- `wix` → **1** match. `airtel` → **4** matches. No others.

**Workspace / config / content / navigation:** 0 Wix or Airtel *provider*
references (grep of `src/pages/workspace/`, `src/config/`, `src/content/`,
excluding the UPI false positive below).

**Live AWS:** 0 Lambdas, 0 DynamoDB tables, 0 Secrets Manager secrets whose name
contains `wix` or `airtel`.

## The 5 remaining matches are false positives — DO NOT "fix" them

| Match | File | Why it must stay |
| --- | --- | --- |
| `RETAILER_PREFIX = "wix"` | `amplify/functions/shared/lambda_utils/ecommerce/meta_catalog_sync.py:62` | A **Meta Commerce retailer-ID prefix** for catalog item IDs, not a Wix runtime dependency. Existing catalog items on Meta's side are keyed with this prefix; changing it without a Meta-side migration orphans the mapping. This is exactly the §9 "don't string-replace a schema key" case. Renaming it is a gated catalog-migration task, not a text edit. |
| `...rzp@rxairtel` ×4 | `src/config/constants.ts:112`, `payment_readiness.py:46`, `outbound-whatsapp/handler.py:427`, `whatsapp-business-api/handler.py:3490` | The literal is a **Razorpay UPI VPA** (`wecaredigitalbh511413.rzp@rxairtel`). `rxairtel` is the Airtel Payments **Bank** handle inside a payment address — not the Airtel voice/SMS provider. Editing it breaks UPI payment routing. |

Neither is the Airtel/Wix *provider*. The program's intent (no Wix/Airtel as a
current provider surface) is satisfied with these two items correctly retained.

## Program checklist (from the WX document, verified)

- Wix absent from Workspace as a provider — **yes**
- Airtel absent from Workspace (no historical tabs/dropdowns/cards) — **yes**
- Customer frontend does not depend on Wix/Airtel — **yes**
- No Wix/Airtel-only page / Lambda / route / secret / IAM remains — **yes**
  (live AWS enumerated above)
- Wix/Airtel AI tool descriptions removed — **yes** (no `get_wix_*` tools found)
- Voice/SMS/RCS architecture provider-neutral — **yes** (no Airtel refs in the
  messaging handlers beyond the UPI VPA)

## Zero-reference final counts

| Token | Count (src+functions) | Disposition |
| --- | --- | --- |
| `wix` | 1 | Meta retailer prefix — justified |
| `WIX_` | 0 | — |
| `wixOrder` / `wixCart` | 0 | — |
| `airtel` | 4 | UPI VPA bank handle — justified |
| `AIRTEL_` | 0 | — |
| `retired_store` / `legacy_history` | 0 in src/functions | — |

Searched without excluding directories. Docs still contain historical Wix/Airtel
mentions by design (archival evidence); the program scopes removal to the current
*application/runtime*, which is clean.

---

# CLOSEOUT — Deep Audit #7 is CLOSED (2026-10-16)

Final targeted re-verification (no build loops run), confirming the end state:

- `retired_store` / `legacy_history` / deep-store / provider-tombstone modules — **0 files** (WX §7/§8 satisfied; the compatibility layer is gone).
- Wix-named schema fields (`WixOrderIds`, `WIX_ORDER_IDS_TABLE`, `wixOrderId`, `wixCartId`, generic `wix*`) — **0** (WX §9 satisfied).
- Wix/Airtel AI tool descriptions (`get_wix_*`, `airtel c2c/call`) — **0** (WX §13 satisfied).
- Live AWS Lambdas / DynamoDB tables / Secrets named `wix`/`airtel` — **0**.

The program's "Definition of Done" is met. The WX document is **closed**. The
items below are **not** reopeners — they are the honest residual list: justified
exceptions, optional improvements, and one documented migration gap.

## A. Pending actions (justified exceptions — KEEP, do not "fix")

| # | Item | Action | Why |
| --- | --- | --- | --- |
| A1 | `RETAILER_PREFIX = "wix"` (`meta_catalog_sync.py:62`) | **KEEP** | It is Meta's `product_retailer_id` namespace. Every live Meta catalog item and every inbound WhatsApp catalog order carries `wix:<productId>:<variantId>`. The module explicitly documents it as an external contract. Changing it ≠ cleanup; it breaks the Meta↔ProductsTable join and inbound order resolution. |
| A2 | UPI VPA `…rzp@rxairtel` (4 files) | **KEEP** | Razorpay UPI address; `rxairtel` is the Airtel Payments **Bank** handle, not the voice/SMS provider. Editing breaks payment routing. |

## B. Improvement opportunities (optional, owner-gated, NOT required for closeout)

| # | Improvement | Effort / risk | Note |
| --- | --- | --- | --- |
| B1 | Re-key the Meta retailer-id namespace off the `wix:` spelling to a neutral prefix (e.g. `wd:`). | High / high-risk | A real Meta catalog migration: publish new ids, carry in-flight WhatsApp carts across, retire old ids. **Cannot run while `META_CATALOG_SYNC_ENABLED=false`.** Only worth doing if the `wix:` string itself is objectionable; functionally it is already provider-neutral. Needs owner approval + a cutover window. |
| B2 | Rename the UPI VPA variable/comment context so `rxairtel` reads less like the provider. | Low / none | Pure readability; the value cannot change (it is the live payment address). A one-line comment "(Airtel Payments Bank handle, not the Airtel comms provider)" at `constants.ts:112` would stop a future agent flagging it. |
| B3 | Add a lint/CI guard: fail if a NEW `wix`/`airtel` provider token appears in `src/`+`functions/` (allowlisting A1/A2). | Low / none | Prevents regression. `scripts/check-wix-policy.sh` already exists for runtime; extend its allowlist to cover these two exceptions so the zero-reference state is enforced, not just verified once. |

## C. Gaps (known, documented — not defects)

| # | Gap | Status |
| --- | --- | --- |
| C1 | The `wix:` retailer prefix is a lingering *spelling* of a provider name in an active contract. | **Documented, accepted.** The code comment at `meta_catalog_sync.py:38-55` already explains the contract and the migration cost. No runtime Wix dependency exists behind it. Tracked as improvement B1 if the owner ever wants the spelling gone. |
| C2 | Historical Wix/Airtel mentions remain in `docs/`. | **By design.** WX scopes removal to the current application/runtime (clean); docs retain archival evidence. `docs/audit-doc-index.md` marks which are superseded. |

## Verdict

**WX / Deep Audit #7: COMPLETE and CLOSED.** No pending *cleanup* work. Two
justified exceptions kept (A1/A2), three optional improvements noted (B1-B3), two
documented non-defect gaps (C1/C2). Next: CON1 (pages consolidation).
