import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTsxModule } from './helpers/loadTsx.mjs';

const { exports: feed } = loadTsxModule( { file: 'src/lib/inbox-feed.ts' } );
let response;
const calls = [];
const { exports: messaging } = loadTsxModule( {
  file: 'src/api/domains/messaging.ts',
  globals: {
    URLSearchParams,
    require: name => name === '../core' ? {
      apiCallResult: async ( ...args ) => { calls.push( args ); return response; },
      normalizeTimestamp: input => input,
    } : { API_BASE: 'https://example.invalid' },
  },
} );
const stamp = i => new Date( 1000 * i ).toISOString();
const row = ( id, sec, channel ) => ( { id, messageId: id, channel, timestamp: stamp( sec ) } );

test( 'inbox client requests bounded contact history and preserves partial status and cursor', async () => {
  response = { ok: true, data: {
    inboxVersion: 1, messages: [ row( 'a', 100, 'sms' ) ],
    nextCursor: 'opaque cursor', unavailableChannels: [ 'rcs' ],
  } };
  const result = await messaging.listInboxMessagePage( { contactId: 'customer-a', cursor: 'previous cursor', limit: 2000 } );
  assert.ok( result.ok );
  assert.equal( result.data.messages[ 0 ].channel, 'SMS' );
  assert.equal( result.data.nextCursor, 'opaque cursor' );
  assert.equal( result.data.unavailableChannels.join(), 'rcs' );
  const url = new URL( calls.at( -1 )[ 0 ] );
  assert.equal( url.searchParams.get( 'contactId' ), 'customer-a' );
  assert.equal( url.searchParams.get( 'cursor' ), 'previous cursor' );
  assert.equal( url.searchParams.get( 'limit' ), '100' );
  assert.equal( calls.at( -1 )[ 4 ], false );
} );

test( 'legacy results remain visible but never claim older cursor support', async () => {
  response = { ok: true, data: { messages: [ row( 'a', 100, 'sms' ) ] } };
  const result = await messaging.listInboxMessagePage();
  assert.ok( result.ok );
  assert.ok( result.data.legacy );
  assert.equal( result.data.nextCursor, null );
  assert.equal( result.data.messages[ 0 ].id, 'a' );
} );

test( 'refresh keeps a failed channel visible, reconciles successful heads and deduplicates pages', () => {
  const history = [ row( 'b', 50, 'SMS' ), row( 'c', 60, 'RCS' ) ];
  const recent = [ row( 'a', 100, 'SMS' ), row( 'd', 80, 'SMS' ) ];
  const head = feed.refreshInboxHead( history, recent, [ 'rcs' ] );
  assert.equal( head.map( m => m.id ).join(), 'a,d,c' );
  assert.equal( feed.displacedInboxRows( history, recent ).map( m => m.id ).join(), 'b' );
  assert.equal( feed.mergeInboxMessages( [ row( 'a', 99, 'SMS' ), ...history ], head ).map( m => m.id ).join(), 'a,d,c,b' );
} );

test( 'high-volume head turnover in one channel flags a possibly stale cursor', () => {
  const previous = [ row( 's1', 80, 'SMS' ), row( 's2', 70, 'SMS' ), row( 'w1', 90, 'WHATSAPP' ) ];
  const newRecent = [ row( 'w1', 90, 'WHATSAPP' ), row( 's4', 120, 'SMS' ), row( 's3', 110, 'SMS' ) ];
  assert.equal( feed.inboxHeadMayHaveGap( previous, newRecent, true ), true );
  assert.equal( feed.inboxHeadMayHaveGap( previous, newRecent, false ), false );
  assert.equal( feed.inboxHeadMayHaveGap( previous, newRecent.slice( 1 ), false ), true );
  assert.equal( feed.inboxHeadMayHaveGap( previous, [ row( 's0', 50, 'SMS' ) ], true ), false );
  assert.equal( feed.inboxHeadMayHaveGap( previous, [ row( 's4', 120, 'SMS' ), previous[ 0 ] ], true ), false );
} );

test( 'new backend sample mode is distinct from old backend and never follows a stale cursor', async () => {
  response = { ok: true, data: {
    inboxVersion: 1, historyMode: 'sampled', messages: [ row( 'a', 100, 'sms' ) ],
    nextCursor: 'must-not-resume',
  } };
  const result = await messaging.listInboxMessagePage();
  assert.ok( result.ok );
  assert.equal( result.data.sampled, true );
  assert.equal( result.data.legacy, false );
  assert.equal( result.data.nextCursor, null );
  assert.equal( result.data.messages[ 0 ].id, 'a' );
} );

test( 'cross-channel rows displaced from a saved thread remain in loaded history', () => {
  const previous = [ row( 's3', 83, 'SMS' ), row( 'w2', 82, 'WHATSAPP' ), row( 'r1', 81, 'RCS' ) ];
  const fresh = [ row( 's5', 85, 'SMS' ), row( 's4', 84, 'SMS' ), previous[ 0 ] ];
  const archive = [ row( 's0', 80, 'SMS' ) ];
  const displaced = feed.displacedInboxRows( previous, fresh, false );
  assert.equal( displaced.map( m => m.id ).join(), 'w2,r1' );
  assert.equal( feed.mergeInboxMessages( archive, displaced, fresh ).map( m => m.id ).join(), 's5,s4,s3,w2,r1,s0' );
} );

test( 'a displaced row tied with the new head boundary survives if older pages remain', () => {
  const previous = [ row( 'same-and-visible', 100, 'SMS' ), row( 'same-but-displaced', 100, 'RCS' ) ];
  const fresh = [ row( 'new', 101, 'SMS' ), previous[ 0 ] ];
  assert.equal( feed.displacedInboxRows( previous, fresh, false, true ).map( m => m.id ).join(), 'same-but-displaced' );
  assert.equal( feed.displacedInboxRows( previous, fresh, false, false ).length, 0 );
} );
