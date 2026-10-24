---
inclusion: always
---

# Project layout and commands

## Where the code lives

The Kiro workspace folder **is** the git root:
`/Users/wecaredigital/aws/wecare-digital`. All source lives here directly —
`package.json`, `src/`, `amplify/`, `scripts/`, `config/` — alongside `.kiro/`, `.omni/` and `tools/`.

Run every build, lint, validation, and git command from
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
- Backend compile check: `python -m compileall -q <changed dirs>`.

## Git

- Current branch: `wecare.digital`. Commit locally; never push unless asked.
- Node `>=24` (currently v24.21.0), npm `11.19.0`. Next.js 16, React 19,
  TypeScript 6.
