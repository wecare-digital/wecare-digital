import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const SOURCE = fs.readFileSync( path.join( process.cwd(), 'src/pages/404.tsx' ), 'utf8' );

describe( 'missing pages use one home fallback', () => {
  it( 'uses a literal home destination without legacy exceptions', () => {
    expect( SOURCE ).toMatch( /router\.replace\(\s*'\/'\s*\)/ );
    expect( SOURCE ).not.toMatch( /router\.push|window\.location|RETIRED_PATH_PREFIXES/ );
  } );
  it( 'is not indexed', () => {
    expect( SOURCE ).toContain( '<meta name="robots" content="noindex, follow" />' );
  } );
  it( 'is a pure redirect to home - a no-JS meta refresh and no visible 404 content', () => {
    // Owner 2026-10-13: the 404 is now a PURE redirect, no visible screen. The no-JavaScript
    // path is a meta refresh to home (the static-export fallback the router.replace cannot
    // cover), and the old "This page is unavailable." copy and the explicit home anchor are gone.
    expect( SOURCE ).toMatch( /http-equiv="refresh"|httpEquiv="refresh"/ );
    expect( SOURCE ).toMatch( /content="0;\s*url=\/"/ );
    expect( SOURCE ).not.toContain( 'This page is unavailable.' );
  } );
} );
