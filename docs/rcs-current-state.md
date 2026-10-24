# Sinch RCS — current state

Read-only discovery, 2026-09-22. Account `775261844268`, region `us-east-1`,
principal `arn:aws:iam::775261844268:user/wecare-admin`. Single-account estate, so
this is **production**; there is no separate dev or staging account.

No credential value appears in this document.

## The headline finding

**Our RCS integration does not run on the Sinch platform that the official Sinch MCP
server talks to.**

| | Our running integration | Official Sinch MCP server |
|---|---|---|
| Auth host | `auth.aclwhatsapp.com` (Keycloak realm `ipmessaging`) | Sinch Build OAuth2 |
| Grant | `password`, `client_id=ipmessaging-client` | access key / client credentials |
| Credentials | `username` + `password` | `KEY_ID` + `KEY_SECRET` |
| Send host | `convapi.aclwhatsapp.com/v1/projects/{id}/messages:send` | `*.conversation.api.sinch.com` |
| Template host | `api.aclwhatsapp.com/access-api/v2/rcs/{appId}/templates` | Sinch Template Management |

`aclwhatsapp.com` is not a third party. **Sinch acquired ACL Mobile Limited (India)
in 2020** ([Sinch press release](https://www.group.sinch.com/media/press-releases-and-news/2020/sinch-ab-publ-sinch-expands-to-india-through-acquisition-of-acl-mobile/),
[TechCrunch](https://techcrunch.com/2020/06/15/sinch-to-buy-indias-acl-mobile-for-70-million/)),
so these are legitimate Sinch-India endpoints inherited from that acquisition. The
integration *is* Sinch. It is simply on the India platform rather than the global
Conversation API. Content rephrased for compliance with licensing restrictions.

Why it matters: the official MCP server authenticates only against the global
platform, so **it cannot introspect, manage or even authenticate against our RCS
setup as it stands.** Its README is explicit that with `MCP_AUTH_MODE` unset a
partial `PROJECT_ID`/`KEY_ID`/`KEY_SECRET` triple refuses to start — and we hold no
`KEY_ID` or `KEY_SECRET` at all.

The identifiers are nonetheless Sinch-shaped, which is the encouraging part:
`project_id` is a UUID and `app_id` is a ULID, exactly the global platform's formats.
So the same project plausibly exists on the global platform and an access key could be
minted for it. That is unverified and is the unblock, not an assumption.

## Credentials and configuration

`wecare/sinch/rcs` — ARN `arn:aws:secretsmanager:us-east-1:775261844268:secret:wecare/sinch/rcs-18kRci`

| Field | Present | Read by |
|---|---|---|
| `username` | yes | `sinch_rcs.py`, `rcs-send` (auth, and as the template-API app id) |
| `password` | yes | `sinch_rcs.py`, `rcs-send` (auth) |
| `project_id` | yes | `sinch_rcs.py` (send URL path) |
| `app_id` | yes | `sinch_rcs.py` (payload `app_id`) |
| `bot_id` | yes | **only** `rcs-send._delete_template` |
| `key_id` | **absent** | — |
| `key_secret` | **absent** | — |
| `auth_name` | **absent** | — |
| `auth_token` | **absent** | — |
| `webhook_secret` | **absent** | — |

Five fields, no rotation configured, default `aws/secretsmanager` KMS key, last
changed 2026-05-05, **last accessed 2026-09-22** — so it is live and in use.

`wecare/sinch/sms` is **scheduled for deletion** (2026-09-20), last accessed
2026-09-19. Consistent with the Sinch-SMS retirement. Not touched.

**No Sinch or RCS configuration exists in SSM Parameter Store or S3.** Everything is
in Secrets Manager plus Lambda environment variables. So there is no S3 credential
exposure to remediate — the Phase 17 S3 question resolves to "none found".

### The authName → senderId mapping the brief asks about does not exist here

The brief describes the global platform's RCS provisioning model, where the sender's
`authName` becomes the Conversation API `senderId` and `authToken` becomes the
`bearerToken`. **Neither field is stored, and nothing in our code references them.**

That is consistent rather than broken: on the India platform the binding between the
app and the RCS agent is made by Sinch-side provisioning against `app_id`/`bot_id`,
not by our application supplying sender credentials. The mapping becomes relevant only
if this integration is migrated to the global Conversation API.

## Live Lambda configuration

| | `wecare-rcs-send` | `wecare-rcs-dlr` |
|---|---|---|
| Env keys | `CONTACTS_TABLE`, `LOG_LEVEL`, `RCS_APP_ID`, `RCS_PROJECT_ID`, `RCS_SECRET_NAME`, `RCS_TABLE` | `CONTACTS_TABLE`, `LOG_LEVEL`, `RCS_TABLE` |
| `RCS_SECRET_NAME` | `wecare/sinch/rcs` | absent → code default `wecare/sinch/rcs` |
| `RCS_TABLE` | `stack-wecare-digital-RcsMessagesTable` | same |
| Timeout | 30s | 15s |
| `SINCH_RCS_ENABLED` | **absent** | **absent** |

Two findings in that table.

**`RCS_TABLE` is stale.** It names `stack-wecare-digital-RcsMessagesTable`, which does
not exist in the account — the drift audit already classifies it `ACCEPTED_ABSENT`. The
code constants were removed on 2026-09-21 and nothing reads the variable, so it is
inert residue in both the live config and `config/lambda-env-manifest.json`.

**`SINCH_RCS_ENABLED` is absent, and it does not gate what you would expect.**
`is_rcs_enabled()` is checked by `sinch_rcs.py` — the *notification* path — so
connected-call and IVR RCS is off. It is **not** checked by `rcs-send/handler.py`, which
is an authenticated HTTP route. So the dashboard can send RCS today while the
notification path cannot. That asymmetry is undocumented and is the single most
surprising operational fact in this audit.

## What exists in code

| Path | Role |
|---|---|
| `amplify/functions/shared/lambda_utils/sinch_rcs.py` | shared client: auth, token cache, text/card/template senders, `send_rcs_ivr_notification`, `is_rcs_enabled` |
| `amplify/functions/messaging/rcs-send/handler.py` | authenticated HTTP route: send, list messages, list/create/delete templates |
| `amplify/functions/messaging/rcs-dlr/handler.py` | public webhook `POST /webhook/sinch-rcs`: delivery reports, inbound, opt-in/out |
| `amplify/functions/shared/lambda_utils/sinch_signature.py` | raw-body HMAC verification for the public callback |
| `src/pages/dm/rcs/{index,send,templates,campaign,inbox,logs}.tsx` | a full six-page RCS dashboard |
| `tests/test_rcs_provider_isolation.py` | asserts Sinch stays confined to RCS |

Callers of `send_rcs_ivr_notification`: `whatsapp-calling` (terminate + post_call_sip) and the
notifications worker (`lambda_utils/notifications/worker.py`). The call trigger points are
ones the connected-call brief classifies as prohibited, and they fired **0** times in the 14
days to 2026-09-21 — so the RCS notification path had no live traffic.

## Sinch-side state — NOT discoverable

Everything in this section requires either the MCP server or the Sinch India control
plane, and neither is currently reachable. Recording them as unknown rather than
guessing:

| Item | State |
|---|---|
| Sinch Project | `project_id` known from the secret (UUID, not printed here) |
| Conversation API App | `app_id` known from the secret (ULID, not printed here) |
| Conversation region | **UNKNOWN** — not stored anywhere, and not in any Lambda env |
| RCS Sender / Agent | **UNKNOWN** — `bot_id` exists in the secret but no sender record was retrieved |
| RCS Sender state | **UNKNOWN** (`DRAFT`/`IN_TEST`/`LAUNCHED`/…) |
| Sender region | **UNKNOWN**, so the app-region/sender-region match cannot be verified |
| `countryStatus[]`, operator status, remarks | **UNKNOWN** |
| `testNumberStates[]` | **UNKNOWN** |
| Device capabilities | **UNKNOWN** |
| `conversationApiAppDetails.channelStatus` | **UNKNOWN** — cannot confirm `ACTIVE`/`PENDING`/`FAILING` |
| RCS webhooks registered at Sinch | **UNKNOWN** from the Sinch side; our receiving endpoint is `POST https://wecare.digital/api/webhook/sinch-rcs` |

The one operator signal we do have is a code comment, not a readback: the three
templates are documented in both handlers as *"approved, Jio, MEDIUM height"*. If
accurate, RCS reach is **Jio only** — one Indian operator — which would materially
limit delivery. It needs confirming against `countryStatus[]`.

## Templates

Three named in code, all described as approved rich cards on Jio:

| Name | Purpose per code | Referenced by |
|---|---|---|
| `rcsmenu` | IVR / call-disconnect notification | `sinch_rcs.send_rcs_ivr_notification`, default in `rcs-send` |
| `rcsorder` | order confirmation | named in docstrings only — **no sender** |
| `waalert` | WhatsApp alert | named in docstrings only — **no sender** |

`send_rcs_order_notification()` and `send_rcs_wa_alert()` were deleted on 2026-09-19 as
dead senders, so `rcsorder` and `waalert` exist remotely with no code path.

Template management is reachable through our own authenticated route
(`action: templates|create_template|delete_template` on `wecare-rcs-send`), which
proxies the Sinch-India template API. **That is the export path available to us** —
`list-messaging-templates` over MCP is not.

## Message types the code can send

| Type | Built by | Notes |
|---|---|---|
| text | both | `text_message` |
| text + buttons | `rcs-send` | `choice_message` when `choices` supplied |
| standalone rich card | both | `card_message`; `sinch_rcs.send_rcs_card` adds media + URL choices |
| carousel | `rcs-send` only | `carousel_message`, pass-through from the request body |
| template | both | `template_message.channel_template.RCS` |
| media | via card | no standalone `media_message` sender |
| location | — | not built; inbound location *is* parsed |

`channel` is always the literal `"RCS"` in `channel_identities`. There is no
`platform: ios`/`android` anywhere, and no `sendToIOS`/`sendToAndroid`. The
architecture already matches the brief's requirement of one integration, one channel,
one sender.

## EXISTING NON-RCS DEPENDENCY — the SMS fallback

`rcs-send/handler.py`:

```python
if body.get('fallback'):
    payload["channel_priority_order"] = ["RCS", "SMS"]
```

An RCS→SMS fallback **already exists**, per-request and opt-in. Per the brief this is
documented, not modified or expanded.

Measured reachability: **no caller sets `fallback`**. Not the six RCS dashboard pages,
not `sinch_rcs.py`, nothing in the repo. So the branch is dormant — present in code,
never exercised. It is also the only place in the RCS path that could cause a Sinch SMS
send, which would breach the Sinch-SMS retirement if it ever fired.

Recommendation, not yet applied: since nothing sets it and `wecare/sinch/sms` is
already scheduled for deletion, removing this branch would close the last route by
which the RCS credential could send SMS. That is a behaviour-affecting change and needs
owner approval.

## Defects found during discovery

**1. Delivery status can move backwards.** `rcs-dlr._process_delivery` applies every
report with an unconditional `SET #s = :status`. A late `QUEUED` (mapped to `sent`)
overwrites `read`; a re-delivered `FAILED` overwrites `delivered`. This is precisely the
defect fixed for WhatsApp on 2026-09-21 by `lambda_utils/wa_status`, which already
provides the rank + `ConditionExpression` mechanism to fix it. Severity **HIGH** —
corrupts what operators see.

**2. Inbound messages can collide.** When Sinch supplies no `message_id`,
`_process_inbound` falls back to `f'rcs-in-{int(time.time())}'` — one-second resolution.
Two inbound messages in the same second share an id and one overwrites the other.
Severity **MEDIUM**, and it is also the webhook-idempotency gap the brief asks about.

**3. Foreign numbers are rewritten into fabricated Indian ones.** Two independent
copies: `sinch_rcs._normalize_phone` and `rcs-send._send_rcs` both do "if it does not
start with 91, take the last 10 digits and prepend 91". `+6581234567` (Singapore, 10
digits in full E.164) becomes `+916581234567` — a different, real Indian subscriber.
This is the exact misdelivery class that `lambda_utils/comms/numbers.py` was written to
eliminate, and its docstring documents the same bug having caused a real misdelivery.
`numbers.to_e164` already solves it correctly. Severity **HIGH**.

**4. Identifiers hardcoded as fallback defaults.** `project_id`, `app_id`, `bot_id` and
`username` all have literal defaults in code, so a stale value is used silently if the
secret field is missing rather than failing loudly. Severity **LOW** (they are not
secrets) but it defeats the purpose of storing them centrally.

**5. `SINCH_RCS_ENABLED` gates only half the surface** — see the Lambda table above.
Severity **MEDIUM**, documentation-level.

## Blockers

| # | Blocker | Unblock |
|---|---|---|
| 1 | No `KEY_ID`/`KEY_SECRET`, so the MCP server cannot start | Create an access key at Settings → Access keys in the Sinch Build dashboard for our project, and store `key_id`/`key_secret` in `wecare/sinch/rcs` |
| 2 | RCS may not be enabled on the *global* project | Per the MCP README, RCS activation is requested from Sinch at `si-richmessaging@sinch.com` |
| 3 | `webhook_secret` absent, so callbacks cannot be authenticated | Configure a signing secret on the Sinch webhook and store it as `webhook_secret` |
| 4 | Conversation region unknown | Read back from Sinch once MCP or the India control plane is reachable |
| 5 | Sender state / country / operator status unknown | Same |

Until 1 and 2 are resolved, Phases 4, 5, 9, 10 and the MCP half of 11 cannot be
completed as specified. Everything achievable without them is being done from our own
side: the authenticated template route, the runtime trace, the callback audit and the
tests.
