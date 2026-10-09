# Meta Flow retirement — 9 October 2026

Owner explicitly requested deprecation of every Flow outside the planned customer-service set. Completed via Meta API through the existing IAM-authorized Business API Lambda. No customer messages, charges, new publication or draft deletion.

Full paginated inventory across WABA2094615664435155 and2513394156072604:59 Flows. Before:11 PUBLISHED,22 DRAFT,26 DEPRECATED. Nine obsolete published Flows retired successfully and read back DEPRECATED. After:2 PUBLISHED,22 DRAFT,35 DEPRECATED.

## Retained plan

| Flow | ID | Meta state |
|---|---|---|
| WD_Orders_Design_v1 | 2167802357142172 | DRAFT |
| WD_Shipments_Design_v1 | 849713848195607 | DRAFT |
| WD_Submit_Request_Paid_v1 | 1107164111921876 | PUBLISHED |
| WD_Leave_Review_v2 | 1578178897413815 | PUBLISHED |
| WD_Drop_Documents | 1211063631104445 | DRAFT |
| 03.WD_Amend_Request | 3678132465672138 | DRAFT |

Vault has no planned separate Flow. Profile/account screens belong in the retained Orders draft. Submit/Review design duplicates and Vault design preview are not retained customer Flow choices.

## Newly deprecated

| Flow | ID | WABA |
|---|---|---|
| 03.WD_POSTPAY_REQUEST | 2672013166527523 | 2094615664435155 |
| WD Submit Request v2 | 1018621047428701 | 2094615664435155 |
| WD Post-Payment Details v1 | 1529800232178121 | 2094615664435155 |
| 02.WD_Profile | 1262971692700761 | 2094615664435155 |
| 03.WD_POSTPAY_REQUEST | 1021379973921053 | 2513394156072604 |
| WD Submit Request v2 | 1935472957154109 | 2513394156072604 |
| WD Post-Payment Details v1 | 959273520451230 | 2513394156072604 |
| WD Post-Payment Details (Test) | 2150051392227837 | 2513394156072604 |
| 02.WD_Profile | 951987930811295 | 2513394156072604 |

## Draft boundary and routing follow-up

Eighteen DRAFT Flows are outside the retained plan. Meta's deprecate action applies to published Flows; they remain unpublished and were not deleted. Their IDs/names and complete before/after inventory are in flow-retirement-2026-10-09.json. Existing DEPRECATED Flows remain historical records.

Legacy Subscribe keyword routes still refer to retired Profile IDs1262971692700761/951987930811295, and selfservice UI labels the first published. Those stale references must be disabled/replaced with the planned verified Orders/profile entry before customer release. Do not attempt to republish the retired Profile as a shortcut, silently route to an unrelated Flow or fabricate a new account. Other old template/flow buttons may refer to deprecated versions; inventory/retarget only as intended, preserving approved template contracts. This retirement does not certify complete routing cleanup.

## Backend repair and validation

Fixed _deprecate_flow to POST /<Flow-ID>/deprecate rather than metadata status mutation, with explicit owning-WABA token context. Fixed _list_flows to paginate and fail closed on missing/repeated cursor; no partial inventory returned as complete. Added5 regressions covering two WABAs, provider failure and cursor behavior. Focused135 passed; full backend10339 passed /7 skipped /3 expected failures. Candidate unauthorized HTTP returned401. Exact ZIP changes handler.py only; all other deployment members preserved. Business API90 hash pAiHGtHkI2cK9AYiUHlNtDlWtiqTXS4++KbMZX1CioI= deployed with revision-guarded alias89→90. Native/payment/writeback/upload gates remain unchanged/off.

## Rollback and continuation

Code rollback: read current alias/revision and guarded90→89 only if needed. This does not restore retired Meta Flows. Recovery of a retired customer contract requires a verified replacement Flow and explicit routing/template migration; do not imply alias rollback reverses provider lifecycle changes. Retained paid Submit/Review and source registry paid record are unaffected. No FlowRegistry bulk sync or overwrite performed.

Next: disable/replace stale retired-Flow entry references and reconcile the eighteen unused draft artifacts without publishing them. Continue Vault renewal and remaining native engineering from xcodex-new-session-full-prompt.md.

Primary API reference: https://www.postman.com/meta/whatsapp-business-platform/request/uje0iad/deprecate-flow
