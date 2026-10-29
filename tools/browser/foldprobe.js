#!/usr/bin/env node
/**
 * Historical name retained for compatibility with local commands.
 *
 * /get/ no longer owns a customer form or download UI. The only exact-file customer route is
 * /vault/?file=<fileId>. This check now pins the static-export contract for the legacy /get/
 * signpost: it must immediately redirect to /vault/ and must not become indexable.
 */
'use strict';

const fs = require( 'node:fs' );
const path = require( 'node:path' );

const FILE = path.resolve( __dirname, '../../out/get/index.html' );

if ( !fs.existsSync( FILE ) )
{
  console.error( 'No out/get/index.html — run `npm run build` first.' );
  process.exit( 2 );
}

const html = fs.readFileSync( FILE, 'utf8' );
const checks = [
  [ /http-equiv=["']refresh["'][^>]*content=["']0; url=\/vault\//i, 'meta refresh -> /vault/' ],
  [ /rel=["']canonical["'][^>]*href=["']https:\/\/wecare\.digital\/vault\//i, 'canonical -> /vault/' ],
  [ /name=["']robots["'][^>]*content=["']noindex, follow["']/i, 'noindex redirect stub' ],
];

const failures = checks.filter( ( [ pattern ] ) => !pattern.test( html ) );
for ( const [ , label ] of checks )
{
  console.log( `${ failures.some( x => x[1] === label ) ? 'FAIL' : 'PASS' } ${ label }` );
}

if ( failures.length )
{
  console.error( `\nfoldprobe: ${ failures.length } FAILURE(S)` );
  process.exit( 1 );
}

console.log( '\nfoldprobe: PASS — /get/ is redirect-only; Vault owns customer downloads.' );
