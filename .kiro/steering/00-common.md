---
inclusion: always
---

# WECARE.DIGITAL common repository settings

This is the single always-on steering file for Kiro and the canonical policy source for
ChatGPT/Codex-style agents and VS Code/GitHub Copilot. Do not create parallel steering files
for these rules; update this file instead.

## Autonomy and workspace

Work end to end without pausing for routine local, reversible actions. Make the most reasonable
interpretation of broad requests and carry them through to completion. Only stop for genuinely
high-risk, hard-to-reverse actions that require explicit authorization, such as pushing to a
shared remote, deleting data outside the workspace, production deploys, or dropping databases.

Work directly in the repository root. Do not create git worktrees unless the owner explicitly
asks for one. Preserve concurrent edits and stage only the exact files you changed.

Do not recreate retired reviewer-agent ceremonies or retired test-suite automation. Validate
with the production build, TypeScript checks, targeted compile checks, and purpose-built
verification scripts that still exist.

## Project layout and verification

The repository root contains `package.json`, `src/`, `amplify/`, `scripts/`, `config/`,
`.kiro/`, and `tools/`.

Verified commands:
- Build: `npm run build` — the real static-export gate. It runs public-page generation,
  vendor CSS generation, Next build, sitemap, blog index/RSS, and llms generators.
- Type-check: `npx tsc --noEmit` or `npm run typecheck`. Run after build when generated
  Next types are needed.
- Lint: `npx eslint .` or `npm run lint`. Existing warnings may remain; errors are the gate.
- Backend compile check: `python -m compileall -q <changed dirs>`.

Use the repository's actual current/default branch rather than assuming a branch name.
Node must satisfy `package.json` engines.

When a unit of work is complete and validation passes, commit locally by explicit path with a
concise conventional-style message. Never use broad staging that can capture another session's
work. Never push unless explicitly asked.

## Coding style

Write code that matches what the repository already does. The linter and type checker are the
gate, but surrounding-file consistency wins for conventions they do not catch.

### TypeScript / React
- Strict TypeScript: do not add `any`, `@ts-ignore`, or `@ts-expect-error` to force a change
  through. Fix the type. If a cast is genuinely unavoidable, narrow it and explain why.
- Prefer named exports for shared modules. Keep framework-required or already-established default
  exports where appropriate.
- Use the `@/*` alias for cross-area imports and relative imports within the same folder.
- Do not use native `alert`, `confirm`, or `prompt`. Use the repository toast/confirm/prompt
  contexts.
- Keep auth loss, timeout, real empty results, and other distinct failure states distinguishable.
  Do not silently collapse errors into `null` or `[]`.
- React Compiler is not enabled. Keep promoted react-hooks rules at zero errors; do not introduce
  render-time `Date.now()`/`Math.random()`, components defined during render, or temporal-dead-zone
  effect dependencies.
- Prefer `async`/`await` over new `.then()` chains.

### Python / Amplify
- Python 3.12+ only. Use modern typing and type-hint public function signatures.
- Module and handler docstrings must explain purpose and authority.
- Apply least privilege to handlers. Do not add write/send/delete/scan capability a handler does
  not need.
- Delete dead capabilities rather than hiding them behind disabled branches.
- Avoid unbounded DynamoDB pagination loops or exhaustive scans when a bounded/query approach exists.

### General
- Comment the non-obvious "why", not obvious mechanics.
- Match the file's existing formatting; do not reformat unrelated lines.
- Never put secrets or PII in code, logs, comments, examples, commits, PRs, or error output.
  Reference secrets only by environment variable or secret-store key name.

## Permissions, privacy, and consent

Request the least access needed at the moment it is needed, and never block the core experience
because a permission was declined or unavailable.

- Request only capabilities a feature actually uses.
- Ask just in time from a clear user action and explain why before the native prompt.
- Provide denied and unsupported fallbacks; never crash or leave a dead end.
- Make permission state transparent and explain how users can change it later.
- Feature-detect browser APIs such as geolocation, notifications, camera/mic, clipboard, storage
  persistence, and push. Assume APIs may be absent in WebViews.
- Respect secure-context and user-gesture requirements.
- Do not re-prompt users in a loop after denial.
- Detect in-app-browser/WebView limitations and fall back.
- On iOS/Android, declare only genuine permissions, use truthful usage descriptions, handle all
  authorization states, and bridge WebView permission requests correctly.

Verification for permission-sensitive work:
- Test granted, denied, and unsupported states.
- Confirm no permission prompt occurs on page load without a user action.
- Confirm WebView/in-app-browser fallback behavior.

## Universal device and browser compatibility

Every public page must remain usable across phone, tablet, foldable, desktop, large desktop,
iOS/iPadOS, Android, macOS, Windows, Linux, Safari, Chrome, Firefox, Edge, Samsung Internet,
native WebViews, and common in-app browsers. Support current and previous major browser versions.

- Design mobile-first with fluid flex/grid layouts and responsive units; no horizontal scroll at
  320px and above.
- Respect safe areas/notches with `env(safe-area-inset-*)` and `viewport-fit=cover`.
- Handle foldable hinges/viewport segments where available and degrade gracefully elsewhere.
- Prefer `dvh`/`svh`/`lvh` over bare `vh` where mobile chrome can clip content.
- Tap targets must be at least 44x44px and work with touch, mouse, pen, and keyboard.
- Honor reduced motion and user zoom/font scaling up to 200%.
- Public WECARE.DIGITAL is intentionally light-only. Declare `color-scheme: light` and do not
  introduce dark mode unless the owner changes that product decision.
- Feature-detect bleeding-edge APIs/CSS and provide fallbacks.
- Avoid critical flows that depend on popups/new tabs unavailable in WebViews.
- Make images/media responsive and use supported formats/fallbacks.
- Keep the viewport meta value `width=device-width, initial-scale=1, viewport-fit=cover`.

Verification for layout/global-CSS work:
- Build successfully.
- Check representative widths around 320, 375, 768, 1024, and 1440 in portrait/landscape.
- Verify at least one WebView/in-app-browser context.
- For foldable work, test folded/unfolded portrait/landscape; a width-only emulator is not proof
  of real hinge behavior.

## Public mobile foundation

Home is the locked reference implementation for the public mobile/app experience. Do not redesign
each route independently or apply blanket selectors that silently restyle unaudited routes.

Migrated page families use these canonical tokens from `src/styles/tokens.css`:
- `--public-mobile-hero-size: 40px`
- `--public-mobile-section-size: 32px`
- `--public-mobile-card-size: 24px`
- `--public-mobile-cta-font-size: 18px`
- `--public-mobile-page-gutter: 16px`
- `--public-mobile-section-gap: 64px`
- `--public-mobile-hero-top: 48px`
- `--public-mobile-form-font-size: 16px`

Do not duplicate values already canonical globally: `--public-body-size: 20px`,
`--tap-min: 44px`, safe-area `--safe-*` tokens, the light-only color scheme, or the
`100vh` + `100dvh` viewport fallback.

Adopt the contract family-by-family. Home, Grahak OS, VayuLok, the public blog listing/post reader,
Terms/Privacy, and shared service/product pages are explicit adopters. Customer forms and
shop/product pages remain family-by-family work; do not infer migration from a shared component
alone. Preserve product-specific visual identity while unifying typography roles, gutters, spacing,
touch targets, safe areas, containment, reflow, WebView behavior, and shared public chrome.

For migrated families, check 320/360/375/390/412/430 phones, tablets, desktop, folded/unfolded and
wide-short foldable postures, 200% reflow, Chromium/Firefox/WebKit, and Capacitor public-shell sync.
Physical-hinge and installed-WKWebView checks remain release-device gates when CI cannot reproduce them.

## SEO, metadata, crawlability, and structured data

SEO is a hard requirement for indexable public pages, but follow current Google Search guidance
rather than obsolete markup or ranking folklore.

### Discovery and indexing
- Keep public pages crawlable, internally linked, and indexable unless there is an intentional
  reason to use `noindex`.
- Maintain a valid `robots.txt` and a current canonical-only `sitemap.xml`.
- Sitemap `lastmod` must reflect a real content modification time or be omitted. Do not fabricate
  dates. Google ignores sitemap `priority` and `changefreq`; do not add them.
- Use Search Console/URL Inspection for crawl/index diagnostics. A sitemap helps discovery but does
  not guarantee crawling or indexing.

### Per-page metadata
- Use a unique, accurate, concise title and a useful unique meta description.
- Emit a self-referencing canonical for indexable pages.
- Set `html lang` and use `hreflang` only where real alternate locales exist.
- Provide accurate Open Graph and Twitter metadata with real absolute image URLs and suitable
  preview dimensions.
- Keep favicon/app-icon/webmanifest/theme-color assets complete and valid.

Do not add the obsolete `meta keywords` tag for SEO; Google Search does not use it.

### Structured data
- Emit only valid schema.org markup that describes content actually visible on the page.
- Keep a single consistent site-level `Organization` and `WebSite` entity graph.
- Do **not** add `SearchAction` merely for the retired sitelinks search box. Google removed that
  feature on 2024-11-21.
- Do not emit public `BreadcrumbList` unless the page actually renders the corresponding visible
  breadcrumb trail.
- Use appropriate page markup such as `Product` + `Offer`, `Article`/`BlogPosting`,
  `SoftwareApplication`, or other supported types when the page content genuinely qualifies.
- `FAQPage` may still be valid schema.org for machine-readable semantics when it exactly mirrors
  visible FAQ content, but do not treat it as a Google FAQ rich-result requirement; Google removed
  FAQ rich-result support in 2026.
- Validate structured data before shipping. Never invent reviews, ratings, prices, availability,
  founding dates, business hours, or other factual claims to satisfy a validator.

### Content and page quality
- Create useful, unique, people-first content with real expertise or first-hand value.
- Organize content clearly with sensible headings and semantic landmarks.
- Use descriptive URLs, alt text, and anchor text.
- Keep internal links useful for discovery and user navigation.
- Optimize images/video when relevant and keep Core Web Vitals healthy.
- Avoid keyword stuffing, scaled commodity content, or pages created only to manipulate search/AI
  results.
- Google generative Search features still depend on core Search indexing/ranking systems; do not
  create special "AI SEO" markup. `llms.txt` may be maintained for other systems, but Google says
  it neither helps nor hurts Google Search visibility.

SEO verification before done:
- `npm run build` succeeds and sitemap/blog-index/RSS/llms generators complete.
- Indexable pages have correct title, description, canonical, robots behavior, social tags, and
  appropriate JSON-LD.
- Sitemap contains only canonical public URLs and truthful/omitted `lastmod`.
- No accidental `noindex` or robots block exists on pages intended to rank.
- Structured data matches the rendered page and passes the relevant validators.

## Account identifiers and secrets

Account IDs, property IDs, measurement IDs, container IDs, project IDs, merchant IDs, location
resource names, and similar public/non-secret identifiers may be kept only in the repository's
existing canonical configuration locations when verified.

Credentials are different: API keys, OAuth client secrets, developer tokens, service-account key
material, signing secrets, refresh tokens, passwords, and similar values must never be committed or
copied into examples. Fetch them only through already-approved secret references/identity flows.
