# Provider inventory and disposition

Every provider touchpoint in the repository, with the action the Unified
Communications Platform spec requires. Baseline commit `41dc41c2`, 2026-09-19.

Disposition vocabulary:

| | meaning |
|---|---|
| **KEEP** | stays as-is, possibly moved behind an abstraction |
| **REWIRE** | keeps working but must route through the orchestrator |
| **DELETE** | removed from runtime; historical records may retain the name |
| **NEW** | does not exist yet, must be built |
| **SCRUB** | contains credential material that must be removed regardless |

---

## 1. Target provider matrix (§54)

| Provider | Messaging | SMS | Voice | RCS |
|---|---|---|---|---|
| **Meta** | WhatsApp ✅ | — | WhatsApp Calling ✅ | — |
| **AWS** | — | **ALL SMS ✅** | — | international ✅ |
| **Sinch** | ❌ | ❌ | ❌ | **India only ✅** |
| **Plivo** | ❌ | ❌ | PSTN/SIP/IVR ✅ | — |

The single most important rule: **AWS End User Messaging is the normal SMS
provider**, for India (`ap-south-1`) and international (`us-east-1` default),
including as the fallback for both RCS paths.

---

## 2. AWS — End User Messaging SMS

| Item | Location | Disposition |
|---|---|---|
| EUM v2 sender, two-region, DLT-aware | `messaging/sms-aws/handler.py` | **KEEP** — becomes `AwsSmsProvider` |
| `us-east-1` client | `sms-aws/handler.py:39` | KEEP |
| `ap-south-1` per-request client | `sms-aws/handler.py:407` | KEEP → move behind `SmsRegionResolver` |
| DLT country params | `sms-aws/handler.py:417-424` | KEEP |
| Hard DLT gate + 422 | `sms-aws/handler.py:92-110,316-334` | KEEP — required by §6 "fail safely" |
| `DryRun` | `sms-aws/handler.py:426-428` | KEEP — use for §49 acceptance |
| Origination identity pinned `+18444891209` | `sms-aws/handler.py:48-59` | KEEP |
| `_format_e164` country-code correctness | `sms-aws/handler.py:479-505` | KEEP |
| Classic Pinpoint template CRUD | `sms-aws/handler.py:41` + `/templates` | **DELETE** — explicitly not DLT (`:66-73`); the DynamoDB registry is authoritative |
| Optimistic `status:'SENT'`, never updated | `sms-aws/handler.py:357-375` | **NEW** — needs a delivery-receipt consumer |
| Region-pinned IAM `sms-voice` ARN | `amplify/iam-policies.ts:94-105` | **REWIRE** — must cover `ap-south-1` |
| Voice via EUM v2 | `messaging/voice-aws/handler.py:34,258-270` | KEEP (out of SMS scope) |

**Gap with no current owner:** no delivery-receipt ingestion exists anywhere for
AWS SMS. Until it is built, "delivered" is unknowable and §42's *delivery rate*
dashboard cannot be honest.

---

## 3. AWS — RCS (international)

| Item | Disposition |
|---|---|
| `AwsRcsProvider` | **NEW** (§14) |
| `AwsRcsTemplateRenderer` | **NEW** (§15) |
| `RcsCapabilityResolver` | **NEW** (§17) — must **not** branch on Android vs iPhone |
| RCS → AWS SMS fallback + channel-state tracking | **NEW** (§16) |
| Agent/pool registration in `us-east-1` | **NEW** — provider-approval gated |

Nothing exists today. There is no `social-messaging` client anywhere in the repo.

---

## 4. Sinch — DELETE all SMS, KEEP India RCS

### 4.1 Sinch SMS — DELETE (§9)

| Item | Location |
|---|---|
| Credential loader | `outbound-sms/handler.py:270-297` (secret `wecare/sinch/sms`) |
| Sender | `outbound-sms/handler.py:299-385` → `jumbo.aclgateway.com/v12/.../messages.json` |
| DLR receiver (whole Lambda) | `messaging/sms-in/sinch/handler.py`, `wecare-sinch-dlr` |
| Frontend forcing the Sinch branch | `src/api/client.ts:1248-1266` `sendSinchSms()` |
| Route `POST /webhook/sinch-dlr` | `docs/WEBHOOK-INVENTORY.md:20` |
| IAM | `amplify/iam-policies.ts:395` |
| Deploy map entry | `scripts/deploy_all_lambdas.py:160` |
| Secret definition | `scripts/store_provider_secret.py:174-185` |
| UI send tab | `src/pages/dm/sms/index.tsx` |

Historical rows may keep `provider = 'sinch'`. **New** SMS must never use Sinch.

Note: `wecare/sinch/sms` currently has **no `oauth_token`**, so Sinch SMS cannot
send at all right now (`outbound-sms/handler.py:315` hard-fails). Deleting this
path removes a already-broken dependency rather than a working one.

### 4.2 Sinch India RCS — KEEP (§10-§13)

| Item | Location | Disposition |
|---|---|---|
| RCS helper | `lambda_utils/sinch_rcs.py` | **KEEP** → `providers/sinch/rcs/` per §10 |
| Send Lambda | `messaging/rcs-send/handler.py` | KEEP |
| DLR Lambda | `messaging/rcs-dlr/handler.py` | KEEP |
| Enable flag `SINCH_RCS_ENABLED` | `lambda_utils/sinch_rcs.py` | KEEP |
| Data model `RcsMessages` | `amplify/data/resource.ts:361-389` | KEEP |
| Approved templates `rcsmenu`/`rcsorder`/`waalert` | `sinch_rcs.py:22-25` | KEEP |
| `send_rcs_order_notification` | `sinch_rcs.py:399-431` | **DELETE** — no callers |
| `send_rcs_wa_alert` | `sinch_rcs.py:434-452` | **DELETE** — no callers |
| `SinchRcsTemplateImporter` | — | **NEW** (§12), read-only |
| Internal `RcsTemplate` model | — | **NEW** (§13) |

**RCS fallback must become AWS SMS `ap-south-1`** (§11). It must never fall back
to Sinch SMS.

---

## 6. Plivo — KEEP voice, never SMS

| Item | Location | Disposition |
|---|---|---|
| Answer URL handler | `messaging/plivo-answer/handler.py` | **KEEP** |
| Application `12775976954213184` `WECARE-WHATSAPP-IVR` | live console | **KEEP** — do not recreate (§20) |
| App SIP URI `sip:12775976954213184@app.plivo.com` | — | **NEW** — must be verified (§24) |
| Endpoint SIP `sip:wecarewaivr203331794466262@phone.plivo.com` | live console | **KEEP** — do not recreate (§23) |
| `sip_auth_type='credential'` | live console | KEEP — inbound SIP already authenticated |
| `?token=` gate on all three URLs | live console + `wecare/plivo-answer` | KEEP |
| `POST /plivo/fallback` | — | **NEW** (§22, §26) |
| `POST /plivo/hangup` | — | **NEW** (§22, §26) |
| `POST /plivo/events` | — | **NEW** (§26) |
| **V3 signature validation** | — | **NEW** (§27) — none exists anywhere |
| Post-call SMS side effect | `plivo-answer/handler.py:145-192` | **REWIRE** through the orchestrator |
| `plivo==4.62.0` | `requirements-dev.txt:73` | dev-only, not bundled — leave |
| Plivo SMS | — | **must never exist** |

No Plivo SMS code exists today, which makes §54's "Plivo SMS = NO" already true.
The CI gate must keep it true.

---

## 7. Meta — KEEP

| Item | Location | Disposition |
|---|---|---|
| WhatsApp Cloud API messaging | ~20 handlers, Graph `v25.0` | **KEEP** (§19) |
| Calling settings read/write incl. SIP | `whatsapp-business-api/handler.py:2530-2751` | **KEEP** — the repoint tool |
| SIP password redaction | `:2556-2585` | KEEP |
| Webhook signature + replay guard | `whatsapp-calling/handler.py:285-397` | KEEP |
| `appsecret_proof` helper | `lambda_utils/appsecret.py` | **REWIRE** — 4 inline re-implementations should use it |
| Unreachable `token2` branch | `whatsapp-calling/handler.py:91,108-127` | **DELETE** — `WABA2_IDS = set()` |
| Post-call SMS/RCS fan-out | `whatsapp-calling/handler.py:1333-1585` | **REWIRE** through the orchestrator |

---

## 8. Google — all NEW

| Item | Disposition |
|---|---|
| `GoogleAuthService`, incremental OAuth | **NEW** (§31) |
| `GoogleContactsService` / People API | **NEW** (§32) |
| `GoogleAdsService`, read-only in V1 | **NEW** (§33) |
| Caller-lookup chain | **NEW** (§32) |

Existing Google-adjacent code is **not** reusable for this: `marketing-ads`
handles Meta CTWA ads, and `scripts/google-*.sh` are one-off shell utilities.

Credentials already in Secrets Manager: `wecare/google/cloud` (unified API key,
verified live against PageSpeed/Places/Geocoding), `wecare/seo/google-oauth`
(client id + secret), `wecare/google/ads` (customer id `836-758-9699`, manager
`427-041-2231`).

**Blocked:** `GOOGLE_ADS_DEVELOPER_TOKEN` is **not** present in
`wecare/google/ads`. Google Ads API cannot authenticate without it.

---

## 9. Truecaller — all NEW

| Item | Disposition |
|---|---|
| `POST /auth/truecaller/callback` | **NEW** (§35) — nonce, replay protection, SSRF guard, no token logging |
| Verification flow | **NEW** (§34) — reuse existing app, do not create another |
| Truecaller for Business caller branding | **NEW** (§36) — stays `false` until KYC approval |

Only the secret definition exists (`scripts/store_provider_secret.py:107-116`).
`wecare/truecaller` now holds `app_key`, `app_name`, `app_domain`,
`callback_url`. Nothing reads it.

---

## 10. TTS — consolidate 4 implementations

| Existing | Location | Disposition |
|---|---|---|
| `/whatsapp-voice/tts` | `whatsapp-voice/handler.py:282-464` | **REWIRE** behind `TextToSpeechService` |
| `/site-language/tts` | `core/site-language/handler.py:332-341` | REWIRE — best pattern: discovers voices via `describe_voices` |
| `_generate_ivr_tts_audio` | `whatsapp-calling/handler.py:2115-2174` | REWIRE |
| `TextToSpeechService` abstraction | — | **NEW** (§30) |
| `VoiceScriptComposer` + approval flow | — | **NEW** (§28, §29) |

`plivo-answer` deliberately uses **no** TTS (pre-recorded audio only) and its
tests enforce that. Do not add TTS to it.

---

## 11. Tooling and governance — NEW

| Item | Disposition |
|---|---|
| `scripts/provider_allowlist.py` + `scripts/check_provider_allowlist.py` | **KEEP** (§44) — positive allow-list; run explicitly before provider-related releases |
| `.env.example` | **NEW** (§45) — only `.env.local.example` exists |
| `scripts/test-aws-sms.sh`, `test-india-aws-sms.sh` | NEW (§46) |
| `scripts/sync-sinch-rcs-templates` | NEW (§12) |
| `scripts/test-aws-rcs`, `test-rcs-{ios,android,fallback}` | NEW (§46) |
| `scripts/test-plivo-{webhook,application-sip}`, `test-whatsapp-sip`, `check-sip-tls` | NEW (§46) |
| `scripts/test-google-{oauth,contacts,ads}`, `test-truecaller-callback` | NEW (§46) |
| `scripts/test_call_paths.py` | **KEEP** — already the authoritative call-leg verifier |

---

## 12. Secrets — current state (31 in account `775261844268`)

| Secret | Provider | Disposition |
|---|---|---|
| `wecare/sinch/sms` | Sinch SMS | DELETE (already unusable — no `oauth_token`) |
| `wecare/sinch/rcs` | Sinch RCS | KEEP |
| `wecare/meta-system-user-token` | Meta | KEEP |
| `wecare/plivo/api`, `wecare/plivo`, `wecare/plivo-answer` | Plivo | KEEP |
| `wecare/google/cloud`, `wecare/google-api-key`, `wecare/google-maps` | Google | KEEP — all three hold the same unified key `sha256:0bd4beb6496a` |
| `wecare/seo/google-oauth` | Google OAuth | KEEP |
| `wecare/google/ads` | Google Ads | KEEP — ~~missing `developer_token`~~ **no longer a blocker, see below** |

### ⛔ Correction, 2026-09-30 — the Google Ads `developer_token` gap is obsolete

`wecare/google/ads` missing a `developer_token` was recorded here as the reason the Ads API
"cannot authenticate without it". That was true when written and is not true now.

**Google sunset developer tokens on 2026-09-09.** They may still be sent and are *ignored by
the API servers*; API access levels now attach to the **Google Cloud project** that owns the
credentials — for a service-account workflow, the project owning the service account. Signup
and access management moved from the Ads manager account's API Center to the Google Ads API
Overview page in Cloud Console, and a manager account is no longer required at all unless you
manage multiple accounts.
<https://developers.google.com/google-ads/api/docs/api-policy/developer-token>

Measured today against the live API with an impersonated service-account token and **no
developer token sent at all** (`scripts/google_products_pull.py`):

```
live API versions                     v22, v23, v24, v25   (v17-v21 are gone and answer an
                                                            HTML 404, which reads like a dead
                                                            endpoint rather than a retired one)
listAccessibleCustomers  (v25)        HTTP 200, 0 customers
query customer 8367589699 (v25)       HTTP 403
                                      authorizationError: USER_PERMISSION_DENIED
```

Read the error precisely, because two different ones mean two different fixes.
`CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION` would mean the Cloud project sits on **Test**
access and needs Explorer or Basic from the Cloud Console page. We get
**`USER_PERMISSION_DENIED`** instead — so OAuth succeeds, the project is *not* refused for
production, and the only thing missing is that the principal is not a user on the Ads account.

So Ads is now in exactly the same category as Tag Manager and Analytics: authentication is
solved, product-level access is not, and none of the three offers an API to grant it. The
unblock for all three is one action:

    add automation@wecaredigitalbw.iam.gserviceaccount.com as a read-only user

**Do not re-add the developer token as a required credential.** A future reader finding this
row should not go hunting for a value that the provider stopped honouring.
| `wecare/truecaller` | Truecaller | KEEP — no consumer yet |

Deleting a secret requires pointwise confirmation
(`.kiro/steering/maintenance-reporting.md`). No secret is deleted during the code
migration; removal is a separate, later step once nothing reads it.

---

## 13. Counts to drive §49 acceptance

Enforced by `scripts/check_provider_allowlist.py` as an explicit operational gate,
which passes on the current tree:

```
SMS transport                       AWS End User Messaging only (wecare-sms-aws; wecare-outbound-sms delegates)
SMS / voice / RCS Lambdas           exactly the CHANNEL_FUNCTIONS set in scripts/provider_allowlist.py
Sinch                               RCS channel only (wecare-rcs-send, wecare-rcs-dlr)
Plivo                               voice resources only, never SMS
AWS SMS delivery-receipt consumers  0   -> target 1
```

Acceptance is met while the gate exits `0` in CI and the delivery-receipt consumer exists.
