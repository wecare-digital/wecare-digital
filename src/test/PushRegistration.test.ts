import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

/**
 * PUSH REGISTRATION WIRING (Phase 3, native app shell).
 *
 * The backend push handler (POST /push/register) and the client plugin wrapper
 * (initPushNotifications in src/lib/capacitor.ts) both existed, but nothing connected them:
 * initPushNotifications was dead code (never called) and no token was ever sent to the backend,
 * so push silently did nothing on the native app. This guard pins the full chain so it cannot
 * regress back to dead code:
 *   initCapacitor -> initPushNotifications -> onPushToken(_app.tsx) -> registerPushToken -> POST /push/register
 */

const ROOT = path.join( __dirname, '..', '..' );
const read = ( rel: string ): string => fs.readFileSync( path.join( ROOT, rel ), 'utf8' );

const CAPACITOR = read( 'src/lib/capacitor.ts' );
const APP = read( 'src/pages/_app.tsx' );
const PUSH_REG = read( 'src/lib/pushRegistration.ts' );

describe( 'push registration wiring', () => {
  it( 'initCapacitor actually calls initPushNotifications when a token sink is provided', () => {
    expect( CAPACITOR ).toContain( 'onPushToken' );
    // initPushNotifications must be invoked somewhere other than its own definition.
    const calls = CAPACITOR.match( /initPushNotifications\(/g ) || [];
    expect( calls.length ).toBeGreaterThanOrEqual( 2 ); // 1 definition + >=1 call
    // and it is gated on the token sink so a build without delivery does not prompt for permission
    expect( CAPACITOR ).toMatch( /if\s*\(\s*opts\.onPushToken\s*\)/ );
  } );

  it( '_app.tsx hands initCapacitor an onPushToken that forwards to registerPushToken', () => {
    expect( APP ).toContain( "import { registerPushToken } from '../lib/pushRegistration'" );
    expect( APP ).toContain( 'onPushToken:' );
    expect( APP ).toMatch( /registerPushToken\(\s*token\s*,\s*platform\s*\)/ );
  } );

  it( 'registerPushToken POSTs the token to the backend /push/register endpoint', () => {
    expect( PUSH_REG ).toContain( '/push/register' );
    expect( PUSH_REG ).toContain( "method: 'POST'" );
    expect( PUSH_REG ).toContain( 'deviceToken' );
    expect( PUSH_REG ).toContain( 'platform' );
    // best-effort: a launch-time failure must not throw out of the app bootstrap
    expect( PUSH_REG ).toMatch( /try\s*\{[\s\S]*catch/ );
  } );
} );
