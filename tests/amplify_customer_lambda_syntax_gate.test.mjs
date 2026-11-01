/**
 * Protect the static frontend release gate from masking invalid customer
 * Lambda Python sources. No AWS calls, messages or payments.
 * Run: node --test tests/amplify_customer_lambda_syntax_gate.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

test('Amplify checks customer-facing Lambda Python syntax before npm/build', () => {
  const pipeline = readFileSync(resolve(root, 'amplify.yml'), 'utf8');
  const start = pipeline.indexOf('        - python3 -m compileall -q ');
  const install = pipeline.indexOf('        - npm ci --cache ');
  assert.ok(start >= 0, 'expected standard-library syntax compilation');
  assert.ok(install > start, 'catch invalid Lambda syntax before dependency install');
  const line = pipeline.slice(start, pipeline.indexOf('\n', start));
  for (const path of [
    'amplify/functions/auth/customer-profile',
    'amplify/functions/messaging/whatsapp-business-api',
    'amplify/functions/messaging/inbound-whatsapp-handler',
    'amplify/functions/core/secure-files',
    'amplify/functions/shared/lambda_utils',
  ]) assert.ok(line.includes(path), 'missing syntax check for ' + path);
  assert.doesNotMatch(line, /deploy|publish|update-function|start-build|invoke/i);
});

test('Release gate keeps backend deployment separate from static frontend', () => {
  const pipeline = readFileSync(resolve(root, 'amplify.yml'), 'utf8');
  assert.ok(pipeline.includes('No `backend:` phase.'));
  assert.ok(pipeline.includes('backend artifacts.'));
});
