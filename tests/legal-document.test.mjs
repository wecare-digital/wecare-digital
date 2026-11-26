import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { transformSync } from 'esbuild';

test('Terms and Privacy retain complete numbered clauses and valid anchors', () => {
  const audit = fileURLToPath(new URL('../tools/audit/legalcheck.js', import.meta.url));
  const output = execFileSync(process.execPath, [audit], { encoding: 'utf8' });
  assert.match(output, /\d+\/\d+ passed/);
});

test('legal pages render numbered provisions without editorial summaries or drafting notices', () => {
  const source = readFileSync(new URL('../src/components/LegalDocument.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /inShort|lgd-short|lgd-disclaimer|numbered text applies|In short/);
  assert.ok(source.includes('...section.paragraphs'));
  for (const document of ['terms', 'privacy']) {
    const content = readFileSync(new URL('../src/content/legal/' + document + '.ts', import.meta.url), 'utf8');
    assert.doesNotMatch(content, /\binShort\s*:/);
  }
});

test('legal page policy details describe actual transaction terms and privacy practices', async () => {
  const source = readFileSync(new URL('../src/content/publicPolicyDetails.ts', import.meta.url), 'utf8');
  const { code } = transformSync(source, { loader: 'ts', format: 'esm' });
  const { publicPolicyDetailsForRoute } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
  const terms = publicPolicyDetailsForRoute('/terms');
  const privacy = publicPolicyDetailsForRoute('/privacy');
  for (const policy of [terms, privacy]) {
    assert.deepEqual(Object.keys(policy).sort(), ['disclaimer', 'refunds', 'returns', 'shipping']);
    for (const value of Object.values(policy)) {
      assert.ok(value.trim());
      assert.doesNotMatch(value, /above controls|no fulfilment applies to this page|nothing on this page is returnable|no payment is taken here/i);
    }
  }
  assert.match(terms.refunds, /store credit valid for 30 calendar days/);
  assert.match(terms.refunds, /Monetary refunds are provided where required by law/);
  assert.match(terms.returns, /Statutory remedies/);
  assert.match(privacy.shipping, /delivery details/);
  assert.match(privacy.refunds, /Payment providers/);
  assert.match(privacy.disclaimer, /one@wecare\.digital/);
});

test('legal heading numbers have a real separator and aligned upright title columns', () => {
  const source = readFileSync(new URL('../src/components/LegalDocument.tsx', import.meta.url), 'utf8');
  for (const tag of ['h2', 'h3']) {
    assert.ok(source.includes('<' + tag + ' className="lgd-' + tag + '"><span className="lgd-num">{ section.number }</span>{ \' \' }<span className="lgd-heading-text">{ section.heading }</span></' + tag + '>'));
  }
  assert.match(source, /\.lgd-h2,\.lgd-h3\{\s*display:grid;grid-template-columns:3\.5rem minmax\(0,1fr\);\s*column-gap:12px;align-items:baseline;text-align:start;font-style:normal;/);
  assert.ok(source.includes('grid-template-columns:3rem minmax(0,1fr);column-gap:8px'));
});

test('legal provisions retain statutory safeguards and clear automated processing disclosure', () => {
  const terms = readFileSync(new URL('../src/content/legal/terms.ts', import.meta.url), 'utf8');
  const privacy = readFileSync(new URL('../src/content/legal/privacy.ts', import.meta.url), 'utf8');
  for (const source of [terms, privacy]) {
    assert.doesNotMatch(source, /Super Intelligence|intelligence-enabled|intelligence-assisted|INR 0|numbered text applies/i);
    assert.match(source, /including artificial intelligence/);
    assert.match(source, /one@wecare\.digital/);
  }
  assert.match(terms, /within 48 hours of receipt/);
  assert.match(terms, /within one month of receipt/);
  assert.match(terms, /within a reasonable period/);
  assert.match(terms, /delivery after the stated schedule/);
  assert.match(terms, /mandatory consumer and product liability/);
  assert.match(privacy, /within one month of receipt/);
  assert.match(privacy, /under 18 years of age/);
  assert.match(privacy, /death or incapacity/);
  assert.match(privacy, /withdraw consent/);
});
