# Protected resource register

Phase 0 snapshot. Every row states **when it was read back and by what**. A value
carried forward from `bw-crm.md` is labelled `CARRIED FORWARD` and is **not**
evidence — it must be re-read from the provider before any mutation.

- Snapshot taken: **2026-09-21**
- Git HEAD at snapshot: `4baf4236dbf78a784ec84f238e091b699f7f8cd4` (local == `origin/stack`)
- AWS identity measured: account `775261844268`, `arn:aws:iam::775261844268:user/wecare-admin`, `us-east-1`
- Method: read-only boto3 through the AWS MCP sandbox. Every inventory call
  reported its error total; **all Phase 0 inventory calls returned errorTotal = 0**.
- No credential value appears here. Secrets are referenced by name only.

## AWS — measured 2026-09-21

| Resource | Measured value | Protection / use rule |
|---|---|---|
| Account | `775261844268` | Only account in scope. Confirm before every deploy. |
| Region | `us-east-1` | |
| Lambda functions | **58** (57 Zip + 1 Image), all `python3.12` | Brief's "65 / 64 wecare-*" is **stale**. |
| SnapStart | `ApplyOn=None` on 58 of 58 | Matches `lambda-snapstart-deploy` steering. |
| Functions with `live` alias | **49** | The alias, not SnapStart, is what makes publish-and-move mandatory. |
| Functions with no alias | **9**: `wecare-ad-attribution`, `wecare-docs-scraper`, `wecare-marketing-ads`, `wecare-partner-onboarding`, `wecare-partner-token-refresh`, `wecare-push-notifications`, `wecare-seo-tools`, `wecare-sla-engine`, `wecare-url-shortener` | `update-function-code` reaches production immediately for these. |
| HTTP APIs | **1**: `zllr9lrg7j` (`wecare-digital-api`, 361 routes) | `79g3bbufdh` (`wecare-api`) was deleted 2026-09-21; see `prohibited-provider-retirement.md`. |
| REST APIs (v1) | 0 | |
| Stages | `prod` on both APIs, `AutoDeploy=true` | Route edits take effect immediately. |
| API Gateway authorizers | **0** | All **361** routes are `AuthorizationType=NONE` (re-measured 2026-09-26; the surface grew by 29 while authorization stayed at zero). |
| Integrations | 102 on `zllr9lrg7j`, 2 on `79g3bbufdh` | |
| DynamoDB tables | **79** | Re-measured 2026-09-26; 67 of them are empty. Recount before any table action. |
| Secrets Manager entries | **31** — 25 active, 6 scheduled for deletion | Values never read. |
| Cognito user pool | `us-east-1_cSx0RHCIR` / `WECARE.DIGITAL`; clients `stack-wecare-digital-web`, `WECARE.DIGITAL` | |
| Cognito MFA | `MfaConfiguration=OFF`; SMS MFA config present but inactive; TOTP not reported enabled | Owner overrides require admin MFA implemented and verified. |
| Regional WAF WebACLs | **0** | |
| CloudFront WAF WebACLs | **0** | |
| GuardDuty detectors | **0** | Optional per owner overrides; not a closure blocker. |
| Security Hub | Not queried (**EXCLUDED** by owner overrides) | Do not enable. |
| Amplify app | `d22dm4b0jn71jw`, default domain `d22dm4b0jn71jw.amplifyapp.com`, app name `wecare.digital` | Frontend deploys only; never proves Lambda state. The app name read `retired legacy frontend host` here until 2026-09-26; `GetApp` reports `wecare.digital`, and the `stack.` host is NXDOMAIN since the CNAME was removed on 2026-09-25. |

### Secrets scheduled for deletion — measured 2026-09-21

| Secret name | Deletion date reported |
|---|---|
| `wecare/airtel-iq` | 2026-09-20 |
| `wecare/airtel/c2c` | 2026-09-20 |
| `wecare/airtel/obd` | 2026-09-20 |
| `wecare/airtel/sms` | 2026-09-20 |
| `wecare/sinch/sms` | 2026-09-20 |
| `wecare/payu` | 2026-08-26 |

`wecare/sinch/rcs` remains **active and must stay** — it is the allowed India RCS path.
A scheduled deletion is `DEPLOYED`, not `LIVE_VERIFIED`, until the secret is
permanently absent after its recovery window.

### Deployed `live` alias versions — measured 2026-09-21

| Function | live alias | Brief's dated value | Change |
|---|---|---|---|
| `wecare-whatsapp-calling` | **12** | 8 | +4 |
| `wecare-inbound-whatsapp` | **37** | 37 | none |
| `wecare-outbound-whatsapp` | **17** | 16 | +1 |
| `wecare-plivo-answer` | **9** | 9 | none |
| `wecare-sms-aws` | **12** | 11 | +1 |
| `wecare-outbound-sms` | **9** | 8 | +1 |
| `wecare-rcs-send` | **7** | 7 | none |
| `wecare-rcs-dlr` | **6** | 6 | none |
| `wecare-razorpay-webhook` | **25** | 25 | none |
| `wecare-invoice-engine` | **17** | 17 | none |

Full 58-row function/sha/alias listing is recorded in `docs/execution/evidence-index.md` under `EV-0002`.

## Meta — CARRIED FORWARD, not read back this session

No Meta Graph call was made during Phase 0. Both Meta MCP servers were
unauthenticated. Re-read every row before any mutation, and never substitute a
same-named template object from another WABA.

| Resource | Carried-forward value | Rule |
|---|---|---|
| Primary number | `+919330994400` | Never deregister, re-register, or change its two-step PIN. |
| Primary phone-number ID | `1016149501586345` | Required sender ID for WABA1. |
| Primary WABA | `2094615664435155` | Preserve registration, templates, history. |
| Secondary number | `+919903300044`, phone ID `1055232054343117` | Preserve; one follow-up only, from this same number. |
| Secondary WABA | `2513394156072604` | Read back before use. |
| Primary app | `2238810740192680` / `WECARE.DIGITAL` | Keep the working callback/subscription. |
| Business Agent app | `1143680903703001` | Inspect only; never offboard a number. |
| WABA1 `wd_menu` | object `998210796499191`, `en`, `UTILITY`, VIDEO header, `Get Started` quick reply | Revalidate APPROVED before every live send. |
| WABA2 `wd_menu` | object `2429247000907048` | WABA2 only. Same name is not the same object. |
| `wd_call_followup_v1` | Does **not exist** | Proposed name only. |
| Payments gateway config | `WECAREDIGITAL`, Razorpay MID `acc_TTFSyolquKEZEy`, MCC `7392`, purpose `03` | MCC/purpose mismatch is an open compliance question, not a default. |
| Payments UPI config | `WECAREUPI`, VPA `wecaredigitalbh511413.rzp@rxairtel` | Byte-for-byte preserved. `rxairtel` is a payment address, not an Airtel integration. |

## Plivo — CARRIED FORWARD, not read back this session

| Resource | Carried-forward value | Rule |
|---|---|---|
| Voice number | `+918031830030` | Voice enabled, SMS disabled. Preserve binding. |
| Application | `12775976954213184` / `WECARE-WHATSAPP-IVR`, SIP `sip:12775976954213184@app.plivo.com` | `default_endpoint_app=true` is protected. |
| Endpoint | `543585900967411` / `WECARE-WhatsApp-IVR-SIP`, `sip:wecarewaivr203331794466262@phone.plivo.com` | Application SIP and endpoint SIP are different resources. |
| Answer / hangup / fallback callbacks | `POST https://api.wecare.digital/plivo/{answer,hangup,fallback}?token=<REDACTED>` | The query token is a credential. `<REDACTED>` everywhere; resolve only by secret reference. |
| Public URI | Not populated in the owner snapshot | Re-read before relying on absence. |

## Other provider identifiers — CARRIED FORWARD

AWS SMS India sender `WDBEEP`, entity `1201161991108627443`, DLT key `ivr-default`,
template `1007277993798259629` (`ap-south-1`). Sinch RCS India template `rcsmenu`,
provider template ID **UNVERIFIED**. Razorpay live key-ID suffix only `…gGJv`;
credential replacement is a deferred `MANUAL_OWNER_ACTION` and outside this plan.
