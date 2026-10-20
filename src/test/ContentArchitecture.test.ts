import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { getAllNavItems, navigationConfig } from '../config/navigation';

const ROOT = path.resolve( __dirname, '..' );
const page = fs.readFileSync( path.join( ROOT, 'pages/workspace/content/index.tsx' ), 'utf8' );
const links = fs.readFileSync( path.join( ROOT, 'components/workspace/content/ShortLinks.tsx' ), 'utf8' );
const seoRedirect = fs.readFileSync( path.join( ROOT, 'pages/workspace/seo/index.tsx' ), 'utf8' );
const linkRedirect = fs.readFileSync( path.join( ROOT, 'pages/workspace/link/index.tsx' ), 'utf8' );

describe( 'canonical Content workspace', () => {
  it( 'has exactly Blog, Production, SEO and Short links as primary modes', () => {
    const block = page.slice( page.indexOf( 'const TABS' ), page.indexOf( 'function one' ) );
    const labels = [ ...block.matchAll( /label: '([^']+)'/g ) ].map( match => match[ 1 ] );
    expect( labels ).toEqual( [ 'Blog', 'Production', 'SEO', 'Short links' ] );
  } );

  it( 'keeps publishing contextual instead of promoting another permanent workspace', () => {
    const primary = navigationConfig.map( item => item.path );
    expect( primary ).not.toContain( '/workspace/content' );
    expect( primary ).not.toContain( '/workspace/link' );
    expect( primary ).not.toContain( '/workspace/seo' );
    expect( getAllNavItems().map( item => item.path ) ).toContain( '/workspace/content' );
  } );

  it( 'keeps supported AWS-native SEO and production work reachable', () => {
    const all = getAllNavItems().map( item => item.path );
    for ( const destination of [
      '/workspace/content?view=blog',
      '/workspace/content?view=production',
      '/workspace/content?view=seo&area=tools',
      '/workspace/content?view=seo&area=pages',
      '/workspace/seo/blog-studio',
      '/workspace/seo/blog-production?tab=review',
      '/workspace/seo/blog-production?tab=qa',
      '/workspace/seo/blog-production?tab=publish',
    ] ) {
      expect( all ).toContain( destination );
    }
  } );

  it( 'does not re-advertise configuration-blocked external SEO client pages', () => {
    const all = getAllNavItems().map( item => item.path.split( '?' )[ 0 ] );
    for ( const blocked of [
      '/workspace/seo/page', '/workspace/seo/pages', '/workspace/seo/issues',
      '/workspace/seo/analytics', '/workspace/seo/tracking', '/workspace/seo/schema',
      '/workspace/seo/properties', '/workspace/seo/sitemaps',
    ] ) {
      expect( all ).not.toContain( blocked );
    }
  } );

  it( 'uses one Short Links implementation and redirects the legacy route', () => {
    expect( page ).toContain( '<ShortLinks />' );
    expect( links ).toContain( 'const ShortLinks: React.FC' );
    expect( linkRedirect ).toContain( "pathname: '/workspace/communications'" );
    expect( linkRedirect ).toContain( "section: 'links'" );
  } );

  it( 'makes the Content short-link entry a redirect to the canonical surface, not a second UI', () => {
    // The only live short-link implementation is messaging/Links.tsx. Content's ShortLinks is a
    // pointer: it must route to Communications → Manage → Links and must NOT re-implement the
    // CRUD (no link fetch, no create/update handlers).
    expect( links ).toContain( "pathname: '/workspace/communications'" );
    expect( links ).toContain( "section: 'links'" );
    expect( links ).toContain( 'router.replace' );
    expect( links ).not.toContain( 'handleCreate' );
    expect( links ).not.toContain( 'handleUpdate' );
    expect( links ).not.toContain( '/links' );
  } );

  it( 'maps the old SEO hub only into supported Content modes', () => {
    expect( seoRedirect ).toContain( "view: 'blog'" );
    expect( seoRedirect ).toContain( "view: 'production'" );
    expect( seoRedirect ).toContain( "view: 'seo'" );
    expect( seoRedirect ).not.toContain( 'NEXT_PUBLIC_SEO_API_URL' );
  } );
} );
