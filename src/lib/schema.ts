/**
 * The site's schema.org entity graph, defined ONCE.
 *
 * WHY THIS FILE EXISTS. Before it, one company was described three different ways:
 * `_app.tsx` defined a full `Organization` with `@id .../#organization`, while
 * `post/[slug].tsx` and `BlogIndexHead.tsx` each inlined a thinner, ANONYMOUS copy as
 * `publisher` — name and url, no `@id`, no logo. Both were right to inline rather than
 * reference, and that is the part worth understanding: `_app.tsx` renders its whole `<Head>`
 * behind `!isContentPublic`, so on `/blog/*` and `/post/*` the `#organization` node does not
 * exist, and `publisher: { '@id': '…#organization' }` there would have been a reference that
 * resolves to nothing — worse than a duplicate.
 *
 * The fix is not to reference a suppressed node. It is to stop the node being suppressed:
 * every public surface now emits `ORGANIZATION` and `WEBSITE` from this module, so the
 * `@id`s are defined on all ~1,350 indexable URLs and references to them resolve everywhere.
 *
 * SCALE OF WHAT THAT CHANGES. The blog is 1,279 posts plus ~54 index pages against 20
 * marketing routes, so before this the company entity was absent from roughly 98% of the
 * indexable site. Entity consolidation is the whole point of `@id`: Google reconciles nodes
 * that share one, and three anonymous publishers named "WECARE.DIGITAL" are three blank
 * nodes rather than one company.
 *
 * WHAT IS DELIBERATELY NOT HERE
 * -----------------------------
 * No `aggregateRating`, no `review`, no `offers`, no `foundingDate`. Each was removed from
 * this graph for a stated reason and none of them has become true since — `_app.tsx`'s
 * comments record the detail, and the short version is that a fabricated rating is grounds
 * for a manual action against the whole domain, and a wrong founding date is a checkable
 * false claim. A validator cannot catch either: invented markup is syntactically perfect.
 *
 * Every value below is sourced from something already published on this site or measured in
 * this repository. Nothing is inferred.
 */

import { MEDIA_BASE, SITE_ORIGIN } from '../config/share';

/** Trailing-slash-free origin. `trailingSlash: true`, so page URLs add their own. */
export const ORIGIN = SITE_ORIGIN;

export const ORG_ID = `${ORIGIN}/#organization`;
export const WEBSITE_ID = `${ORIGIN}/#website`;

/** The square mark. Google renders `Organization.logo` in the knowledge panel and wants the
 *  logo, not a 16:9 banner — which is why this is not `SOCIAL_CARD_URL`'s sibling asset.
 *  Pinned by `src/test/BrandAssets.test.ts`; keep it square. */
export const LOGO_URL = `${MEDIA_BASE}/wecare-digital.png`;

/** Intrinsic size of that asset, measured: 1080x1080. Declared because Google's logo
 *  guidance takes an `ImageObject`, and an `ImageObject` without dimensions is the form
 *  that gets reported as incomplete. */
const LOGO_W = 1080;
const LOGO_H = 1080;

export const COMPANY_DESCRIPTION =
  'WECARE.DIGITAL builds everyday AI for consumers, enterprises, climate tech and frontier '
  + 'tech, with transparent pricing and one place to track everything.';

/**
 * The registered address, verbatim from the site's own legal pages.
 *
 * NOT invented and not taken from the payment path's `importer_address`, which is the
 * shorter compliance form. `src/content/legal/privacy.ts:354` and
 * `src/content/legal/terms.ts:537,663` publish this in full to every visitor, so marking it
 * up discloses nothing new — it makes an already-public fact machine-readable, which is
 * precisely what an address property is for.
 */
export const POSTAL_ADDRESS = {
  '@type': 'PostalAddress',
  streetAddress: 'The W.B.S.I.D.C. Building, Unit 1/20, 81/2/7 Phears Lane',
  addressLocality: 'Kolkata',
  addressRegion: 'West Bengal',
  postalCode: '700012',
  addressCountry: 'IN',
} as const;

/**
 * Coordinates of the building, not the street.
 *
 * From `src/components/ContactLocation.tsx:92-93`, which documents the distinction: OSM
 * geocodes "Phears Lane, Tiretti" to 22.5731893/88.3576881 — the street, roughly 200 m off —
 * and these are Google's own resolved position for the building. Reusing the measured pair
 * rather than re-deriving it keeps the map and the markup on one location.
 */
const GEO = { '@type': 'GeoCoordinates', latitude: 22.5717148, longitude: 88.3566972 } as const;

/**
 * The one Organization node, in its BASE form. Every other entity references it by `@id`.
 *
 * This is the node as published today. `ORGANIZATION` below is this object, optionally
 * enriched with Google Business Profile opening hours and category WHEN (and only when)
 * real data flows from the dormant GBP integration (see `enrichOrganization` and
 * `loadBusinessProfileData`). In the default state (flag off, no data) `ORGANIZATION` IS this
 * object, unchanged and byte-identical, which is the only state reachable without a human
 * first obtaining GBP Basic API Access.
 */
const BASE_ORGANIZATION = {
  '@context': 'https://schema.org',
  '@type': 'Organization',
  '@id': ORG_ID,
  name: 'WECARE.DIGITAL',
  alternateName: 'WECARE.DIGITAL',
  url: `${ORIGIN}/`,
  // ImageObject rather than a bare URL string. A URL is accepted, but the object form is
  // what Google's logo guidance documents and it is the only form that can carry dimensions.
  logo: {
    '@type': 'ImageObject',
    url: LOGO_URL,
    width: LOGO_W,
    height: LOGO_H,
    caption: 'WECARE.DIGITAL',
  },
  image: LOGO_URL,
  description: COMPANY_DESCRIPTION,
  address: POSTAL_ADDRESS,
  geo: GEO,
  contactPoint: {
    '@type': 'ContactPoint',
    contactType: 'customer service',
    // The grievance-desk number, published at `src/content/legal/terms.ts:537` together with
    // this email. `telephone` was the property missing from this node, and it is the one
    // Google's contactPoint guidance is actually about — a contactPoint carrying only a URL
    // says little more than the page it points at.
    telephone: '+91-9330994400',
    email: 'one@wecare.digital',
    url: `${ORIGIN}/contact/`,
    areaServed: 'IN',
    availableLanguage: [ 'English', 'Hindi' ],
  },
} as const;

/**
 * One schema.org `OpeningHoursSpecification` entry, as produced by the dormant GBP mapper.
 *
 * Shape matches `amplify/functions/operations/seo-tools/business_profile.py:to_schema`
 * exactly: that Python module is the ONLY source of these values, read live from the Google
 * Business Profile API for the real location. Nothing here is a default.
 */
export interface OpeningHoursSpecification {
  '@type': 'OpeningHoursSpecification';
  dayOfWeek: string[];
  opens: string;
  closes: string;
}

/**
 * The GBP enrichment payload. This is the JSON that the build-time generator writes into
 * `src/config/business-profile.generated.json` ONLY in the real deployment when the flag is on
 * AND the GBP API returns real data. `null` means "no data", the committed default.
 *
 * Mirror of `business_profile.py:to_schema`'s return: it contains only the keys that were
 * actually present in the live response, so both fields are optional.
 */
export interface BusinessProfileData {
  openingHoursSpecification?: OpeningHoursSpecification[];
  category?: string;
}

/**
 * Whether the GBP LocalBusiness enrichment is switched on. Defaults OFF (fail-safe).
 *
 * `GBP_LOCALBUSINESS_ENABLED` is a build-time, server-side env flag, deliberately NOT a
 * `NEXT_PUBLIC_*` var: it carries no secret and is only read while the static pages are
 * pre-rendered, so it never ships to the client. It mirrors the identically named gate in the
 * Python fetch module (`business_profile.py:business_profile_enabled`); a public read path must
 * never be one typo away from an active integration, so anything but an explicit truthy value
 * resolves to off, and off means no enrichment is emitted.
 */
export const gbpLocalBusinessEnabled = (): boolean => {
  const raw = ( process.env.GBP_LOCALBUSINESS_ENABLED ?? '' ).trim().toLowerCase();
  return raw === '1' || raw === 'true' || raw === 'yes' || raw === 'on';
};

/**
 * Read the optional, build-time-generated GBP data, DEFENSIVELY. Returns `null` unless the flag
 * is on AND the generated file holds real data.
 *
 * DATA PATH. The dormant Python fetch (`business_profile.py`) runs only in the real deployment;
 * when it returns real GBP data a build-time generator writes it to
 * `src/config/business-profile.generated.json`. That file is committed as `null` (no data) and
 * must never be committed populated; absent/empty data changes nothing here. The import is
 * wrapped so a malformed or empty file also resolves to `null`, and the flag is checked first so
 * that even a stray populated file emits nothing while the integration is off.
 */
export const loadBusinessProfileData = (): BusinessProfileData | null => {
  if ( !gbpLocalBusinessEnabled() ) return null;
  try {
    const data = require( '../config/business-profile.generated.json' ) as unknown;
    if ( data && typeof data === 'object' ) return data as BusinessProfileData;
  } catch {
    // Absent or unreadable file is the default, dormant state: no data, no enrichment.
  }
  return null;
};

/**
 * Attach GBP opening hours and category to the Organization node, HONESTLY or not at all.
 *
 * PURE and EXPORTED so a test can hand it a fixture directly, with no build-time file and no env
 * flag involved. Follows the same doctrine as the rest of this file: NOTHING is inferred. The
 * `openingHoursSpecification` and `category` come solely from `data` (ultimately the live GBP
 * response mapped by `business_profile.py`); neither is ever hardcoded or defaulted. This is the
 * same reason `aggregateRating`/`review`/`foundingDate` are absent above: a fabricated value is
 * grounds for a manual action and a validator cannot catch it.
 *
 * When `data` is `null` (the default) the base object is returned UNCHANGED: same reference,
 * same key order, so the serialised Organization is byte-identical to the published baseline.
 * When data is present the enrichment EXTENDS the SAME node under the SAME `@id` (ORG_ID): it
 * appends `openingHoursSpecification` and/or `category` to the Organization rather than spawning
 * a second (or anonymous) LocalBusiness node, so there is exactly one company node on the page
 * and every `@id` reference keeps resolving. A field missing from `data` is omitted, not guessed.
 */
export const enrichOrganization = <T extends object>(
  base: T,
  data: BusinessProfileData | null,
): T | ( T & BusinessProfileData ) => {
  if ( !data ) return base;

  const hours = Array.isArray( data.openingHoursSpecification )
    ? data.openingHoursSpecification.filter( Boolean )
    : undefined;
  const category = typeof data.category === 'string' && data.category.trim()
    ? data.category
    : undefined;

  if ( ( !hours || hours.length === 0 ) && !category ) return base;

  // Spread the base first so existing keys keep their order; only honest, sourced keys are
  // appended. `@id` is untouched, so this stays the one Organization node.
  return {
    ...base,
    ...( hours && hours.length > 0 ? { openingHoursSpecification: hours } : {} ),
    ...( category ? { category } : {} ),
  };
};

/**
 * The one Organization node. Every other entity references it by `@id`.
 *
 * In the default state this is exactly `BASE_ORGANIZATION`. When GBP Basic API Access has been
 * granted, the flag turned on, and the generator has written real data, it is that node extended
 * with `openingHoursSpecification` and/or `category` under the SAME `@id`: never a second node,
 * never a fabricated value.
 */
export const ORGANIZATION = enrichOrganization( BASE_ORGANIZATION, loadBusinessProfileData() );

/**
 * The one WebSite node.
 *
 * `publisher` is an `@id` REFERENCE, not a restatement. It used to inline a second anonymous
 * `Organization` in the same file that defined the real one, so any page carrying both
 * described the company once as a full node and once as a blank one.
 *
 * Still no `potentialAction`/`SearchAction`: Google retired the sitelinks search box on
 * 2024-11-21, and the markup that used to be here pointed at an authenticated dashboard
 * route. Both reasons stand.
 */
export const WEBSITE = {
  '@context': 'https://schema.org',
  '@type': 'WebSite',
  '@id': WEBSITE_ID,
  name: 'WECARE.DIGITAL',
  alternateName: 'WECARE.DIGITAL',
  url: `${ORIGIN}/`,
  description: COMPANY_DESCRIPTION,
  publisher: { '@id': ORG_ID },
  inLanguage: 'en-IN',
} as const;

/**
 * The two site-level nodes as one array, for a surface that needs to emit both.
 *
 * Returned as separate objects rather than a single `@graph` so a caller can drop one
 * without rewriting the other, and so `seocheck.js`'s per-block `@id` walk keeps working
 * unchanged.
 */
export const SITE_ENTITIES: readonly unknown[] = [ ORGANIZATION, WEBSITE ];

/** Serialise for `dangerouslySetInnerHTML`. Centralised so every call site is identical. */
export const ld = ( value: unknown ): { __html: string } =>
  ( { __html: JSON.stringify( value ) } );
