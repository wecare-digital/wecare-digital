# WhatsApp templates, Flow IDs and AWS registries — verified 2026-10-31

Scope: WECARE.DIGITAL, business portfolio `382642103987922`; production Messaging Account `2094615664435155`. The inventory below is **read-only verification**, not permission to activate a Flow or send a message.

## Sources and authority

- **Meta is authoritative** for template approval, button components and Flow publication. On 2026-10-31 both the live `wecare-whatsapp-business-api:live` GET `/wa-business/payment-templates/list?wabaId=2094615664435155` and `wecare-whatsapp-template-management:live` GET `/whatsapp/templates?wabaId=2094615664435155&maxResults=200` returned the same **14** approved English templates. The latter includes the Flow button targets.
- **Meta Flow list**: live `wecare-whatsapp-business-api:live` GET `/wa-business/flows?wabaId=2094615664435155` returned **seven retained PUBLISHED** Flows with empty validation errors and `health_status.can_send_message=AVAILABLE`.
- **AWS application registries**: consistent table read/Scan and DescribeTable in `us-east-1`, AWS account `775261844268`, yielded seven FlowRegistry rows and fifteen WhatsAppTemplateRegistry rows. The fifteen-to-fourteen disagreement is recorded below; don't silently treat the AWS rows as a fresh Meta approval signal.
- **Source identities**: `src/lib/canonicalFlows.ts` and `amplify/functions/shared/lambda_utils/canonical_flows.py`; business template contract `amplify/functions/shared/lambda_utils/whatsapp_templates.py`. The seven retained Flow JSON files live under `amplify/functions/messaging/whatsapp-business-api/flows/published/`.

## Current retained Flows

| Capability | Exact Flow ID | Meta name | Meta status | AWS FlowRegistry |
|---|---|---|---|---|
| F001 Subscribe / Profile | `2413873616105042` | `WD-F001-SUBSCRIBE-PROFILE` | PUBLISHED / AVAILABLE | Present |
| F002 Leave Review | `993862443003108` | `WD-F002-LEAVE-REVIEW` | PUBLISHED / AVAILABLE | Present |
| F003 Drop Docs | `39581903361452878` | `WD-F003-DROP-DOCS` | PUBLISHED / AVAILABLE | Present |
| F004 Submit Request | `993516553092471` | `WD-F004-Submit-Request` | PUBLISHED / AVAILABLE | Present |
| Request Amendment | `2408621596338289` | `WD-F004-Request-Amendment` | PUBLISHED / AVAILABLE | Present |
| F005 Pickup Request | `2988393421499259` | `WD-F005-Pick-Up-Request` | PUBLISHED / AVAILABLE | Present; **fulfillment blocked** |
| F006 Track Shipment | `1804165164183485` | `WD-F006-Track-Shipping` | PUBLISHED / AVAILABLE | Present |

Orders, Vault and Track Request have no canonical retained Flow. This table is an operational list of retained Flows, **not** a listing of historical/deprecated Meta Flow versions.

**Important:** the Pickup registry record still has `fulfillmentReadiness=BLOCKED_META_COMPLETION_PAYLOAD_INCOMPLETE`, despite Meta reporting PUBLISHED and AVAILABLE. Do not enable the payment/fulfillment launch path without verifying the actually published Flow JSON and signed completion contract.

## Current approved Meta templates

Every row below is `en` and APPROVED in the 2026-10-31 Meta live readback. Template IDs and Flow IDs are different identifiers.

| Template name | Exact template ID | Category | Button / canonical Flow ID |
|---|---|---|---|
| `wecare_default_invoice_image_template` | `1782246473079550` | UTILITY | FLOW Leave Review → `993862443003108` |
| `wecare_pdf_direct_download` | `1428669922724280` | UTILITY | FLOW Subscribe → `2413873616105042` |
| `submit_request_flow` | `30181571061431980` | UTILITY | FLOW Submit Request → `993516553092471` |
| `request_amendment_flow` | `4034771700165582` | UTILITY | FLOW Request Amendment → `2408621596338289` |
| `_dropdoc_flow` | `1041974032198332` | UTILITY | FLOW Drop Docs → **`39581903361452878`** |
| `pickup_request_flow` | `1449099850671553` | UTILITY | FLOW Pickup Request → `2988393421499259` |
| `wecare_leave_review` | `1801972550682516` | UTILITY | FLOW Leave Review → `993862443003108` |
| `track_ship_flow` | `1107523855531222` | UTILITY | FLOW Track Shipment → `1804165164183485` |
| `service_details` | `2419125382263851` | UTILITY | FLOW View Details → `2413873616105042` |
| `wecare_location_share_pin` | `1628859001974131` | UTILITY | LOCATION header; no Flow button |
| `wecare_default_download` | `1410998911012572` | UTILITY | URL Access Vault; no Flow button |
| `wecare_whatapp_native_pay_template` | `2714938845570815` | UTILITY | ORDER_DETAILS Review and Pay; no Flow button |
| `wecare_order_status_v3` | `1754227779211208` | UTILITY | No button; order-status component |
| `wecare_otp` | `1292079089453029` | AUTHENTICATION | Copy-code URL; no Flow button |

All **nine** Flow-button templates currently point to the correct canonical Flow IDs with `flow_action=DATA_EXCHANGE`. The approved payment template is spelled `whatapp` (not `whatsapp`) in its actual name; do not silently rename it.

## Where the AWS registry data is stored

All listed tables are DynamoDB tables in account `775261844268`, region `us-east-1`.

| Table name | Primary key | Observed item count | Role |
|---|---|---:|---|
| `stack-wecare-digital-FlowRegistryTable` | `flowId` | 7 | Capability/Flow identity, launch policy, Meta status synchronization |
| `stack-wecare-digital-WhatsAppTemplateRegistryTable` | `templateId` | 15 | Application-side template name, language, category and ID reconciliation |
| `stack-wecare-digital-FlowDraftTable` | `draftKey` | Estimated 18 | Flow drafts; not the publication source of truth |
| `stack-wecare-digital-FlowSubmissionTable` | `submissionId` | Estimated 6 | Flow submissions; customer data, not a template inventory |
| `stack-wecare-digital-FlowLogTable` | `logId` | Estimated 13 | Flow logs |
| `stack-wecare-digital-TemplateAnalyticsTable` | `id` | Estimated 0 | Template analytics, not the template registry |

The first two counts were verified by scanning the metadata tables. Supporting-table counts above are DynamoDB DescribeTable estimates, not scans. **Do not copy customer submissions or secrets into documentation.**

## Reconciliation needed

1. **One orphaned/unverified AWS template record:** `stack-wecare-digital-WhatsAppTemplateRegistryTable` and `whatsapp_templates.py` both still include `wecare_vault_request_ready`, ID `29124703577146420`, but the current provider approval and component lists return only 14 templates and do not include it. A targeted archived/deleted/paused/rejected template lookup also returned no record. Verify its actual provider lifecycle and Vault send-path dependency before retiring, disabling or deleting anything. The registry row's historical `Meta-approved-template-reconciliation-2026-10-30` source is **not** proof of current approval.
2. **Correction to the 2026-10-30 Drop Docs audit:** the live provider component returned the Flow target **`39581903361452878`**, which matches the canonical Flow ID. The earlier audit's **`39581903361452880`** is exactly what JavaScript `Number('39581903361452878')` renders after unsafe-integer rounding. Flow IDs of this size must be compared and serialized as **strings**, not JavaScript Numbers. **Do not edit/re-submit the approved Drop Docs template based on that old mismatch.**
3. **Pickup remains held:** Meta PUBLISHED/AVAILABLE does not override `fulfillmentReadiness=BLOCKED_META_COMPLETION_PAYLOAD_INCOMPLETE` in the live AWS FlowRegistry row. Keep the current release guards until published-asset and completion checks succeed.
4. **Approval is distinct from send readiness:** Flow publication, registry activation, signed user/payment ownership, Flow token/INIT, and handset completion must be checked separately before enabling customer traffic.

## Repeatable non-mutating audit entry points

- `scripts/check_whatsapp_templates_live.py` — provider approval/category plus Flow-button target reconciliation.
- `scripts/check_flow_registry_live.py` — canonical launch contract versus DynamoDB registry rows.
- `docs/whatsapp/published-flows.md` — retained published Flow JSON mapping.
- `docs/operations/whatsapp-shared-flow-audit-20261030.md` — historical risk audit; see the correction recorded above.

No Meta template, published Flow, AWS DynamoDB row, runtime flag, or Lambda alias was changed to produce this report.
