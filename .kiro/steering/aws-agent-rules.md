---
inclusion: always
---

# AWS account and authentication policy (project rules)

These are this project's own rules. Per the AWS Agent Toolkit rules below, where
the two conflict, **these take precedence**.

## Use exactly one account

**Account `775261844268` is the only account to use** — for production, for
builds, and for everything else, unless explicitly told otherwise.

    profile:  wecare-prod
    identity: arn:aws:iam::775261844268:user/wecare-admin   (preferred)
              arn:aws:iam::775261844268:root                (owner-authorized project use)
    region:   us-east-1

`AWS_PROFILE=wecare-prod` is exported from `~/.zprofile`, so login shells,
interactive shells, scripts and boto3 all resolve it without any per-command
flag. Verify with `aws sts get-caller-identity` — it must report
`775261844268`.

Owner override, 2026-10-09: "we will use root for the project now". The existing root connection in account `775261844268` is authorized for reviewed project operations. Root identity alone is not a deployment blocker. Keep exact account/resource guards, scoped changes, captured rollback versions and post-change verification. This grants no credential-value access, payment/provider changes, live-send enabling, destructive blanket cleanup or removal of guards. Do not create, replace or rotate root keys.

A second profile exists, `wecare-selfcare` (account `010526260063`). **Do not use
it** unless a task explicitly names that account.

## Authenticate with the long-term key, never the browser

Auth must be **permanent and non-interactive**. Do not use browser-based login.

- ✅ `AWS_PROFILE=wecare-prod` reading the long-term access key from
  `~/.aws/credentials`. Never expires, no browser, works in CI-style
  non-interactive shells.
- ❌ `aws login` / `aws sso login`. `[default]` in `~/.aws/config` is bound to a
  browser `login_session` that expires roughly every 12 hours and then blocks
  every AWS call. That is what `AWS_PROFILE` deliberately overrides.

If a documented setup procedure instructs a browser login (the AWS Agent Toolkit
setup does, at its Step 3), **skip that step** and verify the existing key-based
profile instead.

Corollary: because a static key on disk grants this account indefinitely,
`~/.aws/credentials` must stay mode `600`, must never be committed, must never be
copied into iCloud or a backup destination, and must never appear on a command
line.

## Do not put developer AWS auth into Secrets Manager

Reading a secret from Secrets Manager requires AWS credentials, so storing the
developer's own AWS credentials there is circular and cannot bootstrap. Keep
application secrets in Secrets Manager; keep human/developer AWS auth in
`~/.aws/credentials` or a role/SSO session.

<!-- BEGIN AWS Agent Toolkit rules -->

# AWS Guidance

- Where these AWS rules conflict with the project's own instructions, the
  project's instructions take precedence.
- Prefer the AWS MCP Server for AWS interactions — it provides sandboxed
  execution, observability, and audit logging. If unavailable, use the
  AWS CLI directly.
- Before starting a task, check whether a relevant AWS skill is available.
  Load the skill with `retrieve_skill` and prefer its guidance over
  general knowledge.
- When uncertain about specific AWS details (API parameters, permissions,
  limits, error codes), verify against documentation rather than guessing.
  State uncertainty explicitly if you cannot confirm.
- When creating infrastructure, prefer infrastructure-as-code (AWS CDK or
  CloudFormation) over direct CLI commands.
- When working with infrastructure, follow AWS Well-Architected Framework
  principles.
- Do not use em dashes in AWS resource names or descriptions. Use
  hyphens instead.

## Secret Safety

- MUST load the `aws-secrets-manager` skill first for any secret,
  credential, API key, token, or password task. MUST NOT call
  `secretsmanager get-secret-value` or `batch-get-secret-value`, and MUST
  NOT hit the Secrets Manager Agent daemon directly. MUST use
  `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` with
  `asm-exec` so the secret resolves at runtime without entering context.

<!-- END AWS Agent Toolkit rules -->


## `UpdateUserPool` is a full replace, not a patch

Learned the hard way on 2026-09-28. This command looks like it changes one setting:

    aws cognito-idp update-user-pool --user-pool-id us-east-1_46ULYuukt \
        --deletion-protection ACTIVE

It returned 200, set deletion protection, and **silently reset every field it was not
given**. On the customer pool that meant:

| Field | Before | After |
|---|---|---|
| `LambdaConfig.DefineAuthChallenge` | `wecare-customer-whatsapp-auth:live` | *gone* |
| `LambdaConfig.CreateAuthChallenge` | `wecare-customer-whatsapp-auth:live` | *gone* |
| `LambdaConfig.VerifyAuthChallengeResponse` | `wecare-customer-whatsapp-auth:live` | *gone* |
| `AdminCreateUserConfig.AllowAdminCreateUserOnly` | `true` | **`false`** |

The first three break customer WhatsApp OTP sign-in outright — the pool is phone-keyed
`CUSTOM_AUTH`, and with no triggers there is no challenge to issue. The fourth is worse:
it **opened self-signup** on an internet-facing pool that WAF fronts precisely because it
is public. Neither produced an error, a warning, or a non-zero exit.

**Never call `update-user-pool` with a partial argument set.** Use:

    python scripts/cognito_pool_safe_update.py --pool-id <id> --set Field=Value --apply

It reads the live pool, applies only the named change, writes the whole configuration
back, and prints any field that moved when it should not have. `--show` lists the
writable fields; a dry run is the default.

Two details that matter if you ever write this by hand instead:

- `DescribeUserPool` returns read-only fields (`Id`, `Arn`, `CreationDate`,
  `SchemaAttributes`, `Domain`, `Status`, `EstimatedNumberOfUsers`) that `UpdateUserPool`
  rejects. Echoing the response back verbatim fails.
- `AdminCreateUserConfig.UnusedAccountValidityDays` is deprecated and derived from
  `Policies.PasswordPolicy.TemporaryPasswordValidityDays`. Sending both is a conflict.

Recovery, if it happens again: the previous values are in CloudTrail's 90-day history.
`lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=UpdateUserPool`
and read `requestParameters` of the last call that set the field — that is how the three
trigger ARNs above were recovered. A Lambda's resource policy is unaffected, so
`AllowCustomerCognitoInvoke` survives and only the pool side needs restoring.

The same replace-not-patch shape applies to `amplify update-app` (omitted fields are
left alone there, but `--repository` additionally demands a token) and to
`cloudfront update-distribution`, which requires the **entire** `DistributionConfig`
plus a matching `ETag`. Treat "update" in an AWS API as "replace" until proven otherwise.
