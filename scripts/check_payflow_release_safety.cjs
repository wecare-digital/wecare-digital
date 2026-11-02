#!/usr/bin/env node
'use strict';
// Offline production source gate. Never imports handlers or invokes providers.
// Kept under scripts/ because owner retired tests/ and .github/workflows/.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');
const failures = [];
const check = (value, reason) => { if (!value) failures.push(reason); };

const wire = read('amplify/functions/messaging/whatsapp-business-api/handler.py');
const outbound = read('amplify/functions/messaging/outbound-whatsapp/handler.py');
const direct = read('amplify/functions/shared/lambda_utils/direct_send.py');
const client = read('src/api/client.ts');
const inbound = read('amplify/functions/messaging/inbound-whatsapp-handler/handler.py');
const sender = wire.slice(wire.indexOf('def _send_message('), wire.indexOf('def _send_text('));
check(sender.includes("message.get('type') not in") &&
      sender.includes("'template'") && !sender.includes("'interactive'"),
      'Meta wire must allow approved templates and deny standalone interactive');
check(outbound.includes('UNSUPPORTED_MESSAGE_TYPE') &&
      outbound.includes("wire.get('type') in {") &&
      !outbound.slice(outbound.indexOf('def _send_direct_api('),
                      outbound.indexOf('def _send_direct_api(') + 800).includes("'interactive'"),
      'Outbound wire must reject unknown and interactive message types');
for (const retired of ['_send_product_msg', '_send_flow_msg',
                       '_send_request_contact_info', '_send_contract_flow']) {
  check(!wire.includes('def ' + retired + '('), 'Removed direct builder returned: ' + retired);
}
check(!direct.includes('def build_authentication_otp_payload('),
      'Direct interactive OTP builder returned');
for (const retired of ['sendTestInteractive', 'sendTestFlow', 'sendTestProduct']) {
  check(!client.includes('export async function ' + retired + ' '),
        'Retired browser sender returned: ' + retired);
}
check(inbound.includes('nfm_reply'), 'Incoming template Flow reply parser missing');

const plivo = read('amplify/functions/messaging/plivo-answer/handler.py');
const calling = read('amplify/functions/messaging/whatsapp-calling/handler.py');
const manifest = read('config/lambda-env-manifest.json');
JSON.parse(manifest);
check(/POST_CALL_SMS_ENABLED = os\.environ\.get\([\s\S]{0,100}'false'\)/.test(plivo) &&
      plivo.includes('if not POST_CALL_SMS_ENABLED or not caller:'),
      'Plivo post-call SMS must honor default-off deployment flag');
check(manifest.includes('"POST_CALL_SMS_ENABLED": "false"'),
      'Deploy manifest must not silently reenable post-call SMS');
check(calling.includes('def _sms_sender_registered()') &&
      calling.includes("region_name='ap-south-1'") &&
      calling.includes("item.get('Registered') is True"),
      'Call SMS reenablement must require verified Indian registered sender');
const settings = calling.slice(calling.indexOf("sms_on_call = body.get('smsOnCall')"));
check(settings.indexOf('if sms_on_call and not _sms_sender_registered():') >= 0 &&
      settings.indexOf('if sms_on_call and not _sms_sender_registered():') <
      settings.indexOf('table.put_item(Item={') &&
      settings.includes('SMS_SENDER_NOT_REGISTERED') &&
      calling.includes('return False  # Default: disabled'),
      'Calling SMS must fail closed, checking sender before config writes');
const callingUi = read('src/components/workspace/whatsapp/calling.tsx');
check(callingUi.includes('if ( !response.ok )') &&
      callingUi.includes('verify live registration before enabling'),
      'Calling UI must not report unverified SMS enablement as success');

const page = read('src/pages/workspace/payments/index.tsx');
const framework = read('src/components/workspace/pay/PaymentFramework.tsx');
const definitions = read('src/lib/paymentFramework.ts');
// Check the actual canonical payment console, not retired CSS selectors. The
// previous guard checked pay-flow-sections/pay-flow-work-tabs, which were removed
// when the working Collect/Vault/Contribute console was rebuilt. The new checks
// bind navigation to the section values, scoped work tabs, and actual framework
// route. Missing any one of them still blocks production.
check(page.includes("type PaymentSection = 'collect' | 'vault' | 'contribute'") &&
      page.includes("type PaymentTab = 'display' | 'create' | 'ledger'") &&
      page.includes('SECTION_OPTIONS.map') &&
      page.includes('className="payment-rail"') &&
      page.includes('className="console-tools"') &&
      page.includes("panel: 'framework'") &&
      page.includes('<PaymentFramework section={section} />') &&
      page.includes('changeSection(option.value)') &&
      page.includes("tab:'create'") &&
      page.includes("tab:'ledger'"),
      'Collect/Vault/Contribute navigation or message framework is unavailable');
for (const role of ['payment', 'status', 'invoice', 'access']) {
  check(definitions.includes('  ' + role + ':'), 'Payment framework template missing: ' + role);
}
check(framework.includes('OutgoingMessageContent'),
      'Framework no longer shows full message/header/button content');
const collect = read('src/components/workspace/pay/CollectOverview.tsx');
check(collect.includes('setRows([])') && collect.includes('totals[currency]'),
      'Collect stale-refresh or currency total regression');
const vault = read('src/components/workspace/pay/VaultWorkbench.tsx');
check(vault.includes('deliveryRequest') && vault.includes('listRequest'),
      'Vault stale file/response identity guard missing');
const contribute = read('src/components/workspace/pay/ContributePaymentPlan.tsx');
// The rebuilt Contribute header intentionally says "Customer pays", not the
// retired "Live customer total:" text. Require a read-only server quote and
// display of its returned total, including correct loading/unavailable states.
check(contribute.includes('fetchContributionPrice()') &&
      contribute.includes('price.available ? price.breakdown : undefined') &&
      contribute.includes('Customer pays') &&
      contribute.includes('b?money(b.totalPayablePaise)') &&
      contribute.includes("'Quote unavailable'") &&
      contribute.includes('ContributeStaffControls price={price}'),
      'Contribute must present the server-quoted amount with safe loading states');

if (failures.length) {
  for (const issue of failures) console.error('FAIL:', issue);
  process.exit(1);
}
console.log('PASS: offline Pay & Flow, approved-template and post-call SMS source contracts');
