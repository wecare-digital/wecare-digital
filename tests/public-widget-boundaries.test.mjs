// A crash in a floating widget must not replace the page (audit WEB-10).
//
// SupportWidget, PublicShare and PublicPolicyDetails each sit in their own ErrorBoundary with
// a null fallback, and ErrorBoundary treats `fallback={ null }` as "render nothing" rather
// than falling through to the full-page error card.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { readSource } from './helpers/loadTsx.mjs';

const boundary = name => new RegExp( `<ErrorBoundary fallback=\\{ null \\}><${ name } /></ErrorBoundary>`, 'g' );

test( 'ErrorBoundary renders a null fallback instead of the error card', () => {
  const source = readSource( 'src/components/ErrorBoundary.tsx' );
  assert.match( source, /this\.props\.fallback !== undefined\) return this\.props\.fallback;/ );
} );

test( 'every widget mount has its own boundary', () => {
  const app = readSource( 'src/pages/_app.tsx' );
  assert.equal( ( app.match( boundary( 'SupportWidget' ) ) || [] ).length, 2, '_app.tsx: public and authenticated SupportWidget' );
  assert.equal( ( app.match( boundary( 'PublicShare' ) ) || [] ).length, 1, '_app.tsx: PublicShare' );
  assert.equal( ( app.match( boundary( 'PublicPolicyDetails' ) ) || [] ).length, 1, '_app.tsx: PublicPolicyDetails' );
  assert.ok( !/^\s*<(SupportWidget|PublicShare|PublicPolicyDetails) \/>/m.test( app ), '_app.tsx: no bare widget mount' );
  const authShell = readSource( 'src/components/AuthShell.tsx' );
  assert.match( authShell, boundary( 'SupportWidget' ) );
  assert.match( authShell, boundary( 'PublicShare' ) );
} );
