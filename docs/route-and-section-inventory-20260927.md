# Route, link and section inventory — 2026-09-27

Everything here is **measured**, not read off the source tree. Three new harnesses produce
it and each finding names the command that reproduces it:

| Harness | What it reads | Answers |
|---|---|---|
| `tools/audit/routegraph.js` | every emitted HTML file in `out/` | routes, internal link graph, broken links, orphans, sitemap coverage |
| `tools/audit/navcheck.js` | `out/workspace/**` + `src/config/navigation.ts` | workspace pages missing from the sidebar, sidebar entries with no page |
| `tools/browser/sectioncheck.js` | the built pages in real Chromium at 1280×900 | how many **bands** each public page renders |

```bash
npm run build                          # produces out/
node tools/audit/routegraph.js
node tools/audit/navcheck.js
cd tools/browser && npm install && cd ../..
node tools/browser/sectioncheck.js
```

`routegraph` and `navcheck` need no browser, which is why they live in `tools/audit/` —
`tools/browser/README.md` promises every script there renders in Chromium, and a pure-`fs`
script sitting among them would make that claim false.

---

## Part 1 — How many sections

### The home page has **3 bands**

Counting `<section>` in source gives 2 and is wrong: the hero is a `<div>`. Measured at
1280×900, `main.home-shell > .home-layout` branches into three children:

| # | Band | Height | Top | Heading |
|---|---|---|---|---|
| 1 | `div.home-hero` | 211px | 188 | *Everyday AI, built for* + rotating pill + sub-line |
| 2 | `section.home-flow` | 650px | 495 | The part you don't have to think about. |
| 3 | `section.home-close` | 552px | 1241 | Start with what you need today. |

Page height 2090px — about 2.3 viewports. Header (108px) and footer are mounted once in
`_app.tsx` for every public route, so they are page chrome rather than bands of this page;
excluded from the count above and verified present on all 18 routes.

**The existing mock covers band 1 only.** `docs/home-review.html` and its generator
`tools/browser/homereview.js` are scoped to the top band, stated in the generator's own
header. So bands 2 and 3 have no mock yet — that is the work you're asking for.

### All public pages — 44 bands across 18 routes

| Bands | h1 | h2 | Page height | Route |
|---|---|---|---|---|
| 3 | 1 | 2 | 2090 | `/` |
| 6 | 1 | 4 | 2872 | `/grahak-os/` |
| **2** | 1 | **0** | **1031** | `/vayulok/` |
| 2 | 1 | 1 | 1485 | `/contact/` |
| 2 | 1 | 48 | 28290 | `/terms/` |
| 2 | 1 | 25 | 13262 | `/privacy/` |
| 2 | 1 | 2 | 1388 | `[retired public path aaee9dd4]/` |
| 2 | 1 | 1 | 1464 | `/bharat-rx/` |
| 2 | 1 | 1 | 1585 | `/elsewhere/` |
| 2 | 1 | 1 | 1442 | `/expo-week/` |
| 2 | 1 | 1 | 1585 | `/dastavez/` |
| 2 | 1 | 1 | 1614 | `/clear-closure/` |
| 2 | 1 | 1 | 1442 | `/ritual-guru/` |
| 2 | 1 | 1 | 1614 | `/anew/` |
| 2 | 1 | 1 | 1471 | `/niji-setu/` |
| 2 | 1 | **746** | **81558** | `/blog/` |
| 3 | **0** | 0 | 900 | `/store/` |
| 4 | 1 | 0 | 900 | `/get/` |

Three things fall out of that table on their own:

**The seven product pages are one template, twice over.** `/elsewhere/`, `/expo-week/`,
`/dastavez/`, `/clear-closure/`, `/ritual-guru/`, `/anew/`, `/niji-setu/` all render
`div.rh-hero` at exactly 269px followed by one `section.pdp`, and their heights cluster in
three values (1442 / 1585 / 1614) because only the bullet count differs. `/bharat-rx/` and
`[retired public path aaee9dd4]/` share the hero and swap the second band. That is good consistency, and it means
**a change to the `rh-hero` band is a change to ten pages**, not one — worth knowing before
any home-page decision gets propagated.

**`/grahak-os/` is the only page with a real section rhythm** — 6 bands. The home page has 3.
Everything else has 2.

**`/vayulok/` renders a headline and nothing else.** Two bands, and both are inside the hero:
`div.vl-eyebrow` and `h1.vl-head`. Zero `h2`, zero `<section>`, 1031px total — of which 188px
is blank space above the first word. It is a product page with no product content, and it is
in the mega-menu and the sitemap.

---

## Part 2 — Deep route check

### Counts

```
871 routes emitted   |  764 public   105 workspace   2 non-page (/404/, /offline/)
```

764 "public" includes 746 blog posts and `/blog/`. The authored public surface is **18 routes**.

### Internal links: clean

- **0 broken internal links.** Every `/…` href in all 871 documents resolves to an emitted
  page, or to `/api/*` and `/r/*`, which are served outside the export.
- **0 mixed trailing slashes.** `trailingSlash:true` is honoured by every link.
- **Sitemap:** 762 entries, none pointing at a page that does not exist, and **no
  `/workspace/*` route leaked into it**.

The `Selfservice` mega-menu group is not a broken-link problem — its children deliberately
point at `/contact/`, documented in `Header.tsx:55`. It is a *destination* problem, below.

### Findings

#### R1 — `/store/` is an internal page sitting on a public URL, and it serves a sign-in wall at HTTP 200

`src/pages/store/index.tsx` imports the authenticated `Layout`. `/store/` is **not** in
`_app.tsx`'s public allowlist, so an anonymous visitor gets the public marketing header and
footer wrapped around the **staff Amplify Authenticator**. Measured in `out/store/index.html`:
`amplify-authenticator` markup present, `div.ag-shell` rendered, **zero `<main>` elements and
zero `<h1>`** — the only public route on the site failing both.

This is the exact shape `_app.tsx:713` records as already having caused a live exposure on
`/contact-test/`, and that comment names `/store/` as having been "clean" at the time. It is
not clean now. It is also unreachable as a public page — 0 inbound links from any of the other
870 documents, and absent from the sitemap — while `navigation.ts:133` lists it as a sidebar
destination labelled *Catalog*.

**Your proposed tree is right about this one:** `/store` belongs under
`/workspace/commerce/`. It is the single strongest argument in the restructure.

Compounding it, `/store/*` is simultaneously an **API prefix**: `_routes.json` declares
`GET /store/preview-product-image`, `POST /store/generate-product-image` and
`POST /store/convert-flag`. One path prefix is doing three jobs — public page, staff page,
API namespace.

#### R2 — `/get/` collides with the CDN media rewrite, and the page's own docblock says so

`src/pages/get.tsx` carries the heading *"Why this page is at /files and not under /get"*,
and explains: `/get/<*>` is an Amplify 200-rewrite onto the CloudFront distribution in front
of the file bucket, **so nothing under that path reaches Next.js at all**.

The page ships at `/get/`.

That the rewrite is live is not a guess — `_app.tsx:111–113` loads the site's own logo and
favicon from `https://wecare.digital/get/o/stream/media/m/…`. Meanwhile `_app.tsx:740`
allowlists `router.pathname === '/get'` as public, and its comment says the staff-sign-in
failure was found "when this page was at `/files`" — i.e. the move happened and the docblock
was never turned around.

So the two comments contradict each other about which path is the broken one, and the page is
emitted at the path one of them says is unreachable. **Whether `/get/` exactly (no
sub-path) survives the rewrite depends on the Amplify rule's pattern, which is Console
configuration and not in this repo** — I could not verify it from the sandbox. It needs
checking against the live console before anything else here is decided, because if the rewrite
is `/get/<*>` the page is dead in production and if it is `/get<*>` the media URLs are.

#### R3 — 4 workspace pages are genuinely unreachable

`navcheck` finds 10 emitted workspace pages absent from `navigation.ts`. Six are reachable
another way; **four have no link anywhere in `src/`**:

| Route | Size | Note |
|---|---|---|
| `/workspace/engage/whatsapp/inbox` | 1837 lines | **Larger than the inbox that *is* in the sidebar** (`/workspace/engage/inbox`, 1489 lines). Two inbox implementations; the bigger one is unreachable. |
| `/workspace/engage/orders` | 532 lines | `/workspace/commerce` (153 lines) is the nav-visible commerce page. |
| `/workspace/engage/rcs/templates` | 224 lines | `rcs/send` is linked from `engage/channels`; `templates` is not linked from anywhere. |
| `/workspace/dashboard/secure-files` | 535 lines | No nav entry, no inbound link. |

That is ~3,100 lines of shipped, routable, unreachable UI. `navigation.ts`'s own header
states the invariant it is meant to hold — *"NOTHING IS UNREACHABLE. `getAllNavItems()`
returns the sidebar AND the settings tree"* — and there is a test on it. The test passes
because it checks nav entries resolve, not that pages are covered. **The missing assertion is
the reverse direction**, which is what `navcheck.js` now provides.

Reachable but not in the sidebar, for the record: `/workspace` and `/workspace/admin` and
`/workspace/settings/internal-agent` (linked from the `/workspace` hub), `/workspace/service`
(children are in nav, index is not), `/workspace/engage/rcs/send` (linked from
`engage/channels`).

#### R4 — `/workspace/seo/page/[id]/` is served as a real page

The export contains a directory literally named `[id]`, so
`out/workspace/seo/page/[id]/index.html` answers 200 at a URL containing brackets. It is the
dynamic template, not a page, and it should not be in the export.

#### R5 — The `/workspace` hub is linked from nowhere

`/workspace/index.tsx` is a module-picker listing Admin, Settings and the rest, and it is the
only route linking `/workspace/admin/` and `/workspace/settings/internal-agent/`. Nothing
links to *it* — not `navigation.ts`, not any page. Both of those pages therefore depend on a
hub an operator has to know to type.

#### R6 — Six mega-menu labels, one destination

On every public page the header offers **Submit Request, Request Amendment, Drop Docs, Leave
Review, Refer & Earn** and **Contact us** — all six resolve to `/contact/`. Documented as
deliberate in `Header.tsx:55` ("an invented path like `[retired public path b180810d]/submit-request` would
404"), and the reasoning is sound. It still means the menu makes six distinct promises and
keeps one, on all 871 pages.

#### R7 — `/blog/` renders all 746 posts in one document

`section.post-grid` is 80,895px tall; the page is 81,558px with 746 `h2`s and no pagination.
`/terms/` is 28,290px with 48 `h2`s.

#### R8 — Workspace pages ship the public marketing header

`out/workspace/engage/index.html` contains hrefs to `/`, `/anew/`, `/bharat-rx/`,
`/clear-closure/`, `/contact/`, `/dastavez/`, `/elsewhere/`, `/expo-week/`, `/grahak-os/`,
`[retired public path aaee9dd4]/` — the full product mega-menu — and **zero `/workspace/*` hrefs**, because the
operator shell is client-rendered behind the auth gate. An authenticated page's static
document is therefore entirely marketing navigation.

The zero is also why `routegraph` lists all 105 workspace routes as orphans: correct about
the crawlable graph, silent about operator reachability. That gap is what `navcheck.js` fills,
and the two scripts are meant to be read together.

### On your proposed tree

Measured against the build, the structure you sketched is already true with three exceptions:

- `workspace/*` — 105 pages, matches your list; every sub-tree you named exists.
- `api/*` and `r/*` — correctly outside the export, correctly excluded from the link check.
- `get/*` — **see R2**; the page and the rewrite are on the same prefix.
- `store/` — **see R1**; still at the root, still authenticated, needs to move under
  `workspace/commerce/`.
- `customerservice/`, `product-page/*` — already removed from the export and absent from the
  sitemap, as intended.

---

## Part 3 — What I propose next, and what I have deliberately not done

**No page source has been changed.** You asked for the mock first, band by band, so nothing
in `src/` is touched by this commit — only the three harnesses and this document.

The mock queue follows the band inventory above:

1. **Home band 2** — `section.home-flow` (650px): terminal left, sticky 380px copy column right.
2. **Home band 3** — `section.home-close` (552px): tinted lime panel, scroll-revealed rule, the page's only CTA.
3. **`rh-hero`** — the 269px band shared by **ten** pages; one mock, ten routes.

Each one gets the same treatment as `docs/home-review.html`: CSS, markup and every
measurement extracted from the real static export at generation time so the mock cannot drift
from the page, panels as live documents at 1280 and 390, before/after per finding.

Two items above are **decisions rather than defects** and are not mine to take:

- **R1/R2 path moves** — moving `/store` and resolving `/get` are routing changes with CDN
  and sitemap consequences.
- **R3 duplicates** — whether the 1837-line `whatsapp/inbox` replaces the 1489-line
  `engage/inbox` or gets deleted is a product call, and it is the larger file.
