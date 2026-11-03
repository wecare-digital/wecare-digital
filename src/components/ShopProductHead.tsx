import React from 'react';
import Head from 'next/head';
import { ORIGIN, ORG_ID, WEBSITE_ID, SITE_ENTITIES, ld } from '../lib/schema';
import {
  SOCIAL_CARD_URL, SOCIAL_CARD_TYPE, SOCIAL_CARD_W, SOCIAL_CARD_H, SOCIAL_CARD_ALT,
  SHARE_CARD_TYPE,
} from '../config/share';
import { shopMetaDescription, shopPageTitle, shopProductPath, shopRoutePath } from '../content/shop';
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
 * NO PRODUCT IMAGE ANYWHERE. The Shop is image-free by design: the catalogue carries no product
 * image URL, so there is nothing to give og:image or Product.image. The share card falls back to the
 * company mark, which every other page uses. Google requires name, image and offers on Product, so
 * with no image the node is ineligible for the rich result and is not emitted at all - the page ships
 * the ItemPage node (which needs no image) and leaves it at that.
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
  /*
   * PAGE-SCOPED @ids FOLLOW THE ROUTE, NOT THE CANONICAL. Catalog v2 lets a product declare a
   * canonical on another page (Anew's is /anew/), and that page defines its own #webpage and
   * #breadcrumb. Keying ours off the canonical made both routes define the same nodes, which
   * schemacheck's cross-route gate fails. So the nodes are identified by the route that emits
   * them, and `url` still carries the canonical. For every other product the two are equal.
   */
  const pageId = ORIGIN + shopRoutePath( product );
  const description = shopMetaDescription( product );

  /**
   * NO Product NODE. The Shop is image-free, and Google requires name, image and offers on Product -
   * an incomplete Product is ineligible for the rich result however complete the rest of it is, so a
   * node with no image buys nothing. Sending the company logo instead would make one image the
   * product photo for every product, which schemacheck.js refuses. The page therefore emits only the
   * ItemPage node, which needs no image, and so there is no `mainEntity` to point at: a reference to
   * an @id nothing defines is a dangling pointer, and schemacheck asserts there are none.
   */
  const schema: { '@context': string; '@graph': LdNode[] } = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'ItemPage',
        '@id': pageId + '#webpage',
        url,
        name: product.name,
        description,
        isPartOf: { '@id': WEBSITE_ID },
        inLanguage: 'en-IN',
        publisher: { '@id': ORG_ID },
      },
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
