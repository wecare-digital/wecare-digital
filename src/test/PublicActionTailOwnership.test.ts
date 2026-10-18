import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const read = ( relative: string ) =>
  fs.readFileSync( path.resolve( process.cwd(), relative ), 'utf8' );

describe( 'global public action tail ownership', () => {
  const app = read( 'src/pages/_app.tsx' );
  const rotatingHero = read( 'src/components/RotatingHero.tsx' );

  it( 'mounts Contribute + Subscribe + Share exactly once in _app after policy and before footer', () => {
    expect( app ).toContain( "import PublicShare from '../components/PublicShare';" );
    expect( ( app.match( /<PublicShare \/>/g ) || [] ) ).toHaveLength( 1 );

    const component = app.indexOf( '<Component { ...pageProps } />' );
    const policy = app.indexOf( '<PublicPolicyDetails />' );
    const actions = app.indexOf( '<div className="public-action-tail">' );
    const share = app.indexOf( '<PublicShare />', actions );
    const footer = app.indexOf( '<Footer />' );

    expect( component ).toBeGreaterThan( -1 );
    expect( policy ).toBeGreaterThan( component );
    expect( actions ).toBeGreaterThan( policy );
    expect( share ).toBeGreaterThan( actions );
    expect( footer ).toBeGreaterThan( share );
  } );

  it( 'keeps RotatingHero hero-only', () => {
    expect( rotatingHero ).not.toContain( "import PublicShare from './PublicShare';" );
    expect( rotatingHero ).not.toContain( '<PublicShare' );
    expect( rotatingHero ).not.toContain( 'noShare' );
    expect( rotatingHero ).not.toContain( 'rh-tail' );
  } );

  it( 'keeps former page-level owners free of a second dock', () => {
    const formerOwners = [
      'src/pages/index.tsx',
      'src/pages/grahak-os/index.tsx',
      'src/pages/vayulok/index.tsx',
      'src/pages/post/[slug].tsx',
    ];

    for ( const file of formerOwners ) {
      const source = read( file );
      expect( source, file ).not.toContain( 'import PublicShare' );
      expect( source, file ).not.toContain( '<PublicShare' );
      expect( source, file ).not.toContain( 'noShare' );
    }
  } );

  it( 'uses the shared public measure and mobile gutter for the app-owned dock', () => {
    const start = app.indexOf( '.public-action-tail{' );
    expect( start ).toBeGreaterThan( -1 );
    const rule = app.slice( start, app.indexOf( '}', start ) );
    expect( rule ).toContain( 'max-width:var(--public-content-max)' );
    expect( rule ).toContain( 'padding:0 var(--public-page-gutter) 48px' );
    expect( app ).toContain( '.public-action-tail{padding-inline:16px;padding-bottom:40px}' );
  } );
} );
