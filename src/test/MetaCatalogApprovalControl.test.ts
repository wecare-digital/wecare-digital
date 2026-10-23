import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

const root = path.resolve( process.cwd() );
// Catalog folded into the Commerce hub as an embedded tab; its body moved to
// src/components/workspace/commerce/Catalog.tsx in the workspace redesign.
const page = fs.readFileSync( path.join( root, 'src/components/workspace/commerce/Catalog.tsx' ), 'utf8' );
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

  it( 'adds an authenticated bulk release action that stops before provider apply', () => {
    expect( page ).toContain( 'Bulk catalog release' );
    expect( page ).toContain( 'Migrate catalog + prepare Meta plan' );
    expect( page ).toContain( "LEGACY_CATALOG_IMAGE_PREFIX = 'secure/public/catalog-deploy/catalog/products/'" );
    expect( page ).toContain( "CANONICAL_CATALOG_IMAGE_PREFIX = 'secure/d/public/catalog-deploy/catalog/products/'" );
    expect( page ).toContain( 'patchNativeProductWithRetry' );
    expect( page ).toContain( 'Legacy keys remaining: 0' );
    expect( page ).toContain( 'Provider writes: none' );
    expect( page ).toContain( 'getMetaCatalogSyncPlan' );
    expect( page ).not.toContain( "runBulkCatalogMigration('apply')" );
  } );

  it( 'promotes only the three explicitly approved catalog drafts for the 28-item release', () => {
    expect( page ).toContain( "native:elsewhere-activities" );
    expect( page ).toContain( "native:ritual-guru-ritva" );
    expect( page ).toContain( "native:vayulok" );
    expect( page ).toContain( 'Promote Activities + Ritva + VayuLok → 28-item plan' );
    expect( page ).toContain( "status: 'active'" );
    expect( page ).toContain( 'websiteEnabled: true' );
    expect( page ).toContain( 'metaEnabled: true' );
    expect( page ).toContain( 'Expected 28 desired Meta items after promotion' );
    expect( page ).toContain( 'VayuLok Standard price to ₹99.00' );
    expect( page ).toContain( 'priceMinor: 9900' );
    expect( page ).toContain( 'VayuLok must read back at ₹99.00 before Meta planning.' );
    expect( page ).toContain( 'previous 25-item approval is stale' );
  } );

  it( 'does not let the browser supply an approver identity', () => {
    const controlFn = client.slice( client.indexOf( 'export async function controlMetaCatalogSync' ),
      client.indexOf( '// ============================================================================\n// WABA MANAGEMENT API' ) );
    expect( controlFn ).not.toContain( 'approvedBy' );
    expect( controlFn ).not.toContain( 'proposedBy' );
  } );
} );
