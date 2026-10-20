import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = process.cwd();
const read = ( file: string ) => fs.readFileSync( path.join( root, file ), 'utf8' );

describe( 'Workspace shared no-sidebar design layer', () => {
  it( 'loads after legacy page/button layers and before the authoritative form-control skin', () => {
    const app = read( 'src/pages/_app.tsx' );
    const innerPages = app.indexOf( "import '../styles/inner-pages.css'" );
    const innerUx = app.indexOf( "import '../styles/inner-ux.css'" );
    const button = app.indexOf( "import '../styles/button.css'" );
    const workspace = app.indexOf( "import '../styles/workspace.css'" );
    const form = app.indexOf( "import '../styles/form-controls.css'" );

    expect( innerPages ).toBeGreaterThan( -1 );
    expect( innerUx ).toBeGreaterThan( innerPages );
    expect( button ).toBeGreaterThan( innerUx );
    expect( workspace ).toBeGreaterThan( button );
    expect( form ).toBeGreaterThan( workspace );
  } );

  it( 'turns the legacy framed inner container into a canvas for every workspace route', () => {
    const css = read( 'src/styles/workspace.css' );
    expect( css ).toContain( '.workspace-shell .inner-content-container {' );
    expect( css ).toContain( 'border: 0 !important;' );
    expect( css ).toContain( 'border-radius: 0 !important;' );
    expect( css ).toContain( 'overflow: visible !important;' );
  } );

  it( 'covers all canonical hub shapes instead of patching only Workspace Home', () => {
    const css = read( 'src/styles/workspace.css' );
    [
      '.comms-page',
      '.commerce-page',
      '.service-page',
      '.page-shell',
      '.inner-page-container',
      '.tk-page',
    ].forEach( selector => expect( css ).toContain( selector ) );

    expect( css ).toContain( '.workspace-main .ps-tab' );
    expect( css ).toContain( '.workspace-main .comms-tabs button' );
    expect( css ).toContain( '.workspace-main .commerce-tabs button' );
    expect( css ).toContain( '.workspace-main .service-tabs button' );
    expect( css ).toContain( '.workspace-main .ledger-switch button' );
  } );

  it( 'uses the locked mobile foundation for canonical hub spacing and typography', () => {
    const css = read( 'src/styles/workspace.css' );
    expect( css ).toContain( 'var(--public-mobile-page-gutter)' );
    expect( css ).toContain( 'var(--public-mobile-section-gap)' );
    expect( css ).toContain( 'var(--public-mobile-section-size)' );
    expect( css ).toContain( 'var(--tap-min)' );
    expect( css ).toContain( 'env(safe-area-inset-bottom, 0px)' );
  } );

  it( 'gives shared PageShell surfaces one Workspace hierarchy', () => {
    const shell = read( 'src/components/PageShell.tsx' );
    const css = read( 'src/styles/workspace.css' );
    expect( shell ).toContain( '<span className="ps-eyebrow">Workspace</span>' );
    expect( css ).toContain( '.workspace-shell .ps-eyebrow' );
    expect( css ).toContain( '.workspace-shell .ps-title' );
    expect( css ).toContain( '.workspace-shell .ps-subtitle' );
  } );

  it( 'gives Customers and Tasks the same canonical hierarchy without rewriting their workflows', () => {
    const customers = read( 'src/pages/workspace/customers/index.tsx' );
    const tasks = read( 'src/pages/workspace/task/index.tsx' );

    expect( customers ).toContain( 'className="workspace-page-head"' );
    expect( customers ).toContain( '<h1>Customers</h1>' );
    expect( tasks ).toContain( 'className="tk-eyebrow">Workspace</p>' );

    // Workflow/data contracts remain intact.
    expect( customers ).toContain( 'api.archiveContact' );
    expect( tasks ).toContain( 'api.listConversationMeta' );
    expect( tasks ).toContain( 'api.updateConversationMeta' );
  } );
} );
