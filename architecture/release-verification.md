# Release verification and rollback evidence

## Frontend

1. Require the **Verify (typecheck, lint, test)** GitHub Actions check for PRs to
   `wecare.digital`; restrict bypasses and direct production branch writes.
   This is a repository ruleset setting. The workflow file alone does not set it.
2. The production Amplify build now checks the exact `AWS_COMMIT_ID` for a
   successful `push` run of `.github/workflows/ci.yml` on `wecare.digital`.
   A green pull-request or third-party check is not accepted instead. The check
   waits for the final CI job up to five minutes and blocks if it cannot obtain
   authoritative success. Retry the build after a temporary API or quota issue
   is resolved; do not disable the gate to ship around a failing Verify run.
   The public read works without credentials. If shared egress quota is a
   problem, configure `WECARE_GITHUB_ACTIONS_READ_TOKEN` as a private environment
   value with Actions read permission for this repo only; never use a
   `NEXT_PUBLIC_*` variable or place the token in the repository.
3. Both GitHub and Amplify run `python scripts/check_release_contracts.py`.
   Amplify still owns the static-export, credential and other environment-specific
   checks. Independently confirming the active Amplify revision and backend aliases
   is necessary; a green GitHub job is not deployment evidence.

## Script-deployed Lambda fleet

1. Review the intended function list and create a clean detached worktree of the
   successful production commit. Run `scripts/deploy_all_lambdas.py --dry-run`
   on the exact targets before requesting authorization for any production use.
2. The canonical apply command verifies production CI **before** changing even
   `$LATEST` (some functions do not use an alias). It preserves existing code
   hash and alias revision checks. A failed multi-function release can still be
   partially staged or promoted: read the receipt and re-check individual targets.
3. Keep the mode-0600 JSONL file in `.scratch/release-receipts/` privately. It
   records the Git commit and Verify run/attempt/job; staged package hashes; and
   for each alias moved, the verified version and code hash plus the previous
   alias version and hash. The previous alias version is the rollback candidate,
   not permission to roll back. Confirm the current alias revision and health
   before a separately authorized rollback. For functions serving `$LATEST`,
   use the last reviewed package and verify the resulting deployed code hash.
4. The canonical gate does not automatically wrap independent provisioning,
   emergency rollback, delegated deployment, or CloudFormation publish commands.
   Owners of those paths must require the same evidence before production use.
   Do not try to move script-owned resources into Amplify as a shortcut.

No customer data, cloud credentials, or provider tokens belong in release receipts.
