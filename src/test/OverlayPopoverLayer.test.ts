import { readdirSync, readFileSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

import { describe, expect, it } from 'vitest';

import { zIndex } from '../lib/design-tokens';

/**
 * INVARIANT 7 - A LAYER 2 CONTROL WHOSE OUTERMOST POSITIONED ANCESTOR RESOLVES ABOVE
 * `zIndex.popover` MUST PASS layer="overlay".
 *
 * IT WAS SCOPED TO ONE FILE AND THAT WAS THE BUG. The first version of this gate read only
 * src/contexts/ConfirmContext.tsx, because the Confirm dialog was the container the design
 * analysis had in hand. The hazard is not the Confirm dialog; it is ANY container that
 * resolves above 1500 in the ROOT stacking context. Scoped to one file, the suite was green
 * while two shipped controls were broken:
 *
 *   - pay/flow's invoice-edit modal put a Brand Select inside `.pf-modal-overlay` (9999). The
 *     menu painted under a 40% black veil, and a click aimed at an option landed on the
 *     overlay instead, whose onClick closes the modal and DISCARDS THE EDIT.
 *   - link's create/edit modal put the expiry DateField inside `.link-modal-overlay` (9999).
 *     The calendar painted behind the veil AND behind the opaque `.link-modal` - hidden, not
 *     merely dimmed - in the only place that control is rendered.
 *
 * Both now pass layer="overlay". The gate below is what makes the third one fail loudly.
 *
 * THE ANALYSIS, in one paragraph so it survives here rather than only in the design document.
 * A Popover's default layer is 1500, which clears every piece of persistent chrome measured -
 * .inner-header 99, .tabs 100/101, .sidebar 100 and 1000 at <=768px - and deliberately sits
 * BELOW the app's real transient-overlay band so a modal or a toast still wins over a stray
 * open menu. That band is 9998-10002, measured across Layout.css, inner-ux.css,
 * flex-layout.css and Layout.tsx. A Popover portals to document.body, so when its owning
 * container is in that band the two compete in the ROOT stacking context and 1500 loses.
 * layer="overlay" is 10001, above every measured container and still below the 10002 toast
 * band, which must stay readable over an open menu.
 *
 * WHY THE OUTERMOST ANCESTOR AND NOT THE NEAREST ONE. The first run of the widened scan
 * reported seven Selects in engage/whatsapp/templates.tsx, because each sits inside
 * `.modal`, and Layout.css:1696 gives `.modal` `position: fixed` with `z-index: 10001`. They
 * are NOT broken, and the reason is the whole of why this gate resolves a chain rather than a
 * class. `.modal` is a child of `.modal-overlay`, which is `position: fixed` with
 * `z-index: 1000` - a positioned element with a z-index establishes a STACKING CONTEXT, so
 * `.modal`'s 10001 is an ordering INSIDE its overlay and never reaches the root. What the
 * portal at 1500 actually competes with is the outermost such ancestor, 1000, and 1500 wins.
 * Requiring layer="overlay" there would have been the harmful direction: 10001 would lift
 * those menus above every other overlay in the app. The two real findings differ precisely
 * here - `.pf-modal-overlay` and `.link-modal-overlay` ARE the outermost positioned ancestor,
 * so their 9999 is a root-level number and it beats 1500.
 *
 * WHAT WAS REJECTED, recorded because it is the obvious-looking fix: migrating the overlays
 * down to var(--z-modal) (1410) so the token scale would apply. The --z-* scale is
 * ASPIRATIONAL AND UNUSED - nothing in the tree reads it - and lowering the confirm dialog to
 * 1410 would put it UNDER at least six existing overlays. Reconciling the whole app to the
 * scale is a separate task and not a prerequisite for a dropdown.
 *
 * A SOURCE TEST RATHER THAN A RENDER TEST, because jsdom computes no stacking context: the
 * two numbers being in the wrong order is invisible to it. What is checkable without a
 * browser is the call-site shape, which is the thing a future edit would get wrong.
 */
const SRC = join( __dirname, '..' );
const REPO = join( SRC, '..' );

/**
 * The three Layer 2 controls that own a Popover, plus the two that compose them.
 *
 * TimeField and DateTimeField are listed because both FORWARD `layer` to the DateField and
 * TimeField they wrap - so a DateTimeField inside an overlay needs the prop just as much, and
 * omitting it from this list would reopen the hole on the composed controls only.
 */
const LAYERED = [ 'Select', 'DateField', 'ColorField', 'TimeField', 'DateTimeField' ];

const WALK = ( dir: string, match: RegExp, out: string[] = [] ): string[] => {
  for ( const entry of readdirSync( dir, { withFileTypes: true } ) ) {
    if ( entry.name === 'node_modules' || entry.name.startsWith( '.' ) ) continue;
    const full = join( dir, entry.name );
    if ( entry.isDirectory() ) WALK( full, match, out );
    else if ( match.test( entry.name ) ) out.push( full );
  }
  return out;
};

const rel = ( full: string ) => relative( REPO, full ).split( sep ).join( '/' );

/**
 * Strip comments, so prose explaining the rule is not read as a violation of it.
 *
 * This file, ConfirmContext and both fixed call sites all necessarily write `<Select` and
 * `layer="overlay"` while explaining why - a scan of the raw text would fail on its own
 * explanation. ScrollbarDeclarations.test.ts and LogicalDirectionCss.test.tsx both record
 * being caught by exactly this.
 */
const codeOnly = ( source: string ): string => source
  .replace( /\/\*[\s\S]*?\*\//g, ' ' )
  .replace( /^[ \t]*\/\/.*$/gm, ' ' );

/**
 * What a class contributes to stacking: its highest declared z-index, and whether any rule
 * for it declares a `position` that makes a z-index apply at all.
 *
 * BOTH HALVES ARE NEEDED. `z-index` on a static element is inert, so a class carrying one
 * without a position does not establish a stacking context and must not be read as a layer.
 * They are accumulated across rules rather than per-rule because this tree splits them - a
 * base rule positions the element and a media-query rule re-declares the number.
 */
type ClassLayer = { z?: number; positioned: boolean };

/**
 * class name -> its stacking contribution.
 *
 * SCANNED, NOT HARDCODED, and from .tsx as well as .css: two of the containers in this tree
 * are styled-jsx declared inside the component that renders them (`.dm-modal-backdrop` in
 * engage/index.tsx, `.modal-overlay` in engage/whatsapp/templates.tsx), so a CSS-only table
 * would miss them and a hand-written table would go stale the day someone adds another.
 *
 * `z-index:` in its CSS spelling is the filter that makes scanning raw .tsx safe: React
 * inline styles write `zIndex:`, so a JS object literal cannot be mistaken for a rule.
 *
 * HIGHEST rather than first, because a rule may be repeated under a media query and the
 * conservative direction here is the one that REQUIRES the prop.
 */
const buildClassLayers = (): Map<string, ClassLayer> => {
  const table = new Map<string, ClassLayer>();
  const files = [ ...WALK( SRC, /\.css$/ ), ...WALK( SRC, /\.tsx$/ ) ];

  for ( const file of files ) {
    const text = codeOnly( readFileSync( file, 'utf8' ) );
    // A rule block with no nested block: `selector { declarations }`. Media queries nest, so
    // the outer block never matches and the inner rule still does.
    for ( const rule of text.matchAll( /([^{}();]+)\{([^{}]*)\}/g ) ) {
      const [ , selector, body ] = rule;
      const z = /(?:^|[;\s])z-index\s*:\s*(\d+)/.exec( body );
      const positioned = /(?:^|[;\s])position\s*:\s*(fixed|absolute|sticky|relative)/.test( body );
      if ( !z && !positioned ) continue;

      for ( const cls of selector.matchAll( /\.([A-Za-z_-][\w-]*)/g ) ) {
        const name = cls[ 1 ];
        const entry = table.get( name ) ?? { positioned: false };
        if ( z ) entry.z = Math.max( entry.z ?? 0, Number( z[ 1 ] ) );
        if ( positioned ) entry.positioned = true;
        table.set( name, entry );
      }
    }
  }
  return table;
};

const CLASS_LAYERS = buildClassLayers();

/**
 * The root-level z-index a `className` value establishes, or undefined if it establishes no
 * stacking context at all.
 */
const layerOf = ( value: string, table: Map<string, ClassLayer> ): number | undefined => {
  let best: number | undefined;
  for ( const token of value.matchAll( /[A-Za-z_-][\w-]*/g ) ) {
    const entry = table.get( token[ 0 ] );
    if ( !entry?.positioned || entry.z === undefined ) continue;
    best = Math.max( best ?? 0, entry.z );
  }
  return best;
};

/** The index of the `>` closing the tag that starts at `from`, or -1. */
const endOfOpeningTag = ( code: string, from: number ): number => {
  let depth = 0;
  for ( let i = from; i < code.length; i += 1 ) {
    const c = code[ i ];
    if ( c === '\'' || c === '"' || c === '`' ) {
      i += 1;
      while ( i < code.length && code[ i ] !== c ) i += code[ i ] === '\\' ? 2 : 1;
      continue;
    }
    if ( c === '{' ) depth += 1;
    else if ( c === '}' ) depth -= 1;
    else if ( c === '>' && depth === 0 ) return i;
  }
  return -1;
};

/**
 * The attribute text of the opening tag starting at `from`.
 *
 * `[^>]*` CANNOT DO THIS, and the first run of the widened scan proved it: the fixed Brand
 * Select in pay/flow is written
 *
 *     <Select ariaLabel="Brand" value={ editForm.purpose }
 *       onChange={ v => setEditForm( { ...editForm, purpose: v } ) }
 *       options={ brandOptions } layer="overlay" />
 *
 * and the `>` of the arrow function ends a `[^>]*` match three attributes early - so the
 * scanner reported a control that DOES pass the prop. Any handler written `v =>` or `a > b`
 * hides every attribute after it, which includes `layer`. Brace depth is the real boundary.
 */
const openingTagAttributes = ( code: string, from: number ): string => {
  const end = endOfOpeningTag( code, from );
  return end < 0 ? '' : code.slice( from, end );
};

type Region = { from: number; to: number; z: number; classes: string };

/**
 * The text spans covered by elements that establish a stacking context, with the z-index each
 * establishes.
 *
 * NESTING IS COMPUTED, NOT ASSUMED, and that is the difference between this gate and a grep.
 * `pay/flow/index.tsx` renders `.pf-modal-overlay` THREE times and holds nine layered
 * controls; only one of those controls is inside one of those overlays. A file-level rule
 * would demand layer="overlay" on the other eight, where it is wrong - 10001 would lift an
 * ordinary inline dropdown over every modal in the app - and the churn would get the gate
 * switched off. So each container's opening tag is matched to its close by counting
 * same-named tags, and the control is resolved against the span it actually lands in.
 */
const stackingRegions = ( code: string, table: Map<string, ClassLayer> ): Region[] => {
  const regions: Region[] = [];

  for ( const attr of code.matchAll( /className\s*=\s*(?:"([^"]*)"|'([^']*)'|\{([^{}]*)\})/g ) ) {
    const raw = attr[ 1 ] ?? attr[ 2 ] ?? attr[ 3 ] ?? '';
    const z = layerOf( raw, table );
    if ( z === undefined ) continue;

    // Walk back to the `<` that opens the tag carrying this attribute.
    const open = code.lastIndexOf( '<', attr.index );
    if ( open < 0 ) continue;
    const tag = /^<([A-Za-z][\w.-]*)/.exec( code.slice( open ) );
    if ( !tag ) continue;
    const name = tag[ 1 ];

    const close = endOfOpeningTag( code, open );
    if ( close < 0 ) continue;
    if ( code[ close - 1 ] === '/' ) continue;   // self-closing: encloses nothing

    const openTag = new RegExp( `<${ name }(?![\\w.-])`, 'g' );
    const closeTag = new RegExp( `</${ name }\\s*>`, 'g' );
    let level = 1;
    let cursor = close + 1;
    while ( cursor < code.length && level > 0 ) {
      openTag.lastIndex = cursor;
      closeTag.lastIndex = cursor;
      const nextOpen = openTag.exec( code );
      const nextClose = closeTag.exec( code );
      if ( !nextClose ) break;
      if ( nextOpen && nextOpen.index < nextClose.index ) {
        level += 1;
        cursor = nextOpen.index + nextOpen[ 0 ].length;
      } else {
        level -= 1;
        cursor = nextClose.index + nextClose[ 0 ].length;
        if ( level === 0 ) regions.push( { from: close, to: nextClose.index, z, classes: raw.trim() } );
      }
    }
  }
  return regions;
};

/** Every layered control tag in `code`, with its offset and its attribute text. */
const layeredControls = ( code: string ): { tag: string; index: number; attributes: string }[] => {
  const found: { tag: string; index: number; attributes: string }[] = [];
  for ( const component of LAYERED ) {
    // `(?![A-Za-z0-9_])` so `<SelectAll` or `<DateFieldGroup` is not read as one of ours.
    const tag = new RegExp( `<${ component }(?![A-Za-z0-9_])`, 'g' );
    for ( const match of code.matchAll( tag ) ) {
      found.push( {
        tag: component,
        index: match.index,
        attributes: openingTagAttributes( code, match.index + match[ 0 ].length ),
      } );
    }
  }
  return found;
};

const HAS_OVERLAY_LAYER = /layer\s*=\s*(?:"overlay"|'overlay'|\{\s*['"]overlay['"]\s*\})/;

const describeTag = ( tag: string, attributes: string ) =>
  `<${ tag }${ attributes.replace( /\s+/g, ' ' ).replace( /\s*\/$/, '' ).trimEnd() }>`;

/**
 * A layered control whose OUTERMOST enclosing stacking context resolves above the popover
 * layer and which does not pass the prop.
 *
 * Used for the whole-tree scan AND for the planted samples, so the mechanism that produces
 * the verdict is the mechanism that is tested.
 */
export const offenders = (
  source: string,
  table: Map<string, ClassLayer> = CLASS_LAYERS,
): string[] => {
  const code = codeOnly( source );
  const regions = stackingRegions( code, table );
  if ( regions.length === 0 ) return [];

  const found: string[] = [];
  for ( const control of layeredControls( code ) ) {
    if ( HAS_OVERLAY_LAYER.test( control.attributes ) ) continue;

    // The OUTERMOST container is the one that competes with the portal in the root context;
    // an inner container's larger number is confined to it. See the header.
    const enclosing = regions
      .filter( r => control.index > r.from && control.index < r.to )
      .sort( ( a, b ) => a.from - b.from );
    const root = enclosing[ 0 ];
    if ( !root || root.z <= zIndex.popover ) continue;

    found.push(
      `${ describeTag( control.tag, control.attributes ) }`
      + ` inside .${ root.classes.split( /\s+/ ).join( '/.' ) } (root z-index ${ root.z })`
    );
  }
  return found;
};

describe( 'a Popover inside an above-popover container uses layer="overlay"', () => {
  it( 'the containers this is defending against are the ones measured in the tree', () => {
    // Pinned so the scan cannot silently stop finding them - a renamed class or a moved
    // declaration shows up here rather than as a quietly empty result set below.
    for ( const [ cls, z ] of [
      [ 'pf-modal-overlay', 9999 ],
      [ 'link-modal-overlay', 9999 ],
      [ 'dm-modal-backdrop', 9999 ],
      [ 'shortcuts-overlay', 10000 ],
      [ 'popup-backdrop', 10000 ],
      [ 'toast-container', 10002 ],
    ] as const ) {
      const entry = CLASS_LAYERS.get( cls );
      expect( entry?.z, `${ cls } is no longer resolvable` ).toBe( z );
      expect( entry?.positioned, `${ cls } must be positioned for its z-index to apply` ).toBe( true );
      expect( z ).toBeGreaterThan( zIndex.popover );
    }

    // And the scan reads .tsx, not only .css: this one is styled-jsx.
    expect( CLASS_LAYERS.get( 'ui-modal-backdrop' )?.z ).toBe( zIndex.modal );

    // The pair that documents the nesting rule. `.modal` is the HIGHER number and the one
    // that needs nothing, because `.modal-overlay` wraps it and caps it at 1000.
    expect( CLASS_LAYERS.get( 'modal' )?.z ).toBe( zIndex.overlayPopover );
    expect( CLASS_LAYERS.get( 'modal-overlay' )?.z ).toBe( 1000 );
    expect( CLASS_LAYERS.get( 'modal-overlay' )?.positioned ).toBe( true );
  } );

  it( 'no file in src/ renders a layered control inside one without layer="overlay"', () => {
    const files = [ ...WALK( SRC, /\.tsx$/ ), ...WALK( SRC, /\.ts$/ ) ]
      .filter( f => !/[\\/]test[\\/]/.test( f ) );

    const report: string[] = [];
    for ( const file of files ) {
      for ( const offence of offenders( readFileSync( file, 'utf8' ) ) ) {
        report.push( `${ rel( file ) }: ${ offence }` );
      }
    }

    expect(
      report,
      'A Select / DateField / ColorField / TimeField / DateTimeField whose OUTERMOST '
      + 'positioned ancestor resolves above zIndex.popover (1500) must pass layer="overlay". '
      + 'A Popover portals to document.body, so at the default 1500 it competes with that '
      + 'ancestor in the ROOT stacking context and LOSES: the menu paints under the overlay, '
      + 'and a click aimed at an option hits the overlay instead - which in a modal usually '
      + 'means the modal closes and the edit is discarded. layer="overlay" is 10001 '
      + '(zIndex.overlayPopover in src/lib/design-tokens.ts), above every container measured '
      + 'and still below the 10002 toast band, as it should be.'
    ).toEqual( [] );
  } );

  it( 'ConfirmContext.tsx renders no Layer 2 control without layer="overlay"', () => {
    // KEPT AS ITS OWN CASE because the Confirm dialog's backdrop is an INLINE `zIndex: 10000`
    // on a non-positioned card, not a class, so the className-driven scan above cannot see
    // it. Vacuously true today - nothing puts a dropdown in a confirm dialog - and committed
    // anyway so the first person who does gets a failure instead of a menu that opens
    // underneath the dialog that owns it.
    const source = codeOnly( readFileSync( join( SRC, 'contexts', 'ConfirmContext.tsx' ), 'utf8' ) );
    const bare = layeredControls( source ).filter( c => !HAS_OVERLAY_LAYER.test( c.attributes ) );
    expect(
      bare.map( c => describeTag( c.tag, c.attributes ) ),
      "The Confirm dialog's backdrop is an inline zIndex: 10000 and its card is a "
      + 'non-positioned child, so a default Popover at 1500 opens UNDERNEATH the dialog it '
      + 'belongs to. Pass layer="overlay".'
    ).toEqual( [] );
  } );

  it( 'detects planted samples, so a silent pass cannot be mistaken for proof', () => {
    // The scanner is tested before it is trusted. Without this, a regex that matched nothing
    // would pass forever on an empty file and still get cited as evidence - which is exactly
    // what the one-file version of this gate did while two controls were broken.
    const table = new Map<string, ClassLayer>( [
      [ 'veil', { z: 9999, positioned: true } ],
      [ 'low', { z: 1000, positioned: true } ],
      [ 'inert', { z: 9999, positioned: false } ],
      [ 'box', { positioned: true } ],
    ] );
    const wrap = ( inner: string, cls = 'veil' ) =>
      `<div className="${ cls }"><div className="box">${ inner }</div></div>`;

    expect( offenders( wrap( '<Select value={v} onChange={set} ariaLabel="x" />' ), table ) ).toHaveLength( 1 );
    expect( offenders( wrap( '<DateField value={v} label="When" />' ), table ) ).toHaveLength( 1 );
    expect( offenders( wrap( '<ColorField value={v} label="Brand" />' ), table ) ).toHaveLength( 1 );
    // The two composed controls forward `layer`, so they are in scope too.
    expect( offenders( wrap( '<TimeField value={v} ariaLabel="t" />' ), table ) ).toHaveLength( 1 );
    expect( offenders( wrap( '<DateTimeField value={v} label="When" />' ), table ) ).toHaveLength( 1 );

    // All accepted spellings of the attribute pass.
    expect( offenders( wrap( '<Select layer="overlay" value={v} />' ), table ) ).toEqual( [] );
    expect( offenders( wrap( "<Select layer={ 'overlay' } value={v} />" ), table ) ).toEqual( [] );

    // A different layer is NOT an exemption.
    expect( offenders( wrap( '<Select layer="default" value={v} />' ), table ) ).toHaveLength( 1 );

    // A container at or below the popover layer demands nothing, and neither does a class
    // with no z-index, nor one whose z-index cannot apply because it is not positioned.
    expect( offenders( wrap( '<Select value={v} />', 'low' ), table ) ).toEqual( [] );
    expect( offenders( wrap( '<Select value={v} />', 'unknown-class' ), table ) ).toEqual( [] );
    expect( offenders( wrap( '<Select value={v} />', 'inert' ), table ) ).toEqual( [] );

    // A component whose name merely starts the same way is not one of ours.
    expect( offenders( wrap( '<SelectAll checked={all} />' ), table ) ).toEqual( [] );

    // And prose is not code.
    expect( offenders( wrap( '/* never render <Select> here */' ), table ) ).toEqual( [] );
    expect( offenders( wrap( '{/* <DateField /> is banned */}' ), table ) ).toEqual( [] );

    // An attribute after a `>` inside a handler is still seen - the regression that made the
    // scan report the one call site that had already been fixed.
    expect( offenders( wrap(
      '<Select ariaLabel="Brand"\n  onChange={ v => set( { p: v } ) }\n  layer="overlay" />'
    ), table ) ).toEqual( [] );
  } );

  it( 'resolves the OUTERMOST container, so a capped inner z-index demands nothing', () => {
    // This is the case that made the first run of the widened scan wrong, and it is the whole
    // reason the gate walks a chain. engage/whatsapp/templates.tsx renders seven Selects
    // inside `.modal`, which Layout.css gives `position: fixed; z-index: 10001` - but
    // `.modal` sits inside `.modal-overlay` at `position: fixed; z-index: 1000`, which
    // establishes a stacking context and confines the 10001 to it. The portal at 1500
    // competes with 1000 and WINS, so those seven are correct as written. Demanding
    // layer="overlay" there would push an ordinary dropdown above every overlay in the app.
    const table = new Map<string, ClassLayer>( [
      [ 'outer-low', { z: 1000, positioned: true } ],
      [ 'inner-high', { z: 10001, positioned: true } ],
      [ 'outer-high', { z: 9999, positioned: true } ],
    ] );

    expect( offenders(
      '<div className="outer-low"><div className="inner-high"><Select value={v} /></div></div>',
      table
    ) ).toEqual( [] );

    // Reverse the nesting and the outer number is the one that counts, so it IS required.
    expect( offenders(
      '<div className="outer-high"><div className="inner-high"><Select value={v} /></div></div>',
      table
    ) ).toHaveLength( 1 );
  } );

  it( 'requires the prop only INSIDE the container, which is why the scan tracks nesting', () => {
    // pay/flow renders .pf-modal-overlay three times and holds nine layered controls; eight
    // of them are outside all three.
    const table = new Map<string, ClassLayer>( [ [ 'veil', { z: 9999, positioned: true } ] ] );
    const source = [
      '<div className="page">',
      '  <Select ariaLabel="outside-before" value={a} />',
      '  <div className="veil">',
      '    <div className="box"><Select ariaLabel="inside" value={b} /></div>',
      '  </div>',
      '  <Select ariaLabel="outside-after" value={c} />',
      '</div>',
    ].join( '\n' );

    const found = offenders( source, table );
    expect( found ).toHaveLength( 1 );
    expect( found[ 0 ] ).toContain( 'inside' );
    expect( found[ 0 ] ).not.toContain( 'outside' );

    // Nested same-named tags must not close the region early: a control after an inner
    // </div> is still inside the overlay.
    const nested = [
      '<div className="veil">',
      '  <div className="box"><span>x</span></div>',
      '  <Select ariaLabel="still-inside" value={b} />',
      '</div>',
    ].join( '\n' );
    expect( offenders( nested, table ) ).toHaveLength( 1 );

    // A self-closing element encloses nothing, so it cannot create a region.
    expect( offenders( '<div className="veil" />\n<Select ariaLabel="after" value={b} />', table ) )
      .toEqual( [] );
  } );

  it( 'the overlay layer is the number the analysis picked, and is bracketed as documented', () => {
    // Pinned so the numbers that bracket it cannot drift apart silently: if ConfirmContext's
    // backdrop or the toast band moves, this pairing is where the mismatch shows up.
    const tokens = readFileSync( join( SRC, 'lib', 'design-tokens.ts' ), 'utf8' );
    expect( tokens ).toMatch( /overlayPopover:\s*10001/ );
    expect( zIndex.overlayPopover ).toBeGreaterThan( 10000 );
    expect( zIndex.overlayPopover ).toBeLessThan( 10002 );

    const confirm = readFileSync( join( SRC, 'contexts', 'ConfirmContext.tsx' ), 'utf8' );
    expect( confirm ).toMatch( /zIndex:\s*10000/ );
    expect( CLASS_LAYERS.get( 'toast-container' )?.z ).toBe( 10002 );
  } );

  it( 'the two call sites that need the prop still pass it', () => {
    // Named rather than counted, because these two are the regression. The whole-tree scan
    // above would also catch their removal, but it would report them as "some file" - and a
    // future edit to either modal is the likeliest way the prop goes missing again.
    const payFlow = codeOnly( readFileSync(
      join( SRC, 'pages', 'workspace', 'pay', 'flow', 'index.tsx' ), 'utf8' ) );
    expect( payFlow ).toMatch(
      /<Select[^>]*ariaLabel="Brand"[\s\S]{0,260}?value=\{ editForm\.purpose \}[\s\S]{0,260}?layer="overlay"/ );

    const link = codeOnly( readFileSync( join( SRC, 'pages', 'workspace', 'link', 'index.tsx' ), 'utf8' ) );
    expect( link ).toMatch( /<DateField[\s\S]{0,200}?label="Expiry Date \(optional\)"[\s\S]{0,200}?layer="overlay"/ );
  } );
} );
