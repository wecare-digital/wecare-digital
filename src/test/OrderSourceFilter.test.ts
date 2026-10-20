import { describe, expect, it } from 'vitest';
import {
  CANONICAL_SOURCES,
  canonicalSource,
  canonicalSourceLabel,
} from '../components/workspace/commerce/Orders';

/**
 * The Commerce Orders source filter is the charter's six canonical attribution buckets, and it
 * must map every HISTORICAL raw value onto one of them so an order written before the rename
 * still filters. Source is a filter only — nothing here touches money — so these tests pin the
 * mapping, not any accounting behaviour.
 */
describe( 'canonical order source filter', () => {
  it( 'exposes exactly the six charter values in order', () => {
    expect( CANONICAL_SOURCES ).toEqual( [
      'WEBSITE', 'WHATSAPP_PAYMENT', 'WHATSAPP_CATALOG',
      'STAFF_COMMERCE', 'STAFF_PAYMENT', 'SERVICE_FLOW',
    ] );
  } );

  it( 'passes canonical values straight through', () => {
    for ( const value of CANONICAL_SOURCES ) {
      expect( canonicalSource( value ) ).toBe( value );
    }
  } );

  it( 'maps the legacy raw values onto their charter bucket', () => {
    // The old generic list was manual/flow/catalog/integration; these are the rows already in
    // the table, and each must keep answering a filter.
    expect( canonicalSource( 'manual' ) ).toBe( 'STAFF_COMMERCE' );
    expect( canonicalSource( 'flow' ) ).toBe( 'SERVICE_FLOW' );
    expect( canonicalSource( 'catalog' ) ).toBe( 'WHATSAPP_CATALOG' );
    expect( canonicalSource( 'integration' ) ).toBe( 'WEBSITE' );
    expect( canonicalSource( 'website' ) ).toBe( 'WEBSITE' );
    expect( canonicalSource( 'whatsapp' ) ).toBe( 'WHATSAPP_PAYMENT' );
    expect( canonicalSource( 'shopify' ) ).toBe( 'WEBSITE' );
  } );

  it( 'is case- and separator-insensitive', () => {
    expect( canonicalSource( ' WhatsApp-Catalog ' ) ).toBe( 'WHATSAPP_CATALOG' );
    expect( canonicalSource( 'staff payment' ) ).toBe( 'STAFF_PAYMENT' );
  } );

  it( 'defaults an empty or unknown value to the staff bucket rather than dropping it', () => {
    // A row must never become unfilterable: an unrecognised origin is treated as a staff order.
    expect( canonicalSource( '' ) ).toBe( 'STAFF_COMMERCE' );
    expect( canonicalSource( undefined ) ).toBe( 'STAFF_COMMERCE' );
    expect( canonicalSource( 'something-new' ) ).toBe( 'STAFF_COMMERCE' );
  } );

  it( 'renders a human label for each bucket', () => {
    expect( canonicalSourceLabel( 'manual' ) ).toBe( 'Staff commerce' );
    expect( canonicalSourceLabel( 'WHATSAPP_PAYMENT' ) ).toBe( 'WhatsApp payment' );
    expect( canonicalSourceLabel( 'catalog' ) ).toBe( 'WhatsApp catalog' );
  } );
} );
