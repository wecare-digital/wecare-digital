# Dependency upgrades and install boundaries

Current procedure, 2026-10-09. The root manifest owns the web application; amplify/package.json owns backend build tooling. Registry versions and advisories must be refreshed when doing an upgrade. Historical version tables are not a current release target.

## Review the plan

From the repository root, run `./upgrade-latest.sh --plan` or `node scripts/upgrade-dependencies.mjs`. Both are read-only and show only currently declared registry dependencies, retaining dependency/devDependency categories. Local, workspace and Git dependencies are not silently replaced by registry releases.

## Upgrade the web root

`./upgrade-latest.sh` upgrades the current root dependencies, updates the existing lockfile in place, then runs npm ci, typecheck, production build and frontend tests. It does not create a branch, force an audit downgrade, commit, push or deploy. Run in an isolated checkout or with ownership of both manifests; active sessions share the same index and installed modules.

The manually dispatched deps-upgrade workflow has two modes: lock-only refreshes the existing root lock; full-latest first runs the same manifest-derived helper. Both run strict installation/build gates before committing. Backend packages, retired SDKs and removed vendor packages must not be recreated by hard-coded upgrade lists.

## Upgrade backend tooling separately

Inspect amplify/package.json and its lock, then perform a separately reviewed `npm install --prefix amplify`. Its infrastructure/CDK dependencies do not belong in the web root. Dependency updates alone are not authority for a full infrastructure deployment. Review synthesized resources and captured rollback/configuration before any apply.

## Verify and release

Run npm ci, npm run typecheck, npm run build, npm test and npm audit in the web root. Retain actual advisory results; a tool with no patched upstream version cannot be declared fixed by forcing unrelated major downgrades. Preserve the production export/blog/schema/browser gates. Python work uses requirements-dev.txt and Python3.12; full handler tests remain offline unless an explicitly scoped journey is authorized.

Commit only owned explicit paths on stack. An ordinary forward revert restores manifests/lockfile and removed source without rewriting history or undoing another session's work. A Lambda code change must use its reviewed package/deploy owner, capture live versions, publish an Active version and move the guarded live alias. See [the deployment procedure](operations.md#deploying) and [repository ownership](execution/repository-layout.md).

Runtime or architecture migrations are separate changes requiring compatible dependency layers and exact-package handler tests. Do not infer current Lambda counts or provider availability from a dated upgrade document.
