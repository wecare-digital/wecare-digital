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
  '/checkout/whatsapp', // Inactive payment-channel placeholder removed by owner.
  '/cart', // Retired browser-only redirect; canonical basket checkout is /checkout/.
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

const approvedPublicRoutes = new Set();
const sitemapSource = fs.readFileSync(path.join(root, 'scripts/generate-sitemap.js'), 'utf8');
const block = sitemapSource.match(/const PUBLIC_EXACT\s*=\s*new Set\s*\(\s*\[([\s\S]*?)\]\s*\)/);
if (!block) {
  failures.push('Cannot verify the sitemap PUBLIC_EXACT allowlist');
} else {
  const withoutComments = block[1].split('\n').filter(line => !line.trim().startsWith('//')).join('\n');
  const routes = [...withoutComments.matchAll(/['"]((?:\/)[a-z0-9/-]*)['"]/g)].map(x => x[1]);
  for (const route of routes) {
    approvedPublicRoutes.add(route);
    if (denied.has(route)) failures.push('Retired route in sitemap allowlist: ' + route);
  }
}

// Every standalone public page must either appear on the approved crawl list or
// be an explicitly documented non-indexable flow. This closes a loophole where
// someone could add src/pages/old-page.tsx without putting it in the sitemap:
// Next would still export a public HTML page, but the old guard would not notice.
// Workspace/admin pages and API handlers are authenticated operational routes,
// not orphaned public pages; they are intentionally audited separately.
const ALLOWED_NONINDEXABLE_PAGES = new Set([
  '/_app', '/_document', '/404', '/auth', '/vault',
  '/checkout', '/checkout/status', '/checkout/success',
  '/blog/page/[page]', '/blog/topic/[topic]', '/blog/topic/[topic]/page/[page]',
  '/post/[slug]', '/shop/[slug]', '/shop/page/[page]',
]);

function listFiles (directory) {
  if (!exists(directory)) return [];
  const visit = relative => fs.readdirSync(path.join(root, relative), { withFileTypes: true })
    .flatMap(entry => {
      const next = path.posix.join(relative, entry.name);
      if (entry.isDirectory()) return visit(next);
      return entry.isFile() ? [ next ] : [];
    });
  return visit(directory);
}

function nextPageRoute (file) {
  const relative = file.slice('src/pages/'.length)
    .replace(/\.(tsx|ts|jsx|js)$/, '')
    .replace(/(^|\/)index$/, '')
    .replace(/\/$/, '');
  return '/' + relative;
}

const publicPageFiles = listFiles('src/pages')
  .filter(file => /\.(tsx|ts|jsx|js)$/.test(file))
  .filter(file => !file.startsWith('src/pages/workspace/')
    && !file.startsWith('src/pages/api/'));
for (const file of publicPageFiles) {
  const route = nextPageRoute(file);
  if (!approvedPublicRoutes.has(route) && !ALLOWED_NONINDEXABLE_PAGES.has(route)) {
    failures.push('Unregistered/orphaned public page: ' + file + ' (' + route + ')');
  }
}

// Unlike Next page source, public/*.html is served directly even if nothing
// links to it. Only the existing verification and embedded VayuLok page are
// permitted. A new HTML file needs an explicit review/exception.
const ALLOWED_PUBLIC_HTML = new Set([
  'public/google907ae7b9233a31c5.html',
  'public/vayulok-globe.html',
]);
for (const file of listFiles('public').filter(file => /\.html?$/i.test(file))) {
  if (!ALLOWED_PUBLIC_HTML.has(file)) {
    failures.push('Unregistered standalone public HTML file: ' + file);
  }
}

// The dynamic /shop/[slug] route emits one public page per SHOP_PRODUCTS row.
// A catalog payment SKU is not authorization to recreate a former public page.
// Guard the filtered projection, every retired slug and the generated shelf URLs.
const RETIRED_SHOP_SLUGS = new Set([
  'bharat-rx', 'submit-request', 'request-amendment', 'drop-docs', 'vault',
  'shipments-track', 'request-pickup', 'leave-review', 'subscribe', 'get',
  'request-services',
]);
const ACTIVE_ORDER_SERVICE_SLUGS = new Set([
  'submit-request', 'request-amendment', 'drop-docs', 'vault',
  'shipments-track', 'request-pickup',
]);
const shopSource = fs.readFileSync(path.join(root, 'src/content/shop.ts'), 'utf8');
const excluded = shopSource.match(/const ORDER_HUB_SERVICE_SLUGS\s*=\s*new Set\s*\(\s*\[([\s\S]*?)\]\s*\)/);
if (!excluded) {
  failures.push('Dynamic Shop retired-slug exclusion is missing');
} else {
  const blocked = new Set([...excluded[1].matchAll(/'([a-z0-9-]+)'/g)].map(match => match[1]));
  for (const slug of RETIRED_SHOP_SLUGS) {
    if (!blocked.has(slug)) {
      failures.push('Dynamic Shop may republish retired slug: ' + slug);
    }
  }
}
if (!shopSource.includes('.filter( raw => !isServicesRow( raw ) )')) {
  failures.push('SHOP_PRODUCTS must exclude Orders/service payment vehicles');
}
const shopDetails = fs.readFileSync(path.join(root, 'src/pages/shop/[slug].tsx'), 'utf8');
if (!shopDetails.includes('paths: SHOP_PRODUCTS.map(')) {
  failures.push('Dynamic Shop page generation must use the filtered SHOP_PRODUCTS');
}
const listingGenerator = fs.readFileSync(path.join(root, 'scripts/generate_shop_listings.py'), 'utf8');
if (!listingGenerator.includes('"/orders/" if slug in ORDER_HUB_SERVICE_SLUGS')) {
  failures.push('Generated service catalogue links must use the Orders hub');
}
const listingSource = fs.readFileSync(path.join(root, 'src/content/shopProducts.ts'), 'utf8');
for (const line of listingSource.split('\n')) {
  const slug = line.match(/\bslug:\s*'([^']+)'/);
  if (slug && RETIRED_SHOP_SLUGS.has(slug[1])) {
    failures.push('Retired service must not appear on the public Shop shelf: ' + slug[1]);
  }
}

// Keep the six Orders payment products in the native catalog, but without
// public storefront channels or retired canonical page URLs. Exact Vault file
// links are different from the payment product's landing URL.
const catalogSnapshot = fs.readFileSync(path.join(root, 'src/content/catalogSnapshot.ts'), 'utf8');
const liveSnapshot = catalogSnapshot.split('const LIVE_PRODUCTS: CatalogSnapshotProduct[] = [')[1] || '';
for (const slug of ACTIVE_ORDER_SERVICE_SLUGS) {
  const marker = `slug:'${slug}'`;
  const position = liveSnapshot.indexOf(marker);
  const row = position < 0 ? '' : liveSnapshot.slice(position, position + 400);
  if (!/websiteEnabled:false, metaEnabled:false, canonicalPath:'\/orders\/'/.test(row)) {
    failures.push('Retired service public-channel snapshot not disabled: ' + slug);
  }
}

const serviceConfig = fs.readFileSync(path.join(root, 'src/config/services.ts'), 'utf8');
if (/path:'\/(?:submit-request|request-amendment|drop-docs|request-pickup|vault)\/'/.test(serviceConfig)) {
  failures.push('Staff service navigation still references retired public routes');
}
const shelfOrder = listingGenerator.split('SHELF_ORDER: tuple[str, ...] = (')[1]
  ?.split('OFF_SHELF_SLUGS:')[0] || '';
for (const slug of ACTIVE_ORDER_SERVICE_SLUGS) {
  if (shelfOrder.includes(`"${slug}"`)) {
    failures.push('Service product returned to public Shop generator: ' + slug);
  }
}

// Retired or invalid URLs are silent handoffs, not splash/loading pages.
const vaultPage = fs.readFileSync(path.join(root, 'src/pages/vault.tsx'), 'utf8');
const vaultView = fs.readFileSync(path.join(root, 'src/components/get/GetPage.tsx'), 'utf8');
const shell = fs.readFileSync(path.join(root, 'src/pages/_app.tsx'), 'utf8');
if (/Opening your account|Go to Home/.test(vaultPage)) {
  failures.push('Vault redirect renders an obsolete loading waypoint');
}
if (/Opening your Vault|Checking your verified customer session|sf-loading-mark/.test(vaultView)) {
  failures.push('Private Vault preflight renders an obsolete loading waypoint');
}
if (!vaultView.includes("if ( stage === 'loading' && !error ) return null;")) {
  failures.push('Vault preflight must remain silent until owner-scoped verification');
}
// Inspect the immediate private-route render, not fragile route-order substrings.
// Additional or retired redirect-only routes must not break this release check.
const handoffSource = shell.split('// Redirect-only and private handoff routes must never render public chrome,')[1]
  ?.split('// Public page')[0] || '';
const handoffBranch = handoffSource.match(
  /if\s*\(([^)]*)\)\s*\{\s*return\s*\(\s*<ErrorBoundary>\s*<Component\s*\{\s*\.\.\.pageProps\s*\}\s*\/>/
);
const handoffCondition = handoffBranch?.[1]?.trim() || '';
const singleRoute = "router\\.pathname\\s*===\\s*'([^']+)'";
const routeCondition = new RegExp('^' + singleRoute + '(?:\\s*\\|\\|\\s*' + singleRoute + ')*$');
const actualBypassRoutes = new Set(
  [...handoffCondition.matchAll(/router\.pathname\s*===\s*'([^']+)'/g)].map(m => m[1])
);
if (!routeCondition.test(handoffCondition)
    || !actualBypassRoutes.has('/404') || !actualBypassRoutes.has('/vault')) {
  failures.push('404 and private Vault routes must bypass public chrome and translation');
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
