# Public website verification — November 26, 2026

This is the release acceptance checklist for the public search changes and remaining P1/P2 work. A source change or a green unit test does not prove a live transaction or visual journey.

## Automated source/build gates

Run in a checkout with the repository's documented Node version and dependencies:

```sh
node --test tests/public-search-verification.test.mjs tests/navigation-experience.test.mjs
npm test
npm run typecheck
npm run build
node tools/audit/indexcheck.js
node tools/audit/blogcheck.js
```

The new tests cover explicit clear controls, focus/keyboard source contracts, editorial aliases, lazy query initialization, and index retry/cache behavior. They do not replace browser interaction tests.

## P1: device and visual testing

In an approved QA environment with Playwright and Chromium installed, set PUBLIC_QA_BASE to the preview URL and run:

```sh
PUBLIC_QA_BASE=https://your-approved-preview.example node scripts/verify_public_browser.mjs
```

The script navigates read-only pages, records viewport screenshots, checks document overflow, and exercises clear and Escape on legal, blog and Anew searches. It includes desktop, tablet portrait/landscape, mobile, folded cover and unfolded-like viewport dimensions. It does not emulate a physical fold hinge, operating-system keyboard, or Safari; separately inspect physical foldables, mobile Safari, Firefox, screen-reader behavior, zoom, touch targets, safe areas, menu, cart, authentication and order navigation. Attach screenshots and failure logs for each browser/device. No production transaction is created by the smoke test.

## P1: checkout, payments, order and WhatsApp acceptance

Use a designated test account, test catalog/amount, payment-provider test mode and approved test WhatsApp number. Never reuse a real customer identity or send production messages just to verify a screen.

- Checkout: product/variant selection, cart changes, session/OTP, address and applicable tax/total, payment initiation, success/cancel/failure, duplicate callbacks, resume/reload, order confirmation and history/tracking.
- Verify a known authorized test order across backend and customer/staff read surfaces with `python scripts/commerce_acceptance_check.py --order <TEST_ORDER_NUMBER> --json`. The existing script is read-only but points at configured order storage; verify account/environment before executing it.
- WhatsApp: each allowed request type, correct template/recipient and hand-off, validation, submission, confirmation, amendment, retry and no duplicate sends; record message/flow identifiers from the test environment.
- Reconcile amount, currency, order ID and payment state. A screenshot alone is insufficient; check provider and backend records.

## P2: live SEO and retired URLs

From a network-enabled approved runner, run:

```sh
python scripts/retired_url_probe.py
python scripts/probe_url_host_matrix.py --json
python scripts/search_console_index_audit.py /terms/ /privacy/ /blog/ /anew/
```

The first two check public URL behavior; the third requires authorized Search Console credentials. Confirm live robots.txt, sitemap.xml, canonical tags, HTTP statuses and indexability with actual HTTP responses. The repository's current policy keeps retired family parents out of the sitemap and returns 404/410 for explicitly retired paths; do not invent redirects or resubmit a sitemap unless the evidence and owner-approved routing policy call for it.

## P2: performance and accessibility

Use comparable cold-cache desktop and mobile Lighthouse runs and capture LCP, CLS and INP/interaction latency evidence (field data where available), JS/network payloads and keyboard/screen-reader checks. Verify the full blog search index is not downloaded for a browse-only visit, loads on search focus or query, retries on explicit request, and is reused across client navigation after successful load. Confirm accessible X, visible focus, nonoverlapping microphone/clear controls, live result announcements, and no loss of category scope or clause text. Inspect deep-link search (?q=), zero results, typographical errors, and curated Hindi/Bengali keywords.

## Current evidence and status

- Source fixes and regression coverage are on the fix branch. Browser/CI results must be attached before release.
- Public web-indexed content was retrievable for Terms, Privacy, Blog and Anew, but these snapshots do not establish the current live build or response status.
- No real payment, WhatsApp send, order creation, Search Console mutation, or live deployment was performed during this change.
- The local session could not resolve the GitHub or public site DNS names, preventing checkout of dependencies and live HTTP/browser testing. A network-enabled preview/CI runner and designated test environment are required for remaining acceptance gates.
