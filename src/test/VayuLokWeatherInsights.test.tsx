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
      <VayuLokWeatherInsights
        lat={ 25.5788 }
        lng={ 91.8933 }
        placeName="Shillong"
        timeZoneId="Asia/Kolkata"
        zoneLabel="IST"
      />,
    );

    await waitFor( () => {
      expect( screen.getByText( 'Past weather for Shillong' ) ).toBeTruthy();
      expect( screen.getByLabelText( 'Weather history updated time' ) ).toBeTruthy();
    } );

    expect( container.textContent ).not.toContain( 'Grid 5.46 km' );
    expect( container.textContent ).not.toContain( 'Sep 2026–Oct 2026' );
    expect( container.textContent ).not.toContain( 'Shillong · past conditions' );
    expect( screen.getByLabelText( 'Weather history updated time' ).textContent ).toContain( 'IST' );

    const css = Array.from( container.querySelectorAll( 'style' ) )
      .map( style => style.textContent || '' )
      .join( '\n' );
    expect( css ).toContain( '.vl-wi-head p{margin:6px 0 0;color:var(--public-muted);font-size:var(--vl-subtext-size,var(--text-base));font-weight:600' );
    expect( css ).toContain( '.vl-wi-head p{font-size:var(--vl-subtext-size,var(--public-mobile-form-font-size));font-weight:600' );
    expect( css ).toContain( '.vl-wi-range button.is-active{background:rgba(17,21,18,.07);color:var(--public-heading)}' );
    expect( css ).not.toContain( '.vl-wi-range button:hover,.vl-wi-range button.is-active{background:var(--lime-tint)' );
    expect( css ).not.toContain( '.vl-wi-source{' );
    expect( css ).toContain( '.vl-wi-stamp{display:flex;width:fit-content;align-items:center;gap:6px' );
    expect( css ).toContain( 'font-size:var(--vl-meta-size,var(--text-md))' );
    expect( css ).toContain( '.vl-wi-grid strong{color:var(--public-heading);font-size:var(--vl-data-size,var(--public-cta-font-size))' );
  } );
} );
