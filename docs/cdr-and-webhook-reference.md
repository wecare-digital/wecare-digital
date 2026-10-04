# Voice CDR structure and provider webhook reference

Written 2026-09-27 against live code and live AWS. Everything here is either read
from the running account or quoted from the handler that writes it.

**This document contains no credential values, and it must never contain any.**
Field *names*, secret *ids* and *fingerprints* only. §5 explains how to read the
values yourself, on your own machine, without them passing through a chat
transcript or `~/.kiro/logs`. That restriction is not bureaucratic: on 2026-09-19
four live credentials ended up in plaintext on disk precisely because values were
handled casually, and once in a transcript a value must be treated as burned.

---

## 1. Where the CDR lives

| | |
|---|---|
| Table | `stack-wecare-digital-VoiceCDRTable` |
| Region / account | `us-east-1` / `775261844268` |
| Partition key | `id` (string). No sort key. |
| `id` format | `plivo#{CallUUID}` |
| TTL attribute | `expiresAt` — **ENABLED**, 90 days from write |
| Written by | `wecare-plivo-answer` → `_persist_cdr()` |
| Read by | `wecare-voice-cdr-read` (`GET /voice-cdr-read`) |
| GSI | none — readers `Scan` then filter in memory |

**Current row count: 0.** Verified by consistent scan on 2026-09-27. Rows for
calls that logged `cdrPersisted: true` are absent, and this is **not** TTL: a
freshly written row carries `expiresAt` exactly 90.0 days out. `DELETE
/voice-cdr-read` → `_clear_cdr_logs()` clears the table and is `401` at the
handler despite `AuthorizationType=NONE` at the gateway, so an authenticated
admin clear is the plausible explanation. Treat the table as *currently empty*,
not as broken.

---

## 2. Complete CDR record structure

Every callback writes **both** a snake_case and a camelCase shape into the same
item. That is deliberate and neither half may be dropped: the camelCase keys are
what the readers, the stats aggregation and the UI bind to, and the snake_case
keys exist on rows written before the normalisation, so removing them would strip
fields off historical rows on any later callback for the same call.

### 2.1 Identity and routing

| Attribute | Type | Source | Notes |
|---|---|---|---|
| `id` | S | derived | `plivo#{CallUUID}` — the physical key |
| `source` | S | constant | always `plivo`; the discriminator for this table |
| `route` | S | derived | which callback wrote it: `answer-hangup-pass`, `hangup`, `events`, `dial-events`, `fallback` |
| `call_uuid` | S | `CallUUID` | |
| `callUuid` | S | `CallUUID` | camelCase twin |
| `cdrRank` | N | derived | lifecycle rank; see §2.5 |

### 2.2 Parties

| Attribute | Type | Source | Notes |
|---|---|---|---|
| `from_number` | S | `From` | |
| `to_number` | S | `To` | |
| `callerNumber` | S | `From` | |
| `destinationNumber` | S | `To` | |
| `callerId` | S | derived | `To` when INBOUND, else `From` |

### 2.3 Direction and status

| Attribute | Type | Source | Notes |
|---|---|---|---|
| `direction` | S | `Direction` | Plivo's raw value: `inbound`, `outbound`, sometimes `outbound-api` |
| `callType` | S | derived | normalised to exactly `INBOUND` / `OUTBOUND`; readers filter on this |
| `call_status` | S | `CallStatus` | raw |
| `overallCallStatus` | S | derived | the reader's vocabulary — see §2.4 |
| `hangup_cause` / `hangupCause` | S | `HangupCause` ‖ `HangupCauseName` | |
| `hangup_source` / `hangupStatus` | S | `HangupSource` | |
| `end_time` | S | `EndTime` | |

### 2.4 `overallCallStatus` mapping

`_PLIVO_STATUS_TO_OVERALL`, with one refinement that matters for reporting:

| Plivo `CallStatus` | `overallCallStatus` |
|---|---|
| `completed` | `Answered` — **but `Missed` when duration ≤ 0** |
| `busy` | `Busy` |
| `no-answer` / `noanswer` | `Missed` |
| `failed` | `Missed` |
| `cancel` / `canceled` / `cancelled` | `Missed` |
| `timeout` | `Missed` |
| `ringing` | `Ringing` |
| `in-progress` | `In Progress` |
| anything else | `Status.Title()` |

Plivo reports `completed` for a normal teardown whether or not anyone answered,
so a zero-duration `completed` is downgraded to `Missed`. Without that the answer
rate overstates.

### 2.5 Duration

| Attribute | Type | Notes |
|---|---|---|
| `duration_seconds` | S | raw `Duration` ‖ `BillDuration`, as the string Plivo sent |
| `durationSec` | N | whole seconds |
| `durationMs` | N | `durationSec × 1000` |
| `conversationDurationSec` / `…Ms` | N | tracks duration — no separate IVR wait leg to subtract |
| `billableDurationSec` / `…Ms` | N | tracks duration — Plivo bills the whole connected call |

The three pairs are written explicitly rather than derived so a reader does not
have to guess which one it is looking at.

### 2.6 Time

| Attribute | Type | Notes |
|---|---|---|
| `createdAt` | N | unix seconds. **Write-once** — `if_not_exists`. Load-bearing twice: the sort key for both read paths *and* the date fallback when `timestamp` is absent. Restamping it moves the row's place in history. |
| `timestamp` | S | `%Y-%m-%d %H:%M:%S` UTC |
| `received_at` | N | unix seconds, updated on every callback |
| `expiresAt` | N | `createdAt + 7776000` (90 days). The TTL attribute. |

### 2.7 Write semantics — read this before writing a reader

All five call sites write the **same** `id`. A blind `put_item` therefore let the
last callback to arrive win the whole item, and because `put_item` *replaces*,
`hangupCause`, `durationSec` and `end_time` were being deleted by a mid-call
payload. Two rules now prevent that:

1. **`update_item`, not `put_item`** — a field absent from this callback is left
   alone rather than removed.
2. **Conditional on `cdrRank`** — `attribute_not_exists(#rank) OR #rank <= :rank`.

| `route` | `cdrRank` | lifecycle position |
|---|---:|---|
| `events` | 10 | mid-call |
| `dial-events` | 20 | dial outcome, still mid-call |
| `fallback` | 30 | primary answer URL failed |
| `answer-hangup-pass` | 40 | terminal, arriving on the answer URL |
| `hangup` | 40 | terminal |

Equal ranks are allowed through on purpose: a retried `hangup` carrying a
corrected `BillDuration` must land. A `ConditionalCheckFailedException` is **not
an error** — it means a higher-ranked callback already recorded the call — and is
logged as `plivo_cdr_write_superseded`.

---

## 3. Plivo voice webhooks — what to verify with Plivo

Application **`WECARE-WHATSAPP-IVR`**, app id `12775976954213184`, number
`+918031830030`, endpoint `543585900967411`.

| Route | URL | Signature |
|---|---|---|
| answer | `POST https://wecare.digital/api/plivo/answer` | verified **when present**; cannot be required |
| fallback | `POST https://wecare.digital/api/plivo/fallback` | verified when present |
| hangup | `POST https://wecare.digital/api/plivo/hangup` | **REQUIRED** |
| events | `POST https://wecare.digital/api/plivo/events` | **REQUIRED** |
| dial-events | `POST https://wecare.digital/api/plivo/dial-events` | **REQUIRED** |

Each configured URL also carries a `?token=` query parameter. That token is a
diagnostic bearer secret, **not** proof of provider identity.

### 3.1 The `/api` path prefix — mandatory configuration

These are apex paths behind an Amplify rewrite `/api/<*>` → execute-api. The
rewrite **consumes** the `/api` segment. Plivo's V3 signature is an HMAC over the
**URL**, so the Lambda must be told to add the segment back:

```
PLIVO_CALLBACK_HOST        = wecare.digital
PLIVO_CALLBACK_PATH_PREFIX = /api
```

Both are set on `wecare-plivo-answer` (live v25). Without them `hangup`, `events`
and `dial-events` all reject with `signature_mismatch`, while `answer` keeps
working — so the failure is silent: callers still hear the greeting, but the CDR
row and the follow-up SMS are lost.

### 3.2 Signature algorithm

Header `X-Plivo-Signature-V3` (or `X-Plivo-Signature-Ma-V3`, always the **main**
account token) plus `X-Plivo-Signature-V3-Nonce`.

```
base = url_with_sorted_query  +  "."(only if a query string existed)  +  sorted_post_params
sig  = base64( HMAC_SHA256( auth_token, f"{base}.{nonce}" ) )
```

Four details the public docs omit, each of which breaks every signature if got
wrong: the nonce joins with a literal `.`; the trailing `.` after the query string
appears **only** when a query string existed; sorted POST params concatenate
key+value with **no** separators at all; and the header may carry several
comma-separated signatures, any one of which matching is valid.

### 3.3 Credentials — by reference

| Purpose | Secret id | Fields |
|---|---|---|
| V3 signing key + API auth | `wecare/plivo/api` | `auth_id`, `auth_token` |
| Diagnostic `?token=` | `wecare/plivo-answer` | `token` |

Last changed `2026-09-18` and `2026-09-19`. No rotation schedule configured.

> The `wecare/plivo-answer` token value was exposed into a Kiro session
> transcript on 2026-09-27 by a careless field dump. It is the weaker of the two
> Plivo credentials — the V3 signature is the real gate — but it should be treated
> as compromised and rotated when you next touch Plivo credentials.

---

## 4. Sinch / ACL RCS DLR webhook — currently failing closed

| | |
|---|---|
| Endpoint | `POST https://wecare.digital/api/webhook/sinch-rcs` |
| Handler | `wecare-rcs-dlr` |
| Gateway auth | `AuthorizationType=NONE` — a provider cannot present a bearer token |
| Real auth | **raw-body HMAC** over the request body, `lambda_utils/sinch_signature` |
| Provider | Sinch India = ACL Mobile's white-labelled stack |
| Project | `c8114d03-eeb2-401d-a8f1-abb93594cb33` |
| App | `01KQSB792X3R148D8ZGHQYW3SP` |
| Webhook | `01KQSBMVJ5N390DFWY6669A7DC` |

### 4.1 The blocker, stated precisely

`wecare/sinch/rcs` has **no `webhook_secret` field**. The handler loads it lazily
and, when absent, returns **503** — deliberately not 401, because Sinch retries
5xx with exponential backoff, so the reports are not lost while the gap persists.
Measured: **825 refusals in 14 days**.

The secret was last changed **2026-05-05**, so this field has never been present.
Repointing the webhook URL does not fix it; only adding the field does.

**This is owner action.** Writing a credential value is outside what I may do.

### 4.2 Fields the secret carries

From `sinch_rcs.SINCH_RCS_FIELDS` — names only:

| Field | Required | Used for |
|---|---|---|
| `username` | **yes** | Keycloak password grant, and the `appId` path segment on the template API |
| `password` | **yes** | Keycloak password grant |
| `project_id` | no | Conversation API send path |
| `app_id` | no | Conversation API app |
| `bot_id` | no | RCS agent |
| `webhook_secret` | — | **ABSENT.** DLR HMAC verification. Add this to clear the 503. |

There is deliberately **no default for any field**. An earlier version fell back
to a hardcoded username with an empty password, which put half a credential pair
into source control and turned a misconfiguration into a 401 that looked like a
provider outage.

### 4.3 Auth endpoints to quote to the provider

```
token :  POST https://auth.aclwhatsapp.com/realms/ipmessaging/protocol/openid-connect/token
         grant_type=password   client_id=ipmessaging-client
send  :  POST https://convapi.aclwhatsapp.com/v1/projects/{project_id}/messages:send
tpls  :  GET/POST https://api.aclwhatsapp.com/access-api/v2/rcs/{username}/templates
```

Do **not** migrate to `auth.sinch.com` with `KEY_ID`/`KEY_SECRET` — that is the
global Sinch Build platform and it does not carry this project.

---

## 5. Reading the credential values yourself

Do not ask an agent to print these, and do not paste them into a chat. Chat is
persisted to `~/.kiro/logs` and into the session transcript, so a value shown
once is a value you then have to rotate.

Use the helper, which writes to a `0600` file **outside** the repository and
prints only the path and a fingerprint:

```
python scripts/export_provider_credentials.py --secret wecare/sinch/rcs
```

Then open the file yourself, compare with what the provider has on record, and
delete it:

```
open -e ~/.provider-verify/wecare-sinch-rcs.txt     # or your editor of choice
shred -u ~/.provider-verify/wecare-sinch-rcs.txt    # gshred on macOS, or rm -P
```

To check a value matches the provider's **without** revealing it, compare
fingerprints instead — the helper prints `sha256[:12]` per field, which is not
reversible:

```
python scripts/export_provider_credentials.py --secret wecare/sinch/rcs --fingerprint-only
```

---

## 6. Related

- `.kiro/steering/secret-handling.md` — why none of the above prints a value
- `.kiro/steering/lambda-snapstart-deploy.md` — why a code change needs a version publish and alias move
- `docs/CREDENTIAL-ROTATION-RUNBOOK.md` — rotation procedure, and which function reads which secret
- `scripts/rcs_webhook_control_plane.py` — read/repoint the DLR webhook
- `scripts/plivo_control_plane.py` — read/plan/apply Plivo application config

---

## 7. Post-call SMS + RCS after a WhatsApp call — the code works; one hook is missing

### 7.1 What was measured, 2026-09-27

| | |
|---|---|
| `webhook_received` on `wecare-whatsapp-calling`, 14 days | **1,902** |
| `call_event` (any call webhook) | **0** |
| `terminate` | **0** |
| `disconnect_sms_triggered` from the webhook path | **0** |
| `post_call_sip` invocations | **0** |
| `WhatsAppCallingTable` rows | **0** |

Both WABA numbers report calling `status: ENABLED` **and**
`sip: {status: ENABLED, hostname: sip.wecare.digital, port: 5061}`. `calls` **is**
among the 32 subscribed webhook fields, and the callback URL
`https://wecare.digital/api/whatsapp` is active — so neither the subscription nor
the flags are the gap.

`SINCH_RCS_ENABLED=true` is set on `wecare-whatsapp-calling`. RCS was never
flag-blocked on this path.

> **Unverified, and flagged as such:** whether enabling SIP mode is what stops
> `connect`/`terminate` reaching the Cloud API webhook. No official Meta
> documentation confirming it was retrievable. "No WhatsApp calls were placed at
> all" fits the same evidence, and 0 table rows cannot separate the two. A real
> inbound WhatsApp call to each number settles it; a synthetic probe cannot, for
> the same reason an unsigned probe could not test the Plivo signature.

### 7.2 Proof the wiring is complete

Invoking the SIP post-call entry point directly, once, against the
owner-nominated QA number with WABA2's phone id:

```
POST-CALL SIP: sending wd_menu template to +918100640044 via WABA1, WABA2
Post-call SIP wd_menu sent via WABA1: wamid.HBgM…QzM2OEU1QjRG…
Post-call SIP wd_menu sent via WABA2: wamid.HBgM…N0Y3MTVGMTA2…
disconnect_sms_triggered   callId=sip_+918100640044  phoneNumberId=1055232054343117
aws_sms_india_sent         region=ap-south-1 senderId=WDBEEP
                           dltTemplateId=1007277993798259629 dryRun=false
                           messageId=67d6885e-9ff1-46bc-8ac3-1e191fb22746
rcs_send_success           template=rcsmenu messageId=01M3G7KZGJWJMN7Y4B1QGBVBSZ
```

SMS and RCS were **really delivered to the provider**, not merely queued. So
nothing in this repo needs changing to get SMS + RCS after a WhatsApp call for
both WABAs. The sole missing link is that the Asterisk box never invokes the hook.

### 7.3 What Asterisk must invoke

Direct Lambda invoke — **not** an HTTP route. Dispatched at
`whatsapp-calling/handler.py:218` on `event['action'] == 'post_call_sip'`.

```jsonc
{
  "action":        "post_call_sip",
  "callerPhone":   "+9198XXXXXXXX",      // REQUIRED. E.164; a bare number is prefixed with +
  "phoneNumberId": "1055232054343117",   // REQUIRED. The Meta phone id that RECEIVED the call
  "callId":        "sipcall-…",          // optional; a stable id is generated if absent
  "duration":      "11",                 // optional, whole seconds, string or int
  "recordingUrl":  ""                    // optional
}
```

```bash
aws lambda invoke \
  --function-name wecare-whatsapp-calling:live \
  --invocation-type Event \
  --payload '{"action":"post_call_sip","callerPhone":"+91…","phoneNumberId":"1055232054343117","duration":"11"}' \
  /dev/null
```

Use `--invocation-type Event` from the dialplan so a hangup is never delayed by
our side.

**`phoneNumberId` is mandatory and there is deliberately no default.** It used to
fall back to WABA2, which meant a call received on WABA1 was followed up from a
number the caller never dialled — cross-WABA, and outside the 24-hour window
belonging to the conversation they actually opened. With it absent the handler
logs `post_call_sip_no_phone_number_id` / `WHATSAPP_SENDER_UNRESOLVED` and sends
nothing. A missing follow-up is a visible bug; a follow-up from the wrong
business number is an incident.

### 7.4 The both-WABA rule, as implemented

| Call received on | wd_menu sent from | SMS | RCS |
|---|---|---|---|
| WABA1 `1016149501586345` (+91 93309 94400) | WABA1 only | yes | yes |
| WABA2 `1055232054343117` (+91 99033 00044) | **WABA1 and WABA2** | yes | yes |

SMS and RCS are sent once per call regardless of which number received it — they
are not per-WABA, and there is no branch that could duplicate them.

### 7.5 The alternative, and its cost

If Asterisk cannot be changed, the other route is to turn SIP off so Meta
delivers `connect`/`terminate` to the webhook, at which point the existing
`_handle_call_event` block at `handler.py:849-869` fires on its own — same SMS,
same RCS, same both-WABA behaviour.

**That changes what a caller hears.** In SIP mode Asterisk answers and plays audio
over RTP; without it the handler falls back to WhatsApp messages plus
`pre_accept`/`accept`, which is a different call experience. Treat it as a
product decision needing explicit approval, not a configuration tidy-up.

### 7.6 Independent of all the above

`wecare-rcs-dlr` still returns **503** on every delivery report because
`webhook_secret` is missing from `wecare/sinch/rcs` (§4.1). Sends succeed; only the
delivery *reports* are refused, and Sinch retries them. Adding that field is the
one item here that needs a credential write, and therefore you.

---

## 8. RCS template inventory (2026-09-27)

12 templates, all `approved`. `rcsmenu` — the name the code sends — is present.

| Name | Type | Stale host refs |
|---|---|---|
| `rcsmenu` | rich_card | `app.wecare.digital`, `r.wecare.digital` |
| `rcsorder` | rich_card | `app.wecare.digital`, `r.wecare.digital` |
| `wecaremenu` | rich_card | `app.wecare.digital`, `r.wecare.digital` |
| `wdorder` | rich_card | `app.wecare.digital`, `r.wecare.digital` |
| `waalert` | rich_card | `app.wecare.digital`, `r.wecare.digital` |
| `get_started` | rich_card | `app.wecare.digital`, `r.wecare.digital` — **dead thumbnail** |
| `rcsmenu_apex` | rich_card | none — created 2026-09-27 on the migrated URLs |
| `test16` | text_message | none |
| `test17` | text_message | none |
| `wecare_order_update` | text_message | none |
| `wecare_test_create` | text_message | none |
| `wecare_v2_test` | text_message | none |

`get_started`'s thumbnail `stream/media/m/WECARE+SC.png` does not exist in any
spelling — the `+` never decoded to a space. Silently broken, pre-existing.

The three media URLs the rich cards reference, and their state on both hosts:

| Key under `stream/media/m/` | old `app.wecare.digital` | new `wecare.digital/get/o` |
|---|---|---|
| `customerservice.mp4` | 200 `video/mp4` 1302443 b | 200 identical |
| `wecare-digital-rcs-h.png` | 200 `image/png` 89548 b | 200 identical |
| `WECARE+SC.png` | 200 but 596 b of **HTML** | 302 — **key does not exist** |

Because 6 of 12 templates are **approved** against `app.wecare.digital`, that host
cannot be retired until the templates are re-pointed and re-approved. This is one
of three independent blockers on deleting the old S3 folder; the others are 35
`S3_BUCKET`/`MEDIA_BUCKET` env vars naming it as a bucket across 30+ live
functions, and an active writer outside this repo still adding
`stream/blog/source/production-N-decisions.json`.

### 8.1 Template CRUD

All three actions live on `wecare-rcs-send`. `create_template` takes
`type: text_message | rich_card`; for `rich_card` the `text` field carries the
card JSON.

```bash
# list
aws lambda invoke --function-name wecare-rcs-send \
  --payload '{"body":"{\"action\":\"templates\"}"}' /dev/stdout

# create
aws lambda invoke --function-name wecare-rcs-send \
  --payload '{"body":"{\"action\":\"create_template\",\"name\":\"…\",\"type\":\"text_message\",\"text\":\"…\"}"}' /dev/stdout

# delete
aws lambda invoke --function-name wecare-rcs-send \
  --payload '{"body":"{\"action\":\"delete_template\",\"name\":\"…\"}"}' /dev/stdout
```

Creation returned `status: approved` immediately for `rcsmenu_apex`, so there is
no separate approval wait on this provider.

### 8.2 Sending

```bash
aws lambda invoke --function-name wecare-rcs-send \
  --payload '{"body":"{\"action\":\"send\",\"phoneNumber\":\"+9198…\",\"template\":\"rcsmenu\",\"language\":\"en\"}"}' /dev/stdout
```

India destinations only. `rcs-send` normalises with `comms.numbers.to_e164` and
refuses a non-India number with 400 — the old `'91' + clean[-10:]` rewrite was
removed because it turned +65/+852/+45 numbers into real Indian subscribers.

`rcs-send` itself does **not** check `SINCH_RCS_ENABLED`; only its callers do
(`sinch_rcs.is_rcs_enabled()` and `policy.decide_rcs`). So a direct invoke sends
even when the WhatsApp-call path is flag-blocked.
