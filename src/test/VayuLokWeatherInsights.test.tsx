import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import VayuLokWeatherInsights from '../components/VayuLokWeatherInsights';

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
} );

describe( 'VayuLok Weather history public typography', () => {
  it( 'keeps location copy compact and the range selector neutral', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue(
      new Response( JSON.stringify( {
        ok: true,
        range: '30d',
        coverageStart: '2026-09-01T00:00:00Z',
        coverageEnd: '2026-10-01T00:00:00Z',
        gridDistanceKm: 5.46,
        sampleHours: 720,
        meanTemperatureC: 19.4,
        minTemperatureC: 14.2,
        maxTemperatureC: 24.9,
        precipitationMm: 142.3,
        meanHumidityPct: 78.1,
        monthly: [],
      } ), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      } ),
    ) );

    const { container } = render(
      <VayuLokWeatherInsights lat={ 25.5788 } lng={ 91.8933 } placeName="Shillong" />,
    );

    await waitFor( () => {
      expect( screen.getByText( 'Past weather for Shillong' ) ).toBeTruthy();
      expect( screen.getByText( /Grid 5\.46 km/ ) ).toBeTruthy();
    } );

    expect( container.textContent ).not.toContain( 'Shillong · past conditions' );

    const css = Array.from( container.querySelectorAll( 'style' ) )
      .map( style => style.textContent || '' )
      .join( '\n' );
    expect( css ).toContain( '.vl-wi-head p{margin:6px 0 0;color:var(--public-muted);font-size:var(--text-base);font-weight:600' );
    expect( css ).toContain( '.vl-wi-head p{font-size:var(--public-mobile-form-font-size);font-weight:600' );
    expect( css ).toContain( '.vl-wi-range button.is-active{background:rgba(17,21,18,.07);color:var(--public-heading)}' );
    expect( css ).not.toContain( '.vl-wi-range button:hover,.vl-wi-range button.is-active{background:var(--lime-tint)' );
    expect( css ).toContain( '.vl-wi-source{display:flex;flex-wrap:wrap;gap:0;margin-top:var(--space-2);color:var(--public-muted);font-size:var(--text-md)' );
    expect( css ).toContain( '.vl-wi-source{font-size:var(--text-md)}' );
  } );
} );
