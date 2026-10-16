# AWS stale-resource cleanup — ready-to-run (2026-10-16)

Account **775261844268** · region **us-east-1**. From the deep-audit §5/§5c findings.
Each item is a production AWS mutation, so each is 🔒 owner-approved — but every one
is low-risk, reversible, and the exact command + rollback is below. State re-verified
live 2026-10-16; rollback snapshots in `.scratch/cleanup-rollback/`.

## Item 6 (4 unlisted secrets) — NO ACTION NEEDED

Re-check shows all four are **already scheduled for deletion** (in the recovery
window, auto-deletes on schedule):
- `wecare/ads/account-registry` — deleted-at 2026-10-07
- `wecare/integrations/owner-input-20261001` — deleted-at 2026-10-07
- `wecare/plivo` — deleted-at 2026-10-07
- `wecare/sinch/sms` — deleted-at 2026-09-20

Nothing to do. They remove themselves. (To cancel a deletion instead:
`aws secretsmanager restore-secret --secret-id <name>`.)

---

## Item 3 — delete the dangling `UsersTable` CloudWatch alarm

**Why:** `wecare-ddb-throttle-UsersTable` watches dimension
`TableName=stack-wecare-digital-UsersTable`, a table that no longer exists, so the
alarm can never evaluate meaningfully. Verified live: table absent, alarm state `OK`.

**Apply:**
```sh
aws cloudwatch delete-alarms --alarm-names wecare-ddb-throttle-UsersTable --region us-east-1
```
**Verify:**
```sh
aws cloudwatch describe-alarms --alarm-names wecare-ddb-throttle-UsersTable \
  --query 'length(MetricAlarms)' --region us-east-1   # expect 0
```
**Rollback:** recreate from the saved snapshot
`.scratch/cleanup-rollback/usertable-alarm.json`:
```sh
aws cloudwatch put-metric-alarm --cli-input-json file://.scratch/cleanup-rollback/usertable-alarm.json --region us-east-1
```
(Reconcile through whatever IaC provisions alarms so it does not reappear on deploy.)

---

## Item 4 — delete the orphaned Contact IAM role

**Why:** `ContactIAMRole09bdb2-2x7khx2ndra7nmspnydn5kphje-NONE` is an unmaterialised
Amplify-sandbox role (the `-NONE` suffix); it grants a deleted `Contact-...-NONE`
table and is attached to **0 live Lambdas** (verified live). One inline policy
`DynamoDBAccess`, no attached managed policies.

**Apply (inline policy must be deleted before the role):**
```sh
R=ContactIAMRole09bdb2-2x7khx2ndra7nmspnydn5kphje-NONE
aws iam delete-role-policy --role-name "$R" --policy-name DynamoDBAccess
aws iam delete-role --role-name "$R"
```
**Verify:**
```sh
aws iam get-role --role-name ContactIAMRole09bdb2-2x7khx2ndra7nmspnydn5kphje-NONE 2>&1 | grep -q NoSuchEntity && echo "gone"
```
**Rollback:** recreate from snapshots:
```sh
R=ContactIAMRole09bdb2-2x7khx2ndra7nmspnydn5kphje-NONE
aws iam create-role --role-name "$R" \
  --assume-role-policy-document file://.scratch/cleanup-rollback/contact-role-trust.json
aws iam put-role-policy --role-name "$R" --policy-name DynamoDBAccess \
  --policy-document file://.scratch/cleanup-rollback/contact-role-dynamodbaccess.json
```

---

## Item 5 — drop the dead `CustomersTable` grant from email-verification role

**Why:** `wecare-email-verification-role` → inline `EmailVerificationLeastPrivilege`
→ `OtpAndCustomerTables` statement grants `stack-wecare-digital-CustomersTable`,
which does not exist (live tables are `ContactsTable` / `CustomerSessionsTable`).
The statement legitimately keeps `DownloadGrantsTable`. Verified live: dead ARN
still present.

**Apply (replace the inline policy with the corrected one — CustomersTable removed,
DownloadGrantsTable kept):**
```sh
aws iam put-role-policy --role-name wecare-email-verification-role \
  --policy-name EmailVerificationLeastPrivilege \
  --policy-document file://.scratch/cleanup-rollback/email-verif-policy-after.json \
  --region us-east-1
```
**Verify (CustomersTable gone, DownloadGrantsTable remains, SES/OTP intact):**
```sh
aws iam get-role-policy --role-name wecare-email-verification-role \
  --policy-name EmailVerificationLeastPrivilege \
  --query 'PolicyDocument.Statement[?Sid==`OtpAndCustomerTables`].Resource' --output json
# expect only the DownloadGrantsTable ARN
```
**Rollback:** restore the original:
```sh
aws iam put-role-policy --role-name wecare-email-verification-role \
  --policy-name EmailVerificationLeastPrivilege \
  --policy-document file://.scratch/cleanup-rollback/email-verif-policy-before.json
```
Reconcile through `scripts/provision_email_verification.py` so the dead ARN does
not reappear on the next deploy.

---

## Suggested order & batching

All three are independent and reversible. Safe to run together. None touches a
live table, a running function, or any secret value. After applying, reconcile the
IaC for items 4 and 5 so the deleted role/grant do not reappear on a redeploy.
