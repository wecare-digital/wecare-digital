import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const scope = readSource('src/components/ws/customers/ErasureScopeReview.tsx');
const directory = readSource('src/components/ws/customers/CustomerList.tsx');
const contactApi = readSource('amplify/functions/core/contacts/handler.py');

test('workspace lets staff select exact retained identities without automatic name merging', () => {
  assert.ok(directory.includes("import ErasureScopeReview from './ErasureScopeReview'"));
  assert.ok(directory.includes('Review deletion scope'));
  assert.ok(directory.includes('<ErasureScopeReview contacts={contacts}'));
  assert.ok(scope.includes('protectedIds.has(contactKey(contact))'));
  assert.ok(scope.includes('contact.contactId || contact.id'));
  assert.ok(scope.includes('contact.phone'));
  assert.ok(scope.includes('contact.customerDisplayId'));
  assert.ok(!scope.includes('Suvendu Chowdhuri'));
  assert.ok(!scope.includes('8777428606'));
});

test('scope review marks every record as uncertified until authoritative full retention checks', () => {
  for (const marker of [
    'candidateLocked: candidates.filter(contact => contact.locked === true).length',
    'candidateMissingId: candidates.filter(contact => !contactKey(contact)).length',
    'const keepSetComplete = protectedIds.size > 0',
    'eligibleToDelete: 0',
    'Razorpay transaction',
    'payment-related communications',
    'ERASURE_COORDINATOR_UNAVAILABLE',
  ]) assert.ok(scope.includes(marker), marker);
  assert.ok(scope.includes('disabled'));
  assert.ok(scope.includes('No records have been changed by this review'));
});

test('scope preview cannot send destructive mutations or bypass backend refusal', () => {
  const prohibited = [
    'deleteContact(', 'deleteMessage(', 'deleteContactMessages(',
    'softDeleteContactResult(', 'hardDeleteContact(', 'archiveContact(',
    'dynamodb', 'DeleteItem', 'clear-all', 'window.fetch(', 'apiCall(',
  ];
  for (const bad of prohibited) assert.ok(!scope.includes(bad), bad);
  assert.ok(contactApi.includes('dispatch_approved_erasure('));
});
