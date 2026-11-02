// Behavioural regression tests for the api-client failure-classification core.
//
// src/api/core.ts is the shared engine extracted from the api-client module and
// still carries heavy top-level imports (aws-amplify, config, lib helpers) that
// cannot be evaluated wholesale offline. Following the established
// extract-and-run-in-vm idiom (see
// tests/whatsapp-analytics.test.mjs) we slice the REAL apiCallResult function
// body — together with its supporting recordFailure/delay/getAuthToken and the
// RETRYABLE_KINDS plumbing — out of the source text, compile it with esbuild
// and run it in a node:vm with an injected `fetch`, a fast RETRY_CONFIG
// (baseDelayMs 0 so retries add no real delay) and a stubbed auth-session seam.
//
// The classification branches (status -> ApiFailureKind, retry counting,
// structured-refusal surfacing) are the shipped ones: reverting any of them in
// client.ts breaks an assertion here.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

import { compileTsx, readSource } from './helpers/loadTsx.mjs';

// FEAT-002: the shared failure-classification core (RETRYABLE_KINDS .. apiCallResult)
// was relocated verbatim from src/api/client.ts into src/api/core.ts during the
// domain-module decomposition. The extracted span and every assertion below are
// unchanged; only the source file this test slices from moved.
const CLIENT_FILE = 'src/api/core.ts';

// Extract the real module slice from `const RETRYABLE_KINDS` through the end of
// `apiCallResult`. That span carries recordFailure, delay, getAuthToken,
// authFetch, verifyAdminAccess, apiCall and apiCallResult. We re-export only
// apiCallResult + getLastApiFailure and inject the external seams as free
// globals (RETRY_CONFIG, API_BASE, fetch, fetchAuthSession).
function extractCoreSlice() {
  const source = readSource( CLIENT_FILE );
  const start = source.indexOf( 'const RETRYABLE_KINDS' );
  assert.ok( start !== -1, 'RETRYABLE_KINDS must exist in client.ts' );

  const fnMarker = 'export async function apiCallResult';
  const fnStart = source.indexOf( fnMarker );
  assert.ok( fnStart !== -1, 'apiCallResult must exist in client.ts' );

  // Brace-walk from the apiCallResult signature to capture its whole body.
  const braceStart = source.indexOf( '{', fnStart );
  let depth = 0;
  let end = -1;
  for ( let i = braceStart; i < source.length; i++ ) {
    const ch = source[ i ];
    if ( ch === '{' ) depth++;
    else if ( ch === '}' ) {
      depth--;
      if ( depth === 0 ) { end = i + 1; break; }
    }
  }
  assert.ok( end !== -1, 'could not find the end of apiCallResult' );
  // Strip the `export` keyword from declarations in the slice so our single
  // appended re-export is the only export (esbuild rejects duplicates).
  return source.slice( start, end ).replace( /^export\s+/gm, '' );
}

function loadApiCallResult( { fetch, fetchAuthSession, retryConfig, apiBase = 'https://api.invalid' } = {} ) {
  const slice = extractCoreSlice();
  const wrapped = `${ slice }\nexport { apiCallResult, getLastApiFailure, authFetch };`;
  const code = compileTsx( wrapped );
  const compiledModule = { exports: {} };
  const sandbox = {
    module: compiledModule,
    exports: compiledModule.exports,
    API_BASE: apiBase,
    RETRY_CONFIG: retryConfig ?? { maxRetries: 1, baseDelayMs: 0, maxDelayMs: 0 },
    fetch,
    fetchAuthSession: fetchAuthSession ?? ( async () => ( { tokens: null } ) ),
    AbortController,
    URL,
    // The shipped code arms an 8s AbortController timer per attempt and only
    // clears it on the success/refusal path, not when fetch throws. Dropping
    // the long-lived 8s timer keeps the suite fast and leaves no open handle;
    // short `delay()` backoff timers (baseDelayMs 0) still schedule normally.
    setTimeout: ( fn, ms ) => ( ms >= 8000 ? 0 : setTimeout( fn, ms ) ),
    clearTimeout,
    Date,
    console: { debug() {}, error() {}, warn() {}, log() {} },
  };
  vm.runInNewContext( code, sandbox );
  return compiledModule.exports;
}

// Build a fake Response the shipped code understands: .ok, .status,
// .statusText, .json() and .clone().json().
function makeResponse( status, body, { statusText = '' } = {} ) {
  const payload = body;
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText,
    async json() {
      if ( payload === undefined ) throw new Error( 'no body' );
      return payload;
    },
    clone() {
      return {
        async json() {
          if ( payload === undefined ) throw new Error( 'no body' );
          return payload;
        },
      };
    },
  };
}

// A fetch stub that returns a queued sequence of responses (or throws queued
// errors), recording how many times it was called.
function sequencedFetch( steps ) {
  let i = 0;
  const calls = { count: 0 };
  const fn = async () => {
    calls.count++;
    const step = steps[ Math.min( i, steps.length - 1 ) ];
    i++;
    if ( step instanceof Error ) throw step;
    return step;
  };
  fn.calls = calls;
  return fn;
}

test( 'a 200 response returns { ok: true, data }', async () => {
  const fetch = sequencedFetch( [ makeResponse( 200, { hello: 'world' } ) ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/thing' );
  assert.equal( result.ok, true );
  assert.deepEqual( result.data, { hello: 'world' } );
  assert.equal( fetch.calls.count, 1 );
} );

test( '401 retries once with a refreshed token then classifies unauthenticated (non-retryable)', async () => {
  const fetch = sequencedFetch( [
    makeResponse( 401, { message: 'nope' } ),
    makeResponse( 401, { message: 'nope' } ),
  ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/secure' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'unauthenticated' );
  assert.equal( result.failure.status, 401 );
  assert.equal( result.failure.retryable, false );
  // One original attempt + one token-refresh retry.
  assert.equal( fetch.calls.count, 2 );
} );

test( '403 classifies forbidden (non-retryable)', async () => {
  const fetch = sequencedFetch( [ makeResponse( 403, { message: 'denied' } ) ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/admin' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'forbidden' );
  assert.equal( result.failure.retryable, false );
  assert.equal( fetch.calls.count, 1 );
} );

test( '404 classifies not-found (non-retryable)', async () => {
  const fetch = sequencedFetch( [ makeResponse( 404, { message: 'gone' } ) ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/missing' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'not-found' );
  assert.equal( result.failure.retryable, false );
} );

test( '500 classifies server and is retryable', async () => {
  const fetch = sequencedFetch( [ makeResponse( 500, { message: 'boom' } ) ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/crash' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'server' );
  assert.equal( result.failure.retryable, true );
  // 500 does not have its own retry loop, so it is attempted once.
  assert.equal( fetch.calls.count, 1 );
} );

test( '503 retries then classifies unavailable (retryable)', async () => {
  const fetch = sequencedFetch( [
    makeResponse( 503, { message: 'down' } ),
    makeResponse( 503, { message: 'down' } ),
  ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/gw' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'unavailable' );
  assert.equal( result.failure.retryable, true );
  // original + one backoff retry (maxRetries = 1).
  assert.equal( fetch.calls.count, 2 );
} );

test( '504 retries then classifies timeout (retryable)', async () => {
  const fetch = sequencedFetch( [
    makeResponse( 504, { message: 'slow' } ),
    makeResponse( 504, { message: 'slow' } ),
  ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/slow' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'timeout' );
  assert.equal( result.failure.retryable, true );
  assert.equal( fetch.calls.count, 2 );
} );

test( '429 retries then classifies rate-limited (retryable)', async () => {
  const fetch = sequencedFetch( [
    makeResponse( 429, { message: 'slow down' } ),
    makeResponse( 429, { message: 'slow down' } ),
  ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/throttled' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'rate-limited' );
  assert.equal( result.failure.retryable, true );
  assert.equal( fetch.calls.count, 2 );
} );

test( 'an AbortError is retried then classified as timeout', async () => {
  const abort = new Error( 'aborted' );
  abort.name = 'AbortError';
  const fetch = sequencedFetch( [ abort, abort ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/hang' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'timeout' );
  assert.equal( result.failure.status, null );
  assert.equal( fetch.calls.count, 2 );
} );

test( 'a TypeError is retried then classified as network', async () => {
  const typeErr = new TypeError( 'Failed to fetch' );
  const fetch = sequencedFetch( [ typeErr, typeErr ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/offline' );
  assert.equal( result.ok, false );
  assert.equal( result.failure.kind, 'network' );
  assert.equal( result.failure.status, null );
  assert.equal( result.failure.retryable, true );
  assert.equal( fetch.calls.count, 2 );
} );

test( 'a structured JSON refusal surfaces code + details and a human message', async () => {
  const body = {
    errorCode: 'ACCESS_WINDOW_CLOSED',
    message: 'The access window is closed',
    existingContactId: 'contact-123',
  };
  const fetch = sequencedFetch( [ makeResponse( 409, body, { statusText: 'Conflict' } ) ] );
  const { apiCallResult } = loadApiCallResult( { fetch } );
  const result = await apiCallResult( 'https://api.invalid/contacts' );
  assert.equal( result.ok, false );
  // 409 is not a specially-handled status, so it falls through to the
  // generic branch which prefers the server's safe message text.
  assert.equal( result.failure.kind, 'http' );
  assert.equal( result.failure.status, 409 );
  assert.equal( result.failure.code, 'ACCESS_WINDOW_CLOSED' );
  assert.match( result.failure.message, /The access window is closed/ );
  assert.deepEqual( result.failure.details, body );
} );

test( 'a refusal message never leaks the Bearer token', async () => {
  const secret = 'eyJ-super-secret-access-token';
  // The fetch stub inspects the outgoing Authorization header to prove a token
  // was attached, then refuses. The failure message must not echo it back.
  const fetch = async ( _url, init ) => {
    assert.match( init.headers.Authorization, /^Bearer / );
    return makeResponse( 403, { message: 'Access denied' } );
  };
  const fetchAuthSession = async () => ( {
    tokens: { accessToken: { toString: () => secret } },
  } );
  const { apiCallResult } = loadApiCallResult( { fetch, fetchAuthSession } );
  const result = await apiCallResult( 'https://api.invalid/admin' );
  assert.equal( result.ok, false );
  assert.ok( !result.failure.message.includes( secret ), 'token must never appear in the message' );
} );

test( 'authenticated requests reject foreign destinations before reading credentials or fetching', async () => {
  let authReads = 0;
  let requests = 0;
  const { apiCallResult, authFetch } = loadApiCallResult( {
    apiBase: 'https://api.invalid/api',
    fetch: async () => { requests++; return makeResponse( 200, {} ); },
    fetchAuthSession: async () => { authReads++; return { tokens: null }; },
  } );
  for ( const url of [
    'https://evil.invalid/api/contacts',
    'https://api.invalid.evil.invalid/api/contacts',
    '//evil.invalid/api/contacts',
    'https://api.invalid@evil.invalid/api/contacts',
    'https://user:password@api.invalid/api/contacts',
    'http://api.invalid/api/contacts',
    'https://api.invalid/api-other/contacts',
    '/api/../outside',
    'file:///api/contacts',
  ] ) {
    await assert.rejects( authFetch( url ), /outside the configured API/ );
    const result = await apiCallResult( url );
    assert.equal( result.ok, false );
    assert.equal( result.failure.retryable, false );
    assert.equal( result.failure.url, 'https://api.invalid/api' );
  }
  assert.equal( authReads, 0 );
  assert.equal( requests, 0 );
} );

test( 'trusted absolute and root-relative API destinations preserve query, body and staff auth', async () => {
  const calls = [];
  const { apiCallResult, authFetch } = loadApiCallResult( {
    apiBase: 'https://api.invalid/api',
    fetch: async ( url, init ) => { calls.push( { url, init } ); return makeResponse( 200, { ok: true } ); },
    fetchAuthSession: async () => ( { tokens: { accessToken: { toString: () => 'test-token' } } } ),
  } );
  await authFetch( '/api/workspace/mcp?scope=read#fragment', { method: 'POST', body: '{}' } );
  const result = await apiCallResult( 'https://api.invalid/api/contacts?next=https%3A%2F%2Fexample.org' );
  assert.equal( result.ok, true );
  assert.equal( calls[ 0 ].url, 'https://api.invalid/api/workspace/mcp?scope=read' );
  assert.equal( calls[ 0 ].init.body, '{}' );
  assert.equal( calls[ 0 ].init.headers.Authorization, 'Bearer test-token' );
  assert.equal( calls[ 1 ].url, 'https://api.invalid/api/contacts?next=https%3A%2F%2Fexample.org' );
} );
