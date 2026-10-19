import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * THE BOTTOM-RIGHT CORNER BELONGS TO THE SUPPORT PILL, AND TO NOTHING ELSE.
 *
 * Two files have to agree about that and neither imports the other, which is how they came
 * to disagree. Footer.tsx put the lime brand dash in the bottom-right of the footer;
 * SupportWidget.tsx pins a fixed pill to the bottom-right of the viewport. At the end of the
 * page they occupied the same space:
 *
 *   1440   the pill covered 34px of the 56px dash
 *   768    the dash was ENTIRELY behind the pill
 *   412    they cleared by 8px, which flips to an overlap on a taller device
 *   phones the pill landed inside the footer at all seven sizes
 *
 * The dash was ALSO in the wrong place on its own terms: the instruction for this footer was
 * that the right side be blank, and the dash was the only thing in it.
 *
 * Two changes answer it, and this file pins both because either one alone leaves the
 * collision reachable: the dash moved into the brand block, and below 768px the pill parks
 * above the footer instead of descending into it.
 *
 * uicheck.js asserts the RESULT - that the pill covers no footer content at four widths, at
 * the end of the page. These assertions pin the MECHANISM, so a change that happens to look
 * fine at those four widths still has to be deliberate.
 */

const read = ( file: string ): string => fs.readFileSync( path.join( process.cwd(), file ), 'utf8' );

/**
 * Source with comments removed.
 *
 * Every negative assertion below would otherwise fire on the notes explaining the very
 * thing being forbidden - both files now describe the collision they used to have, in prose
 * containing the exact declarations being searched for. This has bitten this suite four
 * times; strip first, assert second.
 */
const code = ( file: string ): string =>
  read( file )
    .replace( /\/\*[\s\S]*?\*\//g, '' )
    .replace( /^\s*\/\/.*$/gm, '' );

const footer = code( 'src/components/Footer.tsx' );
const widget = code( 'src/components/SupportWidget.tsx' );

describe( 'footer brand dash', () => {
  it( 'sits inside the brand block, not in the right-hand column', () => {
    // Order, not just presence: the dash must appear between the tagline and the close of
    // .ft-brand. Testing only that both strings exist would pass with the dash back outside.
    const taglineAt = footer.indexOf( 'className="ft-tagline"' );
    const dashAt = footer.indexOf( 'className="ft-dash"' );
    const brandCloseAt = footer.indexOf( '</div>', taglineAt );

    expect( taglineAt, 'ft-tagline not found' ).toBeGreaterThan( -1 );
    expect( dashAt, 'ft-dash not found' ).toBeGreaterThan( -1 );
    expect(
      dashAt > taglineAt && dashAt < brandCloseAt,
      'The lime dash must render inside .ft-brand, after the tagline. In the right-hand '
      + 'column it shares the bottom-right corner with the fixed support pill, which covered '
      + '34px of it at 1440 and all of it at 768 - and it left the footer\'s right side '
      + 'occupied when the instruction was for it to be blank.'
    ).toBe( true );
  } );

  it( 'is not pinned to the right by align-self', () => {
    // align-self: flex-end was the declaration that kept the dash on the right even below
    // 768px, where .ft-grid becomes a column with align-items: flex-start. That override is
    // why the collision was not a desktop-only problem.
    const dashRule = /\.ft-dash\s*\{([^}]*)\}/.exec( footer );
    expect( dashRule, 'no .ft-dash rule found' ).not.toBeNull();
    expect(
      /align-self/.test( dashRule![ 1 ] ),
      '.ft-dash must not set align-self. flex-end pins it to the right edge and OVERRIDES '
      + 'the column grid\'s align-items: flex-start below 768px, putting it back in the '
      + 'pill\'s column at every width.'
    ).toBe( false );
  } );

  it( 'does not fling a future second element into the pill\'s corner', () => {
    // space-between with one child does nothing, but the moment something is added opposite
    // the brand it lands in the bottom-right - which is exactly how the dash got there.
    const gridRule = /\.ft-grid\s*\{([^}]*)\}/.exec( footer );
    expect( gridRule, 'no .ft-grid rule found' ).not.toBeNull();
    expect( gridRule![ 1 ] ).toMatch( /justify-content\s*:\s*flex-start/ );
    expect( gridRule![ 1 ] ).not.toMatch( /justify-content\s*:\s*space-between/ );
  } );
} );

describe( 'support pill on phones', () => {
  it( 'rests at the same offset as desktop, not above a bar that is not there', () => {
    // 72px cleared the dashboard BottomNav. BottomNav is rendered by Layout.tsx, which no
    // public page uses - checked at fourteen widths and absent at every one - so every
    // public phone page floated the pill 72px above empty space.
    expect( widget ).toContain( 'bottom:calc(20px + env(safe-area-inset-bottom))' );
    // The dashboard keeps it, because there the bar is real.
    expect( widget ).toContain( '.wc-langbar.is-appshell{bottom:calc(72px + env(safe-area-inset-bottom))}' );
    expect( widget ).toContain( "setAppShell( !!document.querySelector( '.layout' ) )" );
  } );

  it( 'drops the chevron and tightens the chip below 768px', () => {
    // 108px is 27% of a 390px screen and 32% of a folded 280px one. The chevron is the only
    // part that can go without cost: it hints that the chip opens something, which a pointer
    // needs and a tap does not - tapping opens the OS language picker either way.
    expect( widget ).toContain( '.wc-arw{display:none}' );
    expect( widget ).toMatch( /\.wc-chip\{min-width:44px/ );
  } );

  it( 'does NOT shrink the controls below the touch floor', () => {
    // The mockup for the slim size used a 36px icon. It was not implemented: 36px is under
    // the 44px touch guideline on the device where that matters most, and 40px is already a
    // compromise held in place by the roundness fix. Width was the complaint, so width is
    // what was spent. This pins the decision so a later "make it smaller still" has to
    // argue with it rather than slide past.
    expect( widget ).toContain( '.wc-wa{width:44px;height:44px;min-width:44px;min-height:44px' );
    expect( widget ).not.toMatch( /\.wc-wa\{width:3\dpx/ );
  } );

  it( 'parks above the footer by measuring it, never by a fixed number', () => {
    // A hardcoded offset would be right on six phones and wrong on the narrowest: at 280px
    // the footer is 216px tall, not 192, because the tagline wraps onto an extra line.
    expect( widget ).toContain( "document.querySelector( 'footer.ft-footer' )" );
    expect( widget ).toContain( 'getBoundingClientRect().top' );
    expect( widget ).toContain( 'const PARK_GAP = 16' );
    // Mobile only - above 767px the footer is short enough that the pill clears it at rest.
    expect( widget ).toContain( 'const MOBILE_MAX = 767' );
    expect( widget ).toContain( 'window.innerWidth > MOBILE_MAX' );
  } );

  it( 'cannot park behind the fixed header', () => {
    // No current device triggers this - on a 320x568 screen the parked pill sits at y316 and
    // the header ends at y96. It is pinned because a landscape phone or a taller footer would
    // turn one collision into another, and nothing would notice.
    expect( widget ).toContain( 'const HEADER_GAP = 12' );
    expect( widget ).toContain( "document.querySelector( 'header.hdr' )" );
    expect( widget ).toMatch( /ceiling/ );
  } );

  it( 'does not set state on every scroll event', () => {
    // A scroll listener that writes state per event fires dozens of times a frame on a
    // trackpad or a momentum flick, and each write is a React render.
    expect( widget ).toContain( 'requestAnimationFrame' );
    expect( widget ).toContain( 'cancelAnimationFrame' );
    expect( widget ).toContain( "{ passive: true }" );
  } );

  it( 'leaves the resting position to CSS', () => {
    // The parked offset is a measured pixel value that changes per frame, so it has to be
    // inline. The resting offset must NOT be: keeping it in the stylesheet is what keeps
    // desktop and the un-scrolled state declarative, and means the pill is positioned
    // correctly before any JavaScript runs.
    expect( widget ).toContain( 'parkedBottom === null ? undefined' );
  } );
} );

describe( 'the retired contact-test page', () => {
  it( 'is gone from the tree, not merely de-listed', () => {
    // It was the only route both in the public allowlist AND wrapped in the authenticated
    // Layout, which prerendered the entire staff sidebar into public HTML at HTTP 200. The
    // allowlist entry was removed first to stop the exposure; the file follows. It also
    // duplicated /contact with a form whose submit handler resolved a setTimeout and threw
    // the message away.
    expect( fs.existsSync( path.join( process.cwd(), 'src', 'pages', 'contact-test' ) ) ).toBe( false );
    const app = code( 'src/pages/_app.tsx' );
    expect( app ).not.toContain( "router.pathname === '/contact-test'" );
  } );
} );
