'use strict';

/**
 * htmlcheck - MARKUP flaws on the public pages, as distinct from design flaws.
 *
 * WHY THIS IS A SEPARATE AXIS, and why the other harnesses could not have caught any of it.
 * Everything measured so far has been geometry, colour and timing - box sizes, composited
 * contrast ratios, loop periods. All of that can be perfect on a page whose markup is
 * invalid, and all of it can be wrong on a page whose markup is immaculate. The two are
 * independent, so they get separate scripts:
 *
 *   sectioncheck / hometree / flowprobe   does it LOOK and BEHAVE right   (design)
 *   htmlcheck                             is it WRITTEN right             (markup)
 *
 * WHAT IT CHECKS, all read from the built HTML in out/ with no browser:
 *   1. heading order      an h1 -> h3 skip, or more than one h1
 *   2. landmarks          main / header / footer count, nesting
 *   3. duplicate id       the most common real defect, and invalid per spec
 *   4. aria references    aria-labelledby / describedby / controls pointing at no such id
 *   5. img alt            missing entirely, as opposed to deliberately empty
 *   6. list content       ul/ol whose children are not li
 *   7. nesting            interactive inside interactive, block inside p, div inside span-only
 *   8. lang               a document with no lang, or an empty one
 *   9. tabindex           positive values, which break natural order
 *  10. label association  inputs with neither a label nor an accessible name
 *
 * SCOPE: the 18 authored public routes. Blog posts share one template, so one stands in for
 * 746 - checking all of them would report the same finding 746 times.
 *
 * Run: node tools/audit/htmlcheck.js          (needs out/ - npm run build)
 *      node tools/audit/htmlcheck.js --route /
 */

const fs = require( 'fs' );
const path = require( 'path' );

const OUT = path.join( __dirname, '..', '..', 'out' );
if ( !fs.existsSync( OUT ) ) { console.error( 'out/ not found - run npm run build' ); process.exit( 2 ); }

const ROUTES = [
  '/', '/grahak-os/', '/vayulok/', '/contact/', '/terms/', '/privacy/',
  '/orders/', '/bharat-rx/', '/elsewhere/', '/expo-week/', '/dastavez/',
  '/clear-closure/', '/ritual-guru/', '/anew/', '/niji-setu/', '/blog/', '/get/',
  // The five Customer service pages, added when the header's six labels stopped all resolving
  // to /contact/. Same shape as the product pages: rotating hero plus one content section.
  '/submit-request/', '/request-amendment/', '/drop-docs/', '/leave-review/', '/refer-and-earn/',
  '/subscribe/',
  // '/store/' is gone: it was a staff page on a public URL and now lives at
  // /workspace/commerce/catalog. It was the only route failing H1-NONE and NO-MAIN here,
  // because the Authenticator renders instead of the page when there is no session.
];

const only = ( () => { const i = process.argv.indexOf( '--route' ); return i > -1 ? process.argv[ i + 1 ] : null; } )();
const list = only ? [ only ] : ROUTES;

const read = route => {
  const f = route === '/' ? path.join( OUT, 'index.html' )
    : path.join( OUT, route.replace( /^\/|\/$/g, '' ), 'index.html' );
  return fs.existsSync( f ) ? fs.readFileSync( f, 'utf8' ) : null;
};

/**
 * Strip <script>, <style> and comments before any structural check.
 * Not cosmetic: the Next.js bundle embeds serialised HTML inside __NEXT_DATA__ and inline
 * boot scripts, so an unstripped document double-counts every id and heading it mentions.
 * The first run of this reported 40 duplicate ids on the home page, every one of them a
 * string inside a script tag.
 */
// The close-tag patterns tolerate whitespace and trailing junk, because a browser
// accepts `</script >`, `</script\n>` and `</script bar>` as close tags and the earlier
// `<\/script>` did not. That is not pedantry here: the whole point of stripping is
// accuracy, and a missed close tag leaves a script body in the document, which is
// exactly the double-counting this function exists to prevent. CodeQL reported it as
// `js/bad-tag-filter` plus three `js/incomplete-multi-character-sanitization`.
//
// It also loops to a fixed point, because one pass is not one: a nested or malformed
// construct can reveal a new `<script` only after the first substitution.
//
// EACH REMOVAL SUBSTITUTES A NEWLINE, NOT THE EMPTY STRING, AND THAT IS THE WHOLE FIX
// for the three remaining `js/incomplete-multi-character-sanitization` alerts. Deleting a
// match splices the two sides together, so the characters either side can form a new
// construct that was never in the source: `<scr<script>x</script>ipt>` collapses to
// `<script>`, and `<sty<!--c-->le>` to `<style>`. The fixed-point loop above catches that
// on a later pass, but only if the loop is reached — and it is a correctness risk either
// way, because this function exists so that script bodies are not counted as document
// text. A `\n` cannot appear inside a tag name, so with it in place no removal can ever
// assemble a tag, one pass or eight. It is whitespace to every check below, all of which
// count tags or read `id="..."`, so nothing downstream can tell the difference.
// (CodeQL's query only considers substitutions whose replacement is the empty string, so
// this also happens to be what takes the alerts out of scope — but the reassembly is real
// and would be worth fixing with no alert attached to it.)
const strip = h => {
  let out = h;
  for ( let i = 0; i < 8; i += 1 ) {
    const next = out
      .replace( /<\s*script\b[^>]*>[\s\S]*?<\s*\/\s*script\b[^>]*>/gi, '\n' )
      .replace( /<\s*style\b[^>]*>[\s\S]*?<\s*\/\s*style\b[^>]*>/gi, '\n' )
      .replace( /<!--[\s\S]*?-->/g, '\n' );
    if ( next === out ) break;
    out = next;
  }
  // An opened-but-never-closed script or style: drop the remainder rather than letting
  // its body be counted as document text.
  return out.replace( /<\s*(script|style)\b[\s\S]*$/i, '' );
};

const findings = [];
const add = ( route, sev, code, msg ) => findings.push( { route, sev, code, msg } );

for ( const route of list ) {
  const raw = read( route );
  if ( !raw ) { add( route, 'HIGH', 'MISSING', 'no built document' ); continue; }
  const h = strip( raw );

  // ---- 1. headings -----------------------------------------------------------
  // Inner tags become a space rather than nothing, for the same reassembly reason as
  // `strip` above: deleting `<b>` from `<scr<b>x</b>ipt>` yields `<script>`. A space also
  // happens to be the better text extraction — `<span>A</span><span>B</span>` reads as
  // "A B" instead of "AB" — and the collapse-and-trim that follows removes the rest.
  const heads = [ ...h.matchAll( /<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1>/gi ) ]
    .map( m => ( { lvl: +m[ 1 ], text: m[ 2 ].replace( /<[^>]+>/g, ' ' ).replace( /\s+/g, ' ' ).trim() } ) );
  const h1s = heads.filter( x => x.lvl === 1 );
  if ( h1s.length === 0 ) add( route, 'HIGH', 'H1-NONE', 'no h1 on the page' );
  if ( h1s.length > 1 ) add( route, 'MED', 'H1-MANY', `${h1s.length} h1 elements: ${h1s.map( x => `"${x.text.slice( 0, 30 )}"` ).join( ', ' )}` );
  for ( let i = 1; i < heads.length; i++ ) {
    const jump = heads[ i ].lvl - heads[ i - 1 ].lvl;
    if ( jump > 1 ) {
      add( route, 'MED', 'H-SKIP',
        `h${heads[ i - 1 ].lvl} -> h${heads[ i ].lvl} skips a level at "${heads[ i ].text.slice( 0, 40 )}"` );
      break; // one report per page; a skipped level usually repeats
    }
  }

  // ---- 2. landmarks ----------------------------------------------------------
  const count = tag => ( h.match( new RegExp( `<${tag}\\b`, 'gi' ) ) || [] ).length;
  const mains = count( 'main' );
  if ( mains === 0 ) add( route, 'HIGH', 'NO-MAIN', 'no <main> landmark' );
  if ( mains > 1 ) add( route, 'HIGH', 'MANY-MAIN', `${mains} <main> elements` );
  if ( count( 'header' ) === 0 ) add( route, 'LOW', 'NO-HEADER', 'no <header>' );
  if ( count( 'footer' ) === 0 ) add( route, 'LOW', 'NO-FOOTER', 'no <footer>' );

  // ---- 3. duplicate ids ------------------------------------------------------
  const ids = [ ...h.matchAll( /\sid="([^"]+)"/g ) ].map( m => m[ 1 ] );
  const seen = new Map();
  for ( const id of ids ) seen.set( id, ( seen.get( id ) || 0 ) + 1 );
  const dupes = [ ...seen ].filter( ( [ , n ] ) => n > 1 );
  for ( const [ id, n ] of dupes ) add( route, 'MED', 'DUP-ID', `id="${id}" appears ${n} times` );

  // ---- 4. dangling aria references -------------------------------------------
  const idSet = new Set( ids );
  for ( const attr of [ 'aria-labelledby', 'aria-describedby', 'aria-controls', 'aria-owns' ] ) {
    for ( const m of h.matchAll( new RegExp( `${attr}="([^"]+)"`, 'g' ) ) ) {
      for ( const ref of m[ 1 ].trim().split( /\s+/ ) ) {
        if ( !idSet.has( ref ) ) add( route, 'MED', 'ARIA-DANGLING', `${attr}="${ref}" — no element has that id` );
      }
    }
  }

  // ---- 5. images -------------------------------------------------------------
  for ( const m of h.matchAll( /<img\b([^>]*)>/gi ) ) {
    if ( !/\salt=/.test( m[ 1 ] ) ) {
      const src = ( /src="([^"]*)"/.exec( m[ 1 ] ) || [ , '(no src)' ] )[ 1 ];
      add( route, 'MED', 'IMG-NO-ALT', `<img> with no alt attribute: ${src.slice( 0, 60 )}` );
    }
  }

  // ---- 6. list contents ------------------------------------------------------
  //
  // DIRECT CHILDREN ONLY, AND GETTING THAT WRONG IS WHY THIS COMMENT EXISTS.
  // The first version stripped nested lists and then flagged the first tag that was not an
  // <li>. That flags DESCENDANTS: <li><strong>Pick up where you left off.</strong> is
  // perfectly valid markup, and it reported the home page plus nine product pages - eleven
  // findings, every one false. <span> and <strong> inside an <li> are exactly what those
  // pages should contain.
  // The fix is to remove whole <li>...</li> blocks first. Whatever is still inside the list
  // after that really is a direct child, because the only thing that can legally be there is
  // an li (or a script/template, which strip() has already removed).
  for ( const m of h.matchAll( /<(ul|ol)\b[^>]*>([\s\S]*?)<\/\1>/gi ) ) {
    const flat = m[ 2 ]
      .replace( /<(ul|ol)\b[\s\S]*?<\/\1>/gi, '' )   // nested lists belong to themselves
      .replace( /<li\b[\s\S]*?<\/li>/gi, '' )        // and so does everything inside an li
      .replace( /<li\b[^>]*\/?>/gi, '' );            // unclosed li, which is legal HTML
    const badChild = /<([a-z][a-z0-9]*)\b/i.exec( flat );
    if ( badChild ) add( route, 'LOW', 'LIST-CHILD', `<${m[ 1 ]}> has a non-li child <${badChild[ 1 ]}>` );
  }

  // ---- 7. nesting ------------------------------------------------------------
  if ( /<a\b[^>]*>(?:(?!<\/a>)[\s\S])*?<(a|button)\b/i.test( h ) ) {
    add( route, 'HIGH', 'NEST-INTERACTIVE', 'an <a> contains another interactive element' );
  }
  for ( const m of h.matchAll( /<p\b[^>]*>([\s\S]*?)<\/p>/gi ) ) {
    const bad = /<(div|ul|ol|section|h[1-6]|p)\b/i.exec( m[ 1 ] );
    if ( bad ) { add( route, 'MED', 'NEST-P', `<p> contains a block element <${bad[ 1 ]}> — the browser will close the p early` ); break; }
  }

  // ---- 8. lang ---------------------------------------------------------------
  const lang = /<html[^>]*\slang="([^"]*)"/.exec( h );
  if ( !lang ) add( route, 'MED', 'NO-LANG', '<html> has no lang attribute' );
  else if ( !lang[ 1 ].trim() ) add( route, 'MED', 'EMPTY-LANG', '<html lang=""> is empty' );

  // ---- 9. tabindex -----------------------------------------------------------
  for ( const m of h.matchAll( /tabindex="(\d+)"/g ) ) {
    if ( +m[ 1 ] > 0 ) add( route, 'MED', 'TABINDEX-POS', `tabindex="${m[ 1 ]}" overrides natural focus order` );
  }

  // ---- 10. form labels -------------------------------------------------------
  for ( const m of h.matchAll( /<input\b([^>]*)>/gi ) ) {
    const a = m[ 1 ];
    if ( /type="(hidden|submit|button|image|reset)"/i.test( a ) ) continue;
    const id = ( /\sid="([^"]+)"/.exec( a ) || [] )[ 1 ];
    const named = /aria-label(?:ledby)?=/.test( a )
      || /\stitle=/.test( a )
      || ( id && new RegExp( `<label[^>]*\\sfor="${id}"` ).test( h ) );
    if ( !named ) add( route, 'MED', 'INPUT-NO-NAME', `<input> with no label, aria-label or title${id ? ` (id="${id}")` : ''}` );
  }
}

// ---- report ------------------------------------------------------------------
const order = { HIGH: 0, MED: 1, LOW: 2 };
findings.sort( ( a, b ) => order[ a.sev ] - order[ b.sev ] || a.route.localeCompare( b.route ) );

const byRoute = {};
for ( const f of findings ) ( byRoute[ f.route ] ||= [] ).push( f );

console.log( `\nMARKUP CHECK — ${list.length} route(s), ${findings.length} finding(s)\n` );

if ( !findings.length ) console.log( '  no markup findings' );
for ( const route of list ) {
  const fs_ = byRoute[ route ];
  if ( !fs_ ) { console.log( `  ok    ${route}` ); continue; }
  console.log( `  ${route}` );
  for ( const f of fs_ ) console.log( `        [${f.sev.padEnd( 4 )}] ${f.code.padEnd( 17 )} ${f.msg}` );
}

const counts = findings.reduce( ( a, f ) => ( a[ f.sev ] = ( a[ f.sev ] || 0 ) + 1, a ), {} );
console.log( `\nHIGH ${counts.HIGH || 0}  MED ${counts.MED || 0}  LOW ${counts.LOW || 0}` );
console.log( 'This checks MARKUP only. Geometry, contrast and timing are the design harnesses' );
console.log( 'in tools/browser/ — the two axes are independent.' );
