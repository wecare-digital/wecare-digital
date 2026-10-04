import React from 'react';
import Head from 'next/head';
import { ORIGIN, ORG_ID, WEBSITE_ID, SITE_ENTITIES, ld } from '../lib/schema';
import {
  SOCIAL_CARD_URL, SOCIAL_CARD_TYPE, SOCIAL_CARD_W, SOCIAL_CARD_H, SOCIAL_CARD_ALT,
  SHARE_CARD_TYPE,
} from '../config/share';
import { shopMetaDescription, shopPageTitle, shopProductPath } from '../content/shop';
import type { ShopProduct } from '../content/shop';

/**
 * The whole document head for a /shop/<slug>/ page.
 *
 * WHY THIS OWNS EVERY TAG instead of leaning on _app.tsx's sitewide Head. PUBLIC_PAGE_META is keyed
 * on `router.pathname`, and for a dynamic route that string is the PATTERN - '/shop/[slug]'. So the
 * canonical would read https://wecare.digital/shop/[slug]/, and so would og:url, twitter:url and the
 * WebPage node's @id and url. PageMeta can override the first three because they carry a `key` and
 * next/head dedupes on it, but the JSON-LD script does not and cannot be replaced - the page would
 * ship two graphs, one of them naming a URL that does not exist.
 *
 * So '/shop/[slug]' joins `isContentPublic` in _app.tsx instead, which suppresses the sitewide Head
 * and makes this component responsible for the lot. /post/[slug] does the same through SEO.tsx and
 * the blog index routes through BlogIndexHead.tsx.
 *
 * THE SITE ENTITIES ARE EMITTED HERE, because with _app.tsx's Head suppressed #organization and
 * #website do not otherwise exist on this page - so the `publisher`, `seller` and `brand` references
 * below would dangle.
 *
 * THE SHARE TAGS ARE WRITTEN OUT, not factored into a helper: next/head reads its DIRECT children to
 * build the tag list, so wrapping them in a component puts a layer between it and the tags and they
 * silently vanish. The values come from src/config/share.ts.
 *
 * NO PRODUCT IMAGE ANYWHERE. The snapshot reports mediaCount 0 for all seven, so there is no URL to
 * give og:image or Product.image. The share card falls back to the company mark, which every other
 * page uses.
 */

interface ShopProductHeadProps {
  product: ShopProduct;
}

/**
 * The JSON-LD graph for one product page, as a PURE FUNCTION so it can be asserted.
 *
 * EXPORTED BECAUSE next/head IS UNTESTABLE FROM jsdom. `<Head>` does not render into the component's
 * container - it is a side effect onto document.head - so a test that renders this component and
 * queries the container for `script[type="application/ld+json"]` finds ZERO scripts and every
 * assertion about the graph's contents passes vacuously. Building the graph here means the test
 * asserts the object while tools/audit/schemacheck.js asserts the built HTML.
 */
/** One JSON-LD node. Deliberately loose: a schema.org graph is heterogeneous by design. */
type LdNode = Record<string, unknown>;

export const shopProductSchema = (
  product: ShopProduct,
): { '@context': string; '@graph': LdNode[] } => {
  const url = ORIGIN + shopProductPath( product );
  const description = shopMetaDescription( product );

  /**
   * THE Product NODE IS EMITTED ONLY WHEN THE PRODUCT HAS AN IMAGE, AND IT HAS NONE TODAY. Google
   * requires name, image and offers on Product, and an incomplete Product is ineligible for the rich
   * result however complete the rest of it is - so the node buys nothing until there is a picture.
   * Sending the company logo instead would make one image the product photo for all seven.
   *
   * `price` is the bare decimal Wix returns, because schema.org/price wants a number with no
   * grouping and no symbol; the visible price uses Wix's formatted string. Two spellings of one
   * value, read from the same field, so markup and page cannot disagree. No `sku` - the snapshot's
   * only identifier is a Wix UUID, which is a database key rather than a stock-keeping unit. No
   * aggregateRating and no review: nobody has rated these.
   *
   * `description` is the full copy rather than the 160-character meta description, because this node
   * describes the product and the meta tag describes the search result.
   */
  const productNode: LdNode[] = product.image ? [ {
    '@type': 'Product',
    '@id': url + '#product',
    name: product.name,
    description: [ product.tagline, ...product.body ].join( ' ' ),
    url,
    image: product.image,
    brand: { '@id': ORG_ID },
    offers: {
      '@type': 'Offer',
      '@id': url + '#offer',
      url,
      price: product.price,
      priceCurrency: product.currency,
      availability: product.inStock
        ? 'https://schema.org/InStock'
        : 'https://schema.org/OutOfStock',
      seller: { '@id': ORG_ID },
    },
  } ] : [];

  const schema: { '@context': string; '@graph': LdNode[] } = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'ItemPage',
        '@id': url + '#webpage',
        url,
        name: product.name,
        description,
        isPartOf: { '@id': WEBSITE_ID },
        inLanguage: 'en-IN',
        breadcrumb: { '@id': url + '#breadcrumb' },
        // mainEntity ONLY when the Product exists. A reference to an @id nothing defines is a
        // dangling pointer, and schemacheck asserts there are none - so an unconditional mainEntity
        // would trade one failure for another.
        ...( productNode.length ? { mainEntity: { '@id': url + '#product' } } : {} ),
        publisher: { '@id': ORG_ID },
      },
      {
        // TWO ITEMS, NOT THREE, since 2026-10-04. Position 2 was
        // { name: 'Shop', item: ORIGIN + '/shop/' } and the catalogue index has been withdrawn on
        // owner instruction, so that URL 301s to the home page - which would make position 2
        // resolve to the same page as position 1.
        //
        // IT MATCHES THE RENDERED TRAIL ON PURPOSE. src/pages/shop/[slug].tsx now renders
        // [ Home, product ], and a BreadcrumbList describing a trail the page does not render is
        // the mismatch that makes a rich result disappear SILENTLY - no error, no warning, the
        // breadcrumb simply stops being shown. The two must be edited together.
        '@type': 'BreadcrumbList',
        '@id': url + '#breadcrumb',
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: ORIGIN + '/' },
          { '@type': 'ListItem', position: 2, name: product.name, item: url },
        ],
      },
      ...productNode,
    ],
  };

  return schema;
};

const ShopProductHead: React.FC<ShopProductHeadProps> = ( { product } ) => {
  const url = ORIGIN + shopProductPath( product );
  const title = shopPageTitle( product );
  const description = shopMetaDescription( product );
  const schema = shopProductSchema( product );

  return (
    <Head>
      <title>{ title }</title>
      <meta name="description" content={ description } />
      <link rel="canonical" href={ url } />
      <meta property="og:type" content="website" />
      <meta property="og:title" content={ title } />
      <meta property="og:description" content={ description } />
      <meta property="og:url" content={ url } />
      <meta property="og:image" content={ SOCIAL_CARD_URL } />
      <meta property="og:image:secure_url" content={ SOCIAL_CARD_URL } />
      <meta property="og:image:type" content={ SOCIAL_CARD_TYPE } />
      <meta property="og:image:width" content={ SOCIAL_CARD_W } />
      <meta property="og:image:height" content={ SOCIAL_CARD_H } />
      <meta property="og:image:alt" content={ SOCIAL_CARD_ALT } />
      <meta property="og:site_name" content="WECARE.DIGITAL" />
      <meta property="og:locale" content="en_IN" />
      <meta name="twitter:card" content={ SHARE_CARD_TYPE } />
      <meta name="twitter:title" content={ title } />
      <meta name="twitter:description" content={ description } />
      <meta name="twitter:url" content={ url } />
      <meta name="twitter:image" content={ SOCIAL_CARD_URL } />
      <meta name="twitter:image:alt" content={ SOCIAL_CARD_ALT } />
      <meta name="robots" content="index, follow, max-image-preview:large" />
      { SITE_ENTITIES.map( ( entity, index ) => (
        <script key={ `site-entity-${index}` } type="application/ld+json"
          dangerouslySetInnerHTML={ ld( entity ) } />
      ) ) }
      <script type="application/ld+json" dangerouslySetInnerHTML={ ld( schema ) } />
    </Head>
  );
};

export default ShopProductHead;
