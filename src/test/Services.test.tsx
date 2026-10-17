import { describe, expect, it } from 'vitest';
import {
  NOT_OFFERED_SERVICE_VARIANT_IDS, SERVICE_CHOICES, SERVICES_CONFIGURED, SERVICES_CURRENCY,
  SERVICES_OPTION_ID, SERVICES_PRODUCT_ID, serviceByKind, serviceChoice,
} from '../config/services';
import { isServiceRefusal, SERVICE_REFUSAL_MESSAGES } from '../lib/serviceRequests';

describe( 'the services config', () => {
  it( 'is a clean slate until the fresh SKU-first service catalog is created', () => {
    expect( SERVICES_PRODUCT_ID ).toBe( '' );
    expect( SERVICES_OPTION_ID ).toBe( '' );
    expect( SERVICES_CURRENCY ).toBe( 'INR' );
    expect( SERVICE_CHOICES ).toEqual( [] );
    expect( NOT_OFFERED_SERVICE_VARIANT_IDS ).toEqual( [] );
    expect( SERVICES_CONFIGURED ).toBe( false );
  } );

  it( 'resolves no retired service identity', () => {
    expect( serviceChoice( 'e9f0eb8b-ca76-4b4f-b00c-be909c02bb2b' ) ).toBeNull();
    expect( serviceByKind( 'SUBMIT_REQUEST' ) ).toBeNull();
    expect( serviceByKind( 'REQUEST_AMENDMENT' ) ).toBeNull();
    expect( serviceByKind( 'DROP_DOCS' ) ).toBeNull();
    expect( serviceByKind( 'VAULT' ) ).toBeNull();
    expect( serviceByKind( 'REQUEST_PICKUP' ) ).toBeNull();
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
