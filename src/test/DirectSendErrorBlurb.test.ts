import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * THE DASHBOARD MUST NAME THE ERROR AN OPERATOR WILL ACTUALLY SEE.
 *
 * The Direct Send tab told operators that a WABA which is not onboarded returns
 * `139200 / 131064`. It does not. Meta's documented not-onboarded error is a
 * synchronous **code 100**, whose `error_data.details` explains that the category
 * requires Direct Send and to use an approved template instead.
 *
 * 139200 and 131064 are the opposite situation: access was granted, and Meta's
 * category-misclassification enforcement has restricted or capped it. Different
 * condition, different remedy - one is "ask Meta for eligibility", the other is
 * "your copy is being classified as marketing".
 *
 * Why this is worth a test rather than just a fix. The blurb is the only place an
 * operator is told what the failure means, and the two conditions send them to
 * different places. The backend now reports them as two separate booleans
 * (`betaGated` and `restricted`), so a blurb that conflates them would quietly
 * contradict the response it is explaining.
 *
 * READ AS TEXT rather than rendered, matching the neighbouring contract tests:
 * importing the page would execute Amplify configuration at module scope, and the
 * thing under test is a literal in the source.
 */

const ROOT = path.resolve( __dirname, '..', '..' );
const TAB = path.join( ROOT, 'src', 'pages', 'workspace', 'dashboard', 'wa-graph-tools.tsx' );
const CLIENT = path.join( ROOT, 'src', 'api', 'client.ts' );

const tab = fs.readFileSync( TAB, 'utf8' );
const client = fs.readFileSync( CLIENT, 'utf8' );

/** The paragraph that explains the Direct Send gate to the operator. */
const blurb = ( () => {
  const match = tab.match( /Send a utility\/authentication message[\s\S]*?<\/p>/ );
  expect( match, 'the Direct Send blurb was not found' ).toBeTruthy();
  return match![ 0 ];
} )();

describe( 'Direct Send blurb names the real not-onboarded error', () => {
  it( 'names Graph code 100', () => {
    // Strict: the words must appear together, so a stray "100" elsewhere in the
    // paragraph (a character limit, say) cannot satisfy this.
    expect( blurb ).toMatch( /code<\/b>\s*100|code\s*<b>100<\/b>|<b>code 100<\/b>|code 100/ );
  } );

  it( 'points at error_data.details, which is what distinguishes a 100', () => {
    expect( blurb ).toContain( 'error_data.details' );
  } );

  it( 'does not present 139200 / 131064 as the onboarding gate', () => {
    // They may be mentioned - they SHOULD be - but as restriction/capping.
    if ( blurb.includes( '139200' ) )
    {
      expect( blurb.toLowerCase() ).toMatch( /restricted|capped/ );
    }
  } );

  it( 'still tells the operator onboarding is a Meta-side action', () => {
    expect( blurb ).toMatch( /WhatsApp Manager|Meta/ );
  } );
} );

describe( 'the two conditions stay separate end to end', () => {
  it( 'DirectSendResult carries both betaGated and restricted', () => {
    const iface = client.match( /export interface DirectSendResult \{[^}]*\}/ );
    expect( iface, 'DirectSendResult not found' ).toBeTruthy();
    expect( iface![ 0 ] ).toContain( 'betaGated' );
    expect( iface![ 0 ] ).toContain( 'restricted' );
  } );

  it( 'directSend passes restricted through from the backend', () => {
    expect( client ).toMatch( /restricted: data\.restricted/ );
  } );

  it( 'the tab distinguishes the two in its toast', () => {
    expect( tab ).toMatch( /r\.betaGated/ );
    expect( tab ).toMatch( /r\.restricted/ );
  } );
} );

describe( 'the undocumented sample-upload path is gone from the UI', () => {
  it( 'has no sample upload control', () => {
    expect( tab ).not.toMatch( /uploadSample|sampleText|sampleBusy/ );
  } );

  it( 'has no API client wrapper for it', () => {
    // The only surviving mention is the comment recording the removal.
    const live = client
      .split( '\n' )
      .filter( ( line ) => !line.trim().startsWith( '//' ) )
      .join( '\n' );
    expect( live ).not.toContain( 'directSendUploadSample' );
  } );
} );

describe( 'the TTL hint matches the per-category bounds the backend enforces', () => {
  it( 'no longer advertises one 30-43200 range for every category', () => {
    const label = tab.match( /TTL seconds \(optional[^<]*/ );
    expect( label, 'the TTL label was not found' ).toBeTruthy();
    // authentication caps at 900, utility reaches 30 days - one range cannot be right.
    expect( label![ 0 ] ).toContain( '900' );
    expect( label![ 0 ] ).toContain( '2592000' );
  } );
} );
