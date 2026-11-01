/**
 * Source-only assertions for the 50 remaining public status positions.
 * No WhatsApp sends, provider requests, payment writes or browser access.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = rel => readFileSync(resolve(ROOT, rel), 'utf8');

test('the remaining public audit checklist accounts for 50 display positions', () => {
  const catalog = read('docs/operations/public-notification-short-copy-50-20261101.md');
  const rows = catalog.split('\n').filter(line => /^\| \d+ \| \[/.test(line));
  assert.equal(rows.length, 50, 'do not mistake notification render sites for unique strings');
  assert.match(catalog, /render positions, not 50 different message strings/);
  assert.match(catalog, /Do not pay again/);
});

test('checkout quote notices remain specific and never hide disabled payment', () => {
  const cart = read('src/components/cart/CartPage.tsx');
  assert.match(cart, /Checking prices…/);
  assert.match(cart, /Sign in to view final price\./);
  assert.match(cart, /Verified price unavailable\. Payment disabled\./);
  assert.match(cart, /quoteNotice\.startsWith\( 'Sign in' \)/);
  assert.match(cart, /data-wc-basket-claim="true"/);
});

test('Vault uses concise recovery copy without concealing payment uncertainty', () => {
  const vault = read('src/components/get/GetPage.tsx');
  assert.match(vault, /Payment recorded\. Confirming access\. Do not pay again\./);
  assert.match(vault, /Payment verified\. 24-hour access starts on delivery or first download\./);
  assert.match(vault, /Review & Pay sent to WhatsApp\. Check status before retrying\./);
  assert.match(vault, /fileStatusLabel\( state \)/);
  assert.match(vault, /file\.accessWindowEndsAt/);
});

test('live VayuLok retains AQI, search and route semantics', () => {
  const live = read('src/components/VayuLokLive.tsx');
  assert.match(live, /Air forecast unavailable\./);
  assert.match(live, /No air forecast for this place\./);
  assert.match(live, /Currency unavailable\./);
  assert.match(live, /Route unavailable\./);
  assert.match(live, /AQI \$\{Math\.round\( inspected\.aqi \)\}/);
  assert.match(live, /role="status"/);
  assert.doesNotMatch(live, /<PublicNotice mode="toast"/);
});

test('checkout receipt preserves distinct paid, confirming and failure states', () => {
  const status = read('src/pages/checkout/status.tsx');
  assert.match(status, /confirming: \{ title: 'Confirming payment…' \}/);
  assert.match(status, /paid: \{ title: 'Payment received' \}/);
  assert.match(status, /finalizing: \{ title: 'Payment received' \}/);
  assert.match(status, /failed: \{ title: 'Payment incomplete' \}/);
  assert.match(status, /unavailable: \{ title: 'Status unavailable' \}/);
  assert.match(status, /Do not pay again\./);
});

test('translation and search keep concise accessible updates', () => {
  const support = read('src/components/SupportWidget.tsx');
  const header = read('src/components/Header.tsx');
  const menu = read('src/components/orders/OrderActionsMenu.tsx');
  assert.match(support, /English restored\./);
  assert.match(support, /Translation unavailable\./);
  assert.match(header, /role="status" aria-live="polite"/);
  assert.match(menu, /No matching actions\./);
});
