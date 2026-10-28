'use strict';

/**
 * Cross-browser public-menu compatibility check.
 * Browser compatibility check for menu-contract repairs. Run explicitly against the built tree.
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

      // Guard the styled-jsx scoping contract with live computed values. This menu once kept
      // correct DOM/ARIA while silently falling back to unrelated global nav styles.
      const home = menu.getByRole( 'link', { name: 'Home', exact: true } );
      const homeStyle = await home.evaluate( node => {
        const css = getComputedStyle( node );
        return {
          fontSize: css.fontSize,
          fontWeight: css.fontWeight,
          backgroundColor: css.backgroundColor,
        };
      } );
      const expectedHomeFontSize = viewport.width <= 340 ? '17px' : '19px';
      if ( homeStyle.fontSize !== expectedHomeFontSize ) {
        fail( `${viewport.name}: Home row font-size ${homeStyle.fontSize} (expected ${expectedHomeFontSize})` );
      }
      if ( Number( homeStyle.fontWeight ) < 700 ) fail( `${viewport.name}: active Home weight ${homeStyle.fontWeight}` );
      if ( homeStyle.backgroundColor !== 'rgb(209, 244, 112)' ) {
        fail( `${viewport.name}: active Home background ${homeStyle.backgroundColor}` );
      }

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

      // Mobile has one vertical scroll owner: the menu itself. A nested Products scroller
      // traps touch momentum and makes every section after Products feel missing.
      if ( viewport.width <= 767 ) {
        const menuScroll = await menu.evaluate( node => ( {
          overflowY: getComputedStyle( node ).overflowY,
          scrollable: node.scrollHeight > node.clientHeight + 1,
        } ) );
        if ( !menuScroll.scrollable || ![ 'auto', 'scroll' ].includes( menuScroll.overflowY ) ) {
          fail( `${viewport.name}: main menu is not the mobile scroll owner ${JSON.stringify( menuScroll )}` );
        }

        const productScroll = await page.locator( '.nav-products-scroll' ).evaluate( node => ( {
          overflowY: getComputedStyle( node ).overflowY,
          scrollable: node.scrollHeight > node.clientHeight + 1,
        } ) );
        if ( productScroll.scrollable || [ 'auto', 'scroll' ].includes( productScroll.overflowY ) ) {
          fail( `${viewport.name}: Products created a nested mobile scroller ${JSON.stringify( productScroll )}` );
        }
      }

      const search = page.getByLabel( 'Search navigation' );

      // Simulate SupportWidget's DOM translation and prove Header harvests the rendered labels
      // before it switches to flat search results.
      await page.getByRole( 'link', { name: 'Visa' } ).locator( '.nav-item-label' ).evaluate(
        node => { node.textContent = 'वीज़ा'; }
      );
      await page.locator( '.nav-tree-item[aria-label="Elsewhere"]' ).evaluate(
        node => node.setAttribute( 'aria-label', 'विदेश यात्रा' )
      );
      await search.focus();
      await search.fill( 'वीज़ा' );
      if ( await page.getByRole( 'link', { name: 'Visa' } ).count() !== 1 ) {
        fail( `${viewport.name}: translated destination search failed` );
      }
      await search.fill( 'विदेश यात्रा' );
      for ( const label of [ 'Visa', 'Trip', 'Activities' ] ) {
        if ( await page.getByRole( 'link', { name: label } ).count() !== 1 ) {
          fail( `${viewport.name}: translated family search missing ${label}` );
        }
      }

      await search.fill( 'elsewhere' );
      const status = await menu.getByRole( 'status' ).textContent();
      if ( status?.trim() !== '3 menu results.' ) fail( `${viewport.name}: search status was ${status}` );
      for ( const label of [ 'Visa', 'Trip', 'Activities' ] ) {
        if ( await page.getByRole( 'link', { name: label } ).count() !== 1 ) fail( `${viewport.name}: missing search result ${label}` );
      }

      await search.fill( '' );
      const googlePlay = page.getByRole( 'link', { name: 'Google Play' } );
      if ( await googlePlay.getAttribute( 'href' ) !== 'https://play.google.com/store/apps/dev?id=5505420420345648842' ) {
        fail( `${viewport.name}: Google Play destination drifted` );
      }
      if ( await page.getByRole( 'link', { name: 'App Store' } ).count() !== 0 ) {
        fail( `${viewport.name}: unverified App Store destination is visible` );
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
