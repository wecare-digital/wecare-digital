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

  // Amplify does not read .nvmrc, so every Node major it names must equal it.
  const pins = [
    ...commands.matchAll(/nvm install --skip-default-packages (\d+)/g),
    ...commands.matchAll(/nvm use (\d+)/g),
    ...commands.matchAll(/if \(m < (\d+)\)/g),
  ].map(match => match[1]);
  assert.equal(pins.length, 3, 'expected nvm install, nvm use and the Node major floor');
  assert.deepEqual([...new Set(pins)], [major], 'amplify.yml Node major must equal .nvmrc');
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
