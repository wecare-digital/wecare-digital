import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { getAllNavItems, navigationConfig } from '../config/navigation';

const ROOT = path.resolve( __dirname, '..' );
const communications = fs.readFileSync( path.join( ROOT, 'pages/workspace/communications/index.tsx' ), 'utf8' );
const links = fs.readFileSync( path.join( ROOT, 'components/workspace/messaging/Links.tsx' ), 'utf8' );
const redirect = fs.readFileSync( path.join( ROOT, 'pages/workspace/link/index.tsx' ), 'utf8' );

describe( 'Links consolidation', () => {
  it( 'exposes Links canonically in Communications Manage', () => {
    expect( navigationConfig.map( ( item ) => item.path ) ).not.toContain( '/workspace/link' );
    expect( getAllNavItems().map( ( item ) => item.path ) )
      .toContain( '/workspace/communications?view=manage&section=links' );
    expect( communications ).toContain( "import( '../../../components/workspace/messaging/Links' )" );
    expect( communications ).toContain( "case 'links': return <LinksPanel" );
  } );

  it( 'keeps the retired top-level URL as a compatibility redirect', () => {
    expect( redirect ).toContain( "pathname: '/workspace/communications'" );
    expect( redirect ).toContain( "view: 'manage'" );
    expect( redirect ).toContain( "section: 'links'" );
  } );

  it( 'uses non-destructive deactivation in the everyday UI', () => {
    expect( links ).toContain( 'const handleDeactivate = async' );
    expect( links ).toContain( "method: 'PUT'" );
    expect( links ).toContain( 'active: false' );
    expect( links ).not.toContain( "method: 'DELETE'" );
    expect( links ).not.toContain( 'handleDelete' );
  } );

  it( 'implements the ACTIVE -> INACTIVE -> RETIRED lifecycle with a reversible reactivate', () => {
    // Deactivate is reversible (handleReactivate), retire is the one terminal, irreversible move
    // and it is a lifecycle transition — not a DELETE — so the record and clicks survive.
    expect( links ).toContain( 'const handleReactivate = async' );
    expect( links ).toContain( 'const handleRetire = async' );
    expect( links ).toContain( "lifecycleState: 'RETIRED'" );
    expect( links ).toContain( 'active: true' );
    expect( links ).toContain( "type LinkLifecycle = 'ACTIVE' | 'INACTIVE' | 'RETIRED'" );
    // A retired link is frozen in the UI: its Edit control is gated off.
    expect( links ).toContain( "disabled={ lifecycle === 'RETIRED' }" );
  } );

  it( 'lets a link be attached to a Customer/Campaign/Order/Invoice/Service/general record', () => {
    expect( links ).toContain( 'relatedType' );
    expect( links ).toContain( 'relatedId' );
    expect( links ).toContain( 'purpose' );
    for ( const kind of [ 'general', 'customer', 'campaign', 'order', 'invoice', 'service' ] ) {
      expect( links ).toContain( `value: '${ kind }'` );
    }
  } );
} );
