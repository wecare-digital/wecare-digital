import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
const TEST_INSIGHTS_URL = 'https://weather-insights.test';

async function loadComponent() {
  vi.resetModules();
  vi.stubEnv( 'NEXT_PUBLIC_VAYULOK_WEATHER_INSIGHTS_URL', TEST_INSIGHTS_URL );
  return ( await import( '../components/VayuLokWeatherInsights' ) ).default;
}

afterEach( () => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
} );

describe( 'VayuLok Weather history public typography', () => {
  it( 'keeps location copy compact and the range selector on the VayuLok lime interaction language', async () => {
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

    const VayuLokWeatherInsights = await loadComponent();
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
    const historyStampText = screen.getByLabelText( 'Weather history updated time' ).textContent || '';
    expect( historyStampText ).toContain( 'IST' );
    expect( historyStampText ).not.toMatch( /\b\d{4}\b/ );
    expect( historyStampText ).not.toMatch( /\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/ );

    const css = Array.from( container.querySelectorAll( 'style' ) )
      .map( style => style.textContent || '' )
      .join( '\n' );
    expect( css ).toContain( '.vl-wi-head p{margin:6px 0 0;color:var(--public-muted);font-size:var(--vl-subtext-size,var(--public-supporting-size));font-weight:600' );
    expect( css ).toContain( '.vl-wi-head p{font-size:var(--vl-subtext-size,var(--public-supporting-size));font-weight:600' );
    expect( css ).toContain( '.vl-ui-compact-pill:hover{border-color:var(--lime,var(--public-brand-lime));background:var(--lime-tint,var(--public-lime-tint))}' );
    expect( css ).toContain( '.vl-ui-compact-pill.is-active{border-color:var(--lime,var(--public-brand-lime));background:var(--lime,var(--public-brand-lime));color:var(--green,var(--public-brand-green))}' );
    expect( container.querySelector( '.vl-ui-section-heading' ) ).not.toBeNull();
    expect( container.querySelector( '.vl-ui-compact-pill' ) ).not.toBeNull();
    expect( container.querySelector( '.vl-ui-freshness-stamp' ) ).not.toBeNull();
    expect( css ).not.toContain( 'background:rgba(17,21,18,.07)' );
    expect( css ).not.toContain( '.vl-wi-source{' );
    expect( css ).toContain( '.vl-wi-stamp{display:flex;width:fit-content;align-items:center;gap:6px' );
    expect( css ).toContain( 'font-size:var(--vl-meta-size,var(--public-meta-size))' );
    expect( css ).toContain( '.vl-wi-grid strong{color:var(--public-heading);font-size:var(--vl-data-size,var(--public-cta-font-size))' );
    expect( css ).toContain( '.vl-wi-head h4{margin:0;color:var(--public-heading);font-size:var(--vl-panel-heading-size,var(--public-data-size))' );
    expect( css ).toContain( '.vl-wi-bar-slot strong{font-size:var(--vl-meta-size,var(--public-meta-size))' );
    expect( css ).not.toContain( 'font-size:var(--text-' );
    expect( css ).not.toMatch( /font-size:\s*(?:\d|\.\d)/ );
    expect( container.textContent ).not.toContain( 'Loading history…' );
    expect( css ).toContain( '.vl-wi-sr{position:absolute!important;width:1px!important;height:1px!important' );
  } );

  it( 'formats the history freshness stamp cleanly when a timezone label is not yet available', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue(
      new Response( JSON.stringify( {
        ok: true,
        range: '30d',
        sampleHours: 24,
        monthly: [],
      } ), { status: 200, headers: { 'Content-Type': 'application/json' } } ),
    ) );

    const VayuLokWeatherInsights = await loadComponent();
    render(
      <VayuLokWeatherInsights
        lat={ 25.5788 }
        lng={ 91.8933 }
        placeName="Shillong"
        timeZoneId="Asia/Kolkata"
        zoneLabel=""
      />,
    );

    const stamp = await screen.findByLabelText( 'Weather history updated time' );
    expect( stamp.textContent ).not.toMatch( /\s$/ );
    expect( stamp.textContent ).not.toContain( 'undefined' );
  } );

  it( 'labels the five-year chart as a month-of-year aggregate rather than a 60-month timeline', async () => {
    const fetchSpy = vi.fn().mockImplementation( ( input: RequestInfo | URL ) => {
      const url = new URL( String( input ) );
      const range = url.searchParams.get( 'range' ) || '30d';
      return Promise.resolve( new Response( JSON.stringify( {
        ok: true,
        range,
        sampleHours: range === '5y' ? 43800 : 720,
        meanTemperatureC: 20,
        minTemperatureC: 12,
        maxTemperatureC: 29,
        precipitationMm: 100,
        meanHumidityPct: 70,
        monthly: [
          { month: 1, meanTemperatureC: 16 },
          { month: 2, meanTemperatureC: 18 },
          { month: 3, meanTemperatureC: 21 },
        ],
      } ), { status: 200, headers: { 'Content-Type': 'application/json' } } ) );
    } );
    vi.stubGlobal( 'fetch', fetchSpy );

    const VayuLokWeatherInsights = await loadComponent();
    render(
      <VayuLokWeatherInsights
        lat={ 25.5788 }
        lng={ 91.8933 }
        placeName="Shillong"
        timeZoneId="Asia/Kolkata"
        zoneLabel="IST"
      />,
    );

    fireEvent.click( await screen.findByRole( 'button', { name: '5Y' } ) );
    await waitFor( () => {
      expect( screen.getByText( '5-year monthly pattern' ) ).toBeTruthy();
      expect( screen.getByText( 'Average by calendar month' ) ).toBeTruthy();
    } );
    expect( screen.queryByText( 'Monthly temp' ) ).toBeNull();
  } );
} );
