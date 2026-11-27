# Public page compatibility acceptance standard

Home is the reference. Audit one route at a time; preserve approved content, design
tokens, security, authentication, payments, policy ownership and navigation. Home is
the only public content page without Policy details.

## Shared responsive baseline

Apply Home's reference tokens to the shared hero, product typography, safe gutters,
closing actions, policy, share dock and footer before individual page audits.
Preserve bespoke layouts, private Workspace, authentication, payments and Vault privacy.

    PUBLIC_QA_BASE=https://wecare.digital PUBLIC_QA_BASELINE_ONLY=1 PUBLIC_QA_ENGINES=chromium,webkit,firefox node scripts/verify_public_browser.mjs

The baseline run covers common chrome on registered routes, not certification of
individual pages or native devices. Verify each page separately after deployment.

## Reusable task prompt

Audit and improve [page name] at [live URL]. Use the current Home reference.
Check phone/tablet/desktop, portrait/landscape, foldable cover/open and actual hinges,
Chrome/Safari/Firefox/Edge, Android WebView and iOS WKWebView, installed PWA and
WhatsApp/Instagram/Facebook in-app browsing. Check 200% zoom, font scaling, safe
areas, keyboard, screen readers, contrast, reduced motion, focus, touch targets,
content clipping, stable layout, loading/error recovery and truthful SEO. Use shared
tokens and accessible controls. Preserve actual behavior; no test transactions.
Fix scoped defects, run existing tests/typecheck/lint/build, review the diff and
prepare a PR. Record CI, merge revision, Amplify job and live route. Mark complete
only for platforms actually verified; distinguish source, viewport emulation and
physical device/native app evidence. Continue to the next page only after review.

## Repeatable browser run

In an approved network-enabled QA checkout with Playwright and the requested engines
installed, run:

    PUBLIC_QA_BASE=https://wecare.digital PUBLIC_QA_ROUTE=/ PUBLIC_QA_ENGINES=chromium,webkit,firefox node scripts/verify_public_browser.mjs

Change PUBLIC_QA_ROUTE for each registered public page; omit it for the existing
all-route smoke. The focused run adds wide desktops, short screens, common phones,
landscape, fold-like widths, reduced motion and a 160 CSS-pixel stress layout.
Playwright viewport profiles and engines are approximations, not device or native
WebView certification. Use actual Android/iOS shells, physical foldables, browser
zoom, Safari/Edge, screen readers, safe-area and keyboard tests separately.

## Shared menu compatibility

Audit the header and navigation before migrating individual product pages.
Use the same live Home reference and representative product, shop and legal routes:

    PUBLIC_QA_BASE=https://wecare.digital PUBLIC_QA_MENU_ONLY=1 PUBLIC_QA_ENGINES=chromium,webkit,firefox node scripts/verify_public_browser.mjs

Add PUBLIC_QA_ROUTE to limit the menu run to one registered route. Verify the
menu bounds, search results and no-result state, clear and Escape, focus recovery,
expandable families, tap targets, short-height/keyboard-size viewport changes and
navigation screenshots. No links that initiate transactions are activated.
Physically verify iOS/Android WebView keyboard, safe areas, foldable hinge, native
back and screen-reader behavior separately. Preserve all menu destinations and
commerce/contact action semantics.

## Per-page completion record

- Name and live URL; reviewed source commit and PR.
- Source tests/typecheck/lint/build, CI checks and merge commit.
- Amplify deployment ID/status and browser report/screenshots for deployed revision.
- Physical device/app/browser evidence, missing coverage and remaining defects.
- User review decision and next route.

Never call a page complete solely because a PR merged. A failed deployment leaves
the last successful revision live. Do not bypass required checks.
