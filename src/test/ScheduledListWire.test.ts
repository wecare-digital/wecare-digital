import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock( 'aws-amplify/auth', () => ( { fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ) } ) );
vi.mock( '../config/constants', async importOriginal => {
  const actual = await importOriginal<typeof import( '../config/constants' )>();
  return { ...actual, API_BASE: 'https://api.example.test', RETRY_CONFIG: { maxRetries: 0, baseDelayMs: 1, maxDelayMs: 1 } };
} );
import { listScheduledMessages } from '../api/client';
afterEach( () => vi.unstubAllGlobals() );
describe( 'scheduled list preserves the deployed filter contract', () => {
  it.each( [ [ undefined, null ], [ '', '' ], [ 'DISPATCH_UNKNOWN', 'DISPATCH_UNKNOWN' ] ] )( 'preserves filter %s', async ( status, expected ) => {
    const transport = vi.fn().mockResolvedValue( { ok: true, status: 200, json: async () => ( { scheduledMessages: [] } ) } );
    vi.stubGlobal( 'fetch', transport );
    expect( await listScheduledMessages( status as string | undefined ) ).toEqual( [] );
    expect( new URL( transport.mock.calls[ 0 ][ 0 ] ).searchParams.get( 'status' ) ).toBe( expected );
  } );
  it( 'preserves explicit dispatch-review state rather than defaulting it to pending', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: true, status: 200, json: async () => ( { scheduledMessages: [ { id: 'fixture', status: 'DISPATCH_UNKNOWN' } ] } ) } ) );
    expect( ( await listScheduledMessages( '' ) )[ 0 ].status ).toBe( 'DISPATCH_UNKNOWN' );
  } );
  it.each( [ [ false, 503, {} ], [ true, 200, {} ], [ true, 200, { scheduledMessages: {} } ] ] )( 'does not turn failed or malformed list evidence into an empty queue', async ( ok, status, body ) => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok, status, json: async () => body } ) );
    await expect( listScheduledMessages( '' ) ).rejects.toThrow( 'Scheduled messages are unavailable' );
  } );
} );
