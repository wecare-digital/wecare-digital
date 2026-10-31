import assert from 'node:assert/strict';
import test from 'node:test';
import { authStateQuery } from '../src/lib/authStateQuery.ts';

test('tracking-only referral URLs initialize ordinary customer sign-in', () => {
  const query = authStateQuery( new URLSearchParams( '?utm_source=chatgpt.com&gclid=sample&fbclid=sample' ) );
  assert.equal( query.toString(), '' );
});

test('website return path is kept without marketing parameters', () => {
  const query = authStateQuery( new URLSearchParams( '?return=%2Forders%2F&utm_campaign=share' ) );
  assert.equal( query.toString(), 'return=%2Forders%2F' );
});

test('all OAuth PKCE fields survive while referral parameters are excluded', () => {
  const raw = new URLSearchParams( {
    client_id: 'client-1', redirect_uri: 'https://chatgpt.com/callback',
    response_type: 'code', scope: 'commerce:read', state: 'state-1',
    resource: 'https://mtx59syrt6.execute-api.us-east-1.amazonaws.com/mcp',
    code_challenge: 'a'.repeat( 43 ), code_challenge_method: 'S256',
    ui_locales: 'en', utm_source: 'chatgpt.com',
  } );
  const safe = authStateQuery( raw );
  assert.equal( safe.has( 'utm_source' ), false );
  assert.equal( safe.get( 'resource' ), raw.get( 'resource' ) );
  assert.equal( safe.get( 'code_challenge' ), raw.get( 'code_challenge' ) );
  assert.equal( safe.get( 'state' ), raw.get( 'state' ) );
  assert.equal( safe.get( 'ui_locales' ), raw.get( 'ui_locales' ) );
  assert.equal( safe.size, 9 );
});

test('duplicate auth parameters are not silently collapsed', () => {
  const query = authStateQuery( new URLSearchParams( 'return=%2Forders%2F&return=%2Fvault%2F&utm_source=chatgpt.com' ) );
  assert.deepEqual( query.getAll( 'return' ), [ '/orders/', '/vault/' ] );
});

test('unrelated sharing parameters cannot select OAuth mode', () => {
  assert.equal( authStateQuery( new URLSearchParams( 'utm_resource=other&ref=partner' ) ).toString(), '' );
});
