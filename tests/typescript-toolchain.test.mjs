import { readFileSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { sep } from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const root = new URL('../', import.meta.url);
const read = path => readFileSync(new URL(path, root), 'utf8');
const pkg = JSON.parse(read('package.json'));
const lock = JSON.parse(read('package-lock.json')).packages;

test('the typescript alias names a published compat release that the lockfile installs', () => {
  // npm ci compares only the version of an aliased dependency, never the package name. A lock
  // entry for the real `typescript` 6.0.3 therefore passed while package.json named
  // `@typescript/typescript6@6.0.3`, a release that does not exist (fresh installs: ETARGET).
  const spec = pkg.devDependencies.typescript.match(/^npm:@typescript\/typescript6@(\d+\.\d+\.\d+)$/);
  assert.ok(spec, 'typescript must alias an exact @typescript/typescript6 release');
  assert.equal(lock['node_modules/typescript'].name, '@typescript/typescript6');
  assert.equal(lock['node_modules/typescript'].version, spec[1]);
  // The compat package re-exports the real TypeScript 6 API, installed as @typescript/old.
  assert.equal(lock['node_modules/@typescript/old']?.name, 'typescript');
  assert.match(lock['node_modules/@typescript/old'].version, /^6\.0\.\d+$/);
});

test('tsc runs TypeScript 7 while the typescript API stays on 6.0', () => {
  const native = pkg.devDependencies['@typescript/native'].match(/^npm:typescript@(\d+\.\d+\.\d+)$/);
  assert.ok(native, '@typescript/native must alias an exact typescript release');
  assert.equal(lock['node_modules/@typescript/native'].version, native[1]);
  // @typescript/native and @typescript/old both declare a `tsc` bin; the linked one must be 7's.
  const tsc = realpathSync(new URL('node_modules/.bin/tsc', root));
  assert.ok(tsc.includes(['node_modules', '@typescript', 'native', ''].join(sep)), `node_modules/.bin/tsc is ${tsc}`);
  const requireFromRoot = createRequire(new URL('package.json', root));
  assert.match(requireFromRoot('typescript').version, /^6\.0\.\d+$/);
});
