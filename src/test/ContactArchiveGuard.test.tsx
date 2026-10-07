/**
 * A SERVER REFUSAL MUST NOT DESTROY THE HISTORY IT WAS PROTECTING.
 *
 * `hardDeleteContact` used to react to a falsy `success` by calling `deleteContactMessages`
 * and then `deleteContact`. Read that against the new server guard: `core/contacts` answers
 * 409 precisely because the contact has a captured payment, and the client then deleted every
 * one of that contact's messages and soft-deleted the row anyway. The guard refused, and the
 * fallback carried out the damage the refusal existed to prevent.
 *
 * So the first two tests here are the ones that matter, and they assert on the REQUESTS the
 * client makes, not on its return value: a 409 must produce exactly one request. A test that
 * only checked the returned object would have passed against the old code too.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Pulled in for the Bearer token. Not under test, so it returns nothing and the client
// proceeds without an Authorization header (the CrmCheckoutAddress pattern).
vi.mock( 'aws-amplify/auth', () => ( {
  fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ),
} ) );

// Retries are real and would otherwise make a failing case sleep for seconds.
vi.mock( '../config/constants', async ( importOriginal ) => {
  const actual = await importOriginal<typeof import( '../config/constants' )>();
  return { ...actual, RETRY_CONFIG: { maxRetries: 2, baseDelayMs: 1, maxDelayMs: 2 } };
} );

import { hardDeleteContact } from '../api/client';

const CONTACT_ID = 'contact-1';

function jsonResponse ( body: unknown, status = 200 ): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

/** Every URL the client requested, in order. */
function requestedUrls (): string[] {
  return fetchMock.mock.calls.map( call => String( call[ 0 ] ) );
}

beforeEach( () => {
  fetchMock = vi.fn();
  vi.stubGlobal( 'fetch', fetchMock );
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
} );

describe( 'a refused hard delete', () => {
  it( 'does NOT go on to delete the messages — the defect this test exists for', async () => {
    fetchMock.mockResolvedValue( jsonResponse( {
      error: 'CONTACT_HAS_PAYMENTS',
      archiveInstead: true,
      reason: 'an invoice for this contact has reached or passed capture',
      signals: [ 'invoices' ],
    }, 409 ) );

    const result = await hardDeleteContact( CONTACT_ID );

    expect( result.ok ).toBe( false );
    // One request, and it is the delete that was refused. `deleteContactMessages` begins by
    // LISTING messages, so any `/messages` call here is the old fallback running.
    expect( requestedUrls() ).toHaveLength( 1 );
    expect( requestedUrls()[ 0 ] ).toContain( `/contacts/${CONTACT_ID}?hard=true` );
    expect( requestedUrls().some( url => url.includes( '/messages' ) ) ).toBe( false );
  } );

  it( 'does not soft-delete the row behind the operator either', async () => {
    // The old fallback finished with `deleteContact`, a second DELETE on the same contact
    // WITHOUT `?hard=true`. One request total is what rules that out.
    fetchMock.mockResolvedValue( jsonResponse(
      { error: 'CONTACT_HAS_PAYMENTS', archiveInstead: true }, 409 ) );

    await hardDeleteContact( CONTACT_ID );

    const softDeletes = requestedUrls().filter(
      url => url.includes( `/contacts/${CONTACT_ID}` ) && !url.includes( 'hard=true' ) );
    expect( softDeletes ).toEqual( [] );
  } );

  it( 'surfaces the archive-instead message so the UI can offer it', async () => {
    const reason = 'an order exists for this contact, and an order is only created after a verified payment';
    fetchMock.mockResolvedValue( jsonResponse(
      { error: 'CONTACT_HAS_PAYMENTS', archiveInstead: true, reason }, 409 ) );

    const result = await hardDeleteContact( CONTACT_ID );

    expect( result ).toEqual( {
      ok: false,
      code: 'CONTACT_HAS_PAYMENTS',
      reason,
      archiveInstead: true,
    } );
  } );

  it( 'keeps "cannot determine" distinct from "has payments"', async () => {
    // Two different sentences in front of an operator: one is "archive it", the other is
    // "this is also worth retrying". Collapsing them loses the retry.
    fetchMock.mockResolvedValue( jsonResponse( {
      error: 'PAYMENT_LINKAGE_UNKNOWN',
      archiveInstead: true,
      reason: 'the invoice linkage could not be read: ClientError',
    }, 409 ) );

    const result = await hardDeleteContact( CONTACT_ID );

    expect( result.ok ).toBe( false );
    if ( !result.ok ) expect( result.code ).toBe( 'PAYMENT_LINKAGE_UNKNOWN' );
  } );

  it( 'reports an unrecognised failure as ERROR rather than inventing a payment reason', async () => {
    fetchMock.mockResolvedValue( jsonResponse( { error: 'Contact not found' }, 404 ) );

    const result = await hardDeleteContact( CONTACT_ID );

    expect( result.ok ).toBe( false );
    if ( !result.ok )
    {
      expect( result.code ).toBe( 'ERROR' );
      expect( result.archiveInstead ).toBe( false );
    }
    expect( requestedUrls() ).toHaveLength( 1 );
  } );

  it( 'treats a thrown network error as ERROR and still deletes nothing', async () => {
    fetchMock.mockRejectedValue( new TypeError( 'Failed to fetch' ) );

    const result = await hardDeleteContact( CONTACT_ID );

    expect( result.ok ).toBe( false );
    if ( !result.ok ) expect( result.code ).toBe( 'ERROR' );
    expect( requestedUrls().some( url => url.includes( '/messages' ) ) ).toBe( false );
  } );
} );

describe( 'a permitted hard delete', () => {
  it( 'still reports what it removed, so the guard narrows the delete without removing it', async () => {
    fetchMock.mockResolvedValue( jsonResponse( {
      success: true,
      contactId: CONTACT_ID,
      deleteType: 'hard',
      messagesDeleted: 3,
      mediaDeleted: 1,
    } ) );

    const result = await hardDeleteContact( CONTACT_ID );

    expect( result ).toEqual( { ok: true, messagesDeleted: 3, mediaDeleted: 1 } );
    expect( requestedUrls() ).toEqual( [
      expect.stringContaining( `/contacts/${CONTACT_ID}?hard=true` ),
    ] );
  } );

  it( 'counts a 200 with no success flag as a refusal, not a success', async () => {
    // The old code reached its destructive fallback on exactly this shape. It must now be a
    // plain refusal: nothing is deleted and nothing is claimed.
    fetchMock.mockResolvedValue( jsonResponse( {} ) );

    const result = await hardDeleteContact( CONTACT_ID );

    expect( result.ok ).toBe( false );
    expect( requestedUrls() ).toHaveLength( 1 );
  } );
} );
