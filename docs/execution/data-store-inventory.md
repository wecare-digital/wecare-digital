# Data store inventory and drift

Measured 2026-09-21 · account `775261844268` · `us-east-1`
Tool: `python scripts/audit_data_model_drift.py`

## The headline: declared models and deployed tables are two disjoint worlds

`amplify/data/resource.ts` declares **65 models**. The account holds **66 tables**.
Almost none of the names correspond:

| Declared model | Live table |
|---|---|
| `Contact` | `stack-wecare-digital-ContactsTable` |
| `Message` | `stack-wecare-digital-MessagesTable` |
| `VoiceCall` | `stack-wecare-digital-VoiceCalls` |
| `WhatsAppInbound` | `stack-wecare-digital-WhatsAppInboundTable` |

`backend.ts` reaches tables indirectly, through
`backend.data.resources.cfnResources.amplifyDynamoDbTables[modelName]`, and it
imports at least one table by literal name
(`dynamodb.Table.fromTableName(..., 'stack-wecare-digital-WebhookDedup')`).

The first version of the drift script assumed `Model` → `stack-wecare-digital-Model`
and reported 61 declared-but-absent models plus 62 deployed-but-undeclared tables.
That was an artefact of the guess, not a finding. The script no longer asserts any
mapping; it compares **exact table-name literals in Python** against `ListTables`,
because both sides of that comparison are facts.

**Open question for Phase 1, not answered here:** whether the Amplify data models
are deployed at all, or whether the live tables predate this Amplify app and the
schema is aspirational. Until that is settled, `resource.ts` must not be treated as
a description of production. The TTL registry in `backend.ts` names 25 models and
the override is wrapped in a `try/catch` that logs and continues, so a silent
mismatch there would not surface.

## Referenced by code, absent from the account

Six, after classifying out SQS queues, Lambda function names and bare prefixes that
share the `stack-wecare-` prefix. Three were retired-provider names that have since been
removed with their code; the other three are below.

| Name | Named by | Assessment |
|---|---|---|
| `…-SmsAwsTable` | `messaging/sms-aws`, `core/messages-read`, `operations/system-cleanup` | **Not a live SMS defect.** Sends write `UNIFIED_TABLE`; the only remaining use is a best-effort legacy `delete_item`. The Phase 4 migration stopped the dual-write and made the canonical store sole. Dead references to remove |
| `…-PstnNotificationDelivery` | `shared/lambda_utils/pstn/claims.py` | `NOTIF-STORE-001`. Declared in `resource.ts` and the TTL registry, named here, and **no table exists**. Inert only because `PSTN_CONNECTED_NOTIFICATIONS_ENABLED` is false |
| `…-SystemConfig` | `operations/system-cleanup` | Wrong name — the live table is `…-SystemConfigTable`. A cleanup pass naming it would fail |

`…-RcsMessagesTable` was a seventh. The three `RCS_TABLE` constants naming it were
removed on 2026-09-21 — each was assigned once and never read, the Phase 4
migration having stopped every legacy RCS write. It is retained in the script's
`ACCEPTED_ABSENT` list with that reason, so a reintroduction is still reported.

## Deployed environment residue

Read from live function configuration, not from source:

| Function | Variable | Problem |
|---|---|---|
| `wecare-rcs-dlr` | `RCS_TABLE` | names a table that does not exist; now inert since the constant was removed |

`wecare-sms-aws`, `wecare-system-cleanup` and `wecare-messages-read` carry **no**
table variables at all, so they run entirely on their source defaults. That is why
a wrong default is not automatically masked by configuration.

## Consequence for Phase 3

`NOTIF-STORE-001` is answered: `PstnNotificationDelivery` is declared in four
places and deployed nowhere. Phase 3 should not create it as-is. The brief already
requires a **fresh** provider-neutral notification domain — `NotificationEvent`,
`NotificationDelivery`, `NotificationAttempt`, `Outbox` — that replaces both
`PstnNotificationDelivery` and the live-but-legacy `CallNotificationsTable`. So the
correct disposition is to design the new stores, deploy them, and delete the
declaration rather than materialise a model nobody finished.

Until then the claim path is unreachable, because
`PSTN_CONNECTED_NOTIFICATIONS_ENABLED` defaults to false — but that is a flag
holding back a latent `ResourceNotFoundException`, not a working feature.

## Live but unreferenced from Python

Five tables exist that no Python literal names. Not necessarily wrong — a table may
be reached through an environment variable with no literal default, or written only
by the frontend data layer — but their names cannot be traced from backend source:

`AmendmentHistoryTable`, `DocumentHistoryTable`, and three others listed by the
script. Phase 1 should join these to their writers.
