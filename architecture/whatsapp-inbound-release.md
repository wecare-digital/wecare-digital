# WhatsApp inbound release: Meta routing prerequisite

The inbound Lambda acknowledges `standby` and `messaging_handovers` without
storing customer payloads or issuing replies. If Meta still assigns a thread
to Business AI rather than the normal messaging path, a 200 alone does not
show that Inbox received it. These checks apply before promoting the
`wecare-inbound-whatsapp:live` alias, including rollbacks that affect routing.

## Release sign-off

Record the Git SHA, proposed Lambda version, current rollback version, reviewer,
timestamp, and a pass/fail result for **each** owned WhatsApp Business Account
(WABA) in the approved private release record:

| Account | Verify with an authorized Meta operator |
| --- | --- |
| WECARE.DIGITAL (WABA 1) | Business AI is disabled or no longer owns traffic on every configured sending number. Ordinary inbound messages reach the normal app subscription and Inbox. |
| Manish Agarwal (WABA 2) | Perform the same independent checks. A pass for WABA 1 does not cover WABA 2. |

1. In the authorized Meta business management surface, confirm both account
   and number-level routing, including any existing conversations still owned
   by the AI or handover path. Check the current subscription for the normal
   message webhook. Use the repository's owned sender mapping only to identify
   the accounts; it is not proof of current provider configuration.
2. Before promotion, provision and verify the monitoring-only
   [CloudFormation stack](../infra/whatsapp-inbound-routing-alarm.yml) through
   the approved AWS change process. Use the existing inbound Lambda log group
   and approved alarm SNS topic in the same account and region. Confirm the
   metric filter and alarm exist, the topic is subscribed by the responsible
   operator, and the release record captures the alarm name. Review the change
   set before execution. Do not publish a Lambda version or modify Meta
   settings as part of provisioning this stack.
3. With separate authorization for a synthetic test, send one ordinary inbound
   test message through each configured route, using designated test
   identities. Confirm it appears once in the expected Inbox with the correct
   WABA. Without authorization or a provable status on either account, mark
   the release **blocked**. Do not use a real customer conversation or send a
   production test message as an alternative.
4. After promotion, check the alarm and recent worker logs during the rollout
   watch window. Confirm normal processing for both WABAs and retain evidence
   that does not include message contents or customer identifiers.

## When the alarm fires

The alarm counts each `webhook_field_ignored` event and alarms at one or more
events in a five-minute period. The event records the field, request ID and
an owned WABA ID when attributable; all other account values are logged as
`unknown-or-partner`. It never emits the ignored message body, phone number,
contact profile or raw provider payload.

Pause further promotion. In the worker log group, find recent
`webhook_field_ignored` events and compare the affected account's routing with
its sign-off. If the account is unknown or inconsistent, check both owned
accounts and the partner path without guessing. Restore normal provider
routing or roll back through the approved release process, as evidence
warrants. Do not blindly replay a standby event or attempt an outbound reply;
first determine whether the same message already reached the canonical Inbox.

An OK alarm is **not** positive provider-routing evidence; absence of events
is expected and missing data is non-breaching. Keep the per-account checks
even when the alarm is green.
