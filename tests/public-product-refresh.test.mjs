import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const read = path => readFileSync(path, 'utf8');
const added = [
  ['/niji-setu/parichay', 'src/pages/niji-setu/parichay.tsx'],
  ['/niji-setu/khata', 'src/pages/niji-setu/khata.tsx'],
  ['/relay-os', 'src/pages/relay-os/index.tsx'],
  ['/atmos/nano-climate', 'src/pages/atmos/nano-climate.tsx'],
  ['/atmos/green-ledger', 'src/pages/atmos/green-ledger.tsx'],
  ['/elsewhere/rail', 'src/pages/elsewhere/rail.tsx'],
  ['/elsewhere/cruise', 'src/pages/elsewhere/cruise.tsx'],
  ['/elsewhere/arogya-yatra', 'src/pages/elsewhere/arogya-yatra.tsx'],
];
const retired = [
  ['/niji-setu', 'src/pages/niji-setu.tsx'],
  ['/dispatch', 'src/pages/dispatch/index.tsx'],
  ['/grahak-os', 'src/pages/grahak-os/index.tsx'],
  ['/vayulok', 'src/pages/vayulok/index.tsx'],
  ['/sehat', 'src/pages/sehat.tsx'],
];

test('new product pages and public registries agree; retired pages are absent', () => {
  const header = read('src/components/Header.tsx');
  const sitemap = read('scripts/generate-sitemap.js');
  // The retired-family denylist may name an old URL; only PUBLIC_EXACT advertises it.
  const publicExact = sitemap.split('const PUBLIC_EXACT = new Set( [')[1].split('] );')[0];
  const meta = read('src/pages/_app.tsx');
  const catalog = JSON.parse(read('config/public-pages.json')).pages;
  for (const [route, file] of added) {
    assert.ok(existsSync(file), file);
    assert.ok(header.includes("href: '" + route + "/'"), route);
    assert.ok(publicExact.includes("'" + route + "'"), route);
    assert.ok(meta.includes("'" + route + "':"), route);
    assert.ok(catalog.some(page => page.path === route), route);
  }
  for (const [route, file] of retired) {
    assert.ok(!existsSync(file), file);
    assert.ok(!header.includes("href: '" + route + "/'"), route);
    assert.ok(!publicExact.includes("'" + route + "'"), route);
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


test('Atmos uses the official outlined grass symbol at its native viewBox', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes("Atmos: 'M80-160v-80h230"));
  assert.ok(header.includes("const MATERIAL_NAV_ICON_LABELS = new Set( [\n  'Atmos',"));
  assert.ok(header.includes("'0 -960 960 960'"));
  assert.ok(header.includes("label: 'Relay OS', href: '/relay-os/'"));
});

test('Niji Setu is a non-clickable family and both destinations use shared submenu icons', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes("label: 'Parichay', href: '/niji-setu/parichay/'"));
  assert.ok(header.includes("label: 'Khata', href: '/niji-setu/khata/'"));
  assert.ok(!header.includes("href: '/niji-setu/'"));
  assert.ok(header.includes('{ link.nested ? ('));
  const notFound = read('src/pages/404.tsx');
  assert.ok(notFound.includes("'/dispatch', '/niji-setu', '/shop/niji-setu'"));
});
