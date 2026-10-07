import { describe, expect, it } from 'vitest';
import {
  NOT_OFFERED_SERVICE_VARIANT_IDS, SERVICE_CHOICES, SERVICES_CONFIGURED, SERVICES_CURRENCY,
  SERVICES_PRODUCT_ID, serviceByKind, serviceChoice,
} from '../config/services';
import { isServiceRefusal, SERVICE_REFUSAL_MESSAGES } from '../lib/serviceRequests';

describe( 'the services config (Phase O-1)', () => {
  it( 'declares the one product, INR, and exactly two offered services at 9900 paise', () => {
    expect( SERVICES_PRODUCT_ID ).toBe( 'df976a0a-f582-4535-b2e1-d532f348bd27' );
    expect( SERVICES_CURRENCY ).toBe( 'INR' );
    expect( SERVICE_CHOICES.map( c => c.kind ) ).toEqual( [ 'SUBMIT_REQUEST', 'REQUEST_AMENDMENT' ] );
    for ( const choice of SERVICE_CHOICES )
    {
      expect( choice.paise ).toBe( 9900 );
      expect( choice.rupees * 100 ).toBe( choice.paise );
      expect( Number.isInteger( choice.paise ) ).toBe( true );
    }
    expect( SERVICES_CONFIGURED ).toBe( true );
  } );

  it( 'never offers Drop Docs or Vault', () => {
    for ( const id of NOT_OFFERED_SERVICE_VARIANT_IDS )
    {
      expect( SERVICE_CHOICES.some( c => c.variantId === id ) ).toBe( false );
      expect( serviceChoice( id ) ).toBeNull();
    }
    expect( NOT_OFFERED_SERVICE_VARIANT_IDS ).toHaveLength( 2 );
    expect( serviceByKind( 'DROP_DOCS' ) ).toBeNull();
    expect( serviceByKind( 'VAULT' ) ).toBeNull();
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
