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

  it( 'keeps consent controls out of the generic customer editor', () => {
    expect( customers ).not.toContain( 'setFormOptInWA' );
    expect( customers ).not.toContain( 'setFormAllowlistWA' );
    expect( customers ).not.toContain( 'onChange={e => item.set(e.target.checked)}' );
  } );

  it( 'ordinary customer create/update payloads do not rewrite evidence-backed consent', () => {
    const createStart = customers.indexOf( 'const handleCreate = async' );
    const updateStart = customers.indexOf( 'const handleUpdate = async' );
    const createBlock = customers.slice( createStart, updateStart );
    const updateBlock = customers.slice( updateStart, customers.indexOf( '// Archive is a distinct', updateStart ) );
    for ( const block of [ createBlock, updateBlock ] ) {
      expect( block ).not.toContain( 'optInWhatsApp:' );
      expect( block ).not.toContain( 'allowlistWhatsApp:' );
    }
  } );
} );
