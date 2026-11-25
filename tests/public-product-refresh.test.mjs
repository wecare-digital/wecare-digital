import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const read = path => readFileSync(path, 'utf8');
const added = [
  ['/relay-os', 'src/pages/relay-os/index.tsx'],
  ['/atmos/nano-climate', 'src/pages/atmos/nano-climate.tsx'],
  ['/atmos/green-ledger', 'src/pages/atmos/green-ledger.tsx'],
  ['/elsewhere/rail', 'src/pages/elsewhere/rail.tsx'],
  ['/elsewhere/cruise', 'src/pages/elsewhere/cruise.tsx'],
  ['/elsewhere/arogya-yatra', 'src/pages/elsewhere/arogya-yatra.tsx'],
];
const retired = [
  ['/dispatch', 'src/pages/dispatch/index.tsx'],
  ['/grahak-os', 'src/pages/grahak-os/index.tsx'],
  ['/vayulok', 'src/pages/vayulok/index.tsx'],
  ['/sehat', 'src/pages/sehat.tsx'],
];

test('new product pages and public registries agree; retired pages are absent', () => {
  const header = read('src/components/Header.tsx');
  const sitemap = read('scripts/generate-sitemap.js');
  const meta = read('src/pages/_app.tsx');
  const catalog = JSON.parse(read('config/public-pages.json')).pages;
  for (const [route, file] of added) {
    assert.ok(existsSync(file), file);
    assert.ok(header.includes("href: '" + route + "/'"), route);
    assert.ok(sitemap.includes("'" + route + "'"), route);
    assert.ok(meta.includes("'" + route + "':"), route);
    assert.ok(catalog.some(page => page.path === route), route);
  }
  for (const [route, file] of retired) {
    assert.ok(!existsSync(file), file);
    assert.ok(!header.includes("href: '" + route + "/'"), route);
    assert.ok(!sitemap.includes("'" + route + "'"), route);
    assert.ok(!meta.includes("'" + route + "':"), route);
    assert.ok(!catalog.some(page => page.path === route), route);
  }
  assert.ok(header.indexOf("label: 'Rail'") < header.indexOf("label: 'Cruise'"));
  assert.ok(header.indexOf("label: 'Cruise'") < header.indexOf("label: 'Arogya Yatra'"));
  assert.ok(!existsSync('src/pages/atmos/index.tsx'));
});

test('generated public page manifest matches source', () => {
  execFileSync(process.execPath, ['scripts/generate-public-pages.js', '--check'], { stdio: 'pipe' });
});

test('retired product URLs do not use a meta refresh or a client redirect', () => {
  const page = read('src/pages/404.tsx');
  assert.ok(!page.includes('httpEquiv="refresh"'));
  assert.ok(page.includes('!RETIRED_PRODUCT_PATHS.has( path )'));
  for (const [route] of retired) assert.ok(page.includes("'" + route + "'"));
});

test('Pause/Play control reserves a stable width and shares the title bar height', () => {
  const terminal = read('src/components/WorkflowTerminal.tsx');
  assert.ok(terminal.includes('height:47px;width:86px;box-sizing:border-box'));
  assert.ok(terminal.includes('width:76px;height:47px'));
  assert.ok(terminal.includes('font-size:16px;font-weight:500;line-height:1'));
});


test('every submenu child uses the shared bent arrow, not a product-specific glyph', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes('<path d={ SUBNAV_ICON_PATH } />'));
  assert.ok(!header.includes('NAV_ICON_PATHS[ child.label ]'));
});


test('Relay OS keeps the existing checkout identity and public label', () => {
  const page = read('src/pages/relay-os/index.tsx');
  const checkout = read('src/config/productCheckout.ts');
  assert.ok(page.includes('slug="grahak-os"'));
  assert.ok(page.includes('path="/relay-os/"'));
  assert.ok(page.includes('title="Relay OS - End-user messaging"'));
  assert.ok(checkout.includes("'grahak-os', 'GOS7K4M2', 'Relay OS'"));
  assert.ok(!page.includes('/dispatch/'));
});
