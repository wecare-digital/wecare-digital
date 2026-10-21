import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const broadcast = fs.readFileSync(
  path.join( root, 'src/pages/workspace/engage/broadcast/index.tsx' ),
  'utf8',
);
const client = fs.readFileSync(
  path.join( root, 'src/api/client.ts' ),
  'utf8',
);
const contacts = fs.readFileSync(
  path.join( root, 'amplify/functions/core/contacts/handler.py' ),
  'utf8',
);

describe( 'Broadcast WhatsApp consent authority', () => {
  it( 'projects MARKETING consent from the append-only ledger on the server', () => {
    const start = contacts.indexOf( 'def _from_dynamo' );
    const projection = contacts.slice( start, start + 1200 );
    expect( projection ).toContain( "result['whatsappMarketingConsent']" );
    expect( projection ).toContain( "purpose=consent_evidence.MARKETING" );
    expect( projection ).not.toContain( "result['whatsappMarketingConsent'] = bool" );
  } );

  it( 'carries the canonical state through the closed Contact normalizer', () => {
    const normalize = client.slice(
      client.indexOf( 'function normalizeContact' ),
      client.indexOf( 'function normalizeCheckoutAddress' ),
    );
    expect( normalize ).toContain( 'whatsappMarketingConsent:' );
    expect( normalize ).toContain( "'OPTED_IN'" );
    expect( normalize ).toContain( "'OPTED_OUT'" );
    expect( normalize ).toContain( "'PENDING'" );
  } );

  it( 'requires ledger OPTED_IN only for MARKETING WhatsApp templates', () => {
    const eligibility = broadcast.slice(
      broadcast.indexOf( 'const eligible =' ),
      broadcast.indexOf( 'const BroadcastPage' ),
    );
    expect( eligibility ).toContain( "whatsappCategory !== 'MARKETING'" );
    expect( eligibility ).toContain( "c.whatsappMarketingConsent === 'OPTED_IN'" );
    expect( eligibility ).not.toContain( "c.optInWhatsApp || c.allowlistWhatsApp" );
  } );

  it( 'uses the selected Meta template category and clears stale selections on template changes', () => {
    expect( broadcast ).toContain( 'selectedTemplate?.category' );
    expect( broadcast ).toContain( '[ channel, templateName ]' );
    expect( broadcast ).toContain( 'No eligible contacts with current WhatsApp marketing opt-in' );
  } );
} );
