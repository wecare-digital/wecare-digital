import test from 'node:test';
import assert from 'node:assert/strict';
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
