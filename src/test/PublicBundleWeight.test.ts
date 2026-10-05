import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The Amplify dependency must not drift back into the bundle every public page downloads.
 *
 * WHAT THIS PROTECTS, AND WHY A TEST RATHER THAN A COMMENT
 * -------------------------------------------------------
 * `_app.tsx` used to do two unconditional things at module scope:
 *
 *   import { Authenticator, ThemeProvider, ... } from '@aws-amplify/ui-react';
 *   import '@aws-amplify/ui-react/styles.css';
 *
 * In the pages router neither is conditional. The first put a 450 kB client chunk in the
 * shared bundle; the second put 310 kB of minified CSS in the `data-n-g` bundle. Measured on
 * the built export, the home page carried 1,098 kB of JavaScript and 520 kB of CSS, and
 * 735 kB of that was for a sign-in card no marketing page renders. Chrome's rule-usage
 * tracker applied SEVEN rules of the stylesheet on `/`.
 *
 * After the split: 666 kB of JavaScript and 217 kB of CSS on the home page, with the
 * Authenticator in `components/AuthShell.tsx` behind `next/dynamic` and the stylesheet served
 * from `public/vendor/amplify-ui.css` by a <link> in the authenticated branch only.
 *
 * BOTH HALVES ARE ONE LINE AWAY FROM COMING BACK. Adding either import to `_app.tsx` is the
 * natural thing to do when wiring a new Amplify UI component, it produces no error, no
 * warning and no visual change, and the cost lands on every public visitor. Nothing else in
 * the suite measures bundle weight, so this is the only place the regression is catchable.
 *
 * It asserts the CAUSE rather than a byte count. A size threshold over a built artifact would
 * need `npm run build` to have run, would drift with every dependency bump, and would report
 * "the home page got bigger" rather than why.
 */
describe( 'the public bundle does not carry the sign-in UI', () => {
  const read = ( ...parts: string[] ): string =>
    readFileSync( resolve( process.cwd(), ...parts ), 'utf8' );

  const app = read( 'src', 'pages', '_app.tsx' );
  const authShell = read( 'src', 'components', 'AuthShell.tsx' );
  const pkg = JSON.parse( read( 'package.json' ) );

  /**
   * _app.tsx with comments removed, for the NEGATIVE assertions only.
   *
   * The same precaution `PublicWidgets.test.tsx` documents, and for the same reason: the
   * comments in `_app.tsx` explaining this split necessarily NAME the imports that were
   * removed, so a check against the raw source fails on the note recording the fix. It did,
   * on the first run of this file.
   */
  const appCode = app
    .replace( /\/\*[\s\S]*?\*\//g, '' )
    .replace( /\{\s*\/\*[\s\S]*?\*\/\s*\}/g, '' )
    .replace( /^\s*\/\/.*$/gm, '' );

  it( 'does not import @aws-amplify/ui-react from the custom App', () => {
    // Any static import of the library from _app.tsx re-merges it into the shared chunk,
    // whichever symbol is pulled in - the module graph does not care that you only wanted
    // one component.
    expect(
      appCode,
      '_app.tsx must not statically import @aws-amplify/ui-react - it would put the '
      + "library's 450 kB chunk back in the bundle every public page loads. Add the component "
      + 'to src/components/AuthShell.tsx instead, which _app.tsx loads with next/dynamic.'
    ).not.toMatch( /from\s+'@aws-amplify\/ui-react'/ );
  } );

  it( 'does not import the Amplify UI stylesheet globally', () => {
    // A global CSS import is unconditional in the pages router: it ships on every route.
    expect(
      appCode,
      "_app.tsx must not import '@aws-amplify/ui-react/styles.css' - a global CSS import "
      + 'lands on every route, and a public page applies seven of its rules. Those seven are '
      + 'src/styles/amplify-base.css; the rest is linked from public/vendor/ on the '
      + 'authenticated branch.'
    ).not.toMatch( /@aws-amplify\/ui-react\/styles\.css/ );
  } );

  it( 'loads the authenticated shell lazily, with SSR left on', () => {
    expect( app ).toMatch( /dynamic\(\s*\(\)\s*=>\s*import\(\s*'\.\.\/components\/AuthShell'\s*\)/ );
    // ssr:false WOULD BE A REGRESSION, NOT AN OPTIMISATION. This is a static export, so SSR
    // means "rendered to HTML at build time"; turning it off would empty the sign-in shell
    // out of 113 exported workspace pages and change what tools/browser/pageaudit.js
    // measures, while saving nothing - the chunk is already split either way.
    expect(
      appCode.match( /dynamic\([\s\S]{0,200}?AuthShell[\s\S]{0,120}?\)/ )?.[ 0 ] ?? '',
      'AuthShell must keep SSR on: the export would otherwise ship 113 workspace pages with '
      + 'no sign-in shell in the HTML'
    ).not.toMatch( /ssr\s*:\s*false/ );
  } );

  it( 'keeps the Amplify UI tree, and only it, inside AuthShell', () => {
    expect( authShell ).toMatch( /from\s+'@aws-amplify\/ui-react'/ );
    expect( authShell ).toContain( '<Authenticator' );
    expect( authShell ).toContain( 'ThemeProvider' );
  } );

  it( 'vendors the stylesheet during the build, before next build runs', () => {
    // ORDER IS THE ASSERTION. `public/` is copied into `out/` by `next build`, so a generator
    // that runs afterwards writes a file the export never sees - and the <link> 404s with no
    // build error at all, leaving the sign-in card unstyled in production only.
    const build: string = pkg.scripts.build;
    const vendor = build.indexOf( 'generate-vendor-css' );
    const next = build.indexOf( 'next build' );
    expect( vendor, 'npm run build must run scripts/generate-vendor-css.js' ).toBeGreaterThan( -1 );
    expect(
      vendor,
      'generate-vendor-css.js must run BEFORE `next build`, which is what copies public/ into out/'
    ).toBeLessThan( next );
  } );

  it( 'references the vendored stylesheet at the path the generator writes', () => {
    // The one string that ties the generator, the gitignore entry and the <link> together. A
    // rename in any one of the three is otherwise a 404 nothing reports.
    expect( app ).toContain( "'/vendor/amplify-ui.css'" );
    expect( read( 'scripts', 'generate-vendor-css.js' ) ).toContain( "'amplify-ui.css'" );
    expect( read( '.gitignore' ) ).toContain( 'public/vendor/amplify-ui.css' );
  } );
} );
