# Public acceptance audit — baseline build 727

Baseline: production commit `dcaf7fcaf8242a53b8bce781356218eff6769e51`,
Amplify job 727 BUILD/DEPLOY/VERIFY succeeded. The new audit is read-only;
it does not change site behavior, payment policy, or the release gate.

## Automated evidence

The generated public route inventory is the starting point (28 canonical
routes). Additional real static routes include GetKosh, UdyamBids, auth,
checkout, checkout status and success. Orders is explicitly gated, not
certified by an anonymous sign-in redirect. Discover representative post,
shop detail and pagination samples from the actual sitemap; do not invent
slugs. Keep the existing browser runner for menu/interaction/19-profile
baseline checks. The separate acceptance runner records real anonymous
browser geometry, each settled rotating word, reduced-motion stability,
axe rules, title/description/canonical/robots/JSON-LD, sitemap inventory,
and supported navigation/LCP/CLS timings. Save per-route JSON/screenshots.

GitHub Actions supplies a network-enabled audit environment. Isolated
Playwright 1.65.1 and @axe-core/playwright 4.14.1 do not enter production
dependencies. The optional workflow uses 3 engines at desktop, phone and
fold cover widths, plus Chromium at landscape, 160px stress and 2560px.
These are approximations, not native device certification. The revision
label is the initial observed baseline, not proof the live site did not
change mid-run. Before accepting evidence, compare the latest Amplify
job and commit before and after the run. Rerun if the revision changed.

## Known source findings before the browser run

- Shared RotatingHero and Home RotatingPill are already wired to contextual
  copy. Existing full-cycle geometry checks cover Home only. Orders,
  checkout, shop detail and upcoming pages intentionally have static
  one-word pills; keep task screens stable and ask for editorial approval
  before changing approved marketing copy. Auth and payment-status rotate
  currently. RotatingPill respects reduced-motion on initial mount but
  has no explicit pause/stop control for indefinite rotation.
- PublicShare's Contribute dropdown explicitly routes to /orders/ and
  stashes a customer menu send intent. customerMenuActions sends action
  create to /ecommerce/checkout (native WhatsApp); this is NOT the
  requested website-only contribution journey. Website checkout already
  has the Razorpay rail, read-only quote, verify callback, and status
  reconciliation. Do not activate the existing Contribute control on
  production: an authenticated session could send a payment request.
- For the separate contribution correction, preserve the approved
  INR 300 amount and exact catalog product/variant, server price authority,
  identity, no charge before explicit review, one live attempt per basket,
  verified capture and receipt/status. Route the public action to a
  website checkout review, do not silently erase unrelated cart lines,
  do not enqueue an Orders WhatsApp send. Keep other legitimate WhatsApp
  services unchanged. Prove quote/prepare/callback success, cancellation,
  duplicate taps, tampered amount, invalid signature, timeout and retry
  in a controlled test environment. No live money or customer message.

## Manual acceptance still required

WCAG 2.2 AA requires human checks as well as axe. Test keyboard, actual
screen readers, contrast, zoom, OS font scaling, RTL/IME, safe areas,
actual Safari/Edge, WebViews, social in-app browsers, fold hinge and PWA.
Collect field Core Web Vitals (p75), not just laboratory navigation
timings. Check canonical/noindex headers and valid structured data against
approved content. Verify all dynamic template variants and authenticated
flows with authorized synthetic accounts. Production build success does
not certify these checks. No checkout payment or message is executed here.
