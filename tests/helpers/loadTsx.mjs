// Offline TSX/TS loader for the node:test harness.
//
// This mirrors the long-standing offline-testing idiom in
// scripts/check_production_data_safety.cjs: a .tsx/.ts source file is
// compiled in memory with esbuild.transformSync({ loader: 'tsx' }) and then
// evaluated in a node:vm context with injectable globals (fetch, env, URL,
// Date, ...). That lets tests exercise the real exported helper functions
// from React components without a bundler, a DOM, or any network access.
//
// esbuild is already a devDependency (^0.28.0), so this harness adds no new
// heavy test-runner dependency. Tests use Node's built-in `node:test` runner.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import * as esbuild from 'esbuild';

const REPO_ROOT = path.resolve( new URL( '../..', import.meta.url ).pathname );

/**
 * Compile a .tsx/.ts source string to CommonJS with esbuild.
 *
 * @param {string} source Raw TypeScript/TSX source.
 * @returns {string} Compiled CommonJS code.
 */
export function compileTsx( source ) {
  return esbuild.transformSync( source, {
    loader: 'tsx',
    format: 'cjs',
    target: 'es2022',
  } ).code;
}

/**
 * Read a source file relative to the repository root.
 *
 * @param {string} relativePath Path such as 'src/components/Foo.tsx'.
 * @returns {string} File contents.
 */
export function readSource( relativePath ) {
  return fs.readFileSync( path.resolve( REPO_ROOT, relativePath ), 'utf8' );
}

/**
 * Compile and evaluate a TSX/TS module in an isolated vm context, returning
 * its exports. Only the named exports present in the compiled source are
 * available; pass `exportNames` to re-export helpers that the source declares
 * but does not already export (matching the `source + '\nexport { ... };'`
 * trick used by check_production_data_safety.cjs).
 *
 * @param {object} options
 * @param {string} [options.file] Path (relative to repo root) to read source from.
 * @param {string} [options.source] Raw source string (alternative to `file`).
 * @param {string[]} [options.exportNames] Extra identifiers to re-export.
 * @param {object} [options.globals] Globals injected into the vm sandbox
 *   (e.g. fetch, env). `env` becomes `process.env` inside the sandbox.
 * @returns {{ exports: object, sandbox: object }} The module exports and the
 *   live sandbox (so a test can swap `sandbox.fetch` between assertions).
 */
export function loadTsxModule( { file, source, exportNames = [], globals = {} } = {} ) {
  if ( typeof source !== 'string' ) {
    if ( typeof file !== 'string' ) {
      throw new Error( 'loadTsxModule requires either a `file` or a `source` string' );
    }
    source = readSource( file );
  }

  const withExports = exportNames.length > 0
    ? `${ source }\nexport { ${ exportNames.join( ', ' ) } };`
    : source;

  const code = compileTsx( withExports );

  const compiledModule = { exports: {} };
  const env = globals.env ?? {};

  const sandbox = {
    module: compiledModule,
    exports: compiledModule.exports,
    process: { env },
    URL,
    Date,
    DOMException,
    console,
    require: globals.require ?? ( () => ( {} ) ),
    fetch: globals.fetch ?? ( async () => {
      throw new Error( 'Unexpected network request' );
    } ),
    ...stripReserved( globals ),
  };

  vm.runInNewContext( code, sandbox );

  return { exports: compiledModule.exports, sandbox };
}

// `env` and `require` are handled explicitly above; everything else in
// `globals` is spread onto the sandbox as-is.
function stripReserved( globals ) {
  const { env, require, fetch, ...rest } = globals;
  void env;
  void require;
  void fetch;
  return rest;
}
