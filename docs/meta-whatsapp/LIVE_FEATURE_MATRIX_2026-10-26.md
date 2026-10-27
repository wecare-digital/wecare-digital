# WhatsApp Business Platform live feature matrix

**Checked:** 2026-10-26  
**Scope:** WECARE.DIGITAL and Manish Agarwal production WhatsApp businesses  
**State vocabulary:** AVAILABLE = provider + account + deployed code can support the capability; BUILT_GATED = implementation exists but provider/account access is missing or intentionally disabled; PARTIAL = some code/event coverage exists but the end-to-end capability is incomplete; MISSING = no production implementation found; OWNER_ACTION = requires business/app administration outside AWS code.

| Capability | WECARE.DIGITAL (+91 93309 94400) | Manish Agarwal (+91 99033 00044) | WECARE implementation | Next action |
|---|---|---|---|---|
| Core Cloud API messaging | AVAILABLE | PARTIAL | Built | Manish needs an administered WhatsApp developer app for complete app/webhook parity |
| Business verification | AVAILABLE | AVAILABLE | Provider state | None |
| Registered production phone | AVAILABLE | AVAILABLE | Provider state | Use the linked/registered Manish sender only; ignore the older migrated record |
| Payment method | AVAILABLE | AVAILABLE | Provider state | None |
| Developer app | AVAILABLE | OWNER_ACTION | External | Connect/admin a WhatsApp-enabled developer app on Manish Agarwal |
| App published | AVAILABLE | OWNER_ACTION | External | Publish the Manish app after it is connected |
| Webhook callback | AVAILABLE | OWNER_ACTION | Built | Configure callback after Manish app connection |
| Account-to-app webhook subscription | AVAILABLE | OWNER_ACTION | Built | Subscribe the Manish account after app connection |
| Direct Send utility | BUILT_GATED | BUILT_GATED | Built and fail-closed | Meta returned error #100: Direct Send is not enabled on either account; keep allowlist empty |
| Direct Send authentication | BUILT_GATED | BUILT_GATED | Built with approved-template fallback; production allowlist is empty after live Meta refusal | Keep fail-closed until Meta explicitly enables authentication Direct Send |
| WhatsApp Marketing Messages API | AVAILABLE | AVAILABLE | Live onboarding readback is ONBOARDED for both WABAs | Keep normal consent/policy gates; this is distinct from Meta Marketing API Full Access |
| Meta Marketing API Access Tier | BUILT_GATED | BUILT_GATED | App Review privilege is not live; current Full Access precheck is unmet | Legitimate API usage must satisfy Meta's qualification threshold; do not manufacture traffic |
| Marketing conversion/click measurement | PARTIAL | OWNER_ACTION | Partial | Complete the attribution loop after Marketing API access is granted |
| Marketing product fallback policy | BUILT_GATED | OWNER_ACTION | `product_policy` supports `CLOUD_API_FALLBACK` / `STRICT` with regression tests | Enable only after Marketing API entitlement |
| Catalog management | BUILT_GATED | OWNER_ACTION | Significant code exists | WECARE app review shows catalog_management not live/rejected; complete review evidence |
| Catalog/product messages | PARTIAL | OWNER_ACTION | Built | Provider entitlement/catalog connection required |
| WhatsApp Flows | BUILT_GATED | OWNER_ACTION | Strong implementation | Live verification/asset readiness still required per flow |
| Calling API | AVAILABLE | AVAILABLE | Live settings show calling ENABLED with SIP enabled on both production numbers | Preserve SIP/call-permission safeguards; handset acceptance QA remains operational testing, not an entitlement gap |
| Groups API | AVAILABLE | AVAILABLE | Live list endpoint succeeds on both WABAs; WECARE currently has the `Bharat Stack` group | No provider eligibility action required |
| Business username | AVAILABLE in code | OWNER_ACTION | Built | Verify live read/write before any mutation |
| Official business account status | AVAILABLE | AVAILABLE | Both production phone numbers read back as Official Business Accounts with GREEN quality | None |
| Messaging limit / quality read | AVAILABLE in code | PARTIAL | Built/read-only | Use this for Direct Send eligibility diagnostics |
| Template lifecycle/quality | AVAILABLE | PARTIAL | Built | Manish app parity required for full webhook lifecycle |
| Template library create | AVAILABLE through connector | AVAILABLE through connector | Repo support varies | Prefer library entries for ordinary utility/auth use cases |
| Limited-time-offer templates | PARTIAL | PARTIAL | Partial/template-builder references | Add only if business need justifies it |
| Media/product carousels | BUILT_GATED | BUILT_GATED | Media/template carousels exist; interactive product carousel now follows Meta `carousel` + `action.cards[]` (2–10 cards) | Controlled live send still requires provider/catalog readiness |
| Coexistence with WhatsApp Business app | AVAILABLE | AVAILABLE | Raw events are archived and the no-automation Inbox replay lane is deployed; production `whatsapp_coexistence_ingest=true` | Monitor replay/dedup metrics; no automation or service-window mutation occurs on imported events |
| Message history synchronization | AVAILABLE | AVAILABLE | History phase/chunk/progress is archived and deduplicated into the canonical Inbox without replaying automation; production ingestion is enabled | Monitor imported-history volume and dedup outcomes |
| Multi-Partner Solutions | PARTIAL | OWNER_ACTION | partner_solutions is audit-only | Design partner lifecycle/ownership before activation |
| Automatic Events | AVAILABLE after 2026-10-26 patch | OWNER_ACTION | Durable system-event capture | Add domain-specific processing only when required |
| Tracking Events | AVAILABLE after 2026-10-26 patch | OWNER_ACTION | Durable system-event capture | Feed into marketing attribution after entitlement |
| Business status update webhook | AVAILABLE after 2026-10-26 patch | OWNER_ACTION | Durable system-event capture | Surface operational alerts as needed |
| Business capability update webhook | AVAILABLE | OWNER_ACTION | Durable system-event capture | Use to refresh feature readiness dynamically |
| Two-step verification management | AVAILABLE in code | PARTIAL | Admin set/change PIN route + Workspace control; PIN is never persisted | Live use requires an owner-selected 6-digit PIN; disabling remains WhatsApp Manager-only per Meta |
| Pre-verified phone onboarding | MISSING | MISSING | Not found | Add only for partner onboarding at scale |
| Business compliance information API | MISSING | MISSING | Not found | Add read-only support if compliance operations need it |
| Business encryption management API | PARTIAL | PARTIAL | Flow crypto exists; account encryption API is separate | Add only if provider/account encryption management is required |
| Analytics lake / Athena catalog | MISSING | MISSING | No WhatsApp Glue table found in us-east-1 | Create curated event/delivery/attribution tables if long-term analytics is a priority |

## Provider blockers confirmed live

- WECARE.DIGITAL core onboarding checks are complete: business profile, app, phone registration, webhook callback, account subscription, published app, and payment method.
- Manish Agarwal has a verified business, registered production phone and payment method, but no WhatsApp-enabled developer app administered through the current connection. Webhooks, account subscription and published-app readiness therefore remain incomplete.
- The WECARE.DIGITAL Meta app has live advanced access for `whatsapp_business_messaging`, `whatsapp_business_management`, `whatsapp_business_manage_events`, `business_management`, and `manage_app_solution`.
- The same app currently reports `Marketing API Access Tier` and `catalog_management` as not live/rejected. This does **not** block the WhatsApp Marketing Messages API, whose WABA onboarding reads back `ONBOARDED` on both accounts. App Review still reports an unfinished catalog screencast step and an unfinished Marketing API precheck in the active submission.
- The app is compliant with no open compliance violations.
- Direct Send remains provider-gated. Utility and authentication production allowlists are now both empty, so sends fail closed to the existing service/template paths until Meta explicitly grants access.

## Event coverage corrected on 2026-10-26

The live WECARE.DIGITAL app subscribes to newer WhatsApp fields including `automatic_events`, `tracking_events`, and `business_status_update`. These are now explicitly captured through the inbound worker's existing durable SystemEvent path, alongside existing fields such as `business_capability_update` and `history`.

## Priority order

1. Complete the active Meta App Review evidence: catalog-management screencast and the Marketing API Full Access usage precheck.
2. Keep Direct Send disabled until Meta grants eligibility; re-test each WABA/category independently before changing either allowlist.
3. Complete the marketing conversion/click attribution loop where business reporting requires it.
4. Add Multi-Partner Solutions only if WECARE.DIGITAL intentionally operates a partner lifecycle for customer accounts.
5. Build a curated WhatsApp analytics lake only if cross-period campaign/delivery attribution is needed beyond DynamoDB/CloudWatch operational views.


## Correction — shared secondary account integration

The Manish Agarwal production sender is not waiting for a separate Manish-owned developer app. The production code and prior live Graph verification show that the secondary account uses the WECARE.DIGITAL app and shared system-user integration. The WhatsApp Business connector's onboarding checklist only reports apps directly administered under the Manish business, so its "no developer app you administer" result is a visibility limitation and must not be treated as proof that the shared WECARE app relationship is absent.

For the secondary sender, preserve the existing WECARE.DIGITAL app/token path and validate account subscription through the WECARE system-user/Graph integration. Do not create a duplicate app merely to satisfy the connector checklist.
