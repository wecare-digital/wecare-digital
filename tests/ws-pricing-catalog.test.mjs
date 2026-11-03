// Offline UI regression tests. No network, AWS calls, payments or DOM required.
// Render the real /ws catalog component with server quote values injected through
// the existing TSX test harness. Assert amount mapping and fail-closed display.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadTsxModule, readSource } from './helpers/loadTsx.mjs';

const quote = {
  itemSubtotalPaise: 10000,
  supplyGstPaise: 1800,
  supplyGstBps: 1800,
  delightPaise: 59,
  expressPaise: 4500,
  collectionBeforeConveniencePaise: 16241,
  convenienceFeePaise: 400,
  convenienceGstPaise: 72,
  convenienceGstBps: 1800,
  totalPayablePaise: 16713,
};

function renderText(node) {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(renderText).join(' ');
  if (typeof node === 'object' && node.type === 'style') return '';
  if (typeof node === 'object' && 'children' in node) return renderText(node.children);
  return '';
}

function makeTree(price) {
  const prices = {
    'submit-request': price,
    vault: { available: false },
    'shipments-track': { available: false },
    contribute: { available: false },
  };
  const initialState = [prices, false, 0, 'submit-request', '', new Date('2026-11-03T09:00:00Z')];
  let index = 0;
  const ReactStub = {
    createElement: (type, props, ...children) => ({ type, props, children }),
    useState: (initial) => [initialState[index++] ?? initial, () => {}],
    useEffect: () => {},
  };
  const { exports } = loadTsxModule({
    file: 'src/components/ws/commerce/PriceCatalogPanel.tsx',
    globals: {
      require: (name) => {
        if (name === 'react') return { ...ReactStub, default: ReactStub };
        if (name.includes('config/services')) return {
          SERVICE_CHOICES: [
            { slug: 'submit-request', label: 'Submit Request', kind: 'SUBMIT_REQUEST', sku: 'RSR7M2P9' },
            { slug: 'vault', label: 'Vault', kind: 'VAULT', sku: 'RVT6K4Q8' },
          ],
        };
        if (name.includes('lib/servicePricing')) return {
          fetchServiceWorkspacePrices: async () => prices,
          rupeesFromPaise: (paise) => (paise / 100).toFixed(2),
        };
        throw new Error('Unexpected import: ' + name);
      },
    },
  });
  return renderText(exports.default({}));
}

test('new /ws catalog surfaces every server-owned bill field, not just item price', () => {
  const text = makeTree({ available: true, paise: 10000, breakdown: quote });
  for (const label of [
    'Base item price', 'Supply GST (18%)', 'DELIGHT discount',
    'Express', 'Before convenience fee', 'Convenience fee',
    'GST on convenience fee (18%)', 'Final payable',
  ]) {
    assert.ok(text.includes(label), label + ' must be shown');
  }
  for (const amount of [10000, 1800, 59, 4500, 16241, 400, 72, 16713]) {
    assert.ok(text.includes('₹' + (amount / 100).toFixed(2)), 'server amount ' + amount + ' must be shown');
  }
  assert.ok(text.includes('₹167.13'), 'final total equals server totalPayablePaise');
  assert.ok(text.includes('Read-only price reference'));
});

test('new /ws catalog never fabricates a full total if server breakdown is absent', () => {
  const text = makeTree({ available: true, paise: 10000 });
  assert.ok(text.includes('At checkout'));
  assert.ok(text.includes('no validated full breakdown'));
  assert.ok(!text.includes('₹167.13'));
});

test('new /ws catalog never prices an unavailable service or renders product images', () => {
  const text = makeTree({ available: false });
  assert.ok(text.includes('Live pricing is unavailable'));
  assert.ok(!text.includes('₹167.13'));
  const source = readSource('src/components/ws/commerce/PriceCatalogPanel.tsx');
  assert.ok(!/<img\b|<Image\b/.test(source), 'product images remain removed');
  assert.ok(source.includes('fetchServiceWorkspacePrices()'), 'prices are read from the canonical backend endpoint');
  assert.ok(!source.includes('Math.round('), 'no local monetary price rounding');
});
