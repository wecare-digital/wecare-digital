#!/usr/bin/env node
/**
 * Copy `@aws-amplify/ui-react`'s stylesheet into `public/vendor/` so it can be loaded by
 * a <link> on the authenticated routes INSTEAD of being bundled into the global CSS that
 * every public page downloads.
 *
 * WHY THIS EXISTS - the measurement, not a hunch
 * ---------------------------------------------
 * `_app.tsx` used to `import '@aws-amplify/ui-react/styles.css'`. In the pages router a
 * global CSS import is unconditional: it lands in the `data-n-g` bundle on EVERY route. The
 * built file is 310 kB minified, and it was the largest single asset on the home page -
 * larger than any JavaScript chunk.
 *
 * Chrome's CSS rule-usage tracker (CSS.startRuleUsageTracking, via
 * `tools/browser/lhcheck.js`'s sibling measurement) says that of that 310 kB, a public page
 * applies exactly SEVEN rules:
 *
 *   *{box-sizing:border-box}
 *   html,[data-amplify-theme]{font-family:var(--amplify-fonts-default-static)}
 *   html,[data-amplify-theme]{font-family:var(--amplify-fonts-default-variable)}   (@supports)
 *   :root,[data-amplify-theme]{--amplify-…}            the design-token block
 *   body{text-rendering:optimizespeed;min-height:100vh;line-height:…}
 *   input,button,textarea,select{font:inherit}
 *
 * Everything else styles Authenticator, Accordion, AIConversation, Autocomplete … components
 * that exist only behind the sign-in. `src/styles/amplify-base.css` now carries the handful
 * of base declarations that were doing real work, and the component stylesheet loads only
 * where the components do.
 *
 * WHY A COPY RATHER THAN A SECOND GLOBAL IMPORT
 * --------------------------------------------
 * Next refuses a global CSS import from anywhere but the custom App, so there is no
 * "import it in the auth component" option. A file under `public/` served through a <link>
 * is the export-mode equivalent, and `_app.tsx` emits that <link> only in the branch that
 * renders the Authenticator.
 *
 * ORDER IS PRESERVED, AND THAT IS WHY THE <link> GOES IN next/head.
 * The stylesheet used to be FIRST in the cascade, so `src/styles/*.css` overrode it - five
 * `.amplify-button--primary` rules in `inner-ux.css` depend on winning that tie. In the
 * exported head, `data-next-head` tags render BEFORE the `data-n-g` stylesheet links
 * (verified in `out/workspace/index.html`), so a next/head <link> keeps Amplify ahead of our
 * bundle exactly as the import did.
 *
 * NOT COMMITTED, BY DESIGN. The output is gitignored and regenerated on every build, so it
 * cannot drift from the installed version the way a checked-in vendor copy would. The URL is
 * stable rather than content-hashed because an Amplify deploy invalidates the distribution.
 */

import { createRequire } from 'node:module';
import { mkdirSync, copyFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require_ = createRequire( import.meta.url );
const root = dirname( dirname( fileURLToPath( import.meta.url ) ) );

/**
 * Resolved through `require.resolve` rather than by joining `node_modules/…`, so a hoisted,
 * nested or pnpm-linked install all work and a missing dependency fails HERE with the name
 * of the package instead of as an absent file later.
 */
const SOURCE = require_.resolve( '@aws-amplify/ui-react/styles.css' );
const DEST_DIR = join( root, 'public', 'vendor' );
const DEST = join( DEST_DIR, 'amplify-ui.css' );

mkdirSync( DEST_DIR, { recursive: true } );
copyFileSync( SOURCE, DEST );

const kb = Math.round( statSync( DEST ).size / 1024 );
console.log( `vendor-css: @aws-amplify/ui-react/styles.css (${kb} kB) -> public/vendor/amplify-ui.css` );
console.log( '  loaded by <link> on the authenticated routes only; public pages get src/styles/amplify-base.css' );
