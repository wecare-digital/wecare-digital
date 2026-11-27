import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

test('Amplify and GitHub CI share the selected Node major and exact npm pin', () => {
  const major = read('.nvmrc').trim();
  const registry = read('packages/config/vendorVersions.ts');
  const spec = read('amplify.yml');
  const ci = read('.github/workflows/ci.yml');
  assert.match(major, /^\d+$/);
  assert.match(registry, new RegExp("name: 'Node\\.js',\\s*configured: '" + major + "'"));
  assert.ok(ci.includes("node-version-file: '.nvmrc'"));
  assert.ok(spec.includes('BUILD_NODE_MAJOR="$(cat .nvmrc)"'));
  assert.ok(spec.includes('nvm use "$BUILD_NODE_MAJOR"'));
  assert.ok(spec.includes("!== process.env.BUILD_NODE_MAJOR"));
  assert.ok(spec.includes('npm install --global "npm@$PINNED_NPM"'));
  assert.ok(spec.includes('test "$(npm --version)" = "$PINNED_NPM"'));
  assert.ok(spec.includes('npm ci --cache .npm'));
  assert.ok(spec.indexOf('BUILD_BOOTSTRAP_DIAGNOSTICS=') < spec.indexOf('nvm install --skip-default-packages'));
  assert.ok(spec.includes('$BUILD_BOOTSTRAP_DIAGNOSTICS/node-failure.log'));
  assert.ok(spec.includes('$BUILD_BOOTSTRAP_DIAGNOSTICS/npm-failure.log'));
  assert.ok(spec.includes('scripts/require_release_ci.py --commit "$AWS_COMMIT_ID"'));
  assert.ok(spec.includes('scripts/verify_public_bundle_secrets.py'));
});
