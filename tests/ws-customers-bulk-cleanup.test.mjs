// Bulk cleanup must be deliberate, recoverable where possible, and safe on small screens.
// Static checks complement normal TypeScript/lint/CI; no live contact is altered in CI.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const directory = readSource('src/components/ws/customers/CustomerList.tsx');
const css = readSource('src/components/ws/customers/CustomerList.module.css');

test('unnamed customers and unverified numbers are separate review categories', () => {
  for (const marker of [
    'function needsName(contact: Contact)',
    '!contact.name?.trim()',
    "filter === 'unnamed' && !needsName(contact)",
    "filter === 'unverified' && contact.phoneVerifiedAt",
    'Review customers without a name', 'Review phone verification',
    'Missing names or unverified phones do not prove inactivity',
  ]) assert.ok(directory.includes(marker), marker);
});

test('bulk selection skips locked/archived/unknown IDs and has a bounded one-go batch', () => {
  for (const marker of [
    'return Boolean(identityId(contact)) && !contact.locked && !contact.archivedAt',
    'const selectableVisible = visible.filter(isBulkEligible)',
    'const protectedVisible = visible.length - selectableVisible.length',
    'selectableVisible.slice(0, MAX_BULK)',
    'const MAX_BULK = 100',
    'disabled={bulkBusy || !isBulkEligible(contact)}',
    "title={isBulkEligible(contact) ? 'Select for reviewed cleanup' : 'Protected: review individually'}",
    "if (selecting && isBulkEligible(contact)) toggleSelected",
    "setSelected(new Set()); setBulkOutcome(''); }, [search, filter]",
  ]) assert.ok(directory.includes(marker), marker);
});

test('only confirmed staff actions write after fresh retention preflight and review', () => {
  const start = directory.indexOf('const runBulk = async (action: BulkAction)');
  const end = directory.indexOf('const openDetails =', start);
  const body = directory.slice(start, end);
  assert.ok(start >= 0 && end > start, 'bulk action exists');
  for (const marker of [
    'await api.listContactsResult()', 'const authoritative = new Map',
    "filter === 'unnamed' && !needsName(contact)",
    "filter === 'unverified' && Boolean(contact.phoneVerifiedAt)",
    'isBulkEligible(contact)', "action === 'delete' && !isSoftDeleteCandidate(contact)",
    'await confirm(', 'if (!approved) return;',
    "await api.archiveContact(", 'await api.softDeleteContactResult(id)',
    "result.data?.success === true && result.data.deleteType === 'soft'",
    'result.ok && result.data?.archivedAt',
    "unknown++; // A network exception could occur AFTER a write",
    'await load()', 'setBulkProgress',
  ]) assert.ok(body.includes(marker), marker);
  assert.ok(body.indexOf('await api.listContactsResult()') < body.indexOf('await confirm('));
  assert.ok(body.indexOf('await confirm(') < body.indexOf('await api.archiveContact('));
  assert.ok(!body.includes('bulkDeleteContacts'), 'legacy boolean counter cannot report per-record refusals');
});

test('missing name and unverified status never automatically trigger deletion', () => {
  for (const marker of [
    'contact.phoneVerifiedAt', 'contact.emailVerifiedAt', 'contact.lastInboundMessageAt',
    'contact.lastFlowInteractionAt', 'contact.bsuid', 'contact.parentBsuid',
    'contact.consentHistory?.length', "contact.whatsappMarketingConsent === 'OPTED_IN'",
    "contact.whatsappMarketingConsent === 'OPTED_OUT'", 'contact.welcomeSent',
    'contact.optInWhatsApp', 'contact.allowlistWhatsApp',
    'contact.tags?.length', 'contactDeliveryAddress(contact)',
    'function isSoftDeleteCandidate(contact: Contact)',
    'return isBulkEligible(contact) && needsName(contact) && !hasIdentityEvidence(contact)',
  ]) assert.ok(directory.includes(marker), marker);
  assert.ok(directory.includes("onClick={() => void runBulk('archive')}"));
  assert.ok(directory.includes("onClick={() => void runBulk('delete')}"));
  assert.ok(!directory.includes('window.confirm('), 'use shared accessible confirmation');
});

test('server enforces an atomic retention lock on archive, including bulk races', () => {
  const handler = readSource('amplify/functions/core/contacts/handler.py');
  const start = handler.indexOf('def _archive_contact(');
  const end = handler.indexOf('def _restore_contact(', start);
  const body = handler.slice(start, end);
  assert.ok(body.includes("'#locked': contact_lock.LOCKED_ATTRIBUTE"));
  assert.ok(body.includes("'AND (attribute_not_exists(#locked) OR #locked = :unlocked)'"));
  assert.ok(body.includes("':unlocked': False"));
  assert.ok(body.includes('ConditionalCheckFailedException'), 'archive refusal is reported as 409');
});

test('mobile selection is accessible on iOS and Android', () => {
  for (const marker of [
    '.cleanupInfo', '.bulkTray', '.bulkActions', '.protectedMarker',
    'grid-template-columns: repeat(2, minmax(0, 1fr))',
    'safe-area-inset-bottom', '@media (max-width: 600px)',
    'min-height: 48px', '.tabs { flex-wrap: wrap',
  ]) assert.ok(css.includes(marker), marker);
  assert.ok(directory.includes('aria-label="Selected customer cleanup actions"'));
  assert.ok(directory.includes('aria-pressed={filter ==='));
});
