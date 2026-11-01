import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('src/pages/workspace/payments/index.tsx', 'utf8');
const plan = readFileSync('src/components/workspace/pay/ContributePaymentPlan.tsx', 'utf8');
const controls = readFileSync('src/components/workspace/pay/ContributeStaffControls.tsx', 'utf8');
const paymentMedia = readFileSync('src/components/workspace/pay/PaymentTemplateMedia.tsx', 'utf8');
const pricing = readFileSync('amplify/functions/shared/lambda_utils/ecommerce/service_pricing_native.py', 'utf8');

// Staff sees Contribute immediately after Vault. This section is not a generic
// Collect invoice: its purpose and tax policy remain separate.
assert.match(page, /\{ id: 'vault', label: 'Vault · Review & Pay' \},\s*\{ id: 'contribute', label: 'Contribute' \}/);
assert.match(plan, /<ContributeStaffControls/);
assert.match(plan, /setLoading\(true\);\s*setPrice\(UNAVAILABLE\);\s*setTemplates\(null\)/);
assert.match(plan, /refreshPrice=\{\(\) => setRefreshSeq\(current => current \+ 1\)\}/);
assert.match(plan, /<PaymentTemplateMedia templates=\{templates\} serviceLabel="Contribute reference" signedPreview\s*\/>/);

// Controls use saved staff Contacts, not browser-typed arbitrary recipients.
assert.match(controls, /api\.listContacts\(\)/);
assert.match(controls, /setContacts\(\[\]\); \/\/ No stale recipient/);
assert.match(controls, /!loadingContacts && !loadingPrice/);
assert.match(controls, /!c\.deletedAt && !c\.archivedAt && !c\.locked/);
assert.match(controls, /<select id="contribute-customer-choice" value=\{selectedId\}/);
assert.match(controls, /Backend identity verification is still required|backend verification required/i);

// Meta approval is separately fetched using the registered template ID;
// absence of provider evidence never silently grants approval.
assert.match(controls, /api\.getTemplateDetails\(templateId\)/);
assert.match(controls, /status === 'APPROVED'/);
assert.match(controls, /ORDER_DETAILS/);
assert.match(controls, /setApproval\('unverified'\)/);

// Price is a strict server-quote equality check; Express stays an internal
// allocation under current voluntary-contribution policy.
assert.match(controls, /TARGET_PAISE = 30000/);
assert.match(controls, /EXPRESS_ALLOCATION_PAISE = 1500/);
assert.match(controls, /p\.paise !== TARGET_PAISE/);
for (const field of [
  'itemSubtotalPaise', 'collectionBeforeConveniencePaise', 'totalPayablePaise',
  'supplyGstPaise', 'delightPaise', 'expressPaise', 'convenienceFeePaise',
  'convenienceGstPaise',
]) assert.ok(controls.includes(field), 'missing amount guard: ' + field);
assert.match(pricing, /def _contribution_breakdown/);
assert.match(pricing, /"expressPaise": 0/);
assert.match(pricing, /"delightPaise": 0/);

// Staff can review and copy an internal draft, but cannot accidentally send
// an unauthorized or wrong-priced payment request.
assert.match(controls, /Internal draft review — nothing sent/);
assert.match(controls, /Copy internal review draft/);
assert.match(controls, /Unsaved in-memory draft/);
assert.match(controls, /Send ₹300 Review & Pay/);
assert.match(controls, /api\.sendStaffContributionPaymentOnce\(selected\.id\)/);
assert.match(controls, /const canSend = .*priceMatches/);
assert.match(controls, /approval === 'approved'/);
assert.match(controls, /useConfirm\(\)/);
assert.match(controls, /setSendLocked\(true\)/);
assert.match(controls, /Check the chat and ledger; do not retry blindly/);
for (const unsafeCall of [
  /api\.sendPaymentLink\(/,
  /api\.sendWhatsAppTemplateMessage\(/,
  /api\.createInvoiceEngine\(/,
  /api\.previewInvoiceEngine\(/,
  /api\.requestSecureFilePayment\(/,
  /api\.createContact\(/,
  /localStorage\./,
  /sessionStorage\./,
]) assert.doesNotMatch(controls, unsafeCall);

// The shared S3 preview uses short-lived signed GETs. Staff cannot replace
// registered Meta media or use the wrong image as the header.
assert.match(paymentMedia, /expiresInSeconds <= 60/);
assert.match(paymentMedia, /Signed S3 preview/);
assert.match(paymentMedia, /approved template header/);
assert.match(paymentMedia, /ORDER_DETAILS item icon/);

console.log('Contribute staff-controls guarded one-shot send contracts passed');
