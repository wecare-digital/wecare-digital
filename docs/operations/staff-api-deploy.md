# Staff API deploy path (template management and AI/settings config)

`wecare-whatsapp-template-management` and `wecare-ai-config-management` now have a complete
CI deploy path. `.github/workflows/staff-api-ci.yml` tests and packages both functions on every
relevant change, and production pushes deploy the exact tested packages through the scoped GitHub
OIDC role `wecare-staff-api-deploy-oidc`.

## 1. Scoped OIDC deploy role

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

The role is provisioned in account `775261844268`, trusts only the production branch OIDC
subject, and can release only the two staff API Lambda functions listed above.

## 2. Deploy behavior

A push to `wecare.digital` on the workflow's watched paths runs test → package → deploy.
Pull requests run test and package only. No repository secret or long-lived AWS key is required.

## 3. Verify

- The deploy job log prints `<fn> live -> v<N> <sha>` for both functions.
- `aws lambda get-function-configuration --function-name <fn> --qualifier live --query CodeSha256`
  equals `aws_code_sha256` in the run's `manifest.json` artifact.
- Probe the Viewer floor without a token: `PUT https://wecare.digital/api/ai/config` must return
  401. Role checks (Operator for settings writes, Admin for template writes) are covered by
  `tests/test_staff_api_authorization.py`. The staff pool has one user, an Admin, so no current
  workflow loses access.
