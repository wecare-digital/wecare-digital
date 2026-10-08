# Kiro handoff

Updated: **2026-09-25**

## Position

| Field | Value |
|---|---|
| Mode | **Unattended.** `.kiro/steering/01-standing-authorization.md` governs; no confirmation queue |
| Phase | **All 11 phases closed.** See `docs/execution/PHASE-10.3-CLOSURE.md`. This session was a verification pass over that closure at a later HEAD |
| Branch | `stack` |
| HEAD at session start | `d39227ca`, local == `origin/stack` |
| Verdict | **⚠️ COMPLETE WITH IMPROVEMENTS** — unchanged, and for the same narrow reason: the most useful remaining verification needs one owner action |

The previous version of this file was four days stale. It reported Phase 1 in
progress at `4095cc68` with 1245 tests, while phases 2–10 had since closed and the
suite had grown to 3424. Treat the numbers below as measured on 2026-09-25 and
re-derive them rather than trusting them, per
`.kiro/steering/00-current-owner-overrides.md`.

## Gates, measured this session

```
pytest                                  3429 passed   (3424 before this session)
vitest                                   224 passed
tsc --noEmit                             clean
npm run build                            ok, 536 sitemap URLs (520 blog posts)
check-provider-policy.sh                 OK 8/8
check_provider_policy_live.py            OK          <- was FAILING at HEAD
check_data_model_drift.py --gate          PASSED     <- was FAILING at HEAD
audit_data_model_drift.py --gate          OK, 0 missing
audit_route_auth.py --gate               0 OPEN / 0 DANGLING / 0 UNRESOLVED
verify_public_webhook_auth.py --gate      17/17 live probes
check_design_drift.py --gate             OK
check_ui_labels.py --gate                OK at every severity
verify_no_secrets_in_tree.py             PASS
verify_secret_hook.py                    26/26
block_catastrophic.py --self-test         97/97
GitHub Actions on d39227ca               5/5 success
Dependabot open alerts                   0     (recorded as 40–48 earlier; now clear)
npm audit                                0 vulnerabilities
```

## What this session changed

**Two gates were red at HEAD.** Both are now green, and neither failure was
cosmetic.

**1. A rate limiter that was dead in production.**
`stack-wecare-digital-RateLimitTable` has a single partition key, `id`. But
`amplify/data/resource.ts` declared `identifier([ 'channel', 'windowStart' ])`, and
`lambda_utils/rate_limit.py` followed the declaration — calling `update_item` with a
composite key. DynamoDB answers that with `ValidationException`, the module's bare
`except Exception` caught it, and the function returned `True`. So every caller was
told it was under its limit and **no rate limit was applied at all**.

Proven, not inferred: a read-only `GetItem` with the composite key is rejected with
*"The provided key element does not match the schema"*; `{'id': ...}` is accepted.

The two real consumers were `operations/bulk-worker` and
`messaging/partner-onboarding` — a bulk sender and the partner control plane, which
are the two places a throughput limit matters most.
`messaging/outbound-whatsapp._check_rate_limit` already wrote the correct `id` shape
and is what produced the 143 rows in the table.

Five unit tests passed throughout, because they mock `dynamodb` wholesale so
`update_item` accepts any key. `TestKeySchemaMatchesTheLiveTable` now pins the shape;
4 of its 5 cases fail against the pre-fix file, verified by restoring it from git.

Fail-open is deliberate and was kept. What changed is that a permanent failure
(`ValidationException`, `ResourceNotFoundException`) now logs at ERROR as
`rate_limit_disabled_permanent_error`, so "rate limiting is off" is greppable instead
of looking identical to a transient blip. Exception *text* is no longer logged, only
the type — `.kiro/steering/secret-handling.md`.

**2. Two Lambdas that no supported deploy path could reach.**
`check_provider_policy_live.py` reported `wecare-pstn-softphone` and
`wecare-get-miss-redirect` as `orphan-no-source`. Both had source in
`amplify/functions`, so the label sent a reader hunting for code that was already
there — and hid the real defect.

`wecare-pstn-softphone` serves five live production routes through its `live` alias
(`GET /pstn/session`, `POST /pstn/session/events`, `POST /pstn/session/presence`,
`GET /pstn/diagnostics`, `POST /pstn/token`). `provision_pstn_softphone.py` only
calls `create_function`, `publish_version` and `create_alias` — there is no update
path — so the first provisioning deploy was also the last one. It is now in the
deploy map. That is the same failure already found and fixed for `wecare-crm`.

`wecare-get-miss-redirect` is genuinely externally deployed: CloudFront associates
Lambda@Edge by published **version**, and an alias is not a valid association
target, so the deploy map's publish-then-move-the-alias contract cannot ship it. It
is recorded in `EXTERNALLY_DEPLOYED` with that reason. The finding is now labelled
`orphan-not-in-deploy-map`, which is what it actually detects.

**Also corrected**

- `amplify/backend.ts` claimed `lastUpdatedAt` "is NOT an expiry" and that enabling
  TTL on it "would purge the entire table". Both halves were wrong: every writer sets
  `windowStart + 86400`, and `DescribeTimeToLive` shows TTL already **ENABLED** on
  that attribute with 143 rows intact.
- A true duplicate `Spec("wecare-crm", "core/crm")` at two places in the deploy map;
  the documented one was kept. The adjacent `url-shortener` pair is *not* a
  duplicate — `wecare-url-shortener` and `stack-wecare-url-shortener` are two
  distinct functions.
- `SecureFilesTable` and `DownloadGrantsTable` arrived live with the secure-file work
  without being declared, which is what failed the data-model gate. Both are now
  recorded in `UNDECLARED_ALLOWED` with their measured keys, GSIs and TTL state.

**Correction.** An earlier version of this file said `--dry-run wecare-pstn-softphone`
reported `unchanged=1` and that this proved its packaged code already matched
production. **That was wrong, and the dry run could not establish it.** The dry-run
branch did `tally["unchanged"] += 1` unconditionally, without comparing anything, so
every target was reported unchanged whatever the bytes were. Fixed: dry run now
computes `base64(sha256(zip))` and compares it to the live `CodeSha256`, reporting
`would_update` separately. Re-run truthfully, `wecare-pstn-softphone` **would**
update — its live v1 was packaged by its provisioner, not by this script, so the
bytes differ. No release of it is pending or implied; the claim of equivalence was
simply unfounded.

**3. A live crash on the WhatsApp inbound path — found, fixed, deployed.**
The regenerated inventory flagged 3 functions with errors in 7 days.
`wecare-inbound-whatsapp` had 9, all identical:
`AttributeError: 'str' object has no attribute 'get'` at `wa_internal_event.py:80`.

`json.loads` succeeding does not mean it returned an *object*. A double-encoded SNS
`Message` decodes one level to a `str`, and `.get()` on a `str` raises. The count
understates the impact: `parse` documents that it "is never an exception, because
this sits at the top of an async worker where raising would send a poison event to
the DLQ on every retry" — so each event was retried and re-crashed rather than
skipped. The existing rejection tests covered non-dict *events* but never a non-dict
decoded *Message*.

Deployed: `wecare-inbound-whatsapp` v50→**v51**, `wecare-whatsapp-calling` v23→**v24**
(both bundle the shared module). Rollback versions captured first, read back
independently as `Active`/`Successful`, and 17/17 live webhook probes still pass.

**4. Log retention had regressed, and the guard was blind to it.**
Closure recorded 0 groups without retention; it was 3. The guard scanned one prefix in
one region, and Lambda@Edge defeats that twice: the group is named
`/aws/lambda/us-east-1.<fn>`, and CloudFront writes it **in the region nearest the
viewer**. A 34-region sweep found never-expiring groups in `us-east-1` *and*
`ap-south-1`. All 5 set to 30 days after confirming each held 0 bytes.

**5. 19 registry rows advanced.** `DISCOVERED` went 19 → 4, each of the 4 verified
genuinely open. See `requirement-registry.md` §2026-09-25.

## Recorded gaps that were already closed

The gap list in `.kiro/work/phases-5-10/plan.md` is partly stale. Re-verified closed:

| Gap | State at 2026-09-25 |
|---|---|
| `payment_verified` defaulted `True` | Closed. Four distinct outcomes plus a `PAYMENT_LOOKUP_REQUIRED` flag; the accept/reject decision is deliberately unchanged |
| Invoice sequence injected `WD-PAY-TEMP-` into the GST series | Closed |
| `_save_flow_submission`, the 4th Flow writer | Removed 2026-09-24 after it was shown to have zero callers |
| `invoice-engine` imported `qrcode`, absent from the package | Closed |
| 7 phantom models | `PHANTOM MODELS` now reports **0**. `RateLimitTracker` was never one — the physical table drops the "Tracker" and `EXPLICIT_TABLE` maps it |
| `_money_amount` passed a non-numeric price through | Closed — validates via `Decimal` and returns `''`, which also repairs the caller's fallback chain |
| 40–48 Dependabot alerts | 0 open |
| `origin` cross-request leak in `wix-store` | Genuinely closed. `global origin` at 241 and the reset at 337 are both inside `handler` (next `def` at 339), so the reset does hit the global |

## Open, and honest about it

| Item | Severity | Note |
|---|---|---|
| `apiCall` collapses every non-ok response to `null` | MEDIUM | Real and large: **304** `apiCall<T>()` wrappers inside `src/api/client.ts`. An auth failure, a timeout and an empty table still render the same screen through those. The non-lossy `apiCallResult` exists and `collectApiFailures` is used by 3 surfaces, so the escape hatch is there — but migrating 304 wrappers is a deliberate refactor and was **not** attempted here |
| `origin` still reaches `_response` via a module global | MEDIUM | Leak fixed; only the signature boundary remains. 36 call sites, 2 with an origin to pass, in a handler whose integration is switched off |
| `calling.tsx` falls back to a 0 Hz oscillator when the mic fails | MEDIUM | Left alone deliberately — changing it changes what a caller hears |
| `VoiceCDRTable` has no GSI; readers scan then filter | LOW | Fine at 56 rows, not at 56,000 |
| `amplify/data/resource.ts` is a document, not infrastructure | HIGH (as a claim) | 0 AppSync APIs; 58 models declared vs 79 live tables. Both drift gates now pass, so the divergence is at least *recorded* rather than implied. It still reads like infrastructure |
| `route-auth.yml` live-AWS job has never run | MEDIUM | Gated on `vars.ROUTE_AUTH_ROLE_ARN`, which is unset, so it reports `skipped`. The source half runs and is blocking; the console-drift half is the missing one |
| `AIInteractionsTable` has no writer | LOW | Readers only; the architecture page's claim is unsupported |
| Cognito `VdmOptions.EngagementMetrics` | LOW | Still unverified whether it injects a tracking pixel into OTP mail |

## Waiting on the owner

Each is one action, and none is engineering hiding behind a label.

| Item | Exact unblock |
|---|---|
| **Admin group membership** — the highest-value item | `aws cognito-idp admin-add-user-to-group --user-pool-id us-east-1_cSx0RHCIR --username wecare.digital --group-name Admin`. Re-confirmed live: the pool has `Admin`/`Operator`/`Partner`/`Viewer`, and its only user is in **none** of them. So 16 handlers can be proven to refuse anonymous callers but **not** to return data to a signed-in Admin |
| `ADMIN_MFA_REQUIRED` stays at `warn` | Correct, not an oversight. Flipping it before an Admin exists would refuse the first one. Precondition is the row above |
| Disclosed Cognito client | Delete client `1jrnb80tcvceg7uln9vuoe8va5` (`WECARE.DIGITAL`); it still exists beside `stack-wecare-digital-web`. Not done here: it modifies authentication and cannot be undone with the same client id |
| Provider credential rotation | Razorpay / Google Ads / Google OAuth / Google API key / Bing. `MANUAL_OWNER_ACTION`; Kiro does not touch credential values |
| Full RCS verification | Set a webhook secret on the Sinch Conversation API webhook and store it as `webhook_secret` in `wecare/sinch/rcs`. No code change needed |
| 7 of 8 integrations at `SCOPE_UNVERIFIED` | Provider access. Every unblock is listed on `/growth` |
| Meta MCP servers | Add `http://localhost:7778/oauth/callback` (DevTools) and `http://localhost:7779/oauth/callback` (WhatsApp Business Tools) to app `2238810740192680` |
| Razorpay MCP | Blocked on the provider: its token endpoint advertises only `client_secret_post` |
| Live QA sends and calls | QA recipient `+918100640044` is nominated (`.kiro/steering/02-qa-recipient.md`), but every live-send flag is still absent by design. Enabling one is a separate decision |
| CI live route-auth gate | Set repo variable `ROUTE_AUTH_ROLE_ARN` to a read-only OIDC role |
| Native Android/iOS packaging | POST-PROJECT by owner override; cannot block closure |

## Re-verify anything here

```bash
.venv/bin/python -m pytest -q                          # 3429
npm test && npm run typecheck && npm run build
bash scripts/check-provider-policy.sh                  # 8/8
.venv/bin/python scripts/check_provider_policy_live.py  # live estate
.venv/bin/python scripts/check_data_model_drift.py --gate
.venv/bin/python scripts/audit_data_model_drift.py --gate
.venv/bin/python scripts/audit_route_auth.py --gate
.venv/bin/python scripts/verify_public_webhook_auth.py --gate
.venv/bin/python scripts/check_ui_labels.py --gate
.venv/bin/python scripts/deploy_all_lambdas.py --dry-run   # packages, uploads nothing
```

## Rollback

This session changed no cloud resource, so there is nothing to roll back in AWS.
The code changes revert with `git revert` of the commit named in
`docs/execution/change-authority-matrix.md`.

Lambda alias rollback for the fleet remains
`docs/execution/snapshots/lambda-aliases-before-full-deploy.txt`; any one function
reverts with
`aws lambda update-alias --function-name <n> --name live --function-version <v>`.
Route, integration and API restore commands:
`docs/prohibited-provider-retirement.md`.
Permissions: `python scripts/apply_unattended_permissions.py --user --restore`.


## 2026-10-08 — WhatsApp customer ideas

| Class | Target | Evidence | Rollback |
|---|---|---|---|
| A1_LOCAL | WD_Leave_Review_v2 Flow JSON, inbound handler, customer_ideas helper, Flow Responses display and focused tests | Owner requested required aspirational thought, working Next/Submit and backend/contact saving. 78 Python tests and 1 frontend test pass; TypeScript and production build pass. | Revert this scoped commit. |
| A3_PRODUCTION | wecare-inbound-whatsapp code and live alias | Existing live 79 and code hash captured before update. Built archive preserves all existing live members, replaces handler.py and adds customer_ideas.py only. New version 80 is Active/Successful, live points to 80. Code SHA256 sIO3xStfy05MJw0P8oTD4dYbG3i/t9qd9Ps0L/h+75A=. | Move live alias back to 79 using current revision guard. |
| A2_REMOTE_CODE | Explicit scoped files on origin/stack | Standing authorization; fetched HEAD and origin/stack both 978eb2c9344fddc22696f90cbaf6e8c3dc139727 before commit. Non-force push. | Revert scoped commit and push stack. |
| A3_PRODUCTION | Amplify d22dm4b0jn71jw stack automatic build | Read app/branch before push: repository wecare-digital/wecare-digital, platform WEB, auto build enabled, prior active job 1432. No configuration or secret changes. | Revert scoped commit and rebuild. |

Storage: stack-wecare-digital-FlowSubmissionTable holds the authoritative idea; stack-wecare-digital-SubmitRequestsTable holds a stable flow_log contact activity projection. Both already exist, role access verified; no schema/IAM mutation. Trusted webhook sender resolves the contact, never handset-supplied IDs. Duplicate delivery repairs the activity projection. No outbound messaging, public review, payment, or sales-lead creation.

Meta Flow 1578178897413815 remains a saved draft. Interactive preview validates required input, navigation, preserved thought and Submit completion. Removed explicit 500 character limit; native Meta limit still applies. Real WhatsApp-to-storage QA is WAITING_FOR_OWNER: supply an authorised test recipient. Preview completion is not evidence of a production submission. No real customer messages sent.


### 2026-10-08 — Balanced Flow brand lockup

A1_LOCAL / A2_REMOTE_CODE: owner supplied website screenshot as the brand proportion reference. Enlarged the Inter ExtraBold wordmark from 43px to 56px, increased the icon-to-wordmark gap, vertically centred both lines, retained the red dot. Updated both embedded Flow banners. Structural comparison confirms all form fields, routing and completion payload remain identical. Meta Run validates zero errors and Save persists the draft. Rollback: revert this asset-only commit. No Lambda or frontend source change.
