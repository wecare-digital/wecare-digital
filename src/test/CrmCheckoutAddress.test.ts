/**
 * THE CHECKOUT DELIVERY ADDRESS HAS TO SURVIVE THE CLIENT MAPPER.
 *
 * `auth/customer-profile` writes `checkoutDeliveryAddress` (a Map) and `checkoutAddressUpdatedAt`
 * (epoch seconds) onto the same ContactsTable row the CRM displays, and `core/contacts` returns
 * the whole item - there is no `ProjectionExpression` on any contact read. So the attribute was
 * already arriving at the browser. It still did not render, because `normalizeContact` in
 * `src/api/client.ts` is a CLOSED field-by-field object literal with no spread of `item`, and
 * every contact read funnels through it: `listContacts`, `getContact`, `createContact`,
 * `updateContact`.
 *
 * The first attempt at this fix added both fields to the `Contact` interface and nothing to the
 * mapper. `tsc --noEmit` passed because both fields are optional; the guard test passed because
 * it only asked whether the string `checkoutDeliveryAddress` appeared anywhere in `client.ts`,
 * which the type declaration satisfies. Green suite, dead feature - the same
 * substitute-does-not-enforce-the-real-constraint blind spot that produced the OTP reserved-word
 * defect this branch exists to fix.
 *
 * These tests therefore drive the REAL `listContacts` and `getContact` against a stubbed `fetch`
 * and read the field off the result. A source-text assertion cannot be the only guard here,
 * because the thing that failed was the data path, not the spelling.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Pulled in by the client for the Bearer token. Not what is under test, so it returns nothing
// and the client proceeds without an Authorization header (the ApiFailureChannel pattern).
vi.mock( 'aws-amplify/auth', () => ( {
  fetchAuthSession: vi.fn().mockResolvedValue( { tokens: undefined } ),
} ) );

// Retries are real and would otherwise make a failing case sleep for seconds.
vi.mock( '../config/constants', async ( importOriginal ) => {
  const actual = await importOriginal<typeof import( '../config/constants' )>();
  return { ...actual, RETRY_CONFIG: { maxRetries: 2, baseDelayMs: 1, maxDelayMs: 2 } };
} );

import { listContacts, getContact } from '../api/client';

/** Exactly what `contact_address.normalize_for_storage` stores, `fullAddress` included. */
const STORED_ADDRESS = {
  addressLine1: '12 Dalhousie Square',
  addressLine2: 'Flat 3B',
  locality: '',
  city: 'Kolkata',
  state: 'West Bengal',
  postalCode: '700001',
  country: 'India',
  countryCode: 'IN',
  fullAddress: '12 Dalhousie Square, Flat 3B, Kolkata, West Bengal, 700001, India',
};

const ROW = {
  id: 'contact-1',
  contactId: 'contact-1',
  name: 'Asha Sen',
  phone: '+918100640044',
  email: 'asha@example.com',
  checkoutDeliveryAddress: STORED_ADDRESS,
  checkoutAddressUpdatedAt: 1700000000,
  createdAt: 1700000000,
  updatedAt: 1700000000,
};

function jsonResponse ( body: unknown, status = 200 ): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach( () => {
  fetchMock = vi.fn();
  vi.stubGlobal( 'fetch', fetchMock );
} );

afterEach( () => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
} );

describe( 'the checkout delivery address through the contacts client', () => {
  it( 'arrives on a listed contact, whole, with the stamp', async () => {
    fetchMock.mockResolvedValue( jsonResponse( { contacts: [ ROW ] } ) );

    const [ contact ] = await listContacts();

    expect( contact.checkoutDeliveryAddress ).toEqual( STORED_ADDRESS );
    expect( contact.checkoutAddressUpdatedAt ).toBe( 1700000000 );
  } );

  it( 'arrives on a single contact read too, since both map through normalizeContact', async () => {
    fetchMock.mockResolvedValue( jsonResponse( { contact: ROW } ) );

    const contact = await getContact( 'contact-1' );

    expect( contact?.checkoutDeliveryAddress?.city ).toBe( 'Kolkata' );
    expect( contact?.checkoutDeliveryAddress?.postalCode ).toBe( '700001' );
  } );

  it( 'keeps `fullAddress`, which no second whitelist here is allowed to drop', async () => {
    // Carried through whole rather than rebuilt field by field, deliberately: a closed mapper at
    // this layer would be a SECOND place to forget a field, which is the exact failure being
    // fixed. The page's `formatCheckoutAddress` builds its line from the components and does its
    // own coercion, so nothing depends on the shape being narrowed here.
    fetchMock.mockResolvedValue( jsonResponse( { contacts: [ ROW ] } ) );

    const [ contact ] = await listContacts();

    expect( ( contact.checkoutDeliveryAddress as Record<string, unknown> ).fullAddress )
      .toBe( STORED_ADDRESS.fullAddress );
  } );

  it( 'leaves a contact that never checked out undefined, not an empty object', async () => {
    // `formatCheckoutAddress` returns '' on an absent address so the page's existing
    // `value || '—'` renders the same dash every other empty field renders. An `{}` would be
    // truthy and would defeat nothing here, but `undefined` keeps "no address" one value.
    fetchMock.mockResolvedValue( jsonResponse( {
      contacts: [ { ...ROW, checkoutDeliveryAddress: undefined, checkoutAddressUpdatedAt: undefined } ],
    } ) );

    const [ contact ] = await listContacts();

    expect( contact.checkoutDeliveryAddress ).toBeUndefined();
    expect( contact.checkoutAddressUpdatedAt ).toBeUndefined();
  } );

  it( 'refuses the shapes that would render as a 1970 date or a dict of indices', async () => {
    // Server data, so the mapper has to survive a legacy or hand-edited row. `Number(null)` and
    // `Number('')` are both 0, which `timeAgo` would print as 1 January 1970; an array is
    // `typeof 'object'` and would reach `formatCheckoutAddress` as numeric keys.
    fetchMock.mockResolvedValue( jsonResponse( {
      contacts: [ { ...ROW, checkoutDeliveryAddress: [ 'x' ], checkoutAddressUpdatedAt: null } ],
    } ) );

    const [ contact ] = await listContacts();

    expect( contact.checkoutDeliveryAddress ).toBeUndefined();
    expect( contact.checkoutAddressUpdatedAt ).toBeUndefined();
  } );
} );
