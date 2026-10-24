# Provider retirement inventory

What the retired SMS and voice paths were replaced by. Code comments in
`amplify/functions/messaging/whatsapp-calling/handler.py` and `scripts/deploy_all_lambdas.py`
point here. The full classified inventory taken before removal (baseline commit `6680a9fa`,
2026-09-19) is in git history.

## Current transports

| Channel | Transport | Lambdas |
|---|---|---|
| SMS | AWS End User Messaging (`pinpoint-sms-voice-v2`) through `lambda_utils.comms`; India in `ap-south-1` behind the TRAI DLT gate (`DLTTemplates`), everything else in `us-east-1` | `wecare-sms-aws`, `wecare-outbound-sms` (delegates to `wecare-sms-aws`) |
| Voice | Plivo PSTN and browser softphone; AWS End User Messaging voice; Meta WhatsApp calling and voice notes | `wecare-plivo-answer`, `wecare-pstn-softphone`, `wecare-voice-aws`, `wecare-voice-cdr-read`, `wecare-whatsapp-calling`, `wecare-whatsapp-voice` |
| RCS | Sinch, Indian destinations only | `wecare-rcs-send`, `wecare-rcs-dlr` |

`VoiceCDRTable` stays: `wecare-plivo-answer` writes it and `wecare-voice-cdr-read` reads it.

## What is gone

The previous India SMS sender and its static-IP proxy, the old click-to-call, outbound-dialler
and CDR-ingest voice Lambdas, the Sinch SMS sender and its DLR receiver, SNS `publish` for SMS
and classic Pinpoint `send_messages`. Their source, deploy-map entries, routes, tables and
secrets are removed; nothing of them remains in the account. Credential disposal is recorded
in [`docs/security.md`](security.md#retired-provider-credentials).

## Enforcement

`scripts/check_provider_allowlist.py`, run explicitly as an operational gate, fails
CI on any host, SDK, secret prefix, provider id, env namespace or channel Lambda that
`scripts/provider_allowlist.py` does not declare. Its `sms-transport`, `rcs-transport` and
`channel-lambdas` rules keep the table above true.
