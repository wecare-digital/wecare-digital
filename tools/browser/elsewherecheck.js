'use strict';

/**
 * Elsewhere assistant touch/responsive contract.
 *
 * Runs against the production export in Chromium, Firefox and WebKit. This is not a
 * substitute for a physical iPhone/Android device, but it makes the previously-manual
 * 320/360/375/390/412px touch assumptions executable in every public browser matrix run.
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
  { name: 'narrow-phone', width: 320, height: 700 },
  { name: 'phone-360', width: 360, height: 800 },
  { name: 'phone-375', width: 375, height: 812 },
  { name: 'phone-390', width: 390, height: 844 },
  { name: 'phone-412', width: 412, height: 915 },
  { name: 'phone-430', width: 430, height: 932 },
  { name: 'tablet', width: 768, height: 1024 },
];

const fail = message => { throw new Error( message ); };
const px = value => Number.parseFloat( String( value || '0' ) ) || 0;

(async () => {
  const t = await target();
  const browser = await engine.launch();
  let checks = 0;
  try {
    for ( const viewport of VIEWPORTS ) {
      const context = await browser.newContext( {
        viewport: { width: viewport.width, height: viewport.height },
        hasTouch: true,
      } );
      const page = await context.newPage();
      await page.goto( `${t.base}/elsewhere/activities/`, { waitUntil: 'load', timeout: 60000 } );
      await page.locator( '.eta-shell' ).waitFor( { state: 'visible' } );
      await page.waitForTimeout( 80 );

      const geometry = await page.evaluate( () => {
        const root = document.documentElement;
        const shell = document.querySelector( '.eta-shell' );
        const tabs = document.querySelector( '.eta-tabs' );
        const response = document.querySelector( '.eta-response-view' );
        if ( !shell || !tabs || !response ) return null;
        const shellRect = shell.getBoundingClientRect();
        const tabButtons = Array.from( tabs.querySelectorAll( '.eta-tab' ) ).map( node => {
          const rect = node.getBoundingClientRect();
          return { top: rect.top, height: rect.height };
        } );
        const activeTab = tabs.querySelector( '.eta-tab.active' );
        const activeRect = activeTab ? activeTab.getBoundingClientRect() : null;
        return {
          pageScrollWidth: root.scrollWidth,
          clientWidth: root.clientWidth,
          shellLeft: shellRect.left,
          shellRight: shellRect.right,
          tabsLeft: tabs.getBoundingClientRect().left,
          tabsRight: tabs.getBoundingClientRect().right,
          tabsScrollWidth: tabs.scrollWidth,
          tabsClientWidth: tabs.clientWidth,
          tabsDisplay: getComputedStyle( tabs ).display,
          tabsTouchAction: getComputedStyle( tabs ).touchAction,
          responseTouchAction: getComputedStyle( response ).touchAction,
          responseOverflowY: getComputedStyle( response ).overflowY,
          activeLeft: activeRect?.left ?? null,
          activeRight: activeRect?.right ?? null,
          activeId: activeTab?.id || '',
          activeSelected: activeTab?.getAttribute( 'aria-selected' ) || '',
          tabButtons,
        };
      } );

      if ( !geometry ) fail( `${viewport.name}: assistant geometry unavailable` );
      if ( geometry.pageScrollWidth > geometry.clientWidth + 1 ) {
        fail( `${viewport.name}: page horizontal overflow ${geometry.pageScrollWidth} > ${geometry.clientWidth}` );
      }
      if ( geometry.shellLeft < -1 || geometry.shellRight > viewport.width + 1 ) {
        fail( `${viewport.name}: assistant escapes viewport` );
      }
      if ( geometry.tabButtons.length !== 4 ) fail( `${viewport.name}: expected four travel tabs` );
      const firstTop = geometry.tabButtons[ 0 ].top;
      if ( geometry.tabButtons.some( item => Math.abs( item.top - firstTop ) > 1 ) ) {
        fail( `${viewport.name}: travel tabs wrapped to multiple rows` );
      }
      if ( viewport.width <= 720 ) {
        if ( geometry.tabsDisplay !== 'flex' ) fail( `${viewport.name}: mobile service rail is not a horizontal flex scroller` );
        if ( geometry.tabsScrollWidth <= geometry.tabsClientWidth ) fail( `${viewport.name}: mobile service rail is not horizontally scrollable` );
        if ( geometry.tabsTouchAction !== 'pan-x' ) fail( `${viewport.name}: tab rail touch-action ${geometry.tabsTouchAction}` );
        if ( geometry.activeId !== 'elsewhere-travel-tab-activities' || geometry.activeSelected !== 'true' ) {
          fail( `${viewport.name}: Activities is not the initial active service` );
        }
        if ( geometry.activeLeft === null || geometry.activeRight === null
          || geometry.activeLeft < geometry.tabsLeft - 1 || geometry.activeRight > geometry.tabsRight + 1 ) {
          fail( `${viewport.name}: active Activities tab is off-screen on initial load` );
        }
        if ( geometry.responseOverflowY !== 'visible' ) {
          fail( `${viewport.name}: mobile results still use a nested vertical scroller (${geometry.responseOverflowY})` );
        }
      } else if ( geometry.responseTouchAction !== 'pan-y' ) {
        fail( `${viewport.name}: response touch-action ${geometry.responseTouchAction}` );
      }

      const textarea = page.getByLabel( 'Ask about travel' );
      await textarea.tap();
      const composerStyle = await page.locator( '.eta-composer' ).evaluate( node => {
        const style = getComputedStyle( node );
        return { boxShadow: style.boxShadow, transform: style.transform };
      } );
      if ( composerStyle.boxShadow === 'none' ) fail( `${viewport.name}: composer has no focus/touch feedback` );
      if ( composerStyle.transform !== 'none' ) fail( `${viewport.name}: composer moves on touch (${composerStyle.transform})` );

      const mic = page.locator( '.eta-shell [data-voice-search-mic="true"]' );
      await mic.waitFor( { state: 'visible', timeout: 2000 } );
      if ( await mic.count() !== 1 ) fail( `${viewport.name}: voice control disappeared instead of showing supported/unavailable state` );
      const micBox = await mic.boundingBox();
      if ( !micBox || micBox.width < 44 || micBox.height < 44 ) fail( `${viewport.name}: mic target below 44px` );

      const visibleButtons = await page.locator( '.eta-shell button' ).evaluateAll( nodes =>
        nodes.filter( node => {
          const rect = node.getBoundingClientRect();
          const style = getComputedStyle( node );
          return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
        } ).map( node => {
          const rect = node.getBoundingClientRect();
          return { label: node.getAttribute( 'aria-label' ) || node.textContent || '', width: rect.width, height: rect.height };
        } )
      );
      const smallTargets = visibleButtons.filter( item => item.height < 43.99 || item.width < 31.99 );
      if ( smallTargets.length ) fail( `${viewport.name}: undersized touch targets ${JSON.stringify( smallTargets )}` );

      const chip = page.getByRole( 'button', { name: /Food \+ culture · 4 hours/ } );
      await chip.tap();
      if ( await chip.getAttribute( 'aria-pressed' ) !== 'true' ) fail( `${viewport.name}: preference tap did not toggle` );

      await textarea.fill( 'Two adults in Jaipur on Saturday, relaxed and back by 8 PM.' );
      const send = page.getByRole( 'button', { name: 'Send' } );
      if ( await send.isDisabled() ) fail( `${viewport.name}: send stayed disabled after input` );
      await send.tap();
      await page.locator( '.eta-result' ).first().waitFor( { state: 'visible', timeout: 5000 } );

      if ( await page.locator( '.eta-result' ).count() !== 3 ) fail( `${viewport.name}: expected three ranked results` );
      const firstCard = page.locator( '.eta-result' ).first();
      const cardCursor = await firstCard.evaluate( node => getComputedStyle( node ).cursor );
      if ( cardCursor === 'pointer' ) fail( `${viewport.name}: non-clickable result card advertises pointer affordance` );

      const demoCheckout = firstCard.locator( '.eta-demo-checkout' );
      if ( await demoCheckout.count() !== 1 ) {
        fail( `${viewport.name}: demo result is missing the Checkout control` );
      }
      if ( ( await demoCheckout.locator( '.eta-action-label' ).textContent() || '' ).trim() !== 'Checkout' ) {
        fail( `${viewport.name}: demo checkout label is not Checkout` );
      }
      if ( await demoCheckout.locator( '.eta-checkout-icon' ).textContent() !== 'shopping_cart_checkout' ) {
        fail( `${viewport.name}: demo checkout is missing the shared shopping_cart_checkout icon` );
      }
      if ( await demoCheckout.getAttribute( 'href' ) !== '/checkout/' ) {
        fail( `${viewport.name}: demo checkout does not point to /checkout/` );
      }
      if ( await firstCard.locator( '.eta-checkout' ).count() !== 0 ) {
        fail( `${viewport.name}: demo result exposes live-provider checkout options` );
      }

      const after = await page.evaluate( () => ( {
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      } ) );
      if ( after.scrollWidth > after.clientWidth + 1 ) fail( `${viewport.name}: results introduced horizontal overflow` );

      checks++;
      await context.close();
    }

    const reduceContext = await browser.newContext( {
      viewport: { width: 320, height: 700 },
      hasTouch: true,
      reducedMotion: 'reduce',
    } );
    const reducePage = await reduceContext.newPage();
    await reducePage.goto( `${t.base}/elsewhere/activities/`, { waitUntil: 'load', timeout: 60000 } );
    await reducePage.getByLabel( 'Ask about travel' ).tap();
    const reduced = await reducePage.locator( '.eta-composer' ).evaluate( node => {
      const style = getComputedStyle( node );
      return { transitionDuration: style.transitionDuration, transform: style.transform, boxShadow: style.boxShadow };
    } );
    const reducedTransitionSeconds = Math.max(
      ...reduced.transitionDuration.split( ',' ).map( value => Number.parseFloat( value ) || 0 )
    );
    if ( reducedTransitionSeconds > 0.001 ) {
      fail( `reduced-motion: composer transition is ${reduced.transitionDuration}` );
    }
    if ( reduced.transform !== 'none' || reduced.boxShadow !== 'none' ) {
      fail( `reduced-motion: composer still moves/lifts (${JSON.stringify( reduced )})` );
    }
    await reduceContext.close();

    // Provider contract: a fresh complete live offer unlocks checkout; stale or unsafe
    // variants do not. The injected bridge is a browser fixture only - no external network.
    const liveContext = await browser.newContext( {
      viewport: { width: 320, height: 700 },
      hasTouch: false,
    } );
    await liveContext.addInitScript( () => {
      window.ElsewhereTravelBridge = {
        search: async () => ( {
          source: 'api',
          summary: 'Fresh provider fixture.',
          results: [ {
            id: 'live-1',
            provider: 'Fixture Provider',
            providerRef: 'provider-ref-1',
            offerId: 'offer-1',
            title: 'Fresh live activity',
            description: 'Provider-confirmed fixture used only by the browser contract.',
            meta: [ '3 h' ],
            price: '₹1,850',
            availability: 'Available',
            cancellationSummary: 'Free cancellation until 24 hours before',
            quoteExpiresAt: new Date( Date.now() + 30 * 60 * 1000 ).toISOString(),
            checkoutReady: true,
            websiteUrl: 'https://provider.example/checkout/offer-1',
            whatsappUrl: 'https://wa.me/910000000000',
          } ],
        } ),
      };
    } );
    const livePage = await liveContext.newPage();
    await livePage.goto( `${t.base}/elsewhere/activities/`, { waitUntil: 'load', timeout: 60000 } );
    await livePage.getByLabel( 'Ask about travel' ).fill( 'Provider contract check' );
    await livePage.getByRole( 'button', { name: 'Send' } ).click();
    await livePage.locator( '.eta-result' ).waitFor( { state: 'visible', timeout: 5000 } );
    const liveActions = livePage.locator( '.eta-action' );
    if ( await liveActions.count() !== 1 ) fail( 'provider contract: expected one checkout action' );
    if ( await liveActions.nth( 0 ).isDisabled() ) {
      fail( 'provider contract: fresh complete offer did not unlock checkout' );
    }
    const liveLabels = await livePage.locator( '.eta-action-label' ).allTextContents();
    if ( liveLabels.join( '|' ) !== 'Checkout' ) {
      fail( `provider contract: checkout label is wrong (${liveLabels.join( '|' )})` );
    }
    if ( await livePage.locator( '.eta-checkout-label' ).count() !== 0 ) {
      fail( 'provider contract: route-level payment channel chooser should be gone' );
    }
    if ( await livePage.locator( '.eta-checkout-icon' ).count() !== await liveActions.count() ) {
      fail( 'provider contract: checkout action is missing the shared shopping_cart_checkout icon' );
    }
    if ( await livePage.locator( '.eta-action-icon' ).count() !== 0 ) {
      fail( 'provider contract: the single checkout action should not carry a payment-channel icon' );
    }
    const liveCardBox = await livePage.locator( '.eta-result' ).boundingBox();
    const liveActionBoxes = await liveActions.evaluateAll( nodes => nodes.map( node => {
      const rect = node.getBoundingClientRect();
      const style = getComputedStyle( node );
      return {
        top: rect.top,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
        fontSize: style.fontSize,
        textDecorationLine: style.textDecorationLine,
        borderTopWidth: style.borderTopWidth,
        backgroundColor: style.backgroundColor,
        transform: style.transform,
        scrollWidth: node.scrollWidth,
        clientWidth: node.clientWidth,
      };
    } ) );
    for ( const action of liveActionBoxes ) {
      if ( action.height < 44 ) fail( 'provider contract: checkout button below 44px' );
      if ( px( action.fontSize ) < 16 ) fail( `provider contract: checkout font too small (${action.fontSize})` );
      // Checkout intentionally diverges from Policy Details: amber surface + a reserved 2px
      // contour (transparent until interaction), with no underline. The older assertion required
      // and blocked the browser matrix before device/RTL checks could run.
      if ( action.textDecorationLine !== 'none' ) fail( `provider contract: checkout text decoration drifted (${action.textDecorationLine})` );
      if ( px( action.borderTopWidth ) < 1.5 ) fail( `provider contract: checkout contour is too weak (${action.borderTopWidth})` );
      if ( action.scrollWidth > action.clientWidth + 1 ) fail( 'provider contract: checkout label overflows horizontally' );
      if ( liveCardBox && action.width >= liveCardBox.width * 0.75 ) {
        fail( 'provider contract: checkout control is no longer compact/content-width' );
      }
    }
    // Hover feedback is intentionally guarded in production by the exact
    // (hover:hover) and (pointer:fine) capability query. Playwright WebKit can accept
    // locator.hover() while still reporting a non-hover pointer, in which case the CSS
    // must NOT activate. Assert the hover treatment only when the browser says that rule
    // is applicable; Chromium/Firefox desktop contexts continue to exercise it.
    const hoverCapable = await livePage.evaluate( () =>
      window.matchMedia( '(hover:hover) and (pointer:fine)' ).matches
    );
    const beforeHover = await liveActions.nth( 0 ).evaluate( node => {
      const style = getComputedStyle( node );
      return { backgroundColor: style.backgroundColor, transform: style.transform, boxShadow: style.boxShadow };
    } );
    await liveActions.nth( 0 ).hover();
    await livePage.waitForTimeout( 220 );
    const afterHover = await liveActions.nth( 0 ).evaluate( node => {
      const style = getComputedStyle( node );
      return { backgroundColor: style.backgroundColor, transform: style.transform, boxShadow: style.boxShadow };
    } );
    if ( hoverCapable && beforeHover.backgroundColor === afterHover.backgroundColor ) {
      fail( 'provider contract: checkout hover background does not change on a hover-capable pointer' );
    }
    if ( hoverCapable && afterHover.transform === 'none' && afterHover.boxShadow === 'none' ) {
      fail( 'provider contract: checkout hover has no feedback on a hover-capable pointer' );
    }
    const livePrice = livePage.locator( '.eta-price' );
    if ( await livePrice.locator( '.eta-price-icon' ).count() !== 1 ) {
      fail( 'provider contract: INR price is missing the rupee icon' );
    }
    if ( !( await livePrice.textContent() || '' ).includes( '1,850' ) ) {
      fail( 'provider contract: live amount is not visible beside the rupee icon' );
    }
    if ( await livePage.locator( '.eta-provider' ).textContent() !== 'Fixture Provider' ) {
      fail( 'provider contract: external provider label missing' );
    }
    await liveContext.close();

    const staleContext = await browser.newContext( {
      viewport: { width: 375, height: 812 },
      hasTouch: true,
    } );
    await staleContext.addInitScript( () => {
      window.ElsewhereTravelBridge = {
        search: async () => ( {
          source: 'api',
          results: [ {
            id: 'stale-1',
            provider: 'Fixture Provider',
            providerRef: 'provider-ref-stale',
            title: 'Expired live activity',
            description: 'Expired fixture.',
            meta: [],
            price: '₹1,850',
            availability: 'Available',
            cancellationSummary: 'Non-refundable',
            quoteExpiresAt: new Date( Date.now() - 60 * 1000 ).toISOString(),
            checkoutReady: true,
            websiteUrl: 'https://provider.example/checkout/expired-offer',
            whatsappUrl: 'https://wa.me/910000000000',
          } ],
        } ),
      };
    } );
    const stalePage = await staleContext.newPage();
    await stalePage.goto( `${t.base}/elsewhere/activities/`, { waitUntil: 'load', timeout: 60000 } );
    await stalePage.getByLabel( 'Ask about travel' ).fill( 'Expired provider contract check' );
    await stalePage.getByRole( 'button', { name: 'Send' } ).tap();
    await stalePage.locator( '.eta-result' ).waitFor( { state: 'visible', timeout: 5000 } );
    const staleActions = stalePage.locator( '.eta-action' );
    if ( await staleActions.count() !== 0 ) {
      fail( 'provider contract: expired offer still exposed checkout' );
    }
    await staleContext.close();

    console.log( `elsewherecheck [${engineName}] ${checks}/${VIEWPORTS.length} touch viewports clean + reduced-motion + provider contract clean` );
  } finally {
    await browser.close();
    if ( t.close ) await t.close();
  }
})().catch( error => {
  console.error( error );
  process.exit( 1 );
});
