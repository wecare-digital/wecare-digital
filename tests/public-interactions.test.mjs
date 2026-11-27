import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { publicSupportGeometry } from '../src/lib/publicSupportGeometry.ts';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

test('public support geometry stays in the visible viewport and keeps a usable panel when possible', () => {
  let count = 0;
  for (const viewportWidth of [160,280,320,390,430,720,768,844,1440,2560]) {
    for (const viewportHeight of [160,200,280,390,640,844,1080]) {
      for (const viewportTop of [0,40]) for (const safeBottom of [0,24]) {
        for (const footerTop of [null,viewportTop+viewportHeight-70,viewportTop+viewportHeight-220]) for (const open of [false,true]) {
          const layoutHeight=viewportTop+viewportHeight+140, pillHeight=54;
          const a=publicSupportGeometry({layoutHeight,viewportTop,viewportHeight,viewportWidth,headerBottom:108,footerTop,pillHeight,safeBottom,open});
          const bottom=layoutHeight-a.bottom, top=bottom-pillHeight;
          assert.ok(top >= viewportTop-1 && bottom <= viewportTop+viewportHeight+1);
          if(open) assert.ok(top-10-a.panelMax >= viewportTop-1);
          assert.ok(a.panelMax >= 0);
          if(open && viewportHeight>=280) assert.ok(a.panelMax>=132);
          count++;
        }
      }
    }
  }
  assert.equal(count,1680);
});
test('the seven public search surfaces opt into the same non-overlapping layout', () => {
  const css=read('src/styles/public-interactions.css');
  for(const token of ['flex-wrap: wrap','flex: 1 1 96px','position: static','outline: 2px solid var(--public-brand-green)']) assert.ok(css.includes(token),token);
  assert.ok(read('src/pages/_app.tsx').includes("import '../styles/public-interactions.css';"));
  for(const path of ['src/components/Header.tsx','src/components/BlogSearch.tsx','src/components/BlogIndexView.tsx','src/components/ProductBlogPanel.tsx','src/components/LegalDocument.tsx','src/pages/post/[slug].tsx','src/components/orders/OrderActionsMenu.tsx']){
    const source=read(path);
    for(const token of ['data-public-search-field=','--public-search-end-padding','nativeEvent.isComposing','<SearchClearButton','<VoiceSearchMic']) assert.ok(source.includes(token),path+' '+token);
  }
  assert.ok(read('scripts/verify_public_browser.mjs').includes('assertSharedSearchGeometry'));
});
test('shared cards, actions and paging keep responsive tokens and logical scroll behavior', () => {
  const shop=read('src/components/ShopListingView.tsx');
  const blog=read('src/components/BlogIndexView.tsx');
  for (const source of [shop,blog]) assert.ok(source.includes('--public-card-padding-reflow'));
  for(const p of ['src/components/Pager.tsx','src/components/ProductBlogPanel.tsx','src/components/ShopListingView.tsx']){
    assert.ok(read(p).includes('--public-pager-size'),p);
    assert.ok(read(p).includes('--public-progress-height'),p);
  }
  for(const p of ['src/components/ProductBlogPanel.tsx','src/components/ShopListingView.tsx']) assert.ok(read(p).includes('Math.abs( el.scrollLeft )'),p);
  assert.ok(read('src/components/PillButton.tsx').includes('--public-responsive-cta-size'));
  assert.ok(read('src/components/CheckoutAction.tsx').includes('--public-responsive-cta-size'));
  const support=read('src/components/SupportWidget.tsx');
  assert.ok(support.includes('window.visualViewport'));
  assert.ok(support.includes('publicSupportGeometry( {'));
});
