#!/usr/bin/env node
// Read-only computed-style regression for approved preview or public site.
// Run PUBLIC_QA_BASE=https://wecare.digital node scripts/verify_public_button_theme.mjs
import assert from 'node:assert/strict';
const base = process.env.PUBLIC_QA_BASE;
if (!base) throw Error('Set PUBLIC_QA_BASE to the approved preview or public site.');
const origin = new URL(base);
assert.ok(['http:', 'https:'].includes(origin.protocol));
const { chromium } = await import('playwright');
const browser = await chromium.launch();
const marker = '[data-public-auth-button-theme="active"]';
const readStyle = (page, selector) => page.locator(selector).first().evaluate(el => {
  const s = getComputedStyle(el);
  const token = name => {
    const p = document.createElement('span');
    p.style.color = 'var(' + name + ')';
    el.append(p);
    const value = getComputedStyle(p).color;
    p.remove();
    return value;
  };
  return { background: s.backgroundColor, color: s.color, radius: s.borderTopLeftRadius, decoration: s.textDecorationLine, height: el.getBoundingClientRect().height, tint: token('--public-lime-tint'), green: token('--public-brand-green'), lime: token('--public-brand-lime') };
});
try {
  for (const width of [1440, 390, 280, 160]) {
    const page = await browser.newPage({ viewport: {width, height: 900}, reducedMotion: 'reduce' });
    try {
      await page.goto(new URL('/', origin).href, {waitUntil:'domcontentloaded'});
      assert.equal(await page.locator(marker).count(), 0, 'Home theme marker');
      const home = await readStyle(page, '.home-close-cta');
      const dock = await readStyle(page, '.ps-contribute');
      assert.equal(home.background, home.lime, 'Home CTA retains original lime');
      assert.equal(home.decoration, 'none');
      assert.equal(dock.radius, '50%', 'Home dock retains original circle');
      for (const [route, selector] of [['/auth/', '.auth-action'], ['/shop/', '.shop-card-action'], ['/anew/', '.cb-cta'], ['/contact/', '.cl-cta']]) {
        await page.goto(new URL(route, origin).href, {waitUntil:'domcontentloaded'});
        assert.equal(await page.locator(marker).count(), 1, route);
        const s = await readStyle(page, selector);
        assert.equal(s.background, s.tint, route + ' surface');
        assert.equal(s.color, s.green, route + ' ink');
        assert.equal(s.radius, '13px', route + ' radius');
        assert.ok(s.decoration.includes('underline'), route + ' label');
        assert.ok(s.height >= 51, route + ' height');
        const compact = await readStyle(page, '.ps-contribute');
        assert.equal(compact.radius, '13px', route + ' compact dock radius');
        assert.equal(compact.background, compact.tint, route + ' compact dock tint');
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2), route + ' horizontal overflow');
      }
      await page.goto(new URL('/', origin).href, {waitUntil:'domcontentloaded'});
      assert.equal(await page.locator(marker).count(), 0);
      assert.deepEqual(await readStyle(page, '.home-close-cta'), home, 'Home after non-Home navigation');
      console.log('PASS', width);
    } finally { await page.close(); }
  }
} finally { await browser.close(); }
