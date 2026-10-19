import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * THE DASHBOARD AND THE BACKEND HAVE TO AGREE, AND NOTHING ELSE MAKES THEM.
 *
 * The Blog Production pages render against enums that live in Python: the eight sections 5 and 28
 * declarations, the five publish job statuses, the thirteen verification assertions, the batch
 * statuses. TypeScript cannot check any of that - the wire is JSON - so a rename on the Python
 * side would show up as a control that silently stops working rather than as a build failure.
 *
 * `BlogStudioContract.test.ts` already does this for the categories. These extend it to the
 * surfaces where a mismatch is worse than cosmetic:
 *
 *   - a declaration the page does not send makes every sign-off fail with "missing", and the
 *     operator cannot tell which one;
 *   - a job status the page does not colour renders as plain text, so REFUSED stops being
 *     visually distinct from PUBLISHED on the one page where that distinction matters;
 *   - a page that offered a publish control without a sign-off would be the single worst defect
 *     this system can have, so the routes each page calls are asserted too.
 *
 * READ AS TEXT rather than imported, the same technique the neighbouring contract tests use: the
 * values being compared are literals in both files, and importing the page would execute Amplify
 * configuration at module scope.
 */

const ROOT = path.resolve( __dirname, '..', '..' );
const LAMBDA = path.join( ROOT, 'amplify', 'functions', 'operations', 'seo-tools' );
// The staged blog-production pipeline folded into one /workspace/seo/blog-production hub
// in the workspace redesign (FEAT-006); each stage's body moved OUT of the routes tree into
// src/components/workspace/seo/blog-production/** (same source, same seoApi calls, only the
// Layout wrapper became an `embedded` guard). The contract the backend and UI share is a set
// of literals in those bodies, so this repoints at the bodies and maps each former
// stage route to its component file.
const PAGES = path.join( ROOT, 'src', 'components', 'workspace', 'seo', 'blog-production' );

/** Former stage route (as this file named it) -> its relocated component file. */
const STAGE_FILE: Record<string, string> = {
  'index.tsx': 'Waves.tsx',
  'batch/index.tsx': 'Batch.tsx',
  'qa/index.tsx': 'Qa.tsx',
  'publish/index.tsx': 'Publish.tsx',
  'review/index.tsx': 'Review.tsx',
};

/** Read a former stage page by the route name this file used, via the relocation map. */
function readStage ( stage: string ): string {
  return fs.readFileSync( path.join( PAGES, STAGE_FILE[ stage ] ), 'utf8' );
}

function read ( ...parts: string[] ): string {
  return fs.readFileSync( path.join( ...parts ), 'utf8' );
}

/** Values from a Python tuple-of-pairs like `DECLARATIONS: ... = (("a", "YES"), ...)`. */
function pythonPairs ( source: string, name: string ): [ string, string ][] {
  const match = source.match(
    new RegExp( `${ name }[^=]*=\\s*\\(([\\s\\S]*?)\\n\\)`, 'm' ) );
  expect( match, `${ name } not found in the Python source` ).toBeTruthy();
  return [ ...( match as RegExpMatchArray )[ 1 ].matchAll(
    /\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)/g ) ].map(
    found => [ found[ 1 ], found[ 2 ] ] );
}

/**
 * Values from a Python tuple of string literals OR of NAMED CONSTANTS.
 *
 * Both spellings are in use and both have to work. `JOB_STATUSES` is a tuple of the constants
 * `QUEUED`, `PUBLISHING` and so on, each defined as `QUEUED = "QUEUED"` above it; reading only
 * quoted literals found nothing and the test passed vacuously on an empty list, which is why the
 * length assertion is here rather than implied.
 */
function pythonStrings ( source: string, name: string ): string[] {
  const match = source.match( new RegExp( `^${ name }[^=]*=\\s*\\(([^)]*)\\)`, 'm' ) );
  expect( match, `${ name } not found in the Python source` ).toBeTruthy();
  const body = ( match as RegExpMatchArray )[ 1 ];
  const quoted = [ ...body.matchAll( /"([^"]+)"/g ) ].map( found => found[ 1 ] );
  if ( quoted.length ) return quoted;
  return [ ...body.matchAll( /\b([A-Z][A-Z_]{2,})\b/g ) ].map( found => found[ 1 ] )
    .filter( identifier => new RegExp( `^${ identifier }\\s*=\\s*"${ identifier }"`, 'm' )
      .test( source ) );
}

describe( 'Blog Production dashboard contract', () => {
  it( 'the QA page sends every declaration the backend demands', () => {
    // A declaration the page omits makes every sign-off fail with "missing", and the operator
    // cannot see which one from the form.
    const backend = pythonPairs( read( LAMBDA, 'blog_qa.py' ), 'DECLARATIONS' );
    expect( backend.length ).toBe( 8 );

    const page = readStage( 'qa/index.tsx' );
    const declared = [ ...page.matchAll( /\[ '([a-zA-Z]+)', '(YES|NO)' \]/g ) ].map(
      found => [ found[ 1 ], found[ 2 ] ] as [ string, string ] );
    expect( declared.sort() ).toEqual( backend.sort() );
  } );

  it( 'the QA page reads the human gates from the response rather than hard-coding them', () => {
    // Eleven gates, and the list is section 29's. Hard-coding it here would drift the moment the
    // standard adds one, so the page maps over `state.humanGates` from the route.
    const page = readStage( 'qa/index.tsx' );
    expect( page ).toContain( 'state?.humanGates' );
    expect( page ).toContain( 'state?.gateAnswers' );
    for ( const gate of [ 'DISTINCTION', 'SOURCE_FIDELITY', 'HUMAN_QUALITY_TEST' ] )
    {
      expect( page, `${ gate } should come from the API, not a literal` ).not.toContain(
        `'${ gate }'` );
    }
  } );

  it( 'the publish page colours every job status the backend can return', () => {
    // REFUSED and FAILED are deliberately different states. A status with no colour renders as
    // plain text, so the distinction disappears on the one page where it matters.
    const statuses = pythonStrings( read( LAMBDA, 'blog_publish.py' ), 'JOB_STATUSES' );
    expect( statuses ).toEqual( [ 'QUEUED', 'PUBLISHING', 'PUBLISHED', 'REFUSED', 'FAILED' ] );
    const page = readStage( 'publish/index.tsx' );
    for ( const status of statuses )
    {
      expect( page, `${ status } has no colour on the publish page` ).toContain(
        `${ status }:` );
    }
  } );

  it( 'the batches page colours every batch status the backend can return', () => {
    const statuses = pythonStrings( read( LAMBDA, 'blog_batches.py' ), 'BATCH_STATUSES' );
    expect( statuses.length ).toBeGreaterThan( 0 );
    const page = readStage( 'index.tsx' );
    for ( const status of statuses )
    {
      expect( page, `${ status } has no colour on the batches page` ).toContain(
        `${ status }:` );
    }
  } );

  it( 'the batches page colours every source status the backend can return', () => {
    const source = read( LAMBDA, 'blog_sources.py' );
    const statuses = [ 'PENDING_UPLOAD', 'UPLOADED', 'EXTRACTING', 'EXTRACTED',
      'EXTRACTION_FAILED' ];
    for ( const status of statuses )
    {
      expect( source, `${ status } is not a status in blog_sources` ).toContain(
        `${ status } = "${ status }"` );
    }
    const page = readStage( 'batch/index.tsx' );
    for ( const status of statuses )
    {
      expect( page, `${ status } has no colour on the batch page` ).toContain( `${ status }:` );
    }
  } );

  it( 'no page hard-codes the thirteen verification assertions', () => {
    // The route advertises them by name for exactly this reason: a hard-coded list can fall out
    // of step with the checks that actually run, and then the report keeps saying "verified".
    const backend = read( LAMBDA, 'blog_verify.py' );
    //: Scoped to the ASSERTIONS block. An unscoped scan of the whole file matched 16, because
    //: ordinary tuples elsewhere - `("PUBLISHED", "VERIFIED")` in a status comparison - have the
    //: same shape. A test that counts the wrong 16 things reports a failure with no defect behind
    //: it, which is how a real one later gets dismissed.
    const assertions = pythonPairs( backend, 'ASSERTIONS' ).map( pair => pair[ 0 ] );
    expect( assertions.length ).toBe( 13 );

    for ( const page of [ 'index.tsx', 'batch/index.tsx', 'qa/index.tsx',
      'publish/index.tsx', 'review/index.tsx' ] )
    {
      const text = readStage( page );
      for ( const assertion of assertions )
      {
        expect( text, `${ page } hard-codes ${ assertion }` ).not.toContain( assertion );
      }
    }
  } );

  it( 'every route the pages call exists in the handler', () => {
    const handler = read( LAMBDA, 'handler.py' );
    const api = read( ROOT, 'src', 'api', 'seo.ts' );
    const routes = [
      'blog-batches', 'blog-batches/close', 'blog-sources', 'blog-analysis',
      'blog-analysis/review', 'blog-templates', 'blog-templates/assign', 'blog-qa',
      'blog-qa/sign-off', 'blog-qa/revoke', 'blog-repetition', 'blog-publish',
      'blog-publish/release', 'blog-publish/withdraw', 'blog-verify',
    ];
    for ( const route of routes )
    {
      expect( api, `seo.ts does not call ${ route }` ).toContain( `'${ route }'` );
      expect( handler, `the handler has no route for ${ route }` ).toContain(
        `endswith('/${ route }')` );
    }
  } );

  it( 'the publish page is the only one offering a publish control', () => {
    // Section 38: processing completion must never automatically mean publishing. A publish
    // button on the batch page would be the convenience that breaks it.
    for ( const page of [ 'index.tsx', 'batch/index.tsx', 'qa/index.tsx', 'review/index.tsx' ] )
    {
      const text = readStage( page );
      expect( text, `${ page } calls publishBlogArticle` ).not.toContain(
        'publishBlogArticle' );
      expect( text, `${ page } calls releaseBlogArticle` ).not.toContain(
        'releaseBlogArticle' );
    }
    const publish = readStage( 'publish/index.tsx' );
    expect( publish ).toContain( 'publishBlogArticle' );
    expect( publish ).toContain( 'releaseBlogArticle' );
  } );

  it( 'the publish page exposes only the AWS-native publication path', () => {
    const publish = readStage( 'publish/index.tsx' );
    expect( publish ).toContain( 'publishBlogArticle' );
    expect( publish ).toContain( 'AWS-native' );
    // No provider-side kill switch (a "...WritesDisabled" flag or a "..._CREDENTIALS_DISABLED"
    // reason) is read on this page: publishing has one path, the native blog.
    expect( publish ).not.toMatch( /WritesDisabled|CREDENTIALS_DISABLED/ );
  } );

  it( 'the review page is the only one recording the source reading', () => {
    // `sourceReviewedFully` has exactly one writer in the backend, and exactly one in the UI.
    for ( const page of [ 'index.tsx', 'batch/index.tsx', 'qa/index.tsx',
      'publish/index.tsx' ] )
    {
      const text = readStage( page );
      expect( text, `${ page } calls recordBlogSourceReview` ).not.toContain(
        'recordBlogSourceReview' );
    }
    expect( readStage( 'review/index.tsx' ) ).toContain( 'recordBlogSourceReview' );
  } );

  it( 'every page uses a query string rather than a dynamic route segment', () => {
    // The site is a static export. A dynamic segment with no getStaticPaths emits one file
    // literally named `[id]` - a real 200 that renders with id === '[id]' - and nothing at the
    // URL an operator reloads. `seo/page/index.tsx` records that defect in full.
    const walk = ( directory: string ): string[] => fs.readdirSync( directory ).flatMap( entry => {
      const full = path.join( directory, entry );
      return fs.statSync( full ).isDirectory() ? walk( full ) : [ full ];
    } );
    for ( const file of walk( PAGES ) )
    {
      expect( path.basename( file ), `${ file } is a dynamic route in a static export` )
        .not.toMatch( /\[.+\]/ );
    }
  } );

  it( 'the content workspace links to the production stage pages', () => {
    // A page nobody can navigate to is a page nobody uses.
    // #956 (Rebuild Content as one publishing workspace): the standalone SEO hub was
    // retired to a router.replace compatibility redirect, so it no longer carries the
    // blog-production links. The canonical surface that now lists every production stage
    // by name is navigationConfig's Content section in src/config/navigation.ts, which
    // links each stage as a ?tab= deep-link. Reading the nav config keeps the original
    // intent (the production stages are reachable by name from the live content surface)
    // against the surface that actually carries them post-#956.
    const nav = read( ROOT, 'src', 'config', 'navigation.ts' );
    for ( const route of [
      '/workspace/seo/blog-production?tab=review',
      '/workspace/seo/blog-production?tab=qa',
      '/workspace/seo/blog-production?tab=publish',
    ] )
    {
      expect( nav, `the Content workspace does not link to ${ route }` ).toContain( `'${ route }'` );
    }
  } );
} );
