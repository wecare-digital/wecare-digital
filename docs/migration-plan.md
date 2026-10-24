# Migration plan — Unified Communications Platform

From the baseline in `current-communications-architecture.md` to the provider set
declared in `scripts/provider_allowlist.py`. Staged so that each stage is
independently deployable, independently verifiable, and independently revertible.

Baseline commit `41dc41c2`. Account `775261844268`, `us-east-1`, branch `stack`.

---

## Ordering constraints that are not negotiable

These come from how the system actually fails, not from preference.

1. **The CI provider-policy gate lands first.** It is the only mechanism that
   stops a half-finished migration from regressing while it is in progress. A
   gate added at the end proves nothing about the work that preceded it.

2. **DLT consolidation precedes SMS rewiring.** The entity id, sender id and
   three template ids currently live in five places
   (`current-communications-architecture.md` §5). Rewiring callers before
   collapsing those five copies means rewiring against a moving target.

3. **AWS India sending is proven before any sender is removed.** `wecare-sms-aws`
   has `DryRun` (`sms-aws/handler.py:426-428`), which validates origination
   identity, DLT parameters and destination **without delivering**. Use it, plus
   one real send to a controlled number, before deleting a sending path.

4. ~~The IAM region gap is closed before India cutover.~~ **Checked, not a
   blocker.** `iam-policies.ts:94-105` reads as `us-east-1`-only, but
   `simulate_principal_policy` against the live `wecare-digital-lambda-role`
   returns `ALLOWED` in both regions and on
   `sender-id/WDBEEP/IN`. IaC is narrower than the deployed policy. Reconciling
   the drift is worth doing; it does not gate the cutover.

5. **Delivery-receipt ingestion is built before the SMS dashboard claims a
   delivery rate.** Today `status` is written as `SENT` and never updated
   (`sms-aws/handler.py:357-375`). A dashboard showing "delivery rate" from that
   data would be fiction.

6. **Plivo endpoints are built and tested before the provider config is
   repointed.** §22 is explicit. `/plivo/fallback` and `/plivo/hangup` must
   exist and return correctly before the Plivo console is changed, otherwise a
   primary failure hits a 404.

7. **One owner for the post-call SMS is chosen before the Meta SIP repoint.**
   Both legs send under the same `ivr-default` DLT template from different
   providers. Repointing while both are active sends two messages per call to the
   same customer under the same registered template
   (`scripts/test_call_paths.py:31-45`).

8. **The Meta SIP repoint happens last, and cannot be self-certified.** A real
   WhatsApp call must be placed by a human; `scripts/test_call_paths.py watch`
   then proves whether SIP headers arrived. An empty `sipHeaders` means synthetic
   traffic only.

---

## Stage 1 — CI provider gate

**Built:** `scripts/provider_allowlist.py` (the single allow-list of approved
providers) and `scripts/check_provider_allowlist.py` (the explicit operational gate) (§44). It is a **positive** gate: any
external host, SDK, secret prefix, provider id, env namespace or channel Lambda
that the allow-list does not declare fails CI.

Rules include: SMS only through AWS End User Messaging (`sms-transport`); the
Sinch transport addresses the RCS channel only (`rcs-transport`); Plivo REST
calls are voice resources only; voice, SMS and RCS Lambdas are exactly the
supported set (`channel-lambdas`); UPI collection addresses are Razorpay-issued
(`upi-vpa`).

**Scope:** runtime code — `amplify/**`, `src/**`, `config/**`, `public/**`, the
hosting config and the `dependencies` of `package.json`. Tests, documentation,
comments and docstrings are skipped, so historical prose cannot fail it.

**Verify:** `python scripts/check_provider_allowlist.py` exits `0`.

**Rollback:** remove the explicit gate invocation. No runtime impact.

---

## Stage 2 — SMS abstraction and AWS account readiness

**Build:**
- `SmsService` interface: `sendSms`, `sendTransactionalSms`, `sendOtpSms`,
  `sendTemplateSms`, `getDeliveryStatus`, `processDeliveryReceipt` (§4)
- `AwsSmsProvider` wrapping the logic already in `sms-aws/handler.py`
- `SmsRegionResolver`: India → `ap-south-1`, default → `us-east-1`, with an
  explicit per-destination override (§5, §7)
- one DLT source of truth, replacing the five copies
- AWS SMS delivery-receipt consumer (the gap from §2 above)

**Verify against the live account, in both regions:** phone pools, origination
identities, registered sender ids, DLT entity/template registration, spend
limits. Then `DryRun` sends for an Indian and a non-Indian destination.

**Do not** migrate any caller in this stage. Both paths coexist.

**Rollback:** the new code is unreferenced; deleting it changes nothing.

---

## Stage 3 — Rewire callers, then remove non-AWS SMS senders

Order within the stage matters: rewire first, delete second, so every deletion is
of something already unused.

**3a — rewire every SMS caller** to `CommunicationOrchestrator → SmsService`:

| Caller | Path |
|---|---|
| `wecare-plivo-answer` | `wecare-sms-aws:live` — move behind the interface |
| `wecare-whatsapp-calling` | `lambda_utils.comms.notify` → AWS End User Messaging, every country |
| `wecare-bulk-worker`, `wecare-agent-action-group`, `wecare-ai-generate-response` | `wecare-outbound-sms` → `wecare-sms-aws` |
| `src/api/client.ts` `sendSinchSms()` | forces the Sinch branch |

**3b — delete Sinch SMS** (§9). Full list in
`provider-inventory.md` §4.1. Note this path is **already non-functional**:
`wecare/sinch/sms` has no `oauth_token` and `outbound-sms/handler.py:315`
hard-fails without one. Deleting it removes a broken dependency.

**3c — delete SNS `publish` and classic Pinpoint `send_messages`** from
`outbound-sms/handler.py`; neither is DLT-capable for India.

**Preserve:** the DLT template registry in DynamoDB
(`stack-wecare-digital-DLTTemplates`) and its content. It is provider-independent
regulatory data and is needed by AWS sending. Only the *transport* changes.

**Verify:** production build and targeted operational checks; `check_provider_allowlist.py` passes; real
India send via AWS `ap-south-1`; real international send via `us-east-1`;
delivery receipts arriving.

**Rollback:** revert the commits. No secret is deleted in this stage; secret
deletion is a later, separately confirmed step.

---

## Stage 4 — Sinch scoped to India RCS

**Build:** `SinchRcsProvider` under `providers/sinch/rcs/` (§10); the internal
provider-neutral `RcsTemplate` model (§13); `SinchRcsTemplateImporter` and
`scripts/sync-sinch-rcs-templates` (§12).

**Read-only:** the importer must not modify Sinch templates. Initial sync pulls
`rcsmenu`, `rcsorder`, `waalert` into the internal model.

**Also:** delete the two dead helpers (`sinch_rcs.py:399-452`). Repoint the India
RCS fallback to **AWS SMS `ap-south-1`** (§11) — never Sinch SMS.

**Rollback:** the existing `sinch_rcs.py` entry point stays functional throughout.

---

## Stage 5 — AWS international RCS

**Build:** `AwsRcsProvider` (§14), `AwsRcsTemplateRenderer` (§15), RCS → AWS SMS
fallback with channel-state tracking (§16), `RcsCapabilityResolver` (§17).

**`RcsCapabilityResolver` must not branch on Android vs iPhone** (§17). Modern
iPhones may support RCS depending on iOS version, country, carrier, device
settings and agent launch status. Resolve capability, do not infer it from
platform.

**Blocked on provider approval — confirmed by measurement, three independent
blockers.** Read live 2026-09-19:

1. `RCS_MESSAGE_MONTHLY_SPEND_LIMIT` is **$1**, and `max` is also **$1**, so it
   cannot be raised without an AWS quota request.
2. **No RCS-capable phone number exists** in `us-east-1` or `ap-south-1`.
3. `US_RCS_LAUNCH_REGISTRATION` and `CA_RCS_LAUNCH_REGISTRATION` are `CREATED`,
   not COMPLETE. Only `TEST_RCS_LAUNCH_REGISTRATION` is COMPLETE.

Build the provider and renderer anyway — they are needed and testable against the
internal template model without sending. But this stage cannot reach
`IMPLEMENTED`, and §51 acceptance cannot be claimed, until all three clear.
Writing code is not the bottleneck here; the AWS quota request and the launch
registrations are.

**Verify:** §18 matrix — Android RCS-capable, iPhone RCS-capable, non-RCS device;
text, media, rich card, carousel, suggested reply, suggested action, delivery
receipt, inbound reply, SMS fallback. Record platform rendering differences; do
not promise pixel-identical rendering.

---

## Stage 6 — CommunicationOrchestrator

**Build** the orchestrator (§37) with the hard routing rules (§38, §39):

```
channel = SMS                  -> AWS, always
  country IN                   -> ap-south-1
  otherwise                    -> us-east-1 (override allowed)

channel = RCS, country IN      -> Sinch RCS    -> fallback AWS SMS ap-south-1
channel = RCS, eligible non-IN -> AWS RCS      -> fallback AWS SMS
```

There must be **no** code path `SMS → Sinch` or `SMS → Plivo`; SMS goes to AWS only.

The follow-up engine (§40) uses the identical rules — it is a caller of the
orchestrator, not a parallel implementation.

---

## Stage 7 — Plivo voice endpoints, then WhatsApp calling

**7a — build and test endpoints before touching provider config** (§22, §26):
`POST /plivo/fallback`, `POST /plivo/hangup`, `POST /plivo/events`, plus **V3
signature validation** (§27), which does not exist anywhere in the repo today.

Note the asymmetry: Plivo does not sign `answer_url` fetches, but it **does**
sign callbacks — and the hangup pass is a callback and is the one with the SMS
side effect. So `/plivo/hangup` and `/plivo/events` get signature validation;
`/plivo/answer` keeps the `?token=` gate.

Route capacity is fine: 361 routes exist as of 2026-09-26 and the old 300 cap has been raised.

**7b — choose one owner for the post-call SMS.** Recommended: the media leg
(`plivo-answer`), because it is the leg that will own the call once Plivo serves
it, and it already routes through `wecare-sms-aws`. Disable
`_send_disconnect_sms` on the webhook leg at the same moment.

**7c — repoint the Plivo console** to the new fallback/hangup URLs.

**7d — WhatsApp calling SIP interop** (§25). Test in order:

- **Option A** Meta → Plivo Application SIP → `/plivo/answer`
- **Option B** Meta → `sip.wecare.digital` → Asterisk → Plivo App SIP
- **Option C** Meta → `sip.wecare.digital` → Asterisk → playback (status quo)

Verify `sip:12775976954213184@app.plivo.com` and
`sip:wecarewaivr203331794466262@phone.plivo.com` **separately** (§24) — they are
different objects and must not be conflated.

**Two facts constrain Option A**, both from Plivo's own documentation:

- Plivo's native WhatsApp Calling configures the Answer URL on the WhatsApp
  number, which requires Plivo to be the BSP. These WABAs are **Direct Meta**,
  so that product path does not apply.
- Plivo requires India traffic to terminate SIP and media **in India**. Both
  numbers are +91.

So Option A is a raw SIP interconnect needing Plivo to confirm the
India-terminating host and the credential Meta must present. Until confirmed,
Option C remains live and nothing is repointed.

**Cannot be self-certified.** A human places a real WhatsApp call; then
`python scripts/test_call_paths.py watch`. Non-empty `sipHeaders` on a
`plivo_answer` event is the only acceptable evidence.

**Rollback:** `wecare/meta/whatsapp-sip` holds the SIP password specifically as a
known-good value to roll back to after a repoint
(`scripts/store_provider_secret.py:139-150`). Reverting is a single
`_update_calling_settings` call restoring `sip.servers[0].hostname`.

---

## Stage 8 — Voice announcements and TTS

`TextToSpeechService` (§30) absorbing the four existing Polly implementations;
`VoiceScriptComposer` (§28) targeting 15-25 seconds; the approval flow (§29)
with **mandatory human approval in V1**.

The composer must never invent dates, times, names, money, appointments,
locations or promises (§28). Do not add TTS to `plivo-answer` — it is
pre-recorded audio by design and its tests enforce that.

---

## Stage 9 — Google

`GoogleAuthService` (§31), `GoogleContactsService` (§32), `GoogleAdsService`
read-only (§33).

**Blocked:** `wecare/google/ads` has no `developer_token`. Google Ads API cannot
authenticate without it, so §33 is `WAITING_FOR_CREDENTIAL`. Contacts and Auth
are not blocked — `wecare/seo/google-oauth` has a usable client id and secret,
and §32 says to reuse that client rather than minting a second one.

---

## Stage 10 — Truecaller

`POST /auth/truecaller/callback` (§35) with nonce verification, replay
protection, SSRF protection, server-side profile retrieval and no token logging.
Reuse the existing application (§34) — do not create another.

Truecaller for Business caller branding (§36) stays `false` until provider/KYC
approval exists. Do not report it complete before then.

---

## Stage 11 — Dashboard

Provider cards per §41; a dedicated AWS SMS card per §42; India RCS and
International RCS shown **separately** per §43. Offer only allow-listed providers
as selectable options — never Sinch SMS or Plivo SMS. Never display credentials.

The SMS card's *delivery rate* depends on Stage 2's delivery-receipt consumer. If
that is not in place, the card must say so rather than show an optimistic number.

---

## Stage 12 — Config, scripts, docs

`.env.example` per §45 (none exists today), all §46 scripts, all §47 docs.

No runtime configuration outside the allow-listed env namespaces (`env-namespaces`
rule) — in particular no `SINCH_SMS_*`, `SINCH_VOICE_*`, `SINCH_WHATSAPP_*` or
`PLIVO_SMS_*`. Scripts must never print credential values.

---

## Stage 13 — Acceptance

Prove, with commands and output rather than assertion:

```
Sinch SMS senders                 0
Plivo SMS senders                 0
distinct SMS providers            1   (AWS End User Messaging)
India SMS                         AWS ap-south-1
international SMS                 AWS us-east-1 (or explicit override)
RCS India                         Sinch -> fallback AWS SMS ap-south-1
RCS international                 AWS us-east-1 -> fallback AWS SMS
check_provider_allowlist.py       exit 0
production build + targeted checks pass
```

Then the §55 per-subsystem report using the required status vocabulary.

---

## Deferred, with reasons

| Item | Why deferred |
|---|---|
| **Secret deletion** | Deleting a secret needs pointwise confirmation. Secrets stay until nothing reads them and the change has been live long enough to trust. |
| **Lightsail retirement** | An **outcome** of Stage 7d (moves the SIP media leg). Not an input. Do not delete before it lands and a real call is verified. |
| **Provider credential rotation** | Deferred by explicit user decision until PROJECT COMPLETE (`.kiro/steering/plaintext-source-policy.md`). Note that credentials pasted into chat are exposed and rotation is remediation, not hygiene. |

---

## Risk register

| Risk | Mitigation |
|---|---|
| India SMS stops because IAM is `us-east-1`-scoped | Verify the live role and `DryRun` in `ap-south-1` before any sender change |
| Unregistered DLT content sent to Indian numbers | Keep the hard 422 gate; never soften `_resolve_dlt_template` |
| Two SMS per call after the SIP repoint | Choose one owner in 7b *before* 7c/7d |
| Repoint breaks WhatsApp calling on a live business number | Test Option A on the secondary number first; roll back via `wecare/meta/whatsapp-sip` |
| E.164 misdelivery to the wrong country | `_format_e164` already fixed; keep its tests |
| Migration regresses while in flight | Stage 1 gate lands first |
| Silent success with no delivery | Origination identity stays pinned off the simulator number |
| Deleting Lightsail too early | Blocked until 7d is verified with a real call |
