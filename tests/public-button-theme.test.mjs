import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
const css = read('src/styles/public-button-theme.css');
const gate = ':root:has([data-public-auth-button-theme="active"])';

test('Auth button theme is scoped to non-Home public pages, including verified Vault', () => {
  const app = read('src/pages/_app.tsx');
  assert.ok(app.includes("import '../styles/public-button-theme.css';"));
  assert.ok(app.includes("data-public-auth-button-theme={ router.pathname === '/' ? undefined : 'active' }"));
  assert.equal(app.match(/data-public-auth-button-theme=/g)?.length, 1);
  assert.ok(read('src/components/public/CustomerVaultChrome.tsx').includes('data-public-auth-button-theme="active"'));
  assert.ok(!read('src/pages/index.tsx').includes('data-public-auth-button-theme'));
  // Each style rule starts with the route gate; commas inside :is/:where are not separate selectors.
  const rules = css.replace(/\/\*[\s\S]*?\*\//g, '').split(/[{}]/).map(s => s.trim());
  const selectors = rules.filter(s => s.startsWith(':'));
  assert.ok(selectors.length >= 12);
  for (const selector of selectors) {
    assert.ok(selector.startsWith(gate), selector);
    // All top-level selector branches in grouped rules must have the same gate.
    let depth = 0, start = 0;
    for (let i = 0; i < selector.length; i++) {
      if (selector[i] === '(') depth++;
      if (selector[i] === ')') depth--;
      if (selector[i] === ',' && depth === 0) {
        assert.ok(selector.slice(start, i).trim().startsWith(gate));
        start = i + 1;
      }
    }
    assert.ok(selector.slice(start).trim().startsWith(gate));
  }
  assert.match(read('src/components/public/ClosingBand.tsx'), /\.cb-cta\{[^}]*background:var\(--public-brand-lime\)/);
  assert.match(read('src/components/PublicShare.tsx'), /\.ps-action\{[^}]*border-radius:50%/);
});

test('explicit labelled actions retain the Auth visual contract',()=>{
  const baseline=read('src/styles/public-interactions.css');
  for(const token of ['var(--public-hover-radius)','var(--public-lime-tint)','var(--public-brand-green)','var(--public-button-hover)','min-height: 52px','font: 700 var(--public-responsive-cta-size)/1.35 var(--font-sans)','text-decoration: underline']){
    assert.ok(css.includes(token),token);
    assert.ok(baseline.includes(token),token);
  }
  for(const [path,selector] of [
    ['src/components/public/ClosingBand.tsx','cb-cta'],
    ['src/components/ProductPage.tsx','pdp-cta'],
    ['src/components/ContactLocation.tsx','cl-cta'],
    ['src/components/ShopListingView.tsx','shop-card-action'],
    ['src/pages/post/[slug].tsx','post-related-all'],
    ['src/pages/relay-os/index.tsx','api-wa-link'],
    ['src/components/orders/OrdersPage.tsx','ord-quiet'],
    ['src/components/cart/CartPage.tsx','cart-quiet-refresh'],
    ['src/components/orders/SubmitRequestForm.tsx','sr-action'],
  ]){
    assert.ok(read(path).includes(selector),path);
    assert.ok(css.includes('.'+selector),selector);
  }
  for(const token of ['[aria-disabled="true"]','prefers-reduced-motion: reduce','forced-colors: active',':focus-visible'])assert.ok(css.includes(token),token);
  assert.match(read('src/components/cart/CartPage.tsx'),/\.cart-quiet-refresh\{[^}]*background:var\(--public-bg\);color:var\(--public-brand-green\)/);
});
test('no wildcard can recolour component-owned controls or override cards',()=>{
  assert.doesNotMatch(css,/button:not\(|--public-card-radius\s*:|--public-hover-radius:\s*6px/);
  assert.doesNotMatch(css,/\.wc-wa\b|\.wc-chip\b|\.ps-action\b|\.pager-arrow\b|\.pp-tab\b|\.vl-ui-icon-action\b|\.eta-send\b/);
  const header=css.match(/:is\(\.hdr-cart, \.nav-trigger\)\s*\{([^}]+)\}/);
  assert.ok(header);
  assert.match(header[1],/--public-hover-radius: var\(--public-option-radius\)/);
  assert.doesNotMatch(header[1],/background|border-radius|padding|width|height/);
  assert.match(read('src/components/HeaderCart.tsx'),/background:none;border:0;border-radius:10px/);
  const support=read('src/components/SupportWidget.tsx');
  assert.match(support,/\.wc-chip\{[^}]*border-radius:9999px;background:transparent/);
  assert.match(support,/\.wc-wa\{[^}]*border-radius:50%/);
  assert.match(read('src/components/Pager.tsx'),/border-radius:50%;background:#fff/);
  assert.ok(read('src/pages/relay-os/index.tsx').includes('className={`pp-tab '));
});
