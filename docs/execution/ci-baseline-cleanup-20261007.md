# CI baseline cleanup - 2026-10-07

Owner instruction: resolve the diagnosed failures and push through a separate branch.
Base: 8db4e595e6eeb3f35ff00131941b318bc9062e6d (merged MCP PR #241).
Branch: codex/ci-baseline-cleanup-20261007. No production mutation or merge is part of this change.

A0_READ: Route auth run 37555699319 passed 76 guarded-handler tests and its live AWS
route audit. Its full suite failed the five pre-existing FAQ/header tests. PR #241
head failed the identical five. Gastronomy runs 37555699265 and 37496460490 failed at
checkout because the gastronomy-quality branch was absent; merge/push never ran.

A1_LOCAL: FAQ CTA validation now accepts an exact declared permanent redirect only
when its destination is in the generated public-page inventory. The withdrawn /shop
catalogue remains withdrawn. The header parser test compares YAML by URL pattern;
header fixtures include pattern-specific cache policy and stub hashed-asset discovery.
A negative regression still fails the gate when an asset lacks Cache-Control.
Production header parsing/enforcement and all authentication checks are unchanged.

Gastronomy sync checks out stack, then checks the remote target with git ls-remote.
Exit 2 means the branch is absent: write a notice/summary and skip sync. Authentication,
transport and other git errors remain failures. If present, fetch and merge as before.
The target is not recreated, and the workflow is not retired without evidence that the
workstream is retired. Three tests exercise its actual preflight shell against local
Git remotes: present, absent and unreachable. No GitHub push occurs in these tests.

Validation: 25 focused tests passed; git diff --check passed. Full Python suite:
8349 passed, 6 skipped, 3 xfailed in 105.74 seconds. All five baseline failures are
resolved; expected skips/xfails remain unchanged. Test tooling uses the Route auth dependency pins;
local AWS credential discovery is isolated, with profile region metadata and no stored
credentials, so tests cannot accidentally select owner credentials.

A2_REMOTE_CODE: owner authorized this feature branch push. Explicit files: the sync
workflow, two repaired test files, workflow preflight test, and this execution record.
Rollback: close the unmerged PR, or revert the cleanup commit after merge. No live
resources, provider settings, security policies or withdrawn pages are changed.
