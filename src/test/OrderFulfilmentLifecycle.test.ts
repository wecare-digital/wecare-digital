import { describe, expect, it } from 'vitest';
import {
  allowedFulfilmentTargets,
  canonicalFulfilmentStatus,
  fulfilmentLabel,
} from '../lib/orderFulfilment';

describe( 'order fulfilment lifecycle', () => {
  it( 'maps legacy order words without losing paid-vs-unpaid meaning', () => {
    expect( canonicalFulfilmentStatus( 'active', 'pending' ) ).toBe( 'pending' );
    expect( canonicalFulfilmentStatus( 'active', 'captured' ) ).toBe( 'processing' );
    expect( canonicalFulfilmentStatus( 'active', 'PAYMENT_PAID' ) ).toBe( 'processing' );
    expect( canonicalFulfilmentStatus( 'fulfilled', 'paid' ) ).toBe( 'completed' );
    expect( canonicalFulfilmentStatus( 'cancelled', 'pending' ) ).toBe( 'canceled' );
    expect( canonicalFulfilmentStatus( 'partially_shipped', 'paid' ) ).toBe( 'partially-shipped' );
  } );

  it( 'matches the backend legal forward transitions for paid fulfilment', () => {
    expect( allowedFulfilmentTargets( 'processing', 'paid' ) )
      .toEqual( [ 'partially-shipped', 'shipped', 'completed' ] );
    expect( allowedFulfilmentTargets( 'partially-shipped', 'captured' ) )
      .toEqual( [ 'shipped', 'completed' ] );
    expect( allowedFulfilmentTargets( 'shipped', 'PAYMENT_PAID' ) )
      .toEqual( [ 'completed' ] );
    expect( allowedFulfilmentTargets( 'completed', 'paid' ) ).toEqual( [] );
    expect( allowedFulfilmentTargets( 'canceled', 'pending' ) ).toEqual( [] );
  } );

  it( 'does not let an unpaid order enter fulfilment from the workspace dropdown', () => {
    expect( allowedFulfilmentTargets( 'pending', 'pending' ) ).toEqual( [] );
    expect( allowedFulfilmentTargets( 'active', 'failed' ) ).toEqual( [] );
    expect( allowedFulfilmentTargets( 'pending', 'captured' ) ).toEqual( [ 'processing' ] );
  } );

  it( 'uses human labels for hyphenated lifecycle words', () => {
    expect( fulfilmentLabel( 'partially-shipped' ) ).toBe( 'Partially Shipped' );
    expect( fulfilmentLabel( 'processing' ) ).toBe( 'Processing' );
  } );
} );
