import { describe, expect, it } from 'vitest';
import {
  NOT_OFFERED_SERVICE_VARIANT_IDS, SERVICE_CHOICES, SERVICES_CONFIGURED, SERVICES_CURRENCY,
  SERVICES_PRODUCT_ID, serviceByKind, serviceChoice,
} from '../config/services';
import { isServiceRefusal, SERVICE_REFUSAL_MESSAGES } from '../lib/serviceRequests';

describe( 'the services config', () => {
  it( 'declares the one product, INR, and exactly four offered services in integer paise', () => {
    expect( SERVICES_PRODUCT_ID ).toBe( 'df976a0a-f582-4535-b2e1-d532f348bd27' );
    expect( SERVICES_CURRENCY ).toBe( 'INR' );
    expect( SERVICE_CHOICES.map( c => c.kind ) ).toEqual(
      [ 'SUBMIT_REQUEST', 'REQUEST_AMENDMENT', 'DROP_DOCS', 'VAULT' ] );
    for ( const choice of SERVICE_CHOICES )
    {
      expect( choice.rupees * 100 ).toBe( choice.paise );
      expect( Number.isInteger( choice.paise ) ).toBe( true );
    }
    expect( SERVICES_CONFIGURED ).toBe( true );
  } );

  it( 'offers Drop Docs at 35000 paise and Vault at 4900, both needing a target', () => {
    expect( NOT_OFFERED_SERVICE_VARIANT_IDS ).toHaveLength( 0 );
    expect( serviceByKind( 'DROP_DOCS' ) ).toMatchObject( {
      variantId: 'db166bc8-a763-41ec-9f65-0f718f18155a', label: 'Drop Docs',
      rupees: 350, paise: 35000, path: '/drop-docs/', needsTarget: true,
    } );
    expect( serviceByKind( 'VAULT' ) ).toMatchObject( {
      variantId: 'dcff995e-448c-493a-9259-f6a82ccdc2b4', label: 'Vault',
      rupees: 49, paise: 4900, path: '/vault/', needsTarget: true,
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
