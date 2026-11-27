# Arogya Yatra appointment storage

The `wecare-arogya-booking` Lambda and `wecare-arogya-bookings` DynamoDB table persist appointment drafts for a customer verified through the existing WhatsApp Cognito flow. This release does not submit patient requests to Apollo or charge a payment. The separate provider-session core and Gmail consent must be connected before that phase can be enabled.

## API and table

The Lambda Function URL accepts POST JSON with a customer access token in `Authorization: Bearer …`. The handler pins the customer pool, calls Cognito GetUser and requires `phone_number_verified=true`. Staff tokens and request-supplied customer IDs cannot select an owner.

| Action | Body | Result |
| --- | --- | --- |
| `quote` | `{action:"quote"}` | Existing server pricing for ₹550 base; no payment created |
| `save` | `{action:"save",draftId:<UUID v4>,revision:0,plan:<AppointmentPlan>}` | Owned draft with revision 1 |
| `save` | Same reference and current revision | Conditional revision increment; stale saves return 409 |
| `get` | `{action:"get",draftId}` | Own unexpired draft or 404 |
| `list` | `{action:"list"}` | At most 20 draft references, without patient details |
| `delete` | `{action:"delete",draftId}` | Idempotent removal from caller's partition |

Partition key is authenticated Cognito subject (`customerId`); sort key is `draftId`. Access uses GetItem, conditional UpdateItem, bounded Query and DeleteItem. There are no scans or indexes. All replies use `Cache-Control: no-store, private`. Drafts expire after 30 days without a save; reads enforce the deadline independently of eventual DynamoDB TTL cleanup. DynamoDB uses its default AWS-owned encryption key at rest. No patient data, token or request body is logged. Deleting a stack retains the table to avoid losing customer data.

The server validates mandatory fields, option enums, date and time formats, text limits, patient details, pickup and admission fields. Extra fields such as a client-supplied price or owner are rejected. Saving preferences does not verify a UHID, doctor, schedule or patient record. Provider submission requires additional authorization and paid-order idempotency gates.

## Cost configuration and evidence

On 27 November 2026 the connected AWS account `775261844268` reported no provisioned DynamoDB capacity across its 75 tables in `us-east-1`. Its Free Tier API reported Lambda usage of 547,853 of 1,000,000 monthly requests and 25,084.853375 of 400,000 GB-seconds, with DynamoDB storage at 0.02830688 of 25 GB-month. These are observations for that month, not permanent reservations.

The dedicated Standard table uses **5 RCU and 5 WCU**, with automatic scaling absent. AWS publishes 25 RCU and 25 WCU of free provisioned capacity per eligible region/account. This table therefore fits within the currently unused allowance. On-demand request billing would not use that provisioned-capacity allowance. See [DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/).

The function has 128 MB memory, 15-second timeout, reserved concurrency 2 and no provisioned concurrency. A Function URL avoids an additional API Gateway charge. There are no scheduled invocations, servers, NAT gateways, new KMS keys, paid dashboards, custom metrics, backup plans, PITR or automatic scaling in this stack. Standard Lambda logs have seven-day retention. Reserved concurrency limits simultaneous work, not the number of monthly requests.

**A permanent ₹0 bill cannot be guaranteed.** Lambda requests and duration, log ingestion, storage, artifact storage and internet transfer are usage-metered and share account allowances. Existing account activity can consume the free allowances. Provisioned capacity is billed if eligibility or the available allowance changes. WhatsApp messages, payment processing, hosting and hospital fees have their own costs. There is no AWS budget setting that guarantees instantaneous zero-cost shutdown; an alert is not a hard spending cap. Do not describe this stack as unconditionally free.

## Release

Build from the merged repository revision:

```sh
python3 scripts/build_arogya_booking.py --output /absolute/path/to/release
cfn-lint amplify/infra/arogya-booking.json
```

The manifest records the immutable ZIP key and SHA256. Upload the ZIP to the existing deployment artifact bucket, validate the template, then review a CREATE change set for `wecare-arogya-booking`. It should contain only Bookings, Logs, Role, Function, Url and the two narrowly conditioned Function URL permissions. Verify current free capacity before execution. No existing table, role, key, customer pool or API is modified.

After deployment, verify the native stack outputs, function configuration and code SHA, table mode/capacity/TTL, unauthenticated 401 and unsupported-method 405. A real customer must sign in through the existing WhatsApp flow for a live owned-draft test; never forge a Cognito identity or use patient data for a synthetic test. Configure the exact Function URL on the page before enabling saved drafts. The current public planner remains a local draft until that frontend connection is deployed.
