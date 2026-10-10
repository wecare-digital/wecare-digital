import { describe, expect, it } from 'vitest';
import {
  NOT_OFFERED_SERVICE_VARIANT_IDS, SERVICE_CHOICES, SERVICES_CONFIGURED, SERVICES_CURRENCY,
  SERVICES_OPTION_ID, SERVICES_PRODUCT_ID, serviceByKind, serviceChoice,
} from '../config/services';
import { isServiceRefusal, SERVICE_REFUSAL_MESSAGES } from '../lib/serviceRequests';

describe( 'the services config', () => {
  it( 'declares the one product, INR, and exactly five offered services with NO price', () => {
    expect( SERVICES_PRODUCT_ID ).toBe( 'df976a0a-f582-4535-b2e1-d532f348bd27' );
    expect( SERVICES_CURRENCY ).toBe( 'INR' );
    expect( SERVICE_CHOICES.map( c => c.kind ) ).toEqual(
      [ 'SUBMIT_REQUEST', 'REQUEST_AMENDMENT', 'DROP_DOCS', 'VAULT', 'REQUEST_PICKUP' ] );
    // NO `rupees` AND NO `paise`, since 2026-10-08. Owner decision: a price must be changeable
    // in Wix with no deploy, so the only price a page shows is the live one it fetches. Asserted
    // on the objects themselves rather than only in the type, because a type error is not a
    // runtime guarantee and this file is also what `tests/test_service_requests.py` mirrors.
    for ( const choice of SERVICE_CHOICES )
    {
      expect( Object.keys( choice ).sort() ).toEqual(
        [ 'choiceId', 'kind', 'label', 'needsTarget', 'path', 'sku', 'slug', 'variantId' ] );
    }
    // The slug vocabulary is the key the live-price payload is read by. Five pages, five slugs.
    expect( SERVICE_CHOICES.map( c => c.slug ) ).toEqual(
      [ 'submit-request', 'request-amendment', 'drop-docs', 'vault', 'request-pickup' ] );
    expect( new Set( SERVICE_CHOICES.map( c => c.slug ) ).size ).toBe( 5 );
    // Each slug matches its own page path, so a card cannot request another page's price.
    for ( const choice of SERVICE_CHOICES )
    {
      expect( choice.path ).toBe( `/${ choice.slug }/` );
    }
    expect( SERVICES_CONFIGURED ).toBe( true );
  } );

  it( 'carries the snapshot\'s choiceId and SKU on every service, under one option id', () => {
    // ADDITIVE REFERENCE METADATA, read out of src/content/wix-catalog.json rather than typed:
    // the cart still travels on `variantId`, and nothing in the payment path reads these. What
    // they buy is that the repo's declaration can be compared to Wix without a second copy of
    // the catalogue existing somewhere to be kept in step by hand.
    expect( SERVICES_OPTION_ID ).toBe( 'aee30ab6-72bd-4a04-ac83-0234652ad0ee' );
    for ( const choice of SERVICE_CHOICES )
    {
      expect( choice.choiceId, choice.slug ).toMatch( /^[0-9a-f-]{36}$/ );
      expect( choice.sku, choice.slug ).toMatch( /^SERVICE-[A-Z-]+$/ );
    }
    // Distinct per service: one id pasted twice would make two services look like one row.
    expect( new Set( SERVICE_CHOICES.map( c => c.choiceId ) ).size ).toBe( SERVICE_CHOICES.length );
    expect( new Set( SERVICE_CHOICES.map( c => c.sku ) ).size ).toBe( SERVICE_CHOICES.length );
    expect( serviceByKind( 'REQUEST_PICKUP' ) ).toMatchObject( {
      variantId: '8ee7e325-d772-4452-a993-5c79e927d42b', label: 'Request Pickup',
      slug: 'request-pickup', path: '/request-pickup/', needsTarget: true,
      choiceId: 'faa3b648-1fba-41ad-a5f2-f84bd2524070', sku: 'SERVICE-REQUEST-PICKUP',
    } );
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
    // The allow-list is still closed: an id the config does not name resolves to nothing. The
    // one below is fabricated - the Drop Docs id with its last character changed - not the fifth
    // variant, which is now Request Pickup and IS offered.
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
