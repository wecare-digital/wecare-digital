'use strict';

/**
 * Elsewhere assistant touch/responsive contract.
 *
 * Runs against the production export in Chromium, Firefox and WebKit. This is not a
 * substitute for a physical iPhone/Android device, but it makes the previously-manual
 * 320/375px touch assumptions executable in every public browser matrix run.
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
  { name: 'phone', width: 375, height: 812 },
  { name: 'large-phone', width: 390, height: 844 },
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
        return {
          pageScrollWidth: root.scrollWidth,
          clientWidth: root.clientWidth,
          shellLeft: shellRect.left,
          shellRight: shellRect.right,
          tabsScrollWidth: tabs.scrollWidth,
          tabsClientWidth: tabs.clientWidth,
          tabsTouchAction: getComputedStyle( tabs ).touchAction,
          responseTouchAction: getComputedStyle( response ).touchAction,
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
      if ( geometry.tabButtons.length !== 6 ) fail( `${viewport.name}: expected six travel tabs` );
      const firstTop = geometry.tabButtons[ 0 ].top;
      if ( geometry.tabButtons.some( item => Math.abs( item.top - firstTop ) > 1 ) ) {
        fail( `${viewport.name}: travel tabs wrapped to multiple rows` );
      }
      if ( viewport.width <= 720 ) {
        if ( geometry.tabsTouchAction !== 'pan-x' ) fail( `${viewport.name}: tab rail touch-action ${geometry.tabsTouchAction}` );
        if ( geometry.tabsScrollWidth <= geometry.tabsClientWidth ) fail( `${viewport.name}: tab rail is not horizontally scrollable` );
      }
      if ( geometry.responseTouchAction !== 'pan-y' ) fail( `${viewport.name}: response touch-action ${geometry.responseTouchAction}` );

      const textarea = page.getByLabel( 'Ask about travel' );
      await textarea.tap();
      const composerStyle = await page.locator( '.eta-composer' ).evaluate( node => {
        const style = getComputedStyle( node );
        return { boxShadow: style.boxShadow, transform: style.transform };
      } );
      if ( composerStyle.boxShadow === 'none' ) fail( `${viewport.name}: composer has no focus/touch feedback` );
      if ( composerStyle.transform !== 'none' ) fail( `${viewport.name}: composer moves on touch (${composerStyle.transform})` );

      const mic = page.locator( '[data-voice-search-mic="true"]' );
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
      const preview = page.locator( '.eta-preview-note' );
      if ( await preview.count() !== 1 ) fail( `${viewport.name}: demo results are not explicitly marked as preview` );

      const firstCard = page.locator( '.eta-result' ).first();
      const cardCursor = await firstCard.evaluate( node => getComputedStyle( node ).cursor );
      if ( cardCursor === 'pointer' ) fail( `${viewport.name}: non-clickable result card advertises pointer affordance` );

      const actions = firstCard.locator( '.eta-action' );
      if ( await actions.count() !== 2 ) fail( `${viewport.name}: first result does not have two checkout channels` );
      if ( !( await actions.nth( 0 ).isDisabled() ) || !( await actions.nth( 1 ).isDisabled() ) ) {
        fail( `${viewport.name}: demo checkout actions should stay disabled without live provider confirmation` );
      }

      const actionBoxes = await actions.evaluateAll( nodes => nodes.map( node => {
        const rect = node.getBoundingClientRect();
        const style = getComputedStyle( node );
        return {
          top: rect.top,
          width: rect.width,
          height: rect.height,
          fontSize: style.fontSize,
          scrollWidth: node.scrollWidth,
          clientWidth: node.clientWidth,
        };
      } ) );
      if ( Math.abs( actionBoxes[ 0 ].top - actionBoxes[ 1 ].top ) > 1 ) {
        fail( `${viewport.name}: checkout buttons are not inline` );
      }
      for ( const action of actionBoxes ) {
        if ( action.height < 44 ) fail( `${viewport.name}: checkout button below 44px` );
        if ( px( action.fontSize ) < 16 ) fail( `${viewport.name}: checkout font too small (${action.fontSize})` );
        if ( action.scrollWidth > action.clientWidth + 1 ) fail( `${viewport.name}: checkout label overflows horizontally` );
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
    if ( reduced.transitionDuration !== '0s' ) fail( `reduced-motion: composer transition is ${reduced.transitionDuration}` );
    if ( reduced.transform !== 'none' || reduced.boxShadow !== 'none' ) {
      fail( `reduced-motion: composer still moves/lifts (${JSON.stringify( reduced )})` );
    }
    await reduceContext.close();

    // Provider contract: a fresh complete live offer unlocks checkout; stale or unsafe
    // variants do not. The injected bridge is a browser fixture only - no external network.
    const liveContext = await browser.newContext( {
      viewport: { width: 375, height: 812 },
      hasTouch: true,
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
    await livePage.getByRole( 'button', { name: 'Send' } ).tap();
    await livePage.locator( '.eta-result' ).waitFor( { state: 'visible', timeout: 5000 } );
    const liveActions = livePage.locator( '.eta-action' );
    if ( await liveActions.count() !== 2 ) fail( 'provider contract: missing checkout channels' );
    if ( await liveActions.nth( 0 ).isDisabled() || await liveActions.nth( 1 ).isDisabled() ) {
      fail( 'provider contract: fresh complete offer did not unlock checkout' );
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
            websiteUrl: 'http://provider.example/insecure',
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
    if ( !( await staleActions.nth( 0 ).isDisabled() ) || !( await staleActions.nth( 1 ).isDisabled() ) ) {
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
