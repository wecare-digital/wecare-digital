# Staff API deploy path (template management and AI/settings config)

GitHub Actions CI is retired for this repository. `wecare-whatsapp-template-management` and
`wecare-ai-config-management` are validated explicitly before release and deployed through the
repository's controlled Lambda deployment tooling. The scoped OIDC role below is retained as
historical deployment infrastructure; no workflow is required by the repository.

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

There is no GitHub Actions deployment trigger. Validate the changed handlers, run
`python scripts/deploy_all_lambdas.py --dry-run wecare-whatsapp-template-management wecare-ai-config-management`,
review the package/config delta, then use the documented production-release mode. Verify the
published versions and `live` aliases after deployment. Do not introduce a repository secret or
long-lived AWS key to replace the retired workflow.

## 3. Verify

- `aws lambda get-function-configuration --function-name <fn> --qualifier live --query CodeSha256`
  equals `aws_code_sha256` in the run's `manifest.json` artifact.
- Probe the Viewer floor without a token: `PUT https://wecare.digital/api/ai/config` must return
  401. Role checks (Operator for settings writes, Admin for template writes) are covered by
  `tests/test_staff_api_authorization.py`. The staff pool has one user, an Admin, so no current
  workflow loses access.
