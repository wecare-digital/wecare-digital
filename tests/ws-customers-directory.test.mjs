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
    'Customer profile username', 'Organization', 'Job title',
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
  assert.ok(!directory.includes('api.softDeleteContactResult('), 'bulk cleanup is archive-only; individual deletes are separate');
  assert.ok(directory.includes('api.archiveContact('), 'archive preserves history by default');
  assert.ok(directory.includes('await confirm('), 'each bulk action needs explicit confirmation');
  assert.ok(directory.includes('contact.locked'));
  assert.ok(directory.includes('if (!record || !isBulkEligible(record))'), 'missing/locked IDs cannot be selected for bulk cleanup');
  assert.ok(directory.includes('CustomerActionsSheet'));
  assert.ok(directory.includes('CustomerManageData'));
  assert.ok(directory.includes('api.exportContactsToCSV(visible)'), 'safe export uses existing CSV serializer');
  assert.ok(directory.includes('setDetailsFor(current => current'), 'reload updates open customer details');
  assert.ok(directory.includes("setSelected(new Set()); setBulkOutcome(''); }, [search, filter]"), 'filter changes clear hidden bulk selections and stale cleanup outcomes');
  const actions = readSource('src/components/ws/customers/CustomerActionsSheet.tsx');
  assert.ok(!actions.includes('api.softDeleteContactResult('), 'incomplete individual deletion must be disabled');
  assert.ok(actions.includes('Delete all customer data — unavailable'));
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


test('BSUID-only WhatsApp customers remain editable but are not bulk-archived by missing phone', () => {
  assert.ok(editor.includes("(!editing || Boolean(fullPhone))"), 'only newly created contacts require a phone');
  assert.ok(editor.includes('required={!editing}'), 'editing a phone-hidden customer must not trigger HTML required');
  assert.ok(editor.includes('...(!editing ? { phone: fullPhone } : {})'), 'staff editing never supplies a phone');
  assert.ok(editor.includes('Meta BSUID (read-only)'), 'Meta identity is visible, never staff-editable');
  assert.ok(directory.includes('Object.keys(contact.whatsappIdentities || {}).length'), 'phone-hidden contact is distinguished across either business');
  assert.ok(directory.includes('&& !(hasBusinessIdentity && !contact.phone)'), 'bulk archive must exclude any business BSUID-only customer');
});

test('customer directory searches and displays Meta identities separately from WECARE profile username', () => {
  for (const marker of [
    'contact.bsuid, contact.parentBsuid', 'contact.contactBookName',
    'Meta WhatsApp username', 'Business-scoped user ID (BSUID)', 'Parent BSUID',
    'WECARE profile username', 'WhatsApp BSUID linked', 'Phone not shared',
  ]) assert.ok(directory.includes(marker), marker);
  assert.ok(!/payload\.bsuid\s*=|payload\.parentBsuid\s*=|payload\.username\s*=/.test(editor),
    'the staff editor cannot overwrite Meta-owned identifiers');
});

test('inbound BSUID-only customer creation never fabricates cross-channel marketing consent', () => {
  const inbound = readSource('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
  for (const field of [
    'optInWhatsApp', 'optInSms', 'optInEmail',
    'allowlistWhatsApp', 'allowlistSms', 'allowlistEmail',
  ]) {
    assert.ok(inbound.includes("'" + field + "': False"), field + ' must default to false');
  }
  assert.ok(inbound.includes('_find_scoped_bsuid(') && inbound.includes('contact_store.find_by_bsuid(contacts_table, bsuid)'),
    'use canonical fail-closed BSUID lookup rather than selecting an arbitrary row');
});

test('WhatsApp contact-request number is read from the contact card and claimed before linking', () => {
  const inbound = readSource('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
  const begin = inbound.indexOf('    # Meta puts `origin` on each contact card');
  const end = inbound.indexOf('    # Update Contact.lastInboundMessageAt', begin);
  assert.ok(begin !== -1 && end > begin, 'contact request handling must exist');
  const segment = inbound.slice(begin, end);
  assert.ok(segment.includes("shared_card.get('origin') != 'contact_request'"));
  assert.ok(!segment.includes("message.get('origin'"), 'message-level origin does not exist in Meta webhook');
  assert.ok(segment.includes("_update_contact_bsuid_fields("), 'use the guarded phone-link path');
  const helper = inbound.slice(inbound.indexOf('def _update_contact_bsuid_fields('),
    inbound.indexOf('def _process_user_id_update('));
  assert.ok(helper.includes('identity_claims.claim_identities('), 'claim phone identity before linking');
  assert.ok(helper.includes('contact_store.find_by_phone('), 'refuse a phone owned by another person');
  assert.ok(helper.includes('pending_phone'), 'do not report phone linked if update failed');
});

test('ambiguous inbound BSUID identities are parked for replay, never silently discarded', () => {
  const inbound = readSource('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
  assert.ok(inbound.includes("conflict_value['messages'] = [message]"));
  assert.ok(inbound.includes("'customer_identity_conflict', request_id"));
  assert.ok(inbound.includes('if not parked:'), 'a failed DLQ write must trigger an upstream retry');
  assert.ok(inbound.includes('inbound_phone_change_requires_review'), 'new phone for an existing ID needs review');
});

test('BSUID change system messages preserve the previous customer and fence phone moves', () => {
  const inbound = readSource('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
  const before = inbound.indexOf('    previous_system_contact = None');
  const resolution = inbound.indexOf('    contact = (previous_system_contact or');
  assert.ok(before !== -1 && resolution > before,
    'previous BSUID lookup must happen before a new contact can be auto-created');
  assert.ok(inbound.includes("'unresolved-previous-bsuid'"), 'missing former identity must be reviewed');
  assert.ok(inbound.includes("'system-bsuid-already-owned'"), 'changed BSUID must not steal another identity');
  assert.ok(inbound.includes("'system_phone_change_requires_review'"), 'new phone must not silently redirect routing');
  assert.ok(!inbound.includes("set_parts.append('phone = :p')"), 'system messages cannot overwrite a claimed phone');
});

test('duplicate live phone owners are never resolved by arbitrary oldest-row fallback', () => {
  const inbound = readSource('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
  assert.ok(inbound.includes("if len(items) > 1:"));
  assert.ok(inbound.includes("raise contact_store.IdentityConflict('phone'"));
  assert.ok(!inbound.includes("contact = sorted(items, key=lambda x: x.get('createdAt', 0))[0]"));
});

test('phone-hidden customer is not incorrectly counted or labeled as unverified', () => {
  assert.ok(directory.includes('contact.phone && <span className={contact.phoneVerifiedAt'),
    'verification badge is rendered only when a phone exists');
  assert.ok(directory.includes('Boolean(item.phone) && !item.phoneVerifiedAt'),
    'unverified filter count must exclude phone-hidden customers');
  assert.ok(directory.includes("(!contact.phone || contact.phoneVerifiedAt)"),
    'unverified filter must exclude missing numbers');
  assert.ok(directory.includes("Boolean(latest.phone) && !latest.phoneVerifiedAt"),
    'bulk archive must recheck only real unverified phones');
});

test('Meta contact-book names are not mapped into an organization', () => {
  const contacts = readSource('src/api/domains/contacts.ts');
  assert.ok(contacts.includes("companyName: item.companyName || ''"));
  assert.ok(!contacts.includes('item.companyName || item.contactBookName'),
    'provider identity must stay separate from company name');
});

test('inbound resolves BSUID before deterministic phone and survives registry outages', () => {
  const inbound = readSource('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
  const start = inbound.indexOf('def _get_or_create_contact(');
  const end = inbound.indexOf('def _update_contact_bsuid_fields(', start);
  assert.ok(start >= 0 && end > start);
  const method = inbound.slice(start, end);
  const bsuidLookup = method.indexOf('_find_scoped_bsuid(');
  const phoneLookup = method.indexOf("r = contacts_table.get_item(Key={'id': det_id}");
  assert.ok(bsuidLookup >= 0 && phoneLookup > bsuidLookup,
    'phone disclosure must not reassign a BSUID-only customer to another phone owner');
  const updateMethod = inbound.slice(end, inbound.indexOf('def _process_user_id_update(', end));
  assert.ok(updateMethod.includes('except Exception as phone_link_error:'),
    'operational registry errors should not lose inbound messages');
  assert.ok(updateMethod.includes("'event': 'inbound_phone_link_unavailable'"),
    'registry outage must be observable without exposing customer PII');
});

test('outbound auto-created contacts never gain invented marketing permission', () => {
  const outbound = readSource('amplify/functions/messaging/outbound-whatsapp/handler.py');
  const begin = outbound.indexOf('def _get_or_create_contact_by_phone(');
  const end = outbound.indexOf('def _enrich_contact_identity(', begin);
  assert.ok(begin >= 0 && end > begin);
  const create = outbound.slice(begin, end);
  for (const field of ['optInWhatsApp', 'optInSms', 'optInEmail',
    'allowlistWhatsApp', 'allowlistSms', 'allowlistEmail']) {
    assert.ok(create.includes("'" + field + "': False"), field + ' must default to false');
    assert.ok(!create.includes("'" + field + "': True"), field + ' cannot be manufactured');
  }
  assert.ok(create.includes('contact_store.find_by_phone(contacts_table, with_plus)'),
    'outbound phone lookup must reject multiple live owners');
  assert.ok(!create.includes("sorted(items, key=lambda x: x.get('createdAt', 0))[0]"),
    'a duplicate phone must never pick the oldest owner');
});

test('both Meta business portfolios maintain independent BSUID ownership claims', () => {
  const inbound = readSource('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
  for (const id of ['2094615664435155', '2513394156072604',
    '382642103987922', '125951953587391']) assert.ok(inbound.includes(id));
  for (const marker of [
    "f'WHATSAPP_BSUID#{portfolio_id}#{value}'",
    "def _find_scoped_bsuid(", "def _attach_scoped_bsuid(",
    'waba_id=source_waba_id', 'whatsappIdentities',
    "'business-identity-already-claimed'", "'unknown-business-identity-scope'",
    "'unscoped-bsuid-reconciliation'",
  ]) assert.ok(inbound.includes(marker), marker);
  assert.ok(inbound.includes("if waba_id != '2094615664435155':"),
    'Manish BSUID must not overwrite WECARE legacy identity fields');
  assert.ok(inbound.includes('scoped_identity ='),
    'BSUID-only deterministic contact ID must include portfolio scope');
});

test('both WhatsApp business identities are read-only in /ws/customer search and details', () => {
  const api = readSource('src/api/domains/contacts.ts');
  for (const marker of [
    'whatsappIdentities?: Record<string, PortfolioWhatsAppIdentity>',
    'whatsappIdentities: normalizePortfolioIdentities(item.whatsappIdentities)',
    "'382642103987922'", "'125951953587391'",
  ]) assert.ok(api.includes(marker), marker);
  for (const marker of [
    'WHATSAPP_BUSINESS_PORTFOLIOS',
    'WECARE.DIGITAL', 'Manish Agarwal',
    "contact.whatsappIdentities?.[business.id]",
    'Object.values(contact.whatsappIdentities || {}).flatMap',
    'hasBusinessIdentity && !contact.phone',
  ]) assert.ok(directory.includes(marker), marker);
  assert.ok(!/payload\.whatsappIdentities\s*=/.test(editor),
    'staff profile editor must never assign business-provider identities');
});

test('website registration and transactions still require a phone verified by OTP', () => {
  const registration = readSource('amplify/functions/auth/customer-registration/handler.py');
  const auth = readSource('amplify/functions/auth/customer-whatsapp-auth/handler.py');
  assert.ok(registration.includes('phone_number_verified'), 'Cognito identity requires verified phone');
  assert.ok(registration.includes('otp_challenge'), 'customer registration retains phone OTP');
  const checkout = readSource('amplify/functions/ecommerce/checkout/handler.py');
  assert.ok(checkout.includes('identity, denied = customer_auth.require_customer(event)'),
    'website checkout must use authenticated Cognito customer identity');
  assert.ok(auth.includes("if key != PRIMARY_WABA_ID or phone_number_id != PRIMARY_PHONE_NUMBER_ID"),
    'website OTP route must not silently change to the second business');
  assert.ok(editor.includes('if ((!editing || Boolean(fullPhone))'),
    'new staff customer needs phone, provisional edits cannot manufacture one');
  assert.ok(editor.includes('Website sign-in, shopping and transactions require') || 
    editor.includes('WECARE.DIGITAL website sign-in, shopping and transactions require'),
    'customer editor explains OTP requirement');
  assert.ok(directory.includes('Website OTP and checkout require a phone'));
});

test('inbound WhatsApp dedup leases complete only after successful message processing', () => {
  const inbound = readSource('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
  const workLoop = inbound.indexOf('leased_message_ids = []');
  const call = inbound.indexOf('                        _process_message(', workLoop);
  const complete = inbound.indexOf('                        if leased_message_ids:', call);
  const catchFailure = inbound.indexOf('                    except Exception as e:', complete);
  assert.ok(workLoop !== -1 && call > workLoop && complete > call && catchFailure > complete,
    'a successful message must finish before its dedup lease is closed');
  assert.ok(inbound.includes('claim_event_with_lease('),
    'inbound message dedup must be recoverable after a processing failure');
  assert.ok(inbound.includes('dedup_tracker.append(whatsapp_message_id)'));
  assert.ok(inbound.includes('complete_event(leased_id)'));
  assert.ok(!inbound.includes("claim_event(whatsapp_message_id, source='whatsapp_inbound')"),
    'permanent pre-processing claim would swallow retry of a failed identity transition');
});
