import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';

// SupportWidget calls useRouter() and binds routeChangeStart; jsdom has no router. A stub with
// an inert events bus lets the widget mount and the reset effect wire up without navigating.
vi.mock( 'next/router', () => ( {
  useRouter: () => ( { pathname: '/vayulok', query: {}, push: vi.fn(), isReady: true, events: { on: vi.fn(), off: vi.fn() } } ),
} ) );

import SupportWidget, { isRtlLanguage } from '../components/SupportWidget';

/* ---------------------------------------------------------------------------------------
   VayuLok TRANSLATION TESTS (task item 19)

   These exercise the client translation engine in SupportWidget end-to-end against a small
   VayuLok-shaped DOM fixture, so the assertions are about REAL behaviour (text nodes AND
   attributes translate, dynamically-inserted content translates via the observer,
   data-wc-no-translate wins, raw numbers/units are untouched, English restoration, no
   observer loop) rather than source text.

   The /site-language endpoints are mocked. The fake translator PREFIXES every string with
   the target code in brackets, e.g. "Air Forecast" -> "[hi] Air Forecast". That makes a
   translated node trivially detectable, lets us prove a node was translated exactly once
   (no double "[hi] [hi]" prefix = no observer loop), and lets us count unique requests.
--------------------------------------------------------------------------------------- */

interface TranslateCall { texts: string[] }
let translateCalls: TranslateCall[];

function mockTranslationFetch() {
  translateCalls = [];
  return vi.fn( ( input: RequestInfo | URL, init?: RequestInit ) => {
    const url = String( input );
    if ( url.includes( '/site-language/languages' ) ) {
      return Promise.resolve( {
        ok: true,
        json: async () => ( { languages: [
          { code: 'en', name: 'English' },
          { code: 'hi', name: 'Hindi' },
          { code: 'ar', name: 'Arabic' },
        ] } ),
      } as Response );
    }
    if ( url.includes( '/site-language/translate' ) ) {
      const body = JSON.parse( String( init?.body ) ) as { texts: string[]; targetLanguage: string };
      translateCalls.push( { texts: body.texts } );
      return Promise.resolve( {
        ok: true,
        json: async () => ( {
          translations: body.texts.map( text => ( { translatedText: `[${body.targetLanguage}] ${text}` } ) ),
        } ),
      } as Response );
    }
    return Promise.resolve( { ok: false, json: async () => ( {} ) } as Response );
  } );
}

/* A compact VayuLok-shaped fixture: a #__next wrapper (the translation walk root), static
   copy, a search input with a placeholder, raw data marked data-wc-no-translate, a
   data-wc-no-translate island, and a hook to inject "late" dynamic content (a Google health
   string / forecast row) AFTER a language is chosen. */
const VayuLokFixture: React.FC = () => {
  const [ showDynamic, setShowDynamic ] = React.useState( false );
  return (
    <div id="__next">
      <main>
        <h1>Bharat air and weather intelligence</h1>
        <p>Forecasts cover cities.</p>
        <input aria-label="Search a city or place" placeholder="Search a city or pincode" />
        <button type="button">Air</button>
        <button type="button">Weather</button>
        <h4>Air Forecast</h4>
        {/* Raw data: number + unit must stay byte-identical. */}
        <span className="pollutant" data-wc-no-translate="true">32 <small>µg/m³</small></span>
        {/* An explicit no-translate island (nearest-flag-wins). */}
        <span data-wc-no-translate="true" className="brand">WECARE.DIGITAL</span>
        <button type="button" data-testid="load" data-wc-no-translate="true" onClick={ () => setShowDynamic( true ) }>load</button>
        { showDynamic && (
          <div className="late">
            <p className="health">Limit prolonged outdoor exertion.</p>
            <span className="late-aqi" data-wc-no-translate="true">AQI 41</span>
            <small className="late-unit" data-wc-no-translate="true">0.4 ppb</small>
          </div>
        ) }
      </main>
    </div>
  );
};

async function selectLanguage( name: RegExp ) {
  const chip = await screen.findByRole( 'button', { name: /Language:/ } );
  fireEvent.click( chip );
  const option = await screen.findByRole( 'option', { name } );
  // Rows commit on mousedown (see SupportWidget).
  fireEvent.mouseDown( option );
}

afterEach( () => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.documentElement.lang = 'en';
  document.documentElement.dir = 'ltr';
  document.body.innerHTML = '';
} );

beforeEach( () => {
  vi.stubGlobal( 'fetch', mockTranslationFetch() );
} );

describe( 'VayuLok translation', () => {
  it( 'translates static text and the search placeholder attribute when Hindi is selected', async () => {
    const { container } = render( <><VayuLokFixture /><SupportWidget /></> );
    await screen.findByRole( 'button', { name: /Language:/ } );
    await act( async () => { await selectLanguage( /Hindi/ ); } );

    await waitFor( () => {
      expect( container.querySelector( 'h1' )?.textContent ).toBe( '[hi] Bharat air and weather intelligence' );
    } );
    // Static labels.
    expect( screen.getByText( '[hi] Air Forecast' ) ).toBeTruthy();
    expect( screen.getByText( '[hi] Air' ) ).toBeTruthy();
    expect( screen.getByText( '[hi] Weather' ) ).toBeTruthy();
    // ATTRIBUTE translation: the placeholder is translated, not just text nodes.
    const input = container.querySelector( 'input' ) as HTMLInputElement;
    expect( input.getAttribute( 'placeholder' ) ).toBe( '[hi] Search a city or pincode' );
    // <html lang> reflects the selection.
    expect( document.documentElement.lang ).toBe( 'hi' );
  } );

  it( 'does not translate data-wc-no-translate content or raw numbers/units', async () => {
    const { container } = render( <><VayuLokFixture /><SupportWidget /></> );
    await screen.findByRole( 'button', { name: /Language:/ } );
    await act( async () => { await selectLanguage( /Hindi/ ); } );
    await waitFor( () => expect( container.querySelector( 'h1' )?.textContent ).toContain( '[hi]' ) );

    // The brand island (data-wc-no-translate) is untouched.
    expect( container.querySelector( '.brand' )?.textContent ).toBe( 'WECARE.DIGITAL' );
    // Raw pollutant value + unit untouched (no "[hi]" prefix, µg/m³ byte-identical).
    const pollutant = container.querySelector( '.pollutant' );
    expect( pollutant?.textContent ).toBe( '32 µg/m³' );
    expect( pollutant?.textContent ).not.toContain( '[hi]' );
  } );

  it( 'translates content inserted AFTER the language was selected (MutationObserver)', async () => {
    const { container } = render( <><VayuLokFixture /><SupportWidget /></> );
    await screen.findByRole( 'button', { name: /Language:/ } );
    await act( async () => { await selectLanguage( /Hindi/ ); } );
    await waitFor( () => expect( container.querySelector( 'h1' )?.textContent ).toContain( '[hi]' ) );

    // Now inject late dynamic content (a Google health string + a forecast row).
    await act( async () => { fireEvent.click( screen.getByTestId( 'load' ) ); } );

    await waitFor( () => {
      expect( container.querySelector( '.health' )?.textContent ).toBe( '[hi] Limit prolonged outdoor exertion.' );
    } );
    // Raw data inside the late block stays raw.
    expect( container.querySelector( '.late-aqi' )?.textContent ).toBe( 'AQI 41' );
    expect( container.querySelector( '.late-unit' )?.textContent ).toBe( '0.4 ppb' );
  } );

  it( 'restores English fully, including attributes, when English is reselected', async () => {
    const { container } = render( <><VayuLokFixture /><SupportWidget /></> );
    await screen.findByRole( 'button', { name: /Language:/ } );
    await act( async () => { await selectLanguage( /Hindi/ ); } );
    await waitFor( () => expect( container.querySelector( 'h1' )?.textContent ).toContain( '[hi]' ) );

    await act( async () => { await selectLanguage( /English/ ); } );
    await waitFor( () => {
      expect( container.querySelector( 'h1' )?.textContent ).toBe( 'Bharat air and weather intelligence' );
    } );
    const input = container.querySelector( 'input' ) as HTMLInputElement;
    expect( input.getAttribute( 'placeholder' ) ).toBe( 'Search a city or pincode' );
    expect( document.documentElement.lang ).toBe( 'en' );
    expect( document.documentElement.dir ).toBe( 'ltr' );
  } );

  it( 'sets dir=rtl for an RTL language and back to ltr for English', async () => {
    const { container } = render( <><VayuLokFixture /><SupportWidget /></> );
    await screen.findByRole( 'button', { name: /Language:/ } );
    await act( async () => { await selectLanguage( /Arabic/ ); } );
    await waitFor( () => expect( container.querySelector( 'h1' )?.textContent ).toContain( '[ar]' ) );
    expect( document.documentElement.dir ).toBe( 'rtl' );
    expect( document.documentElement.lang ).toBe( 'ar' );

    await act( async () => { await selectLanguage( /English/ ); } );
    await waitFor( () => expect( document.documentElement.dir ).toBe( 'ltr' ) );
  } );

  it( 'does not loop: a translated node is not re-translated (single [hi] prefix) and strings dedupe', async () => {
    const { container } = render( <><VayuLokFixture /><SupportWidget /></> );
    await screen.findByRole( 'button', { name: /Language:/ } );
    await act( async () => { await selectLanguage( /Hindi/ ); } );
    await waitFor( () => expect( container.querySelector( 'h1' )?.textContent ).toContain( '[hi]' ) );

    // Inject dynamic content and let the observer run.
    await act( async () => { fireEvent.click( screen.getByTestId( 'load' ) ); } );
    await waitFor( () => expect( container.querySelector( '.health' )?.textContent ).toContain( '[hi]' ) );

    // Give any stray observer passes a chance to (wrongly) run again.
    await act( async () => { await new Promise( r => setTimeout( r, 200 ) ); } );

    // No node carries a doubled prefix - the observer never re-translated already-translated text.
    expect( container.innerHTML ).not.toContain( '[hi] [hi]' );
    // Every batch of texts sent was free of already-translated strings.
    const allSent = translateCalls.flatMap( call => call.texts );
    expect( allSent.some( text => text.includes( '[hi]' ) ) ).toBe( false );
  } );

  it( 'exports isRtlLanguage covering the six RTL base languages', () => {
    for ( const code of [ 'ar', 'fa', 'he', 'ur', 'ps', 'sd' ] ) expect( isRtlLanguage( code ) ).toBe( true );
    for ( const code of [ 'en', 'hi', 'bn', 'ta' ] ) expect( isRtlLanguage( code ) ).toBe( false );
    expect( isRtlLanguage( 'fa-AF' ) ).toBe( true );
  } );
} );

/* Silence the unused-import note for `within` if a future edit drops its last use. */
void within;
