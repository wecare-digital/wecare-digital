import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { publicSupportGeometry } from '../src/lib/publicSupportGeometry.ts';
import { voiceSearchFailureMessage } from '../src/lib/publicVoiceSearch.ts';
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
test('footer parking uses layout coordinates even when the visual viewport pans', () => {
  const a = publicSupportGeometry({layoutHeight:900, viewportTop:40, viewportHeight:500, viewportWidth:320, headerBottom:108, footerTop:460, pillHeight:54, safeBottom:0, open:false});
  assert.equal(a.bottom, 456);
  assert.equal(900-a.bottom, 460-16);
  const b = publicSupportGeometry({layoutHeight:900, viewportTop:80, viewportHeight:500, viewportWidth:320, headerBottom:148, footerTop:500, pillHeight:54, safeBottom:0, open:false});
  assert.equal(b.bottom, 416);
  assert.equal(900-b.bottom, 500-16);
});

test('voice failure and language activation retain typed and accessible alternatives', () => {
  const voice = read('src/components/VoiceSearchMic.tsx');
  assert.match(voiceSearchFailureMessage('not-allowed'), /permissions.*type your search/i);
  assert.ok(voice.includes('role="status" aria-live="polite" aria-atomic="true"'));
  assert.ok(voice.includes("event.error !== 'aborted'"));
  assert.ok(voice.includes('voiceSearchFailureMessage( event.error )'));
  assert.ok(voice.includes('aria-describedby={ feedback ? statusId : undefined }'));
  assert.ok(voice.includes('activeRef.current = true'));
  assert.match(voice, /try \{\s*recognition\.lang = pageVoiceLocale\(\);\s*recognition\.start\(\);/);
  assert.ok(voice.includes('cancelledRef.current = true'));
  assert.ok(voice.includes('.voice-search-status.is-visible{position:static;display:block;flex:0 0 100%'));
  assert.doesNotMatch(read('src/styles/public-interactions.css'), /\.voice-search-feedback/);
  const support = read('src/components/SupportWidget.tsx');
  assert.ok(support.includes('tabIndex={ -1 }'));
  assert.ok(support.includes('onClick={ event => { closePanel( event.detail === 0 ); void applyLanguage( lang.code ); } }'));
  assert.ok(support.includes('list.scrollTop += rowBox.bottom - listBox.bottom'));
  assert.ok(support.includes('document.documentElement.clientHeight || window.innerHeight'));
  const qa = read('scripts/verify_public_browser.mjs');
  for (const token of ['PUBLIC_QA_INTERACTIONS_ONLY','DeniedSpeechRecognition','translationAttempted','verifySupport','verifyVoiceFallback',voiceSearchFailureMessage('not-allowed'),'aria-describedby','voice-search-status.is-visible']) assert.ok(qa.includes(token),token);
});

test('the seven public search surfaces opt into the same non-overlapping layout', () => {
  const css=read('src/styles/public-interactions.css');
  for(const token of ['flex-wrap: wrap','flex: 1 1 96px','position: static','outline: none','box-shadow: inset 0 -2px 0 var(--public-brand-green)','outline: 2px solid Highlight']) assert.ok(css.includes(token),token);
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

test('public navigation arrows use one contrasting blue token, with search focus underlines', () => {
  assert.ok(read('src/styles/tokens.css').includes('--public-nav-arrow: var(--public-accent-blue)'));
  for (const [path, marker] of [
    ['src/components/Header.tsx', '.nav-row-chevron{margin-inline-start:auto;fill:var(--public-nav-arrow)'],
    ['src/components/orders/OrderActionsMenu.tsx', 'flex:none;fill:var(--public-nav-arrow)'],
    ['src/components/LegalDocument.tsx', '.lgd-contents-chevron,.lgd-group-chevron{color:var(--public-nav-arrow)'],
    ['src/components/SupportWidget.tsx', 'border-right:2px solid var(--public-nav-arrow)'],
    ['src/pages/auth.tsx', '.country-arrow{color:var(--public-nav-arrow)}'],
  ]) assert.ok(read(path).includes(marker), path);
  assert.ok(read('src/components/SupportWidget.tsx').includes('.wc-search:focus-within{border-bottom-color:var(--public-brand-green);box-shadow:inset 0 -2px 0 var(--public-brand-green);outline:none}'));
  assert.ok(read('src/pages/auth.tsx').includes('.country-search input:focus{border-bottom-color:var(--public-brand-green);box-shadow:inset 0 -2px 0 var(--public-brand-green);outline:none}'));
});
