import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CATALOG_SNAPSHOT } from '../src/content/catalogSnapshot.ts';
import { shopHeroWords } from '../src/content/shopHeroWords.ts';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
test('shared rotating hero reserves every word and offers a manual motion stop', () => {
  const pill = read('src/components/RotatingPill.tsx');
  for (const marker of ['grid-template-columns:minmax(0,1fr)', 'grid-area:1/1','overflow-wrap:anywhere', 'Pause headline rotation','Resume headline rotation','useSyncExternalStore( subscribeToHydration, readyInBrowser, readyInExport )', 'paused || words.length <= 1',"document.visibilityState === 'hidden'","media.addEventListener( 'change', sync )",'prefers-reduced-motion: reduce']) assert.ok(pill.includes(marker), marker);
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
    ['src/pages/shop/[slug].tsx', ['frame={ product.name }', 'decorativeRotation', 'shopHeroWords( product.slug )']],
    ['src/components/public/UpcomingProductPage.tsx', ['word: subject', "word: 'Not launched'", 'noindex, follow']],
    ['src/pages/get-kosh.tsx', ['subject="Prepaid cards"']],
    ['src/pages/udyam-bids.tsx', ['subject="Tender discovery"']],
  ];
  for (const [path, markers] of checks) for (const marker of markers) assert.ok(read(path).includes(marker), path+' '+marker);
});

test('editorial and product heroes use an exact H1 with the visual cycle outside it', () => {
  const article = read('src/pages/post/[slug].tsx');
  const shared = read('src/components/RotatingHero.tsx');
  assert.match(article, /frame=\{ post.title \}\s+decorativeRotation\s+pillPrefix="Read and"/);
  assert.doesNotMatch(article, /post-title|<h1\b/);
  assert.match(shared, /<Head className="rh-head rh-title">\{ frame \}<\/Head>\s+<div[^>]+aria-hidden="true">/);
  assert.match(shared, /\.rh-title\{text-wrap:balance\}/);
});

test('each current Shop detail has short, unique, truthful rotation copy', () => {
  const hidden = new Set([
    'ritual-guru-puja-guidance', 'ritual-guru-diy-puja-kit', 'ritual-guru-ritva',
    'submit-request', 'request-amendment', 'drop-docs', 'vault', 'shipments-track',
    'request-pickup', 'niji-setu',
  ]);
  const products = CATALOG_SNAPSHOT.products.filter(product => product.visible !== false && product.slug && !hidden.has(product.slug));
  assert.ok(products.length > 0);
  const wordSets = products.map(({slug}) => {
    const words = shopHeroWords(slug).map(({word}) => word);
    assert.equal(new Set(words).size, 3, slug);
    assert.notDeepEqual(words, shopHeroWords('new-catalogue-item').map(({word}) => word), slug);
    assert.ok(words.every(word => word.length <= 18), slug);
    return words.join('|');
  });
  assert.equal(new Set(wordSets).size, products.length);
  assert.deepEqual(shopHeroWords('contribute').map(({word}) => word), ['Contribution', 'Review', 'Receipt']);
  assert.deepEqual(shopHeroWords('toString'), shopHeroWords('new-catalogue-item'));
});
