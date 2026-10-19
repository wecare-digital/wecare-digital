import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { getAllNavItems, navigationConfig } from '../config/navigation';

const ROOT = path.resolve( __dirname, '..' );
const communications = fs.readFileSync( path.join( ROOT, 'pages/workspace/communications/index.tsx' ), 'utf8' );
const links = fs.readFileSync( path.join( ROOT, 'components/workspace/messaging/Links.tsx' ), 'utf8' );
const redirect = fs.readFileSync( path.join( ROOT, 'pages/workspace/link/index.tsx' ), 'utf8' );

describe( 'Links consolidation', () => {
  it( 'exposes Links canonically in Content while keeping the panel embeddable in Communications', () => {
    expect( navigationConfig.map( ( item ) => item.path ) ).not.toContain( '/workspace/link' );
    // #956 (Rebuild Content as one publishing workspace): Short Links moved into the
    // Content workspace, so its canonical nav destination is /workspace/content?view=links
    // (the Content section lists it, label 'Short links') rather than a Communications
    // manage child. The Links PANEL is still hosted by Communications (asserted below),
    // but its primary route now lives under Content.
    expect( getAllNavItems().map( ( item ) => item.path ) )
      .toContain( '/workspace/content?view=links' );
    expect( communications ).toContain( "import( '../../../components/workspace/messaging/Links' )" );
    expect( communications ).toContain( "case 'links': return <LinksPanel" );
  } );

  it( 'keeps the retired top-level URL as a compatibility redirect', () => {
    // #956 re-pointed the retired /workspace/link redirect at the Content workspace
    // (router.replace to /workspace/content with view 'links') instead of Communications.
    expect( redirect ).toContain( "pathname: '/workspace/content'" );
    expect( redirect ).toContain( "view: 'links'" );
  } );

  it( 'uses non-destructive deactivation in the everyday UI', () => {
    expect( links ).toContain( 'const handleDeactivate = async' );
    expect( links ).toContain( "method: 'PUT'" );
    expect( links ).toContain( 'active: false' );
    expect( links ).not.toContain( "method: 'DELETE'" );
    expect( links ).not.toContain( 'handleDelete' );
  } );
} );
