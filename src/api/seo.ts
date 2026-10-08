/**
 * SEO API client — one backend, the Admin-only `wecare-seo-tools` Lambda.
 *
 * This file used to carry TWO backends. The second was `seoFetch`, a client for a
 * separate `wecare-seo-platform` FastAPI service addressed through
 * `NEXT_PUBLIC_SEO_API_URL`, with its own credential store in
 * `localStorage.seo_token`. That half was removed on 2026-10-07 under owner decision
 * B1 = CUT, together with its 27 exports and the eight pages that were its only
 * consumers.
 *
 * Why it went rather than being fixed: `NEXT_PUBLIC_SEO_API_URL` is absent from the
 * `stack` branch environment, so `seoFetch` threw
 * `'SEO API URL not configured'` on every call and all eight screens errored on load.
 * Standing up a second backend platform, with a second login and a second token in
 * local storage, was a permanent cost carried for eight read-only screens that had
 * never worked on this deployment.
 *
 * What remains is the live half: `seoToolsFetch` / `seoToolsJson` over
 * `${API_BASE}/seo-tools/*`, which is Cognito-authenticated through `authFetch` and
 * backs blog-manager, pages-manager, blog-studio and the five blog-production pages.
 */
import { authFetch } from './client';
import { API_BASE } from '../config/constants';

/** Authenticated client for the Admin-only SEO tools Lambda. */
export function seoToolsFetch ( path: string, init: RequestInit = {} ): Promise<Response> {
  const route = path.replace( /^\/+/, '' );
  return authFetch( `${API_BASE}/seo-tools/${route}`, init );
}

/* ------------------------------------------------------------------------- *
 * Blog source intake (Admin-only, /api/seo-tools/blog-sources*)
 *
 * The shapes below mirror `amplify/functions/operations/seo-tools/blog_sources.py`
 * and `blog_draft.py`. They are written out rather than typed as `any` because the
 * admin page branches on `status`, `alreadyKnown` and `uploadUrl`, and a silent
 * rename on the Python side should show up as a type error here rather than as an
 * upload that appears to succeed and moves nothing.
 *
 * Note what is NOT here: the presigned PUT. That request goes straight to S3 and
 * must not carry a Cognito Authorization header, so it is a bare `fetch` at the
 * call site rather than anything routed through `seoToolsFetch`.
 * ------------------------------------------------------------------------- */

/**
 * One source as the list route projects it. Never carries the extracted text.
 *
 * Deliberately narrower than the stored record. The batch index that makes a batch-scoped
 * listing possible can project at most 20 non-key attributes, so `sourceSha256`,
 * `contentSha256`, `sourceDate`, `sourcePages`, `sourceBytes` and `extractedChars` are
 * reachable through `fetchBlogSourceDetail` and not here. None of them were rendered in a
 * list; the ledger table's `sourceSha256` is a different type and is unaffected.
 */
export interface BlogSourceView {
  sourceId: string;
  batchId: string;
  sourceType: string;
  sourceRef: string;
  /**
   * The apex URL of an uploaded PDF, or `''`.
   *
   * `blog_sources.source_url` returns `''` rather than a URL that would 403, so a prefix
   * moved back under the gated root degrades to no link instead of a dead one. Treat an
   * empty string as "there is nothing to open", never as a bug.
   */
  sourceUrl: string;
  status: string;
  category: string;
  articleClass: string;
  sourceTitle: string;
  extractedWords: number;
  slug: string;
  title: string;
  articleStatus: string;
  aiDraftStatus: string;
  gateBlocking: string[];
  gateReview: string[];
  /**
   * Every downstream stage's state, as one attribute.
   *
   * It is a map rather than sixteen sibling fields because DynamoDB caps a GSI at 20
   * projected non-key attributes and the batch index already spends 17 of them. A map counts
   * as one name, so the cap stopped being a design constraint. Every key is always present,
   * empty rather than absent, so a table cell never has to test for existence.
   */
  pipeline: BlogPipelineState;
  error: string;
  createdAt: string;
  updatedAt: string;
}

/** The per-stage state carried on a source row. Empty string means "not reached yet". */
export interface BlogPipelineState {
  analysisId: string;
  analysisVersion: number;
  sourceReviewedFully: string;
  templateId: string;
  templateVersion: number;
  qaRunId: string;
  qaStatus: string;
  signoffId: string;
  signedOffBy: string;
  publishStatus: string;
  publishedAt: string;
  postId: string;
  postUrl: string;
  verifyStatus: string;
  verifiedAt: string;
  repetitionStatus: string;
}

/** The gate's verdict on a proposed article. `humanGatesOutstanding` is why it cannot publish. */
export interface BlogDraftAssessment {
  status: string;
  words: number;
  blocking: string[];
  review: string[];
  humanGatesOutstanding: string[];
}

export interface BlogAiDraft {
  status: string;
  model: string;
  proposedAt: string;
  proposedBy: string;
  notes: string;
  inputTokens: number;
  outputTokens: number;
  proposal: Record<string, unknown>;
  assessment: BlogDraftAssessment;
}

/** The single-source route adds the extract and the draft to the list projection. */
export interface BlogSourceDetail extends BlogSourceView {
  /** The whole extracted text, fetched from S3 rather than read off the DynamoDB item. */
  sourceExtract: string;
  /**
   * Where the text lives, and a bounded preview of it.
   *
   * Both come from `blog_sources.source_detail` and were missing from this type until the source
   * review page tried to render the preview. The list view deliberately carries neither - see
   * `BlogSourceView` - so the detail view is the only place they exist, and a type that omitted
   * them made the one correct call site a compile error.
   */
  extractKey: string;
  extractPreview: string;
  draftRecord: Record<string, unknown>;
  aiDraft: BlogAiDraft | Record<string, never>;
}

export interface BlogSourcesResponse {
  ok: boolean;
  categories: string[];
  articleClasses: string[];
  humanGates: string[];
  /** False when ENABLE_BEDROCK_ASSIST is off, in which case blog-draft refuses. */
  aiDraftEnabled: boolean;
  maxSourceBytes: number;
  total: number;
  byStatus: Record<string, number>;
  byCategory: Record<string, number>;
  pending: number;
  extracted: number;
  failed: number;
  sources: BlogSourceView[];
}

export interface BlogSourceRegisterEntry {
  sourceType: 'pdf' | 'url';
  fileName?: string;
  sha256?: string;
  bytes?: number;
  url?: string;
  category?: string;
  articleClass?: string;
}

export interface BlogSourceRegisterRequest {
  category: string;
  articleClass: string;
  sources: BlogSourceRegisterEntry[];
}

/** One registration outcome. `uploadUrl` is empty for a URL and for an already-known source. */
export interface BlogSourceRegistration {
  sourceId: string;
  sourceRef: string;
  sourceType: string;
  status: string;
  alreadyKnown: boolean;
  uploadUrl: string;
  expiresInSeconds?: number;
}

export interface BlogSourceRegisterResponse {
  ok: boolean;
  sources: BlogSourceRegistration[];
  bucket: string;
}

export interface BlogSourceConfirmResponse {
  ok: boolean;
  confirmed: string[];
  /** Registered, but `head_object` found no bytes — the PUT never landed. */
  missingUpload: string[];
  unknownSourceId: string[];
  workerStarted: boolean;
}

export interface BlogSourceRetryResponse {
  ok: boolean;
  sourceId: string;
  status: string;
  workerStarted: boolean;
}

export interface BlogDraftResponse {
  ok: boolean;
  sourceId: string;
  aiDraft: BlogAiDraft;
  /** Always false coming out of a model call — no field it writes can set a human gate. */
  readyToPublish: boolean;
  note: string;
}

export interface BlogDraftAcceptResponse {
  ok: boolean;
  sourceId: string;
  articleStatus: string;
  blocking: string[];
  review: string[];
  humanGatesOutstanding: string[];
  readyToPublish: boolean;
}

/**
 * JSON over `seoToolsFetch`, raising on a transport failure OR on `ok: false`.
 *
 * The handler answers a rejected request with HTTP 400 and `{ ok: false, error }`, so
 * checking only `response.ok` would swallow the message the operator needs — which for
 * this surface is usually the specific validation the backend refused on.
 */
async function seoToolsJson<T> ( path: string, init: RequestInit = {} ): Promise<T> {
  const response = await seoToolsFetch( path, init );
  const payload = await response.json().catch( () => ( {} ) ) as T & { ok?: boolean; error?: string };
  if ( !response.ok || payload.ok === false )
  {
    throw new Error( payload.error || response.statusText || `seo-tools/${path} failed` );
  }
  return payload;
}

/** Every source with its status, plus the enums and flags the page renders against. */
export const listBlogSources = () => seoToolsJson<BlogSourcesResponse>( 'blog-sources' );

/** One source including its extract and draft. Split out because the extract is large. */
export const getBlogSource = ( sourceId: string ) =>
  seoToolsJson<{ ok: boolean; source: BlogSourceDetail }>(
    `blog-sources/${encodeURIComponent( sourceId )}` );

/** Register sources and get one presigned PUT per PDF. No bytes are sent by this call. */
export const registerBlogSources = ( body: BlogSourceRegisterRequest ) =>
  seoToolsJson<BlogSourceRegisterResponse>( 'blog-sources', {
    method: 'POST', body: JSON.stringify( body ),
  } );

/** Tell the backend the bytes arrived. It verifies each key itself, then starts the worker. */
export const confirmBlogSources = ( sourceIds: string[] ) =>
  seoToolsJson<BlogSourceConfirmResponse>( 'blog-sources/confirm', {
    method: 'POST', body: JSON.stringify( { sourceIds } ),
  } );

/** Put a failed source back in the queue. */
export const retryBlogSource = ( sourceId: string ) =>
  seoToolsJson<BlogSourceRetryResponse>( 'blog-sources/retry', {
    method: 'POST', body: JSON.stringify( { sourceId } ),
  } );

/** Ask the model for an article. A proposal only — it cannot reach READY_TO_PUBLISH. */
export const proposeBlogDraft = ( sourceId: string ) =>
  seoToolsJson<BlogDraftResponse>( 'blog-draft', {
    method: 'POST', body: JSON.stringify( { sourceId } ),
  } );

/** Accept a proposal, with a human's edits, as the working draft. Still not an approval. */
export const acceptBlogDraft = ( sourceId: string, edits: Record<string, unknown> ) =>
  seoToolsJson<BlogDraftAcceptResponse>( 'blog-draft-accept', {
    method: 'POST', body: JSON.stringify( { sourceId, edits } ),
  } );

/* ------------------------------------------------------------------------- *
 * Blog Production: batches, analysis, templates, QA, repetition, publish, verify
 *
 * These mirror the Python modules of the same names. Written out rather than typed as
 * `any` for the reason the block above gives, and with one addition that matters more
 * here: every one of these surfaces has a REFUSAL path the operator has to read. A
 * release that cannot happen, a sign-off the gate will not accept, a publish the kill
 * switch refused — each returns a reason, and a page that types the response as `any`
 * is a page where that reason quietly stops being rendered.
 * ------------------------------------------------------------------------- */

/** A production wave. `status` is DERIVED from the rollup wherever one is present. */
export interface BlogBatchView {
  batchId: string;
  name: string;
  description: string;
  defaultCategory: string;
  articleClass: string;
  defaultTemplateId: string;
  defaultTemplateVersion: string;
  tags: string[];
  /** Derived from the rollup when one was computed. Authoritative. */
  status: string;
  /**
   * The value last written by a refresh. It can lag the derived one, because a refresh reads
   * the batch index and a GSI is eventually consistent — exposed so the lag is visible rather
   * than papered over.
   */
  storedStatus: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  rollup?: BlogBatchRollup;
}

/** Counts derived from the source records on every read. Never an incremented counter. */
export interface BlogBatchRollup {
  sources: number;
  bySourceStatus: Record<string, number>;
  byArticleStatus: Record<string, number>;
  extracted: number;
  failed: number;
  pending: number;
  words: number;
  complete: boolean;
  note: string;
}

export interface BlogBatchesResponse {
  ok: boolean;
  batches: BlogBatchView[];
  total: number;
  categories: string[];
  articleClasses: string[];
  batchStatuses: string[];
}

export interface BlogBatchDetail extends BlogBatchView {
  rollup: BlogBatchRollup;
  sources: BlogSourceView[];
}

/** Mechanically derived evidence about a source. Never a judgement of quality. */
export interface BlogAnalysisSummary {
  words: number;
  paragraphs: number;
  sentences: number;
  meanSentenceWords: number;
  firstPersonPassages: number;
  checkableClaims: number;
  reviewFlagsTriggered: string[];
  quotations: number;
  unattributedQuotations: number;
  namedIndividuals: number;
  obsoleteMarkers: string[];
}

export interface BlogAnalysisView {
  analysisId: string;
  sourceId: string;
  batchId: string;
  version: number;
  extractSha256: string;
  summary: BlogAnalysisSummary;
  generatedBy: string;
  createdAt: string;
  reviewedBy: string;
  reviewedAt: string;
  /** '', 'YES' or 'NO'. Written ONLY by `recordBlogSourceReview`. */
  sourceReviewedFully: string;
  reviewNotes: string;
}

export interface BlogAnalysisEvidence {
  chars: number;
  words: number;
  paragraphs: number;
  sentences: number;
  longestParagraphWords: number;
  meanSentenceWords: number;
  firstPersonPassages: { paragraph: number; markers: number; text: string }[];
  checkableClaims: { sentence: number; reviewFlags: string[]; quantities: number; text: string }[];
  quotations: { text: string; attributionNearby: boolean }[];
  unattributedQuotations: number;
  namedIndividuals: string[];
  obsoleteMarkers: { kind: string; text: string }[];
}

export interface BlogAnalysisDetail extends BlogAnalysisView {
  evidence: BlogAnalysisEvidence;
}

export interface BlogBatchReviewState {
  sources: number;
  analysed: number;
  reviewed: number;
  awaitingAnalysis: number;
  awaitingReview: number;
  analysisVersions: number;
}

/** A section contract. `order` is the list position, never a field a caller supplies. */
export interface BlogTemplateSection {
  key: string;
  order: number;
  heading: string;
  required: boolean;
  headingRequired: boolean;
  minWords: number;
  maxWords: number;
  guidance: string;
}

export interface BlogTemplateView {
  recordId: string;
  templateId: string;
  version: number;
  name: string;
  description: string;
  category: string;
  articleClass: string;
  minWords: number;
  maxWords: number;
  sections: BlogTemplateSection[];
  forbiddenPhrases: string[];
  requireList: boolean;
  notes: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  deprecatedAt: string;
}

/** `created: false` means an unlocked version was edited in place; `true` means it forked. */
export interface BlogTemplateSaveResponse extends BlogTemplateView {
  ok: boolean;
  created: boolean;
  reason: string;
}

export interface BlogQaRunView {
  qaRunId: string;
  sourceId: string;
  batchId: string;
  verdict: string;
  status: string;
  words: number;
  blockingCount: number;
  reviewCount: number;
  /** Posts the duplication check actually compared against. A PASS is worth only this. */
  corpusChecked: number;
  bodySha256: string;
  templateId: string;
  templateVersion: number;
  analysisId: string;
  analysisVersion: number;
  ranBy: string;
  ranAt: string;
}

export interface BlogQaReport {
  qaRunId: string;
  sourceId: string;
  verdict: string;
  status: string;
  words: number;
  machineGate: Record<string, string>;
  blocking: string[];
  review: string[];
  notes: string[];
  humanGatesOutstanding: string[];
  declarationsRequired: string[];
  /** Only the section 20 domains this body actually touches. */
  reviewFlagsRequired: string[];
  corpus: { loaded: number; present: boolean; note: string };
  template: { checked: boolean; compliant: boolean; findings: string[]; templateName: string };
}

export interface BlogSignoffView {
  signoffId: string;
  sourceId: string;
  batchId: string;
  qaRunId: string;
  bodySha256: string;
  gates: Record<string, string>;
  declarations: Record<string, string>;
  statement: string;
  signedBy: string;
  signedAt: string;
  revokedAt: string;
  revokedBy: string;
  revokeReason: string;
}

/** `runStale`/`signoffStale` mean the body moved after the run or the signature. */
export interface BlogQaSourceState {
  sourceId: string;
  bodySha256: string;
  latestRun: BlogQaRunView | Record<string, never>;
  runStale: boolean;
  signoff: BlogSignoffView | Record<string, never>;
  signoffStale: boolean;
  releasable: boolean;
  reason: string;
  runs: number;
  signoffs: number;
}

export interface BlogQaResponse {
  ok: boolean;
  humanGates: string[];
  gateAnswers: string[];
  state?: BlogQaSourceState;
  runs?: BlogQaRunView[];
  signoffs?: BlogSignoffView[];
  batchState?: {
    sources: number; qaRun: number; byVerdict: Record<string, number>;
    signedOff: number; awaitingSignoff: number; totalRuns: number; totalSignoffs: number;
  };
  corpus?: { loaded: number; present: boolean; packaged: boolean; note: string };
}

/** A collection-level finding. Advisory: nothing here blocks a release. */
export interface BlogRepetitionPattern {
  kind: string;
  shape: string;
  count: number;
  share: number;
  severity: string;
  description: string;
  sources: string[];
}

export interface BlogRepetitionPair {
  a: string;
  b: string;
  aTitle: string;
  bTitle: string;
  bodySimilarity: number;
  severity: string;
}

export interface BlogRepetitionRunView {
  repetitionRunId: string;
  batchId: string;
  articles: number;
  pairCount: number;
  nearDuplicateCount: number;
  titlePairCount: number;
  distinctionPairCount: number;
  patternCount: number;
  dominantPatternCount: number;
  implicatedCount: number;
  cadenceSpread: number;
  ranBy: string;
  ranAt: string;
}

export interface BlogRepetitionReport extends BlogRepetitionRunView {
  pairs: BlogRepetitionPair[];
  titlePairs: { kind: string; a: string; b: string; aTitle: string; bTitle: string; similarity: number }[];
  distinctionPairs: { kind: string; a: string; b: string; aTitle: string; bTitle: string; similarity: number }[];
  patterns: BlogRepetitionPattern[];
  implicated: string[];
  note: string;
}

export interface BlogPublishJobView {
  jobId: string;
  sourceId: string;
  batchId: string;
  status: string;
  articleSlug: string;
  articleTitle: string;
  category: string;
  bodySha256: string;
  signoffId: string;
  qaRunId: string;
  templateId: string;
  templateVersion: number;
  releasedBy: string;
  releasedAt: string;
  attempts: number;
  postId: string;
  postUrl: string;
  publishedAt: string;
  error: string;
  createdAt: string;
  updatedAt: string;
}

/** Every source in the wave WITH the reason it cannot be released, not just the eligible ones. */
export interface BlogReleaseCandidate {
  sourceId: string;
  title: string;
  slug: string;
  releasable: boolean;
  reason: string;
  jobId: string;
  jobStatus: string;
}

export interface BlogPublishResponse {
  ok: boolean;
  jobStatuses: string[];
  queue: BlogPublishJobView[];
  /** True when a publish would be REFUSED before it is attempted. */
  wixWritesDisabled: boolean;
  batchState?: {
    sources: number; byStatus: Record<string, number>; published: number;
    queued: number; refused: number; failed: number; unreleased: number; jobs: number;
  };
  candidates?: BlogReleaseCandidate[];
}

export interface BlogVerifyAssertionResult {
  assertion: string;
  result: 'PASS' | 'FAIL' | 'SKIP';
  expected: string;
  found: string;
  note: string;
  description: string;
}

export interface BlogVerifyRunView {
  verificationRunId: string;
  sourceId: string;
  batchId: string;
  articleSlug: string;
  postId: string;
  status: string;
  assertions: number;
  passed: number;
  failed: number;
  skipped: number;
  failedAssertions: string[];
  readError: string;
  ranBy: string;
  ranAt: string;
}

export interface BlogVerifyReport extends BlogVerifyRunView {
  results: BlogVerifyAssertionResult[];
  expected: Record<string, string>;
  bodyLength: number;
  verified: boolean;
}

export interface BlogVerifyResponse {
  ok: boolean;
  /** The thirteen by name, so a page never hard-codes a list that can fall out of step. */
  assertions: { assertion: string; description: string }[];
  runs?: BlogVerifyRunView[];
  expected?: Record<string, string>;
  expectationNote?: string;
  batchState?: {
    sources: number; published: number; byStatus: Record<string, number>;
    verified: number; failed: number; awaitingVerification: number; runs: number;
  };
  pending?: string[];
}

/* ── Batches ─────────────────────────────────────────────────────────────── */

/** `withRollup: false` skips one index query per batch. A real cost switch, not a convenience. */
export const listBlogBatches = ( withRollup = true ) =>
  seoToolsJson<BlogBatchesResponse>(
    `blog-batches${withRollup ? '' : '?rollup=none'}` );

export const getBlogBatch = ( batchId: string, limit = 0 ) =>
  seoToolsJson<{ ok: boolean; batch: BlogBatchDetail }>(
    `blog-batches/${encodeURIComponent( batchId )}${limit ? `?limit=${limit}` : ''}` );

export const createBlogBatch = ( body: Record<string, unknown> ) =>
  seoToolsJson<BlogBatchView & { ok: boolean; rollup: BlogBatchRollup }>( 'blog-batches', {
    method: 'POST', body: JSON.stringify( body ),
  } );

export const closeBlogBatch = ( batchId: string ) =>
  seoToolsJson<{ ok: boolean; batchId: string; status: string; alreadyClosed: boolean }>(
    'blog-batches/close', { method: 'POST', body: JSON.stringify( { batchId } ) } );

/** One batch's sources, scoped through the batch index rather than reading every source. */
export const listBlogSourcesInBatch = ( batchId: string ) =>
  seoToolsJson<BlogSourcesResponse>(
    `blog-sources?batchId=${encodeURIComponent( batchId )}` );

/* ── Source analysis ─────────────────────────────────────────────────────── */

export const analyseBlogSource = ( sourceId: string ) =>
  seoToolsJson<BlogAnalysisDetail & { ok: boolean }>( 'blog-analysis', {
    method: 'POST', body: JSON.stringify( { sourceId } ),
  } );

export const getBlogAnalysis = ( analysisId: string ) =>
  seoToolsJson<{ ok: boolean; analysis: BlogAnalysisDetail }>(
    `blog-analysis/${encodeURIComponent( analysisId )}` );

export const listBlogAnalyses = ( sourceId: string ) =>
  seoToolsJson<{ ok: boolean; history: BlogAnalysisView[] }>(
    `blog-analysis?sourceId=${encodeURIComponent( sourceId )}` );

export const getBlogBatchReviewState = ( batchId: string ) =>
  seoToolsJson<{ ok: boolean; reviewState: BlogBatchReviewState; pendingAnalysis: string[] }>(
    `blog-analysis?batchId=${encodeURIComponent( batchId )}` );

/**
 * Record that a human read the source, against a NAMED analysis version.
 *
 * The only route that can write `sourceReviewedFully`. The version is named explicitly rather
 * than defaulted, so a re-analysis produced while the reviewer was reading cannot become the
 * thing they signed for.
 */
export const recordBlogSourceReview = ( body: {
  analysisId: string;
  sourceReviewedFully: 'YES' | 'NO';
  centralDistinctionCandidate?: string;
  wrapperToRemove?: string;
  reviewNotes?: string;
  originalSourceDate?: string;
  originalSourceTitle?: string;
} ) => seoToolsJson<BlogDraftAcceptResponse & { ok: boolean; analysisId: string; note: string }>(
  'blog-analysis/review', { method: 'POST', body: JSON.stringify( body ) } );

/* ── Templates ───────────────────────────────────────────────────────────── */

export const listBlogTemplates = () =>
  seoToolsJson<{ ok: boolean; templates: BlogTemplateView[]; total: number; anyCategory: string; categories: string[] }>(
    'blog-templates' );

export const getBlogTemplate = ( reference: string ) =>
  seoToolsJson<{ ok: boolean; template: BlogTemplateView; locked: boolean }>(
    `blog-templates/${encodeURIComponent( reference )}` );

export const getBlogTemplateHistory = ( templateId: string ) =>
  seoToolsJson<{ ok: boolean; templateId: string; versions: BlogTemplateView[] }>(
    `blog-templates/${encodeURIComponent( templateId )}?history=1` );

/** Edits an unlocked version in place, or forks a version a published article used. */
export const saveBlogTemplate = ( body: Record<string, unknown> ) =>
  seoToolsJson<BlogTemplateSaveResponse>( 'blog-templates', {
    method: 'POST', body: JSON.stringify( body ),
  } );

export const assignBlogTemplate = ( sourceId: string, templateId: string, version = 0 ) =>
  seoToolsJson<{ ok: boolean; sourceId: string; templateId: string; templateVersion: number; templateName: string }>(
    'blog-templates/assign', {
      method: 'POST', body: JSON.stringify( { sourceId, templateId, version } ),
    } );

/* ── QA and sign-off ─────────────────────────────────────────────────────── */

export const getBlogQaState = ( sourceId: string ) =>
  seoToolsJson<BlogQaResponse>( `blog-qa?sourceId=${encodeURIComponent( sourceId )}` );

export const getBlogBatchQaState = ( batchId: string ) =>
  seoToolsJson<BlogQaResponse>( `blog-qa?batchId=${encodeURIComponent( batchId )}` );

export const getBlogCorpusState = () => seoToolsJson<BlogQaResponse>( 'blog-qa' );

export const runBlogQa = ( sourceId: string ) =>
  seoToolsJson<BlogQaRunView & { ok: boolean; report: BlogQaReport }>( 'blog-qa', {
    method: 'POST', body: JSON.stringify( { sourceId } ),
  } );

export const getBlogQaRun = ( qaRunId: string ) =>
  seoToolsJson<{ ok: boolean; run: BlogQaRunView & { report: BlogQaReport } }>(
    `blog-qa/${encodeURIComponent( qaRunId )}` );

/**
 * A human accepts a named QA run and answers the eleven judgements plus the declarations.
 *
 * Makes READY_TO_PUBLISH reachable and publishes nothing. Editing the body afterwards
 * invalidates the signature automatically — there is no revocation step to remember.
 */
export const signOffBlogGate = ( body: {
  qaRunId: string;
  gates: Record<string, string>;
  declarations: Record<string, string>;
  statement: string;
} ) => seoToolsJson<BlogSignoffView & { ok: boolean; readyToPublish: boolean; articleStatus: string; blocking: string[]; review: string[]; note: string }>(
  'blog-qa/sign-off', { method: 'POST', body: JSON.stringify( body ) } );

export const revokeBlogSignoff = ( signoffId: string, reason: string ) =>
  seoToolsJson<BlogSignoffView & { ok: boolean; alreadyRevoked: boolean }>(
    'blog-qa/revoke', { method: 'POST', body: JSON.stringify( { signoffId, reason } ) } );

/* ── Collection repetition ───────────────────────────────────────────────── */

export const getBlogRepetitionState = ( batchId: string ) =>
  seoToolsJson<{
    ok: boolean;
    state: { sources: number; byStatus: Record<string, number>; implicated: number; clear: number; unchecked: number; latestRun: BlogRepetitionRunView | Record<string, never>; runs: number };
    runs: BlogRepetitionRunView[];
    thresholds: Record<string, number>;
  }>( `blog-repetition?batchId=${encodeURIComponent( batchId )}` );

export const runBlogRepetition = ( batchId: string ) =>
  seoToolsJson<BlogRepetitionRunView & { ok: boolean; report: BlogRepetitionReport }>(
    'blog-repetition', { method: 'POST', body: JSON.stringify( { batchId } ) } );

export const getBlogRepetitionRun = ( repetitionRunId: string ) =>
  seoToolsJson<{ ok: boolean; run: BlogRepetitionRunView & { report: BlogRepetitionReport } }>(
    `blog-repetition/${encodeURIComponent( repetitionRunId )}` );

/* ── Publish queue ───────────────────────────────────────────────────────── */

export const getBlogPublishQueue = ( status = '' ) =>
  seoToolsJson<BlogPublishResponse>(
    `blog-publish${status ? `?status=${encodeURIComponent( status )}` : ''}` );

export const getBlogBatchPublishState = ( batchId: string ) =>
  seoToolsJson<BlogPublishResponse>(
    `blog-publish?batchId=${encodeURIComponent( batchId )}` );

export const getBlogPublishJob = ( jobId: string ) =>
  seoToolsJson<{ ok: boolean; job: BlogPublishJobView & { record: Record<string, unknown> } }>(
    `blog-publish/${encodeURIComponent( jobId )}` );

/** Records the decision. Performs NO Wix write — publishing is a separate call. */
export const releaseBlogArticle = ( sourceId: string ) =>
  seoToolsJson<BlogPublishJobView & { ok: boolean; created: boolean; note: string }>(
    'blog-publish/release', { method: 'POST', body: JSON.stringify( { sourceId } ) } );

export const withdrawBlogRelease = ( jobId: string, reason: string ) =>
  seoToolsJson<BlogPublishJobView & { ok: boolean; withdrawn: boolean }>(
    'blog-publish/withdraw', { method: 'POST', body: JSON.stringify( { jobId, reason } ) } );

/** The only Wix mutation in the system. `refused: true` means the kill switch stopped it. */
export const publishBlogArticle = ( jobId: string ) =>
  seoToolsJson<BlogPublishJobView & { ok: boolean; published: boolean; refused?: boolean; postId?: string; postUrl?: string; note: string }>(
    'blog-publish', { method: 'POST', body: JSON.stringify( { jobId } ) } );

/* ── Publish verification ────────────────────────────────────────────────── */

export const getBlogVerifyAssertions = () =>
  seoToolsJson<BlogVerifyResponse>( 'blog-verify' );

export const getBlogVerifyState = ( sourceId: string ) =>
  seoToolsJson<BlogVerifyResponse>( `blog-verify?sourceId=${encodeURIComponent( sourceId )}` );

export const getBlogBatchVerifyState = ( batchId: string ) =>
  seoToolsJson<BlogVerifyResponse>( `blog-verify?batchId=${encodeURIComponent( batchId )}` );

export const verifyBlogArticle = ( sourceId: string ) =>
  seoToolsJson<BlogVerifyRunView & { ok: boolean; report: BlogVerifyReport; note: string }>(
    'blog-verify', { method: 'POST', body: JSON.stringify( { sourceId } ) } );

export const getBlogVerifyRun = ( verificationRunId: string ) =>
  seoToolsJson<{ ok: boolean; run: BlogVerifyRunView & { report: BlogVerifyReport } }>(
    `blog-verify/${encodeURIComponent( verificationRunId )}` );
