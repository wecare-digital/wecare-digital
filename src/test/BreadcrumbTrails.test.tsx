/**
 * The visible breadcrumb and the BreadcrumbList JSON-LD are ONE trail.
 *
 * .kiro/steering/30-seo.md requires the BreadcrumbList to "mirror the visible breadcrumb trail
 * exactly". Until 2026-10-16 the fifteen product and family pages rendered Home / Shop / [Parent /]
 * Name while _app.tsx emitted Home / Name for them, and blog topic pages rendered Home / Blog while
 * BlogIndexHead emitted Home / Blog / <Topic>. Both pairs now share a source:
 * src/content/breadcrumbTrails.ts for the product family, and the stream base for the blog.
 *
 * These tests pin the sharing rather than today's fifteen trails, so a page added with a
 * hand-typed `crumbs` array, or a JSON-LD builder that stops reading the map, fails here first.
 */
import React from 'react';
import fs from 'fs';
import path from 'path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import { BREADCRUMB_TRAILS, breadcrumbTrail } from '../content/breadcrumbTrails';
import { PRODUCTS } from '../content/products';
import { PRODUCT_CHILDREN } from '../content/productChildren';
import BlogIndexView from '../components/BlogIndexView';
import { toBlogCard, type PublicBlogPost } from '../lib/public-blog';
import type { BlogIndexPageProps } from '../lib/blog-index-props';

vi.mock( 'next/head', () => ( { default: ( { children }: { children: React.ReactNode } ) => <>{ children }</> } ) );

const ROOT = path.resolve( __dirname, '..', '..' );
const PAGES = path.join( ROOT, 'src', 'pages' );
const APP = fs.readFileSync( path.join( PAGES, '_app.tsx' ), 'utf8' );

/** PUBLIC_PAGE_META's `name` for a route, read from the _app.tsx source. */
const metaName = ( route: string ): string | undefined => {
  const escaped = route.replace( /[.*+?^${}()|[\]\\/]/g, '\\$&' );
  const m = APP.match( new RegExp( `\\n\\s*'${escaped}': \\{ name: '([^']+)'` ) );
  return m?.[ 1 ];
};

const pageFileFor = ( route: string ): string | null => {
  for ( const f of [ path.join( PAGES, `${route}.tsx` ), path.join( PAGES, route, 'index.tsx' ) ] ) {
    if ( fs.existsSync( f ) ) return f;
  }
  return null;
};

const walk = ( dir: string ): string[] => fs.readdirSync( dir, { withFileTypes: true } ).flatMap(
  entry => entry.isDirectory() ? walk( path.join( dir, entry.name ) ) : [ path.join( dir, entry.name ) ] );

describe( 'the product-family trails', () => {
  const routes = Object.keys( BREADCRUMB_TRAILS );

  it( 'covers every ProductPage that renders a visible trail, and nothing else', () => {
    const withCrumbs = walk( PAGES )
      .filter( f => f.endsWith( '.tsx' ) && !f.includes( `${path.sep}workspace${path.sep}` ) )
      .filter( f => /\bcrumbs=\{ breadcrumbTrail\(/.test( fs.readFileSync( f, 'utf8' ) ) )
      .map( f => '/' + path.relative( PAGES, f ).replace( /\\/g, '/' ).replace( /(\/index)?\.tsx$/, '' ) );
    expect( withCrumbs.sort() ).toEqual( [ ...routes ].sort() );
  } );

  it.each( Object.keys( BREADCRUMB_TRAILS ) )( '%s takes its visible trail from the shared map', route => {
    const file = pageFileFor( route.slice( 1 ) );
    expect( file, `no page file for ${route}` ).not.toBeNull();
    const source = fs.readFileSync( file as string, 'utf8' );
    // No hand-typed array: the one call, naming this page's own route.
    expect( source ).toContain( `crumbs={ breadcrumbTrail( '${route}' ) }` );
    expect( source ).not.toMatch( /crumbs=\{\s*\[/ );
  } );

  it.each( Object.keys( BREADCRUMB_TRAILS ) )( '%s is a well-formed trail ending at its own page', route => {
    const trail = BREADCRUMB_TRAILS[ route ];
    expect( trail[ 0 ] ).toEqual( { label: 'Home', href: '/' } );
    // Ends at the current page, unlinked, under the name PUBLIC_PAGE_META gives the route - the
    // name the WebPage node already carries.
    expect( trail[ trail.length - 1 ].href ).toBeUndefined();
    expect( trail[ trail.length - 1 ].label ).toBe( metaName( route ) );
    for ( const crumb of trail.slice( 0, -1 ) ) {
      expect( crumb.href, `${route}: an ancestor crumb must link` ).toBeDefined();
      expect( crumb.href as string ).toMatch( /\/$/ );
      if ( crumb.href !== '/' ) {
        expect( pageFileFor( ( crumb.href as string ).slice( 1, -1 ) ), `${crumb.href} is not a page` ).not.toBeNull();
      }
    }
  } );

  it( 'names each page exactly as its content module does', () => {
    const names = new Map<string, string>( [
      ...PRODUCTS.map( p => [ `/${p.slug}`, p.name ] as [ string, string ] ),
      ...PRODUCT_CHILDREN.map( c => [ c.path.replace( /\/$/, '' ), c.product.name ] as [ string, string ] ),
    ] );
    for ( const [ route, trail ] of Object.entries( BREADCRUMB_TRAILS ) ) {
      expect( names.get( route ), `${route} is not in products.ts or productChildren.ts` ).toBeDefined();
      expect( trail[ trail.length - 1 ].label ).toBe( names.get( route ) );
    }
    // A child's parent crumb is the parent productChildren.ts declares, when it has a page.
    for ( const child of PRODUCT_CHILDREN ) {
      const trail = BREADCRUMB_TRAILS[ child.path.replace( /\/$/, '' ) ];
      const parent = trail[ trail.length - 2 ];
      if ( child.parentHref ) expect( parent ).toEqual( { label: child.parent, href: child.parentHref } );
      else expect( parent ).toEqual( { label: 'Shop', href: '/shop/' } );
    }
  } );

  it( 'is what _app.tsx builds the BreadcrumbList from', () => {
    expect( APP ).toContain( "import { breadcrumbTrail } from '../content/breadcrumbTrails';" );
    expect( APP ).toContain( 'key="public-breadcrumbs"' );
    expect( APP ).toContain( 'breadcrumbSchema( breadcrumbTrail( router.pathname )?.map( ( { label, href } ) => ( { name: label, href } ) )' );
  } );

  it( 'normalises the trailing slash and hands out copies', () => {
    expect( breadcrumbTrail( '/dastavez/drafting/' ) ).toEqual( breadcrumbTrail( '/dastavez/drafting' ) );
    expect( breadcrumbTrail( '/contact' ) ).toBeUndefined();
    const copy = breadcrumbTrail( '/hunar/kaushal' ) as { label: string }[];
    copy[ 0 ].label = 'changed';
    expect( BREADCRUMB_TRAILS[ '/hunar/kaushal' ][ 0 ].label ).toBe( 'Home' );
  } );
} );

describe( 'the blog trails', () => {
  const post: PublicBlogPost = {
    id: 'post-1', title: 'A Note', slug: 'a-note', excerpt: 'An excerpt.', category: 'Guides',
    tags: [], author: 'WECARE.DIGITAL', publishedDate: '2026-09-28T00:00:00Z',
    modifiedDate: '2026-09-28T00:00:00Z', robots: 'index, follow', richContent: { nodes: [] },
  } as unknown as PublicBlogPost;
  const props = ( overrides: Partial<BlogIndexPageProps> ): BlogIndexPageProps => ( {
    posts: [ toBlogCard( post ) ], page: 1, totalPages: 3, totalPosts: 3,
    categories: [ 'Conversations', 'Guides' ], categoryCounts: { Conversations: 1, Guides: 2 },
    activeCategory: 'Conversations', defaultCategory: 'Conversations', ...overrides,
  } );
  const trailOf = ( container: HTMLElement ) => Array.from(
    container.querySelectorAll( 'nav[aria-label="Breadcrumb"] li' ) ).map( li => ( {
    label: ( li.textContent || '' ).trim(),
    // next/link drops the trailing slash under vitest (trailingSlash lives in next.config.js, which
    // the test runner does not load), so compare paths without it.
    href: li.querySelector( 'a' )?.getAttribute( 'href' )?.replace( /(.)\/$/, '$1' ) ?? undefined,
  } ) );

  beforeEach( () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true, json: async () => ( { ok: true, count: 0, posts: [] } ),
    } ) );
  } );
  afterEach( () => { vi.unstubAllGlobals(); } );

  it( 'keeps /blog/ and /blog/page/N/ as they were', () => {
    expect( trailOf( render( <BlogIndexView { ...props( {} ) } /> ).container ) ).toEqual( [
      { label: 'Home', href: '/' }, { label: 'Blog', href: undefined } ] );
    expect( trailOf( render( <BlogIndexView { ...props( { page: 2 } ) } /> ).container ) ).toEqual( [
      { label: 'Home', href: '/' }, { label: 'Blog', href: '/blog' }, { label: 'Page 2', href: undefined } ] );
  } );

  it( 'names the topic on a topic stream, as BlogIndexHead does', () => {
    expect( trailOf( render( <BlogIndexView { ...props( { activeCategory: 'Guides' } ) } /> ).container ) ).toEqual( [
      { label: 'Home', href: '/' }, { label: 'Blog', href: '/blog' }, { label: 'Guides', href: undefined } ] );
    expect( trailOf( render( <BlogIndexView { ...props( { activeCategory: 'Guides', page: 3 } ) } /> ).container ) )
      .toEqual( [
        { label: 'Home', href: '/' }, { label: 'Blog', href: '/blog' },
        { label: 'Guides', href: '/blog/topic/guides' }, { label: 'Page 3', href: undefined } ] );
  } );
} );
