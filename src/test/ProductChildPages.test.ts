import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = process.cwd();
const read = ( rel: string ): string => fs.readFileSync( path.join( ROOT, rel ), 'utf8' );

const CHILDREN = [
  [ '/elsewhere/visa/', 'src/pages/elsewhere/visa.tsx' ],
  [ '/elsewhere/trip/', 'src/pages/elsewhere/trip.tsx' ],
  [ '/elsewhere/activities/', 'src/pages/elsewhere/activities.tsx' ],
  [ '/dastavez/drafting/', 'src/pages/dastavez/drafting.tsx' ],
  [ '/dastavez/registration/', 'src/pages/dastavez/registration.tsx' ],
  [ '/dastavez/legal-reference/', 'src/pages/dastavez/legal-reference.tsx' ],
  [ '/ritual-guru/ritva/', 'src/pages/ritual-guru/ritva.tsx' ],
  [ '/ritual-guru/puja-guidance/', 'src/pages/ritual-guru/puja-guidance.tsx' ],
  [ '/ritual-guru/diy-puja-kit/', 'src/pages/ritual-guru/diy-puja-kit.tsx' ],
] as const;

describe( 'product family child pages', () => {
  it( 'ships every menu child as a real ProductPage route', () => {
    const header = read( 'src/components/Header.tsx' );
    const app = read( 'src/pages/_app.tsx' );
    const sitemap = read( 'scripts/generate-sitemap.js' );

    for ( const [ route, file ] of CHILDREN ) {
      expect( fs.existsSync( path.join( ROOT, file ) ), file ).toBe( true );
      const page = read( file );
      expect( page, file ).toContain( '<ProductPage' );
      expect( page, file ).toContain( 'canonicalPath={ child.path }' );
      expect( header, route ).toContain( `href: '${route}'` );
      expect( app, route ).toContain( `'${route.replace( /\/$/, '' )}':` );
      expect( sitemap, route ).toContain( `'${route.replace( /\/$/, '' )}'` );
    }
  } );

  it( 'keeps Elsewhere as a category only, never a standalone product/page', () => {
    expect( fs.existsSync( path.join( ROOT, 'src/pages/elsewhere.tsx' ) ) ).toBe( false );
    expect( read( 'src/content/products.ts' ) ).not.toContain( "slug: 'elsewhere'" );
    expect( read( 'src/pages/_app.tsx' ) ).not.toMatch( /^\s*'\/elsewhere'\s*:/m );
    const sitemap = read( 'scripts/generate-sitemap.js' );
    const publicExact = sitemap.match( /const PUBLIC_EXACT = new Set\( \[([\s\S]*?)\]\s*\);/ )?.[ 1 ] || '';
    expect( publicExact ).not.toMatch( /^\s*'\/elsewhere',?\s*$/m );
    // /elsewhere MAY appear in RETIRED_FAMILY_PARENTS; that guard is what prevents the
    // category label from ever becoming a sitemap destination again.

    const header = read( 'src/components/Header.tsx' );
    expect( header ).toContain( "label: 'Elsewhere'" );
    // Elsewhere's own keys run from its label to its children array. The children carry hrefs
    // of their own, so a fixed-width window past the label would read the Visa link as Elsewhere's.
    const ownKeys = header.match( /label:\s*'Elsewhere',([\s\S]*?)children:/ );
    expect( ownKeys, 'Elsewhere must stay a family with children' ).not.toBeNull();
    expect( ownKeys![ 1 ] ).not.toMatch( /\bhref\s*:/ );
    // And nothing in the menu links to a standalone /elsewhere/ page.
    expect( header ).not.toMatch( /href:\s*'\/elsewhere\/?'/ );
  } );

  it( 'keeps Ritva, Puja Guidance and DIY Puja Kit in the intended menu order', () => {
    const header = read( 'src/components/Header.tsx' );
    expect( header.indexOf( "label: 'Ritva'" ) ).toBeGreaterThan( -1 );
    expect( header.indexOf( "label: 'Puja Guidance'" ) ).toBeGreaterThan( header.indexOf( "label: 'Ritva'" ) );
    expect( header.indexOf( "label: 'DIY Puja Kit'" ) ).toBeGreaterThan( header.indexOf( "label: 'Puja Guidance'" ) );
  } );
} );
