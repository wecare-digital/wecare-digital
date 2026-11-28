// customHttp.yml Cache-Control rules (audit WEB-5).
//
// Amplify does not document which block wins when several patterns match one URL. Measured on
// the live site, matching blocks merge and the later, more specific block wins for a header. So
// this resolves every probe URL twice - "last matching block wins" and "most specific block
// wins" - and requires both answers to be the intended value. The glob model is the usual one:
// `**` crosses `/`, `*` does not, and a trailing slash on the URL is ignored.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve( new URL( '..', import.meta.url ).pathname );
const HTML = 'public, max-age=0, must-revalidate, s-maxage=31536000';
const MEDIA = 'public, max-age=86400, stale-while-revalidate=604800';
const HASHED = 'public, max-age=31536000, immutable';
const NO_STORE = 'no-store, max-age=0, must-revalidate';

/** Ordered `{ pattern, cacheControl }` blocks. Folded multi-line values are skipped. */
function cacheBlocks() {
  const blocks = [];
  let current = null;
  let key = null;
  for ( const raw of fs.readFileSync( path.join( ROOT, 'customHttp.yml' ), 'utf8' ).split( '\n' ) ) {
    const line = raw.trim();
    if ( !line || line.startsWith( '#' ) ) continue;
    const pattern = /^-\s*pattern:\s*["']?(.+?)["']?\s*$/.exec( line );
    if ( pattern ) {
      current = { pattern: pattern[ 1 ], cacheControl: null };
      blocks.push( current );
      continue;
    }
    const keyLine = /^-\s*key:\s*["']?(.+?)["']?\s*$/.exec( line );
    if ( keyLine ) { key = keyLine[ 1 ].toLowerCase(); continue; }
    const value = /^value:\s*["']?(.+?)["']?\s*$/.exec( line );
    if ( value && current && key === 'cache-control' ) current.cacheControl = value[ 1 ];
  }
  return blocks;
}

function globToRegExp( glob ) {
  let re = '';
  for ( let i = 0; i < glob.length; i++ ) {
    const ch = glob[ i ];
    if ( ch === '*' && glob[ i + 1 ] === '*' ) {
      if ( glob[ i + 2 ] === '/' ) { re += '(?:.*/)?'; i += 2; } else { re += '.*'; i += 1; }
    } else if ( ch === '*' ) {
      re += '[^/]*';
    } else if ( ch === '/' && glob.slice( i + 1 ) === '**' ) {
      re += '(?:/.*)?';
      break;
    } else {
      re += ch.replace( /[.+?^${}()|[\]\\]/g, '\\$&' );
    }
  }
  return new RegExp( `^${ re }$` );
}

const matches = ( glob, url ) => {
  const re = globToRegExp( glob );
  return re.test( url ) || ( url.length > 1 && url.endsWith( '/' ) && re.test( url.slice( 0, -1 ) ) );
};

/** Literal patterns beat wildcards; otherwise the longer literal prefix wins. */
const specificity = glob => ( glob.includes( '*' ) ? glob.indexOf( '*' ) : 1000 + glob.length );

function resolve( url ) {
  const hits = cacheBlocks().filter( b => b.cacheControl && matches( b.pattern, url ) );
  const last = hits.at( -1 )?.cacheControl;
  const specific = [ ...hits ].sort( ( a, b ) => specificity( b.pattern ) - specificity( a.pattern ) )[ 0 ]?.cacheControl;
  return { last, specific, patterns: hits.map( h => h.pattern ) };
}

function assertCache( url, expected ) {
  const { last, specific, patterns } = resolve( url );
  assert.equal( last, expected, `${ url }: last matching block (${ patterns.join( ', ' ) })` );
  assert.equal( specific, expected, `${ url }: most specific block (${ patterns.join( ', ' ) })` );
}

test( 'the glob model matches the shapes this file uses', () => {
  assert.ok( matches( '**/*', '/' ) );
  assert.ok( matches( '**/*', '/api/contacts' ) );
  assert.ok( matches( '/blog/**', '/blog/' ) );
  assert.ok( matches( '/blog/**', '/blog/page/2/' ) );
  assert.ok( !matches( '/blog/**', '/blogs/' ) );
  assert.ok( matches( '/atmos/nano-climate*', '/atmos/nano-climate/' ) );
  assert.ok( matches( '/get/o/**/*', '/get/o/stream/media/m/a.png' ) );
  assert.ok( !matches( '/get/o/**/*', '/get/secure/d/public/a.png' ) );
} );

test( 'every block sets one of the four intended Cache-Control values', () => {
  const blocks = cacheBlocks();
  assert.ok( blocks.length > 10, 'customHttp.yml parsed' );
  for ( const block of blocks.filter( b => b.cacheControl ) ) {
    assert.ok( [ HTML, MEDIA, HASHED, NO_STORE ].includes( block.cacheControl ), `${ block.pattern }: ${ block.cacheControl }` );
  }
  assert.equal( blocks[ 0 ].pattern, '**/*' );
  assert.equal( blocks[ 0 ].cacheControl, NO_STORE, 'the sitewide default stays no-store' );
} );

test( 'HTML pages revalidate in the browser and stay in the CDN until the next deploy', () => {
  for ( const url of [
    '/', '/contact/', '/terms/', '/blog/', '/blog/page/2/', '/blog/topic/x/page/3/', '/post/some-slug/',
    '/shop/', '/shop/kiosk/', '/checkout/', '/checkout/status/', '/orders/', '/vault/',
    '/elsewhere/visa/', '/atmos/green-ledger/', '/relay-os/', '/workspace/', '/workspace/engage/inbox/',
    '/ws/', '/ws/customers/',
  ] ) assertCache( url, HTML );
} );

test( 'VayuLok HTML and globe stay no-store', () => {
  for ( const url of [ '/atmos/nano-climate', '/atmos/nano-climate/', '/atmos/nano-climate/index.html', '/vayulok-globe.html' ] ) {
    assertCache( url, NO_STORE );
  }
} );

test( 'proxied API, auth, MCP and private media responses are never made cacheable', () => {
  for ( const url of [
    '/api/contacts', '/api/customer/orders/', '/api/site-language/languages', '/auth/', '/auth/state',
    '/auth/step', '/mcp', '/mcp/', '/get/secure/d/public/whatsapp/incoming/a.jpg', '/get/',
    '/manifest.json', '/robots.txt', '/sitemap.xml', '/vendor/amplify-ui.css',
  ] ) assertCache( url, NO_STORE );
} );

test( 'stable media is cached for a day with a week of stale-while-revalidate', () => {
  for ( const url of [ '/get/o/stream/media/m/wecare-digital.png', '/images/bharat-stack-group.png', '/images/sub/a.svg' ] ) {
    assertCache( url, MEDIA );
  }
} );

test( 'hashed Next assets stay immutable', () => {
  assertCache( '/_next/static/chunks/0abc.js', HASHED );
  assertCache( '/_next/static/css/0abc.css', HASHED );
} );

test( 'every top-level page under src/pages has an HTML cache block', () => {
  const pagesDir = path.join( ROOT, 'src/pages' );
  // /auth/ shares its prefix with the proxied /auth/state and /auth/step endpoints.
  const skip = new Set( [ '_app', '_document', '404', 'auth', 'index' ] );
  const routes = fs.readdirSync( pagesDir, { withFileTypes: true } )
    .map( entry => entry.isDirectory() ? entry.name : entry.name.replace( /\.(tsx|ts|jsx|js)$/, '' ) )
    .filter( name => !skip.has( name ) );
  assert.ok( routes.includes( 'contact' ) && routes.includes( 'workspace' ), 'pages listed' );
  for ( const name of routes ) {
    const { last } = resolve( `/${ name }/` );
    assert.equal( last, HTML, `/${ name }/ needs a "/${ name }/**" block in customHttp.yml` );
  }
} );
