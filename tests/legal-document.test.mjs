import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

test('Terms and Privacy retain complete numbered clauses and valid anchors', () => {
  const audit = fileURLToPath(new URL('../tools/audit/legalcheck.js', import.meta.url));
  const output = execFileSync(process.execPath, [audit], { encoding: 'utf8' });
  assert.match(output, /\d+\/\d+ passed/);
});

test('shared legal summary notice applies to Terms and Privacy without calling both an agreement', () => {
  const source = readFileSync(new URL('../src/components/LegalDocument.tsx', import.meta.url), 'utf8');
  assert.ok(source.includes('If a summary differs from the numbered text, the numbered text applies,'));
  assert.ok(!source.includes('They are not part of the agreement and do not change it.'));
});
