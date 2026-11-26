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

test('legal heading numbers have a real separator and aligned upright title columns', () => {
  const source = readFileSync(new URL('../src/components/LegalDocument.tsx', import.meta.url), 'utf8');
  for (const tag of ['h2', 'h3']) {
    assert.ok(source.includes('<' + tag + ' className="lgd-' + tag + '"><span className="lgd-num">{ section.number }</span>{ \' \' }<span className="lgd-heading-text">{ section.heading }</span></' + tag + '>'));
  }
  assert.match(source, /\.lgd-h2,\.lgd-h3\{\s*display:grid;grid-template-columns:3\.5rem minmax\(0,1fr\);\s*column-gap:12px;align-items:baseline;text-align:start;font-style:normal;/);
  assert.ok(source.includes('grid-template-columns:3rem minmax(0,1fr);column-gap:8px'));
});
