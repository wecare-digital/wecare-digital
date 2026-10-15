#!/usr/bin/env node
/**
 * Write out/llms.txt and out/llms-full.txt — the curated map of this site for LLMs.
 *
 * WHAT THIS IS, AND WHAT IT HONESTLY IS NOT
 * -----------------------------------------
 * llms.txt is a community convention (llmstxt.org, proposed by Jeremy Howard in September
 * 2024): a markdown file at the site root giving a model a pre-digested map of the
 * important pages instead of making it guess from HTML. Anthropic, Stripe, Vercel,
 * Cloudflare and Supabase publish one.
 *
 * It is worth having and it is not worth overselling. As of 2026 adoption sits somewhere
 * near one site in ten, Google has said Search does not use it, and no major AI vendor has
 * committed its answer engine to reading it. It is also NOT an access-control file: it
 * grants nothing, blocks nothing, and no crawler is obliged to look at it. robots.txt is
 * where permission lives.
 *
 * So the value here is cheap insurance plus one thing that is certain: it is a correct,
 * machine-readable statement of what this site publishes and how it may be cited, which is
 * useful to a human reviewer and to any agent pointed at it explicitly - including our own
 * MCP server at /mcp, which is the surface that actually has clients rather than hoping for
 * them. Treat /mcp as the load-bearing one and this as the fallback.
 *
 * WHY IT IS GENERATED RATHER THAN COMMITTED
 * -----------------------------------------
 * seo/llm/llms-txt-draft.md is the cautionary tale: a complete, careful, hand-written
 * llms.txt that advertises /bnb, /legal-champ, /ritual, [retired public path] and /_functions/* - the old
 * site. Not one of those paths exists now. A hand-maintained file describing a site
 * that changes is a file that will be wrong, and wrong quietly.
 *
 * config/public-pages.json is the single source, shared with the MCP server's zip, and
 * src/test/PublicAiSurface.test.ts fails the build when it drifts from the two allowlists
 * that decide what is actually public.
 *
 * Its `pages` array is itself generated, by scripts/generate-public-pages.js, which runs
 * FIRST in the build chain. So the path from "a page was added" to "llms.txt and /mcp know
 * about it" needs no hand edit at all: the scan picks the route up, this file publishes it.
 *
 * RUN ORDER MATTERS: after generate-blog-search-index.js
 * -----------------------------------------------------
 * The 889 posts are not in this repository. They come from /api/seo-tools/blog-public,
 * which returns the whole corpus as 924 kB in about five seconds, and which is already the
 * hottest function in the fleet at ~392k invocations a week. generate-blog-search-index.js
 * has already fetched and trimmed exactly the fields needed and written them to
 * out/blog/search-index.json, so this reads that file instead of fetching a fourth copy
 * during one build. lib/public-blog.ts memoises for the same reason.
 *
 * FAILURE POLICY, which differs per artifact on purpose
 * ----------------------------------------------------
 *   REFUSE to write   a page listed here that is absent from the export, or any URL that
 *                     robots.txt disallows. Both would publish a statement we know to be
 *                     false: the first advertises a dead link, the second tells a crawler
 *                     to read a page it is forbidden to fetch.
 *   WARN only         a missing or empty blog index. This file degrades to the page map,
 *                     which is still correct. generate-sitemap.js takes the opposite line
 *                     and refuses, because a sitemap that silently loses 834 URLs is a
 *                     ranking event that takes weeks to undo; an llms.txt without the blog
 *                     section is a smaller, reversible loss.
 *
 * Run: node scripts/generate-llms-txt.js   (after next build, sitemap and search index)
 */

// ESM: package.json declares "type": "module", so `require` is not defined here. Same
// __dirname reconstruction as the two generators beside this one.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname( fileURLToPath( import.meta.url ) );
const ROOT = path.join( __dirname, '..' );
const OUT_DIR = path.join( ROOT, 'out' );
const CATALOG_PATH = path.join( ROOT, 'config', 'public-pages.json' );
const SEARCH_INDEX = path.join( OUT_DIR, 'blog', 'search-index.json' );

const INDEX_TARGET = path.join( OUT_DIR, 'llms.txt' );
const FULL_TARGET = path.join( OUT_DIR, 'llms-full.txt' );

/**
 * How many articles go into llms-full.txt.
 *
 * All 889 at roughly 200 bytes each is about 180 kB, which is fine to serve and a real
 * corpus map. The cap exists so the file cannot grow without bound as the blog does - a
 * multi-megabyte text file is one a consumer truncates at an arbitrary point, which is
 * worse than a bounded file that says where it stopped.
 */
const FULL_POST_LIMIT = 1000;

/** trailingSlash is set in next.config.js, so every route but the root carries the slash. */
function canonical ( siteUrl, routePath ) {
  return routePath === '/' ? `${siteUrl}/` : `${siteUrl}${routePath}/`;
}

/** Route path -> the file next build emits for it. */
function exportedFile ( routePath ) {
  return routePath === '/'
    ? path.join( OUT_DIR, 'index.html' )
    : path.join( OUT_DIR, routePath.replace( /^\//, '' ), 'index.html' );
}

/**
 * The Disallow rules actually being served. Prefer the built copy over public/, since that
 * is the one a crawler will read. Lifted from generate-sitemap.js so the two agree.
 */
function robotsDisallows () {
  for ( const candidate of [ path.join( OUT_DIR, 'robots.txt' ),
                             path.join( ROOT, 'public', 'robots.txt' ) ] )
  {
    if ( !fs.existsSync( candidate ) ) continue;
    return fs.readFileSync( candidate, 'utf-8' )
      .split( '\n' )
      .filter( line => /^\s*disallow\s*:/i.test( line ) )
      .map( line => line.split( ':' ).slice( 1 ).join( ':' ).trim() )
      .filter( Boolean );
  }
  return [];
}

function readBlogPosts () {
  if ( !fs.existsSync( SEARCH_INDEX ) )
  {
    console.warn(
      '\nllms.txt WARNING: out/blog/search-index.json not found.\n'
      + '  Writing the page map without the article section. Run\n'
      + '  node scripts/generate-blog-search-index.js first to include it.\n'
    );
    return [];
  }
  try
  {
    const body = JSON.parse( fs.readFileSync( SEARCH_INDEX, 'utf-8' ) );
    if ( !body?.ok || !Array.isArray( body.posts ) ) return [];
    return body.posts.filter( post => post?.slug && post?.title );
  } catch ( error )
  {
    console.warn( `\nllms.txt WARNING: search index unreadable (${error.message}); omitting articles.\n` );
    return [];
  }
}

/** `- [Name](url): description` — the link line shape llmstxt.org specifies. */
function linkLine ( name, url, description ) {
  const detail = String( description || '' ).trim();
  return `- [${name}](${url})${detail ? `: ${detail}` : ''}`;
}

function buildIndex ( catalog, pages, posts ) {
  const { site, groups, ai_surface: ai, usage_terms: usageTerms } = catalog;
  const lines = [];

  // H1 then a blockquote summary then free prose, in that order: the spec is explicit that
  // the H1 is the only required element and that the blockquote is the short summary.
  lines.push( `# ${site.name}` );
  lines.push( '' );
  lines.push( `> ${site.summary}` );
  lines.push( '' );
  lines.push( `${site.tagline} Content language ${site.language}. Every URL below is canonical and` );
  lines.push( 'carries a trailing slash; the slashless form redirects.' );
  lines.push( '' );

  // The MCP endpoint goes near the top on purpose. An agent that can speak MCP should use
  // it rather than this file: it can ask a question and get a scoped answer, where this can
  // only hand over a fixed list.
  //
  // THIS SECTION IS ALSO WHERE THE RETIRED /llm PAGE WENT. That page described the endpoint
  // in prose for an operator wiring up a client; it was deleted on 2026-09-30 because it was
  // a fifth copy of the endpoint URL, the protocol versions and the tool list, and /llm now
  // 301s here. So this section carries what it carried - the config snippet, the tool list,
  // and the cannot-do list - which puts it in front of the reader who arrives from
  // robots.txt rather than behind one more hop.
  lines.push( '## For agents: a live query interface' );
  lines.push( '' );
  lines.push( `This site runs a read-only Model Context Protocol server at ${ai.mcp_endpoint} over` );
  lines.push( `the Streamable HTTP transport (protocol versions ${ai.mcp_protocol_versions.join( ', ' )}).` );
  lines.push( 'Prefer it over this file: it searches the pages and the published articles on demand,' );
  lines.push( 'rather than handing over a fixed snapshot. It needs no credentials.' );
  lines.push( '' );
  lines.push( linkLine( 'MCP endpoint', ai.mcp_endpoint,
    'POST JSON-RPC and you get one JSON object back. GET returns 405 by design; this server is stateless and offers no SSE stream.' ) );
  lines.push( '' );
  lines.push( 'Add it to an MCP client like this:' );
  lines.push( '' );
  // A fenced block, so a consumer that renders this as markdown does not reflow the JSON
  // into prose. `type: "http"` is the Streamable HTTP transport; the older `sse` type would
  // attempt the deprecated HTTP+SSE transport, which this server does not implement and
  // which would fail at the GET.
  lines.push( '```json' );
  for ( const line of JSON.stringify( ai.mcp_client_config, null, 2 ).split( '\n' ) ) lines.push( line );
  lines.push( '```' );
  lines.push( '' );
  lines.push( `It exposes ${ai.mcp_tools.length} tools, every one of them a read of content that is already public:` );
  lines.push( '' );
  for ( const tool of ai.mcp_tools ) lines.push( `- \`${tool.name}\` — ${tool.summary}` );
  lines.push( '' );
  lines.push( `Plus ${ai.mcp_resources.length} resources, both as JSON:` );
  lines.push( '' );
  for ( const resource of ai.mcp_resources ) lines.push( `- \`${resource.uri}\` — ${resource.summary}` );
  lines.push( '' );
  // Stated plainly rather than left to inference. An agent that assumes a tool endpoint can
  // act will try, and a refusal it did not expect reads as a fault rather than as a limit.
  lines.push( 'What it cannot do:' );
  lines.push( '' );
  for ( const limit of ai.mcp_cannot ) lines.push( `- ${limit}` );
  lines.push( '' );
  lines.push( `${ai.note}` );
  lines.push( '' );

  for ( const group of groups )
  {
    const inGroup = pages.filter( page => page.group === group.id );
    if ( inGroup.length === 0 ) continue;
    lines.push( `## ${group.title}` );
    lines.push( '' );
    if ( group.note ) { lines.push( group.note ); lines.push( '' ); }
    for ( const page of inGroup )
    {
      lines.push( linkLine( page.name, canonical( site.url, page.path ), page.description ) );
    }
    lines.push( '' );
  }

  if ( posts.length > 0 )
  {
    lines.push( '## Articles' );
    lines.push( '' );
    lines.push( `${posts.length} published articles, newest first, at ${site.url}/post/<slug>/ .` );
    lines.push( `The full list with summaries is in ${ai.llms_full_txt} ; the paginated index is` );
    lines.push( `${site.url}/blog/ .` );
    lines.push( '' );
  }

  // "Optional" is a term of art in the spec: a consumer short of context may skip this
  // section. Legal and machine-readable indexes belong here; nothing a model needs in
  // order to describe the business correctly does.
  lines.push( '## Optional' );
  lines.push( '' );
  lines.push( linkLine( 'Sitemap', site.sitemap, 'Every indexable URL including all articles.' ) );
  lines.push( linkLine( 'Expanded index', ai.llms_full_txt,
    'This file plus every article title and summary.' ) );
  lines.push( linkLine( 'robots.txt', `${site.url}/robots.txt`,
    'The authoritative crawl permissions. This file grants nothing.' ) );
  lines.push( '' );

  lines.push( '## Using this content' );
  lines.push( '' );
  for ( const term of usageTerms ) lines.push( `- ${term}` );
  lines.push( '' );

  return lines.join( '\n' );
}

function buildFull ( catalog, index, posts ) {
  const { site, ai_surface: ai } = catalog;
  const capped = posts.slice( 0, FULL_POST_LIMIT );
  const lines = [ index.trimEnd(), '' ];

  lines.push( '---' );
  lines.push( '' );
  lines.push( '# Articles, expanded' );
  lines.push( '' );
  // Said plainly, because the community name for this file implies more than it delivers
  // here. A consumer that assumes full body text and finds summaries will quote a summary
  // as though it were the article.
  lines.push( 'This section lists every published article with its own summary. It is an expanded' );
  lines.push( 'INDEX, not the body text: fetch the article URL for that, or use the MCP endpoint at' );
  lines.push( `${ai.mcp_endpoint} to search the same corpus.` );
  lines.push( '' );
  if ( capped.length < posts.length )
  {
    lines.push( `Showing the ${capped.length} most recent of ${posts.length}. The complete list of URLs` );
    lines.push( `is in ${site.sitemap} .` );
    lines.push( '' );
  }

  let currentCategory = null;
  for ( const post of capped )
  {
    const category = post.category || 'Uncategorised';
    if ( category !== currentCategory )
    {
      lines.push( `## ${category}` );
      lines.push( '' );
      currentCategory = category;
    }
    lines.push( linkLine( post.title, `${site.url}/post/${post.slug}/`, post.excerpt ) );
  }
  lines.push( '' );
  return lines.join( '\n' );
}

// --------------------------------------------------------------------------- //

if ( !fs.existsSync( OUT_DIR ) )
{
  console.error( 'llms.txt: out/ not found — run next build first.' );
  process.exit( 1 );
}

const catalog = JSON.parse( fs.readFileSync( CATALOG_PATH, 'utf-8' ) );
const allPages = catalog.pages || [];

if ( allPages.length < 5 )
{
  console.error( `llms.txt REFUSED: config/public-pages.json lists ${allPages.length} pages.` );
  process.exit( 1 );
}

/**
 * REFUSE on a page that is not in the export.
 *
 * A warning would be the softer choice and it is the wrong one here. generate-sitemap.js
 * only warns about the same condition, but it can afford to: it emits routes it actually
 * FOUND, so a stale entry makes the sitemap quietly shorter. This file emits what the
 * catalogue says, so a stale entry becomes a published dead link that a model will cite.
 */
const missing = allPages.filter( page => !fs.existsSync( exportedFile( page.path ) ) );
if ( missing.length > 0 )
{
  console.error(
    `\nllms.txt REFUSED: ${missing.length} catalogued page(s) are not in the export:\n`
    + missing.map( page => `    ${page.path}  (expected ${path.relative( ROOT, exportedFile( page.path ) )})` ).join( '\n' )
    + '\n\n  Either the page was removed — delete it from config/public-pages.json — or the\n'
    + '  build did not emit it, which is the serious case. Publishing this file would\n'
    + '  advertise a URL that 404s to every model that reads it.\n'
  );
  process.exit( 1 );
}

/**
 * REFUSE on a URL that is both advertised here and Disallowed in robots.txt.
 *
 * The same contradiction generate-sitemap.js fails on, and it fails for the same reason:
 * the authenticated dashboard is exported into the same bucket as the marketing pages and
 * is held out of the index by robots.txt alone. One wrong catalogue entry is all it takes
 * to point a model at an internal route.
 */
const disallows = robotsDisallows();
const contradicted = allPages
  .map( page => ( { page, pathname: page.path === '/' ? '/' : `${page.path}/` } ) )
  .filter( ( { pathname } ) => disallows.some( rule => rule !== '/' && pathname.startsWith( rule ) ) );
if ( contradicted.length > 0 )
{
  console.error(
    `\nllms.txt REFUSED: ${contradicted.length} URL(s) are advertised here and Disallowed in robots.txt:\n`
    + contradicted.map( ( { page, pathname } ) => `    ${page.path}  (blocked by a rule matching ${pathname})` ).join( '\n' )
    + '\n\n  Remove it from config/public-pages.json if it is authenticated, or remove the\n'
    + '  Disallow if it is genuinely public.\n'
  );
  process.exit( 1 );
}

const posts = readBlogPosts();
const index = buildIndex( catalog, allPages, posts );
const full = buildFull( catalog, index, posts );

fs.writeFileSync( INDEX_TARGET, `${index.trimEnd()}\n`, 'utf-8' );
fs.writeFileSync( FULL_TARGET, `${full.trimEnd()}\n`, 'utf-8' );

const kb = file => Math.max( 1, Math.round( fs.statSync( file ).size / 1024 ) );
console.log(
  `llms.txt: ${allPages.length} pages, ${posts.length} articles`
  + ` -> llms.txt (${kb( INDEX_TARGET )} kB), llms-full.txt (${kb( FULL_TARGET )} kB)`
);
