import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

// Only the executable `- ...` command lines of amplify.yml, never its comments.
const amplifyCommands = () =>
  read('amplify.yml')
    .split('\n')
    .filter(line => /^\s*- /.test(line))
    .join('\n');

test('Amplify and GitHub CI select the same Node major', () => {
  const major = read('.nvmrc').trim();
  const registry = read('packages/config/vendorVersions.ts');
  const ci = read('.github/workflows/ci.yml');
  const commands = amplifyCommands();
  assert.match(major, /^\d+$/);
  assert.match(registry, new RegExp("name: 'Node\\.js',\\s*configured: '" + major + "'"));
  assert.ok(ci.includes("node-version-file: '.nvmrc'"));

  // Amplify does not read .nvmrc by itself, so the bootstrap reads it, installs and selects that
  // major, and fails unless the running Node has exactly that major.
  assert.ok(commands.includes('export BUILD_NODE_MAJOR="$(cat .nvmrc)"'));
  assert.ok(commands.includes('nvm install --skip-default-packages "$BUILD_NODE_MAJOR"'));
  assert.ok(commands.includes('nvm use "$BUILD_NODE_MAJOR"'));
  assert.ok(commands.includes('!== process.env.BUILD_NODE_MAJOR'));
  // A hard-coded major next to it would let amplify.yml and .nvmrc drift apart again.
  for (const pinned of [/nvm install --skip-default-packages \d/, /nvm use \d/, /if \(m < \d+\)/]) {
    assert.doesNotMatch(commands, pinned, 'amplify.yml must take the Node major from .nvmrc');
  }
});

test('Amplify build does not install OS packages', () => {
  // The Amplify build user is not root: `dnf install libatomic` failed jobs 784 and 786
  // ("This command has to be run with superuser privileges"). Node 26 needs that library,
  // so it cannot be fixed from amplify.yml on this image.
  assert.doesNotMatch(amplifyCommands(), /\b(?:dnf|yum|apt-get|apt|apk)\b[^\n]*\binstall\b/);
});

test('Amplify keeps the exact npm pin and the production release gates', () => {
  const commands = amplifyCommands();
  assert.ok(commands.includes('npm install --global "npm@$PINNED_NPM"'));
  assert.ok(commands.includes('test "$(npm --version)" = "$PINNED_NPM"'));
  assert.ok(commands.indexOf('npm install --global "npm@$PINNED_NPM"') < commands.indexOf('npm ci --cache .npm'));
  assert.ok(commands.includes('scripts/require_release_ci.py --commit "$AWS_COMMIT_ID"'));
  assert.ok(commands.includes('scripts/verify_public_bundle_secrets.py'));
});

test('Amplify stores early Node and npm bootstrap failures in the private diagnostics bucket', () => {
  const commands = amplifyCommands();
  const destination = commands.indexOf('export BUILD_BOOTSTRAP_DIAGNOSTICS=');
  assert.ok(destination >= 0, 'BUILD_BOOTSTRAP_DIAGNOSTICS must be defined');
  assert.ok(
    destination < commands.indexOf('nvm install --skip-default-packages'),
    'the diagnostics destination must exist before Node setup can fail',
  );
  assert.ok(commands.includes('"$BUILD_BOOTSTRAP_DIAGNOSTICS/node-failure.log"'));
  assert.ok(commands.includes('"$BUILD_BOOTSTRAP_DIAGNOSTICS/npm-failure.log"'));
});
