/**
 * PageMeta - the per-page half of the document head.
 *
 * WHY THIS EXISTS. Thirteen public pages each declared the same three-line Head by hand:
 * a <title>, a <meta name="description">, and a keyed canonical. None of them declared
 * og: or twitter: tags, and only /grahak-os/ does. Everything else therefore inherited the
 * SITEWIDE share preview from _app.tsx, which means /contact/, /terms/, /privacy/,
 * /orders/, /bharat-rx/, /vayulok/ and all seven product pages shared ONE og:title and
 * ONE og:description between them - measured on the built export, fourteen routes previewed
 * as "Everyday AI, built for Bharat | WECARE.DIGITAL" with the company description.
 *
 * Every one of those pages already had good, owner-written title and description copy. The
 * share tags simply were not wired to it. So this component takes the strings the page
 * already passes and emits the whole set from them - no new copy, and no second place to
 * edit when the copy changes, which is the part that matters: a page whose og:title is a
 * hand-copied duplicate of its <title> drifts the first time one of them is edited.
 *
 * THE og: KEYS ARE LOAD-BEARING. next/head de-duplicates meta by `name`, `httpEquiv`,
 * `charSet` and `itemProp` - `property` is NOT on that list, so two og:title tags coexist
 * where two twitter:title tags collapse to one. /grahak-os/ shipped two of every og tag
 * for exactly this reason until matching keys were added on both sides. The keys here must
 * stay character-identical to the ones in src/pages/_app.tsx, or these tags will be added
 * alongside the sitewide ones instead of replacing them. Verify with:
 *   grep -o '"og:title"' out/contact/index.html | wc -l   # must be 1
 * twitter: tags need no key - they are keyed on `name` already.
 *
 * WHAT STAYS IN _app.tsx: og:type, og:image, og:image:width, og:image:height, og:site_name,
 * og:locale, twitter:card, twitter:image and the robots/verification/PWA block. Those are
 * genuinely sitewide and no page overrides them.
 */

import Head from 'next/head';

const SITE = 'https://wecare.digital';

interface PageMetaProps {
  /** The full <title>, brand suffix included. Used verbatim for og:title and twitter:title. */
  title: string;
  /** The meta description. Used verbatim for og:description and twitter:description. */
  description: string;
  /**
   * Route path WITH a leading and trailing slash, e.g. '/contact/'. next.config.js sets
   * trailingSlash, so the canonical form of every route except the root carries one; a
   * canonical pointing at the slashless spelling names a URL that 308-redirects, which is
   * a contradictory signal.
   */
  path: string;
  /**
   * OPTIONAL per-page structured data. Each entry is emitted as its own
   * <script type="application/ld+json"> inside this page's head. Only pass markup that
   * describes content ACTUALLY VISIBLE on the page - e.g. an FAQPage only when the questions
   * and answers are rendered. Marking up absent content violates Google's guidelines (the
   * reason a sitewide FAQ block was deleted from _app.tsx). Omit entirely on pages with none.
   */
  jsonLd?: Record<string, unknown>[];
  /**
   * OPTIONAL per-page social-preview card. When provided it OVERRIDES the sitewide square brand
   * card from _app.tsx for og:image / twitter:image on this page only (the keys below match
   * _app.tsx so next/head de-dupes rather than emitting duplicates). Pass a landscape ~1.91:1
   * asset and set card='summary_large_image' to show the large preview; a square asset should
   * keep the default 'summary'. Pages that omit `image` are completely unaffected.
   */
  image?: {
    url: string;
    alt: string;
    width?: number;
    height?: number;
    /** twitter:card type for this page. Defaults to 'summary_large_image' when an image is given. */
    card?: 'summary' | 'summary_large_image';
  };
}

export default function PageMeta( { title, description, path, jsonLd, image }: PageMetaProps ) {
  const url = `${SITE}${path}`;
  const twitterCard = image ? ( image.card || 'summary_large_image' ) : undefined;
  return (
    <Head>
      <title>{ title }</title>
      <meta name="description" content={ description } />
      {/* key="canonical" so this REPLACES the computed one from _app.tsx rather than adding
          a second. Two canonicals on a page is ambiguous, and the likeliest reading is that
          the page duplicates whichever one is listed first - a defect already fixed once
          here, when every public page shipped the site root as its first canonical. */}
      <link rel="canonical" key="canonical" href={ url } />
      <meta property="og:title" key="og:title" content={ title } />
      <meta property="og:description" key="og:description" content={ description } />
      <meta property="og:url" key="og:url" content={ url } />
      <meta name="twitter:title" content={ title } />
      <meta name="twitter:description" content={ description } />
      {/* Per-page social card. The keys MATCH _app.tsx's sitewide tags (og:image* keyed on
          `property`, twitter:* de-duped on `name`), so these REPLACE them on this page rather
          than adding a second set. Only emitted when a page passes `image`. */}
      { image && <meta property="og:image" key="og:image" content={ image.url } /> }
      { image?.width != null && <meta property="og:image:width" key="og:image:width" content={ String( image.width ) } /> }
      { image?.height != null && <meta property="og:image:height" key="og:image:height" content={ String( image.height ) } /> }
      { image && <meta property="og:image:alt" key="og:image:alt" content={ image.alt } /> }
      { image && <meta name="twitter:image" content={ image.url } /> }
      { image && <meta name="twitter:image:alt" content={ image.alt } /> }
      { twitterCard && <meta name="twitter:card" content={ twitterCard } /> }
      { ( jsonLd || [] ).map( ( node, i ) => (
        <script
          // eslint-disable-next-line react/no-danger
          key={ `ld-${i}` }
          type="application/ld+json"
          dangerouslySetInnerHTML={ { __html: JSON.stringify( node ) } }
        />
      ) ) }
    </Head>
  );
}
