# Phase 05 — current-truth discovery and the deploy-readback closures

Opened 2026-09-26. Authority classes exercised: `A0_READ` throughout,
`A1_LOCAL` for one new script, `A3_PRODUCTION` for five Lambda deployments.
No `A4_DESTRUCTIVE` action was taken.

Tree at start `1efd670c`; remote had moved to `5653a12a` and then `6ffcbcef`
while this ran, because two other warm sessions share this working tree. Work
committed from this session: `5ab9fc66`.

**Amended after `df67e7f3`.** Three gap-register rows added — `SEC-POLLY-001`,
`SEC-DOMAIN-001`, `SEO-404-001` — and `OBS-DLQ-001` closed, since `df67e7f3`
repaired the alarms it describes. The three additions are `A0_READ` findings drawn
from evidence already committed (entries 182, 225, 234, 249, 254 of the
change-authority matrix, and `runtime-inventory.json`); **no new live measurement
was taken for them**, and each names the live read it still needs. They are logged
here rather than left in conversation.

Everything below was measured in this session. Dated counts from the master
prompt and from steering were **not** carried forward — where they disagree with
a measurement, the measurement is recorded and the stale figure is named.

---

## 1. Controller-state table

| ID | Requirement | State | `proven_through` |
|---|---|---|---|
| `ENV-INV-001` | Fresh full-account AWS inventory | `LIVE_VERIFIED` | `aws_account_inventory.py`, 0 collector errors, 2026-09-26T03:28Z |
| `SEC-ROUTE-001` | Route authorization, full live inventory | `LIVE_VERIFIED` | `audit_route_auth.py`: 361 routes, 0 OPEN |
| `SEC-WAF-001` | WAF live and associated | `LIVE_VERIFIED` | web ACL → 2 Cognito pools; Amplify `ASSOCIATION_SUCCESS` |
| `DEP-READBACK-001` | Per-file proof of what each `live` alias runs | `LIVE_VERIFIED` | `check_deployed_source.py`, 62 functions |
| `SEC-SITELANG-001` | Unauthenticated Polly + open translate proxy closed | `LIVE_VERIFIED` | v6→v7; 200→404 on `/voices`, 403 on `/translate` |
| `DEP-STALE-001` | Stale rate limiter reached its two callers | `LIVE_VERIFIED` | bulk-worker v16, partner-onboarding v16, 83/83 files identical |
| `DEP-STALE-003` | Softphone artifact carries current `middleware.py` | `DEPLOYED` | v1→v2, 83/83 identical; behind feature flag, so not live-verifiable |
| `RET-PAYU-001` | PayU permanently absent | `LIVE_VERIFIED` | `DeleteSecret` 2026-08-26 window=30; now `ResourceNotFoundException` |
| `RET-SINCHSMS-001` | Sinch SMS retired, India RCS retained | `DEPLOYED` | `wecare/sinch/sms` in window; `wecare/sinch/rcs` untouched |
| `RET-ELEVENLABS-001` | ElevenLabs surface absent at runtime | `DISCOVERED` | 6 Lambdas + 3 HTTP APIs + 1 table absent; 6 CFN stacks + 1 IAM role remain |
| `PROV-POLICY-001` | Provider policy, static and live | `LIVE_VERIFIED` | both gates green, 361 routes scanned |
| `PSTN-PLIVO-001` | Plivo voice-only, protected binding intact | `LIVE_VERIFIED` | `plivo-reconcile` all PASS; `+918031830030` → app `12775976954213184` |
| `PAY-RZP-001` | Razorpay is the only gateway, correct secret path | `LIVE_VERIFIED` | `verify_razorpay_secret_path.py`: new path resolves, old returns 501 |
| `META-SUB-001` | Meta subscription ownership | `DISCOVERED` | 2 apps subscribed to WABA1 and WABA2; WABA3 read returns 400 |
| `SEC-CODEQL-001` | High static-analysis findings remediated or triaged | `BLOCKED` | 206 open HIGH, **0 triaged** |
| `OBS-TRAIL-001` | Management-event audit trail | `DISCOVERED` | 0 CloudTrail trails, 0 event data stores |
| `NOTIF-DOMAIN-001` | Unified connected-call notification domain | `DEPLOYED` | 4 tables + queue + DLQ live, PITR on, 0 rows; consumer ESM **Disabled** |
| `WA-E2E-001` | WhatsApp inbound→reply→`wamid` reconciliation | `WAITING_FOR_OWNER` | artifacts current; needs an authorized handset round trip |

---

## 2. What the fresh inventory changed

`docs/execution/aws-inventory.{json,md}`, regenerated with 0 collector errors.

| Item | Master-prompt snapshot | Measured 2026-09-26 |
|---|---|---|
| Lambda functions | 58 | **65** (58 with a `live` alias) |
| HTTP APIs | 2 | **1** (`zllr9lrg7j`, stage `prod`, auto-deploy) |
| HTTP API routes | 332 | **361** |
| Regional WAF web ACLs | 0 | **1**, associated to both Cognito pools |
| CloudFront-scope WAF | not stated | **1**, attached to Amplify `d22dm4b0jn71jw`, `ASSOCIATION_SUCCESS` |
| DynamoDB tables | not stated | 79 |
| Secrets | not stated | 31, of which 5 in a deletion recovery window |

The WAF line is the one worth dwelling on, because the inventory script had a
defect that manufactured a false CRITICAL. `ListResourcesForWebACL` defaults
`ResourceType` to `APPLICATION_LOAD_BALANCER`, and this account has no load
balancers, so a single call reports every regional web ACL as protecting nothing.
Asking for all seven regional resource types shows `wecare-cognito-waf` attached
to `us-east-1_46ULYuukt` and `us-east-1_cSx0RHCIR`. A CloudFront-scope ACL has no
such API at all, and an Amplify app's distribution is AWS-owned so it never
appears in `ListDistributions` — the only readable proof is the app's own
`wafConfiguration`. Two further defects in the same collector set: `sesv2
list_email_identities` has no paginator, so the SES section came back empty and
read as "no verified sender" while `one@wecare.digital` is in fact verified with
DKIM `SUCCESS`. All three were fixed in `scripts/aws_account_inventory.py`.

**Two HTTP APIs is not simply stale — it is a phantom.** Six CloudFormation
stacks still declare three HTTP APIs (`gr7vx195g6`, `ppq3shpmbd`, `2sz7b19ugc`),
six Lambdas and one DynamoDB table for the retired ElevenLabs integration. Every
one of those resources returns `ResourceNotFoundException`; they were deleted
outside CloudFormation. What survives is `wecare-elevenlabs-postcall-role` (inline
policy `postcall`, last used 2026-09-20T04:19Z) and the six stacks themselves,
which are a live recreation path: any `update-stack` or drift remediation would
rebuild retired-provider infrastructure. Templates exported with checksums to
`docs/retirement-exports/` so the rollback record exists before anyone proposes
deleting them.

### New gaps found by the inventory

| Gap | Severity | Detail |
|---|---|---|
| No CloudTrail trail | HIGH | 0 trails, 0 event data stores. The 90-day console event history is still queryable — it is what dated the secret deletions below — but nothing is retained past 90 days and nothing is queryable with Athena |
| 3 DLQs with no alarm | MEDIUM | `stack-wecare-digital-{inbound,notification,outbound}-dlq` |
| 2 alarms watch queues that do not exist | MEDIUM | `wecare-inbound-dlq-depth`, `wecare-outbound-dlq-depth` point at `base-wecare-digital-*`; they can never fire, so the DLQ they were meant to cover is unmonitored twice over |
| `E2GP22R4BIFGQ3` min TLS `TLSv1` | MEDIUM | the other two distributions are `TLSv1.2_2021` |
| Customer pool deletion protection `INACTIVE` | LOW | `us-east-1_46ULYuukt`; the admin pool has it `ACTIVE` |
| `ap-south-1` SES has no production access | LOW | sandbox only; India SMS uses sender ID `WDBEEP`, not SES, so nothing is broken today |

---

## 3. The deploy readback, and why the existing dry run could not do it

`deploy_all_lambdas.py --dry-run` reported `would_update=56` of 62, including
functions untouched for weeks. That is not 56 stale functions. Every zip embeds
`amplify/functions/shared/lambda_utils/`, so one commit to a shared module
changes all 62 package hashes at once. An aggregate zip hash cannot answer the
question the brief asks, which is whether a specific pushed fix is in the artifact
production executes.

`scripts/check_deployed_source.py` (new, commit `5ab9fc66`) downloads the artifact
the `live` alias points at and diffs each file inside it against the working tree.
That turned 56 opaque drifts into 10 distinct stale files:

| Stale file | Artifacts | Actually executed by | Verdict |
|---|---:|---|---|
| `lambda_utils/rate_limit.py` | 55 | `bulk-worker`, `partner-onboarding` only | **real gap** |
| `lambda_utils/wa_internal_event.py` | 55 | `inbound-whatsapp`, `whatsapp-calling` only | no gap — both already current |
| `site-language/handler.py` | 1 | itself | **real gap, and live** |
| `voice-in-obd/handler.py` | 1 | itself | **real gap** |
| 7 modules on `pstn-softphone` | 1 | itself | **real gap** |

The distinction matters and is checkable rather than asserted:
`lambda_utils/__init__.py` imports `rate_limit`, so it loads in all 62, but
`check_rate_limit` is called from exactly two handlers — and commit `854b60e4`
fixed a limiter that never applied, which is a logic defect, not an import-time
one. `__init__.py` does **not** import `wa_internal_event`; only two handlers do,
and both were current. So 51 artifacts carry a stale copy of a module they never
load. Per rule 34 — deploy only the affected dependency closure — those were left
alone; the next ordinary deploy of each clears them.

### `SEC-SITELANG-001` — the finding that was live

Deployed `wecare-site-language` v6 (2026-09-25T05:01Z) predated the removal of the
Amazon Polly read-aloud surface. The repository had deleted `GET
/site-language/voices` and `POST /site-language/tts` and added an Origin
allowlist to `/translate`. The API Gateway routes were never removed, and the
integration points at `:live`. Measured before the fix:

```
GET https://wecare.digital/api/site-language/voices   -> 200, 19,835 bytes
                                                          (full Polly voice catalogue)
POST .../site-language/translate  (no Origin)         -> reached the handler,
                                                          which had no Origin check
```

Unauthenticated, on the production custom domain, billable, with no consumer —
the in-repo comment puts the `/tts` ceiling near $0.67 per second at the shared
15 rps throttle. `POST /tts` was **not** probed, deliberately: invoking it would
have incurred the charge the finding is about, and the route plus the readback are
sufficient evidence.

Fixed by deploying, not by editing. `tests/test_site_language_origin.py` 9 passed,
then v6 → v7. After:

```
GET  /site-language/voices     -> 404 {"error": "Not found"}      (handler, not gateway)
POST /site-language/tts        -> 404 {"error": "Not found"}
GET  /site-language/languages  -> 200                             (retained, correct)
POST /site-language/translate  -> 403 {"error": "Not allowed from this origin"}
                                  for both absent and hostile Origin
```

125 invocations, 0 errors, 0 throttles over a 20-minute window that straddles the
deploy — so it proves no error spike, not a clean post-deploy period in isolation.
Readback: `handler.py` byte-identical to the tree.

This also exposes a blind spot in `audit_route_auth.py`, which reports 0 OPEN
routes. It greps **local handler source** for auth markers. Local source had
already deleted these routes, so the audit could not see that the deployed
artifact still served them. Route-auth proof is only as current as the artifact.

### The Polly grant is three declarations, and one of them has live consumers

Recorded because the obvious follow-up to `SEC-SITELANG-001` — "revoke the Polly
grant" — is wrong in three separate ways, and each was checked rather than assumed.

**It is not in the Amplify backend definition.** The site-language grant is
`scripts/deploy_site_language.py:104-106`, an inline policy named
`wecare-site-language` put on role `wecare-digital-lambda-role`. That is an edit in
this repo plus a re-run of the script, not a backend deploy.

**Polly is declared three times, and two of the three are load-bearing:**

| Where | Grants | Consumer |
|---|---|---|
| `scripts/deploy_site_language.py:104` | `DescribeVoices` + `SynthesizeSpeech` | none — this is the dead one |
| `amplify/iam-policies.ts:316-328`, mapped at `:363` via the `polly` group | both | `wecare-whatsapp-voice` — live |
| `scripts/iam-policy-update.json:145` | `SynthesizeSpeech` | third declaration, unattributed |

`whatsapp-voice/handler.py:42` builds a Polly client at module scope and serves
`GET /whatsapp-voice/voices`; `whatsapp-calling/handler.py:1429` does the same and
`voice-in/obd/handler.py:392` calls `synthesize_speech` directly;
`voice-aws/handler.py:39` carries a Polly voice id. Revoking Polly account-wide
breaks WhatsApp voice notes and the IVR prompt path. **"Revoke" is the wrong verb.**

**And narrowing the site-language policy may not reduce site-language's effective
permissions at all.** Permissions attach to the role, not the function, and
`runtime-inventory.json` confirms `wecare-site-language` and
`wecare-whatsapp-voice` both run as `wecare-digital-lambda-role` — the script's own
comment calls that role "shared with every other Lambda in the account". So
deleting the two Polly actions from one inline policy leaves the `polly` group
still granting them on the same role. Genuinely denying Polly to site-language
means a least-privilege role of its own, which is the pattern entry 142 already
established for the Cognito trigger.

The narrowing edit is worth doing as **cleanup**, and must not be written up as
closing the exposure. Per entry 182 — read the live policy document, because IaC
and account can disagree — the effective-permission claim needs
`list-role-policies` + `list-attached-role-policies` on the live role before anyone
records it as fixed. Not done in this session.

### Deployments made

Rollback baseline captured before each; all four then read back with all 83 files
byte-identical.

| Function | `live` before | after | Focused tests |
|---|---|---|---|
| `wecare-site-language` | v6 | **v7** | `test_site_language_origin.py` 9 passed |
| `wecare-bulk-worker` | v15 | **v16** | `test_rate_limit`, `test_middleware`, `test_pstn_softphone`, `test_pstn_browser_token` — 138 passed |
| `wecare-partner-onboarding` | v15 | **v16** | as above |
| `wecare-voice-in-obd` | v17 | **v18** | as above |
| `wecare-pstn-softphone` | v1 | **v2** | as above |

Rollback: `aws lambda update-alias --function-name <f> --name live
--function-version <6|15|15|17|1>`. No alarm entered ALARM.

---

## 4. Provider retirement — dated, not asserted

CloudTrail's 90-day event history answers the recovery-window question that
`ListSecrets` cannot, since `DeletedDate` there is the request time and the window
length is only in the API call:

| Secret | `DeleteSecret` | Window | Permanent absence |
|---|---|---:|---|
| `wecare/payu` | 2026-08-26T10:10:20Z | 30 | **already elapsed — `ResourceNotFoundException` confirmed** |
| `wecare/airtel-iq` | 2026-09-20T01:46:18Z | 30 | ~2026-10-20T01:46Z |
| `wecare/airtel/c2c` | 2026-09-20T01:46:18Z | 30 | ~2026-10-20T01:46Z |
| `wecare/airtel/obd` | 2026-09-20T01:46:18Z | 30 | ~2026-10-20T01:46Z |
| `wecare/airtel/sms` | 2026-09-20T01:46:19Z | 30 | ~2026-10-20T01:46Z |
| `wecare/sinch/sms` | 2026-09-20T01:46:19Z | 30 | ~2026-10-20T01:46Z |
| `wecare/wix-api-key` | 2026-09-23T02:36:45Z | force | immediate |
| `wecare/elevenlabs` | 2026-09-20T08:50:01Z | force | immediate |

Also confirmed `ResourceNotFoundException`: `wecare/payu/api`,
`wecare/sinch/voice`, `wecare/sinch/whatsapp`, `wecare/plivo/sms`.
`wecare/sinch/rcs` is present and untouched, as required.

Both gates green: `check-provider-policy.sh` (8 rules) and
`check_provider_policy_live.py` (361 routes, no untracked violations).
Event source mappings: 2 total, both pointing at functions that exist — no
obsolete mapping. Repository recreation paths for ElevenLabs: one hit, in
`check_provider_policy_live.py` itself, which names it as retired and must stay.

---

## 5. Meta, Plivo, Razorpay

**Meta** — two apps are subscribed to the same WABAs: `2238810740192680`
(WECARE.DIGITAL) and `1143680903703001` (Business Agent), both on WABA1
`2094615664435155` and WABA2 `2513394156072604`. WABA3 `1055232054343117` returns
HTTP 400 on the subscription read, and the app-level callback read returns code
104, so the callback URL could not be enumerated with the token available. Those
two are `RUNTIME_INVENTORY_REQUIRES_VERIFICATION`, not evidence of absence. No
number was deregistered and no subscription removed. Separately,
`socialmessaging list_linked_whatsapp_business_accounts` returns `[]`, which is
positive confirmation that AWS Social is not the WhatsApp transport.

**Plivo** — one application `WECARE-WHATSAPP-IVR` (`12775976954213184`), number
`+918031830030` bound to it unchanged, SIP endpoint bound to the same app, answer
/ fallback / hangup callbacks all on `wecare.digital/api` carrying the same token
fingerprint. Every assertion PASS. Voice only; no SMS surface.

**Razorpay** — `wecare/razorpay/api` resolves with both fields populated; the old
`wecare/razorpay-webhook` path carries only `webhook_secret` and would return 501.
The fix is confirmed on the current tree. No value printed.

---

## 6. Security backlog — the hard gate

| Rule | Lambda | Scripts | Frontend | Total |
|---|---:|---:|---:|---:|
| `py/clear-text-logging-sensitive-data` | 134 | 58 | — | **192** |
| `py/weak-sensitive-data-hashing` | 6 | 3 | — | 9 |
| `js/insecure-randomness` | — | — | 2 | 2 |
| `py/bad-tag-filter` | 1 | — | — | 1 |
| `js/xss-through-dom` | — | — | 1 | 1 |
| `js/clear-text-storage-of-sensitive-data` | — | — | 1 | 1 |
| | | | | **206** |

All HIGH. **Dismissed or formally triaged: 0.** Open Dependabot alerts: 0.

Rule 28 requires every open high-severity finding to be either remediated or
formally triaged with evidence, so this is a release gate that is currently
failing, and the count is the reason it cannot be waved through: 192 of 206 are a
single rule, which usually means one logging idiom repeated rather than 192
independent defects. The steering is explicit that suppression is not the
remedy — remove the log line or derive the logged value from something that never
touched the secret — and that CodeQL tracks taint across function boundaries, so
reducing a secret to a boolean does not launder it.

---

## 7. Notification domain — built, deployed, deliberately off

`scripts/provision_notification_domain.py --verify` state holds:
`NotificationEvents`, `NotificationDeliveries`, `NotificationAttempts`,
`NotificationOutbox`, all with PITR enabled and **0 rows**; queue and DLQ present
with redrive `maxReceiveCount` 3 and depth 0.

The consumer is off by intent, not by accident: the event source mapping on
`stack-wecare-digital-notification-queue` → `wecare-notification-worker:live` is
`Disabled`, `USER_INITIATED`, since 2026-09-22T07:02Z. `NOTIF_CUTOVER_WATERMARK`
is absent in production and absent means suppress everything, so enabling the
domain without setting it yields zero sends rather than a backfill.

Meanwhile the only follow-up customers actually receive is still
`plivo-answer`'s post-call SMS, triggered by **hangup** — a trigger the brief
prohibits — at 32 sends per 14 days. Turning it off before the replacement is
live would remove a real customer touchpoint and deliver nothing in its place, so
it stays until `PSTN_CONNECTED_NOTIFICATIONS_ENABLED=true` plus a watermark plus a
QA round trip. Enabling a live-send path is outside the standing grant.

---

## 8. Gap register

| ID | Severity | Impact | Cause | Workaround | Next action | Est. |
|---|---|---|---|---|---|---|
| `SEC-CODEQL-001` | HIGH | Release gate fails; real leaks could hide in the noise | 192 instances of one logging idiom, never triaged | none | Fix the idiom at source in `lambda_utils`, then re-scan; triage the residue individually | 16–24 h |
| `OBS-TRAIL-001` | HIGH | No management-event audit beyond 90 days; no Athena query path | No trail ever created | 90-day console history | Create one multi-region trail to an SSE-KMS bucket | 1–2 h |
| `RET-ELEVENLABS-001` | MEDIUM | 6 CFN stacks can recreate retired-provider infrastructure | Resources deleted outside CloudFormation | stacks are inert unless updated | `A4` gate: delete 6 stacks + `wecare-elevenlabs-postcall-role`; templates already exported | 1 h |
| `SEC-SITELANG-002` | MEDIUM | `/voices` and `/tts` routes still exist, now 404 | Routes were never deleted with the code | handler 404s them | `A4` gate: delete both routes; target Lambda exists so this is outside the standing grant | 30 m |
| `OBS-DLQ-001` | MEDIUM | 3 DLQs unmonitored; 2 alarms can never fire | Alarms point at `base-wecare-digital-*`, queues are `stack-wecare-digital-*` | none | **Closed in `df67e7f3`** — 2 alarms repointed, notification DLQ alarm added, statistic corrected to `Maximum > 0`; 33 alarms also given a human subscriber | done |
| `SEC-POLLY-001` | LOW | Dead Polly grant persists on the shared Lambda role; the grant cannot be revoked account-wide because it has live consumers | 3 separate declarations; `deploy_site_language.py:104-106` writes the dead one onto a role shared account-wide | none needed — no route reaches it since v7 | Narrow `deploy_site_language.py` and re-run (**cleanup, not closure**). Real fix is a least-privilege role for site-language, per entry 142. Confirm effective permissions with a live `list-role-policies` read before recording as fixed | 30 m edit; 2 h for the role |
| `SEC-DOMAIN-001` | MEDIUM | The Amplify app is configured to answer **every** `*.wecare.digital` name, bound to branch `stack` | Domain association carries a wildcard subdomain entry: `* CNAME d2av2go6w170k.cloudfront.net` with `prefix` absent and `branchName: stack` | Latent, not live: entry 234 verified **no** wildcard CNAME in Route 53, so an unconfigured name NXDOMAINs rather than reaching the app | Decide whether the wildcard entry should exist. First a live read — Amplify `GetDomainAssociation` plus the zone — since the only evidence today is a pre-teardown snapshot. `A3` if removed | 1 h |
| `SEO-404-001` | MEDIUM | Every unknown **path** serves the full home page under an HTTP 404 — wrong for crawlers, and the address bar keeps the bad URL | `/<*> -> /index.html` at `NOT_FOUND_REWRITE`, the last of the 20 Amplify custom rules | none | Add a real 404 page, or accept and document. Note `[retired public path 169e0fd8]/logs` now lands here too (entry 256) | 2 h |
| `DEP-STALE-004` | LOW | 51 artifacts carry a stale unused `wa_internal_event.py` | Shared module changed after their last deploy | none needed — not loaded | Let ordinary deploys clear it; do not fleet-deploy for this | 0 |
| `SEC-TLS-001` | LOW | `E2GP22R4BIFGQ3` accepts TLSv1 | Distribution predates the policy | none | Raise to `TLSv1.2_2021` | 15 m |
| `META-SUB-001` | LOW | Cannot enumerate WABA3 subscription or the app callback URL | Token lacks the scope | — | Owner/provider: token with `whatsapp_business_management` over WABA3 | blocked |
| `WA-E2E-001` | — | WhatsApp E2E remains `DEPLOYED`, not `LIVE_VERIFIED` | Needs a handset round trip | — | Authorized QA send to `+918100640044` | 1 h once authorized |

---

## 9. Status groups

**`LIVE_VERIFIED`** — AWS inventory · route authorization (0 open of 361) · WAF
association · per-file deploy readback · site-language exposure closed · rate
limiter reaching its callers · PayU permanently absent · provider policy static
and live · Plivo voice-only
with protected binding intact · Razorpay secret path.

**`ENGINEERING REMAINING`** — 206 HIGH CodeQL findings · CloudTrail trail ·
TLS floor on one distribution · the wildcard subdomain decision · a real 404
page · least-privilege role for site-language · unified notification cutover
(code done, flags off) · duplicate producer retirement · Web Phone completion ·
customer identity and OTP · page composer · commerce, order,
billing and tracking · frontend consolidation · CRM, growth, MCP · native shells.

**`WAITING_FOR OWNER/PROVIDER`** — WhatsApp handset round trip · connected-call
QA sends · `PSTN_CONNECTED_NOTIFICATIONS_ENABLED` and the cutover watermark ·
provider credential rotation · Meta token scope for WABA3 · the `A4` gates for the
6 ElevenLabs stacks, the IAM role and the 2 dead routes.

**`IMPROVEMENT BACKLOG`** — clear the 51 stale unused module copies through
ordinary deploys · Cognito customer-pool deletion protection · `ap-south-1` SES
production access if SES is ever needed there · retire the 6 retired-provider log
groups once their retention value expires.

---

## 10. Completion

Weighted controller completion and genuinely-`LIVE_VERIFIED` weight are
deliberately **not** stated here. Both are properties of the whole requirement
registry, which spans roughly 250 requirements, and this phase measured a slice of
it. Quoting a percentage from a slice is exactly the aggregate-behind-which-a-
blocker-hides that rule 39 forbids. `docs/execution/requirement-registry.md`
remains the place those two numbers belong, once the registry itself has been
re-scored against the measurements above.

What can be said without inventing a denominator: one live unauthenticated and
billable production surface was found and closed with before-and-after evidence,
one pushed fix was found not to have reached either of its two real callers and
now has, and the "0 WAF web ACLs" and "2 HTTP APIs" figures that have been
carried through several reports are both wrong — the first understates the
security posture, the second counts three APIs that do not exist.
