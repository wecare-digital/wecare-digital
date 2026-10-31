// Offline Collect/payment-send regression. Uses the actual production helper AST.
// No browser, AWS credentials, payments, WhatsApp sends, or external network.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const pay = readFileSync(new URL('../src/components/workspace/pay/PayFlow.tsx', import.meta.url), 'utf8');
const page = readFileSync(new URL('../src/pages/workspace/payments/index.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('PayFlow.tsx', pay, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
assert.equal(ast.parseDiagnostics.length, 0, 'Collect TypeScript should parse');

const names = new Set([
  'PAYMENT_REQUEST_DELIVERY_SUCCESS',
  'hasConfirmedPaymentRequestDelivery',
  'SEND_SUCCESS_COMMAND',
  'SEND_SUCCESS_RECONCILED',
  'describeSendOutcome',
]);
const statements = ast.statements.filter(stmt =>
  ts.isVariableStatement(stmt) &&
  stmt.declarationList.declarations.some(decl =>
    ts.isIdentifier(decl.name) && names.has(decl.name.text)));
const found = new Set(statements.flatMap(stmt =>
  stmt.declarationList.declarations.map(decl => decl.name.getText(ast))));
assert.deepEqual(found, names, 'All production payment-send guards must remain testable');
const pureSource = statements.map(stmt => stmt.getText(ast)).join('\n');
const js = ts.transpileModule(pureSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
}).outputText;
const { hasConfirmedPaymentRequestDelivery: hasDelivery, describeSendOutcome: outcome } =
  vm.runInNewContext(js + '\n;({ hasConfirmedPaymentRequestDelivery, describeSendOutcome })');

function check(label, input, delivery, expectedTone, textMatch) {
  const actual = outcome(input, delivery);
  assert.equal(actual.tone, expectedTone, label);
  assert.match(actual.text, textMatch, label);
}

const sent = { ok: true, data: { status: 'payment_link_sent', sendStatus: 'SENT' } };
const pending = { ok: false, failure: { status: 502, kind: 'unavailable', message: 'Upstream timed out' } };
const refused = { ok: false, failure: { status: 409, kind: 'conflict', message: 'Refused by gateway' } };
const dedup = { ok: true, data: { status: 'send_in_progress', sendStatus: 'PENDING', deduplicated: true } };
const explicitRefusal = { ok: true, data: { status: 'payment_link_rejected', sendStatus: 'REJECTED' } };

assert.equal(hasDelivery(undefined), false, 'Absent delivery log is never success');
assert.equal(hasDelivery([{ channel: 'whatsapp', status: 'read', error: '' }]), false,
  'Reading the invoice is not proof the payment request was accepted');
assert.equal(hasDelivery([{ channel: 'whatsapp_payment', status: 'accepted', error: '' }]), true);
assert.equal(hasDelivery([{ channel: 'whatsapp_payment', status: 'sent', error: 'Meta refused' }]), false);
assert.equal(hasDelivery([{ channel: 'whatsapp_payment', status: 'read', error: '' }]), true);

check('confirmed send', sent, false, 'success', /payment request sent/i);
check('502 without readback', pending, false, 'error', /unknown.*reconcile/i);
check('502 with durable readback', pending, true, 'success', /accepted.*delivery/i);
check('rejected send even with stale readback', refused, true, 'error', /refused.*NOT sent/i);
check('explicit terminal refusal', explicitRefusal, false, 'error', /refused.*NOT sent/i);
check('deduplicated in-flight send', dedup, false, 'error', /already in progress.*do not resend/i);

assert.ok(page.includes('mode="collect"'), 'Collect tab must mount PayFlow in collect mode');
assert.ok(page.includes('mode="invoices"'), 'Ledger must mount invoice readback mode');
assert.ok(pay.includes("entryPoint: 'pay_flow'"), 'Collect must retain server-side source identity');
assert.ok(pay.includes('if ( invoiceCreateInFlight.current ) return;'), 'Create must be single-flight');
assert.ok(pay.includes('invoiceCreateInFlight.current = true;'), 'Create must claim in-flight guard');
assert.ok(pay.includes('invoiceCreateInFlight.current = false;'), 'Create guard must release');
assert.ok(pay.includes('crypto.randomUUID()'), 'Each collection must have a fresh reference');
assert.ok(pay.includes('api.createInvoiceEngineResult( req )'), 'Creation must use server response');
assert.ok(pay.includes('api.getInvoiceDeliveryLog( r.invoiceId )'), 'Ambiguous send must read back');
assert.ok(pay.includes('hasConfirmedPaymentRequestDelivery( delivery.deliveryLogs )'));
assert.ok(pay.includes('describeSendOutcome( sent, deliveryConfirmed )'));
assert.ok(!pay.includes('api.deleteInvoice('), 'Issued GST invoices must never be hard-deleted');

console.log('PASS: Collect routing, single-flight create, refusal/duplicate/ambiguous send, durable readback and immutable ledger contracts');
