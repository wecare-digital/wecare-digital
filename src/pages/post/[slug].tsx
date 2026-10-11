import type { GetStaticPaths, GetStaticProps } from 'next';
import type { ReactNode } from 'react';
import { Fragment, useEffect, useRef } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import ShareLinks from '../../components/ShareLinks';
import BlogContribution from '../../components/BlogContribution';
import {
  SOCIAL_CARD_URL, SOCIAL_CARD_W, SOCIAL_CARD_H, SOCIAL_CARD_TYPE, SOCIAL_CARD_ALT, SHARE_CARD_TYPE,
} from '../../config/share';
import { ORG_ID, ORIGIN, WEBSITE_ID, SITE_ENTITIES, ld } from '../../lib/schema';
import { extractRecipe, recipeSchema } from '../../lib/recipe-schema';
import { getPublicBlogPost, listPublicBlogPosts, PublicBlogPost } from '../../lib/public-blog';
import { postContext, type PostLink } from '../../lib/post-neighbours';
import RotatingHero, { CycleWord } from '../../components/RotatingHero';
import Breadcrumbs from '../../components/Breadcrumbs';
import BlogSearch from '../../components/BlogSearch';

/**
 * WHICH ACCENT A TAG GETS, DERIVED FROM THE TAG ITSELF RATHER THAN FROM ITS POSITION.
 *
 * The blog already cycles the contract's accent hues by position: .post-card steps
 * #3da35a, #2563eb, #9849e8 with nth-child(3n+...). That is right for a card in a stream,
 * where position is the only thing available and nobody expects card three to look like
 * card three on another page.
 *
 * It is wrong for a tag. The same tag appears across many posts, and position-based cycling
 * would colour "Chai" green on one post and blue on the next - which spends the colour
 * without buying the recognition it is for. Hashing the tag name makes a tag look the same
 * everywhere it appears, so the colour becomes a property of the tag rather than of the row.
 *
 * Deterministic and pure, so the server and the client compute the same value and hydration
 * does not mismatch - that is the reason this is a hash rather than a random pick or a
 * useState.
 *
 * FOUR HUES, NOT FIVE. Amber #f0a818 is the one the hero pills use that is excluded here: it
 * measures 2.04:1 on white, which is the ratio the design contract records as the reason it
 * was rejected for light surfaces. The other four all clear the 3:1 that WCAG 1.4.11 asks of
 * a graphic used to identify a control - green 3.19:1, blue 5.17:1, purple 4.72:1, red
 * 4.83:1 - so this palette is measured rather than picked.
 *
 * Verified against the real corpus: 433 distinct tags in the built export distribute
 * 112/108/108/105 across the four, which is close enough to even that no hue dominates a
 * post's row by accident.
 *
 * THE UNSIGNED SHIFT IS LOAD-BEARING, and this is the bug the first version shipped.
 * It used & 0xffffffff, which in JavaScript yields a SIGNED 32-bit integer - and a negative
 * remainder stays negative, because -5 % 4 is -1 in JS rather than 3. So tags hashing to a
 * negative value produced class names like tag-h-1 and tag-h-2, which match no rule, and
 * those pills silently fell back to the neutral grey border. Measured in the browser: of
 * three tags on one post, two were grey.
 *
 * It survived its own verification because that was written in Python, where & 0xffffffff is
 * UNSIGNED and the distribution came out even. The check and the code disagreed about the
 * language, not about the maths. The distribution figures above are re-measured in Node.
 */
const TAG_HUE_COUNT = 4;
const tagHue = ( tag: string ): number => {
  let h = 0;
  for ( let i = 0; i < tag.length; i += 1 ) h = ( h * 33 + tag.charCodeAt( i ) ) >>> 0;
  return h % TAG_HUE_COUNT;
};

/**
 * EVERY FIELD BELOW `post` IS OPTIONAL, and that is not defensiveness - it is what keeps
 * BlogDesign.test.tsx compiling. Its two post-page tests render <BlogPostPage post={ samplePost } />
 * with no other props, so a required prop here would break them, and they are the only guard on
 * this page's type rungs.
 * They are also genuinely absent in real cases: `newer` on the newest post in a stream, `older`
 * on the oldest, and all of them if the corpus fetch returns nothing during a build.
 */
interface Props {
  post: PublicBlogPost;
  newer?: PostLink;
  older?: PostLink;
  related?: PostLink[];
  streamHref?: string;
  streamLabel?: string;
}

interface RicosNode {
  type?: string;
  nodes?: RicosNode[];
  textData?: {
    text?: string;
    decorations?: Array<Record<string, any>>;
  };
  headingData?: { level?: number };
}

function textRun ( node: RicosNode, key: string ): ReactNode {
  let child: ReactNode = node.textData?.text || '';
  for ( const decoration of node.textData?.decorations || [] ) {
    const type = String( decoration.type || '' ).toUpperCase();
    if ( type === 'BOLD' ) child = <strong>{ child }</strong>;
    if ( type === 'ITALIC' ) child = <em>{ child }</em>;
    if ( type === 'UNDERLINE' ) child = <u>{ child }</u>;
    if ( type === 'STRIKETHROUGH' ) child = <s>{ child }</s>;
    if ( type === 'LINK' ) {
      const href = decoration.linkData?.link?.url;
      if ( href ) child = <a href={ href }>{ child }</a>;
    }
  }
  return <Fragment key={ key }>{ child }</Fragment>;
}

function inlineNodes ( nodes: RicosNode[] = [], prefix = 'inline' ): ReactNode[] {
  return nodes.map( ( node, index ) => {
    if ( node.type === 'TEXT' ) return textRun( node, `${prefix}-${index}` );
    return <Fragment key={ `${prefix}-${index}` }>{ inlineNodes( node.nodes || [], `${prefix}-${index}` ) }</Fragment>;
  } );
}

function listItemContent ( node: RicosNode, prefix: string ): ReactNode {
  return ( node.nodes || [] ).map( ( child, index ) => {
    if ( child.type === 'PARAGRAPH' || child.type === 'HEADING' ) {
      return <Fragment key={ `${prefix}-${index}` }>{ inlineNodes( child.nodes || [], `${prefix}-${index}` ) }</Fragment>;
    }
    return renderRicosNode( child, `${prefix}-${index}` );
  } );
}

function renderRicosNode ( node: RicosNode, key: string ): ReactNode {
  switch ( node.type ) {
    case 'PARAGRAPH':
      if ( !( node.nodes || [] ).length ) return <div key={ key } className="spacer" aria-hidden="true" />;
      return <p key={ key }>{ inlineNodes( node.nodes || [], key ) }</p>;
    case 'HEADING': {
      const level = Number( node.headingData?.level || 2 );
      if ( level >= 3 ) return <h3 key={ key }>{ inlineNodes( node.nodes || [], key ) }</h3>;
      return <h2 key={ key }>{ inlineNodes( node.nodes || [], key ) }</h2>;
    }
    case 'BLOCKQUOTE':
      return <blockquote key={ key }>{ ( node.nodes || [] ).map( ( child, index ) => renderRicosNode( child, `${key}-${index}` ) ) }</blockquote>;
    case 'BULLETED_LIST':
      return <ul key={ key }>{ ( node.nodes || [] ).map( ( child, index ) => renderRicosNode( child, `${key}-${index}` ) ) }</ul>;
    case 'ORDERED_LIST':
      return <ol key={ key }>{ ( node.nodes || [] ).map( ( child, index ) => renderRicosNode( child, `${key}-${index}` ) ) }</ol>;
    case 'LIST_ITEM':
      return <li key={ key }>{ listItemContent( node, key ) }</li>;
    case 'IMAGE':
    case 'GALLERY':
    case 'GIF':
    case 'VIDEO':
      return null;
    default:
      return <Fragment key={ key }>{ ( node.nodes || [] ).map( ( child, index ) => renderRicosNode( child, `${key}-${index}` ) ) }</Fragment>;
  }
}

function fallbackBlocks ( content: string ) {
  return content.split( /\r?\n/ ).map( line => line.trim() ).filter( Boolean );
}

function inlineFormat ( text: string ) {
  return text.split( /(\*\*[^*]+\*\*|\*[^*]+\*)/g ).filter( Boolean ).map( ( part, index ) => {
    if ( part.startsWith( '**' ) && part.endsWith( '**' ) ) {
      return <strong key={ index }>{ part.slice( 2, -2 ) }</strong>;
    }
    if ( part.startsWith( '*' ) && part.endsWith( '*' ) ) {
      return <em key={ index }>{ part.slice( 1, -1 ) }</em>;
    }
    return part;
  } );
}

/** Same four words and tints as /blog/ - this band is the blog's masthead, so it must not
 * say something different from the section it belongs to. */
const HERO_WORDS: CycleWord[] = [
  { word: 'clarity', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'practice', tint: '#fef3c7', dot: '#f0a818' },
  { word: 'meaning', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'change', tint: '#ede9fe', dot: '#9849e8' },
];

export default function BlogPostPage ( {
  post, newer, older, related = [], streamHref = '/blog/', streamLabel = 'Blog',
}: Props ) {
  const canonical = `https://wecare.digital/post/${post.slug}/`;
  const title = post.seoTitle || post.title;
  const description = post.metaDescription || post.excerpt || '';

  /**
   * THE ENTRANCE, RUN THE WAY THE HOME PAGE RUNS ITS OWN - see the reveal effect in
   * pages/index.tsx, whose rules these follow exactly.
   *
   * CSS SHIPS THE FINISHED STATE. The pre-animation state lives behind .is-armed, and script adds
   * that class only after confirming it can finish the job. So a reader with no JavaScript, a
   * crawler, or a webview where the bundle failed gets the share row, the pager and the related
   * cards fully visible rather than a permanently transparent block. Doing it the other way round
   * - opacity:0 in CSS, opacity:1 from script - is how a page ships an invisible section.
   *
   * IT ARMS THE ARTICLE BUT WATCHES THE SHARE ROW. The article starts at the top of the page and
   * is already intersecting on load, so observing it would fire the reveal immediately and the
   * animation would play off-screen where nobody sees it. The share row is the first element of
   * the tail, so it is the honest trigger for "the reader has reached the end".
   *
   * classList, NOT setState: this is a visual side effect that changes nothing React renders,
   * which is the documented use for an effect and avoids a cascading render. It is also what
   * keeps react-hooks/set-state-in-effect quiet.
   *
   * One-shot. It is an entrance, not a scroll effect, so the observer disconnects on the first
   * hit and scrolling back up does not replay it.
   */
  const shareRef = useRef<HTMLDivElement | null>( null );
  useEffect( () => {
    const el = shareRef.current;
    const article = el?.closest( 'article' );
    if ( !el || !article ) return;
    if ( typeof IntersectionObserver === 'undefined' ) return;
    // Asked before arming, so a reader who prefers less motion never enters the pre-state at all.
    if ( window.matchMedia( '(prefers-reduced-motion: reduce)' ).matches ) return;

    article.classList.add( 'is-armed' );
    const io = new IntersectionObserver(
      entries => {
        if ( entries.some( e => e.isIntersecting ) ) {
          article.classList.add( 'is-in' );
          io.disconnect();
        }
      },
      { threshold: 0.18 }
    );
    io.observe( el );
    return () => io.disconnect();
  }, [] );
  const richNodes = ( post.richContent?.nodes || [] ) as RicosNode[];
  const blocks = fallbackBlocks( post.content || '' );
  /**
   * THE STORED-SCHEMA BRANCH IS NOW VALIDATED RATHER THAN TRUSTED.
   *
   * `post.jsonLd` is `{}` for every post on the public surface — `seo-tools/wix.py` hardcodes
   * it — so this branch is dead today and the fallback below is what actually ships. The guard
   * matters anyway, because the old test was truthiness of the OBJECT: `{ blogPosting: {} }`
   * is truthy, so the day that pipeline is wired, a `{}` would have been emitted verbatim as a
   * JSON-LD block with no `@context` and no `@type`. An empty schema block is worse than none:
   * a validator reports it against the page rather than ignoring it.
   */
  const storedSchema = post.jsonLd?.blogPosting;
  const useStored = !!storedSchema
    && typeof storedSchema === 'object'
    && typeof ( storedSchema as Record<string, unknown> )[ '@type' ] === 'string';
  const articleSchema = useStored ? storedSchema : {
    '@context': 'https://schema.org',
    '@type': 'BlogPosting',
    '@id': `${canonical}#article`,
    headline: post.title,
    description,
    url: canonical,
    // `image` WAS ABSENT, ON ALL 1,279 POSTS, and it is the property that gates the Article
    // rich result — Google documents it as required, so without it every post was ineligible
    // no matter how complete the rest of the node was. The asset was already in scope on this
    // page and already used for og:image three lines below; the schema simply never got it.
    // ImageObject with dimensions rather than a bare URL, for the reason the logo carries
    // them: the object form is what the guidance documents.
    image: {
      '@type': 'ImageObject',
      url: SOCIAL_CARD_URL,
      width: Number( SOCIAL_CARD_W ),
      height: Number( SOCIAL_CARD_H ),
    },
    datePublished: post.publishedDate || undefined,
    dateModified: post.modifiedDate || post.publishedDate || undefined,
    author: { '@type': 'Organization', name: post.authorName || 'Anew by WECARE.DIGITAL' },
    // A REFERENCE now, not a second anonymous Organization. This used to inline
    // `{ name, url }` — no `@id`, no logo — because the real `#organization` node lives in
    // _app.tsx's <Head>, which is suppressed on this route. It is no longer suppressed
    // anywhere: ORGANIZATION is emitted below from lib/schema.ts, so this `@id` resolves.
    publisher: { '@id': ORG_ID },
    // Ties the article to the page carrying it. Absent before, and it is what stops the
    // BlogPosting reading as an entity that merely happens to be on this URL.
    // A COMPLETE WebPage node, not a typed stub. `{ '@type': 'WebPage', '@id': ... }` carries a
    // @type, so it asserts an entity rather than referencing one - and schemacheck.js correctly
    // failed it on all 1,279 posts for having no `name` or `url`. Completing it is the better
    // answer than removing the @type: a post route otherwise has no WebPage entity at all,
    // where every marketing route gets one from _app.tsx's graph.
    mainEntityOfPage: {
      '@type': 'WebPage',
      '@id': `${canonical}#webpage`,
      url: canonical,
      name: post.title,
      isPartOf: { '@id': WEBSITE_ID },
      breadcrumb: { '@id': `${canonical}#breadcrumb` },
    },
    // INLINE DEFINITION, NOT A BARE REFERENCE. `{ '@id': '…/blog/#blog' }` alone was the first
    // version of this line and `tools/audit/schemacheck.js` failed it on all 1,279 posts: the
    // full Blog node is only emitted on /blog/ page 1, so the reference dangled everywhere
    // else. Carrying @type/url/name makes it a partial restatement with consistent values,
    // which is exactly what BlogIndexHead.tsx does for the same node and for the same reason.
    isPartOf: {
      '@type': 'Blog',
      '@id': `${ORIGIN}/blog/#blog`,
      url: `${ORIGIN}/blog/`,
      name: 'WECARE.DIGITAL Blog',
    },
    inLanguage: 'en-IN',
  };
  /**
   * RECIPE STRUCTURED DATA, DERIVED RATHER THAN AUTHORED.
   *
   * 448 of the 1279 posts are recipes - every one with an "Ingredients" heading and a "Method"
   * heading, counted in the built export - and none of them was eligible for Google's Recipe
   * rich result, because all 1279 emitted BlogPosting and nothing else.
   *
   * extractRecipe() reads the same Ricos nodes this page renders, so this is automatic: a new
   * recipe post becomes eligible the moment it is published, with no field to remember and no
   * step for an author. A post without both lists gets nothing, which is what keeps the 831
   * essays out of the recipe index.
   *
   * It runs on `richNodes`, so posts that arrive through the markdown fallback are not covered.
   * That is the honest boundary and not an oversight: every recipe in the corpus renders through
   * the Ricos path, and inferring a recipe from loose lines of markdown would be guessing.
   */
  const recipeParts = extractRecipe( richNodes );
  const recipeJsonLd = recipeParts ? recipeSchema( {
    parts: recipeParts,
    name: post.title,
    description,
    canonical,
    // The same ImageObject the article node uses. Google documents image as REQUIRED for
    // Recipe, and one source for it means the two nodes cannot disagree.
    image: {
      '@type': 'ImageObject',
      url: SOCIAL_CARD_URL,
      width: Number( SOCIAL_CARD_W ),
      height: Number( SOCIAL_CARD_H ),
    },
    datePublished: post.publishedDate || undefined,
    authorName: post.authorName || undefined,
    publisherId: ORG_ID,
  } ) : null;

  const storedCrumbs = post.jsonLd?.breadcrumbList;
  const useStoredCrumbs = !!storedCrumbs
    && typeof storedCrumbs === 'object'
    && Array.isArray( ( storedCrumbs as Record<string, unknown> ).itemListElement );
  const breadcrumbSchema = useStoredCrumbs ? storedCrumbs : {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    // Addressable, so it is one named node rather than an orphan list. The two @graph
    // breadcrumbs elsewhere on the site already carry one; this was the odd one out.
    '@id': `${canonical}#breadcrumb`,
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://wecare.digital/' },
      { '@type': 'ListItem', position: 2, name: 'Blog', item: 'https://wecare.digital/blog/' },
      { '@type': 'ListItem', position: 3, name: post.title, item: canonical },
    ],
  };

  return (
    <>
      <Head>
        <title>{ title }</title>
        <meta name="description" content={ description } />
        <link rel="canonical" href={ canonical } />
        <meta name="robots" content={ post.robots || 'index, follow, max-image-preview:large' } />
        <meta property="og:type" content="article" />
        <meta property="og:title" content={ title } />
        <meta property="og:description" content={ description } />
        <meta property="og:url" content={ canonical } />
        <meta property="og:site_name" content="WECARE.DIGITAL" />
        <meta property="og:locale" content="en_IN" />
        {/* THE CARD THIS PAGE NEVER HAD. og:image, twitter:image and a large twitter:card live in
            the sitewide Head in _app.tsx, and that Head is suppressed for the five content routes
            because they declare their own - so a post, the single most shared kind of page on this
            site, unfurled with no image anywhere. Measured live before this change: og:image
            MISSING, twitter:image MISSING, twitter:card "summary".
            Values from config/share.ts so the card has one definition; see that file for why the
            marketing branch in _app.tsx still carries its own literals and what holds the two
            equal. */}
        <meta property="og:image" content={ SOCIAL_CARD_URL } />
        <meta property="og:image:secure_url" content={ SOCIAL_CARD_URL } />
        <meta property="og:image:type" content={ SOCIAL_CARD_TYPE } />
        <meta property="og:image:width" content={ SOCIAL_CARD_W } />
        <meta property="og:image:height" content={ SOCIAL_CARD_H } />
        <meta property="og:image:alt" content={ SOCIAL_CARD_ALT } />
        {/* WAS "summary", WHICH WAS THE WRONG CARD EVEN ONCE AN IMAGE EXISTED. The small card
            crops to a square thumbnail, and the asset is 16:9 - a wordmark loses both ends. */}
        <meta name="twitter:card" content={ SHARE_CARD_TYPE } />
        <meta name="twitter:title" content={ title } />
        <meta name="twitter:description" content={ description } />
        <meta name="twitter:image" content={ SOCIAL_CARD_URL } />
        <meta name="twitter:image:alt" content={ SOCIAL_CARD_ALT } />
        {/* THE SITE-LEVEL ENTITIES, which this route did not carry.
            _app.tsx's <Head> is suppressed for every blog and post route (isContentPublic), so
            Organization and WebSite were absent from all 1,279 posts and ~54 index pages - about
            98% of the indexable site. That is also why `publisher` here used to inline an
            anonymous copy instead of referencing #organization: the node genuinely did not
            exist on this page. Emitting it from lib/schema.ts fixes both at once, and there is
            no duplicate risk because the suppression still holds - this is the only Head on
            this route that carries them. */}
        { SITE_ENTITIES.map( ( entity, index ) => (
          <script key={ `site-entity-${index}` } type="application/ld+json"
            dangerouslySetInnerHTML={ ld( entity ) } />
        ) ) }
        <script type="application/ld+json" dangerouslySetInnerHTML={ ld( articleSchema ) } />
        <script type="application/ld+json" dangerouslySetInnerHTML={ ld( breadcrumbSchema ) } />
        {/* Emitted only when the post actually has both an ingredient list and a step list -
            see extractRecipe(). A separate script tag rather than a member of one @graph,
            matching how articleSchema and breadcrumbSchema are already emitted here. */}
        { recipeJsonLd
          ? <script type="application/ld+json" dangerouslySetInnerHTML={ ld( recipeJsonLd ) } />
          : null }
        { ( post.jsonLd?.faqSchema?.mainEntity?.length || 0 ) > 0 && (
          <script type="application/ld+json" dangerouslySetInnerHTML={ ld( post.jsonLd?.faqSchema ) } />
        ) }
      </Head>
      {/* THE BLOG'S MASTHEAD, ABOVE THE ARTICLE - option B, chosen by the owner from
          docs/post-layout-review.html.
          `subordinate` is not optional here: without it RotatingHero renders its own <main>
          and <h1>, and this page already has both. That would put two main landmarks and two
          h1s on all 824 posts, which fails MANY-MAIN at HIGH and H1-MANY in
          tools/audit/htmlcheck.js. Measured in the mock before the prop existed: 2 mains,
          2 h1s. With it the wrapper is a <section> and the headline an <h2>, styled by class
          so the 55px/600 rung is pixel-identical either way.
          NO badgeLabel, matching /blog/ and the home page: the header already states the
          brand, and repeating it directly beneath is what the home page removed.
          The trade is recorded rather than hidden: this band is the same on every post, so it
          is the blog's masthead and not the article's own content, and it moves the writing
          from 338px down to 812px. Both numbers are in the mock. */}
      <RotatingHero
        subordinate
        frame="Notes on"
        words={ HERO_WORDS }
        sub="Short pieces on the distinctions that change how a thing is seen."
        ariaLabel="WECARE.DIGITAL blog"
      />
      <main className="article-shell">
        <article>
          {/* A REAL TRAIL, replacing a single "← Blog" back link at 13px/650 - the only
              control on this page below the site's 12px/700 smallest UI rung. The page's own
              JSON-LD has always declared a BreadcrumbList; now the page shows one. */}
          <Breadcrumbs items={ [
            { label: 'Home', href: '/' },
            { label: 'Blog', href: '/blog/' },
            { label: post.title },
          ] } />
          {/* GET mode: the post list is not in this page, so the box navigates to /blog/?q=
              and the index filters. Same component, same markup, different mode. */}
          <BlogSearch />
          { post.category && <div className="category">{ post.category }</div> }
          <h1>{ post.title }</h1>
          {/* NO PUBLISHED DATE IN THE BYLINE, on owner instruction. It rendered beside the
              author as a formatted en-IN date and is gone from every blog and post surface.
              WHAT DELIBERATELY STAYS: datePublished and dateModified in the BlogPosting
              JSON-LD below. Those are machine-readable fields Google treats as recommended on
              an article, they are not shown to a reader, and stripping them would cost the
              date treatment in search and Discover while changing nothing on the page. The
              stored-schema branch could not be stripped from here anyway - when the API
              supplies post.jsonLd.blogPosting that object is emitted verbatim.
              publishedDate also still orders the corpus in lib/public-blog.ts, so the field is
              read in three places and printed in none.
              data-wc-no-translate MOVED TO THE WRAPPER now the time element has gone. It was
              pinned to the span so the date beside it could still translate; with only a
              proper noun left there is nothing in this row that should be translated. The
              reasoning for the name itself is unchanged: post.authorName is a person's or a
              brand's name, and the fallback is two brand names joined by "by" - translating
              one preposition is not worth rendering the two names as invented words. */}
          <div className="byline" data-wc-no-translate="true">
            { post.authorName || 'Anew by WECARE.DIGITAL' }
          </div>
          <div className="content">
            { richNodes.length > 0
              ? richNodes.map( ( node, index ) => renderRicosNode( node, `block-${index}` ) )
              : blocks.map( ( line, index ) => {
                if ( line.startsWith( '### ' ) ) return <h3 key={ index }>{ inlineFormat( line.slice( 4 ) ) }</h3>;
                if ( line.startsWith( '## ' ) ) return <h2 key={ index }>{ inlineFormat( line.slice( 3 ) ) }</h2>;
                if ( line.startsWith( '# ' ) ) return <h2 key={ index }>{ inlineFormat( line.slice( 2 ) ) }</h2>;
                return <p key={ index }>{ inlineFormat( line ) }</p>;
              } ) }
          </div>
          {/* TAGS ARE LINKS NOW, AND THEY GO WHERE TAGS ARE ALREADY USED.
              They were plain spans, so giving them a hover would have been an affordance for
              nothing - the trap Footer.tsx documents at .ft-tagline, where a hover was removed
              precisely because the line was not a link.
              There is no /blog/tag/<x>/ route and inventing one is not the answer, because the
              destination already exists: scripts/generate-blog-search-index.js records that
              `tags` is requested FOR SEARCH rather than for display - "Beverages", "Herbal Tea",
              "Chai", "Lemongrass" are tags on posts whose title and excerpt contain none of
              those words. So a tag linking to a search FOR ITSELF is the one destination that
              matches what the field is for.
              /blog/?q= is a real target, not a guess: BlogSearch is a form with
              action="/blog/" method="get" and name="q", and its own note says q is "the one
              /blog/ reads". It also works with JavaScript off, which is why this is a plain
              navigation rather than a click handler.
              next/link with :global() in the CSS below, matching .category-switch and
              .post-related-card - styled-jsx does not scope a composite component, so a
              className passed to Link would arrive unstyled. */}
          {/* nav + aria-label, copying .category-switch rather than adding a visible heading.
              A heading was tried first and is wrong here twice over: typecheck.js asserts every
              section h2 sits on the 40px/700 rung, so a 14px "Tagged" would either fail it or
              need a documented exception the way .lgd-toc-title does - and the row does not
              need a heading to be understood, it needs a NAME, which is what aria-label gives a
              landmark. */}
          { post.tags && post.tags.length > 0 && (
            <nav className="tags" aria-label="Tags on this post">
              { post.tags.map( tag => (
                <Link
                  key={ tag }
                  href={ `/blog/?q=${encodeURIComponent( tag )}` }
                  className={ `tag-h${tagHue( tag )}` }
                  aria-label={ `Search posts tagged ${tag}` }
                >{ tag }</Link>
              ) ) }
            </nav>
          ) }

          {/* SUBSCRIBE ON WHATSAPP - the in-page signup box was removed in favour of a single
              button that opens a WhatsApp conversation at this subscribe deep link. A real
              anchor, not a button+onClick: it leaves the site, so it must be middle-clickable,
              long-pressable and copyable.
              TEXT ONLY, no glyph: the WhatsApp logo inside the filled pill read as too busy, so
              the destination moves to the quiet `.blog-wa-note` microcopy below. This is the
              matched twin of the Contribute pill in BlogContribution.tsx - same lime object, same
              one-word label, same microcopy line. */}
          <a
            className="blog-wa-subscribe"
            href="https://wa.me/message/WUDPTMYSO6XII1"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Subscribe on WhatsApp"
          >
            <span>Subscribe</span>
          </a>
          {/* MICROCOPY: three words and a trailing arrow naming where the button goes. aria-hidden
              because the anchor's accessible name already carries "on WhatsApp". */}
          <p className="blog-wa-note" aria-hidden="true">Continue on WhatsApp →</p>

          {/* CONTRIBUTE - the voluntary-contribution block, placed AFTER Subscribe and BEFORE the
              share row so the reading order is content -> Tags -> Subscribe -> Contribute ->
              Share -> pager/related.
              IT IS THE SUBSCRIBE ANCHOR'S TWIN: one lime pill, the same WhatsApp glyph, one word,
              opening a DIFFERENT Meta message link (BYFLCAAMSZBXD1, not the WUDPTMYSO6XII1 above).
              There is no amount to choose, no form and no cart write - the block was a
              central-config amount pill with an honest-degradation seam until the owner replaced
              both of its button-looking controls with this single link; see the component's
              docblock for what was removed and why.
              It stays a component (components/BlogContribution.tsx) so the pill and its unit cases
              live in one place rather than inlined here. postId AND slug are still passed so the
              block is attributable (data-post-id); the component's heading is an h2, never an h1,
              so the page keeps its single h1 and htmlcheck's H1-MANY guard is satisfied. It does
              NOT take the shareRef - that stays on .post-share below, which is the
              IntersectionObserver reveal sentinel. */}
          <BlogContribution postId={ post.id } slug={ post.slug } />

          {/* SHARE, AT THE END OF THE READING RATHER THAN THE START.
              A share control above the article asks a reader to recommend something they have not
              read yet; the end of the piece is where the intent actually exists, and it is where
              the page already puts its other outbound controls - the pager and the related cards
              follow immediately below. One row, one place: a second copy under the title would be
              two controls competing to do one job.
              canonical, NOT router.asPath: what gets shared has to be the address the page
              declares as its own, without a utm string or a #hash the reader happened to arrive
              with. post.title rather than the seoTitle, because the seoTitle carries the
              " | WECARE.DIGITAL" suffix that belongs in a browser tab, not in a WhatsApp message
              where og:site_name already says whose link it is.
              This div is also the sentinel the reveal effect observes - see the note above. */}
          <div className="post-share" ref={ shareRef }>
            <ShareLinks url={ canonical } title={ post.title } />
          </div>

          {/* WALKING THE STREAM, ONE POST AT A TIME.
              Until now the only way out of a post was back up to the listing, so reading two in a
              row cost a round trip through /blog/ and a hunt for where you had got to.

              IT MIRRORS THE INDEX PAGER ON PURPOSE - the same rel=prev/next, the same
              "dead direction is rendered, not omitted" rule, the same 44px/12px-radius/#1a3a2a
              rung. Two different pagination idioms on one blog would read as two products.

              NEWER/OLDER RATHER THAN PREVIOUS/NEXT, because that is what /blog/ already calls
              these two directions, and "previous post" is ambiguous in a newest-first list - it
              means the one published before this, which is the one BELOW it. The rel attributes
              still say prev/next: those describe position in the document sequence, and the
              sequence is newest-first, so prev is the newer post. Same mapping the index uses.

              THE DEAD END IS RENDERED AND aria-hidden. Rendering it keeps the two boxes the same
              size so the row does not reflow between posts, and aria-hidden stops a screen reader
              announcing a control that does nothing. Copied from .pager-step.is-off. */}
          <nav className="post-nav" aria-label="Newer and older posts">
            { newer
              ? <Link className="post-nav-step is-prev" rel="prev" href={ `/post/${newer.slug}/` }>
                <span className="post-nav-dir"><i className="post-nav-mark" aria-hidden="true" />Newer</span>
                <span className="post-nav-name">{ newer.title }</span>
              </Link>
              : <span className="post-nav-step is-prev is-off" aria-hidden="true">
                <span className="post-nav-dir"><i className="post-nav-mark" />Newer</span>
                <span className="post-nav-name">This is the newest</span>
              </span> }
            { older
              ? <Link className="post-nav-step is-next" rel="next" href={ `/post/${older.slug}/` }>
                <span className="post-nav-dir">Older<i className="post-nav-mark" aria-hidden="true" /></span>
                <span className="post-nav-name">{ older.title }</span>
              </Link>
              : <span className="post-nav-step is-next is-off" aria-hidden="true">
                <span className="post-nav-dir">Older<i className="post-nav-mark" /></span>
                <span className="post-nav-name">This is the oldest</span>
              </span> }
          </nav>

          {/* RELATED BY SHARED TAGS, WEIGHTED - see src/lib/post-neighbours.ts for the scoring and
              the measurement behind it. Briefly: all 914 posts carry tags and nothing else on the
              record is a relatedness signal, so tags are it; each shared tag is worth 1/(posts
              carrying it), so a specific overlap beats a broad one and every post in a category
              does not end up with the same three neighbours.

              h2 AT THE EYEBROW RUNG. It is a real heading because it labels a section and a
              reader navigating by heading should find it, and it is 12px/700/.08em uppercase
              because it is furniture rather than a claim - the same thing .lgd-toc-title does on
              /grahak-os/ and the same declaration .home-close-eyebrow and Breadcrumbs use. The
              card titles below are h3, so the page's outline stays h1 > h2 > h3.

              THE CARDS ARE THE INDEX'S CARDS: 1px #e5e7eb, radius 14px, 23px/700 heading. The
              border is on the li and the link is the heading inside it, matching .post-card
              exactly - which is also what keeps the 1px-static / 2px-hoverable hairline rule
              intact, since the box is not the thing being hovered. */}
          { related.length > 0 && (
            <section className="post-related" aria-labelledby="post-related-title">
              <h2 className="post-related-title" id="post-related-title">More in { streamLabel }</h2>
              <ul className="post-related-list">
                { related.map( item => (
                  <li key={ item.slug } className="post-related-card">
                    <h3><Link href={ `/post/${item.slug}/` }>{ item.title }</Link></h3>
                  </li>
                ) ) }
              </ul>
              {/* Back to the listing this post is actually on - /blog/ for the default category,
                  /blog/topic/<slug>/ for the others. The same branch BlogIndexView uses for its
                  pills, so the link cannot point at a listing that does not contain this post. */}
              <Link className="post-related-all" href={ streamHref }>
                All { streamLabel } posts<i className="post-nav-mark" aria-hidden="true" />
              </Link>
            </section>
          ) }
        </article>
      </main>
      <style jsx>{`
        /* padding-top is 40px, not 156px: the hero above now owns the header offset. */
        .article-shell{max-width:1300px;margin:0 auto;padding:40px 24px 96px;color:#1a1a1a;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
        article{max-width:700px;margin:0 auto}
        /* .back rules removed with the link - Breadcrumbs replaced it. */
        /* THE SAME BADGE AS THE INDEX CARD'S, SO IT GETS THE SAME TREATMENT.
           A reader meets this category on the listing card and again at the top of the post;
           they were the same component in two different styles, which is the kind of gap that
           reads as a rendering bug rather than a design. Both are now BrandBadge's rung:
           14px/600/-.125px, #d1f470 fill, #1a3a2a type, no border. See the longer note at
           .category in BlogIndexView.tsx for why identity takes the fill and not the .22
           tint - the short version is that .22 composites to a barely-not-white wash. */
        .category{display:inline-block;background:#d1f470;color:#1a3a2a;border-radius:999px;padding:6px 12px;font-size:14px;font-weight:600;letter-spacing:-.125px;margin-bottom:18px}
        h1{font-size:clamp(36px,4.3vw,60px);line-height:1.04;letter-spacing:-0.04em;color:rgba(0,0,0,.95);margin:0 0 20px;font-weight:600;text-wrap:balance;max-width:20ch}
        /* AUTHOR ONLY NOW, so the row is no longer a row. The flex, the gap and the wrap all
           existed to lay out two children - the author and the date - and with the date gone
           they described a layout that cannot happen.
           12px/600 is the site's smallest UI rung; the old 13px sat below every other piece of
           furniture on this page, which is the same complaint that retired the 13px/650 back
           link. rgba(0,0,0,.54) is the public palette's dim value, replacing 6b7280 - a
           dashboard token from tokens.css that had no business on a public page. */
        .byline{font-size:12px;font-weight:600;letter-spacing:.01em;line-height:1.4;color:rgba(0,0,0,.54);margin-bottom:40px}
        .content{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
        .content :global(p),
        .content :global(li){font-size:20px;line-height:1.55;letter-spacing:-.125px;font-weight:400;color:rgba(0,0,0,.898)}
        .content :global(p){margin:0}
        .content :global(p + p){margin-top:28px}
        .content :global(.spacer){height:28px}
        .content :global(h2){font-size:30px;line-height:1.15;letter-spacing:-.6px;color:rgba(0,0,0,.95);margin:48px 0 20px;font-weight:700}
        .content :global(h3){font-size:23px;line-height:1.3;color:rgba(0,0,0,.95);margin:36px 0 16px;font-weight:700}
        .content :global(h2 + p),.content :global(h3 + p){margin-top:0}
        .content :global(ul),.content :global(ol){margin:28px 0;padding-inline-start:1.4em}
        .content :global(li + li){margin-top:10px}
        .content :global(blockquote){margin:36px 0;padding:2px 0 2px 22px;border-inline-start:3px solid #d1f470;font-size:21px;line-height:1.5;letter-spacing:-.125px;font-weight:400;color:rgba(0,0,0,.898)}
        .content :global(blockquote p){font:inherit;color:inherit;letter-spacing:inherit}
        .content :global(a){color:#1a3a2a;text-underline-offset:3px}
        .content :global(a:hover){text-decoration-thickness:2px}
        .content :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px;border-radius:2px}
        .content :global(strong){font-weight:700}
        /* TAG PILLS, ON THE HOME PAGE'S PILL LANGUAGE.
           These were 11px on a #f3f4f6 fill with no border, which made them the only pill on
           the site that did not look like one. Measured against the design contract, four
           things were off:
           1. #f3f4f6 is off-palette. The palette's grey is #e5e7eb, and this repo has already
              retired #4b5563 and #9ca3af from the same Tailwind family for reading cooler than
              the neutrals beside them.
           2. No border at all, where every pill in this language carries a hairline. The rule
              is weight-as-meaning: 2px means hoverable, 1px means static. A tag is a plain
              span with no hover, so 1px is the correct half of that rule - the same weight
              .trust-card uses.
           3. 11px is below every documented rung. The label rung is 14px, which is also what
              BrandBadge uses, so 14px lands them on an existing level rather than inventing a
              fifth one. Tracking -.125px matches that rung; weight stays 400 because these are
              metadata, not identity - the contract's label spec is plain 14px/400.
           4. It was the one contrast miss on the page. rgba(0,0,0,.54) over #f3f4f6 measured
              4.49:1, which fails the 4.5:1 AA minimum for normal text by 0.01. The same label
              colour over #fff measures 4.59:1 and passes, so moving to the palette fixed the
              contrast as a side effect rather than needing a darker grey.
           The wrapper already used the palette hairline and is unchanged. */
        /* ONE LINE THAT SCROLLS, NOT A BLOCK THAT WRAPS.
           This was flex-wrap:wrap, so on a phone a post with six tags grew the row to three
           lines and pushed the footer down; on a landscape phone it wrapped for no reason at
           all, because the width was there and the row simply refused to use it. nowrap plus
           overflow-x:auto keeps it to a single line at every width and lets the row scroll
           instead - which is exactly what .category-switch on /blog/ already does, so this is
           the site's existing answer to the same problem rather than a new one.

           DIRECTION IS NOT HARD-CODED. overflow-x on a flex row follows the document's dir
           so under the RTL languages SupportWidget switches to, the row starts at the right and
           scrolls leftward with no separate rule. That is why there is no direction or
           margin-left declaration here - a logical layout gets RTL for free, and rtlcheck asserts it.

           padding-bottom:6px is for the FOCUS RING, not for looks. A scroll container clips its
           children, and these pills carry a 3px outline at 2px offset; without the room the ring
           on a focused tag is sliced off at the container's edge. .category-switch carries the
           same 6px for the same reason. -2px top padding does the same for the hover lift.

           scrollbar-width:thin rather than hidden: a row that scrolls should say so. Hiding the
           bar leaves a mouse-only user with no indication there is more to the right. */
        .tags{
          display:flex;flex-wrap:nowrap;gap:8px;overflow-x:auto;
          margin-top:52px;padding:26px 0 6px;border-top:1px solid #e5e7eb;
          scrollbar-width:thin;align-items:center;
        }
        /* 2px, not 1px - and that change is the whole point of making these links.
           The hairline rule is weight-as-meaning: 2px means hoverable, 1px means static. These
           were spans at 1px, correctly, because nothing happened when you moused over them. Now
           that each one navigates to a search for itself, it is a hoverable control and takes
           the 2px edge that .pill, .pp-pill and .category-switch all carry.
           :global() because these are next/link, and styled-jsx does not scope a composite
           component - the same reason .category-switch and .post-related-card use it. */
        .tags :global(a){
          flex:0 0 auto;display:inline-flex;align-items:center;gap:7px;
          font-size:14px;font-weight:400;letter-spacing:-.125px;
          background:#fff;border:2px solid #e5e7eb;border-radius:999px;
          padding:6px 13px;color:rgba(0,0,0,.54);text-decoration:none;white-space:nowrap;
          transition:background-color .2s,border-color .2s,color .2s,transform .2s,box-shadow .2s;
        }
        /* THE DOT IS THE HOME HERO PILL'S OTHER HALF.
           Those pills are a pale tint with a saturated dot of the same hue. The dot travels
           here; the tint does not, and that is a contrast decision rather than a stylistic
           one. The label is rgba(0,0,0,.54), which measures 4.61:1 on white and clears the
           4.5:1 AA minimum for normal text with almost nothing to spare - over a pale tint it
           drops under. That is not hypothetical: these pills were on #f3f4f6 until recently
           and measured 4.49:1, failing by 0.01. So the ground stays white and the hue arrives
           as a dot and a border instead.
           A pseudo-element, so it is decorative by construction and never reaches the
           accessibility tree - the same reason the hero dot carries aria-hidden. */
        .tags :global(a)::before{
          content:'';flex:0 0 auto;width:7px;height:7px;border-radius:50%;
          background:#e5e7eb;transition:background-color .2s;
        }
        /* THE HUE IS IN THE DOT ONLY. THE BORDER STAYS THE NEUTRAL HAIRLINE.
           An earlier pass put the accent on the border as well, and it was too loud: a 2px
           saturated edge runs the whole perimeter, so three or four tags in different hues
           sitting side by side competed with the post they belong to instead of labelling it.
           The dot is 7px and carries the same information for a fraction of the ink.
           There is a consistency argument too, and it is the stronger one. Every other pill in
           this design language rests on 2px #e5e7eb - .pill, .pp-pill and .category-switch all
           do. A coloured resting edge made the tags the only pill on the site with one, which
           is the opposite of matching the home page. Neutral border, coloured dot: quieter AND
           more consistent, rather than a trade between the two.
           What does not change is the split the contract cares about - accent for identity,
           lime for interaction. Hover still swaps the border to lime, and because the resting
           border is now neutral that swap reads more clearly than it did against a saturated
           hue. .post-card keeps its accent on the border because there it is a single 3px
           inline-start edge on a large card, not a ring around a 34px pill. */
        .tags :global(.tag-h0)::before{background:#3da35a}
        .tags :global(.tag-h1)::before{background:#2563eb}
        .tags :global(.tag-h2)::before{background:#9849e8}
        .tags :global(.tag-h3)::before{background:#dc2626}
        /* THE HOME PAGE'S HOVER, EXACTLY. Lime border, the .22 state tint, a 2px lift and the one
           shadow this design language uses - the same four properties .category-switch and the
           home closing CTA move, at the same .2s. The label also goes from the muted
           rgba(0,0,0,.54) to solid #1a3a2a, because a control being pointed at should read as
           active rather than as quiet metadata: 12.48:1 on the tint.
           Anchored on :hover AND :focus-visible so a keyboard user gets the same feedback a
           mouse user does, which is the split .lgd-toc-link needed for the opposite reason. */
        .tags :global(a:hover),.tags :global(a:focus-visible){
          border-color:#d1f470;background:rgba(209,244,112,.22);color:#1a3a2a;
          transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12);
        }
        .tags :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:2px}
        /* SUBSCRIBE ON WHATSAPP BUTTON. Same object as the home-page CTA: 52px minimum
           height, 28px inline padding, a 2px dark-green edge, 50px pill radius, 17px/600
           label, and the same white hover inversion. TEXT ONLY now - the glyph was dropped,
           so the destination lives in the .blog-wa-note microcopy below rather than on the
           button. The visible label is Subscribe; the full WhatsApp context stays in the
           accessible name. This mirrors the Contribute pill (.bc-cta) exactly. */
        .blog-wa-subscribe{
          display:inline-flex;align-items:center;justify-content:center;margin-top:44px;
          min-height:52px;padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;
          background:#d1f470;color:#1a3a2a;font-size:17px;font-weight:600;
          text-decoration:none;transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        .blog-wa-subscribe:hover{background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .blog-wa-subscribe:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
        /* MICROCOPY under the Subscribe pill - the twin of .bc-cta-note in BlogContribution.tsx.
           Very small, quiet, naming the destination the button no longer shows with a glyph.
           HOVER CARRIES THE FOOTER TAGLINE'S COLOUR SWEEP (see .ft-tagline in Footer.tsx and the
           long note on .bc-cta-note in BlogContribution.tsx): a band of brand green runs through
           the muted text on hover. Clip + transparent fill live under :hover only, so the resting
           line stays solid grey rather than invisible. Both gradient stops are measured on white
           (4.61:1 and 12.48:1), so the band only darkens the text, never washes it out. */
        /* SOLID GREY AT REST, ONE-SHOT LIME SWEEP ON HOVER - like the footer tagline, which runs
           its sweep once and stops. The continuous looping was removed on owner instruction: a
           line of quiet microcopy that keeps moving on its own pulls the eye. The
           clip/gradient/transparent-fill now live ONLY under :hover, so the resting line is plain
           solid grey; on hover the band passes through the glyphs a single time (1 iteration,
           forwards) and settles. Both stops are on white (4.61:1 and 12.48:1), so the band only
           darkens the text. */
        .blog-wa-note{
          font-size:13px;line-height:1.4;color:rgba(0,0,0,.54);margin:10px 0 0;
        }
        .blog-wa-note:hover{
          background-image:linear-gradient(100deg,
            rgba(0,0,0,.54) 44%, #1a3a2a 50%, rgba(0,0,0,.54) 56%);
          background-size:300% 100%;background-repeat:no-repeat;
          -webkit-background-clip:text;background-clip:text;
          -webkit-text-fill-color:transparent;
          animation:blog-wa-note-sweep 1.1s cubic-bezier(.22,.61,.36,1) 1 forwards;
        }
        @keyframes blog-wa-note-sweep{from{background-position:100% 0}to{background-position:-100% 0}}
        /* Motion-sensitive readers get the line static and solid grey: WCAG 2.2.2 carve-out. */
        @media(prefers-reduced-motion:reduce){
          .blog-wa-note{
            animation:none;background-image:none;
            -webkit-text-fill-color:currentColor;color:rgba(0,0,0,.54);
          }
        }
        /* The share row sits in the same hairline rhythm as the tags above it and the pager below
           - 24px of air under a 1px e5e7eb rule - so the tail of the page reads as three bands of
           one object rather than three unrelated blocks. The controls style themselves; see
           components/ShareLinks.tsx. */
        .post-share{margin-top:44px;padding-top:24px;border-top:1px solid #e5e7eb}

        /* THE ENTRANCE, AND THE FINISHED STATE IS THE DEFAULT.
           Everything below is scoped to article.is-armed, a class the page adds only after
           confirming an IntersectionObserver exists and the reader has not asked for less motion.
           Without it these three blocks are simply visible - which is what a crawler, a
           no-JavaScript reader and a failed bundle all get. The home page's reveal is built the
           same way and records why: the inverse, hiding in CSS and showing from script, is how a
           page ships a section nobody can see.
           14px and .56s cubic-bezier(.22,.61,.36,1) are the home page's own reveal values, not new
           ones - the footer tagline and the closing points use the same pair. */
        article.is-armed .post-share,
        article.is-armed .post-nav,
        article.is-armed .post-related{
          opacity:0;transform:translateY(14px);
          transition:opacity .56s cubic-bezier(.22,.61,.36,1),transform .56s cubic-bezier(.22,.61,.36,1);
        }
        article.is-armed.is-in .post-share,
        article.is-armed.is-in .post-related,
        article.is-armed.is-in .post-nav{opacity:1;transform:none}
        /* Staggered in reading order, with the home page's own .09s-ish spacing between steps, so
           the three arrive as a sequence rather than a single block appearing. */
        article.is-armed.is-in .post-nav{transition-delay:.1s}
        article.is-armed.is-in .post-related{transition-delay:.2s}
        /* THE ESCAPE HATCH, AND IT IS NOT OPTIONAL. These blocks are nothing but links. If the
           observer never fires - a short viewport, a browser that resolves the threshold
           differently, a reader who tabs straight from the header to the end of the article
           without scrolling - a keyboard reader would be moving focus into invisible controls.
           focus-within reveals the tail the moment anything inside it takes focus. The home page
           carries the same hatch on its closing band for the same reason. */
        article.is-armed:focus-within .post-share,
        article.is-armed:focus-within .post-nav,
        article.is-armed:focus-within .post-related{opacity:1;transform:none}

        /* THE NEWER/OLDER PAGER. Every value is lifted from .pager-step on the index rather than
           chosen again: 2px rgba(26,58,42,.22) border because a hoverable edge is 2px on this
           site and a static one is 1px, radius 12px, colour 1a3a2a, the lime .28 hover tint, and
           the solid-1a3a2a focus ring at offset 2px that the index pager uses.
           44px is the WCAG 2.5.8 floor for a touch target and it is a floor, not the height - the
           padding and the two lines take these well past it.
           Two equal columns, so the pair reads as one control and neither box changes size when
           the titles differ in length. text-align on the older half is logical (end, not right)
           so a mirrored page does not push it the wrong way. */
        /* THE STEPS GO THROUGH :global() BECAUSE THEY ARE next/link, and this is not a style
           preference - it is the difference between these rules applying and not applying.
           styled-jsx attaches its scoping class only to lowercase DOM tags it can see here, never
           to a capitalised component, so <Link className="post-nav-step"> renders
           class="post-nav-step" with no jsx- hash and a plain .post-nav-step rule matches nothing.
           The is-off placeholders are <span>, so those WOULD have been styled and the live links
           would not - a pager where only the dead halves look like buttons. The blog index pager
           had exactly this bug and shipped with it; see the long note in BlogIndexView.tsx.
           Scoped under .post-nav, which is a <nav> in this file and does carry the hash, so these
           compile to .jsx-xxx.post-nav .post-nav-step and cannot leak. Same idiom as
           .content :global(p) above. */
        .post-nav{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:52px;padding-top:24px;border-top:1px solid #e5e7eb}
        .post-nav :global(.post-nav-step){
          display:flex;flex-direction:column;gap:5px;min-height:44px;padding:14px 16px;
          border:2px solid rgba(26,58,42,.22);border-radius:12px;
          color:#1a3a2a;text-decoration:none;
        }
        /* .22, not .28 - hover is transient state, which is precisely the role the .22 tint
           exists for. .28 was an alpha the language does not contain. */
        .post-nav :global(.post-nav-step:hover){background:rgba(209,244,112,.22)}
        .post-nav :global(.post-nav-step:focus-visible){outline:3px solid #1a3a2a;outline-offset:2px}
        .post-nav :global(.post-nav-step.is-off){border-color:#e5e7eb;color:rgba(0,0,0,.32);cursor:default}
        .post-nav :global(.post-nav-step.is-next){align-items:flex-end;text-align:end}
        /* The site's 12px/700/.08em eyebrow rung, same as .post-related-title below. */
        .post-nav :global(.post-nav-dir){display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
        /* THE DIRECTION MARK IS DRAWN, NOT TYPED. These labels read "← Newer" and "Older →" with
           literal U+2190 / U+2192, and with the webfont unavailable both rendered as tofu next to
           legible text - confirmed by comparing their canvas advance width against a private-use
           codepoint with no glyph anywhere: identical, so nothing in the fallback chain covered
           them. A rotated border box cannot fall back to a missing glyph.
           Same technique as the breadcrumb chevron and the terminal's play/pause marks, which
           exist for this reason. currentColor so it dims with the is-off text for free. */
        .post-nav :global(.post-nav-mark){
          width:6px;height:6px;flex:0 0 auto;
          border-top:2px solid currentColor;border-right:2px solid currentColor;
        }
        .post-nav :global(.is-prev .post-nav-mark){transform:rotate(-135deg)}
        .post-nav :global(.is-next .post-nav-mark){transform:rotate(45deg)}
        /* 16px/600 is the index pager's own size for a control label. Two lines maximum, because
           a long title in a half-width box would otherwise set the height of the whole row. */
        .post-nav :global(.post-nav-name){
          font-size:16px;font-weight:600;line-height:1.3;
          display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
        }

        /* RELATED POSTS, REBUILT. This was one column of title-only boxes at every width -
           three stacked bars inside a 700px measure - which reads as a bordered link list
           rather than as cards, and it was the least considered block on the page.
           TWO COLUMNS, WITH THE THIRD CARD SPANNING. RELATED_COUNT is 3, so a plain
           two-column grid leaves a half-width orphan on the second row; letting an odd last
           card take the whole measure makes that shape deliberate instead of accidental, and
           needs no change to post-neighbours.ts or to the payload it ships per page.
           THE HEADING IS THE HOME CARD RUNG - 22px/700/1.27/-.25px on solid black - the same
           one the listing cards now use, so a related card and a listing card are recognisably
           the same object. It was 23px/1.22/-.3px, a size that exists nowhere else on the site.
           THE 3px SPINE IN GREEN, BLUE, PURPLE is the home page's accent device, in the
           contract's order, matching the listing grid. Three cards, three hues, and the set is
           closed - amber measured 2.04:1 and was rejected.
           HOVER AND FOCUS ARE THE HOME CTA'S: a 2px lift with the single permitted shadow, and
           an opaque 1a3a2a ring replacing the rgba(26,58,42,.25) one that failed WCAG 1.4.11 at
           1.51:1 against white.
           THE PADDING STAYS ON THE ANCHOR. It used to sit on the li, which left the link as
           tall as one line of text - measured 28px at 1280 and 25px at 390 - so the card looked
           like a button and only the middle third of it responded. The 1px border stays on the
           li because that is the static frame; the spine replaces it on one edge only, so the
           1px-static / 2px-hoverable rule is untouched. */
        .post-related{margin-top:44px;padding-top:24px;border-top:1px solid #e5e7eb}
        .post-related-title{margin:0 0 18px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#1a3a2a}
        .post-related-list{margin:0;padding:0;list-style:none;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
        .post-related-list li:last-child:nth-child(odd){grid-column:1 / -1}
        .post-related-card{
          display:flex;background:#fff;border:1px solid #e5e7eb;
          border-inline-start:3px solid #3da35a;border-radius:14px;
          transition:border-color .2s,transform .2s,box-shadow .2s;
        }
        .post-related-card:nth-child(2){border-inline-start-color:#2563eb}
        .post-related-card:nth-child(3){border-inline-start-color:#9849e8}
        .post-related-card:hover{border-color:#d1f470;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .post-related-card h3{margin:0;flex:1;font-size:22px;font-weight:700;line-height:1.27;letter-spacing:-.25px}
        .post-related-card h3 :global(a){display:block;padding:18px 20px;color:#000;text-decoration:none}
        .post-related-card h3 :global(a:hover){color:#1a3a2a}
        /* border-radius matches the card so the ring traces the shape it belongs to, and the
           offset is 2px rather than the usual 3px because the anchor sits on the card's own
           edge - 3px would have the ring straddling the border. */
        .post-related-card h3 :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:2px;border-radius:14px}
        /* THE CLOSING LINK IS THE HOME PAGE'S CTA NOW, not a bare 16px text link. It is the one
           way out of this section to the listing the post sits on, which is the same job
           .home-close-cta does at the foot of the home page - so it gets the same object: 52px
           tall, 50px radius, lime fill inside a 2px 1a3a2a edge, a 17px/600 label, and a hover
           that goes to white and lifts. That also clears the 44px touch floor by 8px rather
           than sitting exactly on it.
           :global() because it is next/link, like the steps above. */
        .post-related :global(.post-related-all){
          display:inline-flex;align-items:center;gap:8px;min-height:52px;margin-top:24px;
          padding:0 28px;border:2px solid #1a3a2a;border-radius:50px;background:#d1f470;
          color:#1a3a2a;font-size:17px;font-weight:600;text-decoration:none;
          transition:background-color .2s,transform .2s,box-shadow .2s;
        }
        .post-related :global(.post-related-all:hover){background:#fff;transform:translateY(-2px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        /* Its trailing mark, drawn for the same reason as the pager's - see the note there. */
        .post-related :global(.post-nav-mark){
          width:6px;height:6px;flex:0 0 auto;
          border-top:2px solid currentColor;border-right:2px solid currentColor;
          transform:rotate(45deg);
        }
        .post-related :global(.post-related-all:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px}
        @media(max-width:680px){
          .article-shell{padding:128px 16px 64px}
          h1{max-width:none}
          .byline{margin-bottom:34px}
          .content :global(p),.content :global(li){font-size:18px;line-height:1.6}
          .content :global(p + p){margin-top:24px}
          .content :global(.spacer){height:24px}
          .content :global(h2){font-size:27px;margin-top:42px}
          .content :global(h3){font-size:22px}
          .content :global(blockquote){font-size:19px;line-height:1.55;margin:32px 0;padding-inline-start:18px}
          /* ONE COLUMN BELOW 680px, and the older half stops being end-aligned with it. Two
             44px-plus boxes side by side at 360px leaves about 160px each, which clamps a title
             to two lines of five words - the link stops saying which post it goes to. Stacked,
             each gets the full measure. The index pager does the same thing at the same width
             (.pager-list goes full width and .pager-step flexes). */
          .post-nav{grid-template-columns:1fr;gap:10px}
          .post-nav :global(.post-nav-step.is-next){align-items:flex-start;text-align:start}
          /* Related collapses to one column for exactly the reason the pager above it does:
             two cards sharing a 360px line leaves about 160px each, which clamps a title to a
             few words and the link stops saying which post it goes to. The heading keeps its
             rung - it used to drop to 21px here, which was a fourth heading size for no reason
             now that the card is on the home rung and the card is full width. */
          .post-related-list{grid-template-columns:1fr;gap:12px}
          .post-related :global(.post-related-all){width:100%;justify-content:center}
        }
        /* NOTHING LIFTS FOR A READER WHO ASKED FOR LESS MOTION. The related cards and the
           closing CTA are the only things on this page that move, and both were given the
           transform and the shadow the home page uses - so this page now needs the block the
           home page already has and this file did not carry.
           The shadow is cancelled as well as the transform: a shadow appearing under a card is
           the same "something moved" cue as the lift itself. */
        @media(prefers-reduced-motion:reduce){
          .post-related-card,.post-related :global(.post-related-all){transition:none}
          .post-related-card:hover,.post-related :global(.post-related-all:hover){transform:none;box-shadow:none}
          /* The tag pills lose the lift, not the feedback. transform is the part a reader who
             asked for less motion should not get; the lime border, the tint and the darkened
             label all stay, so the control still answers when it is pointed at. Same treatment
             the related cards above get, and the same reason. */
          .tags :global(a),.tags :global(a)::before{transition:none}
          .tags :global(a:hover),.tags :global(a:focus-visible){transform:none;box-shadow:none}
          /* THE REVEAL IS CANCELLED HERE AS WELL AS SKIPPED IN SCRIPT, and the belt and the
             braces do different jobs. The effect reads the preference once, on mount, and never
             arms if it is set - that covers the normal case. This covers the one the script
             cannot: the preference being turned on AFTER the class is already on the node, at
             which point the only thing that can put the three blocks back is CSS. Scoped to
             .is-armed so it beats the armed rule rather than beating it by accident. */
          article.is-armed .post-share,
          article.is-armed .post-nav,
          article.is-armed .post-related{opacity:1;transform:none;transition:none}
        }
      `}</style>
    </>
  );
}

export const getStaticPaths: GetStaticPaths = async () => {
  const posts = await listPublicBlogPosts();
  return {
    paths: posts.map( post => ( { params: { slug: post.slug } } ) ),
    fallback: false,
  };
};

export const getStaticProps: GetStaticProps<Props> = async ( context ) => {
  const slug = String( context.params?.slug || '' );
  const post = await getPublicBlogPost( slug );
  if ( !post ) return { notFound: true };
  /* FREE, because getStaticPaths above already pulled the corpus through the memoised fetch in
   * listPublicBlogPosts and postContext builds its tag index once for the whole build. What this
   * adds to the page is five slug/title pairs - about 0.4 kB - not a category of cards.
   * Spread rather than assigned key by key: newer and older are absent at the ends of a stream,
   * and Next refuses to serialise an explicit undefined in props. */
  const around = await postContext( slug );
  return { props: { post, ...around } };
};
