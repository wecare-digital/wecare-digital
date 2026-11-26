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
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
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
  assert.ok(terminal.includes('.wt-play-icon{display:block;width:1.2em;height:1.2em;flex:0 0 1.2em;fill:currentColor}'));
  assert.ok(terminal.includes('color:#f0a818;font-size:15px'));
  assert.ok(terminal.includes('.wt-play.is-paused{color:#3da35a;'));
  assert.ok(terminal.includes('.wt-play.is-paused:hover,.wt-play.is-paused:focus-visible{color:#d1f470}'));
  assert.ok(terminal.includes("aria-label={ paused ? 'Play the illustration of a customer request' : 'Pause the illustration of a customer request' }"));
  assert.ok(terminal.includes('onClick={ togglePlay }'));
  assert.ok(terminal.includes('M320-200v-560l440 280-440 280Z'));
  assert.ok(terminal.includes('M520-200v-560h240v560H520Z'));
  assert.ok(!terminal.includes("{ paused ? 'Play' : 'Pause' }"));
  assert.ok(!terminal.includes('wt-play-mark'));
});

test('Terms and Privacy share responsive collapsible contents with subsection deep links, not collapsed legal prose', () => {
  const legal = read('src/components/LegalDocument.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
  for (const page of ['terms', 'privacy']) {
    assert.ok(read('src/pages/' + page + '.tsx').includes('<LegalDocument'));
  }
  assert.ok(legal.includes('<details className="lgd-contents" ref={ tocRef } open>'));
  assert.ok(legal.includes('<summary className="lgd-toc-summary" aria-label="Toggle legal section list"'));
  assert.ok(legal.includes('className="lgd-toc-group"'));
  assert.ok(legal.includes('child.number.startsWith('));
  assert.ok(legal.includes('href={ `#${child.id}` }'));
  assert.ok(legal.includes('Section { section.number } overview'));
  assert.ok(legal.includes("window.matchMedia( '(min-width: 1100px)' )"));
  assert.ok(legal.includes("window.addEventListener( 'hashchange', revealDeepLink )"));
  assert.ok(legal.includes('group instanceof HTMLDetailsElement'));
  assert.ok(legal.includes('id={ section.id }'));
  assert.ok(legal.includes('section.paragraphs.map'));
  assert.ok(legal.includes("const CONTENTS_ICON = 'M360-240h440v-107H360v107ZM160-613h120v-107H160v107Zm0 187h120v-107H160v107Zm0 186h120v-107H160v107Zm200-186h440v-107H360v107Zm0-187h440v-107H360v107ZM160-160q-33 0-56.5-23.5T80-240v-480q0-33 23.5-56.5T160-800h640q33 0 56.5 23.5T880-720v480q0 33-23.5 56.5T800-160H160Z'"));
  assert.ok(legal.includes("const CONTENTS_ICON_VIEW_BOX = '40 -920 880 880'"));
  assert.ok(legal.includes('CONTENTS_ICON, CONTENTS_ICON_VIEW_BOX, ROW_CHEVRON_PATH, ROW_CHEVRON_VIEW_BOX, SUBNAV_ICON_PATH, SUBNAV_DOT_PATH, SUBNAV_ICON_VIEW_BOX'));
  assert.ok(!legal.includes('LEGAL_DOUBLE_ARROW'));
  assert.ok(legal.includes("const ROW_CHEVRON_PATH = 'M383-480 200-664l56-56 240 240-240 240-56-56 183-184Zm264 0L464-664l56-56 240 240-240 240-56-56 183-184Z'"));
  assert.ok(legal.includes("const ROW_CHEVRON_VIEW_BOX = '174.55 -785.45 610.9 610.9'"));
  assert.ok(legal.includes('viewBox={ CONTENTS_ICON_VIEW_BOX }'));
  assert.equal((legal.match(/viewBox=\{ ROW_CHEVRON_VIEW_BOX \}/g) || []).length, 2);
  assert.equal((legal.match(/<path d=\{ ROW_CHEVRON_PATH \} \/>/g) || []).length, 2);
  assert.equal((legal.match(/viewBox=\{ SUBNAV_ICON_VIEW_BOX \}/g) || []).length, 3);
  assert.equal((legal.match(/<path d=\{ SUBNAV_ICON_PATH \} \/>/g) || []).length, 3);
  assert.equal((legal.match(/<path className="lgd-sub-dots" d=\{ SUBNAV_DOT_PATH \} \/>/g) || []).length, 3);
  assert.ok(legal.includes("section.number.includes( '.' )"));
  assert.ok(legal.includes('.lgd-sub-icon .lgd-sub-dots{fill:currentColor;stroke:none}'));
  assert.ok(legal.includes(".lgd-sub-icon{transform:scaleX(-1)}"));
  assert.ok(!legal.includes('<span>Contents</span>'));
  assert.ok(legal.includes('width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);flex:0 0 var(--public-nav-icon-size);fill:currentColor'));
  assert.ok(legal.includes("return () => wide.removeEventListener( 'change', syncLayout );\n  }, [] );"));
  assert.ok(legal.includes("aria-current={ activeId === child.id ? 'location' : undefined }"));
  assert.ok(legal.includes("onClick={ event => selectSection( event, child.id ) }"));
  assert.ok(legal.includes('tocRef.current.open = false;'));
  assert.ok(legal.includes('lgd-toc-link[aria-current="location"]'));
  assert.ok(legal.includes('.lgd-contents[open]>.lgd-toc-summary .lgd-contents-chevron'));
  assert.ok(legal.includes('.lgd-toc-group[open]>.lgd-toc-group-summary .lgd-group-chevron'));
});


test('every submenu child uses the curved arrow with two round dots, including search results', () => {
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
  assert.equal((header.match(/<path d=\{ SUBNAV_ICON_PATH \} \/>/g) || []).length, 3);
  assert.equal((header.match(/<path className="nav-sub-dots" d=\{ SUBNAV_DOT_PATH \} \/>/g) || []).length, 3);
  assert.ok(header.includes("const SUBNAV_ICON_PATH = 'M5 12v1a5 5 0 0 0 5 5h11m-4-4 4 4-4 4';"));
  assert.ok(header.includes("const SUBNAV_DOT_PATH = 'M5 1.75a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 1 1 0-2.5ZM5 6.25a1.25 1.25 0 1 1 0 2.5 1.25 1.25 0 1 1 0-2.5Z';"));
  assert.ok(header.includes("const SUBNAV_ICON_VIEW_BOX = '1.375 0.875 23 23'"));
  assert.ok(header.includes('.nav-sub-icon .nav-sub-dots{fill:currentColor;stroke:none}'));
  assert.ok(header.includes('.nav-section-icon,.nav-row-icon,.nav-sub-icon,.nav-row-chevron{fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}'));
  assert.ok(header.includes(".nav-sub-icon{transform:scaleX(-1)}"));
  assert.ok(!header.includes('.nav-sub-icon{transform:rotate('));
  assert.ok(!header.includes('NAV_ICON_PATHS[ child.label ]'));
});


test('Atmos and Relay OS retain their official outlined Material Symbols in optically centered viewBoxes', () => {
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
  assert.ok(header.includes("Atmos: 'M80-160v-80h230"));
  assert.ok(header.includes("const MATERIAL_NAV_ICON_LABELS = new Set( [\n  'Atmos',"));
  assert.ok(header.includes("Atmos: '43.63 -916.37 872.73 872.73'"));
  assert.ok(header.includes("'Relay OS': 'M560-32v-80"));
  assert.ok(header.includes("'Relay OS': '-41.82 -993.82 1003.64 1003.64'"));
  assert.ok(header.includes("label: 'Relay OS', href: '/relay-os/'"));
});

test('Niji Setu is a non-clickable family and both destinations use shared submenu icons', () => {
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
  assert.ok(header.includes("label: 'Parichay', href: '/niji-setu/parichay/'"));
  assert.ok(header.includes("label: 'Khata', href: '/niji-setu/khata/'"));
  assert.ok(!header.includes("href: '/niji-setu/'"));
  assert.ok(header.includes('{ link.nested ? ('));
  const notFound = read('src/pages/404.tsx');
  assert.ok(notFound.includes("'/dispatch', '/niji-setu', '/shop/niji-setu'"));
});

test('menu icons share a 24px viewport and stay visible at narrow widths', () => {
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
  assert.ok(header.includes('.nav-section-icon,.nav-row-icon,.nav-sub-icon,.nav-row-chevron,.nav-trigger-icon,.nav-products-more-icon{display:block;width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);flex:0 0 var(--public-nav-icon-size)}'));
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
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
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
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
  assert.ok(header.includes("Aastha: 'M80-80v-440h80v80h80"));
  assert.ok(header.includes("'Atmos',\n  'Aastha',\n  'Relay OS',"));
  assert.ok(header.includes("Aastha: '21.81 -958.18 916.37 916.37'"));
  assert.ok(header.includes('width:var(--public-nav-icon-size);height:var(--public-nav-icon-size);flex:0 0 var(--public-nav-icon-size)'));
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

test('Elsewhere uses the selected official outlined pin_road symbol, with a measured centered crop', () => {
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
  assert.ok(header.includes("Elsewhere: 'M320-120v-160h80v160h-80Zm0-280v-160h80v160h-80Zm0-280v-160h80v160h-80ZM80-120l100-720h80L160-120H80Zm598.5-3q-5.5-3-8.5-9l-4-9q-23-48-64-82.5T532-302q-17-26-25-55t-8-59q0-78 57-130.5T692-599q78 0 133 56t55 135q0 29-8 56t-24 50q-29 44-70.5 78.5T714-141l-4 9q-3 6-8.5 9t-11.5 3q-6 0-11.5-3Zm68-230.5Q770-377 770-410t-23.5-56.5Q723-490 690-490t-56.5 23.5Q610-443 610-410t23.5 56.5Q657-330 690-330t56.5-23.5ZM494-599l-34-241h80l26 187q-20 11-38 24t-34 30Z'"));
  assert.ok(header.includes("'Relay OS',\n  'Elsewhere',\n  'Hunar',"));
  assert.ok(header.includes("Elsewhere: '43.63 -916.37 872.73 872.73'"));
});

test('every named menu and section icon has an explicit square optical crop', () => {
  const header = read('src/components/Header.tsx') + '\n' + read('src/lib/publicNavigationIcons.ts');
  function map(name) {
    const body = header.match(new RegExp('const ' + name + ': Record<string, string> = \\{([\\s\\S]*?)\\n\\};'))?.[1];
    assert.ok(body, name);
    return Object.fromEntries([...body.matchAll(/^\s*(?:'([^']+)'|([A-Za-z]+)): '([^']+)',/gm)].map(match => [match[1] || match[2], match[3]]));
  }
  for (const [paths, boxes] of [['NAV_ICON_PATHS', 'NAV_ICON_VIEW_BOXES'], ['SECTION_ICON_PATHS', 'SECTION_ICON_VIEW_BOXES']]) {
    const icons = map(paths);
    const crops = map(boxes);
    assert.deepEqual(Object.keys(crops).sort(), Object.keys(icons).sort());
    for (const [label, crop] of Object.entries(crops)) {
      const v = crop.split(' ').map(Number);
      assert.equal(v.length, 4, label);
      assert.ok(v.every(Number.isFinite), label);
      assert.ok(v[2] > 0 && v[2] === v[3], label);
    }
  }
  // The original icon sets have different units and fill/stroke geometry. Check
  // representative measured largest-axis bounds from every column and icon type.
  for (const [label, span, stroke, box] of [
    ['Home', 18, 2, 21.6], ['Atmos', 800, 0, 872.73], ['Elsewhere', 800, 0, 872.73],
    ['Request Amendment', 14, 2, 16.8], ['Vault', 640, 0, 698.19],
    ['Partner', 800, 0, 872.73], ['Shop', 800, 0, 872.73], ['Orders', 800, 0, 872.73],
    ['App', 880, 0, 960], ['AI', 880, 0, 960],
  ]) {
    const [, , width] = map('NAV_ICON_VIEW_BOXES')[label].split(' ').map(Number);
    assert.equal(width, box, label);
    assert.ok(Math.abs(span * 24 / width + stroke - 22) < 0.03, label);
  }
});

test('Anew uses the exact selected outlined social_leaderboard glyph and normalized 24px crop', () => {
  const icons = read('src/lib/publicNavigationIcons.ts');
  const header = read('src/components/Header.tsx');
  assert.ok(icons.includes("Anew: 'M480-160q75 0 127.5-52.5T660-340q0-75-52.5-127.5T480-520q-75 0-127.5 52.5T300-340q0 75 52.5 127.5T480-160ZM363-572q20-11 42.5-17.5T451-598L350-800H250l113 228Zm234 0 114-228H610l-85 170 19 38q14 4 27 8.5t26 11.5ZM256-208q-17-29-26.5-62.5T220-340q0-36 9.5-69.5T256-472q-42 14-69 49.5T160-340q0 47 27 82.5t69 49.5Zm448 0q42-14 69-49.5t27-82.5q0-47-27-82.5T704-472q17 29 26.5 62.5T740-340q0 36-9.5 69.5T704-208ZM480-80q-40 0-76.5-11.5T336-123q-9 2-18 2.5t-19 .5q-91 0-155-64T80-339q0-87 58-149t143-69L120-880h280l80 160 80-160h280L680-559q85 8 142.5 70T880-340q0 92-64 156t-156 64q-9 0-18.5-.5T623-123q-31 20-67 31.5T480-80Zm0-260ZM363-572 250-800l113 228Zm234 0 114-228-114 228ZM406-230l28-91-74-53h91l29-96 29 96h91l-74 53 28 91-74-56-74 56Z'"));
  assert.ok(icons.includes("Anew: '43.63 -916.37 872.73 872.73'"));
  const materialLabels = icons.match(/const MATERIAL_NAV_ICON_LABELS = new Set\( \[([\s\S]*?)\] \);/)?.[1];
  assert.ok(materialLabels?.includes("'Anew'"));
  assert.ok(header.includes("label: 'Anew', href: '/anew/'"));
  const [, , width] = '43.63 -916.37 872.73 872.73'.split(' ').map(Number);
  assert.ok(Math.abs(800 * 24 / width - 22) < 0.03);
});

test('Request, Shop, Orders, App and AI use exact outlined Material glyphs and optical crops', () => {
  const icons = read('src/lib/publicNavigationIcons.ts');
  const menu = read('src/components/orders/OrderActionsMenu.tsx');
  for (const [label, path, crop] of [
    ['Request', 'M200-160v-80h64l79-263q8-26 29.5-41.5T420-560h120q26 0 47.5 15.5T617-503l79 263h64v80H200Zm148-80h264l-72-240H420l-72 240Zm92-400v-200h80v200h-80Zm238 99-57-57 142-141 56 56-141 142Zm42 181v-80h200v80H720ZM282-541 141-683l56-56 142 141-57 57ZM40-360v-80h200v80H40Zm440 120Z', '0 -980 960 960'],
    ['Shop', 'M240-80q-33 0-56.5-23.5T160-160v-480q0-33 23.5-56.5T240-720h80q0-66 47-113t113-47q66 0 113 47t47 113h80q33 0 56.5 23.5T800-640v480q0 33-23.5 56.5T720-80H240Zm0-80h480v-480h-80v80q0 17-11.5 28.5T600-520q-17 0-28.5-11.5T560-560v-80H400v80q0 17-11.5 28.5T360-520q-17 0-28.5-11.5T320-560v-80h-80v480Zm160-560h160q0-33-23.5-56.5T480-800q-33 0-56.5 23.5T400-720ZM240-160v-480 480Z', '43.63 -916.37 872.73 872.73'],
    ['Orders', 'M655-200 513-342l56-56 85 85 170-170 56 57-225 226Zm0-320L513-662l56-56 85 85 170-170 56 57-225 226ZM80-280v-80h360v80H80Zm0-320v-80h360v80H80Z', '43.63 -937.86 872.73 872.73'],
    ['App', 'M280-40q-33 0-56.5-23.5T200-120v-720q0-33 23.5-56.5T280-920h400q33 0 56.5 23.5T760-840v124q18 7 29 22t11 34v80q0 19-11 34t-29 22v404q0 33-23.5 56.5T680-40H280Zm0-80h400v-720H280v720Zm0 0v-720 720Zm200-200 160-160-56-56-64 62v-166h-80v166l-64-62-56 56 160 160Z', '20 -960 960 960'],
    ['AI', 'M160-360q-50 0-85-35t-35-85q0-50 35-85t85-35v-80q0-33 23.5-56.5T240-760h120q0-50 35-85t85-35q50 0 85 35t35 85h120q33 0 56.5 23.5T800-680v80q50 0 85 35t35 85q0 50-35 85t-85 35v160q0 33-23.5 56.5T720-120H240q-33 0-56.5-23.5T160-200v-160Zm200-80q25 0 42.5-17.5T420-500q0-25-17.5-42.5T360-560q-25 0-42.5 17.5T300-500q0 25 17.5 42.5T360-440Zm240 0q25 0 42.5-17.5T660-500q0-25-17.5-42.5T600-560q-25 0-42.5 17.5T540-500q0 25 17.5 42.5T600-440ZM320-280h320v-80H320v80Zm-80 80h480v-480H240v480Zm240-240Z', '0 -980 960 960'],
  ]) {
    assert.ok(icons.includes(label + ": '" + path + "'"), label);
    assert.ok(icons.includes(label + ": '" + crop + "'"), label);
  }
  assert.ok(icons.includes("MATERIAL_SECTION_ICON_LABELS = new Set( [ 'Refer & Earn', 'Request' ] )"));
  assert.ok(menu.includes(".orm-section .orm-section-icon-fill{fill:currentColor;stroke:none}"));
  const materialLabels = icons.match(/const MATERIAL_NAV_ICON_LABELS = new Set\( \[([\s\S]*?)\] \);/)?.[1];
  for (const label of ['Shop', 'Orders', 'App', 'AI']) assert.ok(materialLabels?.includes("'" + label + "'"), label);
});

test('menu disclosure arrows use the selected outlined double chevron and preserve dotted child arrows', () => {
  const icons = read('src/lib/publicNavigationIcons.ts');
  const header = read('src/components/Header.tsx');
  const orders = read('src/components/orders/OrderActionsMenu.tsx');
  assert.ok(icons.includes("ROW_CHEVRON_PATH = 'M383-480 200-664l56-56 240 240-240 240-56-56 183-184Zm264 0L464-664l56-56 240 240-240 240-56-56 183-184Z'"));
  assert.ok(icons.includes("ROW_CHEVRON_VIEW_BOX = '174.55 -785.45 610.9 610.9'"));
  assert.ok(header.includes('.nav-row-chevron{margin-inline-start:auto;fill:currentColor;stroke:none}'));
  assert.ok(header.includes('SUBNAV_DOT_PATH'));
  assert.ok(orders.includes('const CHEVRON_PATH = ROW_CHEVRON_PATH'));
  assert.ok(orders.includes('flex:none;fill:currentColor;\n          stroke:none;opacity:.65;'));
  assert.ok(Math.abs(560 * 24 / 610.9 - 22) < 0.03);
});
