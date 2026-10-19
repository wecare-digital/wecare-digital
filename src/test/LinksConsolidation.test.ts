import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { getAllNavItems, navigationConfig } from '../config/navigation';

const ROOT = path.resolve( __dirname, '..' );
const communications = fs.readFileSync( path.join( ROOT, 'pages/workspace/communications/index.tsx' ), 'utf8' );
const links = fs.readFileSync( path.join( ROOT, 'components/workspace/messaging/Links.tsx' ), 'utf8' );
const redirect = fs.readFileSync( path.join( ROOT, 'pages/workspace/link/index.tsx' ), 'utf8' );

describe( 'Links consolidation', () => {
  it( 'keeps Links contextual to Communications', () => {
    expect( navigationConfig.map( ( item ) => item.path ) ).not.toContain( '/workspace/link' );
    expect( getAllNavItems().map( ( item ) => item.path ) )
      .toContain( '/workspace/communications?view=manage&section=links' );
    expect( communications ).toContain( "import( '../../../components/workspace/messaging/Links' )" );
    expect( communications ).toContain( "case 'links': return <LinksPanel" );
  } );

  it( 'keeps the retired top-level URL as a compatibility redirect', () => {
    expect( redirect ).toContain( "pathname: '/workspace/communications'" );
    expect( redirect ).toContain( "section: 'links'" );
  } );

  it( 'uses non-destructive deactivation in the everyday UI', () => {
    expect( links ).toContain( 'const handleDeactivate = async' );
    expect( links ).toContain( "method: 'PUT'" );
    expect( links ).toContain( 'active: false' );
    expect( links ).not.toContain( "method: 'DELETE'" );
    expect( links ).not.toContain( 'handleDelete' );
  } );
} );
