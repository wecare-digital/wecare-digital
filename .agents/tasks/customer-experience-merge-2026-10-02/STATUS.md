# Customer-experience merge + URL cleanup — status

Date: 2026-10-02
Branch: `stack` (local, NOT pushed — orchestrator pushes after review)

## Final SHA

- **Final local `stack` HEAD: `0e11f3c3b37b74dff3bb553475433d077f1e5720`**
- Key commits (newest first):
  - `0e11f3c3` merge origin/stack (e1db5d62 — Wix manifest align)
  - `7e215bb8` merge origin/stack (3b8f6b06 — JSON 404 / retire stale origins)
  - `26e970ae` merge origin/stack (800106aa — live-env edit + payment work)
  - `e1339b60` **fix: repoint active customer-facing CTAs off dead/redirecting old URLs** (the URL cleanup)
  - `08bb2ad8` **Merge feature/customer-experience-upgrade into stack** (the conflict resolution; parents 863c6ebd + 6a2a2b5f)

origin/stack advanced THREE times during the task (863c6ebd -> 800106aa ->
3b8f6b06 -> e1db5d62). Each was incorporated by **merge, never reset**. None
overlapped the merged/cleanup files, so all follow-on merges were clean (no
re-conflicts). Final state: origin/stack (e1db5d62) is fully an ancestor of
local stack.

## The 8 conflicts and how each was resolved

Root cause: a parallel session had already landed an EARLIER version of the
/zip + /perks "match the home page" work on stack with the OLD labels (nav
"Zip", heading/label "Perks"), plus the /perks collapse to a single nav link.
The feature branch carried the NEWER label decisions (Shipments / Extras).
Principle applied per hunk: **keep the feature branch's newer labels/content;
preserve the legitimate parallel work stack added that did not conflict**
(the perks collapse + removal of gift-card/offers/rewards sections survives).

1. **config/public-pages.json** — feature side won: `name`/`title` "Extras"
   (route key stays `/perks`). Regenerated via `node scripts/generate-public-pages.js`;
   `--check` passes (parity with PUBLIC_PAGE_META, asserted by PublicAiSurface).
2. **src/components/Header.tsx** — feature side won on both conflicted hunks:
   group heading "Perks"->"Extras", nav link label "Perks"->"Extras" (route
   /perks/). The "Zip"->"Shipments" rename + move above Leave Review had
   auto-merged cleanly (stack never touched that region). Stack's perks-collapse
   comment/structure is retained.
3. **src/components/__tests__/Header.test.tsx** — feature side won: asserts the
   "Shipments" and "Extras" labels and that the old "Perks" link is gone.
4. **src/pages/_app.tsx** — feature side won: PUBLIC_PAGE_META `/perks` name
   "Extras" (key stays `/perks`). (The `/zip` meta `name` stays "Zip" by the
   feature branch's own deliberate decision — that is the machine schema name,
   not the customer-facing label; left exactly as the feature branch set it.)
5. **src/pages/zip.tsx** — feature side won on all 3 hunks: badgeLabel / title /
   ariaLabel / docblock identity read "Shipments". Route stays /zip/.
6. **src/pages/perks.tsx** — feature side won on all 4 hunks: badgeLabel / title /
   ariaLabel / eyebrow / body copy read "Extras". Route stays /perks/.
7. **src/test/ZipPage.test.tsx** — feature side won on all 3 hunks: asserts
   "Shipments" identity.
8. **src/test/PerksPage.test.tsx** — feature side won: asserts "Extras" present
   and "Perks" absent in customer-facing copy.

No conflict markers remain anywhere (`grep -rn '^<<<<<<<|^=======|^>>>>>>>'
src/ config/ amplify/` -> none).

## URL cleanup — exact CTAs repointed (file:line -> old -> new)

Gift-card CTAs: `wecare.digital/gift-card` -> `wecare.digital/perks/` (the
Extras page; matches what inbound-whatsapp-handler, ai-generate-response and
seo-tools/wix.py already use):
- src/pages/workspace/dashboard/system-architecture.tsx:652  (BOT_MENU row 6 action)
- src/pages/workspace/engage/whatsapp/scripts.tsx:78         (cta_gift URL)
- src/pages/workspace/engage/whatsapp/settings.tsx:68        (BOT_MENU row 6 action)

Dead `[retired public path b180810d]` CTAs (apex [retired public path b180810d] 404s; documented in orders.tsx)
-> intent-matched live Request-group routes:
- amplify/functions/ai/ai-generate-response/handler.py:359  Start Now  [retired public path b180810d] -> /submit-request/   (menu_submit_request)
- amplify/functions/ai/ai-generate-response/handler.py:363  Start Now  [retired public path b180810d] -> /request-amendment/ (menu_amend_request)
- amplify/functions/ai/ai-generate-response/handler.py:367  Start Now  [retired public path b180810d] -> /orders/            (menu_track_request)
- amplify/functions/ai/ai-generate-response/handler.py:371  Book Slot  [retired public path b180810d] -> /submit-request/    (menu_rx_slot; see ambiguous note)
- amplify/functions/ai/ai-generate-response/handler.py:375  Upload Now [retired public path b180810d] -> /drop-docs/          (menu_drop_docs)
- amplify/functions/ai/ai-generate-response/handler.py:379  Get Support/customerservice -> /submit-request/    (menu_enterprise; see note)
- amplify/functions/ai/ai-generate-response/handler.py:383  Customer Service/customerservice -> /submit-request/   (menu_hours; see note)
- src/pages/workspace/engage/whatsapp/calling.tsx:642   "Submit your request here" [retired public path b180810d] -> /submit-request/
- src/pages/workspace/engage/whatsapp/calling.tsx:1266  "Submit your request here" [retired public path b180810d] -> /submit-request/

### Ambiguous-destination choices (stated per briefing)
- **menu_rx_slot "Book Slot"** -> /submit-request/. Rationale: it is an
  appointment/booking intent, but there is NO visit/booking backend in the repo
  (zip.tsx lists "Book a visit" as an explicit non-transacting coming-soon). The
  briefing's default for ambiguous intent is /submit-request/, so a working
  request-intake page is used rather than a dead or coming-soon target.
- **menu_enterprise "Get Support"** and **menu_hours "Customer Service"** ->
  /submit-request/. Both are generic customer-service entry points; the request hub
  (/submit-request/) is the closest live customer destination in the briefing's
  allowed set (/submit-request/, /orders/, /zip/).

### Deliberately NOT changed (and why)
- **src/pages/workspace/seo/pages-manager.tsx:57 `/my-orders`** — LEFT AS-IS.
  Proof: it is a Wix **member-area SYSTEM page** (`type: 'system'`, BASE =
  Wix apex), sitting in a coherent group of Wix system pages (`/cart-page`,
  `/checkout`, `/my-account`, `/my-addresses`, `/my-wallet`, `/members-area`,
  `/order-confirmation`). This is a different namespace from the public Next.js
  `/orders/` route. The documented rename was `[retired public path aaee9dd4]` (singular) -> `/orders`
  for the PUBLIC page; this `/my-orders` (plural Wix system) is not that stale
  copy. Rename not proven safe, so per the master prompt it is untouched.
- **The retired-origin + redirect system**: scripts/provision_legacy_redirects.py,
  scripts/check_retired_origins.py, src/pages/404.tsx — all preserved untouched.
- **CORS `www.wecare.digital` allow-lists** — preserved (confirmed present in
  amplify/functions/ai/mcp/handler.py, site-language/handler.py). Not removed.
- **src/config/analytics.ts BING.siteUrl = `https://www.wecare.digital/`** — intact.
- Historical explanatory `[retired public path b180810d]` comments (orders.tsx, bharat-rx.tsx,
  products.ts) left as documentation.
- No internal/technical `customerservice` identifiers, workspace routes, provider
  template ids or integration ids touched.

### No dead route registrations found to remove
public-pages.json / PUBLIC_PAGE_META / sitemap PUBLIC_EXACT contain no
`[retired public path aaee9dd4]`, `/gift-card` or `[retired public path b180810d]` registration. `/zip` and `/perks`
remain registered (routes kept; labels changed only). Nothing to delete.

## Gate results (true counts, on final HEAD 0e11f3c3)

- **tsc --noEmit**: exit 0.
- **vitest run**: 57 files, **758 passed**, exit 0 (meets 758+ baseline).
- **pytest -q**: **6381 passed, 1 skipped, 1 failed**, exit 1.
  - The single failure is PRE-EXISTING and OUT OF SCOPE:
    `tests/test_meta_version.py::test_no_request_url_embeds_a_version_literal`
    — flags a hardcoded `graph.facebook.com/v26.0` literal in
    `amplify/functions/ai/workspace-mcp/handler.py:533` (a Meta Graph API
    version string). Unrelated to the merge or the customer-facing URL cleanup;
    present on the live stack branch and not fixed by any parallel push.
  - The other pre-existing failure observed at merge time
    (`test_provision_checkout_contract` manifest _variables 399 vs 401) was
    FIXED by a parallel origin/stack push (f4d7f8c8) and is now green.
  - Passed count rose from 6378 (merge time) to 6381 as parallel pushes added
    passing contract tests. Meets/beats the 6372+ baseline.
- **npm run build**: exit 0, 1409 sitemap URLs (1321 blog posts). One run hit
  the known transient upstream blog 429 on /post/[slug]; re-running produced
  exit 0 (build safety not weakened).

## Built-output verification (out/)

- `out/zip/index.html`: "Shipments" present (6x), title "Shipments —
  WECARE.DIGITAL", exactly one `<h1>` and one `<main>`. Exports at /zip/.
- `out/perks/index.html`: "Extras" present (12x), zero `>Perks<` in body,
  exactly one `<h1>` and one `<main>`. Exports at /perks/.
- `out/index.html` nav: shows "Shipments" and "Extras" (and "Leave Review",
  "Legal Stuff").
- No conflict markers in src/, config/, amplify/, or built output.

## Confirmation of invariants from the brief

- Shipments: YES (nav label + /zip page identity).
- Extras: YES (nav label/heading + /perks page identity).
- Contribute: YES (BlogContribution.tsx heading "Contribute"; not "Support
  this work").
- Contact-last: YES — Terms "How to contact us" = section 47 (last); Privacy
  "Who we are and how to reach us" = section 24 (last). Privacy contribution /
  gift-card clauses and Terms contribution / gift-card / coupon / rewards / zip
  clauses from the feature branch all survived.

## Handover

- NOT pushed, no PR opened (orchestrator will push after review).
- Commits were staged by explicit path; the cleanup commit used
  `git commit --only <paths>` per the multi-session steering rules.
- A live steering message from the user (listing the 8 conflicting files) was
  received mid-task; it matched exactly the resolution already in progress.
