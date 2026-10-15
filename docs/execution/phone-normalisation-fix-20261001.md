# Phone normalisation, session cache headers and a shared-role over-grant — 2026-10-01

Three findings from the 2026-10-01 audit of the customer sign-in and checkout path. Two are fixed
in source and tests here; the third is measured, evidenced and left for owner approval because it
is a production IAM change on a role 62 Lambda functions depend on.

| # | Finding | Status |
|---|---|---|
| 1 | `normalize_phone` prepended the India country code to an already-complete foreign number | ✅ COMPLETE in source · ⚠️ the live trigger (version 11) predates the iteration-2 separator fix **and** the iteration-3 digit-predicate fix |
| 2 | Session and OTP responses carried no `Cache-Control` | ✅ COMPLETE (two handlers, source-only — neither function exists in the account) · ✅ COMPLETE and **live** for `wecare-customer-session`, closed by another workstream |
| 3 | `wecare-digital-lambda-role` grants `UpdateItem`/`DeleteItem` on the customer session table to 62 functions | ⚠️ NEEDS CONFIRMATION — severity HIGH, **no IAM write attempted** |

> **CORRECTION, 2026-10-01 (review iteration 2).** This section previously read "**No deploy was
> performed.** No `update-function-code`, no version publish, no alias move. The live
> `wecare-customer-whatsapp-auth` and `wecare-customer-session` functions stay on their current
> code." **Every one of those claims is false**, and so was "Not pushed" below. Three functions
> were deployed and two `live` aliases moved while this task was being committed. The measured
> state is in [§ What actually reached production](#what-actually-reached-production). The
> original sentence is kept here rather than deleted, because a doc that silently corrects itself
> teaches nobody why it was wrong: the task was *scoped* source-only and the author reported the
> scope instead of measuring the account. **Nothing has been deployed or rolled back to make the
> original sentence true.**

Every AWS interaction performed *by this task* is a read. That is not the same as "nothing was
deployed" — see below.

**Phone numbers in this document are masked to the last four digits**, per the repo's logging rule.
The complete case tables live in `tests/test_phone_country_code_preservation.py`, where they are test
fixtures rather than a document that gets copied around. Where a digit *count* carries the meaning,
the count is stated instead of the digits.

---

## What actually reached production

Measured 2026-10-01 by `GetFunctionConfiguration` + `ListVersionsByFunction` + `GetAlias` on each
function, and attributed with `cloudtrail lookup-events` on `UpdateFunctionCode20150331v2`,
`PublishVersion20150331` and `UpdateAlias20150331` over 2026-10-01. Reads only; nothing in this
section was performed by this task.

### The deploys

| Time (UTC) | Function | Principal | Became |
|---|---|---|---|
| 14:16:00 | `wecare-seo-tools` | `GitHubActions-bharat-stack-seo-tools` (CI OIDC) | `$LATEST` |
| 14:34:59 | `wecare-customer-whatsapp-auth` | `iam::775261844268:user/wecare-admin` | version **11** |
| 14:35:10 | `wecare-customer-session` | `iam::775261844268:user/wecare-admin` | version **4** |
| 14:37:45 | `wecare-seo-tools` | `GitHubActions-bharat-stack-seo-tools` (CI OIDC) | `$LATEST` (current) |

### The alias moves

| Time (UTC) | Alias | From | To |
|---|---|---|---|
| 14:35:16 | `wecare-customer-session:live` | 3 | **4** |
| 14:36:08 | `wecare-customer-whatsapp-auth:live` | 10 | **11** |

### How the whatsapp-auth deploy was attributed to *this* change

Not inferred from the timestamp. `wecare-customer-whatsapp-auth` is packaged `standalone=True`, so
its zip is exactly one deterministic member (`handler.py`, `ZIP_DATE = (2026, 1, 1, 0, 0, 0)`,
`external_attr 0o644 << 16`, `ZIP_DEFLATED`). Rebuilding that zip from git and hashing it
reproduces the live digests exactly:

| Source of `handler.py` | Reconstructed `CodeSha256` | Live version |
|---|---|---|
| `456b5716~1` (pre-fix) | `EHPLBO9iwjT++WhFi/3HsZ1wWSgsTYc3+rJAaMqfnSo=` | version **10** |
| `b1833c22` (post-fix, committed) | `WmCx1537bzzjOOMrSUA+wbvbrFPY90IKIdjyIQ/KEKM=` | version **11**, `$LATEST`, `live` |

The `PublishVersion` call at 14:35:40Z carries `codeSha256 WmCx1537…` with the description
`Checkout country preservation and no-cache response guards 2026-10-01`, which names this change
outright. So the attribution rests on a byte-exact digest match *and* an operator-written
description, not on proximity in time.

`wecare-customer-session` version 4 came from the concurrent workstream's commit `6ed1426b`
("Stop the new customer-session handler leaking a cacheable CSRF token"), a parent of merge
`805c7517`. That handler calls `sessions.harden_session_headers(result['headers'])` at two return
paths — so the helper Finding 2 added here was consumed and deployed by another session, which is
why it is live despite this task never invoking it.

### Rollback targets — recorded late, which is itself the gap

`01-standing-authorization.md` gates an `A3_PRODUCTION` alias move on "rollback version captured
first". No rollback version was captured for either function, because the author believed no alias
had moved. Recorded now:

| Function | Pre-change `live` | Pre-change `CodeSha256` | Restore with |
|---|---|---|---|
| `wecare-customer-whatsapp-auth` | **10** | `EHPLBO9iwjT++WhFi/3HsZ1wWSgsTYc3+rJAaMqfnSo=` | `aws lambda update-alias --function-name wecare-customer-whatsapp-auth --name live --function-version 10 --region us-east-1` |
| `wecare-customer-session` | **3** | `IpQUxkbBSRNepaEJzZObaNGocoB7440gm1tLfEBJhho=` | `aws lambda update-alias --function-name wecare-customer-session --name live --function-version 3 --region us-east-1` |

**Moving the alias is the operative step, not `update-function-code`.** The Cognito user pool
invokes `…:function:wecare-customer-whatsapp-auth:live`, so `$LATEST` is not what signs in a
customer; version 11 began serving at 14:36:08Z when the alias moved, not at 14:34:59Z when the
code uploaded. A rollback that only reverts source changes nothing in production.

### Live blast radius, stated honestly

The trigger is **stricter** in production than it was. Two reasons that is survivable, and one that
is not comfortable:

- **Nobody is locked out.** Every existing pool user was provisioned by `normalize_phone`, which
  always emits a leading `+`. The new marker requirement therefore matches every stored
  `phone_number` attribute, and the strict path refuses only input that never reached the pool.
- **The digit floor widened, it did not narrow.** `8 <= len <= 15` replaced `10 <= len <= 15`, so
  the change admits more values rather than fewer, on a pool with
  `AdminCreateUserConfig.AllowAdminCreateUserOnly`.
- **⚠️ The coupling argument in `plan.md` §0.4 is now inverted.** That section argued the trigger
  fix and the registration-door fix "must land together", because fixing registration alone would
  make the trigger's latent defect live. What actually happened is the reverse: the **trigger is
  deployed and strict**, while the registration door is **not deployed at all** —
  `wecare-customer-registration` and `wecare-email-verification` both return
  `ResourceNotFoundException`. That is the safe half of the asymmetry (a strict destination cannot
  misdeliver), but the argument's premise no longer describes production and should not be quoted
  as if it did.

### ⏳ PENDING — the live trigger does not carry the review-iteration-2 fix

The separator-predicate correction below (`not ch.isspace()`, see
[Finding 1 › the two implementations](#two-implementations-and-why-the-duplication-is-correct)) is
**source only**. The same reconstruction method gives:

| Source | `CodeSha256` | Deployed as |
|---|---|---|
| working tree, iteration-2 fix applied | `wYKP21XLw7GL0TIZQ9jlOnfUr0Q8KijwE5bO3YZ7TM0=` | **nothing** |

So live version 11 carries the ASCII-only separator set. The exposure is narrow — it needs a
non-ASCII space between the marker and a leading zero in a stored Cognito `phone_number`, which no
current pool value has, since all were written through `normalize_phone` — but it is a real
divergence between this tree and the running function, and it is not this task's to deploy.

### The rule this establishes, for `lambda-snapstart-deploy.md`

`.github/workflows/seo-tools-deploy.yml` lists `amplify/functions/shared/lambda_utils/**` among its
`push: branches: [stack]` path filters, and its deploy job packages
`(shared/lambda_utils).glob('*.py')` before calling `update-function-code` on `wecare-seo-tools`.
That function has **no `live` alias**, so `$LATEST` serves immediately.

This change edited `lambda_utils/customer_session.py` — a top-level `*.py`, inside the glob — so
the push that carried these commits deployed it. Run `36874922132` (head_sha `805c7517`) reached
AWS at 14:16:00Z and failed only at a later live verification step, well after the deploy
step succeeded. Run `36877743960` (head_sha `e455c87e`) deployed again at 14:37:45Z and is what
`$LATEST` carries today, `CHw4cX6xTz0Kc36gW7zv5Kd6kokHStawGZwRA6NKxBU=`.

**The general rule: a task scoped "source only" stops being source-only the moment a top-level
`amplify/functions/shared/lambda_utils/*.py` edit reaches `origin/stack`**, because that path is a
push trigger on a workflow that deploys an unaliased function. Note the precise boundary — the
glob is `*.py`, not `**/*.py`, so this task's `identity/customer.py` and `identity/registration.py`
edits did *not* travel this way; only `customer_session.py` did.

`lambda-snapstart-deploy.md` documents only the manual publish-and-move path and does not mention
this CI path at all. Flagged for that file: a contributor reading it today would conclude, as this
doc originally did, that not running a deploy script means not deploying.

---

## Finding 1 — the India default was applied to numbers that already had a country code

Commit `456b5716` on `stack`, 7 files, +870/-19.

> **CORRECTION.** This line read "Not pushed." Both `456b5716` and `f8a73fb0` are ancestors of
> `origin/stack`, carried there inside merge `805c7517` ("Merge remote-tracking branch
> 'origin/stack' into stack") pushed by a concurrent session. Verified with
> `git merge-base --is-ancestor <sha> origin/stack` — both return 0. This task did not push; the
> index and the branch are shared, and another session's push took these commits with it.

### What the defect was

`amplify/functions/shared/lambda_utils/identity/customer.py::normalize_phone` stripped every
non-digit — including the `+` — before it did any country-code detection. `_INDIAN_MOBILE_RE`
(`^[6-9]\d{9}$`) then matched any 10-digit string starting 6-9, and `DEFAULT_COUNTRY_CODE = '91'`
was prepended to it. A complete Singapore, New Zealand, Thai or 10-digit UAE number is exactly that
shape.

The consequence is not a cosmetic one. Uniqueness is enforced on the normalised value, so:

1. the OTP went to an unrelated Indian subscriber who never asked for it;
2. the real customer could never sign in, because the number they own was never the number stored;
3. the **wrong identity was reserved** — a `CUS_<ULID>` row and a Cognito username keyed to a
   stranger's number.

It was reachable from shipped UI: `src/lib/dialCodes.ts` offers +65 and ten other codes that each
have a digit count at which the corruption fires.

### Reproduction, before and after (masked)

Measured with `./.venv/bin/python`, `amplify/functions/shared` on the path.

| Input (masked) | Total digits | `normalize_phone` (legacy) | `normalize_phone_preserving_country` (new) |
|---|---:|---|---|
| `+65 ···4567` Singapore | 10 | `+91` + all 10 → **wrong country** | `+65` preserved ✅ |
| `0065 ···4567` Singapore via `00` | 10 | `+91` + all 10 → **wrong country** | `+65` preserved ✅ |
| `+65(····)4567` with separators | 10 | **wrong country** | `+65` preserved ✅ |
| `+64 ···1234` New Zealand | 10 | **wrong country** | `+64` preserved ✅ |
| `+66 ···3456` Thailand | 10 | **wrong country** | `+66` preserved ✅ |
| `+971 ···2345` UAE, 10-digit form | 10 | **wrong country** | `+971` preserved ✅ |
| `+971 ···4567` UAE, 12-digit form | 12 | correct (misses the trap) | correct |
| `+1 ···2671` US | 11 | correct | correct |
| `+44 ···3456` UK | 12 | correct | correct |
| `+91 ···4400` India | 12 | correct | correct |
| `+91 0···4400` India with a trunk zero | 13 | **stuck trunk zero**, 13 digits out | one zero stripped, 12 digits ✅ |
| `0091 ···4400` India via `00` | 12 | correct | correct |
| bare national digits, no code | 10 | silently assumed Indian | **rejected** (`MissingCountryCode`) |
| `0093···4400` read as `00` + country `93` | 10 | assumed Indian | `+93` preserved — **not** `+91` |

The rule is exact: the legacy function corrupts when `len(country_code + national) == 10` and the
first digit is 6-9. `+971` is therefore not "safe"; only its 12-digit spelling is.

Two rows that the plan did not list and are worth recording:

- `normalize_phone` on an Indian number written with a trunk zero leaves the zero stuck, producing
  a 13-digit value. The strict function strips exactly one. Both behaviours are frozen in the
  snapshot test.
- `00` is read as the international prefix per E.123/E.164 even when what follows looks Indian, so
  `0093…` resolves to country code **93**, not 91. Deliberate: inferring otherwise is the defect
  wearing a different coat.

### The fix: additive, never a modification

`normalize_phone` is **byte-identical**. The diff for `customer.py` is `+120 / -0` — zero deleted
lines, which is the strongest available form of "purely additive". It still has eight non-entry-point
callers and its lenient behaviour is correct for them.

Added beside it:

```
class MissingCountryCode(InvalidPhoneNumber)        # -> InvalidPhoneNumber -> ValueError
def normalize_phone_preserving_country(raw) -> str  # returns '+<digits>'
```

Both exported from `__all__`. There is deliberately **no** `default_country` keyword: accepting one
would reopen the inference the function exists to remove.

The order of operations is the whole fix. The `+` / `00` marker decision happens on the trimmed
original text, after a separator-tolerant compaction (`[\s\-().]` only, which matches neither `+`
nor a digit) and **before** any `\D` strip. A wrapper around `normalize_phone` cannot work: by the
time it sees a result, the marker is gone and `0065…` has already been collapsed. `MissingCountryCode`
subclassing `InvalidPhoneNumber` is load-bearing rather than tidy — the existing
`except customer_identity.InvalidPhoneNumber` clauses at the call sites absorb the new rejection with
zero control-flow change.

Validation rules: no leading zero in the remainder (no country code starts with zero); `8 <= digits
<= 15`; a trunk zero stripped **only** for `91`. Every other country gets no trunk handling, because
we do not know their rules. Documented consequence: a UK number written with its trunk zero comes
out with the zero intact and the provider rejects it — a visible failure, which is strictly better
than a silent delivery to a stranger.

### Two implementations, and why the duplication is correct

`amplify/functions/auth/customer-whatsapp-auth/handler.py::_normalise_phone` is an independently
written second copy of the same defect, reached by the sign-in OTP destination, the masked
destination shown to the browser, and the per-phone throttle key.

It **cannot** import the fix. `scripts/deploy_all_lambdas.py:174` declares that function
`standalone=True` and the deployed function has `Layers: null`, so `lambda_utils` is not in its
package. Adding an import would mean a packaging change to a live Cognito trigger. It was therefore
fixed in place, and a drift-agreement test asserts
`trigger._normalise_phone(row) == normalize_phone_preserving_country(row).lstrip('+')` for every row
of the table above. The handler still imports nothing from `lambda_utils`, asserted by an AST test.

The two fixes are **coupled**. The trigger's bug is latent today only because
`_provision_login` writes the already-corrupted value as the Cognito username, so the pool cannot
currently hold a foreign number. Fixing registration alone would make it live.

One deliberate divergence from the plan at that site: the trigger's length bound was widened from
`10 <= digits <= 15` to `8 <= digits <= 15` to match the canonical implementation. A tighter bound at
sign-in than at registration is the same class of harm — a customer could register with an 8 or
9 digit E.164 number and then never be able to sign in. The pool is `AllowAdminCreateUserOnly`, so a
wider accept opens nothing.

#### Review iteration 2 — the drift the drift test could not see

The duplication was reproduced faithfully in shape but not in predicate. The canonical function
compacts separators with `re.sub(r"[\s\-().]", "", text)`; the in-place copy spelled it
`"".join(ch for ch in text if ch not in " \t-().")`. Those are not the same test — `\s` matches
Unicode whitespace and an explicit ASCII set does not — and the drift-agreement test could not
detect it, because `.strip()` runs first and the trailing `isdigit()` filter discards whatever the
compaction left behind. Every row of the shared table therefore agreed by coincidence.

The divergence is only observable when the surviving character changes a *branch* decision, and
there is exactly one such branch: the leading-zero refusal. Measured:

| Input | Canonical | Trigger, ASCII-only set |
|---|---|---|
| `+\u00a00065 …` | refused (`a country code does not start with zero`) | **accepted**, leading zeros intact |
| `+\u00a00…` (Indian spelling) | refused | **accepted**, leading zero intact |

The accepted value would have been the OTP destination. Fixed by making the predicate the same
predicate: `not ch.isspace() and ch not in "-()."`, which agrees with `[\s\-().]` on every one of
the 0x110000 codepoints — verified exhaustively rather than argued. Pinned by
`test_the_two_implementations_agree_on_refusal_too`, which asserts agreement on **refusal** as well
as on output, because agreement on accepted rows was what hid this.

Two Unicode-space rows were also added to the shared table. They pin that a non-ASCII separator is
tolerated at all; they do **not** catch the predicate divergence, and the table says so, so nobody
mistakes them for the guard.

⏳ This fix is source-only. See [§ What actually reached production](#what-actually-reached-production)
— live version 11 carries the ASCII-only set.

#### Review iteration 3 — the *second* predicate, and non-ASCII digits at the identity door

Iteration 2 fixed the separator predicate and verified it exhaustively. It left the **digit**
predicate as two spellings that agreed only by coincidence, which is the same defect class one
line further down:

| | Canonical `customer.py` | Trigger `handler.py` |
|---|---|---|
| Before | `re.sub(r"\D", "", rest)` | `"".join(ch for ch in rest if ch.isdigit())` |
| After | `re.sub(r"[^0-9]", "", rest)` | `"".join(ch for ch in rest if ch in "0123456789")` |

`re`'s `\d` matches Unicode category Nd only; `str.isdigit()` additionally matches anything with
`Numeric_Type=Digit`. The two therefore disagree on **128 codepoints**, beginning at U+00B2
SUPERSCRIPT TWO, U+00B3, U+00B9 and the Ethiopic numerals from U+1369 — measured by enumerating all
0x110000 codepoints, not argued. Measured against both live implementations before the fix:

| Input | Canonical | Trigger |
|---|---|---|
Masked to the last four per the rule stated at the top of this document. The marker character's
POSITION is what carries the meaning in each row, so it is kept exactly where it occurred; the
preceding digits are not. The unmasked vectors are fixtures in
`tests/test_phone_country_code_preservation.py`, which is where they belong.

| Input | Canonical | Trigger |
|---|---|---|
| `+65<U+00B2>•••••4567` | `+65•••••4567` | **`65<U+00B2>•••••4567`** |
| `+91•••••••4400<U+00B2>` | `+91•••••••4400` | **`91•••••••4400<U+00B2>`** |
| `+91<U+00B2>0••••••4400` | `+91•••••••4400` | **`91<U+00B2>0••••••4400`** |

The trigger's docstring promises a digits-only E.164 destination and was returning a string
containing a non-digit. That value is the `_consume_send_budget` throttle key, the WhatsApp send
`to` field, and the masked destination shown to the browser — so the consequences are a wrong
throttle bucket and a malformed send target. The drift-agreement test could not see it because every
`PRESERVED` row was ASCII and none of the three refusal rows was numeric-but-not-decimal. The table's
own comment named the `isdigit()` filter as the thing that hides divergences while leaving that
filter unverified.

The same change closes a second, independent problem in the canonical function, which is the more
serious of the two. `\D` does not strip a **non-ASCII decimal** digit — Arabic-Indic U+0660-U+0669 is
category Nd — so those characters survived the strip, passed the 8..15 bound that counted them, and
were returned inside the `+`-prefixed result. Measured: `+91••••••440<U+0660>` was returned verbatim,
and an all-Arabic-Indic input returned itself. `registration.complete` writes `normalizedPhone` and
the Cognito `Username` from this value and enforces uniqueness on it, so that string and the
same number ending `4400` were **two distinct identities that read identically to a human** — the same
permanent wrong-identity reservation as the headline defect, reached through a different door. A
direct API caller is the reachable path.

Both are fixed by one change, which is why it was taken as one: `[^0-9]` and `ch in "0123456789"` are
the same predicate **by construction** rather than by argument, verified at 0 disagreements across all
0x110000 codepoints, and ASCII-only simultaneously removes the non-ASCII-digit acceptance.

Pinned by: three numeric-but-not-decimal rows added to the shared `PRESERVED` table (so the drift
test fails the moment the predicates separate again); two all-non-ASCII-digit rows added to
`test_the_two_implementations_agree_on_refusal_too`; and a new
`test_no_non_ascii_digit_survives_into_the_reserved_identity`, which asserts the **shape** of the
output rather than one codepoint, because the defect is "a non-digit reached the identity" and not
"this particular character did".

`normalize_phone` was **not** touched — verified byte-identical to `HEAD` by AST extraction and
sha256, and `LEGACY_SNAPSHOT` is unchanged. It keeps `\D` and therefore keeps this behaviour; that is
deliberate, since its snapshot is frozen and its eight callers were not audited for it. The lenient
function is not a customer entry point.

One collateral test change: `test_the_marker_branch_precedes_every_digit_strip` located the strip by
the literal `\D` and would have tripped its own "expected a digit strip somewhere in the function"
assertion. It now matches either spelling, enumerated explicitly rather than loosened to "any
`re.sub`" — a looser match would also catch the separator compaction, which runs *before* the marker
branch by design, inverting the assertion so that it passes on a broken function.

⏳ Source-only, like iteration 2. Live version 11 carries neither predicate fix.

### Entry points wired — and the ones deliberately not

Four call sites, all customer-facing doors:

| Wired | Why |
|---|---|
| `identity/registration.py::begin` | where the OTP destination is chosen |
| `identity/registration.py::complete` | where the identity is reserved |
| `auth/customer-whatsapp-auth/handler.py::_normalise_phone` | the sign-in OTP destination (second copy) |
| `auth/email-verification/handler.py` throttle axis | the raw phone was the throttle key |

The email-verification change is a throttle-key normalisation only. One number written spaced and
the same number written unspaced previously got two separate buckets, so respacing bought a fresh
budget — a free evasion of the per-phone limit. It
**never** returns 400 on phone shape — the phone is optional on that endpoint, so an unparseable
value falls back to the normalised email as the throttle subject.

Deliberately untouched: `build_customer`, `validation.py::normalize_phone` and its five messaging
callers, `outbound-whatsapp::_normalize_phone_number`, `sinch_rcs::_normalize_phone`,
`ecommerce/checkout`, `ecommerce/customer_cart`, `ecommerce/initiation`, `identity/address.py`,
`core/crm`. These handle numbers that are already stored or already E.164, or are operator-facing
rather than customer-facing; tightening them would reject existing data without fixing any
misdelivery.

### Contract change at the registration door — flagged, not discovered later

**A bare national number is now refused at the registration and sign-in doors.** This is a behaviour
change, taken deliberately for three checkable reasons: the owner handoff asks for it;
`src/components/PhoneField.tsx` always emits a dial code, so no real UI state produces a bare
number — only a direct API caller does; and the approved copy for the state already exists in
`src/lib/signInMessages.ts::MISSING_CODE`. No `src/` file was edited.

Test coverage moved rather than dropped: the one-counter parametrize kept its three explicit-code
spellings and lost the two bare ones, and a new sibling test asserts those two bare spellings now
return `INVALID_PHONE`, consume no throttle budget, send nothing and write nothing. A matching
HTTP-level test was added at the handler.

---

## Finding 2 — a session or OTP response could be cached and replayed to another customer

### The defect

`lambda_utils/response.py::cors_headers` sets `Content-Type` and three CORS headers and **no**
`Cache-Control`. These responses do not reach the browser directly either: the Amplify `/api/<*>`
rewrite serves them with status 200, so a shared cache sits in front of them.

`customer_session.SessionView.csrf_token` is a per-session secret that a handler returns in a
response **body**. A cache that stored one customer's session response and replayed it to another
would hand over that customer's CSRF token — and that token is precisely what `build_set_cookie`'s
deliberate `SameSite=Lax` choice relies on to guard the mutations Lax still permits. Losing its
secrecy does not weaken the defence, it removes it.

### Fix sites (all owned, all source-only)

| Site | Change |
|---|---|
| `lambda_utils/customer_session.py` | `NO_STORE_HEADERS = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}` and `harden_session_headers(headers=None)`, both exported from `__all__`, in the existing cookie-assembly section |
| `auth/customer-registration/handler.py` | a local `_no_store()` wrapper applied to **every** return path: `_request`, `_verify`, the handler-level 500, the 502 `send_failed`, and the OPTIONS preflight |
| `auth/email-verification/handler.py` | the same, on all twelve return paths including the `otp_throttle.throttled_response` 429, which is built by `otp_throttle` rather than `cors_response` |

`Pragma: no-cache` is included because that is the pair the repo already emits at
`edge/get-miss-redirect/handler.py:83`; `ai/mcp/handler.py:568` and `core/site-language/handler.py:198`
use `no-store` alone. The stricter existing pattern was copied.

**`lambda_utils/response.py` is unmodified, deliberately.** `core/contacts/handler.py:285` removed
`Cache-Control` there on purpose, so a blanket header in the shared builder would override a
considered decision in an unrelated handler. The contract lives beside the session it protects and
each owning handler opts in. A test pins this: `response.py` must contain no `Cache-Control`.

### Cross-workstream precondition — checked, holds

This change adds **response** headers only. It does not enable `assert_csrf` on any route and adds
no required request header, so `src/pages/cart.tsx` (~line 149) and `src/pages/checkout/status.tsx`
(~line 159), which gate on `getSession()` and send no CSRF header, cannot break. No `src/` file was
modified; `npx tsc --noEmit` is clean and the three UI contract suites pass unchanged.

### ✅ COMPLETE — the deployed `wecare-customer-session` handler (reported here, fixed elsewhere)

Reported as `⏳ PENDING` when this doc was written; closed by another workstream during the
cross-seam pass. The original reasoning is kept below because it is what made the handover
actionable, with the resolution recorded after it.

`wecare-customer-session` is live on its own role `wecare-customer-sessions-Role-An9RPVcLOdkj`.
**Its handler source does not exist in this tree** — another workstream owns it — so it could not be
fixed here. It is the one handler that will actually return a `csrfToken`, which makes it the highest-
value site for this header.

Exact change required, for whoever owns it:

```python
from lambda_utils.customer_session import harden_session_headers
...
response["headers"] = harden_session_headers(response.get("headers") or {})
```

applied to every return path, including the sign-out and the 503 refresh-unavailable paths. A
forward-looking tripwire in `tests/test_session_response_is_not_cacheable.py` fails the build if any
`amplify/functions/**/handler.py` ever returns a body with a `csrfToken` key without calling
`harden_session_headers`. It matches nothing today, and it has a positive control so it cannot pass
vacuously.

#### ✅ RESOLVED by another workstream, and the tripwire is no longer vacuous

Recorded during the cross-seam pass, because this was the one open item here that depended on
somebody else's file. The sequence, which is worth keeping straight:

1. When this section was written the source genuinely was absent — `git cat-file -e
   f8a73fb0:amplify/functions/ecommerce/customer-session/handler.py` does not resolve. The premise
   was correct, not a failure to look.
2. It arrived afterwards in `722fa300`, at `amplify/functions/ecommerce/customer-session/` — under
   `ecommerce/`, not the `auth/` directory the other two OTP doors live in, which is why a search
   for it by sibling path would have missed it even a moment later.
3. `6ed1426b` then routed **both** of its response sites through
   `customer_session.harden_session_headers`, which is exactly the call named above, imported as
   `sessions`.

So the `csrfToken` tripwire now has a real subject rather than only its positive control: the one
handler that actually returns a token is the one now covered. Nothing in this task was changed to
make that true.

> **CORRECTION.** This paragraph ended "and nothing here is deployed — … that handler, like the two
> in this change, keeps serving its old responses until a version is published and the `live` alias
> moves." The mechanism is right and the conclusion is wrong: that is precisely what happened, and
> it has already happened. `wecare-customer-session` version 4 was published at 14:35:14Z and
> `live` moved from 3 to 4 at 14:35:16Z, so the hardened responses **are** what production serves.
> See [§ What actually reached production](#what-actually-reached-production). The two OTP doors
> remain undeployed for a different reason — `wecare-customer-registration` and
> `wecare-email-verification` do not exist in the account at all.

---

## Finding 3 — ⚠️ NEEDS CONFIRMATION (severity HIGH) — shared-role over-grant on the session table

**No IAM write was attempted.** The three commands below are reads. No `put-role-policy`, no
`create-policy`, no `delete-role-policy`.

### Evidence

| Measurement | Result |
|---|---|
| Table | `stack-wecare-digital-CustomerSessionsTable`, **ACTIVE**, HASH `sidHash` |
| Granting policy | inline `wecare-digital-lambda-permissions` on `wecare-digital-lambda-role`, Sid `DynamoDB` |
| Actions granted | GetItem, PutItem, **UpdateItem**, **DeleteItem**, Query, Scan, BatchGetItem, BatchWriteItem, DescribeTable |
| Resource | `arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-*` and `…/index/*` |
| Condition | **none** |
| Functions on that role | **62 of 68** |
| Functions referencing the session table | **0** of those 62 |

### Command output, re-measured 2026-10-01 (reads only)

Command 1 — the grant on the shared role:

```
dynamodb:UpdateItem  allowed  role_wecare-digital-lambda-role_wecare-digital-lambda-permissions
dynamodb:DeleteItem  allowed  role_wecare-digital-lambda-role_wecare-digital-lambda-permissions
dynamodb:PutItem     allowed  role_wecare-digital-lambda-role_wecare-digital-lambda-permissions
dynamodb:GetItem     allowed  role_wecare-digital-lambda-role_wecare-digital-lambda-permissions
```

Command 2 — the legitimate custodian's own role, confirming it does not depend on the shared grant:

```
dynamodb:UpdateItem  allowed  role_wecare-customer-sessions-Role-An9RPVcLOdkj_CustomerSessionCustody
dynamodb:DeleteItem  allowed  role_wecare-customer-sessions-Role-An9RPVcLOdkj_CustomerSessionCustody
dynamodb:PutItem     allowed  role_wecare-customer-sessions-Role-An9RPVcLOdkj_CustomerSessionCustody
dynamodb:GetItem     allowed  role_wecare-customer-sessions-Role-An9RPVcLOdkj_CustomerSessionCustody
```

That is the decisive point: `wecare-customer-session` is separately and sufficiently granted by
`CustomerSessionCustody` on its own role, so removing the shared role's path to this table takes
nothing away from the function that legitimately owns the data.

Command 3 — the statement text, `aws iam get-role-policy --role-name wecare-digital-lambda-role
--policy-name wecare-digital-lambda-permissions`, Sid `DynamoDB`, verbatim:

```json
{
  "Sid": "DynamoDB",
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "dynamodb:BatchGetItem",
    "dynamodb:BatchWriteItem",
    "dynamodb:DescribeTable"
  ],
  "Resource": [
    "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-*",
    "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-*/index/*"
  ]
}
```

The policy's other statements, untouched and listed for completeness: `CloudWatchLogs`, `S3Access`,
`WhatsApp`, `PinpointSMSVoice`, `SES`, `SQS`, `SNS`, `Bedrock`, `SecretsManager`,
`CloudWatchMetrics`, `Polly`, `HealthAndAdvisor`.

### The item for approval

- **Impact.** 62 functions can delete or rewrite any customer session row. Concretely, a bug or a
  compromise in any one of them could revoke every remembered login, or alter `absoluteExpiresAt`
  and extend a session past the 30-day cap the session module enforces in code — the one rule the
  requirement is explicit about. Session rows hold no token (only a Secrets Manager reference), so
  this is an integrity and availability exposure, not a credential disclosure.
- **Current state.** `allowed` for all four mutating actions from the shared role, with no condition.
- **Desired state.** Only `wecare-customer-sessions-Role-An9RPVcLOdkj` can mutate that table.
- **Measured blast radius of the change: zero.** None of the 62 functions references the table.
- **Recommended option — a NEW inline policy containing an explicit `Deny`.** An explicit Deny
  overrides any Allow, leaves the existing `DynamoDB` statement and the ~61 other tables untouched,
  and is removable in one call.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyCustomerSessionMutationFromSharedRole",
      "Effect": "Deny",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-CustomerSessionsTable",
        "arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-CustomerSessionsTable/index/*"
      ]
    }
  ]
}
```

- **Rejected alternative.** Narrowing the existing `stack-wecare-digital-*` wildcard to an explicit
  table list. It changes the grant for all 62 functions in order to fix one table, and any table
  omitted from the list breaks its function silently at runtime. Not recommended.
- **Rollback.** `aws iam delete-role-policy --role-name wecare-digital-lambda-role --policy-name
  wecare-digital-session-table-deny`. One call, immediate, no data effect.
- **Verification after approval** — the same read used as evidence above, expecting
  `explicitDeny` on the three mutating actions and `allowed` unchanged on `GetItem`:

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::775261844268:role/wecare-digital-lambda-role \
  --action-names dynamodb:UpdateItem dynamodb:DeleteItem dynamodb:PutItem dynamodb:GetItem \
  --resource-arns arn:aws:dynamodb:us-east-1:775261844268:table/stack-wecare-digital-CustomerSessionsTable \
  --output json
```

Awaiting an explicit owner decision. **Not applied.**

---

## Verification

```
./.venv/bin/python -m pytest tests/test_phone_country_code_preservation.py -q     98 passed
./.venv/bin/python -m pytest tests/test_session_response_is_not_cacheable.py -q   21 passed
./.venv/bin/python -m pytest tests/ -q                            5935 passed, 1 skipped
npx tsc --noEmit                                                  clean
npx vitest run SignInMessages / AccountSignIn / CartCheckout       3 files, 42 tests passed
git diff --stat -- src/ amplify/.../lambda_utils/response.py       empty
```

Baseline before this work was 5875 Python tests passing; the measured 93-test
(`test_customer_identity` + `test_customer_session`) group is unchanged.

**Read the full-suite and vitest totals as dated, not as this change's arithmetic.** The two
findings landed as separate commits (`456b5716`, `f8a73fb0`) into a working tree shared with
several live sessions, so the totals move with their work as well as ours: the figures above were
measured after the cross-seam pass below, by which point concurrent workstreams had added tests of
their own. During that pass the suite twice reported transient failures in
`test_url_host_routing_rules.py`, `test_provision_checkout_contract.py`,
`test_legacy_redirect_rollback_snapshot.py` and `test_checkout_package_completeness.py` — each
passed in isolation moments later, and all four belong to other workstreams and import nothing
this change touches. That is a half-written file caught mid-run, not a regression. The counts
attributable here are the two per-file figures, and they are exact.

### Cross-seam verification, after both findings had landed

The two commits were written independently, so the seams between them were checked separately
rather than assumed:

| Seam | Result |
|---|---|
| `normalize_phone` still byte-identical across **both** commits | ✅ `+120 / -0` for `customer.py`, zero deleted lines |
| Exactly four call sites moved to the strict normaliser | ✅ `registration.begin`, `registration.complete`, the trigger's `_normalise_phone`, the email-verification throttle axis. `build_customer`, `validation.py::normalize_phone` and its five messaging callers, `sinch_rcs`, `outbound-whatsapp` and `core/contacts` all still call the legacy function |
| The standalone trigger still imports nothing from `lambda_utils` | ✅ only `json`, `os`, `secrets`, `time`, `boto3`; the three `lambda_utils` mentions are a comment and a docstring |
| The two implementations agree on all 17 rows | ✅ re-measured directly, 0 drift |
| `email-verification/handler.py`, the one file **both** commits changed | ✅ the normalised throttle subject and the `_no_store` wrapper coexist; every one of its 12 returns is wrapped, including `otp_throttle.throttled_response`, which does not go through `cors_response` |
| **Packaging.** Both header-fix handlers newly import `customer_session`; neither is `standalone`, so `build_zip` copies the whole `lambda_utils` tree | ✅ proved by staging the exact member set into a temp dir and importing `handler.py` with only that directory on `sys.path` — 114 modules, both import clean. `customer_session` pulls in no `boto3` client, reads no secret, and reads env only with defaults, so the new import adds no init-time dependency |
| Header merge keeps what it was handed | ✅ `Retry-After` survives on the 429 and `Content-Type` on every response, while `no-store` overrides a weaker `max-age` |
| `src/` and `response.py` untouched | ✅ `git diff --stat` empty for both. `src/pages/404.tsx` moved in `5114ae70`, another workstream's commit, not in either commit here |
| No logging expression in any touched file carries a phone, an OTP or a secret | ✅ every site logs `type(exc).__name__`, a count, a boolean or an event name; `customer.py` logs nothing at all |

One gap was found and closed. The log-safety AST guard in
`tests/test_phone_country_code_preservation.py` enumerates its files by hand, and the list was
written during Finding 1 — before Finding 2 edited `customer-registration/handler.py` and
`customer_session.py`. Two of the six files this task changed were therefore outside the guard
meant to cover the task's own edits. Both already satisfied it, so nothing was leaking; the fix is
that the **next** edit to either is now checked rather than trusted. The parametrize ids were also
disambiguated, because three of the six sources are named `handler.py` and the failure message
said only `handler.py`. The detector was re-confirmed to fire on a deliberate violation rather
than passing vacuously.

| Gate | Result |
|---|---|
| Deploy **by this task** | ➖ NOT REQUIRED — out of scope; no `update-function-code`, `publish-version` or `update-alias` was called from here |
| Deploy **that happened anyway** | ⚠️ COMPLETE WITH IMPROVEMENTS — 3 functions deployed, 2 `live` aliases moved, by `user/wecare-admin` and by CI, measured in [§ What actually reached production](#what-actually-reached-production). Rollback targets recorded **after** the fact, which breaches the `A3_PRODUCTION` "rollback version captured first" condition |
| Live trigger matches this tree | ❌ NO — version 11 predates the iteration-2 separator fix and the iteration-3 digit-predicate fix. Source-only, not deployed |
| AWS writes **by this task** | ➖ NOT REQUIRED — reads only, nothing mutated |
| Secrets Manager reads | ➖ NOT REQUIRED — none performed, in any spelling |
| `src/` modified | ➖ NOT REQUIRED — none |
| Finding 3 applied | ⚠️ NEEDS CONFIRMATION — deliberately not applied |
| Cross-seam verification between the two commits | ✅ COMPLETE — see the table above |
| `wecare-customer-session` no-store headers | ✅ COMPLETE — closed by another workstream in `6ed1426b`, and **live** on version 4 since 14:35:16Z |
| Pushed | ✅ `456b5716` and `f8a73fb0` are ancestors of `origin/stack` via merge `805c7517`, pushed by a concurrent session — not by this task |

**Overall: ⚠️ COMPLETE WITH IMPROVEMENTS.** Findings 1 and 2 are fixed in source and pinned by
tests, and the seams between the two commits that delivered them are verified. **One** item remains
outside this task's authority: the Finding 3 IAM change, which needs an owner decision. The
`wecare-customer-session` handler, reported here as pending, has since been fixed by the workstream
that owns it using the call this doc named.

> **CORRECTION.** This paragraph read "Nothing above is deployed. That is the one thing not to read
> as finished: under `lambda-snapstart-deploy.md` a published version and an alias move are what
> make a payments- or auth-path change live, and neither has happened, so all three handlers
> continue to serve their previous code." Both the publish and the alias move **had** happened, for
> two of the three, before this was written.

The thing not to read as finished is the inverse of what this section originally claimed. Under
`lambda-snapstart-deploy.md` a published version plus an alias move is what makes an auth-path
change live, and for `wecare-customer-whatsapp-auth` (version 11, alias moved 14:36:08Z) and
`wecare-customer-session` (version 4, alias moved 14:35:16Z) both steps are done — so those two are
live, with their rollback targets recorded only retrospectively. What is **not** finished:

- the iteration-2 separator fix and the iteration-3 digit-predicate fix on the trigger are both
  source-only; live version 11 carries neither;
- `wecare-customer-registration` and `wecare-email-verification` are not deployed because they do
  not exist in the account, so the Finding 2 header work on those two handlers is source-only too;
- Finding 3 is still an owner decision.

## Related

- `.agents/tasks/phone-normalisation-fix-20261001/plan.md` — the design, the entry-point
  justification and the full test list
- `tests/test_phone_country_code_preservation.py` — the complete case tables, the frozen legacy
  snapshot and the drift-agreement test
- `tests/test_session_response_is_not_cacheable.py` — the per-return-path guard and the `csrfToken`
  tripwire
- `.kiro/steering/lambda-snapstart-deploy.md` — the publish-and-move rule that makes an auth-path
  change live. Flagged above: it documents only the manual path and omits the
  `seo-tools-deploy.yml` push trigger on `amplify/functions/shared/lambda_utils/**`, which deploys
  an unaliased function straight from a push to `stack`
- `docs/execution/change-authority-matrix.md` — where the alias moves recorded above belong as
  `A3_PRODUCTION` entries
