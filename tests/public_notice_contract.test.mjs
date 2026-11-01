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

test('one sitewide public toast replaces the previous one and cleans up on navigation', () => {
  const provider = read('src/components/public/PublicToastProvider.tsx');
  const app = read('src/pages/_app.tsx');
  assert.match(app, /import PublicToastProvider from '\.\.\/components\/public\/PublicToastProvider'/);
  assert.match(app, /if \( isPublic \)[\s\S]*?<PublicToastProvider>/);
  assert.match(provider, /useState<PublicToast \| null>\( null \)/);
  assert.match(provider, /setActive\( \{ id, message, tone \} \)/);
  assert.match(provider, /if \( activeId\.current !== id \) return/);
  assert.match(provider, /router\.events\.on\( 'routeChangeStart', onRouteChange \)/);
  assert.match(provider, /durationMs === undefined \? \( tone === 'error' \? 0 : 2500 \)/);
  assert.match(provider, /const value = useOptionalPublicToast\(\)/);
  assert.match(provider, /<PublicNotice key=\{ active\.id \} mode="toast"/);
  assert.doesNotMatch(provider, /setActive\( current => \[ \.\.\.current/,
    'never queue multiple transient notices');
});

test('Orders uses one global toast and one inline actionable error', () => {
  const source = read('src/components/orders/OrdersPage.tsx');
  assert.match(source, /const \{ showToast, hideToast \} = usePublicToast\(\)/);
  assert.equal((source.match(/showToast\( customerMenuNotice\( 'pending' \)\.message/g) || []).length, 2);
  assert.match(source, /showToast\( notice\.message,/);
  assert.match(source, /hideToast\( inviteToastId\.current \)/);
  assert.match(source, /setOrdersAlert\( \{ source: 'service', message: notice\.message \} \)/);
  assert.match(source, /showToast\( 'Copied\.',/);
  assert.match(source, /setOrdersAlert\( \{ source: 'copy', message: 'Selected\. Copy with keyboard\.' \} \)/);
  assert.match(source, /<PublicNotice mode="inline" tone="error" message=\{ ordersAlert\.message \}/);
  assert.doesNotMatch(source, /inviteNotice|copyNotice|ord-toast-rail|setCopyNotice/,
    'never stack three notification boxes on Orders');
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

test('PublicShare uses the shared host on public pages and keeps Workspace fallback', () => {
  const source = read('src/components/PublicShare.tsx');
  assert.match(source, /const publicToast = useOptionalPublicToast\(\)/);
  assert.match(source, /showToast\?\.\( 'Link copied\.',/);
  assert.match(source, /showToast\?\.\( "Couldn't copy link\.",/);
  assert.match(source, /\{ !publicToast && \(/);
  assert.match(source, /<PublicNotice mode=\{ copied \? 'toast' : 'screen-reader' \}/);
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
