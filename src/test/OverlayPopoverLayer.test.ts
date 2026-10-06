import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * INVARIANT 7 - A Layer 2 CONTROL RENDERED INSIDE THE CONFIRM DIALOG MUST PASS layer="overlay".
 *
 * IT IS VACUOUSLY TRUE TODAY, AND THAT IS WHY IT IS COMMITTED. Nothing currently renders a
 * Select, a DateField or a ColorField inside src/contexts/ConfirmContext.tsx - no call site
 * puts a dropdown in a confirm dialog. The invariant exists so the layering analysis behind it
 * is not re-derived by the first person who does, at which point the failure is a menu that
 * opens UNDERNEATH the dialog that owns it and nothing in the suite says why.
 *
 * THE ANALYSIS, in one paragraph so it survives here rather than only in the design document.
 * A Popover's default layer is 1500, which clears every piece of persistent chrome measured -
 * .inner-header 99, .tabs 100/101, .sidebar 100 and 1000 at <=768px - and deliberately sits
 * BELOW the app's real transient-overlay band so a modal or a toast still wins over a stray
 * open menu. That band is 9998-10002, measured across Layout.css, inner-ux.css,
 * flex-layout.css and Layout.tsx, and ConfirmContext's own backdrop is an inline
 * `zIndex: 10000` whose dialog card is a non-positioned child. So inside that dialog, and
 * only there, 1500 is under the thing it belongs to and layer="overlay" (10001) is required.
 * The toast band at 10002 (Layout.css:1718, inner-ux.css:776) still wins, correctly.
 *
 * WHAT WAS REJECTED, recorded because it is the obvious-looking fix: migrating
 * ConfirmContext's backdrop down to var(--z-modal) (1410) so the token scale would apply.
 * The --z-* scale is ASPIRATIONAL AND UNUSED - nothing in the tree reads it - and lowering the
 * confirm dialog to 1410 would put it UNDER at least six existing overlays. Reconciling the
 * whole app to the scale is a separate task and not a prerequisite for a dropdown.
 *
 * A SOURCE TEST RATHER THAN A RENDER TEST, because jsdom computes no stacking context: the
 * two numbers being in the wrong order is invisible to it. What is checkable without a browser
 * is the call-site shape, which is the thing a future edit would get wrong.
 */
const SRC = join( __dirname, '..' );

/** The three Layer 2 controls that own a Popover. TimeField and DateTimeField compose them. */
const LAYERED = [ 'Select', 'DateField', 'ColorField' ];

/**
 * Every opening tag for one of those components, with the whole tag body, comments removed
 * first. The prose in ConfirmContext and in this file necessarily writes `<Select` while
 * explaining the rule, and a scan of the raw text would fail on the explanation - the exact
 * trap ScrollbarDeclarations.test.ts and LogicalDirectionCss.test.tsx both record being
 * caught by.
 */
function offenders ( source: string ): string[] {
  const code = source
    .replace( /\/\*[\s\S]*?\*\//g, '' )
    .replace( /^\s*\/\/.*$/gm, '' );

  const found: string[] = [];
  for ( const component of LAYERED ) {
    // `(?![A-Za-z])` so `<SelectAll` or `<DateFieldGroup` is not read as `<Select`.
    const tag = new RegExp( `<${ component }(?![A-Za-z0-9_])([^>]*)>`, 'g' );
    for ( const match of code.matchAll( tag ) ) {
      const attributes = match[ 1 ];
      if ( /layer\s*=\s*(?:"overlay"|'overlay'|\{\s*['"]overlay['"]\s*\})/.test( attributes ) ) continue;
      found.push( `<${ component }${ attributes.replace( /\s+/g, ' ' ) }>` );
    }
  }
  return found;
}

describe( 'a Popover inside the Confirm dialog uses layer="overlay"', () => {
  it( 'ConfirmContext.tsx renders no Layer 2 control without layer="overlay"', () => {
    const source = readFileSync( join( SRC, 'contexts', 'ConfirmContext.tsx' ), 'utf8' );
    expect(
      offenders( source ),
      'A Select / DateField / ColorField inside the Confirm dialog must pass layer="overlay". '
      + "The dialog's backdrop is an inline zIndex: 10000 and its card is a non-positioned "
      + 'child, so a default Popover at 1500 opens UNDERNEATH the dialog it belongs to. '
      + 'layer="overlay" is 10001 (zIndex.overlayPopover in src/lib/design-tokens.ts), which '
      + 'paints above the card and still loses to the 10002 toast band, as it should.'
    ).toEqual( [] );
  } );

  it( 'detects a planted sample, so a silent pass cannot be mistaken for proof', () => {
    // The scanner is tested before it is trusted. This assertion is the whole reason a
    // vacuously-true gate is worth committing: without it, a regex that matched nothing would
    // pass forever on an empty file and still get cited as evidence.
    expect( offenders( '<Select value={v} onChange={set} ariaLabel="x" />' ) ).toHaveLength( 1 );
    expect( offenders( '<DateField value={v} onChange={set} label="When" />' ) ).toHaveLength( 1 );
    expect( offenders( '<ColorField value={v} onChange={set} label="Brand" />' ) ).toHaveLength( 1 );

    // All three accepted spellings of the attribute pass.
    expect( offenders( '<Select layer="overlay" value={v} />' ) ).toEqual( [] );
    expect( offenders( "<Select layer={ 'overlay' } value={v} />" ) ).toEqual( [] );

    // A different layer is NOT an exemption.
    expect( offenders( '<Select layer="default" value={v} />' ) ).toHaveLength( 1 );

    // A component whose name merely starts the same way is not one of ours.
    expect( offenders( '<SelectAll checked={all} />' ) ).toEqual( [] );

    // And prose is not code.
    expect( offenders( '/* never render <Select> here without layer="x" */' ) ).toEqual( [] );
    expect( offenders( '// <DateField /> is banned in this file' ) ).toEqual( [] );
  } );

  it( 'the overlay layer is the number the analysis picked, and is bracketed as documented', () => {
    // Pinned so the two numbers that bracket it cannot drift apart silently: if
    // ConfirmContext's backdrop moves, this pairing is where the mismatch shows up.
    const tokens = readFileSync( join( SRC, 'lib', 'design-tokens.ts' ), 'utf8' );
    expect( tokens ).toMatch( /overlayPopover:\s*10001/ );

    const confirm = readFileSync( join( SRC, 'contexts', 'ConfirmContext.tsx' ), 'utf8' );
    expect( confirm ).toMatch( /zIndex:\s*10000/ );
  } );
} );
