#!/usr/bin/env node
/** Read-only Auth picker UI regression. Mock the initial Auth state, block
 * every POST; no OTP, customer session, message or payment is created. */
import assert from 'node:assert/strict';
assert.ok(process.env.PUBLIC_QA_BASE, 'Set PUBLIC_QA_BASE to an approved preview or site');
const origin = new URL(process.env.PUBLIC_QA_BASE);
assert.ok(['https:', 'http:'].includes(origin.protocol));
const { chromium } = await import('playwright');
const browser = await chromium.launch();
try {
  for (const width of [1440,768,390,280,160]) {
    const context = await browser.newContext({viewport:{width,height:width===1440?600:720},hasTouch:width<768,isMobile:width<768,reducedMotion:'reduce',serviceWorkers:'block'});
    let otpRequests = 0;
    await context.route('**/*', route => {
      const req = route.request(), url = new URL(req.url());
      if (url.origin === origin.origin && url.pathname === '/auth/step') otpRequests++;
      if (req.method() !== 'GET' || url.origin !== origin.origin) return route.abort();
      if (url.pathname === '/auth/state') return route.fulfill({json:{phase:'phone',csrf:'local-test-only',message:'',website:true,returnPath:'/',clientName:'',destination:''}});
      return route.continue();
    });
    try {
      const page = await context.newPage();
      await page.goto(new URL('/auth/',origin).href,{waitUntil:'domcontentloaded'});
      const trigger = page.locator('.country-trigger');
      const search = page.getByRole('searchbox',{name:'Search countries'});
      const panel = page.locator('.country-panel');
      const phone = page.locator('#auth-phone');
      await trigger.click();
      await panel.waitFor({state:'visible'});
      assert.equal(await trigger.getAttribute('aria-expanded'),'true');
      assert.equal(await panel.evaluate(el => getComputedStyle(el).borderRadius),'8px');
      const rect = await panel.evaluate(el => {
        const a = el.getBoundingClientRect(), v = window.visualViewport;
        const left = v?.offsetLeft ?? 0, top = v?.offsetTop ?? 0;
        return a.left >= left-1 && a.top >= top-1 && a.right <= left+(v?.width ?? innerWidth)+1 && a.bottom <= top+(v?.height ?? innerHeight)+1;
      });
      assert.ok(rect,'panel outside visual viewport');
      const selected = page.getByRole('option',{selected:true});
      assert.match(await selected.textContent(),/India/);
      assert.equal(await selected.evaluate(el => getComputedStyle(el).borderRadius),'6px');
      if(width===1440){
        const other = page.getByRole('option',{name:/United Arab Emirates/});
        await other.hover();
        assert.equal(await other.evaluate(el => getComputedStyle(el).backgroundColor),'rgb(242, 249, 222)');
        assert.equal(await selected.getAttribute('aria-selected'),'true');
      }
      await search.fill('United Kingdom');
      assert.equal(await page.getByRole('option').count(),1);
      await search.press('Enter');
      assert.match(await trigger.textContent(),/\+44/);
      assert.equal(await panel.count(),0);
      assert.equal(await phone.evaluate(el=>document.activeElement===el),true);
      await trigger.click();
      await panel.waitFor({state:'visible'});
      assert.equal(await search.inputValue(),'');
      await search.fill('India');
      await search.press('ArrowDown');
      const india=page.getByRole('option',{name:/India/});
      assert.equal(await india.evaluate(el=>document.activeElement===el),true);
      await india.press('Enter');
      assert.match(await trigger.textContent(),/\+91/);
      await trigger.focus();
      await trigger.press('ArrowDown');
      await panel.waitFor({state:'visible'});
      await search.press('Escape');
      assert.equal(await panel.count(),0);
      assert.equal(await trigger.evaluate(el=>document.activeElement===el),true);
      await trigger.click();
      await panel.waitFor({state:'visible'});
      await phone.click();
      assert.equal(await panel.count(),0);
      assert.equal(otpRequests,0,'country selection sent OTP');
      console.log('PASS',width);
    } finally { await context.close(); }
  }
} finally { await browser.close(); }
