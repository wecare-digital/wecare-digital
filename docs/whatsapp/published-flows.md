# Published customer WhatsApp Flows

Last checked: 30 October 2026. Canonical WABA: `2094615664435155`.

For the **31 October 2026 live Meta template/button reconciliation** and exact AWS DynamoDB registry names, see [WhatsApp templates, Flow IDs and AWS registries](../operations/whatsapp-template-flow-aws-registry-20261031.md).

The repository deliberately retains **seven** Meta Flow JSON definitions, all
under `amplify/functions/messaging/whatsapp-business-api/flows/published/`.

| Capability | Flow ID | JSON asset |
|---|---|---|
| Subscribe / Profile | `2413873616105042` | `subscribe.json` |
| Leave Review | `993862443003108` | `f002-leave-review.json` |
| Drop Docs | `39581903361452878` | `f003-drop-docs.json` |
| Submit Request | `993516553092471` | `submit-request.json` |
| Request Amendment | `2408621596338289` | `request-amendment.json` |
| Pickup Request | `2988393421499259` | `request-pickup.json` |
| Track Shipment | `1804165164183485` | `shipments.json` |

The TypeScript and Python identity sources are `src/lib/canonicalFlows.ts`
and `amplify/functions/shared/lambda_utils/canonical_flows.py`.
Orders and Vault have no published WhatsApp Flow asset.
Pickup Request's current runtime launcher is intentionally disabled until its
completion payload matches the pickup-specific contract.

The previous `flows/design-drafts/` and versioned top-level legacy JSON files
were removed from the working tree on 30 October 2026, along with the
`serviceDesignDrafts` Lambda handler action and the unpublished asset generator.
Their historical existence can still be inspected through Git history; removing
tracked files does not erase prior Git commits or Meta's deprecated Flow records.

Meta status synchronization and registry authorization remain independent.
Do not republish historic designs or treat a Meta PUBLISHED status as runtime
authorization to send.
