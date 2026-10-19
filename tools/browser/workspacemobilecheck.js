'use strict';

/**
 * workspacemobilecheck - probes whether representative workspace (CRM) layouts overflow a phone.
 *
 * The workspace shell (Layout.tsx) sets .workspace-main{overflow-x:clip}, which HIDES page-level
 * horizontal scroll - so a too-wide inner grid is clipped (content cut off) rather than
 * scrollable. This harness mounts representative inner markup inside a 320px viewport and reports,
 * per fixture: does the element's scrollWidth exceed the viewport (content that would be clipped)?
 *
 * It does NOT need the real pages (they are auth-gated and data-driven); it mounts the exact
 * inline-style patterns the components emit so the measurement reflects the real CSS.
 */

const { chromium } = require( 'playwright-core' );
const EXECUTABLE = '/inner_container/opt/playwright/chromium_headless_shell-1232/chrome-headless-shell-linux64/chrome-headless-shell';

// Fixtures: [name, innerHTML] - the real inline-style patterns from the components.
const FIXTURES = [
  [ 'orders-detail-grid (3-col inline, no @media)',
    `<div style="overflow-x:clip;width:100%">
       <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
         <div><span>Full Order ID</span><div style="font-family:monospace">WD-000000123456</div></div>
         <div><span>Customer</span><div>A customer with a fairly long display name here</div></div>
         <div><span>Amount</span><div>Rs 12,345.00</div></div>
       </div>
     </div>` ],
  [ 'orders-table (scroll-wrapped, minWidth 900)',
    `<div style="overflow-x:clip;width:100%">
       <div style="overflow-x:auto"><table style="width:100%;min-width:900px"><tr><td>a</td><td>b</td></tr></table></div>
     </div>` ],
  [ 'heavy side padding (24px 32px)',
    `<div style="overflow-x:clip;width:100%">
       <div style="padding:24px 32px;max-width:1440px"><div style="background:#eee">content block</div></div>
     </div>` ],
];

( async () => {
  const browser = await chromium.launch( { executablePath: EXECUTABLE, args: [ '--no-sandbox' ] } );
  const page = await browser.newPage( { viewport: { width: 320, height: 800 }, deviceScaleFactor: 1 } );
  let problems = 0;
  for ( const [ name, html ] of FIXTURES ) {
    await page.setContent( `<!doctype html><meta charset=utf-8><style>*{box-sizing:border-box;margin:0}body{width:320px}</style><body>${html}</body>`, { waitUntil: 'load' } );
    const r = await page.evaluate( () => {
      const de = document.documentElement;
      const grid = document.querySelector( '[style*="grid-template-columns"]' );
      return {
        docScroll: de.scrollWidth, docClient: de.clientWidth,
        gridScroll: grid ? grid.scrollWidth : null, gridClient: grid ? grid.clientWidth : null,
      };
    } );
    const pageOverflow = r.docScroll > r.docClient + 1;
    const gridOverflow = r.gridScroll != null && r.gridScroll > r.gridClient + 1;
    const bad = pageOverflow || gridOverflow;
    if ( bad ) problems++;
    console.log( `${bad ? 'OVERFLOW' : 'ok      '}  ${name}` +
      `  page=${r.docScroll}/${r.docClient}` + ( r.gridScroll != null ? `  grid=${r.gridScroll}/${r.gridClient}` : '' ) );
  }
  await browser.close();
  console.log( `\n${problems} fixture(s) overflow a 320px phone.` );
} )().catch( ( e ) => { console.error( e ); process.exit( 1 ); } );
