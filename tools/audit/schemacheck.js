#!/usr/bin/env node
/**
 * Structured-data truth check over the whole static export.
 *
 * WHY THIS EXISTS WHEN seocheck.js ALREADY LOOKS AT JSON-LD. That harness asserts exactly two
 * things — every block parses, and no `@id` is defined twice within one page — and its own
 * source says so: "Neither is a truth check". It also drives a browser over 20 hardcoded
 * marketing ROUTES, so `/blog/` and `/post/` are outside it entirely. That is the larger part
 * of the site by two orders of magnitude, and the blind spot has already cost something real:
 * `/blog/` once shipped ZERO JSON-LD and nobody noticed, which `BlogIndexHead.tsx` records.
 *
 * So this reads `out/` directly — every emitted page, no browser, no route list to fall out of
 * date — and asserts the things that decide whether markup earns a rich result:
 *
 *   1. no empty or unparseable block. An empty `<script type="application/ld+json">` is worse
 *      than none: a validator reports it against the page rather than skipping it.
 *   2. required properties per type. Where Google documents required properties they are
 *      used; for the Article family Google now documents NONE ("There are no required
 *      properties"), so that row is this site's own floor - and it no longer includes `image`,
 *      because the only image a post has is the brand logo, which Google's Article guidance
 *      asks publishers not to use ("Use images that are relevant to the article, rather than
 *      logos"). Assertion 5 below refuses the logo there outright.
 *   3. EVERY `@id` REFERENCE RESOLVES ON THE SAME PAGE. This is the assertion that catches the
 *      specific hazard this site kept walking into. `_app.tsx` renders its `<Head>` behind
 *      `!isContentPublic`, so `#organization` was undefined on the blog surface, and
 *      `publisher: { '@id': '…#organization' }` there would have been a reference pointing at
 *      nothing. A dangling reference is not a parse error and has no duplicate `@id`, so both
 *      of seocheck's checks pass while the graph is broken.
 *   4. no cross-route `@id` collision. Two URLs defining one node with different content is
 *      the conflicting-copy case; seocheck's check is per-page and cannot see it.
 *   5. no Article-family or Recipe node presents the BRAND LOGO as its image. A logo there is a
 *      claim about the content ("this picture represents the article / is the finished dish")
 *      made only to fill a field, which .kiro/steering/00-common.md forbids.
 *
 * WHAT IT DELIBERATELY DOES NOT DO. It cannot tell whether a value is TRUE. A fabricated
 * `aggregateRating` is syntactically perfect, and inventing one is grounds for a manual action
 * against the domain — so this file also refuses the specific self-serving properties that
 * were removed from this graph on purpose, to stop them coming back through a later edit.
 *
 * Usage:  node tools/audit/schemacheck.js            (after npm run build)
 *         node tools/audit/schemacheck.js --json
 */
/* CommonJS, matching the rest of tools/audit - the directory's own package.json overrides the
 * repo root's "type": "module". routegraph.js, blogcheck.js and htmlcheck.js all use require. */
const fs = require( 'fs' );
const path = require( 'path' );

const OUT = path.join( __dirname, '..', '..', 'out' );
const JSON_MODE = process.argv.includes( '--json' );

/**
 * Required properties. Recommended-but-absent is reported, not failed.
 *
 * THE ARTICLE ROWS ARE THIS SITE'S FLOOR, NOT GOOGLE'S LIST: Google's Article documentation
 * says "There are no required properties". `image` was dropped from them on 2026-10-25 -
 * it had been satisfied on every post with the brand logo, which that same documentation asks
 * publishers not to use. A real, relevant image is welcome; the logo is refused below.
 */
const REQUIRED = {
  Organization: [ 'name', 'url', 'logo' ],
  WebSite: [ 'name', 'url' ],
  BlogPosting: [ 'headline', 'datePublished', 'author', 'publisher' ],
  Article: [ 'headline', 'datePublished', 'author', 'publisher' ],
  NewsArticle: [ 'headline', 'datePublished', 'author', 'publisher' ],
  BreadcrumbList: [ 'itemListElement' ],
  WebPage: [ 'name', 'url' ],
  ContactPage: [ 'name', 'url' ],
  CollectionPage: [ 'name', 'url' ],
  Blog: [ 'name', 'url' ],
  Service: [ 'name' ],
  SoftwareApplication: [ 'name', 'applicationCategory' ],
  FAQPage: [ 'mainEntity' ],
  Product: [ 'name', 'image', 'offers' ],
};

/**
 * Properties this repository removed on purpose. Each is a self-serving claim that cannot be
 * validated by syntax, and each has a comment in source explaining the removal. Present here
 * so a later edit reintroducing one fails a gate instead of shipping.
 */
const REFUSED = {
  aggregateRating: 'invented ratings are grounds for a manual action against the whole domain',
  review: 'same class as aggregateRating - self-serving review markup',
  foundingDate: 'was "2020" with nothing in the repo supporting it; a wrong date is a checkable false claim',
};

/** Google truncates an Article headline past ~110 characters. */
const HEADLINE_MAX = 110;

/**
 * Types whose `image` must depict the content itself. For these, the brand logo is refused:
 * Google's Article guidance says to use relevant images "rather than logos", and a Recipe image
 * is defined as the completed dish. Organization.logo / Organization.image are not affected.
 */
const CONTENT_IMAGE_TYPES = new Set( [ 'Article', 'BlogPosting', 'NewsArticle', 'Recipe' ] );
/** The brand marks served from the media bucket - any of them in a content image slot fails. */
const BRAND_LOGO = /\/(wecare-digital|wecaredigital|wd-brand-16x9)\.(png|svg|ico|jpe?g|webp)(\?|$)/i;

function walkHtml ( dir, acc = [] ) {
  if ( !fs.existsSync( dir ) ) return acc;
  for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) )
  {
    const full = path.join( dir, entry.name );
    if ( entry.isDirectory() )
    {
      if ( entry.name.startsWith( '_' ) || entry.name.startsWith( '.' ) ) continue;
      walkHtml( full, acc );
    }
    else if ( entry.name === 'index.html' ) acc.push( full );
  }
  return acc;
}

const LD_RE = /<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g;

/** Collect every node carrying an @type, plus what defines and what references an @id. */
function analyse ( parsed ) {
  const nodes = [], defined = new Set(), referenced = new Set();
  const walk = value => {
    if ( Array.isArray( value ) ) return value.forEach( walk );
    if ( !value || typeof value !== 'object' ) return;
    const type = value[ '@type' ];
    const id = value[ '@id' ];
    if ( typeof id === 'string' )
    {
      // An object with @type AND @id DEFINES an entity; @id alone REFERENCES one. Conflating
      // the two reports every correct reference as a duplicate - the false positive
      // seocheck.js documents having hit on its first run.
      if ( typeof type === 'string' ) defined.add( id );
      else referenced.add( id );
    }
    if ( typeof type === 'string' )
    {
      /**
       * `isEntity` IS THE DIFFERENCE BETWEEN A CLAIM AND A ROLE, and getting it wrong made
       * this check report 2,580 false failures on its first run.
       *
       * A node with an `@id`, or one at the root of a block, is ASSERTING an entity and must
       * be complete. A nested blank node is filling a ROLE - `author`, `publisher`,
       * `provider`, `itemOffered` - and naming the thing is the whole job. Demanding
       * `Organization.logo` of a post's `author` is demanding a logo for a byline.
       */
      const isEntity = typeof id === 'string' || value === parsed
        || ( Array.isArray( parsed[ '@graph' ] ) && parsed[ '@graph' ].includes( value ) );
      nodes.push( { node: value, isEntity } );
    }
    Object.values( value ).forEach( walk );
  };
  walk( parsed );
  return { nodes, defined, referenced };
}

const pages = walkHtml( OUT );
if ( pages.length === 0 )
{
  console.error( 'schemacheck: out/ is empty or missing - run `npm run build` first' );
  process.exit( 1 );
}

const problems = { empty: [], invalid: [], missing: [], dangling: [], duplicate: [], refused: [], long: [], relImage: [], logoImage: [] };
const definitionsByRoute = new Map();   // @id -> Set(route)
const typeCounts = new Map();
let pagesWithLd = 0, blockCount = 0;

for ( const file of pages )
{
  const route = '/' + path.relative( OUT, path.dirname( file ) ).split( path.sep ).join( '/' );
  const normalised = route === '/.' ? '/' : route;
  const html = fs.readFileSync( file, 'utf-8' );

  let match, sawLd = false, index = 0;
  const pageDefined = new Set(), pageReferenced = new Set();
  /* COUNTS, not membership. `pageDefined` is a Set, so an @id defined twice on one page
   * collapsed into one entry and the duplicate was invisible - which is precisely the
   * conflicting-copy case seocheck.js checks for, and seocheck cannot see /post/ or /blog/. */
  const defCount = new Map();

  while ( ( match = LD_RE.exec( html ) ) !== null )
  {
    index++; blockCount++; sawLd = true;
    const body = match[ 1 ].trim();
    if ( !body )
    {
      problems.empty.push( `${normalised} block ${index}` );
      continue;
    }
    let parsed;
    try { parsed = JSON.parse( body ); }
    catch ( error )
    {
      problems.invalid.push( `${normalised} block ${index}: ${error.message}` );
      continue;
    }

    const { nodes, defined, referenced } = analyse( parsed );
    if ( nodes.length === 0 )
    {
      // Parses, but describes nothing - e.g. a bare `{}`. Counted with empties because the
      // consequence is identical.
      problems.empty.push( `${normalised} block ${index} (parses but carries no @type)` );
    }
    defined.forEach( id => {
      pageDefined.add( id );
      defCount.set( id, ( defCount.get( id ) || 0 ) + 1 );
      if ( !definitionsByRoute.has( id ) ) definitionsByRoute.set( id, new Set() );
      definitionsByRoute.get( id ).add( normalised );
    } );
    referenced.forEach( id => pageReferenced.add( id ) );

    for ( const { node, isEntity } of nodes )
    {
      const type = node[ '@type' ];
      typeCounts.set( type, ( typeCounts.get( type ) || 0 ) + 1 );

      for ( const [ prop, why ] of Object.entries( REFUSED ) )
      {
        if ( prop in node ) problems.refused.push( `${normalised} ${type}.${prop} - ${why}` );
      }

      const required = isEntity ? REQUIRED[ type ] : null;
      if ( required )
      {
        const absent = required.filter( prop => {
          const v = node[ prop ];
          return v === undefined || v === null || v === ''
            || ( Array.isArray( v ) && v.length === 0 );
        } );
        if ( absent.length ) problems.missing.push( `${normalised} ${type} missing ${absent.join( ', ' )}` );
      }

      if ( typeof node.headline === 'string' && node.headline.length > HEADLINE_MAX )
      {
        problems.long.push( `${normalised} headline ${node.headline.length} chars` );
      }
      // A relative image URL is not resolvable by a crawler fetching the markup out of band.
      const img = node.image;
      const imgUrl = typeof img === 'string' ? img : ( img && img.url );
      if ( typeof imgUrl === 'string' && imgUrl && !/^https?:\/\//.test( imgUrl ) )
      {
        problems.relImage.push( `${normalised} ${type}.image is not absolute: ${imgUrl}` );
      }
      // An image array is checked entry by entry: one logo among real photos is still a claim
      // that the logo depicts the content.
      if ( CONTENT_IMAGE_TYPES.has( type ) && img )
      {
        const urls = ( Array.isArray( img ) ? img : [ img ] )
          .map( entry => ( typeof entry === 'string' ? entry : entry && entry.url ) )
          .filter( url => typeof url === 'string' );
        const logo = urls.find( url => BRAND_LOGO.test( url ) );
        if ( logo ) problems.logoImage.push( `${normalised} ${type}.image is the brand logo: ${logo}` );
      }
    }
  }

  if ( sawLd ) pagesWithLd++;
  for ( const id of pageReferenced )
  {
    if ( !pageDefined.has( id ) ) problems.dangling.push( `${normalised} references ${id} which nothing on that page defines` );
  }
  for ( const [ id, n ] of defCount )
  {
    if ( n > 1 ) problems.duplicate.push( `${normalised} defines ${id} ${n} times` );
  }
}

const crossRoute = [ ...definitionsByRoute.entries() ]
  .filter( ( [ , routes ] ) => routes.size > 1 )
  // A site-level entity is SUPPOSED to be defined on every page - that is what makes its @id
  // resolvable everywhere. Only a PAGE-scoped @id appearing on two routes is a collision.
  //
  // `#blog` is in this list for a different and weaker reason, so it is worth separating: it is
  // DELIBERATELY restated. /blog/ page 1 defines the Blog node in full, and every paginated
  // page, every topic stream and every post inlines `isPartOf: { '@type': 'Blog', '@id': ... }`
  // - a partial restatement, because the alternative is a reference that dangles on 1,332 pages
  // where the full node is not emitted. BlogIndexHead.tsx argues that trade and it is the right
  // one; the values are consistent, which is the condition that makes a restatement safe.
  .filter( ( [ id ] ) => !/#(organization|website|service|blog)$/.test( id ) )
  .map( ( [ id, routes ] ) => `${id} defined on ${routes.size} routes: ${[ ...routes ].slice( 0, 4 ).join( ', ' )}` );

const failures = [
  [ 'empty or contentless JSON-LD blocks', problems.empty ],
  [ 'unparseable JSON-LD blocks', problems.invalid ],
  [ 'nodes missing a Google-required property', problems.missing ],
  [ 'unresolved @id references', problems.dangling ],
  [ 'the same @id defined twice on one page', problems.duplicate ],
  [ 'refused self-serving properties', problems.refused ],
  [ 'image URLs that are not absolute', problems.relImage ],
  [ 'brand logo presented as an article or recipe image', problems.logoImage ],
  [ 'page-scoped @id defined on more than one route', crossRoute ],
];

if ( JSON_MODE )
{
  console.log( JSON.stringify( {
    pages: pages.length, pagesWithLd, blocks: blockCount,
    types: Object.fromEntries( [ ...typeCounts ].sort( ( a, b ) => b[ 1 ] - a[ 1 ] ) ),
    problems: { ...problems, crossRoute },
  }, null, 2 ) );
}
else
{
  console.log( `schemacheck - ${pages.length} pages, ${pagesWithLd} carrying JSON-LD, ${blockCount} blocks\n` );
  console.log( 'ENTITIES' );
  for ( const [ type, n ] of [ ...typeCounts ].sort( ( a, b ) => b[ 1 ] - a[ 1 ] ) )
  {
    console.log( `  ${String( n ).padStart( 6 )}  ${type}` );
  }
  console.log( '\nASSERTIONS' );
  for ( const [ label, list ] of failures )
  {
    console.log( `  ${list.length === 0 ? 'ok  ' : 'FAIL'} no ${label}${list.length ? ` (${list.length})` : ''}` );
    for ( const line of list.slice( 0, 8 ) ) console.log( `         ${line}` );
    if ( list.length > 8 ) console.log( `         +${list.length - 8} more` );
  }
  const pagesWithout = pages.length - pagesWithLd;
  console.log( `\n  ${pagesWithout === 0 ? 'ok  ' : 'note'} every exported page carries JSON-LD`
    + ( pagesWithout ? ` - ${pagesWithout} do not` : '' ) );
}

const total = failures.reduce( ( n, [ , list ] ) => n + list.length, 0 );
if ( !JSON_MODE ) console.log( total ? `\nFAIL: ${total} structured-data problem(s)` : '\nok: structured data is complete and internally consistent' );
process.exit( total ? 1 : 0 );
