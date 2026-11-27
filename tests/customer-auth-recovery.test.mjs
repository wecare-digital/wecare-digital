import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {transformSync, buildSync} from 'esbuild';
import {ORDER_REQUESTS, orderRequestFromHash, orderRequestMenuHref, preserveOrderRequest, takeOrderRequest} from '../src/lib/orderRequestSelection.ts';

const compiled=transformSync(readFileSync(new URL('../src/lib/customerAuth.ts',import.meta.url),'utf8'),{loader:'ts',format:'cjs'}).code;
const feedbackModule={exports:{}};
vm.runInNewContext(buildSync({entryPoints:['src/lib/authStepFeedback.ts'],bundle:true,platform:'node',format:'cjs',write:false}).outputFiles[0].text,{module:feedbackModule,exports:feedbackModule.exports});
const {authStepFeedback}=feedbackModule.exports;
const fresh={csrfToken:'new-csrf',expiresAt:Date.now()+86400000,persistent:true};
function storage(initial={},blocked=false){
  const values=new Map(Object.entries(initial));
  return {getItem(k){if(blocked)throw Error('blocked');return values.get(k)??null;},setItem(k,v){if(blocked)throw Error('blocked');values.set(k,v);},removeItem(k){if(blocked)throw Error('blocked');values.delete(k);}};
}
function runtime({prior='null',cached=false,localBlocked=false,sessionBlocked=false,status=200}={}){
  let cookie='wc_customer_session_hint='+encodeURIComponent(JSON.stringify(fresh));
  const calls=[];
  const listeners={};
  const authModule={exports:{}};
  const context=vm.createContext({module:authModule,exports:authModule.exports,process:{env:{}},Date,console,
    document:{get cookie(){return cookie;},set cookie(v){cookie=v.includes('Max-Age=0')?'':v;}},
    window:{localStorage:storage({'wecare.customer.sessionHint':prior},localBlocked),sessionStorage:storage(cached?{'wecare.customer.accessToken':'old-access','wecare.customer.expiresAt':String(Date.now()+3600000)}:{},sessionBlocked),addEventListener(name,fn){listeners[name]=fn;}},
    fetch:async(url,options)=>{calls.push({url,options});return {status,ok:status===200,json:async()=>({accessToken:'new-access',expiresAt:Date.now()+3600000})};}});
  vm.runInContext(compiled,context);
  return {auth:authModule.exports,calls,context,listeners};
}

for(const [name,prior] of [['expired',JSON.stringify({...fresh,csrfToken:'old',expiresAt:1})],['unexpired',JSON.stringify({...fresh,csrfToken:'old'})],['malformed','{invalid']]){
  test(`fresh login supersedes ${name} saved hint and cached access`,async()=>{
    const r=runtime({prior,cached:true});
    assert.equal(r.auth.getSession(),null);
    const restored=await r.auth.restoreSession();
    assert.equal(restored.accessToken,'new-access');
    assert.equal(r.calls.length,1);
    assert.equal(r.calls[0].options.headers['X-Customer-CSRF'],'new-csrf');
  });
}
test('new login can refresh and retain its short token with browser storage denied',async()=>{
  const r=runtime({localBlocked:true,sessionBlocked:true});
  assert.equal((await r.auth.restoreSession()).accessToken,'new-access');
  assert.equal((await r.auth.restoreSession()).accessToken,'new-access');
  assert.equal(r.calls.length,1);
});
test('another tab changing account invalidates the cached access token',async()=>{
  const r=runtime();
  await r.auth.restoreSession();
  r.listeners.storage({key:'wecare.customer.sessionHint',newValue:'changed'});
  assert.equal(r.auth.getSession(),null);
});
test('definitive refresh refusal clears the handoff instead of retrying it forever',async()=>{
  const r=runtime({localBlocked:true,status:401});
  assert.equal(await r.auth.restoreSession(),null);
  assert.equal(await r.auth.restoreSession(),null);
  assert.equal(r.calls.length,1);
});
test('known resend/onboarding outcomes are success, arbitrary backend copy is never displayed',()=>{
  for(const outcome of ['code_sent','retry_code'])assert.equal(authStepFeedback('',outcome).tone,'info');
  for(const message of ['Wrong code. Try again.','Could not complete sign-in. Try again.','arbitrary private provider details']){
    const result=authStepFeedback(message);
    assert.equal(result.tone,'error');
    assert.equal(result.message,"Couldn't complete. Try again.");
  }
  assert.equal(authStepFeedback(''),null);
});
test('all six request links survive new-tab Orders to Auth and back without storage',()=>{
  const previous=globalThis.window;
  try{
    for(const request of ORDER_REQUESTS){
      const href=orderRequestMenuHref(request.label,'/orders/');
      const hash=new URL(href,'https://wecare.digital').hash;
      assert.equal(orderRequestFromHash(hash),request.id);
      const auth=preserveOrderRequest('/auth?return=/orders/',hash);
      assert.equal(preserveOrderRequest('/orders/',new URL(auth,'https://wecare.digital').hash),href);
      globalThis.window={location:{hash},sessionStorage:{getItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}}};
      assert.equal(takeOrderRequest(),request.id);
    }
  }finally{if(previous===undefined)delete globalThis.window;else globalThis.window=previous;}
});
test('request fragments cannot introduce another destination, selector, or send intent',()=>{
  for(const hash of ['#request=arbitrary','#request=vault&request=drop-docs','#request=vault&orderId=private','#service=subscribe'])assert.equal(orderRequestFromHash(hash),null);
  const hash='#request=drop-docs';
  for(const destination of ['https://example.com/','//example.com/orders/','/checkout/','/vault/','/auth?return=/vault/'])assert.equal(preserveOrderRequest(destination,hash),destination);
  assert.equal(orderRequestMenuHref('Subscribe','/orders/'),'/orders/');
});

for(const status of [200,401]) test(`older refresh (${status}) cannot overwrite or clear a newer login`,async()=>{
  const r=runtime();
  const normalFetch=r.context.fetch;
  let finish;
  r.context.fetch=()=>new Promise(resolve=>{finish=resolve;});
  const older=r.auth.restoreSession();
  r.context.document.cookie='wc_customer_session_hint='+encodeURIComponent(JSON.stringify({...fresh,csrfToken:'newer-csrf'}));
  r.context.fetch=normalFetch;
  assert.equal((await r.auth.restoreSession()).accessToken,'new-access');
  finish({status,ok:status===200,json:async()=>({accessToken:'obsolete-access',expiresAt:Date.now()+3600000})});
  assert.equal(await older,null);
  assert.equal(r.auth.getSession().accessToken,'new-access');
});
