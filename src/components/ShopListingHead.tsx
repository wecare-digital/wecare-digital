import React from 'react';
import Head from 'next/head';
import { shopListingPageHref } from '../content/shopProducts';
import { SITE_ENTITIES, ORG_ID, ld } from '../lib/schema';
import {
  SOCIAL_CARD_URL, SOCIAL_CARD_W, SOCIAL_CARD_H, SOCIAL_CARD_TYPE, SOCIAL_CARD_ALT, SHARE_CARD_TYPE,
} from '../config/share';

/**
 * Head for /shop/page/N/, and ONLY for /shop/page/N/.
 *
 * WHY PAGE 1 IS NOT HERE. /shop/ is a static pathname-keyed route, so _app.tsx reads
 * PUBLIC_PAGE_META['/shop'] and already emits its canonical, its title, its WebPage node and a
 * BreadcrumbList of [Home, Shop] - which is exactly the trail the listing renders. There is
 * nothing to add and a second <head> would compete with it.
 *
 * WHY PAGES 2..N MUST OWN THEIRS. router.pathname for a dynamic route is the PATTERN
 * '/shop/page/[page]', so a PUBLIC_PAGE_META entry would compute a canonical of
 * https://wecare.digital/shop/page/[page]/ and a WebPage @id to match. ShopProductHead.tsx
 * documents the same trap for /shop/[slug], and BlogIndexHead.tsx is the listing-shaped
 * precedent this file copies. The route is in the isContentPublic chain in _app.tsx instead,
 * which both suppresses that sitewide Head and makes this file responsible for the whole of it -
 * including the Organization and WebSite entities, which otherwise would not exist on the page.
 *
 * EVERY PAGE IS SELF-CANONICAL and index,follow. Pointing them all at /shop/ would say "index
 * that URL instead of me" about the only pages listing most of the shelf, and noindex would
 * remove the only crawlable route to it. What they get instead is a DISTINCT title and
 * description carrying the page number, because several pages sharing one title is what actually
 * reads as duplicate content in a results list.
 *
 * ONE CollectionPage, NOT a second WebPage for the catalogue: thirty page-2s each claiming to be
 * the shop is the defect BlogIndexHead records. It carries `name` AND `url` because
 * tools/audit/schemacheck.js requires both on a CollectionPage.
 *
 * NO ItemList, deliberately, and this is the one place this file diverges from BlogIndexHead. An
 * ItemList over a mixed set of products and services needs per-item types to be worth anything,
 * and the Product + Offer nodes already live on the /shop/<slug>/ item pages via ShopProductHead.
 * Adding one here would create a new schema contract with no test behind it.
 */

const ORIGIN = 'https://wecare.digital';
const SHOP_ROOT = `${ORIGIN}/shop/`;

/**
 * THE PAGE-NUMBERED COPY, derived from the one sentence PUBLIC_PAGE_META already publishes for
 * /shop so the page has one voice. Both sit inside the bounds tools/browser/seocheck.js enforces
 * (a title of 15 to 75 characters, a description of 50 to 170) at today's three pages and at two
 * digits.
 */
const BASE_DESCRIPTION =
  'Every WECARE.DIGITAL product and service on one page, each linking to its own page.';

interface ShopListingHeadProps {
  /** 2 or greater. Page 1 is /shop/ and is served by _app.tsx. */
  page: number;
  totalPages: number;
}

const ShopListingHead: React.FC<ShopListingHeadProps> = ( { page, totalPages } ) => {
  const canonical = `${ORIGIN}${shopListingPageHref( page )}`;
  const title = `Shop, page ${page} of ${totalPages} | WECARE.DIGITAL`;
  const description = `${BASE_DESCRIPTION} Page ${page} of ${totalPages}.`;

  const schema = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'CollectionPage',
        '@id': `${canonical}#page`,
        url: canonical,
        name: title,
        description,
        inLanguage: 'en-IN',
        // The WebPage _app.tsx emits for /shop/, by the @id it emits it under. Resolving rather
        // than dangling is the whole reason the shape is `${url}#webpage`.
        isPartOf: { '@type': 'WebPage', '@id': `${SHOP_ROOT}#webpage`, url: SHOP_ROOT, name: 'Shop' },
        breadcrumb: { '@id': `${canonical}#breadcrumb` },
        publisher: { '@id': ORG_ID },
      },
      {
        // ITEM FOR ITEM WHAT ShopListingView RENDERS. A graph describing a trail the page does
        // not render makes the rich result disappear with no error at all, which is why the two
        // are edited together.
        '@type': 'BreadcrumbList',
        '@id': `${canonical}#breadcrumb`,
        itemListElement: [
          { '@type': 'ListItem', position: 1, name: 'Home', item: `${ORIGIN}/` },
          { '@type': 'ListItem', position: 2, name: 'Shop', item: SHOP_ROOT },
          { '@type': 'ListItem', position: 3, name: `Page ${page}`, item: canonical },
        ],
      },
    ],
  };

  return (
    <Head>
      <title>{ title }</title>
      <meta name="description" content={ description } />
      <link rel="canonical" href={ canonical } />
      { page > 1 && <link rel="prev" href={ `${ORIGIN}${shopListingPageHref( page - 1 )}` } /> }
      { page < totalPages && <link rel="next" href={ `${ORIGIN}${shopListingPageHref( page + 1 )}` } /> }
      <meta property="og:type" content="website" />
      <meta property="og:title" content={ title } />
      <meta property="og:description" content={ description } />
      <meta property="og:url" content={ canonical } />
      {/* WRITTEN OUT AS DIRECT CHILDREN OF <Head>, not pulled into a helper component.
          next/head reads its direct children to build the tag list, so wrapping these in a
          component makes them vanish silently. The values come from config/share.ts, so there is
          still one source for what the card IS.
          og:image:secure_url alongside og:image is for the older Facebook scrapers that look for
          it specifically; the URL is https either way. */}
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
      <meta name="twitter:image" content={ SOCIAL_CARD_URL } />
      <meta name="twitter:image:alt" content={ SOCIAL_CARD_ALT } />
      <meta name="robots" content="index, follow, max-image-preview:large" />
      {/* The site-level entities. _app.tsx's Head is suppressed on this route, so #organization
          would not exist here and the publisher reference above would dangle. */}
      { SITE_ENTITIES.map( ( entity, index ) => (
        <script key={ `site-entity-${index}` } type="application/ld+json"
          dangerouslySetInnerHTML={ ld( entity ) } />
      ) ) }
      <script type="application/ld+json" dangerouslySetInnerHTML={ ld( schema ) } />
    </Head>
  );
};

export default ShopListingHead;
