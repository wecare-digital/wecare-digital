#!/usr/bin/env node

/**
 * Writes out/blog/rss.xml — an RSS 2.0 feed of the most recent blog posts, for feed readers,
 * email digest services, and the discovery signal search engines read from <link rel="alternate">.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The blog is in the sitemap and every post is indexable, but there was no FEED - the one
 * machine-readable "here is what is new, newest first" document that readers subscribe to and
 * that aggregators (and Google's own freshness signals) consume. A sitemap says "these URLs
 * exist"; a feed says "these are the latest, in order, with their content". They are different
 * jobs, which is why both ship. This is the feed.
 *
 * MODELLED ON generate-blog-search-index.js, DELIBERATELY. Same endpoint, same build-time fetch,
 * same newest-first sort, same post-`next build` timing, and the same NON-FATAL-ON-EMPTY rule.
 * The content is not in this repository - it comes from wecare.digital/api/seo-tools/blog-public
 * at build time - so a file committed under public/ would be a snapshot that goes stale the moment
 * anything is published.
 *
 * IT DOES NOT FAIL THE BUILD ON AN EMPTY LIST, matching the search index and UNLIKE the sitemap.
 * The sitemap refuses to write zero posts because dropping 1000+ URLs from the index is an SEO
 * event that takes weeks to undo. A feed is a progressive enhancement: a reader whose feed is
 * briefly empty gets no new items for one build, which is recoverable. A loud warning is printed
 * instead of a non-zero exit, so a transient fetch blip does not block a deploy whose post pages
 * built perfectly well.
 *
 * ONLY THE MOST RECENT `FEED_LIMIT` POSTS. A feed is "what is new", not an archive - that is what
 * the sitemap and the search index are for. Shipping all 1000+ posts would make a multi-megabyte
 * document that every subscribing reader re-downloads on every poll, for no benefit: readers keep
 * their own history, and no feed reader shows a thousand-item backlog. 50 is the conventional feed
 * window and is what every major CMS defaults to within a small range.
 *
 * Run: node scripts/generate-blog-rss.js   (after next build)
 */

// ESM, not CommonJS: package.json declares "type": "module", so a .js file here is a module and
// `require` is not defined. generate-sitemap.js and generate-blog-search-index.js beside this one
// do the same __dirname reconstruction for the same reason.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname( fileURLToPath( import.meta.url ) );

const OUT_DIR = path.join( __dirname, '..', 'out' );
const TARGET = path.join( OUT_DIR, 'blog', 'rss.xml' );

// The public site origin. The apex, NOT www - the same host generate-sitemap.js emits, and the
// one every current canonical/og:url signal on the site uses. A feed whose links pointed at www
// would advertise URLs that 301, which weakens the very freshness signal the feed exists to send.
const SITE_URL = 'https://wecare.digital';
const FEED_SELF = `${SITE_URL}/blog/rss.xml`;
const BLOG_URL = `${SITE_URL}/blog/`;

const CHANNEL_TITLE = 'WECARE.DIGITAL Blog';
const CHANNEL_DESCRIPTION = 'Ideas, guides and updates from WECARE.DIGITAL.';
const CHANNEL_LANGUAGE = 'en-IN';

// A feed is a window on what is new, not the archive. See the header.
const FEED_LIMIT = 50;

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

// The fields an RSS item needs: the link + guid (slug), the title, the summary (excerpt),
// the <pubDate> (publishedDate) and the <category>. Projected rather than downloading the full
// ~900 kB response to discard most of it, exactly as the search index does.
const FIELDS = [ 'slug', 'title', 'excerpt', 'category', 'publishedDate' ];
const ENDPOINT = `${API_BASE}/seo-tools/blog-public?fields=${FIELDS.join( ',' )}`;

/** Same sort as lib/public-blog.ts listBlogCards and the search index: newest first, undated last, then by slug. */
function byNewest ( a, b ) {
  const at = a.publishedDate ? Date.parse( a.publishedDate ) : NaN;
  const bt = b.publishedDate ? Date.parse( b.publishedDate ) : NaN;
  if ( Number.isNaN( at ) && Number.isNaN( bt ) ) return String( a.slug ).localeCompare( String( b.slug ) );
  if ( Number.isNaN( at ) ) return 1;
  if ( Number.isNaN( bt ) ) return -1;
  return bt - at;
}

/**
 * XML text escaping for element content and attributes. The five predefined XML entities only -
 * a feed value is text, never markup, so < > & " ' must not be allowed to open a tag or close a
 * CDATA section. Applied to every interpolated value below without exception.
 */
function xmlEscape ( value ) {
  return String( value == null ? '' : value )
    .replace( /&/g, '&amp;' )
    .replace( /</g, '&lt;' )
    .replace( />/g, '&gt;' )
    .replace( /"/g, '&quot;' )
    .replace( /'/g, '&apos;' );
}

/** RFC 822 date, which is what RSS 2.0 <pubDate> requires - NOT ISO 8601. `null` for unparseable. */
function rfc822 ( value ) {
  if ( !value ) return null;
  const d = new Date( value );
  if ( Number.isNaN( d.getTime() ) ) return null;
  return d.toUTCString();
}

function itemXml ( post ) {
  const link = `${SITE_URL}/post/${encodeURIComponent( post.slug )}/`;
  const pubDate = rfc822( post.publishedDate );
  return [
    '    <item>',
    `      <title>${xmlEscape( post.title )}</title>`,
    `      <link>${xmlEscape( link )}</link>`,
    // isPermaLink="true": the slug URL is a stable permalink, so the guid can simply be the link.
    `      <guid isPermaLink="true">${xmlEscape( link )}</guid>`,
    pubDate ? `      <pubDate>${pubDate}</pubDate>` : null,
    post.category ? `      <category>${xmlEscape( post.category )}</category>` : null,
    post.excerpt ? `      <description>${xmlEscape( post.excerpt )}</description>` : null,
    '    </item>',
  ].filter( Boolean ).join( '\n' );
}

async function main () {
  if ( !fs.existsSync( OUT_DIR ) ) {
    console.error( 'Blog RSS: out/ not found — run next build first.' );
    process.exit( 1 );
  }

  let posts = [];
  try {
    const response = await fetch( ENDPOINT, { headers: { Accept: 'application/json' } } );
    if ( !response.ok ) throw new Error( `HTTP ${response.status}` );
    const body = await response.json();
    if ( body?.ok && Array.isArray( body.posts ) ) posts = body.posts;
  } catch ( error ) {
    console.warn( `Blog RSS: fetch failed (${error.message}) — writing an empty feed.` );
  }

  const items = posts
    .filter( post => post && post.slug && post.title )
    .sort( byNewest )
    .slice( 0, FEED_LIMIT );

  // lastBuildDate reflects when the feed was generated; pubDate on the channel is the newest
  // item's date when there is one, so a reader can tell "nothing new" from "feed rebuilt".
  const now = new Date().toUTCString();
  const newest = items.map( p => rfc822( p.publishedDate ) ).find( Boolean );

  const channelHead = [
    '  <channel>',
    `    <title>${xmlEscape( CHANNEL_TITLE )}</title>`,
    `    <link>${xmlEscape( BLOG_URL )}</link>`,
    `    <description>${xmlEscape( CHANNEL_DESCRIPTION )}</description>`,
    `    <language>${CHANNEL_LANGUAGE}</language>`,
    `    <lastBuildDate>${now}</lastBuildDate>`,
    newest ? `    <pubDate>${newest}</pubDate>` : null,
    // The feed's own address, so a reader that only has the document can find where it lives.
    `    <atom:link href="${xmlEscape( FEED_SELF )}" rel="self" type="application/rss+xml" />`,
  ].filter( Boolean ).join( '\n' );

  const xml =
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    + '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
    + channelHead + '\n'
    + ( items.length ? items.map( itemXml ).join( '\n' ) + '\n' : '' )
    + '  </channel>\n'
    + '</rss>\n';

  fs.mkdirSync( path.dirname( TARGET ), { recursive: true } );
  fs.writeFileSync( TARGET, xml, 'utf-8' );

  const kb = Math.round( fs.statSync( TARGET ).size / 1024 );
  console.log( `Blog RSS: ${items.length} items (of ${posts.length} posts), ${kb} kB -> ${TARGET}` );

  // A LOUD WARNING, NOT A FAILURE, when the list is empty - the same choice the search index
  // makes and the opposite of the sitemap's. See the header for why.
  if ( items.length === 0 ) {
    console.warn( 'Blog RSS: EMPTY. The feed was written with no items — check the blog-public API.' );
  }
}

main().catch( error => {
  console.error( `Blog RSS: unexpected failure — ${error.stack || error.message}` );
  process.exit( 1 );
} );
