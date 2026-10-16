# Pages Router consolidation (CON1) — status on current `stack` (2026-10-16)

Re-verified against `stack` (`35f8cc6d`), as CON1 §0 requires ("do not trust the
old audit blindly"). The repo is **further along than CON1 assumes** (CON1 is
dated 2026-10-15; several items already landed). This maps each Phase-1 item to
its real state so the actual PR is scoped to what is genuinely open.

## Already done — no work needed

| Item | Evidence |
| --- | --- |
| **C2 — `/shop/` own metadata** | `src/pages/shop/index.tsx:54` emits `<PageMeta title="Shop \| WECARE.DIGITAL" …>` with its own description and `/shop/` canonical. The file comment documents the exact home-title-bleed bug CON1 describes and its fix. |
| **C19 — `vayulok-globe.html` noindex** | `public/vayulok-globe.html` already has `<meta name="robots" content="noindex" />` plus the "iframe asset, not a page" comment. Globe still embedded via `VayuLokApprovedGlobe.tsx` → `/vayulok-globe.html`. |

## Genuinely open — real work, needs a proper PR (not a rushed pass)

| Item | State | Why it is not a quick edit |
| --- | --- | --- |
| **C17 — `/anew/` payload** | **OPEN, confirmed.** `anew.tsx` `getStaticProps` ships the FULL corpus: `listBlogCards(...).slice()` is a copy, not a cap (comment: "no per-category cap — the panel pages through everything"). All ~1,400 cards serialize into `__NEXT_DATA__`. | Fix = first-page SSG + client-fetch the rest via the existing `/blog/` loader, then **prove the reduction from `out/`** (CON1 §15 forbids claiming success on a TS diff). Requires a full static-export build to measure. |
| **C14 — one title builder** | **PARTIAL.** Titles already follow `… \| WECARE.DIGITAL` everywhere (`ShopListingHead`, `BlogIndexHead`, `PageMeta`), but via inline template strings, not one shared `buildPageTitle()`. | Introduce the util + migrate public pages + regression tests pinning the format. Low-risk but touches many files; belongs in the PR with its tests. |
| **C9 — Contact request hub** | OPEN. `/contact/` needs to become a real hub linking the 7 request routes, reusing existing `CUSTOMERSERVICE` definitions. | UI build + must not retire/redirect the 7 child routes (§C9). |
| **C13 — unified PageShell + breadcrumbs** | OPEN. One shell driving both visible breadcrumb and `BreadcrumbList` JSON-LD from one `crumbs` input. | Cross-cuts many pages and the SEO registries (§2); must coexist with `_app.tsx` chrome. Core refactor, highest blast radius. |
| **C12 — dead components** | OPEN, needs importer check. `ContributeBlock`, `BlogSubscribe`, `ShareLinks` — delete only if zero runtime importers on `stack`. | Must verify static + dynamic imports before deleting; remove dead CSS/tests. |
| **§7 — decompose large routes** | OPEN. `cart.tsx` 2,343L, `orders.tsx` 1,485L, `get.tsx` 744L, `account/sign-in.tsx` 719L. | Behavior-preserving extraction of UI into `src/components/**` while keeping Next data hooks in `src/pages`. `cart`/`orders` touch checkout — §19 forbids altering commerce contracts. High-care work. |
| **W1/W4/W5 — workspace nav dedup** | OPEN. Remove duplicate/dead nav rows (Docs, Access, duplicate WhatsApp Inbox, waba-usernames) in `navigation.ts` — only after confirming each is a redirect/duplicate; keep the underlying routes. | Needs per-row route inspection. |

## Current counts (recount from `stack`, per CON1 §16)

- `src/pages` route files: **153** (was 146 in the old audit)
- workspace pages: **105**
- public/framework pages: **44**
- Large inline routes: cart 2,343L · orders 1,485L · get 744L · sign-in 719L

## Honest scope note

CON1 is a multi-commit, single-PR refactor with hard build/test/routegraph/
navcheck gates and an explicit "preserve behavior first" rule. It cannot be
"quick completed." The responsible path is one Phase-1 PR off a dedicated branch
(CON1 §1.1, §22), smallest-risk items first (C14, then C12/C17), with the
checkout-adjacent decomposition (`cart`/`orders`) done last and most carefully.
Owner-decision items (C3/C5/C6/C8/C10/C15/C18/W8) stay out of Phase 1 (§8).

## Recommended Phase-1 order

1. C14 title builder + regression tests (low risk, enables C13).
2. C12 dead-component removal (after importer verification).
3. C17 anew payload (measure `out/` before+after).
4. C9 Contact hub (reuse `CUSTOMERSERVICE`).
5. C13 PageShell/breadcrumbs (the cross-cutting core).
6. §7 route decomposition — `get`/`sign-in` first, then `orders`, then `cart`.
7. W1/W4/W5 nav dedup.
Each with its own commit; one PR; green gates before merge.
