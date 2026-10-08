import { describe, expect, it } from 'vitest';
import {
  NOT_OFFERED_SERVICE_VARIANT_IDS, SERVICE_CHOICES, SERVICES_CONFIGURED, SERVICES_CURRENCY,
  SERVICES_PRODUCT_ID, serviceByKind, serviceChoice,
} from '../config/services';
import { isServiceRefusal, SERVICE_REFUSAL_MESSAGES } from '../lib/serviceRequests';

describe( 'the services config', () => {
  it( 'declares the one product, INR, and exactly four offered services with NO price', () => {
    expect( SERVICES_PRODUCT_ID ).toBe( 'df976a0a-f582-4535-b2e1-d532f348bd27' );
    expect( SERVICES_CURRENCY ).toBe( 'INR' );
    expect( SERVICE_CHOICES.map( c => c.kind ) ).toEqual(
      [ 'SUBMIT_REQUEST', 'REQUEST_AMENDMENT', 'DROP_DOCS', 'VAULT' ] );
    // NO `rupees` AND NO `paise`, since 2026-10-08. Owner decision: a price must be changeable
    // in Wix with no deploy, so the only price a page shows is the live one it fetches. Asserted
    // on the objects themselves rather than only in the type, because a type error is not a
    // runtime guarantee and this file is also what `tests/test_service_requests.py` mirrors.
    for ( const choice of SERVICE_CHOICES )
    {
      expect( Object.keys( choice ).sort() ).toEqual(
        [ 'kind', 'label', 'needsTarget', 'path', 'slug', 'variantId' ] );
    }
    // The slug vocabulary is the key the live-price payload is read by. Four pages, four slugs.
    expect( SERVICE_CHOICES.map( c => c.slug ) ).toEqual(
      [ 'submit-request', 'request-amendment', 'drop-docs', 'vault' ] );
    expect( new Set( SERVICE_CHOICES.map( c => c.slug ) ).size ).toBe( 4 );
    // Each slug matches its own page path, so a card cannot request another page's price.
    for ( const choice of SERVICE_CHOICES )
    {
      expect( choice.path ).toBe( `/${ choice.slug }/` );
    }
    expect( SERVICES_CONFIGURED ).toBe( true );
  } );

  it( 'offers Drop Docs and Vault, both needing a target, neither carrying a price', () => {
    expect( NOT_OFFERED_SERVICE_VARIANT_IDS ).toHaveLength( 0 );
    expect( serviceByKind( 'DROP_DOCS' ) ).toMatchObject( {
      variantId: 'db166bc8-a763-41ec-9f65-0f718f18155a', label: 'Drop Docs',
      slug: 'drop-docs', path: '/drop-docs/', needsTarget: true,
    } );
    expect( serviceByKind( 'VAULT' ) ).toMatchObject( {
      variantId: 'dcff995e-448c-493a-9259-f6a82ccdc2b4', label: 'Vault',
      slug: 'vault', path: '/vault/', needsTarget: true,
    } );
    expect( serviceByKind( 'SUBMIT_REQUEST' )?.needsTarget ).toBe( false );
    expect( serviceByKind( 'REQUEST_AMENDMENT' )?.needsTarget ).toBe( true );
    // The allow-list is still closed: a fifth variant of the same product names nothing.
    expect( serviceChoice( 'db166bc8-a763-41ec-9f65-0f718f18155b' ) ).toBeNull();
    expect( serviceByKind( 'DROPDOCS' ) ).toBeNull();
  } );

  it( 'resolves by variant (case-insensitively) and by kind', () => {
    expect( serviceChoice( SERVICE_CHOICES[ 0 ].variantId.toUpperCase() )?.kind ).toBe( 'SUBMIT_REQUEST' );
    expect( serviceByKind( 'REQUEST_AMENDMENT' )?.path ).toBe( '/request-amendment/' );
  } );

  it( 'has one honest sentence per refusal code', () => {
    for ( const [ code, message ] of Object.entries( SERVICE_REFUSAL_MESSAGES ) )
    {
      expect( isServiceRefusal( code ) ).toBe( true );
      expect( message.endsWith( 'Nothing has been charged.' ) ).toBe( true );
    }
    expect( isServiceRefusal( 'CART_NOT_PAYABLE' ) ).toBe( false );
    expect( isServiceRefusal( 'toString' ) ).toBe( false );
  } );
} );
