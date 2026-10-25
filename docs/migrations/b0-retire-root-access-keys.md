# B-0 — Retire the root account access key

Account **775261844268** · region **us-east-1** · prepared 2026-10-16 from live
read-only IAM metadata. This is the highest-blast-radius finding in
`docs/execution/deep-audit-20261016.md`.

🔒 **Owner-executed.** This runbook changes who automation authenticates as and
then deletes a root credential. Every mutating step is marked and must be run by
the owner with eyes on. Nothing here was executed by the audit.

---

## The problem, measured

- `aws iam get-account-summary` → `AccountAccessKeysPresent = 1`. The **root user
  has an active access key**.
- The local automation profile is wired to it: `AWS_PROFILE=wecare-prod`, and
  `aws sts get-caller-identity` under both the default and `wecare-prod` profiles
  returns `arn:aws:iam::775261844268:root`. So the key stored under
  `[wecare-prod]` in `~/.aws/credentials` **is the root key** — every audit and
  provisioning script in this repo currently runs as root.
- Root MFA is already enabled (`AccountMFAEnabled = 1`) — good, keep it.

Why this matters: a root key cannot be scoped by IAM policy or restrained by an
SCP, is exempt from most guardrails, and its compromise is total, unrecoverable
account takeover. AWS's own guidance is to have **zero** root access keys.

## What already exists (so we don't build from scratch)

- IAM user **`wecare-admin`** — `AdministratorAccess`, one active programmatic key
  (id `AKIA…TYEC`, created 2026-09-18; full id via `aws iam list-access-keys
  --user-name wecare-admin`). A usable, non-root principal.
- IAM user **`wecare-user`** — `AdministratorAccess`, **no** access keys. Its console
  password (no MFA device, last used 2026-09-25) was removed on 2026-10-25, so it has no
  credentials at all; see `docs/execution/snapshots/wecare-user-console-password-removal-20261025.json`.
- IAM user **`asterisk-ivr-service`** — service user, no attached managed policy
  (the Lightsail IVR identity). Since 2026-10-25 it has no Secrets Manager access; the
  unused `wecare/*` read was removed.
- IAM user **`wecare-xacct-reader`** — can assume `OrganizationAccountAccessRole` in the
  backup account `991322955408`. Its only access key, never used, was set Inactive on
  2026-10-25.
- 74 roles for the Lambda/CI workloads (unaffected by this change).

## Target state

1. The `wecare-prod` profile authenticates as a **dedicated IAM automation
   principal**, not root.
2. **Zero root access keys.** Root is console-only, MFA-protected, used only for
   the handful of tasks that genuinely require root.
3. (Follow-up, separate change) the automation principal is **least-privilege**,
   not `AdministratorAccess`.

---

## Plan S — IAM Identity Center profile (steps 1–3 done 2026-10-25, recommended)

**Status 2026-10-25 08:25:29 UTC:** `wecare-prod` resolves to
`assumed-role/AWSReservedSSO_AdministratorAccess_39eb59d8bf7f2071/wecare-user` for both the
CLI and boto3 (`method: sso`). Under the SSO role, the account inventory and cost model
passed; `check_live_provider_independence.py` produced the same check outcomes as under root
(its one FAIL, `lambda-env`, is an existing finding); `remediate_commerce_keys_iam.py` plan mode
was COMPLIANT; and the `wecare-invoice-engine` v111 / `wecare-checkout` v121 hotfix was
published with it. `docs/operations.md` is updated. Step 4 (the root key) remains.

Nothing has to be created in AWS and no new key is issued. Verified live 2026-10-25:
the organization instance `ssoins-72233d266e9d7140` (access portal
`https://d-906601e018.awsapps.com/start`, `us-east-1`) has the user `wecare-user`, and the
`AdministratorAccess` permission set (`ps-722332fc036c7db8`) is assigned to that user on
`775261844268` and provisioned. Role credentials are short-lived and the CLI refreshes them,
so there is no standing secret on disk.

Already added locally (non-secret, additive; `wecare-prod` untouched): `~/.aws/config`
holds `[sso-session wecare]` (portal above, region `us-east-1`, scope `sso:account:access`)
and `[profile wecare-sso]` (`AdministratorAccess` on `775261844268`).

1. 🔒 Owner: `aws sso login --sso-session wecare`, sign in as `wecare-user` with its MFA,
   choose **Allow**.
2. Verify: `aws sts get-caller-identity --profile wecare-sso` must show
   `assumed-role/AWSReservedSSO_AdministratorAccess_…/wecare-user`, then run the Step 3
   checks below with `AWS_PROFILE=wecare-sso`.
3. Cut over without renaming any profile:
   ```sh
   aws configure set profile.wecare-prod.sso_session wecare
   aws configure set profile.wecare-prod.sso_account_id 775261844268
   aws configure set profile.wecare-prod.sso_role_name AdministratorAccess
   ```
   The AWS CLI and boto3 (all of this repo's tooling) try the SSO settings before
   `~/.aws/credentials`, so the root key stops being used while staying in place as the
   fallback. Rollback: delete those three lines from `[profile wecare-prod]`. Do not use
   `aws configure set sso-session.<name>.<key>`: it writes a stray key into the active
   profile instead of the session section.
4. 🔒 Plan A Steps 4–5: deactivate the root key (`AKIA…PONC`), soak, delete. Before
   deactivating, confirm in CloudTrail (`lookup-events` on that `AccessKeyId`) that nothing has
   used it since the cutover; a process started earlier keeps the key it loaded until it
   restarts, and Kiro's AWS MCP server is one such process. When it is deactivated, also remove
   the `[wecare-prod]` keys from `~/.aws/credentials` (some SDKs prefer static keys over SSO
   settings).

Trade-off: when the Identity Center sign-in session ends (8 hours by default; settable from
15 minutes to 90 days under IAM Identity Center → Settings → Authentication), every AWS call
fails closed until step 1 is repeated. If unattended runs must never wait for a sign-in,
use Plan A.

### Other root sign-ins (CloudTrail, 2026-10-25)

Deleting the root access key does not end these, because they use root's console sign-in:

- `openai-connectors-oauth/1.0`: a ChatGPT connector authorised as root, 483
  `CreateOAuth2Token` refreshes since 2026-10-03. Disconnect it, or reconnect it signed in
  as a non-root identity.
- `aws-cli/2.38.5` on Windows 10 (`aws login`, same network as the Mac), 6 refreshes on
  2026-10-25. Run `aws logout` there and sign in with the Identity Center profile instead.

---

## Plan A — minimal, lowest-risk (non-interactive alternative)

Repoint automation to a **new dedicated IAM user** created for tooling, verify,
then delete the root key. A new user (rather than reusing `wecare-admin`) keeps
automation credentials separate from an interactive admin and makes later
scoping and rotation cleaner.

### Step 1 — 🔒 create a dedicated automation user (owner)
```sh
aws iam create-user --user-name wecare-automation
# Interim: attach AdministratorAccess so nothing breaks during cutover.
# Tightened to least-privilege in Plan C below, as a separate reviewed change.
aws iam attach-user-policy --user-name wecare-automation \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
aws iam create-access-key --user-name wecare-automation
# ^ prints AccessKeyId + SecretAccessKey ONCE. Store them straight into the
#   profile below; do not paste them into chat, a file, or a commit.
```

### Step 2 — repoint the local profile (owner, no AWS mutation)
Edit `~/.aws/credentials` so `[wecare-prod]` holds the **new user's** key instead
of the root key:
```ini
[wecare-prod]
aws_access_key_id     = AKIA...        # wecare-automation
aws_secret_access_key = ...            # wecare-automation
```
(Prefer `aws configure --profile wecare-prod` so the secret never hits your
shell history.)

### Step 3 — verify the new identity works (read-only, safe to run)
```sh
aws sts get-caller-identity --profile wecare-prod
# EXPECT: arn:aws:iam::775261844268:user/wecare-automation  (NOT :root)

# Re-run the repo's own read-only audits under the new profile; all must pass:
AWS_PROFILE=wecare-prod python scripts/aws_account_inventory.py --json-only
AWS_PROFILE=wecare-prod python scripts/check_live_provider_independence.py
AWS_PROFILE=wecare-prod python scripts/aws_cost_model.py --live
```
Also exercise one representative provisioning script in **dry-run** if it has one
(e.g. `scripts/remediate_commerce_keys_iam.py` plan mode) to prove write paths
resolve under the new principal.

### Step 4 — 🔒 deactivate (don't delete) the root key first
Deactivating is instantly reversible; it flushes out any forgotten consumer
without burning the bridge.
```sh
# Find the root key id in the Billing/IAM console (CLI cannot list root keys).
# Security credentials (root) → Access keys → Make inactive.
```
Leave it inactive **24–72h**. Watch CloudTrail for any `AccessDenied` or signs of
a job that still used root. If something breaks, re-activate and investigate.

### Step 5 — 🔒 delete the root access key (owner, console)
After the soak with no fallout:
```
Root → My Security Credentials → Access keys → Delete.
```
Confirm:
```sh
aws iam get-account-summary --query 'SummaryMap.AccountAccessKeysPresent'
# EXPECT: 0
```

### Rollback
- Up to Step 4: re-activate the root key in the console; set `[wecare-prod]` back
  to it. Instant.
- After Step 5 (key deleted): root keys cannot be "undeleted," but the owner can
  always create a fresh one from the console if ever truly needed. The point of
  the exercise is that routine automation never uses it again.

---

## Plan B — reuse `wecare-admin` (faster, slightly less clean)

Skip Step 1; put the existing `wecare-admin` key into `[wecare-prod]`, then run
Steps 3–5. Downside: mixes "interactive admin" and "automation" into one
identity, so a future rotation or scoping touches both. Fine as a stopgap; Plan A
is tidier.

---

## Plan C — least privilege (follow-up, separate reviewed change)

`AdministratorAccess` on the automation user is still broad. Once Plan A is
stable, replace it with a scoped customer-managed policy built from what the
tooling actually calls — the audit scripts need read-only across
Lambda/DynamoDB/IAM/SecretsManager/CloudWatch/Lightsail/CostExplorer, and the
`provision_*` / `remediate_*` scripts need specific write actions on named
resources. Derive the action set from CloudTrail for `wecare-automation` over a
week, then write the policy and detach `AdministratorAccess`. Track as its own
task with its own approval.

Even better long-term: no long-lived user key at all — assume a role via
short-lived STS credentials (SSO or `AssumeRole`), so there is no standing secret
to leak. That is a larger change and can follow Plan C.

---

## Verification checklist (owner signs off)

- [x] `wecare-prod` → `get-caller-identity` shows the Identity Center role (Plan S) or an
      IAM user (Plan A/B), not `:root`. (2026-10-25, Plan S)
- [x] All three read-only audit scripts pass under `AWS_PROFILE=wecare-prod`. (2026-10-25;
      provider-independence matches its root run, including the existing `lambda-env` FAIL)
- [x] One write-path script resolves (dry-run) under the new principal. (2026-10-25:
      `remediate_commerce_keys_iam.py` plan mode COMPLIANT; a real Lambda publish also ran)
- [ ] Root key soaked ≥24h **inactive** with no CloudTrail `AccessDenied`.
- [ ] `AccountAccessKeysPresent = 0`.
- [ ] Root login still has MFA (`AccountMFAEnabled = 1`).
- [ ] (Plan C) automation policy scoped; `AdministratorAccess` detached.

## Credential hygiene (applies throughout)

Never print, paste, commit, or log a secret access key. Store it only in
`~/.aws/credentials` (or via `aws configure`). This repo's secret-safety rules
and `docs/SECURITY_AND_SECRETS.md` apply.
