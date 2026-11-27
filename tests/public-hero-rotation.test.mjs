import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
test('shared rotating hero reserves every word and offers a manual motion stop', () => {
  const pill = read('src/components/RotatingPill.tsx');
  for (const marker of ['grid-template-columns:minmax(0,1fr)', 'grid-area:1/1','overflow-wrap:anywhere', 'Pause headline rotation','Resume headline rotation', 'paused || words.length <= 1',"document.visibilityState === 'hidden'","media.addEventListener( 'change', sync )",'prefers-reduced-motion: reduce']) assert.ok(pill.includes(marker), marker);
  for (const path of ['src/components/RotatingHero.tsx','src/pages/index.tsx']) {
    const source = read(path);
    assert.ok(source.includes('paused={ rotationPaused }'), path);
    assert.ok(source.includes('<HeroRotationControl'), path);
  }
});
test('former static or generic hero bands use page-specific context and multiple words', () => {
  const checks = [
    ['src/components/orders/OrdersPage.tsx', ["word: 'orders'", "word: 'payments'", "word: 'invoices'"]],
    ['src/components/cart/CartPage.tsx', ['frame="Checkout: review and"', "word: 'confirm'", "word: 'verify'", "word: 'pay'"]],
    ['src/pages/checkout/status.tsx', ['frame="Review payment"', "word: 'status'", "word: 'confirmation'"]],
    ['src/pages/shop/[slug].tsx', ['Explore ${product.name}', "word: 'details'", "word: 'options'"]],
    ['src/components/public/UpcomingProductPage.tsx', ['word: subject', "word: 'Not launched'", 'noindex, follow']],
    ['src/pages/get-kosh.tsx', ['subject="Prepaid cards"']],
    ['src/pages/udyam-bids.tsx', ['subject="Tender discovery"']],
  ];
  for (const [path, markers] of checks) for (const marker of markers) assert.ok(read(path).includes(marker), path+' '+marker);
});
