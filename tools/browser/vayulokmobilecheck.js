'use strict';

/**
 * vayulokmobilecheck — measures that the VayuLok live card's "table" layouts STACK on a phone
 * and never force horizontal overflow.
 *
 * WHY A BESPOKE HARNESS. The live React component (src/components/VayuLokLive.tsx) fetches
 * Google Air-Quality / Weather APIs client-side, so it will not populate real rows in a
 * headless run without keys and a dev server. But the complaint is purely CSS: the daily-
 * forecast and pollutant "tables" kept multiple columns on a phone instead of stacking. That
 * is measurable WITHOUT the network by lifting the component's styled-jsx <style> block verbatim
 * and mounting a representative DOM (the exact class names the render emits) under it, then
 * reading getBoundingClientRect at phone widths.
 *
 * It asserts, at 320 / 375 / 430 CSS px:
 *   (1) the page/container never scrolls horizontally (scrollWidth <= clientWidth);
 *   (2) the daily-forecast row renders as TWO visual lines (temp sits on the top line with the
 *       day; the condition wraps onto a second line BELOW the day) — i.e. it is stacked, not a
 *       single cramped 4/5-column strip;
 *   (3) the pollutant row stacks (label on its own line, value below the label's top).
 */

const fs = require( 'node:fs' );
const path = require( 'node:path' );
const { chromium } = require( 'playwright-core' );

const EXECUTABLE = '/inner_container/opt/playwright/chromium_headless_shell-1232/chrome-headless-shell-linux64/chrome-headless-shell';
const COMPONENT = path.join( __dirname, '..', '..', 'src', 'components', 'VayuLokLive.tsx' );

function extractCss() {
  const src = fs.readFileSync( COMPONENT, 'utf8' );
  const open = src.indexOf( '<style jsx>{`' );
  const close = src.indexOf( '`}</style>', open );
  if ( open < 0 || close < 0 ) throw new Error( 'could not locate styled-jsx block' );
  let css = src.slice( open + '<style jsx>{`'.length, close );
  // styled-jsx template uses ${...} interpolations? VayuLok uses none inside the block, but be safe:
  css = css.replace( /\$\{[^}]*\}/g, '' );
  return css;
}

// A representative slice of the real render tree (class names copied from the JSX at ~3385 and
// ~3976): three pollutant rows and three daily-forecast rows, inside the air card wrap.
const BODY = `
<div class="vl-live"><div class="vl-live-shell">
  <div class="vl-live-air-card-wrap"><aside class="vl-live-air-card">
    <ul class="vl-live-air-pollutant-list">
      <li><div class="vl-live-air-pollutant-row">
        <span class="vl-live-air-pollutant-label">Particulate matter (PM2.5)</span>
        <span class="vl-live-air-pollutant-value">38<small>µg/m³</small></span>
        <button class="vl-live-air-pollutant-info" type="button">i</button>
      </div></li>
      <li><div class="vl-live-air-pollutant-row">
        <span class="vl-live-air-pollutant-label">Nitrogen dioxide (NO₂)</span>
        <span class="vl-live-air-pollutant-value">12<small>ppb</small></span>
        <button class="vl-live-air-pollutant-info" type="button">i</button>
      </div></li>
    </ul>
    <ul class="vl-live-wx-daily-list">
      <li><button class="vl-live-wx-daily-row" type="button">
        <span class="vl-live-wx-daily-day">Mon</span>
        <span class="vl-live-wx-daily-icon-spacer"></span>
        <span class="vl-live-wx-daily-cond">Partly cloudy with a chance of afternoon showers</span>
        <span class="vl-live-wx-daily-temp">21° — 29°</span>
        <span class="vl-live-wx-daily-rain">40%</span>
      </button></li>
      <li><button class="vl-live-wx-daily-row" type="button">
        <span class="vl-live-wx-daily-day">Tue</span>
        <span class="vl-live-wx-daily-icon-spacer"></span>
        <span class="vl-live-wx-daily-cond">Sunny</span>
        <span class="vl-live-wx-daily-temp">22° — 31°</span>
        <span class="vl-live-wx-daily-rain">5%</span>
      </button></li>
    </ul>
  </aside></div>
</div></div>`;

const WIDTHS = [ 320, 375, 430 ];

( async () => {
  const css = extractCss();
  const html = `<!doctype html><html><head><meta charset="utf-8">
    <style>*{box-sizing:border-box}body{margin:0}
    /* root vars the component reads (lifted names; values are representative) */
    :root{--hair:#e5e7eb;--muted:#6b7280;--body:#111;--green:#1a3a2a;--lime:#d1f470;--lime-tint:rgba(209,244,112,.22);
      --status:#2563eb;--radius-lg:12px;--panel-r:16px;--pill-r:12px;
      --tap-min:44px;--vl-action-size:var(--tap-min);--vl-content-gap:12px;--vl-heading-gap:12px;--vl-section-gap:20px;--vl-section-pad:16px}
    .vl-live-air-card-wrap{display:grid}
    </style>
    <style>${css}</style></head><body>${BODY}</body></html>`;

  const browser = await chromium.launch( { executablePath: EXECUTABLE, args: [ '--no-sandbox' ] } );
  let failures = 0;
  for ( const w of WIDTHS ) {
    const page = await browser.newPage( { viewport: { width: w, height: 900 }, deviceScaleFactor: 1 } );
    await page.setContent( html, { waitUntil: 'load' } );
    const r = await page.evaluate( () => {
      const q = ( s ) => document.querySelector( s );
      const rect = ( el ) => { const b = el.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height, bottom: b.bottom, right: b.right }; };
      const de = document.documentElement;
      const row = q( '.vl-live-wx-daily-row' );
      const day = q( '.vl-live-wx-daily-day' );
      const cond = q( '.vl-live-wx-daily-cond' );
      const temp = q( '.vl-live-wx-daily-temp' );
      const prow = q( '.vl-live-air-pollutant-row' );
      const plabel = q( '.vl-live-air-pollutant-label' );
      const pval = q( '.vl-live-air-pollutant-value' );
      return {
        docScroll: de.scrollWidth, docClient: de.clientWidth,
        day: rect( day ), cond: rect( cond ), temp: rect( temp ), row: rect( row ),
        plabel: rect( plabel ), pval: rect( pval ), prow: rect( prow ),
      };
    } );
    const hOverflow = r.docScroll > r.docClient + 1;
    // condition wraps BELOW the day (its top is below the day's bottom-ish) => stacked second line
    const condBelowDay = r.cond.y >= r.day.y + r.day.h - 2;
    // temp shares the top line with the day (roughly same y)
    const tempTopLine = Math.abs( r.temp.y - r.day.y ) <= 8;
    // pollutant value sits BELOW the label => stacked
    const valBelowLabel = r.pval.y >= r.plabel.y + r.plabel.h - 2;
    const ok = !hOverflow && condBelowDay && tempTopLine && valBelowLabel;
    if ( !ok ) failures++;
    console.log(
      `@${w}px  h-overflow=${hOverflow ? 'YES(' + r.docScroll + '>' + r.docClient + ')' : 'no'}` +
      `  cond-below-day=${condBelowDay}  temp-on-top-line=${tempTopLine}  pollutant-stacked=${valBelowLabel}  => ${ok ? 'PASS' : 'FAIL'}`
    );
    await page.close();
  }
  await browser.close();
  if ( failures ) { console.error( `\n${failures} width(s) FAILED` ); process.exit( 1 ); }
  console.log( '\nAll phone widths PASS: tables stack vertically, no horizontal overflow.' );
} )().catch( ( e ) => { console.error( e ); process.exit( 1 ); } );
