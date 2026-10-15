---
inclusion: always
---

# Coding style

Write code that matches what this repo already does. The linter and type
checker are the gate (see `10-project.md`); the rules below are the conventions
they do not catch. Follow the surrounding file over any rule here when they
conflict — consistency within a file wins.

## TypeScript / React

- **Strict TS, no escapes.** `strict` is on and `noEmit` is set. Do not add
  `any`, `@ts-ignore`, or `@ts-expect-error` to make a change compile — fix the
  type. If a cast is genuinely unavoidable, narrow it and leave a one-line
  reason.
- **Named exports by default.** Prefer `export const` / `export function` /
  `export class` for shared modules. Reserve `export default` for the places the
  framework requires it (Next.js pages, layouts, route handlers, and
  `*.config` files). Don't convert existing default-exported components for its
  own sake.
- **Import with the `@/*` alias** for cross-area imports (`@/components/...`),
  matching `tsconfig` `paths`. Relative imports are fine within the same folder.
- **No native browser dialogs.** `alert`, `confirm`, and `prompt` are ESLint
  errors. Use `useToastContext()` (`src/contexts/ToastContext.tsx`),
  `useConfirm()` and `usePromptDialog()` (`src/contexts/ConfirmContext.tsx`).
- **Don't collapse distinct failures into one empty value.** Follow the
  structured-failure pattern in `src/api/client.ts`: an auth loss, a timeout,
  and a genuinely empty result must stay distinguishable so the UI can show
  "Sign in", "Retry", or "Nothing here" correctly — not the emptiest of the
  three. Never silently swallow an error into `null`/`[]` without recording it.
- **React Compiler is not enabled.** `set-state-in-effect` is an advisory
  warning here; the five promoted react-hooks rules are errors and must stay at
  zero. Don't introduce render-time `Date.now()`/`Math.random()`, components
  defined during render, or effect deps read in the temporal dead zone.
- Prefer `async`/`await` over `.then()` chains for new code.

## Python (backend / Amplify functions)

- **3.12+ only** (`conftest.py` enforces it). Use modern typing (`str | None`,
  built-in generics) and type-hint public function signatures.
- **Module and handler docstrings** explain *purpose and authority* — what the
  handler may and may not do — as the existing handlers do. Keep them truthful
  and current.
- **Least privilege in handlers.** Don't add send/write/delete/scan capability a
  handler doesn't need. Mirror the governance pattern in
  `amplify/functions/ai/...`.
- **Delete dead code, don't gate it.** Remove a disabled capability rather than
  leaving it behind an `if False`/`try: pass`. Dead code that still works is how
  a removed power comes back.
- Avoid unbounded `while True` on DynamoDB `LastEvaluatedKey`; paginate with a
  bound or a query, not an exhaustive table scan.

## General

- **Comment the non-obvious "why", not the "what".** This repo documents the
  reason a tricky line exists (and what breaks without it) rather than narrating
  obvious code. Match that: a comment should save the next reader an
  investigation.
- **No secrets or PII in code, logs, or error output** (ties into
  `40-permissions.md`). Reference secrets by key name, never value.
- **Match the formatting the file already uses** — indentation, quotes, and
  spacing. Don't reformat untouched lines or run a formatter across a file you're
  making a small change to; that buries the real diff.
