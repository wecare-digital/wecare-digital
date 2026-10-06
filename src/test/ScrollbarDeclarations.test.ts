import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * THE SET OF FILES THAT DECLARE A SCROLLBAR THUMB COLOUR IS EXACTLY TWO. Invariant 3.
 *
 * WHY A GREP AND NOT A BROWSER. tools/browser/designsweep.js owns "which declaration wins",
 * and it is the better instrument wherever it can reach. It cannot reach any of the four
 * declarations this test exists for: its probe reads pseudo-elements of
 * document.documentElement only, `.sidebar-nav` is behind auth and never renders in the static
 * export at all, and `.nav-products-scroll` and `.wc-rows` need a menu opened first. A grep is
 * the only instrument that reaches them.
 *
 * WHAT WENT WRONG, so the shape of this test makes sense. The scrollbar was consolidated into
 * one declaration once already - and then six grew back, one file at a time, each one
 * reasonable on its own:
 *
 *   src/styles/Layout.css:714       lime thumb on the workspace sidebar        Gecko only
 *   src/styles/Layout.css:722-733   the same thing for Blink, with !important  Blink only
 *   src/components/Header.tsx:775   lime thumb on the public header nav        Gecko only
 *   src/components/Header.tsx:777-780  the same thing for Blink                Blink only
 *   src/components/SupportWidget.tsx:810  a 1.16:1 grey, on every public page  Gecko only
 *   src/styles/Pages.css:2544       the same 1.16:1 grey on the composer       Gecko only
 *
 * The two engines read DIFFERENT PROPERTIES for the same thing - `scrollbar-color` in Gecko,
 * `::-webkit-scrollbar-thumb` in Blink - so each of those is invisible in the engine the
 * author was not testing. That does not look like a CSS conflict; it looks like a browser bug.
 * A token change does not fix any of them, which is why they were deleted rather than retuned.
 *
 * WHAT IS NOT IN SCOPE. The nine `::-webkit-scrollbar { display: none }` and `{ height: 6px }`
 * rules on tab strips and carousels are untouched and must stay passing: they hide or resize a
 * scrollbar and set no colour, so none of them competes. The test therefore keys on a thumb
 * COLOUR, not on the presence of a `::-webkit-scrollbar` selector.
 */

const SRC = path.join( __dirname, '..' );

const WALK = ( dir: string, out: string[] = [] ): string[] => {
  for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) ) {
    const full = path.join( dir, entry.name );
    if ( entry.isDirectory() ) WALK( full, out );
    else if ( /\.(css|tsx)$/.test( entry.name ) ) out.push( full );
  }
  return out;
};

/**
 * Mask quoted strings that cannot hold the declaration being searched for.
 *
 * THIS RUNS BEFORE COMMENT-STRIPPING AND IT IS NOT TIDINESS. Four files in this repo carry a
 * file-input `accept="image/*,video/*"`, and the slash-star inside it opens a false comment
 * that a naive strip then closes at the next real terminator - in one measured case swallowing
 * 237 lines. A
 * declaration inside the swallowed range disappears and this test passes while a stray
 * scrollbar is live, which is a fail-OPEN.
 *
 * The mask is deliberately conditional: a quoted string containing `scrollbar` is left intact,
 * so masking can never be the reason a declaration goes unseen. Backticks are not masked -
 * styled-jsx CSS lives in them, and so do the two allowed declarations.
 */
const maskHazardousStrings = ( src: string ): string => src.replace(
  /'[^'\n]*'|"[^"\n]*"/g,
  m => ( /scrollbar/i.test( m ) ? m : ' '.repeat( m.length ) ) );

/**
 * COMMENT-STRIPPING IS LOAD-BEARING AND MUST COME FIRST. Five files explain this defect in
 * prose that necessarily contains the exact declarations being searched for -
 * inner-ux.css:2944-2975, Layout.css:74, Layout.css:101, Header.tsx and tokens.css's SCROLLBAR
 * block - so an unstripped scan reports every one of them as a live declaration and the test
 * can only be made to pass by allow-listing the comments.
 *
 * Line comments are stripped ANCHORED TO THE LINE START only, so a `https://` inside a URL or
 * a trailing `// see above` cannot eat the rest of a line that holds real code.
 */
const stripComments = ( src: string ): string => maskHazardousStrings( src )
  .replace( /\/\*[\s\S]*?\*\//g, ' ' )
  .replace( /^[ \t]*\/\/.*$/gm, ' ' );

/** True when the text declares a scrollbar thumb colour in either engine's property. */
const declaresThumbColour = ( raw: string ): boolean => {
  const src = stripComments( raw );
  // Gecko's half. `scrollbar-color` always names the thumb first, so any occurrence counts.
  if ( /scrollbar-color\s*:/.test( src ) ) return true;
  // Blink's half, and only when the block actually paints: a `::-webkit-scrollbar-thumb` rule
  // setting nothing but a border-radius is not a competing colour.
  for ( const m of src.matchAll( /::-webkit-scrollbar-thumb[^{}]*\{([^}]*)\}/g ) ) {
    if ( /(^|[\s;])background(-color)?\s*:/.test( m[ 1 ] ) ) return true;
  }
  return false;
};

/**
 * The two files allowed to declare it.
 *
 * inner-ux.css is the canonical declaration and reads the --scrollbar-* tokens exclusively.
 * WorkflowTerminal.tsx is the one exception, and it is a real one rather than an unfixed
 * leftover: `.wt-space` is a white-on-dark terminal panel where the site palette is
 * unreadable, so it declares its own white-on-translucent pair.
 */
const ALLOWED = [
  'src/styles/inner-ux.css',
  'src/components/WorkflowTerminal.tsx',
];

describe( 'scrollbar thumb colour is declared in exactly two files', () => {
  const files = WALK( SRC );

  it( 'scanned a plausible number of files', () => {
    // Anti-vacuous guard on the walk itself, separate from the planted sample below: an empty
    // or near-empty file list satisfies the set assertion for the wrong reason.
    expect( files.length ).toBeGreaterThan( 200 );
  } );

  it( 'is exactly inner-ux.css and WorkflowTerminal.tsx', () => {
    const found = files
      .filter( f => declaresThumbColour( fs.readFileSync( f, 'utf8' ) ) )
      .map( f => path.relative( path.join( SRC, '..' ), f ).split( path.sep ).join( '/' ) )
      .sort();

    expect(
      found,
      'a scrollbar thumb colour outside these two files is invisible in the engine you are not '
      + 'testing, because Gecko reads scrollbar-color and Blink reads ::-webkit-scrollbar-thumb. '
      + 'The site shipped six such declarations once. Put the colour in the --scrollbar-* tokens '
      + 'in src/styles/tokens.css and let the canonical block in src/styles/inner-ux.css apply '
      + 'it; keep any `scrollbar-width: thin` line, which is a width and not a colour.',
    ).toEqual( [ ...ALLOWED ].sort() );
  } );

  it( 'keeps every scrollbar-width: thin line that the nested scrollers need', () => {
    // The deletions removed colours, NOT widths, and the distinction is load-bearing: Gecko
    // does not inherit scrollbar-width and the canonical block declares it on `html` only, so
    // dropping it from a nested scroller hands Firefox the system-default gutter inside it.
    const needsThin = [
      'src/styles/Layout.css', 'src/styles/Pages.css',
      'src/components/Header.tsx', 'src/components/SupportWidget.tsx',
    ];
    for ( const rel of needsThin ) {
      const src = stripComments( fs.readFileSync( path.join( SRC, '..', rel ), 'utf8' ) );
      expect( /scrollbar-width\s*:\s*thin/.test( src ), `${rel} lost scrollbar-width: thin` )
        .toBe( true );
    }
  } );

  it( 'leaves the nine display:none and height:6px hiders alone', () => {
    // They set no colour, so they do not compete, and deleting one would bring back a visible
    // scrollbar on a tab strip or a carousel. Counted so a silent cull is caught here.
    const hiders = files.flatMap( f => {
      const src = stripComments( fs.readFileSync( f, 'utf8' ) );
      return Array.from( src.matchAll( /::-webkit-scrollbar(?!-)[^{}]*\{([^}]*)\}/g ) )
        .filter( m => /display\s*:\s*none|height\s*:\s*6px/.test( m[ 1 ] ) );
    } );
    expect( hiders.length ).toBe( 9 );
  } );

  it( 'finds a planted declaration, and loses a commented one', () => {
    // PLANTED SAMPLE. The assertion above is "the scan found exactly these two", which a regex
    // that matched NOTHING would also satisfy for every file but the two - and would then be
    // cited as evidence that no stray declaration exists. So the detector is exercised on text
    // whose answer is known, including the two ways it could fail open.
    expect( declaresThumbColour( '.a{scrollbar-color:#d1f470 transparent}' ) ).toBe( true );
    expect( declaresThumbColour( '.a::-webkit-scrollbar-thumb{background:#d1f470}' ) ).toBe( true );
    expect( declaresThumbColour(
      '.a::-webkit-scrollbar-thumb:hover{ background-color: #c5e866 }' ) ).toBe( true );

    // Comments must not read as declarations - the reason this file's own prose is safe.
    expect( declaresThumbColour( '/* scrollbar-color: #d1f470 transparent */' ) ).toBe( false );
    expect( declaresThumbColour(
      '/* .a::-webkit-scrollbar-thumb{background:#d1f470} was deleted */' ) ).toBe( false );
    expect( declaresThumbColour( '  // scrollbar-color: #d1f470 transparent' ) ).toBe( false );

    // A MIME wildcard must not open a comment that swallows a live declaration after it.
    expect( declaresThumbColour(
      '<input accept="image/*,video/*" />\n.a{scrollbar-color:#d1f470 transparent}' ) ).toBe( true );
    // ...and masking must not be able to hide one that is itself inside a quoted string.
    expect( declaresThumbColour(
      'head.innerHTML = ".a{scrollbar-color:#d1f470 transparent}"' ) ).toBe( true );

    // A width, a hider and a radius-only thumb rule are all legal and must not be reported.
    expect( declaresThumbColour( '.a{scrollbar-width:thin}' ) ).toBe( false );
    expect( declaresThumbColour( '.a::-webkit-scrollbar{display:none}' ) ).toBe( false );
    expect( declaresThumbColour( '.a::-webkit-scrollbar{height:6px}' ) ).toBe( false );
    expect( declaresThumbColour( '.a::-webkit-scrollbar-thumb{border-radius:999px}' ) )
      .toBe( false );
  } );
} );
