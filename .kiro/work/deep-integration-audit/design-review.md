# Design review round 4 — focused confirmation of round 3's 16 findings

**Verdict: `CHANGES_REQUESTED`** — 1 HIGH / 3 MEDIUM / 4 NIT, **4 blocking**.
**`mustResolveBeforeAnyCode: [1, 3, 4]`**

**All 16 round-3 findings are confirmed resolved.** The four blocking findings below are residual
defects *inside the resolution pass itself* — three stale or self-contradicting verification
transcripts, and one incomplete fix scope. None of them re-opens a round-3 finding and none of them
is a new broad scope. Three are one-line edits.

---

## Step 1 — base confirmed, no drift

```
git fetch origin && git rev-parse origin/stack
    -> 061b6e77c8a352d174c713834af0ca7d61b027b9
git rev-list --left-right --count HEAD...origin/stack   (worktree 0425dce1)
    -> 1  12
git merge-base HEAD origin/stack                        -> 53ed298e
```

| Declared in | Value | Matches live `origin/stack`? |
|---|---|---|
| `design.md` §0 | `061b6e77c8a352d174c713834af0ca7d61b027b9` | **yes** |
| `answers.md` CITATION BASE | `061b6e77c8a352d174c713834af0ca7d61b027b9` | **yes** |

`origin/stack` did **not** move again during the resolution-to-review gap, so the author's re-anchor
target is the current head and the `xcodex` session has not pushed since. Both headers are honest.

**The two hops between round 3's base and now, verified:**

```
git log --oneline e9e377ce..origin/stack  ->  4fe31824, 061b6e77          (TWO commits)
git diff e9e377ce..4fe31824     --stat    ->  12 files, +2121/-1   docs/outputs only
git diff 4fe31824..origin/stack --stat    ->  11 files, +1784/-13  INCLUDES CODE
git diff e9e377ce..origin/stack --stat    ->  16 files, +3905/-14  INCLUDES CODE
git diff e9e377ce..origin/stack --name-only | grep -E '^(amplify|scripts|src|tests)/'
    ->  amplify/functions/messaging/whatsapp-business-api/handler.py
    ->  tests/test_audit_payment_diagnostic.py
```

`design.md` §0 documents this correctly, including the +12/+13 shift, and **all nine of its
re-derived `whatsapp-business-api` citations reproduce** (`:5996`, `:6034`, `:3535`, `:3564`,
`:3620`, `:6399-6404`, `:5912`, `:6574`). `checkout/handler.py` was untouched by both hops, as §0
states, and `:3062`/`:3063`/`:3064`/`:3065`/`:3078`/`:3080`/`:3081` all reproduce exactly.

**§9, however, says the opposite** — that is blocking finding 1.

---

## Step 2 — per-finding confirmation (all 16)

| # | Sev | Round-3 finding | Result | Command used |
|---|---|---|---|---|
| **1** | HIGH | F-9 "live today" vs `SECURE_FILES_PAYMENT_ENABLED=false` | **CONFIRMED** | `git grep -n "_payment_enabled\|SECURE_FILES_PAYMENT_ENABLED" origin/stack -- .../secure-files/handler.py` → `255,261,981,1058,1156,1272`; `def _redeem` → `1405`, not among them |
| **2** | HIGH | F-9 re-issues from a TTL-swept row | **CONFIRMED** | `git grep -n expiresAt origin/stack -- .../vault_access.py` → none; `git show origin/stack:scripts/check_data_model_drift.py \| sed -n '186,196p'` → `TTL DISABLED` `:189`, `TTL ENABLED on expiresAt` `:193-194` |
| **3** | HIGH | False QA-recipient provenance; §8's unapplied correction | **CONFIRMED** | `git grep -n 918100640044 origin/stack -- docs/whatsapp/service-rollout/` → none; `git grep -l … \| wc -l` → `90`; `git ls-tree -r --name-only origin/stack \| grep -i qa-recipient` → none |
| **4** | MED | `answers.md` A/D/J/L stale; `:3080` cited for the gates | **CONFIRMED** | `git show origin/stack:.../checkout/handler.py \| sed -n '3060,3082p'`; `git grep -n verified_identity origin/stack -- amplify` |
| **5** | MED | Answer J specified O2 two incompatible ways | **CONFIRMED** | `git grep -n "def _claimable" origin/stack -- amplify` → `auth/customer-profile/handler.py:143`; `sed -n '156,172p'` → rules `:158-163`, return `:168`; `CONTACT_IDENTITY_CONFLICT` → `299,309,508,509` |
| **6** | MED | F-5's test unbuildable (`ClientError` renders its code) | **CONFIRMED** | `git grep -n "def is_conditional_failure" origin/stack -- .../order_keys.py` → `177`; body branches on `response['Error']['Code']` at `:186-187` |
| **7** | MED | F-2 test 5 contradicted `_read_row`'s behaviour | **CONFIRMED** | `git show origin/stack:.../order_keys.py \| sed -n '335,350p'` → `try :342`, `except Exception :344`, `raise :345-347` |
| **8** | MED | F-9 mis-named the auth envelope | **CONFIRMED** | `git show origin/stack:.../secure-files/handler.py \| sed -n '1800,1845p'` → `:1827`, `:1828`, `:1829-1830`, `:1836`, `:1840`, warning `:1806-1807` — all five rows exact |
| **9** | MED | Route-shape disagreement; impossible cap condition | **CONFIRMED** | `git show origin/stack:.../secure-files/handler.py \| sed -n '1424,1441p'` → `ConditionExpression=(` spans `:1428-1431`, `consumed = :false` on `:1430` |
| **10** | MED | Seven `Filter='sub'` sites, not six | **CONFIRMED** | `git grep -n "Filter='sub" origin/stack -- amplify` → **7**; `git grep -n is_cognito_subject origin/stack -- amplify` → absent; `re.fullmatch` in `customer_orders.py` → `57` |
| **11** | MED | `--revision-id` rule vs item 7's script | **CONFIRMED** | `git grep -n "update_alias\|publish_version\|no-publish" origin/stack -- scripts/set_lambda_env_flag.py` → `71, 145, 146, 147-148` (no `RevisionId`) |
| **12** | MED | Production invoke gated by two owner items | **CONFIRMED** | `design.md` scope table `:1807-1811`, row 3a `:1819`, row 5 `:1826`, §7 `:2018`/`:2049` |
| **13** | NIT | F-10's reason enum not derivable | **CONFIRMED** | `git show origin/stack:.../paid_vault.py \| sed -n '103p'` → single compound guard, left-to-right as stated |
| **14** | NIT | Off-by-one `metaCatalogAnalytics.ts` ranges | **CONFIRMED** | `git show origin/stack:src/lib/metaCatalogAnalytics.ts \| sed -n '1,14p'` → comment `:3-5`, `:6`, `:8`, `:11`, builder `:12-13`; `Purchase` → `:101`; `catalogContentId` → `:64` |
| **15** | NIT | F-1's `caplog` mechanism undocumented | **CONFIRMED** | `git show origin/stack:.../lambda_utils/logging.py \| sed -n '14,32p'` → `get_logger :17`, `getLogger :22`, `setLevel :24`, no handler, no `propagate=False`; handler logger at `:57` |
| **16** | NIT | F-6's snippet needed two imports | **CONFIRMED** | `git show origin/stack:.../paid_submit_request.py \| sed -n '1,16p'` → `hashlib :8` … `order_keys/store :13`; no `logger`, no `json` |

**Not confirmed: none.** On the seven the step prompt singled out as most likely wrong:

- **(1/F-9)** gating is now stated correctly — the flag's four refusal sites, `_redeem` ungated, the
  native minter in a different Lambda, live residue scoped to the `:1459-1460` copy, and §5 row 4c
  split into a copy half that ships regardless and a route half contingent on `4c-read ≥ 1`.
- **(2)** the TTL sweep is fully analysed in a three-origin lifetime table, option (b) chosen
  (durable **file** row), option (a) explicitly rejected *as a TTL extension*, and the cap **and**
  counter moved onto the file row. The swept-grant test is specified with an empty grants table.
- **(3)** `answers.md` retracts the claim in so many words and `design.md` §8 / F-8 item 6 are
  imperative and labelled UNAPPLIED. (One stale number survives in the transcript — finding 3.)
- **(4)** A/D/J/L all carry current-base values and **L no longer cites `:3080` for any gate**; a
  table now names why `:3080`/`:3081` were the worst possible wrong lines.
- **(6)** `OpaqueConditionalFailure(ClientError)` overriding `__str__` while preserving `.response`,
  with both premise assertions and the branch-on-`.response` invariant.
- **(7)** injection is moved outside `_read_row`'s `try` (two tabulated points) and the test renamed.
- **(8)** the route is in the `_customer_identity` envelope at `:1827-1836` with a BINDING
  prohibition on the `:1840` Operator block, corrected in `outputs` §6.5 too.
- **(9)** one route shape, the alternative deleted, `attribute_not_exists(reissueCount) OR …` marked
  mandatory in both documents, with a full re-read mapping for `ConditionalCheckFailedException`.
- **(10)** seven sites acknowledged, both inline regexes converted (so the pattern really does appear
  once), and the design correctly corrects the *review* on `:57` vs `:58`.
- **(11)** the preferred conditional route is written into row 7 in five steps and generalised to
  every alias move; the unconditional exception is rejected with its reason.
- **(12)** O13 cited everywhere 3a appears; O10 reserved for deploys, with a disjoint scope table.

---

## Step 3 — safety invariants: all hold

No gate opened (items 8, 9 and F-7's remainder are STOP). No payment-config mutation and no payment
object created, read or mutated. No deletion (§3 is an inventory). No live send. No fleet-wide
publisher — `set_lambda_env_flag.py` runs `--no-publish` with a manual per-function conditional alias
move. Every production step is OWNER CONFIRM, with O10 (deploys) and O13 (the single inspect invoke)
disjoint. `get-secret-value` / `batch-get-secret-value` appear **only** as prohibitions.

**No TTL lengthened.** F-9 mints on the ordinary 60 s `DOWNLOAD_URL_TTL` (`:215`), and the option
that would have extended the grant row's `expiresAt` on redeem is explicitly **rejected** — the
entitlement proof is read from the already-durable `SecureFilesTable` row instead, so nothing is
extended, not even the entitlement-proof retention. F-11 *lowers* the stated env value
(`21600` → `900`) to match the existing clamp, behaviour unchanged.

**Auth / ownership / signature / IAM / isolation only tightened.** F-9 adds a fourth caller to the
existing `_owned_active_file` chokepoint and never touches `consumed`; F-4 adds a guard to five
unguarded sites and collapses two inline regexes into one shared helper; the two F-9 sensitivity
tests exist to fail if the fix ever becomes a loosening.

---

## Blocking findings

### 1. HIGH — §9 contradicts §0 on whether code citations moved, and its recorded `git diff` does not reproduce

**Where:** `design.md` §9 opening paragraph and the command block under it (≈`:2261-2272`).

§9 states *"The single intervening commit is **docs-and-outputs only**, so no code citation moved"*
and records:

```
git diff e9e377ce..origin/stack --stat   -> 12 files, +2121/-1, no amplify/ scripts/ src/ tests/
```

Neither is true at `061b6e77`. There are **two** intervening commits and the actual range diff is
**16 files, +3905/-14**, including `amplify/functions/messaging/whatsapp-business-api/handler.py` and
`tests/test_audit_payment_diagnostic.py`. The recorded figures are the hop-1 (`e9e377ce..4fe31824`)
diff pasted against the full range.

§0 of the same document gets this right — it documents both hops, states *"Hop 2 DID touch code"*,
and re-derives nine citations in that handler. So the two sections disagree on the most load-bearing
fact in the plan. Those citations carry F-9's native reach-path (`:5996-6000`), plus F-4's and F-6's
live sites scheduled under §5 row 4b-ii. A reader who trusts §9 — the section offered as proof of
resolution — concludes no re-derivation is needed in that file, which is exactly what round 3's
finding 4 punished.

**Fix.** Replace the paragraph and block so §9 defers to §0 instead of restating it:

> **Base re-anchored first, before any finding was touched.** The review verified against
> `e9e377ce`; `origin/stack` is now `061b6e77` — **1 ahead / 12 behind**. The base moved **twice**
> during this resolution pass and **hop 2 changed code**. See §0 for the per-citation re-derivation.
> Summary: hop 1 (`e9e377ce`→`4fe31824`) was docs-and-outputs only; hop 2
> (`4fe31824`→`061b6e77`) edited `amplify/functions/messaging/whatsapp-business-api/handler.py` and
> `tests/test_audit_payment_diagnostic.py`, shifting every citation in that handler below line 321
> by **+12** and below 6106 by **+13**. Two document citations in the QA-send authority chain also
> moved.

```
git diff e9e377ce..4fe31824     --stat  -> 12 files, +2121/-1,  docs/outputs only
git diff 4fe31824..origin/stack --stat  -> 11 files, +1784/-13, INCLUDES CODE
git diff e9e377ce..origin/stack --stat  -> 16 files, +3905/-14, INCLUDES CODE
```

### 2. MEDIUM — §9's coverage claim contradicts itself in consecutive sentences

**Where:** `design.md` §9, ≈`:2274-2276`.

> **139 load-bearing citations were individually re-verified** at `061b6e77` … All 97 pass.

A reader cannot tell whether 97 or 139 citations were checked, or what became of the 42-citation
difference. This is the headline assurance the whole §9 table rests on, in a document whose central
lesson is that an unverified number is not evidence. My spot-checks found no actually-failing
citation, so this is bookkeeping, not a hidden failure — but as written it cannot be audited.

**Fix.** State one number, and keep inventory separate from coverage:

> **139 load-bearing citations were individually re-verified** at `061b6e77` with `git grep -n` plus
> a per-line `git show | sed -n '<n>p'` substring assertion. **All 139 reproduce; 11 carried changed
> values, each listed in the row that uses it.**

If 97 is the hand-checked subset, say so explicitly and name what the remainder is.

### 3. MEDIUM — `answers.md`'s QA-authority transcript records `continue-prompt.txt:7`, the pre-hop-2 value, four lines above its own table that correctly says `:9`

**Where:** `answers.md` "Binding authority re-established" — the fenced transcript (≈`:98-102`) vs
the table below it (≈`:107-111`).

The transcript records `… continue-prompt.txt -> 7`. At `061b6e77` that command returns **9**; `7` is
the `4fe31824` reading and `5` the `e9e377ce` one. The table four lines below correctly gives `:9`,
and `design.md` §0 correctly traces `:5 → :7 → :9` as *"moved in BOTH hops"*. The transcript simply
was not refreshed.

This is load-bearing: F-8 item 6 must edit that exact prose line, and line 7 at `061b6e77` is a
different line (`HISTORICAL CONTINUATION BELOW — overridden by the current checkpoint above:`). It
also sits inside the one block whose purpose is to demonstrate re-derivation discipline on the
authority chain for the only rule governing live WhatsApp sends.

**Fix.**

```
git grep -n "0044" origin/stack -- docs/whatsapp/service-rollout/continue-prompt.txt -> 9
    # :5 at e9e377ce, :7 at 4fe31824 — moved in BOTH hops
```

### 4. MEDIUM — the copy fix is scoped to `:1459-1460`, but the identical "Please pay again" string also sits at `:1224-1225`

**Where:** `design.md` F-9 copy bullet (`:1507`) and invariant table row (`:1540`); §5 row 4c half
(i); `outputs/…architecture.md` §6.5 (`:603`) and the V-1 row (`:558`).

```
git grep -n 'Please pay again' origin/stack -- amplify/functions/core/secure-files/handler.py
    -> 1225   (_redeem_after_reconcile, except ClientError arm at :1220)
    -> 1460   (_redeem's refusal arm)
```

Every document scopes the correction to `:1459-1460`; none mentions `:1225`.

The scoping is **right for today** — `_redeem_after_reconcile` is entered only when
`_reconcile_grant` returns `True` (`:1453-1454`), and that function returns `False` immediately while
the flag is off (`:1156-1157`). So this is not a live-reachability error, and round 3 finding 1's
requirement is met.

The problem is the completeness claim. F-9's invariant table assigns *"A paid customer is never told
to pay again"* to *"the `:1459-1460` copy"*, and §5 item 8 (enable native checkout, **STOP**) lists
F-9 among its prerequisites. The moment item 8 opens that flag, a paid-and-consumed grant taking the
reconcile arm lands on the same sentence at `:1225`, with F-9 recorded as done.

**Fix.** Cover both sites and say why:

> Correct the refusal copy at **`:1459-1460`** (`_redeem`) **and at `:1224-1225`
> (`_redeem_after_reconcile`, the identical string)** so a paid-and-consumed grant is never told to
> pay again. `:1225` is **not** live-reachable today — `_redeem_after_reconcile` is entered only when
> `_reconcile_grant` returns `True` (`:1453-1454`), and that returns `False` while
> `_payment_enabled()` is false (`:1156-1157`) — but it becomes reachable the moment §5 item 8 opens
> the flag, and item 8 lists F-9 as satisfied. Fixing one site and not the other re-introduces the
> defect at the gate opening.

Then amend the invariant-table row to name both ranges. Leaving `:1225` alone is acceptable **only**
as an explicit, owner-visible exception recorded in item 8's prerequisite list, stating that F-9 does
not satisfy its own invariant once the payment flag opens.

---

## Non-blocking findings

### 5. NIT — §0's shift table labels both value columns with the same base, and row 1 is self-inconsistent

The header reads `| Citation | At 061b6e77 | **At 061b6e77** | Shift |`; the first value column should
be `4fe31824`. Row 1 then reads `:5996-6000 | :5996-6000 | +12`, which is arithmetically impossible —
the pre-hop value is `:5984`. Every bolded current-base value reproduces (I checked all nine), so no
load-bearing number is wrong, but the table cannot sanity-check itself in the one section that
forbids trusting a number.

**Fix.** Relabel the header `| Citation | At 4fe31824 | **At 061b6e77** | Shift |` and set row 1's
first cell to `:5984-5988`.

### 6. NIT — `answers.md` J calls `customer_orders.py:61` "a fifth caller" in a four-row table

`git grep -n verified_identity origin/stack -- amplify` returns four call sites (`checkout:3081`,
`catalog_services:56`, `customer_commands:84`, `customer_orders:61`) plus the definition at
`catalog_service_checkout.py:35`. The line number and the correction are right; only the ordinal is
off, counting the definition as a caller.

**Fix.** "a **fourth caller** revision 3 omitted entirely", and caption the table "four call sites;
the definition is at `catalog_service_checkout.py:35`." Mirror it in §9's finding-4 row.

### 7. NIT — `answers.md` J labels the `_claimable` re-derivation "Re-verified at `e9e377ce`"

Under a header declaring `061b6e77`. The values are all correct at `061b6e77` (the file was touched
by neither hop), so only the label is stale — which is the one thing §0 says a reader must never have
to second-guess.

**Fix.** "Re-verified at `061b6e77`:" plus "(file untouched by both upstream hops, so these are
unchanged since `e9e377ce`)".

### 8. NIT — the `DownloadGrantsTable` TTL citation differs between §9 and F-9.0

§9's finding-2 row cites `check_data_model_drift.py:193-194` and claims to have corrected the
review's `:191-196`; F-9.0's body still says `:191-196`. Both land inside the right dict entry
(`:191` is the key, `:193-194` the TTL sentence), so neither misleads.

**Fix.** Use `:193-194` in both, or phrase it once as "`:191-196` (the `DownloadGrantsTable` entry;
the TTL sentence is on `:193-194`)" and reuse that wording.

---

## Verified assumptions

- `origin/stack` = `061b6e77c8a352d174c713834af0ca7d61b027b9`, exactly as declared in **both**
  `design.md` §0 and `answers.md`'s header; worktree `0425dce1`, 1 ahead / 12 behind, merge base
  `53ed298e`. The base did **not** move again.
- The two hops are as §0 describes, and all nine re-derived `whatsapp-business-api` citations
  reproduce: `:5996`, `:6034`, `:3535`, `:3564`, `:3620`, `:6399-6404`, `:5912`, `:6574`.
- `checkout/handler.py` untouched by both hops; `:3062`, `:3063`, `:3064`, `:3065`, `:3078`, `:3080`
  (Cognito `Filter`), `:3081` (`verified_identity`) all exact — every F-4 / answer-L correction holds
  and `:3080` is no longer cited for a gate.
- `secure-files/handler.py`: `_payment_enabled` `:255`/`:261`, refusals `:981`/`:1058`/`:1156`/`:1272`;
  `_redeem` `:1405` ungated; `:1427` and `:1428-1431` with `consumed = :false` on `:1430`; customer
  envelope `:1827-1836` with `_customer_identity` `:1828` and 401 `:1829-1830`;
  `require_auth(event,'Operator')` `:1840`; inline warning `:1806-1807`; "pay again" at `:1460`
  **and** `:1225`.
- `vault_access.py` writes **no** `expiresAt`; grant dict `:64-67`; the `SecureFilesTable` write
  carrying `vaultAccessGrantId` + `vaultPaymentStatus='PAID'` at `:71`.
- `check_data_model_drift.py`: `SecureFilesTable` "TTL DISABLED" `:189`; `DownloadGrantsTable`
  "TTL ENABLED on `expiresAt`" `:193-194` — the durable/swept asymmetry F-9 relies on is real.
- `order_keys.py`: `OrderIdentityUnavailable` `:169`, `is_conditional_failure` `:177` branching on
  `response['Error']['Code']` at `:186-187`, `_read_row` `:335` with `try :342` / `except Exception
  :344` / `raise :345-347`, `resolve_payment_reference` `:380`.
- Exactly **seven** `Filter='sub'` sites; `customer_commands` guard `:80` / `Filter :83`;
  `customer_orders` guard `:57`, raise `:58`, `Filter :60`, `verified_identity :61`;
  `is_cognito_subject` absent from the tree.
- `verified_identity` has four call sites plus the definition at `catalog_service_checkout.py:35`;
  `paid_submit_request.py:90`/`:142` and `paid_vault.py:69` use inline checks — answer J's correction
  of revision 3 is right.
- `auth/customer-profile/handler.py`: `_claimable :143`, docstring rules `:158-163`, return `:168`,
  `_owned_contact :171`, `checkoutCustomerId` writer `:263`, conditional updates `:320`/`:385`,
  `CONTACT_IDENTITY_CONFLICT` `:299`/`:309`/`:508-509`.
- `set_lambda_env_flag.py`: `--no-publish :71`, guard `:145`, `publish_version :146`, `update_alias
  :147-148` with **no** `RevisionId` — item 7's mechanism change is necessary and the chosen route is
  the review's preferred one.
- `lambda_utils/logging.py`: `get_logger :17`, `getLogger :22`, `setLevel :24`, `log_event :28`, no
  handler added, `propagate` never disabled; `meta-catalog-sync/handler.py:57` binds the logger.
- `paid_submit_request.py` imports exactly `hashlib :8` … `order_keys`/`store :13` — no `logger`, no
  `json`.
- `metaCatalogAnalytics.ts`: comment `:3-5`, `META_DATASET_ID :6`, `META_PIXEL_ID :8`,
  `PURCHASE_KEY :11`, builder `:12-13`, `catalogContentId :64`, `Purchase :101`.
- `paid_vault.py:103` is the single compound guard, so F-10's stated reason order is derivable.
- `docs/whatsapp/service-rollout/`: no full E.164 anywhere; suffix-only prose at `README.md:59` and
  `continue-prompt.txt:9`; 90 tracked files carry the full number; `docs/execution/qa-recipient.md`
  does not exist.
- `outputs` §6.5 opens with a subordination blockquote, carries one route shape, the mandatory `OR
  attribute_not_exists` arm, the `_customer_identity` envelope with an explicit "NOT `require_auth`",
  and six tests matching `design.md`'s six.

## Unverified / wrong assumptions

**Wrong and blocking**

- §9: *"The single intervening commit is docs-and-outputs only, so no code citation moved"*, and the
  `12 files, +2121/-1, no amplify/ scripts/ src/ tests/` transcript — two commits, 16 files,
  +3905/-14, including `whatsapp-business-api/handler.py` (finding 1). §0 is correct.
- §9: *"139 load-bearing citations … All 97 pass"* — the two counts cannot both be the set size
  (finding 2).
- `answers.md`: the recorded `continue-prompt.txt -> 7` — the reproducing value is `9` (finding 3).
- F-9's invariant *"A paid customer is never told to pay again"* owned by the `:1459-1460` copy alone
  — the identical string also sits at `:1224-1225` and becomes reachable when item 8 opens the flag
  (finding 4).

**Wrong but not blocking**

- §0's shift-table header labels both value columns `061b6e77`; row 1 shows `:5996-6000 →
  :5996-6000` with a +12 shift (finding 5).
- `customer_orders.py:61` called "a fifth caller" in a four-row table (finding 6).
- `_claimable` bullets labelled "Re-verified at `e9e377ce`" under a `061b6e77` header; the values are
  nonetheless correct (finding 7).
- `DownloadGrantsTable` TTL cited `:191-196` in the body and `:193-194` in §9 (finding 8).

**Correctly flagged unverified, no action needed**

Graph `100`/subcode 33 (needs the Meta token; `get-secret-value` forbidden) · deletion vs permission
on `1607047307067517` (O1) · `items_batch` write authority on `1457045652952851` ·
`wecare_default_download` approval and button (O12) · dataset id as an `fbq` browser target (P2/T-1)
· Wix product revision 4 vs 5 (C4) · v87–v89 vs committed source (O11), now correctly stated as
uncertified by anyone · Flow `1107164111921876` DRAFT vs PUBLISHED (C2, self-enforcing) · Orders Flow
`2167802357142172` (out of scope) · the durable-grant population count, deliberately deferred to §5
row 4c-read with F-9's route half branched on its result.

**Not re-verified by this review, by instruction**

All CloudWatch captures · all Lambda alias / version / `RevisionId` / `CodeSha256` / environment
values, including live **34** / `01e8e9ef…` for `wecare-secure-files` and
`SECURE_FILES_PAYMENT_ENABLED=false` · the 157 focused / 10394 whole-suite baseline · the DynamoDB
and Cognito reads behind answer J. §0, §5 row 0 and §6 all require these to be re-read immediately
before use, so no plan step depends on them still being true.

---

## Must resolve before any code

1. **Finding 1** — fix §9's re-anchor paragraph and diff block so it agrees with §0 that hop 2 moved
   code in `whatsapp-business-api/handler.py`.
2. **Finding 3** — correct the `continue-prompt.txt` transcript value to `9`.
3. **Finding 4** — bring `:1224-1225` into the copy correction, or record an explicit owner-visible
   exception in item 8's prerequisites.

Finding 2 and the four NITs can ride with these. Everything else in the design is implementable as
written.
