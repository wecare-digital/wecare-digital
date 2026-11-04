// Regression guards for the rebuilt /ws/customers page.
// These tests are static: the live Contacts API and authenticated browser flow are verified
// separately and are never exercised with production customer data in CI.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readSource } from './helpers/loadTsx.mjs';

const route = readSource('src/pages/ws/customers/index.tsx');
const directory = readSource('src/components/ws/customers/CustomerList.tsx');
const editor = readSource('src/components/ws/customers/CustomerEditor.tsx');
const directoryCss = readSource('src/components/ws/customers/CustomerList.module.css');
const editorCss = readSource('src/components/ws/customers/CustomerEditor.module.css');

test('customers page stays inside the shared authenticated /ws shell', () => {
  assert.ok(route.includes('<WsShell active="customers"'));
  assert.ok(route.includes('<SEO title="Customers"'));
  assert.ok(route.includes('noindex'));
  assert.ok(route.includes('<CustomerList'));
  assert.doesNotMatch(route, /import\s+[^;]*\b(?:SiteHeader|Header|Footer|SiteFooter)\b/, 'no duplicate public chrome imports');
  assert.doesNotMatch(route, /<\s*(?:Header|Footer|SiteHeader|SiteFooter)\b/, 'no duplicate header/footer elements');
});

test('directory has real search, filters, sorting, loading and recoverable errors', () => {
  for (const marker of [
    'api.listContactsResult()', 'type="search"', 'search.trim().toLowerCase()',
    'filter ===', 'contactDeliveryAddress(contact)', 'setFilter',
    'Recently updated', 'Name A–Z', 'Could not load customers', 'Retry',
    'No matching customers', 'Create contact',
  ]) {
    assert.ok(directory.includes(marker), marker);
  }
  assert.ok(!directory.includes('fetch('), 'no direct unauthenticated data fetches');
});

test('customer card and drawer show canonical profile, verification and address', () => {
  for (const marker of [
    'CustomerDetails', 'contact.profileUsername', 'contact.companyName',
    'contact.designation', 'contact.phoneVerifiedAt', 'contact.whatsappMarketingConsent',
    'contactDeliveryAddress(contact)', 'customerDisplayId', 'Retention lock',
    'Edit contact', 'More actions',
  ]) assert.ok(directory.includes(marker), marker);
  assert.ok(directory.includes('router.query.contact'), 'existing deep links still work');
});

test('new contact editor follows the F001 profile, address, review steps', () => {
  for (const marker of [
    "'Profile', 'Address', 'Review'", 'Full name', 'WhatsApp phone number',
    'WhatsApp username', 'Organization', 'Job title',
    'ADDRESS_FIELDS.map', 'COUNTRY_OPTIONS.map', 'addressComplete(address)',
    'addressPayload(address)', 'formatAddress(address)',
    'Review before saving', 'Create contact',
  ]) assert.ok(editor.includes(marker), marker);
});

test('customer saves preserve identity, consent and server-side uniqueness', () => {
  assert.ok(editor.includes('contactPhoneE164(phone, dial)'), 'normalise staff phone');
  assert.ok(editor.includes('api.createContactResult(payload)'), 'only canonical create API');
  assert.ok(editor.includes('api.updateContactResult(contact.contactId, payload)'), 'only canonical update API');
  assert.ok(editor.includes('...(!editing ? { phone: fullPhone } : {})'), 'profile edit must not rewrite a verified phone provenance');
  assert.ok(editor.includes('api.updateContactResult(createdId, { profileUsername: desiredUsername })'), 'legacy create runtime receives narrow username follow-up');
  assert.ok(editor.includes('if (!editing && desiredUsername && saved.profileUsername !== desiredUsername)'), 'follow-up must be creation only');
  assert.ok(directory.includes('if (warning) toast.warning(warning)'), 'partial profile username update is disclosed');
  assert.ok(editor.includes('result.failure.status === 409'), 'handle server-side duplicates');
  assert.ok(editor.includes('CONTACT_IDENTITY_RECONCILIATION_REQUIRED'), 'show reconciliation failures');
  assert.ok(!/payload\.optIn|payload\.allowlist|payload\.phoneVerifiedAt|payload\.username\s*=/.test(editor),
    'staff editing cannot grant consent or provider verification');
  assert.ok(!editor.includes('Math.random'), 'server assigns customer IDs');
  assert.ok(!editor.includes('localStorage'), 'customer details must not be cached in local storage');
});

test('destructive actions stay confirm-gated, protected and report server failure', () => {
  assert.ok(directory.includes('api.softDeleteContactResult(id)'), 'use result-aware soft-delete API, not legacy count helper');
  assert.ok(directory.includes('api.archiveContact('), 'archive preserves history by default');
  assert.ok(directory.includes('await confirm('), 'each bulk action needs explicit confirmation');
  assert.ok(directory.includes('contact.locked'));
  assert.ok(directory.includes('if (!record || !isBulkEligible(record))'), 'missing/locked IDs cannot be selected for bulk cleanup');
  assert.ok(directory.includes('CustomerActionsSheet'));
  assert.ok(directory.includes('CustomerManageData'));
  assert.ok(directory.includes('api.exportContactsToCSV(visible)'), 'safe export uses existing CSV serializer');
  assert.ok(directory.includes('setDetailsFor(current => current'), 'reload updates open customer details');
  assert.ok(directory.includes('setSelected(new Set()); }, [search, filter]'), 'filter changes clear hidden bulk selections');
  const actions = readSource('src/components/ws/customers/CustomerActionsSheet.tsx');
  assert.ok(actions.includes('api.softDeleteContactResult'));
  assert.ok(actions.includes('api.archiveContact'));
});

test('responsive layout covers desktop, tablet and iOS/Android browsers', () => {
  for (const marker of [
    '@media (max-width: 1199px)', '@media (max-width: 860px)',
    '@media (max-width: 600px)', '@media (max-width: 360px)',
    'env(safe-area-inset-bottom', 'font-size: 16px',
    '@media (prefers-reduced-motion: reduce)',
  ]) assert.ok(directoryCss.includes(marker), marker);
  assert.ok(editorCss.includes('@media (max-width: 650px)'));
  assert.ok(editorCss.includes('env(safe-area-inset-bottom'));
  assert.ok(directoryCss.includes('var(--ws-'), 'use existing /ws theme tokens');
});

test('staff-created contact persists the declared profile username separately from Meta username', () => {
  const contactsHandler = readSource('amplify/functions/core/contacts/handler.py');
  assert.ok(contactsHandler.includes("'profileUsername': body.get('profileUsername', '').strip()"),
    'create handler must not silently discard F001 profile username');
  assert.ok(contactsHandler.includes("'username': body.get('username', '').strip()"),
    'Meta/provider username stays separate');
  assert.ok(contactsHandler.includes("Staff creation NEVER manufactures consent"),
    'creation keeps consent-evidence rules');
});
