import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';
import {
  NOT_OFFERED_SERVICE_VARIANT_IDS, SERVICE_CHOICES, SERVICES_CONFIGURED, SERVICES_CURRENCY,
  SERVICES_OPTION_ID, SERVICES_PRODUCT_ID, serviceByKind, serviceChoice,
} from '../config/services';
import { isServiceRefusal, SERVICE_REFUSAL_MESSAGES } from '../lib/serviceRequests';

const SOURCE = fs.readFileSync( path.join( __dirname, '..', 'config', 'services.ts' ), 'utf8' );

describe( 'the services config', () => {
  it( 'keeps production clean while exposing synthetic choices only to tests', () => {
    expect( SOURCE ).toContain( "TESTING ? '11111111-1111-4111-8111-111111111111' : ''" );
    expect( SOURCE ).toContain( 'TESTING ? TEST_SERVICE_CHOICES : []' );
    expect( SERVICES_PRODUCT_ID ).toBe( '11111111-1111-4111-8111-111111111111' );
    expect( SERVICES_OPTION_ID ).toBe( '10101010-1010-4010-8010-101010101010' );
    expect( SERVICES_CURRENCY ).toBe( 'INR' );
    expect( SERVICE_CHOICES ).toHaveLength( 5 );
    expect( NOT_OFFERED_SERVICE_VARIANT_IDS ).toEqual( [] );
    expect( SERVICES_CONFIGURED ).toBe( true );
  } );

  it( 'resolves the five synthetic test services without any retired UUID', () => {
    expect( SERVICE_CHOICES.map( c => c.kind ) ).toEqual(
      [ 'SUBMIT_REQUEST', 'REQUEST_AMENDMENT', 'DROP_DOCS', 'VAULT', 'REQUEST_PICKUP' ] );
    expect( SERVICE_CHOICES.map( c => c.slug ) ).toEqual(
      [ 'submit-request', 'request-amendment', 'drop-docs', 'vault', 'request-pickup' ] );
    expect( serviceChoice( SERVICE_CHOICES[ 0 ].variantId.toUpperCase() )?.kind )
      .toBe( 'SUBMIT_REQUEST' );
    expect( serviceByKind( 'REQUEST_AMENDMENT' )?.path ).toBe( '/request-amendment/' );
    expect( serviceChoice( 'ffffffff-ffff-4fff-8fff-ffffffffffff' ) ).toBeNull();
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
