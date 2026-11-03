import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {build} from 'esbuild';

test('Vault forwards the exact reviewed total without an optional description, once',async()=>{
 const built=await build({stdin:{contents:"export {requestSecureFilePayment,sendSecureFileAccess} from './src/api/domains/platform';export {startVaultUpload,VaultUploadRefused} from './src/api/vault';",resolveDir:process.cwd()},bundle:true,platform:'node',format:'cjs',write:false,plugins:[{name:'isolate',setup(b){b.onResolve({filter:/lib\/amplifyConfig$/},()=>({path:'empty',namespace:'stub'}));b.onResolve({filter:/^(?:\.\.\/core|\.\/client)$/},()=>({path:'core',namespace:'stub'}));b.onLoad({filter:/.*/,namespace:'stub'},({path})=>({contents:path==='core'?`export const authFetch=(...args)=>globalThis.capture(...args);export const apiCall=()=>{};export const apiCallResult=()=>{};export const WA_BIZ_BASE='https://example.test';`:'',loader:'js'}));}}]});
 const calls=[],m={exports:{}};let fail=false,status=200;
 vm.runInNewContext(built.outputFiles[0].text,{module:m,exports:m.exports,process:{env:{}},capture:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});if(fail)throw Error('uncertain');return{ok:status===200,status,json:async()=>({outcome:'ACCEPTED',error:'REGISTRATION_REFUSED'})};},URL,URLSearchParams});
 await m.exports.requestSecureFilePayment('exact-file',undefined,8497);assert.equal(calls.length,1);assert.deepEqual(calls[0].body,{expectedTotalPaise:8497});assert.match(calls[0].url,/exact-file\/request-payment$/);
 await m.exports.sendSecureFileAccess('exact-file','unique-request','prior-request');assert.deepEqual(calls[1].body,{requestId:'unique-request',previousRequestId:'prior-request'});
 fail=true;const result=await m.exports.requestSecureFilePayment('exact-file',undefined,8497);assert.equal(result.outcome,'NO_RESPONSE');assert.equal(calls.length,3,'a timeout must never auto-retry a send');
 fail=false;status=403;await assert.rejects(()=>m.exports.startVaultUpload({name:'Saved',mobile:'919000000001',originalFilename:'file.pdf',contentType:'application/pdf',sizeBytes:100}),e=>e instanceof m.exports.VaultUploadRefused);
 status=503;await assert.rejects(()=>m.exports.startVaultUpload({name:'Saved',mobile:'919000000001',originalFilename:'file.pdf',contentType:'application/pdf',sizeBytes:100}),e=>!(e instanceof m.exports.VaultUploadRefused));assert.equal(calls.length,5,'upload registration is also one-shot');
});
