---
inclusion: fileMatch
fileMatchPattern: ["src/pages/grahak-os/**", "src/components/**", "src/styles/**"]
---

# Public page design contract (/grahak-os)

Calibrated against notion.com by measuring the live site, not by eye. Values below
are what the page currently ships. Change them deliberately, not incidentally.

## Type ladder

Notion's ladder is counterintuitive: **the section h2 is heavier than the hero
h1** (700 vs 600). That is intentional — do not "fix" it.

| Role | Selectors | Spec |
|---|---|---|
| Hero h1 | `.hero-left h1` | `clamp(36px,4.3vw,60px)` / **600** / lh `1.04` / ls `-2.2px` / `rgba(0,0,0,.95)` |
| Section h2 | `.section-header h2`, `.api-info h2`, `.trust-heading` | `clamp(28px,3.2vw,40px)` / **700** / lh `1.08` / ls `-1.2px` / `rgba(0,0,0,.95)` |
| Card heading | `.pp-strip-title` (h3), `.trust-wordmark` | `22px` / **700** / lh `1.27` / ls `-0.25px` / `#000` |
| Body — one level only | `.hero-left p`, `.section-header p`, `.api-desc`, `.pp-strip-sub`, `.trust-subtext`, `.trust-caption` | `20px` / **400** / lh `1.4` / ls `-0.125px` / `rgba(0,0,0,.898)` |

### Why the section h2 is 40px and not 54px

This row used to read `clamp(32px,4.2vw,54px)` / lh `1.04` / ls `-1.875px`, which was
**not** what any page shipped — it resolved to 53.76px at 1280px and existed nowhere in
the codebase. Measuring all 15 public routes in a browser found `/grahak-os/` carrying
`clamp(32px,4.2vw,54px)` on four headings while twelve headings on ten other pages shared
`clamp(28px,3.2vw,40px)` / 700 / lh `1.08` / ls `-1.2px`. The site was reconciled onto the
40px formula rather than the 54px one, for a measurable reason: the hero h1 above is
`clamp(36px,4.3vw,60px)`, which resolves to **55.04px at 1280px**, so a 53.76px h2 sat
1.28px below the h1 and the hierarchy collapsed — the h2 being the heavier weight, it read
as the larger of the two. At 40px the gap is unambiguous and the 700-over-600 weight
inversion still reads as intended.

There are now **17 headings on one declaration**. Verify with the browser harness, which
measures the resolved clamp rather than the source string:

```
npm run build && node tools/browser/typecheck.js
```

`.lgd-h2` on `/terms/` and `/privacy/` stays at 28px — 71 numbered legal sections at 40px
would read as 45 page titles — and `.lgd-toc-title` (14px, uppercase, letter-spaced) is an
eyebrow that happens to be marked up as an `h2`, not a section heading. The harness reports
both rather than failing them.

**There is exactly ONE body level across the whole page.** Verify after any change:

```js
// in devtools, expect a single entry
var s={};['.hero-left p','.section-header p','.api-desc','.pp-strip-sub','.trust-subtext','.trust-caption']
 .forEach(q=>document.querySelectorAll(q).forEach(e=>{var c=getComputedStyle(e);
 s[c.fontSize+'/'+c.lineHeight+'/'+c.letterSpacing+'/'+c.color]=1}));Object.keys(s)
```

Eyebrows/labels are **not uppercase and not letter-spaced** — notion uses plain
`14px / 400 / rgba(0,0,0,.54)`. Do not add `text-transform:uppercase`.

## Palette

| Token | Use |
|---|---|
| `#1a1a1a` | Brand lockup (WECARE.DIGITAL), header + footer + dashboard sidebar |
| `#1a3a2a` | Dark green — icons, phone header, active states, accents |
| `#d1f470` | Lime — **our own surfaces only** (sent bubbles, active tab, hero pill) |
| `#ece5dd` | WhatsApp chat beige |
| `rgba(0,0,0,.898)` | Body text |
| `rgba(0,0,0,.95)` | Headings |

**Never put lime on a third-party mark.** The Meta card was lime and read as a
sticker we printed ourselves; a borrowed logo must look borrowed. A test pins this.

The inverse also holds: lime **is** the right green for our own marks. `BrandBadge`
— the pill on `/`, `/grahak-os` and `/vayulok` — fills with **`#d1f470` at full
strength and `#1a3a2a` type**, the same pair as `.tab.active` and `.msg.sent`, with
no border (neither of those carries one either). `#1a3a2a` on `#d1f470` is ~10:1.

There are exactly **three** lime treatments in this design language. Reach for one
of these rather than mixing a fresh tint or a new alpha — inventing an in-between
value is how `#f2fbf6` and `#fbfff0` got here in the first place:

| Treatment | Use | Examples |
|---|---|---|
| `#d1f470` fill + `#1a3a2a` type | our own surfaces, full voice | `.msg.sent`, `.tab.active`, `BrandBadge` |
| `rgba(209,244,112,.22)` fill | transient state, not identity | nav hover / active / expanded |
| `#1a3a2a` fill + `#d1f470` type | inverted, dark | `Layout.tsx` mode switch |

The badge began on the `.22` tint and was lifted, because that value composites to
`(245,253,224)` over white — a wash that reads as barely-not-white rather than as a
green badge. It is a **state** tint, not an identity one; that distinction is the
reason the two exist.

### Amber `#f0a818` is a DARK-SURFACE accent, not a rejected colour

This was recorded as "rejected at 2.04:1" and that number is real but incomplete: 2.04:1 is
amber **on white**. On the dark surfaces it is actually used on, `WorkflowTerminal.tsx` measures
it at **6.92:1**, **10.32:1** and **8.60:1** and documents each. So the rule is about the
backdrop, not the hex.

Where it is legitimately used, amber is a **shared token** — `AMBER = { tint: '#fef3c7', dot:
'#f0a818' }` in both `src/content/products.ts` and `src/content/customerservice.ts`, plus
`BlogIndexView.tsx`'s rotating words and the terminal's status lights.

The one questionable use is the rotating hero pill on `/grahak-os/`, where the amber dot sits on
its own pale `#fef3c7` tint and measures **1.83:1**. Three things keep that from being a defect
to close unilaterally:

1. The dot is `aria-hidden="true"` and purely decorative, with a real `.sr-only` list of the
   four channel names beside it — so WCAG 1.4.11 does not bind.
2. Its siblings are no better: green `#3da35a` on `#e0f7c8` measures **2.78:1**, also under 3:1.
   The dot/tint pairs were never designed to a contrast target; they are a notion-style pale
   tint with a saturated dot of the same hue.
3. Only `#dc2626` remains on the approved accent list as a fourth hue (3.95:1 on `#fee2e2`), so
   "fixing" it means changing the hero's colour and either diverging from the shared `AMBER`
   token or changing it across four surfaces.

**So it is an owner decision, not a bug.** If the answer is to move it, change the token in
`src/content/` rather than the page, or the page and the products grid stop matching.

**Settled further on 2026-09-29 by a tool that had no stake in it.** `tools/browser/lhcheck.js`
runs Lighthouse's axe-core pass over every public route, and on its first run it found four
contrast failures that five green suites and a hand-written focus-ring sweep had all walked
past — `.msg-time`, the breadcrumb's current crumb, and `.lgd-num`/`.lgd-toc-num` on the legal
pages. It does **not** flag the amber hero dot, and `/grahak-os/` now scores **accessibility
100**. So the dot is confirmed decorative rather than argued to be: `aria-hidden="true"` with a
real `.sr-only` channel list beside it. What remains is palette consistency across four files,
which is a design call and not an accessibility one.

### The logo weight is blocked by a test that exists on purpose

`wecaredigital.png` is 1080×1080 and 30,226 bytes, painted into a 60px box in the header and
44px in the footer — on **all 23 public routes**. It cannot be fixed from this repository, and
the reason is worth naming precisely so it stops being re-proposed:

- The CDN serves no derivatives. Measured: `?w=`, `?width=` and `?w=&h=&fit=` all return the
  same object, and an `Accept: image/webp` request still returns the same 30,226-byte PNG.
- **`src/test/BrandAssets.test.ts:126` pins `src/components/BrandLockup.tsx` to
  `${MEDIA_BASE}/${TRANSPARENT}`**, alongside `Layout.tsx` and `FloatingAgent.tsx`. Its comment
  says why: *"asserted so a later sweep does not 'finish the job' by replacing these too. On a
  white page the transparent mark is right and the opaque square would render as a visible
  white tile behind the logo."* Repointing the lockup at a repo-local copy fails that test, and
  the test is correct to fail it.
- `width={1080} height={1080}` are **deliberately** the intrinsic size, documented in
  `BrandLockup.tsx`: the rendered size is 60/54/44/40px across two variants and two
  breakpoints, and an attribute can hold one pair, so the intrinsic ratio is the only value
  true in every slot. Do not "fix" those either — without them the browser reserves 0×0 for the
  first element on every public page.

The remedy is a resized object uploaded to `s3://wecare-digital-get/o/stream/media/m/`, which
is the same constraint already recorded for `wd-brand-16x9.png` in `_app.tsx`. Until then this
is a known, measured, accepted cost — not an open defect to keep rediscovering.

Retired, do not reintroduce: `#2f6b52`, `#075e54`, `#f2fbf6`, `#fbfff0`,
`#1e293b` (as the code panel body). All five are now absent from the page — the
last holdouts were `#fbfff0` on three `:hover` rules and `#1e293b` on `.api-demo`,
cleared along with `#0f172a` and `#94a3b8` from the same slate ramp. **Both code
panels are `#000`.**

`#4b5563` is also gone: pill labels are `rgba(0,0,0,.54)`, the label value above.
It was the only blue-tinted grey in the page's own copy and read cooler than the
neutral body text beside it.

## Hairlines — weight carries meaning

`2px` means hoverable, `1px` means static, and the colour is always `#e5e7eb`.

| Weight | Elements | Why |
|---|---|---|
| `2px solid #e5e7eb` | `.pill`, `.pp-pill`, `.mockup-wrapper` | Each has a `:hover` that swaps the border to lime `#d1f470`; it needs the weight to register |
| `1px solid #e5e7eb` | `.trust-card` | Static, no hover |

**Do not "unify" the two weights** — the split is a signal, not drift. `.trust-card`
was the one real inconsistency and used `rgba(0,0,0,.1)`; it is `#e5e7eb` now.

`.code-body`'s `1.5px solid rgba(255,255,255,.92)` is exempt: it is the editor-pane
stroke on a black panel, documented at its own rule.

## Hero mockup geometry — these are solved together

The code panel is anchored `bottom:0`, so **its top edge is a function of wrapper
height**: `panelTop = wrapperHeight - panelHeight`. Change one value and you move
the panel over the message bubbles.

```
.mockup-wrapper  min-height:614px      <- sets where the panel's top edge lands
.chat-area       min-height:504px      <- sets phone height (phone = 62 header + chat)
.phone           width:56% max 320px, top:28px
.code-box        width:60% max 340px   <- 56+60 = 116%, so a ~90px lap
```

Constraints that produced those numbers:

1. `panelTop` must clear the bottom of the **lowest right-aligned bubble** (~300px)
   → `wrapperHeight >= 577`
2. The panel should overhang the phone by only ~20px → `phoneBottom ≈ wrapperHeight - 20`

**The two min-heights move together, always.** They were 590/480 until the code
panel's `"message"` line grew past the panel's 36-character measure and wrapped to
two lines, adding ~22px of panel height. Both constraints above are differential, so
the pair went to 614/504: `panelTop` holds because the wrapper grew by what the panel
grew, and the ~20px overhang holds because the phone grew by what the wrapper grew.
Move one alone and you either drop the panel onto the sent bubbles or leave it
hanging 44px past the phone.

**Corollary: line length in `.code-body` is layout, not content.** 340px fits 36
monospace characters at 14px. Every extra wrapped line is ~22px of panel height
pushing the top edge up into the thread, so a copy edit in that code sample is a
geometry change — re-measure with the rect-intersection snippet below.

**The thread order is load-bearing.** Both `.msg.sent` bubbles sit at the top,
above the panel's edge; the lapped band below holds only `.msg.received` and the
typing dots, which are left-aligned and clear the panel. `.msg.received` is capped
at `66%` (not 82%) so it cannot grow past the panel's left edge.

Do **not** solve a collision by left-aligning a sent bubble — that puts a business
reply on the customer's side of the thread. Verify with rect intersection:

```js
var C=document.querySelector('.code-box').getBoundingClientRect();
[].forEach.call(document.querySelectorAll('.chat-area .msg'),function(e){var R=e.getBoundingClientRect();
if(Math.min(R.right,C.right)-Math.max(R.left,C.left)>2&&Math.min(R.bottom,C.bottom)-Math.max(R.top,C.top)>2)
console.warn('covered:',e.textContent)});
```

## Floating widgets — the z-index ceiling

`#wecarewa-widget` (injected by the external `wecare-wa-widget.js`) is **64×64 at
`right:16px bottom:120px` with `z-index: 2147483647`** — the maximum 32-bit
integer. **Nothing can ever be stacked above it.**

Consequence: a floating panel must clear it **geometrically**, not by z-index. Any
overlap means a green circle punches through your UI. `.wc-langbar` therefore sits
at `right:96px; bottom:16px` with its width capped against `calc(100vw - 108px)`.

## styled-jsx traps that have each caused a real bug here

1. **`<style jsx>` only scopes JSX statically visible inside `return`.** Extract
   markup into a variable or child component and **all** its styles silently
   vanish. This broke the hero pill once.
2. **styled-jsx does not scope composite components.** `<Link className="ft-link">`
   rendered with zero styles. `Footer.tsx` uses plain anchors with a documented
   `eslint-disable @next/next/no-html-link-for-pages` for this reason.
3. **No backticks inside `<style jsx>` CSS comments.** The block is a template
   literal; one stray backtick ends it and the build fails with
   `Expected '</', got 'ident'`.
4. **Media queries come after base rules**, so a `font-size` in a breakpoint wins.
   When removing size overrides, confirm you did not strip the base rule too — the
   symptom is type silently falling back to an inherited 17px.
5. **Global unscoped CSS in `src/styles/*.css` leaks in** for generic class names:
   `.pill`, `.stat`, `.phone`, `.chat-area`, `.btn-primary`, `.sep`, `.msg-time`,
   `.ftr`, `.contact-name`, **`.tab`, `.code-block`, `.nav-item`, and bare `pre`**.
   `Layout.css:214` has `.layout ~ .ftr{position:fixed;bottom:0}` — a dormant
   landmine; `ftr` was dropped from Footer because of it.

   **Specificity is not the protection you think it is.** The jsx class means a page
   rule always outranks a global one — but only for properties the page rule actually
   declares. Anything left undeclared falls through, and the symptom is a change that
   looks like it never applied:

   | Leak | Global | Effect before it was closed |
   |---|---|---|
   | `.code-block` | `Pages.css:3228` `background:#1e1e1e` | API code pane rendered the **retired** slate over the panel's `#000`, so the black treatment looked like it had not shipped |
   | `.tab:hover` | `Layout.css:1815` `background:var(--hover)` = `rgba(209,244,112,.2)` | idle tabs lit up in a pale lime wash on hover |
   | `.code-block`, `pre` | same rule's 768px block | `width:calc(100% + 24px)`, negative side margins, squared corners, and an `::after` scroll gradient that fades in on hover |

   So when a restyle appears not to take, **check whether the property is declared at
   all** before suspecting the build, the cache or the service worker. Declare
   `background`, `width` and `border` explicitly on any element whose class name is
   generic, even where the value looks like a default.

## Routing traps

- `next.config.js` sets `trailingSlash: true` → URLs need the trailing slash.
- `src/pages/_app.tsx` has an **exact-match** public route allowlist (search for
  `const isPublic` — the line number has moved twice, so do not trust one here):
  `router.pathname === '/' || '/grahak-os' || '/vayulok' || '/contact-test'`.
  Any other route renders an empty body with HTTP 200. Add new public pages there
  or they will look like a 404 that isn't one. `[retired public path 1965ee0f]` and `/partners` were removed
  from this list when both pages were deleted in favour of absolute links to
  `www.wecare.digital` — re-adding a local route for either is what would make
  those links look broken again.
- ~~`_app.tsx` returns `null` until `mounted`, so the static export ships an **empty
  body** for `/grahak-os/`.~~ **Fixed.** The `if ( !mounted ) return null;` that ran
  before the public branch is gone. Measured against the built export on 2026-09-24, by
  stripping `<script>` from `<body>` and counting the remaining text:

  | Page | Body text | JSON-LD |
  |---|---|---|
  | `out/index.html` | 2,501 chars | 1 block |
  | `out/grahak-os/index.html` | 2,448 chars | 1 block |
  | `out/vayulok/index.html` | 489 chars | 1 block |

  A non-JS crawler now gets the copy, the headings and the structured data.
  **Open, but a content gap rather than a rendering one:** `/vayulok` ships an `h1` and
  no `h2` at all, which is why its body text is a fifth of the other two. That is the
  page's actual content, not a partial render.

  **THERE WAS A SECOND GATE, AND THIS TABLE COULD NOT SEE IT.** The `return null` above was
  only half the no-JS problem. `.anim` declared `opacity:0` as its **base** state, with
  `.show` added by an `IntersectionObserver` in a `useEffect` — so with JavaScript off all
  six sections of `/grahak-os/` rendered at `opacity:0` and the page was blank. Measured
  against the export with `javaScriptEnabled:false`.

  The reason it outlived the fix above is worth keeping: **opacity does not remove text from
  the DOM**, so the body-text counts in this very table stayed correct while nothing was
  visible. A text measurement cannot detect a paint bug, and every harness suite passed too —
  all five measure one settled state, with JS running.

  Fixed by inverting the default: CSS now ships the finished state (`.anim{opacity:1}`) and
  `.anim.is-armed` is what hides a section. The page arms itself only after confirming it can
  animate, and seeds whatever already intersects the viewport in the same React batch so the
  hero never blinks. **Do not move `opacity:0` back onto `.anim`.** Pinned by
  `GrahakOsPage.test.tsx`, and the honest check is a browser with scripting disabled, not a
  character count.

## Verifying a change

A dev server exiting without error proves nothing. Render it and measure:

```bash
rm -rf .next && npx next dev -p 3000
# browser: a plain F5 is enough
```

**The "always hard refresh" rule is retired.** That symptom was `public/sw.js`
serving `/_next/static/*.js` cache-first with no revalidation — styled-jsx ships
its CSS inside those chunks, so a cached chunk meant stale design, and
`Ctrl+Shift+R` only appeared to fix it because a hard reload is what bypasses a
service worker. Registration is production-only now (`a4963b02`). A worker already
installed in your browser needs **one** hard refresh to be torn down; after that
`F5` reflects edits. If styles still look stale, confirm DevTools → Application →
Service Workers lists none on `localhost:3000` before suspecting the CSS.

Gate before committing: `npx tsc --noEmit`, `npx vitest --run`, `npm run build`.

`src/test/GrahakOsPage.test.tsx` asserts on **source strings**, so any CSS value
change here breaks it by design — update the assertion and its comment, do not
loosen it. Several assertions exist specifically to stop a past decision being
reverted; each says why.

## Known open issues

- ~~Section rhythm is not implemented.~~ **It is.** `#touchpoint,#capabilities` sit
  on `#fafafa` at `width:100vw` with a centring negative margin, and `.pp-inner`
  carries the 1300px measure — see the `FULL-BLEED SECTIONS (pp-*)` block. The
  earlier `background:#fff` on those section classes is overridden by those id
  selectors, so grepping for `background:#fff` makes it look unimplemented when it
  is not. Rhythm today: hero white, touchpoint grey, api white, capabilities grey,
  why / trust / closer white.
- ~~`.why-section` has **no `max-width`** — measures ~1391px against `.api`'s 1300px.~~
  **Gone.** Re-measured 2026-09-24: neither `.why-section` nor `.why-item` exists
  anywhere in `src/` any more, so this entry described a class that had already been
  removed. Verified the general case instead, by parsing the styled-jsx of all three
  public pages and flattening `@media` blocks: **every centred container** (`margin:0
  auto`) on `/`, `/grahak-os` and `/vayulok` declares a `max-width`. The type-ladder rows
  above still name `.why-item strong` and `.why-item span`; treat those as historical.
  **Updated 2026-09-29:** the ladder and hairline tables no longer name dead selectors at all.
  `.capability-card` and `.cap-icon` went the same way as `.why-item` — the card grid became
  `.pp-strip`, which is borderless because it is not interactive — so the card-heading row now
  reads `.pp-strip-title` / `.trust-wordmark` and the body row names `.pp-strip-sub`. The
  devtools snippet above was querying three classes that match nothing, which made a
  one-body-level check pass by finding less than it thought.

- **`.trust-caption` is body, not a card heading.** It was listed on the card-heading rung while
  shipping `20px/400`. That is deliberate — the designation describes the logo above it rather
  than titling anything — so the contract row moved to match the code, not the other way round.

- **`.trust-wordmark` was three quarters of a rung.** Size, weight and tracking matched the
  card-heading row; `line-height` was never declared, so it inherited and measured **34.1px**
  against the rung's **27.94px**. Now declared. `.pp-strip-title` always had it, which is why
  the two card headings were 6px apart in line box while documented as one rung.

- **There is no CTA in `<main>`, and that is settled.** `/grahak-os/` has three focusable
  elements (the code-sample language tabs) and **zero links** inside `<main>`. That reads like
  an accessibility gap and is not one: `GrahakOsPage.test.tsx` pins it with
  `it( 'removes both added CTA buttons' )`, asserting `>Start with WhatsApp<`, `>Talk to us<`
  and `className="cta-actions"` are all absent. The hero leads on the rotating channel pill and
  the page routes through the header and footer instead. **Do not "fix" the missing CTA** — that
  test exists to stop exactly that. Reopening it is a product decision for the owner, not a
  defect to close.
- ~~`.page{overflow-x:hidden}` should be `clip`.~~ **Done, and done carefully.**
  `grahak-os` ships `overflow-x:hidden` as the base with an `@supports
  (overflow-x:clip)` block upgrading it — `clip` from Chrome 90 / Firefox 81 / Safari
  16, and anything older still needs `hidden` or the `width:100vw` full-bleed bands make
  the page horizontally scrollable. The two values are kept in **separate rules** on
  purpose: written as two declarations on one rule, a CSS minifier drops the first as
  dead. `/` and `/vayulok` never needed it — their only `overflow:hidden` uses are the
  rotating-word mask and the sr-only utility, so `.home-flow-copy`'s `position:sticky`
  has no scroll-container ancestor to break it.
- ~~`.pill` uses `font-size:var(--text-base)`, and a mobile breakpoint pushes it to
  20px.~~ **Both fixed.** `.pill` and `.pp-pill` are an explicit `17px`. The token
  was the real hazard: `--text-base` is declared as `16px` in `tokens.css` and
  `15px` in `Pages.css`, and only `Pages.css` is imported by `_app.tsx` — so the
  size was decided by import order, and importing `tokens.css` would have resized
  every pill. The `20px` was already dead: this TYPOGRAPHY CONTRACT block is later
  in source order at equal specificity, so its value had always won.
- `.usecase-pills` is a 3-column `max-content` grid, not wrapped flex, so the six
  use cases land 3 + 3 deterministically (2 columns at `=<767px`). Under flex they
  broke 4 + 2, and a tightened cap would have sat ~27px from the boundary — close
  enough for a copy edit or a fallback font to flip it back.
