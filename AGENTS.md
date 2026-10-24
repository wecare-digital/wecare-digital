# Repository instructions

These instructions apply to the entire repository and are the portability layer for
ChatGPT/Codex-style agents, Kiro, and VS Code/GitHub Copilot.

## Canonical policy

Before changing code, read and follow every always-on steering file below. They are the
single source of truth; do not maintain a separate, conflicting copy of their rules here.

- `.kiro/steering/00-autonomy.md`
- `.kiro/steering/10-project.md`
- `.kiro/steering/20-device-compat.md`
- `.kiro/steering/25-public-mobile-foundation.md`
- `.kiro/steering/30-seo.md`
- `.kiro/steering/40-permissions.md`
- `.kiro/steering/50-coding-style.md`

If a future nested `AGENTS.md` exists, its more specific instructions apply within that
subtree. Otherwise the steering files above govern repository work.

## Working rules

- Match the surrounding file and existing architecture before introducing a new pattern.
- Do not assume a branch name. Inspect the current/default branch and preserve concurrent work.
- Run the verification gates required by `.kiro/steering/10-project.md` for the files changed.
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
