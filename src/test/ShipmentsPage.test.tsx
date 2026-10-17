import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import ShipmentTrackPage from '../pages/shipments/track';
import { SHIPMENT_TRACK } from '../content/shipments';
import { whatsappServiceLink } from '../config/whatsappServiceEntries';

vi.mock( 'next/router', () => ( {
  useRouter: () => ( { push: vi.fn().mockResolvedValue( true ) } ),
} ) );

describe( 'Shipments Track child page', () => {
  it( 'renders through the shared ProductPage shell', () => {
    const { container } = render( <ShipmentTrackPage /> );
    expect( container.querySelectorAll( 'h1' ) ).toHaveLength( 1 );
    expect( container.querySelectorAll( 'main' ) ).toHaveLength( 1 );
    expect( screen.getByText( 'Track by WECARE.DIGITAL' ) ).toBeInTheDocument();
  } );

  it( 'is tracking only, never the retired Shipments parent hub', () => {
    const { container } = render( <ShipmentTrackPage /> );
    expect( SHIPMENT_TRACK.slug ).toBe( 'shipments-track' );
    expect( SHIPMENT_TRACK.ctaLabel2 ).toBeUndefined();
    expect( SHIPMENT_TRACK.ctaHref2 ).toBeUndefined();
    expect( container.textContent ).not.toContain( 'Request pickup' );
    expect( container.textContent ).not.toContain( 'Everything about your' );
  } );

  it( 'keeps the tracking WhatsApp action and fresh checkout price', () => {
    render( <ShipmentTrackPage /> );
    expect( SHIPMENT_TRACK.ctaHref ).toBe( 'https://wa.me/message/WGN4NMFLFSJVB1' );
    expect( whatsappServiceLink( SHIPMENT_TRACK.slug ) ).toBe( SHIPMENT_TRACK.ctaHref );
    expect( screen.getByRole( 'link', { name: 'Track on WhatsApp' } ) )
      .toHaveAttribute( 'href', SHIPMENT_TRACK.ctaHref );
    expect( screen.getByRole( 'button', { name: 'Continue to checkout →' } ) ).toBeInTheDocument();
    expect( screen.getByText( '₹49.00' ) ).toBeInTheDocument();
  } );

  it( 'keeps the route thin and owns no chrome', () => {
    const src = readFileSync( join( process.cwd(), 'src/pages/shipments/track.tsx' ), 'utf8' );
    expect( src ).not.toMatch( /components\/(Header|Footer|SupportWidget|Layout)'/ );
    expect( src ).toContain( "from '../../components/ProductPage'" );
    expect( src ).toContain( 'canonicalPath="/shipments/track/"' );
  } );

  it( 'keeps the public metadata in step with the Track child', () => {
    const app = readFileSync( join( process.cwd(), 'src/pages/_app.tsx' ), 'utf8' );
    expect( app ).toContain( "'/shipments/track': { name: 'Track'" );
    expect( app ).not.toContain( "'/shipments': { name: 'Shipments'" );
  } );
} );
