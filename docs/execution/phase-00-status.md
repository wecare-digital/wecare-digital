# Phase 0 — safety freeze and protected snapshot

Status: **✅ COMPLETE** · Date: 2026-09-21 · Authority used: `A0_READ` only
Deployment: **NO DEPLOYMENT**. No credential changed. No write, no delete, no flag flipped.

## Entry evidence

| Item | Measured |
|---|---|
| Branch | `stack` |
| HEAD | `4baf4236dbf78a784ec84f238e091b699f7f8cd4` |
| `origin/stack` | `4baf4236dbf78a784ec84f238e091b699f7f8cd4` (local == remote) |
| Commits since the brief's `827cd614` snapshot | **28** |
| Working tree | 2 deleted spec files (`.kiro/specs/plivo-api-control-plane-fix/{bugfix,design}.md`), 2 untracked (`bw-crm.md`, `.kiro/steering/00-current-owner-overrides.md`) — **not mine, left alone** |
| AWS identity | `775261844268` / `user/wecare-admin` / `us-east-1` |
| Inventory error total | **0** across every Phase 0 call |

Never reset to `827cd614` or any other historical SHA. The 28 intervening commits
include the credential sweep, the ElevenLabs retirement series, deletion of 40
dead `defineFunction` declarations, removal of the broken deploy path, and
`4baf4236` which extended the three deny guards to cover the AWS MCP route.

## Measured vs. the baselines we were given

| Metric | Owner overrides | bw-crm.md (dated) | Measured 2026-09-21 | Verdict |
|---|---|---|---|---|
| Lambda functions | 58 | 65 | **58** | overrides correct; brief stale |
| HTTP APIs | 2 | 1 discussed | **2** | brief only ever describes `zllr9lrg7j` |
| HTTP API routes | 332 | 331 | **332** (329 + 3) | overrides correct |
| API Gateway authorizers | 0 | 0 | **0** | confirmed |
| Routes `AuthorizationType=NONE` | 332 | 329 | **332** | confirmed |
| Regional WAF WebACLs | 0 | 0 | **0** | confirmed |
| Cognito MFA | OFF | OFF | **OFF** | confirmed |
| GuardDuty detectors | 0 | 0 | **0** | confirmed |
| DynamoDB tables | — | 67 | **66** | brief stale |
| Secrets | — | 32 | **31** (25 active, 6 scheduled) | brief stale |
| Functions with `live` alias | — | 53 | **49** | brief stale (fleet shrank) |

## What Phase 0 found that the brief does not contain

### 1. A second HTTP API that no prior audit covered — `79g3bbufdh`

3 routes, no authorizer, stage `prod`, auto-deploy:

```
GET  /webhook/sinch-dlr -> wecare-sinch-dlr          (function ABSENT)
POST /webhook/sinch-dlr -> wecare-sinch-dlr          (function ABSENT)
POST /ai/generate       -> wecare-ai-generate-response ($LATEST, not :live)
```

`scripts/audit_route_auth.py` hardcodes a single API and reported
"329 routes across 4 pages" — it has **never scanned this API**. Every prior
"331/332 routes audited, 0 findings" claim therefore excludes these three.

### 2. Two unauthenticated production ingresses, proven from config + source

**`/webhook/sinch-rcs` (GET and POST) → `wecare-rcs-dlr:live`.**
`AuthorizationType=NONE`, and `amplify/functions/messaging/rcs-dlr/handler.py`
(341 lines) contains **zero** auth markers — no HMAC, no signature, no shared
secret, no `require_auth` (grep for `require_auth|signature|hmac|verify|secret|token|authoriz`
returns nothing). The handler then:

- writes to the canonical `MessagesTable` via `put_message` and `update_item`,
- calls `evaluate_rules`, and on a rule match **invokes `wecare-rcs-send`** with
  `phoneNumber` taken straight from the unauthenticated request body.

So an anonymous caller can forge inbound RCS traffic and delivery states into the
canonical message store, and can potentially cause outbound RCS sends to
arbitrary numbers at our cost. `audit_route_auth.py` did flag these two as OPEN.

**`POST /whatsapp/inbound` → `wecare-inbound-whatsapp:live`.**
`AuthorizationType=NONE`. The handler's entry point consumes
`event['Records'][*]['Sns']['Message']` — the legacy AWS End User Messaging
Social / SNS envelope — with **no signature verification and no `require_auth`**.
It also honours a direct-invoke branch `event['action'] == 'create_invoice'`
before any authorization check. The audit tool classified this route as
"handler source not resolvable" (a false negative from the
`inbound-whatsapp-handler` directory vs `wecare-inbound-whatsapp` function name
mismatch), so it was never counted as a finding.

Live exploitability is **deliberately unverified**: probing it means sending an
unsigned request to a production ingress. That is in the confirmation queue.

### 3. Five dangling routes pointing at deleted functions

| Route(s) | Target (absent) | API |
|---|---|---|
| `GET`, `POST /webhook/sinch-dlr` | `wecare-sinch-dlr` | `79g3bbufdh` |
| `POST`, `GET`, `DELETE /voice-in/cdr` | `wecare-voice-in-cdr` | `zllr9lrg7j` |

Both targets are retired-provider handlers (Sinch SMS DLR, a voice CDR ingester).
The functions are gone; the public routes and integrations were left behind. No
handler means no data loss today, but this is exactly the declarative residue the
retirement acceptance criteria forbid, and it is a recreation path.

### 4. Notification ownership is still split, though one producer did go away

`wecare-elevenlabs-postcall-sms` is **absent from the live fleet** — the duplicate
post-call SMS producer named in the brief as the first production risk appears
retired. Remaining: the DLT key `ivr-default` is still referenced by 8 source
files including `comms/notify.py`, `pstn/notifications.py`, `voice-in/obd`,
`voice-in/c2c`, `whatsapp-calling` and `plivo-answer`. `CallNotificationsTable`
exists live and is referenced only by `whatsapp-calling`.

`PstnNotificationDelivery` is declared in `amplify/backend.ts`,
`amplify/data/resource.ts`, `pstn/claims.py` and `pstn/keys.py` but **no such
physical table exists** in the 66 measured tables. Consistent with
`PSTN_CONNECTED_NOTIFICATIONS_ENABLED` defaulting to false.

Similarly `rcs-dlr` defaults `RCS_TABLE` to `stack-wecare-digital-RcsMessagesTable`,
which is **not** among the 66 live tables.

## Exit criteria

| Criterion | Result |
|---|---|
| Account / repo / branch / concurrent edits confirmed | ✅ |
| No credential changed; exposed families recorded as `MANUAL_OWNER_ACTION` | ✅ |
| Protected identifiers snapshotted, provider values labelled carried-forward | ✅ `docs/protected-resource-register.md` |
| Lambda aliases / routes / tables / secrets / Cognito / WAF / GuardDuty measured | ✅ errorTotal 0 |
| Production write and cutover flags untouched | ✅ |
| No code or cloud deletions | ✅ |

## Remaining work owned by Phase 1

Per-source-function and per-route machine-readable inventory joined to IaC,
permissions, tables, traffic and frontend caller; documentation queues (Plivo,
Meta, Razorpay, Google, Bing); MCP schema inventory; SDK/packaged-runtime
matrix; browser/device matrix; cleanup dry-run. Phase 1 entry is gated on the
confirmation queue in `docs/kiro-handoff.md`.
