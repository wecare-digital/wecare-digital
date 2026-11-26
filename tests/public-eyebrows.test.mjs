import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
const source = path => read('src/' + path);
const { pages } = JSON.parse(read('config/public-pages.json'));

test('one responsive two-colour eyebrow is owned by BrandBadge', () => {
  const badge = source('components/BrandBadge.tsx');
  assert.match(badge, /data-wc-no-translate="true"/);
  assert.match(badge, /<BrandMark\s*\/>/);
  assert.match(badge, /className="brand-badge-label"[^>]*>\{ label \}/);
  assert.match(badge, /background:var\(--public-brand-lime,#d1f470\)/);
  assert.match(badge, /color:var\(--public-brand-green,#1a3a2a\)/);
  assert.match(badge, /max-width:100%/);
  assert.match(badge, /overflow-wrap:anywhere/);
  assert.doesNotMatch(badge, /white-space:nowrap/);
  assert.match(source('components/RotatingHero.tsx'), /<BrandBadge label=\{ badgeLabel \}/);
});

test('every canonical public marketing route has a deliberate eyebrow contract', () => {
  const exceptions = new Map([
    ['/', ['pages/index.tsx', null]],
    ['/contact', ['pages/contact.tsx', 'badgeLabel="Requests by WECARE.DIGITAL"']],
    ['/blog', ['components/BlogIndexView.tsx', "badgeLabel={ activeCategory && activeCategory !== defaultCategory"]],
    ['/shop', ['components/ShopListingView.tsx', 'badgeLabel="Shop"']],
    ['/orders', ['components/orders/OrdersPage.tsx', 'badgeLabel="Orders"']],
    ['/privacy', ['pages/privacy.tsx', 'badgeLabel="Privacy Policy — WECARE.DIGITAL"']],
    ['/terms', ['pages/terms.tsx', 'badgeLabel="Terms of Service — WECARE.DIGITAL"']],
    ['/relay-os', ['pages/relay-os/index.tsx', 'badgeLabel="Relay OS by WECARE.DIGITAL"']],
    ['/atmos/nano-climate', ['pages/atmos/nano-climate.tsx', 'badgeLabel="Nano Climate by WECARE.DIGITAL"']],
    ['/elsewhere/arogya-yatra', ['pages/elsewhere/arogya-yatra.tsx', 'badgeLabel="Arogya Yatra by WECARE.DIGITAL"']],
  ]);
  const shared = source('components/ProductPage.tsx');
  assert.ok(shared.includes('badgeLabel={ `${product.name} by WECARE.DIGITAL` }'));
  for (const { path } of pages) {
    const entry = exceptions.get(path);
    if (entry) {
      const [file, label] = entry;
      if (label === null) assert.doesNotMatch(source(file), /<BrandBadge\b|badgeLabel=/, path);
      else assert.ok(source(file).includes(label), path);
      continue;
    }
    const file = 'pages' + path + '.tsx';
    assert.ok(existsSync(new URL('../src/' + file, import.meta.url)), path);
    const route = source(file);
    assert.match(route, /<ProductPage\b/, path);
    assert.match(route, /product=\{ (?:child\.product|productBySlug\()/, path);
    if (route.includes('productChildByPath')) assert.ok(route.includes("productChildByPath( '" + path + "/' )"), path);
    else assert.ok(route.includes("productBySlug( '" + path.slice(1) + "' )"), path);
  }
});

test('upcoming, dynamic and customer pages supply contextual labels without maker guesses', () => {
  const upcoming = source('components/public/UpcomingProductPage.tsx');
  assert.ok(upcoming.includes('badgeLabel={ `${name} by WECARE.DIGITAL` }'));
  for (const [file, label] of [
    ['pages/get-kosh.tsx', 'name="GetKosh"'],
    ['pages/udyam-bids.tsx', 'name="UdyamBids"'],
    ['pages/shop/[slug].tsx', 'badgeLabel={ `Shop · ${product.name}` }'],
    ['pages/post/[slug].tsx', 'badgeLabel="Blog article"'],
    ['pages/auth.tsx', 'badgeLabel="Account access"'],
    ['components/get/GetPage.tsx', 'badgeLabel="Vault"'],
    ['components/cart/CartPage.tsx', 'badgeLabel="Checkout"'],
    ['pages/checkout/status.tsx', 'badgeLabel="Payment status"'],
  ]) assert.ok(source(file).includes(label), file);
  assert.match(source('pages/checkout/success.tsx'), /export \{ default \} from '\.\/status'/);
});

test('eyebrow motion is a single progressive enhancement of the hero entrance', () => {
  const hero = source('components/RotatingHero.tsx');
  assert.match(hero, /@media\(prefers-reduced-motion:no-preference\)\s*\{\s*\.rh-layout\.is-armed\.show \.rh-eyebrow\s*\{\s*animation:rh-eyebrow-enter \.32s cubic-bezier\(\.16,1,\.3,1\) both;/);
  assert.match(hero, /@keyframes rh-eyebrow-enter\s*\{\s*from\{opacity:\.85;transform:translateY\(4px\)\}\s*to\{opacity:1;transform:translateY\(0\)\}/);
  assert.match(hero, /\.rh-eyebrow\{display:flex;align-items:center;justify-content:flex-start;align-self:flex-start;margin:0 0 12px;min-width:0;max-width:100%\}/);
  assert.doesNotMatch(hero, /animation:rh-eyebrow-enter[^;]*infinite/);
});

test('eyebrow type, mark and compact spacing stay centred at both responsive sizes', () => {
  const badge = source('components/BrandBadge.tsx');
  const mark = source('components/BrandMark.tsx');
  assert.match(badge, /--brand-mark-height:1\.2em/);
  assert.match(badge, /display:inline-flex;align-items:center;justify-content:center;gap:6px/);
  assert.match(badge, /width:fit-content;min-width:0;max-width:100%/);
  assert.match(badge, /padding:5px 10px/);
  assert.match(badge, /font-size:17px;font-weight:650;letter-spacing:-\.125px;line-height:1\.2/);
  assert.match(badge, /@media\(min-width:768px\)\{\.brand-badge\{font-size:18px\}\}/);
  assert.match(badge, /display:block;min-width:0;margin:0;padding:0;font:inherit/);
  assert.match(mark, /height:var\(--brand-mark-height,18px\);width:auto;aspect-ratio:1451\/1718/);
});
