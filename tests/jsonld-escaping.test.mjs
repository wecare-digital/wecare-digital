// JSON-LD serialisation (audit WEB-9).
//
// lib/schema.ts ld() is the one serialiser for every <script type="application/ld+json">.
// A value containing `</script>` must not be able to close the element, and the output must
// still parse to the same data. PageMeta.tsx, post/[slug].tsx and _app.tsx must use it.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import vm from 'node:vm';
import * as esbuild from 'esbuild';

import { readSource } from './helpers/loadTsx.mjs';

function loadLd() {
  const { outputFiles } = esbuild.buildSync( {
    entryPoints: [ path.resolve( new URL( '..', import.meta.url ).pathname, 'src/lib/schema.ts' ) ],
    bundle: true,
    write: false,
    format: 'cjs',
    platform: 'node',
    target: 'es2022',
  } );
  const compiled = { exports: {} };
  vm.runInNewContext( outputFiles[ 0 ].text, { module: compiled, exports: compiled.exports, require: () => ( {} ), process: { env: {} } } );
  return compiled.exports.ld;
}

test( 'ld() escapes <, U+2028 and U+2029 and round-trips the data', () => {
  const ld = loadLd();
  const value = { headline: 'a </script><script>alert(1)</script> <!-- b', note: 'line\u2028sep\u2029para' };
  const { __html } = ld( value );
  assert.ok( !__html.includes( '<' ), __html );
  assert.ok( !__html.includes( '\u2028' ) && !__html.includes( '\u2029' ) );
  const parsed = JSON.parse( __html );
  assert.equal( parsed.headline, value.headline );
  assert.equal( parsed.note, value.note );
} );

test( 'PageMeta, the post template and _app emit JSON-LD only through ld()', () => {
  for ( const file of [ 'src/components/PageMeta.tsx', 'src/pages/post/[slug].tsx', 'src/pages/_app.tsx' ] ) {
    const source = readSource( file );
    assert.ok( source.includes( 'ld(' ), `${ file } uses ld()` );
    assert.ok( !/__html:\s*JSON\.stringify/.test( source ), `${ file } has no raw JSON.stringify JSON-LD` );
  }
} );
