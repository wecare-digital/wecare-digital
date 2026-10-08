# WhatsApp coverage: preservation and upgrade plan

Owner-supplied audit received 7 October 2026. This addendum integrates its useful coverage findings into the 14-destination workspace design and internal-agent phases. It is documentation/research, not an activation or deployment of the audit's suggested batches.

## What the audit establishes and what it does not

The report's 80–95% completion figures are author judgments, not acceptance-test or live-readiness metrics. Its final section states that no tests ran, live AWS state was not refreshed and frontend/backend wiring was sampled. A named function, route string or test file establishes source coverage, not provider eligibility, deployed availability or a verified customer outcome. Use distinct states: source present, contract verified, deployed, provider-authorized, tested end to end, intentionally disabled.

Source checks in the current research tree found:

- Embedded Signup is **not an unwired stub**. `embedded-signup.tsx` mounts `EmbeddedSignupPanel`, whose `exchange` posts to `/partners/embedded-signup` and renders completion/error states. The admin UI flag is not proof of backend authorization; separately verify server authorization, OAuth origin/state/code binding, provider readiness and tenant ownership before onboarding. No onboarding was performed.
- `meta-business-agent/handler.py` still has the legacy-looking `_thread_control` implementation and defaults `GRAPH_HOST` to `https://api.facebook.com`. This confirms the source shape, not the correct replacement endpoint. Its request-contract/action validation must be verified against current provider documentation and fixtures before changing it. Do not change every Business Agent endpoint to a guessed host.
- Group event branches store system events. A separate `_process_group_event` helper also exists, updating participant/lifecycle state; its existence alone does not prove a dispatch path. Trace event routing before declaring all group processing absent or adding duplicate writers.
- Revoke handling explicitly documents missing target-message correlation. Do **not** mark/delete a message based only on sender and approximate timestamp. Keep an unresolved event and use a documented target ID or an explicit reviewed resolution.
- `OTPTemplateUI.tsx` comments mention one-tap, but current controls offer `copy_code`/`url`. A string match is neither proof of supported one-tap delivery nor proof of total absence. Native autofill remains post-project until a business requirement and supported implementation are established.
- Repository task policy says website-only checkout supersedes in-WhatsApp payments. Keep dormant native payment code out of the active purchase and agent-tool flows. Preserve customer WhatsApp OTP for website orders/cart.
- Signature/smoke rejection log strings exist. The limited source search did not establish production metric-filter/alarm coverage; no live observability API inspection was performed in this turn. Treat the audit's “missing alarm” statements as verification tasks, not confirmed live absence.

The supplied audit refers to source HEAD `cb505edf` in another checkout. This branch's prior audited production base is `a82ff4c9`; differences may reflect concurrent work. Findings below are grounded in explicitly checked files or labeled as audit claims pending validation, not a claim that the two trees are identical.

## WhatsApp capabilities in the final workspace

```text
Inbox → channel=WhatsApp
  Conversation / notes / media / reactions / templates / interactive messages
  Service-window state / read-delivery state / customer-context panel
  Ownership state → human / customer AI / unknown; guarded handover actions

Campaigns
  Template library → selected template → builder / validation / status
  Audience → content → schedule → delivery → measured results
  Marketing API and promotional variants appear only when supported and authorized

Catalog
  Product → provider/channel IDs → catalog/Flow mapping → sync result
  Product-message selection remains a contextual Inbox/Campaigns action

Service Ops
  Website requests / Flow submissions / forms / orders / documents
  Source-aware detail → payment reference / amendment / task / history

Settings → Channels → WhatsApp
  Accounts | Identity & profile | Groups | Webhooks | Calling
  Account detail → numbers / permissions / onboarding readiness / health

Settings → Automation & AI
  Customer AI | Internal agent | Rules | Flows | Policies
  Flow detail → design / version / validation / publish readiness
  Business Agent detail → eligibility / config / knowledge / connectors / evaluation

Settings → Integrations
  Provider grants / scopes / authorized-read evidence / refresh / reconnect

Work
  Human tasks / agent runs / owner exceptions / verified receipts

Settings → Platform
  Webhook failures / failed deliveries / deployment versions / timestamped health
```

These are inner views/actions in the existing destination groups, not 31 new sidebar entries. Groups management belongs in channel settings; group conversations belong in Inbox only after group-origin identity/permissions are verified. Calling settings and actual call records remain separate views. Internal workspace AI and customer Business Agent have distinct actors, prompts and permissions.

## Twelve-area capability preservation matrix

| Audit area | Final home | Preserve during consolidation | Admission gate |
|---|---|---|---|
| A Accounts | Channels → WhatsApp; Integrations | WABA/number identity, profile, username/BSUID, assigned permissions, QR links, partner connection status | Correct workspace/account scope and actual provider permissions; protected number/PIN operations remain excluded |
| B Messaging | Inbox; Campaigns | Supported message/media composers, contextual replies, reactions, read/typing states, service-window behavior, blocked-user state | WhatsApp inbox feature parity, media safety, delivery evidence and existing send restrictions |
| C Templates | Campaigns → Templates | Categories, languages, media/buttons, OTP, TTL, validation and approval/quality status | Backend payload/provider constraints, accurate lifecycle state; no blanket enablement of new variants |
| D Flows | Automation & AI → Flows; responses in Service Ops | JSON/version management, encrypted data exchange, validation, response IDs and lineage | Handler/JSON agreement, key custody, idempotent completion and source-aware staff reads |
| E Calling | Channels → Calling; records in Inbox | Permission/call-hours/voicemail/SIP settings and supported call records | Provider entitlement, correct initiation/permission contract and consent; no SIP cutover or live call activation here |
| F Groups | Channels → Groups; contextual work | Group detail, membership/invites/join requests and status | Verified event dispatch and actor scope; notify-only before any approval automation |
| G Webhooks | Platform; domain timelines | HMAC validation, deduplication, monotonic status, system events and handover observations | Per-handler auth/metrics verification and truthful unknown event state |
| H Commerce/payments | Catalog, Service Ops, Payments | Product context, website checkout, order/payment references, invoices and receipts | Website-only purchase rule; no native payment reactivation/capture/refund/config mutation |
| I Marketing API | Campaigns → Content/Insights | Supported marketing drafts, eligibility and conversion/attribution evidence | Authorization and read-back contract verified; no spend/send activation implied |
| J Business Agent | Automation & AI → Customer AI | Eligibility, settings, knowledge/connectors and test/evaluation history | Correct thread-ownership contract; prevent competing responders; customer scope distinct from internal agent |
| K Analytics | Campaigns insights; account usage detail | Real provider analytics and measured delivery/usage; timestamp/source/scope | Valid provider account/time range and aggregation; no synthetic current billing or Cost Explorer restoration |
| L Infrastructure | Platform; Work runtime | Deployment/version state, rate limits, bounded jobs, secret references and fail-closed actions | Exact-tree tests, live deployment evidence, rollback and per-operation policy |

## Classify all 25 reported gaps before implementation

| ID | Disposition in this redesign | Next evidence or implementation requirement |
|---|---|---|
| G1 Signature failure monitoring | Verify first, then high-value Platform backend work | Inspect all affected log filters, metrics, alarms and notification destinations; add missing coverage through IaC |
| G2 PIN set/change | Excluded by current project restrictions | Do not add/enable PIN or migration operations from this pasted recommendation |
| G3 Payment config drift | Deferred diagnostic scope | Verify relevant active dependencies first; do not restore retired native checkout |
| G4 Thread control | Contract verification required | Confirm provider contract, recipient identity, action allowlist and ownership transitions; no guessed endpoint or autonomous takeover |
| G5 Group automation | Notify/task first | Trace current dispatch; add deduplicated pending-join internal tasks and status; approval needs separate bounded policy |
| G6 Marketing metrics | Conditional read-only Insights work | Verify provider metric availability, entitlement, pagination/time range and real attribution joins |
| G7 Revoke target | Preserve unresolved state | Documented target reference required; heuristic sender/time correlation cannot authorize deletion |
| G8 Embedded Signup stub | Corrected: frontend is wired | Test shared component/backend authorization and provider configuration, not a replacement page |
| G9 Limited-time offer | Optional campaign extension | Business requirement, official payload validation, provider support and preview tests |
| G10 Native OTP autofill | Post-project/optional | Keep working website WhatsApp OTP; native signing/registration outside current web scope |
| G11 Product carousel | Optional catalog/composer extension | Official supported payload and provider readiness; preserve existing product types first |
| G12 Calling permission | Contract review | Distinguish user/business initiated calls; validate actual consent state and error guidance |
| G13 Pricing analytics | Conditional account/Insights panel | Verify existing API response/time range and access; separate provider usage from AWS billing |
| G14 Marketing send UI | Draft/eligibility only under current policy | Existing client function is not live-send authorization |
| G15 Template pacing/pausing | Useful template status upgrade | Verify readable provider fields and webhook transitions before promising advance availability |
| G16 OBA status | Optional account detail read | Confirm current readable field/edge and permissions |
| G17 Compliance information | Optional account detail read | Verify provider contract, permission and relevance; protect sensitive business fields |
| G18 Encryption API | Verify need | Existing Flow encryption is distinct; no gratuitous key/config rotation |
| G19 Provider health | Useful read-only diagnostics | Verify supported API and failure distinction; preserve unavailable state |
| G20 Callback override | Defer unless needed | No callback/provider mutation merely for coverage completeness |
| G21 Coexistence | Deferred capability | Source string absence does not establish provider eligibility; explicit deployment requirement needed |
| G22 Multi-partner solutions | Deferred capability | Tenant, ownership and partner lifecycle design needed; no offboarding/migration |
| G23 Recording/transcription | Optional consent-dependent work | Distinguish call recording from voice-note transcription; provider contract and lawful consent requirements before adoption |
| G24 Call button/deep link | Optional composer enhancement | Supported schema, call readiness and existing send policy |
| G25 Group-origin attribution | Verify before exposing Inbox group views | Real documented fixture, normalized source IDs and scoped permissions |

This classifies research recommendations; it does not adopt the report's severity/completion rankings as measured production impact. The report's extra improvement items I1–I13 remain a backlog to inspect individually rather than claiming they are already fixed.

## Implementation batches that fit the workspace and agent phases

1. **Baseline and preserve:** derive effective capability states from backend/provider readiness; fix false stub labels; create parity checks for inbox, template, Flow, Group and Calling consolidation. Do not infer runtime success from source coverage percentages.
2. **Observe and triage:** verify signature/smoke/DLQ monitoring; expose scoped failures in Platform and Work. Start group join requests as internal notifications/tasks. Synthetic alarm tests must avoid paging real operational channels accidentally.
3. **Correct contracts:** verify thread control, calling permissions, schedule cancellation, unresolved revoke behavior, save confirmations and template state. Use provider docs plus offline fixtures before any live provider action.
4. **Consolidate UI:** migrate capability-preserving components to Inbox, Campaigns, Service Ops and WhatsApp settings; retain deep links and distinct data ownership. Embedded Signup is reused, not rewritten because of its line count.
5. **Add autonomous eligible workflows:** the internal agent can read health, create internal follow-ups and prepare drafts after its MCP delegation/durable execution phases. No direct provider CRUD, join approval, send or payment power bypasses its server policy.
6. **Optional expansion:** admit marketing read-back or new composer variants only when business demand and provider eligibility justify them. Deferred platform features do not create empty sidebar pages.

## Verification performed and limitations

Read the supplied audit's gap/batch/verification sections, the cited repository source and existing reconciliation. Source-confirmed Embedded Signup's component/API chain, thread-control construction, group event storage/helper, revoke TODO, OTP control mismatch and website-only payment rule. No app tests, provider-authenticated reads, model calls, live sends, migrations, PIN/payment operations or production changes were performed.

Attempted to refresh Meta's official Conversation Routing, Groups and Embedded Signup documentation on 7 October 2026. Conversation Routing was inaccessible; Groups and Embedded Signup returned HTTP 429. Consequently **no current replacement thread-control/API contract is certified here**. Official references are entry points for the subsequent contract review, not evidence successfully retrieved in this turn:

- https://developers.facebook.com/docs/whatsapp/cloud-api/conversation-routing/
- https://developers.facebook.com/docs/whatsapp/cloud-api/groups/
- https://developers.facebook.com/docs/whatsapp/embedded-signup/

All source paths above are relative to this repository, under `src/` or `amplify/functions/`. Existing audit/deployment snapshots are historical evidence from this session, not new live measurements in this addendum.
