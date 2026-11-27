#!/usr/bin/env node
/**
 * Browser checkout acceptance with synthetic responses only. Never forward a
 * non-static request, even on error. No production session, OTP, charge or invoice.
 * Run against the approved production HTML; all transactional endpoints are
 * intercepted before navigation and every other non-static request is aborted.
 */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import * as playwright from 'playwright';
import { AxeBuilder } from '@axe-core/playwright';

const origin = new URL(process.env.PUBLIC_QA_BASE || 'https://wecare.digital');
assert.equal(origin.href, 'https://wecare.digital/', 'Only the approved public site is allowed');
const engine = process.env.PUBLIC_QA_ENGINE || 'chromium';
assert.ok(['chromium','firefox','webkit'].includes(engine));
const out = process.env.PUBLIC_QA_OUTPUT || '/tmp/wecare-checkout-fixture';
await mkdir(out,{recursive:true});
const browser = await playwright[engine].launch({headless:true});
const failures=[], evidence=[];
const profile = {status:'PROFILE_READY', contactId:'qa-contact', name:'Synthetic Customer', firstName:'Synthetic', lastName:'Customer', profileComplete:true, addressComplete:false, address:null, phone:'', email:''};
const amount=30000, productId='24fa0f39-330b-5365-b7eb-9caf27ad37f1', variantId='CNT5Q2M8';
const quote = delta => ({status:'QUOTE_READY',quote:{currency:'INR',items:[{name:'Contribution',quantity:1,unitPricePaise:23541,totalPaise:23541}],charges:{merchandisePaise:23541,supplyGstPaise:4237,discountPaise:138,deliveryPaise:1500,convenienceFeePaise:729+delta,convenienceGstPaise:131,totalPaise:amount+delta}}});
const attempt='qa-attempt', order='WD-ORD-QA0001';
const sdk = 'window.Razorpay=class{constructor(o){this.o=o;window.__qaRazorpayOptions={amount:o.amount,currency:o.currency};}on(){}open(){window.__qaRazorpayOpen=(window.__qaRazorpayOpen||0)+1;window.__qaDismiss=()=>this.o.modal.ondismiss();window.__qaCapture=()=>this.o.handler({razorpay_payment_id:"qa-payment",razorpay_order_id:"qa-order",razorpay_signature:"qa-signature"});}};';
const staticPage = new Set(['/','/shop/','/checkout/','/checkout/status/','/checkout/success/','/auth','/auth/','/orders/']);
const allowedStatic = url => url.origin===origin.origin && (
  staticPage.has(url.pathname) || url.pathname.startsWith('/_next/static/') ||
  /^\/_next\/data\/[^/]+\/(?:index|checkout(?:\/status|\/success)?|auth|orders|shop)\.json$/.test(url.pathname) ||
  /^\/(?:favicon\.ico|robots\.txt|manifest\.json|[^/]+\.(?:woff2?|png|svg|ico))$/.test(url.pathname)
);
const json = (route,data,status=200) => route.fulfill({status,contentType:'application/json',headers:{'access-control-allow-origin':origin.origin,'cache-control':'no-store'},body:JSON.stringify(data)});
async function scenario(width,mode) {
  const context=await browser.newContext({viewport:{width,height:width>=768?900:844},hasTouch:width<768,reducedMotion:'reduce',serviceWorkers:'block',acceptDownloads:true});
  const events=[];let prepare=0,verify=0,native=0,profileSaved=mode!=='profile',profileBootstrap=false,paid=false;
  try {
    if (typeof context.routeWebSocket === 'function') await context.routeWebSocket('**/*',socket=>socket.close());
    await context.addInitScript(() => {
      // Auth fixture's session hint is synthetic; access token exists only
      // in the mock response and is never passed through to a live endpoint.
      if (sessionStorage.getItem('qa-sign-in')==='yes') localStorage.setItem('wecare.customer.sessionHint',JSON.stringify({csrfToken:'qa-csrf',expiresAt:Date.now()+3600000,persistent:false}));
    });
    await context.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url()),method=req.method();
      if (url.href==='https://checkout.razorpay.com/v1/checkout.js') return route.fulfill({status:200,contentType:'application/javascript',body:sdk});
      if(url.origin!==origin.origin) return route.abort();
      if (url.pathname==='/auth/state' && method==='GET') return json(route,{phase:'code',csrf:'qa-csrf',message:'',website:true,returnPath:'/checkout/',clientName:'WECARE.DIGITAL',destination:'synthetic fixture'});
      if (url.pathname==='/auth/step' && method==='POST') {
        events.push('auth:mock-verify');
        return json(route,{redirect:'/checkout/'});
      }
      if (url.pathname==='/api/ecommerce/customer-session' && method==='POST') return json(route,{accessToken:'qa-only-not-a-real-token',expiresAt:Date.now()+3600000});
      if (url.pathname==='/api/ecommerce/prepare-checkout' && method==='POST') {
        const body=req.postDataJSON();events.push(body.action);
        if(body.action==='profile') return json(route,profileSaved?profile:{status:'PROFILE_REQUIRED'});
        const lines=body.lineItems;
        assert.equal(lines.length,1);
        assert.equal(lines[0].catalogReference.catalogItemId,productId);
        assert.equal(lines[0].catalogReference.options.variantId,variantId);
        assert.equal(lines[0].quantity,1);
        if(body.action==='quote') return profileSaved?json(route,quote(mode==='mismatch'?1:0)):json(route,{error:'PROFILE_REQUIRED'},409);
        if(body.action==='prepare'){
          prepare++;
          return json(route,{status:'CHECKOUT_OPTIONS_READY',paymentAttemptId:attempt,options:{keyId:'rzp_test_fixture',orderId:'qa-order',amountPaise:amount,currency:'INR'}});
        }
        return json(route,{error:'UNEXPECTED_FIXTURE_ACTION'},400);
      }
      if (url.pathname==='/api/customer/profile' && method==='POST'){
        const body=req.postDataJSON()||{};
        if(!profileSaved&&body.fullName&&!profileBootstrap) return json(route,{error:'INVALID_ADDRESS',code:'ADDRESS_REQUIRED'},400);
        if(!Object.keys(body).length&&!profileSaved){profileBootstrap=true;return json(route,{...profile,name:'',profileComplete:false});}
        if(body.fullName){assert.ok(!('address' in body),'Contribution does not require delivery');profileSaved=true;events.push('profile:saved');}
        return json(route,profile);
      }
      if (url.pathname==='/api/ecommerce/verify-callback'&&method==='POST'){
        verify++;paid=true;events.push('verify:mock-paid');
        return json(route,{status:'VERIFIED_PAID',paymentAttemptId:attempt});
      }
      if (url.pathname==='/api/ecommerce/checkout/status'&&method==='POST'){
        return json(route,{attempt:{status:paid?'PAYMENT_PAID':'PAYMENT_PENDING',orderNumber:paid?order:null,amountPaise:amount,currency:'INR'}});
      }
      if(url.pathname==='/api/ecommerce/my-orders'&&method==='POST') return json(route,{orders:paid?[{orderNumber:order,referenceId:'qa-order-ref',createdAt:1700000000,amountPaise:amount,currency:'INR',currencyUnexpected:false,status:'captured'}]:[],cursor:''});
      if(url.pathname==='/api/ecommerce/my-invoice'&&method==='POST'){events.push('invoice:mock');return json(route,{available:false});}
      if(url.pathname==='/api/ecommerce/checkout'&&method==='POST'){native++;return json(route,{error:'TEST_BLOCKED'},400);}
      if(method==='GET'&&allowedStatic(url)&&req.resourceType()!=='fetch'&&req.resourceType()!=='xhr') return route.continue();
      // Next client navigation may read only its own generated static JSON.
      if(method==='GET'&&url.pathname.startsWith('/_next/data/')&&allowedStatic(url)) return route.continue();
      return route.abort();
    });
    const page=await context.newPage();page.setDefaultTimeout(20000);
    async function snapshot(label){
      const geom=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));
      const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']).analyze();
      const result={engine,width,mode,label,geometry:geom,violations:axe.violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))};
      evidence.push(result);console.log(JSON.stringify(result));
      await page.screenshot({path:join(out,engine+'-'+width+'-'+mode+'-'+label+'.png')});
      if(geom.scroll>geom.width+2) failures.push(label+' horizontal overflow at '+width);
      if(result.violations.length) failures.push(label+' axe '+result.violations.map(v=>v.id).join(',')+' at '+width);
    }
    await page.goto(new URL('/checkout/?contribute=1',origin).href,{waitUntil:'domcontentloaded'});
    await page.locator('.cart-contribution-review').waitFor({state:'visible'});
    await snapshot('review');
    assert.equal(prepare,0);
    await page.getByRole('button',{name:'Review contribution',exact:true}).click();
    await page.getByRole('link',{name:'Sign in to continue',exact:true}).waitFor({state:'visible'});
    assert.equal(await page.getByRole('button',{name:'Pay on WhatsApp',exact:true}).count(),0);
    assert.equal(await page.locator('.cart-pay-website').isDisabled(),true);
    await snapshot('signed-out');
    await page.getByRole('link',{name:'Sign in to continue',exact:true}).click();
    await page.locator('#auth-code').waitFor({state:'visible'});
    await snapshot('auth');
    await page.evaluate(()=>sessionStorage.setItem('qa-sign-in','yes'));
    await page.locator('#auth-code').fill('000000');
    await page.getByRole('button',{name:'Verify',exact:true}).click();
    await page.waitForURL('**/checkout/');
    if(mode==='profile'){
      await page.getByLabel('Full name',{exact:true}).fill('Synthetic Customer');
      await snapshot('name-only-profile');
      await page.getByRole('button',{name:'Save & continue',exact:true}).click();
      await page.waitForFunction(()=>!document.querySelector('.checkout-profile'));
      assert.ok(profileBootstrap&&profileSaved);
    }
    const pay=page.locator('.cart-pay-website');
    if(mode==='mismatch'){
      await page.getByText(/contribution.*(?:available|payable|price)|price.*contribution/i).first().waitFor({state:'visible'}).catch(()=>{});
      await page.waitForFunction(()=>!document.querySelector('.cart-quiet-refresh')?.disabled);
      assert.ok(await pay.isDisabled(),'Wrong total must disable payment');
      assert.equal(prepare,0);
      await snapshot('wrong-quote');
      return;
    }
    await page.waitForFunction(()=>{const b=document.querySelector('.cart-pay-website');return b&&!b.disabled;});
    await snapshot('quoted');
    assert.match(await page.locator('.receipt-total').innerText(),/300(?:\.00)?/);
    assert.equal(await page.getByRole('button',{name:'Pay on WhatsApp',exact:true}).count(),0);
    await pay.click();
    await page.waitForFunction(()=>window.__qaRazorpayOpen===1);
    assert.deepEqual(await page.evaluate(()=>window.__qaRazorpayOptions),{amount:30000,currency:'INR'});
    assert.ok(await pay.isDisabled());
    assert.equal(prepare,1);
    await page.evaluate(()=>window.__qaDismiss());
    await page.waitForFunction(()=>{const b=document.querySelector('.cart-pay-website');return b&&!b.disabled;});
    await snapshot('dismissed');
    await pay.click();
    await page.waitForFunction(()=>window.__qaRazorpayOpen===2);
    await page.evaluate(()=>window.__qaCapture());
    await page.waitForURL('**/orders/**',{timeout:30000});
    await page.getByText(order,{exact:true}).waitFor({state:'visible'});
    await snapshot('mock-paid-orders');
    assert.equal(verify,1);
    assert.equal(native,0);
    assert.equal(await page.evaluate(()=>localStorage.getItem('wecare.cart.v1')),null);
    const invoice=page.getByRole('button',{name:'Download invoice',exact:true});
    if(await invoice.count()===1&&await invoice.isEnabled()){
      await invoice.click();
      await page.waitForTimeout(500);
      assert.ok(events.includes('invoice:mock'));
    }
    console.log(JSON.stringify({engine,width,mode,events,prepare,verify,native,syntheticOnly:true}));
  } finally {await context.close();}
}
try {
  for(const width of [390,768,1440,280,160]) {
    for(const mode of width===390?['profile','mismatch','ready']:['ready']) {
      try {await scenario(width,mode);} catch(e){failures.push(engine+' '+width+' '+mode+': '+String(e.message).slice(0,500));}
    }
  }
} finally {
  await browser.close();
  await writeFile(join(out,'checkout-fixture.json'),JSON.stringify({engine,revision:process.env.PUBLIC_QA_REVISION,syntheticOnly:true,failures,evidence},null,2));
}
console.log('Checkout fixture summary: '+JSON.stringify({engine,failures,scenes:evidence.length,syntheticOnly:true}));
assert.equal(failures.length,0,failures.join('\n'));
