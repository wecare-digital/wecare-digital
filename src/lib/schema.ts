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
 * The one Organization node. Every other entity references it by `@id`.
 */
export const ORGANIZATION = {
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
