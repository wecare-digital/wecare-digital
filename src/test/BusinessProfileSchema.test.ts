/**
 * The Google Business Profile enrichment of the Organization node: dormant by default, honest
 * when live.
 *
 * TWO STATES, BOTH ASSERTED. The integration that feeds this is DORMANT: the GBP API is not yet
 * approved for the project (see scripts/business_profile_access.py and
 * amplify/functions/operations/seo-tools/business_profile.py), so the ONLY state reachable here is
 * flag-off / no-data. That state must leave the Organization node byte-for-byte as it was before
 * this feature existed: no openingHoursSpecification, no category, one node under ORG_ID. The
 * second state, real GBP hours + category flowing in, cannot be produced in this sandbox, so it
 * is exercised the only honest way it can be: by handing the PURE enrichOrganization() a fixture
 * data object directly, exactly the shape business_profile.py:to_schema returns.
 *
 * WHY THIS IMPORTS src/lib/schema.ts AND NOT _app.tsx. schema.ts is pure data; _app.tsx runs
 * Amplify.configure at module scope (StructuredDataService.test.ts reads it as text for that very
 * reason). The enrichment lives in schema.ts precisely so it can be tested without booting the SDK.
 *
 * NO FABRICATION. The fixture below is clearly test-only and is NOT shipped site data: the
 * committed src/config/business-profile.generated.json is `null`. The whole point of this feature
 * is that absent data means absent markup.
 */
import { describe, expect, it } from 'vitest';
import {
  ORG_ID,
  ORGANIZATION,
  enrichOrganization,
  gbpLocalBusinessEnabled,
  loadBusinessProfileData,
  type BusinessProfileData,
} from '../lib/schema';

/**
 * The expected Organization node in the default (dormant) state, written out verbatim rather than
 * derived, the same reason the Service test writes out its offerings list. Derived, this test
 * would agree with whatever schema.ts produced, including an accidental opening-hours leak.
 */
const BASELINE_ORGANIZATION = {
  '@context': 'https://schema.org',
  '@type': 'Organization',
  '@id': 'https://wecare.digital/#organization',
  name: 'WECARE.DIGITAL',
  alternateName: 'WECARE.DIGITAL',
  url: 'https://wecare.digital/',
  logo: {
    '@type': 'ImageObject',
    url: 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png',
    width: 1080,
    height: 1080,
    caption: 'WECARE.DIGITAL',
  },
  image: 'https://wecare.digital/get/o/stream/media/m/wecare-digital.png',
  description:
    'WECARE.DIGITAL builds everyday AI for consumers, enterprises, climate tech and frontier '
    + 'tech, with transparent pricing and one place to track everything.',
  address: {
    '@type': 'PostalAddress',
    streetAddress: 'The W.B.S.I.D.C. Building, Unit 1/20, 81/2/7 Phears Lane',
    addressLocality: 'Kolkata',
    addressRegion: 'West Bengal',
    postalCode: '700012',
    addressCountry: 'IN',
  },
  geo: { '@type': 'GeoCoordinates', latitude: 22.5717148, longitude: 88.3566972 },
  contactPoint: {
    '@type': 'ContactPoint',
    contactType: 'customer service',
    telephone: '+91-9330994400',
    email: 'one@wecare.digital',
    url: 'https://wecare.digital/contact/',
    areaServed: 'IN',
    availableLanguage: [ 'English', 'Hindi' ],
  },
};

/**
 * A realistic GBP fragment, the exact shape business_profile.py:to_schema returns: a few
 * openingHoursSpecification entries and a category string. TEST-ONLY, never shipped, never
 * committed into the generated JSON. Mon-Fri 09:00-18:00, Sat 10:00-14:00, category "Software company".
 */
const FIXTURE: BusinessProfileData = {
  openingHoursSpecification: [
    { '@type': 'OpeningHoursSpecification', dayOfWeek: [ 'Monday' ], opens: '09:00', closes: '18:00' },
    { '@type': 'OpeningHoursSpecification', dayOfWeek: [ 'Tuesday' ], opens: '09:00', closes: '18:00' },
    { '@type': 'OpeningHoursSpecification', dayOfWeek: [ 'Wednesday' ], opens: '09:00', closes: '18:00' },
    { '@type': 'OpeningHoursSpecification', dayOfWeek: [ 'Thursday' ], opens: '09:00', closes: '18:00' },
    { '@type': 'OpeningHoursSpecification', dayOfWeek: [ 'Friday' ], opens: '09:00', closes: '18:00' },
    { '@type': 'OpeningHoursSpecification', dayOfWeek: [ 'Saturday' ], opens: '10:00', closes: '14:00' },
  ],
  category: 'Software company',
};

describe( 'GBP enrichment: default dormant state', () => {
  it( 'defaults the flag OFF when the env var is unset', () => {
    // The suite does not set GBP_LOCALBUSINESS_ENABLED, so this is the real default.
    expect( gbpLocalBusinessEnabled() ).toBe( false );
  } );

  it( 'loads no data while the flag is off', () => {
    // Even though the generated JSON is committed as null, the flag is checked first.
    expect( loadBusinessProfileData() ).toBeNull();
  } );

  it( 'emits the Organization node byte-identical to the published baseline', () => {
    // No openingHoursSpecification, no category: the dormant-state invariant.
    expect( ORGANIZATION ).toEqual( BASELINE_ORGANIZATION );
    expect( JSON.stringify( ORGANIZATION ) ).toBe( JSON.stringify( BASELINE_ORGANIZATION ) );
    expect( ORGANIZATION ).not.toHaveProperty( 'openingHoursSpecification' );
    expect( ORGANIZATION ).not.toHaveProperty( 'category' );
  } );
} );

describe( 'GBP enrichment: enrichOrganization() is pure and honest', () => {
  it( 'returns the base unchanged when data is null (same reference, byte-identical)', () => {
    const out = enrichOrganization( BASELINE_ORGANIZATION, null );
    expect( out ).toBe( BASELINE_ORGANIZATION );
    expect( JSON.stringify( out ) ).toBe( JSON.stringify( BASELINE_ORGANIZATION ) );
  } );

  it( 'returns the base unchanged when data carries neither field', () => {
    expect( enrichOrganization( BASELINE_ORGANIZATION, {} ) ).toBe( BASELINE_ORGANIZATION );
  } );

  it( 'attaches hours and category to the SAME @id, spawning no second node', () => {
    const enriched = enrichOrganization( BASELINE_ORGANIZATION, FIXTURE ) as Record<string, unknown>;

    // One node, same identity, not a second/anonymous LocalBusiness.
    expect( enriched[ '@id' ] ).toBe( ORG_ID );
    expect( enriched[ '@type' ] ).toBe( 'Organization' );

    // The honest, sourced values are present and valid.
    expect( enriched.openingHoursSpecification ).toEqual( FIXTURE.openingHoursSpecification );
    expect( enriched.category ).toBe( 'Software company' );

    for ( const spec of enriched.openingHoursSpecification as BusinessProfileData['openingHoursSpecification'] ?? [] ) {
      expect( spec[ '@type' ] ).toBe( 'OpeningHoursSpecification' );
      expect( Array.isArray( spec.dayOfWeek ) ).toBe( true );
      expect( spec.opens ).toMatch( /^\d{2}:\d{2}$/ );
      expect( spec.closes ).toMatch( /^\d{2}:\d{2}$/ );
    }

    // Base fields are preserved verbatim and nothing else was invented.
    expect( enriched.name ).toBe( 'WECARE.DIGITAL' );
    expect( enriched.logo ).toEqual( BASELINE_ORGANIZATION.logo );
    expect( enriched ).not.toHaveProperty( 'aggregateRating' );
    expect( enriched ).not.toHaveProperty( 'review' );
    expect( enriched ).not.toHaveProperty( 'foundingDate' );
  } );

  it( 'attaches only hours when the category is absent (honest omission)', () => {
    const out = enrichOrganization( BASELINE_ORGANIZATION, {
      openingHoursSpecification: FIXTURE.openingHoursSpecification,
    } ) as Record<string, unknown>;
    expect( out.openingHoursSpecification ).toEqual( FIXTURE.openingHoursSpecification );
    expect( out ).not.toHaveProperty( 'category' );
  } );

  it( 'attaches only the category when hours are absent (honest omission)', () => {
    const out = enrichOrganization( BASELINE_ORGANIZATION, {
      category: 'Software company',
    } ) as Record<string, unknown>;
    expect( out.category ).toBe( 'Software company' );
    expect( out ).not.toHaveProperty( 'openingHoursSpecification' );
  } );

  it( 'ignores an empty hours array and a blank category (no fabrication)', () => {
    expect( enrichOrganization( BASELINE_ORGANIZATION, { openingHoursSpecification: [], category: '   ' } ) )
      .toBe( BASELINE_ORGANIZATION );
  } );
} );
