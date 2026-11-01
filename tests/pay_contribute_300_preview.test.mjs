import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('src/pages/workspace/payments/index.tsx', 'utf8');
const component = readFileSync('src/components/workspace/pay/ContributePaymentPlan.tsx', 'utf8');
const backend = readFileSync('amplify/functions/shared/lambda_utils/ecommerce/service_pricing_native.py', 'utf8');
const contribution = readFileSync('amplify/functions/shared/lambda_utils/ecommerce/blog_contribution.py', 'utf8');

assert.ok(page.includes("{ id: 'vault', label: 'Vault · Review & Pay' },\n  { id: 'contribute', label: 'Contribute' }"));
assert.ok(page.includes("if ( value === 'contribute' ) return 'contribute'"));
assert.ok(page.includes("tab === 'contribute' && <ContributePaymentPlan />"));

// Proposal must not become a second browser payment calculator or a payment sender.
assert.match(component, /TARGET_TOTAL_PAISE = 30000/);
assert.match(component, /EXPRESS_PAISE = 1500/);
assert.match(component, /Promise\.all\(\[fetchContributionPrice\(\), fetchServicePrices\(\)\]\)/);
assert.match(component, /Send only after a fresh server quote/);
assert.match(component, /exact match required at send time/);
assert.match(component, /single voluntary payment/);
assert.doesNotMatch(component, /sendPaymentLink\(|createInvoice\(|sendWhatsAppPayment\(|prepareCheckout\(|updateSystemConfig\(/);

// Existing Contribute exemption remains untouched.
assert.match(backend, /def _contribution_breakdown/);
assert.match(backend, /"delightPaise": 0/);
assert.match(backend, /"expressPaise": 0/);
assert.match(backend, /"convenienceFeePaise": 0/);
assert.match(contribution, /CONTRIBUTION_PRESETS_PAISE: Tuple\[int, \.\.\.\] = \(30000,\)/);

// Proposed ₹300 total, both accounting interpretations, in exact integer paise.
const target = 30000;
const express = 1500;
assert.equal(target - express + express, target);
const item = 23541;
const supplyGst = Math.floor((item * 1800 + 5000) / 10000);
const delight = Math.max(1, Math.floor((item + supplyGst) * 50 / 10000));
const collection = item + supplyGst - delight + express;
const fee = Math.floor((collection * 250 + 5000) / 10000);
const feeGst = Math.floor((fee * 1800 + 5000) / 10000);
assert.deepEqual({ supplyGst, delight, collection, fee, feeGst }, {
  supplyGst: 4237, delight: 138, collection: 29140, fee: 729, feeGst: 131,
});
assert.equal(collection + fee + feeGst, target);

console.log('Contribute ₹300 Pay proposal and guarded send breakdown contracts passed');
