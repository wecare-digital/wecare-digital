/** Source-contract checks for the existing Pay & Flow page navigation.
 * Run: node --test tests/payflow_navigation.test.mjs
 * No browser session, payment, Meta send, or AWS mutation is required.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const root = new URL('../', import.meta.url);
const read = path => readFileSync(new URL(path, root), 'utf8');
const page = read('src/pages/workspace/payments/index.tsx');
const shell = read('src/components/PageShell.tsx');
const vault = read('src/components/workspace/service/SecureFiles.tsx');
const contribute = read('src/components/workspace/pay/ContributePaymentPlan.tsx');
const overview = read('src/components/workspace/pay/CollectOverview.tsx');

test('Pay & Flow stays on its existing page with one dropdown and exactly three work tabs', () => {
  assert.match(page, /id="pay-flow-section"/);
  assert.match(page, /value: 'collect', label: 'Collect'/);
  assert.match(page, /value: 'vault', label: 'Vault'/);
  assert.match(page, /value: 'contribute', label: 'Contribute'/);
  assert.match(page, /value: 'display', label: 'Display'/);
  assert.match(page, /value: 'create', label: 'Create'/);
  assert.match(page, /value: 'ledger', label: 'Ledger'/);
  assert.match(page, /tabs=\{\[\]\} navigation=\{nav\}/);
  assert.match(shell, /navigation\?: React\.ReactNode/);
  assert.match(shell, /tabs\.length > 0 &&/);
});

test('legacy bookmarks resolve without breaking existing Create, default and timing links', () => {
  assert.match(page, /if \(view === 'defaults'\) return \{section: 'collect', tab: 'create'/);
  assert.match(page, /if \(view === 'timing'\) return \{section: 'vault', tab: 'create'/);
  assert.match(page, /return \{section: view, tab: chosenTab, legacy: null\}/);
  assert.match(page, /return \{section: 'collect', tab: 'display', legacy: null\}/);
  assert.match(page, /one\(rawLedger\) === 'activity'/);
  assert.match(page, /query\.invoice = invoice/);
  assert.match(page, /view: 'collect', tab: 'create', preset: choice\.slug/);
});

test('existing payment, file and contribution tools remain in Create', () => {
  assert.match(page, /<PayFlowPage signOut=\{signOut\} user=\{user\} embedded mode="collect"/);
  assert.match(page, /<VaultWorkbench signOut=\{signOut\} user=\{user\} embedded workspaceView="create"/);
  assert.match(page, /<ContributePaymentPlan workspaceView="create"/);
  assert.match(page, /<DefaultInvoiceItems onUse=\{useDefaultItem\}/);
  assert.match(page, /<VaultDeliveryTiming \/>/);
  assert.match(vault, /workspaceView === 'create' && <section className="sf-workbench"/);
  assert.match(contribute, /workspaceView === 'create' \? \(/);
});

test('Display is read-only, while scoped ledgers reuse existing authoritative records', () => {
  assert.match(page, /<CollectOverview \/>/);
  assert.match(page, /workspaceView="display"/);
  assert.match(page, /serviceKind="VAULT"/);
  // Contribute is a catalog order, not a request-service ledger filter.
  assert.doesNotMatch(page, /serviceKind="CONTRIBUTE"/);
  assert.match(page, /Existing Contribute records/);
  assert.match(page, /view=contribute&tab=payments/);
  assert.match(page, /view=ledger&ledger=invoices/);
  assert.match(page, /<PaymentsActivity \/>/);
  assert.match(page, /mode="invoices"/);
  assert.match(vault, /workspaceView === 'create' && <td>/);
  assert.match(overview, /row\.entryPoint \|\| ''\)\.toLowerCase\(\) === 'pay_flow'/);
  assert.doesNotMatch(overview, /sendPaymentLinkResult|sendStaffContributionPaymentOnce|revokeSecureFile/);
});

test('the old WhatsApp catalog, payment templates and customer files are not changed', () => {
  assert.doesNotMatch(page, /sendPaymentLinkResult|sendStaffContributionPaymentOnce/);
  assert.match(page, /from '\.\.\/\.\.\/\.\.\/components\/workspace\/pay\/PayFlow'/);
  assert.match(page, /from '\.\.\/\.\.\/\.\.\/components\/workspace\/pay\/InvoiceRecords'/);
});
