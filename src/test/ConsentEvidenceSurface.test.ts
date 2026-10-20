import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve( __dirname, '..' );
const settings = fs.readFileSync( path.join( ROOT, 'pages/workspace/engage/settings/index.tsx' ), 'utf8' );
const consentPanel = fs.readFileSync( path.join( ROOT, 'components/workspace/customers/ConsentPanel.tsx' ), 'utf8' );
const client = fs.readFileSync( path.join( ROOT, 'api/client.ts' ), 'utf8' );

describe( 'Consent-as-evidence surface replaces the boolean percentage anti-pattern', () => {
  it( 'engage/settings no longer computes opt-in from ContactsTable booleans', () => {
    expect( settings ).not.toContain( 'optInWhatsApp || c.allowlistWhatsApp' );
    expect( settings ).not.toContain( '% opted in' );
    expect( settings ).not.toContain( 'c.pct' );
    // It points staff at the Customer-owned consent surface instead.
    expect( settings ).toContain( 'Consent is evidence, owned by the customer' );
    expect( settings ).toContain( '/workspace/customers' );
  } );

  it( 'the consent panel reads the evidence model, shows OPTED_OUT first-class and history', () => {
    expect( consentPanel ).toContain( 'api.getConsent' );
    expect( consentPanel ).toContain( 'api.appendConsent' );
    expect( consentPanel ).toContain( 'OPTED_OUT' );
    expect( consentPanel ).toContain( 'Opted out' );
    expect( consentPanel ).toContain( 'history' );
    // No casual boolean toggle: evidence is recorded, not flipped.
    expect( consentPanel ).not.toContain( 'type="checkbox"' );
  } );

  it( 'uses Toast/Confirm contexts, never a native dialog', () => {
    expect( consentPanel ).toContain( 'useToastContext' );
    expect( consentPanel ).toContain( 'useConfirm' );
    for ( const native of [ 'window.alert(', 'window.confirm(', 'window.prompt(' ] ) {
      expect( consentPanel ).not.toContain( native );
    }
  } );

  it( 'the client exposes typed evidence read/append/import with a first-class OPTED_OUT state', () => {
    expect( client ).toContain( 'export async function getConsent' );
    expect( client ).toContain( 'export async function appendConsent' );
    expect( client ).toContain( 'export async function importConsent' );
    expect( client ).toContain( "'OPTED_IN' | 'OPTED_OUT' | 'PENDING'" );
  } );
} );
