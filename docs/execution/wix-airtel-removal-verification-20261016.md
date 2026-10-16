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
