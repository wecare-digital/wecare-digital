// Behavioural regression tests for the pure timestamp/address normalizers in
// src/api/core.ts (normalizeTimestamp, normalizeEpochSeconds,
// normalizeCheckoutAddress). These are pure functions with no external imports,
// so we extract each function body from the source text, compile it with
// esbuild and run it in a node:vm with NO injected dependencies. Inputs are
// fixed so there is no Date.now() nondeterminism; outputs are asserted exactly.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

import { compileTsx, readSource } from './helpers/loadTsx.mjs';

// FEAT-002: the three pure normalizers (normalizeTimestamp, normalizeEpochSeconds,
// normalizeCheckoutAddress) were relocated verbatim from src/api/client.ts into
// src/api/core.ts during the domain-module decomposition. Every assertion below is
// unchanged; only the source file this test slices from moved.
const CLIENT_FILE = 'src/api/core.ts';

// Brace-walk one `function <name> (...) { ... }` body out of the source.
function extractFn( source, name ) {
  const marker = `function ${ name } (`;
  const start = source.indexOf( marker );
  assert.ok( start !== -1, `${ name } must exist in client.ts` );
  const braceStart = source.indexOf( '{', start );
  let depth = 0;
  let end = -1;
  for ( let i = braceStart; i < source.length; i++ ) {
    const ch = source[ i ];
    if ( ch === '{' ) depth++;
    else if ( ch === '}' ) {
      depth--;
      if ( depth === 0 ) { end = i + 1; break; }
    }
  }
  assert.ok( end !== -1, `could not find the end of ${ name }` );
  return source.slice( start, end );
}

function loadNormalizers() {
  const source = readSource( CLIENT_FILE );
  const names = [ 'normalizeTimestamp', 'normalizeEpochSeconds', 'normalizeCheckoutAddress' ];
  const bodies = names.map( n => extractFn( source, n ) ).join( '\n\n' );
  const wrapped = `${ bodies }\nexport { ${ names.join( ', ' ) } };`;
  const code = compileTsx( wrapped );
  const compiledModule = { exports: {} };
  const sandbox = {
    module: compiledModule,
    exports: compiledModule.exports,
    Date,
    Number,
    isNaN,
    String,
    Array,
    Object,
  };
  vm.runInNewContext( code, sandbox );
  return compiledModule.exports;
}

// --- normalizeEpochSeconds -------------------------------------------------

test( 'normalizeEpochSeconds returns undefined for the Number()-coercion traps', () => {
  const { normalizeEpochSeconds } = loadNormalizers();
  assert.equal( normalizeEpochSeconds( null ), undefined );
  assert.equal( normalizeEpochSeconds( undefined ), undefined );
  assert.equal( normalizeEpochSeconds( '' ), undefined );
  // 0 and negatives would otherwise coerce to the 1970 epoch.
  assert.equal( normalizeEpochSeconds( 0 ), undefined );
  assert.equal( normalizeEpochSeconds( -5 ), undefined );
  assert.equal( normalizeEpochSeconds( 'junk' ), undefined );
} );

test( 'normalizeEpochSeconds returns the number for positive finite input', () => {
  const { normalizeEpochSeconds } = loadNormalizers();
  assert.equal( normalizeEpochSeconds( 1709568000 ), 1709568000 );
  assert.equal( normalizeEpochSeconds( '1709568000' ), 1709568000 );
} );

// --- normalizeTimestamp ----------------------------------------------------

test( 'normalizeTimestamp treats numbers < 1e12 as epoch SECONDS', () => {
  const { normalizeTimestamp } = loadNormalizers();
  // 1709568000 seconds = 2024-03-04T16:00:00.000Z
  assert.equal( normalizeTimestamp( 1709568000 ), '2024-03-04T16:00:00.000Z' );
  assert.equal( normalizeTimestamp( '1709568000' ), '2024-03-04T16:00:00.000Z' );
} );

test( 'normalizeTimestamp treats numbers >= 1e12 as epoch MILLIS', () => {
  const { normalizeTimestamp } = loadNormalizers();
  // 1709568000000 ms = 2024-03-04T16:00:00.000Z
  assert.equal( normalizeTimestamp( 1709568000000 ), '2024-03-04T16:00:00.000Z' );
} );

test( 'normalizeTimestamp parses ISO strings and rejects junk', () => {
  const { normalizeTimestamp } = loadNormalizers();
  assert.equal( normalizeTimestamp( '2024-03-04T16:00:00.000Z' ), '2024-03-04T16:00:00.000Z' );
  assert.equal( normalizeTimestamp( 'not-a-date' ), undefined );
  assert.equal( normalizeTimestamp( null ), undefined );
  assert.equal( normalizeTimestamp( undefined ), undefined );
  assert.equal( normalizeTimestamp( '' ), undefined );
} );

// --- normalizeCheckoutAddress ----------------------------------------------

test( 'normalizeCheckoutAddress rejects null, arrays and empty objects', () => {
  const { normalizeCheckoutAddress } = loadNormalizers();
  assert.equal( normalizeCheckoutAddress( null ), undefined );
  assert.equal( normalizeCheckoutAddress( undefined ), undefined );
  // An array must not pass as a dict of numeric keys.
  assert.equal( normalizeCheckoutAddress( [ 'a', 'b' ] ), undefined );
  assert.equal( normalizeCheckoutAddress( [] ), undefined );
  assert.equal( normalizeCheckoutAddress( {} ), undefined );
} );

test( 'normalizeCheckoutAddress passes a non-empty object through unchanged', () => {
  const { normalizeCheckoutAddress } = loadNormalizers();
  const addr = { line1: '1 Example Road', city: 'Testville', state: 'KA', pincode: '560001' };
  assert.deepEqual( normalizeCheckoutAddress( addr ), addr );
} );
