import React from 'react';
import Head from 'next/head';
import { blogPageHref } from './BlogIndexView';
import { SITE_ENTITIES, ORG_ID, ld } from '../lib/schema';
import {
  SOCIAL_CARD_URL, SOCIAL_CARD_W, SOCIAL_CARD_H, SOCIAL_CARD_TYPE, SOCIAL_CARD_ALT, SHARE_CARD_TYPE,
} from '../config/share';

/**
 * Head for one page of the blog index.
 *
 * STRUCTURED DATA IS DECLARED HERE, not in _app.tsx.
 *
 * /blog/ is in `isContentPublic`, and _app.tsx renders its shared <Head> behind
 * `!isContentPublic` - so the Organization, WebSite, WebPage and BreadcrumbList graph every
 * other public route gets is deliberately suppressed on /blog/ and /post/[slug]/, to stop two
 * components emitting competing canonicals. The consequence went unnoticed once: /blog/ is in
 * the sitemap and indexable but shipped ZERO JSON-LD, while the structured data checker only
 * looked at six hardcoded routes and never asked about this one.
 *
 * THE GRAPH IS SELF-CONTAINED ON PURPOSE. It cannot reference the shared nodes by @id -
 * `#website` and `#organization` are defined in the <Head> that is suppressed here, so
 * pointing at them would emit references that resolve to nothing, which is worse than
 * omitting them. Publisher is therefore inlined.
 *
 * WHAT PAGINATION ADDED TO THIS FILE
 * ----------------------------------
 * EVERY PAGE IS SELF-CANONICAL. /blog/page/7/ canonicalises to itself, NOT to /blog/. It is
 * tempting to point all 35 pages at /blog/, and it is wrong: a canonical says "index this
 * other URL instead of me", so 810 posts whose only listing is on pages 2-35 would have no
 * indexable page linking to them at all. Google's own guidance on paginated sequences is that
 * each page is its own canonical.
 *
 * rel=prev/next IS STILL EMITTED although Google retired it as an indexing signal in 2019. It
 * remains the correct semantic relationship between these documents, browsers and reading
 * tools use it to offer "next page", and nothing costs anything by its presence.
 *
 * PAGES 2 AND UP ARE index,follow, not noindex. noindex on a paginated tail is the other
 * common mistake: it removes the only crawlable route to most of the corpus. What they do get
 * is a DISTINCT <title> and description carrying the page number, because 35 pages sharing one
 * title is what actually reads as duplicate content in a search result list.
 *
 * ONLY THE Blog NODE CARRIES THE POST COUNT, and it sits on page 1. The pages describe
 * themselves as parts of one Blog via `isPartOf`.
 *
 * EVERY LISTING PAGE NOW ALSO CARRIES AN ItemList, and this paragraph used to say it must not.
 * The reason given was that "repeating an itemListElement of 24 posts on every page would
 * describe 35 overlapping collections". That is factually wrong, and it was measured rather
 * than argued: across all 54 listing pages in the export - /blog/, /blog/page/2..35/,
 * /blog/topic/gastronomy/ and its 18 pages - ZERO posts appear on more than one listing page,
 * and all 1279 are linked from exactly one. The slices are perfectly DISJOINT, so an ItemList
 * per page describes 54 non-overlapping collections, each one exactly what that page contains.
 *
 * Without it, 54 pages declared themselves CollectionPage and then said nothing about what they
 * collected. ItemList is the property Google documents for that, and it is derived from the
 * same `posts` array the view renders, so a new post, a new page or a new category stream is
 * described the moment it exists - there is nothing to author and nothing to keep in step.
 *
 * `itemListOrder` is deliberately NOT emitted. The rendered order is carried by `position`,
 * which is true by construction; naming an order would be a claim about the sort that this
 * component does not perform and has not verified.
 */

const ORIGIN = 'https://wecare.digital';
const DESCRIPTION = 'Ideas, guides and updates from WECARE.DIGITAL.';

interface BlogIndexHeadProps {
  page: number;
  totalPages: number;
  /** Set on /blog/topic/<slug>/ - the category this stream lists. */
  topic?: string;
  topicHref?: string;
  /** Posts in this stream, for the description. */
  count?: number;
  /**
   * The posts THIS page lists, in the order it lists them. Only slug and title are needed, so
   * the prop stays satisfiable by any caller without reshaping BlogCard.
   *
   * Optional so a caller that genuinely has no list still renders a valid head rather than
   * throwing; the ItemList is simply omitted. All four listing routes pass it.
   */
  posts?: Array<{ slug: string; title: string }>;
}

/**
 * The ItemList node for one listing page, or null when there is nothing to list.
 *
 * `url` + `name` per entry rather than a nested Thing: that is the shape Google documents for a
 * summary listing page, and it keeps the node to what the page actually shows. `position` starts
 * at 1 and follows render order, so it is true without asserting a sort.
 */
const itemListFor = (
  url: string, posts: Array<{ slug: string; title: string }> | undefined,
): Record<string, unknown> | null => {
  if ( !posts?.length ) return null;
  return {
    '@type': 'ItemList',
    '@id': `${url}#itemlist`,
    numberOfItems: posts.length,
    itemListElement: posts.map( ( post, index ) => ( {
      '@type': 'ListItem',
      position: index + 1,
      url: `${ORIGIN}/post/${post.slug}/`,
      name: post.title,
    } ) ),
  };
};

const BlogIndexHead: React.FC<BlogIndexHeadProps> = ( { page, totalPages, topic, topicHref, count, posts } ) => {
  /*
   * A CATEGORY STREAM IS ITS OWN CANONICAL, like every paginated page. It has to be: the default
   * category is at /blog/ and the others are here, so these are the ONLY index pages listing
   * their posts. Canonicalising them at /blog/ would point at a page that does not contain them.
   */
  if ( topic ) {
    /* THE STREAMS PAGINATE NOW, so this branch has to carry a page number the way the /blog/
     * branch below already does. It used to assume one page per category and hardcode the
     * canonical to topicHref, which after the split would have pointed all four pages of
     * Gastronomy at page one - and a canonical means "index that URL instead of me", so the 66
     * posts listed only on pages 2 to 4 would have had no indexable page linking to them. That is
     * the exact mistake the note above records for /blog/page/N/; it applies here unchanged. */
    const streamFirst = `${ORIGIN}${topicHref}`;
    const url = `${ORIGIN}${blogPageHref( page, topicHref )}`;
    const onFirst = page <= 1;
    const title = onFirst
      ? `${topic} | WECARE.DIGITAL Blog`
      : `${topic} — page ${page} of ${totalPages} | WECARE.DIGITAL Blog`;
    const base = `${count ?? ''} ${count === 1 ? 'post' : 'posts'} on ${topic}, from WECARE.DIGITAL.`.trim();
    // A distinct description per page: several pages sharing one is what reads as duplicate
    // content in a results list, which is the reasoning the /blog/ branch records.
    const description = onFirst ? base : `${base} Page ${page} of ${totalPages}.`;
    const streamList = itemListFor( url, posts );
    const schema = {
      '@context': 'https://schema.org',
      '@graph': [
        {
          '@type': 'CollectionPage',
          '@id': `${url}#page`,
          url,
          name: title,
          description,
          inLanguage: 'en-IN',
          isPartOf: { '@type': 'Blog', '@id': `${ORIGIN}/blog/#blog`, url: `${ORIGIN}/blog/`, name: 'WECARE.DIGITAL Blog' },
          breadcrumb: { '@id': `${url}#breadcrumb` },
          // Points at the list of what this page actually collects. A CollectionPage with no
          // mainEntity names a collection and then declines to say what is in it.
          ...( streamList ? { mainEntity: { '@id': `${url}#itemlist` } } : {} ),
        },
        {
          '@type': 'BreadcrumbList',
          '@id': `${url}#breadcrumb`,
          // The category always points at the stream's FIRST page, and a page number is a fourth
          // crumb beyond it - the same shape the /blog/ branch below uses, where "Page N" is
          // appended rather than replacing "Blog". A trail whose category crumb pointed at page 3
          // would describe the stream as living there.
          itemListElement: onFirst
            ? [
              { '@type': 'ListItem', position: 1, name: 'Home', item: `${ORIGIN}/` },
              { '@type': 'ListItem', position: 2, name: 'Blog', item: `${ORIGIN}/blog/` },
              { '@type': 'ListItem', position: 3, name: topic, item: streamFirst },
            ]
            : [
              { '@type': 'ListItem', position: 1, name: 'Home', item: `${ORIGIN}/` },
              { '@type': 'ListItem', position: 2, name: 'Blog', item: `${ORIGIN}/blog/` },
              { '@type': 'ListItem', position: 3, name: topic, item: streamFirst },
              { '@type': 'ListItem', position: 4, name: `Page ${page}`, item: url },
            ],
        },
        // Appended by a filtered spread so a page with no posts emits exactly the two nodes it
        // emitted before, in the same order.
        ...( streamList ? [ streamList ] : [] ),
      ],
    };
    return (
      <Head>
        <title>{ title }</title>
        <meta name="description" content={ description } />
        <link rel="canonical" href={ url } />
        {/* RSS AUTODISCOVERY. Feed readers and search engines find the blog feed from this tag;
            it is generated post-build by scripts/generate-blog-rss.js and served at
            /blog/rss.xml. The same tag is on the /blog/ branch below and on every post page. */}
        <link rel="alternate" type="application/rss+xml" title="WECARE.DIGITAL Blog"
          href={ `${ORIGIN}/blog/rss.xml` } />
        { page > 1 && <link rel="prev" href={ `${ORIGIN}${blogPageHref( page - 1, topicHref )}` } /> }
        { page < totalPages && <link rel="next" href={ `${ORIGIN}${blogPageHref( page + 1, topicHref )}` } /> }
        <meta property="og:type" content="website" />
        <meta property="og:title" content={ title } />
        <meta property="og:description" content={ description } />
        <meta property="og:url" content={ url } />
        {/* THE LINK-PREVIEW CARD. A topic stream had none: og:image, twitter:card and
            twitter:image are declared in the sitewide Head in _app.tsx, and that Head is
            suppressed for every blog and post route because they declare their own - so these
            pages unfurled as a bare title and description everywhere they were shared.
            WRITTEN OUT RATHER THAN SHARED WITH THE BRANCH BELOW. next/head reads its direct
            children to build the tag list, and wrapping them in a component or helper puts a
            layer between it and the tags. Two explicit copies in one file is the cheaper
            mistake; the values themselves come from config/share.ts, so there is still one
            source for what the card IS.
            og:image:secure_url alongside og:image is for the older Facebook scrapers that
            look for it specifically; the URL is https either way. */}
        <meta property="og:image" content={ SOCIAL_CARD_URL } />
        <meta property="og:image:secure_url" content={ SOCIAL_CARD_URL } />
        <meta property="og:image:type" content={ SOCIAL_CARD_TYPE } />
        <meta property="og:image:width" content={ SOCIAL_CARD_W } />
        <meta property="og:image:height" content={ SOCIAL_CARD_H } />
        <meta property="og:image:alt" content={ SOCIAL_CARD_ALT } />
        <meta property="og:site_name" content="WECARE.DIGITAL" />
        <meta property="og:locale" content="en_IN" />
        {/* summary_large_image, because the card is 16:9. The small "summary" card crops a wide
            image to a square thumbnail, which is how a wordmark loses its ends. */}
        <meta name="twitter:card" content={ SHARE_CARD_TYPE } />
        <meta name="twitter:title" content={ title } />
        <meta name="twitter:description" content={ description } />
        <meta name="twitter:image" content={ SOCIAL_CARD_URL } />
        <meta name="twitter:image:alt" content={ SOCIAL_CARD_ALT } />
        <meta name="robots" content="index, follow, max-image-preview:large" />
        {/* THE SITE-LEVEL ENTITIES. The note at the top of this file explains why the graph
            below is self-contained and why `publisher` used to be inlined: _app.tsx's <Head> is
            suppressed on every blog route, so #organization did not exist here and an @id
            reference would have dangled. It is emitted here now, from lib/schema.ts, so the
            reference resolves and one company is described once instead of three times. */}
        { SITE_ENTITIES.map( ( entity, index ) => (
          <script key={ `site-entity-${index}` } type="application/ld+json"
            dangerouslySetInnerHTML={ ld( entity ) } />
        ) ) }
        <script type="application/ld+json" dangerouslySetInnerHTML={ ld( schema ) } />
      </Head>
    );
  }

  const canonical = `${ORIGIN}${blogPageHref( page )}`;
  const blogRoot = `${ORIGIN}/blog/`;
  const first = page === 1;

  const title = first
    ? 'Blog | WECARE.DIGITAL'
    : `Blog — page ${page} of ${totalPages} | WECARE.DIGITAL`;
  const description = first
    ? DESCRIPTION
    : `${DESCRIPTION} Page ${page} of ${totalPages}.`;
  const blogList = itemListFor( canonical, posts );

  const schema = {
    '@context': 'https://schema.org',
    '@graph': [
      first
        ? {
          '@type': 'Blog',
          '@id': `${blogRoot}#blog`,
          url: blogRoot,
          name: 'WECARE.DIGITAL Blog',
          description: DESCRIPTION,
          inLanguage: 'en-IN',
          publisher: { '@id': ORG_ID },
          breadcrumb: { '@id': `${canonical}#breadcrumb` },
          // What page 1 actually lists. The Blog node carries the corpus-wide count; this
          // names the 24 it shows.
          ...( blogList ? { mainEntity: { '@id': `${canonical}#itemlist` } } : {} ),
        }
        : {
          // A CollectionPage that declares itself part of the Blog, rather than a second
          // Blog node. Thirty-five Blog nodes at thirty-five URLs would each claim to be
          // the publication.
          '@type': 'CollectionPage',
          '@id': `${canonical}#page`,
          url: canonical,
          name: `WECARE.DIGITAL Blog — page ${page}`,
          description,
          inLanguage: 'en-IN',
          isPartOf: { '@type': 'Blog', '@id': `${blogRoot}#blog`, url: blogRoot, name: 'WECARE.DIGITAL Blog' },
          breadcrumb: { '@id': `${canonical}#breadcrumb` },
          ...( blogList ? { mainEntity: { '@id': `${canonical}#itemlist` } } : {} ),
        },
      {
        '@type': 'BreadcrumbList',
        '@id': `${canonical}#breadcrumb`,
        // The tail must be the canonical, slash included, or the breadcrumb describes a
        // URL that redirects. trailingSlash is on for this export.
        itemListElement: first
          ? [
            { '@type': 'ListItem', position: 1, name: 'Home', item: `${ORIGIN}/` },
            { '@type': 'ListItem', position: 2, name: 'Blog', item: blogRoot },
          ]
          : [
            { '@type': 'ListItem', position: 1, name: 'Home', item: `${ORIGIN}/` },
            { '@type': 'ListItem', position: 2, name: 'Blog', item: blogRoot },
            { '@type': 'ListItem', position: 3, name: `Page ${page}`, item: canonical },
          ],
      },
      ...( blogList ? [ blogList ] : [] ),
    ],
  };

  return (
    <Head>
      <title>{ title }</title>
      <meta name="description" content={ description } />
      <link rel="canonical" href={ canonical } />
      {/* RSS AUTODISCOVERY. See the topic branch above - same feed, generated post-build by
          scripts/generate-blog-rss.js and served at /blog/rss.xml. */}
      <link rel="alternate" type="application/rss+xml" title="WECARE.DIGITAL Blog"
        href={ `${ORIGIN}/blog/rss.xml` } />
      { page > 1 && <link rel="prev" href={ `${ORIGIN}${blogPageHref( page - 1 )}` } /> }
      { page < totalPages && <link rel="next" href={ `${ORIGIN}${blogPageHref( page + 1 )}` } /> }
      <meta property="og:type" content="website" />
      <meta property="og:title" content={ title } />
      <meta property="og:description" content={ description } />
      <meta property="og:url" content={ canonical } />
      {/* The same card as the topic branch above, and written out for the same reason - see the
          note there. Measured on the live site before this: /blog/ carried no og:image, no
          twitter:card and no twitter:image at all. */}
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
      {/* Same two entities as the topic branch above, for the same reason. */}
      { SITE_ENTITIES.map( ( entity, index ) => (
        <script key={ `site-entity-${index}` } type="application/ld+json"
          dangerouslySetInnerHTML={ ld( entity ) } />
      ) ) }
      <script type="application/ld+json" dangerouslySetInnerHTML={ ld( schema ) } />
    </Head>
  );
};

export default BlogIndexHead;
