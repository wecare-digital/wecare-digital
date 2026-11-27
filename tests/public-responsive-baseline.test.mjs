import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
test('shared responsive tokens own safe gutters and mobile scale', () => {
  const tokens = read('src/styles/tokens.css');
  for (const token of ['--public-responsive-gutter:', '--public-safe-gutter-left:', '--public-safe-gutter-right:', '--public-responsive-cta-size:', '--public-mobile-supporting-size:', '--public-mobile-hero-size: clamp(']) assert.ok(tokens.includes(token), token);
  for (const path of ['src/pages/index.tsx','src/pages/_app.tsx','src/components/RotatingHero.tsx','src/components/Footer.tsx','src/components/public/PublicPolicyDetails.tsx','src/components/public/CustomerVaultChrome.tsx']) {
    assert.ok(read(path).includes('padding-left:var(--public-safe-gutter-left)'), path);
    assert.ok(read(path).includes('padding-right:var(--public-safe-gutter-right)'), path);
  }
  assert.ok(!read('src/pages/_app.tsx').includes('--public-mobile-hero-size:clamp('));
});
test('public components use a common foundation while retaining page content', () => {
  assert.ok(read('src/components/RotatingHero.tsx').includes('mobileFoundation = true'));
  assert.ok(read('src/components/ProductPage.tsx').includes('mobileFoundation = true'));
  assert.ok(read('src/components/RotatingPill.tsx').includes('.rp-cyc-word.on{max-width:100%;white-space:normal;overflow-wrap:anywhere}'));
  assert.ok(read('src/components/public/ClosingBand.tsx').includes('max-width:100%;min-width:0;text-align:center;overflow-wrap:anywhere'));
  assert.ok(read('src/components/PublicShare.tsx').includes('.ps-menu{position:relative;top:auto;inset-inline-start:auto;width:min(330px,100%);margin-top:10px}'));
});
test('baseline QA preserves Home policy exception and private Vault sharing', () => {
  for (const marker of ['PUBLIC_QA_BASELINE_ONLY','viewport-fit=cover','shared action rail','policy count','shared gutter','baseline.png']) assert.ok(read('scripts/verify_public_browser.mjs').includes(marker), marker);
  assert.ok(read('src/content/publicPolicyDetails.ts').includes("pathname === '/' || pathname === '/404'"));
  assert.ok(read('src/components/public/CustomerVaultChrome.tsx').includes('url={ SAFE_VAULT_SHARE_URL }'));
});
