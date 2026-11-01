/**
 * Source-level contract for the public/customer-facing notice component.
 * No providers, networks, payments or WhatsApp sends are exercised here.
 * Run with: node --test tests/public_notice_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(ROOT, path), 'utf8');

test('one public notice defines toast, persistent inline and screen-reader modes', () => {
  const source = read('src/components/public/PublicNotice.tsx');
  assert.match(source, /'toast' \| 'inline' \| 'screen-reader'/);
  assert.match(source, /const role = tone === 'error' \? 'alert' : 'status'/);
  assert.match(source, /aria-live=\{ role === 'alert' \? 'assertive' : 'polite' \}/);
  assert.match(source, /aria-atomic="true"/);
  assert.match(source, /is-screen-reader/);
  assert.match(source, /is-toast/);
  assert.match(source, /is-inline/);
  assert.match(source, /border-inline-start:4px solid var\(--public-brand-lime\)/);
  assert.doesNotMatch(source, /setTimeout|setInterval|window\.setTimeout/,
    'a shared display component must not auto-dismiss critical information');
});

test('Orders uses brief invitation and copy toasts, but keeps backend alerts persistent', () => {
  const source = read('src/components/orders/OrdersPage.tsx');
  assert.match(source, /<PublicNotice mode="toast" tone=\{ inviteNotice\.error/);
  assert.match(source, /<PublicNotice mode="inline" tone="error" message=\{ ordersAlert\.message \}/);
  assert.match(source, /copyNotice\.kind === 'fallback' \? 'inline' : 'toast'/);
  assert.match(source, /restartTimer\( \(\) => setCopyNotice\( null \), 2500 \)/);
  assert.doesNotMatch(source, /setTimeout\( \(\) => setInviteNotice\( null \)/);
});

test('checkout, profile, sign-in and Vault errors remain inline, not auto-dismissing', () => {
  const cart = read('src/components/cart/CartPage.tsx');
  const profile = read('src/components/CheckoutProfile.tsx');
  const auth = read('src/pages/auth.tsx');
  const vault = read('src/components/get/GetPage.tsx');
  assert.match(cart, /notice\.kind === 'error' && \(\s*<PublicNotice mode="inline" tone="error"/);
  assert.match(profile, /<PublicNotice mode="inline" tone="error" message=\{ message \}/);
  assert.match(auth, /<PublicNotice id="auth-error" mode="inline" tone="error"/);
  assert.match(auth, /aria-describedby=\{ error \? 'auth-error' : undefined \}/);
  assert.match(vault, /<PublicNotice mode="inline" tone="error" message=\{ error \} flush/);
  assert.match(vault, /<PublicNotice mode="inline" tone="error" message=\{ feedback\.message \}/);
  assert.match(vault, /Payment recorded\. Confirming access\. Do not pay again\./);
});

test('copy-link has one polite live region which becomes a compact visible toast', () => {
  const source = read('src/components/PublicShare.tsx');
  assert.match(source, /<PublicNotice mode=\{ copied \? 'toast' : 'screen-reader' \} tone="success"/);
  assert.match(source, /message=\{ copied \? 'Link copied\.' : '' \}/);
  assert.doesNotMatch(source, /<span className="ps-status" role="status"/);
});

test('data-heavy VayuLok states and payment status screens are not converted into toasts', () => {
  const live = read('src/components/VayuLokLive.tsx');
  const status = read('src/pages/checkout/status.tsx');
  assert.match(live, /role="status"/);
  assert.match(status, /role="status"/);
  assert.doesNotMatch(live, /<PublicNotice mode="toast"/);
  assert.doesNotMatch(status, /<PublicNotice mode="toast"/);
});
