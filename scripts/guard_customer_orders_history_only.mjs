/**
 * Customer Orders is permanently a compact history, never an expandable receipt.
 *
 * This is a build invariant, NOT a retired tests/ suite or GitHub Actions job.
 * Import from next.config.js so both direct Next builds and Amplify builds fail
 * closed if the deleted customer detail view or its deep-link path returns.
 * Staff-only Orders details and internal statutory records are not affected.
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export function assertCustomerOrdersHistoryOnly(root = defaultRoot) {
  const problems = [];
  const read = (relative) => {
    const file = join(root, relative);
    try {
      return readFileSync(file, 'utf8');
    } catch {
      problems.push('Missing required source: ' + relative);
      return '';
    }
  };
  const orders = read('src/components/orders/OrdersPage.tsx');
  const route = read('src/pages/orders.tsx');
  const helper = read('src/lib/orderPage.ts');
  const checkoutStatus = read('src/pages/checkout/status.tsx');
  const actions = read('src/components/orders/OrderActionsMenu.tsx');
  const checkoutBackend = read('amplify/functions/ecommerce/checkout/handler.py');

  const componentDir = join(root, 'src/components/orders');
  if (existsSync(join(root, 'src/pages/orders'))) {
    problems.push('A separate customer /orders/* route was reintroduced.');
  }
  if (existsSync(componentDir)) {
    const detailFiles = readdirSync(componentDir).filter(
      (name) => /^order(?:detail|receipt)/i.test(name),
    );
    if (detailFiles.length) {
      problems.push('Customer order-detail component exists: ' + detailFiles.join(', '));
    }
  }

  const jsx = orders.split('<style jsx>{`')[0];
  const headingMarkup = (jsx.match(/<thead>[\s\S]*?<\/thead>/) || [''])[0];
  const headings = [...headingMarkup.matchAll(/<th\b[^>]*>([^<]*)<\/th>/g)]
    .map((match) => match[1].trim());
  if (headings.join('|') !== 'Order #|Date|Amount|Status|Invoice') {
    problems.push('Customer Orders must render only the five history column headings.');
  }
  if (!/<tr\s+key=\{\s*rowId\s*\}\s+className="ord-tr"\s*>/.test(jsx)) {
    problems.push('Order rows must remain static, without extra interactive attributes.');
  }
  if (!/<span\s+className="ord-ordno"(?=\s|>)/.test(jsx)) {
    // JSX's real order-number span has other attributes; the class is its identity.
    problems.push('The static order-number label is missing.');
  }
  if (!jsx.includes('<OrderActionsMenu') || !jsx.includes('MY_INVOICE_URL')) {
    problems.push('Keep More actions and invoice download on the compact row.');
  }

  const forbidden = [
    ['customer detail component or expanded state',
      /\b(?:OrderDetail|OrderReceipt|expandedOrder|setExpandedOrder|selectedOrder|setSelectedOrder|setExpanded|openOrderDetails|toggleOrderDetails)\b/],
    ['order breakdown data fields',
      /\b(?:lineItems|deliveryAddress|paymentReference|invoiceNumber|gstAmount)\b/],
    ['clickable order table row or cell',
      /<(?:tr|th|td)\b[^>]*\bonClick\s*=/s],
    ['expandable receipt or dialog in customer Orders',
      /<(?:details|dialog)\b|\baria-expanded\s*=/i],
    ['retired detail checkout call',
      /\baction\s*:\s*['"]order['"]/],
  ];
  for (const [name, pattern] of forbidden) {
    if (pattern.test(jsx)) problems.push('Found ' + name + ' in customer Orders.');
  }
  if (!jsx.includes("params.has( 'o' )") ||
      !jsx.includes("window.history.replaceState( window.history.state, '', '/orders/' )") ||
      !jsx.includes("sessionStorage.removeItem( 'wecare.pendingOrderView' )")) {
    problems.push('Legacy order-detail query/selector must be discarded on /orders/.');
  }

  if (!route.includes("export default OrdersPage;") ||
      !route.includes("import OrdersPage from '../components/orders/OrdersPage'")) {
    problems.push('/orders must delegate to the one compact OrdersPage component.');
  }
  const pathFunction = helper.match(/export function orderPagePath\s*\([^)]*\)\s*:\s*string\s*\{([^}]*)\}/);
  if (!pathFunction || !/^\s*return\s+['"]\/orders\/['"];\s*$/.test(pathFunction[1])) {
    problems.push('All order links must resolve to exactly /orders/.');
  }
  if (!/router\.replace\(\s*orderPagePath\(/.test(checkoutStatus) ||
      !/href=\{\s*orderPagePath\(/.test(checkoutStatus) ||
      /sessionStorage\.setItem\(\s*['"]wecare\.pendingOrderView/.test(checkoutStatus) ||
      /[?&]o=/.test(checkoutStatus)) {
    problems.push('Paid checkout must return to history without selecting a receipt.');
  }
  if (/\bOrderDetail\b|\/orders\/\$\{|[?&]o=/.test(actions)) {
    problems.push('Order menu must not navigate to individual order details.');
  }

  const retiredAction = checkoutBackend.indexOf('if action == "order":');
  const refusedAction = checkoutBackend.indexOf(
    'return _hardened(cors_response(410, {"error": "ORDER_DETAILS_RETIRED"}, origin))',
    retiredAction,
  );
  const paymentCreate = checkoutBackend.indexOf('if action == "create":', retiredAction);
  if (retiredAction < 0 || refusedAction < retiredAction ||
      paymentCreate <= refusedAction ||
      /^\s*def _order_(?:detail|view|lines)\b/m.test(checkoutBackend)) {
    problems.push('Retired checkout order-detail API must refuse with 410 before payment create.');
  }

  if (problems.length) {
    throw new Error('Customer Orders history-only build gate FAILED:\n- ' +
      problems.join('\n- '));
  }
  return true;
}

// Explicit read-only manual command, separate from the retired root tests/ suite.
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    assertCustomerOrdersHistoryOnly();
    console.log('Customer Orders history-only build gate: PASS');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
