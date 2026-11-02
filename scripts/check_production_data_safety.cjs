/* Offline regression checks: execute real search logic with a controlled provider. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const esbuild = require('esbuild');
const source = fs.readFileSync('src/components/ElsewhereTravelAssistant.tsx', 'utf8');
const output = esbuild.transformSync(source + '\nexport { searchTravel, normaliseResponse, safeHttpsUrl, quoteIsFresh };', {loader:'tsx',format:'cjs',target:'es2022'}).code;
const compiledModule = {exports:{}};
const env = {};
const sandbox = {module:compiledModule,exports:compiledModule.exports,process:{env},URL,Date,DOMException,
  require: () => ({}), fetch: async () => {throw Error('Unexpected network request');}};
vm.runInNewContext(output, sandbox);
const {searchTravel, normaliseResponse, safeHttpsUrl, quoteIsFresh} = compiledModule.exports;
(async () => {
  await assert.rejects(searchTravel('flights','Delhi',[],{}), /unavailable/);
  env.NEXT_PUBLIC_ELSEWHERE_SEARCH_ENDPOINT = 'https://provider.invalid/search';
  sandbox.fetch = async () => ({ok:false,status:503});
  await assert.rejects(searchTravel('flights','Delhi',[],{}), /503/);
  sandbox.fetch = async () => ({ok:true,json:async () => ({results:[]})});
  await assert.rejects(searchTravel('flights','Delhi',[],{}), /No usable provider results/);
  sandbox.fetch = async () => ({ok:true,json:async () => ({results:[{id:'offer-1',title:'Provider offer',price:'₹100'}]})});
  const live = await searchTravel('flights','Delhi',[],{});
  assert.equal(live.source,'api');
  assert.equal(live.results[0].id,'offer-1');
  assert.equal(live.results[0].checkoutReady,false, 'Missing provider readiness must not authorize checkout');
  assert.equal(safeHttpsUrl('javascript:alert(1)'), '');
  assert.equal(quoteIsFresh('2000-01-01'),false);
  assert.throws(() => normaliseResponse({results:[]}), /No usable/);
  assert.ok(!source.includes('eta-demo-checkout'));
  const analytics = fs.readFileSync('src/components/workspace/whatsapp/templates.tsx','utf8');
  assert.ok(!analytics.includes('Math.random'));
  const rcs = fs.readFileSync('src/components/workspace/channels/RcsSend.tsx','utf8');
  assert.ok(!rcs.includes('FALLBACK_TEMPLATE_OPTIONS'));
  assert.match(rcs, /templateOptions.some/);
  console.log('Production data safety passed: unavailable, failed, empty and real provider searches; safe checkout defaults; no fabricated analytics or template fallback.');
})().catch(err => {console.error(err);process.exitCode=1;});
