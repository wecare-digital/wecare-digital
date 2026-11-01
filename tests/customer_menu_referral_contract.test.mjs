/**
 * Source contract for the one-use, signed-in Referral menu invitation.
 * No AWS/WhatsApp calls: run with
 *   node --test tests/customer_menu_referral_contract.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFileSync(resolve(root, path), 'utf8');

test('Referral uses the same explicit Orders/Header send intent as Subscribe and Review', () => {
  const actions = read('src/lib/customerMenuActions.ts');
  const orders = read('src/components/orders/OrderActionsMenu.tsx');
  const header = read('src/components/Header.tsx');
  assert.match(actions, /CustomerMenuAction = 'subscribe' \| 'leave-review' \| 'referral' \| 'contribute'/);
  assert.match(actions, /referral: '\/orders\/'/);
  assert.match(actions, /if \( label === 'Referral' \) return 'referral'/);
  assert.match(actions, /parsed\.action === 'referral'/);
  assert.match(actions, /action === 'referral' \? 'sendReferral'/);
  assert.match(actions, /action === 'referral' \? 'REFERRAL_REQUEST_SENT'/);
  assert.match(actions, /body: JSON\.stringify\( \{ action: backendAction \} \)/);
  assert.match(orders, /label: 'Referral'[^\n]+href: CUSTOMER_MENU_HREFS\.referral/);
  assert.match(orders, /onInvite\( sendAction \)/);
  assert.match(header, /label: 'Referral', href: CUSTOMER_MENU_HREFS\.referral/);
  assert.match(header, /stashCustomerMenuAction\( sendAction \)/);
  assert.match(actions, /window\.sessionStorage\.removeItem\( PENDING_KEY \)/);
  assert.match(actions, /MAX_PENDING_AGE_MS = 10 \* 60 \* 1000/);
});

test('Profile API selects only the verified session phone and audits before an internal send', () => {
  const profile = read('amplify/functions/auth/customer-profile/handler.py');
  assert.match(profile, /"sendReferral": \(\s*"customerReferralTemplate", "wecare_referal_update",\s*"REFERRAL_REQUEST_SENT", "REFERRAL_REQUEST_UNAVAILABLE"/);
  assert.match(profile, /action not in \("sendProfileUpdate", "sendLeaveReview", "sendReferral", "sendContribute"\)/);
  assert.match(profile, /if len\(body\) != 1/);
  assert.match(profile, /identity\.normalize_phone_preserving_country\(identity_session\.phone\)/);
  const start = profile.indexOf('def _send_customer_menu_template(');
  const stop = profile.indexOf('\ndef _pepper(', start);
  assert.ok(start >= 0 && stop > start);
  const send = profile.slice(start, stop);
  assert.ok(send.indexOf('attempt_id = record_audit(') < send.indexOf('_lambda_client().invoke('));
  assert.match(send, /"phone": phone,/);
  assert.doesNotMatch(send, /"phone": body\[/);
});

test('The approved referral template has the image and DATA_EXCHANGE Flow action only', () => {
  const sender = read('amplify/functions/messaging/whatsapp-business-api/handler.py');
  const templates = read('amplify/functions/shared/lambda_utils/whatsapp_templates.py');
  const media = read('amplify/functions/shared/lambda_utils/template_media.py');
  const backend = read('amplify/functions/shared/lambda_utils/canonical_flows.py');
  const frontend = read('src/lib/canonicalFlows.ts');
  assert.match(templates, /REFERRAL = Template\(name="wecare_referal_update"/);
  assert.match(templates, /"wecare_referal_update": "1596216325046969"/);
  assert.match(templates, /REFERRAL\.name\}/);
  assert.match(media, /"wecare_referal_update": SHARED_TEMPLATE_HEADER/);
  assert.match(backend, /'referral': \{\s*'flowNumber': 'F008'/);
  assert.match(frontend, /referral: \{\s*flowNumber: 'F008'/);
  assert.match(sender, /if event\.get\('internalAction'\) == 'customerReferralTemplate'/);
  const start = sender.indexOf('def _customer_referral_template(');
  const stop = sender.indexOf('\ndef handler(', start);
  assert.ok(start >= 0 && stop > start);
  const send = sender.slice(start, stop);
  assert.match(send, /published_flow\('referral'\)/);
  assert.match(send, /publication_decision\(capability='referral', registry_row=registry\)/);
  assert.match(send, /flow_sessions\.mint_token\('referral', phone, waba='1'\)/);
  assert.match(send, /template_media\.fixed_image_header\(template\.name\)/);
  assert.match(send, /'type': 'header'/);
  assert.match(send, /'type': 'button', 'sub_type': 'flow', 'index': '0'/);
  assert.match(send, /'flow_token': token/);
  // Reject only actual object keys; comments documenting the prohibition are safe.
  assert.doesNotMatch(send, /['"](?:flow_action_data|flowActionData|marketingOptIn)['"]\s*:/);
  assert.match(send, /_track_customer_menu_template_send\(/);
  assert.match(send, /'status': 'REFERRAL_REQUEST_SENT'/);
  assert.doesNotMatch(send, /referral_response\.save_referral|create_contact\(/);
});

test('F008 DATA_EXCHANGE INIT opens published REFER screen and terminal persistence is separate', () => {
  const router = read('amplify/functions/messaging/whatsapp-business-api/flows/router.py');
  const refer = read('amplify/functions/shared/lambda_utils/referral_response.py');
  const published = JSON.parse(read('docs/whatsapp/drafts/f008-referral-preview.json'));
  assert.match(router, /if flow_key == 'referral':\s*if action == 'INIT':\s*return \{'screen': 'REFER', 'data': \{\}\}/);
  assert.deepEqual(published.screens.map(screen => screen.id), ['REFER', 'REVIEW', 'CONFIRMATION']);
  assert.match(refer, /FLOW_CODE = "WD-F008-REFERRAL"/);
  assert.match(refer, /"permission_confirmed"/);
  assert.match(refer, /"marketingOptIn": False/);
  assert.doesNotMatch(refer, /send_message\(|create_contact\(/);
});

test('WhatsApp Logs identifies Referral separately from Leave Review', () => {
  const logs = read('src/components/workspace/service/WhatsAppServiceLogs.tsx');
  assert.match(logs, /'service_details', 'wecare_leave_review', 'wecare_referal_update'/);
  assert.match(logs, /FLOW_CODES = new Set\( \[[\s\S]*?'WD-F008-REFERRAL'/);
  assert.match(logs, /message\.templateName === 'wecare_referal_update'[\s\S]*?return 'Referral'/);
  assert.match(logs, /message\.templateName === 'wecare_leave_review'[\s\S]*?return 'Leave Review'/);
});
