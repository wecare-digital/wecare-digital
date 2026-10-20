import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = process.cwd();
const read = ( file: string ) => fs.readFileSync( path.join( root, file ), 'utf8' );

describe( 'Workspace Home visual contract', () => {
  it( 'styles Next/Link cards through a prefixed global styled-jsx block', () => {
    const source = read( 'src/pages/workspace/index.tsx' );
    expect( source ).toContain( '<style jsx global>' );
    expect( source ).toContain( '.workspace-home .attention-card' );
    expect( source ).toContain( '.workspace-home .start-card' );
    expect( source ).toContain( '.workspace-home .work-card' );
    expect( source ).toContain( 'grid-template-columns:repeat(2,minmax(0,1fr))' );
    expect( source ).toContain( 'grid-template-columns:repeat(4,minmax(0,1fr))' );
    expect( source ).toContain( 'grid-template-columns:repeat(3,minmax(0,1fr))' );
  } );

  it( 'inherits the canonical Home mobile rhythm without copying the public shell', () => {
    const source = read( 'src/pages/workspace/index.tsx' );
    expect( source ).toContain( 'var(--public-mobile-hero-top)' );
    expect( source ).toContain( 'var(--public-mobile-page-gutter)' );
    expect( source ).toContain( 'var(--public-mobile-section-gap)' );
    expect( source ).toContain( 'var(--public-mobile-hero-size)' );
    expect( source ).toContain( 'var(--public-mobile-section-size)' );
    expect( source ).toContain( 'var(--public-mobile-card-size)' );
    expect( source ).toContain( '@media(max-width:340px)' );
  } );

  it( 'removes the generic bordered inner-page frame only on Workspace Home', () => {
    const source = read( 'src/components/Layout.tsx' );
    expect( source ).toContain( "isHome ? 'workspace-home-shell' : ''" );
    expect( source ).toContain( '.workspace-home-shell :global(.inner-content-container)' );
    expect( source ).toContain( 'border:0;' );
    expect( source ).toContain( 'overflow:visible;' );
  } );
} );

describe( 'Workspace universal search visual contract', () => {
  it( 'renders as a fixed contained modal rather than document flow', () => {
    const source = read( 'src/components/SearchModal.tsx' );
    expect( source ).toContain( '<style jsx global>' );
    expect( source ).toContain( '.search-overlay{' );
    expect( source ).toContain( 'position:fixed;' );
    expect( source ).toContain( 'z-index:1600;' );
    expect( source ).toContain( '.search-overlay .search-modal{' );
    expect( source ).toContain( 'max-height:min(720px,calc(100dvh - 120px))' );
    expect( source ).toContain( '.search-overlay .search-result-item{' );
    expect( source ).toContain( '@media(max-width:640px)' );
  } );

  it( 'keeps the universal record-search implementation behind the repaired shell', () => {
    const source = read( 'src/components/SearchModal.tsx' );
    expect( source ).toContain( 'api.searchContacts' );
    expect( source ).toContain( 'api.listOrders' );
    expect( source ).toContain( 'api.listInvoicesEngine' );
    expect( source ).toContain( 'api.listFlowSubmissions' );
    expect( source ).toContain( "fetch( '/api/links' )" );
  } );
} );
