# WECARE.DIGITAL repository instructions

Use the repository's Kiro steering files as the canonical engineering policy for every
Copilot/VS Code coding task. Read all of these before editing:

- `.kiro/steering/00-autonomy.md`
- `.kiro/steering/10-project.md`
- `.kiro/steering/20-device-compat.md`
- `.kiro/steering/25-public-mobile-foundation.md`
- `.kiro/steering/30-seo.md`
- `.kiro/steering/40-permissions.md`
- `.kiro/steering/50-coding-style.md`

Also follow the repo-wide `AGENTS.md`. Keep these files as pointers to the canonical
steering rules rather than duplicating policy text that can drift.

Important defaults:
- Match existing code style and architecture; strict TypeScript rules and repo lint/type gates win.
- Treat SEO, permission fallbacks, mobile/device compatibility, and accessible responsive behavior
  as required acceptance criteria when relevant.
- Never paste or commit secrets, API keys, OAuth client secrets, tokens, or credential values.
  Use existing environment/secret-store references only.
- Do not assume a branch name or overwrite concurrent work.
- Run the verification commands required by `.kiro/steering/10-project.md` before declaring done.
