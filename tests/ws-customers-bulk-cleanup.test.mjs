// Static guards: bulk directory cleanup is review-first and ARCHIVE-ONLY.
// No live customer data is mutated during CI. Individual deletion stays in ActionsSheet.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const directory = readSource('src/components/ws/customers/CustomerList.tsx');
const css = readSource('src/components/ws/customers/CustomerList.module.css');
const actions = readSource('src/components/ws/customers/CustomerActionsSheet.tsx');

test('unnamed and unverified are distinct review filters, not deletion criteria', () => {
  for (const marker of [
    'function needsName(contact: Contact)',
    '!contact.name?.trim()',
    "filter === 'unnamed' && !needsName(contact)",
    "filter === 'unverified' && contact.phoneVerifiedAt",
    'Review customers without a name', 'Review phone verification',
    'Missing names and unverified phones do not prove inactivity',
  ]) assert.ok(directory.includes(marker), marker);
});

test('select-all is bounded, protected rows are not selectable, and filter changes clear selection', () => {
  for (const marker of [
    'return Boolean(identityId(contact)) && !contact.locked && !contact.archivedAt',
    'const selectableVisible = visible.filter(isBulkEligible)',
    'const protectedVisible = visible.length - selectableVisible.length',
    'selectableVisible.slice(0, MAX_BULK)',
    'const MAX_BULK = 100',
    'setSelected(allVisibleSelected ? new Set() : new Set(batchVisible.map(identityId)))',
    'disabled={bulkBusy || !isBulkEligible(contact)}',
    "if (selecting && isBulkEligible(contact)) toggleSelected",
    "setSelected(new Set()); setBulkOutcome(''); }, [search, filter]",
  ]) assert.ok(directory.includes(marker), marker);
});

test('bulk action remains archive-only and requires confirmation + two authoritative reads', () => {
  const start = directory.indexOf('const bulkArchive = async () =>');
  const end = directory.indexOf('const openDetails =', start);
  const body = directory.slice(start, end);
  assert.ok(start >= 0 && end > start);
  for (const marker of [
    'await api.listContactsResult()', 'const authoritative = new Map',
    'isBulkEligible(contact)', "filter === 'unnamed' && !needsName(contact)",
    "filter === 'unverified' && Boolean(contact.phoneVerifiedAt)",
    'await confirm(', 'if (!approved) return;',
    'const finalSnapshot = await api.listContactsResult()',
    'const finalTargets = targets.filter(contact =>',
    'if (finalTargets.length === 0) return;',
    'await api.archiveContact(', 'result.ok && result.data?.archivedAt',
    'unconfirmed++', 'await load()', 'setBulkProgress',
  ]) assert.ok(body.includes(marker), marker);
  assert.ok(body.indexOf('await api.listContactsResult()') < body.indexOf('await confirm('));
  assert.ok(body.indexOf('await confirm(') < body.indexOf('const finalSnapshot = await api.listContactsResult()'));
  assert.ok(body.indexOf('const finalSnapshot = await api.listContactsResult()') < body.indexOf('await api.archiveContact('));
  assert.ok(!directory.includes('api.bulkDeleteContacts('));
  assert.ok(!directory.includes('api.softDeleteContactResult('));
  assert.ok(!directory.includes("runBulk('delete')"));
  assert.ok(directory.includes('onClick={() => void bulkArchive()}'));
  assert.ok(actions.includes('api.softDeleteContactResult'), 'single-record reviewed removal remains available');
});

test('no archives run automatically and in-flight progress cannot be hidden by clearing search', () => {
  assert.ok(directory.includes('disabled={bulkBusy}'));
  assert.ok(directory.includes('aria-label="Clear customer search"'));
  assert.ok(directory.includes('setBulkProgress({ done: 0, total: finalTargets.length })'));
  assert.ok(directory.includes('Archive keeps customer history. Delete individually after review.'));
  assert.ok(!directory.includes('window.confirm('), 'use the shared accessible dialog');
});

test('atomic backend retention guard rejects a contact locked after staff review', () => {
  const handler = readSource('amplify/functions/core/contacts/handler.py');
  const start = handler.indexOf('def _archive_contact(');
  const end = handler.indexOf('def _restore_contact(', start);
  const body = handler.slice(start, end);
  assert.ok(body.includes("'#locked': contact_lock.LOCKED_ATTRIBUTE"));
  assert.ok(body.includes("'AND (attribute_not_exists(#locked) OR #locked = :unlocked)'"));
  assert.ok(body.includes("':unlocked': False"));
  assert.ok(body.includes('ConditionalCheckFailedException'));
});

test('contact mapper retains portfolio-scoped and parent business-scoped IDs', () => {
  const mapper = readSource('src/api/domains/contacts.ts');
  assert.ok(mapper.includes("bsuid: item.bsuid || ''"));
  assert.ok(mapper.includes("parentBsuid: item.parentBsuid || ''"));
});

test('mobile cleanup remains reachable on Safari and Android', () => {
  for (const marker of [
    '.cleanupInfo', '.bulkTray', '.bulkActions', '.protectedMarker',
    'safe-area-inset-bottom', '@media (max-width: 600px)',
    'min-height: 48px', '.tabs { flex-wrap: wrap',
    'grid-template-columns: minmax(0, 1fr)',
  ]) assert.ok(css.includes(marker), marker);
  assert.ok(directory.includes('aria-label="Selected customer cleanup actions"'));
  assert.ok(directory.includes('aria-pressed={filter ==='));
});
