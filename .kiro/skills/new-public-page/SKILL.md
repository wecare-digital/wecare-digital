---
name: new-public-page
description: "Build or change a public page on wecare.digital to the standard the home band was held to — mock it before applying, measure every claim in a real browser, and verify it across mobile, foldable, webview, reduced-motion, no-JS and translated states. Use when creating a new public route, adding a top section, or changing shared chrome."
license: MIT
---

# New or changed public page

The house standard for public pages. It exists because a home-page audit found **seven
defects that every existing suite passed** — `animcheck` 18/18, `uicheck` 96/96, `typecheck`
3/3, `seocheck` 11/11, 251 unit tests, all green while the hero's rotating word rendered
blank on every single load. The suites all measured one settled state: JavaScript running,
motion allowed, viewport fixed at load. Every defect lived somewhere else.

**The rule this skill encodes: a page is not done when it looks right. It is done when the
states nobody looks at have been measured.**

---

## 0. Preconditions, and when to stop before starting

### If the brief still has brackets, stop and ask

`docs/NEW-PAGE-PROMPT.md` is a template. It has arrived pasted verbatim, brackets intact —
`Build [PAGE NAME] at [/route/]`, `What it is: [one sentence a visitor would understand]`.
The numbered process survives the paste; the brief does not. Page name, route, sub-line and
rotating words are product decisions and none of them is inferable from the repo.

Do not pick plausible values and proceed. §3 is an explicit *wait for approval*, so inventing
a brief spends the whole mock-and-assert cycle on the wrong page and the gate that exists to
catch it cannot — the reviewer is handed a faithful mock of something nobody asked for. Ask
for the five fields and stop.

### The toolchain the mock needs

Verified on a clean clone. Each of these blocked a real run, in this order:

```bash
npm install                      # root deps
npm run build                    # produces out/ — needed by §1, not only by §7
cd tools/browser && npm install  # separate manifest: playwright-core lives here
```

**`out/` is a precondition of §1, not a pre-commit gate.** §7 lists `npm run build` under
"gates to run before committing", which reads as *afterwards*. It is also the first step:
`lib/serve.js` resolves `OUT_DIR` to `<repo>/out` and **throws** `No export found at …` when
it is absent, so mock generation and every harness stop dead. `next.config.js` sets
`output:'export'` only when `NODE_ENV === 'production'`, so `next dev` never writes `out/`;
a build is the only way to get one. On this repo it emits 763 HTML files.

**`tools/browser` carries its own `package.json`.** A root `npm install` does not install
`playwright-core`, and the failure arrives as `Cannot find module 'playwright-core'` from
inside a harness rather than as an obviously missing install.

**Chromium is never downloaded.** `playwright-core` does not fetch browsers, by design.
`lib/browser.js` resolves one, preferring `/opt/playwright/chromium-<rev>` — `chromium-1232`
on this sandbox, and **the revision changes across sandbox resets, so never hardcode it**.
There is no system Chrome on this box. `CHROME=/path/to/chrome` overrides everything.

**Harnesses take an origin.** `BASE=http://localhost:3000 node tools/browser/pageaudit.js`
skips the static server, which matters because `out/` and `next dev` are two different
renders and a suite that only ever ran against `out/` has not tested what a developer sees.

## 1. Mock before you apply. Always.

Do not edit source to show someone a proposal. Generate a review page instead.

- **Harvest, never paste.** Extract CSS and markup from the real built export at generation
  time (`out/`), not by copying rules into a mock file. A hand-pasted mock is true exactly
  once; the day either source changes it shows the old design and says nothing. There is a
  working generator at `tools/browser/homereview.js` — copy its harvesting approach, but not
  its panels. Its own header states the frames are *live* ("the pill rotates and focus rings
  appear"); it predates the static-markup rule below and now contradicts it. Take the
  extract-from-`out/` machinery and emit static markup instead. It is also scoped to the top
  band alone, so a whole-page review means extending it section by section.
- **Panels are iframes at real widths**, only visually scaled. The frame must genuinely be
  1280 or 390 wide so `clamp()`, `vw` units, media queries and `position:fixed` all resolve
  as they would on a real screen. Rendering variants as divs in one document makes every
  viewport-relative unit wrong.
- **An iframe's height IS `100vh` inside it.** A 640px-tall panel showed a 320px menu where
  the live page gives 580px, because the rule was `calc(100vh - 320px)`. Use real viewport
  heights, not crops.
- **Emit panels as static markup. No JavaScript.** A mock whose panels are built by a script
  shows headings and nothing else in any viewer that does not run scripts — which is the
  exact defect class being documented.
- **Bake the settled state into "original" panels.** With scripting off, an un-hydrated hero
  renders its *defect*. A panel labelled "as it ships today" that shows the broken state is
  a lie. Server-rendered values plus the classes JS would add must be written into the markup.
- **Show the original first, at 1:1, labelled unmodified.** Then the proposal. Reviewers need
  the baseline more than they need the pitch.
- **If a state cannot be previewed faithfully, publish numbers instead.** Font fallback and
  `forced-colors` resolve against the operating system, so the build machine's rendering is
  not the reader's. A confident panel there is worse than a table.
- **Options are alternatives, and say so.** Label plainly that exactly one ships. Include a
  deliberately-wrong option only if you mark it "not a candidate".
- **Give the page a build stamp.** A cached copy is otherwise indistinguishable from a bug,
  and someone will report the cache as a defect.

## 2. Assert on the mock, do not look at it

Every before/after panel must be verified by reading computed style inside the frame. Looking
at it is not enough — this caught, in one project:

- a proposed fix that would have made a 200ms flash **permanent** (`position:static` alone
  turns a span into a non-replaced inline box whose `offsetWidth` is `0`, so the measuring
  effect wrote `width:0px`; it needed `display:inline-block`)
- injected fix CSS that **never applied**, because styled-jsx compiles `.x::before` to
  `.x.jsx-HASH::before` at (0,2,1) and the injection was (0,1,1)
- `\b` inside a JS template literal becoming a **backspace character**, so a class-strip regex
  silently stopped matching and every "before" panel showed the fixed state
- a CSS trim that dropped `*{box-sizing:border-box}`, reporting a 72px menu where the live
  page gives 40px

Assert **equality with live measurements**, not ranges. A range hides a fidelity drift; an
equality check fails the moment the mock stops matching the page.

## 3. The state matrix — the part that finds real defects

Run each of these. They are ordered by how many defects they have actually caught.

| State | How | What it catches |
|---|---|---|
| **No JavaScript** | omit the boot script / `javaScriptEnabled:false` | content that only exists after hydration |
| **First paint** | sample `requestAnimationFrame` from document start | width/height written by an effect after mount |
| **Reduced motion** | `reducedMotion:'reduce'` | intervals that never start, so nothing re-measures |
| **Resize after load** | `setViewportSize` post-load | values measured once and never again |
| **WCAG 1.4.12 text spacing** | inject `line-height:1.5;letter-spacing:.12em;word-spacing:.16em` | `overflow:hidden` on a JS-measured box. **Level AA** |
| **Translated** | see §5 | text that grows, and text that never translates |
| **Webfont swap** | block `fonts.googleapis.com`, compare | layout shift on every cold load |
| **`forced-colors: active`** | `forcedColors:'active'` | designs whose only cue is colour |
| **Dark mode** | `colorScheme:'dark'` | absent support, and absent *declaration* |
| **Keyboard** | walk `Tab` from load | focusable-but-invisible controls (`opacity:0` stays in the tab order) |

## 4. Device matrix — foldables are not optional

Run `node tools/browser/devicecheck.js` and require 100% — **18 routes × 15 postures = 270
combinations**, on at least two engines (see §7). It exists separately from `pageaudit.js`
because pageaudit sweeps every route at three *widths*, which is the right trade for a census
and structurally cannot see a viewport that is wide **and** short. Add new routes to its
`ROUTES` array by hand.

The failure mode that width-only testing cannot see is **wide AND short**. It is rare on a
phone and normal on a folded-landscape device.

```
phones      320×844 · 360×800 · 390×844 · 411×797 · 480×900
foldables   280×653  Galaxy Fold folded            653×280  ← folded landscape
            344×882  Z Fold cover                 882×344  ← cover landscape
            904×1084 Z Fold unfolded              1084×904
            360×880  Z Flip                        880×360  ← the common killer
            411×797  Pixel Fold outer              841×1010 inner
            540×720  Surface Duo one pane          720×540
            1114×705 Surface Duo spanned
            853×1280 Zenbook Fold                 1280×853
desktop     1280×900 · 1440×800 · 1920×1080
webview     390×844 with the OS chrome subtracted — use dvh, never vh
```

**Never subtract a magic number from the viewport.** A menu sized
`max-height:calc(100vh - 320px)` measured **0px** at 653×280 and 40px at 880×360. Anchor to a
real element: `calc(100dvh - 140px)` where 140 = the 108px header + 32px of air, both nameable.

**Height conditions need no width ceiling.** An existing rule in this repo guards the same
case with `@media (max-width:768px) and (max-height:500px)` — which misses 880 and 882 wide
entirely. Also honour `@media (vertical-viewport-segments: 2)`; there is precedent at
`src/styles/Layout.css:2204`, asserted by `BottomNav.test.tsx:140`.

Use `dvh`, not `vh`. `100vh` is the viewport with browser chrome *hidden*, so anything sized
to it is taller than what a phone visitor can see. Declare `vh` first as the fallback, `dvh`
second.

## 5. Translation — assume nothing is translated until measured

`SupportWidget` walks **text nodes** and rewrites `nodeValue`. Consequences, all measured
across 124 routes:

- **Attribute text is never translated.** `aria-label`, `title`, `placeholder`, `alt` are not
  text nodes. **1329 strings sitewide, 147 on public routes** stay English in every language —
  116 of them `aria-label`, so screen-reader users get English labels around translated text.
  If a string matters, it belongs in a text node or needs its own path.
- **`aria-hidden="true"` subtrees are skipped**, correctly — and a rotating headline word
  carries `aria-hidden` for an equally correct reason (so a screen reader does not read the
  headline once per word). The two combine into a **mixed-language headline**: the frame line
  translates, the word inside the pill does not. 78 nodes sitewide.
- **`data-wc-no-translate` on a brand lockup is correct — do not "fix" it.** `BrandBadge.tsx:56`
  sets it deliberately so the **brand name** survives translation, and says so in a comment. An
  earlier version of this skill called it a misapplied dashboard flag; that was wrong. The real
  and much smaller problem is that the descriptor shares the label — "Legal Stuff —
  WECARE.DIGITAL", "Customer service by WECARE.DIGITAL" — so the words around the brand name are
  collateral. If you need the descriptor translated, split it into its own element rather than
  removing the flag.
- **A translated word is wider.** "consumers" 278px → "उपभोक्ताओं" 317px, and Devanagari is
  taller at the same size. Any box with `overflow:hidden` and a JS-measured width will clip.
  `width:max-content` plus a `ResizeObserver` **on the text element, not its container**, is
  the pattern that survives it. Observing the container never fires or feeds itself.

- **A brand name must NOT translate, and a census cannot see that.** `pageaudit.js` counts
  what translates and what is skipped, which treats every translated node as a success. The
  opposite defect is invisible to it: `BrandLockup` renders "WECARE" and "DIGITAL" as two
  separate text nodes, neither was flagged, so the provider returned `نحن نهتم. رقمي` in
  Arabic and `डिजिटल` in Hindi — the wordmark came apart mid-brand on **every** route, header
  and footer, while the census read green. Use `tools/browser/translatecheck.js`, which fails
  on a translatable brand node and asserts in the same run that the header menu and footer
  still translate — because the failure mode of an exclusion is scope, and putting the flag on
  a container instead of the wordmark silently un-translates everything beneath it.
- **Proper nouns are the general case.** Author names, business names on a map card and brand
  eyebrows are all names, not prose. An author byline was the largest single source: **1276**
  occurrences across the exported blog. Prefer the flag on the element holding the name alone,
  never on a wrapper that also holds a date or an address — those should translate.
- **A name inside a sentence is a different problem.** 44 strings embed the brand in real
  prose ("WECARE.DIGITAL is not an emergency service…"). Flagging those would stop a genuine
  sentence translating, so `translatecheck.js` reports them without failing. The visible
  symptom is inconsistency rather than breakage: the provider may render the name in one
  language and pass it through in another.

Verify with the census in `tools/browser/pageaudit.js`, which reimplements the walker's filter
exactly and reports per route what would translate, what would be skipped, and why. **That
filter now exists in three places** — `SupportWidget.tsx`, `pageaudit.js` and
`translatecheck.js`. If `acceptNode` changes, all three change together.

## 5b. Right-to-left: `lang` and `dir` are not independent

The catalogue offers Arabic, Persian, Hebrew, Urdu, Pashto and Sindhi — measured against the
live endpoint and captured in `docs/execution/language-catalogue.json`, 76 entries of which six
are RTL — so RTL is one button press away. `_document.tsx` declares `dir="ltr"` and
`SupportWidget` rewrites it; `rtlcheck.js` asserts the result across **125 routes × 6
viewports**, on Chromium and Firefox.

**Write logical properties in stylesheets, and nothing physical.** All 216 physical direction
declarations in `src/styles/*.css` are gone, and `src/test/LogicalDirectionCss.test.tsx` fails
if one returns. That static check exists because `rtlcheck.js` cannot reach inside an
authenticated view — the export ships auth shells, so real tables and side panels never render
— and whether a rule names a physical edge is a property of the text, not the render.

**Converting a base rule while leaving a media-query override physical is WORSE than leaving
both.** The logical form gains a `:lang()` specificity class (see below) and beats the
override. Either convert both or neither.

**Write logical properties, but know they do not ship.** `inset-inline-end`,
`padding-inline-start` and `border-inline-start` are the right thing to write and appear **zero
times in `out/`**. Lightning CSS downlevels each one for the browserslist targets into a pair
of rules keyed on `:lang()`:

```css
.wc-langbar:not(:is(:lang(ar),:lang(he), … )){left:auto;right:20px}
.wc-langbar:is(:lang(ar),:lang(he), … )){left:20px;right:auto}
```

So in the shipped stylesheet **mirroring is driven by `lang` while the bidi algorithm is driven
by `dir`**. Set one without the other and you get half a mirror. This cost a debugging round:
the first version of `rtlcheck.js` set only `dir`, reported the language widget still pinned
right, and blamed the CSS — the gate was wrong, not the fix. Anything that changes direction
must write both attributes, and any harness that simulates RTL must do the same.

**Two things have no logical form.** `transform-origin` takes no logical keyword, so a
`scaleX` reveal needs an explicit `[dir='rtl']` override or it wipes in from the edge the
reader finishes on. And a glyph drawn from borders — a tick, a chevron — is an *orientation*,
not a side: mirroring a tick produces a backwards mark that reads as an error cross.

**Measure the mirror, do not trust it.** `rtlcheck.js` asserts the widget actually *moved*
between LTR and RTL, because every other assertion in it passes on a page that ignored the
direction entirely — which is exactly the state it exists to catch. It also compares each
block element's distance from the inline-**start** edge across directions, which is what
catches a physical property that was never converted; four classes of false positive had to be
excluded first — inline-level boxes and their subtrees, repeated class names, viewport-relative
offsets (the scrollbar switches sides), and `el.className` on an SVG.

**A third-party wrapper can override the document.** Amplify's `ThemeProvider` renders
`dir="ltr"` on its own wrapper, which left the dashboard *half*-mirrored — boxes unmoved while
`[dir='rtl']` rules still matched, putting the nav panel at `left:-504px` on 105 routes. An
author declaration beats the attribute's presentational hint.

**Arabic typography cannot be measured on the build host.** `fc-list` reports **zero** families
with Arabic or Devanagari coverage against 82 with Latin, so both render as `.notdef` and every
glyph measures the same width. Chromium's CDP is actively misleading here:
`CSS.getPlatformFontsForNode` answers "Inter" for an Arabic string because it names the family
*requested*, not the one that supplied the glyphs. `rtlcheck.js` prints the coverage counts at
startup so a mirrored-Latin pass can never be read as an Arabic pass.

**Do not split a sentence around a pinned word.** It assumes the word keeps its position
through translation, and it does not: English puts a preposition before the noun while Hindi,
Bengali, Tamil, Telugu, Marathi, Gujarati and Urdu put the object first with a postposition
after it. Wrapping "Bharat" in `data-wc-no-translate` stranded the postposition and appended the
name in source order — grammatically broken in all seven, measured against the live endpoint.
Either pin the whole line or let the whole line translate.

## 6. Structure every public page must carry

- Shared chrome: `header` + `footer` + support widget. Being public is the gate — a new public
  route picks all three up from `_app.tsx`'s public branch; do not add a per-page flag.
- A **top section after the header**: one visible `<h1>` inside `<main>`, above the fold,
  saying what the page is about. No CTA, no price, no conversion furniture in that band — the
  action belongs further down. Only the words, the rotation and the sub-line change per page.
- Exactly one `<h1>`. Section headings on the site's `clamp(28px,3.2vw,40px)/700/1.08/-1.2px`
  rung — verify with `typecheck.js`, do not invent a rung.
- Tracking in `em`, never `px`, on any fluid (`clamp`) font size. A fixed px value against a
  fluid size made optical tightness swing 2.75× across breakpoints.
- Declare the font stack on the component. Do not inherit `body` and hope: with the global rule
  absent, an inheriting lockup fell to a serif while a declaring headline stayed on Inter.
- Touch targets ≥ 44px. The site's CTA is `min-height:52px`.
- `opacity:0` does **not** remove an element from the tab order. Use `visibility:hidden` or
  `inert` for anything hidden pending a reveal.
- Entrance animations are **opt-in**: ship the readable final state in CSS and let JavaScript
  add a class that hides the start state. Never the reverse. See the `.is-armed` pattern in
  `src/pages/index.tsx` — and note it missed focus, so cover that too.
- Content that moves automatically for over 5s needs a pause mechanism (**WCAG 2.2.2**).

## 7. Gates to run before committing

```bash
npm run build                          # produces out/, which every harness reads
npx tsc --noEmit
npx vitest run
node tools/browser/animcheck.js        # rotating-headline reflow, 21 viewports
node tools/browser/homeprobe.js        # the degradation states from §3
node tools/browser/pageaudit.js        # structure + translation census + overflow
node tools/browser/designsweep.js      # buttons/fields/scrollbar vs the home CTA, 20 routes
node tools/browser/devicecheck.js      # 18 routes × 15 postures, incl. foldables
node tools/browser/devicecheck.js --firefox   # same matrix on Gecko
node tools/browser/translatecheck.js   # brand name must NOT translate; header/footer must
node tools/browser/rtlcheck.js         # mirrored layout, 125 routes × 6 viewports
node tools/browser/rtlcheck.js --firefox      # same sweep on Gecko
node tools/browser/uicheck.js
node tools/browser/typecheck.js
node tools/browser/seocheck.js
python3 scripts/check_design_drift.py
python3 -m pytest tests/test_design_drift_tokens.py -q
```

**Run at least two engines.** Chromium and Firefox both pass 270/270 today. `--webkit` is wired
up but **cannot run on this host**: Amazon Linux 2023 ships ICU 67 while the Playwright WebKit
build links ICU 74, and it also wants GTK4, GStreamer, libgraphene, libxslt, libopus and flite —
`playwright install-deps` only knows apt-get, and AL2023 has no flite package. It needs an
Ubuntu-based image (`mcr.microsoft.com/playwright`). **Until it runs, iOS is unverified**, because
WebKit is Safari's engine and the engine behind every browser and WebView on iOS. Treat that as a
known task, not a caveat.

**`devicecheck.js` was absent from this list until two sessions added it independently**, while
§4 devoted a whole section to the matrix it enforces. The gate sat on disk and the checklist did
not name it, so a full pass of §7 returned green having never loaded a foldable posture — this
skill's own failure mode turned on itself. Two people finding the same omission separately is the
argument for keeping it listed.

**`designsweep.js` is the one that compares pages with each other**, which is the axis every other
gate structurally cannot see. It harvests the home CTA's computed style at run time and holds every
other route's buttons, fields and scrollbar against it. The whole suite above ran green while the
dial-code half of the phone field shipped with **none of its own styling** on four public surfaces,
while the scrollbar was lime in Firefox and a 5px grey hairline in Chromium, while one `!important`
in `Layout.css` overrode the 17px field size four components declare, and while `/account/sign-in/`
and `/get/` had no way at all to ask for another OTP. Those are cross-page facts; a per-page
assertion cannot reach any of them. It also carries a hardcoded `ROUTES` array, so add a new public
route by hand.

A new page adds a route to `pageaudit.js`'s discovery automatically, but **`devicecheck.js`
carries a hardcoded `ROUTES` array** — 18 routes against 126 page files, and a new public route
is invisible to it until you add it there by hand. If the page introduces a state the matrix in
§3 does not cover, add the assertion — a green suite that cannot see a defect is worse than no
suite, because it is cited as evidence.

## 8. What to commit

- **Source, tests and the mock in one reviewable change.** Add the assertion that pins the fix,
  and write *why* in the test body — the failure mode, not the expectation.
- **Comments are the artefact the next change is based on.** One band accumulated eleven
  incorrect comment claims: a measured width that was wrong by 8px, "five words" for a set of
  four, a rung described as nonexistent that existed, and an attribution to the wrong
  stylesheet. Re-measure anything a comment asserts, in the same commit.
- **Never commit to the default branch.** Push a feature branch and open a PR into it
  (`gh api repos/{owner}/{repo}/pulls -f head=... -f base=...`). **This repo's default branch
  is `stack`, not `main`** — confirmed against the remote, and it is what a fresh clone checks
  out. So `base=stack`, and the branch you must not commit to is the one you are already on.
  Verify rather than assume: `gh api repos/{owner}/{repo} --jq .default_branch`.
- `gh pr create` and the other `gh pr` / `gh issue` subcommands are GraphQL-backed and fail in
  this sandbox. Use `gh api` REST endpoints.
- **State what is not fixed.** Name the defects left open and why, and name what you did not
  check — print, RTL, real browser zoom — so the gap is visible rather than implied.
- **Regenerating a mock after applying its fixes invalidates it.** It harvests the built
  export, so its "before" panels pick up the fix and stop reproducing anything. Either keep the
  pre-fix mock as the evidence or say plainly in the PR that it no longer demonstrates.
