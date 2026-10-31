'use strict';

/**
 * Do not resurrect retired public marketing/transaction landing pages.
 *
 * Customer functions (Orders, WhatsApp, paid service records, and the exact-file
 * /vault/?file= link) remain supported. This guards only obsolete public pages
 * and unused page-specific assets. It runs as an npm prebuild check.
 */
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const retired = [
  '/bharat-rx',
  '/submit-request',
  '/request-amendment',
  '/drop-docs',
  '/request-pickup',
  '/shipments/track',
  '/shop/shipments-track',
  '/leave-review',
  '/subscribe',
  '/get', // Legacy customer-file signpost; /get/<*> media stays active.
];
const deadModules = [
  'src/content/customerservice.ts',
  'src/content/shipments.ts',
  'src/components/ServiceBuyBox.tsx',
];
const deadDesignDir = 'docs/whatsapp/catalog-design';

const exists = (relative) => fs.existsSync(path.join(root, relative));
const failures = [];

for (const route of retired) {
  const base = 'src/pages/' + route.slice(1);
  for (const candidate of [
    base + '.tsx', base + '.ts', base + '.jsx', base + '.js',
    base + '/index.tsx', base + '/index.ts',
    base + '/index.jsx', base + '/index.js',
  ]) {
    if (exists(candidate)) failures.push('Retired public page reappeared: ' + candidate);
  }
}
for (const relative of deadModules) {
  if (exists(relative)) failures.push('Retired page-only module reappeared: ' + relative);
}
if (exists(deadDesignDir)) {
  failures.push('Retired page design assets reappeared: ' + deadDesignDir);
}

const catalogue = JSON.parse(fs.readFileSync(path.join(root, 'config/public-pages.json'), 'utf8'));
const denied = new Set(retired);
for (const page of catalogue.pages || []) {
  if (denied.has(page.path) || denied.has(page.path.replace(/\/$/, ''))) {
    failures.push('Retired public page advertised in catalogue: ' + page.path);
  }
}

const sitemapSource = fs.readFileSync(path.join(root, 'scripts/generate-sitemap.js'), 'utf8');
const block = sitemapSource.match(/const PUBLIC_EXACT\s*=\s*new Set\s*\(\s*\[([\s\S]*?)\]\s*\)/);
if (!block) {
  failures.push('Cannot verify the sitemap PUBLIC_EXACT allowlist');
} else {
  const withoutComments = block[1].split('\n').filter(line => !line.trim().startsWith('//')).join('\n');
  const routes = [...withoutComments.matchAll(/['"]((?:\/)[a-z0-9/-]*)['"]/g)].map(x => x[1]);
  for (const route of routes) {
    if (denied.has(route)) failures.push('Retired route in sitemap allowlist: ' + route);
  }
}

// /vault/?file=ID is not a retired marketing page. Keep the protected entry.
// The CloudFront /get/<*> media rewrite is also intentionally out of scope.
if (!exists('src/pages/vault.tsx')) failures.push('Protected exact-file Vault route is missing');
if (!exists('src/pages/orders.tsx')) failures.push('Customer Orders route is missing');

if (failures.length) {
  console.error('Retired public page guard FAILED:\n' + failures.map(x => ' - ' + x).join('\n'));
  process.exit(1);
}
console.log('Retired public page guard passed: no standalone pages or obsolete designs');
