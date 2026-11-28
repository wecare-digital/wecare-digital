// Public pages must not download the staff app (audit WEB-3).
//
// pages/_app.tsx and pages/_document.tsx are evaluated on every route, so everything they
// import statically lands in the bundle every public page downloads. This walks that static
// import graph through the source (dynamic import() calls are not followed, type-only imports
// are skipped) and fails if it reaches the staff shells, the staff API client, the Amplify
// configuration or the Amplify / Capacitor packages. A static WorkspaceShell import in _app.tsx
// put all of those, and the staff Cognito pool id, on every public page.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve( new URL( '..', import.meta.url ).pathname );
const ENTRIES = [ 'src/pages/_app.tsx', 'src/pages/_document.tsx' ];
const EXTENSIONS = [ '.tsx', '.ts', '.jsx', '.js', '.mjs' ];

// Local modules that only the authenticated apps may load.
const STAFF_MODULES = [
  /^src\/components\/WorkspaceShell\.tsx$/,
  /^src\/components\/AuthShell\.tsx$/,
  /^src\/components\/ws\/WsAuthShell\.tsx$/,
  /^src\/lib\/amplifyConfig\.ts$/,
  /^src\/lib\/capacitor\.ts$/,
  /^src\/api\//,
];
// Packages that must not be in the shared bundle.
const STAFF_PACKAGES = [ /^aws-amplify(\/|$)/, /^@aws-amplify\//, /^@capacitor\// ];

function stripComments( source ) {
  return source
    .replace( /\/\*[\s\S]*?\*\//g, '' )
    .replace( /(^|[^:'"`\\])\/\/.*$/gm, '$1' );
}

/** Static, value-level module specifiers of one source file. */
function staticSpecifiers( source ) {
  const code = stripComments( source );
  const specifiers = [];
  const statement = /(?:^|[;\n}])\s*(import|export)\s+(type\s+)?([^'"`;]*?\sfrom\s+)?['"]([^'"]+)['"]/g;
  let match;
  while ( ( match = statement.exec( code ) ) ) {
    const [ , keyword, typeOnly, clause, specifier ] = match;
    if ( typeOnly ) continue;
    if ( keyword === 'export' && !clause ) continue;
    // `import { type A, type B } from 'x'` is erased by the compiler.
    const named = clause && /^\s*\{([\s\S]*)\}\s*from\s+$/.exec( clause );
    if ( named && named[ 1 ].split( ',' ).map( s => s.trim() ).filter( Boolean ).every( s => s.startsWith( 'type ' ) ) ) continue;
    specifiers.push( specifier );
  }
  return specifiers;
}

function resolveLocal( fromFile, specifier ) {
  const base = specifier.startsWith( '@/' )
    ? path.join( ROOT, specifier.slice( 2 ) )
    : path.resolve( path.dirname( fromFile ), specifier );
  const candidates = [ base, ...EXTENSIONS.map( e => base + e ), ...EXTENSIONS.map( e => path.join( base, `index${ e }` ) ) ];
  return candidates.find( c => fs.existsSync( c ) && fs.statSync( c ).isFile() ) || null;
}

/** Every module reachable from the entries through static imports, with the chain to it. */
function staticGraph( entries ) {
  const parents = new Map();
  const packages = new Map();
  const queue = entries.map( e => [ path.join( ROOT, e ), null ] );
  while ( queue.length ) {
    const [ file, parent ] = queue.shift();
    if ( parents.has( file ) ) continue;
    parents.set( file, parent );
    if ( !/\.(tsx?|jsx?|mjs)$/.test( file ) ) continue;
    for ( const specifier of staticSpecifiers( fs.readFileSync( file, 'utf8' ) ) ) {
      if ( specifier.startsWith( '.' ) || specifier.startsWith( '@/' ) ) {
        const resolved = resolveLocal( file, specifier );
        if ( resolved ) queue.push( [ resolved, file ] );
      } else if ( !packages.has( specifier ) ) {
        packages.set( specifier, file );
      }
    }
  }
  const rel = p => path.relative( ROOT, p ).split( path.sep ).join( '/' );
  const chain = file => {
    const steps = [];
    for ( let at = file; at; at = parents.get( at ) ) steps.push( rel( at ) );
    return steps.join( ' <- ' );
  };
  return { files: [ ...parents.keys() ], packages, rel, chain };
}

test( 'the import parser sees value imports and skips type-only and dynamic imports', () => {
  const specs = staticSpecifiers( [
    "import a from './a';",
    "import { b,\n  c } from './bc';",
    "import type { T } from './types';",
    "import { type U } from './u-types';",
    "import './side-effect.css';",
    "export { d } from './d';",
    "export type { E } from './e-types';",
    "const F = dynamic( () => import( './lazy' ), { ssr: false } );",
    "// import nope from './commented';",
  ].join( '\n' ) );
  assert.deepEqual( specs, [ './a', './bc', './side-effect.css', './d' ] );
} );

test( 'modules every page loads do not statically import staff code, Amplify or Capacitor', () => {
  const { files, packages, rel, chain } = staticGraph( ENTRIES );
  const staffFiles = files.filter( f => STAFF_MODULES.some( re => re.test( rel( f ) ) ) );
  assert.deepEqual( staffFiles.map( chain ), [], 'staff modules reached from _app/_document' );
  const staffPackages = [ ...packages ].filter( ( [ name ] ) => STAFF_PACKAGES.some( re => re.test( name ) ) );
  assert.deepEqual(
    staffPackages.map( ( [ name, file ] ) => `${ name } <- ${ chain( file ) }` ), [],
    'Amplify or Capacitor packages reached from _app/_document',
  );
  // The walk itself must be working: _app reaches the public chrome.
  assert.ok( files.some( f => rel( f ) === 'src/components/Header.tsx' ), 'graph walk reached Header' );
} );

test( '_app.tsx loads every authenticated shell lazily and client-only', () => {
  const app = stripComments( fs.readFileSync( path.join( ROOT, 'src/pages/_app.tsx' ), 'utf8' ) );
  for ( const shell of [ 'components/AuthShell', 'components/ws/WsAuthShell', 'components/WorkspaceShell' ] ) {
    const lazy = new RegExp( `dynamic\\(\\s*\\(\\)\\s*=>\\s*import\\(\\s*'\\.\\./${ shell.replace( /\//g, '\\/' ) }'\\s*\\),\\s*\\{\\s*ssr:\\s*false\\s*\\}\\s*\\)` );
    assert.match( app, lazy, `${ shell } must be next/dynamic with ssr: false` );
  }
} );
