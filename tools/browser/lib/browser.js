'use strict';

/**
 * Chromium resolution for the browser harness.
 *
 * NEVER HARDCODE THE REVISION. This sandbox ships Chromium under
 * /opt/playwright/chromium-<rev>/, not the ~/.cache/ms-playwright path Playwright
 * looks in by default, AND THE REVISION CHANGES ACROSS SANDBOX RESETS. Harnesses
 * pinned to `chromium-1243` all died with "executable doesn't exist" on a box that
 * had `chromium-1232` sitting right there. That failure reads like a broken harness
 * rather than a relocated browser, and it cost a full debugging round - which is the
 * entire reason this file exists instead of a string literal at each call site.
 *
 * We depend on playwright-core, not playwright, on purpose: playwright-core never
 * tries to download a browser. It drives whatever binary it is handed via
 * executablePath, which is exactly the arrangement we want when the binary is
 * already on disk and its revision is not ours to choose.
 *
 * THIS FILE USED TO BE LINUX-ONLY, AND THAT COST A DEBUGGING ROUND OF ITS OWN -
 * the same kind the revision scan above exists to prevent, one platform out. It
 * searched /opt/playwright, ~/.cache/ms-playwright and four /usr/bin paths, so on
 * macOS every harness in this directory threw "No Chromium executable found" on a
 * machine with Google Chrome sitting in /Applications. Nothing was broken: the
 * cache is ~/Library/Caches/ms-playwright on macOS, not ~/.cache, and a Mac browser
 * is an .app bundle rather than a file on PATH. Neither is an unusual setup, which
 * is precisely why hardcoding one platform's shape reads as a harness bug.
 *
 * Resolution order, first hit wins:
 *   1. CHROME env var             - explicit override, always respected
 *   2. PLAYWRIGHT_BROWSERS_PATH   - respected when Playwright's own cache is moved
 *   3. /opt/playwright            - the Linux sandbox, highest chromium-* revision
 *   4. Playwright's per-OS cache  - ~/.cache (Linux) or ~/Library/Caches (macOS)
 *   5. system chrome/chromium     - a developer laptop, Linux paths or .app bundles
 *
 * On total failure it THROWS naming every path it searched. It must never return
 * undefined: launch() would then report a misleading "executable doesn't exist" for
 * a path nobody chose, which is the confusing failure this module is built to avoid.
 */

const fs = require( 'fs' );
const os = require( 'os' );
const path = require( 'path' );

/**
 * Where a chromium-<rev> directory keeps its binary. Taken from playwright-core's own
 * EXECUTABLE_PATHS table (lib/coreBundle.js, v1.63) rather than from memory, because the
 * names have churned: the mac directories are chrome-mac-x64 / chrome-mac-arm64 and NOT
 * the chrome-mac that older guides and older Playwright releases describe.
 *
 * Every platform's paths are listed unconditionally and simply miss on the wrong OS. That
 * is deliberate - a process.platform switch here would be one more thing to get wrong on
 * the next host, and a miss costs one statSync.
 *
 * ORDER IS SIGNIFICANT. Full-chrome layouts come first and headless-shell layouts last,
 * for the reason the original file gave: a headless shell cannot report layout for
 * anything that needs a real compositor, so it is a fallback rather than an equal.
 */
const BINARY_SUBPATHS = [
  // Linux, current then legacy.
  path.join( 'chrome-linux64', 'chrome' ),
  path.join( 'chrome-linux-arm64', 'chrome' ),
  path.join( 'chrome-linux', 'chrome' ),
  // macOS. The bundle is "Google Chrome for Testing", which is what Playwright ships;
  // a Chromium.app name covers older cached revisions.
  path.join( 'chrome-mac-arm64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing' ),
  path.join( 'chrome-mac-x64', 'Google Chrome for Testing.app', 'Contents', 'MacOS', 'Google Chrome for Testing' ),
  path.join( 'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium' ),
  // Headless shells, current naming then legacy.
  path.join( 'chrome-headless-shell-linux64', 'chrome-headless-shell' ),
  path.join( 'chrome-headless-shell-linux-arm64', 'chrome-headless-shell' ),
  path.join( 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell' ),
  path.join( 'chrome-headless-shell-mac-x64', 'chrome-headless-shell' ),
  path.join( 'chrome-linux64', 'headless_shell' ),
  path.join( 'chrome-linux', 'headless_shell' ),
];

/**
 * A browser already installed on the host. Linux paths are files on PATH; macOS ones are
 * executables inside .app bundles, which is the shape the old list could not express.
 *
 * Chrome ranks above Edge and both rank above a Beta/Canary channel: these harnesses
 * measure layout, and a pre-release engine can legitimately lay out differently from the
 * one visitors use, so it should only ever be a last resort.
 */
const SYSTEM_CANDIDATES = [
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium',
  '/snap/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta',
  '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
];

/**
 * Playwright's browser cache, per OS, plus the PLAYWRIGHT_BROWSERS_PATH override it
 * documents. macOS is ~/Library/Caches/ms-playwright and Linux is ~/.cache/ms-playwright;
 * searching only the second is what made this module blind on a Mac.
 */
function playwrightCacheRoots() {
  const roots = [];
  const override = process.env.PLAYWRIGHT_BROWSERS_PATH;
  // '0' means "next to the package" and names no directory, so it is not a root.
  if ( override && override !== '0' ) roots.push( override );
  roots.push( '/opt/playwright' );
  if ( process.platform === 'darwin' ) {
    roots.push( path.join( os.homedir(), 'Library', 'Caches', 'ms-playwright' ) );
  } else if ( process.platform === 'win32' ) {
    roots.push( path.join( os.homedir(), 'AppData', 'Local', 'ms-playwright' ) );
  }
  // Always searched: it is the Linux default, and a manually seeded cache lands here too.
  roots.push( path.join( os.homedir(), '.cache', 'ms-playwright' ) );
  return roots;
}

function isExecutableFile( p ) {
  try {
    if ( !fs.statSync( p ).isFile() ) return false;
    fs.accessSync( p, fs.constants.X_OK );
    return true;
  } catch {
    return false;
  }
}

/**
 * Highest-numbered chromium-* under a root. Sorted NUMERICALLY, not
 * lexicographically: a string sort puts "chromium-999" above "chromium-1232", which
 * would pick a stale build on any box that happened to hold both.
 */
function scanRevisionRoot( root, searched ) {
  searched.push( root );
  let entries;
  try {
    entries = fs.readdirSync( root );
  } catch {
    return null;
  }

  const revisions = entries
    .map( name => {
      const m = /^chromium(?:_headless_shell)?-(\d+)$/.exec( name );
      return m ? { name, rev: Number( m[ 1 ] ), headless: name.includes( 'headless_shell' ) } : null;
    } )
    .filter( Boolean )
    // Prefer a full chrome over a headless shell at the same revision, then newest first.
    .sort( ( a, b ) => ( b.rev - a.rev ) || ( Number( a.headless ) - Number( b.headless ) ) );

  for ( const { name } of revisions ) {
    for ( const sub of BINARY_SUBPATHS ) {
      const candidate = path.join( root, name, sub );
      if ( isExecutableFile( candidate ) ) return candidate;
    }
  }
  return null;
}

function resolveChrome() {
  const searched = [];

  if ( process.env.CHROME ) {
    searched.push( `$CHROME=${process.env.CHROME}` );
    if ( isExecutableFile( process.env.CHROME ) ) return process.env.CHROME;
  }

  for ( const root of playwrightCacheRoots() ) {
    const found = scanRevisionRoot( root, searched );
    if ( found ) return found;
  }

  for ( const candidate of SYSTEM_CANDIDATES ) {
    searched.push( candidate );
    if ( isExecutableFile( candidate ) ) return candidate;
  }

  throw new Error(
    `No Chromium executable found on ${process.platform}/${process.arch}. Searched:\n  `
    + searched.join( '\n  ' )
    + '\nSet CHROME=/path/to/chrome, or install one with:\n'
    + '  cd tools/browser && npx playwright install chromium'
  );
}

/**
 * The newest Playwright-cached Firefox bundle on macOS, as { app, rev }, or null.
 */
function macFirefoxBundle() {
  for ( const root of playwrightCacheRoots() ) {
    let entries;
    try {
      entries = fs.readdirSync( root );
    } catch {
      continue;
    }
    const revisions = entries
      .map( name => /^firefox-(\d+)$/.exec( name ) )
      .filter( Boolean )
      .sort( ( a, b ) => Number( b[ 1 ] ) - Number( a[ 1 ] ) );
    for ( const m of revisions ) {
      const app = path.join( root, m[ 0 ], 'firefox', 'Nightly.app' );
      if ( isExecutableFile( path.join( app, 'Contents', 'MacOS', 'firefox' ) ) ) return { app, rev: m[ 1 ] };
    }
  }
  return null;
}

/**
 * FIREFOX ON macOS 27 NEEDS AN APP NAME OF ITS OWN, or it cannot start.
 *
 * Playwright's bundled Firefox is branded Name=Firefox, so Gecko keeps its profiles.ini
 * bookkeeping under ~/Library/Application Support/Firefox - the real Firefox's directory, which
 * macOS 27 protects. Launched from a terminal or an editor without Full Disk Access, that lookup
 * is denied and Firefox exits with "Could not find profile folder" before Playwright can talk to
 * it (measured 2026-10-26: macOS 27.0.1, playwright-core 1.63, firefox-1543), whatever -profile
 * says. Diagnosis and fix: https://github.com/microsoft/playwright/issues/42768 - start the same
 * binary with -app pointing at a copy of application.ini whose Name and Vendor differ, so its
 * app-data directory is its own.
 *
 * -app must be the FIRST argument, which launch() args cannot express, so a two-line wrapper
 * script is the executablePath. The bundle is cloned into os.tmpdir() with `cp -c` (APFS
 * clonefile, so no extra disk) and Playwright's shared cache is never modified. Built once per
 * revision; a temporary directory renamed into place keeps two harness runs from racing.
 * Returns undefined when no cached Firefox exists, so Playwright reports its own error.
 */
function macFirefoxExecutable() {
  const found = macFirefoxBundle();
  if ( !found ) return undefined;
  const dir = path.join( os.tmpdir(), `wcd-harness-firefox-${found.rev}` );
  const wrapper = path.join( dir, 'firefox' );
  if ( isExecutableFile( wrapper ) ) return wrapper;
  const { execFileSync } = require( 'child_process' );
  const tmp = `${dir}.tmp-${process.pid}`;
  fs.rmSync( tmp, { recursive: true, force: true } );
  fs.mkdirSync( tmp, { recursive: true } );
  try {
    execFileSync( 'cp', [ '-cR', found.app, path.join( tmp, 'Nightly.app' ) ] );
  } catch {
    execFileSync( 'cp', [ '-R', found.app, path.join( tmp, 'Nightly.app' ) ] );
  }
  // READ FROM Resources/, WRITE TO Resources/browser/, deliberately. Resources/application.ini is
  // the file carrying the branding (Vendor=Mozilla, Name=Firefox in firefox-1543), under a comment
  // saying it is unused unless copied into browser/ and named with -app, which is exactly what this
  // does. If a future bundle moves or drops those keys, refuse rather than silently launching with
  // the original branding, which would bring the "Could not find profile folder" exit back.
  const resources = path.join( tmp, 'Nightly.app', 'Contents', 'Resources' );
  const source = fs.readFileSync( path.join( resources, 'application.ini' ), 'utf8' );
  if ( !/^Vendor=.*$/m.test( source ) || !/^Name=.*$/m.test( source ) ) {
    fs.rmSync( tmp, { recursive: true, force: true } );
    throw new Error( `Firefox ${found.rev}: Resources/application.ini has no Vendor=/Name= line to rebrand` );
  }
  const ini = source
    .replace( /^Vendor=.*$/m, 'Vendor=WecareHarness' )
    .replace( /^Name=.*$/m, 'Name=WecareHarnessFirefox' );
  fs.writeFileSync( path.join( resources, 'browser', 'application.ini' ), ini );
  // The wrapper names the FINAL location, which is where it runs from after the rename.
  const finalApp = path.join( dir, 'Nightly.app' );
  fs.writeFileSync( path.join( tmp, 'firefox' ),
    `#!/bin/sh\nexec "${path.join( finalApp, 'Contents', 'MacOS', 'firefox' )}" -app "${path.join( finalApp, 'Contents', 'Resources', 'browser', 'application.ini' )}" "$@"\n`,
    { mode: 0o755 } );
  try {
    fs.renameSync( tmp, dir );
  } catch ( e ) {
    fs.rmSync( tmp, { recursive: true, force: true } );
    if ( !isExecutableFile( wrapper ) ) throw e;
  }
  return wrapper;
}

/**
 * Launch one of the three engines: 'chromium' (resolved as above), 'webkit', or 'firefox'
 * (with the macOS 27 workaround). Callers own closing it.
 */
async function launchEngine( engine = 'chromium', opts = {} ) {
  if ( engine === 'chromium' ) return launch( opts );
  const pw = require( 'playwright-core' );
  if ( engine === 'firefox' && process.platform === 'darwin' ) {
    const executablePath = macFirefoxExecutable();
    if ( executablePath ) return withMediaCache( await pw.firefox.launch( { executablePath, ...opts } ) );
  }
  return withMediaCache( await pw[ engine ].launch( opts ) );
}

/** Launch a headless Chromium. Callers own closing it. */
async function launch( opts = {} ) {
  const { chromium } = require( 'playwright-core' );
  return withMediaCache( await chromium.launch( {
    executablePath: resolveChrome(),
    // BOTH FLAGS ARE LINUX CONTAINER WORKAROUNDS, so they are scoped to Linux rather
    // than passed everywhere. --no-sandbox: the sandbox container runs as root, where
    // Chromium's setuid sandbox refuses to start at all. --disable-dev-shm-usage:
    // /dev/shm is small there and the renderer crashes on larger pages without it.
    //
    // Neither condition exists on a developer Mac, and --no-sandbox is not a harmless
    // no-op - it turns off a real security boundary while this harness loads pages. A
    // flag whose justification does not hold should not be sent.
    args: process.platform === 'linux' ? [ '--no-sandbox', '--disable-dev-shm-usage' ] : [],
    ...opts,
  } ) );
}

/**
 * Navigate, and wait for the page to be MEASURABLE - which is not the same thing as
 * waiting for the network to go quiet.
 *
 * WHY NOT waitUntil:'networkidle'. Every harness here used it, and it failed in CI:
 * typecheck.js died on `page.goto: Timeout 30000ms exceeded` after animcheck and seocheck
 * had already passed on the same runner. networkidle resolves only after 500ms with no
 * in-flight requests, so anything that keeps a connection warm - an analytics beacon, a
 * font request that retries, a container that polls - can stop it resolving at all. It is
 * a proxy for "the page has settled" that depends on conditions unrelated to the page, and
 * it is flakiest on the harness that navigates most: typecheck visits 15 routes at 2 widths,
 * so it gets 30 chances to hit it where animcheck gets 4.
 *
 * WHAT ACTUALLY MATTERS for these measurements is that web fonts have loaded. Text width,
 * line count and reflow all change when a fallback face is swapped for Inter, and that is
 * the one late-arriving resource that can alter a number. document.fonts.ready is the
 * direct signal for it, so this waits on the real dependency instead of on a correlate.
 *
 * The short settle after it absorbs the layout pass that a font swap triggers. Verified to
 * produce byte-identical output to the networkidle version of typecheck.js locally.
 */
async function gotoStable( page, url, opts = {} ) {
  const res = await page.goto( url, {
    waitUntil: 'load',
    // Generous because a cold CI runner compiling a route is legitimately slow, and the
    // failure this replaces was a timeout rather than a broken page.
    timeout: opts.timeout || 60000,
  } );
  // Never let font detection itself break a run: a page with no webfonts, or a browser
  // without the FontFaceSet API, should measure fine.
  await page.evaluate( async () => {
    if ( document.fonts && document.fonts.ready ) await document.fonts.ready;
    return true;
  } ).catch( () => {} );
  await page.waitForTimeout( opts.settle === undefined ? 250 : opts.settle );
  return res;
}

/**
 * PRODUCTION MEDIA, SERVED FROM A LOCAL CACHE (2026-10-27 audit).
 *
 * The static export references shop images and logos by absolute production URL, so every page
 * the harness opened downloaded them from wecare.digital again. On the Public UI compliance
 * workflow's first day that was about 0.26 GB of Amplify transfer per run, mostly 2.4 MB catalog
 * PNGs re-fetched for each route and posture. Browsers from launch() and launchEngine() now answer
 * those URLs from a disk cache keyed by URL, so each image crosses the network once per cache
 * lifetime. The bytes are the same, so the layout under test is unchanged. A failed fetch falls
 * through to the network. HARNESS_MEDIA_CACHE sets the directory (CI keeps one per day), and
 * HARNESS_LIVE_MEDIA=1 turns the cache off.
 */
const MEDIA_URL = /^https:\/\/wecare\.digital\/(api\/catalog-media\/|get\/)/;
const MEDIA_HEADERS = [ 'content-type', 'cache-control', 'etag', 'last-modified', 'access-control-allow-origin' ];
const mediaStats = { cached: 0, fetched: 0 };
const mediaRouted = new WeakSet();

function mediaCacheDir() {
  const mpath = require( 'path' );
  return mpath.resolve( process.env.HARNESS_MEDIA_CACHE || mpath.join( require( 'os' ).tmpdir(), 'wecare-harness-media' ) );
}

async function serveMedia( route ) {
  const mfs = require( 'fs' ), mpath = require( 'path' );
  const request = route.request();
  if ( request.method() !== 'GET' ) return route.fallback();
  const key = require( 'crypto' ).createHash( 'sha256' ).update( request.url() ).digest( 'hex' );
  const bodyFile = mpath.join( mediaCacheDir(), key ), metaFile = `${ bodyFile }.json`;
  try {
    const { headers } = JSON.parse( mfs.readFileSync( metaFile, 'utf8' ) );
    const body = mfs.readFileSync( bodyFile );
    mediaStats.cached++;
    return route.fulfill( { status: 200, headers, body } );
  } catch { /* not cached yet */ }
  let response;
  try { response = await route.fetch(); } catch { return route.fallback(); }
  const body = await response.body();
  if ( response.status() === 200 ) {
    try {
      const all = response.headers(), headers = {};
      for ( const h of MEDIA_HEADERS ) if ( all[ h ] ) headers[ h ] = all[ h ];
      mfs.mkdirSync( mpath.dirname( bodyFile ), { recursive: true } );
      mfs.writeFileSync( `${ bodyFile }.tmp`, body );
      mfs.renameSync( `${ bodyFile }.tmp`, bodyFile );
      mfs.writeFileSync( `${ metaFile }.tmp`, JSON.stringify( { url: request.url(), headers } ) );
      mfs.renameSync( `${ metaFile }.tmp`, metaFile );
    } catch { /* the cache is best effort */ }
  }
  mediaStats.fetched++;
  return route.fulfill( { response, body } );
}

async function routeMedia( context ) {
  if ( mediaRouted.has( context ) ) return;
  mediaRouted.add( context );
  await context.route( MEDIA_URL, serveMedia );
}

function withMediaCache( browser ) {
  if ( process.env.HARNESS_LIVE_MEDIA === '1' || browser.__wecareMediaCache ) return browser;
  browser.__wecareMediaCache = true;
  const newContext = browser.newContext.bind( browser );
  browser.newContext = async ( ...args ) => {
    const context = await newContext( ...args );
    await routeMedia( context );
    return context;
  };
  const newPage = browser.newPage.bind( browser );
  browser.newPage = async ( ...args ) => {
    const page = await newPage( ...args );
    await routeMedia( page.context() );
    return page;
  };
  return browser;
}

process.on( 'exit', () => {
  if ( mediaStats.cached || mediaStats.fetched ) {
    console.log( `production media: ${ mediaStats.cached } served from cache, ${ mediaStats.fetched } fetched (${ mediaCacheDir() })` );
  }
} );

module.exports = { resolveChrome, launch, launchEngine, gotoStable };
