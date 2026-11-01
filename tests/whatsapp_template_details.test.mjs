import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeWhatsAppTemplateDetails } from '../src/lib/whatsappTemplateDetails.ts';

const meta = {
  metaTemplateId: '2714938845570815',
  templateName: 'wecare_whatapp_native_pay_template',
  templateStatus: 'APPROVED',
  language: 'en',
  category: 'UTILITY',
  components: [
    { type: 'HEADER', format: 'IMAGE' },
    { type: 'BODY', text: 'Review and Pay' },
    { type: 'BUTTONS', buttons: [{ type: 'ORDER_DETAILS', text: 'Review and Pay' }] },
  ],
};

test('canonicalizes wrapped staff Meta response and preserves actual approval', () => {
  const row = normalizeWhatsAppTemplateDetails({ template: meta }, meta.metaTemplateId);
  assert.equal(row?.id, meta.metaTemplateId);
  assert.equal(row?.name, meta.templateName);
  assert.equal(row?.status, 'APPROVED');
  assert.deepEqual(row?.components, meta.components);
});

test('accepts native Meta response without changing declined statuses', () => {
  const row = normalizeWhatsAppTemplateDetails({
    id: '1754227779211208', name: 'wecare_order_status_v3',
    status: 'paused', components: [{ type: 'BODY', text: 'Updated' }],
  });
  assert.equal(row?.status, 'PAUSED');
});

test('rejects mismatched IDs, conflicting aliases, and unsafe numeric IDs', () => {
  assert.equal(normalizeWhatsAppTemplateDetails({ template: meta }, '999'), null);
  assert.equal(normalizeWhatsAppTemplateDetails({ ...meta, id: '999' }), null);
  assert.equal(normalizeWhatsAppTemplateDetails({ ...meta, status: 'REJECTED' }), null);
  assert.equal(normalizeWhatsAppTemplateDetails({ ...meta, name: 'another_template' }), null);
  assert.equal(normalizeWhatsAppTemplateDetails({ ...meta, metaTemplateId: Number.MAX_SAFE_INTEGER + 10 }), null);
});

test('no approval when provider fields or components are missing', () => {
  assert.equal(normalizeWhatsAppTemplateDetails(null), null);
  assert.equal(normalizeWhatsAppTemplateDetails({ template: { ...meta, templateStatus: undefined } }), null);
  assert.equal(normalizeWhatsAppTemplateDetails({ template: { ...meta, components: undefined } }), null);
  assert.equal(normalizeWhatsAppTemplateDetails({ template: { ...meta, metaTemplateId: undefined } }), null);
});

test('provider quality UNKNOWN does not override template APPROVED status', () => {
  const row = normalizeWhatsAppTemplateDetails({ template: { ...meta, qualityScore: { score: 'UNKNOWN' } } });
  assert.equal(row?.status, 'APPROVED');
});
