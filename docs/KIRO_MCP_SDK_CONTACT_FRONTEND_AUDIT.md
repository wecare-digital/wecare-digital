# Kiro MCP, SDK, Contacts, Flow CRM, Frontend and Video Audit

Audit date: 20 September 2026. This is a repository/configuration snapshot, not a claim about perpetual provider state.

## Executive disposition

| Area | What exists now | Material gap or risk | Required disposition |
|---|---|---|---|
| Kiro plaintext credentials | Six unsafe shell permission entries represented at least four credential families: ad API, Razorpay, duplicate Plivo and Google keys | Values were executable command patterns; historical Kiro session/log records still contain credential variable names and may contain values | Active `permissions.yaml` sanitized and kept mode `0600`; rotate/revoke every exposed provider credential, then validate each consumer from Secrets Manager. Do not paste replacement values into shell commands, prompts, JSON or YAML |
| MCP configuration | Global AWS MCP plus official Meta WhatsApp Business Tools and Meta DevTools; workspace MCP was empty | No Google Cloud or Razorpay MCP; payment MCP would expose high-impact write tools | Workspace config now includes pinned Google Cloud MCP, approval-gated; Razorpay remote MCP is configured disabled, with write tools disabled and an environment placeholder only |
| SDKs | Current direct JS/Python provider SDK set is already pinned or bounded; Plivo Browser SDK is exact `2.2.21` | Declared packages are not the same as proven runtime paths; major-only updates to ESLint/TypeScript are available and must not be bundled into communications work | Produce an import-to-feature matrix before upgrades. Preserve Plivo Browser `2.2.21` until its browser matrix is re-run. Keep unrelated major tooling upgrades separate |
| Contacts | DynamoDB `Contact`, `[retired public path 44011e36]`, Contact 360 and common inbox exist | No Google People import, no OAuth connection/sync-token model, and no Truecaller callback. Flow code uses `Key={'id': contact_id}` while the schema key is `contactId` | Build server-side Google People read-only sync and consent-bound Truecaller verification. Fix the key contract with migration tests before relying on enrichment |
| Lead/pipeline | Contact and several order/service models exist | No `Lead`, `Pipeline`, `PipelineStage`, `Opportunity` or source-link model | Add an explicit CRM layer; never overload Contact tags or raw Flow JSON as the pipeline |
| WhatsApp Flow data | `FlowRegistry`, `FlowSubmission`, `FlowDraft`, `FlowLog`, `SubmitRequest`; generic submission persistence and configurable contact mapping | Lead/pipeline linking absent; two submission implementations drift; some code writes fields not represented by the schema; contact enrichment errors are swallowed | One idempotent Flow completion service must resolve Contact, create/update Lead/Opportunity, persist one submission, apply allowlisted mappings and append an activity event transactionally |
| Frontend | More than 100 Pages Router pages plus one App Router settings page; very broad nested navigation | Multiple duplicate inbox/settings/flow/voice pages, legacy redirects, test pages and `ComingSoon` shells conflict with the intended three-entry communications navigation | Consolidate into Common Inbox, WhatsApp Settings and PSTN Settings with inner tabs. Remove a route only after import/link/API/traffic/SEO/authorization checks and a redirect decision |
| Default video message | `wd_menu` template with a VIDEO header and a hard-coded `customerservice.mp4` link; URL returned HTTP 200 `video/mp4` during this audit | Direct sends exist in incoming-call, IVR and post-call paths, creating duplicate risk; fallback uses `_send_via_aws`; state is written to old outbound/notification tables; video URL is hard-coded | One direct-Meta template dispatcher behind the exactly-once outbox. Select one event policy, persist the real WAMID and delivery receipts, and never mark delivered from a send acceptance |
| Kiro agent health | `kiro-cli mcp list` resolves the default AWS, Meta, Google Cloud and disabled Razorpay entries | The command reports stale missing `file://` prompt resources for the mounted KiroCrew bundle and four pptx-maker agent prompts | Repair/remove only the broken owning agent references after inventorying their packages; do not confuse these prompt-path errors with an MCP connection failure |

## MCP inventory and secure JSON contract

| MCP | Scope/config | Authentication | Read/write risk | Current action |
|---|---|---|---|---|
| AWS MCP | `~/.kiro/settings/mcp.json`; `mcp-proxy-for-aws` against the regional AWS MCP endpoint | AWS profile `wecare-prod`; no literal secret | AWS tools can mutate resources depending on tool and IAM | Retain globally; no wildcard auto-approval; enumerate live schemas in Kiro before each production action |
| Meta WhatsApp Business Tools | Global remote `https://mcp.facebook.com/whatsapp_business_tools` | Provider OAuth/session | WhatsApp account/number/template/webhook writes may affect production | Retain; discover schemas; safe reads first; production writes gated |
| Meta Social Technologies | Global remote `https://mcp.facebook.com/devtools` | Provider OAuth/session | App, webhook, permission and compliance operations | Retain; use the nine documented skills; production writes gated |
| Google Cloud | Workspace stdio `npx -y @google-cloud/gcloud-mcp@0.5.3` | Active gcloud account/project | The single `run_gcloud_command` tool may read or mutate within IAM permissions | Added and enabled with `autoApprove: []`; pin retained; use least-privilege service-account impersonation before production mutations |
| Razorpay | Workspace remote `https://mcp.razorpay.com/mcp` | `Authorization: Basic ${RAZORPAY_MERCHANT_TOKEN}` | Payment capture, orders, links, refunds, QR, settlements and token operations | Added but disabled; explicit mutation tools disabled. Rotate the leaked live key pair, create the merchant token outside tracked files, approve only the environment variable, then test read-only fetches |

`kiro-cli mcp list` confirmed the merged default-agent configuration contains `aws-mcp`, `devtools`, `google-cloud`, disabled `razorpay`, and `whatsapp-business-tools`. The Google entry resolves as enabled with no configured environment values; the Razorpay entry resolves as disabled. This proves configuration discovery, not a successful provider handshake. Capture connection/tool-list evidence separately.

The active workspace file `.kiro/settings/mcp.json` is intentionally Git-ignored. Keep `.kiro/settings/mcp.example.json` as the tracked, credential-free source template and copy/merge it locally; never change the example to contain a resolved credential.

**Razorpay MCP — enabling it is an owner action.** The tracked template carries the
`razorpay` entry (Razorpay's official Model Context Protocol server over its payment
APIs, `https://mcp.razorpay.com/mcp`) with `"disabled": true`, `autoApprove: []`, a
`${RAZORPAY_MERCHANT_TOKEN}` placeholder and all nineteen money-moving tools in
`disabledTools`. Enabling it requires credentials from the existing secret store
(`wecare/razorpay`) and is therefore the owner's step, not an agent's: copy the
template to the Git-ignored `mcp.json`, flip `disabled`, and supply the token after
the leaked live key pair recorded above has been rotated. The placeholder variable is
documented in `.env.local.example`. Nothing in `amplify/` or `src/` reads it — it is
developer tooling and must never enter a Lambda environment.

Kiro supports `${VARIABLE_NAME}` expansion in MCP environment values and headers after explicit approval. No MCP config may contain a resolved token. Do not use `autoApprove: ["*"]`. Pin executable packages, record package integrity/version, inspect tool schemas after connection and store a redacted capability inventory in `docs/mcp-capability-inventory.md`.

Official sources:

- Kiro MCP configuration and environment expansion: https://kiro.dev/docs/mcp/configuration/
- Kiro MCP security model: https://kiro.dev/docs/mcp/security/
- Official Google gcloud MCP: https://github.com/googleapis/gcloud-mcp
- Official Google MCP catalog: https://github.com/google/mcp
- Official Razorpay MCP: https://github.com/razorpay/razorpay-mcp-server
- Razorpay MCP endpoint: `https://mcp.razorpay.com/mcp`

## Direct SDK inventory

| Family | Declared version | Purpose found or intended | Audit result |
|---|---:|---|---|
| Next / React | Next `^16.2.9`; React `^19.2.7` | Web application | In range; do not mix framework migration with provider cutover |
| AWS Amplify | backend `^1.23.0`, UI `^6.15.4`, client `^6.18.0` | Auth, data, infrastructure and frontend | Keep; verify generated client/schema after data-model changes |
| AWS SDK/CDK | Bedrock Runtime `^3.1076.0`; CDK `2.270.0`; boto3/botocore `1.43.98` | AWS runtime/control plane/IaC | Current at audit; confirm Lambda packaged versions independently of dev requirements |
| Capacitor | `8.x` packages | Android/iOS shell and device APIs | Required if Truecaller native SDK is selected; browser-only integration must not assume native callbacks |
| Plivo Browser SDK | exact `2.2.21` | Browser softphone | Preserve exact pin; login method exists but UI/token HTTP route remain acceptance items |
| Plivo Python | `4.62.0` | Control-plane tooling | Current at audit; not proof a Lambda should hold Plivo credentials |
| Meta Python Business SDK | `26.0.1` | Meta Graph tooling | Current at audit; production WhatsApp send path must still be direct Graph API and version-tested |
| Google Ads / Ad Manager | `32.0.0` / `0.10.5` | Advertising integrations | Separate from Google People contacts; never reuse an API key as OAuth credentials |
| Google OAuth/Auth | `google-auth 2.58.0`, `google-auth-oauthlib 1.4.1` | Server OAuth | Usable foundation; add People API client or direct REST only after an authorization-code + PKCE design |
| OpenAI | `3.16.2` | AI features/tooling | Current at audit; exposed ad-service key must be rotated even if a newer secret exists |
| Razorpay Python | `2.0.1` | Payment API | Current at audit; live-key rotation and consumer readback precede MCP enablement |
| ElevenLabs | `2.68.0` | Potential voice/TTS | Declared but current runtime comments say Polly is used; mark unused unless import/runtime evidence proves otherwise |
| ESLint / TypeScript | `9.39.5` / `6.0.3` | Tooling | New major versions exist; defer to an isolated compatibility change |

## Contact identity and enrichment architecture

Google Contacts means the Google People API; the legacy Contacts API was shut down in 2022. Use authorization-code flow with PKCE and minimum scope `https://www.googleapis.com/auth/contacts.readonly`. Call `people/me/connections` with an explicit field mask, paginate fully and request a sync token. Sync tokens expire after seven days, so schedule incremental sync more frequently and fall back to a full sync on `EXPIRED_SYNC_TOKEN`. Encrypt refresh tokens; never return them to the browser.

Truecaller is not a bulk reverse-lookup API for enriching arbitrary CRM phone numbers. Its documented SDK is a user-consent phone-verification/profile-return flow. Build it only for the person currently verifying their own identity. Validate nonce/state, callback origin and access token server-side, fetch the consented profile from the provider-returned endpoint, normalize the verified E.164 number and link it to the Contact. Do not query Truecaller for every imported Google contact or WhatsApp sender.

| Model | Key fields | Purpose |
|---|---|---|
| `OAuthConnection` | connectionId, userId, provider, encryptedTokenRef, scopes, expiresAt, status | Google account authorization metadata; token value remains in Secrets Manager/KMS-backed storage |
| `ContactSourceLink` | sourceLinkId, contactId, provider, externalResourceName, externalEtag, sourceUpdatedAt | Stable mapping from Google Person/Truecaller consent/Meta identity to one Contact |
| `ContactImportJob` | jobId, connectionId, cursorRef, syncTokenRef, counts, status, errorCode | Full/incremental People API job observability and resumability |
| `ContactIdentity` | identityId, contactId, type, normalizedValueHash, verifiedAt, verificationProvider | E.164/email/BSUID/username identities without treating phone as immutable universal ID |
| `Lead` | leadId, contactId, source, status, ownerId, score, consentState, createdAt | Sales/service qualification attached to a Contact |
| `Pipeline` | pipelineId, name, active | Pipeline definition |
| `PipelineStage` | stageId, pipelineId, name, ordinal, terminalType | Ordered stages |
| `Opportunity` | opportunityId, leadId, pipelineId, stageId, value, currency, status, sourceSubmissionId | A lead's progress/value; one contact may have several opportunities |
| `CRMActivity` | activityId, contactId, leadId, opportunityId, type, providerEventId, occurredAt, payloadRef | Append-only inbox/call/Flow/stage history |

Matching precedence is: verified provider mapping, exact normalized E.164 within tenant, verified email within tenant, then manual-review queue. Never merge automatically by display name. Every merge is audited and reversible. Google deletion tombstones unlink the source; they do not delete the CRM Contact or communication history automatically.

## WhatsApp Flow to Contact/Lead/Pipeline contract

```text
Meta Flow completion webhook
  -> signature + replay validation
  -> idempotency claim(provider event / flow token / submission number)
  -> resolve tenant + ContactIdentity
  -> upsert Contact with allowlisted FlowRegistry.contactMapping
  -> persist one immutable FlowSubmission(raw + normalized fields)
  -> apply FlowCRMRule
       -> create/update Lead
       -> create/update Opportunity and permitted stage
       -> append CRMActivity
  -> enqueue allowed acknowledgement/template
  -> receipt/status reconciliation
```

Add `FlowCRMRule` with `flowId/flowCode`, mapping version, lead policy, pipeline/stage policy, field allowlist and consent policy. Add `leadId`, `opportunityId`, `mappingVersion` and `providerEventId` to `FlowSubmission`. Validate destination field names against a server allowlist; a database-configured mapping must never be able to overwrite consent, ownership, keys or audit fields.

First fix the existing primary-key mismatch (`Contact.contactId` versus `Key={'id': contact_id}`), unify the duplicate generic submission writers, and align schema with runtime attributes such as TTL/attachments/request identifiers. Add tests for replay, concurrent completion, unknown mapping, invalid stage transition, contact not found, duplicate phone, consent preservation and transaction retry.

## Frontend consolidation and guarded retirement table

Target communications navigation has exactly three top-level entries: Common Inbox, WhatsApp Settings and PSTN Settings. Contacts/leads/pipeline are inner CRM panes reachable from the Inbox/contact drawer, not additional provider inboxes.

| Existing surface | Target | Action |
|---|---|---|
| `[retired public path 2de923b8]/inbox`, `[retired public path 2de923b8]/whatsapp`, `[retired public path 2de923b8]/whatsapp/inbox`, `[retired public path 2de923b8]/rcs/inbox`, `[retired public path 2de923b8]/ses/inbox` | `[retired public path 2de923b8]/inbox` | Keep one implementation; channel filters/tabs replace provider inbox pages; redirect old bookmarks |
| `[retired public path 44011e36]`, `[retired public path 2de923b8]/contact-360`, `[retired public path 2de923b8]/search` | Inbox right drawer + Contacts/Leads/Pipeline inner tabs | Merge capabilities; retain a canonical deep-linkable contact route if external links require it |
| All `[retired public path 2de923b8]/whatsapp/*` setup, template, Flow, calling, webhook, compliance and analytics pages | `[retired public path 2de923b8]/whatsapp/settings?tab=...` | Convert to lazy inner tabs; keep stable redirects; never remove WABA registration/number management |
| `[retired public path 2de923b8]/voice`, `[retired public path 2de923b8]/voice-in`, `[retired public path 2de923b8]/calls` PSTN parts | `[retired public path 2de923b8]/pstn?tab=...` | Consolidate Plivo/browser softphone, numbers, routing, IVR, calls, recordings, conferences, analytics and troubleshooting |
| `[retired public path 84a04c24]`, `[retired public path a2557b8d]`, `[retired public path 169e0fd8]` | Existing canonical destinations | Remove redirect-only components after permanent redirects exist |
| `/contact-test`, `[retired public path 89347bb2]/cors-settings`, `[retired public path 89347bb2]/order-notifications`, `/nocode`, `/carbon` | None unless evidence proves use | Candidate removal: zero or test-only static references; verify live traffic, APIs, SEO and authorization first |
| `ComingSoon` shells (`forms/create`, `forms/logs`, `link/create`, `link/logs`, `task`) | Real owner surface or none | Remove from production navigation; delete only after product decision and redirect map |
| RCS/SMS/Email pages | Common Inbox/settings appropriate to retained provider ownership | Do not delete valid AWS SMS, AWS non-India RCS, Sinch India RCS or SES functionality merely to simplify navigation |

Deletion gate per route: source owner, navigation/import references, API calls, inbound deep links, authorization wrapper, analytics/live access for the observation window, SEO/canonical status, replacement, redirect, test update and rollback commit. Static reference count alone is not proof of non-use.

## Default WhatsApp video-template send

Current behavior uses template `wd_menu`, language `en`, VIDEO header, and public link `https://app.wecare.digital/stream/media/m/customerservice.mp4`. The link returned HTTP 200 with `content-type: video/mp4` and approximately 1.3 MB during this audit. The verified WABA1 template object ID from the preceding Meta audit is `998210796499191`; re-read approval/components for every sending WABA before live use.

The handler currently has at least three direct template dispatch locations: incoming-call notification, IVR-menu send and SIP post-call send. It can also fall back through `_send_via_aws`, writes old `WhatsAppOutboundTable` rows and records `CallNotificationsTable`. Replace these with one event policy:

| Canonical event | Default policy | Send asset | Exactly-once key |
|---|---|---|---|
| `WHATSAPP_CALL_CONNECTED` | No video by default unless product policy explicitly chooses connected-time send | none | callId + event + recipient + channel |
| `WHATSAPP_CALL_ENDED` | Send one `wd_menu` from the receiving WABA if approved/eligible | VIDEO header using configured HTTPS asset; direct Meta only | callId + ended + recipient + whatsapp + template + language |
| `PSTN_CALL_CONNECTED` | Existing connected notification policy controls SMS/RCS/WhatsApp eligibility | same dispatcher if WhatsApp is eligible | CallUUID + connected + recipient + channel |

Store the asset URL/config version outside source, preflight HTTPS/content type/size, and record the Meta request ID/WAMID. A successful Graph response means accepted/sent, not delivered. Delivery/read/failure comes only from verified Meta status webhooks. If template send fails, record failure and retry through the outbox policy; do not silently change transport to AWS Social Messaging or send a free-form message outside the customer-service window.
