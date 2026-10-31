/**
 * Regression tests for the two customer-initiated WhatsApp invitations.
 *
 * Pure local tests: no AWS calls, no WhatsApp sends, no customer data.
 * Run: node --test tests/customer_menu_notice_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function loadTS(relativePath) {
  const source = readFileSync(resolve(ROOT, relativePath), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    reportDiagnostics: true,
  });
  assert.deepEqual(compiled.diagnostics || [], [], 'TypeScript transpilation must succeed');
  const mod = { exports: {} };
  new Function('exports', 'module', 'require', compiled.outputText)(mod.exports, mod, require);
  return mod.exports;
}

const menu = loadTS('src/lib/customerMenuActions.ts');
const notices = loadTS('src/lib/customerMenuNotices.ts');

test('one short toast vocabulary for authenticated WhatsApp invitations', () => {
  assert.deepEqual(notices.customerMenuNotice('pending'), {
    message: 'Processing…', error: false,
  });
  assert.deepEqual(notices.customerMenuNotice('accepted'), {
    message: 'Sent to WhatsApp.', error: false,
  });
  assert.deepEqual(notices.customerMenuNotice('failed'), {
    message: "Couldn't confirm. Check WhatsApp.", error: true,
  });
  assert.doesNotMatch(notices.customerMenuNotice('accepted').message, /delivered|review submitted/i);
});

test('other Orders actions cannot claim a WhatsApp invitation was sent', () => {
  assert.equal(menu.menuActionForLabel('Subscribe'), 'subscribe');
  assert.equal(menu.menuActionForLabel('Leave Review'), 'leave-review');
  for (const label of ['Submit Request', 'Request Amendment', 'Drop Docs', 'Vault',
    'Track', 'Pickup Request', 'Shipped Orders']) {
    assert.equal(menu.menuActionForLabel(label), null);
  }
  const actionsMenu = readFileSync(resolve(ROOT, 'src/components/orders/OrderActionsMenu.tsx'), 'utf8');
  assert.match(actionsMenu, /const sendAction = menuActionForLabel\( action.label \)/);
  assert.match(actionsMenu, /if \( sendAction \) \{/);
});

test('Orders uses the same catalog for row and redirected-header invitations', () => {
  const page = readFileSync(resolve(ROOT, 'src/components/orders/OrdersPage.tsx'), 'utf8');
  assert.equal((page.match(/customerMenuNotice\( 'pending' \)/g) || []).length, 2);
  assert.match(page, /customerMenuNotice\( kind \)/);
  assert.doesNotMatch(page, /inviteName\(/);
  assert.match(page, /<PublicNotice mode="toast" tone=\{ inviteNotice\.error \? 'error'/);
  assert.match(page, /<PublicNotice mode="inline" tone="error" message=\{ ordersAlert\.message \}/);
  assert.match(page, /className="ord-backend-toast ord-invite-toast"/);
  assert.match(page, /\.ord-backend-toast\.ord-invite-toast\s*\{\s*inline-size:fit-content;max-inline-size:100%/);
});

test('both Lambda dispatchers and template-to-Flow mapping hooks are present in source', () => {
  const profile = readFileSync(resolve(ROOT, 'amplify/functions/auth/customer-profile/handler.py'), 'utf8');
  const sender = readFileSync(resolve(ROOT, 'amplify/functions/messaging/whatsapp-business-api/handler.py'), 'utf8');

  assert.match(profile, /sendLeaveReview/);
  assert.match(profile, /customerLeaveReviewTemplate/);
  assert.match(sender, /internalAction'\) == 'customerLeaveReviewTemplate'/);
  assert.match(sender, /return _customer_leave_review_template\(event\)/);
  assert.match(sender, /includeTemplateMappings/);
  assert.match(sender, /syncTemplateFlowMappings/);
});

test('one-time intent is consumed before any possible refresh, including expired intents', () => {
  const oldWindow = globalThis.window;
  const oldNow = Date.now;
  const store = new Map();
  const sessionStorage = {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, value) => { store.set(key, String(value)); },
    removeItem: (key) => { store.delete(key); },
  };
  try {
    globalThis.window = { sessionStorage };
    Date.now = () => 1700000000000;
    menu.stashCustomerMenuAction('leave-review');
    assert.equal(menu.takeCustomerMenuAction(), 'leave-review');
    assert.equal(menu.takeCustomerMenuAction(), null, 'refresh must not re-queue the send');

    menu.stashCustomerMenuAction('subscribe');
    Date.now = () => 1700000000000 + 11 * 60 * 1000;
    assert.equal(menu.takeCustomerMenuAction(), null, 'expired intent must never send');
    assert.equal(store.size, 0);
  } finally {
    globalThis.window = oldWindow;
    Date.now = oldNow;
  }
});

test('only the authenticated action is posted, with no recipient or automatic retry', async () => {
  const oldFetch = globalThis.fetch;
  const requests = [];
  try {
    globalThis.fetch = async (url, init) => {
      requests.push({ url, init });
      return { ok: true, status: 200,
        json: async () => ({ status: 'REVIEW_REQUEST_SENT', messageId: 'synthetic-id' }) };
    };
    assert.deepEqual(await menu.sendCustomerMenuAction('leave-review', 'synthetic-token'), {
      kind: 'accepted', messageId: 'synthetic-id',
    });
    assert.equal(requests.length, 1);
    assert.deepEqual(JSON.parse(requests[0].init.body), { action: 'sendLeaveReview' });
    assert.equal(requests[0].init.headers.Authorization, 'Bearer synthetic-token');
    assert.equal(requests[0].init.cache, 'no-store');

    globalThis.fetch = async () => ({
      ok: true, status: 200,
      json: async () => ({ status: 'PROFILE_UPDATE_SENT', messageId: 'synthetic-profile' }),
    });
    assert.equal((await menu.sendCustomerMenuAction('subscribe', 'synthetic-token')).kind, 'accepted');

    let failures = 0;
    globalThis.fetch = async () => { failures += 1; throw new Error('synthetic network timeout'); };
    assert.deepEqual(await menu.sendCustomerMenuAction('leave-review', 'synthetic-token'), {
      kind: 'failed',
    });
    assert.equal(failures, 1, 'an ambiguous failure must never retry automatically');

    globalThis.fetch = async () => ({ ok: false, status: 401, json: async () => ({}) });
    assert.deepEqual(await menu.sendCustomerMenuAction('leave-review', 'synthetic-token'), {
      kind: 'expired',
    });

    globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({}) });
    assert.deepEqual(await menu.sendCustomerMenuAction('leave-review', 'synthetic-token'), {
      kind: 'failed',
    });
  } finally {
    globalThis.fetch = oldFetch;
  }
});
