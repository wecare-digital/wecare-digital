import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * NOTHING OUTSIDE src/test/ MAY REACH A NATIVE BROWSER DIALOG. Second line of defence.
 *
 * WHY THIS EXISTS WHEN eslint.config.mjs ALREADY HAS THE RULE. The real gate is the ESLint
 * pair appended to eslint.config.mjs, and it is the better instrument: `no-restricted-globals`
 * resolves scope, so it flags only references that reach the DOM global and leaves every
 * `const confirm = useConfirm()` alone. This file is here because a lint rule can be deleted,
 * downgraded or shadowed by a later config object in one line, and `npm run lint` exits 0 with
 * warnings - so a demotion from 'error' to 'warn' would not fail CI. So the suite asserts both
 * halves: no native call in the tree, AND the rule still present and still an error.
 *
 * WHY THE BARE-CALL SCAN IS PER-FILE AND NOT A FLAT GREP. `confirm` means three different
 * things here - the DOM global, the useConfirm hook, and a local useCallback at
 * src/components/security/TotpSetup.tsx:221 that completes TOTP enrolment. A flat grep for
 * `confirm(` returns roughly forty hook call sites and that local function, so the test
 * approximates scope the only way a text scan can: a file may call `confirm(` IF it also
 * declares the identifier. The lint rule is what checks it properly.
 */

const REPO = path.join( __dirname, '..', '..' );
const SRC = path.join( REPO, 'src' );
const DIALOGS = [ 'alert', 'confirm', 'prompt' ] as const;

const WALK = ( dir: string, out: string[] = [] ): string[] => {
  for ( const entry of fs.readdirSync( dir, { withFileTypes: true } ) ) {
    const full = path.join( dir, entry.name );
    if ( entry.isDirectory() ) WALK( full, out );
    else if ( /\.(ts|tsx)$/.test( entry.name ) ) out.push( full );
  }
  return out;
};

const rel = ( full: string ) => path.relative( REPO, full ).split( path.sep ).join( '/' );

/**
 * Reduce a file to its CODE: comments blanked, string and template-literal TEXT blanked, and
 * `${ ... }` interpolations kept because those are code.
 *
 * THIS IS A CHARACTER SCANNER AND NOT A REGEX, and that is not fastidiousness - both regex
 * attempts were measurably wrong, in opposite directions:
 *
 *   - Stripping `/* ... *\/` by regex first: four files carry a file-input
 *     `accept="image/*,video/*"` whose slash-star opens a false block comment that the strip
 *     then closes at the next real terminator, in one measured case swallowing 237 lines. A
 *     native call inside the swallowed range disappears and this test passes while the dialog
 *     is live. That is a fail-OPEN.
 *   - Masking only quoted strings to dodge it: src/pages/workspace/dashboard/index.tsx holds
 *     BACKTICKED ARNs like `arn:aws:dynamodb:...:table/*`, so the same false comment opened
 *     from a template literal and swallowed that file's `const confirm = useConfirm()` - which
 *     made a correctly-migrated file look like it called the global. A fail-CLOSED, which is
 *     merely annoying, but it proves the regex cannot tell data from code here.
 *
 * Keeping `${ ... }` is the one deliberate asymmetry: a template literal's text is data, but
 * its interpolations are expressions and a call could hide in one.
 */
const codeOnly = ( src: string ): string => {
  let out = '';
  let i = 0;
  const n = src.length;
  while ( i < n ) {
    const c = src[ i ];
    const next = src[ i + 1 ];
    if ( c === '/' && next === '*' ) {
      const end = src.indexOf( '*/', i + 2 );
      out += ' ';
      i = end === -1 ? n : end + 2;
      continue;
    }
    if ( c === '/' && next === '/' ) {
      const end = src.indexOf( '\n', i );
      out += ' ';
      i = end === -1 ? n : end;
      continue;
    }
    if ( c === '\'' || c === '"' ) {
      const quote = c;
      out += ' ';
      i++;
      while ( i < n && src[ i ] !== quote && src[ i ] !== '\n' ) {
        i += src[ i ] === '\\' ? 2 : 1;
      }
      i++;
      continue;
    }
    if ( c === '`' ) {
      out += ' ';
      i++;
      while ( i < n ) {
        if ( src[ i ] === '\\' ) { i += 2; continue; }
        if ( src[ i ] === '`' ) { i++; break; }
        if ( src[ i ] === '$' && src[ i + 1 ] === '{' ) {
          i += 2;
          const start = i;
          let depth = 1;
          while ( i < n ) {
            if ( src[ i ] === '{' ) depth++;
            else if ( src[ i ] === '}' && --depth === 0 ) break;
            i++;
          }
          // Recursed, so a nested template literal inside the interpolation is handled too.
          out += ` ${ codeOnly( src.slice( start, i ) ) } `;
          i++;
          continue;
        }
        i++;
      }
      out += ' ';
      continue;
    }
    out += c;
    i++;
  }
  return out;
};

/** `window.alert(...)` and friends. Never legal outside src/test/, in any file. */
const windowDialogCalls = ( raw: string ): string[] => {
  const src = codeOnly( raw );
  return DIALOGS.filter( name => new RegExp( `window\\s*\\.\\s*${ name }\\s*\\(` ).test( src ) );
};

/**
 * A bare `confirm(...)` / `prompt(...)` / `alert(...)` whose identifier the file does not
 * declare, which is the only shape that can resolve to the global.
 */
const undeclaredDialogCalls = ( raw: string ): string[] => {
  const src = codeOnly( raw );
  return DIALOGS.filter( name => {
    const called = new RegExp( `(^|[^.\\w$])${ name }\\s*\\(` ).test( src );
    if ( !called ) return false;
    const declared = new RegExp(
      `(const|let|var|function|function\\*)\\s+${ name }\\b`
      + `|\\{[^}]*\\b${ name }\\b[^}]*\\}\\s*=`        // destructured
      + `|\\(\\s*${ name }\\s*[,:)]`,                   // a parameter
    ).test( src );
    return !declared;
  } );
};

describe( 'no native browser dialogs outside src/test/', () => {
  const files = WALK( SRC ).filter( f => !rel( f ).startsWith( 'src/test/' ) );

  it( 'scanned a plausible number of files', () => {
    // Anti-vacuous guard on the walk itself: an empty list satisfies every assertion below
    // for the wrong reason.
    expect( files.length ).toBeGreaterThan( 200 );
  } );

  it( 'calls window.alert, window.confirm or window.prompt nowhere', () => {
    const offenders = files
      .map( f => [ rel( f ), windowDialogCalls( fs.readFileSync( f, 'utf8' ) ) ] as const )
      .filter( ( [ , hits ] ) => hits.length )
      .map( ( [ name, hits ] ) => `${ name }: ${ hits.join( ', ' ) }` );

    expect(
      offenders,
      'A native dialog is the browser\'s UI, not ours: it ignores every design token, cannot '
      + 'be styled, blocks the main thread and reads as a system error on mobile. Use '
      + 'useToastContext() for an outcome, useConfirm() for a gate, usePromptDialog() for a '
      + 'free-text answer - all in src/contexts/.',
    ).toEqual( [] );
  } );

  it( 'never calls a bare alert/confirm/prompt that the file does not declare', () => {
    const offenders = files
      .map( f => [ rel( f ), undeclaredDialogCalls( fs.readFileSync( f, 'utf8' ) ) ] as const )
      .filter( ( [ , hits ] ) => hits.length )
      .map( ( [ name, hits ] ) => `${ name }: ${ hits.join( ', ' ) }` );

    expect( offenders ).toEqual( [] );
  } );

  it( 'leaves TotpSetup\'s local confirm alone, because it is not the global', () => {
    // src/components/security/TotpSetup.tsx:221 declares `const confirm = useCallback(...)`
    // that completes TOTP enrolment, and :386 calls it. A sed across the files this batch
    // touched would have broken MFA setup. This asserts both halves are still there.
    const src = fs.readFileSync( path.join( SRC, 'components', 'security', 'TotpSetup.tsx' ), 'utf8' );
    expect( /const\s+confirm\s*=\s*useCallback/.test( src ) ).toBe( true );
    expect( /void\s+confirm\s*\(\s*\)/.test( src ) ).toBe( true );
    expect( undeclaredDialogCalls( src ) ).toEqual( [] );
  } );

  it( 'routes all six migrated sites through a hook', () => {
    const expected: [ string, RegExp ][] = [
      [ 'src/components/TemplateSender.tsx', /useConfirm\b/ ],
      [ 'src/pages/workspace/dashboard/secure-files.tsx', /useConfirm\b/ ],
      [ 'src/pages/workspace/engage/whatsapp/ctwa-ads.tsx', /useConfirmDanger\b/ ],
      [ 'src/pages/workspace/seo/blog-manager.tsx', /useConfirmDanger\b/ ],
      [ 'src/pages/workspace/seo/blog-production/qa/index.tsx', /usePromptDialog\b/ ],
      [ 'src/pages/workspace/seo/blog-production/publish/index.tsx', /usePromptDialog\b/ ],
    ];
    for ( const [ file, hook ] of expected ) {
      const src = codeOnly( fs.readFileSync( path.join( REPO, file ), 'utf8' ) );
      expect( hook.test( src ), `${ file } no longer uses ${ hook }` ).toBe( true );
    }
  } );

  it( 'finds a planted call, and loses a commented one', () => {
    // PLANTED SAMPLE. "The scan found nothing" and "the regex matches nothing" are the same
    // result, and the second one would be cited as evidence. So the detectors are exercised
    // on text whose answer is known, including the two ways they could fail open.
    expect( windowDialogCalls( 'if ( window.confirm( "x" ) ) go();' ) ).toEqual( [ 'confirm' ] );
    expect( windowDialogCalls( 'window . prompt ( "x" )' ) ).toEqual( [ 'prompt' ] );
    expect( undeclaredDialogCalls( 'if ( confirm( "x" ) ) go();' ) ).toEqual( [ 'confirm' ] );
    expect( undeclaredDialogCalls( 'alert( "x" );' ) ).toEqual( [ 'alert' ] );

    // A declared identifier is a different thing with the same name, and must pass.
    expect( undeclaredDialogCalls( 'const confirm = useConfirm();\nif ( await confirm( "x" ) ) go();' ) ).toEqual( [] );
    expect( undeclaredDialogCalls( 'const prompt = usePromptDialog();\nawait prompt( { label: "y" } );' ) ).toEqual( [] );
    expect( undeclaredDialogCalls( 'const confirm = useCallback( () => {}, [] );\nvoid confirm();' ) ).toEqual( [] );
    expect( undeclaredDialogCalls( 'const { confirm } = ctx();\nconfirm( "x" );' ) ).toEqual( [] );
    expect( undeclaredDialogCalls( 'obj.confirm( "x" );' ) ).toEqual( [] );

    // Comments must not read as calls - the reason this file's own prose is safe.
    expect( windowDialogCalls( '/* window.confirm( "x" ) was deleted */' ) ).toEqual( [] );
    expect( undeclaredDialogCalls( '  // confirm( "x" ) was deleted' ) ).toEqual( [] );
    expect( undeclaredDialogCalls( 'go(); // confirm( "x" ) was deleted' ) ).toEqual( [] );

    // A quoted string is data, not code, and the ESLint rule agrees. This is what lets the
    // XSS commentary and fixtures mentioning javascript:alert(1) survive.
    expect( windowDialogCalls( 'const s = "window.alert(1)";' ) ).toEqual( [] );
    expect( undeclaredDialogCalls( 'check( "javascript:alert(1)" );' ) ).toEqual( [] );

    // A MIME wildcard must not open a comment that swallows a live call after it...
    expect( windowDialogCalls( '<input accept="image/*,video/*" />\nwindow.alert( "x" );' ) )
      .toEqual( [ 'alert' ] );
    // ...and nor must a backticked ARN wildcard, which is how a real migrated file came to
    // look unmigrated.
    expect( undeclaredDialogCalls(
      'const a = `arn:aws:dynamodb:x:y:table/*`;\nconst confirm = useConfirm();\nconfirm( "x" );' ) )
      .toEqual( [] );
    // An interpolation IS code, so a call hiding in one is still found.
    expect( windowDialogCalls( 'const t = `x ${ window.confirm( "y" ) } z`;' ) )
      .toEqual( [ 'confirm' ] );
  } );
} );

describe( 'the ESLint gate that keeps a seventh native dialog out', () => {
  const config = fs.readFileSync( path.join( REPO, 'eslint.config.mjs' ), 'utf8' )
    // The config's own rationale names the rules and the config objects in prose, so the
    // comments go first or every one of them reads as a declaration.
    .replace( /^[ \t]*\/\/.*$/gm, ' ' );

  /**
   * The `name` of each config OBJECT, which is a `name:` at the start of its own line.
   *
   * The qualifier is load-bearing: `no-restricted-globals` entries are `{ name: 'prompt' }`
   * written inline, so an unanchored match returns 'prompt' as the last config name and the
   * ordering assertion fails for a reason that has nothing to do with ordering.
   */
  const objectNames = [ ...config.matchAll( /^[ \t]*name:\s*'([^']+)'/gm ) ].map( m => m[ 1 ] );

  it( 'declares both objects as the LAST TWO entries of the exported array', () => {
    // Order matters twice over. Flat config resolves by order, so the src/test/** exemption
    // has to come after the rule it relaxes. And being last keeps the gate out of the
    // 'wecare/react-compiler-advisory' block, whose own comment ends "this block should be
    // deleted rather than extended" - a gate living inside it would vanish with it.
    expect( objectNames.slice( -2 ) ).toEqual( [
      'wecare/no-native-dialogs',
      'wecare/no-native-dialogs-test-exempt',
    ] );
    expect( objectNames ).toContain( 'wecare/react-compiler-advisory' );
    // Nothing may follow the exemption but the end of the array.
    expect( config.slice( config.lastIndexOf( '\'no-restricted-properties\': \'off\'' ) ) )
      .toMatch( /^'no-restricted-properties':\s*'off'\s*\}\s*,?\s*\}\s*,?\s*\]\s*;?\s*$/ );
  } );

  it( 'restricts all three globals and all three window properties, as errors', () => {
    const gate = config.slice( config.indexOf( '\'wecare/no-native-dialogs\'' ),
      config.indexOf( '\'wecare/no-native-dialogs-test-exempt\'' ) );
    expect( gate ).toContain( '\'no-restricted-globals\': [ \'error\'' );
    expect( gate ).toContain( '\'no-restricted-properties\': [ \'error\'' );
    for ( const name of DIALOGS ) {
      expect( gate, `no-restricted-globals is missing ${ name }` )
        .toMatch( new RegExp( `name:\\s*'${ name }'` ) );
      expect( gate, `no-restricted-properties is missing window.${ name }` )
        .toMatch( new RegExp( `object:\\s*'window',\\s*property:\\s*'${ name }'` ) );
    }
  } );

  it( 'exempts src/test/** and nothing else', () => {
    // The exemption keeps the four XSS fixtures asserting `javascript:alert(1)` working, and
    // lets this suite's own planted samples exist. Widening it past src/test/** would open
    // the gate on real source.
    const exempt = config.slice( config.indexOf( '\'wecare/no-native-dialogs-test-exempt\'' ) );
    expect( exempt ).toMatch( /files:\s*\[\s*'src\/test\/\*\*'\s*\]/ );
    expect( exempt ).toContain( '\'no-restricted-globals\': \'off\'' );
    expect( exempt ).toContain( '\'no-restricted-properties\': \'off\'' );
    expect( exempt.match( /files:\s*\[/g ) ).toHaveLength( 1 );
  } );
} );
