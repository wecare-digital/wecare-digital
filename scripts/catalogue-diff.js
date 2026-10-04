#!/usr/bin/env node
/**
 * Did the Wix catalogue actually CHANGE, or did the clock?
 *
 * Usage
 *   node scripts/catalogue-diff.js <before.json> <after.json>
 *
 * Exits 0 either way and reports on stdout. When `GITHUB_OUTPUT` is set it also writes
 * `changed`, `added`, `removed`, `modified` and `summary` as step outputs, so
 * `.github/workflows/catalogue-sync.yml` can branch on a fact rather than parse a log.
 *
 * WHY THIS EXISTS, AND IT IS NOT TIDINESS
 * ---------------------------------------
 * `scripts/fetch-wix-catalog.js` stamps `fetchedAt` and `variantVerifiedAt` with
 * `new Date().toISOString()` on EVERY run. So `git diff --quiet src/content/wix-catalog.json`
 * is true on every single run, including the overwhelmingly common one where Wix returned
 * byte-identical products. Measured 2026-10-04: two consecutive fetches minutes apart
 * produced a 2-line diff, both lines a timestamp.
 *
 * A scheduled sync wired to a raw `git diff` would therefore:
 *   - commit to `stack` four times a day with nothing in it,
 *   - and - the real cost - trigger a full Amplify production build each time, because
 *     branch `stack` has `enableAutoBuild: true`. A rebuild is not free and a history of
 *     empty commits is worse than no history.
 *
 * So the comparison ignores exactly those two fields and nothing else. It is a allowlist of
 * two names rather than "ignore anything that looks like a date": `fetchedAt` is also what
 * `catalogReadOn()` renders on the page, so if it were the ONLY change the page would be
 * reprinting the same catalogue with a newer date on it - which is not information.
 *
 * WHAT COUNTS AS A CHANGE IS DELIBERATELY EVERYTHING ELSE
 * ------------------------------------------------------
 * A price edit, a description edit, a slug rename, a variant appearing or disappearing, a
 * product hidden in Wix, `productCount` moving - all of it. The per-product comparison is a
 * deep compare of the whole row, not a chosen subset, because a subset is a guess about which
 * Wix fields matter and the site renders more of them than anyone will remember to list.
 *
 * NEITHER FILE IS WRITTEN. This script reads and reports; the workflow decides.
 */
import fs from 'node:fs';
import path from 'node:path';

/** The only fields whose change is NOT a change. Both are wall-clock stamps from the fetch. */
const TIMESTAMP_FIELDS = [ 'fetchedAt', 'variantVerifiedAt' ];

function die( msg ) {
  console.error( `catalogue-diff: ${msg}` );
  process.exit( 2 );
}

function read( file ) {
  let text;
  try {
    text = fs.readFileSync( file, 'utf-8' );
  } catch {
    die( `cannot read ${file}` );
  }
  try {
    return JSON.parse( text );
  } catch ( e ) {
    die( `${file} is not JSON: ${e && e.message ? e.message : e}` );
  }
}

/**
 * Deep structural equality over JSON values.
 *
 * Written out rather than `JSON.stringify(a) === JSON.stringify(b)` because stringify is
 * KEY-ORDER SENSITIVE: Wix is under no obligation to serialise a product's fields in the same
 * order twice, and an order flip would read as a catalogue change and trigger a build.
 */
function deepEqual( a, b ) {
  if ( a === b ) return true;
  if ( a === null || b === null ) return false;
  if ( typeof a !== typeof b ) return false;
  if ( Array.isArray( a ) !== Array.isArray( b ) ) return false;
  if ( Array.isArray( a ) ) {
    if ( a.length !== b.length ) return false;
    return a.every( ( item, i ) => deepEqual( item, b[ i ] ) );
  }
  if ( typeof a !== 'object' ) return false;
  const ka = Object.keys( a ).sort();
  const kb = Object.keys( b ).sort();
  if ( ka.length !== kb.length || !ka.every( ( k, i ) => k === kb[ i ] ) ) return false;
  return ka.every( k => deepEqual( a[ k ], b[ k ] ) );
}

/** The snapshot minus the two timestamps, products keyed by slug. */
function normalise( snapshot ) {
  const rest = {};
  for ( const [ key, value ] of Object.entries( snapshot || {} ) ) {
    if ( TIMESTAMP_FIELDS.includes( key ) ) continue;
    if ( key === 'products' ) continue;
    rest[ key ] = value;
  }
  const bySlug = new Map();
  for ( const product of ( ( snapshot || {} ).products || [] ) ) {
    // Keyed on slug because the slug is the ROUTE: two rows sharing one slug is itself a
    // change worth reporting, and `|| product.id` keeps a slugless row visible rather than
    // collapsing every one of them onto the empty string.
    bySlug.set( String( product.slug || product.id || '' ), product );
  }
  return { rest, bySlug };
}

/**
 * Compare two snapshots. Returns `{ changed, added, removed, modified, meta, summary }`.
 *
 * Exported so `src/test/CatalogueDiff.test.ts` drives this function rather than the process.
 */
export function compare( before, after ) {
  const a = normalise( before );
  const b = normalise( after );

  const added = [ ...b.bySlug.keys() ].filter( slug => !a.bySlug.has( slug ) ).sort();
  const removed = [ ...a.bySlug.keys() ].filter( slug => !b.bySlug.has( slug ) ).sort();
  const modified = [ ...b.bySlug.keys() ]
    .filter( slug => a.bySlug.has( slug ) )
    .filter( slug => !deepEqual( a.bySlug.get( slug ), b.bySlug.get( slug ) ) )
    .sort();

  // Top-level fields other than the two timestamps and the product array - `productCount`,
  // `source`, `catalogVersion`. A `source` change means the fetch scope moved (a visitor token
  // replaced by an admin key, say), which is worth a rebuild and worth a reader noticing.
  const meta = !deepEqual( a.rest, b.rest );

  const changed = added.length > 0 || removed.length > 0 || modified.length > 0 || meta;

  const parts = [];
  if ( added.length ) parts.push( `added ${added.join( ', ' )}` );
  if ( removed.length ) parts.push( `removed ${removed.join( ', ' )}` );
  if ( modified.length ) parts.push( `changed ${modified.join( ', ' )}` );
  if ( meta ) parts.push( 'catalogue metadata changed' );

  const summary = changed
    ? `Wix catalogue: ${parts.join( '; ' )}`
    : 'Wix catalogue: no change (only the fetch timestamps moved)';

  return { changed, added, removed, modified, meta, summary };
}

function main() {
  const [ beforeFile, afterFile ] = process.argv.slice( 2 );
  if ( !beforeFile || !afterFile ) {
    die( 'usage: node scripts/catalogue-diff.js <before.json> <after.json>' );
  }

  const result = compare( read( beforeFile ), read( afterFile ) );

  console.log( result.summary );
  for ( const slug of result.added ) console.log( `  + ${slug}` );
  for ( const slug of result.removed ) console.log( `  - ${slug}` );
  for ( const slug of result.modified ) console.log( `  ~ ${slug}` );

  const out = process.env.GITHUB_OUTPUT;
  if ( out ) {
    fs.appendFileSync( out, [
      `changed=${result.changed}`,
      `added=${result.added.join( ',' )}`,
      `removed=${result.removed.join( ',' )}`,
      `modified=${result.modified.join( ',' )}`,
      `summary=${result.summary}`,
      '',
    ].join( '\n' ) );
  }
}

// Only when run as a script, so the test can import `compare` without the argv check firing.
const invoked = process.argv[ 1 ] && path.resolve( process.argv[ 1 ] ) === path.resolve(
  new URL( import.meta.url ).pathname );
if ( invoked ) main();
