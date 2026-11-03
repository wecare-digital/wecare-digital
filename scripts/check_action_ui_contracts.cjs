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
// Source-read dependencies are operational consumers too. Inspect the scripts
// invoked by the production pipeline, so an unmounted component cannot be
// deleted while a release gate still reads it.
const packageScripts = Object.values(JSON.parse(read('package.json')).scripts).join('\n');
const amplifyCommands = read('amplify.yml').split('\n')
  .filter(line => !/^\s*#/.test(line)).join('\n');
const productionScripts = new Set(
  [...(packageScripts + '\n' + amplifyCommands).matchAll(/\bnode\s+(scripts\/[A-Za-z0-9_./-]+\.(?:cjs|mjs|js))\b/g)]
    .map(match => match[1])
);
for (const script of productionScripts) {
  const compiled = esbuild.transformSync(read(script), {
    loader: 'js', format: 'cjs', target: 'es2022', legalComments: 'none',
  }).code;
  for (const match of compiled.matchAll(/\bread\(\s*(['"])(src\/[^'"]+)\1\s*\)/g)) {
    assert.ok(fs.existsSync(path.join(ROOT, match[2])),
      'Deleted production gate dependency: ' + script + ' reads ' + match[2]);
  }
}

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
  'src/components/public/CustomerVaultChrome.tsx',
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
const staffOrders = read('src/components/workspace/commerce/Orders.tsx');
for (const route of [
  'src/components/workspace/commerce/Orders.tsx',
  'src/components/workspace/whatsapp/groups.tsx',
  'src/components/workspace/whatsapp/calling.tsx',
]) {
  const source = read(route);
  assert.match(source, /useActionCopy/, 'Staff Copy must await the validated clipboard helper: ' + route);
  assert.doesNotMatch(source, /navigator\.clipboard\.writeText/, 'Forbidden fire-and-forget Copy: ' + route);
}
assert.match(staffOrders, /event\.stopPropagation\(\)/, 'Copy must not navigate to an order detail');
assert.match(staffOrders, /aria-label=\{ `Copy full order ID/, 'Staff Copy must be keyboard accessible');

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

// /vault/?file=<id> is an exact-file private flow, not a public toast surface.
// _app must render this route BEFORE its global PublicToastProvider mount.
// Vault retains persistent inline payment, download and access guidance.
const vaultRoute = read('src/pages/vault.tsx');
const vaultPage = read('src/components/get/GetPage.tsx');
const vaultEarlyExit = app.match(
  /if\s*\(\s*router\.pathname === '\/404' \|\| router\.pathname === '\/vault'\s*\)[\s\S]*?\n  \}/
);
assert.ok(vaultEarlyExit, 'Vault must bypass the global public toast provider');
assert.ok(app.indexOf(vaultEarlyExit[0]) < app.indexOf('<PublicToastProvider>'),
  'Vault no-toast branch must be evaluated before the public toast mount');
assert.match(vaultEarlyExit[0],
  /return\s*\(\s*<ErrorBoundary>\s*<Component\s*\{\s*\.\.\.pageProps\s*\}\s*\/>\s*<\/ErrorBoundary>\s*\)/,
  'Vault must mount directly without any toast-provider wrapper');
assert.doesNotMatch(vaultEarlyExit[0],
  /<(?:PublicToastProvider|ToastProvider|ActionNotificationProvider)\b/,
  'Vault route must not mount a floating notification provider');
assert.match(vaultRoute, /fileParam\s*=\s*router\.query\.file/,
  'The exact-file Vault route must keep the file query parameter');
assert.match(vaultRoute, /return\s*<GetPage\s+targetFileId=\{\s*targetFileId\s*\}\s*\/>/,
  'Vault must continue rendering the owner-scoped file page');
assert.doesNotMatch(vaultPage,
  /\b(?:usePublicToast|useActionNotification|showToast|PublicToastProvider|ActionNotificationProvider|wc-action-toast)\b|<PublicNotice\b[^>]*\bmode=["']toast["']/,
  'No floating toast calls or toast-mode notices are allowed on the Vault page');
assert.match(vaultPage, /<PublicNotice\s+mode="inline"\s+tone="error"/,
  'Vault must retain visible inline payment and download failure guidance');

// Vault hero rotates like Home. Only its keywords change; retain the fixed
// explanation and card heading without repeating a second security subtitle.
const vaultKeywords = vaultPage.match(/const GET_WORDS: CycleWord\[\] = \[([\s\S]*?)\n\];/);
assert.ok(vaultKeywords, 'Vault must retain the shared hero word list');
for (const word of ['document', 'file', 'download', 'access']) {
  assert.match(vaultKeywords[1], new RegExp("word:\\s*'" + word + "'"),
    'Missing rotating Vault hero keyword: ' + word);
}
assert.match(vaultPage, /sub="Check the status and choose your next step\."/,
  'Vault subtitle must explain the task without repeating the file heading');
assert.match(vaultPage, /<p className="sf-card-kicker">PRIVATE VAULT<\/p>/,
  'Vault card label must remain unchanged');
assert.match(vaultPage, /<h2 className="sf-card-title">Shared with you<\/h2>/,
  'Vault card heading must use the approved customer wording');
assert.doesNotMatch(vaultPage, /Protected by your verified account\./,
  'Remove the redundant Vault card security subtitle');

assert.match(vaultPage, /case 'UNPAID': return 'Payment required';/,
  'Unpaid customer file must identify payment required rather than a blocked action');
assert.match(vaultPage, /case 'READY': return 'Payment verified';/,
  'Verified payment must remain distinct from an unverified payment');
assert.match(vaultPage, /case 'PAID_UNVERIFIED': return 'Confirming paid access';/,
  'Payment-recorded files must not claim download authorization before verification');
assert.match(vaultPage, /Your 24-hour access begins with your first download\./,
  'Paid access must explain that its clock starts with the first download');
assert.match(vaultPage, /Payment recorded\. Confirming access\. No additional payment is needed\./,
  'Pending access must never invite double payment');
assert.match(vaultPage, /<h3 className="sf-file-name">\{ file\.displayName \}<\/h3>/,
  'Vault must preserve the existing file-name display per customer request');
assert.match(vaultPage, /box-sizing:border-box;margin-top:-16px;/,
  'Vault card alone should have the approved slightly reduced hero spacing');
assert.match(vaultPage, /\.sf-card\{padding:28px 20px max\(30px,env\(safe-area-inset-bottom\)\);border-radius:20px;margin-top:-8px\}/,
  'Vault must reduce the mobile gap without changing shared hero styles');


// The fresh /ws Collect screen must use the same GSTIN-from-saved-customer
// contract as the established Workspace Collect flow. No second input, and no
// obsolete four-argument serializer call that fails TypeScript and production.
const wsCollectCreate = read('src/components/ws/collect/CollectCreatePanel.tsx');
assert.match(wsCollectCreate, /collectDraft\(\s*customer,\s*lines,\s*express\s*\)/,
  'New WS Collect must use the current three-argument invoice draft serializer');
assert.doesNotMatch(wsCollectCreate, /setGstin|cc-gstin|Customer GST number \(GSTIN\)/,
  'New WS Collect must not restore the retired editable buyer GSTIN field');

// The exact-file Vault alone renders shared public chrome after the owner-scoped
// fetch settles. Preserve the silent redirect and no-floating-toast contracts.
const vaultChrome = read('src/components/public/CustomerVaultChrome.tsx');
assert.match(vaultPage, /if \( stage === 'loading' && !error \) return null;/,
  'Vault must remain blank during owner verification and redirects');
assert.match(vaultPage, /<CustomerVaultChrome>[\s\S]*<RotatingHero/,
  'Vault customer UI must reuse the isolated shared chrome');
assert.match(vaultPage, /data-wc-no-translate="true"/,
  'Private file details must be excluded from automatic translation requests');
for (const component of ['Header', 'PublicPolicyDetails', 'PublicShare', 'Footer', 'SupportWidget']) {
  assert.match(vaultChrome, new RegExp('<' + component + '\\b'),
    'Vault shell missing shared public component: ' + component);
}
assert.doesNotMatch(vaultChrome, /(?:ToastProvider|ActionNotificationProvider|showToast|usePublicToast)/,
  'Vault shell must not add floating notifications');
assert.match(vaultChrome, /SAFE_VAULT_SHARE_URL\s*=\s*.+SITE_ORIGIN.+\/orders\//,
  'Vault sharing must use the safe Orders URL, not an exact-file link');
assert.match(vaultChrome, /url=\{\s*SAFE_VAULT_SHARE_URL\s*\}/,
  'PublicShare must receive an explicit non-file URL');
assert.doesNotMatch(vaultChrome, /(?:targetFileId|router\.query|fileParam|window\.location\.href)/,
  'Shared public actions must not read or publish private file identifiers');

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
  const loadedModule = { exports: {} };
  const sandbox = { module: loadedModule, exports: loadedModule.exports, require: mockRequire };
  vm.runInNewContext(output, sandbox, { timeout: 4000, filename: file });
  return loadedModule.exports;
}
const publicNotices = loadTypeScript('src/lib/publicActionNotices.ts', name => { throw Error('Unexpected public notice import: ' + name); });
const vaultPolicies = loadTypeScript('src/content/publicPolicyDetails.ts',
  name => { throw Error('Unexpected Vault policy import: ' + name); });
assert.ok(vaultPolicies.publicPolicyDetailsForRoute('/vault'),
  'Exact-file Vault must have a shared policy disclosure');
assert.equal(vaultPolicies.publicPolicyDetailsForRoute('/404'), null,
  'Redirect-only 404 must remain free of public disclosures');
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

// Prevent reintroduction of the explicitly retired customer-facing messages.
// Compile TSX without executing it: the transform strips non-rendered comments.
const publicScreens = [
  'src/components/ProductBlogPanel.tsx',
  'src/components/ElsewhereTravelAssistant.tsx',
  'src/components/ProductBuyBox.tsx',
  'src/components/VayuLokLive.tsx',
  'src/components/SupportWidget.tsx',
  'src/lib/whatsappBasket.ts',
  'src/lib/serviceRequests.ts',
  'src/lib/orderStatusLabels.ts',
  'src/components/orders/OrdersPage.tsx',
  'src/pages/auth.tsx',
  'src/components/cart/CartPage.tsx',
  'src/pages/checkout/status.tsx',
  'src/components/CheckoutProfile.tsx',
  'src/components/AddressFields.tsx',
  'src/components/get/GetPage.tsx',
];
const retiredPublicCopy = [
  "No posts match that search.",
  "Place not found.",
  "Search unavailable.",
  "Route unavailable.",
  "Number verified",
  "No booking or payment started.",
  "Checkout not ready. Payment unavailable.",
  "Item price unavailable. Review cart.",
  "Choose product options to see total.",
  "Choose a quantity from 1 to 99.",
  "Review the quantities in your cart.",
  "Some items are no longer available. Please review your cart.",
  "Secure checkout is being prepared. No payment has been started.",
  "We could not open the payment. No charge was made - please try again.",
  "Verify and save your checkout details again.",
  "Confirm your delivery address to continue.",
  "Verifying payment",
  "Access locked",
  "The secure file link is invalid. Please try downloading again.",
  "This cart link is no longer available.",
  "This service is not offered yet. Nothing has been charged.",
  "The price of this service has changed. Nothing has been charged.",
  "Air quality unavailable.",
  "Weather unavailable.",
  "Alerts unavailable.",
  "Currency unavailable.",
  "English restored.",
  "Translation unavailable.",
  "Translating to",
  "Translated to",
  "Checkout could not start. No charge made. Try again.",
  "Calculating your total securely…",
  'Selected. Copy with keyboard.',
  'Checking orders…',
  'Requests are unavailable right now.',
  'Enter your WhatsApp number.',
  'Enter a valid number.',
  'Couldn’t send a code. Check your number.',
  'Check your code.',
  'Code expired. Send a new one.',
  'Wait before trying again.',
  'Enter the 6-digit code.',
  'Check the number and try again.',
  'Checking prices…',
  'Verified price unavailable. Payment disabled.',
  'Price service unavailable. Payment disabled.',
  'Sign in to view final price.',
  'Confirm address to view final price.',
  'Payment window closed. Your cart is unchanged.',
  'Payment was not completed. Check your orders before trying again.',
  'We could not start this order. No charge was made. Please try again shortly.',
  'Secure payment could not open. Your cart is unchanged.',
  'We could not confirm checkout. Check your orders before trying again.',
  'Confirming payment…',
  'Payment received',
  'Payment incomplete',
  'Status unavailable',
  'Do not pay again.',
  'Enter your full name.',
  'Please check your delivery address.',
  'Enter a valid 6-digit PIN.',
  'Paid Vault access is not ready for this file yet.',
  'This file is not registered to your verified number.',
  'The download URL was not returned. Please try again.',
  'Payment recorded. Confirming access. Do not pay again.',
  'Payment verified. Your 24-hour access begins on your first authenticated download.',
  'Access expired',
];
for (const file of publicScreens) {
  const compiled = esbuild.transformSync(read(file), {
    loader: 'tsx', format: 'cjs', target: 'es2022', legalComments: 'none',
  }).code;
  for (const message of retiredPublicCopy) {
    assert.ok(!compiled.includes(message),
      'Retired public notification copy still rendered in ' + file + ': ' + message);
  }
}
assert.ok(!fs.existsSync(path.join(ROOT, 'src/lib/signInMessages.ts')),
  'Retired sign-in notification vocabulary must not be restored');

// The new retirements are checked across all reachable public-facing source
// directories, not merely the screens currently known to emit the words.
// Staff Workspace is intentionally exempt from this customer wording contract.
const newlyRetiredPublicCopy = [
  "No posts match that search.",
  "Place not found.",
  "Search unavailable.",
  "Route unavailable.",
  "Number verified",
  "No booking or payment started."
];
const publicSourceFiles = [];
function walkPublicSource(dir) {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    const relative = path.relative(ROOT, full).split(path.sep).join('/');
    if (entry.isDirectory()) {
      if (/^src\/(?:components|pages)\/(?:workspace|dashboard)(?:\/|$)/.test(relative)) continue;
      walkPublicSource(full);
    } else if (entry.isFile() && /\.(?:tsx?|jsx?)$/.test(entry.name)) {
      publicSourceFiles.push(relative);
    }
  }
}
for (const root of ['src/components', 'src/pages', 'src/lib', 'src/content']) {
  walkPublicSource(path.join(ROOT, root));
}
for (const file of publicSourceFiles) {
  const loader = /\.tsx$/.test(file) ? 'tsx' : /\.jsx$/.test(file) ? 'jsx'
    : /\.ts$/.test(file) ? 'ts' : 'js';
  const compiled = esbuild.transformSync(read(file), {
    loader, format: 'cjs', target: 'es2022', legalComments: 'none',
  }).code;
  for (const message of newlyRetiredPublicCopy) {
    assert.ok(!compiled.includes(message),
      'Retired extra customer copy returned in ' + file + ': ' + message);
  }
}
// Search found no matches is a factual empty result, not a system failure.
// The status must continue to distinguish zero results from unavailable service.
assert.match(read('src/components/ProductBlogPanel.tsx'), /filtered\.length === 0[\s\S]*?0 results/,
  'Blog no-results feedback must remain factual rather than reporting a failed request');
assert.match(read('src/components/VayuLokLive.tsx'), /searchStatus === 'no-results'[^\n]*0 results/,
  'Place search must keep no-results distinct from service unavailability');
assert.match(read('src/components/VayuLokLive.tsx'), /searchStatus === 'unavailable'[^\n]*publicActionText\( 'blocked' \)/,
  'Unavailable search must use the shared blocked notice');
assert.match(read('src/components/VayuLokLive.tsx'), /vl-live-route-unavailable[^\n]*publicActionText\( 'blocked' \)/,
  'Unavailable route must use the shared blocked notice');


const customerPayments = loadTypeScript('src/lib/orderStatusLabels.ts', name => {
  throw Error('Unexpected payment-label import: ' + name);
}).PAYMENT_STATUS_LABEL;
assert.deepEqual(
  Object.keys(customerPayments).sort(),
  ['authorized', 'captured', 'created', 'disputed', 'failed', 'pending', 'refunded'],
  'Every payment outcome must still have a visible, truthful label',
);
for (const [state, oldText] of Object.entries({
  captured: 'Paid',
  pending: 'Payment confirming',
  failed: 'Not paid',
  refunded: 'Refunded',
  disputed: 'Under review',
})) {
  assert.notEqual(customerPayments[state], oldText,
    'Retired payment state copy must not return: ' + state);
}
assert.equal(new Set(Object.values(customerPayments)).size, Object.keys(customerPayments).length,
  'Paid, unpaid, pending, refund and dispute states must stay distinguishable');
const refusalSource = read('src/lib/serviceRequests.ts');
assert.equal((refusalSource.match(/SERVICE_[A-Z_]+: publicActionText\(/g) || []).length, 11,
  'Every public service refusal should use the shared action vocabulary');


const cartFeedback = read('src/components/cart/CartPage.tsx');
assert.match(cartFeedback, /railTerminalRef\.current = true;\s+setRailTerminal\( true \);\s+setNotice\( \{ kind: 'error', message: publicActionText\( 'blocked' \) \} \)/,
  'Unknown payment outcomes must disarm checkout before showing a generic notice');
assert.match(cartFeedback, /quoteSignInRequired && \(/,
  'Retiring old sign-in copy must preserve a sign-in action');
const statusScreen = read('src/pages/checkout/status.tsx');
assert.match(statusScreen, /view === 'finalizing' && !stalled[\s\S]*?href="\/orders\/"/,
  'Pending payment finalization must offer Orders, not another charge');

// Fail closed if any retired mock or synthetic catalog data is reintroduced into live pages.
for (const [path, forbidden] of [
  ['src/components/ElsewhereTravelAssistant.tsx', /demoResponse\s*\(|eta-demo-checkout/],
  ['src/components/workspace/whatsapp/templates.tsx', /totalTemplatesSent: templates\.length \* 50/],
  ['src/components/workspace/channels/RcsSend.tsx', /FALLBACK_TEMPLATE_OPTIONS|useState\( 'test16' \)/],
  ['src/config/services.ts', /TEST_SERVICE_CHOICES/],
  ['src/config/contribution.ts', /TEST_CONTRIBUTION_CHOICES/],
  ['src/content/catalogSnapshot.ts', /TEST_PRODUCTS|synthetic-test-catalog/],
]) {
  assert.doesNotMatch(read(path), forbidden, 'Production mock data must not be restored: ' + path);
}
assert.match(read('src/components/ElsewhereTravelAssistant.tsx'),
  /Live travel search is unavailable/, 'Travel search must refuse invented provider results');
assert.match(read('src/components/workspace/channels/RcsSend.tsx'),
  /Select a confirmed RCS template before sending/, 'RCS must refuse an unverified template');

console.log('Action UI gate passed: imports, Orders targets, six public notices, retired copy, payment guardrails.');
