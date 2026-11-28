import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { publicMenuGeometry } from '../src/lib/publicMenuGeometry.ts';

test('menu fits visible viewport in 480 width, height, direction and safe-area cases', () => {
  const widths = [160, 280, 320, 360, 375, 390, 412, 430, 720, 768, 844, 1024, 1280, 1440, 1920, 2560];
  const heights = [180, 280, 390, 844, 1440];
  let count = 0;
  for (const width of widths) for (const height of heights) for (const direction of ['ltr', 'rtl']) for (const inset of [0, 24, 44]) {
    const viewport = {left: 7, top: 13, width, height};
    const anchor = direction === 'ltr' ? {left: Math.min(width-46,240), right: Math.min(width,286), bottom: 86}
      : {left: Math.max(0,width-286), right: Math.max(46,width-240), bottom: 86};
    const a = publicMenuGeometry({viewport, anchor, headerBottom: 108+inset, direction, safeLeft: inset, safeRight: inset, safeBottom: inset});
    assert.ok(a.width > 0 && a.maxHeight > 0);
    assert.ok(a.left >= viewport.left && a.left + a.width <= viewport.left + width + .01);
    assert.ok(a.top >= viewport.top && a.top + a.maxHeight <= viewport.top + height + .01);
    assert.ok(a.columns >= 1 && a.columns <= 3);
    if (width < 768) assert.equal(a.columns, 1);
    count++;
  }
  assert.equal(count, 480);
});

test('desktop retains a 760px anchored menu; keyboard-sized viewport moves it up', () => {
  const common = {anchor: {left: 260, right: 306, bottom: 77}, headerBottom: 108, direction: 'ltr', safeLeft: 0, safeRight: 0, safeBottom: 0};
  const desktop = publicMenuGeometry({...common, viewport: {left: 0, top: 0, width: 1440, height: 900}});
  assert.equal(desktop.width, 760);
  assert.equal(desktop.left, 260);
  assert.equal(desktop.columns, 3);
  const narrow = publicMenuGeometry({...common, viewport: {left: 0, top: 0, width: 160, height: 640}});
  assert.equal(narrow.tight, true);
  const keyboard = publicMenuGeometry({...common, viewport: {left: 0, top: 0, width: 390, height: 200}});
  assert.ok(keyboard.top < common.headerBottom);
  assert.ok(keyboard.maxHeight >= 160);
});

test('shared menu reacts to visible viewport and protects deliberate keyboard focus', () => {
  const header = readFileSync(new URL('../src/components/Header.tsx', import.meta.url), 'utf8');
  for (const token of ['publicMenuGeometry(', 'window.visualViewport', "visual?.addEventListener( 'resize', syncMenuGeometry )", "visual?.addEventListener( 'scroll', syncMenuGeometry )", 'root.dataset.navTight', 'hasMenuFocus()', "root?.addEventListener( 'focusout', onFocusOut )", 'close( true )', '.hdr::before', '.hdr.is-nav-open{z-index:1400}', "data-nav-tight='true'"]) {
    assert.ok(header.includes(token), token);
  }
  assert.doesNotMatch(header, /\.hdr\{[^}]*backdrop-filter:/);
  assert.doesNotMatch(header, /onClick=\{ close \}/);
  assert.match(header, /\.nav-menu\{position:fixed;top:var\(--nav-panel-top/);
  const qa = readFileSync(new URL('../scripts/verify_public_browser.mjs', import.meta.url), 'utf8');
  assert.ok(qa.includes('PUBLIC_QA_MENU_ONLY'));
  assert.ok(qa.includes('outside focus was stolen'));
  assert.ok(qa.includes('keyboard-size stress approximation'));
});

test('public header restores original component radii and shares the Products double arrow',()=>{
  const header=readFileSync(new URL('../src/components/Header.tsx',import.meta.url),'utf8');
  const theme=readFileSync(new URL('../src/styles/public-button-theme.css',import.meta.url),'utf8');
  const tokens=readFileSync(new URL('../src/styles/tokens.css',import.meta.url),'utf8');
  assert.doesNotMatch(theme,/\.nav-(?:menu|dropdown|item|section-toggle|group-link|trigger|products-more)\b/);
  assert.match(theme,/\[data-public-search-field\][^}]*--public-hover-radius: var\(--public-search-radius\)/);
  assert.match(tokens,/--public-hover-radius: 13px;/);
  assert.match(header,/\.nav-menu\{[^}]*border-radius:24px/);
  assert.match(header,/\.nav-dropdown\[data-nav-tight='true'\] \.nav-menu\{[^}]*border-radius:14px/);
  assert.match(header,/\.nav-item\{[^}]*border-radius:var\(--public-nav-radius\)/);
  assert.match(header,/\.nav-trigger\{[^}]*border-radius:10px/);
  assert.match(header,/\.nav-trigger:hover\{[^}]*border-radius:var\(--public-hover-radius\)/);
  assert.match(header,/\.nav-group-link\{[^}]*border-radius:8px/);
  assert.match(header,/\.nav-products-more\{[^}]*border-radius:50%;background:var\(--public-brand-lime\)/);
  assert.match(header,/className="nav-products-more-icon"\s+viewBox=\{ ROW_CHEVRON_VIEW_BOX \}[^>]*>\s*<path d=\{ ROW_CHEVRON_PATH \} \/>/);
  assert.match(header,/\.nav-products-more-icon\{fill:var\(--public-nav-arrow\);stroke:none;transform:rotate\(90deg\)\}/);
  assert.match(header,/onClick=\{ scrollProductsForward \}/);
});
