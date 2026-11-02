// Regression tests for the WhatsApp template analytics mock-data fix.
//
// Bug (now fixed): the analytics panel used to invent delivery rates, read
// rates and sent counts (via Math.random) when its API failed. The fix makes
// loadAnalytics set analytics=null + analyticsError=true on failure, renders
// "Template analytics unavailable. No statistics are shown until real data is
// available." instead of fake numbers, and the summary cards only render when
// `analytics` is non-null. The api client contract is tightened too:
// getTemplateAnalyticsSummary throws 'Template analytics unavailable' when the
// underlying apiCall yields no data.
//
// These tests assert the UI source invariants and behaviourally exercise the
// real getTemplateAnalyticsSummary body (extracted and run with an injected
// apiCall stub) so reverting either half of the fix fails a test.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

import { compileTsx, readSource } from './helpers/loadTsx.mjs';

const TEMPLATES_FILE = 'src/components/workspace/whatsapp/templates.tsx';
const CLIENT_FILE = 'src/api/client.ts';

test( 'templates.tsx contains no Math.random fabricated metrics', () => {
  const source = readSource( TEMPLATES_FILE );
  assert.ok( !source.includes( 'Math.random' ), 'no fabricated delivery/read/sent values' );
} );

test( 'templates.tsx renders an unavailable/error state instead of fake numbers', () => {
  const source = readSource( TEMPLATES_FILE );
  assert.match(
    source,
    /Template analytics unavailable\. No statistics are shown until real data is available\./,
  );
  // On failure the handler must clear analytics and flag the error state.
  assert.match( source, /setAnalytics\(\s*null\s*\)/ );
  assert.match( source, /setAnalyticsError\(\s*true\s*\)/ );
} );

test( 'summary cards only render when analytics is non-null', () => {
  const source = readSource( TEMPLATES_FILE );
  // The summary cards live behind an `analytics ? ( ... ) : ( <unavailable/> )`
  // branch, so the fabricated-value cards cannot show without real data.
  assert.match( source, /analytics \? \(/, 'summary block is gated on a non-null analytics value' );
  // The analytics.tsx must still compile through the offline harness.
  const code = compileTsx( source );
  assert.match( code, /summary-value/ );
} );

// --- Behavioural: the api client contract ---------------------------------
//
// client.ts is a 3400-line module with many external imports (aws-amplify,
// config, lib helpers) that cannot be evaluated wholesale offline. Instead we
// extract the real getTemplateAnalyticsSummary function body from source and
// run it with an injected apiCall + API_BASE, exercising the exact shipped
// data/no-data branch.

function extractAnalyticsSummary() {
  const source = readSource( CLIENT_FILE );
  const start = source.indexOf( 'export async function getTemplateAnalyticsSummary' );
  assert.ok( start !== -1, 'getTemplateAnalyticsSummary must exist in client.ts' );

  // Walk braces from the function signature to capture the whole body.
  const braceStart = source.indexOf( '{', start );
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
  assert.ok( end !== -1, 'could not find the end of getTemplateAnalyticsSummary' );
  return source.slice( start, end ).replace( /^export\s+/, '' );
}

function loadAnalyticsSummary( apiCall ) {
  const fnSource = extractAnalyticsSummary();
  const wrapped = `${ fnSource }\nexport { getTemplateAnalyticsSummary };`;
  const code = compileTsx( wrapped );
  const compiledModule = { exports: {} };
  const sandbox = {
    module: compiledModule,
    exports: compiledModule.exports,
    API_BASE: 'https://api.invalid',
    apiCall,
    console,
  };
  vm.runInNewContext( code, sandbox );
  return compiledModule.exports.getTemplateAnalyticsSummary;
}

test( 'getTemplateAnalyticsSummary throws when apiCall returns no data', async () => {
  const fn = loadAnalyticsSummary( async () => null );
  await assert.rejects( fn(), /Template analytics unavailable/ );
} );

test( 'getTemplateAnalyticsSummary returns real values only when data is present', async () => {
  const fn = loadAnalyticsSummary( async () => ( {
    totalTemplatesSent: 42,
    avgDeliveryRate: 97.5,
    avgReadRate: 80.1,
    topTemplates: [ { templateName: 'order_confirmation' } ],
    byCategory: { UTILITY: 42 },
  } ) );
  const summary = await fn();
  assert.equal( summary.totalTemplatesSent, 42 );
  assert.equal( summary.avgDeliveryRate, 97.5 );
  assert.equal( summary.avgReadRate, 80.1 );
  assert.deepEqual( summary.byCategory, { UTILITY: 42 } );
} );

test( 'client.ts source throws the unavailable error on the no-data branch', () => {
  const source = readSource( CLIENT_FILE );
  assert.match( source, /throw new Error\(\s*'Template analytics unavailable'\s*\)/ );
} );
