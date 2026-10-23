---
inclusion: always
---

# Project layout and commands

## Where the code lives

The Kiro workspace folder **is** the git root:
`/Users/wecaredigital/aws/wecare-digital`. All source lives here directly —
`package.json`, `pytest.ini`, `conftest.py`, `src/`, `amplify/`, `tests/`,
`scripts/`, `config/` — alongside `.kiro/`, `.omni/` and `tools/`.

Run every build, test, lint, and git command from
`/Users/wecaredigital/aws/wecare-digital` (the workspace root, which is also the
working directory tools default to).

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
- Python tests: `python -m pytest -q <paths>` (use the repo venv at
  `.venv/bin/python` if present; otherwise a Python 3.12+ interpreter).
  `conftest.py` refuses interpreters below 3.12. Scope to the touched tests.
- Backend compile check: `python -m compileall -q <changed dirs>`.

## Known pre-existing failure (not yours)

`tests/test_checkout_handler.py::test_waba2_cannot_prepare_a_native_service_payment_and_leaves_no_claim`
fails on `origin/stack` with `unknown table 'stack-wecare-digital-ContactsTable'`.
Expect it; do not fix it; do not let it mask a new failure.

## Git

- Current branch: `stack`. Commit locally; never push unless asked.
- Node `>=24` (currently v24.21.0), npm `11.19.0`. Next.js 16, React 19,
  Vitest 5, TypeScript 6.
