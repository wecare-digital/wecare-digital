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
    expect( read( 'scripts/generate-sitemap.js' ) ).not.toMatch( /^\s*'\/elsewhere',?\s*$/m );

    const header = read( 'src/components/Header.tsx' );
    expect( header ).toContain( "label: 'Elsewhere'" );
    expect( header ).not.toMatch( /label:\s*'Elsewhere'[\s\S]{0,120}?href:/ );
  } );

  it( 'keeps Puja Guidance above DIY Puja Kit in the menu', () => {
    const header = read( 'src/components/Header.tsx' );
    expect( header.indexOf( "label: 'Puja Guidance'" ) ).toBeGreaterThan( -1 );
    expect( header.indexOf( "label: 'DIY Puja Kit'" ) ).toBeGreaterThan( header.indexOf( "label: 'Puja Guidance'" ) );
  } );
} );
