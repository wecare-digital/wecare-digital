# CodeQL triage: `py/clear-text-logging-sensitive-data`

Rule 28 accepts an open high-severity finding as closed when it is **either remediated or
formally triaged with evidence**. This repository carried **223 open alerts with zero
triaged**, which is a failing release gate, and the size of the pile was itself the
problem: it was large enough that nobody read it, and the things worth reading were inside
it.

**Current state: 14 open, all this rule.** 223 → 52 → 26 → 20 → 14. The most recent pass is
§4e, and it is the one to read first if you are picking this up: it found a real disclosure
that an earlier pass had signed off, in a helper the triage tool trusted by name.

This document records what was found, what was fixed, and what each remaining dismissal
rests on. It exists because a dismissal without a reason is indistinguishable from a
dismissal without a thought.

---

## 1. What was in the pile

Of ~203 alerts on this one rule, roughly 155 were `phoneNumberId`, `metaPhoneId` and
`phoneHash` — Meta business identifiers this repository's own documentation publishes, and
SHA-256 digests. Genuinely safe, genuinely noise.

Buried in that noise, and found by reading rather than by grepping:

| Finding | Sites | Why it was invisible |
|---|---:|---|
| Full E.164 numbers in logger dicts | ~30 | Under keys like `senderPhone`, so *findable* — but drowned in 155 safe alerts |
| Customer names and WhatsApp usernames | 5 | Same |
| **WhatsApp Flow tokens** | 4 | The key is `flowToken`. A Flow token is `{prefix}-{uuid4}-waba-{n}-ph-{phone}` and `flows/common.get_phone_from_token` splits on `-ph-`, so the token **is** the phone number. No phone-shaped-field-name check could see it |
| **`contactId`** | 85 | The field that looked safest in the tree. `_deterministic_contact_id` mints it as `f'wa{digits}'`, so a WhatsApp-originated contact id is the customer's digits behind a two-character prefix. Confirmed against the live table without reading a value: all 6 rows match the character-class pattern `Ax999999999999` |
| Whole Meta request bodies | 5 | `'payload': message_payload` carries an unmasked `to` and the message content. One dict masked `recipientPhone` **and** `normalizedPhone` on consecutive lines and then dumped the entire payload two lines later |
| The customer's inbound message text | 1 | `'content': content_lower` on `pay_keyword_triggered` |
| The flow response echoed back to Meta | 1 | Truncated strings to 200 chars, which does not remove a name or an address. Its own `except` branch already logged keys only |
| A customer-written request subject | 1 | Free text |
| Raw `str(e)` where taint reaches it | 14 | Steering: log `type(e).__name__` unless our own code built the message |

**About 146 real disclosures, all remediated — not dismissed.** Three gates in
`tests/test_log_phone_masking.py` now fail the build if any class returns, and the
`mask_flow_token` / `mask_contact_id` helpers mask exactly the disclosing form and pass
the opaque form through untouched.

## 2. The mistakes made while fixing it, because they are the reusable part

**A dict entry plays three different roles.** `'to': phone` is a log line, the Meta request
body, or the stored CRM record, and only the first should be masked. Masking the second
breaks sending; masking the third destroys the record the CRM exists to keep.

Two regex heuristics got this wrong before an AST pass got it right:

1. *"Wrap any line matching the pattern"* — hit **11** payload and item dicts.
2. *"Walk back to the nearest `logger.`"* — hit **20** more, including
   `_store_call_log({...})` sitting a few lines below an unrelated `logger.info`. That
   masked the call log's own numbers and dropped the caller's name from it.
   `tests/test_calling.py::test_bsuid_extraction_from_contacts` is what caught it.

All 31 were reverted. The classifier now walks the AST and asks which call actually
consumes each dict, seeing through `json.dumps` because `json.dumps` into
`lambda_client.invoke` is a payload and into `logger.info` is a log.

**A slice is not an index.** `_is_sanitised` treated every `ast.Subscript` as safe, because
`phone[-4:]` truncates. But `contact['id']` is a dict lookup returning the whole value, and
conflating the two hid exactly two raw contact ids.

**An error message can contain the thing you are testing for.** Checking whether an API
existed by grepping command output reported three deleted HTTP APIs as present, because
`NotFoundException: Invalid API identifier specified 775261844268:ppq3shpmbd` contains the
id. Exit codes, not output matching.

## 3. What each dismissal rests on

`scripts/triage_codeql_logging.py --report` reproduces the classification; `--apply`
performs the dismissals.

The alert location points at the whole `json.dumps({...})` call, not at the element CodeQL
considers sensitive, and the REST API does not expose the code flow. So rather than
guessing which element was meant, the script enumerates **every** key/value pair and
classifies each one. **An alert is dismissed only when no element can carry identifying
data** — which is a stronger claim than matching CodeQL's choice would have been.

| Classification | Meaning | Example |
|---|---|---|
| `CONST` | A literal in the source | `'event': 'message_stored'` |
| `SANITISED:<fn>` | Through a masking or reducing helper | `mask_phone(...)`, `bool(...)`, `len(...)` |
| `TYPE_NAME` | `type(e).__name__` | exception type, not text |
| `SLICE` | A truncating slice | `phone[-4:]` |
| `OPAQUE_ID` | An identifier we or a provider mint | `requestId`, `wamid`, `phoneNumberId`, `phoneHash` |
| `REVIEWED` | Judged one group at a time, reason in the source | media ids, DLT template ids, outcome flags |
| `AUDIT_RETAINED` | Deliberately kept | the **staff** Cognito username in `middleware.py` — logging who performed an administrative action is an audit requirement, so removing it would be the wrong remediation |
| `NUMERIC` / `ENUM` / `BOOL_KEY` | A count, a closed set, a predicate | `statusCode`, `direction`, `hasMedia` |
| `REDUCED:<fn>` / `DERIVED:<fn>` | For `print()` sites in `scripts/` | `len(v)`, `fingerprint(v)` |

### The 69 alerts in `scripts/`

Developer-run tooling that uses `print()`, so there is no dict. CodeQL flags them because
names like `SECRET_ID` and `args.secret` look sensitive — they hold secret **identifiers**,
and the value-bearing lines emit a length, a label or an irreversible `sha256[:12]`, which
is precisely the by-reference reporting `.kiro/steering/secret-handling.md` (retired; now .kiro/steering/00-common.md) prescribes:
*provider, credential present YES/NO, field count, fingerprint, length*.

All 69 were read. Exactly one interpolated something that could have been a value —
`verify_secret_consumption.py`'s JSON `leaks` list — and reading it shows `what` is a label
from the known-credential map and `fp` is `digest(value)`. No value is printed.

### Staleness, and why the guard is per-file

An alert records the `commit_sha` it was analysed on. Line numbers move, and this work
moved thousands of them, so resolving an old `start_line` against the current file can land
on a different dict and "prove" the wrong thing safe.

The first guard required `commit_sha == HEAD`. Correct in principle, unreachable in
practice: three sessions were pushing every few minutes, so CodeQL was always a commit or
two behind and the check never passed. The guard is now per-**file** — the file the alert
points into must be unchanged between the analysed commit and HEAD — and it **fails
closed**, treating an unknown commit or a locally-modified file as stale.

## 4. What is NOT dismissed

Alerts stay open because the classifier could not prove them, not because they are known
bad. "I could not prove this" and "this is fine" must not produce the same outcome.

### 4a. The two blind spots, closed 2026-09-29 — and the disclosure that fell out

The count stood at 52 open with **1** provable, because the classifier could read a
`json.dumps({...})` dict and a `print()` and nothing else. Two extensions took provable from
1 to 26 of 52:

- **Logged f-strings.** 23 alerts reported as `neither a logger dict nor a print() at
  location`, which reads like "not a log line" and meant nothing of the sort — they are
  ordinary `logger.info(f"...")` calls. Every `FormattedValue` is now classified on its own,
  exactly as a dict's elements are. `tests/test_log_phone_masking.py` had the identical gap
  for the identical reason and it was hiding fourteen real disclosures, so the shape was
  already proven to matter.
- **Name resolution.** 28 alerts turned on a bare name carrying no hint (`sid`, `p`,
  `nblobs`, `RAZORPAY_SECRET_NAME`). A name is now resolved to what it is *bound* to, with
  every rule failing closed: a function parameter, a `for` target, a `with`/walrus/`except`
  binding, a tuple unpack, or a module constant bound more than once all stay UNPROVEN.

**Refusing to prove two sites is what found the defect.** Both
`whatsapp-calling/handler.py` sites interpolating `json.dumps(result)` sit on the
`if result.get('error')` branch, and `_send_via_aws` **returns the raw Meta response
unchanged** on that branch. Meta writes the recipient into the prose of several messaging
errors — 131030 is the well-known one — and `error_data.details` is free text in general. So
both lines masked the number on the left with `mask_phone(to_number or '')` and could
reprint it on the right. That is the second instance of the exact pattern §1 records finding
once before, and `json.dumps(result)[:500]` is not a fix: truncation removes a suffix, not a
number sitting at character 40.

Remediated with `meta_error_summary` in `lambda_utils/masking.py`, which keeps `code`,
`error_subcode`, `type` and `fbtrace_id` — the identifiers a human debugs from, all from
closed sets — and reduces any message to `message_present=True`. Applied at lines 1245,
2097 (where the raw error enters the function) and 2125, plus 2127 switched to naming the
one field its success shape contains. `tests/test_meta_error_summary.py` asserts on the
**absence of the number**, not on the presence of the code.

⚠️ **Five same-class sites in the same file are NOT remediated** and are recorded here
rather than quietly fixed, because each needs its own read of where `result` comes from:
`whatsapp-calling/handler.py` lines **1106, 1329, 1367, 1369, 1389**. Three of them
(`1329`, `1389`) sit next to a `mask_phone(to_number)` on the same line, so they are the
highest-priority of the five. None is currently reported by CodeQL, which is exactly why
they need to be written down.

### 4b. Two mistakes made inside this pass, kept because they are the reusable part

- **`mask_text` was added to the sanitiser list on the strength of its name, then
  removed.** Reading it shows it substitutes `Bearer <token>` and masks no phone number at
  all — so it would have proven a Meta error body safe and dismissed the very alert that
  led to the finding above. `tests/test_codeql_triage_classifier.py` asserts it is absent.
- **The exception rule first rejected any expression *mentioning* `exc`.** That wrongly
  condemned `type(exc).__name__` and `exc.response['Error']['Code']` — the two forms
  `.kiro/steering/secret-handling.md` (retired; now .kiro/steering/00-common.md) actually prescribes. The rule now distinguishes the
  exception's *text* (`{e}`, `str(e)`, `exc.args`, `…['Message']`) from a narrowing of it.

### 4c. The staleness guard was unsound at HEAD

It compared the analysed commit to HEAD and only consulted the working tree when the two
differed — so editing a file and re-running at the same commit skipped the check and
classified the alert against lines that had already moved. Found the hard way: the
remediation above shifted its own alert by four lines and the report described a different
statement without saying anything was wrong. The dirty-tree check is now independent of any
commit comparison.

### 4d. What remains

26 stay open and fall into one shape: an expression whose value cannot be attributed
without following it further than this pass goes — a loop variable over a runtime list
(`sid` over `targets`, `p` over `problems`, `verb`/`wpath` over `attempts`), a counter
accumulated from another unresolved name (`tree_hits`, `hist_hits`), a dict index
(`spec['secret_id']`, `d["project_id"].strip()`), or a method call on an object
(`live_smoke.describe()`). Nearly all are developer-run tooling in `scripts/` printing
diagnostics, and §3 records that all 69 of that group were read by hand. They are left open
rather than pattern-matched into safety.

### 4e. The next pass, 2026-09-29 — and §3 was wrong about a value-bearing line

Picked up at **20 open, 0 provable**. Left at **14 open, 6 dismissed with evidence**. The
part worth reading is not the count.

**§3 says the value-bearing lines in `scripts/` "emit a length, a label or an irreversible
`sha256[:12]`", and says all 69 were read. One of them did not, and the read missed it**
because it checked the call site and trusted the helper's name:

```python
# scripts/audit_secrets_structure.py, until 2026-09-29
def fingerprint(v: object) -> str:
    return f"len={len(v):<4} {v[:4]}…{v[-2:]}"
```

Four leading and two trailing characters of **every field of all seven secrets** that
script reports on, including `wecare/razorpay/api`'s `key_secret` and the AWS IAM secret
access key, printed to a terminal — which is `~/.kiro/logs` and the session transcript, the
exact path that put four credentials on disk on 2026-09-19. `SAFE_PRINT_CALLS` contained
`fingerprint`, so the triage tool proved that line safe.

**This is §4b's `mask_text` mistake, repeated with a different word.** It is also a defect
the project had already found and fixed once: `secrets_backup.py::fp` carries the correction
and the reasoning in its docstring. Two copies were still doing it and one did it inline:

| Site | Was | Now |
|---|---|---|
| `audit_secrets_structure.py::fingerprint` | `{v[:4]}…{v[-2:]}` on every field of 7 secrets | `len=` + `sha256[:12]`, `<short>` under 9 chars |
| `sync_webhook_registry.py::fp` | same rendering, on an AWS access key **id** | same fix; smaller exposure, identical shape |
| `verify_razorpay_secret_path.py` | `prefix={k[:4]}` inline, while its docstring claimed it printed only populated-ness and length | `sha256[:12]` |

The `<short>` branch is kept deliberately: a sha256 of a handful of characters is invertible
by brute force, so hashing a 3-character field would disclose it.

**The gate, which is the durable part.** `leaky_reducers()` now reads the definition of every
name in `SAFE_PRINT_CALLS` **in the file under analysis** and withdraws trust when a `return`
yields a slice or an index of a parameter, or of a one-step alias of one. A hashing call
breaks the chain, because `hashlib.sha256(v.encode()).hexdigest()[:12]` slices the digest and
not `v` — without that the check condemns every correct fingerprint in the tree.
`BOUNDED_TAIL_MASKERS` exempts `mask_phone` and friends, whose contract is the opposite: for
a phone number a bounded tail is the prescribed rendering, and for a credential it is the
thing not to print. `tests/test_codeql_triage_classifier.py` parametrises the check over
every `scripts/*.py`, so a fourth copy fails the build instead of being triaged.

**Two raw-exception sites remediated, which is what made them provable.** `sla-engine`'s
no-show handler and `whatsapp-calling`'s IVR-menu lookup both logged `{e}` — a DynamoDB
UpdateItem error can quote the item's own attributes back, and a `json.loads` error can quote
the stored document. Both now log `type(e).__name__`, and the correlation id stays. Verified
with the CodeQL CLI locally (2.27.1, the CI version) that this **did not** clear either
alert: the remaining element is the opaque id, which is exactly the thing triage is for. So
these two are remediated *and then* triaged, in that order.

**Four classifier extensions, each closing a shape §4d names:**

- `Resolver.loop_source` / `list_contents` read `for p in problems` as every expression
  appended to `problems`. Fails closed on a second binding of the loop variable, a
  non-name iterable, a reassigned list, and any mutation that is not `append(one)` or
  `extend(<display>)`.
- `classify` judged a sequence or comprehension element by the **container's** key, so
  `[(k['AttributeName'], k['KeyType']) for k in ...]` was judged as `keys` and attributed
  nothing. It now prefers the element's own identifier — the rule `classify_expr` already
  applied one level up.
- `classify_expr` resolves the interpolations of an f-string reached *through* resolution.
  `classify` has no resolver, so it judged them by name alone.
- `_consuming_call` walks through a non-logging wrapper to reach a logger, which closes
  `logger.warning(mask_text(json.dumps({...})))` in `meta_client.py` — reported as
  `no logger dict at location` and open for that reason alone. Walking through `mask_text`
  is **not** trusting it: the elements are still classified one at a time and it stays out
  of `SANITISERS` per §4b. Where no logger encloses the dict the first call is still
  returned, so `_store_call_log({...})` is still not a log.

`INFRASTRUCTURE_KEYS` is a new group, kept separate so each entry keeps its reason rather
than vanishing into a long alternation: `fbtrace_id` (Meta's own trace id, which
`meta_error_summary` already keeps deliberately), `appointmentId` (a uuid4 DynamoDB hash key
that CodeQL reads as health-adjacent because its `maybePrivate` regexp lists `appointment`),
the AWS control-plane enums (`BillingMode`, `MfaConfiguration`, `TableStatus`, …), and the
IAM/Cognito resource names `maintenance-reporting.md` already permits in a report. `count`
joins `SANITISERS`: `x.count(y)` returns an int by construction, exactly as `len` does.

**The 14 that remain**, unchanged in character — every one turns on a value reached through
a provider secret, a cross-module method call, or a tuple unpack from a function's return:

| Site | Turns on |
|---|---|
| `rcs_webhook_control_plane.py` ×4 | `project`, `verb`/`wpath`, `p`, `used` — all derived from `d["project_id"]`, read out of the Sinch secret. A project id is a provider identifier, but it arrives inside a credential payload and nothing here separates the two |
| `scan_repo_secrets.py` ×2 | `nblobs` from a tuple unpack of `git_blob_data()`; `n` is bound both by `.count()` and by `for n in notes`, so it cannot be attributed |
| `refresh_secret_consumers.py` ×2, `verify_backup_artifact.py`, `store_provider_secret.py`, `audit_secrets_structure.py`, `verify_razorpay_secret_path.py` | a secret **name** reached through a loop over a runtime list, a dict index, or a function return |
| `verify_secret_consumption.py` | five names from a tuple unpack over an accumulated list of tuples |
| `outbound-whatsapp/handler.py` | `live_smoke.describe()` — a cross-module call returning two bools and a 4-digit suffix of an env var, which this pass cannot follow |

Two of those are worth stating plainly rather than leaving implied. `audit_secrets_structure.py`
stays open **after** its disclosure was fixed, because the field *name* `k` still comes from
`json.loads` of the secret and still reaches a `print`; the alert is correct that tainted data
is printed, and wrong only about whether a JSON key name matters. And the `rcs_webhook_control_plane.py`
four are the honest limit of this approach: proving them needs the project id separated from
the credential at the point the secret is read, which is a code change to that script, not a
classifier rule.

The other rules are handled separately and none is dismissed on a pattern:

| Rule | Open | Disposition |
|---|---:|---|
| `py/weak-sensitive-data-hashing` | 9 | **Correct as written, remediation would be a defect.** Six are `hmac.new(app_secret, token, hashlib.sha256)` — Meta's mandated `appsecret_proof` algorithm, not password hashing. Three are irreversible fingerprints (`sha256[:8]`, `sha256[:12]`) that confirm a stored credential matches without displaying it. A slow KDF would break the first and be pointless for the second |
| `js/incomplete-multi-character-sanitization` | 3 → **0, remediated 2026-09-29** | `tools/audit/htmlcheck.js`. The earlier pass made the close-tag patterns whitespace-tolerant and added a fixed-point loop, which took 4 → 3. What it did not change is the thing the query is actually about: **every removal substituted the empty string**, which splices the two sides together, so `<scr<script>x</script>ipt>` collapses to a real `<script>` and `<sty<!--c-->le>` to a real `<style>`. Both removals now substitute `\n`, and the heading-text extraction substitutes a space. A newline cannot appear inside a tag name, so no removal can assemble a tag on any pass. This is a correctness fix first — that function exists so script bodies are not counted as document text — and it clears the alerts as a consequence, because CodeQL's `EmptyReplaceRegExpTerm` only considers substitutions whose replacement `mayHaveStringValue("")` |
| `js/xss-through-dom` | 1 → **0, remediated 2026-09-29** | **The earlier fix did not clear it, and this row used to say "awaiting re-scan confirmation" — the re-scan had in fact happened many times over.** Reading `isSafeHttpUrl` found two defects in the remediation itself. (1) It parsed with a base of `https://wecare.digital`, so the URL parser *resolved* relative input instead of rejecting it: `//evil.com` came back as `https://evil.com` and **passed**, while the function's own docstring stated that a bare `//host` did not. (2) It returned a boolean, so `calling.tsx` validated one string and rendered a different one — the raw input. Replaced by `safeHttpHref`, which parses with no base (absolute http(s) only, correct for a URL a telephony provider must fetch), and returns **the string to render**, rebuilt as a literal scheme plus `parsed.href.slice(protocol.length)` so it is byte-identical to the parser's own serialisation. `src/test/SafeHttpHref.test.ts` pins 15 cases including the `//host` regression, `java\tscript:` (browsers strip the tab before resolving the scheme, so it is a live `javascript:` URL), and equality against `new URL(input).href` |
| `js/clear-text-storage-of-sensitive-data` | 1 | `customerAuth.ts` stores a Cognito access token in `sessionStorage`. Deliberate and documented: the customer pool is separate from the staff pool and the token is not an Amplify session. `sessionStorage` clears on tab close and is the standard SPA choice; the alternative is a backend session behind an httpOnly cookie, which is an architectural change and not warranted by this. **Recorded as accepted risk, not dismissed as a false positive** |

## 5. Reproducing this

```bash
python scripts/triage_codeql_logging.py --report   # classification, no changes
python scripts/triage_codeql_logging.py --apply    # dismiss only the provable ones
python -m pytest tests/test_log_phone_masking.py   # the three gates
```

The gates are the durable part. Triage closes a backlog once; a gate stops it coming back.
