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
| Direct Send authentication | BUILT_GATED | BUILT_GATED | Shared Direct Send foundations present | Meta beta/eligibility required |
| Marketing Messages API | BUILT_GATED | OWNER_ACTION | Partial | WECARE app review shows Marketing API Access Tier not live/rejected; Manish needs an app first |
| Marketing conversion/click measurement | PARTIAL | OWNER_ACTION | Partial | Complete the attribution loop after Marketing API access is granted |
| Marketing product fallback policy | MISSING | OWNER_ACTION | No product_policy handling found | Add after Marketing API entitlement |
| Catalog management | BUILT_GATED | OWNER_ACTION | Significant code exists | WECARE app review shows catalog_management not live/rejected; complete review evidence |
| Catalog/product messages | PARTIAL | OWNER_ACTION | Built | Provider entitlement/catalog connection required |
| WhatsApp Flows | BUILT_GATED | OWNER_ACTION | Strong implementation | Live verification/asset readiness still required per flow |
| Calling API | BUILT_GATED | OWNER_ACTION | Built | Provider/account entitlement and live call QA required |
| Groups API | BUILT_GATED | OWNER_ACTION | Built | Provider/account eligibility and live group QA required |
| Business username | AVAILABLE in code | OWNER_ACTION | Built | Verify live read/write before any mutation |
| Official business account status | AVAILABLE | PARTIAL | Built/read-only | No action required for WECARE |
| Messaging limit / quality read | AVAILABLE in code | PARTIAL | Built/read-only | Use this for Direct Send eligibility diagnostics |
| Template lifecycle/quality | AVAILABLE | PARTIAL | Built | Manish app parity required for full webhook lifecycle |
| Template library create | AVAILABLE through connector | AVAILABLE through connector | Repo support varies | Prefer library entries for ordinary utility/auth use cases |
| Limited-time-offer templates | PARTIAL | PARTIAL | Partial/template-builder references | Add only if business need justifies it |
| Media/product carousels | PARTIAL | PARTIAL | Partial | Validate latest Meta payload contracts before enabling |
| Coexistence with WhatsApp Business app | PARTIAL | OWNER_ACTION | Webhooks subscribed; audit-only processing | Implement message echoes/state sync as a first-class ingestion path if coexistence is desired |
| Message history synchronization | PARTIAL | OWNER_ACTION | history webhook stored as system event only | Build async chunk/phase ingestion for coexistence history before claiming support |
| Multi-Partner Solutions | PARTIAL | OWNER_ACTION | partner_solutions is audit-only | Design partner lifecycle/ownership before activation |
| Automatic Events | AVAILABLE after 2026-10-26 patch | OWNER_ACTION | Durable system-event capture | Add domain-specific processing only when required |
| Tracking Events | AVAILABLE after 2026-10-26 patch | OWNER_ACTION | Durable system-event capture | Feed into marketing attribution after entitlement |
| Business status update webhook | AVAILABLE after 2026-10-26 patch | OWNER_ACTION | Durable system-event capture | Surface operational alerts as needed |
| Business capability update webhook | AVAILABLE | OWNER_ACTION | Durable system-event capture | Use to refresh feature readiness dynamically |
| Two-step verification management | MISSING | MISSING | Registration accepts PIN when required, no management surface | Add set/change management only with an explicit operational requirement |
| Pre-verified phone onboarding | MISSING | MISSING | Not found | Add only for partner onboarding at scale |
| Business compliance information API | MISSING | MISSING | Not found | Add read-only support if compliance operations need it |
| Business encryption management API | PARTIAL | PARTIAL | Flow crypto exists; account encryption API is separate | Add only if provider/account encryption management is required |
| Analytics lake / Athena catalog | MISSING | MISSING | No WhatsApp Glue table found in us-east-1 | Create curated event/delivery/attribution tables if long-term analytics is a priority |

## Provider blockers confirmed live

- WECARE.DIGITAL core onboarding checks are complete: business profile, app, phone registration, webhook callback, account subscription, published app, and payment method.
- Manish Agarwal has a verified business, registered production phone and payment method, but no WhatsApp-enabled developer app administered through the current connection. Webhooks, account subscription and published-app readiness therefore remain incomplete.
- The WECARE.DIGITAL Meta app has live advanced access for `whatsapp_business_messaging`, `whatsapp_business_management`, `whatsapp_business_manage_events`, `business_management`, and `manage_app_solution`.
- The same app currently reports `Marketing API Access Tier` and `catalog_management` as not live/rejected. App Review also reports an unfinished catalog screencast step and an unfinished Marketing API precheck in the active submission.
- The app is compliant with no open compliance violations.
- Live Direct Send QA to both production senders returned Meta error #100 stating that Direct Send is not enabled for the account. Production therefore keeps Direct Send fail-closed.

## Event coverage corrected on 2026-10-26

The live WECARE.DIGITAL app subscribes to newer WhatsApp fields including `automatic_events`, `tracking_events`, and `business_status_update`. These are now explicitly captured through the inbound worker's existing durable SystemEvent path, alongside existing fields such as `business_capability_update` and `history`.

## Priority order

1. Complete WECARE.DIGITAL App Review evidence for Marketing API and catalog management.
2. Connect/admin a WhatsApp-enabled developer app for Manish Agarwal; then configure/publish/subscribe it.
3. Keep Direct Send disabled until Meta grants eligibility; re-test before re-enabling each account independently.
4. Complete Marketing Messages conversion/click attribution and fallback-policy handling.
5. Promote coexistence/history from audit-only capture to explicit asynchronous ingestion if WhatsApp Business app coexistence is a business requirement.
6. Implement Message History chunk/phase processing with idempotency and backpressure before exposing imported history in Inbox.
7. Add Multi-Partner Solutions only if WECARE.DIGITAL is intentionally operating a partner lifecycle for customer accounts.
8. Build a curated WhatsApp analytics lake only if cross-period campaign/delivery attribution is needed beyond DynamoDB/CloudWatch operational views.
