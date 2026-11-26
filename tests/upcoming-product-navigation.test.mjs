import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

test('UdyamBids and GetKosh end the public Products menu as ordinary links', () => {
  const header = read('src/components/Header.tsx');
  const products = header.slice(header.indexOf("heading: 'Products'"), header.indexOf("heading: 'Request'"));
  assert.match(products, /label: 'Niji Setu'[\s\S]*label: 'UdyamBids', href: '\/udyam-bids\/', match: '\/udyam-bids'[\s\S]*label: 'GetKosh', href: '\/get-kosh\/', match: '\/get-kosh'[^\n]*\n\s*\],/);
  const icons = read('src/lib/publicNavigationIcons.ts');
  for (const [name, glyph, route] of [['UdyamBids', 'find_in_page', 'udyam-bids'], ['GetKosh', 'credit_card', 'get-kosh']]) {
    assert.ok(icons.includes('Outlined ' + glyph + ','));
    assert.ok(icons.includes(name + ": '43.63 -916.37 872.73 872.73'"));
    assert.ok(icons.includes("'" + name + "',"));
    assert.ok(read('src/pages/_app.tsx').includes("router.pathname === '/" + route + "'"));
    assert.ok(read('src/pages/' + route + '.tsx').includes('name="' + name + '"'));
    assert.ok(!read('scripts/generate-sitemap.js').includes("'/" + route + "'"));
  }
  assert.match(read('src/components/public/UpcomingProductPage.tsx'), /name="robots" content="noindex, follow"/);
});
