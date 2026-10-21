import React from 'react';
import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import Breadcrumbs from '../components/Breadcrumbs';

const ROOT = path.resolve( __dirname, '..', '..' );
const APP = fs.readFileSync( path.join( ROOT, 'src', 'pages', '_app.tsx' ), 'utf8' );

describe( 'public breadcrumb retirement', () => {
  it( 'renders no public breadcrumb markup', () => {
    const { container } = render(
      <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Example' } ] } />
    );
    expect( container ).toBeEmptyDOMElement();
    expect( container.querySelector( 'nav[aria-label="Breadcrumb"]' ) ).toBeNull();
  } );

  it( 'does not emit a sitewide public BreadcrumbList from _app', () => {
    expect( APP ).not.toContain( 'key="public-breadcrumbs"' );
    expect( APP ).not.toContain( "import { breadcrumbSchema } from '../lib/breadcrumbs';" );
    expect( APP ).not.toContain( "import { breadcrumbTrail } from '../content/breadcrumbTrails';" );
  } );
} );
