import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {buildSync} from 'esbuild';
const code=buildSync({entryPoints:['src/lib/cart.ts'],bundle:true,platform:'node',format:'cjs',write:false}).outputFiles[0].text;
const product={id:'native:commerce-test-1',slug:'',name:'Commerce Test - Rs 1',formattedPrice:'₹0.99',variants:[{id:'WCTEST1R26',label:'Standard',inStock:true}]};
test('reopening a hidden test item refreshes its saved label without changing quantities or other lines',()=>{
  const other={productId:'native:other',variantId:'other',ref:'native:other:other',slug:'',name:'Other item',formattedPrice:'₹12.00',quantity:3};
  const original=[{productId:product.id,variantId:'WCTEST1R26',ref:'native:commerce-test-1:WCTEST1R26',slug:'',name:product.name,formattedPrice:'₹1.00',quantity:1},other];
  const storage=new Map([['wecare.cart.v1',JSON.stringify(original)]]);
  const cartModule={exports:{}};
  const window={localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)}};
  vm.runInNewContext(code,{module:cartModule,exports:cartModule.exports,window,process:{env:{}},URL});
  for(let i=0;i<2;i++){
    const items=cartModule.exports.refreshCartLineDisplay(product,'WCTEST1R26');
    assert.equal(items.length,2);
    assert.equal(items[0].formattedPrice,'₹0.99');
    assert.equal(items[0].quantity,1);
    assert.deepEqual(JSON.parse(JSON.stringify(items[1])),other);
  }
  assert.equal(JSON.parse(storage.get('wecare.cart.v1'))[0].formattedPrice,'₹0.99');
  assert.equal(cartModule.exports.readCart()[0].formattedPrice,'₹0.99');
  assert.deepEqual(JSON.parse(JSON.stringify(cartModule.exports.toLineItems())),[
    {catalogReference:{catalogItemId:product.id,options:{variantId:'WCTEST1R26'}},quantity:1},
    {catalogReference:{catalogItemId:other.productId,options:{variantId:'other'}},quantity:3},
  ]);
});
