import fs from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';

/**
 * WEBVIEW-SAFE EXTERNAL LINKS (Phase 3, native app shell).
 *
 * Inside the Capacitor native WebView there is no separate browser tab, so a bare
 * `window.open(url, '_blank')` to an EXTERNAL URL can silently do nothing — the link never
 * opens. The repo's `openExternal()` (src/lib/capacitor.ts) is the single fix: it routes
 * through `@capacitor/browser` (in-app browser) on native and falls back to `window.open`
 * on the web. This guard pins the critical money/document flows onto `openExternal` so a
 * future edit cannot quietly reintroduce a `_blank` that breaks the native app.
 *
 * SCOPE, deliberately narrow: only the flows that open a REMOTE url a user must reach.
 *   - the WhatsApp-account wallet top-up (the Razorpay/payment short link) — the money flow;
 *   - the Drop Docs document download (the S3 signed URL).
 * NOT in scope: `src/api/client.ts`'s `window.open('', '_blank')` for PRINT — that opens a
 * blank document the code then writes into (not an external URL), and browser printing is a
 * desktop/web affordance, not a native-app flow, so it is left as-is.
 */

const ROOT = path.join( __dirname, '..', '..' );
const read = ( rel: string ): string => fs.readFileSync( path.join( ROOT, rel ), 'utf8' );

const MY_ACCOUNT = 'src/components/workspace/whatsapp/my-account.tsx';
const DOCUMENTS = 'src/components/workspace/service/Documents.tsx';
const CAPACITOR = 'src/lib/capacitor.ts';

describe( 'WebView-safe external links', () => {
  it( 'openExternal routes through @capacitor/browser on native and falls back to window.open on web', () => {
    const cap = read( CAPACITOR );
    expect( cap ).toContain( 'export async function openExternal' );
    // native branch opens the in-app browser; web branch is the only window.open allowed here
    expect( cap ).toContain( 'Browser.open(' );
    expect( cap ).toMatch( /isNative\(\)[\s\S]*Browser\.open\(/ );
  } );

  it( 'the wallet top-up opens its payment link through openExternal, not a raw _blank', () => {
    const src = read( MY_ACCOUNT );
    expect( src ).toContain( "import { openExternal } from '../../../lib/capacitor'" );
    expect( src ).toContain( 'openExternal( data.shortUrl )' );
    // No bare window.open anywhere in this component (the payment flow must stay native-safe).
    expect( src ).not.toMatch( /window\.open\s*\(/ );
  } );

  it( 'the document download opens its URL through openExternal, not a raw _blank', () => {
    const src = read( DOCUMENTS );
    expect( src ).toContain( "import { openExternal } from '../../../lib/capacitor'" );
    expect( src ).toContain( 'openExternal( url )' );
    expect( src ).not.toMatch( /window\.open\s*\(/ );
  } );
} );
