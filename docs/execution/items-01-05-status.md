# Items 01–05 — what is complete, what is pending

Measured on the merged tree at `ae272065` (PRs #58, #59, #60 all merged), not asserted from PR
descriptions. Every number below came from a run on this tree.

**Gates on this tree:** 251/251 unit tests · `animcheck` 18/18 · `uicheck` 96/96 ·
`typecheck` 3/3 · `seocheck` 11/11 · `devicecheck` **270/270** · design drift OK · 33 token
tests · `tsc` clean · `homeprobe` 8/11.

---

## Scope correction that governs items 01, 02 and 05

**105 of 124 built routes render an Authenticator shell.** The dashboard is client-rendered
behind login, so those routes expose no content in the static export. They have no public top
section to add, nothing statically auditable, and the translation widget's dashboard path is
already handled separately (`.layout` root, `.main-content` carrying `data-wc-no-translate`).

**The addressable surface is 19 routes:** the 15 public ones plus `/404/`, `/blog/`, `/get/`,
`/offline/`. Every "complete" below means complete for those 19.

---

## 01 — Top section on all public and orphaned pages

**COMPLETE for the addressable surface.**

| | before | now |
|---|---|---|
| Routes missing a top section | 2 | **1** (`/offline/` only) |
| Routes missing header/footer/widget | 1 | **1** (`/offline/` only) |
| `<main>` landmark on `/grahak-os/` | **absent** | present |

The band itself was fixed on **all four** hero implementations, not just the home page — there is
no single component. With JavaScript disabled the rotating word measured `0px` on every one:

| Route | prefix | no-JS word width |
|---|---|---|
| `/` | `home-` | 0 → **278px** |
| `/grahak-os/` | `hero-` | 0 → **262px** |
| `/vayulok/` | `vl-` | 0 → **70px** |
| `/contact/`, `/terms/`, `/anew/` … 13 routes | `rh-` | 0 → **409 / 181 / 152px** |

Also: tracking moved to `-0.04em` on the three copies that still used `-2.2px` with
per-breakpoint overrides — the 2.75× optical swing.

### PENDING
- **`/offline/`** has no chrome and no top section. It is the PWA offline fallback, so shipping
  header/footer/widget assets there arguably defeats the point. **A decision nobody has made**,
  not an accident.
- The 105 auth-gated routes — out of scope by construction, see above.

---

## 02 — Translation

**The headline fix is complete.** The cause was not what the first census suggested.

`SupportWidget`'s `contentRoot()` resolved to `main`, and on a public page the header and footer
are **siblings** of `main`, not children. Measured across twelve routes: `root.contains(header)`
was **false on all twelve**. So the body translated while the navigation menu and the whole
footer stayed English. Root is now `#__next`.

| | before | now |
|---|---|---|
| Header inside the translation root | **false** on 12/12 routes | **true** |
| Footer inside the translation root | **false** on 12/12 routes | **true** |
| `aria-hidden` skips, public routes | 69 | **6** (all genuinely decorative) |
| `aria-hidden` skips, sitewide | 78 | **16** |
| Rotating words translated | 0 | **4–6 per page** |

The rotating words needed a new opt-in, `data-wc-translate="true"`, which beats `aria-hidden`
on a nearest-flag-wins basis. Both original rules were correct — rejecting `aria-hidden` keeps
decorative text out of a per-character billed batch, and the words carry `aria-hidden` so a
screen reader does not read the headline once per word. Together they produced a mixed-language
headline.

### PENDING — and one is a decision, not a bug
- **Attribute text is still never translated.** `aria-label`, `title`, `placeholder`, `alt` are
  not text nodes, so the walker cannot reach them: **147 strings on public routes, 1329
  sitewide**, of which **116 public are `aria-label`**. Screen-reader users therefore get English
  labels around translated content. Reaching it means translating attributes too, which adds
  ~1329 strings to a **per-character billed** API. **Cost decision for the owner.**
- **`BrandBadge` descriptor.** 16 nodes on public routes are skipped by
  `data-wc-no-translate`. **This is correct** — `BrandBadge.tsx:56` sets it so the *brand name*
  survives translation, and says so. But the descriptor shares the label — "Legal Stuff",
  "Customer service" — so it is collateral. Splitting the two touches a component on 14 pages.
  *(This corrects a claim in #59 that called the flag misapplied. It is not.)*
- **Dashboard routes**: `.main-content` is deliberately `data-wc-no-translate` so live
  operational data is never machine-translated. Sidebar and chrome do translate. Unchanged and
  intended.

---

## 03 — The prompt and the skill

**COMPLETE.**

- `.kiro/skills/new-public-page/SKILL.md` — the long form: mock-first method, the ten-state
  matrix, the device matrix, translation rules, structure requirements, gates, what to commit.
- `docs/NEW-PAGE-PROMPT.md` — the short, pasteable prompt, plus a table mapping each numbered
  instruction to the specific defect that justifies it.

---

## 04 — Legal clauses

**COMPLETE as drafted. NOT counsel-reviewed.**

`src/content/legal/terms.ts` gained two sections, and the source comment states plainly that
they need whoever signs off the rest of the document:

- **46 — Machine translation.** English prevails; translations are automatic and unreviewed; no
  warranty; discrepancies create no obligation. Plus the part specific to this site, which the
  census proved: **parts of a page may not translate at all**.
- **47 — Artificial intelligence and automated processing.** Output can be inaccurate or
  fabricated while appearing confident; it is not professional advice; consequential decisions
  require independent verification; a human remains responsible for decisions that materially
  affect a user.

Appended as 46 and 47 rather than inserted, because every section's `id` is its in-page anchor
and inserting would renumber up to six and break deep links. Verified: 47 sections render, both
new anchors resolve, `s45` intact.

### PENDING
- **Legal review.** The engineering facts in both clauses are measured; the legal effect of the
  wording is not something this repo can assert.

---

## 05 — Device, browser and viewport compatibility

**COMPLETE for the addressable surface, in Chromium.** `tools/browser/devicecheck.js` is new and
runs 18 routes × 15 postures = **270 combinations, all clean**, asserting per combination: no
horizontal overflow, the `h1` inside the viewport, the open menu ≥120px and not running off the
bottom, and every header tap target ≥44px.

| | before | now |
|---|---|---|
| Routes with horizontal overflow | 1 (`/contact/`, 11px @320) | **0** |
| Menu height at 653×280 | **0px** (computed `max-height` zero) | **140px** |
| Menu at 882×344 / 880×360 / 844×390 | 24 / 40 / 70px | **204 / 220 / 250px** |
| Route×posture combinations clean | — | **270/270** |

`/contact/` needed two rungs, and the second was derived rather than guessed: the widest phrase
is "amend a request" at 279px on the 36px floor, the pill adds ~0.52em, so required width is
`279·(F/36) + 0.52F = 8.27F`; a 280px viewport leaves 248px, giving `F ≤ 30.0`. 28px at ≤340px.

### Cross-browser — CLOSED for Chromium and Firefox, BLOCKED for WebKit

| Engine | Result | Notes |
|---|---|---|
| **Chromium** 153 | **270/270** | default |
| **Firefox** 155 (Gecko) | **270/270** | `--firefox`; zero failures, including every foldable posture |
| **WebKit** | **cannot run on this host** | see below |

Feature support confirmed directly in both engines that run, rather than assumed from
caniuse: `width:max-content`, `height:100dvh`, `ResizeObserver` and `text-wrap:balance` all
report `true` in Chromium **and** Firefox. Those are the four the fixes depend on.

### PENDING — WebKit, and it is an image problem not an install problem
- **WebKit will not launch here, and the reason is specific.** The host is Amazon Linux 2023,
  which ships **ICU 67**; the Playwright WebKit build links `libicudata.so.74`,
  `libicui18n.so.74` and `libicuuc.so.74`. It also wants GTK4, a full GStreamer stack,
  `libgraphene`, `libxslt`, `libopus` and `flite`. `playwright install-deps` only knows
  `apt-get` and fails on AL2023; `dnf` has no `flite` package at all. The fix is an
  Ubuntu-based image — `mcr.microsoft.com/playwright` — not a longer dnf line.
- **Consequence, stated plainly: iOS is unverified.** WebKit is Safari's engine and the engine
  behind *every* browser and WebView on iOS, so that is the platform this leaves open — not a
  minor third engine. `--webkit` is already wired into `devicecheck.js`, so closing it is one
  CI job on the right base image.
- **No real WebView test.** The matrix approximates it with `dvh` and a phone viewport. Android
  WebView is Chromium-based, so the Chromium pass covers its engine but not its chrome-inset or
  font-scaling behaviour; iOS `WKWebView` is WebKit and therefore blocked by the same item above.
- **Not checked at all:** print stylesheet, RTL (`dir="rtl"`), and real browser zoom at 200/400%
  as distinct from a narrow viewport.
- **105 auth-gated routes** are unverified for any of this, by construction.

---

## Still open across all items

| Item | Why it is open |
|---|---|
| Hero's no-JS tint and dot | Needs the closing band's `.is-armed` inversion applied to the hero. `homeprobe` 2 of its 3 reds. |
| Closing band's invisible tab stop | `.home-close-cta` is `opacity:0` while armed and stays focusable — the third `homeprobe` red. One property: `visibility`. |
| Rotation pause (WCAG 2.2.2) | 9.6s, unpausable. Hover+focus pausing adds no furniture; a visible control does. **Owner decision.** |
| 80px blank above the headline | Tuned around a deleted brand badge, never revisited. Cosmetic. **Owner decision.** |
| Attribute translation | ~1329 strings on a per-character billed API. **Cost decision.** |
| Sitewide fake `aggregateRating` + `foundingDate` | `_app.tsx:306-312` and `:252`, on 17 and 123 built pages. Google manual-action risk. Separate change, should not wait. |
| `.btn` missing `'Inter'` | Buttons render in the system face sitewide. |
| Four hero copies still exist | The fixes were ported to all four. Retiring the three inline copies onto `RotatingHero` is the durable fix; `animcheck` already asserts they animate identically, so it would hold the migration honest. |
