"""Metric filter + alarm for a refused WhatsApp-first identity claim.

Why this exists
---------------
The claim is the step that links a WhatsApp-first contact to a website session, and every refusal
answers the customer with the same generic `409 CONTACT_IDENTITY_CONFLICT` — no reason, by design,
because a per-reason code would turn the refusal into an oracle for "is this number already owned
by somebody". The reason lives in two places instead: the `Identity Conflict` tag plus
`identityConflictReason` on the contact row, which is the staff reconciliation surface, and an
`identity.claim_refused` audit record.

Neither covers the dead end that matters most. A refusal whose cause is the SESSION rather than the
data (`UNVERIFIED_PHONE`) deliberately marks NO contact — tagging the customer's own row for a
conflict that does not exist would fill the one CRM view staff work from with rows needing no work —
so it leaves no CRM surface at all, and the audit table is not monitored. The customer is simply
stuck on a permanent 409 that is visible from nowhere.

`identity_claim_refused` (WARNING, from `auth/customer-profile`) closes that. It carries the reason
CODE and the number of rows marked, and nothing else: no phone, no email, no owner id.

Threshold is deliberately 1, not a rate. A blocked sign-in is individually actionable and these are
rare by construction; averaging would hide the first. Read the `reason` field on the log line:

* `UNVERIFIED_PHONE` — the session's `phone_number_verified` is not `true`. Both code paths that
  create a customer-pool user set it to `true` (`core/secure-files::_provision_partner_user` and
  the undeployed `auth/customer-registration`), and the pool is `AllowAdminCreateUserOnly`, so this
  should be unreachable. If it fires, a user exists that those paths did not create, and NO contact
  was marked — this alarm is the only trace.
* `FOREIGN_OWNER` — the number is already linked to a different customer. Operator-actionable, and
  the contact row carries the tag.
* `AMBIGUOUS_PHONE` — more than one live contact on one number. Needs a merge decision from staff.
* `NO_INBOUND_EVIDENCE` — a staff/outbound-only row with no proof the holder ever messaged in. The
  claim is refused on purpose; the row is tagged for staff.
* `DELETED_CONTACT` — an archived row. The `isDeleted`-only shape is a permanent 409 until staff
  act, which is why it is marked.

`TreatMissingData='notBreaching'` because no data is the expected steady state.

MODELLED ON `scripts/provision_payment_gate_alarms.py`, the working in-repo pattern for a log-event
metric filter. Created via boto3 because ampx cannot run in the agent environment. Every put_* is
an upsert, so this script is idempotent and safe to re-run.

NOT RUN by the branch that added it: that work was AWS read-only. Run it once before relying on the
alarm.

Cost: metric filters are free; one alarm at roughly $0.10/month.
"""
import boto3

REGION = "us-east-1"
NS = "WECARE.DIGITAL"
SNS_ARN = "arn:aws:sns:us-east-1:775261844268:wecare-alarm-notifications"

#: The one function that performs the claim. `scripts/provision_customer_profile.py::FUNCTION_NAME`
#: is the same name; spelled here rather than imported so this script has no import-time coupling
#: to a provisioner that talks to IAM.
FUNCTION_NAME = "wecare-customer-profile"

EVENT = "identity_claim_refused"
METRIC_NAME = "IdentityClaimRefused"


def main() -> None:
    logs = boto3.client("logs", region_name=REGION)
    cw = boto3.client("cloudwatch", region_name=REGION)

    log_group = f"/aws/lambda/{FUNCTION_NAME}"
    filter_name = "identity-claim-refused"
    logs.put_metric_filter(
        logGroupName=log_group,
        filterName=filter_name,
        filterPattern=f'"{EVENT}"',
        metricTransformations=[{
            "metricName": METRIC_NAME,
            "metricNamespace": NS,
            "metricValue": "1",
            "defaultValue": 0.0,
            "dimensions": {"FunctionName": FUNCTION_NAME},
        }],
    )
    print(f"metric filter {filter_name} set on {log_group}")

    alarm_name = f"wecare-{FUNCTION_NAME}-identity-claim-refused"
    cw.put_metric_alarm(
        AlarmName=alarm_name,
        AlarmDescription=(
            f"{FUNCTION_NAME}: {EVENT} logged - a customer signing in with a verified WhatsApp "
            "number could not be linked to their existing contact, and was answered with the "
            "generic 409. Read the `reason` field. UNVERIFIED_PHONE should be unreachable and "
            "marks no contact, so this alarm is its ONLY trace; the other reasons also tag the "
            "contact row with `Identity Conflict` for staff on /workspace/contacts."
        ),
        Namespace=NS,
        MetricName=METRIC_NAME,
        Dimensions=[{"Name": "FunctionName", "Value": FUNCTION_NAME}],
        Statistic="Sum",
        Period=300,
        EvaluationPeriods=1,
        # One blocked sign-in is actionable.
        Threshold=0.0,
        ComparisonOperator="GreaterThanThreshold",
        TreatMissingData="notBreaching",
        AlarmActions=[SNS_ARN],
        OKActions=[],
    )
    print(f"alarm {alarm_name} created")

    for alarm in cw.describe_alarms(AlarmNames=[alarm_name])["MetricAlarms"]:
        print(f'verify: {alarm["AlarmName"]} state={alarm["StateValue"]} '
              f'alarm_actions={len(alarm["AlarmActions"])}')


if __name__ == "__main__":
    main()
