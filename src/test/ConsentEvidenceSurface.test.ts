import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve( __dirname, '..' );
const workspace = fs.readFileSync( path.join( ROOT, 'pages/workspace/index.tsx' ), 'utf8' );
const consentPanel = fs.readFileSync( path.join( ROOT, 'components/workspace/customers/ConsentPanel.tsx' ), 'utf8' );
const client = fs.readFileSync( path.join( ROOT, 'api/client.ts' ), 'utf8' );

describe( 'Consent-as-evidence surface replaces the boolean percentage anti-pattern', () => {
  it( 'the workspace routes consent ownership to the canonical Customers surface', () => {
    expect( workspace ).not.toContain( 'optInWhatsApp || c.allowlistWhatsApp' );
    expect( workspace ).not.toContain( '% opted in' );
    expect( workspace ).toContain( "detail: 'Identity, address, consent and customer history'" );
    expect( workspace ).toContain( "href: '/workspace/customers'" );
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
