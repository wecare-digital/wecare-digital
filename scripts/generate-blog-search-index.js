#!/usr/bin/env node

/**
 * Writes out/blog/search-index.json — the full post list, for search only.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * /blog/ used to hold all 834 posts in one document, and that is what let search and the
 * category pills filter the whole corpus: everything was already there. Pagination removed
 * that, for reasons in components/BlogIndexView.tsx - 842 kB of props and 115.5 screens of
 * DOM. Narrowing search to the visible 24 posts would have been a silent downgrade, so the
 * full list still ships; it just is not in the page any more.
 *
 * The browser fetches this ONCE, LAZILY, on the first keystroke or the first category press.
 * A reader who does not search never requests it.
 *
 * FOUR FIELDS, AND WHY EACH ONE
 * -----------------------------
 *   slug      the link target, and the React key
 *   title     matched, and rendered on the result card
 *   excerpt   matched, and rendered. The largest field at ~180 kB of the ~264 kB total, and
 *             it stays: dropping it would shrink this file to 84 kB and turn "search the
 *             blog" into "search blog titles", which is a different feature.
 *   category  matched, and rendered as the pill
 *
 * publishedDate and authorName are deliberately ABSENT even though the card renders both.
 * They are 41 kB, they are never matched, and a search result missing its byline is a much
 * smaller loss than 41 kB on every searching reader. The card already treats both as
 * optional because a post can legitimately lack them.
 *
 * WHY POST-BUILD AND NOT public/
 * ------------------------------
 * The content is not in this repository - it comes from wecare.digital/api/seo-tools/
 * blog-public at build time - so a file committed under public/ would be a snapshot that goes
 * stale the moment anything is published. Generated after `next build`, beside
 * generate-sitemap.js, which already works this way for the same reason.
 *
 * IT DOES NOT FAIL THE BUILD ON AN EMPTY LIST, and that is the opposite of the sitemap's
 * rule. generate-sitemap.js REFUSES to write a sitemap with zero posts, because a sitemap
 * that silently loses 834 URLs is an SEO event that takes weeks to undo. This file is a
 * progressive enhancement: if it is missing or empty, BlogIndexView says so in a notice and
 * searches the current page instead. Blocking a deploy over a degraded search box would be
 * the more expensive failure.
 *
 * Run: node scripts/generate-blog-search-index.js   (after next build)
 */

// ESM, not CommonJS: package.json declares "type": "module", so a .js file in this repo is a
// module and `require` is not defined in it. generate-sitemap.js beside this one does the same
// __dirname reconstruction for the same reason.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { mergedAwaySlugs } from './blog-merges.js';

const __dirname = path.dirname( fileURLToPath( import.meta.url ) );

const OUT_DIR = path.join( __dirname, '..', 'out' );
const TARGET = path.join( OUT_DIR, 'blog', 'search-index.json' );

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';

/**
 * ?fields= ASKS FOR THE FOUR THIS FILE KEEPS, instead of downloading 924 kB to discard
 * half of it.
 *
 * The header above already explains that publishedDate and authorName are deliberately
 * absent from the output because they cost 41 kB and are never matched. That reasoning
 * applies with more force to the transfer itself: the unprojected response carries
 * jsonLd, keywords, hashtags, robots, focusKeyword and metaDescription for all 889 posts,
 * none of which appear in the index this writes.
 *
 * Kept as a named constant beside the endpoint so the two cannot drift: if a field is
 * added to the card shape below, it has to be added here or it arrives undefined.
 */
/*
 * `tags` IS REQUESTED FOR SEARCH, NOT FOR DISPLAY, and it is the reason this list grew.
 * Every post in the corpus carries tags, and they hold words a reader types that appear nowhere in
 * the title or the excerpt - "Beverages", "Herbal Tea", "Chai", "Lemongrass" are all tags on posts
 * whose visible text contains none of them, so those searches returned nothing at all.
 * Measured over 1064 posts: the written index goes from 350.0 kB to 391.4 kB. It is fetched lazily,
 * only after a reader types, so nobody who does not search pays for it.
 */
const FIELDS = [ 'slug', 'title', 'excerpt', 'category', 'publishedDate', 'tags' ];
const ENDPOINT = `${API_BASE}/seo-tools/blog-public?fields=${FIELDS.join( ',' )}`;

/** Same sort as lib/public-blog.ts listBlogCards: newest first, undated last, then by slug. */
function byNewest ( a, b ) {
  const at = a.publishedDate ? Date.parse( a.publishedDate ) : NaN;
  const bt = b.publishedDate ? Date.parse( b.publishedDate ) : NaN;
  if ( Number.isNaN( at ) && Number.isNaN( bt ) ) return String( a.slug ).localeCompare( String( b.slug ) );
  if ( Number.isNaN( at ) ) return 1;
  if ( Number.isNaN( bt ) ) return -1;
  return bt - at;
}

async function main () {
  if ( !fs.existsSync( OUT_DIR ) ) {
    console.error( 'Blog search index: out/ not found — run next build first.' );
    process.exit( 1 );
  }

  let posts = [];
  try {
    const response = await fetch( ENDPOINT, { headers: { Accept: 'application/json' } } );
    if ( !response.ok ) throw new Error( `HTTP ${response.status}` );
    const body = await response.json();
    if ( body?.ok && Array.isArray( body.posts ) ) posts = body.posts;
  } catch ( error ) {
    console.warn( `Blog search index: fetch failed (${error.message}) — writing an empty index.` );
  }

  // Merged-away posts answer 301 and have no page, as in lib/public-blog.ts. llms.txt reads
  // this index, so dropping them here covers it too.
  const mergedAway = mergedAwaySlugs();
  const cards = posts
    .filter( post => post && post.slug && post.title && !mergedAway.has( post.slug ) )
    .sort( byNewest )
    .map( post => {
      const card = { slug: post.slug, title: post.title };
      if ( post.excerpt ) card.excerpt = post.excerpt;
      if ( post.category ) card.category = post.category;
      // Length-guarded, matching toBlogCard in lib/public-blog.ts: an empty array is bytes on
      // every record for nothing. The two projections have to agree, or a tag search behaves one
      // way on the page's own cards and another way once the index arrives.
      if ( Array.isArray( post.tags ) && post.tags.length ) card.tags = post.tags;
      return card;
    } );

  fs.mkdirSync( path.dirname( TARGET ), { recursive: true } );
  // No pretty-printing: this is fetched, not read. Indentation on 834 records is ~30 kB of
  // whitespace that every searching reader would download.
  fs.writeFileSync( TARGET, JSON.stringify( { ok: true, count: cards.length, posts: cards } ) );

  const kb = Math.round( fs.statSync( TARGET ).size / 1024 );
  console.log( `Blog search index: ${cards.length} posts, ${kb} kB -> ${TARGET}` );

  /**
   * A LOUD WARNING RATHER THAN A FAILURE when the list is empty. The blog lives behind a
   * network call, and generate-sitemap.js documents a real incident where a healthy endpoint
   * returned nothing mid-build. Search degrading for one deploy is recoverable; the notice in
   * BlogIndexView tells the reader what happened. A non-zero exit here would block a deploy
   * whose 834 post pages built perfectly well.
   */
  if ( cards.length === 0 ) {
    console.warn( 'Blog search index: EMPTY. Blog search will fall back to the current page only.' );
  }
}

main().catch( error => {
  console.error( `Blog search index: unexpected failure — ${error.stack || error.message}` );
  process.exit( 1 );
} );
