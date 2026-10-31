# WECARE.DIGITAL repository instructions

Follow the current repository policy and manual validation guidance before editing:

- `AGENTS.md`
- `docs/operations/repository-validation.md`

GitHub Actions and the root test suite are retired. Do not recreate them to satisfy
historical references. Keep this file a pointer to the current policies.

Important defaults:
- Match existing code style and architecture; strict TypeScript rules and repo lint/type gates win.
- Treat SEO, permission fallbacks, mobile/device compatibility, and accessible responsive behavior
  as required acceptance criteria when relevant.
- Never paste or commit secrets, API keys, OAuth client secrets, tokens, or credential values.
  Use existing environment/secret-store references only.
- Do not assume a branch name or overwrite concurrent work.
- Run the manual release-scoped checks in `docs/operations/repository-validation.md` before declaring done.
