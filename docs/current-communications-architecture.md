# Current communications architecture

What runs today for SMS, voice, RCS and WhatsApp. Function and route names come from the deploy
map in `scripts/deploy_all_lambdas.py` and the handlers under `amplify/functions/messaging/`;
re-read those before relying on a detail. The AWS account facts in §6 are a dated measurement.

---

## 1. Providers

| Channel | Provider | Functions |
|---|---|---|
| SMS | AWS End User Messaging SMS (`pinpoint-sms-voice-v2`), TRAI DLT for India | `wecare-sms-aws`, `wecare-outbound-sms` |
| Voice — PSTN | Plivo | `wecare-plivo-answer`, `wecare-pstn-softphone`, `wecare-voice-cdr-read` |
| Voice — outbound voice messages | AWS End User Messaging voice (`SendVoiceMessage`) | `wecare-voice-aws` |
| Voice — WhatsApp | Meta WhatsApp Business Calling | `wecare-whatsapp-calling` |
| RCS | Sinch India | `wecare-rcs-send`, `wecare-rcs-dlr` |
| WhatsApp messaging | Meta Cloud API (Graph) | `wecare-outbound-whatsapp`, `wecare-inbound-whatsapp`, `wecare-whatsapp-business-api` |

Post-call and order notifications fan out through `wecare-notification-worker`, which has SMS,
WhatsApp and Sinch RCS adapters (`amplify/functions/notifications/worker.py`).

---

## 2. SMS — AWS End User Messaging with TRAI DLT

Shared layer: `amplify/functions/shared/lambda_utils/comms/` (`numbers`, `region`, `dlt`, `sms`,
`notify`).

- **Region.** Indian numbers send from `ap-south-1`, everything else from `us-east-1`
  (`comms/region.py`).
- **India.** `OriginationIdentity=WDBEEP` plus `DestinationCountryParameters`
  `IN_ENTITY_ID` / `IN_TEMPLATE_ID` (`comms/sms.py`, `sms-aws/handler.py`).
- **International.** Pinned to toll-free `+18444891209`. The simulator `+14255556333` sits in
  the same pool, accepts sends and delivers nothing, which is why the pool is never used as
  the origination identity.
- **DLT, one source of truth.** `comms/dlt.py` holds entity `1201161991108627443`, sender
  `WDBEEP` (registration `1405170900886606599`) and the approved template map; the DynamoDB
  registry `stack-wecare-digital-DLTTemplates` is the fallback. Lookup fails closed: an Indian
  send without an approved template is refused with `422 MISSING_DLT_TEMPLATE`.

| Template key | DLT template id |
|---|---|
| `ivr-default` | `1007277993798259629` |
| `wa-alert` | `1007284579074821763` |
| `wd_order` | `1007723091207562020` |

| Sender | Route | Implementation |
|---|---|---|
| `wecare-sms-aws` | `POST /sms-aws/send` | inline `pinpoint-sms-voice-v2` `send_text_message` |
| `wecare-outbound-sms` | `POST /sms/send` | `comms.sms` `AwsSmsProvider`; any provider other than AWS is refused `422 UNSUPPORTED_PROVIDER`; a raw `dltTemplateId` must be in the approved map |

Callers:

- `wecare-plivo-answer` → `wecare-sms-aws:live`, asynchronous, Indian callers only.
- `wecare-whatsapp-calling` and `wecare-notification-worker` → `comms.notify` →
  `wecare-sms-aws:live`.
- `wecare-bulk-worker` and `wecare-ai-generate-response` → `wecare-outbound-sms`.

Delivery receipts are **not ingested**. Status is recorded at submission (`SENT`/`FAILED`), and
`comms.sms` reports `UNKNOWN_NO_RECEIPTS` for anything later.

---

## 3. Voice

### 3.1 Plivo PSTN

`wecare-plivo-answer` (`amplify/functions/messaging/plivo-answer/handler.py`) serves
`/plivo/answer`, `/plivo/fallback`, `/plivo/hangup`, `/plivo/events` and `/plivo/dial-events`
for the Plivo application `WECARE-WHATSAPP-IVR`.

- Default call flow is `<Play>` then `<Hangup/>`. Browser routing (`<Dial><User>`) runs only
  when `PSTN_BROWSER_ROUTING_ENABLED=true`, which defaults to false.
- Plivo V3 signatures (`X-Plivo-Signature-V3` / `-Ma-V3`, HMAC-SHA256 over URL + nonce) are
  verified by `lambda_utils/plivo_signature.py`: required on hangup, events and dial-events,
  verified when present on answer and fallback.
- Secrets: `wecare/plivo-answer`, `wecare/plivo/api`.
- CDRs are written to `stack-wecare-digital-VoiceCDRTable` (`plivo#{CallUUID}`) and read by
  `wecare-voice-cdr-read`.
- Dial events feed the notifications outbox drained by `wecare-notification-worker`.

Browser softphone: `wecare-pstn-softphone` serves `/pstn/token`, `/pstn/session`,
`/pstn/session/events`, `/pstn/session/presence` and `/pstn/diagnostics`. It mints a Plivo JWT
(300 s, voice grants, `lambda_utils/pstn/browser_token.py`) only when
`PSTN_BROWSER_ROUTING_ENABLED=true`.

### 3.2 AWS End User Messaging voice

`wecare-voice-aws` sends voice messages with `pinpoint-sms-voice-v2` `send_voice_message` in
`us-east-1` (SSML, Polly voice). The origination identity comes from
`VOICE_ORIGINATION_IDENTITY` (`+18444891209` in `config/lambda-env-manifest.json`); an empty
value refuses the send. Invoked by `wecare-ai-generate-response`.

### 3.3 Meta WhatsApp calling

`wecare-whatsapp-calling` serves `/whatsapp`: the Meta webhook (verify and events), call
control through Graph `/{phone_id}/calls`, and forwarding of non-call webhook fields to
`wecare-inbound-whatsapp`.

- After a call it sends the WhatsApp follow-up, the `ivr-default` SMS through `comms.notify`
  → `wecare-sms-aws`, and Sinch RCS when `SINCH_RCS_ENABLED=true`.
- SIP mode: the Asterisk AGI callback (`post_call_sip`) and the `sip.wecare.digital`
  certificate check are handled here.
- The live SIP target is a Meta-side calling setting, not stored in code. Read it through
  `wecare-whatsapp-business-api` (`_get_calling_settings`); `_update_calling_settings` writes it
  and `_redact_sip_credentials` keeps SIP passwords out of responses.

---

## 4. RCS — Sinch India

`amplify/functions/shared/lambda_utils/sinch_rcs.py`, `wecare-rcs-send`, `wecare-rcs-dlr`.

- Auth: `auth.aclwhatsapp.com` (password grant). Send:
  `POST https://convapi.aclwhatsapp.com/v1/projects/{projectId}/messages:send`. Template admin:
  `api.aclwhatsapp.com`.
- Secret `wecare/sinch/rcs`; templates `rcsmenu` (default), `rcsorder`, `waalert`.
- `send_rcs_ivr_notification` invokes `wecare-rcs-send`, with a direct Sinch call as fallback.
  `wecare-rcs-send` never falls back to SMS.
- `wecare-rcs-dlr` serves `POST /webhook/sinch-rcs` with HMAC verification and fails closed.
- There is no AWS RCS implementation; `notifications/policy.py` only carries a stub behind
  `AWS_RCS_AVAILABLE` (see §6 for why AWS RCS cannot be used yet).

---

## 5. WhatsApp messaging — Meta Cloud API

- Direct Graph calls (`graph.facebook.com/{version}`); the version is decided in one place,
  `lambda_utils/meta_version.py`, and pinned per function in the env manifest.
- One credential, `wecare/meta-system-user-token`.

---

## 6. AWS End User Messaging — measured account state

Read live on 2026-09-19.

### ap-south-1 (India)

```
sender id      WDBEEP   IN   Promotional,Transactional   Registered=True
registration   IN_SENDER_ID_REGISTRATION   COMPLETE
phone numbers  none
pools          none
opt-out lists  Default
account tier   PRODUCTION
```

No phone numbers or pools is **correct** — India sends by registered sender id, not by a number.

### us-east-1 (international)

```
+18444891209   TOLL_FREE   ACTIVE   US   TRANSACTIONAL   InternationalSendingEnabled=true
+14255556333   SIMULATOR   ACTIVE   US   TRANSACTIONAL   InternationalSendingEnabled=false
pool           pool-27cc4ee23f1e4225aa71172cbaedbb58   ACTIVE   TRANSACTIONAL
sender ids     none   (correct: the US does not use them)
opt-out lists  Default
protect config protect-b137924dfb934c32b1d10c28b737d08c   AccountDefault=True
account tier   PRODUCTION
```

### Spend limits — a hard constraint in both regions

```
TEXT_MESSAGE_MONTHLY_SPEND_LIMIT    enforced 200   max 200
MEDIA_MESSAGE_MONTHLY_SPEND_LIMIT   enforced 200   max 200
RCS_MESSAGE_MONTHLY_SPEND_LIMIT     enforced   1   max   1
VOICE_MESSAGE_MONTHLY_SPEND_LIMIT   enforced   1   max   1
NOTIFY_MESSAGE_MONTHLY_SPEND_LIMIT  enforced   1   max   1
```

`max` equals `enforced` everywhere, so none of these can be raised without an AWS quota request.
SMS has a $200/month ceiling.

### AWS RCS is not usable yet — three independent blockers

1. `RCS_MESSAGE_MONTHLY_SPEND_LIMIT` is **$1**, with a max of **$1**.
2. **No RCS-capable phone number exists** in either region.
3. Launch registrations are incomplete:

```
us-east-1   US_RCS_LAUNCH_REGISTRATION     CREATED    (x2)
us-east-1   CA_RCS_LAUNCH_REGISTRATION     CREATED
us-east-1   TEST_RCS_LAUNCH_REGISTRATION   COMPLETE   (x2)
ap-south-1  TEST_RCS_LAUNCH_REGISTRATION   COMPLETE
us-east-1   NOTIFY_TIER_UPGRADE_REGISTRATION   REQUIRES_UPDATES
```

Only the TEST launch registrations are COMPLETE, so non-India RCS traffic cannot flow until all
three are cleared. India RCS stays on Sinch.

---

## 7. Deployment and routing

Lambdas are deployed by scripts, not by Amplify Gen 2:

1. `scripts/deploy_all_lambdas.py` — zip build + `update_function_code` from the function→dir
   deploy map. It refuses to create functions.
2. `scripts/snapstart_publish.py` — publish a version and move the `live` alias.

Routes live on HTTP API `zllr9lrg7j` (stage `prod`). Integrations target `function:live`, so a
`$LATEST` change does not reach production until a version is published and the alias moved.

---

## 8. Duplicate post-call SMS hazard (formerly §10)

Both call legs can send a post-call SMS under the same `ivr-default` DLT template:

- `wecare-whatsapp-calling` `_send_disconnect_sms` → `comms.notify` → `wecare-sms-aws`, on call
  terminate and on SIP hangup.
- `wecare-plivo-answer` `_send_post_call_sms` → `wecare-sms-aws:live` on hangup, for Indian
  callers; `POST_CALL_SMS_ENABLED` defaults to `true`.

If WhatsApp calls are routed through the Plivo application, both fire for one call and the
customer receives two SMS under the same registered template. Choose one owner before any Meta
calling setting is repointed.
