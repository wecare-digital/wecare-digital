# WhatsApp template-to-Flow mapping — production sync

**Environment:** AWS account `775261844268`, `us-east-1`. WABA `2094615664435155`.

## Authoritative sources and boundaries

- The Meta Graph API `GET /{waba}/message_templates` is authoritative for **approved** template IDs/names and FLOW button `flow_id` associations.
- The Meta Graph API `GET /{waba}/flows` supplies Flow publication, validation and sendability health. Only the **seven canonical retained** Flow IDs may be mapped.
- The dedicated DynamoDB table `stack-wecare-digital-WhatsAppTemplateFlowMappingTable` is a **snapshot**, not a template-send authorization or proof of successful customer completion. Key: `flowId` (string HASH) + `templateId` (string RANGE), with `templateId-index` GSI.
- The existing `WhatsAppTemplateRegistryTable`, `FlowRegistryTable`, Meta assets, customer sends, payments, and runtime launch flags are **never modified by this synchronization**. They have their own ownership.

## Deployed reconciler

- Source: `amplify/functions/messaging/whatsapp-business-api/flows/template_flow_sync.py`, invoked from `handler.py` only through guarded `internalAction=syncTemplateFlowMappings`.
- AWS EventBridge scheduled rule: `wecare-whatsapp-template-flow-meta-sync`, **rate(1 hour)**, default bus, **ENABLED**.
- One target: Lambda alias `arn:aws:lambda:us-east-1:775261844268:function:wecare-whatsapp-business-api:live`.
- Rule ARN: `arn:aws:events:us-east-1:775261844268:rule/wecare-whatsapp-template-flow-meta-sync`.
- Target input is a static JSON object with `internalAction=syncTemplateFlowMappings`, `source=aws.events`, `detail-type=Scheduled Event`, and that rule ARN under `resources`. HTTP-shaped events are rejected.
- The Lambda `live` alias has a scoped resource-based permission `AllowTemplateFlowMetaSyncHourly`, principal `events.amazonaws.com`, with that rule ARN and source account condition.
- Lambda execution role `wecare-digital-lambda-role` has a narrow inline IAM policy `TemplateFlowMappingAtomicSync` permitting `dynamodb:TransactWriteItems` **only** on the mapping table. Existing registry scans use existing permissions.

The helper pages full Meta inventories, validates canonical IDs and Flow availability, and uses one DynamoDB transaction to update the snapshot and remove genuinely stale links. If Meta is unavailable, a page is truncated, or link identities/health are inconsistent, it raises and does not perform a partial update. The mapping `lastVerifiedAt` advances only after successful reconciliation. This does **not** independently verify the published Flow JSON bytes or a handset transaction.

## Verification and investigation

- `GET /wa-business/flow-registry?includeTemplateMappings=true` exposes the linked templates and exact string IDs; the default GET response stays backward compatible.
- The Flow Hub in Workspace uses that opt-in GET to show names/IDs for each retained customer Flow.
- Read the nine rows in DynamoDB with a consistent Scan. Subscribe and Leave Review should each link to two templates; Drop Docs Flow ID `39581903361452878` must remain a **string**.
- Check `/aws/lambda/wecare-whatsapp-business-api` for `template_flow_meta_sync_complete` or `Template-to-Flow scheduled reconciliation failed`.
- Check EventBridge rule state and Lambda alias version if the `lastVerifiedAt` time stops advancing. Meta errors are not a reason to force-enable payment or send messages.

## Rollback

1. Disable EventBridge rule `wecare-whatsapp-template-flow-meta-sync` to stop scheduled writes.
2. If the new backend code is faulty, move `wecare-whatsapp-business-api:live` back to its prior verified Lambda version using a revision-guarded alias update. Do not repackage the entire codebase or overwrite another deployer's `$LATEST`.
3. Retain the mapping table data and IAM audit; do not delete or recreate customer records. The previous mapping API remains independently read-only.

## Test gates

- `python -m unittest discover -s tests -p test_template_flow_auto_sync.py`
- `python -m unittest discover -s tests -p test_template_flow_registry_mapping.py`
- `npm run typecheck`, `npm run lint`, `npm run build` and the brace-depth guard.
- A scoped backend release uses a pinned source SHA and patch of the currently running Lambda ZIP. The production alias must be checked before and after publishing.
