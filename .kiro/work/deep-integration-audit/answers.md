# Deep Integration Audit — Answers A–U

# Deep Integration Audit — Answers A–U

**Revision 3**, after design review 2 (`design-review.json`, verdict `CHANGES_REQUESTED`, 2 HIGH /
8 MEDIUM / 4 NIT) and **re-anchored after design review 3** (3 HIGH / 9 MEDIUM / 4 NIT, 12
blocking). Review 2's findings are answered in `design.md` §8; review 3's in `design.md` "Design
review round 3 resolution".

> ## CITATION BASE
> **Every `file:line` below is relative to `origin/stack` =
> `061b6e77c8a352d174c713834af0ca7d61b027b9` (`061b6e77`, "fix: retire obsolete Meta Flows with
> WABA-aware lifecycle API", 2026-10-09T11:02:30+05:30).** Divergence:
> `git rev-list --left-right --count HEAD...origin/stack` → **`1  12`** (1 ahead, 11 behind), merge
> base `53ed298e`. **Rebase target = `061b6e77`.** Derived with
> `git grep -n '<pattern>' origin/stack -- '<path>'`.
>
> **Rows in `docs/execution/change-authority-matrix.md` are numbered independently of file lines;
> citations here are FILE LINES.**
>
> **What this header does and does not promise** (review 3 finding 4 — revision 3's header claimed
> blanket re-derivation while answers **A**, **D**, **J**, **L** and the **T**/**P4** ranges still
> carried revision-2 values). It promises exactly what `design.md` §0 promises, and no more:
>
> - **one declared base**, named above, for the whole document;
> - **load-bearing citations re-derived at that base**, with an anchor pattern where the line number
>   drives a code change;
> - **re-derivation is mandatory before use.** A line number is a fact about a commit, not about the
>   repository. `origin/stack` moved three times across this audit's three revisions
>   (`53ed298e` → `4e259800` → `e9e377ce` → `4fe31824` → `061b6e77`). **Do not trust a number here without
>   re-running `git grep -n` at the then-current base.**
>
> Non-load-bearing ranges — narrative pointers that drive no fix — are marked where known to be
> approximate rather than silently presented as exact.

Worktree: `/Users/wecaredigital/wecare-digital/wecare-digital/.worktrees/deep-integration-audit`
Branch `deep-integration-audit` @ `0425dce1`. **`origin/stack` is now `061b6e77` — twelve commits
ahead of this worktree, up from ten at revision 3's first derivation and four at revision 2.** The
base moved **twice during the round-3 resolution pass**: `e9e377ce` → `4fe31824` (docs only) →
`061b6e77` (**which changed `whatsapp-business-api/handler.py`**, shifting every citation into that
file; see `design.md` §0 for the per-line table). All live reads are
read-only. No secret value
was read, printed or logged. No gate was enabled, no Flow created, no catalog mutated, no message
sent, no payment touched.

Every claim is tagged **PROVEN** (direct `file:line`, or a sanitized live read quoted with its
timestamp), **INFERRED** (reasoned from proven facts, stated as such) or **NOT VERIFIED** with the
reason. Revision 3 adds two tags the review required:
**PROVEN BY ANOTHER SESSION'S STRUCTURED ARTIFACT** (second-hand but machine-readable, not
reproduced here) and **REPORTED BY ANOTHER SESSION** (prose only, no structured capture). The
phrase "looks correct" appears nowhere.

### What is structurally unavailable to this agent, stated up front

Review 2's finding 9 asked this step to re-run three inert reads itself. **Two of the three cannot
be performed, and that is a property of the safety rules rather than an omission:**

- `/wa-business/payment-config/check` and `/wa-business/payment-config/list` sit behind
  `require_auth` (`handler.py:6034`, before any route dispatch; `AUTH_SKIP_PATHS` holds one
  unrelated member). This agent has no Cognito session and must not create one.
- `GET /1607047307067517/products` needs the Meta token, which lives in Secrets Manager. The binding
  rules forbid `get-secret-value`/`batch-get-secret-value` **in any spelling**. So no independent
  Graph read is possible. **Any claim to have performed one should be disbelieved.**

What *was* available and was used instead: **CloudWatch logs** (read-only, no credential),
**Lambda configuration metadata** (`get-alias`, `get-function-configuration` — env var *names* and
non-secret values only), and **committed artifacts** that are the handler's own serialised output.
That turned out to be a better route for answer **G** than the one the review prescribed. See **G4**.

### New conflicts found this revision

| # | Conflict | Resolution |
|---|---|---|
| **C14** | The parallel session's checkpoint (`service-rollout/README.md`, added by `e9e377ce`) states "Backend 10334/7 skipped/3 xfailed". This pass measured **10394 passed, 6 skipped, 3 xfailed** at `e9e377ce`. | **Both are correct at their own commit.** Theirs is measured at its stated baseline `d03ac81d`, already stale at `e9e377ce`. Not an error by either party — an illustration of why a test count is a timestamp. **Use the measured 10394/6/3 at `e9e377ce` as the gate.** |
| **C15** | Revision 2's §3 asserted "the Wix webhook is still firing (`/aws/lambda/wecare-wix-catalog-webhook`, streams through 2026-10-09)". | **No longer true at this read.** Last delivery **2026-10-09T00:24:18Z**; nothing in the four hours before 04:36:35Z. Consequence: `design.md` §5 item **3b** (await a natural webhook) cannot be relied on, which is why item **3a** exists. |
| **C16** | Prior handoff material describes the Vault signed-download window as **300 seconds**. | **Not in the code and not in the live environment.** `secure-files:215` `DOWNLOAD_URL_TTL` default **60**, live `DOWNLOAD_URL_TTL_SECONDS=60`; `:218` `WHATSAPP_LINK_TTL` effective **900**. Code and live agree with each other and disagree with the prose. See **P4**. |
| **C17** | Live `wecare-secure-files` sets `WHATSAPP_LINK_TTL_SECONDS=21600` (6 h), but `:218` clamps it: `max(60, min(900, 21600))` = **900** (15 min). | Behaviour is safe — the clamp is the `724dcc38` hardening. But environment and behaviour disagree by **23×** on a security-relevant value. Finding **V-3** / design item **F-11**. |
| **C18** | `docs/whatsapp/native-catalog-release-status.md` still closes by citing `native-catalog-integration-evidence.json`, **and `e9e377ce` added a second reference to it in `change-authority-matrix.md`.** | **Conflict C1 has WIDENED, not closed.** `git ls-tree -r --name-only origin/stack \| grep -i 'native-catalog.*evidence'` returns **nothing**. Two documents now cite a file that has never existed. F-8 item 1 removes both claims rather than fabricating the file. |
| **C19** | The parallel session's checkpoint introduces Orders Flow **`2167802357142172`** — an eight-screen **DRAFT**, zero validation errors. | Not in this audit's known-state list and **not audited this pass.** Recorded so the planner does not treat it as covered. Out of scope; `design.md` §7. |

---

## Binding authority re-established

`.kiro/steering/*` and all `.kiro/skills/*` were deleted in `af7858fa` ("chore: remove outdated
.kiro steering and skills", 31 files, 5199 deletions) and that commit **is an ancestor of
`origin/stack`** — so the deletion is the intended current state, not local damage. `AGENTS.md` is
absent; both confirmed absent from the worktree. Binding authority is therefore: the task safety
rules, the five deny-hooks in `.kiro/hooks/` (`block-broad-git-staging`, `block-catastrophic`,
`block-inline-secrets`, `block-s3-bucket-creation`, `heal-parallel-setup`), and the history in
`docs/execution/change-authority-matrix.md` and `docs/kiro-handoff.md`.

**The deletion removed `02-qa-recipient.md`, the document of record nominating `+918100640044`, and
NOTHING replaced it.** Revision 3 claimed the nomination *"survives in
`docs/whatsapp/service-rollout/README.md` §9 and `continue-prompt.txt`"`.* **That claim is false and
is retracted here** (review 3 finding 3). Verified at `061b6e77`:

```
git grep -n "918100640044" origin/stack -- docs/whatsapp/service-rollout/   ->  NO MATCHES
git grep -l "918100640044" origin/stack | wc -l                            ->  90
git grep -n "0044" origin/stack -- docs/whatsapp/service-rollout/README.md          ->  59
git grep -n "0044" origin/stack -- docs/whatsapp/service-rollout/continue-prompt.txt ->  9   # :5 at e9e377ce, :7 at 4fe31824 — moved in BOTH hops
```

What actually survives in those two files is **only the four-digit suffix**, in prose:

| File:line (`061b6e77`) | Text | Moved since `e9e377ce` |
|---|---|---|
| `docs/whatsapp/service-rollout/README.md:59` | *"**QA**: owner authorized personal number ending 0044 for customer QA. Business number ending 4400 is deliberately excluded from checkout."* | **yes — was `:57`** |
| `docs/whatsapp/service-rollout/continue-prompt.txt:9` | *"The owner supplied QA customer number ending 0044 and will complete real payments personally; business sender +919330994400 must not be used as a customer."* | **yes — was `:5`** |

The full E.164 appears in **90 tracked files** (88 at `e9e377ce`) — test fixtures, evidence JSON,
historical logs — and **not one of them is a document of record.** A number that appears in ninety
incidental places and zero authoritative ones has no authority at all.

> **A suffix cannot authorize a send.** "Ending 0044" identifies a number to a human reader who
> already knows it; it is not a specification. It cannot be mechanically compared against a
> send target, it cannot distinguish two numbers sharing a suffix, and it cannot be audited after
> the fact. This is the authority chain for the **only rule governing live WhatsApp sends in this
> project**, and it is currently a prose fragment in a rollout README.

**Required, not optional — see design item F-8 item 6:** create
**`docs/execution/qa-recipient.md`** as the document of record, carrying the full `+918100640044` in
E.164, the **explicit exclusion of `+919330994400`** (the business sender, which
`catalog_service_checkout.verified_identity:38` already refuses in code via
`whatsapp_basket.is_business_sender`), and the statement that **a suffix cannot authorize a send**.
Until that file exists, the nomination rests on this task's own prompt rules and on nothing in the
repository. **No live send may be justified by a suffix match.**

**Authorization for production deploys** (review finding 3). No steering file granting standing
authorization survives. What survives is `docs/execution/change-authority-matrix.md`, whose
classification table at `:1154` defines `A3_PRODUCTION` as requiring "Explicit owner approval for
the exact target **and** rollback, immediately before acting", and whose log rows record historical
`A3_PRODUCTION` single-Lambda deploys against "owner blanket" / "standing grant" (e.g. `:1183`,
`:1184`). **The grant is historical and its granting document is deleted.** This audit therefore
treats every production deploy as requiring a fresh owner confirmation, and schedules none without
one. See `design.md` §5, which now carries an Authorization column.

---

## Current truth discovered during this revision — a parallel session is active

**PROVEN.** This supersedes revision 1's answers **A**, **B**, **C**, **D**, and materially
changes **F**, **G**, **H**, **I** and **P**.

```
git fetch origin            ->  53ed298e..4e259800  stack -> origin/stack
git log --oneline HEAD..origin/stack
  4e259800 docs: reconcile concurrent production releases and delivery contract
  e006b5f3 fix: enforce permanent ownership for customer profiles
  c24fab39 fix: restrict SEO deployment to packaged source changes
  724dcc38 fix: bind private files to permanent customer ownership
git log --oneline origin/stack..HEAD
  0425dce1 docs(audit): start deep integration audit evidence log
```

Commit timestamps are 2026-10-09 08:06 → 08:50 +0530, i.e. interleaved with revision 1's own
authoring window. The session identifies itself as "xcodex" and published its own report at
`docs/execution/xcodex-20261009/xcodex-final-report-2026-10-09.md`.

What it changed that overlaps this audit:

| Their change | Overlap with this audit |
|---|---|
| `724dcc38` — `vault_access.bind_file` now requires `ownerCustomerId == identity.customer_id` and its `ConditionExpression` is a bare `ownerCustomerId=:owner` | **Resolves review finding 2 in the tree**, in the direction the review called "option (a)". Half of **F-3**. |
| `724dcc38` — `core/secure-files/handler.py`: `_customer_list`, `_owned_active_file`, `_reconcile_grant`, `_redeem_after_reconcile`, `_create_order`, `_send_whatsapp_payment` all now require a positive `subject`/`customerId` match; `WHATSAPP_LINK_TTL` capped at `max(60, min(900, …))` | Closes an IDOR class and a long-lived bearer-URL window this audit would otherwise have raised. |
| `724dcc38` — `_read_payment_configurations` added to `messaging/whatsapp-business-api/handler.py` with bounded cursor pagination, no `fields` filter, fail-closed on incomplete pagination | **Root-causes and fixes answer F's historical contradiction.** |
| `e006b5f3` — `auth/customer-profile`: `_owned_contact` no longer adopts an unowned row; `_upsert_contact` raises `CONTACT_IDENTITY_CONFLICT`; update carries `ConditionExpression="attribute_exists(id) AND checkoutCustomerId=:customer"` | Closes a contact-adoption path. Note it makes **O2** stricter, not looser — see **J**. |
| Six production releases, then three more | **Expires revision 1's answer C and D entirely.** See **C**. |

**Concurrency rule this imposes on every item in `design.md`:** the fleet is a moving target.
Between two reads 7 minutes apart in this session, `wecare-meta-catalog-sync` live moved 6 → 7 and
`wecare-whatsapp-business-api` live moved 87 → 88. Any deploy must therefore re-read the alias
immediately before acting and move it **conditionally on the captured `RevisionId`**, never
blindly.

---

## Document conflicts found (newest independently verified evidence wins)

| # | Conflict | Resolution |
|---|---|---|
| C1 | `docs/whatsapp/native-catalog-release-status.md` closes with "Machine-readable deployment/readback evidence: native-catalog-integration-evidence.json". **That file does not exist** anywhere in the tree. | The doc's machine-readable claim is unsupported. Treat the document as 2026-10-08 narrative, superseded where it disagrees with a newer live read. **Recorded as the brief required.** Design item **F-8** removes the claim rather than fabricating the file. |
| C2 | Same doc: Submit Request Paid Flow `1107164111921876` = **DRAFT**. `live-evidence.json` + README §8 = **PUBLISHED**. The parallel session's report asserts "Historical DRAFT/pending claims are superseded by live published paid/review Flows". | Newest evidence says PUBLISHED, and it is self-enforcing in code — see **K**. An authoritative re-read needs a Graph call this step does not make: **NOT VERIFIED — owner/provider read required.** |
| C3 | Same doc: live aliases `wecare-checkout` 36, `wecare-whatsapp-business-api` 76, inbound 88, outbound 55. | **Stale, and so is revision 1's own correction.** See **C** for two timestamped captures. |
| C4 | README says the Wix service product is at "revision 5"; `wix-artwork-evidence.json` records `"revision": "4"`. | **NOT VERIFIED** — needs a credentialed Wix read. Immaterial to any decision below. Recorded, not guessed. |
| C5 | README "Verified deployment and blockers" states catalog sync "returns read_failed with applied=0; propagation into Meta remains unverified". | **Superseded twice.** The sync succeeded 45 times through 2026-10-08T23:28:48Z, then failed for an externally-caused reason now identified (**G**), and the live target has since been changed (**I**). |
| C6 | Source default `META_CATALOG_ID` is `1457045652952851` at `meta-catalog-sync/handler.py:73`, but live v6's env set `META_CATALOG_ID=1607047307067517`. | **RESOLVED BY THE PARALLEL SESSION, not by this audit.** Live v7 env now reads `META_CATALOG_ID=1457045652952851`. See **I**. |
| C7 | Prior audit `.kiro/work/deep-repository-audit/` file/test counts. | **EXPIRED** by instruction; nothing from it is cited as current. |
| C8 | **NEW.** Revision 1 §C/§D cite `wecare-whatsapp-business-api` v79 and `wecare-checkout` v40 as the deployed-bytes evidence. Both have been superseded. | **Revision 1's §D conclusions are EXPIRED as statements about live.** They remain true as statements about v79/v40. See **C**, **D**. |
| C9 | **NEW.** Revision 1 §I asserts "`applied: 0` has two meanings". | **Wrong.** Five return arms produce `applied: 0`; three carry no `reason`. Enumerated in **I**. This was review finding 5 and it is accepted. |
| C10 | **NEW.** `docs/whatsapp/service-rollout/README.md:70` says "Meta then explicitly denied management access to both catalog `1088514403989109` and the current `1607047307067517`". | **Refined, not contradicted.** The parallel session's independent Graph read returns **error 100 / subcode 33** for `1607047307067517` and **HTTP 200 with an empty product list** for `1457045652952851`. A 100/33 cannot distinguish deletion from missing permission. See **G**, **H**. |
| C11 | **NEW.** The design review states `order_keys.is_conditional_failure` is at `:174` and `re.fullmatch` in `customer_commands.py` is at `:82`. | **The review is wrong on both.** `grep -n` gives `is_conditional_failure` at `order_keys.py:177` (revision 1 was right) and `re.fullmatch` at `customer_commands.py:80`. Full re-derived citation table in `design.md` §8 finding 13. |
| C12 | **NEW.** The parallel session published `docs/execution/xcodex-20261009/whatsapp-customer-service-architecture.md`, `website-to-whatsapp-migration-matrix.md` and `whatsapp-payment-state-machine.md` — the same three deliverable names this audit owes under `outputs/`. | Both sets exist; conclusions are compatible (both reject a fully-native replacement). This audit's `outputs/` versions are cited by `file:line` and are the ones `design.md` references. Overlap recorded so the planner does not treat either as missing. |
| C13 | **NEW.** The parallel session's report claims "business `$LATEST` differs from live … reconcile that pending package before any overwrite". | **No longer true at this read.** `CodeSha256` of `$LATEST` equals that of the live qualifier for all six in-scope functions (read 2026-10-09T03:32Z). Recorded because it was true earlier and may become true again while another session deploys. |

---

## A. Is `origin/stack` clean and internally consistent?

**PROVEN — `origin/stack` is clean but it is NOT the tree this audit read, and it is moving.**

Revision 1 answered "yes, and the worktree is clean" against `origin/stack` = `53ed298e`. That is
now false in the part that matters:

```
git status --short                       -> only this audit's own untracked .kiro/work files
git rev-parse --abbrev-ref HEAD          -> deep-integration-audit
git fetch origin && git rev-parse origin/stack
    -> 061b6e77c8a352d174c713834af0ca7d61b027b9   (061b6e77)
git rev-list --left-right --count HEAD...origin/stack -> 1  12
git merge-base HEAD origin/stack         -> 53ed298e
git worktree list -> main @ 53ed298e [stack]; this worktree @ 0425dce1
```

**`origin/stack` has now moved three times across this audit's revisions** — `53ed298e` (revision 1)
→ `4e259800` (revision 2) → `e9e377ce` (revision 3, first derivation) → `4fe31824` → **`061b6e77`** (revision 3,
re-anchored). Revision 3 declared `4e259800` with "1 ahead, 4 behind" in this answer while its own
`§0` declared `e9e377ce` with 1/10; **both were stale and are replaced by the single current reading
above** (review 3 finding 4).

So: this worktree is **1 ahead, 12 behind**. The main checkout at
`/Users/wecaredigital/wecare-digital/wecare-digital` is also still on `53ed298e` and is likewise
behind. Nothing is dirty beyond this audit's own output, and no file this audit proposes to change
has uncommitted work in it.

Internal consistency: `origin/stack` is self-consistent as source. The release-state inconsistency
revision 1 flagged (source ahead of live for the shared-catalog commit `a739d016`) has been
**partially closed by the parallel session** — not by deploying `a739d016`'s code, but by changing
the live environment variable to the catalog that commit intends. Code and configuration now agree
on the target; the code change itself is still undeployed. See **D** and **I**.

**Consequence for the plan, stated because it changes the first step: the rebase target is
`061b6e77`.** Every design item must be rebased onto it before implementation.

**What the last two upstream hops did and did not touch.** `4fe31824` ("docs: specify renewable
Vault access and complete session handoff") is a **docs-and-outputs-only** commit; `061b6e77`
("fix: retire obsolete Meta Flows with WABA-aware lifecycle API") **does change code**:

```
git merge-base --is-ancestor e9e377ce origin/stack  ->  YES (fast-forward)
git diff e9e377ce..4fe31824 --stat                  ->  12 files, +2121/-1   (docs/outputs only)
git diff 4fe31824..origin/stack --stat              ->  11 files, +1784/-13  (INCLUDES CODE)
git diff 4fe31824..origin/stack --name-only | grep -E '^(amplify|scripts|src|tests)/'
    ->  amplify/functions/messaging/whatsapp-business-api/handler.py
    ->  tests/test_audit_payment_diagnostic.py
```

Hop 1 touched `docs/execution/change-authority-matrix.md`,
`docs/whatsapp/service-rollout/{README.md,continue-prompt.txt,live-evidence.json}` and seven
`outputs/*` files only. **Hop 2 changed
`amplify/functions/messaging/whatsapp-business-api/handler.py`**, adding 12 lines at `@@ -310 @@` and
one at `@@ -6094 @@`, so **every citation into that file shifted** — `+12` below line 321, `+13`
below 6106. All were re-derived individually; the per-line table is in `design.md` §0. Notably
`preparePaidSubmitRequest` `:5984-5988` → **`:5996-6000`**, `require_auth(event)` `:6022` →
**`:6034`**, the `/payment-config/raw` 410 arm `:6386-6391` → **`:6399-6404`**, and two citations in
**S1** that were **already stale before hop 2** and that no offset explains: `:5875` → **`:5912`**
and `:6519-6521` → **`:6574`**.

**`amplify/functions/ecommerce/checkout/handler.py` was touched by neither hop**, so answer **L**'s
re-derived gate lines (`:3062`/`:3063`/`:3064`/`:3065`/`:3078`) and answer **J**'s `:3081` hold as
stated. Three **document** citations moved and are corrected where they appear: `README.md:57` →
**`:59`**, `continue-prompt.txt:5` → **`:9`** (it moved in *both* hops), and the E.164 file count
88 → **90** (see "Binding authority re-established").

Two files the plan touches were modified by
`724dcc38` (`shared/lambda_utils/ecommerce/vault_access.py`,
`messaging/whatsapp-business-api/handler.py`), and `tests/test_audit_customer_file_ownership.py`
and `tests/test_audit_payment_diagnostic.py` exist only on `origin/stack` — confirmed by
`pytest` erroring `file or directory not found` for the former at this worktree's HEAD.

## B. Is local missing remote commits or parallel changes?

**PROVEN — YES. Revision 1's "no" is superseded.**

Four commits (`724dcc38`, `c24fab39`, `e006b5f3`, `4e259800`) are on `origin/stack` and not here,
authored 2026-10-09 08:06–08:50 +0530 by a concurrent session. Their content is summarised in
"Current truth" above and inspected per-answer below.

Parallel work is also present in **production**, which git cannot show: nine Lambda releases, six
claimed by the parallel session's own record and three later ones it reconciles separately.

Nothing was discarded, reset or force-pushed. The prior session's `findings.md` and the untracked
`.kiro/work/deep-repository-audit/` output in the main checkout were left untouched.

## C. Which live Lambda versions / aliases serve production?

**PROVEN, and the honest answer includes that it changed twice during the reads.**

Capture 1 — 2026-10-09T03:25Z:

| Function | live | CodeSha256 | LastModified |
|---|---|---|---|
| `wecare-whatsapp-business-api` | **87** | `AeAmzmToWnN7hE0UZbt2bSedaNPbmWRe0gP0XV11Qco=` | 03:15:48Z |
| `wecare-checkout` | **41** | `kfqE0FcwNlzWfzpA2asO9hi8NU27YHouMTixzHFT1F8=` | 03:05:25Z |
| `wecare-outbound-whatsapp` | **56** | `vETlj63GfKtbwQwEAOE1CmlzF2/d/PvVS7lhiL/qDtU=` | 2026-10-08T23:27:43Z |
| `wecare-razorpay-webhook` | **56** | `h9LRnYAhPjGkCg6tT1L8NwmYAwto2aAdNjofhsYcVEI=` | 2026-10-08T12:07:39Z |
| `wecare-invoice-engine` | **49** | `XPBw76dLHOAzUVsNz5drw9huk47bfHgxYpVZUi+kDbw=` | 2026-10-08T22:41:09Z |
| `wecare-meta-catalog-sync` | **6** | `9Nrpq65Z1Cd5ANxpCdTiHdylN9lijITni+ruPbCiKn4=` | 2026-10-08T23:26:32Z |
| `wecare-secure-files` | **34** | `6l0bIzOc/6StE2ttnhIEhZdIlSnks/PllJdyYTlRnZ8=` | 03:08:53Z |
| `wecare-inbound-whatsapp` | **92** | — | — |
| `wecare-messages-read` | **29** | — | — |
| `wecare-service-requests` | **5** | — | — |
| `wecare-wix-catalog-webhook` | **9** | — | — |
| `wecare-contacts` | **32** | — | — |
| `wecare-customer-profile` | **10** | — | — |

Capture 2 — 2026-10-09T03:32–03:34Z, seven minutes later:

| Function | live | Change |
|---|---|---|
| `wecare-meta-catalog-sync` | **7** | 6 → 7, `RevisionId` `dc895968-c89d-4a3b-9da3-2e366fb1465f`, `LastModified` 03:30:32Z, `CodeSha256` **unchanged** (`9Nrpq65Z…`) — so this was an **environment-only** release |
| `wecare-whatsapp-business-api` | **88** | 87 → 88 |

**Capture 3 — 2026-10-09T04:32:07Z, one hour later. The fleet moved AGAIN.**

| Function | live | `RevisionId` | Change since capture 2 |
|---|---|---|---|
| `wecare-whatsapp-business-api` | **89** | `766722c7-05d8-4664-ab37-5be8c38d9f57` | **88 → 89** |
| `wecare-secure-files` | **34** | `01e8e9ef-f514-4829-9dc5-7299321465ab` | unchanged |
| `wecare-meta-catalog-sync` | **7** | `dc895968-c89d-4a3b-9da3-2e366fb1465f` | unchanged |
| `wecare-checkout` | 41 | `10b82920-f493-4e19-acdf-5200899a9ce5` | unchanged |
| `wecare-razorpay-webhook` | 56 | `06eb2a78-f73d-4dd8-ab8d-efd4c2f9ef07` | unchanged |
| `wecare-invoice-engine` | 49 | `460d1d6f-b0fb-4fcc-a85d-b4d9b5a7bfe8` | unchanged |
| `wecare-outbound-whatsapp` | 56 | `6307da00-d3c1-48ef-be5a-02ba740c36a3` | unchanged |
| `wecare-inbound-whatsapp` | 92 | `54c18149-cef0-4ea2-b6be-ac7d784bf80f` | unchanged |
| `wecare-messages-read` | 29 | `a3e12e61-34e5-45ac-b285-8f4a6e3e6153` | unchanged |
| `wecare-wix-catalog-webhook` | 9 | `f24b0e2b-762a-4cf6-9951-9ca7fdb459fc` | unchanged |

**So `wecare-whatsapp-business-api` went 79 → 87 → 88 → 89 and `wecare-secure-files` 31 → 34 inside
this one audit: four observed fleet movements.** The parallel session's own checkpoint, added by
`e9e377ce`, independently corroborates the state — *"deployed Business API89 (rollback88). Secure
Files34, Service Requests5, catalog sync7 and checkout41 remain current."* Two independent sources,
one answer.

**`$LATEST` vs live `CodeSha256`, re-read 2026-10-09T04:37:14Z: SAME on all eight functions
checked** (`wecare-whatsapp-business-api`, `wecare-checkout`, `wecare-razorpay-webhook`,
`wecare-invoice-engine`, `wecare-secure-files`, `wecare-meta-catalog-sync`,
`wecare-outbound-whatsapp`, `wecare-inbound-whatsapp`). So there is **no pending unpublished
package** anywhere in scope at this read. **C13 closes again — for the second time in two
revisions.** It became true, then false, then true. Any plan must re-check it rather than cite this
line.

`$LATEST` vs live `CodeSha256` at the earlier capture: **SAME** for all of
`wecare-meta-catalog-sync`, `wecare-whatsapp-business-api`, `wecare-checkout`,
`wecare-razorpay-webhook`, `wecare-invoice-engine`, `wecare-service-requests` (read 03:32Z). This
closes C13 as of that moment only.

**Rollback targets now recorded for the two functions revision 1 omitted** (review finding 1):
`wecare-razorpay-webhook` live **56** (`RevisionId` `06eb2a78-f73d-4dd8-ab8d-efd4c2f9ef07`) and
`wecare-invoice-engine` live **49** (`RevisionId` `460d1d6f-b0fb-4fcc-a85d-b4d9b5a7bfe8`). Both are
required before **F-5** may ship, and both must be **re-read immediately before** any move because
of the concurrency above.

Version history proving the churn is real, not a misread:
`wecare-whatsapp-business-api` published 78 (00:09:38Z), 79 (00:24:22Z), 80 (01:37:26Z),
81 (01:40:39Z), 82 (01:47:19Z), 83 (02:46:29Z), 84 (02:52:34Z), 85 (03:06:31Z), 86 (03:08:51Z),
87 (03:15:48Z); `wecare-checkout` published 40 (2026-10-08T23:38:25Z), 41 (03:05:25Z).

Naming corrections that still stand: the sync function is **`wecare-meta-catalog-sync`**; three
catalog functions exist (`wecare-meta-catalog-sync`, `wecare-catalog-management`,
`wecare-wix-catalog-webhook`).

## D. Does live code match repo intent?

**Revision 1's package-diff evidence is EXPIRED as a statement about live. Its findings about v79
and v40 remain true about those versions, which no longer serve production.**

Revision 1 extracted each live package and diffed the handler against source, finding
`wecare-checkout` v40 byte-identical, `wecare-meta-catalog-sync` v6's shared module
byte-identical with `handler.py` differing, and `wecare-whatsapp-business-api` v79's `handler.py`
differing behaviourally (per-WABA dataset get-or-create vs source's fixed
`CAPI_FIXED_DATASET_ID`). That method is the correct one — `change-authority-matrix.md` records
that the packager writes each file with `ZipFile.write`, embedding mtime, so `CodeSha256` cannot
prove equality in the other direction.

What is true now:

| Function | live | Status |
|---|---|---|
| `wecare-checkout` | 41 | **NOT RE-DIFFED.** v40 was byte-identical to `53ed298e` source; v41 is the parallel session's profile-reader repair, whose source is `e006b5f3` — a commit not in this worktree. Re-diff must happen after rebasing. |
| `wecare-whatsapp-business-api` | **89** | **NOT RE-DIFFED.** (Corrected from revision 3's `88` — review 3 finding 4; `§C` and `design.md §7` already said 89 and this row disagreed with both.) The parallel session certifies v86 against its own source for five named functions (`_read_payment_configurations`, `_payment_readiness_for`, `_check_payment_gateway`, `vault_access.bind_file`, `payment_list_uses_shared_reader`) and explicitly records `allOtherChangesCertified: false`. **v87, v88 and v89 are uncertified by anyone.** |
| `wecare-meta-catalog-sync` | 7 | **Code identical to v6** (`CodeSha256` `9Nrpq65Z…` on both). So live code still carries the old `META_CATALOG_ID` default `"1607047307067517"` and the old docstring, while source `handler.py:73` defaults to `"1457045652952851"`. The default is now moot: live env **explicitly sets** `META_CATALOG_ID=1457045652952851`. |
| `wecare-razorpay-webhook` | 56 | Unchanged since 2026-10-08T12:07Z; no parallel-session edit. |
| `wecare-invoice-engine` | 49 | Unchanged since 2026-10-08T22:41Z; no parallel-session edit. |

**The live-vs-source drift that remains material** is the CAPI dataset one, and it is now
*worse-documented* rather than resolved: source pins `CAPI_FIXED_DATASET_ID` for both WABAs, and
nobody has certified whether v87/v88/v89 contain that change. The parallel session's own report notes
v86 "introduces a safer delivery contract **ahead of source**: 502 is `SEND_UNKNOWN`" — i.e. live
is ahead of source on the outbound delivery contract, and it flags the resulting drift as AUD-018.
**So drift now runs in both directions.** Reconciling it is engineering work owned by that
session, and `design.md` deliberately does not touch it.

**NOT VERIFIED:** whether live `wecare-whatsapp-business-api` **v89** matches any committed source.
Re-establishing that needs a package extraction after rebasing onto **`061b6e77`**, and it is a
prerequisite for any change to that function — which gates `design.md` §5 row 4b-ii (F-4's live
sites and F-6). Tracked as **O11**.

## E. Is the `/payment-config/raw` contract defect fixed?

**PROVEN FIXED in source, and proven fixed in the deployed bytes of the version that served
production when revision 1 read it.**

The historical defect: checkout posted `/wa-business/payment-config/raw` with `wabaId`, the
dispatcher substring-matched the generic `/payment-config` arm, demanded `phoneId`, answered `400`,
and `payment_readiness.evaluate` mapped any error to `META_UNAVAILABLE` — so the readiness gate
could never pass.

Caller, `amplify/functions/ecommerce/checkout/handler.py:300-306`:

```python
invoke_event = {
    "httpMethod": "GET",
    "path": "/wa-business/payment-config/list",
    "queryStringParameters": {"wabaId": waba_id},
}
```

`:303` is the literal `"path": "/wa-business/payment-config/list"`.

**UPGRADED THIS REVISION — the defect is now retired by an explicit arm and a committed test, not
merely by arm ordering.** `e9e377ce` ("audit: reconcile customer-service rollout and **retire raw
payment diagnostic**") added a dedicated route to
`amplify/functions/messaging/whatsapp-business-api/handler.py`:

```python
elif path.rstrip('/').endswith('/payment-config/raw'):                        # :6386
    # Retired diagnostics must not fall through to phone-level settings.      # :6387
    # Native readiness consumes the normalized list; this route never writes.  # :6388
    return _resp(410, {'error': 'Payment configuration raw endpoint retired', # :6389
        'replacement': '/wa-business/payment-config/list',                    # :6390
        'diagnostic': '/wa-business/payment-config/check'})                   # :6391
```

Current dispatcher order at `e9e377ce` — the `raw` arm is now **first** of the four, so the
fall-through is structurally impossible rather than incidentally avoided:

```
6368:  elif '/payment-config/check' in path:                        # takes wabaId
6386:  elif path.rstrip('/').endswith('/payment-config/raw'):       # 410 + replacement pointers
6393:  elif '/payment-config/list'  in path:                        # takes wabaId, returns {data:[...]}
6400:  elif '/payment-config'       in path:                        # requires phoneId (:6402-6403)
```

(Revision 2 cited `:6334`/`:6352`/`:6360`, correct at the then-current tree; review 2 corrected them
to `:6358`/`:6376`/`:6383` at `4e259800`; both are now superseded by `e9e377ce`. Three readings,
three trees — see `design.md` §0.)

**And it is pinned by a committed regression test**,
`tests/test_audit_payment_diagnostic.py::test_retired_raw_diagnostic_has_explicit_replacement_without_provider_call`,
parametrised over `GET` and `POST`, asserting `statusCode == 410`, both pointer fields, **and
`graph.assert_not_called()`** — so the retired diagnostic provably makes no provider call. Note the
test passes `queryStringParameters: {'phoneId': 'fixture-phone'}`, i.e. it specifically proves the
request no longer reaches the `phoneId`-requiring handler that was the historical defect.

No code constructs the `raw` path as a client:
`git grep -n 'payment-config/raw' origin/stack -- amplify src` returns the new server arm, the
docstring at `checkout/handler.py:296-297`, and nothing executable on the calling side.

Deployed proof from revision 1's package extraction (live at the time, now superseded versions):

```
live wecare-checkout v40              handler.py:303   "path": "/wa-business/payment-config/list"
live wecare-whatsapp-business-api v79 handler.py:6316  elif '/payment-config/list' in path:
                                      handler.py:3464  def _flatten_payment_configurations(raw)
```

Regression guard: `tests/test_graft_money_correctness.py:1785-1795`
(`test_website_prepare_makes_no_lambda_invoke`), whose docstring names the retired route.

**Caveat, stated:** v40 and v79 no longer serve production (**C**; live is now checkout **41** and
business-api **89**). The *source* contract is unchanged by `724dcc38`/`e006b5f3` in this respect —
`checkout/handler.py:303` still posts `/payment-config/list`, and `724dcc38` only changed what that
arm calls internally (`_flatten_payment_configurations(...)` → `_read_payment_configurations`). The
route contract itself is untouched. **No regression introduced.**

**VERDICT: E is CLOSED, and no engineering work remains on it.** It is the only question in A–U
that is closed by committed source **plus** a committed test rather than by inference. The
historical defect — checkout calling `/wa-business/payment-config/raw` and landing in a handler that
required `phoneId` — cannot recur: the client does not construct that path, and the server answers
it with a `410` and two pointers before reaching the `phoneId` arm.

## F. Current payment-config state in Meta and through the backend

**RESOLVED as to the contradiction's root cause. Evidence standard stated honestly below, per
review 2 finding 9.**

### F1 — the live state

> **TAG: PROVEN BY ANOTHER SESSION'S STRUCTURED ARTIFACT (v86, 2 inert GETs) — NOT REPRODUCED THIS
> PASS.** Review 2 finding 9 is accepted. The underlying artifact is
> `docs/execution/xcodex-20261009/current-payment-diagnostics.json`, which is structured and carries
> `statusCode` and `executedVersion: "86"` per call — reasonable evidence, and better than the
> prose that supports **G1** — but it is second-hand. **This pass could not reproduce it**: both
> `/wa-business/payment-config/*` routes sit behind `require_auth` (`handler.py:6034`) and this
> agent has no Cognito session and must not create one. See the "structurally unavailable" note at
> the top of this document.
>
> **No mutation was performed by anyone.** Both calls were `GET`. The binding rule against
> creating or mutating a Meta/Razorpay payment configuration is intact, and **F is closed without a
> single write** — which was the point.

`docs/execution/xcodex-20261009/current-payment-diagnostics.json` on `origin/stack`, two
inert authenticated GETs, no mutation:

```json
[{"path": "/wa-business/payment-config/check", "statusCode": 200, "executedVersion": "86",
  "body": {"checks": [{"totalConfigs": 2, "activeConfigs": 2},
                      {"totalConfigs": 2, "activeConfigs": 2}]}},
 {"path": "/wa-business/payment-config/list",  "statusCode": 200, "executedVersion": "86",
  "body": {"data": [{"configuration_name": "WECAREUPI",      "status": "Active"},
                    {"configuration_name": "WECAREDIGITAL",  "status": "Active",
                     "provider_name": "Razorpay"}]}}}
```

Two configurations exist and **both are Active**. `WECAREDIGITAL` is the Razorpay one, and it is
the value live `wecare-checkout` expects (`EXPECTED_CONFIGURATION_NAME='WECAREDIGITAL'`). The two
diagnostics now **agree with each other** and with Meta Manager.

### F2 — ROOT CAUSE of the historical "missing / `local_only`" contradiction

Two independent defects, both now fixed in `724dcc38`, both visible in its diff:

1. **A `fields` filter that returns an empty collection.** The old
   `_check_payment_gateway` called
   `_graph_api(f'{wid}/payment_configurations', params={'fields': 'configuration_name,status,payment_gateway,merchant_category_code,purpose_code'}, waba_id=wid)`.
   The commit removes the `params` entirely with the recorded reason **"Meta's fields filter
   returns an empty collection for this edge."** So the diagnostic was reading a genuinely empty
   response from a genuinely populated edge and reporting "missing".
2. **No pagination.** The old readiness path called the edge once. The new
   `_read_payment_configurations` follows up to 20 bounded cursor pages using the fixed edge,
   refuses to follow a provider-supplied absolute URL, tracks a `seen` cursor set to break
   repetition, and **fails closed** — returning
   `{'error': {'message': 'Payment configuration pagination is incomplete'}}` rather than
   certifying a subset. `_payment_readiness_for` now passes `fetch_configurations=_read_payment_configurations`.

That is the "pagination omission" class the brief asked me to hunt for, found on the payment path,
and already repaired upstream. **Nothing is left for this audit to fix here.**

### F3 — the backend contract is fail-closed by construction

`amplify/functions/shared/lambda_utils/payment_readiness.py`:

- `PAYMENT_READY` is the only permissive state (`:68`); `BLOCKING_STATES` is **enumerated, not
  derived from `!= PAYMENT_READY`** (`:80-96`), so a newly added state cannot become permissive by
  omission. `is_ready` returns true only for `PAYMENT_READY` (`:168-169`).
- Any exception from the injected fetcher yields `META_UNAVAILABLE` (`:228`) — "unreachable" is
  never read as "fine".
- An empty `expected_provider_mid` yields `CONFIGURATION_UNVERIFIED` (`:244-248`) rather than
  skipping the comparison; "we did not compare" is a refusal, not a pass.
- Only a configuration whose status is Active may take money (`:138`, `:312-316`), and the MID Meta
  reports is **compared** to the expectation rather than adopted (`:39`).

Live `wecare-checkout` env (names and non-secret config values only):
`PAYMENT_WABA_ID='2094615664435155'`, `EXPECTED_CONFIGURATION_NAME='WECAREDIGITAL'`,
`EXPECTED_PROVIDER_MID` = a Razorpay `acc_…` identifier (set, value withheld),
`CHECKOUT_INITIATION_ENABLED='true'`, `WIX_CART_V2_ENABLED='true'`.

**No configuration was created, mutated or probed by this audit, and under the binding rules none
may be.** The resolution above required no mutation: it is two inert GETs plus a source diff.

## G. Why did Meta catalog sync return `read_failed`? ROOT CAUSE

**VERDICT, stated with its evidence grade rather than flattened to one word:**

| Claim | Grade | Basis |
|---|---|---|
| The sync **did** fail its Meta read, continuously, against catalog `1607047307067517` | **PROVEN — first-party, read this pass** | 15 `meta_catalog_sync_read_failed` records, 2026-10-09T00:21:01.427Z → 02:13:22.575Z, CloudWatch read 04:33:06Z. **G4.** |
| The failure is **external**, not a code defect | **PROVEN** | Live v6/v7 `CodeSha256` identical and unchanged across the 23:28:48Z success → 00:21:01Z failure boundary; the only `raise` in the file is at `:233`; 45 prior successes on the same bytes. **G3**, **G4.** |
| The retargeted catalog `1457045652952851` **is** readable and **is** empty | **PROVEN BY A FIRST-PARTY STRUCTURED ARTIFACT** | `catalog-proposals-20261009.json` is the handler's own `:568-572` return value: `readOnly: true`, `counts.create: 4`, `existingItems: []`, `applied: 0`. **G4.** |
| The specific Graph answer is **error 100 / subcode 33** | **REPORTED BY ANOTHER SESSION (prose summary, no structured capture) — NOT INDEPENDENTLY VERIFIED, AND NOT VERIFIABLE BY THIS AGENT** | Review 2 finding 9, accepted in full. See the box below. |
| Therefore: deleted **or** unassigned, indistinguishable | **INFERRED** from the two rows above | **G2**, **H** |

> **Why the 100/33 subcode cannot be independently verified here, and what was done instead.**
> Review 2 rightly objected that revision 2 tagged this **PROVEN** on the strength of a prose
> sentence in another session's narrative markdown (`xcodex-deep-audit-2026-10-09.md:61`) plus a
> prose string in `live-evidence.json:162`, with no request URL, no timestamp and no raw response
> body anywhere — thinner than this document's own definition of PROVEN. **Accepted; re-tagged.**
>
> The review's remedy was for this step to re-run the Graph read itself. **That is impossible under
> the binding rules**: the read needs the Meta token, which lives in Secrets Manager, and
> `get-secret-value`/`batch-get-secret-value` are forbidden in any spelling. So the subcode stays
> second-hand, and **F-1 exists precisely so that the next occurrence is answered by the system's
> own telemetry instead of by a human with a token.**
>
> What was done instead — and it is a better route than the review prescribed, because it needs no
> credential: **the system's own CloudWatch logs and the handler's own committed return value.**
> That independently establishes the failure, its sustained nature, its externality, and the
> old-unreadable/new-readable-and-empty asymmetry. It does **not** establish the subcode. The
> remaining gap is exactly one integer, and `O1` is the way to close it.

Revision 1 proved the failure was external and bounded it to a 53-minute onset window by
elimination. Revision 2 added the provider response second-hand. **Revision 3 adds first-party
telemetry — and finds a worse defect than either previous revision described.**

### G0 — NEW, and it changes what F-1 is for: the sync has an unobservable success mode

**PROVEN — read this pass, `/aws/lambda/wecare-meta-catalog-sync`, 2026-10-09T04:33:30Z.** Two
invocations of the retargeted v7 ran, and **neither emitted a single application log line**:

```
stream 2026/10/09/[7]d4ca3db9…   03:31:28.595Z START RequestId d5873a76-…  Version: 7
                                 03:31:29.500Z END   (Duration 904.58 ms, Max Memory 100 MB)
stream 2026/10/09/[7]72d497d6…   04:03:42.687Z START RequestId 3887e848-…  Version: 7
                                 04:03:43.465Z END   (Duration 776.98 ms, Max Memory 100 MB)
```

No `meta_catalog_sync_planned`, no `meta_catalog_sync_read_failed`, no
`meta_catalog_sync_unconfigured`. Reading the handler explains it exactly. The module has **one**
`logger.info`, at `:577-594`, and **two return arms precede it**:

| Arm | Lines | Logs? |
|---|---|---|
| `unconfigured` (empty token field) | `:521-529` | **yes**, `logger.error` at `:525-527` — so this is excluded |
| `batchHandle` readback | `:531-534` | **no** |
| `read_failed` | `:553-559` | **yes**, `logger.error` at `:554-557` — excluded |
| **`inspect` readback** | `:565-572` | **no** |
| the single `planned` line | `:577-594` | — |

So the two silent runs took either `:531-534` or `:565-572`. **Which one is not determinable from
telemetry**, and that indeterminacy *is* the defect. A production Lambda completed successfully,
performed a real outbound read, and left no evidence of what it saw.

**Why this matters more than revision 2's framing.** Revision 2 justified F-1 as "`reason` is absent
on three of five `applied: 0` arms" — a hygiene argument. The real position is stronger: **two arms
produce no telemetry at all.** F-1 is therefore worth doing regardless of what the owner decides
about `O1`, and `design.md` §5 keeps it as items 1–2, ahead of everything else.

**INFERRED, and explicitly not claimed as proven:** the 03:31:28Z run (56 seconds after v7 was
published at 03:30:32Z) was the parallel session's post-deploy `inspect` check, and its output is
what is committed at `docs/whatsapp/service-flow-drafts/catalog-proposals-20261009.json`. The file's
shape matches `:568-572` field for field. **The link cannot be proven from telemetry** — which is
the cost of the defect, demonstrated on the very question the audit needed answered.

### G1 — the provider response, from an independent Graph read

`docs/execution/xcodex-20261009/codex-deep-audit-2026-10-09.md:61` (commit `4e259800`):

> current manifest `META_CATALOG_ID=1457045652952851`; live version 6 env `=1607047307067517`.
> Inspect invocation returns `read_failed`/`applied 0`. **Independent products read of old target
> returns Graph 100/subcode 33; new target returns 200/products[] on business 79.**

Repeated at `xcodex-final-report-2026-10-09.md:122` and
`docs/whatsapp/service-rollout/live-evidence.json:162`
(`"oldTargetRead": "Graph 100/subcode 33; permission versus deletion unresolved"`).

Graph `code 100 / error_subcode 33` is Meta's "Unsupported get request — object does not exist,
cannot be loaded due to missing permissions, or does not support this operation". It is
**deliberately ambiguous between deletion and missing permission**, which is why the parallel
session recorded "permission versus deletion unresolved" rather than picking one.

### G2 — what this proves and what it excludes

> **Evidence grade for this subsection, after review 2 finding 9.** The exclusions below rest on the
> **asymmetry** — old target fails, new target succeeds, same credential, same code — not on the
> `100/33` subcode itself. **The asymmetry is independently established this pass and does not
> depend on the other session's prose:** the failure side is 15 first-party CloudWatch records
> (**G4**), and the success side is the handler's own committed `inspect` output showing
> `1457045652952851` with `existingItems: []` (**G0**). So the eight exclusions stand on first-party
> evidence. **Only the deleted-vs-unassigned disambiguation needs the subcode**, and that is the one
> thing left for `O1`. Revision 2 presented the subcode as doing the excluding work; it does not.

The decisive fact is the **pair** of reads: with the *same* credential, `1607047307067517` fails
while `1457045652952851` returns a successful, empty product list. Therefore:

| Hypothesis | Status |
|---|---|
| Token absent / empty | **EXCLUDED.** `meta_catalog_sync_unconfigured` count = 0 across all logs; and a 200 was obtained. |
| Token invalid / expired / wrong source | **EXCLUDED.** The same token read a different catalog successfully. |
| App lacks catalog-management capability in general | **EXCLUDED.** A catalog *was* readable. |
| Graph endpoint / API version wrong | **EXCLUDED.** Centralised in `lambda_utils.meta_version` via `graph_url` (`meta-catalog-sync/handler.py:186-188`); unchanged across the boundary; and a 200 was obtained through the same code. |
| Request construction / response shape / pagination | **EXCLUDED.** Same code path produced 45 successful paged reads and one 200. |
| Catalog ID typo | **EXCLUDED.** The same literal appears in every log line, success and failure. |
| Retailer IDs | **EXCLUDED.** `foreign` stable at 1 (`WD-APPREVIEW-TEST`). |
| Wix leg | **EXCLUDED.** A Wix failure raises `WixEcomError`, not `RuntimeError` — see G3. |
| **Object `1607047307067517` is deleted** | **NOT EXCLUDED** — one of the two surviving possibilities. |
| **Object `1607047307067517` is no longer assigned to this app/business** | **NOT EXCLUDED** — the other. |

Separating the last two is an **owner action in Business Settings**, not engineering. Design item
**O1**.

### G3 — `errorType: "RuntimeError"` localises the failure to the Meta read, exclusively

`meta-catalog-sync/handler.py:535-559` wraps `_wix_products(wix)`, `catalog.desired_items(...)` and
`_existing_items(graph, …)` in one `try` and logs only `type(error).__name__`. The taxonomy makes
that name decisive:

| Raiser | Exception | `__name__` |
|---|---|---|
| `_existing_items` on any Graph error, `handler.py:233` | bare `RuntimeError` | `RuntimeError` |
| every Wix failure — HTTP, transport, non-JSON, missing key | `WixEcomError(RuntimeError)`, `wix_ecom.py:51` | **`WixEcomError`** |
| Wix non-paise amount | `AmountNotWhole(ValueError)`, `wix_ecom.py:53` | `AmountNotWhole` |
| `desired_items` mapping failures | `RetailerIdError` / `ValueError` | those names |

`WixEcomError` subclasses `RuntimeError`, but `type(e).__name__` returns the **subclass** name. So
`"RuntimeError"` is produced by exactly one line in the whole read path. `grep -n 'raise ' ` on
that handler returns `:233` as its only bare `RuntimeError`.

### G4 — the timeline, re-read first-party this pass. This is the proof the code did not change behaviour.

> **TAG: PROVEN — independently read by this step**, `aws logs filter-log-events` on
> `/aws/lambda/wecare-meta-catalog-sync`, **read 2026-10-09T04:33:06Z**. Not taken from any
> handoff. This is the evidence review 2 finding 9 asked for, obtained by a route that needs no
> credential.

```
2026-10-08 03:25:36 … 03:25:51   20 x read_failed   WixEcomError   (Wix leg)
2026-10-08 06:25:34 … 23:28:48   45 x planned       Meta read OK
2026-10-09 00:21:01 … 02:13:22   15 x read_failed   RuntimeError   (Meta leg)
2026-10-09 03:31:28 , 04:03:42    2 x (NO LOG LINE AT ALL)         v7, silent arm — see G0
```

Verbatim boundary records from this pass's capture, sanitised only by truncation:

```
23:07:47.607Z {"event":"meta_catalog_sync_planned","catalogId":"1607047307067517","source":"wix-webhook",
               "entityId":"003931a0-b7d0-4e74-b22c-eb72310f10dc","enabled":true,"dryRun":false,
               "desired":2,"existing":3,"create":0,"update":0,"retire":0,"foreign":1,
               "foreignRetailerIds":["WD-APPREVIEW-TEST"],"planHash":"1cc87806…"}
23:28:48.242Z {"event":"meta_catalog_sync_planned","catalogId":"1607047307067517","source":"unknown",
               "entityId":"","enabled":true,"dryRun":false,"desired":2,"existing":2,
               "create":0,"update":2,"retire":0,"foreign":0,"planHash":"28b62201…"}
00:21:01.427Z {"event":"meta_catalog_sync_read_failed","errorType":"RuntimeError",
               "catalogId":"1607047307067517","source":"wix-webhook"}
```

**Two things in that capture matter beyond the onset boundary.**

First, the **final successful run planned `update: 2` with `enabled: true, dryRun: false`** — i.e.
it was about to write two item updates to `1607047307067517`, and then the read side failed before
any subsequent run could. Whether those two updates were applied is **NOT VERIFIED**: the
`:608-614` apply arm's own return is not logged, only the plan is. That is a second instance of the
same observability defect F-1 addresses, and it is why answer **I** cannot say whether the last Wix
change reached Meta.

Second, the `source` field distinguishes trigger provenance — `wix-webhook`, `schedule`,
`owner-artwork-verification`, `manual-dataset-audit`, `codex-audit`, `unknown` — which is how the
15 failures are known to include both automatic and manual triggers, and therefore not to be an
artifact of one caller.

42 of the 45 successes carried `enabled:true, dryRun:false`. A representative untruncated line:

```json
{"event":"meta_catalog_sync_planned","catalogId":"1607047307067517","source":"wix-webhook",
 "entityId":"45c21a35-7b54-45f2-8382-1edba8b6660b","enabled":true,"dryRun":false,
 "desired":2,"existing":3,"create":0,"update":0,"retire":0,"foreign":1,"blocked":0,
 "blockedProducts":[],"foreignRetailerIds":["WD-APPREVIEW-TEST"],
 "planHash":"1cc87806334ca375800751cd4d42b8ea904756dc668da4ad8dadbb06e9063b02"}
```

`existing: 3` can only come from a successful paged `GET /1607047307067517/products`. Onset is
between **2026-10-08T23:28:48Z and 2026-10-09T00:21:01Z**, and inside that window: not the code
(v6 published 23:26:32Z, immutable, and the 23:28:48Z success was already on v6); not the
configuration (a published version freezes its environment, and the alias had not moved); not the
credential in AWS (`describe-secret wecare/meta-system-user-token` → `LastChangedDate`
2026-10-01T04:28:36+05:30, `LastRotatedDate: null`, 2 versions — metadata only, no value read);
not Wix (`describe-secret wecare/wix/headless-api-key` → last changed 2026-10-05, and a Wix
failure would log `WixEcomError`).

Latest log line, 2026-10-09T02:13:22.575Z, `/aws/lambda/wecare-meta-catalog-sync`:

```json
{"event":"meta_catalog_sync_read_failed","errorType":"RuntimeError",
 "catalogId":"1607047307067517","source":"codex-audit"}
```

### G5 — the genuine engineering defect, which still stands

`_graph_request` **captures** the Graph HTTP status — `handler.py:209-211` returns
`{"error": {"status": int(error.code)}}` — and `_existing_items:233` then raises a bare
`RuntimeError` carrying none of it. The `except` arm at `:554-557` logs only `errorType`,
`catalogId`, `source`. A 403, 400, 429, 500 and a DNS failure are **indistinguishable in
production**.

This is still worth fixing even though G1 answered the question by other means: the answer came
from an out-of-band manual Graph read by a human-driven session, not from the system's own
telemetry. The next occurrence would be just as opaque. Design item **F-1** — now correctly scoped
as **diagnostic hygiene, not the critical path to O1**, which is a demotion from revision 1's
framing.

### G6 — is it fixed?

**The failure mode is gone, by reconfiguration rather than repair, and the fix is UNOBSERVED.**
Live v7 (03:30:32Z) now sets `META_CATALOG_ID=1457045652952851` — the catalog that returns 200.
But v7 also sets `META_CATALOG_SYNC_ENABLED=false` and `META_CATALOG_SYNC_DRY_RUN=true`, so the
sync will plan and write nothing. And **no invocation has occurred since the retarget**: the last
line in the log group is still the 02:13:22Z failure. See **I**.

## H. Can the current app/account actually manage the intended Meta catalog?

**PROVEN split answer: YES for `1457045652952851` (read proven); NO for `1607047307067517`.
"Manage" in the write sense is NOT VERIFIED for either.**

| Catalog | Read | Status |
|---|---|---|
| `1457045652952851` (`wecare_shop`, source default `meta-catalog-sync/handler.py:73`, and now the live env target) | **HTTP 200, `products[]` empty** | Readable and reachable. **Empty** — the two in-scope items have never been published into it. |
| `1607047307067517` (the previous live target) | **Graph 100 / subcode 33** | Not loadable. Deleted or unassigned; not distinguishable without an owner read. |
| `1088514403989109` | not re-read this pass | README `:70` records Meta denied management access. **NOT VERIFIED** currently. |

So the account can manage *a* catalog — which is what excludes the whole "app has no
catalog-management permission" hypothesis class in **G2**. What is **NOT VERIFIED** is whether the
credential holds **write** (`items_batch`) authority on `1457045652952851`, because no write has
been attempted and none may be: the gates are closed and this audit must not open them.

`live-evidence.json` `catalog.apiInventory` = "empty owned/shared response; contradicted by visible
UI inventory". An empty owned/shared inventory **alongside** a working product read is itself
diagnostic: the token can read a catalog's products while the business-asset listing returns
nothing — consistent with asset-assignment scope rather than a dead token.

**Owner/provider boundary.** Re-granting Meta catalog-management is not an engineering action and
must not be worked around. Nothing in this repository may create a replacement catalog to dodge it;
`continue-prompt.txt` and the task rules both forbid minting replacement product identities, and
`live-evidence.json` records `freshCreated: false`, which must stay false until the owner decides.
The parallel session reached the same conclusion: "do not create replacement products to evade an
access failure".

## I. Did Wix artwork / variant / price changes propagate to Meta?

**PROVEN for the two in-scope items up to 2026-10-08T23:28:48Z. PROVEN blocked from
2026-10-09T00:21Z. Now RETARGETED to an empty catalog with the gates closed, so the answer going
forward is "nothing is propagating, by configuration".**

### I1 — what had propagated

The last successful plan (2026-10-08T23:07:47Z, and 41 like it) was **empty**:
`desired:2, existing:3, create:0, update:0, retire:0, blocked:0`, with an identical `planHash`
across all of them.

An empty plan means `_comparable(current) == _comparable(item)` for both desired items across
`COMPARED_FIELDS = ("name","description","availability","price","currency","image_url","url")`
(`meta_catalog_sync.py:111`). `image_url` **is** compared, and `blocked: 0` means both desired
items carried a non-empty `image_url` (`blockers`, `:477-492`). So at 23:07Z the two scoped Meta
items already matched Wix on name, description, availability, price, currency, **artwork URL** and
url. **Artwork had propagated for those two.**

Artwork resolution is real, not incidental: `_slim_product` harvests
`options[].choicesSettings.choices[].linkedMedia[].image.url` into `row["choiceImages"]`, and
`desired_items` resolves `_image_url(variant) or _image_url(product)`
(`meta_catalog_sync.py:453-455`), setting `image_url` as a key **only when present**
(`:408-409`) so an imageless product reads as absent rather than cleared.

### I2 — `applied: 0` has FIVE return arms, not two

Revision 1's two-row table was wrong (C9, review finding 5). Re-derived mechanically from
`amplify/functions/ecommerce/meta-catalog-sync/handler.py`:

| Lines | Shape | `reason`? |
|---|---|---|
| `:528-529` | `ok:False, reason:"unconfigured", dryRun:True, applied:0` | **yes** |
| `:558-559` | `ok:False, reason:"read_failed", dryRun:True, applied:0` | **yes** |
| `:568-572` | `ok:True, enabled:…, dryRun:True, readOnly:True, counts, blocked, desiredItems, existingItems, applied:0` — the `inspect` readback | **no** |
| `:599-601` | `ok:True, enabled:…, dryRun:True, counts, blocked, planHash, applied:0` — **disabled OR dry-run, the two are not distinguished** | **no** |
| `:604-606` | `ok:True, enabled:True, dryRun:False, counts, blocked, planHash, applied:0` — empty plan | **no** |

A sixth return at `:534` (`{"readOnly": True, "batchStatus": status}`, the `batchHandle` arm)
carries no `applied` key at all.

So reading `applied: 0` alone cannot distinguish "credential missing", "Meta read failed",
"read-only inspection", "switched off", "dry run" and "already in sync". **That** is what produced
the mistaken "propagation is failing" conclusion in the handoff, when the honest reading of the
last successful run was "Meta already matched Wix for the two items in scope". Design item **F-1**
makes `reason` total over the return surface.

### I3 — three bounded limits, all PROVEN, and one now changed

1. **Only two of six entries are in scope.** Live v7
   `META_CATALOG_SYNC_VARIANT_IDS=e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b,dcff995e-448c-493a-9259-f6a82ccdc2b4`
   = Submit Request + Vault. `handler.py:541-549` filters `desired` **and** `existing` to that set.
   Request Amendment and Drop Docs artwork and prices have **never** been sent to Meta. Intentional
   scoping, not a defect.
2. **Both are forced out of stock.** Live v7 `META_CATALOG_SYNC_FORCE_OUT_OF_STOCK=true` →
   `handler.py:550-553` overwrites `availability` to `out of stock`. Not customer-purchasable.
3. **The target changed and the gates closed.** Live v7 (2026-10-09T03:30:32Z) env:
   `META_CATALOG_ID=1457045652952851`, `META_CATALOG_SYNC_ENABLED=false`,
   `META_CATALOG_SYNC_DRY_RUN=true`, `META_CATALOG_SYNC_FORCE_OUT_OF_STOCK=true`,
   `WIX_SITE_ID=c993128b-26be-41cd-9fcd-904abe23462f`. So the next invocation will take the
   `:599-601` arm — `ok:True, dryRun:True, applied:0`, **with no `reason` field** — which is
   precisely the ambiguity F-1 exists to remove. The retarget **raises** F-1's value rather than
   lowering it.

### I4 — webhook delivery is confirmed, confirmed NOT to be proof of Meta receipt, and **has now stopped**

> **TAG: PROVEN — read this pass**, `/aws/lambda/wecare-wix-catalog-webhook`,
> **read 2026-10-09T04:36:35Z.**

**The chain works and is signature-verified.** Verbatim, one complete delivery:

```
00:21:58.206Z {"event":"wix_webhook_verified","eventType":"wix.stores.catalog.v3.product_updated",
               "slug":"updated","entityId":"4ccc0c13-65b9-427f-9946-41b24ea556ae",
               "instanceId":"218087d5-5d02-479a-b910-ed96f44a9552"}
00:21:58.710Z {"event":"catalogue_dispatch_sent","status":204,
               "repository":"wecare-digital/wecare-digital","eventType":"wix-catalogue-changed"}
00:21:58.927Z {"event":"meta_catalog_sync_invoked","function":"wecare-meta-catalog-sync:live",
               "entityId":"4ccc0c13-65b9-427f-9946-41b24ea556ae"}
```

Note there are **two** fan-outs per webhook, not one: a GitHub `repository_dispatch`
(`catalogue_dispatch_sent`, HTTP 204) **and** the Lambda invoke. Only the second feeds Meta.

**Webhook delivery is NOT proof of Meta receipt — proven here by direct pairing.** Five webhooks
delivered successfully between 00:21:58Z and 00:24:18Z, each logging `meta_catalog_sync_invoked`,
and each corresponding sync invocation logged `meta_catalog_sync_read_failed` within a second
(**G4**). The handoff's warning is correct and this is the paired evidence for it.

**CONFLICT C15 — the webhook has STOPPED FIRING, and revision 2's statement is now false.**
Revision 2 asserted "the Wix webhook is still firing (streams through 2026-10-09)". **The last
delivery was 2026-10-09T00:24:18.846Z — nothing in the four hours before this read.** The
consequence is a scheduling one rather than a defect: `design.md` §5 item **3b** ("await a
naturally occurring webhook") **cannot be relied on to produce a reading**, which is why item **3a**
(an owner-confirmed `{"inspect": true}` invoke on the provably write-free arm at
`handler.py:565-572`) exists as the actionable half.

Whether the subscription itself is still healthy or merely idle because nobody has edited a Wix
product is **NOT VERIFIED** — separating those requires either a Wix product mutation
(**forbidden**; see `design.md` "Explicitly NOT doing") or an owner-side Wix webhook-subscription
read. Recorded as an owner item rather than guessed.

**NOT VERIFIED:** the present-tense values on the Meta items in `1457045652952851`. The catalog
reads successfully but **empty** (`existingItems: []`, **G0**), so the four in-scope items are not
in it; four `create` proposals are staged and unapplied. Publishing them is a write, gated on
**O1**/**O3** and on opening `META_CATALOG_SYNC_ENABLED` — currently `false`, with `DRY_RUN=true`
and `FORCE_OUT_OF_STOCK=true` (live v7 env, read 04:36:05Z). None is permitted here.

**NOT VERIFIED, and newly sharpened this revision:** whether the **last successful plan's two
updates were ever applied.** The 23:28:48Z run planned `update: 2` with `enabled: true,
dryRun: false` against `1607047307067517` — the write was intended — but the `:608-614` apply arm's
return is **not logged**, only the plan is (`:577-594`). So the final pre-failure write is
unobservable. This is a second instance of the F-1 defect, and it is the direct reason **I** cannot
state whether the last Wix change reached Meta.


## J. Is the QA contact linked to the verified permanent customer identity?

**PROVEN — the Cognito half is DONE; the ContactsTable half is MISSING. Re-verified live this
revision. One owner action closes it, and it is an ordinary signed-in save, not a bypass.**

Fresh read, 2026-10-09, reported as values that are not PII-sensitive plus booleans:

```
dynamodb query stack-wecare-digital-ContactsTable / phone-index  phone = "+918100640044"
  -> 1 item: {"id": "wa918100640044", "checkoutCustomerId": null,
              "customer_uuid": null, "deletedAt": null, "phone": "+918100640044"}
```

and from revision 1, unchanged:

```
cognito-idp list-users --user-pool-id us-east-1_46ULYuukt
        --filter 'phone_number = "+918100640044"'
  matchCount = 1 | Enabled = True | UserStatus = CONFIRMED
  phone_number_verified = true | has sub = True
describe-user-pool us-east-1_46ULYuukt -> EstimatedNumberOfUsers = 1
```

So the customer pool contains exactly one user, it **is** the authorized QA number, and it is
confirmed with a **verified** phone. The WhatsApp contact row `wa918100640044` exists, is not
deleted, and carries **no** `checkoutCustomerId` and **no** `customer_uuid`. That is precisely and
only why `readOnlyOrdersSmoke` returns `VERIFIED_CUSTOMER_REQUIRED`.

The parallel session reached the same reading: "QA phone verified but contact
`checkoutCustomerId`/`customerUuid` absent; preserve `VERIFIED_CUSTOMER_REQUIRED`". **Re-confirmed
still open at `e9e377ce`**, in its own checkpoint added by that commit
(`docs/whatsapp/service-rollout/README.md`): *"QA contact lacks permanent account link/public
UUID."* So three independent readings agree.

**The exact gate, re-derived at `061b6e77` so the owner action can be stated precisely.** Two
layers, and **both** must pass — which is why nothing short of a real signed-in save will do:

Layer 1, the caller's own pre-check. Three sites, three different shapes:

Layer 1 has **four** sites, not three (the fourth was omitted by revision 3 and is the same one F-4
finding 10 added):

| Site | Test | Refusal |
|---|---|---|
| `flows/customer_commands.py:78-81` | `re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', owner)` on `contact['checkoutCustomerId']` | `VERIFIED_CUSTOMER_REQUIRED` + sign-in URL (`:81`) |
| **`flows/customer_orders.py:56-58`** | **the same regex** on `contact['checkoutCustomerId']` (`:57`) | **`raise customer_auth.CustomerNotAuthorized('account unavailable')`** (`:58`) — a raise, not a return |
| `ecommerce/checkout/handler.py:3076-3078` | `not owner or owner != row.get('customerId')` | `VERIFIED_CUSTOMER_REQUIRED` (`:3078`) |
| `flows/catalog_services.py:53` | same class | `VERIFIED_CUSTOMER_REQUIRED` (`:53`), after a sign-in prompt send at `:50-52` |

With `checkoutCustomerId` null, **all four refuse at layer 1** — the `null` fails the UUID regex and
fails `not owner`. That is the current state.

Layer 2, `catalog_service_checkout.verified_identity:35-46`, which runs only once layer 1 passes and
is the stricter of the two. **Seven conditions, any one of which refuses:**

```python
if (not number or whatsapp_basket.is_business_sender(phone) or not owner        # :38
        or contact.get('deletedAt') is not None or contact.get('isDeleted')      # :39
        or whatsapp_basket.e164(contact.get('phone')) != number or len(users) != 1
        or not users[0].get('Enabled', True)):                                   # :40-41
    raise customer_auth.CustomerNotAuthorized('verified customer required')      # :42
attrs = {a['Name']: a['Value'] for a in users[0].get('Attributes', [])}          # :43
if attrs.get('sub') != owner or attrs.get('phone_number') != number \
        or attrs.get('phone_number_verified') != 'true':                         # :44
    raise customer_auth.CustomerNotAuthorized('verified customer required')      # :45
return customer_auth.CustomerIdentity(customer_id=owner, subject=owner, phone=number)  # :46
```

Three properties worth naming, because they are the reason this gate must not be worked around:

- **`:38` refuses the business sender explicitly.** `whatsapp_basket.is_business_sender(phone)` is
  checked *before* anything else, so `+919330994400` can never become a customer identity even if
  every other condition held. The binding rule is enforced in code, not only in documentation.
- **`:40`'s `len(users) != 1`** means a *second* Cognito user on the same number breaks the gate.
  This is why the **O2** decision below has a real data consequence.
- **`:44` re-derives `sub`, `phone_number` and `phone_number_verified` from Cognito at use time**
  rather than trusting the stored `checkoutCustomerId`. So linking the contact is necessary but not
  sufficient; the Cognito side must stay verified.

**The exact safe owner action — one authenticated, self-service save. No bypass, no DynamoDB write.**

> The owner signs in on `wecare.digital` as the existing customer account whose `phone_number` is
> `+918100640044` (already `CONFIRMED` with `phone_number_verified = true`) and saves the customer
> profile with that phone number. The `auth/customer-profile` handler then writes
> `checkoutCustomerId` onto the contact row — `assignments.append("checkoutCustomerId=:customer")`
> at `handler.py:263`, within `_upsert_contact` (`:280`).

**`VERIFIED_CUSTOMER_REQUIRED` is not to be bypassed, and this audit does not propose bypassing
it.** No agent writes `checkoutCustomerId` directly: doing so would create a verified-customer link
that no verified sign-in ever produced, which is exactly the control the gate exists to enforce.

**O2 — the complication `e006b5f3` introduced, which is an owner decision with a data
consequence.** That commit made the profile handler refuse to adopt an unowned contact row.
Re-verified at `061b6e77` (file untouched by both upstream hops, so these are unchanged since
`e9e377ce`):

- `_claimable` (**`:143-168`**, corrected from revision 3's `:147-168`) returns
  `not str(item.get("checkoutCustomerId") or "").strip()` (`:168`), with the docstring stating the
  rules at **`:158-163`** (corrected from `:158-160`): *"An EMPTY owner only… Claiming is NOT
  verifying. The claim writes `checkoutCustomerId` and nothing else."*
- `_owned_contact` (`:171-182`) matches only on `item.get("checkoutCustomerId") == customer_id`
  (`:182`).
- `_upsert_contact` (`:280`) raises `ValueError("CONTACT_IDENTITY_CONFLICT")` at `:299` and
  `:308-309`, and both update paths carry
  `ConditionExpression="attribute_exists(id) AND checkoutCustomerId=:customer"` (`:320`, `:385`)
  with the conditional failure re-raised as the same conflict (`:326`, `:391`). The handler maps it
  to `409 CONTACT_IDENTITY_CONFLICT` at `:508-509`.

**Reading in favour of the owner action:** `wa918100640044` has `checkoutCustomerId` **null**, so
`_claimable:168` returns `True` and the claim path is open. **The save should link the existing row
rather than create a second one.** That is the expected outcome and it is the good case.

**But it is INFERRED, not PROVEN**, because the claim is reached only if the handler's lookup
selects that row, and this audit has not executed the handler. Revision 2 asserted the pessimistic
outcome ("will now create a second contact"); that was **over-stated** and is corrected here. The
honest position: `_claimable` is satisfied, so linking is the likely result; a second row is the
failure mode to watch for, and if it occurs `verified_identity:40`'s `len(users) != 1` and
`paid_vault.py:85-86`'s exactly-one-contact rule are what will surface it. **Either way the owner
performs the save and the result is read afterwards — the decision between linking and staff
reconciliation is not improvised by an agent.**

**The gate is correct and must not be touched.** `catalog_service_checkout.verified_identity`
requires all of: a parsable E.164 number; not the business sender; `contact.checkoutCustomerId`
present; contact not soft-deleted (`deletedAt is None` and not `isDeleted`);
`e164(contact.phone) == number`; **exactly one** matching Cognito user; that user `Enabled`;
`sub == checkoutCustomerId`; `phone_number == number`; `phone_number_verified == 'true'`. Anything
else raises `CustomerNotAuthorized`.

**Callers re-derived at `061b6e77`** with `git grep -n "verified_identity" origin/stack -- amplify`.
Revision 3's list was wrong in two ways and is corrected here:

| Caller | Line | Note |
|---|---|---|
| `flows/customer_commands.py` | `:84` | ✓ as cited |
| `flows/catalog_services.py` | `:56` | ✓ as cited |
| `ecommerce/checkout/handler.py` | **`:3081`** | revision 3 cited `:3099` — **wrong**. `:3081` is the line immediately after the `Filter='sub'` call at `:3080`, which is design `§2` F-4's "single most dangerous stale citation" neighbourhood |
| `flows/customer_orders.py` | **`:61`** | **a fourth caller revision 3 omitted entirely** (`return contact, catalog.verified_identity(contact, users, phone)`, inside `_verified` at `:53`) |

**Four call sites; the definition is at `catalog_service_checkout.py:35`.** `git grep` returns five
matches — the four rows above plus that definition, which is not a caller.

**Revision 3's claim that `flows/paid_submit_request.py:84-102`/`:141-150` and
`flows/paid_vault.py:43-62` call `verified_identity` is false** — `git grep` returns no match in
either file. Those three sites perform their **own inline** identity check,
`if len(users) != 1 or not users[0].get('Enabled', True)`, at `paid_submit_request.py:91`, `:143` and
`paid_vault.py:70`. That is a weaker check than `verified_identity` (it omits the business-sender
refusal, the soft-delete test, the phone round-trip and the `sub`/`phone_number_verified`
re-derivation), and it is recorded here as an observation, **not** as something this audit changes:
those are live paid paths and tightening them is outside this pass's scope. The definition itself is
at `catalog_service_checkout.py:35`.

### The exact safe action — one authenticated save, performed by the owner

`checkoutCustomerId` has exactly one writer in the tree: `_contact_update_expression` in
`amplify/functions/auth/customer-profile/handler.py`
(`assignments.append("checkoutCustomerId=:customer")`), reached through `_upsert_contact`, which
matches the contact by `phone-index`. The attribute name is centralised as
`contact_payment_links.CHECKOUT_CUSTOMER_ATTRIBUTE`.

So: **sign in at `https://wecare.digital/account/sign-in/` as that customer, then open the
account/checkout profile and SAVE it** (name / phone / address). Signing in alone is not enough —
the write happens on save. That one save sets `checkoutCustomerId = <Cognito sub>` and, in the same
expression, `customerUuid` and `phoneVerifiedAt` via `if_not_exists`, which is why all three are
currently absent together.

**The effect of `e006b5f3`, stated once.** Review 3 finding 5 is accepted: revision 3 carried **two
mutually exclusive conclusions** about O2 inside this one answer — the corrected optimistic reading
above and an unedited revision-2 pessimistic block here. The pessimistic block is **deleted**. There
is one statement, and it is the same in answers **J**, answers **U** and design `§7`:

> **O2 remains a single self-service save, and linking is the expected outcome.**
> `wa918100640044` carries `checkoutCustomerId = null`, so `_claimable`
> (`auth/customer-profile/handler.py:143`, returning
> `not str(item.get("checkoutCustomerId") or "").strip()` at `:168`) **is satisfied** and the claim
> path is open. The save is expected to **link the existing contact row**, not mint a second one.
> This is **INFERRED**, not PROVEN: the audit did not execute the handler.
>
> **The failure mode to watch for is a second contact row, or a `409 CONTACT_IDENTITY_CONFLICT`**
> (`:299`, `:309`, re-raised from the conditional failures at `:326` and `:391`, mapped to the HTTP
> status at `:508-509`). **If and only if that occurs**, the owner chooses between staff
> reconciliation of the two rows and accepting the second row — a decision with a data consequence,
> which this audit specifies and does not improvise.
>
> **The result is read after the save**, either way. **No agent writes `checkoutCustomerId`.**

What `e006b5f3` actually changed is narrower than revision 2 claimed. It made `_owned_contact`
(`:171`) match only on `item.get("checkoutCustomerId") == customer_id`, and added
`ConditionExpression="attribute_exists(id) AND checkoutCustomerId=:customer"` to both update paths
(`:320`, `:385`). It did **not** remove the claim path: `_claimable` exists precisely to let a
session adopt *an unowned row bearing its own Cognito-proven phone*, and its docstring says so at
`:151-154` — *"the phone is not browser-supplied… So 'a row bearing my verified phone and belonging
to nobody' is a row about me."* It is bounded at `:158-163`: an **empty** owner only (a row owned by
a different `checkoutCustomerId` is refused exactly as before), and claiming writes
`checkoutCustomerId` and nothing else — *"Claiming is NOT verifying."*

So the parallel session's framing — *"Staff/owner must reconcile the legacy QA contact… a phone-only
save is refused"* — is the **failure-mode branch**, not the expected one. Recorded as the
contingency above rather than as the prediction.

**Explicitly ruled out:** hand-writing `checkoutCustomerId` into DynamoDB. It would fabricate the
exact link the gate exists to prove and would bypass `VERIFIED_CUSTOMER_REQUIRED` in substance
while appearing to satisfy it. Not permitted; not proposed.

## K. Current state of the paid Submit Request Flow

**Code-enforced regardless of which document is right. Provider status: NOT VERIFIED — needs an
owner/provider Graph read.**

Conflict C2 stands on the provider side. It matters less than it appears, because the condition is
checked **live at the moment of use** rather than trusted from a document.
`catalog_service_checkout.meta_ready` (`:89-104`) refuses unless **all** of:

- `wecarepay_wa`, `wecare_leave_review`, `wecare_default_download` each have matching `name`,
  `status == 'APPROVED'`, `language == 'en'` — loop `:93-96`, test at `:95`;
- `wecare_default_download`'s first button is `type: 'URL'` with url exactly
  `https://wecare.digital/vault/?file={{1}}` — `:100`;
- and for `SUBMIT_REQUEST` specifically: `flow.id == '1107164111921876'`,
  `flow.status == 'PUBLISHED'`, and falsy `flow.validation_errors` — `:104`.

The readiness dict is built from a live Graph read in `flows/catalog_services.py:28-36`. So a DRAFT
Flow **cannot** produce a payable native Submit Request: `meta_ready` returns False and no payment
reference is minted. If the Flow is in fact PUBLISHED, it passes. Either way the live answer is
authoritative and the documents are advisory. This is a well-placed invariant and needs no change.

`live-evidence.json.flows` records Request Amendment `3678132465672138` = **DRAFT** and Drop Docs
`1211063631104445` = **DRAFT**, with README §8 noting both "need their legacy phone lookup inspected
and repaired before publication". Neither is in the catalog sync scope (**I**), so neither is
purchasable today.

## L. Can native service checkout be safely enabled?

**No — not yet. One of revision 1's two code blockers has been closed upstream; one remains.**

Current state is correctly closed. The gate is `WHATSAPP_CATALOG_SERVICES_ENABLED`, default
`'false'`, checked twice. **Citations re-derived at `061b6e77`** (review 3 finding 4 — revision 3
carried revision-2 values here, and they were the single most dangerous stale pair in the document):

```
git grep -n "NATIVE_SERVICE_ROLLOUT_DISABLED\|NATIVE_SERVICE_WRITEBACK_NOT_READY" origin/stack \
    -- amplify/functions/ecommerce/checkout/handler.py
git grep -n "Filter='sub" origin/stack -- amplify/functions/ecommerce/checkout/handler.py
```

| Thing | **Correct line (`061b6e77`)** | Revision 3 cited | Why the error mattered |
|---|---|---|---|
| `WHATSAPP_CATALOG_SERVICES_ENABLED` gate test | **`:3062`** | `:3080-3081` | — |
| `NATIVE_SERVICE_ROLLOUT_DISABLED` return | **`:3063`** | `:3080-3081` | **`:3080` is the Cognito `Filter='sub'` line** and `:3081` is the `verified_identity` call — a coder editing "the gate" at `:3080-3081` would have edited the identity lookup F-4 is separately fixing |
| `wix_writeback.is_enabled()` test | **`:3064`** | `:3082-3083` | — |
| `NATIVE_SERVICE_WRITEBACK_NOT_READY` return | **`:3065`** | `:3082-3083` | `:3082` is a local `import` and `:3083` a `_table(...)` read |
| `VERIFIED_CUSTOMER_REQUIRED` return | **`:3078`** | — | with its `not owner or owner != row.get('customerId')` test at `:3076-3077` |

Verbatim at the current base:

```python
    if os.environ.get('WHATSAPP_CATALOG_SERVICES_ENABLED', 'false').lower() != 'true':   # :3062
        return {'outcome': 'NATIVE_SERVICE_ROLLOUT_DISABLED'}                            # :3063
    if not wix_writeback.is_enabled():                                                   # :3064
        return {'outcome': 'NATIVE_SERVICE_WRITEBACK_NOT_READY'}                          # :3065
```

The second check is `flows/catalog_services.py:42-43` → the same outcome. The variable is **absent
from every live function environment** read, so the default governs and the feature is off. The real
flag name is `WHATSAPP_CATALOG_SERVICES_ENABLED`; "native-services flag" in the handoffs refers to
this.

Criteria that must all hold before it may be opened:

1. **A readable, correctly-populated Meta catalog.** `1457045652952851` reads 200 but is **empty**
   (**H**), and the two items are force-out-of-stock. The catalog cannot be the entry point until
   the items are in it and in stock — both writes, both gated on **O1**/**O3**.
2. **The QA identity link must exist** (**J**) — otherwise every native entry correctly dead-ends
   at `VERIFIED_CUSTOMER_REQUIRED`. Note **J**'s new complication.
3. **Finding R-1 (duplicate review invitation) must be fixed.** Latent today, customer-visible the
   moment this flag flips. See **R**. Design item **F-2**. **STILL OPEN.**
4. **Finding P-1 (Vault selection admits an unattributed file) must be fixed.** **PARTIALLY CLOSED
   UPSTREAM** — `724dcc38` fixed `vault_access.bind_file`, but `flows/catalog_services.py:94` is
   still `in (None, identity.customer_id)` and is now the only such site in `amplify/`. See **P**.
   Design item **F-3**. **STILL OPEN.**
5. **A real owner-completed payment** must produce exactly one order, one Wix association, one
   receipt and one review — verifiable only after 1–4. Per the binding rules the owner performs it
   personally; nothing here may simulate it.
6. `meta_ready` must pass live (**K**) — self-enforcing, needs no separate gate.

Wix writeback is **not** a hard prerequisite, because `checkout/handler.py:3064-3065` (corrected
from `:3082-3083`) already refuses with `NATIVE_SERVICE_WRITEBACK_NOT_READY` when
`wix_writeback.is_enabled()` is false — so the native path cannot run half-configured. It is
sequenced in **M**.

## M. Can Wix external-order writeback be safely enabled?

**No, and the gate is already stronger than a flag — which is correct. Keep it closed.**

`amplify/functions/shared/lambda_utils/ecommerce/wix_writeback.py:118-130` requires three
independent conditions simultaneously:

```python
flag   = WIX_WRITEBACK_ENABLED      in ("1","true","yes","on")
probed = WIX_ECOM_WRITE_CONFIRMED   in ("1","true","yes","on")
return (flag and probed and os.environ.get("WIX_SITE_ID") == CONFIRMED_SITE_ID and ...)
```

with `CONFIRMED_SITE_ID = "c993128b-26be-41cd-9fcd-904abe23462f"` pinned at `:82`. Both flags are
**absent** from live `wecare-checkout` (env read), so `is_enabled()` is false. The module docstring
(`:6-10`) states it is "written, tested and guarded, but **not wired to run**", and that
"historical configuration claims are not activation evidence" — the right posture, and why the
site-id pin exists beside the flags.

Criteria before enabling:

1. A live capability probe proving the runtime site grants the eCommerce **write** scope — not a
   historical claim. Requires a credentialed Wix call; not performed here. The parallel session
   independently concluded "Wix writeback requires a verified current contract before release".
2. The exact `cart-v2-external-v1` contract attested against the live site.
3. Amount-equality enforcement confirmed: a created Wix order whose total/currency disagrees with
   the frozen quote **retains the provider order id and stops fulfilment**, and re-entry cannot
   create a second order (`wix_writeback.py:209-210` returns the existing `wixOrderId` on a
   duplicate call rather than creating).
4. Enable **after** native checkout's blockers (**L**), not before — writeback has no independent
   consumer while the native path is closed, so enabling it first adds risk and buys nothing.

Payments must remain fail-closed throughout; writeback is a post-payment record step and must never
gate or reverse a captured payment.

## N. Does one payment produce exactly one canonical order and one Wix association?

**PROVEN idempotent by conditional-write claims at every step. One residual brittleness.**

The primitive is `_claim_row` (`shared/lambda_utils/ecommerce/order_keys.py:312`), a conditional
`put_item` on the single-key commerce-keys table, with
`is_conditional_failure` at **`order_keys.py:177`** distinguishing a lost race from an outage.
(Revision 1 cited `:177` correctly; the design review's `:174` is wrong — `grep -n "def
is_conditional_failure"` returns `177`. Its docstring at `:178-185` records why it is public: "The
tree already held three inline copies of this check".) Built on it:

| Concern | Function | Line |
|---|---|---|
| one payment reference per intent | `reserve_payment_reference` / `allocate_payment_reference` | `:352`, `:399` |
| one order per payment attempt | `claim_order_for_payment` | `:468` |
| one public order number | `reserve_public_order_number` / `reserve_order_number` | `:427`, `:641` |
| provider-transaction → order resolution | `resolve_order_for_provider_payment` | `:579` |
| capture that could not be placed | `record_capture_quarantine` | `:699` |

In the webhook the paid transition is conditional rather than unconditional:
`razorpay-webhook/handler.py:2144` uses `ConditionExpression='#st <> :paid'` with the comment "a
concurrent or replayed delivery cannot settle twice", and the `ConditionalCheckFailedException` arm
logs at **info**, not error (`:2149-2152`) — expected, not a fault. Status regression is blocked by
a monotonic rank guard, `ConditionExpression=payment_status.condition_expression()` with `:rank`
(`:2027-2031`), so an out-of-order delivery cannot downgrade a paid row. Settlement rows are
claimed with `attribute_not_exists(id)` (`:2864`).

Wix association: `wix_writeback` returns `{"wixOrderId": …, "created": false}` from the existing
claim row on a duplicate call (docstring `:193`, return `:209-210`), so one payment yields at most
one Wix order even under
retry. Currently moot — writeback is off (**M**).

In the native path, replay protection starts earlier: `flows/catalog_services.py:76-85` claims
`CATALOGSERVICEMSG#<sourceMessageId>` with `attribute_not_exists(orderId)` and returns
`CATALOG_SERVICE_REPLAY` on conflict, so a duplicate customer tap on the same catalog message
cannot prepare a second payment. A second claim,
`NATIVESERVICEACTIVE#<customerId>` (`:126-133`), enforces one outstanding native purchase per
permanent customer even across catalog messages.

**GAP N-1 (LOW).** Conditional-failure detection by exception-message substring on the money path:
`'ConditionalCheckFailedException' in str(...)` at `razorpay-webhook/handler.py:1719`, `:2036`,
`:2149`, `:2746`, `:2866`, and `'... not in str(claim_err)'` at
`payments/invoice-engine/handler.py:853`. The sixth is **negated** — a detail that matters, because
a mechanical rewrite would invert it. A botocore message change would silently reclassify an
expected race as an error, or the reverse. Not currently broken; it is a brittleness, and the
structural helper already exists. Design item **F-5**.

Eight further substring sites exist and are **deliberately out of scope**:
`core/contacts/handler.py:527`, `:589`, `:617`;
`messaging/inbound-whatsapp-handler/handler.py:3280`, `:7858`;
`messaging/outbound-whatsapp/handler.py:4078`;
`whatsapp-business-api/flows/postpay.py:169`;
`shared/lambda_utils/flow_completion.py:242`. Named so the six are not read as exhaustive.

## O. Does Submit Request fulfilment attach to the correct PREVIOUS order?

**PROVEN correct, and defended in three independent ways.**

`shared/lambda_utils/ecommerce/paid_submit_request.list_orders` (`:78-103`):

- queries only the customer's own partition — `IndexName='customerId-createdAt-index'`,
  `KeyConditionExpression='customerId=:owner'` with `:owner = row['customerId']` (`:82-84`). No
  phone scan, no table scan;
- **excludes the new service order explicitly**: `if not oid or oid == row['orderId']: continue`
  (`:91-92`);
- **re-reads each base row with `ConsistentRead=True` and re-checks ownership**
  (`:93-95`: `if current.get('customerId') != row['customerId']: continue`) rather than trusting
  the GSI projection — correct, since a GSI is eventually consistent and projected;
- paginates properly via `LastEvaluatedKey` / `ExclusiveStartKey` with a 100-row ceiling and
  `Limit: 50` per page (`:85-86`, `:100-103`);
- labels rows `str(current.get('orderNumber') or oid)` truncated to 60 chars (`:96-97`).

This matches the stated invariant — "The new Submit Request purchase is a service order. It does not
become the earlier order the request is about" — and the selector spans product *and* service
orders, not only prior Submit Requests.

Two observations rather than defects.

1. The `orderNumber`-absent fallback puts an internal `orderId` in a customer-facing list title at
   `:93`. `flows/customer_commands.order_page` deliberately refuses that same fallback ("Never fall
   back to internal UUIDs as customer-facing order numbers"), keeping only values that are
   non-empty, `<= 80` chars and newline-free. The two paths disagree on one product rule. Design
   item **F-6** — and note it is **not** purely cosmetic: `list_orders`' return value is also used
   as a boolean **eligibility gate** at `flows/catalog_services.py:64-69`, so naively skipping rows
   would flip a legacy-only customer from eligible to refused. F-6 is scoped accordingly.
2. The 100-order ceiling is a real product limit for a long-tenured customer and is unflagged to
   the customer. Recorded, not fixed — it is a product decision.

## P. Does Vault payment grant exactly the intended file entitlement?

**Delivery-time enforcement PROVEN strong and now stronger. The selection-time hole is PROVEN and
is now the LAST remaining site. No double-charge path found.**

### P1 — delivery is well defended

`flows/paid_vault.prepare_and_send:35-62` re-derives everything rather than trusting the session:
`vault_access.grant_access(...)` produces `(row, file, grant)` (`:38-41`); then Cognito
`list_users` by `sub` must return exactly one `Enabled` user (`:43-46`); then
`phone_number_verified == 'true'` **and** `phone == '+' + grant['ownerPhone']` (`:48-50`); then the
ContactsTable `phone-index` matches are each re-read with `ConsistentRead=True` and filtered to
`checkoutCustomerId == row['customerId']`, not deleted (`:51-59`); and **exactly one** must survive
(`:60-61`: `if len(valid) != 1: return CONTACT_LINK_UNAVAILABLE`). Any failure returns an outcome,
never a URL.

`vault_access.grant_access` independently re-checks at `:51-52`:
`file.get('ownerCustomerId') != row.get('customerId')` → writes `vaultStatus='FILE_UNAVAILABLE'`
and returns `None`. The grant commit is a transaction whose file-update
`ConditionExpression` is `ownerCustomerId=:owner AND #s=:active` (`:71`), and an existing grant with
a mismatched `customerId`/`fileId`/`orderId`/`paid` raises `ValueError('grant ownership mismatch')`
(`:62-65`). That is positive attribution enforced at the money step.

The dynamic-download template is additionally flag-gated — `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED`,
default `'false'` (`flows/paid_vault.py:68`), comment "Enable only after live Meta readback confirms
this exact template is approved". Live `wecare-secure-files` has
`SECURE_FILES_PAYMENT_ENABLED='false'` and `DROPDOCS_ATTACH_ENABLED='false'`.

**Newly strengthened by `724dcc38`**, which this audit did not do and should not duplicate:
`WHATSAPP_LINK_TTL = max(60, min(900, int(os.environ.get("WHATSAPP_LINK_TTL_SECONDS", "900"))))`
replaces a 6-hour default, with the rationale "Direct links are bearer capabilities. Keep the read
window bounded". `_customer_identity` now additionally requires `phone_number_verified == 'true'`
and a `sub`. `_customer_list`, `_owned_active_file`, `_reconcile_grant` and
`_redeem_after_reconcile` all moved from `ownerCustomerId not in (None, subject)` to a positive
`== subject` match, and `_redeem_after_reconcile`'s `ConditionExpression` gained
`AND customerId = :owner`. That is an IDOR class closed and an unsafe-signed-URL window reduced
25-fold.

### P2 — FINDING P-1 (MEDIUM-HIGH, latent): selection accepts a file with no customer attribution

`flows/catalog_services.py:93-95`:

```python
if (file.get('status') == 'active' and file.get('ownerPhone') == identity.phone.lstrip('+')
        and file.get('ownerCustomerId') in (None, identity.customer_id)      # :94
        and not file.get('vaultAccessGrantId') and file.get('vaultPaymentStatus') != 'PAID'):
```

`in (None, identity.customer_id)` admits any file whose `ownerCustomerId` is **absent**, on an
`ownerPhone` match alone.

**This is now the only such site in `amplify/`.** Verified:

```
git grep -n "ownerCustomerId') in (None" origin/stack -- amplify
-> amplify/functions/messaging/whatsapp-business-api/flows/catalog_services.py:94
```

`724dcc38` changed `vault_access.bind_file:16` to
`not identity.customer_id or row.get('ownerCustomerId') != identity.customer_id`, replaced the
comment "Adopt legacy phone-owned files only after an authenticated verified session" with "A phone
can be reassigned. Legacy ownerless files require explicit staff reconciliation; a matching verified
phone never establishes their original owner", and tightened the `ConditionExpression` from
`(attribute_not_exists(ownerCustomerId) OR ownerCustomerId=:owner)` to a bare `ownerCustomerId=:owner`.

**This resolves design-review finding 2 in the tree, in the direction the review preferred
(option (a)).** The repository no longer holds two mutually exclusive rules by intent — it holds
one rule plus one unconverted site. `bind_file` is now effectively a verifier whose `update_item`
is a no-op rewrite of a value that already equals the owner.

Consequence of the asymmetry as it stands today: `catalog_services.py:94` would *offer* an
unattributed legacy file and mint a payment reference for it, and `bind_file` — called at
`catalog_services.py:119` (the `select` action) and `:152` (before checkout) — would then raise
`CustomerNotAuthorized`. So the customer is **offered something that will fail**, and the failure
happens at `:119`/`:152`, which is *before* the native checkout invoke at `:157`. No money
moves. Latent in any case because `WHATSAPP_CATALOG_SERVICES_ENABLED` is absent.

So **P-1's severity is reduced from "foreign-document disclosure" to "offered-then-refused dead
end"**, and revision 1's claim that such a file "would be offered, charged for and delivered" is
**no longer true** — it was true against `53ed298e` and is false against `4e259800`. Recording that
correction matters more than preserving the stronger-sounding finding.

It is still a hard prerequisite for **L**: a selector that lists documents it cannot deliver is a
customer-visible defect, and the two written invariants
(`native-catalog-release-status.md` "matching a phone alone never grants ownership";
`service-rollout/README.md` §4 "a matching phone is not sufficient to transfer ownership") are now
true of the code everywhere **except** this line. Design item **F-3**.

**Ownership of the invariant.** The invariant "a WhatsApp phone number alone never grants access to
a customer's private data" is owned by the **selection layer** (`catalog_services.py`), not the
delivery layer. Delivery re-derives from a grant that selection already created; by then the
entitlement decision has been made and a payment reference may exist. Enforcing it at delivery only
means offering first and refusing after — which is exactly the current state. That is why F-3
belongs at `:94`.

### P3 — no double charge

Already-unlocked files are excluded at selection (`not file.get('vaultAccessGrantId') and
vaultPaymentStatus != 'PAID'`, `:95`); the source-message claim `CATALOGSERVICEMSG#…` prevents a
second preparation from one tap (`:76-85`); the `NATIVESERVICEACTIVE#<customerId>` claim allows one
outstanding native purchase per customer (`:126-133`); the already-unlocked branch at `:120-122`
sends "This document is already unlocked… no new payment has been requested"; and the
no-eligible-files branch (`:96-101`) sends "If you already paid, open your Vault access message. No
new payment has been requested."

### P4 — NEW (owner requirement, revision 3): the order -> download message sequence, and FINDING V-1 (HIGH, LIVE via the native path)

The owner asked for the Vault order -> download sequence to be documented precisely against actual
code. Doing so surfaced the **most customer-damaging finding in this audit**. The full trace — both
delivery paths, every message, every guard, the TTL table and the GAP register — is in
`outputs/whatsapp-customer-service-architecture.md` **§6**. Summarised here with the verdicts.

**The sequence, Path A (native, `flows/paid_vault.py`, gated).** Strictly linear, each step
returning a distinct outcome rather than continuing:

1. **Grant first, always.** `prepare_and_send:60` calls `vault_access.grant_access` at `:63-64` as
   its first action and returns `VAULT_ACCESS_UNAVAILABLE` (`:66`) if it yields nothing. **No Vault
   message can be sent before a file-access grant exists.** PROVEN.
2. **Identity re-verified between grant and send** (`:68-86`): exactly one `Enabled` Cognito user
   (`:70`), `phone_number_verified == 'true'` **and** `phone == '+' + grant['ownerPhone']` (`:74`),
   then a `ContactsTable` `phone-index` query with a per-row `ConsistentRead=True` re-read requiring
   `checkoutCustomerId == row['customerId']` (`:77-84`), and **exactly one** surviving contact
   (`:85-86`). PROVEN. (`:69` is one of F-4's five unguarded `Filter='sub` sites.)
3. **Message 1 — the ready/order template** (`:91-96`), claimed once under `vaultNotificationStatus`.
4. **Message 2 — the PDF attachment** (`:100-109`), conditional on `deliverable == 'pdf'` **and**
   `deliveryKey` **and** the 24-hour window (`0 <= time.time() - float(last or 0) < 86400`, `:103`),
   because an attachment is a non-template message.
5. **Message 3 — the review invitation** (`:110-112`), one of F-2's three senders.

Each send goes through `_send_once` (`:13-57`), which is a genuine single-claim mechanism:
`ConsistentRead=True` read (`:15`), early return if `ACCEPTED` (`:16-17`), claim via
`ConditionExpression='attribute_not_exists(<key>)'` (`:25`), and — the part that matters most —
**anything other than a 2xx or an enumerated client error becomes `SEND_UNKNOWN` and is never
retried** (`:38`, `:44-48`), with the comment at `:49-51`: *"Failure may occur after Meta accepted
the message. Never blindly retry it."* That is the correct posture and must not be relaxed.

**FINDING V-2 (MEDIUM, latent) — the download template is not actually sent today.** PROVEN at
`:91-95`: the default is **`wecare_share_pdf`**, and `wecare_default_download` with its
`https://wecare.digital/vault/?file={{1}}` button is used **only if**
`VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED == 'true'` (`:93`) — absent everywhere.
`wecare_share_pdf` has an IMAGE header and carries no URL button and no file parameter. So the
sequence today is not "order message then download template"; it is "one share template, then
*possibly* an attachment". If the customer is outside the 24-hour window, step 4 is skipped too and
the function still returns **`VAULT_READY`** (`:113`) — a success outcome for a purchase that
delivered neither a link nor a file. Design item **F-10**.

The staging posture is otherwise coherent and should not be disturbed:
`catalog_service_checkout.meta_ready:91-106` refuses native checkout unless all three templates are
`APPROVED` and `en` (`:93-96`) **and** the download template's first button is `type: 'URL'` with
exactly `https://wecare.digital/vault/?file={{1}}` (`:98-101`). Readiness is proven before the flag
can open; readiness and *use* are simply decoupled, and only readiness is currently true. **Whether
that template is still APPROVED with that exact button is NOT VERIFIED — provider read, owner-only
(O12).**

**File origin and the real TTLs — CONFLICT C16.** The document is a private S3 object served by a
presigned GET minted at `secure-files:1240-1257`, with
`ResponseContentDisposition: attachment; filename="…"` (`:1252-1254`) and
`ExpiresIn=int(ttl or DOWNLOAD_URL_TTL)` (`:1256`). Constants at `:212-219`, with live values read
2026-10-09T04:39:21Z:

| Constant | Line | Code default | Live env | Effective |
|---|---|---|---|---|
| `UPLOAD_URL_TTL` | `:213` | 900 | `UPLOAD_URL_TTL_SECONDS=900` | 900 s |
| `DOWNLOAD_URL_TTL` | `:215` | **60** | `DOWNLOAD_URL_TTL_SECONDS=60` | **60 s** |
| `WHATSAPP_LINK_TTL` | `:218` | `max(60, min(900, …))` | `WHATSAPP_LINK_TTL_SECONDS=`**`21600`** | **900 s** (clamped) |
| `GRANT_TTL` | `:219` | 1800 | `GRANT_TTL_SECONDS=1800` | 1800 s |

**`GRANT_TTL` is a DynamoDB TTL sweep, not merely a validity window — and it applies to only TWO of
the three grant origins.** Review 3 finding 2 is accepted: revision 3 listed `GRANT_TTL` in this
table and never said what it does to the record. Re-derived at `061b6e77`:

| Grant origin | Writes `expiresAt`? | Lifetime | Evidence |
|---|---|---|---|
| `secure-files._create_order` | **yes**, `now + GRANT_TTL` | **TTL-swept after 1800 s** | `handler.py:1016` |
| `secure-files._reconcile_grant` | **yes**, `now + GRANT_TTL` | **TTL-swept after 1800 s** | `handler.py:1306` |
| **native `vault_access.grant_access`** | **NO `expiresAt` at all** | **durable — never swept** | `vault_access.py:64-67`; `git grep -n expiresAt origin/stack -- .../vault_access.py` → no matches |

`DownloadGrantsTable` has **TTL ENABLED on `expiresAt`** — *"a download grant is deliberately
short-lived, so expiry is the point of the record"* (`scripts/check_data_model_drift.py:191-196`).
DynamoDB TTL only sweeps items that **have** the attribute, so the native grant is permanent.

**The durable proof of payment is on the FILE row, not the grant row.** `vault_access.py:71` writes
`vaultAccessGrantId`, `vaultPaymentStatus='PAID'`, `vaultOrderNumber` and `vaultRequestNumber` onto
`SecureFilesTable`, whose TTL is **DISABLED** by deliberate design — *"a shared file outlives any
session and must not be swept"* (`check_data_model_drift.py:186-190`). This is what **F-9** derives
re-issue entitlement from, and it is why **no TTL is created, extended or touched** by that fix.

**The "300 seconds" in prior handoff prose is in neither the code nor the live environment**
(C16). And **FINDING V-3 (LOW, live config)**: the live env asks for 6 hours and `:218` clamps it to
15 minutes — safe, because the clamp is the `724dcc38` hardening, but environment and behaviour
disagree by 23× on a security-relevant value (C17). Design item **F-11**.

**Ownership is checked before any URL is minted, and the signed URL is not the access control.**
PROVEN. `_owned_active_file` (`:948-960`) is the single chokepoint, and it is positive-attribution
only: `ownerPhone` match (`:956-957`) **and** `identity['subject']` present **and**
`ownerCustomerId == identity['subject']` (`:958-959`). Its docstring records the enumeration
defence — *"Every failure mode returns None so callers cannot tell them apart"* (`:951`) — so a
caller cannot distinguish "no such file" from "not yours". All three existing callers pass through
it (`:977`, `:1268`, `:1417`), and `_redeem` additionally requires
`grant['customerId'] == identity['subject']` (`:1421`). **Knowledge of a file ID is not
authorization**: the id is a path parameter and is useless without a Cognito session whose `sub`
equals the file's `ownerCustomerId`. Delivery re-checks independently at `:1358-1363`.

### FINDING V-1 (HIGH, LIVE via the native path) — a paid customer whose link expires after redeeming is told to pay again

This is the answer to the owner's question 3, and it is worse than a missing feature.

**Which path is gated and which is not — the precise reachability claim** (review 3 finding 1). The
review held that `SECURE_FILES_PAYMENT_ENABLED=false` makes V-1 unreachable. That is true of the
`secure-files` paid routes and **false of the path that mints Vault grants in production.**
Re-derived at `061b6e77`:

| Fact | Evidence |
|---|---|
| `_payment_enabled` has **exactly four** refusal sites | `secure-files/handler.py:981` (`_create_order`), `:1058`, `:1156` (`_reconcile_grant`), `:1272` (`_send_whatsapp_payment`); definition `:255`, env read `:261` |
| **`_redeem` (`:1405`) is NOT among them** | the redeem route runs regardless of the flag |
| The flag exists **nowhere else** in `amplify/` | only `scripts/provision_secure_files_api.py:349,360,370,682` |
| The native minter is in a **different Lambda**, ungated | `flows/paid_vault.py:63` → `vault_access.grant_access` (`vault_access.py:30`), in `wecare-whatsapp-business-api` |
| Its reach-path carries no rollout flag either | `whatsapp-business-api/handler.py:5996-6000` → `paid_submit_request.py:104` → `:127` `kind == 'VAULT'` → `:128-129`. The only flag in `paid_vault.py` is `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` (`:93`), which picks a template |

**So the live chain is the native one and it is open today:** native purchase → durable grant
(`vault_access.py:64-67`, no `expiresAt`) → web redeem through the **ungated** `_redeem` → `consumed`
flips (`:1427`) → the 60 s URL expires → retry hits `:1459-1460` *"Please pay again to download."*
**V-1 stays HIGH.** The gated `secure-files` origins are additionally affected, but their grants are
TTL-swept, so for them the live residue is the `:1459-1460` copy alone.

**Population count before the route ships** (`A0_READ`, justifies `design.md` §5 row 4c):
`dynamodb scan --select COUNT` on `DownloadGrantsTable` with
`paid = :t AND consumed = :t AND attribute_not_exists(expiresAt)` isolates the durable native
grants. ≥ 1 justifies the route; `0` demotes V-1 to MEDIUM-latent and ships only the copy fix.

**Case 1 — WhatsApp link expires, grant NOT consumed: recoverable, no second charge. Correct
today.** Delivery deliberately mints its URL outside the redeem route — `:1371-1374`: *"Generated
here rather than reusing the redeem route so delivery does not consume the grant the customer may
still redeem on the web."* So after the 900-second link dies, `GET /files/mine` (`:1800-1804`) still
surfaces `paidGrantId` and `deliveryStatus: 'READY'`, because `_customer_list:933` requires
`grant.get('paid') and not grant.get('consumed')`. The customer redeems once on the web. PROVEN
working.

**Case 2 — grant consumed, then the 60-second URL expired: NOT recoverable.** PROVEN:

- `_redeem` is single-use by construction. `ConditionExpression` requires `consumed = :false` and
  the update sets `consumed = True` (`:1425-1441`); rationale at `:1408-1410` — *"a forwarded link
  is dead on second use."*
- On the conditional failure it correctly tries `_reconcile_grant` first (`:1453`, asking Razorpay
  directly for the never-arrived-webhook case — genuinely good), and otherwise returns
  `403 GRANT_NOT_REDEEMABLE` with the message **"This download link is not valid. Please pay again
  to download."** (`:1456-1463`, the copy itself on `:1459-1460`).
- `_customer_list:933` no longer offers a `paidGrantId` once consumed, so the UI has nothing to
  retry with.
- The only remaining route is `_create_order` (`:963`) — **a second ₹49 charge** — whose own
  docstring (`:966-972`) describes it as the recovery path for *"a customer who has already paid
  [to] collect a file when WhatsApp delivery keeps failing"*.

**The code states an intent it does not deliver.** `:216-217`: *"a customer can use authenticated
Vault access after the delivery link expires."* True while the grant is unredeemed; **false once
consumed.** Sixty seconds is a narrow window on a mobile connection — a suspended tab, a tunnel, a
user who taps and then reads a message. This is an ordinary occurrence, not an edge case.

**Root cause.** `consumed` is doing two unrelated jobs: defeating a **forwarded** link used by a
third party, and capping the **owner's own** re-downloads. The first is essential; the second is an
accident of sharing one flag. **A forwarded link carries no Cognito session, so it can never satisfy
`_owned_active_file:948-960` or `:1421`** — which is why re-issuing to the authenticated owner does
not weaken the forwarded-link defence at all, and why the fix is a strengthening rather than a
relaxation.

**Design item F-9 is the binding specification** — smallest-safe-change, the auth envelope
(`_customer_identity` at `secure-files/handler.py:1828`, inside the customer block at `:1827-1836`;
**not** `require_auth(event, 'Operator')` at `:1840`, which is the admin surface), the single
conditional update including its mandatory
`(attribute_not_exists(reissueCount) OR reissueCount < :cap)` clause, the
`ConditionalCheckFailedException` mapping, per-condition error handling, input validation and **six**
regression tests — among them
`test_a_swept_grant_does_not_tell_a_paid_customer_to_pay_again`.
`outputs/whatsapp-customer-service-architecture.md` §6.5 is **subordinate** to `design.md` F-9
wherever the two differ: its alternative route shape is deleted and the one shape is
**`GET /files/{id}/download?reissue=1`**. The cap and counter live on the **durable FILE row**, not
the TTL-swept grant row.

**Catalog description and availability (owner question 4).** The Vault item's name, description,
price, image and availability are projected from Wix, not hand-maintained: Wix change ->
signature-verified `wecare-wix-catalog-webhook` -> `wecare-meta-catalog-sync` -> `items_batch`,
with an identical join key on all three sides (`meta_catalog_sync.retailer_id:182-205` builds
`wix:<productId>:<variantId>` lowercased; `catalog_service_checkout.payment_details:73` builds the
same string for the order line; the browser builds it at
`src/lib/metaCatalogAnalytics.ts:64-67`). Availability is **force-held out of stock** while the
gates are shut — live `META_CATALOG_SYNC_FORCE_OUT_OF_STOCK=true`, applied at
`meta-catalog-sync/handler.py:550-552`, and the staged proposal shows all four items including
Vault at `price: "49.00"` carrying `"availability": "out of stock"`. **A vanished item is retired,
never deleted** (guarantee declared at `meta_catalog_sync.py:562-567`, enforced by the retire loop
at `:606-620`). **But the write half of this pipeline is currently blocked for an external reason —
see G and H**: the targeted catalog reads successfully and is empty, so the Vault item's description
and availability are computed correctly and **not yet present** in Meta.


## Q. Are invoice / receipt sends correct and deduplicated on webhook retry?

**PROVEN deduplicated, and the failure postures are deliberately asymmetric in the right
direction.**

- **Invoice creation** is claimed before numbering. `payments/invoice-engine/handler.py:843-852`
  derives a deterministic `invoice_id = 'inv-' + sha256(f'invoice\x1f{reference_id}\x1f{payment_id}')[:32]`
  and puts `{'invoiceId', 'status':'claiming', 'createdAt'}` under
  `ConditionExpression='attribute_not_exists(invoiceId)'`. The comment at `:829-833` records the
  exact bug this fixed — webhook and inbound handler both invoking for the same payment, both
  scanning, both missing, both inserting, with a fresh `uuid4` making the final guard useless — and
  notes it mattered more than an ordinary duplicate because it **consumed a GST sequence number**.
  The sequence has a compensating decrement guarded by `ConditionExpression='lastSeq > :zero'`.
  `referenceId` binding is `attribute_not_exists(referenceId) OR referenceId = :ref`, so re-posting
  the same reference is a no-op and a *different* one is refused.
- **Invoice WhatsApp delivery** is claimed per channel via
  `order_keys.claim_invoice_delivery(..., channel='whatsapp')` →
  `INVOICEDELIVERY#<invoiceId>#whatsapp`, and the dispatch is async `Event` so a delivery failure
  cannot make Razorpay retry a captured payment. Delivery is additionally gated on
  `channel == 'whatsapp' and checkout_mode == 'WHATSAPP_NATIVE_PG'`
  (`razorpay-webhook/handler.py:2449-2450`) — deliberately, so that gating on channel alone does
  not start sending documents to website customers who receive none today.
- **Post-payment Flow send** is claimed with
  `ConditionExpression='attribute_not_exists(postPaymentFlowSentAt)'`
  (`razorpay-webhook/handler.py:1710-1715`), and the conditional-failure arm logs
  `post_payment_flow_skipped … 'already sent (idempotent)'` at **info** (`:1719-1721`) then
  `return`s. A non-conditional error logs a warning and **continues to send once** (`:1723-1724`) —
  a deliberate fail-open on a non-financial artifact.
- `claim_invoice_delivery` **fails closed**: `False` only on a lost race, while a throttle raises
  `OrderIdentityUnavailable` so the caller cannot mistake an outage for a prior delivery.

Correct posture, worth naming: the invoice claim fails **closed** toward not sending (a duplicate
GST document is a compliance artifact) while the review request fails **open** toward not sending
(a missing nudge costs nothing). `razorpay-webhook/handler.py:2463-2467` states that asymmetry
explicitly. I agree with it.

Subject to **N-1** on the same path — and note `invoice-engine/handler.py:853` is the **negated**
site, on the GST-sequence path, which is the most consequential of the six.

## R. Are review invitations correct and deduplicated, with the correct trigger?

**Each path is internally idempotent. PROVEN they do not dedupe against EACH OTHER — a native
service purchase can send two `wecare_leave_review` templates.**

Three independent senders of the same template, with three **unrelated** claim namespaces:

| Sender | Trigger | Claim key | Store |
|---|---|---|---|
| `razorpay-webhook/handler.py:2468-2470` → `_request_review_on_whatsapp` (`:2593`), claim at `:2622-2624` | any confirmed-paid webhook where `contact and invoice_id` | `INVOICEDELIVERY#<invoiceId>#review` | commerce-keys table |
| `flows/paid_submit_request.py:96-101` | after `detailsSubmittedAt` is saved | `requestReviewStatus` attribute | ServiceRequests row |
| `flows/paid_vault.py:87` | after the ready notification (and the document send, when a PDF is deliverable) | `vaultReviewStatus` attribute | ServiceRequests row |

**FINDING R-1 (MEDIUM, latent).** The webhook arm is **not** excluded for native catalog service
purchases. Its guard is only `if contact and invoice_id:` at `razorpay-webhook/handler.py:2468`,
and the comment block immediately above (`:2454-2467`) says so deliberately — with the sentence
"So **BOTH legs ask** - WhatsApp and website - which is deliberate and is the one place this
differs from step 4" at `:2458-2459`. That reasoning is sound for the website/WhatsApp split it was
written for, but it predates the native service paths, which add their own review send keyed on a
different row. Nothing correlates `INVOICEDELIVERY#<invoiceId>#review` with `requestReviewStatus` /
`vaultReviewStatus`.

Consequence: one native Submit Request purchase that produces an invoice sends the review template
once at capture (webhook) and once after details are saved (`paid_submit_request`). Same for Vault
after delivery. This contradicts README §9 ("a single review invitation") and
`native-catalog-release-status.md` ("once-only `wecare_leave_review`"). Latent only because
`WHATSAPP_CATALOG_SERVICES_ENABLED` is absent. Hard prerequisite for **L**. Design item **F-2**.

**Trigger correctness.** The native triggers are better than the webhook's: Submit Request asks only
after `detailsSubmittedAt` (reviewing a service actually received), and
`flows/paid_submit_request.py:81-95` re-verifies the recipient from scratch —
`contact.checkoutCustomerId == row.customerId`, not deleted, `contact.phone == row.flowPhone`,
exactly one `Enabled` Cognito user, `phone_number == row.flowPhone`,
`phone_number_verified == 'true'` — before sending, returning `VERIFIED_RECIPIENT_UNAVAILABLE`
otherwise. The webhook's trigger (at capture, before any fulfilment) is the weaker one and is the
arm that should yield.

**The consequence F-2 must own explicitly** (review finding 9). The native senders are
*conditional*: `send_review` returns `REVIEW_NOT_DUE` (`:81-83`) without
`kind == 'SUBMIT_REQUEST'` **and** `detailsSubmittedAt` **and** `flowContactId` **and**
`flowPhone`; `paid_vault` reaches its review send only after `grant_access` succeeded, the identity
chain held, and the notification claim was won (`:71-72`), with `VAULT_DOCUMENT_PENDING` at `:84`
if a deliverable PDF's send claim is lost. So after F-2, **a paid native purchase that is never
fulfilled receives ZERO invitations.** That is the correct product rule and `design.md` F-2 states
it as a decision with a test, rather than leaving it as a silent side effect.

## S. Does the workspace show the purchase once, with customer, public order number, payment state and Wix order ID?

**Answered from source this revision. Revision 1 quoted a document it had itself declared
superseded (review finding 11); that citation is withdrawn and replaced with `file:line` reads.**

### S1 — the backend list, `amplify/functions/messaging/whatsapp-business-api/service_api.py:100-153`

Reached via `GET /wa-business/orders` → `handler.py:6574` → `_svc_list_orders(params)`, which
is `service_api._list_orders` imported at `handler.py:5912`. **Authenticated**: `require_auth(event)`
runs at `handler.py:6034`, before any route dispatch, and the only member of `AUTH_SKIP_PATHS` is
`/wa-business/flow-data`. No auth bypass on this route.

What it does, exactly:

| Behaviour | Line | Note |
|---|---|---|
| `phone` → query `customerPhone` GSI; `status` → `orderStatus` GSI; `source` → `source` GSI | `:107-118` | first matching branch wins; they are mutually exclusive |
| **no filter → full `table.scan()`** | `:120-121` | a whole-table scan of the production order table |
| **traverses every result page** | `:124-127` | `while resp.get('LastEvaluatedKey')` with `ExclusiveStartKey`; `:126` correctly re-dispatches `query` vs `scan` |
| **maps `PAYMENT_PAID` → `paid`** | `:128-130` | server-side, per item |
| defaults `status` from `orderStatus` | `:131` | |
| **`search` matches `orderId` + `orderNumber` + `wixOrderId` + `customerName` + `customerPhone`** | `:132-134` | the filter itself is `:134`; substring, lowercased — so public order numbers **and** Wix IDs are searchable |
| sorts by `createdAt` desc | `:136` | |
| **truncates to `limit`, default 200** | `:137-138` | **silent truncation** |
| N+1 `COUNT` query per order for `requestCount` | `:141-150` | up to 200 extra round trips |

So the three behaviours `native-catalog-release-status.md` asserted are **true**, but the mapping
and the search live in the **backend**, not the frontend. Revision 1 attributed them to the
frontend; the design review assumed they were frontend and therefore wrong. **Both were mistaken
about location; the document was right about substance.**

### S2 — the frontend, `src/pages/workspace/engage/orders/index.tsx`

- `loadOrders` (`:187-204`) calls `api.listOrders({status, source, search})`. It passes **no
  `limit`**, so the 200 default governs, and **no cursor**: `setOrders(data.orders || [])` takes one
  response. Since the backend already traverses pages, there is no client-side pagination gap — the
  gap is the **200-row ceiling**.
- `paymentFilter` is applied **client-side only** (`:282-286`), over the truncated set.
- Paging is client-side over the fetched array: `PAGE_SIZE = 20` (`:18`),
  `totalPages = Math.ceil(filtered.length / PAGE_SIZE)` (`:288`), `paged = filtered.slice(...)`
  (`:289`).
- List columns (`:338-346`): Order ID, Date, Customer, Source, Items, Status, Payment, Requests.
  The label is `order.orderNumber || order.shortId || extractShortId(order.orderId)` (`:351`) — so
  it **does** fall back to a derived short form of the internal id. Acceptable on a staff surface,
  but it means "public order numbers only" is **not** true of the workspace.
- Payment state renders as `<Badge status={order.paymentStatus} />` (`:365`), and `Badge`
  displays `(status || '—').replace(/_/g, ' ')` (`:128`) — i.e. the backend-normalised `paid`, or a
  raw state with underscores spaced.
- **`wixOrderId` appears only in the detail panel** (`:439`, conditional on presence), not in the
  list. It is the only `wixOrderId` reference in `src/pages` besides a dashboard schema label.
- `openDetail` (`:209-211`) passes the already-loaded list row and fetches submissions + tracking;
  it does **not** call `getOrder`.

Worth recording because it is a genuine inconsistency the review half-spotted: `src/api/client.ts`
has **two** different normalisations. `listOrders` (`:5769-5785`) passes the backend payload through
untouched, while `getOrder` (`:5786-5790`) re-maps
`order.paymentStatus === 'PAYMENT_PAID' ? 'paid' : order.paymentStatus` **client-side**. Two
normalisation points for one concept, in one module. Not a security issue; recorded for **F-8**.

### S3 — verdict

**Yes for "once", yes for customer, yes for payment state, yes for Wix order ID (detail panel
only), and NOT STRICTLY for "public order number"** — the workspace falls back to a derived
internal short id when `orderNumber` is absent, which is exactly the legacy-attribution debt
**F-6** addresses on the customer-facing side.

The "once" guarantee comes from **N**'s claim set, not from the UI: `orderNumber` on the order row,
`wixOrderId` persisted on the writeback claim (`wix_writeback.py:239`, `:272`), payment reference
via `PAYREF#<referenceId>` (`order_keys.py:40`, `:84`), and `customerUuid` minted once with
`if_not_exists`.

**NOT VERIFIED:** the rendered row for a real purchase. That needs an authenticated staff session,
which needs **O7** (the sole Cognito user is in none of `Admin`/`Operator`/`Partner`/`Viewer` per
`docs/kiro-handoff.md`), and a real purchase, which needs **O2** and **O4**. Recorded as pending,
not as passing.

Two defects for the backlog, neither in `design.md`'s fix register because neither is on this
audit's critical path: the unfiltered `scan()` at `service_api.py:121`, and the silent 200-row
truncation at `:137-138` which gives an operator no indication that orders are missing.

## T. Are tracking events wired to the CURRENT catalog content IDs?

**Content-ID format: PROVEN to match. Event destination: PROVEN inconsistent, and unverified at
Meta. The catalog retarget has made the mismatch worse, not better.**

**Format matches.** `src/lib/metaCatalogAnalytics.ts:12-13` (re-derived; revision 3 cited `:11-12`,
where `:11` is the `PURCHASE_KEY` constant — review 3 nit 14) builds
`` `wix:${SERVICES_PRODUCT_ID}:${row.variantId}` `` with
`SERVICES_PRODUCT_ID = 'df976a0a-f582-4535-b2e1-d532f348bd27'` (`src/config/services.ts:49`). The
backend writes `retailer_id(product_id, variant_id)` = `wix:<productId>:<variantId>` lowercased
(`meta_catalog_sync.py:182-199`, `RETAILER_PREFIX = "wix"` at `:50`), and `parse_retailer_id`
(`:208-227`) anchors on exactly three colon-separated segments with two UUIDs. Wix UUIDs are already
lowercase hex, so the TS value equals the backend value. `AddToCart` and `Purchase` additionally
validate every `contents[].id` against that same allow-list (`:93`, **`:101`** — `Purchase` is at
`:101`, not `:102`; nit 14), so an unknown id is refused rather than sent, and `catalogContentId`
(`:64`) returns `null` for anything not in the set (`:66`).

**Scope matches too**: `:12` filters to `SUBMIT_REQUEST` and `VAULT` only, which is exactly the
live `META_CATALOG_SYNC_VARIANT_IDS` pair. Request Amendment and Drop Docs are not tracked,
consistent with their not being in the catalog (**I**).

**FINDING T-1 (MEDIUM) — the destination id is a dataset id used as a browser pixel target.**
`src/lib/metaCatalogAnalytics.ts:6-8`:

```ts
export const META_DATASET_ID = '4554612361454941';
export const META_PIXEL_ID = META_DATASET_ID;   // "Back-compat alias only - Same value."
```

Every browser event is `fbq('trackSingle', META_DATASET_ID, …)` (`:73`, `:82`, **`:101`**). The
comment at **`:3-5`** asserts "Events Manager unified pixels and datasets, so a dataset id is a valid
`fbq('init', …)` / `fbq('trackSingle', …)` target". That is a **claim, not a measurement**, and the
repository's own commit `53ed298e` concedes the point in its title: *"fix: label the shared CAPI
dataset as configured, not verified"*. Meanwhile `docs/kiro-handoff.md` and README §10 both record
the **website** event source as Pixel `3411484995761247`, which appears nowhere in this module. If
`4554612361454941` is not a valid browser target, every `ViewContent`/`AddToCart`/`Purchase` from
the site is silently dropped — a failure that produces no error anywhere.

**Compounded by the retarget.** Content IDs are catalog-independent retailer ids, so they resolve
against whichever catalog actually holds the items. The items were published into
`1607047307067517`; live now targets `1457045652952851`, which reads **200 with an empty product
list** (**H**). So **right now every catalog-matched event is unmatched**, because the targeted
catalog contains none of the items. Before the retarget the items existed but the catalog was
unreadable; after it the catalog is readable but empty. Either way the catalog-match is broken, and
fixing it requires publishing the items — a write gated on **O1**/**O3**.

Confirming the pixel-vs-dataset question needs an Events Manager read: **NOT VERIFIED — owner /
provider check, not engineering.** The parallel session concurs: "Dataset linkage, event reception
and legitimate Purchase/catalog-match diagnostics are NOT VERIFIED. No synthetic Purchase events
sent." None were sent here either.

## U. Owner vs provider vs engineering

### Blocked on the OWNER

| # | Item | Exact action | Changed this revision |
|---|---|---|---|
| O1 | **Meta catalog access / assignment** — blocks **G, H, I, L, T** | Determine in Business Settings → Assets → Catalogues whether `1607047307067517` was **deleted** or **unassigned** (Graph 100/33 cannot tell), and confirm the system user holds catalog-management on `1457045652952851`. No code change. | **Narrowed** — the refusal code is now known; only deletion-vs-permission is open |
| O2 | **QA customer identity link** — blocks **J, L, S** | **Sign in on `wecare.digital` as the existing customer account whose `phone_number` is `+918100640044` (already CONFIRMED, `phone_number_verified = true`) and save the customer profile with that number.** That writes `checkoutCustomerId` onto the contact row via `auth/customer-profile/handler.py:263`. **No agent writes it directly and `VERIFIED_CUSTOMER_REQUIRED` is not bypassed.** Because `wa918100640044` has `checkoutCustomerId` null, `_claimable` (`auth/customer-profile/handler.py:143`, returning at `:168`) is satisfied, so **linking the existing row is the expected outcome** — **INFERRED**, not proven. The **failure mode** is a second contact row or `409 CONTACT_IDENTITY_CONFLICT` (`:299`, `:309`, `:508-509`); **if that occurs**, the owner chooses between staff reconciliation and accepting it. The result is read after the save either way. **O2 is a single self-service save with one contingency, not a decision required before acting.** | **CORRECTED and now stated identically in J, U and `design.md` §7** (review 3 finding 5). Revision 2 asserted a second contact *would* be created; revision 3 carried both readings at once. See **J** |
| O3 | **Which catalog is canonical** | Decide. **Already acted on in production by the parallel session** — live `wecare-meta-catalog-sync` v7 targets `1457045652952851`. Confirm that was intended, or roll back to v6's env. | **Changed — decision was executed, not just pending** |
| O4 | **Real QA payments** | Owner completes both journeys personally. Requires an existing earlier order (Submit Request) and an owner-uploaded file (Vault). | — |
| O5 | **Submit Request draft publication** | Approve publishing the exact paid draft if it is in fact DRAFT (C2). | — |
| O6 | **Wix eCom write scope attestation** | Attest the live site grants eCommerce write before `WIX_WRITEBACK_ENABLED` / `WIX_ECOM_WRITE_CONFIRMED` are considered. | — |
| O7 | **Admin group membership** | `admin-add-user-to-group … --group-name Admin` on `us-east-1_cSx0RHCIR`. The sole user is in no group, which blocks every Admin-authenticated verification including **S**. | — |
| O8 | **SDK app decision** | `2238810740192680`: earlier keep, later cleanup, auto-review rejected for want of a fresh explicit choice. | — |
| O9 | **Old-catalog deletion** | Only after an inventory, and now additionally complicated: `1607047307067517` may already be deleted. Deletion is forbidden here; the inventory in `design.md` §3 is the deliverable. | **Narrowed** |
| O10 | **NEW — authorize or refuse this audit's DEPLOYS** | No surviving steering file grants standing authorization. `design.md` §5 lists each proposed deploy with its target, mechanism and rollback for explicit approval. **Scope: §5 rows 2, 4b-i, 4b-ii, 4c and 7 only.** It does **not** cover the production inspect invoke — that is **O13**, separately refusable (review 3 finding 12). | **New; scope narrowed** |
| O11 | **Adjudicate the two-session overlap** | Two sessions are editing and deploying the same functions; `wecare-whatsapp-business-api` reached **v89** during this audit and **v87–v89 are certified against source by nobody**. Decide which session owns `messaging/whatsapp-business-api` and the outbound delivery contract (their AUD-018) before this audit's **F-4 live sites**/**F-6** touch it. **Note F-2 and F-5 are now explicitly NOT blocked on this** — they target `wecare-razorpay-webhook` and `wecare-invoice-engine`, untouched by the parallel session (`design.md` §5 row 4b-i). | **Narrowed and re-scoped** |
| O12 | **NEW — confirm the Vault download template** | Read in WhatsApp Manager that `wecare_default_download` is still **APPROVED**, language `en`, with its first button `type: URL` and url exactly `https://wecare.digital/vault/?file={{1}}`. `catalog_service_checkout.meta_ready:93-101` enforces this, so it blocks nothing silently — but **F-10** makes it a hard precondition of opening the native Vault gate, and nothing in this audit read Meta. Provider read; no write. | **New** |
| O13 | **NEW — authorize or refuse the single PRODUCTION INSPECT INVOKE (`design.md` §5 row 3a)** | One `{"inspect": true, "source": "audit"}` invoke of `wecare-meta-catalog-sync:live`. It is a **production Lambda invoke** (`A3_PRODUCTION`), but provably constructs no write — `handler.py:565-572` returns before `_batch_requests` is reachable. It is the only reliable way to read the retarget's effect, because the Wix webhook has not fired since 00:24:18Z (**C15**). **This is the only item gating row 3a; `design.md` §5 row 3a, §5 row 5's dependency and §7 all cite O13, never O10.** §5 row 5 (F-8 docs) depends on 3a or on the unreliable 3b. | **New** |

### Blocked on a THIRD PARTY / PROVIDER

| # | Item | Status |
|---|---|---|
| P1 | **Which** Meta refusal is behind **G** | **PARTLY RESOLVED** — code 100 / subcode 33 is known. Deletion-vs-permission still needs a Business Settings read (O1). |
| P2 | Whether a CAPI **dataset** id is a valid `fbq` browser target (**T-1**) | Events Manager read. Open. |
| P3 | Direct Send per-WABA onboarding | Granted by Meta per WABA; unverifiable without a token call. Open. |
| P4 | Razorpay MCP | Provider token endpoint advertises only `client_secret_post`. Open. |
| P5 | Wix product revision 4-vs-5 (C4) | Needs a credentialed Wix read. Open. |
| P6 | **NEW** — Meta component / in-Flow payment capability | The parallel session records "Current primary Meta component/payment docs could not be fetched; detailed picker/payment account support remains unverified". Open; **not claimed** anywhere. |

### Remaining ENGINEERING (all permitted, none destructive, none enables a gate)

| # | Finding | Severity | Permitted | Changed this revision |
|---|---|---|---|---|
| **F-9** | **A paid Vault customer whose grant is consumed and whose 60 s URL expired cannot re-download, and the product tells them to pay again** (`secure-files:1456-1462`) | **HIGH, LIVE** | Yes — it *strengthens* authorization; the forwarded-link defence is untouched | **NEW.** The only HIGH finding reachable by a real customer on a live, unflagged path today |
| F-1 | `read_failed` discards the Graph status; **two arms emit no telemetry at all** (`:531-534`, `:565-572`) and three more carry no `reason` | MEDIUM (diagnostic) | Yes — logging only | **Rescoped and strengthened.** Revision 2's "3 of 5 arms lack `reason`" understated it: §1.1 proves two production invocations completed with **zero** application log lines. The HIGH→MEDIUM demotion is withdrawn in substance; F-1 stays items 1–2, ahead of everything |
| F-2 | Duplicate review invitation across the webhook and native paths (**R-1**) | MEDIUM, latent | Yes | **Rewritten.** The call must be **guarded**: unguarded it would turn a DynamoDB throttle into a webhook 500 and replay a captured payment. Fail-open posture, table handle and two failure-branch tests now specified |
| F-10 | A native Vault purchase outside the 24 h window returns `VAULT_READY` having delivered neither a link nor a file (`paid_vault.py:91-113`) | MEDIUM, latent | Yes | **NEW** |
| F-3 | `flows/catalog_services.py:94` still accepts `ownerCustomerId is None` (**P-1**) | MEDIUM, latent | Yes — tightens a check | Unchanged from revision 2: halved by `724dcc38`; one site left; offered-then-refused, no money moves |
| F-4 | `list_users` Filter built by string concatenation — **SEVEN sites: two guarded, five unguarded** | LOW | Yes | **Count corrected** (review 3 finding 10): the seventh is `customer_orders.py:60`, guarded by its own inline `re.fullmatch` at `:57`. Fix set is still the five unguarded, **plus** converting **both** inline regexes to `customer_auth.is_cognito_subject` so the literal pattern appears exactly once. **Citations re-derived**: `checkout:3080` (was `:3098`) and `paid_vault:69` (was `:44`) both moved upstream |
| F-5 | Conditional-failure detection by exception substring at six money-path sites, one **negated** | LOW | Yes | Re-verified unchanged at `e9e377ce`. Note `razorpay-webhook:640` **already** uses `order_keys.is_conditional_failure` — an in-tree model for the fix |
| F-6 | `list_orders` can surface an internal `orderId` as a customer-facing label, and its result doubles as an eligibility gate | LOW | Yes | **Redesigned.** Revision 2's `order_choices` had two incompatible return shapes and was not implementable from its inputs. Now: a plain `list`, the rule applied inside the loop using `order_keys.is_public_order_number`, and eligibility split into a new `has_prior_order` |
| F-11 | Live `WHATSAPP_LINK_TTL_SECONDS=21600` silently clamped to 900 (C17) | LOW, config | **OWNER CONFIRM** — it is a production env write, publish and alias move | **NEW** |
| F-7 | Deploy `a739d016` (shared catalog + fixed CAPI dataset) | MEDIUM | **Owner-gated — STOP** | Unchanged: catalog half achieved by env change in v7; the CAPI half is untouched |
| F-8 | Documentation reconciliation: C1–C19 | MEDIUM | Yes | **Expanded** by C14–C19. Item 6 (QA recipient) **corrected** — revision 2's provenance claim was wrong |

### Already CLOSED

Graded, per review 2 finding 9. "Closed" means no engineering work remains, not that every
sub-fact is first-party.

| Q | Status | Evidence grade |
|---|---|---|
| **E** `/payment-config/raw` | **CLOSED — the strongest close in the audit** | **PROVEN.** `e9e377ce` added an explicit `410` arm at `handler.py:6399-6404`, placed before the `phoneId` handler, pinned by a committed test asserting `410`, both pointer fields and `graph.assert_not_called()`. Committed source **plus** a committed test |
| **F** payment configuration | **CLOSED with no mutation** | **PROVEN BY ANOTHER SESSION'S STRUCTURED ARTIFACT (v86, 2 inert GETs) — not reproduced this pass.** Re-tagged per finding 9. Both calls were `GET`; the no-mutation rule is intact. The root cause (Meta's `fields` filter returning an empty collection for the `payment_configurations` edge, plus an unpaginated read) is a **source diff**, which *is* first-party |
| **G** root cause | **CLOSED as engineering; one provider fact open** | **Split.** Failure, sustained nature, externality and the old-unreadable/new-readable-and-empty asymmetry: **PROVEN first-party this pass** (CloudWatch 04:33:06Z + the handler's own committed `inspect` output). The `100/subcode 33` value itself: **REPORTED BY ANOTHER SESSION, NOT INDEPENDENTLY VERIFIED — and not verifiable by this agent**, because it needs the Meta token and `get-secret-value` is forbidden |
| **H** | **CLOSED as a hypothesis class** | **INFERRED from the asymmetry.** A catalog *was* read successfully with the same credential, which excludes "no catalog-management permission in general". What remains is object-specific: deleted or unassigned — **O1** |
| **N** one payment → one order → one Wix association | CLOSED | **PROVEN** — conditional claims at every step, `file:line` throughout |
| **O** Submit Request parent-order distinction | CLOSED | **PROVEN** — explicit `oid == row['orderId']` exclusion (`:91-92`) plus a `ConsistentRead=True` ownership recheck (`:93-95`) |
| **P** delivery half | CLOSED | **PROVEN** — positive attribution at `grant_access:51-52` and the grant transaction's `ConditionExpression` at `:71`; bearer-link ceiling clamped to 15 min upstream |
| **P** entitlement/re-issue half | **OPEN — F-9, HIGH** | **PROVEN defect.** This is new in revision 3 and it is the audit's most serious customer-facing finding |
| **Q** invoice/receipt dedup | CLOSED | **PROVEN** — claimed per invoice and per channel, failing closed |
| **S** | CLOSED as to backend behaviour | **PROVEN** from `service_api.py:100-153`; the rendered row still needs **O2**, **O4**, **O7** |
| **G/I** "catalog sync is broken" | **SUPERSEDED TWICE** | The sync worked 45 times on the same bytes; the block is external and bounded; the live target has since moved. **But I cannot say whether the last planned `update: 2` was applied** — the apply arm's return is unlogged, which is F-1 again |

### The honest bottom line on what this audit could not do

Three things, stated so nobody mistakes silence for completion:

1. **No independent Meta Graph read was possible** — the token is in Secrets Manager and reading it
   is forbidden. Every Meta-side fact here is either first-party telemetry, a source diff, or
   explicitly second-hand.
2. **No authenticated backend read was possible** — `require_auth` at `handler.py:6034` precedes
   route dispatch, and this agent has and must have no Cognito session.
3. **No live purchase, send, capture, refund, fabricated webhook or simulated customer was
   performed, and none may be.** The owner completes real payments personally; the only authorized
   QA recipient is `+918100640044`; `+919330994400` is never a customer identity — and
   `catalog_service_checkout.verified_identity:38` enforces that last rule in code, not just in
   documentation.
