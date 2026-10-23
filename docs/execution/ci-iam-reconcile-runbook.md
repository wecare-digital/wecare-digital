# CI deploy-role IAM reconcile runbook

Why this exists
---------------
The GitHub Actions deploy workflows assume dedicated, exact-scope IAM roles. Each role's
PERMISSION policy is written by a committed `scripts/provision_ci_*role*.py` script, but
**nothing deploys those scripts automatically** — a CI deploy role is deliberately NOT
allowed to rewrite its own permissions (that would be privilege escalation). So when a
workflow gains a new step that needs a permission the role does not yet hold, CI fails with
`AccessDenied` until a human with IAM admin runs the provisioner with `--apply`.

This happened on 2026-10-23: `storage-layout-runtime-deploy.yml` gained a
`provision_catalog_media.py` step whose first call is `iam:GetRole` on
`wecare-catalog-media-role`. The committed grant was added to
`provision_ci_runtime_deploy_role.py` (PR #1374), but the live role was unchanged until an
admin ran `--apply`. The step now also has a preflight (PR #1378) that fails with the exact
remediation command instead of a raw botocore traceback.

The reconcile procedure
-----------------------
When a `*-deploy.yml` workflow step fails with
`AccessDenied ... iam:<Action> on resource ... GitHubActions-*` (or the storage-layout
preflight prints its remediation), an operator with IAM admin runs, once:

    python scripts/provision_ci_runtime_deploy_role.py --apply
    python scripts/provision_ci_runtime_deploy_role.py --verify

`--apply` reconciles the live role to the committed policy document; `--verify` asserts
live == committed and exits non-zero on any difference. Then re-run the failed workflow.

Rules the provisioners enforce (do not work around):
- The committed `POLICIES` in each script are the source of truth. Widen the policy by
  editing the script and opening a PR; never hand-edit the live role in the console.
- `--verify` refuses if live and committed disagree, so a manual console change will be
  caught as drift.
- No deploy role may `DeleteFunction`, and function-deploy write statements never use a
  `"*"` resource. `provision_ci_runtime_deploy_role.verify()` pins both.

CI deploy roles and who provisions them
---------------------------------------
Keep this table in step with `.github/workflows/*-deploy.yml` and `scripts/provision_ci_*`.

| Deploy role (assumed by a workflow)            | Committed provisioner                               | Workflows that assume it |
| ---------------------------------------------- | --------------------------------------------------- | ------------------------ |
| `GitHubActions-wecare-runtime-deploy`          | `scripts/provision_ci_runtime_deploy_role.py`       | storage-layout, safe-commerce, outbound-whatsapp-template, meta-catalog |
| `GitHubActions-wecare-checkout-deploy`         | `scripts/provision_ci_checkout_deploy_role.py`      | (checkout deploy) |
| `GitHubActions-wecare-digital-route-auth`      | `scripts/provision_ci_route_auth_role.py`           | (route-auth) |
| `GitHubActions-wecare-digital-plivo-drift`     | `scripts/provision_ci_plivo_drift_role.py`          | (plivo drift) |
| `GitHubActions-wecare-native-catalog-deploy`   | **MISSING — no committed provisioner (see below)**  | native-catalog-admin-deploy |

Open gap: native-catalog-deploy role has no committed provisioner
-----------------------------------------------------------------
`native-catalog-admin-deploy.yml` assumes `GitHubActions-wecare-native-catalog-deploy`, and
that role exists and works live (its deploy run is green). But there is NO
`scripts/provision_ci_*` that writes its trust and permission policy — it lives only in the
account. `scripts/provision_native_catalog_api.py` provisions the function's EXECUTION role
(`wecare-native-catalog-admin-role`), which is a different role.

This is the same drift class PR #1368/#1374 closed for other roles: a role whose grant is
not a committed, reviewable document fails invisibly (console-only) instead of in a diff, and
cannot be rebuilt from the repo if it is deleted or drifts. Recommended follow-up: add
`scripts/provision_ci_native_catalog_deploy_role.py` mirroring the shape of
`provision_ci_runtime_deploy_role.py` (OIDC trust pinned by repo id, branch-scoped to `stack`,
least-privilege to exactly what `provision_native_catalog_api.py` calls), capturing the live
role's current policy as the initial committed state.

What an agent in this repo CANNOT do
-------------------------------------
Agents have no AWS credentials and must not read Secrets Manager values. So an agent can:
- edit a provisioner's committed `POLICIES` and open a PR (the reviewable change), and
- add the actionable preflight / drift guard.

An agent CANNOT run `--apply`/`--verify` (needs IAM admin) — that step is always a human
action, recorded here so it is not rediscovered from first principles each time.
