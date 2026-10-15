import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * GUARDS A DRIFT THAT WOULD ONLY SHOW UP AT INGESTION TIME.
 *
 * `blog-studio.tsx` lets an operator pick a category and an article class, and sends them
 * either to the live `blog-sources` routes or into a work order for the CLI.
 * `scripts/blog_quality_v2.py` owns the authoritative lists; `blog_ingest.read_work_order`
 * refuses a work order naming a category the gate does not accept, and
 * `blog_sources.register` answers one with a 400.
 *
 * So if the page gains a third category and the Python does not, the operator selects it,
 * spends an afternoon assembling a batch, and every row of it is refused. The lists cannot
 * be shared across the language boundary without a build step, so this test is the seam: it
 * reads the Python source as text and asserts the page agrees.
 *
 * Reading source as text rather than importing is the same technique
 * PublicRouteRegistration.test.ts uses, and for the same reason - the values under test
 * are literals in the file.
 */
const ROOT = process.cwd();
const PAGE = path.join( ROOT, 'src', 'pages', 'workspace', 'seo', 'blog-studio.tsx' );
const GATE = path.join( ROOT, 'scripts', 'blog_quality_v2.py' );
const CLIENT = path.join( ROOT, 'src', 'api', 'seo.ts' );

const pageSource = fs.readFileSync( PAGE, 'utf8' );
const gateSource = fs.readFileSync( GATE, 'utf8' );
const clientSource = fs.readFileSync( CLIENT, 'utf8' );

/**
 * Pull a `const NAME = [ 'a', 'b' ] as const;` list out of the TSX.
 *
 * The optional `: type` is not cosmetic. `IN_FLIGHT_STATUSES` is annotated
 * `readonly string[]` so that `.includes()` accepts a plain `string`, and a pattern that
 * only matched `const NAME =` threw "not found" on it - a test failing because the value it
 * guards grew a type annotation is a test that will get deleted rather than fixed.
 */
const tsList = ( name: string ): string[] => {
  const match = pageSource.match(
    new RegExp( `const ${ name }(?:\\s*:[^=]*)?\\s*=\\s*\\[([^\\]]*)\\]` ) );
  if ( !match ) throw new Error( `${ name } not found in blog-studio.tsx` );
  return Array.from( match[ 1 ].matchAll( /'([^']+)'/g ) ).map( ( m ) => m[ 1 ] );
};

/** Pull a `NAME: Tuple[str, ...] = ("a", "b")` or `NAME = ("a", "b")` list out of the Python. */
const pyList = ( name: string ): string[] => {
  const match = gateSource.match(
    new RegExp( `^${ name }(?:\\s*:[^=]*)?\\s*=\\s*\\(([\\s\\S]*?)\\)`, 'm' ) );
  if ( !match ) throw new Error( `${ name } not found in blog_quality_v2.py` );
  return Array.from( match[ 1 ].matchAll( /"([^"]+)"/g ) ).map( ( m ) => m[ 1 ] );
};

describe( 'Blog Studio agrees with the quality gate', () => {
  it( 'offers exactly the categories the gate accepts', () => {
    expect( tsList( 'CATEGORIES' ).slice().sort() ).toEqual( pyList( 'CATEGORIES' ).slice().sort() );
  } );

  it( 'offers exactly the article classes the gate accepts', () => {
    expect( tsList( 'ARTICLE_CLASSES' ).slice().sort() )
      .toEqual( pyList( 'ARTICLE_CLASSES' ).slice().sort() );
  } );

  it( 'names the same machine-decided gates', () => {
    expect( tsList( 'MACHINE_GATES' ) ).toEqual( pyList( 'MACHINE_GATES' ) );
  } );

  it( 'names the same human-only gates', () => {
    expect( tsList( 'HUMAN_GATES' ) ).toEqual( pyList( 'HUMAN_GATES' ) );
  } );

  it( 'still has exactly two categories', () => {
    // Not a style preference. `/blog/` serves whichever category sorts first
    // alphabetically (src/lib/blog-index-props.ts), and every other category needs its own
    // /blog/topic/<slug>/ stream registered. A third category is a routing change, not a
    // dropdown change, so it should not be possible to add one here alone.
    expect( tsList( 'CATEGORIES' ) ).toHaveLength( 2 );
  } );

  it( 'renders every source status the backend can report', () => {
    // A status the page does not know about renders as an unstyled string with no action
    // offered, which for EXTRACTION_FAILED would mean a failed source with no Retry
    // button and no visible reason.
    const backend = fs.readFileSync(
      path.join( ROOT, 'amplify', 'functions', 'operations', 'seo-tools', 'blog_sources.py' ),
      'utf8' );
    for ( const status of tsList( 'SOURCE_STATUSES' ) )
    {
      expect( backend ).toContain( `${ status } = "${ status }"` );
    }
    expect( tsList( 'SOURCE_STATUSES' ) ).toContain( 'EXTRACTION_FAILED' );
  } );
} );

describe( 'Blog Studio is an authenticated surface', () => {
  it( 'renders inside the dashboard Layout', () => {
    // PublicRouteRegistration.test.ts reads the Layout import to decide whether a route is
    // public in shape. Losing it here would make this page look like a public route that
    // was never added to the allowlist, which renders the staff sign-in screen at HTTP 200.
    expect( pageSource ).toMatch( /import Layout from '[^']*components\/Layout'/ );
  } );

  it( 'is marked noindex', () => {
    expect( pageSource ).toContain( 'noindex' );
  } );

  it( 'reaches the bulk ledger through the build, not through a request', () => {
    expect( pageSource ).toContain( 'getStaticProps' );
    expect( pageSource ).toContain( 'content' );
  } );
} );

/**
 * THE ASSERTION THAT USED TO LIVE HERE, AND WHY IT IS GONE.
 *
 * This file previously asserted that the page contained no `fetch(`, `authFetch` or
 * `seoToolsFetch` at all - "does not claim to upload anything". That was correct while it
 * was true: there was no blog-source ingest backend, and a button that appears to upload
 * and silently does nothing is the worst available outcome, worse than a page that plainly
 * says the work happens in a script. The test existed to stop someone adding the button
 * before the backend.
 *
 * The backend now exists (`amplify/functions/operations/seo-tools/blog_sources.py`,
 * `blog_draft.py`), so the reason has expired and the assertion is replaced by ones that
 * check the upload actually works the way the backend requires. The intent is unchanged:
 * the page must not misrepresent what it does.
 */
describe( 'the upload path is wired to the real routes', () => {
  it( 'goes through the authenticated client for every API call', () => {
    // Not raw fetch against API_BASE: these routes are Admin-only and the Lambda calls
    // require_auth before routing, so an unauthenticated request is a 401.
    expect( pageSource ).toMatch( /from '[^']*api\/seo'/ );
    for ( const helper of [
      'registerBlogSources', 'confirmBlogSources', 'listBlogSources', 'retryBlogSource',
      'proposeBlogDraft',
    ] )
    {
      expect( pageSource ).toContain( helper );
      expect( clientSource ).toContain( `export const ${ helper }` );
    }
  } );

  it( 'names the three-phase blog-sources contract in the client', () => {
    expect( clientSource ).toContain( "'blog-sources'" );
    expect( clientSource ).toContain( "'blog-sources/confirm'" );
    expect( clientSource ).toContain( "'blog-sources/retry'" );
    expect( clientSource ).toContain( "'blog-draft'" );
    expect( clientSource ).toContain( "'blog-draft-accept'" );
    expect( clientSource ).toMatch( /blog-sources\/\$\{encodeURIComponent/ );
  } );

  it( 'routes the blog-source calls through seoToolsFetch, not a bare request', () => {
    const helper = clientSource.slice( clientSource.indexOf( 'async function seoToolsJson' ) );
    expect( helper ).toContain( 'seoToolsFetch(' );
  } );

  it( 'sends the presigned PUT with bare fetch and no Authorization header', () => {
    // THE HAZARD THIS GUARDS. A presigned URL carries its own SigV4 signature in the query
    // string. Adding a Cognito Authorization header on top makes S3 see two competing auth
    // mechanisms and reject the PUT - so the one request on this page that must NOT be
    // authenticated is the one carrying the bytes.
    const put = pageSource.slice(
      pageSource.indexOf( 'async function putPresigned' ),
      pageSource.indexOf( 'function formatBytes' ) );
    expect( put ).toMatch( /await fetch\( uploadUrl, \{/ );
    expect( put ).toContain( "method: 'PUT'" );
    expect( put ).not.toMatch( /seoToolsFetch|authFetch|Authorization/ );
  } );

  it( 'never imports the authenticated helpers under a name the PUT could reach', () => {
    // The page holds only the typed route helpers, so there is nothing in scope that could
    // accidentally sign the PUT.
    //
    // Matched against imports and call sites rather than as a bare substring, and that
    // distinction matters: the bare check also fired on `putPresigned`'s own doc comment,
    // which names both helpers in order to explain why neither is used. A test that fails
    // when you write the hazard down is a test that teaches people to stop writing it down.
    expect( pageSource ).not.toMatch( /import[^;]*\b(?:seoToolsFetch|authFetch)\b/ );
    expect( pageSource ).not.toMatch( /\b(?:seoToolsFetch|authFetch)\s*\(/ );
  } );

  it( 'holds the File objects between registration and upload', () => {
    // Registration and the PUT are two separate requests. If the File were not kept, the
    // presigned URL would arrive with nothing to send through it.
    expect( pageSource ).toContain( 'file: File' );
    expect( pageSource ).toMatch( /blogsrc_\$\{ item\.sha256 \}/ );
  } );

  it( 'confirms only after a successful PUT', () => {
    const flow = pageSource.slice(
      pageSource.indexOf( 'const sendToPipeline' ),
      pageSource.indexOf( 'const retry = useCallback' ) );
    expect( flow.indexOf( 'registerBlogSources' ) ).toBeLessThan( flow.indexOf( 'putPresigned' ) );
    expect( flow.indexOf( 'putPresigned' ) ).toBeLessThan( flow.indexOf( 'confirmBlogSources' ) );
    expect( flow ).toContain( 'confirmable.push' );
  } );

  it( 'keeps total volume unlimited while bounding transport and upload concurrency', () => {
    expect( pageSource ).toContain( 'INTAKE_CHUNK_SIZE' );
    expect( pageSource ).toContain( 'CONFIRM_CHUNK_SIZE' );
    expect( pageSource ).toContain( 'UPLOAD_CONCURRENCY' );
    expect( pageSource ).toContain( 'mapWithConcurrency' );
    expect( pageSource ).toContain( 'chunked( requests, INTAKE_CHUNK_SIZE )' );
    expect( pageSource ).toContain( 'chunked( confirmable, CONFIRM_CHUNK_SIZE )' );
    expect( pageSource ).toContain( 'unlimited bulk' );
    expect( pageSource ).not.toMatch( /files\.length\s*>\s*1000/ );
  } );

  it( 'uses exact backend rollups even when the visible source table is bounded', () => {
    expect( clientSource ).toContain( 'shown: number;' );
    expect( clientSource ).toContain( 'truncated: boolean;' );
    expect( pageSource ).toContain( 'setSourceRollup( data.byStatus || {} )' );
    expect( pageSource ).toContain( 'const liveRollup = sourceRollup;' );
    expect( pageSource ).toContain( 'recent rows of' );
    expect( pageSource ).toContain( 'total sources' );
  } );

  it( 'links the source document so a reviewer can actually read it', () => {
    // Section 2 of the standard forbids building an article from a title or an excerpt, and
    // `blog_sources.source_url` exists only to make that reading one click away - it returns
    // "" rather than a URL that would 403, so the page must treat empty as "nothing to
    // open". `rel="noopener noreferrer"` is not decoration here: without it the target gets
    // a `window.opener` handle to an authenticated admin tab.
    expect( pageSource ).toContain( 'function reviewLink' );
    expect( pageSource ).toContain( 'Open the source document' );
    expect( pageSource ).toMatch( /target="_blank" rel="noopener noreferrer"/ );
    // The field has to survive the type boundary too, or the page reads `undefined` and
    // silently offers no link at all.
    expect( clientSource ).toContain( 'sourceUrl: string;' );
    const backend = fs.readFileSync(
      path.join( ROOT, 'amplify', 'functions', 'operations', 'seo-tools', 'blog_sources.py' ),
      'utf8' );
    expect( backend ).toContain( '"sourceUrl"' );
  } );

  it( 'polls only while the backend has work in flight', () => {
    // An unconditional interval would keep an idle admin tab calling an authenticated
    // Lambda for as long as it stays open.
    expect( pageSource ).toContain( 'IN_FLIGHT_STATUSES' );
    expect( pageSource ).toContain( 'if ( inFlight === 0 ) return undefined;' );
    expect( pageSource ).toContain( 'clearInterval' );
    expect( tsList( 'IN_FLIGHT_STATUSES' ) )
      .toEqual( [ 'PENDING_UPLOAD', 'UPLOADED', 'EXTRACTING' ] );
  } );
} );

describe( 'the AI draft is presented as a proposal', () => {
  it( 'says so in the draft panel, not only in the standard tab', () => {
    expect( pageSource ).toContain( 'Proposals, not approvals' );
    expect( pageSource ).toMatch( /cannot reach/ );
  } );

  it( 'renders the whole assessment rather than a single verdict', () => {
    for ( const field of [ 'blocking', 'review', 'humanGatesOutstanding', 'words', 'status' ] )
    {
      expect( pageSource ).toContain( `assessment.${ field }` );
    }
    expect( pageSource ).toContain( 'draft.note' );
  } );

  it( 'disables the button when the cost flag is off and says why', () => {
    expect( pageSource ).toContain( 'aiDraftEnabled' );
    expect( pageSource ).toContain( 'ENABLE_BEDROCK_ASSIST' );
    expect( pageSource ).toMatch( /disabled=\{ !aiDraftEnabled/ );
  } );

  it( 'keeps the standard tab explanation that a model cannot set a human gate', () => {
    const standard = pageSource.slice( pageSource.indexOf( "tab === 'standard'" ) );
    expect( standard ).toContain( 'READY_TO_PUBLISH' );
    expect( standard ).toContain( 'EDITORIAL_QA' );
    expect( standard ).toMatch( /whitelist/ );
  } );

  it( 'the backend keeps the human gates out of what a model may write', () => {
    // The page's claim is only true because of this. WRITABLE_FIELDS is the boundary.
    const draft = fs.readFileSync(
      path.join( ROOT, 'amplify', 'functions', 'operations', 'seo-tools', 'blog_draft.py' ),
      'utf8' );
    const whitelist = draft.slice( draft.indexOf( 'WRITABLE_FIELDS = (' ),
      draft.indexOf( 'SYSTEM_PROMPT' ) );
    expect( whitelist ).not.toContain( 'sourceReviewedFully' );
    expect( whitelist ).not.toMatch( /"gate"/ );
    expect( whitelist ).not.toContain( '"status"' );
  } );
} );

describe( 'both intake paths stay distinguishable', () => {
  it( 'labels the live path and the committed-file path differently', () => {
    expect( pageSource ).toContain( 'Uploads' );
    expect( pageSource ).toContain( 'Bulk ledger' );
  } );

  it( 'keeps the work-order export that drives the CLI path', () => {
    expect( pageSource ).toContain( 'workOrder' );
    expect( pageSource ).toContain( 'Download work order' );
    expect( pageSource ).toContain( 'blog_ingest.py ingest' );
  } );

  it( 'says which path is for which volume', () => {
    expect( pageSource ).toMatch( /thousands of sources/ );
    expect( pageSource ).toMatch( /interactive batch/ );
  } );
} );

describe( 'the ingestion pipeline cannot self-certify', () => {
  it( 'draft records are created as SOURCE_REVIEW', () => {
    const ingest = fs.readFileSync( path.join( ROOT, 'scripts', 'blog_ingest.py' ), 'utf8' );
    expect( ingest ).toContain( '"status": "SOURCE_REVIEW"' );
  } );

  it( 'the draft builder never writes a gate object or a sourceReviewedFully flag', () => {
    const ingest = fs.readFileSync( path.join( ROOT, 'scripts', 'blog_ingest.py' ), 'utf8' );
    const builder = ingest.slice( ingest.indexOf( 'def draft_record' ),
      ingest.indexOf( 'def build_drafts' ) );
    expect( builder ).not.toMatch( /"gate"\s*:/ );
    expect( builder ).not.toMatch( /"sourceReviewedFully"\s*:/ );
  } );

  it( 'the gate holds a record without human verdicts at EDITORIAL_QA', () => {
    expect( gateSource ).toContain( 'return "EDITORIAL_QA"' );
  } );
} );
