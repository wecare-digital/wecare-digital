import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

test('UdyamBids and GetKosh end the public Products menu as ordinary links', () => {
  const header = read('src/components/Header.tsx');
  const products = header.slice(header.indexOf("heading: 'Products'"), header.indexOf("heading: 'Request'"));
  assert.match(products, /label: 'Niji Setu'[\s\S]*label: 'UdyamBids', href: '\/udyam-bids\/', match: '\/udyam-bids'[\s\S]*label: 'GetKosh', href: '\/get-kosh\/', match: '\/get-kosh'[^\n]*\n\s*\],/);
  const icons = read('src/lib/publicNavigationIcons.ts');
  for (const [name, glyph, route, box, path] of [
    ['UdyamBids', 'warehouse', 'udyam-bids', '43.63 -916.37 872.73 872.73', 'M160-200h80v-320h480v320h80v-426L480-754 160-626v426Zm-80 80v-560l400-160 400 160v560H640v-320H320v320H80Zm280 0v-80h80v80h-80Zm80-120v-80h80v80h-80Zm80 120v-80h80v80h-80ZM240-520h480-480Z'],
    ['GetKosh', 'money_bag', 'get-kosh', '87.27 -872.73 785.46 785.46', 'M336-120q-91 0-153.5-62.5T120-336q0-38 13-74t37-65l142-171-97-194h530l-97 194 142 171q24 29 37 65t13 74q0 91-63 153.5T624-120H336Zm144-200q-33 0-56.5-23.5T400-400q0-33 23.5-56.5T480-480q33 0 56.5 23.5T560-400q0 33-23.5 56.5T480-320Zm-95-360h190l40-80H345l40 80Zm-49 480h288q57 0 96.5-39.5T760-336q0-24-8.5-46.5T728-423L581-600H380L232-424q-15 18-23.5 41t-8.5 47q0 57 39.5 96.5T336-200Z'],
  ]) {
    assert.ok(icons.includes('Outlined ' + glyph + ','));
    assert.ok(icons.includes(name + ": '" + path + "'"));
    assert.ok(icons.includes(name + ": '" + box + "'"));
    assert.ok(icons.includes("'" + name + "',"));
    assert.ok(read('src/pages/_app.tsx').includes("router.pathname === '/" + route + "'"));
    assert.ok(read('src/pages/' + route + '.tsx').includes('name="' + name + '"'));
    assert.ok(!read('scripts/generate-sitemap.js').includes("'/" + route + "'"));
  }
  assert.match(read('src/components/public/UpcomingProductPage.tsx'), /name="robots" content="noindex, follow"/);
});
