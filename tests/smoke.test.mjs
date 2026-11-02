// Smoke test: proves the offline TSX harness itself works before the
// behavioural bug-fix tests land. If this fails, `npm test` wiring or the
// esbuild + node:vm loader is broken, not the production code.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { compileTsx, loadTsxModule } from './helpers/loadTsx.mjs';

test( 'compileTsx transforms TypeScript syntax to runnable JS', () => {
  const code = compileTsx( 'export const double = ( n: number ): number => n * 2;' );
  assert.match( code, /double/ );
  assert.doesNotMatch( code, /: number/, 'type annotations should be stripped' );
} );

test( 'loadTsxModule compiles and runs a pure exported helper', () => {
  const { exports } = loadTsxModule( {
    source: 'export function add( a: number, b: number ): number { return a + b; }',
  } );
  assert.equal( typeof exports.add, 'function' );
  assert.equal( exports.add( 2, 3 ), 5 );
} );

test( 'loadTsxModule re-exports identifiers named in exportNames', () => {
  const { exports } = loadTsxModule( {
    source: 'const greet = ( name: string ): string => `hi ${ name }`;',
    exportNames: [ 'greet' ],
  } );
  assert.equal( exports.greet( 'wecare' ), 'hi wecare' );
} );

test( 'loadTsxModule injects env and a controllable fetch into the sandbox', async () => {
  const { exports, sandbox } = loadTsxModule( {
    source: [
      'export async function check(): Promise<{ flag: string; ok: boolean }> {',
      '  const res = await fetch( "https://example.invalid" );',
      '  return { flag: process.env.FEATURE_FLAG, ok: res.ok };',
      '}',
    ].join( '\n' ),
    globals: {
      env: { FEATURE_FLAG: 'on' },
      fetch: async () => ( { ok: true } ),
    },
  } );

  const first = await exports.check();
  assert.equal( first.flag, 'on' );
  assert.equal( first.ok, true );

  // The live sandbox lets a test swap fetch between assertions.
  sandbox.fetch = async () => ( { ok: false } );
  const second = await exports.check();
  assert.equal( second.ok, false );
} );

test( 'the default sandbox fetch rejects unexpected network access', async () => {
  const { exports } = loadTsxModule( {
    source: 'export const ping = () => fetch( "https://example.invalid" );',
  } );
  await assert.rejects( exports.ping(), /Unexpected network request/ );
} );
