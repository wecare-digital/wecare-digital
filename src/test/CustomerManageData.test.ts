import { describe, expect, it } from 'vitest';
import { buildCustomerDataReview } from '../components/workspace/customers/ManageData';

const contact = ( overrides: Record<string, unknown> ) => ( {
  contactId: 'c-default',
  customerUuid: 'WC-DEFAULT',
  name: 'Customer',
  phone: '+918100000000',
  email: 'customer@example.com',
  checkoutDeliveryAddress: { addressLine1: '1 Main Road' },
  shippingAddress: '',
  addressLine1: '',
  ...overrides,
} as any );

describe( 'Customers Manage Data review', () => {
  it( 'groups duplicates only on exact normalized phone or email, never display name', () => {
    const review = buildCustomerDataReview( [
      contact( { contactId: 'c1', name: 'Same Name', phone: '+91 81000 00000', email: 'one@example.com' } ),
      contact( { contactId: 'c2', name: 'Same Name', phone: '+918100000000', email: 'two@example.com' } ),
      contact( { contactId: 'c3', name: 'Same Name', phone: '+919999999999', email: 'TWO@example.com' } ),
      contact( { contactId: 'c4', name: 'Same Name', phone: '+917777777777', email: 'four@example.com' } ),
    ] );

    expect( review.duplicates ).toHaveLength( 2 );
    expect( review.duplicates.map( group => group.kind ).sort() ).toEqual( [ 'email', 'phone' ] );
    expect( review.duplicates.flatMap( group => group.contacts.map( item => item.contactId ) ) )
      .not.toContain( 'c4' );
  } );

  it( 'surfaces missing IDs, phones, invalid E.164 and addresses independently', () => {
    const review = buildCustomerDataReview( [
      contact( { contactId: 'missing-id', customerUuid: '' } ),
      contact( { contactId: 'missing-phone', phone: '' } ),
      contact( { contactId: 'bad-phone', phone: '8100064004' } ),
      contact( {
        contactId: 'missing-address',
        checkoutDeliveryAddress: undefined,
        shippingAddress: '',
        addressLine1: '',
      } ),
    ] );

    expect( review.missingCustomerId.map( c => c.contactId ) ).toEqual( [ 'missing-id' ] );
    expect( review.missingPhone.map( c => c.contactId ) ).toEqual( [ 'missing-phone' ] );
    expect( review.invalidPhone.map( c => c.contactId ) ).toEqual( [ 'bad-phone' ] );
    expect( review.missingAddress.map( c => c.contactId ) ).toEqual( [ 'missing-address' ] );
  } );
} );
