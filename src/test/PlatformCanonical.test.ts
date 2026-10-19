import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { getAllNavItems, navigationConfig } from '../config/navigation';

const ROOT = path.resolve( __dirname, '..' );
const canonical = fs.readFileSync( path.join( ROOT, 'pages/workspace/platform/index.tsx' ), 'utf8' );
const legacy = fs.readFileSync( path.join( ROOT, 'pages/workspace/settings/platform/index.tsx' ), 'utf8' );
const home = fs.readFileSync( path.join( ROOT, 'pages/workspace/index.tsx' ), 'utf8' );

describe( 'canonical Platform workspace', () => {
  it( 'is a first-class operating area', () => {
    expect( navigationConfig.map( ( item ) => item.path ) ).toContain( '/workspace/platform' );
    expect( home ).toContain( "href: '/workspace/platform'" );
  } );

  it( 'keeps the real heavy tools on the canonical hub', () => {
    expect( canonical ).toContain( "const MCPConnectionsPage = lazyTab(" );
    expect( canonical ).toContain( "const SystemArchitecturePage = lazyTab(" );
    expect( canonical ).toContain( "const LambdaFunctionsPage = lazyTab(" );
    expect( canonical ).toContain( "router.query.view" );
  } );

  it( 'keeps Settings/Platform only as a compatibility redirect', () => {
    expect( legacy ).toContain( "pathname: '/workspace/platform'" );
    expect( legacy ).not.toContain( 'MCPConnectionsPage' );
  } );

  it( 'search indexes canonical Platform deep links', () => {
    const paths = getAllNavItems().map( ( item ) => item.path );
    expect( paths ).toContain( '/workspace/platform?view=system-architecture' );
    expect( paths ).toContain( '/workspace/platform?view=lambda-functions' );
    expect( paths ).not.toContain( '/workspace/settings/platform?tab=system-architecture' );
  } );
} );
