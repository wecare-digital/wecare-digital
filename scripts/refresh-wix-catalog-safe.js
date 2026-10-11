/**
 * refresh-wix-catalog-safe - run fetch-wix-catalog.js on every build, but NEVER fail the build.
 *
 * WHY A WRAPPER RATHER THAN CALLING fetch-wix-catalog DIRECTLY FROM `build`.
 * The owner's instruction is "only live data for blog and product": the blog is already
 * re-fetched from Wix on every build (listPublicBlogPosts runs at build time), and this makes the
 * PRODUCT catalogue match by refreshing src/content/wix-catalog.json before `next build` reads it.
 *
 * But fetch-wix-catalog.js calls process.exit(1) on any failure - a Wix outage, a 503, a network
 * blip in CI. Wired straight into the `build` chain with `&&`, that turns a transient third-party
 * hiccup into a failed deploy. The committed snapshot is the whole point of the static-export
 * design: it guarantees the site always builds with the LAST GOOD catalogue even when Wix is
 * unreachable. So this wrapper runs the fetch as a child process and treats a failure as
 * non-fatal: it logs a warning and exits 0, leaving the committed snapshot in place. Fresh data
 * when Wix answers; last-good data when it does not; a deploy that never dies on Wix's behalf.
 *
 * The fetch itself is credential-free (anonymous Wix visitor token minted from the PUBLIC
 * WIX_CLIENT_ID in config), so this runs in CI with no secrets.
 *
 * ESM, like the sibling build scripts (fetch-wix-catalog.js, generate-sitemap.js), because the
 * app's package.json sets "type": "module".
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname( fileURLToPath( import.meta.url ) );
const script = path.join( HERE, 'fetch-wix-catalog.js' );

const result = spawnSync( process.execPath, [ script ], { stdio: 'inherit' } );

if ( result.error ) {
  console.warn(
    `refresh-wix-catalog-safe: could not launch the fetch (${result.error.message}). `
    + 'Keeping the committed catalogue snapshot and continuing the build.'
  );
  process.exit( 0 );
}

if ( result.status !== 0 ) {
  console.warn(
    `refresh-wix-catalog-safe: fetch exited ${result.status}. Wix was likely unreachable or `
    + 'slow. Keeping the committed catalogue snapshot (src/content/wix-catalog.json) and '
    + 'continuing the build - a transient Wix failure must not fail a deploy.'
  );
  process.exit( 0 );
}

console.log( 'refresh-wix-catalog-safe: catalogue refreshed from Wix.' );
