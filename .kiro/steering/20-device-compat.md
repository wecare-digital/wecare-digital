---
inclusion: always
---

# Universal device and browser compatibility

Every page must render and work correctly on 100% of target devices and
browsers. Treat this as a hard requirement, not a nice-to-have: a feature is not
done until it works across the full matrix below.

## Target matrix

- **Form factors:** phone, tablet, foldable (folded + unfolded), desktop, large
  desktop. Design mobile-first and scale up; never assume a fixed viewport.
- **Operating systems:** iOS/iPadOS, Android, macOS, Windows, Linux.
- **Browsers:** Safari (incl. iOS Safari), Chrome, Firefox, Edge, Samsung
  Internet. Support the current and previous major version of each.
- **Embedded contexts:** native **app WebView** and in-app browsers
  (iOS `WKWebView`/`SFSafariViewController`, Android `WebView`/Custom Tabs,
  WhatsApp/Instagram/Facebook in-app browsers).

## Layout and responsiveness rules

- Use fluid, responsive layouts (flex/grid, relative units, `clamp()`), not
  fixed pixel widths. No horizontal scroll at any width from 320px up.
- Respect **safe areas** and notches/cutouts with
  `env(safe-area-inset-*)` and `viewport-fit=cover`.
- Handle foldable hinges and dual-screen with viewport-segment media features / environment
  variables where applicable; degrade gracefully otherwise. Critical content must not sit
  beneath a physical hinge.
- Prefer the dynamic viewport units `dvh`/`svh`/`lvh` over `vh` so mobile
  browser chrome (collapsing address bars) does not clip content.
- All tap targets ≥ 44×44px; support touch, mouse, pen, and keyboard input.
- Honor `prefers-reduced-motion` and user font-size / zoom settings up to 200% without
  breaking layout.
- **Color scheme:** the public WECARE.DIGITAL experience is intentionally light-only. Declare
  `color-scheme: light` and a document-level light color-scheme meta value so browsers/WebViews
  do not auto-recolour controls. Do not introduce dark-mode styling unless the owner explicitly
  changes this product decision.

## Cross-browser rules

- Autoprefix / verify vendor support for CSS features; avoid relying on
  bleeding-edge APIs without a fallback or feature detection (`@supports`).
- Avoid WebView-breaking patterns: no reliance on pop-ups, `window.open` to new
  tabs for critical flows, or APIs commonly disabled in in-app browsers.
- Images and media must be responsive (`srcset`/`sizes`, `max-width:100%`) and
  use broadly supported formats with fallbacks.
- Ensure the `<meta name="viewport">` tag is present and correct on every page:
  `width=device-width, initial-scale=1, viewport-fit=cover`.

## Verification before "done"

- Confirm the static export builds (`npm run build`) — the real gate.
- Sanity-check responsive behavior at representative widths (≈320, 375, 768,
  1024, 1440) and in both portrait and landscape.
- When a change touches layout or global CSS, verify it in at least one
  WebView/in-app-browser context in addition to a desktop browser.
- For foldable/dual-screen changes, test folded + unfolded portrait/landscape widths. When a
  platform exposes a real hinge/viewport-segment posture, verify that critical content and
  controls do not straddle or sit beneath the hinge. A width-only emulator does not count as
  true hinge verification.
