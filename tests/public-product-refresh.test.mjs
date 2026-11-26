import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const read = path => readFileSync(path, 'utf8');
const added = [
  ['/aastha/panchang', 'src/pages/aastha/panchang.tsx'],
  ['/aastha/vidhi', 'src/pages/aastha/vidhi.tsx'],
  ['/aastha/samagri', 'src/pages/aastha/samagri.tsx'],
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
  ['/ritual-guru/ritva', 'src/pages/ritual-guru/ritva.tsx'],
  ['/ritual-guru/puja-guidance', 'src/pages/ritual-guru/puja-guidance.tsx'],
  ['/ritual-guru/diy-puja-kit', 'src/pages/ritual-guru/diy-puja-kit.tsx'],
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

test('Home pause/play uses official Material Symbols, a stable accessible icon-only control and matching title-bar height', () => {
  const terminal = read('src/components/WorkflowTerminal.tsx');
  assert.ok(terminal.includes('height:47px;width:52px;box-sizing:border-box'));
  assert.ok(terminal.includes('width:52px;height:47px'));
  assert.ok(terminal.includes('.wt-play-icon{display:block;width:24px;height:24px;flex:0 0 24px;fill:currentColor}'));
  assert.ok(terminal.includes("aria-label={ paused ? 'Play the illustration of a customer request' : 'Pause the illustration of a customer request' }"));
  assert.ok(terminal.includes('onClick={ togglePlay }'));
  assert.ok(terminal.includes('M320-200v-560l440 280-440 280Z'));
  assert.ok(terminal.includes('M520-200v-560h240v560H520Z'));
  assert.ok(!terminal.includes("{ paused ? 'Play' : 'Pause' }"));
  assert.ok(!terminal.includes('wt-play-mark'));
});

test('Terms and Privacy share responsive collapsible contents with subsection deep links, not collapsed legal prose', () => {
  const legal = read('src/components/LegalDocument.tsx');
  for (const page of ['terms', 'privacy']) {
    assert.ok(read('src/pages/' + page + '.tsx').includes('<LegalDocument'));
  }
  assert.ok(legal.includes('<details className="lgd-contents" ref={ tocRef } open>'));
  assert.ok(legal.includes('<summary className="lgd-toc-summary">'));
  assert.ok(legal.includes('className="lgd-toc-group"'));
  assert.ok(legal.includes('child.number.startsWith('));
  assert.ok(legal.includes('href={ `#${child.id}` }'));
  assert.ok(legal.includes('Section { section.number } overview'));
  assert.ok(legal.includes("window.matchMedia( '(min-width: 1100px)' )"));
  assert.ok(legal.includes("window.addEventListener( 'hashchange', revealDeepLink )"));
  assert.ok(legal.includes('group instanceof HTMLDetailsElement'));
  assert.ok(legal.includes('id={ section.id }'));
  assert.ok(legal.includes('section.paragraphs.map'));
  assert.ok(legal.includes("const CONTENTS_ICON = 'M120-240v-80h520v80H120Z"));
  assert.ok(legal.includes('viewBox="60 -900 840 840"'));
  assert.ok(legal.includes('width:24px;height:24px;flex:0 0 24px;fill:currentColor'));
  assert.ok(legal.includes("return () => wide.removeEventListener( 'change', syncLayout );\n  }, [] );"));
  assert.ok(legal.includes("aria-current={ activeId === child.id ? 'location' : undefined }"));
  assert.ok(legal.includes("onClick={ event => selectSection( event, child.id ) }"));
  assert.ok(legal.includes('tocRef.current.open = false;'));
  assert.ok(legal.includes('lgd-toc-link[aria-current="location"]'));
  assert.ok(legal.includes('.lgd-contents[open]>.lgd-toc-summary .lgd-contents-chevron'));
  assert.ok(legal.includes('.lgd-toc-group[open]>.lgd-toc-group-summary .lgd-group-chevron'));
});


test('every submenu child uses the shared bent arrow, not a product-specific glyph', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes('<path d={ SUBNAV_ICON_PATH } />'));
  assert.ok(!header.includes('NAV_ICON_PATHS[ child.label ]'));
});


test('Atmos and Relay OS retain their official outlined Material Symbols in optically centered viewBoxes', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes("Atmos: 'M80-160v-80h230"));
  assert.ok(header.includes("const MATERIAL_NAV_ICON_LABELS = new Set( [\n  'Atmos',"));
  assert.ok(header.includes("Atmos: '40 -880 880 880'"));
  assert.ok(header.includes("'Relay OS': 'M560-32v-80"));
  assert.ok(header.includes("'Relay OS': '-40 -980 1000 1000'"));
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

test('menu icons share a 24px viewport and stay visible at narrow widths', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes('.nav-section-icon,.nav-row-icon,.nav-sub-icon,.nav-row-chevron,.nav-trigger-icon,.nav-products-more-icon{display:block;width:24px;height:24px;flex:0 0 24px}'));
  assert.ok(header.includes('vector-effect:non-scaling-stroke'));
  assert.ok(header.includes('viewBox={ SUBNAV_ICON_VIEW_BOX }'));
  assert.ok(header.includes('viewBox={ sectionIconViewBox( section.heading ) }'));
  assert.ok(header.includes('navIconViewBox( link.label )'));
  assert.ok(header.includes('white-space:normal;overflow-wrap:anywhere'));
  assert.ok(!/\.nav-(?:row-icon|sub-icon)[^{]*\{[^}]*display:none/.test(header));
  assert.ok(!header.includes('NAV_MATERIAL_SYMBOLS'));
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

test('Aastha is a non-clickable family, with all three approved destinations and the expanded Panchang scope', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes("label: 'Aastha',"));
  assert.ok(!header.includes("href: '/aastha/'"));
  assert.ok(header.includes("label: 'Vidhi', href: '/aastha/vidhi/'"));
  assert.ok(header.includes("label: 'Samagri', href: '/aastha/samagri/'"));
  assert.ok(header.includes("label: 'Panchang', href: '/aastha/panchang/'"));
  const products = read('src/content/productChildren.ts');
  for (const name of ['Astrology', 'Vastu', 'Panchang', 'Ritual calendar']) {
    assert.ok(products.includes("heading: '" + name + "'"));
  }
  assert.ok(products.includes("slug: 'ritual-guru-ritva'"));
  assert.ok(!existsSync('src/pages/aastha/index.tsx'));
});

test('Aastha uses the official outlined Hindu temple artwork with the shared 24px menu icon footprint', () => {
  const header = read('src/components/Header.tsx');
  assert.ok(header.includes("Aastha: 'M80-80v-440h80v80h80"));
  assert.ok(header.includes("'Atmos',\n  'Aastha',\n  'Relay OS',"));
  assert.ok(header.includes("Aastha: '20 -960 920 920'"));
  assert.ok(header.includes('width:24px;height:24px;flex:0 0 24px'));
});

test('Panchang keeps the approved native product and variant in the cart fallback without restoring legacy Shop URLs', () => {
  const snapshot = read('src/content/catalogSnapshot.ts');
  assert.ok(snapshot.includes("id:'native:ritual-guru-ritva', name:'Panchang', slug:'ritual-guru-ritva'"));
  const row = snapshot.split("id:'native:ritual-guru-ritva'")[1].split("  },")[0];
  assert.ok(row.includes("formattedPrice:'₹99.00', price:'99.00'"));
  assert.ok(row.includes("canonicalPath:'/aastha/panchang/'"));
  assert.ok(row.includes("id:'2b1655cf-198a-438d-93b6-c57612b819b6'"));
  const shop = read('src/content/shop.ts');
  const detail = read('src/pages/shop/[slug].tsx');
  assert.ok(shop.includes('SHOP_DETAIL_PRODUCTS = SHOP_PRODUCTS.filter('));
  assert.ok(shop.includes('!RETIRED_SHOP_DETAIL_SLUGS.has( product.slug )'));
  assert.ok(detail.includes('paths: SHOP_DETAIL_PRODUCTS.map('));
  const notFound = read('src/pages/404.tsx');
  for (const slug of ['ritual-guru-puja-guidance', 'ritual-guru-diy-puja-kit', 'ritual-guru-ritva']) {
    assert.ok(notFound.includes("'/shop/" + slug + "'"));
  }
});
