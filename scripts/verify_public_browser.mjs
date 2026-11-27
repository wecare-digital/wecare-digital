#!/usr/bin/env node
/**
 * Read-only public browser smoke: desktop, tablet, phone, and foldable-like
 * viewport sizes. Requires Playwright + Chromium in the QA environment.
 * Does not submit checkout, payment, login or WhatsApp forms.
 */
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { installHeroTrace, verifyHeroRotation } from './public_hero_audit.mjs';

const base = process.env.PUBLIC_QA_BASE;
if (!base) throw new Error('Set PUBLIC_QA_BASE to an approved preview or public website URL.');
const origin = new URL(base);
if (!['http:', 'https:'].includes(origin.protocol)) throw new Error('HTTP(S) base required');
const output = process.env.PUBLIC_QA_OUTPUT || join(tmpdir(), 'wecare-public-qa-' + Date.now());
await mkdir(output, {recursive: true});
const playwright = await import('playwright').catch(() => {
  throw new Error('Install Playwright and the requested browser engines in the QA environment; no production dependency is required.');
});
const engineNames = (process.env.PUBLIC_QA_ENGINES || 'chromium').split(',').map(name => name.trim()).filter(Boolean);
for (const engine of engineNames) assert.ok(['chromium', 'firefox', 'webkit'].includes(engine), 'Unknown browser engine: ' + engine);
assert.ok(engineNames.length, 'Select at least one browser engine');
const menuOnly = process.env.PUBLIC_QA_MENU_ONLY === '1';
const baselineOnly = process.env.PUBLIC_QA_BASELINE_ONLY === '1';
const interactionsOnly = process.env.PUBLIC_QA_INTERACTIONS_ONLY === '1';
assert.ok([menuOnly, baselineOnly, interactionsOnly].filter(Boolean).length <= 1, 'Choose one focused QA mode');
const requestedRoute = process.env.PUBLIC_QA_ROUTE;
const normalizedRoute = requestedRoute ? new URL(requestedRoute, origin).pathname.replace(/\/+$/, '') || '/' : null;
if (requestedRoute) assert.equal(new URL(requestedRoute, origin).origin, origin.origin, 'QA route must use the approved origin');
const devices = [
  ['desktop', 1440, 900, false],
  ['tablet-portrait', 768, 1024, true],
  ['tablet-landscape', 1024, 768, true],
  ['mobile', 390, 844, true],
  ['fold-cover', 320, 800, true],
  ['fold-unfolded', 720, 900, true],
  ['mobile-reduced-motion', 390, 844, true, 'reduce'],
];
const routes = [
  {path: '/', name: 'home'},
  {path: '/shop/', name: 'shop', input: '#shop-q', query: 'visa'},
  {path: '/terms/', name: 'terms', input: 'input[aria-label="Find a legal clause"]', query: 'refund'},
  {path: '/privacy/', name: 'privacy', input: 'input[aria-label="Find a legal clause"]', query: 'personal data'},
  {path: '/blog/', name: 'blog', input: '#blog-q', query: 'integrity'},
  {path: '/anew/', name: 'anew', input: '#pbp-q', query: 'integrity'},
  {path: '/orders/', name: 'orders'},
];
// The generated public catalogue is the route inventory; every registered page
// is checked, not just the initial sample. Home deliberately avoids a brand-only
// duplicate of its header. Upcoming pages are not indexed, but are real routes.
const { pages: publicPages } = JSON.parse(await readFile(new URL('../config/public-pages.json', import.meta.url), 'utf8'));
const specialEyebrows = {
  '/': null,
  '/contact': 'Requests by WECARE.DIGITAL',
  '/blog': 'Blog',
  '/shop': 'Shop',
  '/orders': 'Orders',
  '/terms': 'Terms of Service — WECARE.DIGITAL',
  '/privacy': 'Privacy Policy — WECARE.DIGITAL',
};
const expected = new Map(publicPages.map(({ path, name }) => [
  path, Object.hasOwn(specialEyebrows, path) ? specialEyebrows[path] : name + ' by WECARE.DIGITAL',
]));
for (const [path, eyebrow] of [
  ['/get-kosh', 'GetKosh by WECARE.DIGITAL'],
  ['/udyam-bids', 'UdyamBids by WECARE.DIGITAL'],
  ['/auth', 'Account access'],
  ['/checkout', 'Checkout'],
]) expected.set(path, eyebrow);
for (const [path, eyebrow] of expected) {
  const url = path === '/' ? '/' : path + '/';
  const existing = routes.find(route => route.path === url);
  if (existing) existing.eyebrow = eyebrow;
  else routes.push({path: url, name: path.slice(1).replaceAll('/', '-'), eyebrow});
}
const selectedRoutes = normalizedRoute ? routes.filter(route => (route.path.replace(/\/+$/, '') || '/') === normalizedRoute)
  : menuOnly ? routes.filter(route => ['/', '/relay-os/', '/shop/', '/terms/'].includes(route.path))
  : interactionsOnly ? routes.filter(route => route.path === '/' || route.input) : routes;
assert.ok(selectedRoutes.length, 'No registered QA route matches ' + normalizedRoute);
const focusedDevices = [
  ['desktop-2560', 2560, 1440, false], ['desktop-1920', 1920, 1080, false],
  ['laptop-1280', 1280, 800, false], ['desktop-short', 1280, 600, false],
  ['tablet-large', 834, 1194, true], ['phone-360', 360, 800, true],
  ['phone-375', 375, 812, true], ['phone-412', 412, 915, true],
  ['phone-430', 430, 932, true], ['phone-landscape', 844, 390, true],
  ['fold-280', 280, 653, true], ['reflow-stress-160', 160, 640, true, 'reduce'],
];
const matrix = normalizedRoute || menuOnly || baselineOnly || interactionsOnly ? [...devices, ...focusedDevices] : devices;
async function assertSharedSearchGeometry(field, name, withFeedback = false) {
  const geometry = await field.evaluate((el, withFeedback) => {
    const parent = el.parentElement;
    const box = parent.getBoundingClientRect();
    const controls = [el, ...parent.querySelectorAll('button.public-search-clear, button.voice-search-mic')].filter(node => node.getClientRects().length);
    const feedback = withFeedback ? parent.querySelector('.voice-search-status.is-visible') : null;
    if (feedback) controls.push(feedback);
    const rects = controls.map(node => {const r=node.getBoundingClientRect(); return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height};});
    const style = getComputedStyle(el);
    return {box:{left:box.left,right:box.right,top:box.top,bottom:box.bottom},rects,hasFeedback:!!feedback,marked:parent.hasAttribute('data-public-search-field'),
      focused:el === document.activeElement, forcedColors:matchMedia('(forced-colors: active)').matches,
      outlineStyle:style.outlineStyle, outlineWidth:style.outlineWidth, focusShadow:style.boxShadow};
  }, withFeedback);
  if (withFeedback) assert.ok(geometry.hasFeedback, name + ': failure did not render a visible status row');
  assert.ok(geometry.marked, name + ': missing shared search layout');
  if (geometry.focused && !geometry.forcedColors) {
    assert.ok(geometry.outlineStyle === 'none' || parseFloat(geometry.outlineWidth) === 0, name + ': extra rectangular search focus box');
    assert.match(geometry.focusShadow, /inset.*0px -2px 0px/, name + ': focused search must have the visible bottom line');
  }
  for (const [i, a] of geometry.rects.entries()) {
    assert.ok(a.left >= geometry.box.left - 2 && a.right <= geometry.box.right + 2 && a.top >= geometry.box.top - 2 && a.bottom <= geometry.box.bottom + 2, name + ': search control leaves row');
    if (withFeedback && i === geometry.rects.length - 1) {
      assert.ok(a.width >= geometry.box.right - geometry.box.left - 2 && a.height > 1, name + ': failure status does not fill its own row');
    } else if (i > 0) {
      assert.ok(a.width >= 44 && a.height >= 44, name + ': search action touch size');
    }
    for (const b of geometry.rects.slice(i+1)) {
      assert.ok(a.right <= b.left+1 || b.right <= a.left+1 || a.bottom <= b.top+1 || b.bottom <= a.top+1, name + ': search controls overlap');
    }
  }
}

async function verifyMenu(page, name, width, height, touch) {
  const trigger = page.getByRole('button', {name: 'Open navigation', exact: true});
  const nav = page.getByRole('navigation', {name: 'Public navigation'});
  const field = nav.getByRole('searchbox', {name: 'Search navigation'});
  const assertBounds = async () => {
    await page.waitForFunction(() => {
      const el = document.getElementById('public-navigation-menu');
      if (!el || !el.classList.contains('open')) return false;
      const box = el.getBoundingClientRect();
      const v = window.visualViewport;
      const x = v?.offsetLeft || 0, y = v?.offsetTop || 0;
      return box.width > 0 && box.height > 0 && box.left >= x - 2 && box.top >= y - 2
        && box.right <= x + (v?.width || document.documentElement.clientWidth) + 2
        && box.bottom <= y + (v?.height || window.innerHeight) + 2;
    }, null, {timeout: 5000});
  };
  const triggerBox = await trigger.boundingBox();
  const cartBox = await page.locator('.hdr-cart').boundingBox();
  assert.ok(triggerBox && triggerBox.width >= 44 && triggerBox.height >= 44, name + ': menu tap target');
  assert.ok(cartBox && cartBox.width >= 44 && cartBox.height >= 44, name + ': cart tap target');
  assert.ok(triggerBox.x + triggerBox.width <= cartBox.x + 1 || cartBox.x + cartBox.width <= triggerBox.x + 1, name + ': overlapping header controls');
  await trigger.click();
  await nav.waitFor({state: 'visible'});
  assert.equal(await trigger.getAttribute('aria-expanded'), 'true');
  const arrowColor = await trigger.locator('.nav-trigger-icon').evaluate(el => getComputedStyle(el).fill);
  assert.equal(arrowColor, 'rgb(37, 99, 235)', name + ': navigation trigger arrow color');
  const chevrons = await nav.locator('.nav-row-chevron:visible').evaluateAll(els => els.map(el => getComputedStyle(el).fill));
  assert.ok(chevrons.every(color => color === arrowColor), name + ': inconsistent navigation chevron color');
  await assertBounds();
  await page.screenshot({path: join(output, name + '-menu.png')});
  const row = nav.locator('.nav-item:visible').first();
  const rowBox = await row.boundingBox();
  assert.ok(rowBox && rowBox.height >= 44 && rowBox.width >= 44, name + ': navigation row target');
  assert.ok(await row.evaluate(el => parseFloat(getComputedStyle(el).fontSize) >= 18), name + ': navigation text too small');
  const family = nav.locator('.nav-family-label').filter({hasText: 'Elsewhere'}).first();
  if (await family.count()) {
    const before = await family.getAttribute('aria-expanded');
    await family.click();
    assert.notEqual(await family.getAttribute('aria-expanded'), before, name + ': submenu did not toggle');
  }
  await field.fill('Drafting');
  await nav.getByRole('link', {name: /Drafting/i}).first().waitFor({state: 'visible'});
  await assertBounds();
  const clear = nav.getByRole('button', {name: 'Clear search', exact: true});
  const clearBox = await clear.boundingBox();
  assert.ok(clearBox && clearBox.width >= 44 && clearBox.height >= 44, name + ': clear target');
  await assertSharedSearchGeometry(field, name);
  await clear.click();
  assert.equal(await field.inputValue(), '', name + ': clear query');
  assert.ok(await field.evaluate(el => el === document.activeElement), name + ': clear focus');
  await field.fill('zzzzzzzzzzzzzzzz');
  await nav.getByText('No matching page.', {exact: false}).waitFor({state: 'visible'});
  if (touch && height >= 390) {
    // Resized viewport is a keyboard-size stress approximation, not native IME testing.
    await page.setViewportSize({width, height: Math.max(220, Math.floor(height * .6))});
    try { await assertBounds(); }
    finally { await page.setViewportSize({width, height}); }
  }
  await field.press('Escape');
  assert.equal(await field.inputValue(), '', name + ': Escape clears query');
  await field.press('Escape');
  await nav.waitFor({state: 'hidden'});
  assert.ok(await trigger.evaluate(el => el === document.activeElement), name + ': navigation focus recovery');
  assert.equal(await trigger.getAttribute('aria-expanded'), 'false');
  await trigger.click();
  await field.focus();
  await page.locator('.hdr-cart').focus();
  await nav.waitFor({state: 'hidden'});
  assert.ok(await page.locator('.hdr-cart').evaluate(el => el === document.activeElement), name + ': outside focus was stolen');
}

// Fixtures deliberately replace permission and language catalogue calls. No
// microphone is accessed, no translation POST is permitted, and no contact,
// order, login or payment control is activated.
async function installInteractionFixtures(page) {
  let translationAttempted = false;
  await page.route('**/site-language/languages', route => route.fulfill({
    json: {languages: [
      {code:'en',name:'English'}, {code:'ar',name:'Arabic'},
      {code:'bn',name:'Bengali'}, {code:'hi',name:'Hindi'},
      {code:'mr',name:'Marathi'}, {code:'ta',name:'Tamil'},
    ]},
    headers: {'access-control-allow-origin':'*'},
  }));
  await page.route('**/site-language/translate*', route => {
    translationAttempted = true;
    return route.abort();
  });
  await page.addInitScript(() => {
    class DeniedSpeechRecognition {
      start() { queueMicrotask(() => { this.onerror?.({error:'not-allowed'}); this.onend?.(); }); }
      stop() {}
      abort() {}
    }
    Object.defineProperty(window, 'SpeechRecognition', {value:DeniedSpeechRecognition, configurable:true});
  });
  return () => assert.equal(translationAttempted, false, 'QA must not request translation');
}

async function verifyVoiceFallback(page, route, name) {
  let field;
  if (route.input) field = page.locator(route.input);
  else {
    await page.getByRole('button', {name:'Open navigation',exact:true}).click();
    field = page.getByRole('navigation', {name:'Public navigation'}).getByRole('searchbox', {name:'Search navigation'});
  }
  const parent = field.locator('..');
  await field.fill(route.query || 'Drafting');
  const value = await field.inputValue();
  await parent.locator('button.voice-search-mic').click();
  const feedback = parent.locator('.voice-search-status.is-visible');
  await feedback.waitFor({state:'visible'});
  assert.equal(await feedback.innerText(), 'Microphone access is unavailable. Check your permissions or type your search.', name + ': permission-specific fallback');
  assert.equal(await feedback.getAttribute('role'), 'status', name + ': missing voice status semantics');
  assert.equal(await feedback.getAttribute('aria-atomic'), 'true', name + ': incomplete announcement');
  const mic = parent.locator('button.voice-search-mic');
  const statusId = await feedback.getAttribute('id');
  assert.ok(statusId, name + ': status has no id');
  assert.equal(await mic.getAttribute('aria-describedby'), statusId, name + ': microphone status not linked');
  assert.equal(await mic.getAttribute('aria-pressed'), 'false', name + ': microphone remains active after denial');
  assert.equal(await field.inputValue(), value, name + ': permission denial changed query');
  await assertSharedSearchGeometry(field, name, true);
  await parent.getByRole('button', {name:'Clear search',exact:true}).click();
  assert.equal(await field.inputValue(), '', name + ': typed fallback clear');
  assert.ok(await field.evaluate(el => el === document.activeElement), name + ': typed fallback focus');
  if (!route.input) await field.press('Escape');
}

async function verifySupport(page, name, width, height) {
  const dock = page.locator('.wc-langbar');
  const chip = dock.locator('.wc-chip');
  const panel = dock.locator('.wc-panel');
  const field = dock.getByRole('combobox', {name:'Search language'});
  const assertBounds = async () => {
    await page.waitForFunction(() => {
      const el = document.querySelector('.wc-langbar');
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const v = window.visualViewport;
      const x = v?.offsetLeft || 0, y = v?.offsetTop || 0;
      return r.width > 0 && r.height > 0 && r.left >= x-2 && r.top >= y-2
        && r.right <= x+(v?.width || document.documentElement.clientWidth)+2
        && r.bottom <= y+(v?.height || document.documentElement.clientHeight)+2;
    }, null, {timeout:5000});
  };
  await chip.waitFor({state:'visible'});
  await chip.click();
  await field.waitFor({state:'visible'});
  await assertBounds();
  await field.fill('zzzzzzzz');
  await dock.getByText('No language matches that.', {exact:true}).waitFor({state:'visible'});
  await dock.getByRole('button', {name:'Clear search',exact:true}).click();
  assert.equal(await field.inputValue(), '', name + ': language query clear');
  assert.ok(await field.evaluate(el => el === document.activeElement), name + ': language clear focus');
  await field.press('ArrowDown');
  assert.ok(await field.evaluate(el => !!document.getElementById(el.getAttribute('aria-activedescendant') || '')), name + ': missing active language');
  if (height >= 390) {
    // Resizing is only a keyboard-size approximation; no native IME claim.
    await page.setViewportSize({width,height:Math.max(220,Math.floor(height*.6))});
    try { await assertBounds(); }
    finally { await page.setViewportSize({width,height}); }
  }
  await page.evaluate(() => { document.documentElement.lang = 'ar'; document.documentElement.dir = 'rtl'; });
  try {
    await assertBounds();
    await page.waitForFunction(() => {
      const r = document.querySelector('.wc-langbar')?.getBoundingClientRect();
      const v = window.visualViewport;
      return !!r && r.left - (v?.offsetLeft || 0) <= 22;
    }, null, {timeout:5000});
  } finally { await page.evaluate(() => { document.documentElement.lang = 'en'; document.documentElement.dir = 'ltr'; }); }
  await field.press('Escape');
  await panel.waitFor({state:'hidden'});
  assert.ok(await chip.evaluate(el => el === document.activeElement), name + ': language Escape focus');
  await chip.click();
  await field.fill('en');
  // A synthesized click tests the activation path used by assistive
  // technologies. English is a local reset, not a translation request.
  await dock.getByRole('option', {name:/English/}).evaluate(el => el.click());
  await panel.waitFor({state:'hidden'});
  assert.ok(await chip.evaluate(el => el === document.activeElement), name + ': language activation focus');
  await page.evaluate(() => window.scrollTo(0,document.documentElement.scrollHeight));
  await assertBounds();
  if (width <= 767) {
    await page.waitForFunction(() => {
      const pill = document.querySelector('.wc-pill')?.getBoundingClientRect();
      const footer = document.querySelector('footer.ft-footer')?.getBoundingClientRect();
      const header = document.querySelector('header.hdr')?.getBoundingClientRect();
      if (!pill || !footer || !header) return false;
      // A tall footer and short visible viewport can make both clearances
      // impossible. Require footer clearance whenever there is room for it.
      return footer.top < header.bottom + 12 + pill.height + 16 || pill.bottom <= footer.top - 14;
    }, null, {timeout:5000});
  }
  await page.screenshot({path:join(output,name+'-support.png')});
}

const results = [];
for (const engine of engineNames) {
const browser = await playwright[engine].launch({headless: true});
try {
  for (const [device, width, height, touch, reducedMotion = 'no-preference'] of matrix) {
    const context = await browser.newContext({viewport: {width, height}, hasTouch: touch, deviceScaleFactor: 1, reducedMotion, ...(interactionsOnly ? {serviceWorkers:'block'} : {})});
    try {
      for (const route of selectedRoutes) {
        const page = await context.newPage();
        const name = engine + '-' + device + '-' + route.name;
        try {
          const assertNoTranslation = interactionsOnly ? await installInteractionFixtures(page) : null;
          if (route.path === '/' && normalizedRoute && !menuOnly && !baselineOnly && !interactionsOnly) await installHeroTrace(page);
          const response = await page.goto(new URL(route.path, origin).href, {waitUntil: 'domcontentloaded', timeout: 30000});
          assert.ok(response && response.ok(), name + ': non-success response');
          await page.locator('h1').first().waitFor({state: 'attached'});
          await page.evaluate(() => document.fonts.ready);
          const dimensions = await page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth,
          }));
          assert.ok(dimensions.scroll <= dimensions.width + 2, name + ': horizontal page overflow ' + JSON.stringify(dimensions));

          if (interactionsOnly) {
            await verifyVoiceFallback(page, route, name);
            if (route.path === '/') await verifySupport(page, name, width, height);
            assertNoTranslation();
            results.push({engine, device, width, height, reducedMotion, path: route.path, status: 'pass'});
            continue;
          }

          if (baselineOnly) {
            const meta = page.locator('meta[name="viewport"]');
            assert.equal(await meta.count(), 1, name + ': viewport meta count');
            const viewport = (await meta.getAttribute('content')) || '';
            assert.match(viewport, /viewport-fit=cover/, name + ': missing safe-area viewport');
            assert.doesNotMatch(viewport, /user-scalable\s*=\s*no|maximum-scale\s*=\s*1(?:[.,\s]|$)/i, name + ': zoom disabled');
            assert.equal(await page.locator('header.hdr').count(), 1, name + ': shared header');
            assert.equal(await page.locator('footer.ft-footer').count(), 1, name + ': shared footer');
            assert.equal(await page.locator('.public-share').count(), 1, name + ': shared action rail');
            assert.equal(await page.locator('details.wc-policy').count(), route.path === '/' ? 0 : 1, name + ': policy count');
            const chrome = await page.evaluate(() => ({
              insets: [...document.querySelectorAll('.public-action-tail,.ft-in')].map(el => [getComputedStyle(el).paddingLeft,getComputedStyle(el).paddingRight]),
              tagline: getComputedStyle(document.querySelector('.ft-tagline')).fontSize,
            }));
            assert.equal(chrome.tagline, width < 768 ? '18px' : '16px', name + ': footer typography');
            assert.ok(chrome.insets.length >= 2, name + ': missing shared gutter');
            for (const [left,right] of chrome.insets) assert.ok(parseFloat(left) >= (width < 768 ? 16 : 24) && parseFloat(right) >= (width < 768 ? 16 : 24), name + ': shared gutter');
            await page.screenshot({path: join(output, name + '-baseline.png')});
            results.push({engine, device, width, height, reducedMotion, path: route.path, status: 'pass'});
            continue;
          }
          if (menuOnly) {
            await verifyMenu(page, name, width, height, touch);
            results.push({engine, device, width, height, reducedMotion, path: route.path, status: 'pass'});
            continue;
          }

          // Home is the reference. Check actual text bounds, not just document
          // scrollWidth, since overflow clipping can hide otherwise unreadable text.
          if (route.path === '/') {
            assert.equal(await page.locator('main.home-shell').count(), 1, name + ': Home landmark');
            assert.equal(await page.locator('h1').count(), 1, name + ': Home h1 count');
            const frame = page.locator('.home-head-line');
            assert.match(await frame.innerText(), /Everyday\s+AI,\s+built\s+for/, name + ': hero copy');
            const textFits = async locator => locator.evaluate(el => {
              const container = el.closest('.home-hero, .cb-panel') || el;
              const bounds = container.getBoundingClientRect();
              const range = document.createRange();
              range.selectNodeContents(el);
              return [...range.getClientRects()].filter(rect => rect.width > 0).every(rect =>
                rect.left >= bounds.left - 2 && rect.right <= bounds.right + 2
                && rect.left >= -2 && rect.right <= document.documentElement.clientWidth + 2);
            });
            assert.ok(await textFits(frame), name + ': clipped hero frame');
            const active = page.locator('.home-head .rp-cyc-word.on');
            await active.waitFor({state: 'visible'});
            const assertActiveFits = async () => {
              await active.evaluate(async el => {
                const cycle = el.closest('.rp-cycle');
                if (cycle) await Promise.all(cycle.getAnimations().map(animation => animation.finished.catch(() => undefined)));
              });
              assert.ok(await textFits(active), name + ': clipped rotating word');
            };
            await assertActiveFits();
            if (normalizedRoute) {
              const words = (await page.locator('.home-head .rp-cyc-word').allTextContents()).map(word => word.trim());
              assert.equal(words.length, 4, name + ': Home word inventory');
              const rotation = await verifyHeroRotation(page, words, reducedMotion === 'reduce');
              assert.deepEqual(rotation.issues, [], name + ': continuous headline rotation');
              const geometry = await page.locator('.home-head .rp-cyc-word').evaluateAll(nodes => nodes.map(node => {
                const bounds = node.closest('.rp-cycle').getBoundingClientRect();
                const range = document.createRange();
                range.selectNodeContents(node);
                return [...range.getClientRects()].filter(rect => rect.width > 0).every(rect =>
                  rect.left >= Math.max(bounds.left, 0) - 2 && rect.right <= Math.min(bounds.right, document.documentElement.clientWidth) + 2);
              }));
              assert.ok(geometry.every(Boolean), name + ': clipped rotating word');
            }
            const cta = page.locator('.home-close-cta');
            await cta.scrollIntoViewIfNeeded();
            assert.equal(await cta.getAttribute('href'), '/contact/', name + ': closing destination');
            assert.ok(await textFits(cta), name + ': clipped closing action');
            const ctaBox = await cta.boundingBox();
            assert.ok(ctaBox && ctaBox.height >= 44 && ctaBox.width >= 44, name + ': closing touch target');
            // Read-only navigation and illustration interactions, no account,
            // checkout, contribution or WhatsApp submissions.
            if (width >= 280) {
              await verifyMenu(page, name, width, height, touch);
              const playback = page.locator('.wt-play');
              await playback.waitFor({state: 'visible'});
              const before = await playback.getAttribute('aria-label');
              await playback.click();
              await page.waitForFunction(previous => document.querySelector('.wt-play')?.getAttribute('aria-label') !== previous, before);
              if (reducedMotion === 'reduce') await playback.click(); // restore paused preference
            }
            await page.evaluate(() => window.scrollTo(0, 0));
          }

          // Verify the actual rendered eyebrow, not only source prop text.
          const eyebrow = page.locator('.rh-eyebrow .brand-badge');
          if (route.eyebrow === null) {
            assert.equal(await page.locator('.brand-badge').count(), 0, name + ': duplicate home brand badge');
          } else {
            await eyebrow.waitFor({state: 'visible'});
            assert.equal(await eyebrow.count(), 1, name + ': expected one hero eyebrow');
            assert.equal((await eyebrow.innerText()).replace(/\s+/g, ' ').trim(), route.eyebrow,
              name + ': incorrect eyebrow identity');
            const layout = await eyebrow.evaluate(el => {
              const style = getComputedStyle(el);
              const box = el.getBoundingClientRect();
              const label = el.querySelector('.brand-badge-label');
              const mark = el.querySelector('svg');
              const parent = el.parentElement.getBoundingClientRect();
              const labelBox = label?.getBoundingClientRect();
              const markBox = mark?.getBoundingClientRect();
              const labelStyle = label && getComputedStyle(label);
              return {
                background: style.backgroundColor, ink: style.color,
                fontSize: labelStyle?.fontSize, lineHeight: labelStyle?.lineHeight,
                weight: labelStyle?.fontWeight,
                markHeight: markBox?.height,
                centerOffset: labelBox && markBox ? Math.abs((labelBox.top + labelBox.bottom - markBox.top - markBox.bottom) / 2) : Infinity,
                leftInset: markBox && labelBox ? Math.min(markBox.left, labelBox.left) - box.left : Infinity,
                rightInset: markBox && labelBox ? box.right - Math.max(markBox.right, labelBox.right) : Infinity,
                topInset: markBox && labelBox ? Math.min(markBox.top, labelBox.top) - box.top : Infinity,
                bottomInset: markBox && labelBox ? box.bottom - Math.max(markBox.bottom, labelBox.bottom) : Infinity,
                fits: box.left >= -1 && box.right <= document.documentElement.clientWidth + 1
                  && box.width <= parent.width + 1 && !!label && label.scrollWidth <= label.clientWidth + 1,
                mark: !!mark && mark.getBoundingClientRect().width > 0,
              };
            });
            assert.equal(layout.background, 'rgb(209, 244, 112)', name + ': eyebrow fill');
            assert.equal(layout.ink, 'rgb(26, 58, 42)', name + ': eyebrow ink');
            assert.ok(layout.fits && layout.mark, name + ': eyebrow reflow ' + JSON.stringify(layout));
            assert.equal(layout.fontSize, width >= 768 ? '18px' : '17px', name + ': eyebrow text too small');
            assert.equal(layout.weight, '650', name + ': eyebrow font weight');
            assert.ok(Math.abs(layout.markHeight - parseFloat(layout.lineHeight)) <= 1, name + ': logo must track text line height');
            assert.ok(layout.centerOffset <= 1, name + ': logo/text vertical alignment ' + JSON.stringify(layout));
            assert.ok(Math.abs(layout.leftInset - 10) <= 1 && Math.abs(layout.rightInset - 10) <= 1
              && Math.abs(layout.topInset - 5) <= 1 && Math.abs(layout.bottomInset - 5) <= 1,
              name + ': unequal or excessive eyebrow padding ' + JSON.stringify(layout));
            const wrapper = eyebrow.locator('..');
            if (reducedMotion === 'no-preference') {
              await page.locator('.rh-layout.is-armed.show').first().waitFor({state: 'attached'});
              const motion = await wrapper.evaluate(async el => {
                const style = getComputedStyle(el);
                const initial = {name: style.animationName, duration: style.animationDuration, iterations: style.animationIterationCount};
                await Promise.all(el.getAnimations().map(animation => animation.finished));
                return {...initial, settledOpacity: getComputedStyle(el).opacity};
              });
              assert.match(motion.name, /rh-eyebrow-enter/, name + ': missing shared entrance');
              assert.equal(motion.duration, '0.32s', name + ': unexpected entrance duration');
              assert.equal(motion.iterations, '1', name + ': eyebrow must not loop');
              assert.equal(motion.settledOpacity, '1', name + ': eyebrow did not finish fully visible');
            } else {
              const motion = await wrapper.evaluate(el => ({name: getComputedStyle(el).animationName, opacity: getComputedStyle(el).opacity, transform: getComputedStyle(el).transform}));
              assert.deepEqual(motion, {name: 'none', opacity: '1', transform: 'none'}, name + ': reduced-motion eyebrow must be static');
            }
          }

          // Policy is present once on each content page, except Home.
          const policies = page.locator('details.wc-policy');
          assert.equal(await policies.count(), route.path === '/' ? 0 : 1,
            name + ': missing or duplicate Policy details');
          if (route.path !== '/') {
            assert.equal((await policies.locator('summary').innerText()).trim(), 'Policy details',
              name + ': incorrect policy summary');
          }

          const tagline = page.locator('.ft-tagline');
          assert.equal(await tagline.count(), 1, name + ': missing or duplicated footer tagline');
          const footerType = await tagline.evaluate(el => {
            const style = getComputedStyle(el);
            const box = el.getBoundingClientRect();
            return {
              fontSize: style.fontSize,
              fits: box.left >= -1 && box.right <= document.documentElement.clientWidth + 1
                && el.scrollWidth <= el.clientWidth + 1,
            };
          });
          assert.equal(footerType.fontSize, width < 768 ? '18px' : '16px', name + ': footer tagline size');
          assert.ok(footerType.fits, name + ': footer tagline overflow');

          if (route.name === 'terms' || route.name === 'privacy') {
            const headings = await page.locator('.lgd-h2, .lgd-h3').evaluateAll(elements => elements.map(heading => {
              const number = heading.querySelector('.lgd-num');
              const title = heading.querySelector('.lgd-heading-text');
              if (!number || !title) return {ok: false, text: heading.textContent};
              const n = number.getBoundingClientRect();
              const t = title.getBoundingClientRect();
              const style = getComputedStyle(heading);
              return {
                text: heading.textContent,
                ok: t.left - n.right >= 7 && style.fontStyle === 'normal'
                  && getComputedStyle(title).fontStyle === 'normal'
                  && style.transform === 'none'
                  && heading.textContent.startsWith(number.textContent + ' ')
                  && number.scrollWidth <= number.clientWidth + 1,
                titleOffset: t.left - heading.getBoundingClientRect().left,
              };
            }));
            assert.equal(headings.length, route.name === 'terms' ? 65 : 40, name + ': missing legal headings');
            for (const heading of headings) {
              assert.ok(heading.ok, name + ': number spacing or heading style ' + JSON.stringify(heading));
              assert.ok(Math.abs(heading.titleOffset - headings[0].titleOffset) <= 1,
                name + ': inconsistent title column ' + JSON.stringify(heading));
            }
          }
          await page.screenshot({path: join(output, name + '.png')});
          if (route.input) {
            const field = page.locator(route.input);
            const clear = field.locator('..').getByRole('button', {name: 'Clear search', exact: true});
            await field.fill(route.query);
            await clear.waitFor({state: 'visible', timeout: 10000});
            if (route.name === 'terms' || route.name === 'privacy') {
              await page.getByRole('list', {name: 'Matching clauses'}).getByRole('link').first().waitFor({state: 'visible'});
            }
            await page.screenshot({path: join(output, name + '-search.png')});
            const inputBox = await field.boundingBox();
            const clearBox = await clear.boundingBox();
            assert.ok(inputBox && clearBox && clearBox.width >= 44 && clearBox.height >= 44,
              name + ': missing or undersized clear target');
            await assertSharedSearchGeometry(field, name);
            await clear.click();
            assert.equal(await field.inputValue(), '');
            assert.ok(await field.evaluate(el => el === document.activeElement), name + ': focus not restored');
            await field.fill(route.query);
            await field.press('Escape');
            assert.equal(await field.inputValue(), '');
            await clear.waitFor({state: 'hidden'});
          }
          results.push({engine, device, width, height, reducedMotion, path: route.path, status: 'pass'});
        } catch (error) {
          results.push({engine, device, width, height, reducedMotion, path: route.path, status: 'fail', error: String(error)});
          await page.screenshot({path: join(output, name + '-failure.png')}).catch(() => {});
        } finally {
          await page.close();
        }
      }
    } finally {
      await context.close();
    }
  }
} finally {
  await browser.close();
}
}
console.log(JSON.stringify({origin: origin.origin, route: normalizedRoute, engines: engineNames, output, results}, null, 2));
if (results.some(result => result.status !== 'pass')) process.exitCode = 1;
