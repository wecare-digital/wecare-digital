---
inclusion: always
---

# Public mobile foundation

Home is the locked reference implementation for the public mobile/app experience.
Do not redesign each route independently and do not apply blanket selectors that silently
restyle unaudited routes.

## Canonical mobile contract

Pages that have completed their public-mobile migration consume the named foundation tokens
from `src/styles/tokens.css`:

- `--public-mobile-hero-size: 40px`
- `--public-mobile-section-size: 32px`
- `--public-mobile-card-size: 24px`
- `--public-mobile-cta-font-size: 18px`
- `--public-mobile-page-gutter: 16px`
- `--public-mobile-section-gap: 64px`
- `--public-mobile-hero-top: 48px`
- `--public-mobile-form-font-size: 16px`

Do not duplicate mobile-only tokens for values already canonical globally:
`--public-body-size: 20px`, `--tap-min: 44px`, safe-area `--safe-*` tokens,
light-only colour scheme, and the `100vh` + `100dvh` viewport fallback.

## Migration rule

Adopt the contract family-by-family. Home is already migrated. Grahak OS is the next
reference migration, followed by VayuLok, shared service/product pages, customer forms,
shop/product pages, then blog/legal/long-form pages.

A migration may keep product-specific visual identity and interaction patterns. Unify the
foundation — typography roles, gutters, spacing, touch targets, safe areas, responsive
containment, reflow, WebView behaviour and shared public chrome — not every component shape.

## Verification

For every migrated family, run build/type/unit gates plus the public browser/device matrix.
Check 320/375/390/430 phones, tablet widths, desktop, folded/unfolded and wide-short foldable
postures, 200% reflow, Chromium/Firefox/WebKit, and Capacitor public-shell sync. A real physical
hinge and installed WKWebView remain release-device gates when browser CI cannot reproduce them.
