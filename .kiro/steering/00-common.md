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

## Non-negotiable safety boundaries

These rules apply regardless of tool surface (Kiro, ChatGPT/Codex, GitHub connector, VS Code/Copilot,
shell, AWS MCP, or another agent):

- Never weaken, disable, delete, bypass, or work around a safety hook, policy gate, permission check,
  authentication check, secret scanner, branch protection, or verification step merely to make a task
  pass. If a gate blocks the intended operation, use the safer path it identifies or report the blocker.
- Never use broad destructive Git operations in a shared checkout: no `git reset --hard`, force checkout,
  tree-wide restore, `git clean -f`, bare `git stash`, force-push, or history rewrite unless the owner
  explicitly requested that exact destructive action and concurrent work is proven safe.
- Never use broad staging such as `git add .`, `git add -A`, `git add -u`, or `git commit -a`.
  Stage explicit paths only.
- Agent/tooling sessions must not retrieve secret plaintext merely to inspect or verify it. Do not run
  `aws secretsmanager get-secret-value`, `batch-get-secret-value`, or equivalent ad-hoc secret reads.
  Verify secret presence/metadata by name and let approved server-side runtime code consume values.
- Never put credential values in shell arguments, environment assignments shown in logs, MCP/tool payloads,
  source, comments, fixtures, screenshots, prompts, issue/PR text, generated artifacts, or chat replies.
- A credential that appears in chat, a ticket, an issue, a PR, a log, or another non-secret surface must
  be treated as exposed. Do not copy or reuse the literal value; reference its secret-store location and
  record rotation/replacement as owner action where applicable.
- Production deploys, provider-account writes, IAM/access changes, billing changes, destructive cloud
  operations, database/table deletion, and external data deletion require explicit owner authorization.
  A broad feature request is not implicit permission for an unrelated irreversible operation.
- Never create a new S3 bucket, provider account, OAuth client, API key, service-account key, webhook
  credential, or parallel credential family "just in case". Reuse the established resource/secret path
  or stop and document the missing prerequisite.

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

### Concurrent-work and branch discipline

- At the start of local work, inspect `git status --short` and, when available, run
  `python scripts/session_map.py`. Treat a file another active session is editing as owned by that
  session until proven otherwise.
- Immediately before writing a file, re-read its current contents. Preserve unrelated changes and
  never replace a file from an earlier snapshot after another session has modified it.
- For local Kiro sessions, work in the shared checkout as configured by this repository. For remote
  GitHub/ChatGPT-style edits, use a task branch and pull request unless the owner explicitly requested
  a direct base-branch change.
- Before merge or push, refresh the base ref and resolve divergence without discarding unrelated work.
  Use fast-forward/safe merge strategies; do not solve drift with force.
- Do not infer that a successful commit, PR creation, or zero exit code means the requested behavior is
  correct. Inspect the resulting artifact/state.

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
- Keep authorization server-side. Never trust a client-supplied role, user/customer id, account id,
  order id, phone number, redirect target, price, entitlement, or ownership claim without binding it
  to the authenticated principal on the server.
- Default to deny for privileged capabilities. Adding a new action requires an explicit authorization
  path; absence of an error is not authorization.
- Validate untrusted input at trust boundaries and encode/escape output for its destination.
- Verify third-party webhook/callback signatures and replay protections before mutating state.
- Do not log access tokens, authorization headers, cookies, signed URLs, raw webhook bodies containing
  personal data, or full provider error payloads when they can contain credentials/PII.
- Prefer idempotent writes and explicit request/idempotency keys for payments, messaging, commerce,
  provisioning, and other retryable external actions.
- Do not add a new dependency when the existing stack can solve the task cleanly. When a dependency is
  necessary, use the repository package manager/lockfile, avoid unpinned remote installers or
  `curl | sh` patterns, and keep lockfile changes scoped to the intended package update.

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

## Cloud, IAM, data, and external-provider safety

- Use least privilege for IAM policies, OAuth scopes, API scopes, resource policies, Lambda permissions,
  CORS, bucket access, and provider roles. Avoid wildcard actions/resources unless the platform genuinely
  requires them and the reason is documented beside the policy.
- Prefer workload identity, role credentials, or service-account impersonation over long-lived key files.
  Do not create/download a service-account JSON key when an existing identity flow can perform the task.
- Read-only provider access is the default. Google Ads, Meta Ads, Merchant Center, Business Profile,
  Tag Manager, Search Console/Bing, and similar mutations require the owner's explicit instruction for
  that mutation.
- Before any provider write, verify the exact target account/resource id, environment, authenticated
  principal, required scope, and current linkage. Manager/account labels are not proof of relationship.
- Where an API supports preview, validation-only, dry-run, draft, paused, or plan/apply semantics, use it
  before the live write.
- Never broaden a provider write from one named account/resource to all accounts visible to a manager.
- Do not use production customer data as test fixtures or copy production PII into local files.
- For data migrations or cleanup, define the selection predicate, upper bound, rollback/recovery path,
  and verification query before mutation. Avoid unbounded scans and mass deletes.
- If provider/API access is missing, restricted, quota-limited, unverified, or ambiguous, fail closed and
  report the exact missing prerequisite instead of silently switching identities/accounts or creating
  replacement credentials.
- Distinguish repository configuration, deployed configuration, provider-side state, and proven end-to-end
  behavior. A value present in source does not prove it is deployed; an account id does not prove access.

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
- The canonical public origin is `https://wecare.digital` (apex). Do not reintroduce `www` into
  canonical tags, sitemap URLs, Open Graph URLs, JSON-LD entity ids, or internal canonical links.
  A provider property recorded with `www` does not change the site's canonical origin.
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
- Do not request recrawling/indexing until the changed URL is actually deployed, publicly fetchable,
  canonical to itself, and returns the intended content. Do not repeatedly resubmit the same URL.
- Preserve redirect equity: use direct permanent redirects for genuinely moved public URLs, avoid
  redirect chains/loops, and never advertise a redirected/non-canonical URL in the sitemap.

## Verification and evidence standard

A task is not "done" merely because code was edited.

- Run the narrowest relevant checks plus the repository's required build/type/lint/compile gates for the
  touched surface.
- Report what was actually verified and what was not. Never claim a browser, physical device, WebView,
  production deployment, provider account, permission state, or end-to-end flow was tested unless it was.
- For security-sensitive or provider-facing changes, verify both the success path and at least one denied,
  missing, malformed, or failure path.
- For mutations, verify the intended postcondition from an independent read when feasible.
- When a check cannot run because credentials, hardware, provider approval, or environment access is
  unavailable, leave the feature fail-safe and state the exact release gate instead of guessing.
- Treat comments, old audit documents, screenshots, and prior chat as clues, not live-state proof. Refresh
  evidence before making irreversible or externally visible changes.

## Account registry, identifiers, and secrets

These identifiers are owner-confirmed references for the WECARE.DIGITAL SEO/advertising/analytics
estate. They identify intended resources; they do **not** prove current API scope, quota, linkage,
verification, billing state, or authorization. Re-verify live state before a credential-dependent
operation. If a canonical runtime config disagrees with this registry, investigate the drift rather
than silently choosing one; update the registry and canonical config together once provider-side truth
is proven.

### Google
- Google Ads advertiser: **WECARE.DIGITAL** — customer ID `836-758-9699`.
- Google Ads manager: **WECARE.DIGITAL** — manager/login customer ID `427-041-2231`.
- Google Cloud project: **WECARE-DIGITAL** — project ID `wecaredigitalbw`, project number
  `756034744787`.
- Google automation service account:
  `automation@wecaredigitalbw.iam.gserviceaccount.com`.
- Google OAuth web client identifier:
  `756034744787-occ06h9v22rh0kbm83mmedpfqqqfni44.apps.googleusercontent.com`.
- Google Analytics 4 property: `550346663`.
- GA4 web stream: **WECARE.DIGITAL** — stream ID `16126298947`, measurement ID
  `G-6GW8JXKKT7`, stream URL `https://wecare.digital`.
- Google Business Profile location: `locations/11367616731342236672`.
- Google Merchant Center: display account `wecare.digital`, merchant ID `5841142064`.
- Google Play developer page:
  `https://play.google.com/store/apps/dev?id=5505420420345648842`.
- Google Tag Manager account ID: `6372080304`.
  - Web container: `GTM-TXZ8JT78`.
  - Server container: `GTM-NPR6TB98`.

### Meta / Facebook / WhatsApp commerce
- Meta Ads account IDs recorded by the owner:
  `2477665435963445`, `1685177122467383`, `757566744073180`,
  `2107046253414284`, `1574832283724191`, `4437435039910843`,
  `3770879209885614`.
- WECARE dataset / CAPI dataset ID: `4554612361454941`.
- WhatsApp / Meta catalog: **wecare_shop** — catalog ID `1457045652952851`.

### Bing Webmaster
- Verified/owner-supplied Bing Webmaster site reference: `https://www.wecare.digital/`.
  This provider property does not override the website's canonical apex URL
  `https://wecare.digital/`.

### Credential references — never copy values into source

The owner has supplied live credentials for several of these accounts. Their literal values are
**not repository settings** and must never be copied into this file, source code, examples, logs,
commits, pull requests, or generated artifacts. Use the existing secret references instead:

- Google Ads credential family / developer-token field: AWS Secrets Manager
  `wecare/google/ads`.
- Google OAuth client secret: AWS Secrets Manager `wecare/seo/google-oauth`.
- Unified Google API key: AWS Secrets Manager `wecare/google-api-key` (or the existing
  service-specific Google secret already used by the target integration; do not duplicate it).
- Google Cloud service-account key material, only where a key is still required:
  AWS Secrets Manager `wecare/google/cloud`. Prefer impersonation/workload identity.
- Bing Webmaster API credential: AWS Secrets Manager `wecare/bing/api`.

API keys, OAuth client secrets, developer tokens, service-account key material, refresh tokens,
passwords, signing secrets, private keys, session cookies, and bearer/access tokens remain secret
even if previously supplied or accessed. Agents must not echo, display, paste, or fetch those
plaintext values for convenience. Runtime code may read an approved secret inside its authorized
server-side execution context; callers receive only the minimum derived result, never the secret.
Never infer that an account ID or a stored credential proves current provider authorization.
