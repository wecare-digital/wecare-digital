/**
 * Orders Copy must be a visible, usable public action on every supported
 * customer browser. Source contract only: no customer tokens, orders, sends,
 * clipboard permissions or payments are accessed.
 *
 * Run: node --test tests/orders_copy_action_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const orders = readFileSync(resolve(root, 'src/components/orders/OrdersPage.tsx'), 'utf8');

test('every real order ID renders an identifiable Copy action beside the reference', () => {
  assert.match(orders, /<span className="ord-id-line">/);
  assert.match(orders, /<span className="ord-ordno" id=\{ `ord-id-\$\{ index \}` \}/);
  assert.match(orders, /\{ copyValue && \(/);
  assert.match(orders, /className="ord-copy"/);
  assert.match(orders, /aria-label=\{ `Copy order ID \$\{ copyValue \}` \}/);
  assert.match(orders, /<span className="ord-copy-label">Copy<\/span>/);
  assert.match(orders, /onClick=\{ \(\) => copyId\( copyValue, index \) \}/);
  assert.doesNotMatch(orders, /canCopy|setCanCopy/);
});

test('Clipboard API success has one approved toast; unavailable or denied clipboard has a usable fallback', () => {
  assert.match(orders, /if \( !navigator\.clipboard\?\.writeText \) throw new Error/);
  assert.match(orders, /await navigator\.clipboard\.writeText\( value \)/);
  assert.match(orders, /showToast\( 'success', \{ durationMs: 2500 \} \)/);
  assert.match(orders, /const selected = selectText\( document\.getElementById\( `ord-id-\$\{ index \}` \) \)/);
  assert.match(orders, /message: selected \? 'Selected\. Copy with keyboard\.' : publicActionText\( 'failure' \)/);
  assert.match(orders, /function selectText \( el: HTMLElement \| null \): boolean/);
  assert.match(orders, /return selection\.toString\(\)\.trim\(\) === el\.textContent\.trim\(\)/);
  assert.doesNotMatch(orders, /execCommand\(\s*['"]copy['"]/);
});

test('Copy stays inline and remains a keyboard-focusable touch target on mobile', () => {
  assert.match(orders, /\.ord-id-line\{display:inline-flex;align-items:center;gap:12px;white-space:nowrap\}/);
  assert.match(orders, /\.ord-copy\{\s*flex:none;align-self:center;inline-size:auto;min-inline-size:44px;\s*padding-inline:10px;gap:5px;/);
  assert.match(orders, /\.ord-copy-label\{/);
  assert.match(orders, /\.ord-account-action,\.ord-copy,\.ord-inv\{[\s\S]*?block-size:44px;/);
  assert.match(orders, /\.ord-copy:focus-visible/);
  assert.match(orders, /\.ord-tablewrap\{overflow-x:auto;/);
  assert.match(orders, /\.ord-table\{\s*min-inline-size:600px;/);
  assert.match(orders, /@media\(max-width:767px\)\{[\s\S]*?\.ord-table\{min-inline-size:480px\}/);
});

test('Copy does not mutate order data, issue payments or add a second transient notice', () => {
  const start = orders.indexOf('  const copyId = async ( value: string, index: number ) => {');
  // Bound this check by the next named handler, not by the first indented
  // closing brace (which could belong to a nested arrow function).
  const end = orders.indexOf('\n  const dismissAlertFor =', start);
  assert.ok(start > 0 && end > start, 'copyId must end before dismissAlertFor');
  const body = orders.slice(start, end);
  assert.match(body, /\n  };\s*\/\*\*/, 'copyId must close before the next handler');
  assert.doesNotMatch(body, /fetch\(|window\.location|sendCustomerMenuAction|downloadInvoice/);
  assert.equal((body.match(/showToast\(/g) || []).length, 1);
  assert.match(body, /setOrdersAlert\(/);
  assert.match(orders, /const copyValue = order\.orderNumber \|\| order\.referenceId \|\| ''/);
  assert.doesNotMatch(orders, /const copyValue = .*\|\| date/);
});
