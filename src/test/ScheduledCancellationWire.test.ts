import { describe, it, expect, vi, afterEach } from 'vitest';
vi.mock( 'aws-amplify/auth', () => ( {
  fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ),
} ) );
vi.mock( '../config/constants', async importOriginal => {
  const actual = await importOriginal<typeof import( '../config/constants' )>();
  return { ...actual, API_BASE: 'https://api.example.test' };
} );
import { cancelScheduledMessage } from '../api/client';
afterEach( () => vi.unstubAllGlobals() );
describe( 'scheduled cancellation uses the deployed API contract', () => {
  it( 'addresses the existing DELETE route and preserves the complete id', async () => {
    const transport = vi.fn().mockResolvedValue( {
      ok: true, status: 200, json: async () => ( { success: true } ),
    } );
    vi.stubGlobal( 'fetch', transport );
    expect( await cancelScheduledMessage( 'schedule/with ?reserved&characters' ) ).toBe( true );
    const [ request, options ] = transport.mock.calls[ 0 ];
    const url = new URL( request );
    expect( url.pathname ).toBe( '/scheduled' );
    expect( url.searchParams.get( 'scheduledId' ) ).toBe( 'schedule/with ?reserved&characters' );
    expect( options.method ).toBe( 'DELETE' );
  } );
  it.each( [ { success: false }, {} ] )( 'does not claim cancellation from a non-success response %o', async body => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( {
      ok: true, status: 200, json: async () => body,
    } ) );
    expect( await cancelScheduledMessage( 'schedule-1' ) ).toBe( false );
  } );
} );
