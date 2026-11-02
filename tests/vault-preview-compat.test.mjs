import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {buildSync} from 'esbuild';
const built=buildSync({entryPoints:['src/lib/vaultPreview.ts'],bundle:true,platform:'node',format:'cjs',write:false});
const m={exports:{}};vm.runInNewContext(built.outputFiles[0].text,{module:m,exports:m.exports});
const {nativeVaultPdfRequired}=m.exports;

test('supported older iPhone/iPad WebViews use their native PDF engine',()=>{
 for(const ua of ['Mozilla/5.0 (iPhone; CPU iPhone OS 15_8 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148','Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 CriOS/120.0 Mobile/15E148','Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15'])assert.equal(nativeVaultPdfRequired(ua,true),true,ua);
});
test('modern browsers retain the private local canvas renderer',()=>{
 for(const ua of ['Mozilla/5.0 AppleWebKit/537.36 Chrome/145.0 Safari/537.36','Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'])assert.equal(nativeVaultPdfRequired(ua,true),false,ua);
 assert.equal(nativeVaultPdfRequired('Unknown embedded browser',false),true);
});

test('native preview rejects an expired signed link or an HTML error before opening an iframe',async()=>{
 const builtNative=buildSync({entryPoints:['src/lib/vaultPreview.ts'],bundle:true,platform:'node',format:'cjs',write:false});
 const module={exports:{}};let response=new Response('Expired',{status:403});
 vm.runInNewContext(builtNative.outputFiles[0].text,{module,exports:module.exports,Blob,fetch:async()=>response});
 const signal=new AbortController().signal;
 await assert.rejects(()=>module.exports.loadNativeVaultPdf('https://private.example/file',signal));
 response=new Response('<html>%PDF- is an error message</html>',{headers:{'content-type':'text/html'}});
 await assert.rejects(()=>module.exports.loadNativeVaultPdf('https://private.example/file',signal));
 response=new Response('%PDF-1.4\nverified private PDF bytes',{headers:{'content-type':'application/pdf'}});
 const file=await module.exports.loadNativeVaultPdf('https://private.example/file',signal);
 assert.equal(file.type,'application/pdf');assert.ok((await file.text()).startsWith('%PDF-'));
});
