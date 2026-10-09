# The new-page prompt

Paste the block below when you want a new public page, or a change to an existing one. It is
self-contained: the procedure below records the mock, verification and review requirements.

Replace the bracketed parts. Delete any line that does not apply — but delete it knowingly,
because each one is there because something shipped broken without it.

---

## Copy from here

```
Build [PAGE NAME] at [/route/].

What it is: [one sentence a visitor would understand]
Top-section sentence: [the one line under the headline, or "you write it, propose options"]
Rotating words, if any: [word, word, word, word]  — audiences or fields, never service names
Primary action: [none / where it goes] — the top band carries no CTA and no price by default

Follow the procedure in this document. Specifically:

1. MOCK FIRST, do not touch src/. Generate a review page the way
   tools/browser/homereview.js does — harvest CSS and markup from the built export, never
   paste rules into a mock. Panels are iframes at real widths (1280, 390) and real viewport
   heights, emitted as static markup so the page needs no JavaScript to view. Show the
   original at 1:1 first, labelled unmodified, then the proposal. Give it a build stamp.

2. ASSERT ON THE MOCK, do not eyeball it. Read computed style inside each frame and check
   equality with live measurements, not ranges. If a "before" panel does not reproduce the
   defect, the mock is broken — say so rather than shipping it.

3. Show me the mock and WAIT. Do not apply anything until I pick.

4. After I approve, apply it and prove it with the state matrix:
   no JavaScript · first paint (sample rAF from document start) · prefers-reduced-motion ·
   resize after load · WCAG 1.4.12 text spacing (line-height 1.5, letter-spacing .12em,
   word-spacing .16em) · translated · webfont blocked · forced-colors · dark mode ·
   Tab from load (opacity:0 stays focusable)

5. Device matrix — run `node tools/browser/devicecheck.js` and require 100%:
   280×653 and 653×280 · 344×882 and 882×344 · 360×880 and 880×360 · 904×1084 · 841×1010 ·
   540×720 and 720×540 · 853×1280 · 320×844 · 390×844 · 1280×900 · 1920×1080
   The wide-and-short postures are the ones that find bugs. Use dvh, never vh. Never subtract
   a magic number from the viewport — anchor to a real element and name it in a comment.

6. Translation — run `node tools/browser/pageaudit.js` and account for every skipped node:
   the page must translate its header menu, its footer and its own body. Attribute text
   (aria-label, title, placeholder) is NOT reachable by the walker — if a string matters, it
   belongs in a text node. aria-hidden subtrees need data-wc-translate="true" to be included.

7. Structure: shared header + footer + widget (automatic for a public route), a <main>
   landmark, exactly one visible <h1> inside it above the fold, section h2 on the
   clamp(28px,3.2vw,40px)/700 rung, tracking in em not px, tap targets ≥44px, font stack
   declared on the component rather than inherited.

8. Gates, all green before you commit:
   npm run build && npx tsc --noEmit && npx vitest run
   node tools/browser/{animcheck,homeprobe,pageaudit,devicecheck,uicheck,typecheck,seocheck}.js
   python3 scripts/check_design_drift.py
   python3 -m pytest tests/test_design_drift_tokens.py -q

9. Commit source + tests + mock together on a feature branch and open a PR into the default
   branch. Never commit to the default branch. In the PR: a before→after table of measured
   numbers, and an explicit list of what you did NOT fix and what you did NOT check.

10. Re-measure anything a comment asserts, in the same commit. Stale comments are how the next
    change goes wrong.
```

## To here

---

## Why each numbered item exists

Not decoration — every one of these maps to something that shipped broken on this site while
every suite was green.

| Item | What it caught |
|---|---|
| 1 — harvest, don't paste | A hand-pasted mock kept showing an old design after the source changed, and said nothing. |
| 1 — real viewport heights | A 640px-tall panel showed a 320px menu where the live page gives 580px, because an iframe's height *is* `100vh` inside it. |
| 1 — static markup, no JS | A mock whose panels were script-built showed headings and nothing else in a viewer that does not run scripts — the exact defect class it documented. |
| 2 — assert, don't eyeball | Caught a proposed fix that would have made a 200ms flash **permanent**, injected CSS that never applied because of styled-jsx specificity, and a `\b` in a template literal becoming a backspace so every "before" panel rendered the fixed state. |
| 4 — no-JS / first paint | A rotating word rendered `0px` wide on **all four** hero implementations: ~200ms every load, permanent with scripts off. |
| 4 — reduced motion + resize | A pill held a width measured at the old viewport for good, clipping 96px — 35% of the word. |
| 4 — WCAG 1.4.12 | 78.8px, 22% of a word, clipped by a reader's own letter-spacing. Level **AA**. |
| 5 — wide and short | A menu with a computed `max-height` of **zero** at 653×280, and 40px at 880×360. Every width-only check passed. |
| 5 — derive, don't guess | A 32px font step fixed 320px and still overflowed 7px at 280px. The right value came from arithmetic: `279·(F/36) + 0.52F ≤ 248` → `F ≤ 30`. |
| 6 — translation | The header menu and footer **never translated on any public page**, because the walk started at `main` and they are siblings of it. |
| 7 — `<main>` landmark | `/grahak-os/` shipped with no `<main>` at all, so assistive tech had nothing to skip to. |
| 9 — say what you did not check | Every "done" claim in this project that turned out to be wrong was a claim nobody had measured. |
| 10 — re-measure comments | Eleven incorrect comment claims accumulated in one band, including a width wrong by 8px and a font rung described as nonexistent that existed. |
