#!/usr/bin/env node
/**
 * LEGALCHECK — structural assertions on the two legal documents.
 *
 * Written because the contact-clause move renumbered three sections, and the only thing
 * standing between "reordered correctly" and "shipped a contract with two section 46s"
 * was reading the diff. Numbering in a contract is load-bearing: a duplicate or a gap is
 * not a cosmetic defect, and nothing in the existing suite looked at it.
 *
 * WHAT IT ASSERTS, per document:
 *   1. Top-level numbers run 1..N with no gap and no duplicate.
 *   2. Every `id` is unique, and every top-level id is `s<number>` — the renderer emits
 *      the id as the in-page anchor and the number as visible text, so a mismatch is a
 *      deep link that lands on the wrong clause while looking correct.
 *   3. Sub-sections (14.2 and friends) sort under their parent and their parent exists.
 *   4. Array order matches numeric order. This is the one that catches a reorder that
 *      renumbered the labels but left the blocks where they were.
 *   5. The contact clause is the LAST top-level section, in both documents, on owner
 *      instruction. privacy.ts already ended that way; terms.ts now does too.
 *   6. Every section has a non-empty heading, inShort and at least one paragraph.
 *
 * Reads the compiled content so it checks the real exported arrays rather than a regex over
 * the source. The TypeScript is compiled with esbuild, which the app already depends on; this
 * used `tsx`, which is not installed anywhere in the repo, so the check could not run at all.
 */
const path = require( 'node:path' );

const REPO = path.resolve( __dirname, '..', '..' );

const CONTACT_LAST = {
  terms: 'How to contact us',
  privacy: 'Who we are and how to reach us',
};

let failures = 0;
let checks = 0;

const ok = ( label ) => { checks++; console.log( `  ok    ${label}` ); };
const bad = ( label, detail ) => {
  checks++; failures++;
  console.log( `  FAIL  ${label}` );
  if ( detail ) console.log( `        ${detail}` );
};

function checkDoc( name, sections ) {
  console.log( `\n${name}.ts — ${sections.length} sections` );

  const top = sections.filter( s => !s.number.includes( '.' ) );
  const nums = top.map( s => Number( s.number ) );

  // 1. contiguous 1..N
  const expected = Array.from( { length: top.length }, ( _, i ) => i + 1 );
  const sorted = [ ...nums ].sort( ( a, b ) => a - b );
  if ( JSON.stringify( sorted ) === JSON.stringify( expected ) ) {
    ok( `top-level numbers run 1..${top.length} with no gap or duplicate` );
  } else {
    const dupes = sorted.filter( ( n, i ) => sorted[ i - 1 ] === n );
    const gaps = expected.filter( n => !sorted.includes( n ) );
    bad( 'top-level numbers are not a contiguous 1..N',
      `duplicates: [${dupes}] · missing: [${gaps}] · got: [${sorted}]` );
  }

  // 2. unique ids, and top-level id === s<number>
  const ids = sections.map( s => s.id );
  const dupeIds = ids.filter( ( id, i ) => ids.indexOf( id ) !== i );
  if ( dupeIds.length === 0 ) ok( `all ${ids.length} ids unique` );
  else bad( 'duplicate ids', [ ...new Set( dupeIds ) ].join( ', ' ) );

  const mismatched = top.filter( s => s.id !== `s${s.number}` );
  if ( mismatched.length === 0 ) ok( 'every top-level id matches s<number>' );
  else bad( 'id does not match its number — deep links land on the wrong clause',
    mismatched.map( s => `${s.number} has id ${s.id}, expected s${s.number}` ).join( ' · ' ) );

  // 3. sub-sections have a parent
  const subs = sections.filter( s => s.number.includes( '.' ) );
  const orphans = subs.filter( s => !top.some( t => t.number === s.number.split( '.' )[ 0 ] ) );
  if ( orphans.length === 0 ) ok( `${subs.length} sub-sections all have a parent` );
  else bad( 'sub-sections with no parent', orphans.map( s => s.number ).join( ', ' ) );

  // 4. array order === numeric order
  const outOfOrder = [];
  for ( let i = 1; i < nums.length; i++ ) {
    if ( nums[ i ] < nums[ i - 1 ] ) outOfOrder.push( `${nums[ i - 1 ]} then ${nums[ i ]}` );
  }
  if ( outOfOrder.length === 0 ) ok( 'array order matches numeric order' );
  else bad( 'sections are out of order in the array — the page renders them like this',
    outOfOrder.join( ' · ' ) );

  // 5. contact clause last
  const want = CONTACT_LAST[ name ];
  const last = top[ top.length - 1 ];
  if ( last.heading === want ) {
    ok( `ends on ${last.number} "${want}"` );
  } else {
    bad( `contact clause is not last — expected "${want}"`,
      `ends on ${last.number} "${last.heading}"` );
  }

  // 6. content present. `inShort` is a TOP-LEVEL-ONLY field by design - the rewrite added
  //    summaries per section, not per sub-clause - so requiring it on 14.2 and friends
  //    fails 27 perfectly good sub-sections. Asserted where it is actually promised.
  const noText = sections.filter( s => !s.heading?.trim() || !( s.paragraphs?.length > 0 ) );
  if ( noText.length === 0 ) ok( `all ${sections.length} sections have a heading and a paragraph` );
  else bad( 'sections missing heading/paragraphs', noText.map( s => s.number ).join( ', ' ) );

  const noSummary = top.filter( s => !s.inShort?.trim() );
  if ( noSummary.length === 0 ) ok( `all ${top.length} top-level sections have an inShort` );
  else bad( 'top-level sections missing inShort', noSummary.map( s => s.number ).join( ', ' ) );
}

/**
 * Load a TypeScript module and its imports as CommonJS. esbuild bundles it in memory (nothing is
 * written) and the result is compiled as a module rooted at the source file, so relative paths
 * and stack traces still point at src/.
 */
function loadTs ( relative ) {
  const esbuild = require( 'esbuild' );
  const Module = require( 'node:module' );
  const file = path.join( REPO, relative );
  const built = esbuild.buildSync( {
    entryPoints: [ file ], bundle: true, platform: 'node', format: 'cjs', write: false, logLevel: 'silent',
  } );
  const mod = new Module( file, module );
  mod.filename = file;
  mod.paths = Module._nodeModulePaths( path.dirname( file ) );
  mod._compile( built.outputFiles[ 0 ].text, file );
  return mod.exports;
}

( async () => {
  const terms = loadTs( 'src/content/legal/terms.ts' );
  const privacy = loadTs( 'src/content/legal/privacy.ts' );

  console.log( 'LEGALCHECK — legal document structure' );
  checkDoc( 'terms', terms.TERMS_SECTIONS );
  checkDoc( 'privacy', privacy.PRIVACY_SECTIONS );

  console.log( `\n${checks - failures}/${checks} passed` );
  if ( failures ) {
    console.log( `${failures} FAILED` );
    process.exit( 1 );
  }
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
