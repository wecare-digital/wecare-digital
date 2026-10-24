# WECARE.DIGITAL repository instructions

Use the repository's common Kiro steering file as the canonical engineering policy for every
Copilot/VS Code coding task. Read all of these before editing:

- `.kiro/steering/00-common.md`

Also follow the repo-wide `AGENTS.md`. Keep this file as a pointer to the canonical
steering policy rather than duplicating text that can drift.

Important defaults:
- Match existing code style and architecture; strict TypeScript rules and repo lint/type gates win.
- Treat SEO, permission fallbacks, mobile/device compatibility, and accessible responsive behavior
  as required acceptance criteria when relevant.
- Never paste or commit secrets, API keys, OAuth client secrets, tokens, or credential values.
  Use existing environment/secret-store references only.
- Do not assume a branch name or overwrite concurrent work.
- Run the verification commands required by `.kiro/steering/10-project.md` before declaring done.
