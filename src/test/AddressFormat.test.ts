import { describe, expect, it } from 'vitest';
import { EMPTY_ADDRESS_FIELDS, formatAddress } from '../lib/address-format';

describe( 'address formatting preserves a saved fallback', () => {
  it( 'returns no new address for untouched default country fields', () => {
    expect( formatAddress( EMPTY_ADDRESS_FIELDS ) ).toBe( '' );
    expect( formatAddress( { country: 'United Kingdom', countryCode: 'GB' } ) ).toBe( '' );
  } );

  it( 'composes entered address content and the country', () => {
    expect( formatAddress( { ...EMPTY_ADDRESS_FIELDS, addressLine1: '12 MG Road',
      city: 'Bengaluru', state: 'Karnataka', postalCode: '560001' } ) )
      .toBe( '12 MG Road, Bengaluru, Karnataka 560001, India' );
  } );
} );
