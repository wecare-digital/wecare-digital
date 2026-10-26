'use strict';

/**
 * dotreview - the three remaining lime dots, mocked in their real surroundings.
 *
 * WHY. After 3B recoloured the terminal's window lights, three lime dots were left on the home
 * page and "update copy section of 2b dot in same way" did not say which. Guessing is the wrong
 * move here because two of the three are not decoration: they are the panel's only state signal,
 * and recolouring them spends the accent on chrome and leaves the meaning without a colour.
 *
 * So each one is shown where it actually lives, at 1:1, with its measured contrast against its
 * OWN background - which differs per dot and is the thing that decides the answer:
 *
 *   .wt-state-dot   on #3b271a  the brown title bar, beside "8 services · 1 foundation"
 *   .wt-foot-dot    on #000000  the black footer, beside "running" / "complete"
 *   .rp-mark-dot  on a tint   inside the hero pill, already one hue per rotating word
 *
 * Writes docs/dot-review.html, then docs/dot-mock/*.png and docs/dot-review.md via the same
 * render-to-PNG step the divider and accent mocks use, because a committed .html is served as
 * text/plain by GitHub and shows as source.
 *
 * Run: node tools/browser/dotreview.js
 */

const fs = require( 'fs' );
const path = require( 'path' );
const { launch } = require( './lib/browser' );

const DOCS = path.join( __dirname, '..', '..', 'docs' );
const HTML = path.join( DOCS, 'dot-review.html' );
const SHOTS = path.join( DOCS, 'dot-mock' );
const MD = path.join( DOCS, 'dot-review.md' );

/* ---------- contrast ---------- */
const luminance = hex => {
  const c = [ 1, 3, 5 ].map( i => parseInt( hex.substr( i, 2 ), 16 ) / 255 )
    .map( v => ( v <= 0.03928 ? v / 12.92 : Math.pow( ( v + 0.055 ) / 1.055, 2.4 ) ) );
  return 0.2126 * c[ 0 ] + 0.7152 * c[ 1 ] + 0.0722 * c[ 2 ];
};
const r2 = ( a, b ) => {
  const [ hi, lo ] = [ luminance( a ), luminance( b ) ].sort( ( x, y ) => y - x );
  return ( ( hi + 0.05 ) / ( lo + 0.05 ) ).toFixed( 2 );
};

const BAR = '#3b271a';
const BLACK = '#000000';
const LIME = '#d1f470';
const AMBER = '#f0a818';
const PURPLE = '#9849e8';
const GREEN = '#3da35a';

/* The title bar, rendered with a chosen state-dot colour. Values copied from
 * WorkflowTerminal.tsx rather than approximated: 47px tall, 11px lights, 6px state dot. */
const titleBar = ( dot, cls = '' ) => `
<div class="term">
  <div class="bar">
    <span class="light" style="--c:${AMBER}"></span>
    <span class="light" style="--c:${PURPLE}"></span>
    <span class="light" style="--c:${GREEN}"></span>
    <span class="bar-title">platform / production</span>
    <span class="bar-state"><i class="sdot ${cls}" style="--c:${dot}"></i>8 services · 1 foundation</span>
  </div>
  <div class="body">
    <span class="caret">&rsaquo;</span> One customer places an order.
    <div class="step"><i class="stepdot"></i><b>All services healthy</b> <span class="t">2.1s</span></div>
  </div>
  <div class="foot"><i class="fdot" style="--c:${LIME}"></i>complete<span class="fr">8 services · 1 retry absorbed</span></div>
</div>`;

/* The footer strip on black, rendered with a chosen foot-dot colour. */
const footStrip = ( dot, cls = '' ) => `
<div class="term">
  <div class="body compact">
    <div class="step"><i class="stepdot"></i><b>Payment captured</b> <span class="t">0.8s</span></div>
    <div class="step"><i class="stepdot"></i><b>Invoice issued</b> <span class="t">1.2s</span></div>
  </div>
  <div class="foot"><i class="fdot ${cls}" style="--c:${dot}"></i>complete<span class="fr">8 services · 1 retry absorbed</span></div>
</div>`;

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The three remaining lime dots — WECARE.DIGITAL review</title>
<style>
  :root{--ink:rgba(0,0,0,.898);--muted:rgba(0,0,0,.54);--line:#e5e7eb}
  *{box-sizing:border-box}
  body{margin:0;padding:48px 24px 96px;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:var(--ink);background:#fafafa}
  .wrap{max-width:1180px;margin:0 auto}
  h1{font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;letter-spacing:-1.2px;margin:0 0 16px}
  h2{font-size:26px;font-weight:700;letter-spacing:-.6px;margin:60px 0 6px;padding-top:24px;border-top:2px solid var(--line)}
  h3{font-size:16px;font-weight:700;letter-spacing:-.2px;margin:0}
  .lede{font-size:20px;line-height:1.4;letter-spacing:-.125px;margin:0 0 10px;max-width:76ch}
  .note{font-size:17px;line-height:1.55;color:var(--muted);max-width:78ch;margin:0 0 26px}
  code{background:#fff;border:1px solid var(--line);border-radius:5px;padding:1px 5px;font-size:.88em}
  .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}
  @media(max-width:1000px){.grid{grid-template-columns:1fr}}
  .card{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .card header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 18px;border-bottom:1px solid var(--line)}
  .tag{flex:none;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:4px 9px;border-radius:999px}
  .t-now{background:#f3f4f6;color:var(--muted)}
  .t-branch{background:#dbeafe;color:#1e40af}
  .t-rec{background:#d1f470;color:#1a3a2a}
  .t-no{background:#fee2e2;color:#991b1b}
  .frame{padding:22px 18px}
  .why{margin:0;padding:14px 18px 18px;border-top:1px solid var(--line);background:#fcfcfc}
  .why dt{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:rgba(0,0,0,.42);margin:0 0 4px}
  .why dd{margin:0 0 12px;font-size:15.5px;line-height:1.55}
  .why dd:last-child{margin:0}
  table{border-collapse:collapse;width:100%;margin:14px 0 0;font-size:15px}
  th,td{text-align:left;padding:8px 11px;border-bottom:1px solid var(--line)}
  th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:rgba(0,0,0,.42)}
  .sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:6px;border:1px solid rgba(0,0,0,.12)}
  .pass{color:#166534;font-weight:600}
  .callout{background:rgba(209,244,112,.22);border-inline-start:4px solid #d1f470;border-radius:8px;padding:18px 20px;margin:22px 0 0;max-width:88ch}
  .callout.warn{background:#fef2f2;border-inline-start-color:#dc2626}
  .callout p{margin:0 0 10px;font-size:17px;line-height:1.6}
  .callout p:last-child{margin:0}

  /* ---- the terminal, values from WorkflowTerminal.tsx ---- */
  .term{background:#000;border:1.5px solid rgba(255,255,255,.92);border-radius:14px;overflow:hidden}
  .bar{height:47px;display:flex;align-items:center;gap:8px;padding:0 15px;background:${BAR};border-bottom:1px solid rgba(209,244,112,.30)}
  .light{width:11px;height:11px;border-radius:50%;flex:0 0 auto;background:var(--c)}
  .bar-title{margin-inline-start:7px;color:rgba(255,255,255,.62);font-size:12.5px}
  .bar-state{margin-inline-start:auto;display:flex;align-items:center;gap:6px;color:rgba(255,255,255,.62);font-size:12.5px}
  .sdot{width:6px;height:6px;border-radius:50%;background:var(--c);flex:0 0 auto}
  .body{padding:16px 15px 18px;color:rgba(255,255,255,.62);font-size:13px;line-height:1.7;font-family:ui-monospace,monospace}
  .body.compact{padding:14px 15px}
  .caret{color:#d1f470}
  .step{position:relative;padding-inline-start:26px;margin-top:10px}
  .stepdot{position:absolute;inset-inline-start:0;top:5px;width:12px;height:12px;border-radius:50%;border:2px solid #d1f470;background:#d1f470}
  .step b{color:#fff;font-weight:600}
  .step .t{color:rgba(255,255,255,.46);font-size:12px}
  .foot{height:50px;padding:0 20px;display:flex;align-items:center;gap:6px;background:#000;border-top:1px solid rgba(209,244,112,.30);color:rgba(255,255,255,.54);font-size:12px}
  .fdot{width:5px;height:5px;border-radius:50%;background:var(--c);flex:0 0 auto}
  .fr{margin-inline-start:auto}

  /* ---- the hero pill ---- */
  .pill-row{display:flex;align-items:baseline;gap:10px;font-size:clamp(28px,3vw,40px);font-weight:600;letter-spacing:-1.2px;color:rgba(0,0,0,.95)}
  .pill{display:inline-flex;align-items:center;padding:2px 14px 4px;border-radius:999px;background:var(--tint)}
  .pill i{width:.33em;height:.33em;border-radius:50%;background:var(--dot);margin-inline-end:.33em;flex:0 0 auto}

  /* Pulse, for the option that asks for one. Opacity only - compositor, no layout. */
  .sdot.pulse,.fdot.pulse{animation:dp 2.4s ease-in-out infinite}
  @keyframes dp{0%,100%{opacity:.45}50%{opacity:1}}
  @media(prefers-reduced-motion:reduce){.sdot.pulse,.fdot.pulse{animation:none;opacity:1}}
</style>
</head>
<body>
<div class="wrap">

<h1>The three remaining lime dots</h1>
<p class="lede">After 3B recoloured the window lights, three lime dots are left. “Update the copy
section’s dot in the same way” did not say which, and they are not interchangeable — two of them
carry meaning, one is already a colour system of its own.</p>
<p class="note">Each is shown where it actually lives, at 1:1, with contrast measured against
<b>its own</b> background. That is what decides the answer: the title bar is
<code>${BAR}</code>, the footer is <code>#000</code>, and the same hue scores very differently
on each.</p>

<table>
<tr><th>Colour</th><th>on title bar ${BAR}</th><th>on footer #000</th></tr>
${[ [ 'lime #d1f470 (all three today)', LIME ], [ 'green #3da35a (third light)', GREEN ], [ 'amber #f0a818 (first light)', AMBER ], [ 'purple #9849e8 (second light)', PURPLE ] ]
    .map( ( [ label, hex ] ) => `<tr><td><span class="sw" style="background:${hex}"></span>${label}</td>
    <td class="${Number( r2( hex, BAR ) ) >= 3 ? 'pass' : ''}">${r2( hex, BAR )}:1</td>
    <td class="${Number( r2( hex, BLACK ) ) >= 3 ? 'pass' : ''}">${r2( hex, BLACK )}:1</td></tr>` ).join( '\n' )}
</table>

<h2>C · <code>.wt-state-dot</code> — the copy in the title bar</h2>
<p class="note">6px, beside “8 services · 1 foundation”, in the same 47px strip as the three
lights. <b>This is the one I think you meant</b> — it is the dot attached to copy, in the bar
you just recoloured.</p>

<div class="grid">
  <section class="card">
    <header><h3>C1 · lime — as it was</h3><span class="tag t-now">before</span></header>
    <div class="frame">${titleBar( LIME )}</div>
    <dl class="why"><dt>Contrast</dt><dd>${r2( LIME, BAR )}:1 — the strongest option.</dd>
    <dt>Against</dt><dd>It is now the only lime in a bar that no longer uses lime, so it reads as a leftover rather than a choice.</dd></dl>
  </section>

  <section class="card">
    <header><h3>C2 · green — matches the third light</h3><span class="tag t-rec">recommended · on the branch now</span></header>
    <div class="frame">${titleBar( GREEN )}</div>
    <dl class="why"><dt>Contrast</dt><dd>${r2( GREEN, BAR )}:1 — down from ${r2( LIME, BAR )}:1, well clear of 3:1.</dd>
    <dt>Why</dt><dd>No new colour value, and green is the one hue here that already means what the sentence says: <em>8 services healthy</em>.</dd></dl>
  </section>

  <section class="card">
    <header><h3>C3 · amber — matches the first light</h3><span class="tag t-branch">brighter</span></header>
    <div class="frame">${titleBar( AMBER )}</div>
    <dl class="why"><dt>Contrast</dt><dd>${r2( AMBER, BAR )}:1 — brighter than green.</dd>
    <dt>Against</dt><dd>Amber conventionally means <em>degraded</em>. On a line that says every service is healthy that is the wrong signal, whatever it measures.</dd></dl>
  </section>

  <section class="card">
    <header><h3>C4 · green, breathing</h3><span class="tag t-no">not advised</span></header>
    <div class="frame">${titleBar( GREEN, 'pulse' )}</div>
    <dl class="why"><dt>What it is</dt><dd>C2 with a 2.4s pulse.</dd>
    <dt>Against</dt><dd>Motion that starts by itself and never stops is WCAG 2.2.2 — the rule that already removed this panel’s terminal loop. A “live” dot that pulses forever on a static page is also claiming something the page is not doing.</dd></dl>
  </section>
</div>

<h2>E · <code>.wt-foot-dot</code> — beside “running” / “complete”</h2>
<div class="callout warn">
<p><b>This one I would leave.</b> It is not decoration: it reports live state, and it is making the
same claim as the lime step markers inside the panel, where lime means <em>this service ran</em>.</p>
<p>The window lights are chrome and can be any hue. These two are the panel’s only real signal —
recolouring them spends the accent on decoration and leaves the meaning without a colour of its
own. And it cannot be moved alone: the footer dot and the step dots have to agree, so changing one
is changing nine.</p>
</div>

<div class="grid">
  <section class="card">
    <header><h3>E1 · lime — as it is</h3><span class="tag t-rec">recommended</span></header>
    <div class="frame">${footStrip( LIME )}</div>
    <dl class="why"><dt>Contrast</dt><dd>${r2( LIME, BLACK )}:1 on black.</dd>
    <dt>Why keep</dt><dd>It matches the step dots above it, which is the whole point — one colour means “this happened”.</dd></dl>
  </section>

  <section class="card">
    <header><h3>E2 · green, with the steps left lime</h3><span class="tag t-no">breaks the pair</span></header>
    <div class="frame">${footStrip( GREEN )}</div>
    <dl class="why"><dt>Contrast</dt><dd>${r2( GREEN, BLACK )}:1 — fine on its own.</dd>
    <dt>Against</dt><dd>Look at the two lime step dots above it. The footer now disagrees with the steps it is summarising. To do this properly all nine markers move, and then the panel has no state colour left.</dd></dl>
  </section>
</div>

<h2>A · <code>.rp-mark-dot</code> — the hero pill</h2>
<div class="callout">
<p><b>Already a colour system, and it is the one 3B borrowed from.</b> This dot takes a different
hue for every rotating word, pairing the dot with a pale tint of the same hue:</p>
</div>
<div class="grid">
  <section class="card">
    <header><h3>A1 · as it is — one hue per word</h3><span class="tag t-rec">recommended</span></header>
    <div class="frame" style="display:flex;flex-direction:column;gap:14px">
      ${[ [ 'consumers', '#fef3c7', AMBER ], [ 'enterprises', '#ede9fe', PURPLE ], [ 'climate tech', '#e0f7c8', GREEN ], [ 'frontier tech', '#fee2e2', '#dc2626' ] ]
    .map( ( [ word, tint, dot ] ) => `<div class="pill-row">Everyday AI for <span class="pill" style="--tint:${tint};--dot:${dot}"><i></i>${word}</span></div>` ).join( '\n' )}
    </div>
    <dl class="why"><dt>Why leave it</dt><dd>Pinning it to one colour would break the word-to-hue pairing, and these four hues are where the title-bar lights got theirs — amber, purple and green are three of these four. It is already “in the same way”; it is the source.</dd></dl>
  </section>
  <section class="card">
    <header><h3>A2 · fixed green</h3><span class="tag t-no">loses the pairing</span></header>
    <div class="frame" style="display:flex;flex-direction:column;gap:14px">
      ${[ [ 'consumers', '#fef3c7' ], [ 'enterprises', '#ede9fe' ], [ 'climate tech', '#e0f7c8' ], [ 'frontier tech', '#fee2e2' ] ]
    .map( ( [ word, tint ] ) => `<div class="pill-row">Everyday AI for <span class="pill" style="--tint:${tint};--dot:${GREEN}"></span><span class="pill" style="--tint:${tint};--dot:${GREEN}"><i></i>${word}</span></div>`.replace( /<span class="pill" style="--tint:[^"]*"><\/span>/, '' ) ).join( '\n' )}
    </div>
    <dl class="why"><dt>Against</dt><dd>A green dot inside a red tint on “frontier tech”, and inside an amber tint on “consumers”. The dot and its pill stop being the same colour, which is the one rule that system has.</dd></dl>
  </section>
</div>

<div class="callout">
<p><b>What I would do: C2, and leave E and A alone.</b></p>
<p><b>C2</b> is on the branch now — green, matching the third light, because it was the only lime
left in a bar with no lime and green already means “healthy”. Reverting it is one line.</p>
<p><b>E</b> stays lime because it is state, not chrome, and it cannot move without taking the
eight step dots with it. <b>A</b> stays because it is the palette the lights were taken from — it
is already consistent, in the other direction.</p>
</div>

<p class="note" style="margin-top:34px">Say <b>C1</b>, <b>C2</b>, <b>C3</b> or <b>C4</b>, and
<b>E1</b>/<b>E2</b>, <b>A1</b>/<b>A2</b> if you want those moved too.</p>

</div>
</body>
</html>
`;

fs.mkdirSync( DOCS, { recursive: true } );
fs.writeFileSync( HTML, html );
console.log( `dot review -> ${HTML}  (${Math.round( html.length / 1024 )} kB)` );

/* ---------- render to PNGs + Markdown, so it opens on GitHub ---------- */
const CARDS = [
  'c1-lime-before', 'c2-green-recommended', 'c3-amber', 'c4-green-pulsing',
  'e1-lime-keep', 'e2-green-breaks-pair',
  'a1-hue-per-word', 'a2-fixed-green',
];

( async () => {
  fs.mkdirSync( SHOTS, { recursive: true } );
  const browser = await launch();
  const page = await browser.newPage( { viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 2 } );
  await page.goto( 'file://' + HTML, { waitUntil: 'load' } );
  await page.waitForTimeout( 700 );

  const cards = await page.$$( '.card' );
  for ( let i = 0; i < Math.min( cards.length, CARDS.length ); i++ ) {
    await cards[ i ].screenshot( { path: path.join( SHOTS, `${CARDS[ i ]}.png` ) } );
    console.log( `  ${CARDS[ i ]}.png` );
  }
  await ( await page.$( 'table' ) ).screenshot( { path: path.join( SHOTS, 'contrast-table.png' ) } );
  console.log( '  contrast-table.png' );
  await browser.close();

  const md = `# The three remaining lime dots

> Rendered from \`docs/dot-review.html\` by \`tools/browser/dotreview.js\`. GitHub serves raw
> \`.html\` as \`text/plain\`, so these PNGs are the openable version; the HTML has the pulsing
> option actually pulsing.

After 3B recoloured the window lights, three lime dots are left. *"Update the copy section's dot
in the same way"* did not say which — and they are **not interchangeable**. Two of them carry
meaning; one is already a colour system, and is the one 3B borrowed from.

Contrast is measured against **each dot's own background** — the title bar is \`${BAR}\`, the
footer is \`#000\`, and the same hue scores very differently on each.

![Contrast on both backgrounds](dot-mock/contrast-table.png)

---

## C · \`.wt-state-dot\` — the dot attached to copy in the title bar

6px, beside "8 services · 1 foundation", in the same 47px strip as the three lights.
**This is the one I think you meant.**

| | |
|---|---|
| ![C1](dot-mock/c1-lime-before.png) | ![C2](dot-mock/c2-green-recommended.png) |
| ![C3](dot-mock/c3-amber.png) | ![C4](dot-mock/c4-green-pulsing.png) |

- **C1 lime** — ${r2( LIME, BAR )}:1, strongest, but now the only lime in a bar that uses none.
- **C2 green** — ${r2( GREEN, BAR )}:1. No new colour, and green already means *healthy*, which is
  what the sentence says. **On the branch now.**
- **C3 amber** — ${r2( AMBER, BAR )}:1, brighter, but amber conventionally means *degraded* on a
  line claiming every service is healthy.
- **C4 pulsing** — motion that starts by itself and never stops is WCAG 2.2.2, the rule that
  already removed this panel's terminal loop.

## E · \`.wt-foot-dot\` — beside "running" / "complete"

| | |
|---|---|
| ![E1](dot-mock/e1-lime-keep.png) | ![E2](dot-mock/e2-green-breaks-pair.png) |

**I would leave this one.** It is not decoration — it reports live state and makes the same claim
as the lime step markers inside the panel, where lime means *this service ran*. Look at E2: the
footer now disagrees with the two lime step dots it is summarising. Doing it properly moves all
nine markers, and then the panel has no state colour left.

## A · \`.rp-mark-dot\` — the hero pill

| | |
|---|---|
| ![A1](dot-mock/a1-hue-per-word.png) | ![A2](dot-mock/a2-fixed-green.png) |

**Already a colour system, and the one the lights borrowed from** — amber, purple and green are
three of its four hues. Pinning it to one colour puts a green dot inside a red tint on "frontier
tech". It is already consistent, in the other direction.

---

## What I would do

**C2**, and leave **E** and **A** alone. C2 is on the branch now; reverting it is one line.

Say **C1 / C2 / C3 / C4**, plus **E2** or **A2** if you want those moved too.
`;

  fs.writeFileSync( MD, md );
  const total = fs.readdirSync( SHOTS ).reduce( ( s, f ) => s + fs.statSync( path.join( SHOTS, f ) ).size, 0 );
  console.log( `\n  ${MD}\n  ${fs.readdirSync( SHOTS ).length} PNGs, ${Math.round( total / 1024 )} kB\n` );
} )();
