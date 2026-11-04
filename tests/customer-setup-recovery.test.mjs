import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {build} from 'esbuild';

const built = await build({entryPoints:['src/lib/customer-setup.ts'],bundle:true,platform:'node',format:'cjs',write:false});
const mod = {exports:{}};
vm.runInNewContext(built.outputFiles[0].text,{module:mod,exports:mod.exports});
const {partialCreateContactId,needsCustomerSetup,completeCustomerSetup,ensureCustomerSetup,SETUP_INCOMPLETE_MESSAGE} = mod.exports;

const SUB = '940844d8-c031-70cf-4398-f1a58831231b';
const linked = {id:'c1',contactId:'c1',phone:'+919830047340',checkoutCustomerId:SUB};
const unlinked = {id:'c1',contactId:'c1',phone:'+919830047340',checkoutCustomerId:''};

test('a create that saved the contact but not the account is recognised', () => {
  assert.equal(partialCreateContactId({details:{contactCreated:true,contactId:'c1'}}),'c1');
  for (const failure of [null, {}, {details:{contactCreated:false,contactId:'c1'}}, {details:{contactCreated:true}}, {details:{contactCreated:'true',contactId:'c1'}}]) {
    assert.equal(partialCreateContactId(failure),'');
  }
});

test('only a phone-bearing unlinked record needs setup', () => {
  assert.equal(needsCustomerSetup(unlinked),true);
  assert.equal(needsCustomerSetup(linked),false);
  assert.equal(needsCustomerSetup({phone:'',checkoutCustomerId:''}),false);
  assert.equal(needsCustomerSetup(null),false);
});

test('an already-linked record makes no setup request', async () => {
  let calls = 0;
  const out = await ensureCustomerSetup(linked, async () => { calls++; return {ok:true,data:linked}; });
  assert.equal(out.ok,true);
  assert.equal(calls,0);
});

test('setup succeeds only when the returned record carries the account link', async () => {
  const ok = await completeCustomerSetup('c1', async id => ({ok:true,data:{...unlinked,id,checkoutCustomerId:SUB}}));
  assert.equal(ok.ok,true);
  const stillUnlinked = await completeCustomerSetup('c1', async () => ({ok:true,data:unlinked}));
  assert.equal(stillUnlinked.ok,false);
  assert.equal(stillUnlinked.pendingContactId,'c1');
  assert.equal(stillUnlinked.message,SETUP_INCOMPLETE_MESSAGE);
});

test('failures keep the same record pending and never ask for a new create', async () => {
  const unavailable = await completeCustomerSetup('c1', async () => ({ok:false,failure:{kind:'unavailable',status:503,message:'x',url:'',details:{error:'Contact saved, but customer account setup is incomplete.',contactId:'c1'}}}));
  assert.equal(unavailable.ok,false);
  assert.equal(unavailable.pendingContactId,'c1');
  const conflict = await completeCustomerSetup('c1', async () => ({ok:false,failure:{kind:'client',status:409,message:'x',url:'',details:{errorCode:'CUSTOMER_IDENTITY_CONFLICT'}}}));
  assert.match(conflict.message,/administrator/i);
  const thrown = await completeCustomerSetup('c1', async () => { throw new Error('network'); });
  assert.equal(thrown.pendingContactId,'c1');
  const none = await completeCustomerSetup('', async () => { throw new Error('must not call'); });
  assert.equal(none.ok,false);
});

test('every workspace create screen offers Complete customer setup', () => {
  for (const file of [
    'src/pages/workspace/customers/index.tsx',
    'src/components/workspace/pay/PaymentCustomerEditor.tsx',
    'src/components/workspace/pay/PayFlow.tsx',
    'src/components/ws/customers/CustomerEditor.tsx',
  ]) {
    const source = readFileSync(file,'utf8');
    assert.match(source,/Complete customer setup/,file);
    assert.match(source,/provisionContactIdentityResult/,file);
  }
});
