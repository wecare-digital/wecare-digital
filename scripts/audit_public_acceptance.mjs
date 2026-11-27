#!/usr/bin/env node
/**
 * Read-only acceptance on a deployed public revision. Fresh anonymous contexts;
 * intercept every non-read HTTP method. No account, OTP, payment, or message send.
 * Lab timings in headless browsers are evidence, not field Core Web Vitals.
 */
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import * as playwright from 'playwright';
import { AxeBuilder } from '@axe-core/playwright';

import { installHeroTrace, verifyHeroRotation } from './public_hero_audit.mjs';
import { canonicalOrigin, qaOrigin, pathOf, verifyAuthGate } from './public_qa_origin.mjs';

const {origin, snapshot} = qaOrigin();
const engine = process.env.PUBLIC_QA_ENGINE || 'chromium';
if (!['chromium', 'firefox', 'webkit'].includes(engine)) throw new Error('Unsupported engine');
const profiles = {
  desktop: { width: 1440, height: 900, hasTouch: false },
  phone: { width: 390, height: 844, hasTouch: true },
  tablet: { width: 768, height: 1024, hasTouch: true },
  fold: { width: 280, height: 653, hasTouch: true },
  landscape: { width: 844, height: 390, hasTouch: true },
  stress: { width: 160, height: 640, hasTouch: true, reducedMotion: 'reduce' },
  wide: { width: 2560, height: 1440, hasTouch: false },
};
const profileName = process.env.PUBLIC_QA_PROFILE || 'desktop';
const profile = profiles[profileName];
if (!profile) throw new Error('Unknown viewport profile');
const out = process.env.PUBLIC_QA_OUTPUT || join(tmpdir(), 'wecare-public-acceptance');
await mkdir(out, { recursive: true });
const { pages } = JSON.parse(await readFile(new URL('../config/public-pages.json', import.meta.url), 'utf8'));
const routes = pages.map(p => ({ path: pathOf(p.path), name: p.name, kind: ['/orders/', '/elsewhere/arogya-yatra/'].includes(pathOf(p.path)) ? 'gated' : 'indexable' }));
for (const path of ['/get-kosh/', '/udyam-bids/', '/auth/', '/checkout/', '/checkout/status/', '/checkout/success/']) {
  routes.push({ path, name: path, kind: 'noindex' });
}
const inventoryIssues = [];
// Hash the deployed Home build identifier and static asset references. A stable
// fingerprint is evidence against mid-run changes, not a mapping to a Git SHA.
async function deploymentFingerprint() {
  const res = await fetch(origin, {redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(15000)});
  if (!res.ok) throw new Error('Home fingerprint HTTP ' + res.status);
  const html = await res.text();
  const data = html.match(/<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  const buildId = data ? JSON.parse(data[1]).buildId : null;
  const assets = [...new Set([...html.matchAll(/(?:src|href)="([^"\s]*\/_next\/static\/[^"\s]+)"/g)].map(m => m[1]))].sort();
  if (!buildId || !assets.length) throw new Error('No Next build ID/assets in Home');
  return {buildId, hash: createHash('sha256').update(JSON.stringify(assets)).digest('hex')};
}
let startFingerprint = null;
try { startFingerprint = await deploymentFingerprint(); } catch (e) { inventoryIssues.push('Deployment fingerprint unavailable: ' + e.message); }
try {
  const response = await fetch(new URL('/sitemap.xml', origin), { redirect: 'error', signal: AbortSignal.timeout(15000) });
  if (!response.ok) throw new Error('sitemap HTTP ' + response.status);
  const xml = await response.text();
  // Accept only actual same-origin canonical content URLs, never a session
  // link or untrusted arbitrary destination. Representative template coverage.
  const urls = [...xml.matchAll(/<loc>\s*([^<]+)\s*<\/loc>/g)].flatMap(match => {
    try {
      const u = new URL(match[1].trim());
      return u.origin === canonicalOrigin.origin && !u.search && !u.hash ? [pathOf(u.pathname)] : [];
    } catch { return []; }
  });
  for (const [name, pattern] of [
    ['Blog article', /^\/post\/[^/]+\/$/],
    ['Shop detail', /^\/shop\/(?!page\/)[^/]+\/$/],
    ['Blog pagination', /^\/blog\/page\/[1-9]\d*\/$/],
    ['Shop pagination', /^\/shop\/page\/[1-9]\d*\/$/],
  ]) {
    const path = urls.find(p => pattern.test(p));
    if (path) routes.push({ path, name, kind: 'indexable', sample: true });
    else if (name === 'Blog article' || name === 'Shop detail') inventoryIssues.push(name + ': no sample found in sitemap');
  }
  for (const route of routes.filter(r => r.kind !== 'noindex' && !r.sample)) {
    if (!urls.includes(route.path)) inventoryIssues.push(route.path + ': missing from sitemap');
  }
} catch (error) { inventoryIssues.push('Sitemap could not be read: ' + error.message); }
try {
  const robots = await fetch(new URL('/robots.txt', origin), { redirect: 'error', signal: AbortSignal.timeout(15000) });
  if (!robots.ok) inventoryIssues.push('robots.txt HTTP ' + robots.status);
  else if (!(await robots.text()).includes('Sitemap:')) inventoryIssues.push('robots.txt has no Sitemap declaration');
} catch (error) { inventoryIssues.push('robots.txt could not be read: ' + error.message); }

const browser = await playwright[engine].launch({ headless: true });
const report = {
  origin: origin.origin, mode: snapshot ? 'immutable-export' : 'live-observation', engine, browser: browser.version(), profile: profileName, viewport: profile,
  revisionLabel: process.env.PUBLIC_QA_REVISION || null, startFingerprint, endFingerprint: null, inventoryIssues, results: [],
  limitations: ['Anonymous public HTML only; protected routes need authorized fixtures.',
    'Writes blocked, service workers disabled, no user transactions.',
    'Axe automated rules do not certify WCAG; keyboard, native devices and screen readers require manual evidence.',
    'Lab LCP and CLS are not field p75; INP needs real interaction or field data.',
    'Immutable export mode blocks external resources; it does not measure production latency or verify live integrations.',
    'Dynamic URLs are representative sitemap samples, not an exhaustive article crawl.'],
};
async function save() {
  await writeFile(join(out, 'report.json'), JSON.stringify(report, null, 2) + '\n');
}
await save();

try {
  for (const route of routes) {
    const context = await browser.newContext({
      viewport: { width: profile.width, height: profile.height },
      hasTouch: profile.hasTouch, reducedMotion: profile.reducedMotion || 'no-preference',
      deviceScaleFactor: 1, serviceWorkers: 'block', ignoreHTTPSErrors: snapshot,
    });
    const page = await context.newPage();
    const result = { ...route, status: 'unverified', failures: [], notes: [], metrics: {}, words: [], samples: [] };
    report.results.push(result);
    try {
      if (typeof context.routeWebSocket === 'function') await context.routeWebSocket('**/*', socket => socket.close());
      await context.route('**/*', route => {
        const req = route.request(), url = new URL(req.url());
        if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method())) return route.abort();
        if (snapshot && url.origin !== origin.origin) return route.abort();
        if (snapshot && url.pathname === '/auth/state') {
          return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
            phase:'phone',csrf:'qa-csrf',message:'',website:true,returnPath:url.searchParams.get('return')||'/',clientName:'WECARE.DIGITAL'
          })});
        }
        return route.continue();
      });
      await page.addInitScript(() => {
        const metrics = { lcpMs: null, cls: null, longTaskMs: null };
        Object.defineProperty(window, '__wcPublicAuditMetrics', { value: metrics });
        const observe = (type, callback) => {
          if (!window.PerformanceObserver?.supportedEntryTypes?.includes(type)) return;
          const observer = new PerformanceObserver(list => list.getEntries().forEach(callback));
          observer.observe({ type, buffered: true });
        };
        observe('largest-contentful-paint', entry => { metrics.lcpMs = entry.startTime; });
        let session = 0, start = 0, last = 0, max = 0;
        observe('layout-shift', entry => {
          if (entry.hadRecentInput) return;
          if (entry.startTime - last > 1000 || entry.startTime - start > 5000) {
            session = 0;
            start = entry.startTime;
          }
          session += entry.value;
          last = entry.startTime;
          max = Math.max(max, session);
          metrics.cls = max;
        });
        if (window.PerformanceObserver?.supportedEntryTypes?.includes('layout-shift')) metrics.cls = 0;
        if (window.PerformanceObserver?.supportedEntryTypes?.includes('longtask')) metrics.longTaskMs = 0;
        observe('longtask', entry => { metrics.longTaskMs += entry.duration; });
      });
      await installHeroTrace(page);
      const response = await page.goto(new URL(route.path, origin).href, { waitUntil: 'domcontentloaded', timeout: 30000 });
      if (!response?.ok()) throw new Error('HTTP ' + (response?.status() || 'no response'));
      if (route.kind === 'gated') {
        // Gate before evaluating the document; hydration intentionally changes
        // the execution context. Require the exact same-origin return path.
        await verifyAuthGate(page, origin, route.path);
        result.status = 'gated';
        result.notes.push('Expected sign-in redirect verified; protected content requires authenticated fixtures.');
        await page.screenshot({path:join(out,route.path.replace(/[^a-z0-9]+/gi,'-').replace(/^-|-$/g,'')+'-gate.png'),timeout:10000});
        continue;
      }
      await page.waitForLoadState('load', { timeout: 12000 }).catch(() => result.notes.push('load event timed out'));
      await page.evaluate(() => Promise.race([document.fonts.ready, new Promise(resolve => setTimeout(resolve, 5000))]));
      const actual = new URL(page.url());
      if (actual.origin !== origin.origin || pathOf(actual.pathname) !== route.path) throw new Error('Unexpected route redirect');
      const metadata = await page.evaluate(() => ({
        title: document.title, descriptions: [...document.querySelectorAll('meta[name="description"]')].map(el => el.content),
        canonicals: [...document.querySelectorAll('link[rel="canonical"]')].map(el => el.href),
        robots: [...document.querySelectorAll('meta[name="robots"]')].map(el => el.content),
        lang: document.documentElement.lang,
        mainCount: document.querySelectorAll('main').length,
        h1Count: document.querySelectorAll('h1').length,
        width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
        jsonLd: [...document.querySelectorAll('script[type="application/ld+json"]')].map(el => {
          try { JSON.parse(el.textContent); return true; } catch { return false; }
        }),
      }));
      result.metadata = metadata;
      if (!metadata.title.trim() || !metadata.lang) result.failures.push('Missing title or document language');
      if (metadata.mainCount !== 1 || metadata.h1Count !== 1) result.failures.push('Expected one main and one h1');
      if (metadata.scrollWidth > metadata.width + 2) {
        result.failures.push('Horizontal page overflow');
        result.overflowTargets = await page.evaluate(() => [...document.querySelectorAll('body *')].flatMap(el => {
          const r = el.getBoundingClientRect(), style = getComputedStyle(el);
          if (!r.width || !r.height || style.visibility === 'hidden' || style.display === 'none') return [];
          if (r.right <= document.documentElement.clientWidth + 2 && r.left >= -2) return [];
          // Exclude intentional scrolling and decorative clips; record candidates
          // rather than asserting all candidates cause document overflow.
          if (el.closest('[aria-hidden="true"]')) return [];
          return [{tag: el.tagName.toLowerCase(), id: el.id || undefined,
            classes: typeof el.className === 'string' ? el.className.split(/\s+/).slice(0, 4) : [],
            left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width)}];
        }).sort((a,b) => b.right-a.right).slice(0,25));
      }
      if (metadata.jsonLd.some(valid => !valid)) result.failures.push('Invalid JSON-LD');
      const noindex = metadata.robots.some(value => /\bnoindex\b/i.test(value));
      if (route.kind === 'noindex') {
        if (!noindex) result.failures.push('Expected noindex');
      } else {
        if (noindex) result.failures.push('Unexpected noindex');
        if (metadata.descriptions.length !== 1 || !metadata.descriptions[0]?.trim()) result.failures.push('Missing or duplicate description');
        if (metadata.canonicals.length !== 1 || metadata.canonicals[0] !== new URL(route.path, canonicalOrigin).href) result.failures.push('Unexpected canonical');
      }
      const hero = page.locator('h1.home-head, h1.rh-head');
      if (await hero.count() !== 1) throw new Error('Missing or duplicated shared hero');
      const pill = page.locator('h1.home-head .rp-mark, h1.rh-head .rp-mark, .rh-decoration .rp-mark');
      if (await pill.count() !== 1) throw new Error('Missing or duplicated shared hero pill');
      const words = pill.locator('.rp-cyc-word');
      result.words = (await words.allTextContents()).map(value => value.trim());
      result.frame = (await hero.locator('.home-head-line, .rh-head-line').allTextContents()).join(' ').trim() || (await hero.innerText()).trim();
      if (!result.frame || !result.words.length || result.words.some(word => !word) || new Set(result.words).size !== result.words.length) {
        result.failures.push('Missing or duplicated hero copy');
      }
      const frameFits = await hero.evaluate(el => {
        const bounds = el.getBoundingClientRect();
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
          if (!node.textContent.trim() || node.parentElement?.closest('.rp-mark')) continue;
          const range = document.createRange();
          range.selectNodeContents(node);
          if ([...range.getClientRects()].some(r => r.width > 0
            && (r.left < Math.max(bounds.left, 0) - 2
              || r.right > Math.min(bounds.right, document.documentElement.clientWidth) + 2))) return false;
        }
        return true;
      });
      if (!frameFits) result.failures.push('Clipped fixed hero headline');
      const rotation = await verifyHeroRotation(page, result.words, profile.reducedMotion === 'reduce');
      result.rotationTrace = rotation.trace;
      result.failures.push(...rotation.issues);
      // Every word shares one intrinsic grid cell, so even words no longer
      // active can be measured after fonts settle. Compensate for the inactive
      // word's decorative vertical transform without changing its styles.
      result.samples = await pill.evaluate(mark => {
        const cycle = mark.querySelector('.rp-cycle');
        const bounds = cycle.getBoundingClientRect(), markBounds = mark.getBoundingClientRect();
        return [...cycle.querySelectorAll('.rp-cyc-word')].map(word => {
          const range = document.createRange();
          range.selectNodeContents(word);
          const transform = getComputedStyle(word).transform;
          const shift = transform === 'none' ? 0 : new DOMMatrixReadOnly(transform).m42;
          const textFits = [...range.getClientRects()].filter(r => r.width > 0).every(r =>
            r.left >= Math.max(bounds.left, markBounds.left, 0) - 2
            && r.right <= Math.min(bounds.right, markBounds.right, document.documentElement.clientWidth) + 2
            && r.top - shift >= bounds.top - 1 && r.bottom - shift <= bounds.bottom + 1);
          const rects = [...range.getClientRects()].filter(r => r.width > 0);
          const clip = {
            left: Math.min(...rects.map(r => r.left - bounds.left)),
            right: Math.min(...rects.map(r => bounds.right - r.right)),
            top: Math.min(...rects.map(r => r.top - shift - bounds.top)),
            bottom: Math.min(...rects.map(r => bounds.bottom - r.bottom + shift)),
            overflowX: getComputedStyle(cycle).overflowX, overflowY: getComputedStyle(cycle).overflowY,
            lineHeight: getComputedStyle(word).lineHeight,
          };
          return {word: word.textContent.trim(), height: markBounds.height, textFits, clip};
        });
      });
      for (const sample of result.samples) {
        if (!sample.textFits) result.failures.push('Clipped hero word: ' + sample.word);
      }
      if (rotation.issues.some(issue => issue.includes('did not continue'))) result.notes.push('Headline rotation did not continue beyond its first cycle.');
      if (result.words.length > 1) result.notes.push('Visually review balanced wording and screen-reader behavior separately.');
      const axe = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
      result.axe = {
        // Record selector targets, not HTML, inputs or customer data. The
        // anonymous context and blocked writes remain mandatory.
        violations: axe.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, targets: v.nodes.slice(0, 30).map(n => n.target) })),
        incomplete: axe.incomplete.map(v => ({ id: v.id, nodes: v.nodes.length, targets: v.nodes.slice(0, 30).map(n => n.target) })),
      };
      if (axe.violations.length) result.failures.push('Automated accessibility violations: ' + axe.violations.map(v => v.id).join(', '));
      result.metrics = await page.evaluate(() => {
        const nav = performance.getEntriesByType('navigation')[0];
        return { ...window.__wcPublicAuditMetrics, ttfbMs: nav?.responseStart ?? null, domContentLoadedMs: nav?.domContentLoadedEventEnd ?? null };
      });
      // Timing observations are not pass/fail field Core Web Vitals.
      const file = route.path.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'home';
      await page.screenshot({ path: join(out, file + '.png'), timeout: 10000 });
      result.status = result.failures.length ? 'fail' : 'automated-pass';
    } catch (error) {
      result.failures.push(String(error.message || error).slice(0, 500));
      result.status = 'fail';
    } finally {
      console.log(JSON.stringify({ path: route.path, status: result.status, failures: result.failures, metrics: result.metrics, overflowTargets: result.overflowTargets, axeTargets: result.axe?.violations, clippedWords: result.samples.filter(s => !s.textFits) }));
      await context.close();
      await save();
    }
  }
} finally { await browser.close(); }
const signatures = new Map();
for (const result of report.results.filter(r => r.kind === 'indexable' && !r.sample && r.frame && r.words.length)) {
  const key = JSON.stringify([result.frame, result.words]);
  const previous = signatures.get(key);
  if (previous) {
    result.notes.push('Identical hero copy to ' + previous + '; editorial review needed');
  } else signatures.set(key, result.path);
}
try {
  report.endFingerprint = await deploymentFingerprint();
  if (JSON.stringify(startFingerprint) !== JSON.stringify(report.endFingerprint)) inventoryIssues.push('Deployment changed during this run; do not accept mixed revisions');
} catch (e) { inventoryIssues.push('Final deployment fingerprint unavailable: ' + e.message); }
await save();
const counts = report.results.reduce((all, result) => ({ ...all, [result.status]: (all[result.status] || 0) + 1 }), {});
console.log('Acceptance summary: ' + JSON.stringify({ counts, inventoryIssues, startFingerprint, endFingerprint: report.endFingerprint, revisionLabel: report.revisionLabel }));
if (inventoryIssues.length || report.results.some(result => result.status === 'fail')) process.exitCode = 1;
