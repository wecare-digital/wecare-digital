# Permanent requirement registry

Authoritative source of requirement state. `docs/master-requirement-coverage.md`
is generated from this file; never maintain a second conflicting truth.

IDs are permanent. Never renumber, never silently delete. A superseded row keeps
its ID and names its replacement.

**States:** `DISCOVERED` `CODE_COMPLETE` `TESTED` `PUSHED` `DEPLOYED`
`LIVE_VERIFIED` `WAITING_FOR_OWNER` `WAITING_FOR_PROVIDER` `BLOCKED`
`NOT_APPLICABLE` `SUPERSEDED`. Waiting/blocked rows also carry `proven_through`.

## 2026-09-25 state advancement

**19 rows were advanced in place on 2026-09-25** (`EV-0041`). They had been seeded on
2026-09-21 and never moved, so they still read `DISCOVERED` for work that phases 2–10
shipped on 2026-09-24 — the registry was contradicting
`docs/execution/PHASE-10.3-CLOSURE.md`, and this file is supposed to be the one place
state changes. `DISCOVERED` went from **19 to 4**.

The `Current` column therefore mixes measurement dates. A cell dated 2026-09-25 was
re-measured; the rest still read as at 2026-09-21. Each advanced row cites `EV-0041`.

Four rows were verified open rather than left stale. **Two of them were then closed
later the same day** by a retired-provider sweep; both rows are now retired from this
registry. The two still open:

| Row | Verified on 2026-09-25 | Now |
|---|---|---|
| `SEC-ROUTE-008` | Zero `Admin` checks in the three destructive handlers | ⏳ still open. Blocked behind Admin group membership, which nobody holds |
| `OPS-002` | Not re-measured inline | ⏳ re-derived as **117** route paths with no frontend caller (the earlier 95 was stale against 361 live routes). Classification is the next action |

So `DISCOVERED` stands at **2**, not 4.

Two rows were advanced only to a corrected `Current` and left at their prior state
because nothing proved a higher one: `NOTIF-STORE-002` and `OPS-003` stay
`CODE_COMPLETE`.

Seeded 2026-09-21 at HEAD `4baf4236`. Weights below are the program weights from
`bw-crm.md` §00, redistributed across rows as each domain is decomposed in Phase 1.

| Domain | Weight |
|---|---:|
| Security, identity, protected assets, provider retirement (`SEC`, `PROV`) | 15 |
| WhatsApp messaging and Calling (`WA`, `WAC`) | 14 |
| Canonical notifications, AWS SMS, RCS (`NOTIF`, `SMS`, `RCS`) | 14 |
| PSTN Voice API, Browser SDK, calling ops (`PSTN`) | 14 |
| Payments, contacts, CRM (`PAY`, `CRM`) | 10 |
| Governed MCP / dashboard AI (`MCP`) | 8 |
| Growth APIs and commerce (`GROW`) | 7 |
| Frontend IA / design / tutorials (`UI`) | 8 |
| Android/iOS and device optimization (`NATIVE`) | 4 |
| Tests, observability, deployment, DR (`TEST`, `OPS`, `DEPLOY`, `CLEAN`) | 6 |

## Owner-override adjustments applied

Per `.kiro/steering/00-current-owner-overrides.md`, which outranks `bw-crm.md`:

- `SEC-MFA-001` is a **required target** but **not a blocking gate**. It cannot hold
  project closure hostage; it must still be built.
- `SEC-WAF-001` is **WITHDRAWN as of 2026-09-28.** The owner deleted both web ACLs as a
  cost decision and withdrew the required target in `00-current-owner-overrides.md`, so
  this row is no longer work to do. It is kept rather than deleted because the
  requirement was previously `LIVE_VERIFIED`, and a requirement that goes from verified
  to absent should show that transition rather than vanish.
- Security Hub is `NOT_APPLICABLE` by owner decision (`SEC-SHUB-001`).
- GuardDuty is optional and non-blocking (`SEC-GD-001`).
- All `NATIVE-*` rows are **POST-PROJECT**. The web app must only stay
  WebView/WKWebView-ready. They do not block closure.

## Registry

| ID | Requirement | Source | Current (measured 2026-09-21) | Target | State | proven_through | Evidence | Blocker | Next action |
|---|---|---|---|---|---|---|---|---|---|
| `SEC-BASE-001` | Rediscover git/AWS/provider state before each phase; never reset to a historical SHA | overrides | HEAD `4baf4236`, 28 commits past the brief's snapshot | Re-measured at every phase entry | `LIVE_VERIFIED` | — | `EV-0001` | — | Repeat at Phase 1 entry |
| `SEC-SNAP-001` | Protected-resource snapshot before any mutation | Phase 0 | Published | Refreshed per phase | `LIVE_VERIFIED` | — | `EV-0002`..`EV-0006` | — | Re-read Meta/Plivo rows before any provider write |
| `SEC-CRED-001` | Exposed Razorpay / Google Ads / Google OAuth / Google API key / Bing credential families | brief Part E | Inventoried by secret reference only; no value read | Owner replaces manually | `WAITING_FOR_OWNER` | `DISCOVERED` | `EV-0004` | Owner action, outside this plan | Keep dependent live checks pending |
| `SEC-ROUTE-001` | `/webhook/sinch-rcs` GET+POST was unauthenticated at gateway **and** handler; could forge messages and trigger outbound RCS sends | Phase 0 finding | Sinch raw-body HMAC enforced in `rcs-dlr` live v7; unsigned forged inbound refused | Strict verification once a webhook secret exists at Sinch | `LIVE_VERIFIED` | — | `EV-0012`, `EV-0014`, `EV-0015` | Interim: delivery receipts still processed unverified (see `SEC-ROUTE-006`) | Owner configures a webhook secret at Sinch |
| `SEC-ROUTE-002` | `POST /whatsapp/inbound` was unauthenticated; consumed legacy SNS envelope; `action=create_invoice` ran before any auth | Phase 0 finding | Meta `X-Hub-Signature-256` enforced for HTTP events in `inbound-whatsapp` live v38; `create_invoice` internal-only | Same | `LIVE_VERIFIED` | — | `EV-0013`, `EV-0014`, `EV-0015` | — | Consider deleting the redundant public route in Phase 9 |
| `SEC-ROUTE-003` | `scripts/audit_route_auth.py` scanned only one API and missed the `inbound-whatsapp-handler` directory mapping | Phase 0 finding | Discovers all HTTP APIs; UNRESOLVED 4 → 0; DANGLING is its own class; `--strict`/`--json` added | CI gate once the weak-marker backlog is triaged | `PUSHED` | `TESTED` | `EV-0012` | — | Enable `--gate` after `SEC-ROUTE-005` |
| `SEC-ROUTE-004` | Explicit authentication strategy for every user API route | overrides | 327 routes, 0 authorizers, **0 OPEN**, 0 dangling, 0 unresolved across both APIs | Documented per-route decision + negative tests | `DEPLOYED` | `DEPLOYED` | `EV-0016` | — | Fold the strict-mode backlog in |
| `SEC-ROUTE-005` | 30 routes across 7 handlers had **no caller authentication at all** — the audit had accepted outbound credentials and a CORS string as proof | Phase 0 finding, triaged 2026-09-21 | `require_auth` applied at every entry; url-shortener guarded per route; 5 routes allowlisted with reasons; weak markers retired from the default set | Same, enforced in CI | `LIVE_VERIFIED` | — | `EV-0021`..`EV-0029` | — | Consider role tightening (`Admin`) on the destructive clear-logs routes |
| `SEC-ROUTE-008` | Destructive routes authenticate any signed-in user rather than requiring `Admin` | 2026-09-21 | Still open 2026-09-25. Zero `Admin`/`require_admin` checks in `voice-in/obd`, `voice-in/c2c` or `url-shortener` handlers | `require_auth(event, 'Admin')` after confirming group membership | `DISCOVERED` | — | `EV-0041` (2026-09-25 re-measurement) | Sole pool user is in **no** group; tightening now would lock out the only operator | Blocked behind `admin-add-user-to-group`; tighten immediately after |
| `SEC-ROUTE-006` | While no Sinch webhook secret exists, unverified `MESSAGE_DELIVERY` callbacks are still processed, so forged receipts could alter message status | interim posture | Justified by measurement: 313/313 callbacks in 7 days were `MESSAGE_DELIVERY`; zero inbound, zero opt events | Strict verification of all event types | `DEPLOYED` | `DEPLOYED` | `EV-0012`, `EV-0017` | Owner must set a webhook secret at Sinch and store it as `webhook_secret` in `wecare/sinch/rcs` | Self-heals with no code change once the secret exists |
| `SEC-MFA-001` | Administrator MFA implemented and verified | overrides | Cognito `MfaConfiguration=OPTIONAL`, TOTP + email + SMS enabled; 4 groups exist | TOTP enforced for admin role | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `docs/execution/PHASE-10.3-CLOSURE.md` | `ADMIN_MFA_REQUIRED` stays at `warn` until an Admin with a factor exists | Flip to enforce once the sole user is in `Admin` |
| `SEC-WAF-001` | ~~WAF implemented and live-verified~~ **WITHDRAWN 2026-09-28** | overrides | **0 WebACLs** — both deleted 2026-09-28 by owner cost decision | n/a, requirement withdrawn | `LIVE_VERIFIED` | `WITHDRAWN` | `EV-0041` (2026-09-25) proved it live; the 2026-09-28 deletion is evidenced by `docs/execution/snapshots/waf-*-before-delete-20260928.json` and a post-delete re-measurement showing 0 ACLs in both scopes, `wafConfiguration` null, and no ACL on either pool ARN | — | Restore with `python3 scripts/provision_waf.py --apply` if the decision reverses |
| `SEC-SHUB-001` | Security Hub excluded | overrides | Not subscribed; not queried | Stays excluded | `NOT_APPLICABLE` | — | overrides | Owner decision | None |
| `SEC-GD-001` | GuardDuty optional, non-blocking | overrides | 0 detectors | May evaluate | `NOT_APPLICABLE` | — | `EV-0005` | Owner decision | None |
| `SEC-HOOK-001` | Deny guards cover every tool route including AWS MCP | commit `4baf4236` | 4 hooks present | Kept | `PUSHED` | `TESTED` | `EV-0001` | — | Do not disable to bypass a block |
| `PROV-PAYU-001` | Zero PayU executable/declarative surface | brief | No PayU Lambda/route/table; `wecare/payu` scheduled 2026-08-26 | Permanent absence after recovery window | `DEPLOYED` | `DEPLOYED` | `EV-0004`, `EV-0006` | AWS recovery window | Verify permanent absence; rescan scripts/UI/docs |
| `PROV-SINCHSMS-001` | Zero Sinch SMS surface; Sinch **RCS** preserved | brief | 2 dangling `/webhook/sinch-dlr` routes + integration `qvupugf` **deleted**; `wecare/sinch/sms` scheduled; `wecare/sinch/rcs` untouched and active | Permanent absence after recovery window | `LIVE_VERIFIED` | — | `EV-0016`, `EV-0018` | Secret recovery window | Monitor; never touch `wecare/sinch/rcs` |
| `PROV-GATE-001` | Provider-policy gate covers scripts, IaC, UI, manifests, and live drift | brief | Live-drift gate exists and passes over 361 routes; source gate passes 8/8 but still scans only `amplify/functions src` | Expanded gate + seeded negative fixtures | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `scripts/check_provider_policy_live.py` | — | Widen the SOURCE scan to scripts, IaC, UI and manifests - the live half is done, the scope half is not |
| `WA-INGRESS-001` | One signed direct-Meta ingress with stage-prefix normalization | brief | `whatsapp-calling:live=13` verifies raw-body `X-Hub-Signature-256` against both app secrets and fails closed; `/whatsapp/inbound` now requires its own signature | Single verified ingress | `DEPLOYED` | `DEPLOYED` | `EV-0002`, `EV-0008`, `EV-0035` | Handset QA needs an owner QA recipient | Handset → webhook → inbox → reply → final `wamid` |
| `WA-STATUS-001` | `wamid` status lifecycle must be webhook-driven and never move backward | brief | Monotonic rank + atomic `ConditionExpression` in `_process_status`; initial persisted status is `accepted`, not a manufactured `sent` | Same | `DEPLOYED` | `DEPLOYED` | `EV-0033` | — | Observe `status_out_of_order_skipped` counts over a week |
| `WA-WINDOW-001` | 24-hour service window vs approved template enforced at the send boundary | brief | Window check no longer skippable when no contact row exists; fails closed | Same | `DEPLOYED` | `DEPLOYED` | `EV-0033` | — | — |
| `WA-LOG-001` | Structured outcome logging with redaction, incl. Graph code/subcode and permanent-vs-transient | brief | `graph_errors` wired (was imported by zero handlers); subcode, fbtrace_id and classification captured; 6 cleartext phone log sites masked | Same | `DEPLOYED` | `DEPLOYED` | `EV-0033` | — | — |
| `WA-EVENT-001` | Replace the fake SNS `Records` wrapper with an explicit typed internal event | brief | `lambda_utils/wa_internal_event` contract; consumer deployed before producer; both shapes accepted during drain | Legacy arm removed once `shapes` shows no `legacy-sns` | `LIVE_VERIFIED` | — | `EV-0034` | — | Watch the `shapes` field, then delete the legacy arm |
| `WA-PATH-001` | One reusable stage-prefix normalizer applied before routing and `require_auth` | brief | `lambda_utils/http_path.normalize_path`, now including the bare `/{stage}` case; `plivo_signature` re-exports it; 3 call sites, 0 hand-rolled copies | Same | `DEPLOYED` | `DEPLOYED` | `EV-0035` | — | — |
| `WA-OUTBOUND-001` | Meta Direct sends only; cross-WABA fallback fails closed; `wamid` reconciliation | brief | `outbound-whatsapp:live=17` (brief said 16) | Verified deployed fix | `DEPLOYED` | `DEPLOYED` | `EV-0002` | — | Confirm the fail-closed change is in v17 |
| `WAC-001` | Meta → `sip.wecare.digital:5061` → Asterisk; connected event normalized | brief | Meta ingress deployed and signed; connected-event normalisation built, flags off | Verified connected-state contract | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement) | Live QA call not authorised; no live-send flag is set | One QA call to the nominated recipient would close it |
| `NOTIF-OWN-001` | Exactly one connected-call dispatch owner | brief | Single dispatch owner; the duplicate ElevenLabs post-call producer is gone | One canonical owner | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `docs/notification-retirement-manifest.md` | — | None |
| `NOTIF-STORE-001` | `PstnNotificationDelivery` declared in four places, deployed nowhere | Phase 0 finding, resolved 2026-09-21 | Notification domain tables provisioned and recorded in the drift gate | Phase 3 builds fresh notification stores and deletes this declaration rather than materialising it | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `scripts/check_data_model_drift.py --gate` | Phase 3 design | None |
| `NOTIF-STORE-002` | Three handlers defaulted `RCS_TABLE` to a non-existent table | Phase 0 finding | Constants removed; each was assigned once and never read. Retained in the audit's `ACCEPTED_ABSENT` so a reintroduction is reported | Deployed `RCS_TABLE` env var on `wecare-rcs-dlr` removed too | `CODE_COMPLETE` | `TESTED` | `EV-0030` | — | Remove the now-inert deployed env var |
| `NOTIF-STORE-003` | Declared Amplify models and deployed tables are two disjoint naming worlds | 2026-09-21 finding | 58 models declared vs 79 live tables, 0 AppSync APIs. Both drift gates now PASS, so every divergence is recorded rather than implied | Establish whether the models are deployed at all | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `scripts/check_data_model_drift.py --gate` | — | `resource.ts` is still a document, not infrastructure. Say so in it, or deploy it - do not leave it reading like deployed IaC |
| `NOTIF-STORE-004` | Six table names referenced by code do not exist in the account | 2026-09-21 finding | `audit_data_model_drift.py --gate`: **0** tables named by code but absent | Each removed, corrected, or accepted with a reason | `LIVE_VERIFIED` | `LIVE_VERIFIED` | `EV-0041` (2026-09-25 re-measurement), 4 justified ACCEPTED_ABSENT entries | — | None |
| `NOTIF-LEGACY-001` | Retire `CallNotificationsTable` and direct senders after migration | brief | Legacy direct senders removed; `CallNotificationsTable` retired per manifest | Archived then removed | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `docs/notification-retirement-manifest.md` | A4 approval | None |
| `SMS-001` | AWS End User Messaging is the only SMS sender | brief | `sms-aws:live=12`, `outbound-sms:live=9` | Proven sole sender | `DEPLOYED` | `DEPLOYED` | `EV-0002` | — | Confirm no retired-provider env keys remain on the SMS functions |
| `RCS-001` | India RCS via Sinch only; non-India AWS EUM only when provisioned | brief | `rcs-send:live=7`, `rcs-dlr:live=6`, `wecare/sinch/rcs` active | Preserved, with auth fixed | `DEPLOYED` | `DEPLOYED` | `EV-0002`, `EV-0004` | — | Fix `SEC-ROUTE-001` first |
| `PSTN-TOKEN-001` | Cognito-protected browser-token route | brief | `POST /pstn/token` live on `wecare-pstn-softphone:live`, with 4 more session/diagnostics routes. **Was unpatchable until 2026-09-25** - absent from the deploy map while its provisioner only created, so the first deploy was also the last | Built behind disabled flag | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `scripts/deploy_all_lambdas.py` | — | Browser routing stays off; a QA session would close it |
| `PSTN-FLAG-001` | `PSTN_BROWSER_ROUTING_ENABLED` stays false until cutover | brief | Default false in `plivo-answer` | Unchanged until approval | `DEPLOYED` | `DEPLOYED` | `EV-0011` | — | Keep false |
| `PSTN-DIAL-001` | `/plivo/dial-events` reachable with signed contract | commit `6822c413` | `plivo-answer:live` holds 5 routes | Verified contract | `DEPLOYED` | `DEPLOYED` | `EV-0007` | — | Read back the exact route key set |
| `PAY-001` | Razorpay only; independent Meta and Razorpay verifiers | brief | `razorpay-webhook:live=25`, `invoice-engine:live=17` | Reconciled, no live charges in tests | `DEPLOYED` | `DEPLOYED` | `EV-0002` | `SEC-CRED-001` | Fixture tests only |
| `CRM-KEY-001` | `Contact` key contract: `contactId` vs runtime `id` | brief | `contactId` contract repaired in phase 4e | One canonical key, all callers migrated | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `docs/execution/phase-04e-contact-identity.md` | — | None |
| `MCP-META-001` | Both Meta MCPs authenticate via pre-registered client; write tools disabled | brief | Neither server connected | Read-only discovery | `WAITING_FOR_OWNER` | `DISCOVERED` | brief | Owner must add exact OAuth redirect URIs | Keep disabled |
| `MCP-RZP-001` | Razorpay MCP stays disabled (advertises `client_secret_post`) | brief | Disabled | Stays disabled | `BLOCKED` | `DISCOVERED` | brief | Provider lacks a public-client flow | No token exchange |
| `MCP-AWS-001` | AWS MCP used for sandboxed read-only inventory | Phase 0 | Working; all guards apply | Kept | `LIVE_VERIFIED` | — | `EV-0002`..`EV-0009` | — | Never a production dependency |
| `UI-IA-001` | Eight module homes; exactly three communication entries | brief | 8 module homes; exactly 3 communication entries; 20 legacy redirects live-verified 301 | Implemented | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `check_ui_labels.py --gate` blocking at every severity | — | None |
| `NATIVE-001` | Android/iOS packaging, signing, store work | overrides | Thin Capacitor shell | **POST-PROJECT** | `NOT_APPLICABLE` | — | overrides | Owner decision | Keep web WebView/WKWebView-ready only |
| `TEST-001` | Focused and full gates green at each handoff | brief | pytest **3438**, vitest **231**, typecheck clean, build ok, 10 gates green | Green on the exact commit | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement) | — | Real-browser and native layers still absent; mocked-DynamoDB tests hid a live key-schema mismatch, so add real-shaped fixtures |
| `DEPLOY-001` | Publish version + move `live` alias after every code change | steering | 49 of 58 have `live` | Enforced | `DEPLOYED` | `DEPLOYED` | `EV-0002` | — | Use `scripts/snapstart_publish.py` |
| `DEPLOY-002` | `POST /ai/generate` on a second API targeted `$LATEST`, bypassing the alias model | Phase 0 finding | The whole API was a dead duplicate with no domain and zero 30-day traffic; deleted along with its route, integration and the stale Lambda permission | 1 API, all routes alias-qualified where an alias exists | `LIVE_VERIFIED` | — | `EV-0031` | — | none |
| `DEPLOY-003` | 3 functions serve routes with **no `live` alias**, so `update-function-code` reaches production instantly with no alias rollback | Phase 1 finding | 65 functions, 7 with no `live` alias, of which only 2 serve routes: `seo-tools` (2) and `docs-scraper` (4). Both are the documented deliberate exclusions. `partner-onboarding` and `marketing-ads` now have aliases | Adopt the publish-and-move-alias model, or record why not | `DEPLOYED` | `DEPLOYED` | `EV-0041` (2026-09-25 re-measurement), `scripts/provision_live_alias.py` EXCLUDED | — | None. The 2 exclusions are correct: an alias would make their deploys report false success |
| `OPS-001` | 9 Lambda log groups have no retention set | Phase 1 finding | Regressed to 3 then fixed. The guard was also blind: it scanned one prefix in one region and missed 4 Lambda@Edge groups in `us-east-1` **and** `ap-south-1`. All 5 set to 30 days; read-back 0 never-expiring | A retention policy consistent with the data class | `LIVE_VERIFIED` | `LIVE_VERIFIED` | `EV-0041` (2026-09-25 re-measurement), `scripts/provision_log_retention.py --verify` | — | `me-south-1` is opted-in but unreachable from this host, so its coverage is UNPROVEN, not clean. Run `--strict` from a runner with full egress |
| `OPS-002` | 95 route paths are mentioned by no frontend file | Phase 1 finding | Re-derived and **classified** 2026-09-25: of 117, **13** are provider webhooks, **41** are referenced in Python (Lambda-to-Lambda), **21** are parameterised and textually unmatchable (12 with the prefix present in `src/**`), leaving **42** literal candidates - of which 34 are `/wa-business/*` and 4 deliberately answer `_retired_campaign_endpoint` | Each classified: webhook, internal, or retire | `DEPLOYED` | `DEPLOYED` | `docs/frontend-route-retirement.md` | — | **0 proven dead.** Resolve the 34 `/wa-business/*` callers first - one uniform block, two opposite possible causes |
| `OPS-003` | Runtime inventory is generated and joined rather than assembled by hand | Phase 1 | `scripts/generate_runtime_inventory.py` joins functions, aliases, routes, qualifiers, env names, event sources, log retention and 24h/7d traffic | Regenerated at each phase boundary | `CODE_COMPLETE` | `TESTED` | `EV-0032` | — | Regenerate rather than quote stale counts |

## Weighted progress — 2026-09-21

Reporting credit: `DISCOVERED` 0%, `CODE_COMPLETE` 30%, `TESTED` 50%,
`PUSHED` 55%, `DEPLOYED` 75%, `LIVE_VERIFIED` 100%.

Phase 1 must decompose each domain weight across its rows before any percentage
is published. **No completion percentage is claimed at Phase 0** — the registry
is seeded, not distributed, and publishing a number now would be an estimate
dressed as evidence.
