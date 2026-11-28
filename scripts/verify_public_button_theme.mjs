#!/usr/bin/env node
// Read-only computed-style regression against approved preview or exact export.
// All requests that could write, send messages, translate or pay are blocked.
import assert from 'node:assert/strict';
assert.ok(process.env.PUBLIC_QA_BASE,'Set PUBLIC_QA_BASE to the approved preview or export');
const origin=new URL(process.env.PUBLIC_QA_BASE);
const snapshot=process.env.PUBLIC_QA_SNAPSHOT==='1';
assert.ok(['http:','https:'].includes(origin.protocol));
const {chromium}=await import('playwright');
const browser=await chromium.launch();
const marker='[data-public-auth-button-theme="active"]';
const readStyle=(page,selector)=>page.locator(selector).first().evaluate(el=>{
  const s=getComputedStyle(el),r=el.getBoundingClientRect();
  const token=name=>{
    const p=document.createElement('span');
    p.style.color='var('+name+')';
    el.append(p);const value=getComputedStyle(p).color;p.remove();return value;
  };
  return {background:s.backgroundColor,color:s.color,radius:s.borderTopLeftRadius,border:s.borderTopWidth,
    decoration:s.textDecorationLine,height:r.height,width:r.width,tint:token('--public-lime-tint'),green:token('--public-brand-green'),lime:token('--public-brand-lime')};
});
const componentSelectors=['.hdr-cart','.nav-trigger','.wc-wa','.wc-chip','.ps-contribute','.ps-subscribe','.ps-share-trigger'];
const preserved=({background,color,radius,border,decoration})=>({background,color,radius,border,decoration});
try {
  for(const width of [1440,768,390,280,160]){
    const page=await browser.newPage({viewport:{width,height:900},reducedMotion:'reduce',ignoreHTTPSErrors:snapshot,serviceWorkers:'block'});
    try{
      await page.route('**/*',route=>{
        const req=route.request(),url=new URL(req.url());
        if(!['GET','HEAD'].includes(req.method()))return route.abort();
        if(url.pathname.endsWith('/site-language/languages'))return route.fulfill({json:{languages:[{code:'en',name:'English'},{code:'hi',name:'Hindi'}]},headers:{'access-control-allow-origin':'*'}});
        if(url.origin!==origin.origin)return route.abort();
        if(url.pathname==='/auth/state')return route.fulfill({json:{phase:'phone',csrf:'qa-theme-only',message:'',website:true,returnPath:'/',clientName:'WECARE.DIGITAL'}});
        return route.continue();
      });
      const go=async route=>{
        await page.goto(new URL(route,origin).href,{waitUntil:'domcontentloaded'});
        await page.locator('.wc-chip').waitFor({state:'visible',timeout:15000});
        await page.mouse.move(0,0);
      };
      await go('/');
      assert.equal(await page.locator(marker).count(),0);
      const home=await readStyle(page,'.home-close-cta');
      assert.equal(home.background,home.lime);
      assert.equal(home.decoration,'none');
      const original={};
      for(const selector of componentSelectors) original[selector]=await readStyle(page,selector);
      assert.equal(original['.hdr-cart'].background,'rgba(0, 0, 0, 0)');
      assert.equal(original['.wc-chip'].background,'rgba(0, 0, 0, 0)');
      assert.equal(original['.wc-wa'].radius,'50%');
      assert.equal(original['.ps-contribute'].radius,'50%');
      assert.equal(original['.ps-share-trigger'].background,'rgb(255, 255, 255)');
      for(const [route,selector] of [['/auth/','.auth-action'],['/shop/','.shop-card-action'],['/anew/','.checkout-action'],['/contact/','.cl-cta'],['/blog/',null],['/relay-os/',null],['/atmos/nano-climate/',null]]){
        await go(route);
        assert.equal(await page.locator(marker).count(),1,route);
        for(const control of componentSelectors){
          const current=await readStyle(page,control);
          assert.deepEqual(preserved(current),preserved(original[control]),route+' '+control+' resting appearance');
          if(control==='.wc-chip'||control==='.wc-wa'){
            assert.ok(Math.abs(current.width-original[control].width)<=1,route+' '+control+' width');
            assert.ok(Math.abs(current.height-original[control].height)<=1,route+' '+control+' height');
          }
        }
        if(selector){
          await page.locator(selector).first().waitFor({state:'visible',timeout:15000});
          const s=await readStyle(page,selector);
          assert.equal(s.background,s.tint,route+' action surface');
          assert.equal(s.color,s.green,route+' action ink');
          assert.equal(s.radius,'6px',route+' action radius');
          assert.ok(s.decoration.includes('underline'),route+' action label');
          assert.ok(s.height>=51,route+' action height');
        }
        const search=page.locator('[data-public-search-field] input[type="search"]:visible').first();
        if(await search.count())assert.equal(await search.evaluate(el=>getComputedStyle(el).borderRadius),'6px',route+' search radius');
        const pager=page.locator('a.pager-arrow:visible').first();
        if(await pager.count()){
          assert.equal(await pager.evaluate(el=>getComputedStyle(el).borderRadius),'50%',route+' circular pagination');
          assert.equal(await pager.evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 255, 255)',route+' neutral pagination');
        }
        if(width===1440){
          await page.locator('.hdr-cart').hover();
          const hover=await readStyle(page,'.hdr-cart');
          assert.equal(hover.background,'rgb(242, 249, 222)',route+' cart hover');
          assert.equal(hover.radius,'6px',route+' cart hover radius');
          await page.mouse.move(0,0);
          assert.equal((await readStyle(page,'.hdr-cart')).background,'rgba(0, 0, 0, 0)',route+' cart returns to neutral');
        }
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+2),route+' horizontal overflow');
      }
      await go('/');
      assert.equal(await page.locator(marker).count(),0);
      assert.deepEqual(await readStyle(page,'.home-close-cta'),home,'Home CTA after navigation');
      for(const selector of componentSelectors)assert.deepEqual(preserved(await readStyle(page,selector)),preserved(original[selector]),'Home '+selector);
      console.log('Component style PASS',width);
    }finally{await page.close();}
  }
}finally{await browser.close();}
