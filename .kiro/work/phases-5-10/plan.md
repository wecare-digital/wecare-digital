# Work plan — master-prompt phases 5 to 10

Durable state for an unattended run. **This file is the source of truth, not the
conversation.** If a session is interrupted — autocompacted, the Mac sleeps, the window
closes — the next session reads this file and resumes at the first item that is not `DONE`.
That is the whole reason it exists: a fifteen-item run degrades at the tail when the
requirements are remembered rather than re-read.

Repo: `/Users/wecaredigital/wecare-store` · branch `stack` · account `775261844268`
us-east-1

## How to resume

```
cd /Users/wecaredigital/wecare-store
git fetch -q origin && git -c core.editor=true rebase --autostash origin/stack
.venv/bin/python -m pytest -q | tail -3
cat .kiro/work/phases-5-10/plan.md      # this file: find the first non-DONE item
```

Per-item loop, every time:

1. Rediscover live state for that item — never trust a dated count in `bw-crm.md`.
2. Write failing tests first where the behaviour is testable.
3. Implement. Keep new capability behind a flag that defaults off.
4. Gates: `pytest -q` · `npm run typecheck` · `bash scripts/check-provider-policy.sh` ·
   `.venv/bin/python scripts/verify_public_webhook_auth.py --gate` ·
   `.venv/bin/python scripts/audit_route_auth.py --gate`
5. Deploy affected functions: `.venv/bin/python scripts/deploy_all_lambdas.py <fn>` —
   this publishes a version and moves the `live` alias, which is mandatory because the API
   invokes the alias.
6. Live-verify. Record the rollback version **before** deploying.
7. Commit by explicit path, push to `stack`, mark the item `DONE` here in the same commit.

## Standing constraints

Never, in any item:

- Enable `PSTN_BROWSER_ROUTING_ENABLED`, `WA_LIVE_SMOKE_TEST`,
  `PSTN_CONNECTED_NOTIFICATIONS_ENABLED`, or any live-send flag.
- Rotate, read or replace a provider credential. No `secretsmanager get-secret-value`.
- Put a credential on a command line or in a log.
- `git add .` / `-A` / `-u`, bare `git stash`, force push, history rewrite.
- Delete or re-register a WhatsApp number, WABA, phone-number id, or the protected Plivo
  identifiers `+918031830030` / app `12775976954213184` / endpoint `543585900967411`.
- Use PayU, Airtel messaging, Sinch SMS/Voice/WhatsApp, or Plivo SMS.
- Enable Security Hub.
- Sinch RCS is **India only** — see `.kiro/steering/03-sinch-rcs-india-only.md`.

Live QA sends go only to the owner-nominated QA recipient `+918100640044`, and only when a
send is separately authorised. Otherwise use fixtures and record `WAITING_FOR_OWNER`.

## Items

Status is one of `TODO` · `IN_PROGRESS` · `DONE` · `BLOCKED` · `WAITING_FOR_OWNER`.

---

### 5.1 — Plivo softphone: token route, session state, leg distinction · DONE

Commit `921a1417`. `lambda_utils/pstn/softphone.py` + `messaging/pstn-softphone`.
5 routes live, all 401 unauthenticated, browser routing OFF, 58 tests.
Table `PstnSoftphoneSessions` ACTIVE with TTL.

### 5.2 — Plivo callback authentication audit · DONE

Live `wecare-plivo-answer` v14. The premise — "a token nothing checks" — turned out to be
wrong: verification is real. Per route, measured:

| Route | Gate | Verdict |
|---|---|---|
| `POST /plivo/hangup` | V3 signature **required** | verified |
| `POST /plivo/events` | V3 signature **required** | verified |
| `POST /plivo/dial-events` | V3 signature **required** | verified |
| `POST /plivo/answer` | signature when present, else `?token=` | verified, side effects need ≥ `TRUST_TOKEN` |
| `POST /plivo/fallback` | signature when present, else `?token=` | verified |

`answer` and `fallback` cannot require a signature: Plivo does not sign `answer_url`
fetches, so rejecting an unsigned one drops every real call. The privilege is split instead
— XML is served at `TRUST_NONE`, the `CallStatus=completed` SMS pass is not.

Both secrets show `LastAccessedDate` 2026-09-23, so the gate is live rather than silently
degraded to `unverified_no_token_configured`.

**The token does not leak.** Stage `prod` logs `$context.path`, which excludes the query
string, and no handler log site emits the value — only the mechanism name `'token'`.

Two defects found and fixed:

- `qs.get('token') == token` — short-circuits at the first differing byte, in the same file
  whose signature verifier documents why that is wrong. Now `_token_matches` with
  `hmac.compare_digest`, both sides encoded (`compare_digest` raises `TypeError` on a
  non-ASCII str, and a 500 on `/plivo/answer` is a non-XML body, so the caller hears
  silence instead of a clean hangup).
- Unknown path fell through to `(_route_answer, False)`. That is what concealed the
  stage-prefix incident — `/prod/plivo/hangup` "worked" by returning `<Play>` to a hangup
  callback, re-answering a terminated call. Now a 404, refused before `_verify_provider`.

Live: `/plivo/status` → 404 (was 200 + `<Play>`); all five real paths still reach their auth
layer, none 404. 37 tests in `tests/test_plivo_routes.py`.

### 5.3 — PSTN call/event model: provision or retire · DONE

**Retired, not provisioned.** All five declarations and their `backend.ts` TTL entries are
gone, replaced by a note recording where each concern actually lives.

The decisive discovery came first: **`amplify/data/resource.ts` has never been deployed.**
Zero AppSync GraphQL APIs in the account, and no Amplify data CloudFormation stack — the
only Amplify app, `d22dm4b0jn71jw`, is frontend hosting. Every `stack-wecare-digital-*`
table exists because a provisioning *script* created it. So the file is a schema document
that reads like infrastructure, which is exactly how `PstnNotificationDelivery` came to
cause a real outage: claims raised `ClaimStoreUnavailable` and `/plivo/dial-events`
answered 503 without sending, while the source looked complete.

Provisioning the five would have created five empty tables with 13 GSIs and no writer.
Where each concern lives instead: `PstnCall` → `VoiceCDRTable` (the live record, 56 rows,
written on every callback); `PstnCallEvent` → the ordering problem it was for is now fixed
in place by `cdrRank`; `PstnAgentPresence` → `PstnSoftphoneSessions` + `pstn/softphone.py`
from 5.1; `PstnFlowVersion` and `PstnRecordingAudit` → nothing, because there is no flow
editor and no recording feature.

**The unconditional status write was there, exactly as suspected.** All five `_persist_cdr`
call sites write the same row id `plivo#{CallUUID}` with a blind `put_item`, so the last
callback to arrive won the whole item — and `put_item` REPLACES, so `hangupCause`,
`durationSec` and `end_time` were deleted rather than left alone. A mid-call payload has no
`Duration`, `_plivo_overall_status` downgrades a zero-duration `completed` to `'Missed'`,
and `_calculate_stats` counts the answer rate off that field. An answered call would be
reported as missed.

Latent, not yet fired: 56 of 56 live rows were won by `route='hangup'`. Reachable by
design though — `_route_dial_events` answers 503 on purpose so Plivo redelivers, and a
redelivery can land after hangup. It becomes routine the moment browser routing is enabled.

Fixed with `_CDR_ROUTE_RANK` + a conditional `update_item`: merge forward, never lower the
lifecycle state, equal ranks allowed through (a retried hangup with a corrected
`BillDuration` must land), and `createdAt` written once via `if_not_exists` because it is
the sort key for both read paths.

Verified against **real DynamoDB**, not just the fake: rank-10 after rank-40 →
`ConditionalCheckFailedException`; row still `Answered`/42s/`NORMAL_CLEARING`; equal-rank
retry landed with `createdAt` unmoved; a field absent from the write survived. Probe row
deleted, table back to 56. Live v15 (rollback 14).

### 5.4 — Softphone device matrix, contract-level · DONE

Four of the five named contracts already existed in `pstn/browser_token.py` and were
tested. Rather than rebuild them, this item verified them and closed the two real gaps.

| Contract | State |
|---|---|
| Token TTL | `clamp_ttl`, 30s floor / 24h ceiling, 3 tests — existed |
| `onLoginFailed` code mapping | `LOGIN_ERROR_CODES` 10001-10010 + `describe_login_error` — existed |
| Reconnect → same endpoint | `session_endpoint_username` is deterministic, 4 tests — existed |
| Refresh scheduling | existed as `refreshAfterSeconds`; **invariant was untested** |
| `getUserMedia` secure context | **entirely absent** |

**Refresh scheduling.** `max(20, int(ttl * 0.8))` was pinned by a single TTL=300 case. The
20s floor is the interesting part: if it ever met or exceeded the TTL, a client following
the schedule would refresh at or after expiry and loop — and minting is a Plivo REST call,
so that is a provider rate-limit incident rather than a slow page. It holds only because
`mint_token` clamps internally, which makes `clamp_ttl` load-bearing for a reason unrelated
to why it was added. Now a property test over 18 TTLs asserts `0 < refresh < ttl` with at
least 6s of headroom.

**The WebView constraint** is new: `src/lib/pstn/mediaCapability.ts` + 31 vitest tests.
`useWebRTCCalling.acquireMicrophone` called `navigator.mediaDevices.getUserMedia` unguarded,
and the hook surfaces failures with `setError(e.message)` — so in a container exposing no
`mediaDevices` an operator saw `Cannot read properties of undefined (reading
'getUserMedia')`. Both shells exist in this repo (`ios/`, `android/`), so that path is real.

Two things the research corrected rather than confirmed:

- `isSecureContext` is the right test, **not** `location.protocol === 'https:'`.
  `http://localhost` IS secure, and an https page in an insecure parent frame is not.
- `capacitor://` **is** a secure context on WKWebView from iOS 14.6, so "serve over https"
  is the wrong advice inside the iOS shell. The real cause of an absent `mediaDevices` there
  is a missing `NSMicrophoneUsageDescription` — a native manifest omission surfacing as a
  JavaScript undefined. Checked: both manifests already declare it
  (`NSMicrophoneUsageDescription`, `RECORD_AUDIO`), so this is a regression guard.

Wired into `useWebRTCCalling` and the two directly comparable sites in
`src/pages/dm/whatsapp/calling.tsx`. Nothing dials: `PSTN_BROWSER_ROUTING_ENABLED` is
absent on every function.

**Live-call matrix · `WAITING_FOR_OWNER`.** Exact unblock, in order:

1. Provision per-session Plivo endpoints. `plan_session_endpoint` returns
   `provisioned: false` by design — creating them is a control-plane write and must not be
   a side effect of a user signing in. Without them only outbound is safe; inbound routing
   to a shared endpoint is undefined and eventually hits error 10010.
2. Owner authorisation to set `PSTN_BROWSER_ROUTING_ENABLED=true` on `wecare-plivo-answer`,
   plus `PSTN_AGENT_ENDPOINT` (currently empty, so the flag alone would change nothing).
3. Place calls to the QA recipient `+918100640044` from a desktop browser, Android Chrome,
   the Android WebView build and the iOS WKWebView build, recording per row: login result,
   `onLoginFailed` code if any, whether the mic preflight passed, whether the remote party's
   audio arrived, and `talk_time_seconds`.

Steps 1 and 2 are both owner decisions, so the matrix cannot be produced unattended. Device
metadata belongs in `docs/rcs-ios-android-testing.md` alongside the RCS handset rows.

### 6.1 — Strip the action group's ungoverned powers · DONE

Live `wecare-agent-action-group` v11 (rollback 10). Twelve tools became **4 enabled READ
and 8 refused APPLY**, governed by `lambda_utils/agent/governance.py` — 115 tests.

All four powers removed, and the implementations **deleted** rather than left behind an
`if`. Dead code that still works is how a power comes back:

| Power | Was | Now |
|---|---|---|
| SEND | `sendWhatsApp/Sms/Email` invoked `wecare-outbound-*` directly | refused; no Lambda client, no `OUTBOUND_*_FUNCTION` in env or manifest |
| SCAN | `searchContacts` paginated all of ContactsTable then filtered in Python; `getStats` did 3 exhaustive scans; `getMessages` scanned both message tables | one bounded page, `Limit` sent to DynamoDB, `truncated` reported; stats from table metadata, **zero scans** |
| DELETE | `deleteMessage` hard-deleted; `deleteContact` wrote `deletedAt` | both refused |
| FABRICATE | `createInvoice` returned `success: True` with `INV-<random>` and wrote nothing | refused, and the refusal tells the model not to claim an invoice exists |

Three bugs were hiding inside those powers, each reachable only because the power existed:

- `deleteMessage` reported success for **any** id. `delete_item` succeeds on a nonexistent
  key and the inbound attempt was wrapped in `try/except: pass`, so the outbound branch was
  unreachable and every call claimed a deletion.
- `deleteContact` used an unconditional `update_item`. DynamoDB upserts, so deleting an
  unknown id **created** a row holding only `{id, deletedAt}` — a delete that manufactured
  records.
- `_find_contact_by_phone` scanned with `contains(phone, last10)` and `Limit=1`. `Limit`
  applies **before** the FilterExpression, so it examined one arbitrary item and discarded
  it, normally matching nobody; and `contains` could match the wrong number. ContactsTable
  has `phone-index` and `email-index`, both ALL-projected, so the scan was never needed.

Design points worth keeping: refusals are split into a short model-facing `refusal` (no
table names, function names or ARNs — it travels into a prompt and then a transcript) and an
operator-facing `detail` holding the forensics. My own test caught `DynamoDB` and
`update_item` leaking into the model-facing string. One routing table now covers both
Bedrock conventions; the previous code had two, so a tool could be governed under one
spelling and not the other.

The handler also moved from `CONTACT_WRITERS` to `CONTACT_PHONE_READERS` in
`test_contact_key_wiring.py` and earned that contract — it now calls `assert_consistent` and
logs `contact_key_mismatch`.

Live proof on v11: `sendWhatsApp` to the real QA recipient **refused** with nothing sent;
`createInvoice` refused with no id minted; `deleteMessage` refused via the API-path spelling
too; unknown tool refused and lists only the four reads; `getStats` returns 16 contacts /
204 messages, labelled approximate, with zero scans. No function errors.

### 6.2 — Versioned READ/PLAN/APPLY tool catalog · DONE

Live `wecare-agent-action-group` v13 (rollback 12). `lambda_utils/agent/{plans,receipts}.py`
plus versioning and kill switches in `governance.py`. 65 + 195 tests.

| Requirement | How |
|---|---|
| READ + status first | 5 READ tools live, including `listTools` so a model reads the catalog instead of guessing |
| then PLAN/dry-run | a refused APPLY returns a hashed plan of what it *would* do, plus `nextStep` forbidding the claim that it happened |
| **every APPLY disabled** | structurally, with **no flag at all** |
| immutable plan hashes | sha256 over tool + catalog version + canonical arguments |
| idempotency | key derived from the hash, namespaced `tool#hash` |
| receipts | every attempt, including refusals, through the existing audit sink |
| audit | `AuditLogsTable` via `lambda_utils.audit` |
| kill switches | `AGENT_DISABLED_TOOLS` and `AGENT_TOOLS_KILL_SWITCH` |

Three decisions worth keeping:

- **The timestamp is not in the hash**, so two identical intents hash the same and a retry
  is idempotent. The `flow_completion` lesson again: a coarse key merges two genuine
  requests *visibly*, a too-fine key splits a retry and performs the side effect twice,
  invisibly. Mapping key order is normalised; **list order is not**, because invoice line
  items and recipient lists carry meaning in their order.
- **The catalog version IS in the hash.** A plan approved under one set of tool definitions
  must not be applied under another. That is the whole content of "immutable" here.
- **Kill switches subtract only.** No environment variable can enable an APPLY — asserted
  across nine plausible variable names *and* by a grep of the module, because the failure
  mode is somebody adding one later. A switch that could enable a send is a live-send flag
  by another name.

The hash covers real values while descriptions and receipts carry masked ones: hashing a
masked phone number would collapse two recipients into one plan. Verified live — two
identical attempts produced the same hash, a different recipient produced a different one.

#### Two pre-existing defects found on the way, both fixed

**The audit log had never written a single row.** `AuditLogsTable`'s live key is `id`;
`lambda_utils.audit` built its item with `logId` and never set `id`, so every `put_item`
raised `ValidationException: One of the required keys was not given a value` and the
fail-open `except` returned `None`. Measured: **0 items**, against 17 call sites in
`partner-onboarding` and `waba-management` covering 30+ declared actions including
`payment.refund`, `secret.update`, `phone.register` and `dlq.replay`. All silently lost.

Root cause is the 5.3 finding: `resource.ts` declares `.identifier(['logId'])` and was never
deployed, so the live table was script-created with `id` while the helper was written against
the declaration. Fixed by writing both from one value — the physical-key/alias pattern
`contact_key` already uses. Live proof: the table went 0 → a real receipt row with
`id == logId` and `resourceId` equal to the plan hash the Lambda returned.

**`mask_secrets` had holes, and it feeds persistent storage.** Key matching is exact, so
`auth_token` was unmasked despite `token` being listed — and `auth_token` is the literal
field name of the Plivo credential this codebase reads. Also absent: `api_key`,
`refresh_token`, `api_secret`, `secret_access_key`, `session_token`, `webhook_secret`,
`credentials`. Added those plus a **value-shape backstop** for issuer-prefixed tokens under
any key name, matching the prefixes `block_inline_secrets.py` refuses. A secret key holding a
dict was also being recursed into rather than redacted wholesale. Precision matters here and
my own false-positive test caught an over-match — `"AKIAless text, no credential here"` — so
the rule requires a single whitespace-free token.

#### And one of mine

`test_agent_governance.py`'s fixture stubbed the handler's DynamoDB resource but not the one
inside `lambda_utils.audit`, so with `AWS_PROFILE` exported the suite wrote **35 real rows**
into the production audit table. Invisible only because the sink was broken; a working sink
plus an unstubbed test is production writes on every run. Fixture now installs a resource
that raises on any real table access, 34 test rows were deleted, and a full 2546-test run now
writes zero.

### 6.3 — Internal dashboard chatbot on the shared plane · DONE (APPLY enablement refused)

**Closed 2026-09-24 by the approval work in `.kiro/work/ia-consolidation/plan.md` item D1.**
What was outstanding here was the plan → approve → apply loop, and it now exists end to end:
`stack-wecare-digital-AgentApprovalsTable` with an atomic single-use consume, a server-side
draft store so a client approves by hash and never holds the arguments, an **Admin-gated**
`POST /ai/approvals` (+ `/status`), and an amber approval panel in the chat that states in
words that approving does not send. Live-verified 401 unauthenticated.

**Enablement of the 18 APPLY tools is a REFUSAL, not a pending task.**
`01-standing-authorization.md` lists any live-send flag under "never done, and never asked
about either", so it generates no prompt and no confirmation queue entry. What changed is
only that an apply is now refused for **one** reason (the catalog disables it) where before
it was refused for two. The machinery a future enablement would need exists and is tested,
which was the point — the worst time to design an approval system is the moment somebody
wants a send turned on.

The three sub-findings below remain accurate and are **not** blockers: they are recorded
gaps, not missing deliverables.

#### Original notes

Live `wecare-ai-generate-response` v11 (rollback 10). 66 tests in
`tests/test_agent_surfaces.py`.

**The finding that reframed this item.** 6.1 removed eight ungoverned powers from the
Bedrock action group — a surface that **cannot currently be reached at all**, because agent
`4UUQYFWX64` is `NOT_PREPARED`. The surface every operator actually uses, `/ai/generate`
with `context: 'internal-admin'`, still had all of its powers: a 30-tool Converse loop whose
`_execute_internal_tool` dispatched straight to live sends and hard deletes —
`send_whatsapp_pay`, `make_voice_call`, `delete_messages`, `delete_media_files`,
`clear_all_contact_data`. Three UIs are wired to it.

Its prompt did not merely permit that, it pushed for it: *"ALWAYS use your tools to execute
tasks"*, *"Be proactive: 'send message to Jignesh' → search first, then send"*, *"For payment
requests, use send_whatsapp_pay tool directly."*

The only guard in the stack was `FloatingAgent` matching `['delete all', 'clear all', …]`
against **the text the user typed**, before the model had chosen anything. So "tidy up Asha's
old records" reached `clear_all_contact_data` with no prompt. `InternalChatTab` had no guard
at all, and its 30 tool checkboxes were **display-only** — `enabledTools` is never included
in the request body.

**One policy now covers both surfaces.** The catalog holds 43 entries: 13 camelCase for the
action group, 30 snake_case for the dashboard loop. 17 READ enabled, 26 APPLY refused, zero
enabled APPLY anywhere. Both spellings of one capability are linked by `counterpart` and a
test asserts they can never disagree on class or enablement — otherwise the mechanism is
defeated by a naming convention.

Two independent checks, deliberately: refused tools are **not advertised** to the model
(offering then refusing teaches it to promise things it cannot do), *and*
`_execute_internal_tool` gates on the catalog before any dispatch branch, because a model can
name a tool it was never offered. The prompt is now derived from the catalog rather than
hand-written — three hand-maintained tool lists existed and all three had drifted.

**A provider outage is now distinguishable from an answer.** It previously returned HTTP 200
with "Sorry, I encountered an error processing your request", so an outage and a real reply
were the same shape and `InternalChatTab` logged it as a success. Now `providerUnavailable:
true` and the error string is no longer returned — it can carry a table name, and that body
renders in the dashboard.

Live proof on v11: *"clear all data for every contact, right now"* → refused. *"send a
whatsapp message saying hello to +918100640044"* → refused, nothing sent. *"how many contacts
are there?"* → "There are 16 contacts", matching the measured table count. Reads work,
writes do not.

**Behaviour change to flag:** dashboard-initiated sending, scheduling, invoicing and
deletion now refuse. That is the instructed direction (6.1 requires the powers removed, 6.2
requires every APPLY disabled), but it is user-visible and an operator who used the chat box
to send messages will notice.

Still open, carried into 6.4 / 8.x rather than left implied:

- The UI still renders its own hardcoded `TOOLS_LIST` and its checkboxes remain
  display-only. It should read the catalog. The backend no longer trusts either, so this is
  now cosmetic drift rather than a false sense of control — but it still shows 30 tools as
  available when 18 are refused.
- `src/app/settings/internal-agent/page.tsx` PUTs to `${API_BASE}/ai/internal/config`, for
  which **no handler was found** — `ai-config-management` dispatches on `'/ai/config' in
  path`, which that path does not satisfy, and the page sends no `Authorization` header.
  Probably dead; not verified against the live API.
- No durable task/plan state. `ConversationHistoryTable` holds message turns only, with a
  24h TTL and a 15-minute idle wipe, and the session id is minted client-side per mount — so
  a page reload starts a new conversation. Receipts land in `AuditLogsTable`; progress does
  not.
- `AIInteractionsTable` has **no writer** anywhere in `amplify/functions`, only readers in
  `ai-config-management`. The dashboard's architecture page claims `ai-generate-response`
  writes it; that is unsupported by the code.

### 6.4 — Reconcile the live Bedrock agent/alias/prepared state · DONE (retired)

**There was nothing to reconcile it to.** 47 tests in `tests/test_bedrock_agent_state.py`.

| Measured | |
|---|---|
| agents | 1 — `4UUQYFWX64`, `NOT_PREPARED` |
| foundationModel | **null** |
| instruction | **0 characters** |
| agentResourceRoleArn | **null** |
| preparedAt | **never** |
| action groups | **0** |
| knowledge bases (agent / account) | **0 / 0** |
| versions / aliases | `DRAFT` only; `TSTALIASID`, the auto-created test alias |
| last updated | 2026-04-25, five months ago |
| action group Lambda resource policy | `apigateway.amazonaws.com` only — **no `bedrock.amazonaws.com` principal** |

The agent was created and abandoned. It was never wired to the action group, and Bedrock was
never granted permission to invoke that Lambda. Preparing it would fail outright: no model,
no instruction, no role. `config.ts` said it "needs action groups + prepare", which
understated it.

**Every identifier naming this surface was fabricated, and the live env was worse than the
source defaults:** `INTERNAL_AGENT_ID=QIEEHEBTZO`, `INTERNAL_AGENT_ALIAS=ASCBD7YPUT`,
`INTERNAL_KB_ID=D0JU8Q7IQS`, `EXTERNAL_KB_ID=LYMQLKZNY7`, `AI_AGENT_ID=Z4YAK0ZLBO`,
`AI_AGENT_ALIAS=WANPKHQGIB`. `static-faq` was never an id in any format.

Both consumers were unreachable: `_invoke_bedrock_agent()` had **zero** call sites, and
`_query_knowledge_base()` was called only from inside it. `whatsapp-calling` referenced its
three agent variables **nowhere** in source despite all three being set live.

Retired rather than reconciled: 125 lines of unreachable code and the
`bedrock_agent_runtime` client deleted and replaced by a note carrying the measurement; all
9 stale vars removed from the 3 live functions **and** the manifest; fabricated defaults in
`config.ts`, `ai-config-management` (×2), `inbound-whatsapp-handler` and
`src/types/dashboard.ts` replaced with empty strings, because that config is returned by an
API and rendered in the dashboard where a plausible id reads as configuration.

Live: 5 functions `Active` (ai-generate-response 12, ai-query-kb 10, whatsapp-calling 17,
ai-config-management 10, inbound-whatsapp 44), zero stale vars, and Converse still answers —
"There are 18 contacts in the CRM".

**Owner decision, not a blocker.** Provisioning a real agent is new capability creation:
model, instructions, IAM role, action group attached, a `bedrock.amazonaws.com` invoke
permission, a prepare, and a real alias. Nothing needs it. The empty agent stays — deleting
it is destructive, needs confirmation, and it is inert and free.

### 7.1 — Shared integration registry + sync/metric boundary · DONE (live reads WAITING_FOR_OWNER)

**Closed 2026-09-24 on the master prompt's own terms**, which name the owner-blocked path as
a completion state rather than a gap: "Enable safe READ paths only where the owner has
supplied approved access; **otherwise complete fixtures/contracts and mark the live read
`WAITING_FOR_OWNER`**."

What was actually missing was the first half. `registry.py` described eight providers and
`ReadResult` defined how a read must report itself, and **nothing exercised either** — a
contract nobody runs is a docstring. `tests/test_integration_contracts.py`, **88 tests**
over fixtures with no network call, now drives all five things the prompt names: ownership,
scopes (read-only separated from write-capable), quota as used/limit rather than a
percentage, freshness derived from the provider's own max age, and provider request ids
where available. Plus the properties that make the three-state design load-bearing: nothing
claims VERIFIED, an absent request id is `None` and not `''`, quota-unknown is a different
state from none-remaining, age cannot go negative on clock skew, and the payload is masked
because a provider response can carry a refreshed token.

**It earned its keep on the first run.** The `wix` entry recorded `secret_name=""` while
claiming `SCOPE_UNVERIFIED` — internally contradictory, since that state means a credential
exists. `wecare/wix/headless-api-key` **does exist**; `DescribeSecret` puts its creation at
**2026-09-24 05:43**, after the registry's 2026-09-23 measurement. So the entry was right
when written and went stale, and its unblock still said "move the Wix credential into
Secrets Manager" — which would have sent somebody to create a secret already there. Now it
names the secret and states the real blocker: the function has no `WIX_API_KEY_SECRET`
pointing at it and `WIX_CREDENTIALS_DISABLED=true`, and both must change together on owner
authorisation because the storefront is live. An existing test asserting the old claim was
updated, with the timeline recorded rather than quietly rewritten.

The live reads stay `WAITING_FOR_OWNER`: 7 of 8 providers at `SCOPE_UNVERIFIED`, one at
`CREDENTIAL_ABSENT`, every unblock concrete and machine-checked against vague wording, and
all of them surfaced on `/growth`.

`lambda_utils/integrations/registry.py`, 55 tests. Measured before writing anything, because
the brief's provider list and the repo's state disagree:

| Provider | Adapter files | Credential | Access |
|---|---|---|---|
| Google Ads | **0** | `wecare/google/ads` | SCOPE_UNVERIFIED |
| GA4 | 6 | `wecare/seo/google-oauth` | SCOPE_UNVERIFIED |
| Search Console | **0** | `wecare/seo/google-oauth` | SCOPE_UNVERIFIED |
| Business Profile | 4 | `wecare/seo/google-oauth` | SCOPE_UNVERIFIED |
| Play Reporting | **0** | **none** | CREDENTIAL_ABSENT |
| Bing Webmaster | 14 | `wecare/bing/api` | SCOPE_UNVERIFIED |
| Meta Ads / CTWA | 26 | `wecare/meta-system-user-token` | SCOPE_UNVERIFIED |
| Wix | 31 | **none** — env fallback | SCOPE_UNVERIFIED |

Three of eight have no adapter; one of those has no credential either. **Nothing is
`VERIFIED`** — that state means a real authorised read succeeded and was recorded, and none
has. All eight are `waiting_for_owner()` with the exact console action that would unblock
them.

Design points that earned their place:

- **Access is three-state, not a boolean.** A credential existing is not a scope being
  granted — the Phase 4e finding encoded: the Google OAuth client works and
  `contacts.readonly` was still never added to the consent screen.
- **Two providers have no read-only scope at all.** Business Profile's `business.manage` and
  Play's `androidpublisher` both grant writes and Google offers no narrower option. They sit
  in `write_capable_scopes` with a required mitigation naming *where* the constraint is
  actually enforced — GET-only at code review, and a restricted Play Console role
  respectively. My own test caught them mislabelled as read-only. Google Ads declares **no**
  scope at all for the same reason, and no adapter may be built against it until reviewed.
- **Quota is `used`/`limit`, never a percentage** — "can I make 400 more calls today" is the
  only question a caller has, and a percentage cannot answer it. `quotaKnown: false` is
  distinguishable from `remaining: 0`; those are opposite situations.
- **A read carries its provider request id or records that it has none.** Absent is a fact;
  fabricated wastes a support ticket.
- **Freshness is derived from the provider's own `max_age_seconds`.** Search Console carries
  an explicit note that its data lags 2-3 days at source, so a fresh cache is not fresh data.
- Read-only by construction: no write verb exists, no provider call is made, and
  `get_secret_value` appears nowhere — existence is a `DescribeSecret` question.

**Remaining for 7.1:** the adapters themselves, which cannot be written past a
`SCOPE_UNVERIFIED` boundary without owner console actions. The `sync/metric boundary` half
(scheduled sync jobs writing metrics) is still to do and is not blocked — it can be built
against fixtures.

### 7.2 — Refactor the Meta Ads/attribution and Wix monoliths · DONE (domain layer lifted)

**The domain layer is out, 2026-09-24.** `lambda_utils/ecommerce/wix_domain.py` holds the 13
pure transforms; `wix-store/handler.py` went **1,761 → 1,512 lines** and now imports them.
More to the point than the line count: those functions are unit-testable **without AWS and
without a Wix credential**, where testing `_money_amount` previously meant standing up the
whole integration.

**Equivalence was proven, not asserted**, and that is what makes a "verbatim move"
trustworthy. 64 input/output cases were recorded from the pre-lift handler and replayed
against the lifted module — empty dicts, `None`, zero, a price as a string, unicode with a
rupee sign, a 120-character name, tabs and newlines. The first run found two real problems a
diff could never have shown:

1. `_generate_wd_order_number` **raised `NameError` in all four cases**. The set needed
   `datetime`, `timezone` and `timedelta`; the new module imported `json`, `re`, `time` and
   `uuid` and not those. A verbatim move that drops an import is still broken.
2. Seven **false** differences, because `_generate_sku` mixes in a time-derived suffix and
   `_generate_wd_order_number` a uuid and a clock. Left alone that would have meant either
   accepting noise or letting a real regression hide inside it, so the varying characters
   are masked and the structure is compared — a change in separator, prefix or field count
   still fails.

Final: **64 cases, 0 differences.** `tests/test_wix_domain.py` (44 tests) keeps it.

The adapter and job layers deliberately stayed: `_wix_request`, `_load_wix_api_key`,
`_credentials_disabled`, the two `_sync_*` jobs, `_hydrate_product_variants` (looks pure,
calls `_wix_request` — measured, not assumed) and `_response`, which reads the `origin`
global. Deployed `wecare-wix-store` v17 → **v18**, rollback `--function-version 17`, live
probes 401, zero errors, fleet alias drift 0.

The three **named** defects are resolved. The structural split into
adapter/domain/job is not, and is recorded honestly below rather than half-done.

Measured first: `wix-store` 1707 lines, `marketing-ads` 448, `ad-attribution` 196.

**Interactive scans — fixed.** `ad-attribution` had two, on ordinary HTTP routes:

- `_list_attributions` did `int(params.get('limit', '50'))`, so `?limit=abc` was a
  **500** and `?limit=999999999` an unbounded read — and it passed **no `Limit` at all**
  to DynamoDB, so asking for one item still transferred up to 1 MB per page. With a
  `FilterExpression` that reads the whole table while collecting almost nothing,
  because filtering happens after the read is paid for.
- `_get_stats` was a bare `while True` full-table scan **on every call**.

Both now use shared bounded reads and report `truncated` / `partial`, so a page count
cannot be rendered as a total. Live: `?limit=abc` → 200 with `limit: 25`,
`?limit=999999999` → clamped to 100, stats → `partial: true`.

**`WIX_CREDENTIALS_DISABLED` was a switch that did nothing.** It and
`CREDENTIAL_PURGE_EPOCH=2026-09-23T03:05:00Z` are both set on the live function, and
**neither name appeared anywhere in the repository**. Someone disabled Wix with a
variable the code never read. What actually stopped Wix was the absence of
`WIX_API_KEY_SECRET`, making the loader raise — off by accident, not by the switch.
The same shape as the dashboard's tool checkboxes in 6.3. Now honoured, and checked
*before* any credential read. Deliberately not load-bearing: with the switch unset and
no secret configured it still refuses, but for the honest reason.

**Wix env fallbacks — already absent.** The item asked to remove them; the loader was
already Secrets-Manager-only and fails closed. Two stale docstring claims corrected
instead: it asserted `SnapStart.ApplyOn=PublishedVersions` (measured `None` on all 62)
and "env as migration fallback" (there is none). Both corrected rather than deleted —
the useful part is stating what is actually true, since lazy loading is still right for
a different reason.

Bonus: the bounded-read helpers moved from `agent/governance.py` to
`lambda_utils/dynamo_reads.py`, re-exported for compatibility. They were written for
the agent catalog, but `ad-attribution` had the same defect on a plain HTTP route, and
two copies of one rule is how the stage-prefix bug returned twice.

**Measured Wix state:** integration is entirely off — no `WIX_API_KEY_SECRET`,
`WIX_CREDENTIALS_DISABLED=true`, and **0 rows** in all three cache tables
(`WixProductsCache`, `WixOrdersCache`, `WixOrderIds`). The production site must not be
recreated or republished.

**Update 2026-09-24 — a real bug found while mapping the seams, and fixed.**

Mapping `wix-store` for the split turned up a cross-request leak its own comment described
without noticing:

    # Module-level origin for CORS (set per-invocation in handler)
    origin = ''

`_response` reads that global, and a Lambda execution environment is **reused**. That is
harmless only if every path returning through `_response` sets it first, and two do not:
`_sync_products` and `_sync_orders` run on a schedule with no HTTP event. On a warm sandbox
they would emit the **previous HTTP caller's** Origin in a CORS header on a cron response.

Fixed with a `finally` that clears it, so an unset path emits a blank origin rather than
somebody else's. `tests/test_wix_origin_leak.py` (7 tests) exercises the behaviour rather
than reading the source, because `global origin` is declared once at the top of `handler`
and has to cover the assignment in the `finally` — easy to believe, worth proving. Verified
RED: removing the `finally` fails 3 of the 7, including the exception path, which is the one
most likely to leave a sandbox dirty. Deployed `wecare-wix-store` v16 → **v17**, live probes
still 401, zero errors.

Threading `origin` through the signatures is the cleaner boundary and was deliberately NOT
done: **36 call sites across 22 functions, only 2 of which have an origin to pass**, in a
1,743-line handler whose integration is entirely switched off and therefore cannot be
live-verified. A reset is small and provable; the signature change is the honest remainder.

The seam map itself is now measured rather than guessed. The pure-transform set is
**closed** — 15 functions, 278 lines, calling nothing outside itself and needing only
`SKU_PREFIX` — so the domain layer can be lifted out in one behaviour-preserving move
whenever that is scheduled. An earlier substring check wrongly flagged four of them as
impure; a proper call-graph pass showed `_normalize_v3_product`, `_simple_product_to_v3`,
`_extract_id` and `_s3_public_url` make no I/O call at all.

**Remaining for 7.2:** lifting that 278-line domain set into its own module, threading
`origin` through the 22 signatures, the Meta Ads monolith boundaries, routing
Wix-generated communication through the shared notification system, and Velo source drift
reconciliation. None is blocked; all are substantial. `marketing-ads` and `wix-store` have **0** DynamoDB scans, so there is no
scan debt left in them. `wecare-ad-attribution` has an **empty** live environment — no
configuration at all — worth resolving with the split.

### 7.3 — Growth and Commerce module homes behind flags · DONE (both flags OFF)

Separately routed inner pages, real backend state, connected-service tutorials,
error/stale/quota states. Provider-neutral page names; exact provider labels only inside
authorised connection details. AI may READ and PLAN; growth/storefront APPLY stays disabled.

### 8.1 — Eight module homes · DONE

Home, Communications, Customers, Commerce, Growth, Service Operations, Platform Operations,
Settings. Separately routed, lazy-loaded inner pages.

**Communications exposes exactly three**: Common Inbox, WhatsApp Business, Business Calling.

### 8.2 — productVocabulary + CI label scan · DONE

`src/lib/productVocabulary.ts` + `scripts/check_ui_labels.py` + `.github/workflows/ui-labels.yml`.

Measured before building it: `src/` carried **454** Lambda function names, **147** DynamoDB
table names, **46** ARNs and a raw API Gateway id. But the disclosures were the lesser
problem — the UI was making **false statements about the live system**:

| Claim in the UI | Reality |
|---|---|
| SMS runs on "AWS Pinpoint + Airtel IQ" (10 screens) | AWS End User Messaging. Airtel is prohibited and fully retired |
| webhook inventory: `wecare-sms-in-airtel`, status `active` | **function does not exist**, nor the route |
| "Deploy the SEO platform (`wecare-seo-platform`)" | **does not exist**; the only SEO function is `wecare-seo-tools` |
| public `<meta>` advertising Lambda/DynamoDB/S3/API Gateway/Bedrock | internal topology, sent to search engines |
| empty contact list showed the table name — **twice**, identical lines | — |
| SNS placeholder carried the **real AWS account id** into the DOM | — |
| `calling.tsx` shipped unrendered `lambda`/`table` metadata to the browser | dead weight |
| `ai-agent.tsx` default URL hardcoded the raw execute-api host | bypasses `api.wecare.digital` |

All fixed. **High-severity count 6 resource identifiers + 26 retired-provider claims → 0.**

Gate design points that matter:

- **Allowlist, not denylist.** `system-architecture.tsx`, `InfraTab`, `lambda-functions.tsx`
  and the WABA/webhook screens *exist* to show topology. A scan that failed on those would
  be switched off within a day, so each authorised surface is listed with a stated reason
  and everything else fails.
- **Line numbers had to be right.** My first version dropped import lines, which shifted
  every number after them and pointed at an empty-state div 40 lines below the real match.
  Lines are blanked, never removed, and I verified every reported location against the file.
- **A retired provider is allowed when marked historical.** An old call record really was
  carried by Airtel, so `'Airtel (historical)'` passes and bare `'Airtel'` does not.
- **Comments are stripped.** `SEO.tsx` documents Airtel as retired; reporting that would be
  reporting the documentation as the defect.
- **ARNs need a 12-digit account id.** `arn:aws:iam::role/...` as an input placeholder
  teaches a format and discloses nothing; my first pattern flagged it.
- **Blocking on HIGH only**, with 20 medium (bare service words) tracked. Same staging as
  `provider-policy.yml`, which ran `--expect-fail` until its count hit zero. `--strict`
  fails on the remainder.

Remaining: 20 medium `aws_service_word` hits, and the vocabulary module is defined but not
yet adopted by every screen — 8.1/8.3 will wire it as those screens are rebuilt.

### 8.3a — Propagate the public design contract to the inner pages · DONE

Owner asked to follow the public home page inward, header and footer included, pixel by
pixel, inventing nothing. Commit `796ff60e`, Amplify job **798 SUCCEED**, live-verified.

**The shape of the problem.** There were two design languages and the written contract
only covers one. Public pages use `<style jsx>` with literal hex; the ~103
`Layout`-wrapped inner pages use global CSS plus inline `style={{}}`. Header and Footer
are rendered centrally in `_app.tsx` for public routes and **not at all** once
authenticated — `Layout.tsx` supplies a sidebar shell instead — so there is no shared
header/footer component to restyle. The alignment has to happen in the stylesheets.

**The hairline rule was inverted.** The contract: 2px means hoverable, 1px means static,
the colour is always `#e5e7eb`, and a hover swaps the border **to** lime. The stylesheets
had lime at REST on 53 surfaces with dark green on hover.

| | Before | After |
|---|---|---|
| lime resting borders | **53** | 4, all deliberate |
| resting hairlines rewritten | — | **49** |
| hover borders swapped to lime | — | **32** |
| `#111827` in stylesheets | 25 | **0** |
| `--font-sans` without Inter | 2 of 3 | **0** |
| content measures | 1400 / 1200 / 1300 | one, **1300** |
| danger surfaces in the success green | **5** | 0 |

Seven of the 53 were `select`, `input` and `textarea`, so every dashboard form field wore
a ring that reads as permanently focused — **the same defect already fixed on the sign-in
form**, whose note in `_app.tsx` explains exactly why. The fix landed on the login card
and never on the hundred pages behind it. The worst site was `tokens.css`, where
`input, select, textarea` is **unscoped**, so it painted the public pages too.

2px was applied only where the selector actually has a `:hover` rule. The weight is a
signal, so over-applying it is the error, not under-applying it.

**Kept deliberately.** The four lime resting borders are the success banners and the
outbound bubble — contract treatment 1, our own surfaces at full voice. The single heavy
lime edges on `.inner-header`, `.inner-footer`, `.sidebar` and the panel headers are kept
for the reason `_app.tsx` defends the sign-in card's 4px lime top edge: one heavy edge on
our own surface reads as brand and cannot be mistaken for focus. What is **not** that
pattern is a lime rule repeated under every row of every table, so those 3 went grey.

**The bundle caught me fixing one file out of nine.** After `inner-pages.css` was clean, a
`rm -rf .next out` rebuild still shipped 36 lime resting borders, byte-identical across two
builds so not staleness — the same inversion is repeated in eight other stylesheets.
Measuring the *bundle* rather than the source is what found it.

**Five destructive affordances were painted the success green.** A delete-all button, a
contact delete, a delete-message button, a danger button's icon and a delete panel's
warning text were all `#1a3a2a`, which `tokens.css` assigns to `--success`. Third time in
this run that a state colour proved indistinguishable from another state, and the only one
where the colour told the user a destructive action was safe.

**The gate.** `check_design_drift.py` gains five rules across all nine stylesheets, each
verified against a real regression rather than only against a clean tree — 7 cases,
including two that must *pass*: a lime border inside `:hover`, and proof the danger
allowlist is load-bearing. Its first run earned its keep twice: it found a **40th** lime
border the migration's grep missed because it was written `2px` not `1.5px`, and its first
version flagged 9 danger sites of which **4 were not affordances** (a delete-scope picker,
and the word DELETE in API docs). Both allowlisted with the reason.

**Verified live.** All three CSS chunks on `https://wecare.digital` are byte-identical to
the locally gated build: 0 `#111827`, 0 `#4b5563`, 0 `1400px`, 47 × 2px hairlines, 51 × 1px,
81 lime hovers, Inter leading `--font-sans`, `max-width:1300px` present. Gates: 2794
pytest · 73 vitest · typecheck clean · build clean at 125 sitemap URLs.

Two measurement mistakes of my own, both caught before they became a report: the minifier
rewrites `rgba(0,0,0,.898)` to `#000000e5`, so my first "0 occurrences" was my regex being
wrong; and a `while read` loop silently dropped the last CSS URL for want of a trailing
newline, which nearly produced a false "not deployed".

**NOT done, not claimed:** pixel-by-pixel rendering. I cannot screenshot, so what is
verified is that the shipped CSS carries the contract's values, not that two screens were
compared. The **13px button radius is untouched** — the contract specifies a radius for
pills (50px) and code panels (14px) and says nothing about compact action buttons, so
unifying ~1,500 radius declarations is a separate job needing visual sign-off. Inline
`style={{}}` colours across the pages are also out of scope here; the stylesheets are the
shared surface and they are clean.

### 8.3 — Adaptive navigation + design tokens · DONE

Phone bottom bar, foldable recomposition, tablet rail/sidebar, desktop sidebar. Light-only
Material 3-derived tokens, exact 13px rectangular radius. Prove desktop/mobile/accessibility,
role visibility and backend authorization. Preserve working capability before retiring any
duplicate page.

### 8.4 — Legacy redirects and refresh-safe deep links · DONE

Every retired route redirects; deep links survive a refresh.

### 9.1 — Retire the old notification/Airtel/Sinch-SMS/AWS-Social paths · DONE

The live retirement was already complete; this item verified it and closed the last
surface, which was the UI still *claiming* the retired providers were live.

Measured against account 775261844268:

| | |
|---|---|
| Lambda functions matching a retired provider | **0** of 61 |
| Secrets matching a retired provider | **0** of 25 (the 6 scheduled deletions completed) |
| API routes for Airtel / PayU / Sinch SMS | **0** of 343 |
| `AirtelC2C` / `AirtelSMS` tables | **absent**, already deleted |
| `scripts/check_provider_policy_live.py` | **LIVE PROVIDER POLICY OK — no untracked violations** |

The only `sinch` routes are `GET`/`POST /webhook/sinch-rcs`, which is the **approved**
India RCS provider and correctly retained.

What remained was a documentation surface, not an infrastructure one: ten screens described
SMS as "AWS Pinpoint + Airtel IQ", and the webhook inventory listed `wecare-sms-in-airtel`
as `active` when that function does not exist. Fixed under 8.2, whose CI gate now fails on
any retired provider presented as current — so this cannot silently come back.

Retained deliberately: `stack-wecare-digital-OBDCampaigns` (**0 rows**, but
`voice-in/obd/handler.py` still writes to it at 4 sites, so it is not dead), and the empty
`VoiceCalls` / `VoiceAwsTable` / `SmsOutboundTable`. On-demand tables cost nothing empty,
and deleting one needs the export/snapshot procedure plus pointwise confirmation — not worth
spending that for zero benefit. `legacy_history.py` is correctly named and reads historical
rows.

### 9.2 — Route/dependency cleanup and bundle optimization · DONE

**Update 2026-09-24 — the dependency half is finished.** `npm audit` reports **0
vulnerabilities** and GitHub reports **0 open Dependabot alerts**, down from the 5 advisories
recorded below. The last two were `mysql2 <3.22.0` (HIGH — auth plugin downgrade to
`mysql_clear_password` leaks plaintext credentials) and `csv-parse <7.0.2`, both transitive
under `@aws-amplify/backend-cli`, a devDependency reached only by
`ampx generate schema-from-database` — which this project cannot use, since
`amplify/data/resource.ts` has no SQL data source. Closed with `overrides`, the pattern
already in `package.json` for `lodash`, `fast-xml-parser` and `immutable@3`.

Method note worth keeping: pinning `mysql2` to the advisory's own `first_patched_version`
of `3.22.0` did **not** clear the tree. `npm audit` then reported a *different* moderate
advisory the Dependabot list had not mentioned — unbounded zlib inflate in the compressed
protocol handler, affecting `<=3.23.0`. **A patched version answers one CVE, not "is this
package clean now."** Pinned to `3.24.4`.

**Route cleanup is also substantially done** — 25 routes invoking `$LATEST` reduced to 6
(both remaining sets deliberate, named in `scripts/provision_live_alias.py`), 8 routes created
for three dashboard pages that were calling endpoints which did not exist, `_routes.json`
regenerated from the live API (322 → 353), and every `wecare-*` log group given a retention
period (13 had none, meaning never).

**Still genuinely outstanding: before/after bundle bytes.** No measurement has been taken, so
no claim is made.

#### Original dependency triage

Dependency half done ahead of order, because a **critical** alert should not wait behind UI
work. Route cleanup and before/after bundle bytes still to do.

**BEFORE:** 20 advisories — 1 critical, 5 high, 14 moderate.
**AFTER:** 5 advisories — 0 critical, 1 high, 4 moderate.

All 39 GitHub alerts were npm, all in `package-lock.json`, and **none reached production**.
Several were already satisfied by the installed copy (`tar@7.5.22`, `uuid@11.1.1`,
`@opentelemetry/core@2.11.0`) — GitHub was alerting against superseded lock entries.

**The critical alert and four of the five highs came from one unused dependency.**
`plivo-browser-sdk@2.2.21` was declared as a **production** dependency and imported
**nowhere** — zero matches across `src`, `amplify`, `scripts`. Its chain:

    plivo-browser-sdk -> wasm-pack -> binary-install -> axios@0.26.1 + tar@6.2.1

`wasm-pack` runs `postinstall: node ./install.js`, so `binary-install` downloads a binary
over `axios@0.26.1` and extracts it with `tar@6.2.1` on **every `npm ci`**, in CI and on every
developer machine. The critical CVE was in a postinstall archive extractor for a tool the
application never invokes — the classic supply-chain position, and `fixAvailable` was `False`
for all of it because `plivo-browser-sdk` pins `2.2.21` exactly.

Removed. `npm audit fix` then cleared `@capacitor/cli`, `uuid` and `xcode`.

**The softphone work expects this SDK back.** `pstn/browser_token.py` mints its JWTs and
`src/lib/pstn/mediaCapability.ts` preflights audio for it. It is not needed yet — browser
routing is off, and per-session Plivo endpoints are an unstarted owner decision (5.4). When
it returns, add a **current** version; do not restore `2.2.21`, whose transitive chain is
what produced the critical.

**The remaining 5 are dev-only and the offered "fix" is a downgrade.** All descend from
`@aws-amplify/backend-cli` → `schema-generator` → `graphql-schema-generator`, which pulls
`mysql2@3.9.9` (high) and `csv-parse@5.6.0`. npm's only remedy is `@aws-amplify/backend-cli`
**0.11.1**, a major downgrade of the CLI, which is not a fix.

Worth connecting to 5.3: that generator produces a schema for
`amplify/data/resource.ts`, which has **never been deployed** — 0 AppSync APIs, no Amplify
data stack. So the tooling carrying the last high alert exists to serve a backend that is
not live. Retiring `@aws-amplify/backend*` is the real remedy, but its types are used by
`amplify/*.ts` at typecheck, so that is a scoped change rather than a drive-by.

Verified after the change: `npm run build` succeeds (16 sitemap URLs), typecheck clean,
73 vitest, 2743 pytest.

### 9.3 — Native packaging · WAITING_FOR_OWNER

APK/AAB/IPA and signing are **POST-PROJECT** per `.kiro/steering/00-current-owner-overrides.md`
and cannot block closure. The web app must stay WebView/WKWebView-ready, which 8.3 covers.

### 10.1 — Admin MFA · DONE (enforcement staged, one owner decision)

Pool `us-east-1_cSx0RHCIR` (WECARE.DIGITAL). 20 tests in `tests/test_admin_mfa.py`.

| | Before | After |
|---|---|---|
| `MfaConfiguration` | **OFF** | **OPTIONAL** |
| Software token (TOTP) | not enabled | **enabled** |
| SMS MFA config | present, unused | preserved |
| Application-layer Admin MFA check | none | implemented, warn-mode |

**Two findings, both worth stating.**

*The sole user's MFA was enrolled but inert.* That user already had `SMS_MFA` and
`EMAIL_OTP` registered with `EMAIL_OTP` preferred — but with the pool at `OFF`, Cognito
issues no challenge even to a user who has factors. MFA looked configured and did
nothing. Setting `OPTIONAL` **activated** the existing enrolment, which is why `OPTIONAL`
was right and `ON` was not: `ON` forces every user through a setup flow that has never
been exercised, and with one account the only thing it could achieve is locking out the
sole operator. **This is a live sign-in behaviour change** — that user will now be
challenged for email OTP.

*Nobody is in any group.* All four groups — Admin, Operator, Viewer, Partner — have
**zero** members, and `ROLE_HIERARCHY` defaults an ungrouped user to `Viewer`. Meanwhile
**16 live handlers** gate on `required_role='Admin'`: `messages-read`, `seo-tools`,
`docs-scraper`, `partner-onboarding` (×3), `outbound-whatsapp` payment actions,
`waba-management`, `whatsapp-calling`, `scheduled-messages`, plus role-computed gates in
`invoice-engine`, `crm`, `wix-store`, `whatsapp-voice`, `pstn-softphone`,
`push-notifications`. Every one of them currently refuses the only account.

That is **fail-closed, not exploitable** — but those features are unusable, and granting
the role widens privilege, so it is an owner decision rather than something to do
unilaterally.

**The control.** An Admin must have a second factor enrolled, checked where the Admin
role is *used* rather than at sign-in, and only when Admin is actually required — so an
Admin reading a Viewer-level route pays no extra `AdminGetUser`. The role refusal runs
first, deliberately: a Viewer asking for Admin gets "Insufficient permissions", not an
MFA message that would disclose the role exists and what it needs.

Honest about its limit: it checks **enrolment**, not whether MFA was used this session.
`require_auth` validates an access token via `get_user`, and a Cognito access token
carries no reliable `amr` claim, so the session question is unanswerable here. Enrolment
plus pool `OPTIONAL` means Cognito will have challenged them; claiming more would
overstate it.

Any factor counts — TOTP, SMS or email OTP. Insisting on TOTP would refuse the one
person who actually has a second factor.

`mfaEnrolled` is `True`/`False`/**`None`**, where `None` means the lookup failed, so a
Cognito outage is distinguishable from a user who enrolled nothing. When enforcing, an
unknown answer **fails closed** — the opposite of the audit sink's choice, because a
failed audit write loses a record whereas a failed authorization check grants
administrator.

Staged behind `ADMIN_MFA_REQUIRED`, defaulting to **warn** with an
`ADMIN_MFA_MISSING` alert. Enforcing immediately would refuse the first Admin ever
created until they enrolled, and whoever hit that would switch the check off rather than
enrol.

Deployed to all 58 packaged functions. Verified live: an Admin-gated route
(`wecare-messages-read` v11) still answers **401** unauthenticated.

**Owner decisions:** (1) put the operator in the `Admin` group so those 16 handlers
become usable; (2) enrol TOTP and set `ADMIN_MFA_REQUIRED=true` to move from warn to
enforce; (3) optionally consider pool `ON` once more than one admin exists.

Noted in passing: `amplify/functions/auth/customer-whatsapp-auth` has source but **no
deployed function**, and **zero** routes or integrations reference it — unshipped code.
`deploy_all_lambdas.py` correctly refuses to create a production function that does not
already exist.

### 10.1b — Sign-in URLs and app clients · DONE

Owner asked for the login URL to be updated alongside the design work.

**I have to lead with a correction: I claimed login was broken, and it is not.** The
reasoning failed twice.

1. The Amplify domain serves the apex, and `retired-legacy-host.invalid` 301s to it. I assumed a
   301 would drop the OAuth `?code=`. Probed it: `?code=TESTVALUE123` **survives** the
   redirect.
2. `signin.wecare.digital` returned 403 for the authorize URL and I read that as a
   `redirect_uri` rejection. Control probe with `not-registered.example.com` returned the
   **same** 403 and the same "Sign in" page — managed login does not validate
   `redirect_uri` at render time, so the 403 carries no information about registration.

`NEXT_PUBLIC_APP_URL=https://retired-legacy-host.invalid/` was a historical callback value before the frontend moved to the apex.
The configuration was consistent the whole time.

**What was actually changed — additive only.**

| Web client `1j8kbi48m4v2rped3n224rlevb` | Before | After |
|---|---|---|
| `CallbackURLs` | localhost, `stack.` | localhost, `stack.`, **apex** |
| `LogoutURLs` | localhost, `stack.` | localhost, `stack.`, **apex** |
| OAuth flows / scopes / auth flows | `code` / email openid profile / 3 | unchanged, re-read to prove it |

Registering the apex removes the flow's dependence on a 301 without disturbing a path
that works. `NEXT_PUBLIC_APP_URL` deliberately **not** changed: a prior session's comment
in `_app.tsx` chose the subdomain on purpose, and a full OAuth round trip is not
something this session can test.

`UpdateUserPoolClient` resets omitted fields to defaults — every field was passed back
explicitly and then re-read.

**The real finding was the other client.** `1jrnb80tcvceg7uln9vuoe8va5` ("WECARE.DIGITAL"),
created 2026-02-11 02:40 and never modified since — 35 minutes before the real web client,
so it is the console quick-start client, superseded and forgotten. Its **only** callback
was `https://d84l1y8p4kdic.cloudfront.net`, the AWS sample distribution, with the `code`
flow live and an extra `phone` scope. Zero references to the client id or that host
anywhere in the repo. Now OAuth-disabled with empty callback/logout/flow/scope lists,
every other field preserved.

**Disclosure, recorded rather than buried.** `DescribeUserPoolClient` returns
`ClientSecret` in cleartext, so reading that client to check its redirect URIs put a live
confidential-client secret into the session transcript, which persists to `~/.kiro/logs`.
The value appears in no row, report or file. Bounded: the client is OAuth-disabled, has no
callback, `ALLOW_USER_PASSWORD_AUTH` is off, and a client secret alone authenticates
nobody — it computes `SECRET_HASH` and still needs valid user credentials. **Cognito
cannot rotate an app client secret in place**, so the only remedy is deleting the client:
account-level security, therefore an owner confirmation.

The gap that allowed it is closed. `block_catastrophic.py` gained a
`SECRET_BEARING_READS` table for reads whose *response* carries a credential even though
the operation name looks innocuous, derived into its SDK spelling by the existing builder
so the CLI and MCP tiers cannot drift. Blocked, not asked — with a deliberate exemption
when a CLI `--query` provably excludes the secret (must exist, must descend below the top
level, must not name the field), so the legitimate question stays one flag away and nobody
has a reason to reach past the guard. Self-test **87 → 97**.

**Owner decisions:** delete the vestigial client `1jrnb80tcvceg7uln9vuoe8va5` (invalidates
the disclosed secret; it is unused); and the two carried over from 10.1 — put the operator
in the `Admin` group, then move `ADMIN_MFA_REQUIRED` to enforce.

### 10.2 — WAF · DONE

**The constraint that reshaped the item: WAF cannot protect an HTTP API.** Verified against
AWS documentation rather than recalled — the protected resource types are a CloudFront
distribution, an API Gateway **REST** API, an ALB, an AppSync GraphQL API, a Cognito user
pool, an App Runner service, an Amplify application and a Verified Access instance.
`zllr9lrg7j` is apigatewayv2, so no web ACL can ever attach to it. A service limit, not a
choice. The API keeps the protection it already has: handler-level `require_auth`, provider
signature verification, and per-route Lambda invoke permissions.

Two web ACLs, because the scopes are incompatible — Amplify requires a CloudFront-scope ACL
created in us-east-1 and AWS states a regional one is not usable with it.
`scripts/provision_waf.py`, idempotent, `--apply` / `--verify`.

| | Scope | Blocking | Counting |
|---|---|---|---|
| `wecare-amplify-waf` → app `d22dm4b0jn71jw` | `CLOUDFRONT` | rate 2000/5min, IpReputation, KnownBadInputs, CommonRuleSet | — |
| `wecare-cognito-waf` → pool `us-east-1_cSx0RHCIR` | `REGIONAL` | rate 1000/5min | IpReputation, CommonRuleSet |

Configured **differently on purpose**. Amplify serves a static export — GETs for HTML, JS
and images, no bodies — so the managed groups have almost nothing legitimate to
false-positive on and run in BLOCK. An untuned Core rule set in front of Cognito managed
login could refuse the only account in the pool, so there the rate rule blocks and the
managed groups COUNT until the logs are read. Logging ships in the same change, because a
rule set counting into nothing is the audit sink that failed open in a new costume.

**Live-verified, not asserted.** A Log4Shell probe returns **403** while `/` returns 200, and
CloudWatch attributes the block to `AWSManagedRulesKnownBadInputsRuleSet`. Cognito shows
allowed traffic and zero blocks. `--verify` prints the rate rule as **not verified** rather
than implying otherwise — tripping it means thousands of requests at our own sign-in
endpoint. Cost named: ~$17/month for two ACLs and their rules.

One scare worth keeping: `signin.wecare.digital/login` returned 403 straight after
attachment, which is exactly what a WAF lockout looks like. Ruled out on evidence — zero WAF
samples, `InitiateAuth` still answering, and the default Cognito domain returning 302 for the
same query. Real cause: the client had **no managed login branding**, so the custom domain
(managed login) 403'd while the default domain fell back to the classic hosted UI. Created
with Cognito-provided values: **403 → 200**.

### 10.3 — Production deployment checkpoint + closure report · DONE

See `docs/execution/PHASE-10.3-CLOSURE.md`. Final result **⚠️ COMPLETE WITH IMPROVEMENTS** —
not ALL REQUIRED WORK VERIFIED, because 7.2's boundary refactor was not done and the
Admin-gated handlers cannot be verified until the owner joins the Admin group.

Exact flags, bindings, recipients, migrations, observation metrics, thresholds, cost impact,
rollback commands. Monitor callbacks/notifications/receipts/alarms/Actions/Amplify to
terminal state. Then the final completion/gap/improvement report and the phase-result table.

## Carried-forward gaps

Open, each with a reason, from earlier phases. Fold into the item that touches them.

| Gap | From | Severity |
|---|---|---|
| Meta payment verification defaults `payment_verified = True`, skips lookup when `paymentConfigName` empty | 4d | MEDIUM |
| Invoice phone+amount fallback matches on a float tolerance `< 0.02` | 4d | MEDIUM |
| Five payment vocabularies still coexist in **storage** (`canonical()` maps on read only) | 4d | MEDIUM |
| Invoice sequence failure injects `WD-PAY-TEMP-` into the GST series | 4d | MEDIUM |
| `whatsapp-business-api._save_flow_submission` — 4th Flow writer, different schema, still unguarded; check reachability | 4c | MEDIUM |
| `_handle_flow_data` returns HTTP 200 on a routing exception | 4c | MEDIUM |
| `wecare/sinch/rcs` has no `webhook_secret`; 17 callbacks refused in 30d | RCS | MEDIUM |
| 559 of 730 RCS sends fail — recipients not RCS-capable, not an integration defect | RCS | INFORMATIONAL |
| `rcsmenu` template id/version `UNVERIFIED` | RCS | LOW |
| Google redirect URI + `contacts.readonly` consent scope | 4e | WAITING_FOR_OWNER |
| Truecaller callback registration on developer.truecaller.com | 4e | WAITING_FOR_OWNER |
| `amplify/data/resource.ts` is **not deployed** — 0 AppSync APIs, no data stack. 69 models declared, **12 have no table** under any naming, and **19 live tables no model declares**. Reads like infrastructure, is a document | 5.3 | HIGH |
| 7 remaining phantom models after the 5 PSTN ones: `AdminActionLog` `AirtelC2C` `AirtelSMS` `ProviderDriftSnapshot` `RateLimitTracker` `RcsMessages` `SmsAws`. Airtel is a retired provider; `RcsMessages` already has "write STOPPED" in `rcs-send`; `ProviderDriftSnapshot` has zero writers; `RateLimitTracker`/`SmsAws` look like name drift from the live `RateLimitTable`/`SmsOutboundTable` | 5.3 | MEDIUM |
| `VoiceCDRTable` has **no GSI** and readers filter in memory after a `Scan`. Fine at 56 rows, not at 56,000 | 5.3 | LOW |
| `calling.tsx` auto-answer falls back to a **0 Hz oscillator** when the mic fails, so the call connects and the far party hears silence with no signal that capture failed. Left alone deliberately — changing it alters what a caller hears | 5.4 | MEDIUM |
| `useWebRTCCalling.ts` has 3 pre-existing eslint errors (use-before-declare at 161, lost memoization at 226, setState-in-effect at 620). Present at HEAD before this work; confirmed by linting the file from `git show HEAD:` | 5.4 | LOW |
| 40 Dependabot alerts (1 critical, 20 high, 18 moderate, 1 low) — count re-read from the push warning on 2026-09-23, down from 49 | — | HIGH |
| `route-auth.yml`'s **live-AWS job has never run**. It is gated on `if: vars.ROUTE_AUTH_ROLE_ARN != ''` and `gh variable list` is empty, so the job reports `skipped` on every run (confirmed on `35866106357`). The source gate does run and is blocking; it is the console-drift half that is missing — the half that would catch a route added or re-pointed outside the repo. Unblock: create a read-only OIDC role trusted by this repo and set the repo variable | 5.2 | MEDIUM |
