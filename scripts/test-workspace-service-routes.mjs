/**
 * Runtime test of the actual TypeScript workspace route helper.
 * In particular, catches the reported bug where selecting Vault Ledger
 * routed to tab=logs even though source text mentioned both options.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const input = readFileSync('src/lib/serviceWorkspaceRoutes.ts', 'utf8');
const compiled = ts.transpileModule(input, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  reportDiagnostics: true,
});
if (compiled.diagnostics?.length) {
  throw new Error('TypeScript transpilation diagnostics: ' +
    compiled.diagnostics.map(d => String(d.messageText)).join(', '));
}
const output = { exports: {} };
new Function('exports', 'module', compiled.outputText)(output.exports, output);
const {
  SERVICE_WORKSPACE_VIEWS, serviceWorkspaceQuery, serviceWorkspaceTab,
  serviceWorkspaceView,
} = output.exports;

assert.deepEqual([...SERVICE_WORKSPACE_VIEWS], [
  'submit-request', 'request-amendment', 'drop-docs', 'vault', 'shipments', 'contribute',
]);
assert.equal(serviceWorkspaceView('requests'), 'submit-request');
assert.equal(serviceWorkspaceView(''), 'vault');
assert.equal(serviceWorkspaceView('unknown-service'), 'vault');
assert.equal(serviceWorkspaceView(['drop-docs']), 'drop-docs');

const cases = [
  ['vault', 'documents'], ['vault', 'logs'], ['vault', 'pricing'], ['vault', 'ledger'],
  ['drop-docs', 'upload'], ['drop-docs', 'pricing'], ['drop-docs', 'ledger'],
  ['shipments', 'track'], ['shipments', 'pickup'], ['shipments', 'pickup-ledger'],
  ['submit-request', 'overview'], ['submit-request', 'ledger'],
  ['request-amendment', 'overview'], ['request-amendment', 'ledger'],
  ['contribute', 'overview'], ['contribute', 'payments'],
];
for (const [view, tab] of cases) {
  const next = serviceWorkspaceQuery(view, tab);
  assert.equal(next.view, view);
  assert.equal(serviceWorkspaceTab(serviceWorkspaceView(next.view), next.tab), tab,
    view + ' ' + tab + ' navigation must render what was selected');
}
assert.deepEqual(serviceWorkspaceQuery('vault', 'ledger'),
  {view: 'vault', tab: 'ledger'});
assert.deepEqual(serviceWorkspaceQuery('vault', 'logs'),
  {view: 'vault', tab: 'logs'});
assert.deepEqual(serviceWorkspaceQuery('vault', 'documents'), {view: 'vault'});
assert.deepEqual(serviceWorkspaceQuery('shipments', 'pickup-ledger'),
  {view: 'shipments', tab: 'pickup-ledger'});
assert.deepEqual(serviceWorkspaceQuery('drop-docs', 'upload'), {view: 'drop-docs'});
assert.deepEqual(serviceWorkspaceQuery('submit-request', 'unknown'),
  {view: 'submit-request'});
console.log('PASS: All Service workspace views and tab selections round-trip at runtime');
