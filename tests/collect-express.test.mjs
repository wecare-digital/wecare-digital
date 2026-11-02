import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {buildSync} from 'esbuild';

// Exercise the real draft serializer. No API, renderer or provider is invoked.
const built=buildSync({entryPoints:['src/lib/collect.ts'],bundle:true,platform:'node',format:'cjs',write:false});
const module={exports:{}};
vm.runInNewContext(built.outputFiles[0].text,{module,exports:module.exports});
const {collectDraft,collectInputKey}=module.exports;
const customer={id:'saved-customer',name:'Example Customer',phone:'+919000000001',checkoutDeliveryAddress:{addressLine1:'Example street',city:'Kolkata',state:'West Bengal',postalCode:'700012',country:'India',countryCode:'IN'}};
const lines=[{name:'Custom service',amount:'100.00',quantity:'1',gstRate:'18'}];

test('Collect requires an explicitly entered Express amount',()=>{
  for(const input of [undefined,'',' ','-1','1.234','NaN','Infinity','1e3'])assert.equal(collectDraft(customer,lines,'',input),null,String(input));
});
test('Explicit zero Express is serialized rather than omitted',()=>{
  const draft=collectDraft(customer,lines,'','0');
  assert.ok(draft);assert.equal(draft.shipping,0);assert.ok(Object.hasOwn(draft,'shipping'));
});
test('Entered Express reaches the existing shipping contract without changing item or GST inputs',()=>{
  const draft=collectDraft(customer,lines,'','45.50');
  assert.equal(draft.shipping,45.5);
  assert.equal(draft.items[0].amount,100);assert.equal(draft.items[0].quantity,1);assert.equal(draft.items[0].gstRate,18);
  assert.equal(lines[0].amount,'100.00');
});
test('An Express edit invalidates the local reviewed-input identity',()=>{
  const before=collectInputKey(collectDraft(customer,lines,'','0'));
  const after=collectInputKey(collectDraft(customer,lines,'','45'));
  assert.notEqual(before,after);
});
