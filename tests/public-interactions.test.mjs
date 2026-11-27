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
  for(const token of ['flex-wrap: wrap','flex: 1 1 96px','position: static','outline: none','box-shadow: var(--public-search-focus-shadow)','outline: 2px solid Highlight']) assert.ok(css.includes(token),token);
  assert.ok(read('src/pages/_app.tsx').includes("import '../styles/public-interactions.css';"));
  for(const path of ['src/components/Header.tsx','src/components/BlogSearch.tsx','src/components/BlogIndexView.tsx','src/components/ProductBlogPanel.tsx','src/components/LegalDocument.tsx','src/pages/post/[slug].tsx','src/components/orders/OrderActionsMenu.tsx']){
    const source=read(path);
    for(const token of ['data-public-search-field=','--public-search-end-padding','--public-search-underline','--public-search-focus-shadow','--public-hover-radius','nativeEvent.isComposing','<SearchClearButton','<VoiceSearchMic']) assert.ok(source.includes(token),path+' '+token);
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
  const actions=read('src/styles/public-interactions.css');
  const actionRule=actions.match(/:is\(\.auth-action,[\s\S]*?\)\s*\{([^}]+)\}/);
  assert.ok(actionRule, 'shared Auth action rule');
  assert.match(actionRule[0], /\.public-auth-action\b/);
  assert.match(actionRule[0], /\.checkout-action\b/);
  assert.match(actionRule[1], /font:\s*700 var\(--public-responsive-cta-size\)/);
  assert.ok(read('src/components/PillButton.tsx').includes('pill public-auth-action'));
  assert.ok(read('src/components/CheckoutAction.tsx').includes('className="checkout-action"'));
  const support=read('src/components/SupportWidget.tsx');
  assert.ok(support.includes('window.visualViewport'));
  assert.ok(support.includes('publicSupportGeometry( {'));
});

test('public navigation arrows use the same brand-green token as icons, with search focus underlines', () => {
  assert.ok(read('src/styles/tokens.css').includes('--public-nav-arrow: var(--public-brand-green)'));
  for (const [path, marker] of [
    ['src/components/Header.tsx', '.nav-row-chevron{margin-inline-start:auto;fill:var(--public-nav-arrow)'],
    ['src/components/orders/OrderActionsMenu.tsx', 'flex:none;fill:var(--public-nav-arrow)'],
    ['src/components/LegalDocument.tsx', '.lgd-contents-chevron,.lgd-group-chevron{color:var(--public-nav-arrow)'],
    ['src/components/SupportWidget.tsx', 'border-right:2px solid var(--public-nav-arrow)'],
    ['src/pages/auth.tsx', '.country-arrow{color:var(--public-nav-arrow)}'],
  ]) assert.ok(read(path).includes(marker), path);
  assert.ok(read('src/components/SupportWidget.tsx').includes('.wc-search:focus-within{border-bottom-color:var(--public-search-underline);box-shadow:var(--public-search-focus-shadow);outline:none}'));
  assert.ok(read('src/pages/auth.tsx').includes('.country-search input:focus{border-bottom-color:var(--public-search-underline);box-shadow:var(--public-search-focus-shadow);outline:none}'));
});

test('public searches and labelled actions share the Auth action design', () => {
  const tokens = read('src/styles/tokens.css');
  assert.ok(tokens.includes('--public-search-underline: var(--public-brand-lime)'));
  assert.ok(tokens.includes('--public-search-focus-shadow: inset 0 -3px 0 var(--public-search-underline), inset 0 -5px 0 var(--public-brand-green)'));
  assert.ok(tokens.includes('--public-button-hover: var(--public-hover-surface)'));
  assert.ok(tokens.includes('--public-hover-radius: 13px'));
  assert.ok(tokens.includes('--public-hover-surface: #f2f9de'));
  assert.ok(tokens.includes('--public-nav-hover: var(--public-hover-surface)'));
  const css = read('src/styles/public-interactions.css');
  assert.ok(css.includes('@media (hover: hover) and (pointer: fine)'));
  assert.ok(css.includes('background-color: var(--public-hover-surface)'));
  for (const token of ['background: var(--public-button-hover)', 'border-radius: var(--public-hover-radius)', 'background: var(--public-lime-tint)', 'min-height: 52px', 'font: 700 var(--public-responsive-cta-size)/1.35 var(--font-sans)', 'text-decoration: underline']) assert.ok(css.includes(token), token);
  for (const [path, action] of [
    ['src/pages/auth.tsx', 'auth-action'],
    ['src/components/cart/CartPage.tsx', 'cart-auth-action'],
    ['src/pages/checkout/status.tsx', 'co-auth-action'],
    ['src/components/CheckoutProfile.tsx', 'checkout-profile-action'],
    ['src/components/CheckoutAction.tsx', 'checkout-action'],
    ['src/components/PillButton.tsx', 'public-auth-action'],
    ['src/components/get/GetPage.tsx', 'sf-file-action-button'],
  ]) {
    assert.ok(read(path).includes(action), path);
    assert.ok(css.includes('.' + action), action);
  }
  assert.ok(read('src/components/orders/OrderActionsMenu.tsx').includes('background:var(--public-button-hover)'));
});

test('Home closing CTA and shared dock retain their original design instead of Auth action styles', () => {
  const css=read('src/styles/public-interactions.css');
  assert.doesNotMatch(css, /\.cb-cta\b|\.home-close-cta\b|\.ps-action\b/);
  const home=read('src/pages/index.tsx');
  assert.match(home, /\.home-close-cta\)\{font-size:18px;/);
  const closing=read('src/components/public/ClosingBand.tsx');
  assert.match(closing, /\.cb-cta\{[^}]*border-radius:var\(--public-cta-radius\)/);
  assert.match(closing, /\.cb-cta\{[^}]*background:var\(--public-brand-lime\)/);
  const dock=read('src/components/PublicShare.tsx');
  assert.match(dock, /\.ps-action\{[^}]*border-radius:50%/);
  assert.match(dock, /\.ps-subscribe\{background:var\(--public-brand-lime\)/);
});
