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
      // Owner invariant: the Request family stays visible on all devices and engines.
      // Its service destinations remain customer-session URLs with noindex metadata.
      if ( await menu.locator( '.nav-group-label', { hasText: 'Request' } ).count() !== 1 ) {
        fail( `${viewport.name}: Request section missing from public menu` );
      }
      for ( const label of [ 'Orders', 'Submit Request', 'Request Amendment', 'Drop Docs',
        'Vault', 'Track', 'Pickup Request', 'Leave Review', 'Subscribe' ] ) {
        if ( await menu.getByRole( 'link', { name: label, exact: true } ).count() !== 1 ) {
          fail( `${viewport.name}: Request menu entry ${label} missing or duplicated` );
        }
      }
      if ( await menu.getByText( 'Shipments', { exact: true } ).count() === 0 ) {
        fail( `${viewport.name}: Shipments menu family missing` );
      }
      const box = await menu.boundingBox();
      if ( !box || box.height < 120 ) fail( `${viewport.name}: menu too short or invisible` );
      if ( box.x < -1 || box.x + box.width > viewport.width + 1 ) fail( `${viewport.name}: horizontal menu overflow` );
      if ( box.y + box.height > viewport.height + 1 ) fail( `${viewport.name}: menu runs off viewport bottom` );

      // The panel shares the rounded lime top accent used by the public checkout cards.
      // Check computed styles across desktop/mobile and all three browser engines.
      const panelStyle = await menu.evaluate( node => {
        const css = getComputedStyle( node );
        return {
          borderTopWidth: css.borderTopWidth,
          borderTopStyle: css.borderTopStyle,
          borderTopColor: css.borderTopColor,
          leftRadius: css.borderTopLeftRadius,
          rightRadius: css.borderTopRightRadius,
        };
      } );
      if ( panelStyle.borderTopWidth !== '4px' || panelStyle.borderTopStyle !== 'solid'
        || panelStyle.borderTopColor !== 'rgb(209, 244, 112)'
        || panelStyle.leftRadius !== '24px' || panelStyle.rightRadius !== '24px' ) {
        fail( `${viewport.name}: menu lime top accent drifted ${JSON.stringify( panelStyle )}` );
      }

      // Contact us uses the exact uploaded Material Symbols Outlined "person_text" SVG,
      // embedded as a path instead of downloading a second icon font.
      // Verify both the normal menu and the search results.
      const checkContactIcon = async ( state ) => {
        const contact = menu.getByRole( 'link', { name: 'Contact us', exact: true } );
        if ( await contact.count() !== 1 || await contact.getAttribute( 'href' ) !== '/contact/' ) {
          fail( `${viewport.name} (${state}): Contact us link missing or changed` );
        }
        const icon = contact.locator( 'svg.nav-row-icon-material' );
        if ( await icon.count() !== 1 ) fail( `${viewport.name} (${state}): Contact us SVG missing` );
        const artwork = await icon.evaluate( node => {
          const css = getComputedStyle( node );
          return {
            viewBox: node.getAttribute( 'viewBox' ),
            path: node.querySelector( 'path' )?.getAttribute( 'd' ) || '',
            fill: css.fill,
            stroke: css.stroke,
            ariaHidden: node.getAttribute( 'aria-hidden' ),
          };
        } );
        const expectedPath = 'M34,36V33H44v3H34ZM30,25.5v-3H44v3H30ZM26,15V12H44v3H26ZM11.78,22.13Q10.1,20.45 10.1,17.9t1.67-4.23T16,12t4.23,1.67T21.9,17.9t-1.68,4.23T16,23.8t-4.22-1.67ZM4,36V32.7q0-0.95 0.45-1.8t1.2-1.2q2.25-1.6 4.93-2.38T16,26.55t5.4,0.85t4.95,2.3q0.7,0.5 1.18,1.27T28,32.7V36H4Zm7.23-5.65q-2.58,0.8-4.48,2.1V33h18.5V32.45q-1.95-1.3-4.5-2.1T16,29.55t-4.77,0.8ZM18.1,20q0.8-0.8 0.8-2.1t-0.8-2.1T16,15t-2.1,0.8t-0.8,2.1T13.9,20T16,20.8T18.1,20ZM16,17.9ZM16,33Z';
        if ( artwork.viewBox !== '0 0 48 48'
          || artwork.path !== expectedPath
          || artwork.fill !== 'rgb(26, 58, 42)' || artwork.stroke !== 'none'
          || artwork.ariaHidden !== 'true' ) {
          fail( `${viewport.name} (${state}): Contact us person_text icon drifted ${JSON.stringify( artwork )}` );
        }
        // The source SVG paints only half its 48px viewBox height. Its 20px
        // layout slot is intentionally scaled to 30px, without moving row text.
        // At folded-phone widths the decorative icon is deliberately hidden.
        if ( viewport.width > 340 ) {
          const bounds = await icon.boundingBox();
          if ( !bounds || bounds.width < 29.5 || bounds.height < 29.5 ) {
            fail( `${viewport.name} (${state}): Contact us icon is undersized ${JSON.stringify( bounds )}` );
          }
        }
      };
      await checkContactIcon( 'menu' );

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
      const expectedHomeFontSize = viewport.width <= 340 ? '18px' : viewport.width <= 767 ? '20px' : '19px';
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

      // Mobile intentionally keeps the same capped Products rail as desktop: seven
      // product rows plus the existing continuation button. The important safety contract is
      // that vertical overscroll remains AUTO, so reaching the end of Products can hand the
      // gesture back to the main menu instead of trapping Request and later sections below it.
      if ( viewport.width <= 767 ) {
        const menuScroll = await menu.evaluate( node => ( {
          overflowY: getComputedStyle( node ).overflowY,
          scrollable: node.scrollHeight > node.clientHeight + 1,
        } ) );
        if ( !menuScroll.scrollable || ![ 'auto', 'scroll' ].includes( menuScroll.overflowY ) ) {
          fail( `${viewport.name}: main menu is not scrollable ${JSON.stringify( menuScroll )}` );
        }

        const productScroll = await page.locator( '.nav-products-scroll' ).evaluate( node => {
          const css = getComputedStyle( node );
          return {
            overflowY: css.overflowY,
            overscrollBehaviorY: css.overscrollBehaviorY,
            maxHeight: css.maxHeight,
            scrollable: node.scrollHeight > node.clientHeight + 1,
          };
        } );
        if ( !productScroll.scrollable || ![ 'auto', 'scroll' ].includes( productScroll.overflowY ) ) {
          fail( `${viewport.name}: Products is not a mobile scroll rail ${JSON.stringify( productScroll )}` );
        }
        if ( productScroll.maxHeight !== '364px' ) {
          fail( `${viewport.name}: Products rail height ${productScroll.maxHeight} (expected 364px / seven rows)` );
        }
        if ( productScroll.overscrollBehaviorY !== 'auto' ) {
          fail( `${viewport.name}: Products traps vertical scroll chaining ${JSON.stringify( productScroll )}` );
        }

        const moreProducts = page.getByRole( 'button', { name: 'Scroll to more products' } );
        const moreProductsCount = await moreProducts.count();
        if ( moreProductsCount > 0 ) {
          await moreProducts.waitFor( { state: 'visible' } );
          if ( await moreProducts.getAttribute( 'aria-hidden' ) !== 'false' ) {
            fail( `${viewport.name}: Products continuation button is hidden while products remain` );
          }
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

      await search.fill( 'contact us' );
      await checkContactIcon( 'search' );

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
