# Repository instructions

These instructions apply to the entire repository and are the portability layer for
ChatGPT/Codex-style agents, Kiro, and VS Code/GitHub Copilot.

## Canonical policy

Before changing code, follow the current release-scoped validation policy:

- `docs/operations/repository-validation.md`

The former `.kiro/steering/00-common.md` no longer exists in the default branch.
Do not restore retired test suites or GitHub Actions workflows to satisfy historical references.

If a future nested `AGENTS.md` exists, its more specific instructions apply within that
subtree. Otherwise the common steering file above governs repository work.

## Working rules

- Match the surrounding file and existing architecture before introducing a new pattern.
- Do not assume a branch name. Inspect the current/default branch and preserve concurrent work.
- Run the manual, release-scoped checks in `docs/operations/repository-validation.md` for the files changed.
- Treat public SEO, permission handling, device compatibility, and the public mobile foundation
  as acceptance criteria, not optional cleanup.

## Secret safety

Never copy credentials, API keys, OAuth client secrets, developer tokens, signing material,
or other secret values from chat, tickets, documents, logs, or local files into source code,
examples, comments, commits, pull requests, or generated artifacts. Reference secrets by
environment variable or secret-store key name only.

Public/non-secret identifiers such as measurement IDs, property numbers, customer IDs,
container IDs, project IDs, or resource names may be recorded only when the repository
already has an appropriate canonical config location and the value has been verified. Do not
treat an account identifier as proof of API access or authorization.
