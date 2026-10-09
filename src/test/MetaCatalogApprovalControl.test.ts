import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

const root = path.resolve( process.cwd() );
const page = fs.readFileSync( path.join( root, 'src/pages/workspace/commerce/catalog.tsx' ), 'utf8' );
const client = fs.readFileSync( path.join( root, 'src/api/client.ts' ), 'utf8' );

describe( 'Meta catalog owner approval workspace controls', () => {
  it( 'uses the authenticated wa-business control route rather than a direct Meta or Lambda call', () => {
    expect( client ).toContain( '${API_BASE}/wa-business/catalog-sync' );
    expect( client ).not.toContain( 'graph.facebook.com' );
    expect( client ).not.toContain( 'META_CATALOG_SYNC_APPROVED_PLAN_SHA256' );
  } );

  it( 'shows exact plan approval and keeps Apply locked while release gates are closed', () => {
    expect( page ).toContain( 'WhatsApp Catalog Approval' );
    expect( page ).toContain( 'Exact plan hash' );
    expect( page ).toContain( "metaCatalog.approval?.status !== 'APPROVED'" );
    expect( page ).toContain( '!metaCatalog.enabled || metaCatalog.dryRun !== false' );
    expect( page ).toContain( 'Apply is intentionally locked' );
  } );

  it( 'does not let the browser supply an approver identity', () => {
    const controlFn = client.slice( client.indexOf( 'export async function controlMetaCatalogSync' ),
      client.indexOf( '// ============================================================================\n// WABA MANAGEMENT API' ) );
    expect( controlFn ).not.toContain( 'approvedBy' );
    expect( controlFn ).not.toContain( 'proposedBy' );
  } );
} );
