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

Automated: shared-role S3 least-privilege + catalog image-key migration
-----------------------------------------------------------------------
Two previously-manual items are now automated by
`.github/workflows/least-privilege-and-catalog-migration.yml`, backed by
`scripts/scope_shared_lambda_s3.py` and `scripts/migrate_catalog_image_keys.py`.

A. Shared-role S3 least-privilege (`scope_shared_lambda_s3.py`)
   Narrows the shared `wecare-digital-lambda-role` S3 WRITE surface from the whole bucket
   down to the three roots the fleet actually writes under (`secure/d/public/*`, `o/*`,
   `secure/u/*`), keeps READ broad, and preserves `DenyLegacyMediaWrites` verbatim. The
   prefix set is derived from `lambda_utils.media_paths`, so it cannot drift from the code.
   - CI (push): `--simulate` runs `iam:simulate-custom-policy` for a must-allow / must-deny
     matrix (real WhatsApp/receipts/invoices/cleanup/voice/upload keys) under a read-only
     role; a regression fails the build. Offline unit tests pin the policy shape.
   - Apply (dispatch `scope-apply`, environment `production-iam`): puts the policy with
     `--apply`, which refuses unless the simulation is clean.
   - Requires a dedicated admin role `GitHubActions-wecare-shared-role-scoper` allowed to
     `iam:PutRolePolicy` on `wecare-digital-lambda-role` only. The shared role may not edit
     its own policy, so this role is provisioned out of band by an IAM admin (same boundary
     as every other deploy role here).

B. Catalog image-key migration (`migrate_catalog_image_keys.py`)
   Rewrites legacy `catalogImageKey` values (`secure/public/...`, missing the `d/`) on
   ProductsTable to the canonical `secure/d/public/catalog-deploy/catalog/products/<n>-4096.png`
   by calling the AUTHENTICATED `PATCH /native-catalog/products/{id}` admin API. It does NOT
   write DynamoDB directly and does NOT weaken the auth gate: the STAFF-Admin + MFA control in
   `lambda_utils.middleware.require_auth` is unchanged. There is deliberately NO machine/
   client-credentials path on the staff pool (the middleware pins the one browser app client
   and names an M2M client as a vulnerability), so the one input the automation cannot self-
   mint is the token.
   - Dispatch `catalog-migrate-dry` / `catalog-migrate-apply` (environment
     `production-catalog`). The job reads a staff Admin ACCESS token from the
     `WECARE_STAFF_TOKEN` secret and runs the migrator (dry-run lists the rows + payloads;
     apply performs the PATCHes with optimistic-concurrency retry on 409).
   - The ONLY human step: a staff Admin signs in through the staff app client (MFA satisfied)
     and stores the short-lived access token in the `WECARE_STAFF_TOKEN` environment secret.
     Everything after that is unattended. This is automation OF the operator workflow, not a
     bypass of it.

Why these two apply-paths are not fully unattended
--------------------------------------------------
Both terminal steps cross a control that exists on purpose:
  * `scope-apply` needs `iam:PutRolePolicy` on the shared role - a self-escalation boundary;
    a CI role editing its own (or the fleet's) permissions is exactly what the dedicated,
    admin-provisioned roles prevent.
  * `catalog-migrate-apply` needs a live STAFF Admin + MFA Cognito user token - there is no
    machine credential by design.
So the automation does everything that can be done without weakening a security control, and
stops precisely at the injected-credential boundary rather than drilling through it.

Go-live: opening the Meta catalog release gate
-----------------------------------------------
Once a Meta catalog plan is APPROVED (exact hash) and `META_CATALOG_SYNC_ENABLED=true`, the
only thing keeping "Apply to Meta" locked is `META_CATALOG_SYNC_DRY_RUN=true` on the live
`wecare-meta-catalog-sync` function. This is a deliberate, owner-only, out-of-band switch:
  * nothing in the repo sets it to `false` (and `meta-catalog-runtime-deploy.yml` FAILS the
    deploy if it is not `true`, so the gate cannot be opened by committing config), and
  * it is the final "write to the customer-visible Meta catalogue" control.

Use `scripts/open_meta_release_gate.py` rather than a raw `aws lambda
update-function-configuration`, because the raw call REPLACES the whole env map and would wipe
the function's other variables. The tool MERGES - it reads live env, changes only
`META_CATALOG_SYNC_DRY_RUN`, writes the full map back, waits, and verifies no variable was lost.

    # preview (no write):
    python scripts/open_meta_release_gate.py
    # open the gate (requires AWS creds + the explicit confirmation flag):
    python scripts/open_meta_release_gate.py --apply \
        --i-understand-this-enables-production-catalog-writes
    # re-close afterwards (restore the safe default):
    python scripts/open_meta_release_gate.py --close --apply

BEFORE OPENING, confirm the plan composition is intended - an APPROVED plan with
`retire: N` will REMOVE N live Meta items on Apply (e.g. the 2026-10-23 plan
c2379ec6... is create 28 / retire 21 / foreign 22). The tool only opens the gate; the
exact-plan approval and the Apply click remain separate owner actions, and the whole thing is
reversible until Apply is pressed.
