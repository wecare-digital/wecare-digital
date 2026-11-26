import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ORDER_REQUESTS, orderRequestById, orderRequestForLabel } from '../src/lib/orderRequestSelection.ts';
import { rankNavigation, NAV_DISCOVERY, normalizeNavigationText } from '../src/lib/navigationSearch.ts';

const items = ['Khata','Visa','Panchang','Orders','Trip','Drop Docs','Track','Parichay'].map( label => ( { label, searchText: [label, ...(NAV_DISCOVERY[label] || [])].join(' ') } ) );
const first = query => rankNavigation(items, query)[0]?.label;
test('ranked navigation finds typed, translated, misspelled and multiword requests', () => {
  assert.equal(first('Khata'), 'Khata');
  assert.equal(first('inovice'), 'Khata');
  assert.equal(first('ভিসা'), 'Visa');
  assert.equal(first('पंचांग'), 'Panchang');
  assert.equal(first('digital profile'), 'Parichay');
  assert.equal(first('upload documents'), 'Drop Docs');
  assert.equal(rankNavigation(items, 'zzzzzzz').length, 0);
  assert.equal(rankNavigation(items, '!!').length, 0);
  assert.equal(normalizeNavigationText('   VISA!  '), 'visa');
});

test('every request selection is allowlisted and independent of WhatsApp send intents', () => {
  assert.equal(ORDER_REQUESTS.length, 6);
  for (const request of ORDER_REQUESTS) {
    assert.equal(orderRequestForLabel(request.label)?.id, request.id);
    assert.equal(orderRequestById(request.id)?.label, request.label);
  }
  assert.equal(orderRequestForLabel('Subscribe'), null);
  assert.equal(orderRequestById('javascript:alert(1)'), null);
  const header = readFileSync(new URL('../src/components/Header.tsx', import.meta.url), 'utf8');
  const orders = readFileSync(new URL('../src/components/orders/OrdersPage.tsx', import.meta.url), 'utf8');
  const actions = readFileSync(new URL('../src/components/orders/OrderActionsMenu.tsx', import.meta.url), 'utf8');
  const requestEntries = readFileSync(new URL('../src/config/whatsappServiceEntries.ts', import.meta.url), 'utf8');
  for (const request of ORDER_REQUESTS) assert.ok(requestEntries.includes("slug: '" + request.id + "'"));
  assert.ok(header.includes('if ( request && isPrimaryMenuActivation( event ) ) stashOrderRequest( request.id )'));
  assert.ok(header.includes('aria-expanded={ familyOpen } aria-controls={ familyId }'));
  assert.ok(header.includes('hidden={ !familyOpen }'));
  assert.ok(orders.includes('const selection = takeOrderRequest()'));
  assert.ok(orders.includes('whatsappServiceLink( selectedRequest.id )'));
  assert.ok(actions.includes('onRequest( request.id )'));
  assert.ok(actions.includes("from '../../lib/publicNavigationIcons'"));
});
test('legal scroll tracking and search retain native fragment navigation and full prose', () => {
  const legal = readFileSync(new URL('../src/components/LegalDocument.tsx', import.meta.url), 'utf8');
  assert.ok(legal.includes("window.addEventListener( 'scroll', schedule, { passive: true } )"));
  assert.ok(legal.includes('window.cancelAnimationFrame( frame )'));
  assert.ok(legal.includes('aria-label="Find a legal clause"'));
  assert.ok(legal.includes('className="lgd-return-to-contents"'));
  assert.ok(legal.includes('section.paragraphs.map'));
});
