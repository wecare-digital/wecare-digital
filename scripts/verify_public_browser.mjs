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

const base = process.env.PUBLIC_QA_BASE;
if (!base) throw new Error('Set PUBLIC_QA_BASE to an approved preview or public website URL.');
const origin = new URL(base);
if (!['http:', 'https:'].includes(origin.protocol)) throw new Error('HTTP(S) base required');
const output = process.env.PUBLIC_QA_OUTPUT || join(tmpdir(), 'wecare-public-qa-' + Date.now());
await mkdir(output, {recursive: true});
const { chromium } = await import('playwright').catch(() => {
  throw new Error('Install Playwright and Chromium in the QA environment; no production dependency is required.');
});
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
  {path: '/shop/', name: 'shop'},
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
const browser = await chromium.launch({headless: true});
const results = [];
try {
  for (const [device, width, height, touch, reducedMotion = 'no-preference'] of devices) {
    const context = await browser.newContext({viewport: {width, height}, hasTouch: touch, deviceScaleFactor: 1, reducedMotion});
    try {
      for (const route of routes) {
        const page = await context.newPage();
        const name = device + '-' + route.name;
        try {
          const response = await page.goto(new URL(route.path, origin).href, {waitUntil: 'domcontentloaded', timeout: 30000});
          assert.ok(response && response.ok(), name + ': non-success response');
          await page.locator('h1').first().waitFor({state: 'attached'});
          await page.evaluate(() => document.fonts.ready);
          const dimensions = await page.evaluate(() => ({
            scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth,
          }));
          assert.ok(dimensions.scroll <= dimensions.width + 2, name + ': horizontal page overflow ' + JSON.stringify(dimensions));

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
            assert.ok(clearBox.x >= inputBox.x && clearBox.x + clearBox.width <= inputBox.x + inputBox.width + 2,
              name + ': clear control overflows input');
            await clear.click();
            assert.equal(await field.inputValue(), '');
            assert.ok(await field.evaluate(el => el === document.activeElement), name + ': focus not restored');
            await field.fill(route.query);
            await field.press('Escape');
            assert.equal(await field.inputValue(), '');
            await clear.waitFor({state: 'hidden'});
          }
          results.push({device, path: route.path, status: 'pass'});
        } catch (error) {
          results.push({device, path: route.path, status: 'fail', error: String(error)});
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
console.log(JSON.stringify({output, results}, null, 2));
if (results.some(result => result.status !== 'pass')) process.exitCode = 1;
