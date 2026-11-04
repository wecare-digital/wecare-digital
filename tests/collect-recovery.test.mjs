import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {buildSync} from 'esbuild';

const built=buildSync({entryPoints:['src/lib/collect.ts'],bundle:true,platform:'node',format:'cjs',write:false});
const evaluatedModule={exports:{}};
vm.runInNewContext(built.outputFiles[0].text,{module:evaluatedModule,exports:evaluatedModule.exports});
const {verifiedCollectRecovery}=evaluatedModule.exports;
const complete={invoiceId:'opaque-invoice',referenceId:'WD-PAY-OPAQUE',invoiceNumber:'WD/2627/001',status:'created',total:118,items:[{name:'Saved item',amount:100,quantity:1}]};
const expected={referenceId:complete.referenceId,invoiceId:complete.invoiceId};

test('Completed invoice details preserve opaque identities and permit reconciliation',()=>{
  assert.equal(verifiedCollectRecovery(complete,expected),true);
  assert.equal(verifiedCollectRecovery({...complete,total:'118.00'},expected),true);
});
test('A claiming placeholder or partial details cannot resolve a retained create intent',()=>{
  for(const change of [{status:'claiming'},{invoiceNumber:''},{invoiceNumber:' '},{items:[]},{items:undefined},{total:0},{total:-1},{total:NaN},{total:Infinity},{total:''},{total:'garbage'}]){
    assert.equal(verifiedCollectRecovery({...complete,...change},expected),false,JSON.stringify(change));
  }
});
test('Recovery rejects another invoice or reference even when it looks complete',()=>{
  for(const change of [{invoiceId:'other'},{invoiceId:''},{referenceId:'other'},{referenceId:''}])assert.equal(verifiedCollectRecovery({...complete,...change},expected),false);
  assert.equal(verifiedCollectRecovery(complete,{referenceId:''}),false);
});
test('List discovery may omit the expected invoice id but must match the retained reference',()=>{
  assert.equal(verifiedCollectRecovery(complete,{referenceId:complete.referenceId}),true);
  assert.equal(verifiedCollectRecovery(null,expected),false);
});
