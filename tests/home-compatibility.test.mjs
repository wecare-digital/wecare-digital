import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
test('Home retains its design tokens and allows narrow content to reflow', () => {
  const home = read('src/pages/index.tsx');
  assert.match(home, /<main className="home-shell">/);
  assert.doesNotMatch(home, /<BrandBadge\b|<PolicyDetails\b|<PublicPolicyDetails\b/);
  assert.match(home, /<RotatingPill words=\{ CYCLE_WORDS \} phase=\{ phase \}/);
  assert.match(home, /\.home-head-line\{max-width:100%;white-space:normal;text-wrap:wrap\}/);
  assert.doesNotMatch(home, /\.home-head-line\{[^}]*white-space:nowrap/);
  assert.match(home, /\.home-head :global\(\.rp-cyc-word\.on\)\{max-width:100%;white-space:normal;overflow-wrap:anywhere\}/);
  assert.match(home, /\.home-close-cta\)\{font-size:18px;max-width:100%;min-width:0;justify-content:center;text-align:center;overflow-wrap:anywhere/);
  assert.ok(home.includes('padding-left:var(--public-safe-gutter-left)'));
  assert.ok(home.includes('padding-right:var(--public-safe-gutter-right)'));
});
test('Home fixed header safe areas are now shared with all public routes', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes('background:#fff;padding-top:var(--safe-top,0px)'));
  assert.ok(header.includes('padding-left:max(var(--public-mobile-page-gutter),var(--safe-left,0px))'));
  assert.ok(header.includes('padding-right:max(var(--public-mobile-page-gutter),var(--safe-right,0px))'));
  assert.ok(header.includes('visual?.addEventListener( \'resize\', syncMenuGeometry )'));
});
test('the page-specific browser runner selects an explicit route and browser engines', () => {
  const qa = read('scripts/verify_public_browser.mjs');
  for (const token of ['PUBLIC_QA_ROUTE', 'PUBLIC_QA_ENGINES', "'chromium', 'firefox', 'webkit'", 'reflow-stress-160', 'phone-landscape', 'desktop-2560', 'clipped hero frame', 'clipped rotating word', 'navigation focus recovery']) {
    assert.ok(qa.includes(token), token);
  }
  assert.match(qa, /for \(const route of selectedRoutes\)/);
});
