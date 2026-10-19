import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve( __dirname, '..' );
const customers = fs.readFileSync( path.join( ROOT, 'pages/workspace/customers/index.tsx' ), 'utf8' );

describe( 'Customers consent safety', () => {
  it( 'never infers consent or allowlisting from message-history fallback rows', () => {
    const fallback = customers.slice(
      customers.indexOf( '// API failed — try messages fallback' ),
      customers.indexOf( "toast.warning(`Contacts API error", customers.indexOf( '// API failed — try messages fallback' ) ),
    );
    expect( fallback ).toContain( 'optInWhatsApp: false' );
    expect( fallback ).toContain( 'allowlistWhatsApp: false' );
    expect( fallback ).not.toContain( 'optInWhatsApp: true' );
    expect( fallback ).not.toContain( 'allowlistWhatsApp: true' );
  } );

  it( 'renders consent and allowlist state read-only in the generic customer editor', () => {
    const start = customers.indexOf( 'Consent and channel allowlists are evidence-backed state.' );
    expect( start ).toBeGreaterThan( 0 );
    const block = customers.slice( start, start + 3500 );
    expect( block ).toContain( 'disabled readOnly aria-readonly="true"' );
    expect( block ).not.toContain( 'onChange={e => item.set(e.target.checked)}' );
    expect( block ).not.toContain( 'set: setFormOptInWA' );
    expect( block ).not.toContain( 'set: setFormAllowlistWA' );
  } );

  it( 'still preserves authoritative consent state on ordinary customer edits', () => {
    expect( customers ).toContain( 'setFormOptInWA(contact.optInWhatsApp || false)' );
    expect( customers ).toContain( 'setFormAllowlistWA(contact.allowlistWhatsApp || false)' );
    expect( customers ).toContain( 'optInWhatsApp: formOptInWA' );
    expect( customers ).toContain( 'allowlistWhatsApp: formAllowlistWA' );
  } );
} );
