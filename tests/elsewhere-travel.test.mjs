// Regression tests for the Elsewhere Travel Assistant mock-data fix.
//
// Bug (now fixed): the assistant used to fall back to fictional travel
// results and offer a Checkout link even though no search endpoint is
// configured in any Amplify app or branch. The fix removes the demo
// fallback, so searchTravel throws when no provider is configured, rejects
// failed/empty provider responses, and checkout stays gated to verified
// provider offers only.
//
// These tests exercise the real exported helpers (searchTravel,
// normaliseResponse, safeHttpsUrl, quoteIsFresh) via the offline esbuild+vm
// harness. Each case would fail if the fix were reverted.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadTsxModule, readSource } from './helpers/loadTsx.mjs';

const FILE = 'src/components/ElsewhereTravelAssistant.tsx';
const EXPORTS = [ 'searchTravel', 'normaliseResponse', 'safeHttpsUrl', 'quoteIsFresh' ];

function loadAssistant( globals = {} ) {
  return loadTsxModule( { file: FILE, exportNames: EXPORTS, globals } );
}

test( 'searchTravel rejects as unavailable when no endpoint and no window bridge', async () => {
  const { exports } = loadAssistant( { env: {} } );
  await assert.rejects(
    exports.searchTravel( 'flights', 'Delhi', [], {} ),
    /unavailable/,
  );
} );

test( 'searchTravel rejects with the HTTP status when the provider fetch is not ok', async () => {
  const { exports, sandbox } = loadAssistant( {
    env: { NEXT_PUBLIC_ELSEWHERE_SEARCH_ENDPOINT: 'https://provider.invalid/search' },
  } );
  sandbox.fetch = async () => ( { ok: false, status: 503 } );
  await assert.rejects(
    exports.searchTravel( 'flights', 'Delhi', [], {} ),
    /503/,
  );
} );

test( 'searchTravel rejects an empty provider payload with "No usable provider results"', async () => {
  const { exports, sandbox } = loadAssistant( {
    env: { NEXT_PUBLIC_ELSEWHERE_SEARCH_ENDPOINT: 'https://provider.invalid/search' },
  } );
  sandbox.fetch = async () => ( { ok: true, json: async () => ( { results: [] } ) } );
  await assert.rejects(
    exports.searchTravel( 'flights', 'Delhi', [], {} ),
    /No usable provider results/,
  );
} );

test( 'a real provider offer returns source "api" and checkoutReady defaults to false', async () => {
  const { exports, sandbox } = loadAssistant( {
    env: { NEXT_PUBLIC_ELSEWHERE_SEARCH_ENDPOINT: 'https://provider.invalid/search' },
  } );
  sandbox.fetch = async () => ( {
    ok: true,
    json: async () => ( { results: [ { id: 'offer-1', title: 'Provider offer', price: '₹100' } ] } ),
  } );
  const live = await exports.searchTravel( 'flights', 'Delhi', [], {} );
  assert.equal( live.source, 'api' );
  assert.equal( live.results[ 0 ].id, 'offer-1' );
  assert.equal(
    live.results[ 0 ].checkoutReady,
    false,
    'Missing provider readiness fields must not authorize checkout',
  );
} );

test( 'normaliseResponse throws on an empty results array', () => {
  const { exports } = loadAssistant();
  assert.throws( () => exports.normaliseResponse( { results: [] } ), /No usable provider results/ );
} );

test( 'normaliseResponse only marks checkoutReady true when the offer says so explicitly', () => {
  const { exports } = loadAssistant();
  const withoutFlag = exports.normaliseResponse( { results: [ { id: 'a', price: '₹1' } ] } );
  assert.equal( withoutFlag.results[ 0 ].checkoutReady, false );
  const withFlag = exports.normaliseResponse( {
    results: [ { id: 'a', price: '₹1', checkoutReady: true } ],
  } );
  assert.equal( withFlag.results[ 0 ].checkoutReady, true );
} );

test( 'safeHttpsUrl rejects javascript: URLs and non-https schemes', () => {
  const { exports } = loadAssistant();
  assert.equal( exports.safeHttpsUrl( 'javascript:alert(1)' ), '' );
  assert.equal( exports.safeHttpsUrl( 'http://insecure.example/path' ), '' );
  assert.equal( exports.safeHttpsUrl( 'https://verified.example/offer' ), 'https://verified.example/offer' );
} );

test( 'quoteIsFresh is false for a past date and true for a future date', () => {
  const { exports } = loadAssistant();
  assert.equal( exports.quoteIsFresh( '2000-01-01' ), false );
  assert.equal( exports.quoteIsFresh( undefined ), false );
  const future = new Date( Date.now() + 60 * 60 * 1000 ).toISOString();
  assert.equal( exports.quoteIsFresh( future ), true );
} );

test( 'source carries no demo/fictional fallback markers', () => {
  const source = readSource( FILE );
  assert.ok( !source.includes( 'eta-demo-checkout' ), 'demo checkout marker must not exist' );
  assert.ok( !/demoResults|FALLBACK_RESULTS|sampleResults/i.test( source ), 'no demo result fallback' );
} );
