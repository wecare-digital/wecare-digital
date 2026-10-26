# Staff API deploy path (template management and AI/settings config)

`wecare-whatsapp-template-management` and `wecare-ai-config-management` had no CI deploy path.
Their `live` aliases were last published by the operator script
(`auto-publish by _snapstart_publish.py`). `.github/workflows/staff-api-ci.yml` now tests and
packages both functions on every relevant change. Its deploy job stays **off** until the owner
completes the two steps below. Creating the role is an IAM change, so an agent must not do it.

## 1. Create the scoped OIDC deploy role (owner)

Role name: `wecare-staff-api-deploy-oidc`. Max session 3600 s, no permissions boundary. This
mirrors `wecare-waba-management-deploy-oidc`.

Trust policy (GitHub OIDC, production branch only):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::775261844268:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {"StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub": "repo:wecare-digital@319896805/wecare-digital@1342943014:ref:refs/heads/wecare.digital"
    }}
  }]
}
```

Inline policy `StaffApiLambdaRelease`. It can release these two functions only:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "StaffApiReleaseOnly",
    "Effect": "Allow",
    "Action": ["lambda:GetFunctionConfiguration", "lambda:GetAlias", "lambda:UpdateFunctionCode",
               "lambda:PublishVersion", "lambda:UpdateAlias", "lambda:GetFunction"],
    "Resource": [
      "arn:aws:lambda:us-east-1:775261844268:function:wecare-whatsapp-template-management",
      "arn:aws:lambda:us-east-1:775261844268:function:wecare-whatsapp-template-management:*",
      "arn:aws:lambda:us-east-1:775261844268:function:wecare-ai-config-management",
      "arn:aws:lambda:us-east-1:775261844268:function:wecare-ai-config-management:*"
    ]
  }]
}
```

## 2. Enable the deploy job (owner)

Set the repository variable `STAFF_API_DEPLOY_ENABLED` to `true` (Settings → Secrets and
variables → Actions → Variables). Then run **Staff API CI** with `workflow_dispatch` on
`wecare.digital`, or push a change on its paths.

## 3. Verify

- The deploy job log prints `<fn> live -> v<N> <sha>` for both functions.
- `aws lambda get-function-configuration --function-name <fn> --qualifier live --query CodeSha256`
  equals `aws_code_sha256` in the run's `manifest.json` artifact.
- Probe the Viewer floor without a token: `PUT https://wecare.digital/api/ai/config` must return
  401. Role checks (Operator for settings writes, Admin for template writes) are covered by
  `tests/test_staff_api_authorization.py`. The staff pool has one user, an Admin, so no current
  workflow loses access.
