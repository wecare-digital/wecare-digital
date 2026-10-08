import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock( 'aws-amplify/auth', () => ( { fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ) } ) );
vi.mock( '../config/constants', async importOriginal => {
  const actual = await importOriginal<typeof import( '../config/constants' )>();
  return { ...actual, RETRY_CONFIG: { maxRetries: 0, baseDelayMs: 1, maxDelayMs: 1 } };
} );
import { getSystemHealth } from '../api/client';
afterEach( () => vi.unstubAllGlobals() );
describe( 'health never invents successful service evidence', () => {
  it( 'keeps failed reads unknown and services in warning', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockResolvedValue( { ok: false, status: 503, json: async () => ( {} ) } ) );
    const result = await getSystemHealth();
    expect( result.whatsapp ).toEqual( { status: 'warning', phoneNumbers: null, qualityRating: 'UNKNOWN' } );
    expect( result.email.verified ).toBeNull();
    expect( result.sms ).toEqual( { status: 'warning', poolId: '' } );
    expect( result.ai ).toEqual( { status: 'warning' } );
    expect( result.dlq.depth ).toBeNull();
  } );
  it( 'preserves real zero counts without inventing registered phones', async () => {
    vi.stubGlobal( 'fetch', vi.fn().mockImplementation( async ( url: string ) => ( {
      ok: true, status: 200,
      json: async () => url.endsWith( '/waba' ) ? { wabas: [] }
        : url.endsWith( '/dlq' ) ? { count: 0 } : {},
    } ) ) );
    const result = await getSystemHealth();
    expect( result.whatsapp.phoneNumbers ).toBe( 0 );
    expect( result.whatsapp.status ).toBe( 'warning' );
    expect( result.dlq.depth ).toBe( 0 );
    expect( result.ai.internalAgentAlias ).toBeUndefined();
  } );
} );
