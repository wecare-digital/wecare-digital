#!/usr/bin/env node
// Read-only targeted navigation style and scroll regression on exact export or approved preview.
import assert from 'node:assert/strict';
import {mkdirSync} from 'node:fs';
import {join} from 'node:path';
assert.ok(process.env.PUBLIC_QA_BASE,'Set PUBLIC_QA_BASE');
const origin=new URL(process.env.PUBLIC_QA_BASE);
const output=process.env.PUBLIC_QA_OUTPUT;
if(output)mkdirSync(output,{recursive:true});
const {chromium}=await import('playwright');
const browser=await chromium.launch();
let cueChecks=0;
try{
  for(const width of [1440,768,390,280,160]){
    const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce',ignoreHTTPSErrors:process.env.PUBLIC_QA_SNAPSHOT==='1',serviceWorkers:'block'});
    await context.route('**/*',route=>{
      const req=route.request(), url=new URL(req.url());
      if(!['GET','HEAD'].includes(req.method())||url.origin!==origin.origin)return route.abort();
      return route.continue();
    });
    try{
      const page=await context.newPage();
      for(const route of ['/','/shop/']){
        await page.goto(new URL(route,origin).href,{waitUntil:'domcontentloaded'});
        await page.mouse.move(0,0);
        const trigger=page.locator('.nav-trigger');
        const nav=page.getByRole('navigation',{name:'Public navigation'});
        assert.equal(await trigger.evaluate(el=>getComputedStyle(el).borderRadius),'10px');
        if(width===1440){
          await trigger.hover();
          assert.equal(await trigger.evaluate(el=>getComputedStyle(el).borderRadius),'13px','original trigger hover radius');
          await page.mouse.move(0,0);
        }
        await trigger.click();
        await nav.waitFor({state:'visible'});
        await page.waitForFunction(()=>document.querySelector('.nav-dropdown')?.hasAttribute('data-nav-tight'));
        const tight=await page.locator('.nav-dropdown').getAttribute('data-nav-tight')==='true';
        assert.equal(await nav.evaluate(el=>getComputedStyle(el).borderRadius),tight?'14px':'24px','original panel radius');
        assert.equal(await nav.locator('.nav-item:visible').first().evaluate(el=>getComputedStyle(el).borderRadius),'13px','original row radius');
        const search=nav.getByRole('searchbox',{name:'Search navigation'});
        assert.equal(await search.evaluate(el=>getComputedStyle(el).borderRadius),route==='/'?'13px':'6px','search-only radius');
        const group=nav.locator('.nav-group-link:visible').first();
        if(await group.count()){
          await page.mouse.move(0,0);
          assert.equal(await group.evaluate(el=>getComputedStyle(el).borderRadius),'8px','original group heading radius');
        }
        const scroll=nav.locator('.nav-products-scroll');
        const overflows=await scroll.evaluate(el=>el.scrollHeight>el.clientHeight+1);
        if(overflows){
          const cue=nav.locator('.nav-products-more');
          await cue.waitFor({state:'visible',timeout:5000});
          // Scrolling the outer panel to reveal the cue must not move the inner list.
          await cue.scrollIntoViewIfNeeded();
          await page.mouse.move(0,0);
          const style=await cue.evaluate(el=>{
            const s=getComputedStyle(el),svg=el.querySelector('svg'),v=getComputedStyle(svg),r=el.getBoundingClientRect(),m=new DOMMatrix(v.transform);
            return {radius:s.borderRadius,background:s.backgroundColor,width:r.width,height:r.height,fill:v.fill,iconWidth:v.width,d:svg.querySelector('path').getAttribute('d'),viewBox:svg.getAttribute('viewBox'),rotation:[m.a,m.b,m.c,m.d]};
          });
          const row=await nav.locator('.nav-row-chevron').first().evaluate(svg=>({d:svg.querySelector('path').getAttribute('d'),viewBox:svg.getAttribute('viewBox'),fill:getComputedStyle(svg).fill}));
          assert.equal(style.radius,'50%');
          assert.equal(style.background,'rgb(209, 244, 112)');
          assert.ok(style.width>=44&&style.height>=44);
          assert.equal(style.iconWidth,'24px');
          assert.equal(style.fill,row.fill);
          assert.equal(style.d,row.d,'common double-chevron path');
          assert.equal(style.viewBox,row.viewBox);
          assert.deepEqual(style.rotation.map(n=>Math.round(n)),[0,1,-1,0],'double chevron points down');
          if(output)await page.screenshot({path:join(output,'menu-'+width+(route==='/'?'-home':'-shop')+'.png')});
          const before=await scroll.evaluate(el=>el.scrollTop);
          await cue.click();
          await page.waitForFunction(previous=>document.querySelector('.nav-products-scroll').scrollTop>previous,before);
          cueChecks++;
        }
        await search.focus();
        await search.press('Escape');
        await nav.waitFor({state:'hidden'});
        assert.equal(await trigger.getAttribute('aria-expanded'),'false');
        console.log('Navigation PASS',width,route);
      }
    }finally{await context.close();}
  }
  assert.ok(cueChecks>0,'At least one overflowing Products rail must exercise the common arrow');
}finally{await browser.close();}
