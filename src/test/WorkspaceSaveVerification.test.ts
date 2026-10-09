import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock( 'aws-amplify/auth', () => ( {
  fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ),
} ) );
vi.mock( '../config/constants', async importOriginal => ( {
  ...await importOriginal<typeof import( '../config/constants' )>(),
  RETRY_CONFIG: { maxRetries: 0, baseDelayMs: 1, maxDelayMs: 1 },
} ) );
import { updateSystemConfig, getAWSBilling } from '../api/client';
const response = ( body: unknown, status = 200 ) => new Response( JSON.stringify( body ), { status } );
afterEach( () => vi.unstubAllGlobals() );

describe( 'settings success requires acknowledgement and persisted values', () => {
  it.each( [ {}, { success: false }, { error: 'refused' } ] )( 'rejects an unacknowledged write %o', async body => {
    const transport = vi.fn().mockResolvedValue( response( body ) );
    vi.stubGlobal( 'fetch', transport );
    expect( await updateSystemConfig( 'welcome_message', { enabled: true } ) ).toBe( false );
    expect( transport ).toHaveBeenCalledTimes( 1 );
  } );
  it( 'checks the requested key and values while retaining unrelated stored settings', async () => {
    const transport = vi.fn()
      .mockResolvedValueOnce( response( { success: true } ) )
      .mockResolvedValueOnce( response( { config: { enabled: true, menu: { labels: [ 'Help', 'Shop' ], retained: 1 }, other: 2 } } ) );
    vi.stubGlobal( 'fetch', transport );
    expect( await updateSystemConfig( 'key/with & spaces', { enabled: true, menu: { labels: [ 'Help', 'Shop' ] } } ) ).toBe( true );
    expect( new URL( transport.mock.calls[ 1 ][ 0 ] ).searchParams.get( 'key' ) ).toBe( 'key/with & spaces' );
    expect( transport.mock.calls[ 0 ][ 1 ].method ).toBe( 'PUT' );
  } );
  it.each( [
    { enabled: false, labels: [ 'Help', 'Shop' ] },
    { enabled: true, labels: [ 'Shop', 'Help' ] },
    { enabled: true, labels: [ 'Help', 'Shop', 'Extra' ] },
    null,
  ] )( 'rejects stale, different or absent read-back %o', async config => {
    vi.stubGlobal( 'fetch', vi.fn()
      .mockResolvedValueOnce( response( { success: true } ) )
      .mockResolvedValueOnce( response( { config } ) ) );
    expect( await updateSystemConfig( 'welcome_message', { enabled: true, labels: [ 'Help', 'Shop' ] } ) ).toBe( false );
  } );
  it( 'does not repeat a write when verification fails', async () => {
    const transport = vi.fn()
      .mockResolvedValueOnce( response( { success: true } ) )
      .mockResolvedValueOnce( response( {}, 500 ) );
    vi.stubGlobal( 'fetch', transport );
    expect( await updateSystemConfig( 'welcome_message', { enabled: true } ) ).toBe( false );
    expect( transport.mock.calls.filter( call => call[ 1 ]?.method === 'PUT' ) ).toHaveLength( 1 );
  } );
} );

describe( 'billing unavailable is not an estimated bill', () => {
  it.each( [ 403, 500, 503 ] )( 'reports unavailable for HTTP%s with no synthetic spend or time', async status => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( response( {}, status ) ) );
    const result = await getAWSBilling();
    expect( result ).toMatchObject( { unavailable: true, costReportingEnabled: false, services: [], period: '', lastUpdated: '' } );
    expect( result.note ).toContain( 'unavailable' );
  } );
  it( 'rejects malformed service data instead of supplying sample usage', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( response( { services: 'not a list' } ) ) );
    expect( ( await getAWSBilling() ).unavailable ).toBe( true );
  } );
} );
