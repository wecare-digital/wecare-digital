// Regression tests for the RCS Send mock-data fix.
//
// Bug (now fixed): the RCS Send page used to default the template to `test16`
// and offer `test17` as a fallback when template loading failed. The fix
// filters test-template IDs out of the live options, requires the chosen
// template id to match a confirmed live option before sending, and shows
// "Template sending is disabled" when the templates API fails or returns none.
//
// RcsSend.tsx is a React component whose filter and send guard live inside the
// component body and cannot be cleanly exported without changing production
// behaviour. So these tests do two things that together fail if the fix is
// reverted:
//   1. Compile the component with the harness to prove it builds, and assert
//      the exact filter regex and send-guard source invariants are present.
//   2. Re-create the documented predicate/guard and unit-test that they reject
//      test16/test17 and reject ids not present in the live options.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { compileTsx, readSource } from './helpers/loadTsx.mjs';

const FILE = 'src/components/workspace/channels/RcsSend.tsx';

test( 'RcsSend.tsx compiles cleanly through the offline harness', () => {
  const code = compileTsx( readSource( FILE ) );
  assert.match( code, /RcsSendPage/ );
} );

test( 'source filters out the test-template IDs and keeps the send guard', () => {
  const source = readSource( FILE );
  // The live-template filter must exclude the known test templates.
  assert.match(
    source,
    /\/\^\(test16\|test17\|wecare_test_create\|wecare_v2_test\)\$\/i/,
    'the test-template exclusion regex must be present',
  );
  // Send is gated on a confirmed live match (used in handleSend and disabled).
  assert.match(
    source,
    /templateOptions\.some\(\s*option\s*=>\s*option\.value === templateId\s*\)/,
    'send must require the chosen id to match a live template option',
  );
  // The unavailable/disabled state must be shown when there is no live template.
  assert.match(
    source,
    /No verified RCS templates available\. Template sending is disabled\./,
  );
  // Guard-script invariant: no restored fallback option list.
  assert.ok( !source.includes( 'FALLBACK_TEMPLATE_OPTIONS' ), 'no fallback template option list' );
} );

test( 'there is no test16 default or test17 fallback anywhere in source', () => {
  const source = readSource( FILE );
  // test16/test17 may only ever appear inside the exclusion regex, never as a
  // default value or fallback option. Strip the regex literal, then assert the
  // identifiers are gone.
  const withoutFilter = source.replace( /\/\^\(test16\|test17\|wecare_test_create\|wecare_v2_test\)\$\/i/g, '' );
  assert.ok( !/\btest16\b/.test( withoutFilter ), 'test16 must not appear outside the exclusion filter' );
  assert.ok( !/\btest17\b/.test( withoutFilter ), 'test17 must not appear outside the exclusion filter' );
  assert.ok( !/setTemplateId\(\s*['"]test1[67]['"]\s*\)/.test( source ), 'no test template default' );
} );

// The documented predicate, re-created exactly as it appears in the component,
// so the behaviour it encodes is unit-tested directly. If the component's
// regex were loosened to re-admit test templates, the source-invariant test
// above fails; this proves the predicate itself does the right thing.
const TEST_TEMPLATE_RE = /^(test16|test17|wecare_test_create|wecare_v2_test)$/i;
function liveTemplateOptions( templates ) {
  return templates
    .filter( t => typeof t?.name === 'string' && t.name.trim() && !TEST_TEMPLATE_RE.test( t.name ) )
    .map( t => ( { value: t.name, label: t.name } ) );
}
function canSend( templateId, templateOptions ) {
  return Boolean( templateId ) && templateOptions.some( option => option.value === templateId );
}

test( 'the live-template filter rejects test IDs and accepts a real template', () => {
  const options = liveTemplateOptions( [
    { name: 'test16' },
    { name: 'TEST17' },
    { name: 'wecare_test_create' },
    { name: 'wecare_v2_test' },
    { name: 'order_confirmation' },
    { name: '  ' },
  ] );
  assert.deepEqual( options.map( o => o.value ), [ 'order_confirmation' ] );
} );

test( 'the send guard rejects ids not present in the live options', () => {
  const options = liveTemplateOptions( [ { name: 'order_confirmation' } ] );
  assert.equal( canSend( 'test16', options ), false, 'test16 must never be sendable' );
  assert.equal( canSend( '', options ), false, 'empty id is not sendable' );
  assert.equal( canSend( 'unknown_template', options ), false, 'unlisted id is not sendable' );
  assert.equal( canSend( 'order_confirmation', options ), true, 'confirmed live template is sendable' );
} );

test( 'when the templates API fails (no templates), no option is offered and nothing is sendable', () => {
  const options = liveTemplateOptions( [] );
  assert.equal( options.length, 0 );
  assert.equal( canSend( 'test16', options ), false );
  assert.equal( canSend( 'anything', options ), false );
} );
