/**
 * Offline, fail-closed UI regression gate. Runs after npm ci and before tsc.
 * No network, credentials, browser session, payment or WhatsApp side effects.
 * Checks literal relative imports on live entrypoints; tsc remains authoritative.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const ROOT = path.resolve(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const watched = [
  'src/pages/_app.tsx',
  'src/pages/orders.tsx',
  'src/components/orders/OrdersPage.tsx',
  'src/pages/checkout/index.tsx',
  'src/pages/checkout/status.tsx',
  'src/pages/workspace/payments/index.tsx',
  'src/pages/workspace/service/index.tsx',
  'src/pages/workspace/content/index.tsx',
  'src/components/get/GetPage.tsx',
  'src/components/workspace/commerce/Orders.tsx',
  'src/components/workspace/whatsapp/groups.tsx',
  'src/components/workspace/whatsapp/calling.tsx',
];
const extensions = ['', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.json', '.css', '.scss', '.svg'];

function existsModule(from, specifier) {
  const base = path.resolve(path.dirname(path.join(ROOT, from)), specifier.split(/[?#]/, 1)[0]);
  const names = extensions.flatMap(ext => [base + ext, path.join(base, 'index' + ext)]);
  // TypeScript understands explicit .js imports that point to .ts files.
  if (/\.[mc]?jsx?$/.test(base)) names.push(base.replace(/\.[mc]?jsx?$/, '.ts'), base.replace(/\.[mc]?jsx?$/, '.tsx'));
  return names.some(file => fs.existsSync(file) && fs.statSync(file).isFile());
}

function collectLocalImports(file) {
  // Handles static from imports, bare imports and literal dynamic import(...).
  // TypeScript's full compiler check (run immediately afterward) catches the rest.
  const source = read(file);
  const pattern = /\b(?:from\s*|import\s*\(\s*|require\s*\(\s*|import\s+)(['"])(\.[^'"]+)\1/g;
  return Array.from(source.matchAll(pattern), match => match[2]);
}

for (const file of watched) {
  assert.ok(fs.existsSync(path.join(ROOT, file)), 'Missing protected UI entrypoint: ' + file);
  for (const spec of collectLocalImports(file)) {
    assert.ok(existsModule(file, spec), 'Deleted or unresolved module: ' + file + ' imports ' + spec);
  }
}

const orders = read('src/components/orders/OrdersPage.tsx');
const tokens = read('src/styles/tokens.css');
const css = read('src/styles/inner-ux.css');
const app = read('src/pages/_app.tsx');
const publicAdapter = read('src/components/public/PublicToastProvider.tsx');
const workspaceAdapter = read('src/contexts/ToastContext.tsx');
const provider = read('src/contexts/ActionNotificationProvider.tsx');
const copyHook = read('src/hooks/useActionCopy.ts');
const staffOrders = read('src/components/workspace/commerce/Orders.tsx');
for (const route of [
  'src/components/workspace/commerce/Orders.tsx',
  'src/components/workspace/whatsapp/groups.tsx',
  'src/components/workspace/whatsapp/calling.tsx',
]) {
  const source = read(route);
  assert.match(source, /useActionCopy/, 'Staff Copy must use verified clipboard handler: ' + route);
  assert.doesNotMatch(source, /navigator\.clipboard\.writeText/, 'No fire-and-forget clipboard: ' + route);
}
assert.match(staffOrders, /event\.stopPropagation\(\)/, 'Staff ID Copy must not open its parent order row');
assert.match(staffOrders, /aria-label=\{ `Copy full order ID/, 'Staff ID Copy must have an accessible name');

for (const [name, pattern] of Object.entries({
  'Orders 12px Copy gap': /\.ord-id-line\{[^}]*gap:12px/,
  'Orders 44px Copy target': /\.ord-copy\{[^}]*inline-size:44px;min-inline-size:44px/,
  'Orders 44px invoice target': /\.ord-account-action,\.ord-copy,\.ord-inv\{[^}]*block-size:44px/,
  'Orders mobile Invoice alignment': /\.ord-invoice-cell\{vertical-align:top\}/,
  'Orders named Copy action': /aria-label=\{[^}]*Copy order ID/,
  'Orders focusable Copy button': /type="button"\s+className="ord-copy"/,
  'Orders keyboard fallback': /selectText\( document\.getElementById/,
  'Orders stale clipboard suppression': /requestId !== copyRequestId\.current/,
})) {
  assert.match(orders, pattern, 'Missing contract: ' + name);
}
for (const [name, token, expected] of [
  ['toast type size', '--wc-toast-type-size', '16px'],
  ['toast max width', '--wc-toast-max-width', '360px'],
  ['toast padding', '--wc-toast-padding', '12px 16px'],
  ['toast mobile type size', '--wc-toast-mobile-type-size', '16px'],
  ['toast mobile padding', '--wc-toast-mobile-padding', '12px 16px'],
]) {
  assert.ok(tokens.includes(token + ': ' + expected + ';'), 'Changed ' + name + ': expected ' + expected);
}
assert.match(css, /\.wc-action-toast-host\s*\{[\s\S]*?right: max\(/, 'Toast must align with the content gutter');
assert.match(css, /\.wc-action-toast\s*\{[\s\S]*?max-width: min\(var\(--wc-toast-max-width\)/, 'Missing shared toast width');
assert.equal((app.match(/<PublicToastProvider>/g) || []).length, 1, 'Expected exactly one public provider');
assert.equal((app.match(/<ToastProvider>/g) || []).length, 1, 'Expected exactly one Workspace provider');
assert.equal((provider.match(/data-wc-unified-action-notice-host="true"/g) || []).length, 1, 'Expected one toast host');
assert.match(publicAdapter, /String\(kind\) === 'whatsappFailed'/, 'Unconfirmed WhatsApp must never show a floating toast');
assert.match(workspaceAdapter, /actions\.show\(type, message\)/, 'Workspace must use shared validated host');
assert.match(copyHook, /await navigator\.clipboard\.writeText\(value\)/, 'Copy success must await the clipboard');
assert.match(provider, /const duration = \(type === 'error' \|\| type === 'warning'\) \? 0/, 'Errors and warnings must be persistent');

// Node 24 strips types from pure .ts modules without TypeScript 7's removed JS
// compiler API. Execute the actual policy, not a duplicated approximation.
async function checkRuntimePolicy() {
  const url = pathToFileURL(path.join(ROOT, 'src/lib/publicActionNotices.ts')).href;
  const publicNotices = await import(url);
  const copy = {
    processing: 'Processing…',
    success: 'Done.',
    failure: "Couldn't complete. Try again.",
    blocked: 'This action is unavailable right now.',
    whatsappAccepted: 'Sent to WhatsApp.',
    whatsappFailed: "Couldn't confirm. Check WhatsApp.",
  };
  for (const [key, expected] of Object.entries(copy)) {
    assert.equal(publicNotices.publicActionText(key), expected, 'Public notice changed: ' + key);
  }
  assert.equal(Object.keys(publicNotices.PUBLIC_ACTION_TEXT).length, 6, 'Exactly six canonical public notices');
  for (const status of [403, 404, 409, 423, 429, 501, 503]) assert.equal(publicNotices.publicApiFailureKind(status), 'blocked');
  for (const status of [400, 401, 500, undefined]) assert.equal(publicNotices.publicApiFailureKind(status), 'failure');

  const normalize = publicNotices.normalizeActionNotification;
  assert.equal(normalize('  Ready  ', 'success'), 'Ready');
  assert.equal(normalize(undefined, 'success'), null, 'Undefined may not report success');
  assert.equal(normalize({}, 'success'), null, 'Objects may not report success');
  assert.equal(normalize('undefined', 'error'), copy.failure);
  assert.equal(normalize('  ', 'warning'), copy.blocked);
  assert.equal(normalize('<html>error</html>', 'error'), copy.failure);
  assert.equal(normalize('Bearer abcdefghijklmnop', 'error'), copy.failure);
  assert.equal(normalize('a'.repeat(321), 'error'), copy.failure);
  assert.equal(normalize('Saved changes', 'success'), 'Saved changes');
}
checkRuntimePolicy().then(() => {
  console.log('Action UI gate passed: imports, Orders/Workspace Copy, toast design, approved vocabulary and safety normalization.');
}).catch(error => { console.error(error); process.exitCode = 1; });
