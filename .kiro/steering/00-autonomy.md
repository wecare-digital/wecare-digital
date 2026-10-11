---
inclusion: always
---

# Unattended Autopilot

This workspace runs fully unattended in Autopilot. Work end to end without
pausing for confirmation. Do not ask the user to approve routine steps, do not
stop to report progress mid-task, and do not wait for a go-ahead between items in
a plan. Make the most reasonable decision, act, and keep going until the task is
complete.

## Do not prompt for

- Running shell commands (git, python, pytest, npm, npx, node, aws, gh, and the
  project scripts). All of these are trusted. Run them directly.
- Editing, creating, moving, or deleting files inside this workspace.
- Installing dependencies the task needs, running builds, or running tests.
- Committing finished work (see "Auto commit" below).
- Updating settings, steering, hooks, or other `.kiro/` configuration when the
  task calls for it. Treat `.kiro/` edits as always allowed — never ask first.

Only pause for the genuinely high-risk, hard-to-reverse actions the safety rules
still require: pushing to a shared remote, deleting data outside the workspace,
production deploys, or dropping databases. Everything local and reversible:
just do it.

## No worktree workflow

Work directly in the main checkout at `/Users/wecaredigital/wecare-digital`
(the git root, and where `package.json`, `pytest.ini`, `.venv`, `src/`,
`amplify/`, `tests/` and `scripts/` live). Do not create git worktrees, do not
operate out of `.worktrees/`, and do not use `git -C <worktree>` indirection.
Branch in place when a branch is needed; edit the real files in the main tree.

## No coder + reviewer workflow

There is no separate reviewer agent and no review-loop handoff. Do not generate
`.agents/tasks/*/review.{json,md}`, `verification.md`, `plan.md`, or FEAT
artifacts as a precondition for doing the work. One agent plans briefly in its
head (or in a short chat outline for larger tasks) and implements. Skip the
coder→reviewer→owner-decision ceremony entirely.

## No full-suite gate

Do not run the heavy "full verification gate" (whole `python -m pytest -q`
suite, full `npx vitest run`, full build matrix, header/secret/census scripts)
as a blanket end-of-task gate. Instead verify narrowly and fast:

- Run only the tests that cover the files you touched.
- Type-check or lint only the changed area when it is quick to scope.
- Rely on the build-status check below for the broad signal.

If a change is genuinely broad (touches shared libs, routing, or config that
many modules read), widen the test selection to the affected area — but still
scope to what the change can reach rather than running everything.

## Auto commit and check build status

When a unit of work is complete and its narrow verification passes, commit it
automatically — do not ask. Then check build status rather than running the full
suite.

- Stage the specific files you changed (not `git add -A`). Flag, and do not
  commit, anything that looks like a secret (`.env*`, credentials, tokens).
- Write a concise conventional-style message describing the change.
- Commit locally. Do not push unless the user explicitly asks.
- After committing, check the build: run the project build (`npm run build`) or,
  for backend-only changes, a fast compile check
  (`python -m compileall -q <changed dirs>`). Report whether the build is green.
- If the build breaks, fix it and amend/commit again before moving on. A broken
  build is never left behind.
