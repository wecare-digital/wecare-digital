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
 * It asserts, at 320 / 360 / 375 / 390 / 412 / 430 CSS px:
 *   (1) the page/container never scrolls horizontally (scrollWidth <= clientWidth);
 *   (2) the daily-forecast row renders as TWO visual lines (temp sits on the top line with the
 *       day; the condition wraps onto a second line BELOW the day) — i.e. it is stacked, not a
 *       single cramped 4/5-column strip;
 *   (3) pollutant metrics stay inside the viewport with no reserved tooltip/action column;
 *   (4) Weather history keeps the 24px mobile card heading but uses compact 16px supporting copy;
 *   (5) every Weather history range control keeps the canonical 44px touch floor.
 */

const fs = require( 'node:fs' );
const path = require( 'node:path' );
const { launch } = require( './lib/browser.js' );
const COMPONENT = path.join( __dirname, '..', '..', 'src', 'components', 'VayuLokLive.tsx' );
const INSIGHTS_COMPONENT = path.join( __dirname, '..', '..', 'src', 'components', 'VayuLokWeatherInsights.tsx' );

function extractCss( component ) {
  const src = fs.readFileSync( component, 'utf8' );
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
    <div class="vl-live-air-gauge-row">
      <span class="vl-live-air-aqi-spine"></span>
      <div class="vl-live-air-aqi-score"><strong class="vl-live-air-aqi-number">98</strong><span class="vl-live-air-aqi-unit">AQI</span></div>
      <div class="vl-live-air-gauge-meta">
        <strong class="vl-live-air-gauge-word">Satisfactory air quality</strong>
        <div class="vl-live-air-summary-meta"><span class="vl-live-air-summary-chip">AQI 98</span><span class="vl-live-air-summary-chip">Dominant O3</span></div>
      </div>
    </div>
    <ul class="vl-live-air-pollutant-list">
      <li><div class="vl-live-air-pollutant-row">
        <span class="vl-live-air-pollutant-label">Particulate matter (PM2.5)</span>
        <span class="vl-live-air-pollutant-value">38<small>µg/m³</small></span>
              </div></li>
      <li><div class="vl-live-air-pollutant-row">
        <span class="vl-live-air-pollutant-label">Nitrogen dioxide (NO₂)</span>
        <span class="vl-live-air-pollutant-value">12<small>ppb</small></span>
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
    <section class="vl-wi" aria-label="Weather history">
      <div class="vl-wi-head">
        <div>
          <h4>Weather history</h4>
          <p>Past weather for Thiruvananthapuram.</p>
        </div>
        <div class="vl-wi-range" role="group" aria-label="Weather history range">
          <button type="button">30D</button><button type="button">1Y</button><button type="button">5Y</button>
        </div>
      </div>
      <div class="vl-wi-grid">
        <div><span>Typical temperature</span><strong>21.8°C</strong></div>
        <div><span>Total precipitation</span><strong>151.8 mm</strong></div>
      </div>
      <div class="vl-wi-source"><span>Oct 2025–Oct 2026</span><span> · Grid 5.46 km</span></div>
    </section>
  </aside></div>
</div></div>`;

const WIDTHS = [ 320, 360, 375, 390, 412, 430 ];

( async () => {
  const css = extractCss( COMPONENT );
  const insightsCss = extractCss( INSIGHTS_COMPONENT );
  const html = `<!doctype html><html><head><meta charset="utf-8">
    <style>*{box-sizing:border-box}body{margin:0}
    /* root vars the component reads (lifted names; values are representative) */
    :root{--hair:#e5e7eb;--muted:#6b7280;--body:#111;--green:#1a3a2a;--lime:#d1f470;--lime-tint:rgba(209,244,112,.22);
      --status:#2563eb;--radius-lg:12px;--panel-r:16px;--pill-r:12px;
      --tap-min:44px;--vl-action-size:var(--tap-min);--vl-content-gap:12px;--vl-heading-gap:12px;--vl-section-gap:20px;--vl-section-pad:16px;
      --font-sans:Inter,ui-sans-serif,system-ui,sans-serif;--public-heading:rgba(0,0,0,.95);--public-body:rgba(0,0,0,.898);--public-muted:rgba(0,0,0,.54);
      --public-card-size:22px;--public-card-weight:700;--public-card-leading:1.27;--public-card-tracking:-.25px;
      --public-body-size:20px;--public-body-weight:400;--public-body-leading:1.4;--public-body-tracking:-.125px;
      --public-mobile-card-size:24px;--public-mobile-form-font-size:16px;--public-mobile-section-gap:64px;
      --radius-full:9999px;--space-2:8px;--space-3:12px;--space-4:16px;--space-6:24px;--text-xs:12px;--text-sm:13px;--text-base:16px}
    .vl-live-air-card-wrap{display:grid}
    </style>
    <style>${css}</style><style>${insightsCss}</style></head><body>${BODY}</body></html>`;

  const browser = await launch();
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
      const pinfo = q( '.vl-live-air-pollutant-info' );
      const score = q( '.vl-live-air-aqi-score' );
      const meta = q( '.vl-live-air-gauge-meta' );
      const gaugeRow = q( '.vl-live-air-gauge-row' );
      const history = q( '.vl-wi' );
      const historyHeading = q( '.vl-wi-head h4' );
      const historyBody = q( '.vl-wi-head p' );
      const historyButtons = Array.from( document.querySelectorAll( '.vl-wi-range button' ) );
      const airGaugeWord = q( '.vl-live-air-gauge-word' );
      const weatherDayCond = q( '.vl-live-wx-daily-cond' );
      const weatherDayTemp = q( '.vl-live-wx-daily-temp' );
      const weatherGridKey = q( '.vl-live-wx-grid-k' );
      const weatherGridValue = q( '.vl-live-wx-grid-v' );
      return {
        docScroll: de.scrollWidth, docClient: de.clientWidth,
        day: rect( day ), cond: rect( cond ), temp: rect( temp ), row: rect( row ),
        plabel: rect( plabel ), pval: rect( pval ), prow: rect( prow ), pinfo: Boolean( pinfo ),
        score: rect( score ), meta: rect( meta ), gaugeRow: rect( gaugeRow ),
        history: history ? rect( history ) : null,
        historyHeadingSize: historyHeading ? parseFloat( getComputedStyle( historyHeading ).fontSize ) : -1,
        historyBodySize: historyBody ? parseFloat( getComputedStyle( historyBody ).fontSize ) : -1,
        historyButtonHeights: historyButtons.map( button => rect( button ).h ),
        airGaugeWordSize: airGaugeWord ? parseFloat( getComputedStyle( airGaugeWord ).fontSize ) : -1,
        airGaugeWordWeight: airGaugeWord ? getComputedStyle( airGaugeWord ).fontWeight : '',
        weatherDayCondSize: weatherDayCond ? parseFloat( getComputedStyle( weatherDayCond ).fontSize ) : -1,
        weatherDayTempSize: weatherDayTemp ? parseFloat( getComputedStyle( weatherDayTemp ).fontSize ) : -1,
        weatherGridKeySize: weatherGridKey ? parseFloat( getComputedStyle( weatherGridKey ).fontSize ) : -1,
        weatherGridValueSize: weatherGridValue ? parseFloat( getComputedStyle( weatherGridValue ).fontSize ) : -1,
        weatherGridValueWeight: weatherGridValue ? getComputedStyle( weatherGridValue ).fontWeight : '',
      };
    } );
    const hOverflow = r.docScroll > r.docClient + 1;
    // condition wraps BELOW the day (its top is below the day's bottom-ish) => stacked second line
    const condBelowDay = r.cond.y >= r.day.y + r.day.h - 2;
    // temp shares the top line with the day (roughly same y)
    const tempTopLine = Math.abs( r.temp.y - r.day.y ) <= 8;
    const pollutantFits = r.prow.x >= -1 && r.prow.right <= r.docClient + 1;
    const pollutantCompact = !r.pinfo && pollutantFits;
    // Mobile AQI score + status must be centered against the FULL gauge/card row.
    // Comparing the children to each other can false-green when both are shifted together.
    const rowCenter = r.gaugeRow.x + r.gaugeRow.w / 2;
    const scoreCenter = r.score.x + r.score.w / 2;
    const metaCenter = r.meta.x + r.meta.w / 2;
    const scoreCentered = Math.abs( scoreCenter - rowCenter ) <= 2;
    const metaCentered = Math.abs( metaCenter - rowCenter ) <= 2;
    const summaryCentered = scoreCentered && metaCentered;
    const historyFound = Boolean( r.history );
    const historyFits = historyFound && r.history.right <= r.docClient + 1 && r.history.x >= -1;
    const historyType = Math.abs( r.historyHeadingSize - 24 ) <= 0.1 && Math.abs( r.historyBodySize - 16 ) <= 0.1;
    const historyButtonCount = r.historyButtonHeights.length;
    const historyTouches = historyButtonCount === 3 && r.historyButtonHeights.every( height => height >= 44 );
    const airType = r.airGaugeWordSize >= 23.9 && Number( r.airGaugeWordWeight ) >= 700;
    const weatherType = r.weatherDayCondSize >= 14.9 && r.weatherDayTempSize >= 16.9 &&
      r.weatherGridKeySize >= 16.9 && r.weatherGridValueSize >= 16.9 && Number( r.weatherGridValueWeight ) <= 600;
    const ok = !hOverflow && condBelowDay && tempTopLine && pollutantCompact && summaryCentered && historyFits && historyType && historyTouches && airType && weatherType;
    if ( !ok ) failures++;
    console.log(
      `@${w}px  h-overflow=${hOverflow ? 'YES(' + r.docScroll + '>' + r.docClient + ')' : 'no'}` +
      `  cond-below-day=${condBelowDay}  temp-on-top-line=${tempTopLine}  pollutant-compact=${pollutantCompact}` +
      `  score-centered=${scoreCentered}  meta-centered=${metaCentered}` +
      `  history-found=${historyFound}  history-buttons=${historyButtonCount}` +
      `  history-fits=${historyFits}  history-type=${historyType}  history-touch=${historyTouches}` +
      `  air-type=${airType}  weather-type=${weatherType}  => ${ok ? 'PASS' : 'FAIL'}`
    );
    await page.close();
  }
  await browser.close();
  if ( failures ) { console.error( `\n${failures} width(s) FAILED` ); process.exit( 1 ); }
  console.log( '\nAll VayuLok phone widths PASS: pollutant metrics stay compact, Weather history keeps compact supporting copy and the touch contract, no horizontal overflow.' );
} )().catch( ( e ) => { console.error( e ); process.exit( 1 ); } );
