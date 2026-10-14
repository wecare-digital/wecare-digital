import type { GetStaticPaths, GetStaticProps } from 'next';
import type { ReactNode } from 'react';
import { Fragment, useEffect, useRef } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import PublicShare from '../../components/PublicShare';
import RotatingHero from '../../components/RotatingHero';
import {
  SOCIAL_CARD_URL, SOCIAL_CARD_W, SOCIAL_CARD_H, SOCIAL_CARD_TYPE, SOCIAL_CARD_ALT, SHARE_CARD_TYPE,
} from '../../config/share';
import { ORG_ID, ORIGIN, WEBSITE_ID, SITE_ENTITIES, ld } from '../../lib/schema';
import { extractRecipe, recipeSchema } from '../../lib/recipe-schema';
import { getPublicBlogPost, listPublicBlogPosts, PublicBlogPost } from '../../lib/public-blog';
import { postContext, type PostLink } from '../../lib/post-neighbours';
import Breadcrumbs from '../../components/Breadcrumbs';
import BlogTags from '../../components/BlogTags';
import RssIcon from '../../components/RssIcon';
import VoiceSearchMic from '../../components/VoiceSearchMic';

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
  const postSearchFormRef = useRef<HTMLFormElement | null>( null );
  const postSearchInputRef = useRef<HTMLInputElement | null>( null );
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
        {/* RSS AUTODISCOVERY. A feed reader opening any post finds the blog's feed from this
            tag, and search engines read it as a freshness/alternate-format signal. The feed is
            generated post-build by scripts/generate-blog-rss.js and served at /blog/rss.xml.
            Title names the feed, not the post, because the href is the blog feed. */}
        <link rel="alternate" type="application/rss+xml" title="WECARE.DIGITAL Blog"
          href={ `${ORIGIN}/blog/rss.xml` } />
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
      {/* UNIFIED HERO (owner 2026-10-13): the post carries the same frame + ROTATING lime pill +
          one-shot entrance as every other hero, via the shared RotatingHero. Frame is "Read" and
          the pill cycles a short set of reading verbs - reflect, consider, revisit, return - each
          on its own tint/dot from the house palette, so the post hero animates like the home,
          Grahak OS and VayuLok heroes rather than sitting static. A post has one subject (its
          title), so the title is NOT the pill - it stays the article's own h2 below; the pill
          carries the quiet "what you do with a piece" verb instead. RotatingHero owns the <main>
          and the ONE h1 (the hero), so the page keeps exactly one h1 (htmlcheck H1-MANY). Single
          dynamic template, so every post - today's and any added tomorrow - gets it automatically.
          noShare is set because the post keeps its own PublicShare at the .post-share reveal
          sentinel (mid-content), so the hero must not auto-mount a second dock. */}
      <RotatingHero
        frame="Read and"
        words={ [
          { word: 'reflect', tint: '#e0f7c8', dot: '#3da35a' },
          { word: 'consider', tint: '#dbeafe', dot: '#2563eb' },
          { word: 'revisit', tint: '#ede9fe', dot: '#9849e8' },
          { word: 'return', tint: '#fef9c3', dot: '#ca8a04' },
        ] }
        ariaLabel={ post.title }
        noShare
      >
        <article className="article-shell">
          {/* A REAL TRAIL, replacing a single "← Blog" back link at 13px/650 - the only
              control on this page below the site's 12px/700 smallest UI rung. The page's own
              JSON-LD has always declared a BreadcrumbList; now the page shows one. */}
          <Breadcrumbs items={ [
            { label: 'Home', href: '/' },
            { label: 'Blog', href: '/blog/' },
            { label: post.title },
          ] } />
          {/* THE GLOBAL BORDERLESS SEARCH, button-less - the same field as /blog/ and the /anew/
              panel, so a reader meets one search control across the blog. On a POST page there is
              no post list in the page to filter live, so this is a real GET form to /blog/: typing
              a term and pressing Enter navigates to /blog/?q=<term>, where the index reads ?q= and
              filters the full corpus. name="q" is the param /blog/ reads. There is still no visible
              submit button; the shared lime mic is the one icon on this borderless field. The form submits on
              Enter, and the sr-only label gives it an accessible name. */}
          <form ref={ postSearchFormRef } className="post-search" role="search" action="/blog/" method="get">
            <label className="post-search-sr" htmlFor="post-q">Search the blog</label>
            <input ref={ postSearchInputRef } id="post-q" name="q" type="search" autoComplete="off" placeholder="Search posts" />
            <VoiceSearchMic
              onTranscript={ transcript => {
                if ( !postSearchInputRef.current ) return;
                postSearchInputRef.current.value = transcript;
                if ( postSearchFormRef.current?.requestSubmit ) postSearchFormRef.current.requestSubmit();
                else postSearchFormRef.current?.submit();
              } }
            />
          </form>
          { post.category && <div className="category">{ post.category }</div> }
          {/* The article title is an h2 now: the RotatingHero pill above is the page's single h1,
              so the title steps down one level to keep exactly one h1. .post-title class carries
              the old h1 styling so the visible treatment is unchanged. */}
          <h2 className="post-title">{ post.title }</h2>
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
          {/* TAGS ARE LINKS, AND THEY GO WHERE TAGS ARE ALREADY USED - the markup, the hue hash
              and the whole .tags/.tag-h0..3 style block moved to components/BlogTags.tsx so a tag
              reads as the SAME object here and on the /anew/ panel rather than being re-typed per
              surface. The behaviour is unchanged: each tag is a next/link to /blog/?q=<tag>, the
              one destination that matches what the field is for (generate-blog-search-index.js
              records that `tags` is carried FOR SEARCH, not for display), and the search works
              with JavaScript off because it is a plain navigation.
              className="tags" so this page's layout rule still applies, and the aria-label names
              the landmark - copying .category-switch rather than adding a visible heading, which
              typecheck.js would hold to the 40px/700 section-h2 rung. */}
          <BlogTags tags={ post.tags || [] } className="tags" ariaLabel="Tags on this post" />

          {/* THE OLD INLINE SUBSCRIBE PILL IS GONE. The post page used to carry its own
              `.blog-wa-subscribe` WhatsApp pill and a `.wc-sweep-note` "Continue on WhatsApp →"
              microcopy line here, plus its own `.post-share` ShareLinks row below Contribution.
              The owner unified every public surface onto the ONE global Contribute+Subscribe+Share block
              (components/PublicShare), so both the old Subscribe pill and the page's own Share row
              are removed and PublicShare below provides Contribute, Subscribe and Share in one block.
              There is exactly ONE Subscribe+Share on the page now. */}
          {/* THE GLOBAL CONTRIBUTE + SUBSCRIBE + SHARE BLOCK, AT THE END OF THE READING.
              The page no longer renders its own ShareLinks row; PublicShare is the ONE
              Contribute+Subscribe+Share block every public surface carries - the compact Contribute menu,
              Subscribe, then Share (the icon row for THIS page's own URL + title) in one block.
              canonical + post.title are passed as the share target, NOT router.asPath or the
              seoTitle: what gets shared has to be the address the page declares as its own
              (no utm string, no #hash) and the title without the " | WECARE.DIGITAL" tab suffix,
              because og:site_name already says whose link it is. PublicShare would resolve these
              from location/document itself, but passing them keeps the static export correct and
              avoids a stale value pre-hydration.
              The .post-share wrapper stays as the IntersectionObserver reveal sentinel - shareRef
              still names it, so the staged entrance of this block, the pager and the related cards
              is unchanged. Its own hairline border is dropped (see the CSS note) because
              PublicShare carries its own full-width separator. */}
          <div className="post-share" ref={ shareRef }>
            <PublicShare url={ canonical } title={ post.title } />
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

          {/* THE RSS SUBSCRIBE AFFORDANCE, icon-only, at the foot of the post - the same control
              /blog/ and the /anew/ panel place below their lists, so every blog surface advertises
              the feed with one shared lime glyph. On owner instruction it is on the post page too.
              NOTE: /blog/rss.xml is written by scripts/generate-blog-rss.js at build time into
              out/, so this link resolves on the built/live site but 404s on `next dev`, which does
              not run that generator. */}
          <div className="post-rss">
            <RssIcon />
          </div>
        </article>
      </RotatingHero>
      <style jsx>{`
        /* NO HEADER CLEARANCE HERE ANY MORE: RotatingHero owns the <main>, the 108px/96px header
           clearance, the measure and the gutter. .article-shell is now a plain <article> inside
           .rh-layout, so it only needs its own 700px reading measure and font - the top padding
           moved out with the <main>. */
        .article-shell{max-width:700px;margin:0 auto;color:#1a1a1a;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
        article{max-width:700px;margin:0 auto}
        /* THE GLOBAL BORDERLESS SEARCH FIELD, matching /blog/ (.blog-search) and the /anew/ panel
           (.pbp-search): transparent fill, one quiet bottom hairline, the shared lime mic, no submit button. On focus
           the hairline darkens and a lime underline grows. A GET form, so it works with no JS. */
        .post-search{position:relative;margin:0 0 24px;max-width:520px}
        .post-search-sr{
          position:absolute;width:1px;height:1px;padding:0;margin:-1px;
          overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;
        }
        .post-search input{
          width:100%;box-sizing:border-box;height:52px;padding:0 44px 0 2px;
          font-size:17px;font-family:inherit;color:#1a1a1a;background:transparent;
          border:0;border-bottom:1px solid #e5e7eb;border-radius:0;outline:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .post-search input::placeholder{color:rgba(0,0,0,.44)}
        .post-search input:focus-visible{border-bottom-color:#1a3a2a;box-shadow:0 1px 0 0 #d1f470}
        @media(prefers-reduced-motion:reduce){.post-search input{transition:none}}
        /* The RSS icon's row at the foot of the post, END-aligned (to the side, not centered)
           under the related section - owner instruction. The icon styles itself
           (components/RssIcon.tsx); this only places the row. */
        .post-rss{display:flex;justify-content:flex-end;margin:48px 0 0}
        /* .back rules removed with the link - Breadcrumbs replaced it. */
        /* THE SAME BADGE AS THE INDEX CARD'S, SO IT GETS THE SAME TREATMENT.
           A reader meets this category on the listing card and again at the top of the post;
           they were the same component in two different styles, which is the kind of gap that
           reads as a rendering bug rather than a design. Both are now BrandBadge's rung:
           14px/600/-.125px, #d1f470 fill, #1a3a2a type, no border. See the longer note at
           .category in BlogIndexView.tsx for why identity takes the fill and not the .22
           tint - the short version is that .22 composites to a barely-not-white wash. */
        .category{display:inline-block;background:#d1f470;color:#1a3a2a;border-radius:999px;padding:6px 12px;font-size:14px;font-weight:600;letter-spacing:-.125px;margin-bottom:18px}
        /* .post-title carries the article title's old h1 treatment unchanged - it is an <h2> now
           (RotatingHero's pill is the page's one h1), but the visible size/weight is identical so
           the article still opens on its title at full weight. */
        .post-title{font-size:clamp(36px,4.3vw,60px);line-height:1.04;letter-spacing:-0.04em;color:rgba(0,0,0,.95);margin:0 0 20px;font-weight:600;text-wrap:balance;max-width:20ch}
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
        /* THE TAG ROW'S CSS MOVED WITH ITS MARKUP to components/BlogTags.tsx - the .tags
           layout rule, the .tags :global(a) pill, the four .tag-h0..3 dots and the hover/focus
           and reduced-motion handling all live there now, so the one component styles itself on
           every surface it renders. Nothing was dropped; it is the same block, in one place. */
        /* THE OLD .blog-wa-subscribe PILL CSS IS GONE, with the markup it styled. The post page
           no longer carries its own Subscribe pill (or the .wc-sweep-note microcopy that named
           its destination); the global PublicShare block below provides Subscribe + Share, and
           it styles its own .ps-subscribe pill. */
        /* THE .post-share WRAPPER IS NOW JUST THE REVEAL SENTINEL. It wraps the global
           PublicShare, which carries its OWN full-width hairline separator and its own top
           spacing, so this wrapper must not add a second 1px rule and extra padding on top of
           PublicShare's - that would read as a double divider. The margin-top keeps the block off
           the Contribution above it; the border and padding move into PublicShare itself. */
        .post-share{margin-top:4px}

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
          /* No header clearance here on mobile either - RotatingHero's .rh-layout owns it. */
          .article-shell{padding:0}
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
          /* The tag pills' reduced-motion handling moved to BlogTags with the rest of their CSS. */
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
