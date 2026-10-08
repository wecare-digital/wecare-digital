/**
 * Blog Studio — PDF and URL intake for the Conversations blog.
 *
 * TWO INTAKE PATHS, DELIBERATELY BOTH.
 *
 * 1. UPLOADS (this page, live). Register sources, PUT each PDF straight to S3 with a
 *    presigned URL, confirm, and let the backend worker extract. Three phases rather than
 *    one request because API Gateway cuts a Lambda integration off at 30 seconds:
 *    registration returns URLs without touching bytes, the browser carries the bytes
 *    outside our compute entirely, and extraction runs in an async worker that chains.
 *    Good for an interactive batch — tens of sources, with per-source status visible.
 *
 * 2. BULK LEDGER (the CLI). `scripts/blog_ingest.py --work-order <file>` reads a work
 *    order exported from here and does the whole run locally against the committed
 *    ledger. That is the path that has actually delivered 340 articles, and it is the one
 *    to use for thousands of sources: it is resumable, parallel, and does not depend on a
 *    browser tab staying open.
 *
 * The browser's own contribution to both paths is the SHA-256. It is computed here over
 * the selected bytes with WebCrypto, and it is the record id on the backend — so
 * re-uploading the same PDF under a different name lands on the row that already exists
 * instead of minting a second article. That is the one failure in this pipeline that
 * cannot be undone after publication.
 *
 * Extraction and the quality standard still exist in exactly ONE implementation, in
 * Python. Nothing here re-implements the section 13 phrase list or decides a status; the
 * page renders verdicts it was given.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Layout from '../../../components/Layout';
import SEO from '../../../components/SEO';
import {
  confirmBlogSources, listBlogSources, proposeBlogDraft, registerBlogSources,
  retryBlogSource,
} from '../../../api/seo';
import type { BlogDraftResponse, BlogSourceView } from '../../../api/seo';
import Select, { type SelectOption } from '../../../components/ui/Select';

interface PageProps { signOut?: () => void; user?: any; }

/**
 * The two categories, and the two article classes.
 *
 * Mirrors `CATEGORIES` and `ARTICLE_CLASSES` in scripts/blog_quality_v2.py, which is the
 * authority. `src/test/BlogStudioContract.test.ts` reads that file and fails if the two
 * lists drift, because a category this page can emit but the gate rejects would produce a
 * work order that dies at ingestion — and now also a POST the Lambda answers with a 400.
 *
 * A fixed list rather than a free-text datalist is deliberate. The older Blog Creator
 * form uses `<input list=...>`, so a typo silently creates a third category — and
 * `/blog/` serves whichever category sorts FIRST alphabetically, which means
 * "Conversatons" would have taken over the public blog index.
 */
const CATEGORIES = [ 'Conversations', 'Gastronomy' ] as const;
const ARTICLE_CLASSES = [ 'ARCHIVE_DERIVED', 'ORIGINAL_109' ] as const;

type Category = typeof CATEGORIES[ number ];
type ArticleClass = typeof ARTICLE_CLASSES[ number ];

/* Derived from the two lists above so they cannot drift - BlogStudioContract.test.ts reads
   scripts/blog_quality_v2.py and fails if they do, and that check must keep biting. */
const CATEGORY_OPTIONS: SelectOption[] = CATEGORIES.map( v => ( { value: v, label: v } ) );
const ARTICLE_CLASS_OPTIONS: SelectOption[] = ARTICLE_CLASSES.map( v => ( { value: v, label: v } ) );

/** Section 29, split by who can decide it. Kept in step with blog_quality_v2.HUMAN_GATES. */
const MACHINE_GATES = [ 'NON_DUPLICATION', 'TIGHTNESS', 'METADATA' ] as const;
const HUMAN_GATES = [
  'DISTINCTION', 'SOURCE_FIDELITY', 'CLARITY', 'VALUE', 'ORIGINAL_EXPRESSION',
  'SUBSTANCE', 'VOICE', 'FACTUAL_INTEGRITY', 'ATTRIBUTION', 'PRIVACY',
  'HUMAN_QUALITY_TEST',
] as const;

/**
 * The source statuses, from `blog_sources.py`. These describe a FILE, not an article —
 * the article statuses are a separate vocabulary owned by the quality gate.
 */
const SOURCE_STATUSES = [
  'PENDING_UPLOAD', 'UPLOADED', 'EXTRACTING', 'EXTRACTED', 'EXTRACTION_FAILED',
] as const;

/** While any source sits in one of these, the backend still has work in flight. */
const IN_FLIGHT_STATUSES: readonly string[] = [ 'PENDING_UPLOAD', 'UPLOADED', 'EXTRACTING' ];

const POLL_INTERVAL_MS = 4000;

interface PickedFile {
  name: string;
  size: number;
  sha256: string;
  /**
   * The File itself, held from selection until the presigned PUT.
   *
   * Registration and upload are two separate requests, so the bytes have to survive in
   * between. Keyed by digest below, because the backend's `sourceId` is
   * `blogsrc_<sha256>` — that is what lets a returned registration find its own file.
   */
  file: File;
  /** Per-file overrides, so one batch can mix both categories. */
  category: Category;
  articleClass: ArticleClass;
}

interface LedgerRow {
  sourceType: string;
  sourceRef: string;
  sourceSha256: string;
  status: string;
  category: string;
  slug: string;
  title: string;
  sourceTitle: string;
  extractedWords: number;
  batchFile: string;
  publishedAt: string;
  error: string;
}

interface StudioProps extends PageProps {
  ledger: LedgerRow[];
  ledgerUpdatedAt: string;
  ledgerPresent: boolean;
}

type Tab = 'uploads' | 'bulk' | 'standard';

const th: React.CSSProperties = {
  padding: '8px 10px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#6b7280',
  borderBottom: '1px solid #e5e7eb',
};
const td: React.CSSProperties = { padding: '6px 10px', fontSize: 12, verticalAlign: 'top' };
const btn: React.CSSProperties = {
  padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12,
  fontFamily: 'inherit',
};
const label: React.CSSProperties = {
  fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4,
};
const input: React.CSSProperties = {
  width: '100%', padding: '8px 12px', borderRadius: 8, border: '1.5px solid #e5e7eb',
  fontSize: 13, fontFamily: 'inherit',
};
const muted: React.CSSProperties = { fontSize: 11, color: 'rgba(0,0,0,.54)', marginTop: 4 };

/** One colour per source status, so a stalled batch is legible without reading the words. */
const STATUS_COLOUR: Record<string, string> = {
  PENDING_UPLOAD: 'rgba(0,0,0,.54)',
  UPLOADED: '#0369a1',
  EXTRACTING: '#a16207',
  EXTRACTED: '#15803d',
  EXTRACTION_FAILED: '#b91c1c',
};

/** SHA-256 of the selected bytes, matching what Python computes over the same file. */
async function sha256 ( file: File ): Promise<string> {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest( 'SHA-256', buffer );
  return Array.from( new Uint8Array( digest ) )
    .map( ( byte ) => byte.toString( 16 ).padStart( 2, '0' ) )
    .join( '' );
}

/**
 * The one request on this page that must NOT be authenticated.
 *
 * A presigned URL carries its own SigV4 signature in the query string. Adding a Cognito
 * `Authorization` header on top makes S3 see two competing auth mechanisms and reject the
 * PUT outright — so this is a bare `fetch`, never `seoToolsFetch` or `authFetch`. The
 * hazard is invisible at the call site otherwise, which is why it lives in its own
 * function with its own name, and why `BlogStudioContract.test.ts` asserts it.
 *
 * It also means the bytes never pass through API Gateway, so the 10 MB payload ceiling
 * and the 30-second integration timeout do not apply to them at all.
 */
async function putPresigned ( uploadUrl: string, file: File ): Promise<boolean> {
  const response = await fetch( uploadUrl, {
    method: 'PUT',
    body: file,
    headers: { 'Content-Type': 'application/pdf' },
  } );
  return response.ok;
}

/**
 * The link a reviewer opens to read the source document itself, or `''`.
 *
 * Section 2 of the standard is explicit that an article may not be built from a title or an
 * excerpt, so a one-click route to the actual document is the difference between that rule
 * being followed and being ticked.
 *
 * `sourceUrl` is the apex URL of an uploaded PDF and the backend deliberately returns `''`
 * rather than a URL that would 403 — so if the prefix is ever moved back under the gated
 * root this degrades to no link instead of a dead one. A URL source was never uploaded and
 * carries its own address in `sourceRef`, which is the same document.
 */
function reviewLink ( row: BlogSourceView ): string {
  if ( row.sourceUrl ) return row.sourceUrl;
  return row.sourceType === 'url' && /^https?:\/\//i.test( row.sourceRef ) ? row.sourceRef : '';
}

function formatBytes ( size: number ): string {
  if ( size < 1024 ) return `${ size } B`;
  if ( size < 1024 * 1024 ) return `${ ( size / 1024 ).toFixed( 0 ) } kB`;
  return `${ ( size / ( 1024 * 1024 ) ).toFixed( 1 ) } MB`;
}

/**
 * URLs, one per line, `#` comments dropped — the same shape `--url-file` accepts, so the
 * same text can be pasted here or saved as a file without transformation.
 */
function parseUrls ( raw: string ): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for ( const line of raw.split( /\r?\n/ ) )
  {
    const trimmed = line.trim();
    if ( !trimmed || trimmed.startsWith( '#' ) ) continue;
    const value = /^https?:\/\//i.test( trimmed ) ? trimmed : `https://${ trimmed }`;
    if ( seen.has( value ) ) continue;
    seen.add( value );
    out.push( value );
  }
  return out;
}

const BlogStudio: React.FC<StudioProps> = ( { signOut, user, ledger, ledgerUpdatedAt, ledgerPresent } ) => {
  const [ tab, setTab ] = useState<Tab>( 'uploads' );
  const [ files, setFiles ] = useState<PickedFile[]>( [] );
  const [ urlText, setUrlText ] = useState( '' );
  const [ category, setCategory ] = useState<Category>( 'Conversations' );
  const [ articleClass, setArticleClass ] = useState<ArticleClass>( 'ARCHIVE_DERIVED' );
  const [ hashing, setHashing ] = useState( false );
  const [ uploading, setUploading ] = useState( false );
  const [ log, setLog ] = useState<string[]>( [] );
  const [ dragging, setDragging ] = useState( false );
  const [ sources, setSources ] = useState<BlogSourceView[]>( [] );
  const [ aiDraftEnabled, setAiDraftEnabled ] = useState( false );
  const [ maxSourceBytes, setMaxSourceBytes ] = useState( 0 );
  const [ drafts, setDrafts ] = useState<Record<string, BlogDraftResponse>>( {} );
  const [ workingId, setWorkingId ] = useState( '' );
  const [ apiError, setApiError ] = useState( '' );
  const fileInput = useRef<HTMLInputElement>( null );

  const addLog = useCallback( ( message: string ) => {
    setLog( ( previous ) => [ ...previous, `[${ new Date().toLocaleTimeString() }] ${ message }` ] );
  }, [] );

  const urls = useMemo( () => parseUrls( urlText ), [ urlText ] );

  /** Read the live source list. Also carries the enums and the cost flag. */
  const refresh = useCallback( async () => {
    try
    {
      const data = await listBlogSources();
      setSources( Array.isArray( data.sources ) ? data.sources : [] );
      setAiDraftEnabled( Boolean( data.aiDraftEnabled ) );
      setMaxSourceBytes( Number( data.maxSourceBytes || 0 ) );
      setApiError( '' );
    } catch ( error: any )
    {
      // Surfaced rather than swallowed: an empty table and a broken request look
      // identical otherwise, and the operator would keep picking files into nothing.
      setApiError( String( error?.message || 'could not read the source list' ) );
    }
  }, [] );

  useEffect( () => { void refresh(); }, [ refresh ] );

  const inFlight = useMemo(
    () => sources.filter( ( row ) => IN_FLIGHT_STATUSES.includes( row.status ) ).length,
    [ sources ] );

  /**
   * Poll only while the backend still has something to do, and stop when it does not.
   *
   * An unconditional interval would keep an idle admin tab calling an authenticated
   * Lambda every four seconds for as long as it stays open.
   */
  useEffect( () => {
    if ( inFlight === 0 ) return undefined;
    const timer = setInterval( () => { void refresh(); }, POLL_INTERVAL_MS );
    return () => clearInterval( timer );
  }, [ inFlight, refresh ] );

  /** Hash every selected PDF and de-duplicate by digest, not by filename. */
  const addFiles = useCallback( async ( incoming: FileList | File[] ) => {
    const list = Array.from( incoming );
    const pdfs = list.filter( ( file ) => /\.pdf$/i.test( file.name ) );
    const rejected = list.length - pdfs.length;
    if ( rejected > 0 ) addLog( `${ rejected } non-PDF file(s) ignored` );
    // Checked here as well as in the Lambda, because a file over the limit would
    // otherwise be hashed, registered, uploaded and only then refused.
    const sized = maxSourceBytes > 0
      ? pdfs.filter( ( file ) => file.size <= maxSourceBytes )
      : pdfs;
    if ( sized.length < pdfs.length )
    {
      addLog( `${ pdfs.length - sized.length } file(s) over the ${ formatBytes( maxSourceBytes ) } limit ignored` );
    }
    if ( !sized.length ) return;

    setHashing( true );
    try
    {
      const hashed: PickedFile[] = [];
      for ( const file of sized )
      {
        hashed.push( {
          name: file.name,
          size: file.size,
          sha256: await sha256( file ),
          file,
          category,
          articleClass,
        } );
      }
      setFiles( ( previous ) => {
        // Digest, not filename. Two exports of the same document under different names are
        // one source, and the backend resolves them that way too — so showing them as two
        // rows here would promise work that will not happen.
        const known = new Set( previous.map( ( item ) => item.sha256 ) );
        const fresh = hashed.filter( ( item ) => !known.has( item.sha256 ) );
        const duplicates = hashed.length - fresh.length;
        if ( duplicates > 0 ) addLog( `${ duplicates } duplicate file(s) skipped (same SHA-256)` );
        if ( fresh.length > 0 ) addLog( `${ fresh.length } PDF(s) added` );
        return [ ...previous, ...fresh ];
      } );
    } catch ( error: any )
    {
      addLog( `Hashing failed: ${ error?.name || 'error' }` );
    } finally
    {
      setHashing( false );
    }
  }, [ addLog, category, articleClass, maxSourceBytes ] );

  const onDrop = useCallback( ( event: React.DragEvent<HTMLDivElement> ) => {
    event.preventDefault();
    setDragging( false );
    if ( event.dataTransfer?.files?.length ) void addFiles( event.dataTransfer.files );
  }, [ addFiles ] );

  const total = files.length + urls.length;

  /**
   * Register, upload, confirm — the three phases, in order.
   *
   * The PUTs run one at a time on purpose. The bytes go direct to S3, so there is no
   * Lambda concurrency to win by parallelising, and a serial loop keeps the activity log
   * readable and a partial failure attributable to one named file.
   */
  const sendToPipeline = useCallback( async () => {
    if ( total === 0 || uploading ) return;
    setUploading( true );
    try
    {
      const registered = await registerBlogSources( {
        category,
        articleClass,
        sources: [
          ...files.map( ( item ) => ( {
            sourceType: 'pdf' as const,
            fileName: item.name,
            sha256: item.sha256,
            bytes: item.size,
            category: item.category,
            articleClass: item.articleClass,
          } ) ),
          ...urls.map( ( url ) => ( {
            sourceType: 'url' as const, url, category, articleClass,
          } ) ),
        ],
      } );
      addLog( `${ registered.sources.length } source(s) registered against ${ registered.bucket }` );

      // Both keys, because a registration can be matched by either. `sourceId` is the
      // reliable one (it is derived from the digest); `sourceRef` is the fallback.
      const byId = new Map( files.map( ( item ) => [ `blogsrc_${ item.sha256 }`, item.file ] ) );
      const byName = new Map( files.map( ( item ) => [ item.name, item.file ] ) );

      const confirmable: string[] = [];
      for ( const entry of registered.sources )
      {
        if ( entry.alreadyKnown )
        {
          addLog( `Already known, no re-upload: ${ entry.sourceRef } (${ entry.status })` );
          continue;
        }
        if ( !entry.uploadUrl )
        {
          // A URL source carries no bytes, so it is already UPLOADED and only needs the
          // worker started.
          confirmable.push( entry.sourceId );
          continue;
        }
        const blob = byId.get( entry.sourceId ) || byName.get( entry.sourceRef );
        if ( !blob )
        {
          addLog( `No file held for ${ entry.sourceRef } — re-pick it and upload again` );
          continue;
        }
        const ok = await putPresigned( entry.uploadUrl, blob );
        if ( ok )
        {
          confirmable.push( entry.sourceId );
          addLog( `Uploaded ${ entry.sourceRef }` );
        } else
        {
          addLog( `Upload rejected by S3: ${ entry.sourceRef }` );
        }
      }

      if ( confirmable.length > 0 )
      {
        const confirmed = await confirmBlogSources( confirmable );
        addLog( `${ confirmed.confirmed.length } confirmed, worker ${ confirmed.workerStarted ? 'started' : 'not started' }` );
        if ( confirmed.missingUpload.length > 0 )
        {
          addLog( `${ confirmed.missingUpload.length } source(s) had no object in S3 — upload again` );
        }
        if ( confirmed.unknownSourceId.length > 0 )
        {
          addLog( `${ confirmed.unknownSourceId.length } unknown sourceId(s) reported` );
        }
      }
      setFiles( [] );
      setUrlText( '' );
      await refresh();
    } catch ( error: any )
    {
      addLog( `Intake failed: ${ error?.message || 'error' }` );
    } finally
    {
      setUploading( false );
    }
  }, [ addLog, articleClass, category, files, refresh, total, uploading, urls ] );

  const retry = useCallback( async ( sourceId: string ) => {
    setWorkingId( sourceId );
    try
    {
      const result = await retryBlogSource( sourceId );
      addLog( `Requeued ${ sourceId } (${ result.status }), worker ${ result.workerStarted ? 'started' : 'not started' }` );
      await refresh();
    } catch ( error: any )
    {
      addLog( `Retry failed: ${ error?.message || 'error' }` );
    } finally
    {
      setWorkingId( '' );
    }
  }, [ addLog, refresh ] );

  const propose = useCallback( async ( sourceId: string ) => {
    setWorkingId( sourceId );
    try
    {
      const result = await proposeBlogDraft( sourceId );
      setDrafts( ( previous ) => ( { ...previous, [ sourceId ]: result } ) );
      addLog( `Draft proposed for ${ sourceId } by ${ result.aiDraft.model || 'the model' }` );
      await refresh();
    } catch ( error: any )
    {
      addLog( `Draft failed: ${ error?.message || 'error' }` );
    } finally
    {
      setWorkingId( '' );
    }
  }, [ addLog, refresh ] );

  const workOrder = useMemo( () => ( {
    generatedAt: new Date().toISOString(),
    standard: 'WECARE.DIGITAL Conversations Content Quality Standard v2',
    category,
    articleClass,
    note: 'Consume with: python scripts/blog_ingest.py ingest --work-order <this file> '
      + '--pdf-dir <directory holding the PDFs>',
    sources: [
      ...files.map( ( file ) => ( {
        sourceType: 'pdf',
        fileName: file.name,
        sha256: file.sha256,
        bytes: file.size,
        category: file.category,
        articleClass: file.articleClass,
      } ) ),
      ...urls.map( ( url ) => ( {
        sourceType: 'url',
        url,
        category,
        articleClass,
      } ) ),
    ],
  } ), [ files, urls, category, articleClass ] );

  const download = useCallback( () => {
    const blob = new Blob( [ `${ JSON.stringify( workOrder, null, 2 ) }\n` ],
      { type: 'application/json' } );
    const href = URL.createObjectURL( blob );
    const anchor = document.createElement( 'a' );
    anchor.href = href;
    anchor.download = `work-order-${ new Date().toISOString().slice( 0, 10 ) }.json`;
    anchor.click();
    URL.revokeObjectURL( href );
    addLog( `Work order exported: ${ workOrder.sources.length } source(s)` );
  }, [ workOrder, addLog ] );

  const copyCommand = useCallback( async () => {
    const command = 'python scripts/blog_ingest.py ingest --work-order ~/Downloads/'
      + `work-order-${ new Date().toISOString().slice( 0, 10 ) }.json --pdf-dir <your-pdf-directory>`;
    try
    {
      await navigator.clipboard.writeText( command );
      addLog( 'Ingestion command copied' );
    } catch
    {
      addLog( 'Clipboard unavailable — command shown below' );
    }
  }, [ addLog ] );

  const liveRollup = useMemo( () => {
    const byStatus: Record<string, number> = {};
    for ( const row of sources ) byStatus[ row.status ] = ( byStatus[ row.status ] || 0 ) + 1;
    return byStatus;
  }, [ sources ] );

  const rollup = useMemo( () => {
    const byStatus: Record<string, number> = {};
    const byCategory: Record<string, number> = {};
    const bySourceType: Record<string, number> = {};
    for ( const row of ledger )
    {
      byStatus[ row.status ] = ( byStatus[ row.status ] || 0 ) + 1;
      if ( row.category ) byCategory[ row.category ] = ( byCategory[ row.category ] || 0 ) + 1;
      bySourceType[ row.sourceType ] = ( bySourceType[ row.sourceType ] || 0 ) + 1;
    }
    return {
      total: ledger.length,
      withArticle: ledger.filter( ( row ) => row.slug ).length,
      pending: ledger.filter( ( row ) => !row.slug && row.status !== 'EXTRACTION_FAILED' ).length,
      failed: ledger.filter( ( row ) => row.status === 'EXTRACTION_FAILED' ).length,
      byStatus, byCategory, bySourceType,
    };
  }, [ ledger ] );

  return (
    <Layout user={ user } onSignOut={ signOut }>
      <SEO title="Blog Studio" description="PDF and URL intake for the blog" noindex />

      <div style={ { marginBottom: 16 } }>
        <h1 style={ { fontSize: 20, fontWeight: 700, margin: 0 } }>Blog Studio</h1>
        <p style={ { fontSize: 13, color: '#6b7280', margin: '4px 0 0' } }>
          PDF and URL intake under the Conversations Content Quality Standard v2.
        </p>
      </div>

      <div style={ { display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' } }>
        { ( [
          [ 'uploads', `Uploads${ sources.length ? ` (${ sources.length })` : '' }` ],
          [ 'bulk', `Bulk ledger${ ledger.length ? ` (${ ledger.length })` : '' }` ],
          [ 'standard', 'What is checked' ],
        ] as [ Tab, string ][] ).map( ( [ id, text ] ) => (
          <button key={ id } onClick={ () => setTab( id ) }
            style={ {
              ...btn,
              background: tab === id ? '#d1f470' : '#f3f4f6',
              fontWeight: tab === id ? 600 : 400,
            } }>
            { text }
          </button>
        ) ) }
      </div>

      { tab === 'uploads' && (
        <div style={ { maxWidth: 1040 } }>
          <div className="card" style={ { padding: 16, marginBottom: 16 } }>
            <p style={ { fontSize: 12, color: '#374151', lineHeight: 1.7, margin: 0 } }>
              <strong>This tab uploads for real.</strong> Sources registered here go to S3,
              are extracted by a backend worker and appear below with a live status. It is
              the right path for an interactive batch. For thousands of sources use the
              work order at the bottom of this tab and run the CLI, which is resumable and
              parallel — the <strong>Bulk ledger</strong> tab shows what that path has
              already produced.
            </p>
          </div>

          { apiError && (
            <div className="card" style={ { padding: 16, marginBottom: 16 } }>
              <div style={ { fontSize: 12, color: '#b91c1c' } }>
                The source list could not be read: { apiError }
              </div>
              <button onClick={ () => { void refresh(); } }
                style={ { ...btn, background: '#f3f4f6', marginTop: 8 } }>
                Try again
              </button>
            </div>
          ) }

          <div className="card" style={ { padding: 20, marginBottom: 16 } }>
            <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 } }>
              <div>
                { /*
                   * SHAPE (b), design 5.2, and this is the canonical case for it: `label` is a
                   * shared inline style object the component cannot reproduce, so the external
                   * <label> stays and is pointed at by id instead of being recreated inside
                   * Select. Its `for` attribute is DROPPED - the trigger is a <button>, and per
                   * HTML-AAM a button takes its accessible name from its CONTENTS, so a `for`
                   * naming it is misleading rather than useful. `labelledBy` is what makes the
                   * name compute, and it is asserted by a test rather than by eye.
                   * (Worded without the JSX attribute spelling on purpose: the batch gate greps
                   * for it, and a gate that reports its own commentary gets switched off.)
                   */ }
                <label style={ label } id="blog-studio-category-label">Category</label>
                <Select labelledBy="blog-studio-category-label" value={ category }
                  onChange={ v => setCategory( v as Category ) }
                  options={ CATEGORY_OPTIONS } />
                <div style={ muted }>
                  The only two categories on the live site. Applied to sources added next.
                </div>
              </div>
              <div>
                { /* SHAPE (b) again, for the same reason, and the id is dropped with it. */ }
                <label style={ label } id="blog-studio-class-label">Article class</label>
                <Select labelledBy="blog-studio-class-label" value={ articleClass }
                  onChange={ v => setArticleClass( v as ArticleClass ) }
                  options={ ARTICLE_CLASS_OPTIONS } />
                <div style={ muted }>
                  ARCHIVE_DERIVED gets a fresh slug and today&apos;s publication date.
                  ORIGINAL_109 preserves both.
                </div>
              </div>
            </div>

            <label style={ label }>PDF sources</label>
            <div
              onDragOver={ ( event ) => { event.preventDefault(); setDragging( true ); } }
              onDragLeave={ () => setDragging( false ) }
              onDrop={ onDrop }
              onClick={ () => fileInput.current?.click() }
              role="button"
              tabIndex={ 0 }
              onKeyDown={ ( event ) => {
                if ( event.key === 'Enter' || event.key === ' ' ) fileInput.current?.click();
              } }
              aria-label="Add PDF files"
              style={ {
                border: `2px dashed ${ dragging ? '#84cc16' : '#e5e7eb' }`,
                background: dragging ? '#f7fee7' : '#fafafa',
                borderRadius: 10, padding: '28px 16px', textAlign: 'center', cursor: 'pointer',
              } }>
              <div style={ { fontSize: 13, fontWeight: 600, color: '#374151' } }>
                { hashing ? 'Hashing…' : 'Drop PDFs here, or click to choose' }
              </div>
              <div style={ muted }>
                Read locally first to compute each file&apos;s SHA-256. Nothing leaves the
                browser until you choose to send it.
                { maxSourceBytes > 0 ? ` Up to ${ formatBytes( maxSourceBytes ) } each.` : '' }
              </div>
            </div>
            <input ref={ fileInput } type="file" accept="application/pdf,.pdf" multiple
              aria-label="PDF files to add"
              style={ { display: 'none' } }
              onChange={ ( event ) => {
                if ( event.target.files ) void addFiles( event.target.files );
                event.target.value = '';
              } } />

            { files.length > 0 && (
              <div style={ { marginTop: 12, overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse' } }>
                  <caption style={ { ...muted, captionSide: 'bottom', textAlign: 'left' } }>
                    Selected, not yet sent.
                  </caption>
                  <thead>
                    <tr>
                      <th style={ th } scope="col">File</th>
                      <th style={ th } scope="col">Size</th>
                      <th style={ th } scope="col">SHA-256</th>
                      <th style={ th } scope="col">Category</th>
                      <th style={ th } scope="col">Remove</th>
                    </tr>
                  </thead>
                  <tbody>
                    { files.map( ( file ) => (
                      <tr key={ file.sha256 } style={ { borderBottom: '1px solid #f3f4f6' } }>
                        <td style={ td }>{ file.name }</td>
                        <td style={ td }>{ formatBytes( file.size ) }</td>
                        <td style={ { ...td, fontFamily: 'ui-monospace, monospace', fontSize: 11 } }>
                          { file.sha256.slice( 0, 12 ) }…
                        </td>
                        <td style={ td }>{ file.category }</td>
                        <td style={ td }>
                          <button style={ { ...btn, background: '#f3f4f6', padding: '2px 8px' } }
                            aria-label={ `Remove ${ file.name }` }
                            onClick={ () => setFiles(
                              ( previous ) => previous.filter( ( item ) => item.sha256 !== file.sha256 ) ) }>
                            Remove
                          </button>
                        </td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            ) }

            <div style={ { marginTop: 16 } }>
              <label style={ label } htmlFor="blog-studio-urls">URL sources</label>
              <textarea id="blog-studio-urls" value={ urlText } rows={ 6 }
                onChange={ ( event ) => setUrlText( event.target.value ) }
                placeholder={ '# one per line, comments allowed\nhttps://example.com/an-article' }
                style={ { ...input, fontFamily: 'ui-monospace, monospace', fontSize: 12, resize: 'vertical' } } />
              <div style={ { fontSize: 11, color: '#6b7280', marginTop: 4 } }>
                { urls.length } URL(s) recognised. A URL needs no upload — it is fetched by
                the worker.
              </div>
            </div>

            <div style={ { marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' } }>
              <button onClick={ () => { void sendToPipeline(); } }
                disabled={ total === 0 || uploading || hashing }
                style={ {
                  ...btn,
                  background: total === 0 || uploading || hashing ? '#f3f4f6' : '#d1f470',
                  fontWeight: 600,
                } }>
                { uploading ? 'Sending…' : `Upload and extract${ total ? ` (${ total })` : '' }` }
              </button>
              <button style={ { ...btn, background: '#f3f4f6' } }
                onClick={ () => { setFiles( [] ); setUrlText( '' ); addLog( 'Selection cleared' ); } }>
                Clear selection
              </button>
              <span style={ { fontSize: 11, color: 'rgba(0,0,0,.54)' } }>
                Each PDF is sent straight to S3 with a presigned URL, then confirmed. A
                source already known by its SHA-256 is skipped rather than duplicated.
              </span>
            </div>
          </div>

          <div className="card" style={ { padding: 20, marginBottom: 16 } }>
            <div style={ { display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' } }>
              <h2 style={ { fontSize: 14, fontWeight: 700, margin: '0 0 8px' } }>
                Uploaded sources
              </h2>
              <div style={ { display: 'flex', gap: 8, alignItems: 'center' } }>
                <span style={ { fontSize: 11, color: 'rgba(0,0,0,.54)' } }>
                  { inFlight > 0
                    ? `${ inFlight } in flight — refreshing every ${ POLL_INTERVAL_MS / 1000 }s`
                    : 'Nothing in flight' }
                </span>
                <button onClick={ () => { void refresh(); } }
                  style={ { ...btn, background: '#f3f4f6' } }>
                  Refresh now
                </button>
              </div>
            </div>
            <div style={ { display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, marginBottom: 12 } }>
              { SOURCE_STATUSES.map( ( name ) => (
                <div key={ name }>
                  <div style={ { fontSize: 18, fontWeight: 700, color: STATUS_COLOUR[ name ] } }>
                    { liveRollup[ name ] || 0 }
                  </div>
                  <div style={ { color: 'rgba(0,0,0,.54)', fontSize: 11 } }>{ name }</div>
                </div>
              ) ) }
            </div>

            { sources.length === 0 ? (
              <div style={ { fontSize: 12, color: 'rgba(0,0,0,.54)' } }>
                No sources uploaded through this page yet.
              </div>
            ) : (
              <div style={ { overflowX: 'auto' } }>
                <table style={ { width: '100%', borderCollapse: 'collapse' } }>
                  <thead>
                    <tr>
                      <th style={ th } scope="col">Source</th>
                      <th style={ th } scope="col">Type</th>
                      <th style={ th } scope="col">Status</th>
                      <th style={ th } scope="col">Words</th>
                      <th style={ th } scope="col">Article status</th>
                      <th style={ th } scope="col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    { sources.map( ( row ) => (
                      <tr key={ row.sourceId } style={ { borderBottom: '1px solid #f3f4f6' } }>
                        <td style={ td }>
                          <div style={ { wordBreak: 'break-all' } }>{ row.sourceRef }</div>
                          { row.sourceTitle && (
                            <div style={ { color: '#6b7280', fontSize: 11 } }>{ row.sourceTitle }</div>
                          ) }
                          { reviewLink( row ) && (
                            <div>
                              <a href={ reviewLink( row ) } target="_blank" rel="noopener noreferrer"
                                aria-label={ `Open the source document for ${ row.sourceRef } in a new tab` }
                                style={ { fontSize: 11 } }>
                                Open the source document
                              </a>
                            </div>
                          ) }
                          { row.error && (
                            <div style={ { color: '#b91c1c', fontSize: 11 } }>{ row.error }</div>
                          ) }
                        </td>
                        <td style={ td }>{ row.sourceType }</td>
                        <td style={ { ...td, color: STATUS_COLOUR[ row.status ] || '#374151', fontWeight: 600 } }>
                          { row.status }
                        </td>
                        <td style={ td }>{ row.extractedWords || '—' }</td>
                        <td style={ td }>{ row.articleStatus || '—' }</td>
                        <td style={ td }>
                          { row.status === 'EXTRACTION_FAILED' && (
                            <button onClick={ () => { void retry( row.sourceId ); } }
                              disabled={ workingId === row.sourceId }
                              aria-label={ `Retry extraction for ${ row.sourceRef }` }
                              style={ { ...btn, background: '#f3f4f6', padding: '2px 8px' } }>
                              { workingId === row.sourceId ? 'Retrying…' : 'Retry' }
                            </button>
                          ) }
                          { row.status === 'EXTRACTED' && (
                            <button onClick={ () => { void propose( row.sourceId ); } }
                              disabled={ !aiDraftEnabled || workingId === row.sourceId }
                              aria-label={ `Propose a draft for ${ row.sourceRef }` }
                              style={ {
                                ...btn, padding: '2px 8px',
                                background: aiDraftEnabled ? '#d1f470' : '#f3f4f6',
                              } }>
                              { workingId === row.sourceId ? 'Drafting…' : 'Propose draft' }
                            </button>
                          ) }
                        </td>
                      </tr>
                    ) ) }
                  </tbody>
                </table>
              </div>
            ) }

            { !aiDraftEnabled && (
              <p style={ { fontSize: 11, color: 'rgba(0,0,0,.54)', margin: '12px 0 0', lineHeight: 1.6 } }>
                AI drafting is switched off in the cost flags
                ( <code>ENABLE_BEDROCK_ASSIST</code> ), so <strong>Propose draft</strong> is
                disabled rather than failing on the first click. Extraction and the quality
                gate are unaffected — they cost nothing per source and keep running.
              </p>
            ) }
          </div>

          { Object.keys( drafts ).length > 0 && (
            <div className="card" style={ { padding: 20, marginBottom: 16 } }>
              <h2 style={ { fontSize: 14, fontWeight: 700, margin: '0 0 4px' } }>
                Proposals, not approvals
              </h2>
              <p style={ { fontSize: 12, color: '#374151', lineHeight: 1.7, margin: '0 0 12px' } }>
                A draft below is something the model wrote and nothing more. It cannot reach
                <code> READY_TO_PUBLISH </code>, and not as a matter of policy: the fields
                that record the eleven section 29 human gates are outside the whitelist the
                model can write to, so no output — including an instruction hidden in a
                source PDF — can set them. Only a person recording those gates moves an
                article forward. See <strong>What is checked</strong>.
              </p>
              { Object.entries( drafts ).map( ( [ sourceId, draft ] ) => (
                <div key={ sourceId } style={ {
                  borderTop: '1px solid #e5e7eb', paddingTop: 12, marginTop: 12,
                } }>
                  <div style={ { fontSize: 12, fontWeight: 600, wordBreak: 'break-all' } }>
                    { sourceId }
                  </div>
                  <div style={ { display: 'flex', gap: 20, flexWrap: 'wrap', marginTop: 8, fontSize: 12 } }>
                    <div>
                      <div style={ { fontWeight: 700 } }>{ draft.aiDraft.assessment.status }</div>
                      <div style={ { color: 'rgba(0,0,0,.54)', fontSize: 11 } }>gate status</div>
                    </div>
                    <div>
                      <div style={ { fontWeight: 700 } }>{ draft.aiDraft.assessment.words }</div>
                      <div style={ { color: 'rgba(0,0,0,.54)', fontSize: 11 } }>words</div>
                    </div>
                    <div>
                      <div style={ { fontWeight: 700 } }>
                        { draft.readyToPublish ? 'yes' : 'no' }
                      </div>
                      <div style={ { color: 'rgba(0,0,0,.54)', fontSize: 11 } }>ready to publish</div>
                    </div>
                    <div>
                      <div style={ { fontWeight: 700 } }>{ draft.aiDraft.model || '—' }</div>
                      <div style={ { color: 'rgba(0,0,0,.54)', fontSize: 11 } }>model</div>
                    </div>
                  </div>
                  { ( [
                    [ 'Blocking', draft.aiDraft.assessment.blocking, '#b91c1c' ],
                    [ 'Review', draft.aiDraft.assessment.review, '#a16207' ],
                    [ 'Human gates outstanding', draft.aiDraft.assessment.humanGatesOutstanding, '#374151' ],
                  ] as [ string, string[], string ][] ).map( ( [ heading, items, colour ] ) => (
                    <div key={ heading } style={ { marginTop: 10 } }>
                      <div style={ { fontSize: 11, fontWeight: 600, color: colour } }>
                        { heading } ({ items.length })
                      </div>
                      { items.length > 0 ? (
                        <ul style={ {
                          fontSize: 11, color: '#374151', lineHeight: 1.7, paddingLeft: 18,
                          margin: '4px 0 0',
                        } }>
                          { items.map( ( item ) => <li key={ item }>{ item }</li> ) }
                        </ul>
                      ) : (
                        <div style={ muted }>none</div>
                      ) }
                    </div>
                  ) ) }
                  { draft.aiDraft.notes && (
                    <p style={ { fontSize: 11, color: '#374151', margin: '10px 0 0', lineHeight: 1.6 } }>
                      Model notes: { draft.aiDraft.notes }
                    </p>
                  ) }
                  <p style={ { fontSize: 11, color: 'rgba(0,0,0,.54)', margin: '10px 0 0', lineHeight: 1.6 } }>
                    { draft.note }
                  </p>
                </div>
              ) ) }
            </div>
          ) }

          <div className="card" style={ { padding: 20, marginBottom: 16 } }>
            <h2 style={ { fontSize: 14, fontWeight: 700, margin: '0 0 8px' } }>
              Bulk path — export a work order instead
            </h2>
            <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 12px' } }>
              { total === 0
                ? 'Add at least one source to export a work order.'
                : `${ files.length } PDF(s) and ${ urls.length } URL(s) selected. ` }
              The exported file records each source, its category and its SHA-256, and the
              CLI re-checks that hash against the file on disk and refuses a mismatch — so a
              wrongly selected file cannot become permanent provenance. Use this for
              thousands of sources: it runs in parallel, survives an interruption and does
              not need a browser tab.
            </p>
            <div style={ { display: 'flex', gap: 8, flexWrap: 'wrap' } }>
              <button onClick={ download } disabled={ total === 0 }
                style={ { ...btn, background: '#f3f4f6', fontWeight: 600 } }>
                Download work order
              </button>
              <button onClick={ () => { void copyCommand(); } } style={ { ...btn, background: '#f3f4f6' } }>
                Copy ingestion command
              </button>
            </div>
            <pre style={ {
              background: '#f9fafb', padding: 12, borderRadius: 8, fontSize: 11, lineHeight: 1.7,
              margin: '12px 0 0', whiteSpace: 'pre-wrap', color: '#374151',
            } }>{ `python scripts/blog_ingest.py ingest \\
    --work-order ~/Downloads/work-order-<date>.json \\
    --pdf-dir <directory holding the PDFs> --workers 8

python scripts/blog_ingest.py status
python scripts/blog_ingest.py draft --out content/conversations/drafts/CONV-001-CONV-025.json --limit 25

# after the editorial pass
python scripts/blog_quality_v2.py validate --manifest content/conversations/batches/CONV-001-CONV-025.json` }</pre>
          </div>

          { log.length > 0 && (
            <div className="card" style={ { padding: 16 } }>
              <h2 style={ { fontSize: 13, fontWeight: 600, margin: '0 0 8px' } }>Activity</h2>
              <div style={ {
                fontFamily: 'ui-monospace, monospace', fontSize: 11, color: 'rgba(0,0,0,.54)',
                maxHeight: 160, overflowY: 'auto',
              } }>
                { log.map( ( line, index ) => <div key={ index }>{ line }</div> ) }
              </div>
            </div>
          ) }
        </div>
      ) }

      { tab === 'bulk' && (
        <div style={ { maxWidth: 1100 } }>
          <div className="card" style={ { padding: 20, marginBottom: 16 } }>
            <h2 style={ { fontSize: 14, fontWeight: 700, margin: '0 0 4px' } }>
              Which article came from which source
            </h2>
            <p style={ { fontSize: 12, color: '#6b7280', margin: '0 0 12px' } }>
              The CLI path, read from <code>content/conversations/ledger.json</code> at
              build time — a committed file, not an API call, which is why it can hold
              thousands of rows cheaply.
              { ledgerUpdatedAt ? ` Ledger updated ${ ledgerUpdatedAt }.` : '' }
              { ' ' }Because the site is a static export, this reflects the last build — run
              the ingestion script and rebuild to refresh it. Sources sent from the{ ' ' }
              <strong>Uploads</strong> tab are stored server-side instead and appear there
              immediately.
            </p>
            { !ledgerPresent ? (
              <div style={ { fontSize: 12, color: '#6b7280' } }>
                No ledger committed yet. It is created by the first{ ' ' }
                <code>blog_ingest.py ingest</code> run.
              </div>
            ) : (
              <div style={ { display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 12 } }>
                { ( [
                  [ 'Sources', rollup.total ],
                  [ 'With an article', rollup.withArticle ],
                  [ 'Awaiting an article', rollup.pending ],
                  [ 'Extraction failed', rollup.failed ],
                ] as [ string, number ][] ).map( ( [ text, value ] ) => (
                  <div key={ text }>
                    <div style={ { fontSize: 20, fontWeight: 700 } }>{ value }</div>
                    <div style={ { color: '#6b7280' } }>{ text }</div>
                  </div>
                ) ) }
              </div>
            ) }
          </div>

          { ledger.length > 0 && (
            <div className="card" style={ { padding: 0, overflowX: 'auto' } }>
              <table style={ { width: '100%', borderCollapse: 'collapse' } }>
                <thead>
                  <tr>
                    <th style={ th } scope="col">Source</th>
                    <th style={ th } scope="col">Type</th>
                    <th style={ th } scope="col">Words</th>
                    <th style={ th } scope="col">Category</th>
                    <th style={ th } scope="col">Status</th>
                    <th style={ th } scope="col">Article</th>
                  </tr>
                </thead>
                <tbody>
                  { ledger.map( ( row ) => (
                    <tr key={ row.sourceSha256 } style={ { borderBottom: '1px solid #f3f4f6' } }>
                      <td style={ td }>
                        <div style={ { wordBreak: 'break-all' } }>{ row.sourceRef }</div>
                        { row.sourceTitle && (
                          <div style={ { color: '#9ca3af', fontSize: 11 } }>{ row.sourceTitle }</div>
                        ) }
                        { row.error && (
                          <div style={ { color: '#b91c1c', fontSize: 11 } }>{ row.error }</div>
                        ) }
                      </td>
                      <td style={ td }>{ row.sourceType }</td>
                      <td style={ td }>{ row.extractedWords || '—' }</td>
                      <td style={ td }>{ row.category || '—' }</td>
                      <td style={ td }>{ row.status }</td>
                      <td style={ td }>
                        { row.slug
                          ? <a href={ `https://wecare.digital/post/${ row.slug }/` }
                            rel="noopener noreferrer" target="_blank">{ row.slug }</a>
                          : <span style={ { color: '#9ca3af' } }>not written yet</span> }
                      </td>
                    </tr>
                  ) ) }
                </tbody>
              </table>
            </div>
          ) }
        </div>
      ) }

      { tab === 'standard' && (
        <div style={ { maxWidth: 820 } }>
          <div className="card" style={ { padding: 20, marginBottom: 16 } }>
            <h2 style={ { fontSize: 14, fontWeight: 700, margin: '0 0 8px' } }>
              The pipeline cannot approve an article
            </h2>
            <p style={ { fontSize: 13, color: '#374151', lineHeight: 1.7, margin: '0 0 12px' } }>
              Section 29 of the standard asks for a verdict on whether the writing is
              independently Anew rather than cosmetically rewritten, on whether it sounds
              like WECARE.DIGITAL, and on whether the material deserves its own article.
              Section 30 asks whether a reader would feel it was written because there was
              something worth saying. No program can answer those.
            </p>
            <p style={ { fontSize: 13, color: '#374151', lineHeight: 1.7, margin: '0 0 12px' } }>
              So the automated checks only ever move a record <strong>down</strong>. A
              record that passes every one of them lands on <code>EDITORIAL_QA</code>.
              Reaching <code>READY_TO_PUBLISH</code> — the only status that may enter the
              Wix queue — requires a person to have recorded the eleven human gates.
            </p>
            <p style={ { fontSize: 13, color: '#374151', lineHeight: 1.7, margin: 0 } }>
              That applies to the AI draft on the <strong>Uploads</strong> tab without an
              exception. A model draft is a <strong>proposal</strong>: it may write the
              title, body, metadata and tags, and it may write nothing else. The human-gate
              fields are outside the whitelist it writes into, so a draft cannot reach
              <code> READY_TO_PUBLISH </code>even if the source document instructs it to.
            </p>
          </div>

          <div style={ { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 } }>
            <div className="card" style={ { padding: 16 } }>
              <h3 style={ { fontSize: 13, fontWeight: 700, margin: '0 0 8px' } }>
                Decided automatically
              </h3>
              <ul style={ { fontSize: 12, color: '#374151', lineHeight: 1.9, paddingLeft: 18, margin: 0 } }>
                { MACHINE_GATES.map( ( name ) => <li key={ name }><code>{ name }</code></li> ) }
              </ul>
              <p style={ { fontSize: 11, color: '#6b7280', margin: '10px 0 0', lineHeight: 1.6 } }>
                Plus every mechanical clause: provenance and source hash, the length bands,
                the stock-phrase and self-help detectors, sentence-cadence uniformity,
                false-biography and unattributed-quotation detection, factual-review flags,
                slug and date rules per class, canonical and tag rules, the fixed author and
                the two categories, legacy markup, the image ban, and corpus-wide
                duplication by slug, title and body shingle.
              </p>
            </div>
            <div className="card" style={ { padding: 16 } }>
              <h3 style={ { fontSize: 13, fontWeight: 700, margin: '0 0 8px' } }>
                Requires a human verdict
              </h3>
              <ul style={ { fontSize: 12, color: '#374151', lineHeight: 1.9, paddingLeft: 18, margin: 0 } }>
                { HUMAN_GATES.map( ( name ) => <li key={ name }><code>{ name }</code></li> ) }
              </ul>
            </div>
          </div>

          <div className="card" style={ { padding: 16, marginTop: 16 } }>
            <h3 style={ { fontSize: 13, fontWeight: 700, margin: '0 0 8px' } }>
              Publication stays gated, and stays two-phase
            </h3>
            <p style={ { fontSize: 12, color: '#374151', lineHeight: 1.7, margin: 0 } }>
              Nothing on this page publishes. Conversations go out through{ ' ' }
              <code>wix_blog_migrate.py apply --mode publish</code>, whose default mode
              mutates nothing; Gastronomy through the <code>publish</code> input on the
              content-gate workflow. And because the public site is a static export, a
              published post is not visible until an Amplify build re-reads Wix.
            </p>
          </div>
        </div>
      ) }
    </Layout>
  );
};

/**
 * The committed ledger, read at build time.
 *
 * `node:fs` is imported inside the function rather than at module scope so it never
 * reaches the client bundle. A missing or malformed ledger yields an empty table rather
 * than failing the build: this is an internal admin view, and an unreadable working file
 * must not be able to stop the public site from building.
 */
export async function getStaticProps () {
  const fallback = { ledger: [], ledgerUpdatedAt: '', ledgerPresent: false };
  try
  {
    const [ { default: fs }, { default: path } ] = await Promise.all( [
      import( 'node:fs' ), import( 'node:path' ),
    ] );
    const file = path.join( process.cwd(), 'content', 'conversations', 'ledger.json' );
    if ( !fs.existsSync( file ) ) return { props: fallback };
    const document = JSON.parse( fs.readFileSync( file, 'utf8' ) );
    const rows = Array.isArray( document?.sources ) ? document.sources : [];
    return {
      props: {
        ledgerPresent: true,
        ledgerUpdatedAt: String( document?.updatedAt || '' ),
        ledger: rows.map( ( row: any ) => ( {
          sourceType: String( row?.sourceType || '' ),
          sourceRef: String( row?.sourceRef || '' ),
          sourceSha256: String( row?.sourceSha256 || '' ),
          status: String( row?.status || '' ),
          category: String( row?.category || '' ),
          slug: String( row?.slug || '' ),
          title: String( row?.title || '' ),
          sourceTitle: String( row?.sourceTitle || '' ),
          extractedWords: Number( row?.extractedWords || 0 ),
          batchFile: String( row?.batchFile || '' ),
          publishedAt: String( row?.publishedAt || '' ),
          error: String( row?.error || '' ),
        } ) ),
      },
    };
  } catch
  {
    return { props: fallback };
  }
}

export default BlogStudio;
