import React from 'react';
import fs from 'node:fs';
import path from 'node:path';
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import PageShell from '../components/public/PageShell';
import ProductBlogPanel from '../components/ProductBlogPanel';
import Contact from '../pages/contact';
import { CUSTOMERSERVICE } from '../content/customerservice';
import { buildPageTitle } from '../lib/page-title';
import { blogCrumbs, breadcrumbSchema } from '../lib/breadcrumbs';
import { loadBlogCardIndex } from '../lib/blog-card-index';
import { getStaticProps } from '../pages/anew';
import { getAllNavItems, settingsConfig } from '../config/navigation';

vi.mock( 'next/link', () => ( { default: ( { href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> ) => <a href={ href } { ...props }>{ children }</a> } ) );
vi.mock( 'next/head', () => ( { default: ( { children }: { children: React.ReactNode } ) => <>{ children }</> } ) );
vi.mock( '../lib/blog-card-index', () => ( { loadBlogCardIndex: vi.fn() } ) );
vi.mock( '../lib/public-blog', () => ( {
  listPublicBlogPosts: vi.fn( async () => Array.from( { length: 200 }, ( _, index ) => ( {
    slug: `article-${index}`, title: `Article ${index}`, category: index % 2 ? 'Gastronomy' : 'Conversations',
  } ) ) ),
  listBlogCards: ( posts: unknown[] ) => posts,
} ) );

beforeEach( () => { HTMLElement.prototype.scrollTo = vi.fn(); } );
afterEach( () => { cleanup(); vi.clearAllMocks(); } );

describe( 'public page consolidation contracts', () => {
  it.each( [ 'Shop', 'Shop — WECARE.DIGITAL', 'Shop – WECARE', 'Shop | Wecare', 'Shop | WECARE.DIGITAL' ] )(
    'uses the public title format for %s', input => {
      expect( buildPageTitle( input ) ).toBe( 'Shop | WECARE.DIGITAL' );
    } );

  it( 'keeps PageShell breadcrumb-free while preserving canonical metadata', () => {
    const crumbs = [ { name: 'Home', href: '/' }, { name: 'Shop', href: '/shop/' }, { name: 'Anew' } ];
    const { container } = render( <PageShell title="Anew" description="Reflect on a decision."
      canonical="/anew/" crumbs={ crumbs }><p>Page content</p></PageShell> );
    expect( container.querySelector( 'nav[aria-label="Breadcrumb"]' ) ).toBeNull();
    expect( container.querySelector( 'script[type="application/ld+json"]' ) ).toBeNull();
    expect( document.querySelector( 'link[rel="canonical"]' ) ).toHaveAttribute( 'href', 'https://wecare.digital/anew/' );
    expect( container.querySelectorAll( 'header,footer,main' ) ).toHaveLength( 0 );
  } );

  it( 'keeps topic ancestry in both forms of a paginated blog trail', () => {
    const crumbs = blogCrumbs( 2, 'Gastronomy', '/blog/topic/gastronomy/' );
    const schema = breadcrumbSchema( crumbs, '/blog/topic/gastronomy/page/2/' );
    expect( schema.itemListElement.map( item => item.name ) ).toEqual( [ 'Home', 'Blog', 'Gastronomy', 'Page 2' ] );
    expect( schema.itemListElement[ 2 ].item ).toBe( 'https://wecare.digital/blog/topic/gastronomy/' );
    expect( schema.itemListElement[ 3 ].item ).toBe( 'https://wecare.digital/blog/topic/gastronomy/page/2/' );
  } );

  it( 'keeps the five page-based request services while removing the request hub from Contact', () => {
    render( <Contact /> );
    expect( CUSTOMERSERVICE ).toHaveLength( 5 );
    expect( CUSTOMERSERVICE.some( service => service.slug === 'leave-review' ) ).toBe( false );
    expect( screen.queryByRole( 'heading', { name: 'How can we help?', level: 2 } ) ).not.toBeInTheDocument();
    expect( screen.getByRole( 'heading', { name: 'Where to find us', level: 2 } ) ).toBeInTheDocument();
    for ( const service of CUSTOMERSERVICE ) {
      expect( screen.queryByRole( 'link', { name: service.name } ) ).not.toBeInTheDocument();
    }
  } );

  it( 'seeds a bounded first page for every category rather than the full corpus', async () => {
    const result = await getStaticProps( {} as never );
    expect( 'props' in result ).toBe( true );
    if ( !( 'props' in result ) ) throw new Error( 'Expected static props' );
    const props = await result.props;
    expect( props.blogCards ).toHaveLength( 6 );
    expect( props.blogCategories ).toEqual( [ 'Conversations', 'Gastronomy' ] );
    for ( const category of props.blogCategories ) {
      expect( props.blogCards.filter( card => card.category === category ) ).toHaveLength( 3 );
    }
  } );

  it( 'loads later cards, preserves pagination, and searches tags outside the initial seed', async () => {
    const cards = Array.from( { length: 9 }, ( _, index ) => ( {
      slug: `p-${index}`, title: `Later article ${index}`, category: 'Conversations', tags: index === 8 ? [ 'rare-tag' ] : [],
    } ) );
    vi.mocked( loadBlogCardIndex ).mockResolvedValueOnce( cards );
    const { container } = render( <ProductBlogPanel cards={ cards.slice( 0, 3 ) } categories={ [ 'Conversations' ] } /> );
    await waitFor( () => expect( container.querySelectorAll( '.pbp-card' ) ).toHaveLength( 9 ) );
    fireEvent.click( screen.getByRole( 'button', { name: 'Next page' } ) );
    expect( screen.getByRole( 'progressbar' ) ).toHaveAttribute( 'aria-valuenow', '2' );
    fireEvent.change( screen.getByRole( 'searchbox' ), { target: { value: 'rare-tag' } } );
    expect( screen.getByRole( 'link', { name: /Later article 8/ } ) ).toHaveAttribute( 'href', '/post/p-8/' );
    expect( container.querySelectorAll( '.pbp-card' ) ).toHaveLength( 1 );
  } );

  it( 'keeps seed content accessible after failure and can retry the complete index', async () => {
    vi.mocked( loadBlogCardIndex ).mockRejectedValueOnce( new Error( 'offline' ) ).mockResolvedValueOnce( [
      { slug: 'tail', title: 'Tail article', category: 'Conversations' },
    ] );
    render( <ProductBlogPanel cards={ [ { slug: 'seed', title: 'Seed article', category: 'Conversations' } ] }
      categories={ [ 'Conversations' ] } /> );
    await screen.findByRole( 'button', { name: 'Try again' } );
    expect( screen.getByRole( 'link', { name: /Seed article/ } ) ).toBeInTheDocument();
    expect( screen.getByRole( 'link', { name: 'Browse perspectives' } ) ).toHaveAttribute( 'href', '/blog/' );
    fireEvent.click( screen.getByRole( 'button', { name: 'Try again' } ) );
    expect( await screen.findByRole( 'link', { name: /Tail article/ } ) ).toBeInTheDocument();
  } );

  it( 'preserves the seed and offers retry when the generated index is empty', async () => {
    vi.mocked( loadBlogCardIndex ).mockResolvedValueOnce( [] ).mockResolvedValueOnce( [
      { slug: 'tail', title: 'Recovered article', category: 'Conversations' },
    ] );
    render( <ProductBlogPanel cards={ [ { slug: 'seed', title: 'Seed article', category: 'Conversations' } ] }
      categories={ [ 'Conversations' ] } /> );
    await screen.findByRole( 'button', { name: 'Try again' } );
    expect( screen.getByRole( 'link', { name: /Seed article/ } ) ).toBeInTheDocument();
    fireEvent.click( screen.getByRole( 'button', { name: 'Try again' } ) );
    expect( await screen.findByRole( 'link', { name: /Recovered article/ } ) ).toBeInTheDocument();
  } );

  it( 'removes only redundant navigation entries', () => {
    const paths = getAllNavItems().map( item => item.path );
    for ( const path of [ '/workspace/access', '/workspace/docs', '/workspace/engage/whatsapp', '/workspace/dashboard/waba-usernames' ] ) {
      expect( paths ).not.toContain( path );
    }
    // BSUID & Usernames now deep-links the canonical Communications WhatsApp management surface.
    expect( paths ).toContain( '/workspace/communications?view=manage&section=whatsapp&tool=bsuid' );
    // FEAT-003: Sign-in & MFA relocated OUT of the routes tree into the gear panel, so it is no
    // longer a URL in getAllNavItems. It is reached through the gear (SettingsGear mounts
    // TotpSetup inline for the account group's mfaPanel) — asserted below so reachability holds.
    expect( paths ).not.toContain( '/workspace/access/security' );
    const account = settingsConfig.find( g => g.id === 'account' );
    expect( account?.mfaPanel?.label ).toBe( 'Sign-in & MFA' );
    const gear = fs.readFileSync( path.resolve( __dirname, '../components/SettingsGear.tsx' ), 'utf8' );
    expect( gear ).toContain( '<TotpSetup />' );
    expect( fs.existsSync( path.resolve( __dirname, '../pages/workspace/access/security.tsx' ) ) ).toBe( false );
  } );
} );
