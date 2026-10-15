# Master requirement coverage

Generated **2026-09-25** at HEAD `d39227ca`, branch `stack`, account `775261844268`,
`us-east-1`.

Required by the final conversation-requirements coverage gate in `bw-crm.md`. Its
rule is that this file is *generated from* `docs/execution/requirement-registry.md`
and that no second status vocabulary may contradict the registry.

**It currently does contradict it, and this document's first job is to say so rather
than paper over it.** The registry holds 54 rows measured **2026-09-21**. Phases 2–10
closed on **2026-09-24** (`docs/execution/PHASE-10.3-CLOSURE.md`) without those rows
being advanced. So 19 rows still read `DISCOVERED` for work that has since shipped.
Every such row is named in §3 below. Nothing here silently rewrites registry history:
the registry stays the place a row's state is *changed*, and §3 is the list of changes
it is owed.

---

## 1. Measured gates at this HEAD

Everything in this section was run on 2026-09-25, not carried forward.

| Gate | Result |
|---|---|
| `pytest` | **3429 passed** |
| `vitest` | **224 passed** |
| `tsc --noEmit` | clean |
| `npm run build` | ok, 536 sitemap URLs (520 blog posts) |
| `check_provider_allowlist.py` | OK |
| `check_provider_policy_live.py` | **OK** — was FAILING at this HEAD before this session |
| `check_data_model_drift.py --gate` | **PASSED** — was FAILING at this HEAD before this session |
| `audit_data_model_drift.py --gate` | OK, 0 tables named by code but absent |
| `audit_route_auth.py --gate` | 0 OPEN, 0 DANGLING, 0 UNRESOLVED; 335 handler-authenticated, 5 allowlisted public |
| `verify_public_webhook_auth.py --gate` | 17/17 live probes as expected |
| `check_design_drift.py --gate` | OK |
| `check_ui_labels.py --gate` | OK at every severity |
| `verify_no_secrets_in_tree.py` | PASS |
| `verify_secret_hook.py` | 26/26 |
| `block_catastrophic.py --self-test` | 97/97 |
| GitHub Actions on `d39227ca` | 5/5 success |
| Dependabot open alerts | **0** |
| `npm audit` | 0 vulnerabilities |

Two of those gates were **red** when this session started. Neither failure was
cosmetic; both are covered in §2.

---

## 2. Requirement groups, against the gate in `bw-crm.md`

The brief's coverage gate lists 25 requirement groups. Each row below gives the
highest *proven* state, with the evidence that proves it.

| Requirement group | State | Proof |
|---|---|---|
| Provider ownership | `LIVE_VERIFIED` | Source gate (`check_provider_allowlist.py`) and the live-estate gate both pass. 361 routes scanned across 4 pages; Sinch confined to India RCS |
| Prohibited providers (PayU / Sinch SMS / Plivo SMS) | `DEPLOYED` | No prohibited Lambda, route or table live; the allow-list gate blocks reintroduction. Retired-provider secrets: [`docs/security.md`](security.md#retired-provider-credentials). **`DEPLOYED`, not `LIVE_VERIFIED`, until every scheduled deletion is permanently absent after its recovery window**. Razorpay UPI VPA preserved byte-for-byte |
| Protected Meta assets | `LIVE_VERIFIED` | Never deregistered, re-registered or migrated. `docs/protected-resource-register.md` |
| WhatsApp messaging | `DEPLOYED` | Stage-prefix defect fixed, signed ingress live, `wamid` status lifecycle reconciled. Handset round trip needs a live-send flag that is deliberately absent |
| WhatsApp Calling | `DEPLOYED` | Meta → `sip.wecare.digital:5061` → Asterisk preserved. Connected-event normalisation built; QA call not authorised |
| PSTN / Browser SDK | `DEPLOYED` | Token route, session/presence lifecycle and softphone complete behind `PSTN_BROWSER_ROUTING_ENABLED=false`. **This session made it deployable at all** — see §2.1 |
| Connected notifications | `DEPLOYED` (flags off) | Provider-neutral event/delivery/attempt/outbox domain; one logical delivery per channel; non-connected states create none |
| Notification rebuild | `DEPLOYED` | Legacy direct senders removed; `docs/notification-retirement-manifest.md` |
| AWS SMS and regional RCS | `DEPLOYED` | AWS EUM is the only SMS sender. India RCS via Sinch. Non-India RCS unprovisioned → `SKIPPED/UNSUPPORTED`, never downgraded |
| Payments | `DEPLOYED` | Razorpay only. Independent Meta and Razorpay verifiers. `payment_verified` now has four outcomes plus `PAYMENT_LOOKUP_REQUIRED`; no live charge created by any test |
| Contacts / identity | `DEPLOYED` / `WAITING_FOR_OWNER` | `contactId` key contract repaired. Google People and Truecaller need owner-side consent/registration |
| Flows / CRM | `DEPLOYED` | One idempotent completion service; the 4th writer (`_save_flow_submission`) removed after being shown to have zero callers |
| Frontend information architecture | `DEPLOYED` | Eight module homes; exactly three communication entries; 20 legacy redirects live-verified 301 |
| Product vocabulary | `LIVE_VERIFIED` | `check_ui_labels.py --gate` blocking at **every** severity over 231 ordinary-UI files |
| Design language | `DEPLOYED` | `check_design_drift.py --gate` OK; 13px shape token; light theme only, as scoped |
| Screen / device compatibility | `DEPLOYED` | Adaptive navigation incl. phone bottom bar and tablet rail. Physical-device matrix is POST-PROJECT |
| Native delivery | `WAITING_FOR_OWNER` | POST-PROJECT by `00-current-owner-overrides.md`; cannot block closure |
| Test architecture | `DEPLOYED` | 3429 + 224 tests. **Gap found this session:** mocked-DynamoDB tests passed over a real key-schema mismatch — §2.1 |
| MCP / SDK inventory | `DEPLOYED` / `WAITING_FOR_OWNER` | Meta MCP needs two redirect URIs; Razorpay MCP blocked on the provider's `client_secret_post` |
| Internal chatbot + governed operations | `DEPLOYED` | Versioned READ/PLAN/APPLY catalogue; **18 APPLY tools refused in `governance.py`** |
| Growth and presence APIs | `DEPLOYED` / `WAITING_FOR_OWNER` | 88 fixture-driven contract tests; 7 of 8 providers `SCOPE_UNVERIFIED` pending owner access |
| Commerce / site | `DEPLOYED` | Native AWS commerce: `ProductsTable`, `CartTable`, `CommerceKeys`, `OrderTable`, Razorpay checkout, coupons and gift cards; blog in `SeoToolsTable` ([`docs/design.md`](design.md) §6–§11) |
| Security / compliance | `DEPLOYED` | Raw-body signatures, 0 open routes, MFA staged. **No WAF** — both WebACLs deleted 2026-09-28 by owner cost decision, so the "enforcing on both carrying surfaces" claim is retired. Admin *data-path* proof blocked — §4 |
| Cleanup / storage | `DEPLOYED` | Route, dependency and bundle cleanup with manifests and rollback |
| Deployment / operations | `DEPLOYED` | 65 functions, 0 alias drift (re-measured 2026-09-26), snapshots for rollback, 5/5 CI green |
| Final reporting | `LIVE_VERIFIED` | `PHASE-10.3-CLOSURE.md` plus this document |

### 2.1 What this session actually changed

Two red gates, neither trivial.

**A rate limiter that was disabled in production.** The live
`stack-wecare-digital-RateLimitTable` keys on `id` alone.
`amplify/data/resource.ts` declared `identifier([ 'channel', 'windowStart' ])`, and
`lambda_utils/rate_limit.py` followed the declaration. DynamoDB rejects that key with
`ValidationException`; the module's bare `except Exception` swallowed it and returned
`True`, so **no rate limit was ever applied** for `operations/bulk-worker` or
`messaging/partner-onboarding` — a bulk sender and the partner control plane.

Proven by read-only `GetItem`: the composite key is rejected, `{'id': ...}` accepted.
Five existing tests passed throughout because they mock `dynamodb` wholesale, so any
key shape was accepted — the exact failure mode the brief warns about when it asks
for real-shaped fixtures. `TestKeySchemaMatchesTheLiveTable` now pins it; 4 of its 5
cases fail against the pre-fix file. Fail-open was kept deliberately; permanent
failures now log at ERROR so a dead limiter is greppable.

**Five live routes no supported deploy path could reach.**
`wecare-pstn-softphone` serves `GET /pstn/session`, `POST /pstn/session/events`,
`POST /pstn/session/presence`, `GET /pstn/diagnostics` and `POST /pstn/token` through
its `live` alias, but was absent from the deploy map, and its provisioner only
creates — so the first provisioning deploy was also the last one. Now in the map.
`wecare-get-miss-redirect` is genuinely external (Lambda@Edge associates by version,
so an alias cannot ship it) and is recorded as such.

Both had been reported as `orphan-no-source` while their source sat in
`amplify/functions`, which is why the real defect read as bookkeeping. The label is
now `orphan-not-in-deploy-map`.

**Correction to an earlier claim in this file.** It read: "`--dry-run` reports
`unchanged=1` for `wecare-pstn-softphone`, so its packaged code already matches
production." The dry run could not establish that. Its branch did
`tally["unchanged"] += 1` **unconditionally**, comparing nothing, so every target was
reported unchanged whatever the packaged bytes were. Now fixed to compute
`base64(sha256(zip))` and compare it to the live `CodeSha256`, reporting
`would_update` separately so a dry run cannot be read as a deployment result. Re-run
truthfully, `wecare-pstn-softphone` **would** update: its live v1 was packaged by its
provisioner, not by the deploy script, so the bytes differ. Nothing about it is
pending — the equivalence claim was just unfounded.

---

## 3. Registry rows the registry is owed

These rows read `DISCOVERED` as of 2026-09-21 and are contradicted by later
evidence. Listing them is how the contradiction gets recorded instead of hidden.

| Row | Registry says | Evidence since |
|---|---|---|
| `SEC-MFA-001` | `DISCOVERED` | MFA implemented; Cognito `OPTIONAL` with TOTP + email + SMS. Enforcement staged at `warn` on purpose |
| `SEC-WAF-001` | `WITHDRAWN` | Was `DISCOVERED` with 2 WebACLs live and enforcement proven by a blocked request. Both deleted 2026-09-28 by owner cost decision; the requirement was withdrawn in `00-current-owner-overrides.md` rather than left failing |
| `SEC-ROUTE-008` | `DISCOVERED` | Still genuinely open — blocked on Admin group membership (§4) |
| `PROV-GATE-001` | `DISCOVERED` | Live-estate gate exists and passes; source gate `check_provider_allowlist.py` passes |
| `WAC-001` | `DISCOVERED` | Calling ingress deployed; QA call not authorised |
| `NOTIF-OWN-001`, `NOTIF-LEGACY-001` | `DISCOVERED` | Duplicate producer resolved; legacy senders removed |
| `NOTIF-STORE-001`, `-003`, `-004` | `DISCOVERED` | Domain tables provisioned; drift gate now passes with both new tables recorded |
| `PSTN-TOKEN-001` | `DISCOVERED` | Token route live at `POST /pstn/token`; **and now deployable** |
| `CRM-KEY-001` | `DISCOVERED` | `contactId` contract repaired in phase 4e |
| `UI-IA-001` | `DISCOVERED` | Eight module homes, three communication entries, 20 redirects |
| `TEST-001` | `DISCOVERED` | 3429 + 224 tests; real-browser/native layers still absent |
| `DEPLOY-003` | `DISCOVERED` | Was 3 functions serving routes with no `live` alias; re-measure — the aliasing scripts have since run |
| `OPS-001` | `DISCOVERED` | Log-group retention reported 0 without retention at closure |
| `OPS-002` | `DISCOVERED` | 95 unreferenced route paths — still worth a pass |
| `NOTIF-STORE-002`, `OPS-003` | `CODE_COMPLETE` | Both advanced by later phases |

`SEC-CRED-001` (`WAITING_FOR_OWNER`), `MCP-META-001` (`WAITING_FOR_OWNER`) and
`MCP-RZP-001` (`BLOCKED`) are correct as they stand.

---

## 4. Open, with nothing hidden behind a label

**Engineering, not blocked on anyone**

| Item | Severity | Why it is still open |
|---|---|---|
| `apiCall` collapses every non-ok response to `null` | MEDIUM | 304 `apiCall<T>()` wrappers in `src/api/client.ts`. An auth failure, a timeout and an empty table render identically through them. `apiCallResult` and `collectApiFailures` exist and 3 surfaces use them; migrating 304 wrappers is a deliberate refactor and was **not** attempted |
| `origin` reaches `_response` via a module global | MEDIUM | The cross-request leak *is* fixed (verified: `global origin` and the `finally` reset are both inside `handler`). Only the signature boundary remains |
| `calling.tsx` 0 Hz oscillator fallback | MEDIUM | Untouched on purpose: it changes what a caller hears |
| `amplify/data/resource.ts` is a document, not infrastructure | HIGH as a *claim* | 0 AppSync APIs; 58 models vs 79 live tables. Both drift gates now pass, so the divergence is recorded rather than implied — but the file still reads like infrastructure |
| `route-auth.yml` live-AWS job has never run | MEDIUM | Needs `ROUTE_AUTH_ROLE_ARN`. The source half runs and blocks; the console-drift half is missing |
| `VoiceCDRTable` has no GSI | LOW | Scan-then-filter. Fine at 56 rows, not at 56,000 |
| `AIInteractionsTable` has no writer | LOW | Readers only; the architecture page's claim is unsupported |
| Cognito `VdmOptions.EngagementMetrics` | LOW | Unverified whether it injects a tracking pixel into OTP mail |

**Owner-held. One action each.**

| Item | Unblock |
|---|---|
| **Admin group membership — highest value** | `admin-add-user-to-group --user-pool-id us-east-1_cSx0RHCIR --username wecare.digital --group-name Admin`. Re-confirmed live: all four groups exist, the only user is in none. 16 handlers can be proven to refuse anonymous callers but **not** to serve a signed-in Admin |
| ~~`ADMIN_MFA_REQUIRED` at `warn`~~ | **Withdrawn 2026-09-29 — this row was wrong.** Measured across all 66 functions: `ADMIN_MFA_REQUIRED=true` is set on all **13** that gate anything on an `Admin` role, including every one of the nine handlers passing `required_role='Admin'`. Enforcement is **live**, not pending, and `middleware._admin_mfa_required` already records that the warn-first rationale expired. Nothing is owner-held here |
| Disclosed Cognito client | Delete `1jrnb80tcvceg7uln9vuoe8va5`. Not done here: it modifies authentication and the id cannot be recreated |
| Credential rotation | Razorpay / Google Ads / Google OAuth / Google API key / Bing — `MANUAL_OWNER_ACTION` |
| RCS receipt verification | Store a `webhook_secret` in `wecare/sinch/rcs`. No code change |
| 7 of 8 growth integrations | Provider access; unblocks listed on `/growth` |
| Meta MCP | Add the two loopback redirect URIs to app `2238810740192680` |
| Razorpay MCP | Provider-side: token endpoint offers only `client_secret_post` |
| Live QA send / call | Recipient `+918100640044` nominated; every live-send flag deliberately absent |
| Native packaging | POST-PROJECT by owner override |

---

## 5. Weighted position

Using the program weights from `bw-crm.md` §00 and its milestone credits
(`DEPLOYED` = 75%, `LIVE_VERIFIED` = 100%, `WAITING_FOR_OWNER` at its
`proven_through`).

| Domain | Weight | Highest proven | Credit |
|---|---:|---|---:|
| Security, identity, provider retirement | 15 | `DEPLOYED`, parts `LIVE_VERIFIED` | ~11.8 |
| WhatsApp messaging and Calling | 14 | `DEPLOYED` | 10.5 |
| Notifications, SMS, RCS | 14 | `DEPLOYED` (flags off) | 10.5 |
| PSTN Voice, Browser SDK | 14 | `DEPLOYED` | 10.5 |
| Payments, contacts, CRM | 10 | `DEPLOYED` | 7.5 |
| Governed MCP / dashboard AI | 8 | `DEPLOYED` | 6.0 |
| Growth APIs and commerce | 7 | `DEPLOYED` | 5.25 |
| Frontend IA / design / tutorials | 8 | `DEPLOYED`, vocabulary `LIVE_VERIFIED` | 6.3 |
| Android/iOS | 4 | `WAITING_FOR_OWNER`, POST-PROJECT | 4.0 by override |
| Tests, observability, deployment, DR | 6 | `DEPLOYED` | 4.5 |
| **Total** | **100** | | **≈ 76.9** |

Reported separately, as the brief requires: the weight that is genuinely
**`LIVE_VERIFIED`** is **≈ 12**, concentrated in provider ownership, protected
assets, product vocabulary and the gate/evidence layer. The distance between 77 and
12 is almost entirely **flags that are off on purpose** — `PSTN_BROWSER_ROUTING_ENABLED`,
`PSTN_CONNECTED_NOTIFICATIONS_ENABLED`, `WA_LIVE_SMOKE_TEST`, `SINCH_RCS_ENABLED`, the
two growth module flags and 18 refused APPLY tools. Turning any of them on is a
separate decision, not a remaining task.

Unweighted row counts are in §3 so the single number cannot conceal a blocker.

---

## 6. Verdict

**⚠️ COMPLETE WITH IMPROVEMENTS** — the same verdict as the phase-10.3 closure, and
for the same narrow reason: the single most useful verification left cannot be
performed without one `admin-add-user-to-group` call.

What changed at this HEAD is that two gates were **red** and are now green, and one of
them was hiding a security control that had never worked in production. A gate that
fails for a mislabelled reason trains people to ignore it, which is why the label was
fixed alongside the defect.
