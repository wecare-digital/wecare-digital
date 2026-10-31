/**
 * Contract for the customer Orders history layout on desktop and mobile.
 *
 * Static source test: the 1100px history card must be centered inside the
 * wider hero measure, while narrow screens keep table scrolling INSIDE the
 * card instead of overflowing the document.
 *
 * Run: node --test tests/orders_centered_history_layout.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = readFileSync(resolve(ROOT, 'src/components/orders/OrdersPage.tsx'), 'utf8');

test('Orders card centered in the responsive hero content area', () => {
  assert.match(source, /className="ord-page"/);
  const rule = source.match(/\.ord-page\s*\{\s*color-scheme:light;([^}]*)\}/);
  assert.ok(rule, 'the primary Orders layout rule must exist');
  assert.match(rule[1], /inline-size:\s*100%\s*;/);
  assert.match(rule[1], /max-inline-size:\s*1100px\s*;/);
  assert.match(rule[1], /min-inline-size:\s*0\s*;/);
  assert.match(rule[1], /margin-inline:\s*auto\s*;/);
});

test('mobile table stays inside a horizontally scrollable card', () => {
  assert.match(source, /className="ord-tablewrap"/);
  assert.match(source, /\.ord-tablewrap\s*\{[^}]*overflow-x:auto/);
  assert.match(source, /@media\(max-width:767px\)\s*\{[\s\S]*?\.ord-table\s*\{min-inline-size:480px\}/);
  assert.match(source, /\.ord-list\s*\{\s*width:100%/);
});

test('desktop table remains full width with the existing columns', () => {
  assert.match(source, /\.ord-table\s*\{\s*width:100%;border-collapse:collapse/);
  assert.match(source, /\.ord-table\s*\{\s*min-inline-size:600px/);
  assert.match(source, /<table className="ord-table">/);
});
