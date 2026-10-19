import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

const ROOT = path.join( __dirname, '..', '..' );
const read = ( rel: string ): string => fs.readFileSync( path.join( ROOT, rel ), 'utf8' );

const ORDERS = read( 'src/components/workspace/commerce/Orders.tsx' );
const API = read( 'src/api/client.ts' );

describe( 'manual Order shipment tracking', () => {
  it( 'keeps carrier tracking explicitly manual rather than claiming a courier integration', () => {
    expect( ORDERS ).toContain( 'Manual record — not synced with a courier.' );
    expect( ORDERS ).toContain( 'Manual shipment tracking saved' );
    expect( ORDERS ).toContain( "order.trackingSource === 'manual'" );
    expect( API ).toContain( 'trackingSource?: string' );
    expect( API ).toContain( 'trackingUpdatedAt?: number' );
  } );

  it( 'uses the native-safe external browser only for a validated saved HTTPS URL', () => {
    expect( ORDERS ).toContain( "import { openExternal } from '../../../lib/capacitor'" );
    expect( ORDERS ).toContain( "parsed.protocol !== 'https:'" );
    expect( ORDERS ).toContain( 'openExternal( savedTrackingUrl )' );
    expect( ORDERS ).not.toMatch( /window\.open\([^)]*tracking/i );
  } );

  it( 'edits only the three operator-owned shipment fields', () => {
    expect( API ).toContain( "type ManualTrackingPatch" ).toBe(false);
    expect( API ).toContain( 'carrierName?: string' );
    expect( API ).toContain( 'trackingNumber?: string' );
    expect( API ).toContain( 'trackingUrl?: string' );
    const patchBlock = API.slice( API.indexOf( 'export interface OrderPatch' ), API.indexOf( 'export async function updateOrder' ) );
    expect( patchBlock ).toContain( 'carrierName?: string' );
    expect( patchBlock ).toContain( 'trackingNumber?: string' );
    expect( patchBlock ).toContain( 'trackingUrl?: string' );
    expect( patchBlock ).not.toContain( 'trackingSource?:' );
    expect( patchBlock ).not.toContain( 'trackingUpdatedAt?:' );
  } );
} );
