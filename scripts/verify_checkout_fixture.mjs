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
import { createHash } from 'node:crypto';
import * as playwright from 'playwright';
import { AxeBuilder } from '@axe-core/playwright';
import { readFile } from 'node:fs/promises';
import { canonicalOrigin, qaOrigin } from './public_qa_origin.mjs';

const {origin, snapshot} = qaOrigin();
const engine = process.env.PUBLIC_QA_ENGINE || 'chromium';
assert.ok(['chromium','firefox','webkit'].includes(engine));
const out = process.env.PUBLIC_QA_OUTPUT || '/tmp/wecare-checkout-fixture';
await mkdir(out,{recursive:true});
// Refuse mixed deployment evidence, just as the public-page audit does.
// The fingerprint is an observed asset identity, not proof of a Git SHA.
async function deploymentFingerprint() {
  const res = await fetch(origin, {redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(15000)});
  if (!res.ok) throw new Error('Home fingerprint HTTP ' + res.status);
  const html = await res.text();
  const data = html.match(/<script[^>]*id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  const buildId = data ? JSON.parse(data[1]).buildId : null;
  const assets = [...new Set([...html.matchAll(/(?:src|href)="([^"\s]*\/_next\/static\/[^"\s]+)"/g)].map(m => m[1]))].sort();
  if (!buildId || !assets.length) throw new Error('No Next build ID/assets in Home');
  return {buildId, hash: createHash('sha256').update(JSON.stringify(assets)).digest('hex')};
}
const startFingerprint = await deploymentFingerprint();
let endFingerprint = null;
// Isolate independent synthetic scenarios in separate browser processes, not
// only separate contexts. Firefox repeatedly crashed after the appointment
// scenario on the shared process. A crash in an isolated scenario still fails
// the run; do not retry assertions, skip scenes, or forward live requests.
async function withIsolatedBrowser(run) {
  const browser = await playwright[engine].launch({headless:true});
  try { return await run(browser); }
  finally { await browser.close(); }
}
const failures=[], evidence=[];
const profile = {status:'PROFILE_READY', contactId:'qa-contact', name:'Synthetic Customer', firstName:'Synthetic', lastName:'Customer', profileComplete:true, addressComplete:false, address:null, phone:'', email:''};
const amount=30000, productId='24fa0f39-330b-5365-b7eb-9caf27ad37f1', variantId='CNT5Q2M8';
const quote = delta => ({status:'QUOTE_READY',quote:{currency:'INR',items:[{name:'Contribution',quantity:1,unitPricePaise:23541,totalPaise:23541}],charges:{merchandisePaise:23541,supplyGstPaise:4237,discountPaise:138,deliveryPaise:1500,convenienceFeePaise:729+delta,convenienceGstPaise:131,totalPaise:amount+delta}}});
const attempt='qa-attempt', order='WD-ORD-QA0001';
const sdk = 'window.Razorpay=class{constructor(o){this.o=o;window.__qaRazorpayOptions={amount:o.amount,currency:o.currency};}on(){}open(){window.__qaRazorpayOpen=(window.__qaRazorpayOpen||0)+1;window.__qaDismiss=()=>this.o.modal.ondismiss();window.__qaCapture=()=>this.o.handler({razorpay_payment_id:"qa-payment",razorpay_order_id:"qa-order",razorpay_signature:"qa-signature"});}};';
const staticPage = new Set(['/','/shop/','/checkout/','/checkout/status/','/checkout/success/','/auth','/auth/','/orders/','/elsewhere/arogya-yatra/']);
const allowedStatic = url => url.origin===origin.origin && (
  staticPage.has(url.pathname) || url.pathname.startsWith('/_next/static/') ||
  /^\/_next\/data\/[^/]+\/(?:index|checkout(?:\/status|\/success)?|auth|orders|shop|elsewhere\/arogya-yatra)\.json$/.test(url.pathname) ||
  /^\/(?:favicon\.ico|robots\.txt|manifest\.json|[^/]+\.(?:woff2?|png|svg|ico))$/.test(url.pathname)
);
const cors = {'access-control-allow-origin':origin.origin,'access-control-allow-methods':'GET, POST, OPTIONS','access-control-allow-headers':'authorization, content-type, x-customer-csrf','cache-control':'no-store'};
const json = (route,data,status=200) => route.fulfill({status,contentType:'application/json',headers:cors,body:JSON.stringify(data)});
const invoiceUrl = new URL('/qa-fixture/invoice?X-Amz-Signature=synthetic-only',origin).href;
const bookingEndpoint = JSON.parse(await readFile(new URL('../src/content/arogyaBookingConfig.json',import.meta.url),'utf8')).endpoint;
const apiPaths = new Set(['/api/ecommerce/customer-session','/api/ecommerce/prepare-checkout','/api/customer/profile','/api/ecommerce/verify-callback','/api/ecommerce/checkout/status','/api/ecommerce/my-orders','/api/ecommerce/my-invoice','/api/ecommerce/checkout']);
const isFixtureApi = url => (url.origin===origin.origin||url.origin===canonicalOrigin.origin)&&apiPaths.has(url.pathname);
async function scenario(width,mode) {
  return withIsolatedBrowser(browser=>runScenario(browser,width,mode));
}
async function runScenario(browser,width,mode) {
  const context=await browser.newContext({viewport:{width,height:width>=768?900:844},hasTouch:width<768,reducedMotion:'reduce',serviceWorkers:'block',acceptDownloads:true,ignoreHTTPSErrors:snapshot});
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
      if (method==='OPTIONS' && isFixtureApi(url)) return route.fulfill({status:204,headers:cors});
      if (url.origin!==origin.origin && !isFixtureApi(url)) return route.abort();
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
      if(url.pathname==='/api/ecommerce/my-invoice'&&method==='POST'){events.push('invoice:mock');return json(route,{available:true,url:invoiceUrl});}
      if(url.href===invoiceUrl&&method==='GET') {
        // Use real HTTPS response headers in the immutable snapshot. WebKit's
        // intercepted attachment behavior is not evidence of a real download.
        if(snapshot) return route.continue();
        return route.fulfill({status:200,headers:{'content-type':'text/plain','content-disposition':'attachment; filename="synthetic-checkout-fixture.txt"'},body:'SYNTHETIC CHECKOUT QA ONLY - NOT AN INVOICE'});
      }
      if(url.pathname==='/api/ecommerce/checkout'&&method==='POST'){native++;return json(route,{error:'TEST_BLOCKED'},400);}
      if(method==='GET'&&allowedStatic(url)&&req.resourceType()!=='fetch'&&req.resourceType()!=='xhr') return route.continue();
      // Next client navigation may read only its own generated static JSON.
      if(method==='GET'&&url.pathname.startsWith('/_next/data/')&&allowedStatic(url)) return route.continue();
      return route.abort();
    });
    const page=await context.newPage();page.setDefaultTimeout(20000);
    let phase='initial navigation';
    page.on('crash',()=>console.error(JSON.stringify({engine,width,mode,diagnostic:'page-crash',phase,events:[...events]})));
    async function captureSnapshot(label){
      phase='snapshot geometry: '+label;
      const geom=await page.evaluate(()=>{
        const width=document.documentElement.clientWidth,scroll=document.documentElement.scrollWidth;
        // Record geometry only, not page content or customer data. Include shared chrome.
        const overflowTargets=scroll>width+2?[...document.querySelectorAll('body *')].flatMap(el=>{
          const r=el.getBoundingClientRect(),style=getComputedStyle(el);
          if(!r.width||!r.height||style.visibility==='hidden'||style.display==='none'||(r.right<=width+2&&r.left>=-2)) return [];
          return [{tag:el.tagName.toLowerCase(),classes:typeof el.className==='string'?el.className.split(/\s+/).slice(0,4):[],left:Math.round(r.left),right:Math.round(r.right),position:style.position}];
        }).sort((a,b)=>Math.max(b.right-width,-b.left)-Math.max(a.right-width,-a.left)).slice(0,25):[];
        return {width,scroll,overflowTargets};
      });
      phase='accessibility scan: '+label;
      const axe=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']).analyze();
      const result={engine,width,mode,label,geometry:geom,violations:axe.violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}))};
      evidence.push(result);console.log(JSON.stringify(result));
      await page.screenshot({path:join(out,engine+'-'+width+'-'+mode+'-'+label+'.png')});
      if(geom.scroll>geom.width+2) failures.push(label+' horizontal overflow at '+width);
      if(result.violations.length) failures.push(label+' axe '+result.violations.map(v=>v.id).join(',')+' at '+width);
    }
    await page.goto(new URL('/checkout/?contribute=1',origin).href,{waitUntil:'domcontentloaded'});
    await page.locator('.cart-contribution-review').waitFor({state:'visible'});
    await captureSnapshot('review');
    assert.equal(prepare,0);
    await page.getByRole('button',{name:'Review contribution',exact:true}).click();
    await page.getByRole('link',{name:'Sign in to continue',exact:true}).waitFor({state:'visible'});
    assert.equal(await page.getByRole('button',{name:'Pay on WhatsApp',exact:true}).count(),0);
    assert.equal(await page.locator('.cart-pay-website').isDisabled(),true);
    await captureSnapshot('signed-out');
    await page.getByRole('link',{name:'Sign in to continue',exact:true}).click();
    await page.locator('#auth-code').waitFor({state:'visible'});
    await captureSnapshot('auth');
    await page.evaluate(()=>sessionStorage.setItem('qa-sign-in','yes'));
    await page.locator('#auth-code').fill('000000');
    phase='auth verification and checkout navigation';
    await page.getByRole('button',{name:'Verify',exact:true}).click();
    await page.waitForURL('**/checkout/');
    if(mode==='profile'){
      phase='wait for required checkout profile';
      await page.getByRole('region',{name:'Checkout details'}).waitFor({state:'visible'});
      phase='enter synthetic profile name';
      await page.getByLabel('Full name',{exact:true}).fill('Synthetic Customer');
      await captureSnapshot('name-only-profile');
      await page.getByRole('button',{name:'Save & continue',exact:true}).click();
      await page.waitForFunction(()=>!document.querySelector('.checkout-profile'));
      assert.ok(profileBootstrap&&profileSaved);
    }
    const pay=page.locator('.cart-pay-website');
    if(mode==='mismatch'){
      // Wait for the refusal produced by the mismatched authoritative quote,
      // not a transient disabled button before hydration has sent a quote.
      await page.getByText('Contributions cannot be taken right now. Nothing has been charged.',{exact:true}).waitFor({state:'visible'});
      assert.ok(events.includes('quote'),'A mismatched quote must actually have been requested');
      assert.ok(await pay.isDisabled(),'Wrong total must disable payment');
      assert.equal(prepare,0);
      await captureSnapshot('wrong-quote');
      return;
    }
    await page.waitForFunction(()=>{const b=document.querySelector('.cart-pay-website');return b&&!b.disabled;});
    await captureSnapshot('quoted');
    assert.match(await page.locator('.receipt-total').innerText(),/300(?:\.00)?/);
    assert.equal(await page.getByRole('button',{name:'Pay on WhatsApp',exact:true}).count(),0);
    await pay.click();
    await page.waitForFunction(()=>window.__qaRazorpayOpen===1);
    assert.deepEqual(await page.evaluate(()=>window.__qaRazorpayOptions),{amount:30000,currency:'INR'});
    assert.ok(await pay.isDisabled());
    assert.equal(prepare,1);
    await page.evaluate(()=>window.__qaDismiss());
    await page.waitForFunction(()=>{const b=document.querySelector('.cart-pay-website');return b&&!b.disabled;});
    await captureSnapshot('dismissed');
    await pay.click();
    await page.waitForFunction(()=>window.__qaRazorpayOpen===2);
    await page.evaluate(()=>window.__qaCapture());
    await page.waitForURL('**/orders/**',{timeout:30000});
    await page.getByText(order,{exact:true}).waitFor({state:'visible'});
    // Resting table colours are neutral even on a paid-order fixture.
    await page.mouse.move(0,0);
    const headings = await page.locator('.ord-th').evaluateAll(nodes=>nodes.map(el=>getComputedStyle(el).backgroundColor));
    assert.ok(headings.length>=4 && headings.every(bg=>bg==='rgb(255, 255, 255)'), 'Orders column headings must be white');
    const resting = await page.locator('.ord-copy,.ord-inv,.ord-account-action,.orm-more').evaluateAll(nodes=>nodes.map(el=>getComputedStyle(el).backgroundColor));
    assert.ok(resting.length>=3 && resting.every(bg=>bg==='rgba(0, 0, 0, 0)'), 'Orders icon controls must be neutral at rest');
    const tableFrame=await page.locator('.ord-list').evaluate(el=>{
      const s=getComputedStyle(el);
      return {radius:s.borderRadius,background:s.backgroundColor,borders:[s.borderTopColor,s.borderRightColor,s.borderBottomColor,s.borderLeftColor],widths:[s.borderTopWidth,s.borderRightWidth,s.borderBottomWidth,s.borderLeftWidth]};
    });
    assert.equal(tableFrame.radius,'14px');
    assert.equal(tableFrame.background,'rgb(255, 255, 255)');
    assert.ok(tableFrame.borders.every(color=>color==='rgb(209, 244, 112)'),'Orders only uses lime on the outer border');
    assert.ok(tableFrame.widths.every(width=>width==='1px'),'Orders outer border is a thin outline');
    assert.ok(await page.locator('.ord-tr').evaluate(el=>getComputedStyle(el).backgroundColor==='rgba(0, 0, 0, 0)'));
    await captureSnapshot('mock-paid-orders');
    const more = page.getByRole('button', {name: 'More actions for ' + order, exact: true});
    await more.click();
    const menu = page.getByRole('dialog', {name:'Order actions'});
    await menu.waitFor({state:'visible'});
    assert.equal(await menu.evaluate(el=>getComputedStyle(el).borderRadius),'8px','Orders menu panel radius');
    const searchActions = menu.getByRole('searchbox',{name:'Search order actions'});
    assert.equal(await searchActions.evaluate(el=>getComputedStyle(el).borderRadius),'6px','Orders menu search radius');
    await searchActions.fill('Submit Request');
    const submitRequest = menu.getByRole('link',{name:/Submit Request/});
    assert.ok(await submitRequest.isVisible());
    assert.equal(await submitRequest.evaluate(el=>getComputedStyle(el).borderRadius),'6px','Submit Request row radius');
    // Check actual hit areas in the portalled panel, including the 280px fold.
    // The microphone is conditional on browser speech-recognition support.
    const controls = await menu.evaluate(panel => {
      const input=panel.querySelector('input[type="search"]');
      const buttons=[...panel.querySelectorAll('button.public-search-clear,button.voice-search-mic')].filter(b=>!b.disabled&&b.getClientRects().length);
      const elements=[input,...buttons].filter(Boolean);
      const panelRect=panel.getBoundingClientRect();
      const rects=elements.map(el=>({el,r:el.getBoundingClientRect()}));
      return buttons.map(el=>{
        const {r}=rects.find(v=>v.el===el);
        const target=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
        const overlap=rects.some(other=>other.el!==el&&r.left<other.r.right-.5&&r.right>other.r.left+.5&&r.top<other.r.bottom-.5&&r.bottom>other.r.top+.5);
        return {label:el.getAttribute('aria-label'),width:r.width,height:r.height,inside:r.left>=panelRect.left-.5&&r.right<=panelRect.right+.5&&r.top>=panelRect.top-.5&&r.bottom<=panelRect.bottom+.5,hit:el.contains(target),overlap};
      });
    });
    for(const control of controls){
      assert.ok(control.width>=44&&control.height>=44&&control.inside&&control.hit&&!control.overlap,JSON.stringify(control));
    }
    await captureSnapshot('mock-orders-request-menu');
    await searchActions.press('Escape');
    await searchActions.press('Escape');
    assert.equal(await menu.count(),0);
    assert.ok(await more.evaluate(el=>document.activeElement===el));
    assert.equal(verify,1);
    assert.equal(native,0);
    assert.equal(await page.evaluate(()=>localStorage.getItem('wecare.cart.v1')),null);
    const invoice=page.getByRole('button',{name:'Download invoice',exact:true});
    assert.equal(await invoice.count(),1,'Paid row must expose invoice action');
    assert.ok(await invoice.isEnabled(),'Paid row must enable invoice action');
    // Exercise the signed-link client contract with an intercepted attachment.
    // The file is a fixture marker, not a generated invoice or real bearer URL.
    const downloaded=page.waitForEvent('download',{timeout:15000});
    await invoice.click();
    const attachment=await downloaded;
    assert.equal(attachment.suggestedFilename(),'synthetic-checkout-fixture.txt');
    assert.ok(events.includes('invoice:mock'));
    console.log(JSON.stringify({engine,width,mode,events,prepare,verify,native,syntheticOnly:true,invoiceVerified:true}));
  } finally {await context.close();}
}
// Separate synthetic appointment request scenario; no hospital, patient or
// provider data is sent anywhere. Since #2531 the form is public and sign-in is
// checked only at submission, so a signed-out submit must keep the form filled,
// make no booking call and offer WhatsApp sign-in in a new tab.
async function verifyAppointmentGate(){
  return withIsolatedBrowser(runAppointmentGate);
}
async function runAppointmentGate(browser){
  const context=await browser.newContext({viewport:{width:390,height:844},hasTouch:true,reducedMotion:'reduce',serviceWorkers:'block',ignoreHTTPSErrors:snapshot});
  let bookingCalls=0;
  try{
    if(typeof context.routeWebSocket==='function') await context.routeWebSocket('**/*',socket=>socket.close());
    await context.route('**/*',route=>{
      const req=route.request(),url=new URL(req.url()),method=req.method();
      if(method==='OPTIONS'&&(url.href===bookingEndpoint||isFixtureApi(url))) return route.fulfill({status:204,headers:cors});
      if(url.href===bookingEndpoint){bookingCalls++;return json(route,{error:'FIXTURE_REFUSED'},400);}
      if(method==='GET'&&allowedStatic(url)) return route.continue();
      return route.abort();
    });
    const page=await context.newPage();
    const path='/elsewhere/arogya-yatra/';
    await page.goto(new URL(path,origin).href,{waitUntil:'domcontentloaded'});
    const patient=page.locator('input[name="patientName"]');
    await patient.waitFor({state:'visible',timeout:20000});
    assert.equal(new URL(page.url()).pathname,path,'signed-out visitors stay on the public form');
    assert.equal(await page.locator('a[href*="apollohospitals.com/book-doctor-appointment"]').count(),0);
    await page.locator('input[name="city"]').fill('Pune');
    await page.locator('input[name="preferredDate"]').fill(new Date(Date.now()+7*864e5).toISOString().slice(0,10));
    await patient.fill('QA Synthetic');
    await page.locator('input[name="mobile"]').fill('919999999999');
    await page.locator('#ay-consent').check();
    await page.getByRole('button',{name:'Submit request',exact:true}).click();
    await page.getByRole('heading',{name:'Sign in to submit your request',exact:true}).waitFor({state:'visible',timeout:20000});
    const signIn=page.getByRole('link',{name:'Sign in with WhatsApp (new tab)',exact:true});
    assert.equal(await signIn.getAttribute('href'),'/auth?return=%2Felsewhere%2Farogya-yatra%2F');
    assert.equal(await signIn.getAttribute('target'),'_blank');
    assert.equal(await patient.inputValue(),'QA Synthetic','the form stays filled while signing in');
    assert.equal(new URL(page.url()).pathname,path);
    assert.equal(bookingCalls,0);
    await page.screenshot({path:join(out,engine+'-arogya-signin-at-submit.png')});
    console.log(JSON.stringify({engine,appointmentGate:true,signInAtSubmit:true,syntheticOnly:true}));
  } finally {await context.close();}
}
try {
  if(snapshot){
    try{await verifyAppointmentGate();}catch(e){failures.push(engine+' appointment fixture: '+String(e.message).slice(0,500));}
  }
  for(const width of [390,768,1440,280,160]) {
    for(const mode of width===390?['profile','mismatch','ready']:['ready']) {
      try {await scenario(width,mode);} catch(e){failures.push(engine+' '+width+' '+mode+': '+String(e.message).slice(0,500));}
    }
  }
} finally {
  try {
    endFingerprint = await deploymentFingerprint();
    if (JSON.stringify(startFingerprint) !== JSON.stringify(endFingerprint)) failures.push('Deployment changed during checkout fixture; do not accept mixed revisions');
  } catch (error) { failures.push('Final deployment fingerprint unavailable: ' + error.message); }
  await writeFile(join(out,'checkout-fixture.json'),JSON.stringify({engine,revision:process.env.PUBLIC_QA_REVISION,mode:snapshot?'immutable-export':'live-observation',startFingerprint,endFingerprint,syntheticOnly:true,failures,evidence},null,2));
}
console.log('Checkout fixture summary: '+JSON.stringify({engine,failures,scenes:evidence.length,syntheticOnly:true}));
assert.equal(failures.length,0,failures.join('\n'));
