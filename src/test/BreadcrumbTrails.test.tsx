import React from 'react';
import fs from 'fs';
import path from 'path';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import PageShell from '../components/public/PageShell';
import Breadcrumbs from '../components/Breadcrumbs';

vi.mock( 'next/head', () => ( { default: ( { children }: { children: React.ReactNode } ) => <>{ children }</> } ) );

const ROOT = path.resolve( __dirname, '..', '..' );

describe( 'public breadcrumb policy', () => {
  it( 'keeps the compatibility component visually empty', () => {
    const { container } = render(
      <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Page' } ] } />
    );
    expect( container.querySelector( 'nav[aria-label="Breadcrumb"]' ) ).toBeNull();
  } );

  it( 'keeps PageShell free of visible or structured breadcrumbs', () => {
    const { container } = render(
      <PageShell
        title="Anew"
        description="Reflect on a decision."
        canonical="/anew/"
        crumbs={ [ { name: 'Home', href: '/' }, { name: 'Anew' } ] }
      >
        <p>Page content</p>
      </PageShell>
    );
    expect( container.querySelector( 'nav[aria-label="Breadcrumb"]' ) ).toBeNull();
    expect( container.querySelector( 'script[type="application/ld+json"]' ) ).toBeNull();
  } );

  it( 'keeps workspace breadcrumbs separate from the retired public component', () => {
    const publicSource = fs.readFileSync( path.join( ROOT, 'src', 'components', 'Breadcrumbs.tsx' ), 'utf8' );
    const workspaceSource = fs.readFileSync( path.join( ROOT, 'src', 'components', 'ui', 'Breadcrumbs.tsx' ), 'utf8' );
    expect( publicSource ).toContain( '=> null' );
    expect( workspaceSource ).toContain( 'useRouter' );
    expect( workspaceSource ).toContain( 'breadcrumbs-list' );
  } );
} );
