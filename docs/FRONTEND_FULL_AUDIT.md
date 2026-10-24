# Frontend Full Audit — gaps & improvements (fresh, complete)

Supersedes the structural-only `FRONTEND_DUPLICATION_AUDIT.md`. Covers the home/public pages,
per-page completeness (real vs stub vs mock), reachability, accessibility, and improvements.
~120 route pages under `src/pages`.

## A. Home / public landing (`src/pages/index.tsx`) — RE-CHECKED 2026-09-26, mostly obsolete

> **Do not work from this section.** It was written against a version of the home page that
> no longer exists — the page has since been rewritten around a rotating headline, a
> two-column workflow band and a closing band. Five of the seven items below are gone, and
> the two that survive were **filed against the wrong file**, which is why they read as
> fixed: the JSON-LD moved to `src/pages/_app.tsx` and is now on 17 and 123 built pages
> rather than one. Current findings, measured:
> **`docs/home-design-audit-20260926.md`**, with a re-runnable gate at
> `tools/browser/homeprobe.js`.

| # | Original claim | Status 2026-09-26 |
|---|---|---|
| 1 | **No functional CTAs** — zero conversion action | **STILL TRUE.** Measured: 0 visible interactive elements inside `<main>` above the fold at 1280×900, 1440×800 and 390×844. The only CTA is `.home-close-cta` at the very bottom. Blocked on owner decisions (wording, destination, price) |
| 2 | No header nav and no footer | **OBSOLETE.** Both mount sitewide — `_app.tsx:579`, `:584`, `:1044`, `:1046` |
| 3 | **Fake review schema** `aggregateRating 4.8 / ratingCount 150` | **STILL TRUE, WRONG FILE.** Not in `index.tsx` — `_app.tsx:306-312`, shipping on **17** built pages |
| 4 | **`foundingDate: 2020`** | **STILL TRUE, WRONG FILE.** `_app.tsx:252`, shipping on **123** built pages |
| 5 | `wecare.digital/api/v1/...` examples | **OBSOLETE.** No such example remains on this page |
| 6 | Vague stat placeholders ("B+ Users reachable") | **OBSOLETE.** None on this page |
| 7 | Fake interactivity — `<button>` pills with `cursor:default` | **OBSOLETE.** Zero `<button>` elements in `index.tsx` |

Items 3 and 4 remain **P0**, and two more were found alongside them: the same schema
declares `offers.price: "0"` while the page promises "Know the price before you commit",
and the `Organization` description still reads "Enterprise WhatsApp Business API platform"
— the positioning the hero was deliberately rewritten away from.

Other public pages: `faq.tsx` (root, not in nav), `studio`, `carbon`, `sustainability`, `nocode` — see stubs below.

## B. Stub / "Coming Soon" / placeholder pages (shipped but not real)
Confirmed by reading source:
| Page | Evidence |
|---|---|
| `task/` | renders `<ComingSoon>` component |
| `nocode/` | `<EmptyState … "coming soon">` |
| `studio/` | static "Coming soon" text |
| `carbon/` | `<EmptyState … "coming soon">` |
| `sustainability/` | (same pattern — verify) |
| `contact-test/` | test/dev page, not production |
→ These ship as real routes and (`task`) appear in the sidebar with a "Soon" badge. **Recommendation:** remove from build/nav until real, or gate behind a feature flag. Shipping empty routes hurts UX and SEO.

## C. Real, well-built pages (leave them)
`index` (home, needs CTA fixes), `store/` (products/orders/collections/bulk),
`dm/channels/` (clean launcher hub), `dm/inbox` (unified cross-channel), `dm/whatsapp/*` (deep feature set),
`seo/*` (functional tools), `pay/*`, `service/*`, `contacts/`, `forms/`, `link/`. These use the shared
`Layout`, `Tabs`, `Table`, `EmptyState`, `Spinner`, toast, and `api/client.ts` — good consistency.

## D. Reachability (corrected)
- `dm/channels` is a launcher hub that links to `[retired public path 2de923b8]/logs` (unified), `[retired public path 2de923b8]/rcs/send`, `[retired public path 2de923b8]/ses/inbox`, etc.
  So the per-channel subpages and `dm/logs` ARE reachable via the hub (not fully orphaned) — but they're
  **still duplicates** of the unified `dm/inbox` / `dm/broadcast` / `dm/logs`.
- **Genuinely orphaned** (not in nav, not linked from channels hub) → verify/remove: `admin/` (root),
  `dashboard/admin` (redirect only), `dashboard/cors-settings`, `dashboard/order-notifications`,
  `dm/orders`, `dm/whatsapp/scripts`, `seo/pages-manager` (dup of `seo/pages`), `crm/`, `contact-test`,
  root `faq` (unless intentionally public).

## E. Duplication (from the structural audit, still open)
Inbox ×4, Campaign ×4, Logs ×4, Templates ×3, Usernames ×2, Flows ×4, SEO management ×6, Contacts ×3.
Root cause: channel-by-channel build + a unified `dm/*` layer added on top without retiring originals.
Target ~120 → ~70–80 pages.

## F. Accessibility & UX gaps (cross-cutting)
- **Landing page**: interactive `<button>`s with no action + `cursor:default` (confuse screen readers / keyboard users); no skip-link; decorative empty `<span>` badges without `aria-hidden`.
- **Inline styles everywhere** (store, channels use big inline style objects) — no theming/contrast tokens consistently; harder to guarantee WCAG contrast. `design-tokens`/`colors` exists but isn't used uniformly.
- **Color-only status** — order/payment statuses in `store` use color to convey meaning (and several map to the same `#1a3a2a`), no text/icon differentiation → fails color-contrast/again color-only guidance. Note: several status colors are identical (a bug — PAID/NOT_PAID both `#1a3a2a`).
- **Loading/empty states**: good in `store`/`channels` (Spinner + EmptyState); verify consistency across all list pages.
- **Error handling**: `store` swallows errors to `console.error` (no user-facing toast on fetch failure) — should surface via toast context.

## G. Prioritized action list
### P0 (quick, high value)
1. **Home page CTA above the fold** — still open; header and footer already ship. Blocked on the owner's wording/destination/price calls (see `docs/home-design-audit-20260926.md` M5).
2. **Remove fake review schema** + fix `foundingDate` — in **`src/pages/_app.tsx`**, not the landing page, so the fix is sitewide (17 and 123 built pages). Still open.
3. **De-list / remove stub pages** (`task`, `nocode`, `studio`, `carbon`, `sustainability`, `contact-test`) or feature-flag them.
4. **Fix status-color bug** in `store` (PAID/NOT_PAID rendered same color).

### P1 (consolidation — the maintainability win)
5. Retire per-channel inbox/campaign/logs in favor of unified `dm/*`; update `dm/channels` links accordingly.
6. Merge SEO management page variants into one tabbed manager; delete `seo/pages-manager` dup.
7. Remove genuinely-orphaned pages (section D) after confirming no deep links.

### P2 (structural quality)
8. **Shared channel component**: one `<ChannelInbox channel=…>` / `<ChannelLogs>` so channels never re-fork.
9. **Design-token adoption**: replace ad-hoc inline hex with `design-tokens` for WCAG-safe contrast + theming.
10. **Consistent fetch error → toast** pattern across all list/detail pages.

## Top 10 findings (summary)
1. Landing has **no CTA / login / header / footer** — can't convert or navigate.
2. **Fake `aggregateRating` schema** on landing — SEO penalty risk.
3. **6 stub "coming soon" pages** shipped as routes (`task` even in the sidebar).
4. `store` **status colors identical** for PAID/NOT_PAID (bug) + errors only logged, not toasted.
5. Massive **channel duplication** (inbox/campaign/logs ×4 each).
6. **SEO section** has ~6 near-duplicate management pages.
7. **Orphaned pages** (`admin`, `crm`, `dm/orders`, `seo/pages-manager`, `cors-settings`, …).
8. **Inline styles over design tokens** → inconsistent, contrast risk.
9. `foundingDate 2020` inaccurate structured data.
10. No **shared channel abstraction** → duplication will keep recurring.
