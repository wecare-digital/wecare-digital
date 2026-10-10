import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SERVICE_CHOICES } from '../config/services';
import {
  SERVICE_PRICES_URL, SERVICES_PRICE_CURRENCY, allUnavailable, fetchServicePrices,
  rupeesFromPaise,
} from '../lib/servicePricing';

/**
 * The browser price client. Every case here is a FAIL-CLOSED case except the first: there is no
 * fallback figure anywhere in the module, so what is being pinned is that a bad answer becomes
 * "unavailable" rather than a number the checkout would refuse.
 */

const SLUGS = [
  'submit-request', 'request-amendment', 'drop-docs', 'vault', 'request-pickup',
] as const;

let requested: string[] = [];

function reply ( status: number, body: unknown ) {
  vi.stubGlobal( 'fetch', vi.fn( async ( url: string ) => {
    requested.push( String( url ) );
    return { ok: status < 400, status, json: async () => body };
  } ) );
}

function good ( overrides: Record<string, unknown> = {} ) {
  return {
    currency: 'INR',
    prices: {
      'submit-request': { available: true, paise: 14900 },
      'request-amendment': { available: true, paise: 20100 },
      'drop-docs': { available: true, paise: 45050 },
      'vault': { available: true, paise: 7700 },
      'request-pickup': { available: true, paise: 28800 },
      ...overrides,
    },
  };
}

beforeEach( () => { requested = []; } );
afterEach( () => { vi.unstubAllGlobals(); vi.restoreAllMocks(); } );

describe( 'fetchServicePrices', () => {
  it( 'reads all five slugs, as integer paise with a rupee face', async () => {
    reply( 200, good() );
    const prices = await fetchServicePrices();
    expect( requested ).toEqual( [ SERVICE_PRICES_URL ] );
    expect( prices ).toEqual( {
      'submit-request': { available: true, paise: 14900, rupees: '149' },
      'request-amendment': { available: true, paise: 20100, rupees: '201' },
      'drop-docs': { available: true, paise: 45050, rupees: '450.50' },
      'vault': { available: true, paise: 7700, rupees: '77' },
      'request-pickup': { available: true, paise: 28800, rupees: '288' },
    } );
  } );

  it( 'keeps five DIFFERENT prices different', async () => {
    reply( 200, good() );
    const prices = await fetchServicePrices();
    const faces = SLUGS.map( slug => {
      const price = prices[ slug ];
      return price.available ? price.rupees : '';
    } );
    expect( new Set( faces ).size ).toBe( 5 );
  } );

  it( 'preserves a PER-SLUG unavailable rather than widening it', async () => {
    reply( 200, good( { vault: { available: false } } ) );
    const prices = await fetchServicePrices();
    expect( prices.vault ).toEqual( { available: false } );
    expect( prices.vault ).not.toHaveProperty( 'paise' );
    expect( prices[ 'submit-request' ].available ).toBe( true );
    expect( prices[ 'drop-docs' ].available ).toBe( true );
  } );

  it( 'fails closed on a 503', async () => {
    reply( 503, { error: 'SERVICE_PRICES_UNAVAILABLE' } );
    expect( await fetchServicePrices() ).toEqual( allUnavailable() );
  } );

  it( 'fails closed when fetch throws', async () => {
    vi.stubGlobal( 'fetch', vi.fn( async () => { throw new Error( 'offline' ); } ) );
    expect( await fetchServicePrices() ).toEqual( allUnavailable() );
  } );

  it( 'fails closed on unparseable JSON', async () => {
    vi.stubGlobal( 'fetch', vi.fn( async () => ( {
      ok: true, status: 200, json: async () => { throw new Error( 'not json' ); },
    } ) ) );
    expect( await fetchServicePrices() ).toEqual( allUnavailable() );
  } );

  it.each( [ 'USD', 'inr', '', null, undefined, 1 ] )(
    'refuses a currency that is not exactly INR: %s', async currency => {
      reply( 200, { ...good(), currency } );
      expect( await fetchServicePrices() ).toEqual( allUnavailable() );
    } );

  it( 'compares the currency explicitly and never infers it from the amount', () => {
    expect( SERVICES_PRICE_CURRENCY ).toBe( 'INR' );
  } );

  it.each( [
    [ 'a fractional paise', { available: true, paise: 99.5 } ],
    [ 'a string paise', { available: true, paise: '9900' } ],
    [ 'zero', { available: true, paise: 0 } ],
    [ 'a negative', { available: true, paise: -9900 } ],
    [ 'an unsafe integer', { available: true, paise: Number.MAX_SAFE_INTEGER + 2 } ],
    [ 'NaN', { available: true, paise: Number.NaN } ],
    [ 'Infinity', { available: true, paise: Number.POSITIVE_INFINITY } ],
    [ 'a missing paise', { available: true } ],
    [ 'available as a string', { available: 'true', paise: 9900 } ],
    [ 'a null row', null ],
    [ 'a number instead of a row', 9900 ],
  ] )( 'refuses %s for that slug alone', async ( _label, row ) => {
    reply( 200, good( { 'submit-request': row } ) );
    const prices = await fetchServicePrices();
    expect( prices[ 'submit-request' ] ).toEqual( { available: false } );
    expect( prices.vault.available ).toBe( true );
  } );

  it( 'fails closed when `prices` is missing or not an object', async () => {
    for ( const prices of [ undefined, null, 'x', 7 ] )
    {
      reply( 200, { currency: 'INR', prices } );
      expect( await fetchServicePrices() ).toEqual( allUnavailable() );
    }
  } );

  it( 'reports a slug the server omitted as unavailable', async () => {
    const payload = good();
    delete ( payload.prices as Record<string, unknown> )[ 'drop-docs' ];
    reply( 200, payload );
    const prices = await fetchServicePrices();
    expect( prices[ 'drop-docs' ] ).toEqual( { available: false } );
    expect( Object.keys( prices ).sort() ).toEqual( [ ...SLUGS ].sort() );
  } );

  it( 'ignores a slug the server invented', async () => {
    reply( 200, good( { 'free-everything': { available: true, paise: 1 } } ) );
    expect( Object.keys( await fetchServicePrices() ).sort() ).toEqual( [ ...SLUGS ].sort() );
  } );

  it( 'GETs the one endpoint with no query string and no body', async () => {
    reply( 200, good() );
    await fetchServicePrices();
    const call = ( globalThis.fetch as unknown as { mock: { calls: unknown[][] } } ).mock.calls[ 0 ];
    expect( call[ 0 ] ).toBe( SERVICE_PRICES_URL );
    expect( String( call[ 0 ] ) ).not.toContain( '?' );
    expect( call[ 1 ] ).toEqual( { method: 'GET', headers: { Accept: 'application/json' } } );
  } );
} );

describe( 'rupeesFromPaise', () => {
  it( 'is integer division and modulo, with no float artefact', () => {
    expect( rupeesFromPaise( 4900 ) ).toBe( '49' );
    expect( rupeesFromPaise( 9900 ) ).toBe( '99' );
    expect( rupeesFromPaise( 35000 ) ).toBe( '350' );
    expect( rupeesFromPaise( 1 ) ).toBe( '0.01' );
    expect( rupeesFromPaise( 10 ) ).toBe( '0.10' );
    expect( rupeesFromPaise( 105 ) ).toBe( '1.05' );
    // 0.1 + 0.2 !== 0.3 in binary floating point; 10 + 20 paise is exactly 30.
    expect( rupeesFromPaise( 10 + 20 ) ).toBe( '0.30' );
  } );

  it( 'groups the rupee part Indian-style, as paymentVocabulary does', () => {
    // Newly reachable: the figure is Wix's now, and the catastrophe rail admits up to Rs.50,000,
    // which used to render as `50000`. The grouping is applied to the ALREADY TRUNCATED whole
    // rupees, so it is formatting rather than arithmetic.
    expect( rupeesFromPaise( 123450 ) ).toBe( '1,234.50' );
    expect( rupeesFromPaise( 5000000 ) ).toBe( '50,000' );
    expect( rupeesFromPaise( 100000000 ) ).toBe( '10,00,000' );
    expect( rupeesFromPaise( 1234567890 ) ).toBe( '1,23,45,678.90' );
  } );
} );

describe( 'the slug vocabulary has one owner', () => {
  it( 'derives allUnavailable from SERVICE_CHOICES rather than re-typing the slugs', () => {
    // It was a third hand-typed copy, after src/config/services.ts and the server's
    // SERVICE_KIND_BY_SLUG. Drift failed closed, so nothing would have broken loudly — a fifth
    // service would simply never have received a price and its page would have read
    // "temporarily unavailable" forever.
    expect( Object.keys( allUnavailable() ) )
      .toEqual( SERVICE_CHOICES.map( choice => choice.slug ) );
    expect( Object.values( allUnavailable() ) )
      .toEqual( SERVICE_CHOICES.map( () => ( { available: false } ) ) );
  } );

  it( 'prices exactly the slugs SERVICE_CHOICES declares, and no others', async () => {
    reply( 200, {
      currency: 'INR',
      prices: {
        ...Object.fromEntries(
          SERVICE_CHOICES.map( ( choice, index ) =>
            [ choice.slug, { available: true, paise: 10000 + index * 1100 } ] ) ),
        // A slug the build does not know about must not leak into the result.
        'not-a-service': { available: true, paise: 999999 },
      },
    } );
    const prices = await fetchServicePrices();
    expect( Object.keys( prices ) ).toEqual( SERVICE_CHOICES.map( choice => choice.slug ) );
    expect( Object.keys( prices ) ).not.toContain( 'not-a-service' );
  } );
} );
