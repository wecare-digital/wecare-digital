import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {buildSync} from 'esbuild';

const built=buildSync({entryPoints:['src/lib/cart.ts'],bundle:true,platform:'node',format:'cjs',write:false});
const evaluatedModule={exports:{}};
vm.runInNewContext(built.outputFiles[0].text,{module:evaluatedModule,exports:evaluatedModule.exports,process:{env:{}},URL});
const {cartRequiresDelivery}=evaluatedModule.exports;
test('Vault requires a saved delivery address in the customer cart',()=>{
  assert.equal(cartRequiresDelivery([{productId:'d4cfc6e8-10b3-5c47-94c8-3c69f4c03907'}]),true);
  assert.equal(cartRequiresDelivery([{productId:'e1ca7833-5d7d-567b-837c-face04647598'}]),false);
});
