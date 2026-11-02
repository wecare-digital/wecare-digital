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
// The owner-approved single-workbench console uses a payment rail and tool links,
// not the removed Display/Create/Ledger tab-strip class names. Check navigation
// semantics and the actual rendered inspector instead of an old CSS implementation.
check(page.includes("one(router.query.panel) === 'framework'") &&
      page.includes("panel:'framework'") &&
      page.includes('<PaymentFramework section={section} />') &&
      page.includes('className="payment-rail"') &&
      page.includes('className="console-tools"'),
      'Collect/Vault/Contribute Framework or working navigation missing');
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
// The current headline deliberately says "Customer pays" and shows the live
// server breakdown. Never require a specific prose label or a hardcoded amount.
check(contribute.includes('fetchContributionPrice()') &&
      contribute.includes('setPrice(next)') &&
      contribute.includes('b.totalPayablePaise') &&
      contribute.includes("loading?'Checking…'") &&
      contribute.includes("'Unavailable'"),
      'Contribute heading must reflect loading, unavailable and server quote states');

if (failures.length) {
  for (const issue of failures) console.error('FAIL:', issue);
  process.exit(1);
}
console.log('PASS: offline Pay & Flow, approved-template and post-call SMS source contracts');
