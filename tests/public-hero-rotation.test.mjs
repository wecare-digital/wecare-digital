import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CATALOG_SNAPSHOT } from '../src/content/catalogSnapshot.ts';
import { shopHeroWords } from '../src/content/shopHeroWords.ts';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
import { createHeroRotationClock, HERO_ROTATION_INTERVAL_MS } from '../src/lib/publicHeroRotation.ts';
test('shared hero cycles continuously without a separate visible pause control', () => {
  const pill = read('src/components/RotatingPill.tsx');
  for (const marker of ['grid-template-columns:minmax(0,1fr)', 'grid-area:1/1', 'overflow-wrap:anywhere', 'words.length <= 1', "document.visibilityState !== 'hidden'", "media.addEventListener( 'change', sync )", 'setCycleIndex( index => ( index + 1 ) % words.length )', 'prefers-reduced-motion: reduce', 'className="rp-toggle"', 'aria-pressed={ paused }', 'onClick={ () => setPaused( previous => !previous ) }', '.rp-toggle{display:none}', 'clock.stop()']) assert.ok(pill.includes(marker), marker);
  assert.doesNotMatch(pill, /HeroRotationControl|rp-control|Pause headline rotation|Resume headline rotation|HERO_ROTATION_DEADLINE_MS/);
  for (const path of ['src/components/RotatingHero.tsx','src/pages/index.tsx']) {
    const source = read(path);
    assert.ok(source.includes('<RotatingPill'), path);
    assert.doesNotMatch(source, /HeroRotationControl|rotationPaused/, path);
  }
});

test('continuous clock starts only once, loops and restarts only when enabled', () => {
  let id = 0, activeIndex = 0;
  const timers = new Map();
  const clock = createHeroRotationClock((tick, delay) => {
    assert.equal(delay, HERO_ROTATION_INTERVAL_MS);
    timers.set(++id, tick);
    return id;
  }, timer => timers.delete(timer), () => { activeIndex = (activeIndex + 1) % 4; });
  assert.equal(HERO_ROTATION_INTERVAL_MS, 2400);
  clock.sync(true);
  clock.sync(true);
  assert.equal(timers.size, 1);
  for (let tick = 0; tick < 13; tick++) {
    for (const callback of timers.values()) callback();
    assert.equal(activeIndex, (tick + 1) % 4);
  }
  clock.sync(false);
  clock.sync(false);
  assert.equal(timers.size, 0);
  assert.equal(activeIndex, 1);
  clock.sync(true);
  assert.equal(timers.size, 1);
  for (const callback of timers.values()) callback();
  assert.equal(activeIndex, 2);
  clock.stop();
  assert.equal(timers.size, 0);
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
  assert.match(shared, /<Head className="rh-head rh-title">\{ frame \}<\/Head>\s+<div className="rh-head rh-head-rotate rh-decoration">/);
  assert.doesNotMatch(shared, /className="rh-head rh-head-rotate rh-decoration"[^>]+aria-hidden="true"/);
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
