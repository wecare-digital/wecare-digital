'use strict';

/**
 * Cross-browser public-menu compatibility check.
 *
 * Runs the same interaction contract in Chromium, Firefox and WebKit at desktop and mobile
 * viewport sizes. This is intentionally narrower than devicecheck.js: it validates the menu
 * itself on all three engines, including the engine used by Safari and iOS WKWebView.
 *
 * Run after npm run build:
 *   node tools/browser/menucheck.js --chromium
 *   node tools/browser/menucheck.js --firefox
 *   node tools/browser/menucheck.js --webkit
 */

const { target } = require( './lib/serve' );
const { chromium, firefox, webkit } = require( 'playwright-core' );

const engineName = process.argv.includes( '--firefox' )
  ? 'firefox'
  : process.argv.includes( '--webkit' )
    ? 'webkit'
    : 'chromium';
const engine = { chromium, firefox, webkit }[ engineName ];

const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 900 },
  { name: 'phone', width: 390, height: 844 },
  { name: 'narrow-phone', width: 320, height: 700 },
  { name: 'folded-phone', width: 280, height: 653 },
  { name: 'folded-landscape', width: 653, height: 280 },
  { name: 'wide-short', width: 880, height: 360 },
];

const fail = ( message ) => { throw new Error( message ); };

(async () => {
  const t = await target();
  const browser = await engine.launch();
  let checks = 0;
  try {
    for ( const viewport of VIEWPORTS ) {
      const context = await browser.newContext( { viewport: { width: viewport.width, height: viewport.height } } );
      const page = await context.newPage();
      await page.goto( `${t.base}/`, { waitUntil: 'networkidle' } );

      const trigger = page.getByRole( 'button', { name: 'Open navigation' } );
      await trigger.click();
      await page.waitForTimeout( 40 );

      if ( await trigger.getAttribute( 'aria-expanded' ) !== 'true' ) fail( `${viewport.name}: trigger did not open` );
      if ( await trigger.getAttribute( 'aria-controls' ) !== 'public-navigation-menu' ) {
        fail( `${viewport.name}: trigger is not linked to the public navigation menu` );
      }

      const menu = page.getByRole( 'navigation', { name: 'Public navigation' } );
      if ( await menu.getAttribute( 'id' ) !== 'public-navigation-menu' ) {
        fail( `${viewport.name}: public navigation id is missing or changed` );
      }
      const box = await menu.boundingBox();
      if ( !box || box.height < 120 ) fail( `${viewport.name}: menu too short or invisible` );
      if ( box.x < -1 || box.x + box.width > viewport.width + 1 ) fail( `${viewport.name}: horizontal menu overflow` );
      if ( box.y + box.height > viewport.height + 1 ) fail( `${viewport.name}: menu runs off viewport bottom` );

      const touchTargets = await page.locator( 'header a[href], header button, header input' ).evaluateAll( nodes =>
        nodes.filter( node => {
          const style = getComputedStyle( node );
          const rect = node.getBoundingClientRect();
          return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
        } ).map( node => {
          const rect = node.getBoundingClientRect();
          return { label: node.getAttribute( 'aria-label' ) || node.textContent || node.tagName, w: rect.width, h: rect.height };
        } )
      );
      // Browser layout APIs can report a CSS 44px target as 43.99999px due to
      // sub-pixel floating-point rounding (observed in WebKit on the 320px viewport).
      // Keep the accessibility contract at 44x32 CSS px while allowing a tiny numeric epsilon.
      const TARGET_EPSILON = 0.01;
      const undersized = touchTargets.filter(
        item => item.h < 44 - TARGET_EPSILON || item.w < 32 - TARGET_EPSILON
      );
      if ( undersized.length ) fail( `${viewport.name}: undersized header targets ${JSON.stringify( undersized )}` );

      const partner = page.locator( '.nav-tree-item', { hasText: 'Partner' } ).first();
      const partnerLabels = await partner.locator( '.nav-item' ).allTextContents();
      if ( partnerLabels.join( '|' ) !== 'Partner|Referral|Merchandise|Kiosk' ) {
        fail( `${viewport.name}: Partner order ${partnerLabels.join( ' > ' )}` );
      }

      const search = page.getByLabel( 'Search navigation' );
      await search.fill( 'elsewhere' );
      const status = await menu.getByRole( 'status' ).textContent();
      if ( status?.trim() !== '3 menu results.' ) fail( `${viewport.name}: search status was ${status}` );
      for ( const label of [ 'Visa', 'Trip', 'Activities' ] ) {
        if ( await page.getByRole( 'link', { name: label } ).count() !== 1 ) fail( `${viewport.name}: missing search result ${label}` );
      }

      await search.fill( '' );
      await page.keyboard.press( 'Escape' );
      if ( await trigger.getAttribute( 'aria-expanded' ) !== 'false' ) fail( `${viewport.name}: Escape did not close` );

      await trigger.click();
      await page.locator( 'body' ).click( { position: { x: viewport.width - 4, y: viewport.height - 4 } } );
      if ( await trigger.getAttribute( 'aria-expanded' ) !== 'false' ) fail( `${viewport.name}: outside click did not close` );

      checks++;
      await context.close();
    }
    console.log( `menucheck [${engineName}] ${checks}/${VIEWPORTS.length} viewports clean` );
  } finally {
    await browser.close();
    if ( t.close ) await t.close();
  }
})().catch( error => {
  console.error( error );
  process.exit( 1 );
});
