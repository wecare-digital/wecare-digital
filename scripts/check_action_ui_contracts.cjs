/**
 * Offline, fail-closed UI regression gate. Runs after npm ci and before tsc.
 * No network, credentials, browser session, payment or WhatsApp side effects.
 * esbuild transpilation checks real runtime imports (including dynamic imports),
 * and tsc validates type-only imports later in this pipeline.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
// TypeScript 7 no longer provides the old ScriptTarget/transpileModule JS API.
// esbuild is already a direct, locked devDependency and supports TS + TSX here.
const esbuild = require('esbuild');

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
  // Transform only: this never executes the page. esbuild removes comments,
  // rewrites static imports/exports and dynamic import() as CJS require calls.
  // It is intentionally fail-closed if the TS/TSX source cannot be transformed.
  const code = esbuild.transformSync(read(file), {
    loader: file.endsWith('.tsx') ? 'tsx' : 'ts',
    format: 'cjs',
    target: 'es2022',
    legalComments: 'none',
  }).code;
  return [...code.matchAll(/\brequire\(\s*["']([^"']+)["']\s*\)/g)]
    .map(match => match[1])
    .filter(spec => spec.startsWith('.'));
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

// Execute the ACTUAL shipped TypeScript policies in isolation. Not a duplicate
// hand-written approximation; this catches unsafe text and vocabulary drift.
function loadTypeScript(file, mockRequire) {
  const output = esbuild.transformSync(read(file), {
    loader: file.endsWith('.tsx') ? 'tsx' : 'ts',
    format: 'cjs',
    target: 'es2022',
    jsx: 'automatic',
  }).code;
  const module = { exports: {} };
  const sandbox = { module, exports: module.exports, require: mockRequire };
  vm.runInNewContext(output, sandbox, { timeout: 4000, filename: file });
  return module.exports;
}
const publicNotices = loadTypeScript('src/lib/publicActionNotices.ts', name => { throw Error('Unexpected public notice import: ' + name); });
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

const react = { createContext: () => ({}), useCallback: fn => fn, useMemo: fn => fn(), useContext: () => null };
const notifications = loadTypeScript('src/contexts/ActionNotificationProvider.tsx', name => {
  if (name === 'react') return react;
  if (name === 'next/router') return { useRouter: () => ({}) };
  if (name === 'react/jsx-runtime') return { jsx() {}, jsxs() {} };
  if (name === '../lib/publicActionNotices') return publicNotices;
  throw Error('Unexpected action notification import: ' + name);
});
const normalize = notifications.normalizeActionNotification;
assert.equal(normalize('  Ready  ', 'success'), 'Ready');
assert.equal(normalize(undefined, 'success'), null, 'Undefined may not report success');
assert.equal(normalize({}, 'success'), null, 'Objects may not report success');
assert.equal(normalize('undefined', 'error'), copy.failure);
assert.equal(normalize('  ', 'warning'), copy.blocked);
assert.equal(normalize('<html>error</html>', 'error'), copy.failure);
assert.equal(normalize('Bearer abcdefghijklmnop', 'error'), copy.failure);
assert.equal(normalize('a'.repeat(321), 'error'), copy.failure);
assert.equal(normalize('Saved changes', 'success'), 'Saved changes');

console.log('Action UI gate passed: imports, Orders targets, toast design, exact public vocabulary, safety normalization.');
