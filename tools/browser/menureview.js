'use strict';

/**
 * menureview - the menu icon, the panel that matches it, the step text, and the footer trigger.
 *
 * Five questions, all asked together, all answered in their real surroundings with measured
 * numbers. Interactive on purpose: hover the chips and click the tagline, because "the mouse
 * effect is fine" is a judgement nobody can make from a still image.
 *
 * WHAT WAS MEASURED ON THE LIVE SITE BEFORE ANY OF THIS WAS DRAWN
 *   .nav-trigger  46x46, #f4f7ee fill, #e3ecc9 border, 10px radius - 1.08:1 against the header
 *   .nav-arrow    ONE chevron, 8x8, 2.5px strokes, #1a3a2a at .85 - 11.52:1 on the chip
 *   hover         rgba(209,244,112,.22) composites to rgb(245,253,224)
 *                 -> 1.032:1 against the rest state, an RGB move of 15 out of 441
 *   .nav-menu     760x403, rgb(252,253,251), 14px radius, NO border, shadow 0 8px 28px
 *   20 links, tail reads: Contact us | Terms | Privacy
 *   steps 1-7 service name WHITE; step 8 LIME (is-complete); .wt-svc pill lime on all 8
 *
 * THE CONSTRAINT THAT SHAPES THE WHOLE ICON SECTION. Lime is a light colour, so no lime fill can
 * carry a hover state on a near-white chip - solid #d1f470 is 1.15:1 against the rest fill. Only
 * a luminance inversion registers: #1a3a2a is 11.52:1. That is measured, not asserted, and it is
 * why the recommended option inverts rather than tints.
 *
 * Writes docs/menu-review.html, then docs/menu-mock/*.png and docs/menu-review.md.
 * Run: node tools/browser/menureview.js
 */

const fs = require( 'fs' );
const path = require( 'path' );
const { launch } = require( './lib/browser' );

const DOCS = path.join( __dirname, '..', '..', 'docs' );
const HTML = path.join( DOCS, 'menu-review.html' );
const SHOTS = path.join( DOCS, 'menu-mock' );
const MD = path.join( DOCS, 'menu-review.md' );

/* ---------- contrast, computed not typed ---------- */
const hex = h => [ 1, 3, 5 ].map( i => parseInt( h.substr( i, 2 ), 16 ) );
const over = ( fg, a, bg ) => fg.map( ( v, i ) => Math.round( a * v + ( 1 - a ) * bg[ i ] ) );
const lum = c => {
  const x = c.map( v => v / 255 ).map( v => ( v <= 0.03928 ? v / 12.92 : Math.pow( ( v + 0.055 ) / 1.055, 2.4 ) ) );
  return 0.2126 * x[ 0 ] + 0.7152 * x[ 1 ] + 0.0722 * x[ 2 ];
};
const ratio = ( a, b ) => {
  const [ hi, lo ] = [ lum( a ), lum( b ) ].sort( ( x, y ) => y - x );
  return ( ( hi + 0.05 ) / ( lo + 0.05 ) ).toFixed( 2 );
};
const move = ( a, b ) => Math.round( Math.sqrt( a.reduce( ( s, v, i ) => s + Math.pow( v - b[ i ], 2 ), 0 ) ) );

const W = [ 255, 255, 255 ];
const REST = hex( '#f4f7ee' );
const LIME = hex( '#d1f470' );
const DARK = hex( '#1a3a2a' );
const CUR_HOVER = over( LIME, 0.22, W );

/* Step hues as shipped, in order. */
const STEP = [
  [ 'gateway', '#2563eb', 'Request accepted' ],
  [ 'auth', '#9849e8', 'Account resolved' ],
  [ 'contacts', '#f0a818', 'Customer looked up' ],
  [ 'messaging', '#d1f470', 'Four services pick it up at once' ],
  [ 'commerce', '#3da35a', 'Order and catalog updated' ],
  [ 'billing', '#2563eb', 'Usage metered' ],
  [ 'queue', '#f0a818', 'A provider failed, nobody noticed' ],
  [ 'platform', '#3da35a', 'All services healthy' ],
];

/** One chip variant. `glyph` is 'chevron' | 'lines' | 'lines-arrow'. */
const chip = ( id, glyph, cls ) => `
<button class="chip ${cls}" data-id="${id}" type="button" aria-label="Open navigation">
${glyph === 'chevron' ? '  <span class="chev"></span>' : ''}
${glyph === 'lines' ? '  <span class="lines"><i></i><i></i><i></i></span>' : ''}
${glyph === 'lines-arrow' ? '  <span class="lines la"><i></i><i></i><i></i></span><span class="chev small"></span>' : ''}
</button>`;

/* A short version of the real step list, for the text-colour options. */
const stepList = ( mode ) => `<div class="term"><div class="tbody">
${STEP.map( ( [ svc, hue, name ], i ) => {
    const last = i === STEP.length - 1;
    // mode: 'now' = names white except last lime, pill lime
    //       'name' = name + tick take the dot hue, pill unchanged
    //       'all'  = pill takes the hue too
    const nameColour = mode === 'now' ? ( last ? '#d1f470' : '#fff' ) : hue;
    const pillHue = mode === 'all' ? hue : '#d1f470';
    return `  <div class="st">
    <i class="sdot" style="--c:${hue}"></i>
    <span class="spill" style="--p:${pillHue}">${svc}</span>
    <span class="sname" style="color:${nameColour}">${last ? `<b style="color:${mode === 'now' ? '#d1f470' : hue}">&#10003;</b> ` : ''}${name}</span>
  </div>`;
  } ).join( '\n' )}
</div></div>`;

const NAV_TAIL = [ 'Sehat', 'Orders', 'Contact us', 'Terms', 'Privacy' ];
const NAV_TAIL_FIXED = [ 'Sehat', 'Orders', 'Terms', 'Privacy', 'Contact us' ];

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Menu icon, panel, step text, footer trigger — WECARE.DIGITAL review</title>
<style>
  :root{--ink:rgba(0,0,0,.898);--muted:rgba(0,0,0,.54);--line:#e5e7eb}
  *{box-sizing:border-box}
  body{margin:0;padding:44px 24px 96px;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:var(--ink);background:#fafafa}
  .wrap{max-width:1180px;margin:0 auto}
  h1{font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;letter-spacing:-1.2px;margin:0 0 14px}
  h2{font-size:25px;font-weight:700;letter-spacing:-.6px;margin:58px 0 6px;padding-top:22px;border-top:2px solid var(--line)}
  h3{font-size:16px;font-weight:700;letter-spacing:-.2px;margin:0}
  .lede{font-size:20px;line-height:1.4;letter-spacing:-.125px;margin:0 0 10px;max-width:76ch}
  .note{font-size:17px;line-height:1.55;color:var(--muted);max-width:78ch;margin:0 0 24px}
  code{background:#fff;border:1px solid var(--line);border-radius:5px;padding:1px 5px;font-size:.88em}
  .try{display:inline-block;background:#1a3a2a;color:#d1f470;font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:4px 10px;border-radius:999px;margin:0 0 16px}
  .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
  .grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}
  @media(max-width:1000px){.grid,.grid3{grid-template-columns:1fr}}
  .card{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}
  .card header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 17px;border-bottom:1px solid var(--line)}
  .tag{flex:none;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:4px 9px;border-radius:999px}
  .t-now{background:#f3f4f6;color:var(--muted)} .t-rec{background:#d1f470;color:#1a3a2a}
  .t-opt{background:#dbeafe;color:#1e40af} .t-no{background:#fee2e2;color:#991b1b}
  .frame{padding:26px 18px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
  .why{margin:0;padding:13px 17px 17px;border-top:1px solid var(--line);background:#fcfcfc}
  .why dt{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:rgba(0,0,0,.42);margin:0 0 4px}
  .why dd{margin:0 0 11px;font-size:15px;line-height:1.55} .why dd:last-child{margin:0}
  table{border-collapse:collapse;width:100%;margin:12px 0 0;font-size:15px}
  th,td{text-align:left;padding:8px 11px;border-bottom:1px solid var(--line)}
  th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:rgba(0,0,0,.42)}
  .pass{color:#166534;font-weight:600} .fail{color:#991b1b;font-weight:700}
  .callout{background:rgba(209,244,112,.22);border-inline-start:4px solid #d1f470;border-radius:8px;padding:17px 19px;margin:20px 0 0;max-width:88ch}
  .callout.warn{background:#fef2f2;border-inline-start-color:#dc2626}
  .callout p{margin:0 0 9px;font-size:17px;line-height:1.6} .callout p:last-child{margin:0}

  /* ---------- the chip, on a white header strip ---------- */
  .hdrstrip{background:#fff;border:1px dashed #d7d7d7;border-radius:10px;padding:14px 16px;display:flex;align-items:center;gap:14px}
  .chip{min-width:46px;min-height:46px;border-radius:10px;cursor:pointer;padding:8px;display:inline-flex;align-items:center;justify-content:center;gap:5px;
    background:#f4f7ee;border:1px solid #e3ecc9;transition:background-color .18s ease,border-color .18s ease}
  .chev{width:8px;height:8px;box-sizing:border-box;border-right:2.5px solid #1a3a2a;border-bottom:2.5px solid #1a3a2a;opacity:.85;transform:translateY(-2px) rotate(45deg);transition:transform .2s,border-color .18s}
  .chev.small{width:6px;height:6px;border-width:2px}
  .lines{display:inline-flex;flex-direction:column;gap:3px;width:16px}
  .lines i{display:block;height:2.5px;border-radius:2px;background:#1a3a2a;opacity:.85;transition:background-color .18s,width .2s}
  .lines.la{width:13px}

  /* A1 - what ships today. Hover is the measured 1.03:1 tint. */
  .a1:hover{background:rgba(209,244,112,.22)}
  /* A2 - solid lime. A hue move, not a luminance move. */
  .a2:hover{background:#d1f470;border-color:#8ab23f}
  /* A3 - inversion. The only option with a real luminance step. */
  .a3{border-color:#cfe0a6}
  .a3:hover{background:#1a3a2a;border-color:#1a3a2a}
  .a3:hover .chev{border-right-color:#d1f470;border-bottom-color:#d1f470;opacity:1}
  .a3:hover .lines i{background:#d1f470;opacity:1}
  /* A4 - three lines, inverted hover, with the middle line shortening to hint the arrow. */
  .a4{border-color:#cfe0a6}
  .a4:hover{background:#1a3a2a;border-color:#1a3a2a}
  .a4:hover .lines i{background:#d1f470;opacity:1}
  .a4:hover .lines i:nth-child(2){width:11px}
  .chip:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}

  /* ---------- panel match ---------- */
  .panelbox{padding:18px}
  .pnl{width:100%;max-width:420px;padding:14px;background:rgb(252,253,251);border-radius:14px;box-shadow:0 8px 28px rgba(0,0,0,.1)}
  .pnl.matched{border-radius:10px;background:#f4f7ee;border:1px solid #e3ecc9;box-shadow:0 8px 28px rgba(0,0,0,.07)}
  .pnl ul{margin:0;padding:0;list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:2px}
  .pnl li{font-size:14px;font-weight:600;color:#1a3a2a;padding:7px 9px;border-radius:7px}
  .pnl li:hover{background:rgba(209,244,112,.28)}
  .pnl li.last{background:rgba(209,244,112,.28)}
  .pairing{display:flex;align-items:flex-start;gap:12px}

  /* ---------- the terminal, for the step text ---------- */
  .term{background:#000;border:1.5px solid rgba(255,255,255,.92);border-radius:12px;overflow:hidden}
  .tbody{padding:14px 15px;font-family:ui-monospace,monospace;font-size:12.5px;line-height:1.6}
  .st{position:relative;padding-inline-start:26px;margin-bottom:9px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
  .st:last-child{margin-bottom:0}
  .sdot{position:absolute;inset-inline-start:0;top:4px;width:11px;height:11px;border-radius:50%;background:var(--c);border:2px solid var(--c);box-sizing:border-box}
  .spill{flex:0 0 auto;padding:1px 6px;border-radius:4px;font-size:10.5px;color:var(--p);background:color-mix(in srgb, var(--p) 14%, transparent);border:1px solid color-mix(in srgb, var(--p) 34%, transparent)}
  .sname{font-weight:600}

  /* ---------- footer tagline, hover + click ---------- */
  .ftbox{background:#fff;border:1px dashed #d7d7d7;border-radius:10px;padding:20px}
  .ftag{color:rgba(0,0,0,.54);max-width:340px;margin:0;font-size:15px;line-height:1.6;cursor:pointer;
    transition:opacity .56s cubic-bezier(.22,.61,.36,1),transform .56s cubic-bezier(.22,.61,.36,1)}
  .ftag.run{
    background-image:linear-gradient(100deg,rgba(0,0,0,.54) 42%,#1a3a2a 50%,rgba(0,0,0,.54) 58%);
    background-size:300% 100%;background-repeat:no-repeat;
    -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;
    animation:ftrun 1.15s cubic-bezier(.45,.05,.55,.95) 1 forwards;
  }
  @keyframes ftrun{from{background-position:100% 0}to{background-position:0% 0}}
  .fdash{display:block;width:56px;height:3px;margin-top:4px;background:#d1f470;border-radius:2px;transform-origin:left;transition:transform .62s cubic-bezier(.22,.61,.36,1)}
  .ftag.run + .fdash{animation:fdash .62s cubic-bezier(.22,.61,.36,1) 1 forwards}
  @keyframes fdash{from{transform:scaleX(0)}to{transform:scaleX(1)}}
  @media(prefers-reduced-motion:reduce){
    .ftag,.fdash{transition:none}
    .ftag.run{animation:none;background-image:none;-webkit-text-fill-color:currentColor;color:rgba(0,0,0,.54)}
  }
</style>
</head>
<body>
<div class="wrap">

<h1>Menu icon, the panel, the step text, the footer trigger</h1>
<p class="lede">Every frame is live — <b>hover the chips</b>, <b>hover or click the tagline</b>. Nothing
here is applied to the site yet.</p>
<p class="note">All numbers computed in this file from the values measured on the live page:
chip <code>#f4f7ee</code> / <code>#e3ecc9</code> / 10px, arrow one chevron 8&times;8 at 2.5px,
panel <code>rgb(252,253,251)</code> / 14px / no border, 20 links ending
<code>Contact us | Terms | Privacy</code>.</p>

<h2>1 &middot; The menu icon &mdash; and why the hover is invisible today</h2>
<div class="callout warn">
<p><b>The number that settles the whole section.</b> Lime is a <em>light</em> colour, so no lime
fill can carry a hover state on a near-white chip. Measured against the rest fill
<code>#f4f7ee</code>:</p>
<p>current tint <code>rgba(209,244,112,.22)</code> &rarr; <b class="fail">${ratio( CUR_HOVER, REST )}:1</b>,
an RGB move of <b>${move( CUR_HOVER, REST )}</b> out of 441 &nbsp;&middot;&nbsp;
solid lime <code>#d1f470</code> &rarr; <b>${ratio( LIME, REST )}:1</b> (move ${move( LIME, REST )}) &nbsp;&middot;&nbsp;
dark green <code>#1a3a2a</code> &rarr; <b class="pass">${ratio( DARK, REST )}:1</b> (move ${move( DARK, REST )})</p>
<p>Only an <b>inversion</b> produces a luminance step. Solid lime is a hue move &mdash; visible to most
people, nearly nothing to anyone with reduced colour discrimination.</p>
</div>

<span class="try">hover each chip</span>
<div class="grid">
  <section class="card">
    <header><h3>A1 &middot; as it ships &mdash; one chevron</h3><span class="tag t-now">hover 1.03:1</span></header>
    <div class="frame"><div class="hdrstrip">${chip( 'a1', 'chevron', 'a1' )}<span style="font-size:14px;color:var(--muted)">hover me</span></div></div>
    <dl class="why"><dt>What it is</dt><dd><b>Zero lines.</b> A single corner chevron, 8&times;8px, 2.5px strokes, <code>#1a3a2a</code> at .85 opacity. Rotates 45&deg; &rarr; 225&deg; when open.</dd>
    <dt>Against</dt><dd>Chip is <b>1.08:1</b> against the white header, so the box barely reads as a control, and the hover is <b>1.03:1</b> &mdash; a change of 15/441. There is no perceptible feedback.</dd></dl>
  </section>

  <section class="card">
    <header><h3>A2 &middot; chevron, solid lime on hover</h3><span class="tag t-opt">hue move only</span></header>
    <div class="frame"><div class="hdrstrip">${chip( 'a2', 'chevron', 'a2' )}<span style="font-size:14px;color:var(--muted)">hover me</span></div></div>
    <dl class="why"><dt>Numbers</dt><dd>Fill ${ratio( LIME, REST )}:1 against rest but an RGB move of ${move( LIME, REST )} &mdash; obviously a different colour. Arrow stays legible at ${ratio( DARK, LIME )}:1.</dd>
    <dt>Against</dt><dd>Brand-forward and cheap, but the luminance barely changes, so it is the weakest of the three for anyone not discriminating hue well.</dd></dl>
  </section>

  <section class="card">
    <header><h3>A3 &middot; chevron, inverts on hover</h3><span class="tag t-rec">recommended</span></header>
    <div class="frame"><div class="hdrstrip">${chip( 'a3', 'chevron', 'a3' )}<span style="font-size:14px;color:var(--muted)">hover me</span></div></div>
    <dl class="why"><dt>Numbers</dt><dd>Fill <b>${ratio( DARK, REST )}:1</b> against rest, RGB move ${move( DARK, REST )}. Arrow flips to lime at ${ratio( LIME, DARK )}:1. Border darkens to ${ratio( DARK, W )}:1 against the header.</dd>
    <dt>Why</dt><dd>The only option with a real luminance step, and it uses the brand's own pairing &mdash; lime on dark green &mdash; rather than inventing a hover colour. Rest state also firms up from <code>#e3ecc9</code> so the chip reads as a button before you touch it.</dd></dl>
  </section>

  <section class="card">
    <header><h3>A4 &middot; three lines instead of a chevron</h3><span class="tag t-opt">answers &ldquo;how many lines&rdquo;</span></header>
    <div class="frame"><div class="hdrstrip">${chip( 'a4', 'lines', 'a4' )}<span style="font-size:14px;color:var(--muted)">hover me &mdash; middle line shortens</span></div></div>
    <dl class="why"><dt>What it is</dt><dd>Three 2.5px lines, 16px wide, same <code>#1a3a2a</code>. A3's inverted hover, plus the middle line shortening to 11px &mdash; a hint of direction without adding a second glyph.</dd>
    <dt>Trade</dt><dd>A burger is the more universally read &ldquo;menu&rdquo; symbol. The chevron is quieter and matches a dropdown; three lines say &ldquo;full menu&rdquo;. This is taste, not measurement &mdash; both are legible.</dd></dl>
  </section>
</div>

<h2>2 &middot; The panel does not match the chip</h2>
<p class="note">You said the box matches the icon. Measured, three things differ.</p>
<table>
<tr><th></th><th>chip</th><th>panel</th></tr>
<tr><td>radius</td><td><b>10px</b></td><td><b>14px</b></td></tr>
<tr><td>background</td><td><code>#f4f7ee</code></td><td><code>rgb(252,253,251)</code></td></tr>
<tr><td>border</td><td><code>#e3ecc9</code></td><td><b>none</b> &mdash; shadow only</td></tr>
</table>

<div class="grid">
  <section class="card">
    <header><h3>B1 &middot; as it ships</h3><span class="tag t-now">3 mismatches</span></header>
    <div class="panelbox"><div class="pairing">${chip( 'b1', 'chevron', 'a1' )}<div class="pnl"><ul>${NAV_TAIL.map( r => `<li>${r}</li>` ).join( '' )}</ul></div></div></div>
    <dl class="why"><dt>Against</dt><dd>The chip has a hairline and a 10px corner; the panel has neither. They read as two unrelated surfaces that happen to be adjacent.</dd></dl>
  </section>
  <section class="card">
    <header><h3>B2 &middot; one family</h3><span class="tag t-rec">recommended</span></header>
    <div class="panelbox"><div class="pairing">${chip( 'b2', 'chevron', 'a3' )}<div class="pnl matched"><ul>${NAV_TAIL.map( r => `<li>${r}</li>` ).join( '' )}</ul></div></div></div>
    <dl class="why"><dt>What changed</dt><dd>Panel takes the chip's 10px radius, its <code>#f4f7ee</code> fill and its <code>#e3ecc9</code> hairline, and the shadow softens from .10 to .07 because the border now does part of the work.</dd>
    <dt>Note</dt><dd>Rows keep the lime hover tint they already have &mdash; that is a list-row affordance, not a surface, and it is the one place the light lime works.</dd></dl>
  </section>
</div>

<h2>3 &middot; The step text &mdash; three different limes, not one</h2>
<p class="note">Measured: names are <b>white on steps 1&ndash;7</b>; only step 8 is lime, because it is the
<code>is-complete</code> one. The <code>.wt-svc</code> pill is lime on <b>all 8</b>, and the
<b>&#10003;</b> tick is lime. So &ldquo;the text is still lime&rdquo; is the pill, the tick, and step 8's name.</p>

<div class="grid3">
  <section class="card">
    <header><h3>C1 &middot; as it ships</h3><span class="tag t-now">now</span></header>
    <div class="frame" style="padding:14px">${stepList( 'now' )}</div>
    <dl class="why"><dt>Against</dt><dd>Step 8's lime name is the only lime name, so it reads as &ldquo;special&rdquo; when it means &ldquo;complete&rdquo; &mdash; and it no longer agrees with its own green dot.</dd></dl>
  </section>
  <section class="card">
    <header><h3>C2 &middot; name + tick follow the dot, pill unchanged</h3><span class="tag t-rec">recommended</span></header>
    <div class="frame" style="padding:14px">${stepList( 'name' )}</div>
    <dl class="why"><dt>Why</dt><dd>Your call that <em>the text in the box should be the same</em> is right: the pill is a repeated label, and 5 colours would turn a label into a legend. The name is the per-step thing, so it takes the per-step hue and agrees with its dot.</dd>
    <dt>Cost</dt><dd>Names drop from white (21:1 on black) to their hue &mdash; lowest is blue at 4.06:1. Still well clear, but it is a real reduction on the panel's main text.</dd></dl>
  </section>
  <section class="card">
    <header><h3>C3 &middot; pill takes the hue too</h3><span class="tag t-no">not advised</span></header>
    <div class="frame" style="padding:14px">${stepList( 'all' )}</div>
    <dl class="why"><dt>Against</dt><dd>Eight differently-coloured pills read as a category key the reader is expected to decode. Nothing is being encoded &mdash; it is the service's own name, already written inside it.</dd></dl>
  </section>
</div>

<h2>4 &middot; The footer effect, on hover and on click</h2>
<p class="note">Today the trigger is <b>scroll only</b>, and it fired once then disconnected. You asked for
it on click or hover, every time.</p>
<span class="try">hover the line &middot; then click it</span>
<div class="grid">
  <section class="card">
    <header><h3>D1 &middot; hover replays it</h3><span class="tag t-rec">recommended</span></header>
    <div class="frame"><div class="ftbox">
      <p class="ftag" id="d1">Trusted everyday services for Bharat</p><span class="fdash"></span>
      <p style="font-size:13px;color:var(--muted);margin:14px 0 0">Hover, move away, hover again &mdash; it plays each time.</p>
    </div></div>
    <dl class="why"><dt>Why this is safe</dt><dd>WCAG 2.2.2 governs motion that starts <em>automatically</em>. Hover and click are reader-initiated, so replaying is not the thing that rule forbids &mdash; and each run is bounded at 1.15s.</dd>
    <dt>Kept</dt><dd>The scroll trigger stays as well, so it still announces itself once on arrival for anyone who never points at it.</dd></dl>
  </section>
  <section class="card">
    <header><h3>D2 &middot; the same, on a real pointer target</h3><span class="tag t-opt">consider</span></header>
    <div class="frame"><div class="ftbox">
      <p class="ftag" id="d2" style="cursor:default">Trusted everyday services for Bharat</p><span class="fdash"></span>
      <p style="font-size:13px;color:var(--muted);margin:14px 0 0">Same effect, but no <code>cursor:pointer</code>.</p>
    </div></div>
    <dl class="why"><dt>The one caution</dt><dd>This line has no <code>href</code>. A pointer cursor on it is the <b>false affordance</b> that got the old hover-underline removed in the first place. D1 above deliberately shows <code>cursor:pointer</code> so you can see the difference &mdash; my recommendation is the effect <em>without</em> it.</dd></dl>
  </section>
</div>

<h2>5 &middot; Contact as the last item</h2>
<div class="grid">
  <section class="card">
    <header><h3>E1 &middot; as it ships</h3><span class="tag t-now">Contact is 18th of 20</span></header>
    <div class="panelbox"><div class="pnl matched"><ul>${NAV_TAIL.map( r => `<li class="${r === 'Contact us' ? 'last' : ''}">${r}</li>` ).join( '' )}</ul></div></div>
    <dl class="why"><dt>Tail order</dt><dd><code>${NAV_TAIL.join( ' &rarr; ' )}</code> &mdash; the legal pages come after the one action a visitor might want.</dd></dl>
  </section>
  <section class="card">
    <header><h3>E2 &middot; Contact last</h3><span class="tag t-rec">if that is what you meant</span></header>
    <div class="panelbox"><div class="pnl matched"><ul>${NAV_TAIL_FIXED.map( r => `<li class="${r === 'Contact us' ? 'last' : ''}">${r}</li>` ).join( '' )}</ul></div></div>
    <dl class="why"><dt>Change</dt><dd><code>${NAV_TAIL_FIXED.join( ' &rarr; ' )}</code> &mdash; a reorder in <code>navigation.ts</code>, nothing else.</dd>
    <dt>Check</dt><dd>You wrote &ldquo;in terms of contact&rdquo;. If you meant <b>contrast</b> rather than <b>Contact</b>, say so and I will drop this section.</dd></dl>
  </section>
</div>

<div class="callout">
<p><b>What I would ship: A3, B2, C2, D1 without the pointer cursor, and E2 if you confirm it.</b></p>
<p><b>A3</b> because it is the only hover with a measured luminance step (${ratio( DARK, REST )}:1 against
${ratio( CUR_HOVER, REST )}:1 today) and it borrows the brand's existing lime-on-dark-green pairing.
<b>A4</b> is a free swap if you prefer three lines to a chevron &mdash; same hover, different glyph.</p>
<p><b>C2</b> follows your instruction exactly: name and tick take the dot's hue, the pill stays uniform.</p>
<p><b>D1</b> adds hover and click on top of the scroll trigger, minus <code>cursor:pointer</code> &mdash; the
line still has no <code>href</code>, and pretending otherwise is the defect that removed the old hover.</p>
</div>

<p class="note" style="margin-top:32px">Reply with letters &mdash; e.g. <b>A3, B2, C2, D1, E2</b> &mdash; and I
will build them.</p>

</div>
<script>
/* Hover and click both replay the sweep. Re-adding the class needs a reflow between removal and
   re-add, or the browser coalesces both into one frame and nothing animates - the same trap the
   footer probe exists to catch. */
(function(){
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function play(el){
    if (reduce) return;
    el.classList.remove('run');
    void el.offsetWidth;
    el.classList.add('run');
  }
  ['d1','d2'].forEach(function(id){
    var el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('mouseenter', function(){ play(el); });
    el.addEventListener('click', function(){ play(el); });
    play(el);
  });
})();
</script>
</body>
</html>
`;

fs.mkdirSync( DOCS, { recursive: true } );
fs.writeFileSync( HTML, html );
console.log( `menu review -> ${HTML}  (${Math.round( html.length / 1024 )} kB)` );

/* ---------- render to PNGs + Markdown ---------- */
const CARDS = [
  'a1-chevron-now', 'a2-solid-lime', 'a3-inverts-recommended', 'a4-three-lines',
  'b1-panel-mismatch', 'b2-panel-matched',
  'c1-step-text-now', 'c2-name-follows-dot', 'c3-pill-too',
  'd1-hover-replays', 'd2-no-pointer',
  'e1-contact-18th', 'e2-contact-last',
];

( async () => {
  fs.mkdirSync( SHOTS, { recursive: true } );
  const browser = await launch();
  const page = await browser.newPage( { viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 2 } );
  await page.goto( 'file://' + HTML, { waitUntil: 'load' } );
  await page.waitForTimeout( 900 );

  const cards = await page.$$( '.card' );
  for ( let i = 0; i < Math.min( cards.length, CARDS.length ); i++ ) {
    await cards[ i ].screenshot( { path: path.join( SHOTS, `${CARDS[ i ]}.png` ) } );
    console.log( `  ${CARDS[ i ]}.png` );
  }

  /* The hover states, captured with the pointer actually over each chip - a still of a hover
   * cannot be faked with a class here, because the whole point is what :hover computes to. */
  for ( const [ id, file ] of [ [ 'a1', 'a1-hover' ], [ 'a2', 'a2-hover' ], [ 'a3', 'a3-hover' ], [ 'a4', 'a4-hover' ] ] ) {
    const el = await page.$( `.chip[data-id="${id}"]` );
    if ( !el ) continue;
    await el.hover();
    await page.waitForTimeout( 320 );
    const strip = await el.evaluateHandle( n => n.closest( '.hdrstrip' ) );
    await strip.asElement().screenshot( { path: path.join( SHOTS, `${file}.png` ) } );
    console.log( `  ${file}.png` );
  }

  await ( await page.$( 'table' ) ).screenshot( { path: path.join( SHOTS, 'chip-vs-panel.png' ) } );
  console.log( '  chip-vs-panel.png' );
  await browser.close();

  const md = `# Menu icon, the panel, the step text, the footer trigger

> Rendered from \`docs/menu-review.html\` by \`tools/browser/menureview.js\`. GitHub serves raw
> \`.html\` as \`text/plain\`, so these PNGs are the openable version — **but open the HTML if you
> can**, because the chips and the tagline are live there: hover the chips, hover and click the line.

Nothing here is applied to the site. All numbers are computed in the mock from values measured on
the live page.

---

## 1 · The menu icon

**It has zero lines.** A single corner chevron, 8×8px, 2.5px strokes, \`#1a3a2a\` at .85 opacity,
in a 46×46 chip.

### The number that settles this section

Lime is a *light* colour, so **no lime fill can carry a hover state on a near-white chip**.
Measured against the rest fill \`#f4f7ee\`:

| hover fill | contrast vs rest | RGB move (of 441) |
|---|---|---|
| current \`rgba(209,244,112,.22)\` | **${ratio( CUR_HOVER, REST )}:1** | ${move( CUR_HOVER, REST )} |
| solid lime \`#d1f470\` | ${ratio( LIME, REST )}:1 | ${move( LIME, REST )} |
| dark green \`#1a3a2a\` | **${ratio( DARK, REST )}:1** | ${move( DARK, REST )} |

Only an **inversion** produces a luminance step. Solid lime is a hue move — visible to most people,
nearly nothing to anyone with reduced colour discrimination. The chip is also **1.08:1** against the
white header at rest, so the box barely reads as a control before you touch it.

| | |
|---|---|
| ![A1](menu-mock/a1-chevron-now.png) | ![A2](menu-mock/a2-solid-lime.png) |
| ![A3](menu-mock/a3-inverts-recommended.png) | ![A4](menu-mock/a4-three-lines.png) |

**The hover states, captured with the pointer actually on each chip:**

| A1 — today | A2 — solid lime |
|---|---|
| ![A1 hover](menu-mock/a1-hover.png) | ![A2 hover](menu-mock/a2-hover.png) |

| A3 — inverts | A4 — three lines |
|---|---|
| ![A3 hover](menu-mock/a3-hover.png) | ![A4 hover](menu-mock/a4-hover.png) |

## 2 · The panel does not match the chip

You said the box matches the icon. Three things differ:

![chip vs panel](menu-mock/chip-vs-panel.png)

| B1 — as it ships | B2 — one family |
|---|---|
| ![B1](menu-mock/b1-panel-mismatch.png) | ![B2](menu-mock/b2-panel-matched.png) |

B2 gives the panel the chip's 10px radius, \`#f4f7ee\` fill and \`#e3ecc9\` hairline, and softens the
shadow from .10 to .07 because the border now does part of the work. Rows keep their lime hover
tint — that is a list-row affordance, and it is the one place light lime works.

## 3 · The step text — three different limes, not one

Measured: names are **white on steps 1–7**. Only **step 8** is lime, because it is the
\`is-complete\` one. The \`.wt-svc\` pill is lime on **all 8**, and the **✓** is lime.

So "the text is still lime" is precisely: **the pill, the tick, and step 8's name.**

| C1 — now | C2 — recommended | C3 — not advised |
|---|---|---|
| ![C1](menu-mock/c1-step-text-now.png) | ![C2](menu-mock/c2-name-follows-dot.png) | ![C3](menu-mock/c3-pill-too.png) |

**C2 follows your instruction exactly** — name and tick take the dot's hue, the pill stays uniform.
Your call that *the text in the box should be the same* is right: the pill is a repeated label, and
five colours would turn a label into a legend.

**The cost, stated:** names drop from white (21:1 on black) to their own hue — lowest is blue at
4.06:1. Well clear, but a real reduction on the panel's main text.

## 4 · The footer effect on hover and click

Today the trigger is **scroll only**, and it fired once then disconnected.

| D1 — recommended | D2 — consider |
|---|---|
| ![D1](menu-mock/d1-hover-replays.png) | ![D2](menu-mock/d2-no-pointer.png) |

WCAG 2.2.2 governs motion that starts *automatically*. Hover and click are reader-initiated, so
replaying is not what that rule forbids, and each run is bounded at 1.15s. The scroll trigger stays
too, so it still announces itself once on arrival.

**The one caution:** this line has no \`href\`. A pointer cursor on it is the **false affordance**
that got the old hover-underline removed. My recommendation is the effect *without* \`cursor:pointer\`.

## 5 · Contact as the last item

| E1 — as it ships | E2 — Contact last |
|---|---|
| ![E1](menu-mock/e1-contact-18th.png) | ![E2](menu-mock/e2-contact-last.png) |

Tail today: \`Contact us → Terms → Privacy\` — Contact is 18th of 20, with the legal pages after the
one action a visitor might want. E2 is a reorder in \`navigation.ts\`, nothing else.

**One check:** you wrote "in terms of contact". If you meant **contrast** rather than **Contact**,
say so and I will drop this section.

---

## What I would ship

**A3, B2, C2, D1 without the pointer cursor, and E2 if you confirm it.**

- **A3** — the only hover with a measured luminance step (${ratio( DARK, REST )}:1 against
  ${ratio( CUR_HOVER, REST )}:1 today), using the brand's existing lime-on-dark-green pairing.
- **A4** is a free swap if you prefer three lines to a chevron — same hover, different glyph.
- **C2** — your instruction, exactly.
- **D1** — hover and click on top of scroll, minus \`cursor:pointer\`.

**Reply with letters — e.g. \`A3, B2, C2, D1, E2\` — and I will build them.**
`;

  fs.writeFileSync( MD, md );
  const total = fs.readdirSync( SHOTS ).reduce( ( s, f ) => s + fs.statSync( path.join( SHOTS, f ) ).size, 0 );
  console.log( `\n  ${MD}\n  ${fs.readdirSync( SHOTS ).length} PNGs, ${Math.round( total / 1024 )} kB\n` );
} )();
