/**
 * Every non-home public page shows the breadcrumb its JSON-LD claims.
 *
 * .kiro/steering/30-seo.md requires a VISIBLE breadcrumb on every non-home page, backed by a
 * BreadcrumbList that "mirrors the visible breadcrumb trail exactly". _app.tsx emits that
 * BreadcrumbList ([Home, <PUBLIC_PAGE_META name>]) for every PUBLIC_PAGE_META route, but until
 * this was fixed eleven of those routes rendered NO visible trail - markup describing a path the
 * page never showed, which Breadcrumbs.tsx's own docblock warns "makes a rich result disappear
 * without explanation".
 *
 * These tests read the page sources the way BreadcrumbTrails.test.tsx does and assert that each
 * of the eleven renders a visible <Breadcrumbs> whose FINAL crumb label equals the exact
 * PUBLIC_PAGE_META name the JSON-LD uses. They fail if the breadcrumb is removed, or if its last
 * label drifts away from the name the WebPage/BreadcrumbList carry.
 */
import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';
import { CUSTOMERSERVICE } from '../content/customerservice';

const ROOT = path.resolve( __dirname, '..', '..' );
const PAGES = path.join( ROOT, 'src', 'pages' );
const APP = fs.readFileSync( path.join( PAGES, '_app.tsx' ), 'utf8' );

/** PUBLIC_PAGE_META's `name` for a route, read from the _app.tsx source (as BreadcrumbTrails does). */
const metaName = ( route: string ): string | undefined => {
  const escaped = route.replace( /[.*+?^${}()|[\]\\/]/g, '\\$&' );
  const m = APP.match( new RegExp( `\\n\\s*'${escaped}': \\{ name: '([^']+)'` ) );
  return m?.[ 1 ];
};

/** The slug->name map for the ProductPage-based request pages, from the content module. */
const CS_NAME = new Map( CUSTOMERSERVICE.map( p => [ p.slug, p.name ] as [ string, string ] ) );

/**
 * Resolve a route to the source file that actually renders its visible breadcrumb. orders.tsx
 * re-exports OrdersPage, so the trail lives in the component; the five request pages mount
 * ProductPage with a `crumbs` prop in the route file itself.
 */
const sourceFor = ( route: string ): { file: string; source: string } => {
  const map: Record<string, string> = {
    '/orders': path.join( ROOT, 'src', 'components', 'orders', 'OrdersPage.tsx' ),
  };
  const file = map[ route ]
    ?? ( fs.existsSync( path.join( PAGES, `${route.slice( 1 )}.tsx` ) )
      ? path.join( PAGES, `${route.slice( 1 )}.tsx` )
      : path.join( PAGES, route.slice( 1 ), 'index.tsx' ) );
  return { file, source: fs.readFileSync( file, 'utf8' ) };
};

/**
 * The last label of the visible trail declared in a page source. Handles both shapes used
 * across the eleven pages:
 *   - an inline string literal: <Breadcrumbs items={ [ ..., { label: 'Terms' } ] } />
 *   - the ProductPage prop whose final label is product.name:
 *       crumbs={ [ { label: 'Home', href: '/' }, { label: product.name } ] }
 * For the second shape the resolved name comes from the content module, keyed on the slug the
 * route file passes to customerserviceBySlug/ProductPage.
 */
const finalVisibleLabel = ( route: string, source: string ): string | undefined => {
  // Inline literal trail rendered directly by the page.
  const inline = source.match(
    /<Breadcrumbs\s+items=\{\s*\[[\s\S]*?\{\s*label:\s*'([^']+)'\s*\}\s*\]\s*\}\s*\/>/ );
  if ( inline ) return inline[ 1 ];

  // ProductPage request pages: the trail ends at product.name, resolved from the content module.
  if ( /crumbs=\{\s*\[\s*\{\s*label:\s*'Home',\s*href:\s*'\/'\s*\},\s*\{\s*label:\s*product\.name\s*\}\s*\]\s*\}/.test( source ) ) {
    return CS_NAME.get( route.slice( 1 ) );
  }
  return undefined;
};

const ROUTES = [
  '/grahak-os', '/vayulok', '/bharat-rx',
  '/terms', '/privacy', '/orders',
  '/submit-request', '/request-amendment', '/drop-docs', '/vault', '/request-pickup',
];

describe( 'the eleven public pages that emit a BreadcrumbList', () => {
  it.each( ROUTES )( '%s renders a visible breadcrumb ending at its PUBLIC_PAGE_META name', route => {
    const name = metaName( route );
    expect( name, `${route} is not in PUBLIC_PAGE_META` ).toBeDefined();

    const { source } = sourceFor( route );
    // A visible trail is present at all - the thing that was missing before. It is either
    // rendered directly by the page (<Breadcrumbs .../>) or supplied to ProductPage/PageShell
    // via the `crumbs` prop, which renders the same Breadcrumbs component.
    const rendersTrail = /<Breadcrumbs\b/.test( source ) || /\bcrumbs=\{\s*\[/.test( source );
    expect( rendersTrail, `${route} renders no visible breadcrumb trail` ).toBe( true );

    // And its last rung is the exact name the JSON-LD BreadcrumbList uses, so the two mirror.
    expect( finalVisibleLabel( route, source ), `${route} breadcrumb does not end at '${name}'` )
      .toBe( name );
  } );

  it( 'does not add a second page-level BreadcrumbList JSON-LD on these routes', () => {
    // _app.tsx owns the single BreadcrumbList for every PUBLIC_PAGE_META route. The simple pages
    // render a visible-only trail; the ProductPage request pages route through PageShell, which
    // re-uses next/head key="public-breadcrumbs" with the SAME @id/trail so it dedupes rather
    // than emitting a duplicate. Either way a page file must not hand-roll a BreadcrumbList node.
    for ( const route of ROUTES ) {
      const { source } = sourceFor( route );
      expect( source, `${route} must not inline a BreadcrumbList` ).not.toContain( "'BreadcrumbList'" );
      expect( source, `${route} must not inline a BreadcrumbList` ).not.toContain( '"BreadcrumbList"' );
    }
  } );
} );
