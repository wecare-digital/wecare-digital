# The `public-surface-deploy` roles

Three documents and six commands. They create the two OIDC roles that
`.github/workflows/public-surface-deploy.yml` needs, which are the only thing standing
between it and a working `Run workflow` button.

| Role | Document | Used by |
| --- | --- | --- |
| `GitHubActions-wecare-digital-public-surface` | `iam-public-surface-permissions.json` | the `apply` job, and nothing else |
| `GitHubActions-wecare-digital-public-surface-read` | `iam-public-surface-read-permissions.json` | the `verify` and `confirm` jobs |

Both share one trust document, `iam-public-surface-trust.json` — the difference between them
is entirely in what they may do once assumed, not in who may assume them.

## Why two roles

The first version ran everything on one role that could write, because one job was simpler
than three. The cost is that a read-only check carried `amplify:UpdateApp`,
`lambda:UpdateFunctionCode` and `iam:PassRole` for its whole duration — so a mistake in a
verify path, or anything compromised between checkout and the verify command, held
production write access it never needed.

The split also buys something better than least privilege: `confirm` runs **after** the
apply, on the read role. A deploy that verifies itself with its own write credential is
checking its work with the same hand that did it; confirming on a principal that could not
have produced the result makes the evidence worth something.
`tests/test_github_oidc_trust_policy.py` asserts the read document contains nothing but
`Get` actions, so "read-only" is a property rather than a filename.

## Why a file and not an inline `--policy-document`

A trust policy pasted into a terminal is not reviewable, not diffable, and not something
the next person can check against what is live. Both documents are committed, and
`tests/test_github_oidc_trust_policy.py` asserts the trust file is byte-identical to the
document `scripts/fix_github_oidc_trust.py` enforces — because two copies of one policy is
a thing that drifts, and the drift only shows up as an outage on the next repository
rename.

## Why the subject is a wildcard

Read `scripts/fix_github_oidc_trust.py` before changing the trust document. Short version:
this repository was renamed `bharat-stack` → `wecare-digital` on 2026-09-27 and two deploy
roles went dark for 22 hours with `Not authorized to perform sts:AssumeRoleWithWebIdentity`,
because their trust policies pinned the repository NAME with `StringEquals`. GitHub's
immutable subject format still contains the name segments, and those do not survive a
rename. So the name segments are wildcarded and the two immutable ids are pinned twice —
inside `sub` and again as their own condition keys. The grant is unchanged and strictly
tighter: ids cannot be recycled by a namespace grab, names can.

Pinning the *current* name would be the same bug one rename later. Do not "fix" it.

`aws accessanalyzer validate-policy` will tell you to. It reports
`WILDCARD_USAGE_TOO_PERMISSIVE` on the `sub` condition and asks for six literal characters
before the `*`; there are five, and the only way to add a sixth is to start spelling out
the owner name. The heuristic cannot see that `repository_id` and `repository_owner_id` are
pinned with `StringEquals` right beside the pattern, so the wildcard can only match names
belonging to those two immutable ids. The `MISSING_RESOURCE` error in the same report is
the analyzer applying resource-policy rules to a trust policy, which has no `Resource`
element. The permissions document validates with zero findings.

## The commands

Run from the repository root, with credentials that can write IAM.

```sh
# 0. The OIDC provider should already exist - every other role in the account uses it. Confirm:
aws iam get-open-id-connect-provider \
  --open-id-connect-provider-arn arn:aws:iam::775261844268:oidc-provider/token.actions.githubusercontent.com \
  --query 'ClientIDList' --output text

# Only if that 404s (it should not):
# aws iam create-open-id-connect-provider \
#   --url https://token.actions.githubusercontent.com \
#   --client-id-list sts.amazonaws.com

# 1. The write role.
aws iam create-role \
  --role-name GitHubActions-wecare-digital-public-surface \
  --assume-role-policy-document file://scripts/iam-public-surface-trust.json \
  --description "Write role for public-surface-deploy.yml: Amplify customRules and the wecare-mcp Lambda. Branch stack only."

aws iam put-role-policy \
  --role-name GitHubActions-wecare-digital-public-surface \
  --policy-name PublicSurfaceDeploy \
  --policy-document file://scripts/iam-public-surface-permissions.json

# 2. The read-only role. Same trust document, Get-only permissions.
aws iam create-role \
  --role-name GitHubActions-wecare-digital-public-surface-read \
  --assume-role-policy-document file://scripts/iam-public-surface-trust.json \
  --description "Read-only role for public-surface-deploy.yml's verify and confirm jobs. Branch stack only."

aws iam put-role-policy \
  --role-name GitHubActions-wecare-digital-public-surface-read \
  --policy-name PublicSurfaceRead \
  --policy-document file://scripts/iam-public-surface-read-permissions.json

# 3. Tell the workflow where both roles are.
gh variable set PUBLIC_SURFACE_ROLE_ARN \
  --body arn:aws:iam::775261844268:role/GitHubActions-wecare-digital-public-surface
gh variable set PUBLIC_SURFACE_READ_ROLE_ARN \
  --body arn:aws:iam::775261844268:role/GitHubActions-wecare-digital-public-surface-read

# 4. Read-only first. This changes nothing.
gh workflow run public-surface-deploy.yml -f action=verify -f target=both
```

**Expect that first `verify` to come back RED, and read all three step logs.** Before any
apply, the redirect rules are missing and the deployed MCP catalogue is stale, so two of the
three checks fail — that is the divergence you are about to converge, not a broken workflow.
Each check runs to completion and the job fails at the end, so the run tells you about all
three rather than only the first; the job used to stop at the first failure, which meant the
MCP catalogue check never ran on precisely the run you most wanted it on.

Then, once `verify` has told you what it finds:

```sh
gh workflow run public-surface-deploy.yml -f action=apply -f target=both
```

## If the role already exists

`create-role` fails with `EntityAlreadyExists`. Update in place instead — and prefer the
script, which snapshots the old document to `docs/execution/snapshots/` before writing:

```sh
python scripts/fix_github_oidc_trust.py --status
python scripts/fix_github_oidc_trust.py --apply
```

`fix_github_oidc_trust.py` lists both roles, so `--status` reports them as absent until the
`create-role` steps have run and `--apply` skips them. That is deliberate: a role created
later and never registered there is one that keeps whatever document its creator pasted.

An earlier version of this line called the write role "the only one that can write to
production". That is not true and it was worth checking rather than repeating:
`GitHubActions-bharat-stack-docs-scraper` holds `lambda:UpdateFunctionCode`,
`lambda:CreateFunction`, `ecr:PutImage` and `events:Put*`, and
`GitHubActions-bharat-stack-seo-tools` holds `lambda:UpdateFunctionCode`. Three of the six
roles write to production; this one is simply the newest. What is true, and is the reason for the split
above, is that it is the only role in the account whose *read-only counterpart* exists, so
its safe mode needs no write grant at all.

Being listed is no longer taken on trust. `--status` also compares its list against every
live `GitHubActions-*` role and exits non-zero on one it does not manage, because the list
is a literal and a literal cannot notice a role someone else creates — which is not
theoretical: `GitHubActions-wecare-digital-plivo-drift` was created on 2026-09-28 and sat
unregistered for a day while a test asserted the list was complete.

## Checking it worked

```sh
for role in GitHubActions-wecare-digital-public-surface \
            GitHubActions-wecare-digital-public-surface-read; do
  echo "== $role"
  aws iam get-role --role-name "$role" --query 'Role.AssumeRolePolicyDocument'
  aws iam list-role-policies --role-name "$role" --query 'PolicyNames'
done
gh variable list
```

## Rollback

```sh
aws iam delete-role-policy \
  --role-name GitHubActions-wecare-digital-public-surface --policy-name PublicSurfaceDeploy
aws iam delete-role --role-name GitHubActions-wecare-digital-public-surface
aws iam delete-role-policy \
  --role-name GitHubActions-wecare-digital-public-surface-read --policy-name PublicSurfaceRead
aws iam delete-role --role-name GitHubActions-wecare-digital-public-surface-read
gh variable delete PUBLIC_SURFACE_ROLE_ARN
gh variable delete PUBLIC_SURFACE_READ_ROLE_ARN
```

Deleting the variables alone is enough to disable the workflow: each job fails at its
"Check the … role variable is set" step with a message pointing back at this file.

## Where each permission comes from

Every action below is a call one of the two scripts actually makes. Nothing is
speculative, and nothing is `"Resource": "*"`.

| Action | Called by | Why |
| --- | --- | --- |
| `amplify:GetApp`, `amplify:UpdateApp` | both scripts | The `customRules` array holds the 301s and the `/mcp` rewrite. Both scripts write this same list, which is why the workflow runs them sequentially. |
| `lambda:GetFunction`, `GetFunctionConfiguration` | `deploy_mcp_server.py` | Decide create-vs-update, both waiters, and `--verify` downloading the artifact to compare the deployed catalogue. |
| `lambda:CreateFunction` | `deploy_mcp_server.py` | First deploy only. |
| `lambda:UpdateFunctionCode`, `UpdateFunctionConfiguration` | `deploy_mcp_server.py` | Every later deploy. |
| `lambda:PublishVersion`, `CreateAlias`, `UpdateAlias` | `deploy_mcp_server.py` | The API integration points at the `live` alias, so publishing is not optional. |
| `lambda:AddPermission` | `deploy_mcp_server.py` | Lets API Gateway invoke the alias. Re-running is idempotent because the call is wrapped in `except ResourceConflictException` — **not** because anything reads the policy first. `lambda:GetPolicy` was granted on that mistaken account and has been removed; so has `lambda:GetAlias`, which nothing calls either. |
| `iam:PassRole` on `wecare-digital-lambda-role` | `deploy_mcp_server.py` | `create_function` and `update_function_configuration` pass the execution role. Conditioned to `lambda.amazonaws.com` so it cannot be passed anywhere else. |
| `apigateway:GET` on `/apis/zllr9lrg7j*` | `deploy_mcp_server.py` | `get_integrations`, `get_routes` (paginated), `get_stage`. |
| `apigateway:POST`, `PATCH` on `routes*` and `integrations*` | `deploy_mcp_server.py` | `create_integration`, `create_route`, `update_route`. Narrowed to those two sub-resources so the role cannot `PATCH` the API itself. |
| `apigateway:PATCH` on `stages*` | `deploy_mcp_server.py` | `update_stage`, which is how `ANY /mcp` gets its own throttle instead of spending the stage's shared allowance. |
| `apigateway:DELETE` on `stages/*/routesettings/*` | `deploy_mcp_server.py` | `delete_route_settings`. `UpdateStage` validates the whole merged `RouteSettings` map, so one throttle entry left behind by a deleted route makes the map unwritable by anyone — removing it is the only fix. Scoped to route settings alone: the same wildcard the other statements use would have let this role delete every route and the API. |

The `apigateway:` prefix with HTTP verbs is not a shorthand — it is how API Gateway
authorises its control plane for both REST and HTTP APIs. There is no `apigatewayv2:` IAM
prefix, and a policy naming `apigatewayv2:GetRoutes` is rejected as malformed rather than
being tighter. The header comment in the workflow used to list actions in that spelling,
which is why it now points here instead of restating the list.

`tests/test_public_surface_role_permissions.py` derives this table from the boto3 calls in
the two scripts and asserts the write document grants exactly that, in both directions. It
was written because the table was checked by hand and the hand-check was wrong twice over:
`apigateway:DELETE` was missing, which would have failed an `apply` run with AccessDenied
*after* the live redirect rules had been rewritten — a half-applied deploy — and two lambda
read grants were present for a reason that did not exist.

`aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY` returns zero findings on
both permission documents. It is worth re-running after any edit; it is a read-only call and
it catches a malformed action name that IAM would only reject at `put-role-policy` time.

### The read-only document

`iam-public-surface-read-permissions.json` is what the `verify` and `confirm` jobs get, and
it is three statements:

| Action | Why |
| --- | --- |
| `amplify:GetApp` | Read the current `customRules` to report which retired URLs are wired and which are missing. |
| `lambda:GetFunctionConfiguration` | State, memory and timeout of the `live` alias. |
| `lambda:GetFunction` | **This is the one that is easy to leave out.** The stale-catalogue check downloads the deployed bundle and compares its page list against `config/public-pages.json`. `GetFunctionConfiguration` alone cannot see the code, so without `GetFunction` the check that exists to catch a stale `/orders` entry silently cannot run. |
| `apigateway:GET` | `get_routes` and `get_stage`, for the `/mcp` route and its throttle. |

No `PassRole`, no `POST`, no `PATCH`, no `Update*`. The retired-URL probes in
`provision_legacy_redirects.py --verify` are plain HTTPS requests and need no AWS grant at
all.

The other way to give `verify` no write grant was one role assumed twice, with an
`inline-session-policy` on the safe mode — STS intersects a session policy with the role
policy, so it can only subtract. Two roles won because a session policy is invisible in
`get-role-policy`: the read grant is auditable in IAM as its own document and its own
`sts:AssumeRole` event, rather than living in a workflow file where the audit is "read the
YAML and trust it". The read role also lets `confirm` prove an `apply` worked on a
credential that could not have produced the result, which no session policy on the write
role can do.
