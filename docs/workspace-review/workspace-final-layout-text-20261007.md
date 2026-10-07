# Proposed final workspace: fewer destinations, complete workflows

Owner request, 7 October 2026. Design specification on `codex/workspace-audit-redesign-20261007`; this does not change the deployed UI. Read together with the page audit, investigation reconciliation and internal-agent phases. The pasted report is research input: unsupported “stub”, “orphan” and retirement claims are not carried into the implementation.

## Final navigation target

**14 primary destinations:** Home + eight work areas + five Settings sections. This is a proposed information architecture, not a claim that all 113 current workspace routes can become 14 physical route files. Detail URLs, task steps, role-specific account screens and legacy redirects remain addressable. Reduce independent page implementations and repeated menus; retain useful capabilities.

```text
WECARE.DIGITAL                            [Search records / commands] [Ask agent] [Account]
│
├─ Home                                   Logo / workspace entry, not another menu tree
│
├─ Inbox                                  All channels | Assigned | Unread | Delivery issues
├─ Contacts                               People | Segments; selected contact opens Contact 360
├─ Campaigns                              Drafts | Scheduled | Delivery | Templates | Insights
├─ Service Ops                            Requests | Orders | Appointments | Documents | Responses
├─ Payments                               Ledger | Invoices | Reconciliation
├─ Catalog                                Products | Collections | Channel mapping
├─ Work                                   Tasks | Agent runs | Needs owner | History
├─ Content                                Posts | Production | Pages | Supported SEO; editor role
│
└─ Settings                               Fixed bottom control
   ├─ Your account                        Profile | Access; Partner's own account stays scoped
   ├─ Integrations                        MCP + provider accounts, scopes, verification, reconnect
   ├─ Channels                            WhatsApp | Email | SMS/RCS | Voice | Push
   ├─ Automation & AI                     Internal agent | Customer AI | Rules | Flows | Policies
   └─ Platform                            Admin health | Failed jobs | Deployments | Usage availability
```

Keep eight daily entries at most, with Content hidden for roles lacking editorial access. Home is reached through the logo. No third-level sidebar trees. Use one capability registry for menus, search, visible actions and feature readiness; backend authorization remains authoritative.

## Shared page layout

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Global search / command entry                     Agent run status       │
├─────────────┬───────────────────────────────────────────────────────────┤
│ Daily areas │ Breadcrumb · Page name                      [Primary action]│
│             │ Brief context / last refreshed / connection state          │
│             │ [Local tabs]                                               │
│             │ [Search] [Saved view] [Status] [Owner] [Date] [More filters] │
│             ├──────────────────────────┬────────────────────────────────┤
│             │ Resource queue           │ Selected record / detail        │
│             │ Cursor-paged records     │ Related records · History       │
│             │ Status + assigned owner │ Permitted contextual actions    │
│             │ Clear empty/error state │ Agent evidence when applicable  │
│ Settings    │ [Previous] [Next]         │                                │
└─────────────┴──────────────────────────┴────────────────────────────────┘
```

Five reusable interaction patterns: resource index/detail, conversation, workflow editor, settings, operational overview. A tab selects a distinct workflow or resource; a modal handles a short action; a drawer previews detail. Complex editors and long records keep deep links. URL stores tab/filter/selection so refresh, bookmarks and Back work. Do not cram every action into a modal.

One main page heading and primary action; neutral canvas, dark green text/navigation, lime selected state, compact status badges with text. On mobile show list, detail or editor one at a time; preserve Back and filters. Closed panes/tabs must not keep polling. Loading, no records, no access, sign-in expired, unconfigured provider and request failure are separate states.

## 1. Home: actionable overview

```text
HOME                                          [Ask agent to handle an outcome]
[Needs attention] [Overdue work] [Failed delivery] [Blocked connections]
┌──────────────────────────────┬─────────────────────────────────────────┐
│ My work / team queue         │ Agent activity                           │
│ Task → owning record         │ Running → current step                   │
│ Request → owner / SLA        │ Completed → verified result              │
│ Delivery issue → retry state │ Needs owner → exact decision / reconnect │
└──────────────────────────────┴─────────────────────────────────────────┘
```

Improvement: replace infrastructure/reference-card sprawl with current operational exceptions. Backend: role-scoped summary aggregates with timestamps and bounded reads; link to source queues. No scanning thousands of messages for four summary tiles. No fabricated billing numbers. Cost Explorer remains removed/disabled as instructed.

## 2. Inbox: one conversation workspace

```text
INBOX                [All / WhatsApp / Email / SMS / RCS / Voice]
[Assigned to me] [Unread] [Search] [Saved view]
┌───────────────────┬────────────────────────────┬────────────────────────┐
│ Conversation list │ Selected conversation      │ Customer context       │
│ Latest message    │ Delivery / read state      │ Contact / tags / owner │
│ Channel + owner   │ Messages / internal notes  │ Orders / requests      │
│ Unread + age      │ Attachments / voice record │ Invoice / task links   │
│ Cursor paging     │ Composer / template action │ Agent draft / evidence │
└───────────────────┴────────────────────────────┴────────────────────────┘
```

Merge common and WhatsApp inbox implementations only after preserving templates, attachments, reactions, notes, permissions and channel rules. Voice records are an Inbox filter; calling/IVR configuration belongs in Settings. Delivery issues is a filtered queue/detail, not another messaging app.

Gaps: duplicate 10/15-second full reloads, broad contact/message fetching, missing transcription route, query-filter active-state bug. Backend upgrades: conversation summaries, selected-thread cursor reads, authorized indexed search, stable ordering and shared visibility-aware fetching. Restore transcription only after verifying handler/route support; show unavailable meanwhile. Start delivery failures read-only; replay needs action claims and reconciliation.

## 3. Contacts: list plus Contact 360

```text
CONTACTS                           [Search] [Segments] [Import / New contact]
┌─────────────────────────────┬─────────────────────────────────────────┐
│ Person / company            │ Contact 360                             │
│ Verified channel identities │ Overview | Activity | Orders | Requests │
│ Tags / assignment           │ Invoices | Files | Notes | Tasks        │
│ Last activity / source      │ Field source + change history           │
└─────────────────────────────┴─────────────────────────────────────────┘
```

Keep one identity record; do not create separate contact pages for each channel. Backend: authoritative contact service, normalized indexed lookup, field provenance, optimistic concurrency and bounded related-record reads. Duplicate merging must be a reviewed identity workflow. Optional CRM pipeline belongs here only if the business needs leads/opportunities; zero frontend callers does not justify deleting CRM tables.

## 4. Campaigns: campaign lifecycle in one place

```text
CAMPAIGNS        [Drafts] [Scheduled] [Delivery] [Templates] [Insights]
Campaign / audience / channel / owner / status / schedule / measured result
Select campaign → Overview | Audience | Content | Schedule | Delivery history
Create/edit      → Audience → Template/content → Validate → Review → Save draft
```

Bring Broadcast, schedule inspection, template creation/detail, link attribution and delivery summaries into one resource workflow. Provider account/template approval configuration stays in Settings; daily template selection belongs here.

Gaps: scheduled cancellation client/route mismatch; fragmented template/builder and analytics; provider readiness. Backend: correct cancellation contract, schedule state transitions, cursor lists, audience snapshots, send-policy validation and measured aggregates. Draft and permitted configuration support do not imply live broadcast authorization. Ad activation and budgets remain restricted.

## 5. Service Ops: the operational hub with missing staff coverage added

```text
SERVICE OPS      [Requests] [Orders] [Appointments] [Documents] [Responses]
[Source: website / WhatsApp Flow / form] [Status] [Assigned] [Date]
┌──────────────────────────────┬────────────────────────────────────────┐
│ Request / order queue        │ Record detail                          │
│ Source ID + customer         │ Overview | Timeline | Documents        │
│ Paid/unpaid · service status │ Payment reference | Amendments | Tasks │
│ Owner / age / next step      │ Assign / permitted status update       │
└──────────────────────────────┴────────────────────────────────────────┘
```

Merge Forms Responses, Flow Responses, tracking and service directory navigation. Keep distinct source models visible: website paid service requests and legacy Flow submissions are not the same table/schema. Flow creation/publishing moves to Automation & AI; actual responses stay here. Existing Reviews/FAQ/enterprise service functions must remain reachable contextually or through declared settings/workflow links; they are not silently dropped.

Largest backend gap: add a staff-authorized queue/detail API for the new service-request lifecycle with assignment, status history, payment/order references and amendments. Retain source IDs/lineage in a normalized read view rather than blindly merging tables. Add cursor paging to legacy order/list contracts. Existence of customer self-service endpoints is not an all-customer staff API.

## 6. Payments: one ledger, separate financial actions

```text
PAYMENTS                [Ledger] [Invoices] [Reconciliation]
[Date] [Status] [Customer] [Source] [Search reference]
Reference / customer / amount / provider status / linked order / discrepancy
Select row → Invoice detail | Provider events | Linked request | Audit history
Contextual → Draft invoice / Share existing invoice / UPI sharing when permitted
```

Combine records and payment context into a ledger/detail flow. Preserve the live payments-read service and consumers; the pasted report's orphan label is incorrect. UPI URI generation is UPI sharing, not a provider-hosted payment link with enforced expiry. Browser-local Pay Flow settings must be labeled browser-local until migrated to a real server contract.

Backend: bounded ledger/invoice reads, documented financial source-of-truth, provider-event correlation and immutable audit references. Read-only discrepancies may create internal tasks. Capture/refund/payment configuration remain restricted. Partner own-account wallet/ledger stays separately authorized, not combined with workspace balances.

## 7. Catalog: product record and channel mappings

```text
CATALOG                          [Products] [Collections] [Channel mapping]
Product / SKU / availability / price source / storefront / sync state
Select product → Overview | Media | Channel IDs | Flow mapping | Sync history
```

Keep business products distinct from provider mapping, linked by explicit IDs. Combine overlapping catalog/commerce/builder actions into product detail or a mapping editor. Do not display unavailable shipping/tracking services as active integrations.

Backend: audit authoritative product and mapping contracts before exposing dead catalog helpers; establish a supported list/detail route where needed. Sync jobs need run status, last successful sync, per-item failures and bounded retries. Resolve public product links to `/shop/[slug]`, not `/product-page/{slug}`.

## 8. Work: human tasks and durable agent runs

```text
WORK             [Tasks] [Agent runs] [Needs owner] [History]
[Ask: reconcile today's service requests and assign follow-ups]
┌──────────────────────────────┬────────────────────────────────────────┐
│ Outcome / task queue         │ Selected run                           │
│ Queued / running / verifying│ Requested outcome · active policy      │
│ Completed / partial / failed │ Plan → execution → verification        │
│ Owner / deadline / cost cap  │ Tool receipts · created record links   │
│ Blocked access / decision    │ Stop / retry / exact owner decision    │
└──────────────────────────────┴────────────────────────────────────────┘
```

This is the visible home of the internal-agent roadmap, not a second assistant. Floating chat and dashboard chat create/open runs in this queue. Separate internal AI from customer-facing AI prompts and permissions.

Backend: durable coordinator/run storage, scoped MCP worker identity/delegation, per-action idempotency claims, checkpoint/resume, concurrency controls, verification receipts and budget caps. Existing approval records alone do not execute tools. Eligible workflows use standing policies; no per-step owner clicking. Provider consent/revoked access and actions outside policy are precise exceptions. Details are in `internal-agent-autonomy-phases-20261007.md`.

## 9. Content: one editorial lifecycle

```text
CONTENT                    [Posts] [Production] [Pages] [Supported SEO]
Title / type / owner / draft state / quality findings / publication reference
Select item → Draft → Review → QA → Publish eligibility → Published history
Batch view  → Same stages with per-item status; no duplicate editor implementation
```

Consolidate Blog Studio, manager, production batch/review/QA/publish and page management into a shared item/workflow. Production is already contextually linked; improve role-filtered discovery rather than calling it unreachable. Eight external-client SEO patterns remain configuration-blocked. Do not invent a FastAPI URL/token to make tabs appear live.

Backend: use authenticated `seo-tools` for supported capabilities; explicitly defer/migrate unsupported external SEO contracts. Check content existence before claims, use fenced audit leases and correct canonical URLs. Those source fixes exist in pending PR243 and require release verification; they are not assumed deployed here. Publication permissions and workflow results remain real provider/backend checks.

## 10. Settings inner pages

```text
SETTINGS → INTEGRATIONS
Provider / account / scope / grant owner / last authorized read / status
Select provider → Permissions | Verification history | Reconnect instructions
Status: Not connected / Authorization required / Connected / Verification failed /
        Reconnect required. Infrastructure reachability ≠ provider authorization.

SETTINGS → CHANNELS
[WhatsApp] [Email] [SMS/RCS] [Voice] [Push]
Selected channel → Accounts | Identity/profile | Templates | Webhooks | Readiness
WhatsApp identity consolidates username/BSUID views. Calling has its own local tabs.

SETTINGS → AUTOMATION & AI
[Internal agent] [Customer AI] [Rules] [Flows] [Policies]
Selected workflow → Trigger | Conditions | Permitted actions | Limits | Run history
Flow detail → Design | Validate | Version | Publish readiness | Related responses

SETTINGS → PLATFORM (Admin only)
[Health] [Failed jobs] [Deployments] [Usage availability]
Timestamped source inventory / integration health / alias version / failed-job detail
Architecture and design references → repository documentation, not daily screens.

SETTINGS → YOUR ACCOUNT
[Profile] [Access]
Staff testing login and customer WhatsApp OTP remain distinct.
Partner-own billing/account data is a separately authorized contextual view.
```

Backend: timestamped sanitized operational metadata, truthful connection state, effective server-owned tool catalog, confirmed configuration save/read-back and revocation checks. MCP v10 deployment lag is a separate pending release; changing UI labels does not deploy merged persistence code. Do not recreate Cost Explorer or return synthetic current-looking billing on failure.

## Backend upgrade map: prioritize contracts over adding Lambdas

```text
Shared resource UI / assistant
              │
     Authenticated API / MCP tools
              │
 Capability and actor/workspace policy checks
              │
 Existing authoritative domain services
              │
 Indexed/cursor read contracts + conditional writes
              │
 Durable jobs → action claim → effect → reconcile → receipt
              │
 Truthful UI state / verified agent outcome
```

| Priority | Upgrade | Resolves | Release proof |
|---|---|---|---|
| P0 foundation | Standard response envelope: data, next cursor, freshness/scope, structured error, request ID | Empty-on-error lists; misleading connection/data states | Forbidden/session-expired/unavailable/empty are distinguishable |
| P0 foundation | Shared capability registry + role-filtered menus/search + server enforcement | Tool/menu drift; inappropriate role visibility | Each visible action has a matching allowed contract |
| P1 | Staff paid-request queue/detail and source-preserving linkage | Missing management coverage of new service records | Staff scoping; customer isolation; legacy/new model fixtures |
| P1 | Durable agent runs + worker delegation + action receipts | Browser-bound chat; unavailable autonomous execution | Restart/duplicate/revocation/partial-effect cases |
| P1 | Conversation summary/thread queries and shared caching | Duplicate inbox implementations and broad polling | Feature parity, cursor boundary and measured request reduction |
| P1 | Fix schedule cancellation/save confirmation; gate transcription | Broken action contracts and false success | Fixture cancellation; failed save retained; unavailable button state |
| P2 | Failed-delivery inspection and governed replay | Existing DLQ backend missing useful operator UI | Read first; replay deduplication and permissions before enablement |
| P2 | Canonical content client and source URL resolver | Eight blocked SEO patterns; wrong product audit URL | Configured capability coverage and real content audit fixtures |
| P2 | Ledger and sync-job read contracts | Fragmented payment/product state | Correct reference linkage, paging and failure evidence |
| P2 | Timestamped operational inventory and truthful usage state | Static platform drift; fake billing fallback | Source timestamp/version shown; unavailable stays unavailable |

These are proposed contract families, not assertions that every named endpoint already exists. Reuse existing services; add routes/read models only for proved gaps. A combined staff view may aggregate several source systems without changing their write ownership. Deleting a page does not retire a backend safely. Deleting an idle on-demand table/Lambda may not save a meaningful fixed charge.

## Consolidation decisions

| Current fragmentation | Final destination | Preservation gate |
|---|---|---|
| Common inbox + WhatsApp inbox + channel wrappers | Inbox with channel filter | WhatsApp feature parity, notes/templates/attachments/permissions |
| Forms/Flow responses + track-request + service directory | Service Ops source-filtered queues and detail | Submission/order/payment lineage and legacy URLs |
| Broadcast + schedule + template builder | Campaigns lifecycle + template detail | Validated cancellation and provider readiness |
| Username + BSUID | Channels → WhatsApp → Identity | Stable identity IDs and account scope |
| Customer Meta AI settings variants | Automation & AI → Customer AI | Preserve distinct config fields; internal AI stays separate |
| Flow design/publish variants | Automation & AI → Flows → selected version | Existing provider constraints and version history |
| Blog production/review/QA/publish pages | Content workflow with deep-linked stages | Real stage permissions/actions; URLs remain usable |
| Infrastructure dashboard/registry/code/design references | Platform metadata + repository docs | Admin health kept; stale snapshots removed from UI authority |
| Existing Tasks + contextual agent approvals | Work task/run detail | Existing task contracts retained; durable agent execution added |

Full 113-route mapping is in `workspace-canonical-destinations-20261007.csv`. Mapping a route to a destination means its capability belongs there; it is not deletion approval or proof that its current backend works.

## Public/customer pages remain a separate experience

```text
Public site → Products / Services / Content / Help
Customer    → WhatsApp OTP → Cart / Orders / Request / Amendment / Checkout state
Staff       → Workspace authentication → Operational areas / Settings
```

Keep the 36 public route patterns and canonical product/content URLs unless a separate content decision says otherwise. Use shared public header/footer/product components and one checkout-state component for success/status URLs. Do not introduce the staff sidebar, agent privileges or staff login policy into cart/order flows.

## Release sequence and success measures

1. Fix misleading success/error states and contract gaps; baseline page payload, request volume and task completion steps.
2. Introduce registry, shell and shared list/detail components. Pilot Work and staff requests behind readiness gates.
3. Consolidate Inbox, then Service Ops/Campaigns, then Payments/Catalog and Content. Extract reusable components from routed page files; redirect only after parity.
4. Release integrations/automation/platform changes with deployment evidence and the separate agent phase gates.
5. Remove obsolete implementations only after inbound links, role behavior, embedded consumers and rollback paths are verified.

Measure reachable primary destinations, duplicated implementation removed, time/steps to complete a real task, visible request count, payload size, cold/warm load time, failure clarity and agent verified-completion rate. Targets: 14 primary destinations; one Inbox implementation; one Contact 360; one response/request workspace; one task/agent queue. These are design targets, not completed reductions or measured savings. Keep deep links and existing customer capabilities.

Research basis: Shopify's resource-index pattern supports searchable/filterable resource collections and contextual detail (https://shopify.dev/docs/api/app-home/latest/patterns/templates/resource-index). W3C consistent-navigation guidance supports stable ordering (https://www.w3.org/WAI/WCAG22/Understanding/consistent-navigation.html). The specific layout above is our recommendation adapted to this repository.
