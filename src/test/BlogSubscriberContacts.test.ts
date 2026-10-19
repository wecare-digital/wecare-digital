import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const contacts = readFileSync(
  join( __dirname, '..', 'pages', 'workspace', 'customers', 'index.tsx' ), 'utf8',
);
const client = readFileSync(
  join( __dirname, '..', 'api', 'client.ts' ), 'utf8',
);
const layout = readFileSync(
  join( __dirname, '..', 'styles', 'Layout.css' ), 'utf8',
);

describe( 'blog subscribers in Workspace Customers', () => {
  it( 'exposes the server verification timestamps through the Contact client model', () => {
    expect( client ).toContain( 'phoneVerifiedAt?: string' );
    expect( client ).toContain( 'emailVerifiedAt?: string' );
    expect( client ).toContain( 'blogSubscribedAt?: string' );
    expect( client ).toContain( 'phoneVerifiedAt: normalizeTimestamp( item.phoneVerifiedAt )' );
    expect( client ).toContain( 'emailVerifiedAt: normalizeTimestamp( item.emailVerifiedAt )' );
  } );

  it( 'renders human blog and verified-channel badges instead of exposing the raw tag only', () => {
    expect( contacts ).toContain( "'blog-subscriber': '#1a3a2a'" );
    expect( contacts ).toContain( "'Blog Subscriber'" );
    expect( contacts ).toContain( '✓ WhatsApp verified' );
    expect( contacts ).toContain( '✓ Email verified' );
  } );

  it( 'keeps mobile badges on one horizontally scrollable row', () => {
    const start = layout.indexOf( '.contact-card-tags {' );
    expect( start ).toBeGreaterThanOrEqual( 0 );
    const block = layout.slice( start, start + 420 );
    expect( block ).toContain( 'flex-wrap: nowrap' );
    expect( block ).toContain( 'overflow-x: auto' );
    expect( block ).toContain( 'overscroll-behavior-inline: contain' );
    expect( block ).toContain( 'flex: 0 0 auto' );
  } );
} );
