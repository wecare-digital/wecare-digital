---
inclusion: always
---

# Project layout and commands

## Where the code lives

The Kiro workspace folder (`.../wecare-digital/wecare-digital`) is a thin shell
that holds only `.kiro/`, `.agents/`, `.omni/`, `.vscode/`, `.worktrees/` and
`tools/`. The real repository is its **parent**,
`/Users/wecaredigital/wecare-digital` — that is the git root and where all source
lives: `package.json`, `pytest.ini`, `.venv/`, `src/`, `amplify/`, `tests/`,
`scripts/`, `config/`.

Run every build, test, lint, and git command from
`/Users/wecaredigital/wecare-digital` (pass it as the working directory). A bare
relative path from the Kiro workspace shell lands in the wrong place.

## Verified commands

- Build (the real gate on the static export):
  `npm run build`
  (runs `generate-public-pages.js` → `generate-vendor-css.js` → `next build` →
  sitemap/blog-index/llms generators)
- Type-check: `npx tsc --noEmit` (also `npm run typecheck`). Run **after** a
  build when it needs the generated `next-env.d.ts`.
- Lint: `npx eslint .` (also `npm run lint`). ~190 pre-existing warnings are
  expected; **errors** are the gate.
- Front-end tests: `npx vitest run <files>` (also `npm run test`). Scope to the
  files you touched.
- Python tests: use the repo venv interpreter
  `/Users/wecaredigital/wecare-digital/.venv/bin/python -m pytest -q <paths>`.
  `conftest.py` refuses interpreters below 3.12. Scope to the touched tests.
- Backend compile check: `/Users/wecaredigital/wecare-digital/.venv/bin/python -m compileall -q <changed dirs>`.

## Known pre-existing failure (not yours)

`tests/test_checkout_handler.py::test_waba2_cannot_prepare_a_native_service_payment_and_leaves_no_claim`
fails on `origin/stack` with `unknown table 'stack-wecare-digital-ContactsTable'`.
Expect it; do not fix it; do not let it mask a new failure.

## Git

- Current branch: `stack`. Commit locally; never push unless asked.
- Node `>=24`, npm `11.6.2`. Next.js 16, React 19, Vitest 5, TypeScript 6.
