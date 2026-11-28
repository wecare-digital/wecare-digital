import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {authGateMatches, canonicalOrigin,snapshotOrigin} from '../scripts/public_qa_origin.mjs';
const read=path=>readFileSync(new URL('../'+path,import.meta.url),'utf8');
test('only exact same-origin authentication return is a verified anonymous gate',()=>{
  for(const origin of [canonicalOrigin,snapshotOrigin]){
    const expected='/elsewhere/arogya-yatra/';
    assert.ok(authGateMatches(new URL('/auth?return=%2Felsewhere%2Farogya-yatra%2F',origin).href,origin,expected));
    assert.ok(!authGateMatches(new URL('/auth?return=%2Forders%2F',origin).href,origin,expected));
    assert.ok(!authGateMatches('https://other.example/auth?return=%2Felsewhere%2Farogya-yatra%2F',origin,expected));
    assert.ok(!authGateMatches(new URL('/auth?return=%2Felsewhere%2Farogya-yatra%2F%3Fnext%3Dx',origin).href,origin,expected));
  }
});
test('shared hero reserves font overhang without altering horizontal grid',()=>{
  const source=read('src/components/RotatingPill.tsx');
  assert.match(source,/box-sizing:border-box;padding-block:\.10em;line-height:1\.1;overflow:hidden/);
  assert.match(source,/grid-template-columns:minmax\(0,1fr\)/);
  assert.match(source,/aria-pressed=\{ paused \}/);
  assert.doesNotMatch(source,/Pause headline rotation|rp-control/);
});
test('Relay code panes have keyboard focus and an accessible name',()=>{
  const source=read('src/pages/relay-os/index.tsx');
  assert.match(source,/<pre className="code-body" role="region" tabIndex=\{ 0 \} aria-label=/);
  assert.match(source,/<pre className="code-block" dir="ltr" role="region" tabIndex=\{ 0 \} aria-label=/);
  assert.match(source,/\.code-block:focus-visible,\.code-body:focus-visible/);
});
test('immutable acceptance shares a verified exact export, never proxies transactions',()=>{
  const workflow=read('.github/workflows/public-acceptance.yml');
  assert.match(workflow,/name: exact-public-export/);
  assert.match(workflow,/sha256sum -c export\.sha256/);
  assert.match(workflow,/test "\$\(cat revision\.txt\)" = "\$PUBLIC_QA_REVISION"/);
  const server=read('scripts/serve_public_qa.mjs');
  assert.match(server,/server\.listen\(4173,'127\.0\.0\.1'/);
  assert.match(server,/!\['GET','HEAD'\]\.includes\(req\.method\)/);
  const fixture=read('scripts/verify_checkout_fixture.mjs');
  assert.match(fixture,/Contributions cannot be taken right now\. Nothing has been charged\./);
  assert.match(fixture,/if\(snapshot\) return route\.continue\(\)/);
  assert.doesNotMatch(fixture,/function snapshot\(/);
  assert.match(fixture,/async function captureSnapshot\(label\)/);
  assert.match(fixture,/await verifyAppointmentGate\(\)/);
  assert.match(fixture,/return withIsolatedBrowser\(browser=>runScenario\(browser,width,mode\)\)/);
  assert.match(fixture,/return withIsolatedBrowser\(runAppointmentGate\)/);
  // #2531: the Arogya form is public; sign-in is checked only at submission.
  assert.match(fixture,/Sign in to submit your request/);
  // The only axe exemption: Firefox profile scenario; other engines and Firefox's other scenarios still scan.
  assert.equal(fixture.match(/axeSkipped/g)?.length,1);
  assert.match(fixture,/if\(engine==='firefox'&&mode==='profile'\)\{/);
  assert.match(fixture,/assert\.equal\(bookingCalls,0\)/);
  assert.doesNotMatch(fixture,/Retry live choices|verifyAuthGate\(page,origin,'\/elsewhere\/arogya-yatra\/'\)/);
  assert.match(fixture,/finally \{ await browser\.close\(\); \}/);
  assert.match(fixture,/assert\.equal\(failures\.length,0,failures\.join/);
});

test('immutable snapshot explicitly builds the intercepted invoice read capability',()=>{
  const workflow=read('.github/workflows/public-acceptance.yml');
  assert.match(workflow,/name: Build static website[\s\S]*?NEXT_PUBLIC_ENABLE_INVOICE_DOWNLOAD: 'true'/);
  const fixture=read('scripts/verify_checkout_fixture.mjs');
  assert.match(fixture,/my-invoice'&&method==='POST'/);
  assert.match(fixture,/Paid row must expose invoice action/);
});
test('travel assistant send icon has no visible font-ligature fallback',()=>{
  const source=read('src/components/ElsewhereTravelAssistant.tsx');
  const send=source.match(/<button\s+className="eta-send"([\s\S]*?)<\/button>/);
  assert.ok(send);
  assert.match(send[1],/aria-label="Send"/);
  assert.match(send[1],/<svg[^>]*aria-hidden="true"[^>]*focusable="false"/);
  assert.doesNotMatch(send[1],/symbol\(|eta-material/);
});


test('dark Relay editor tabs are excluded from every light public action theme selector',()=>{
  const css=read('src/styles/public-button-theme.css');
  assert.doesNotMatch(css,/button:not\(|\.pp-tab\b/);
  const relay=read('src/pages/relay-os/index.tsx');
  assert.match(relay,/aria-pressed=\{activeCode === i\} className=\{`pp-tab/);
  assert.match(relay,/\.pp-tab\{[^}]*color:#b8b8b8;background:transparent/);
  assert.match(relay,/\.pp-tab:focus-visible\{outline:3px solid var\(--public-brand-lime\)/);
});

test('narrow order search retains full-size nonoverlapping voice and clear targets',()=>{
  const menu=read('src/components/orders/OrderActionsMenu.tsx');
  assert.match(menu,/@media\(max-width:359px\)\{[\s\S]*?\.orm-search-field > \.orm-search\{flex:0 0 100%/);
  assert.match(menu,/\.orm-search-field > :global\(button\.voice-search-mic\)\{[^}]*min-inline-size:46px;block-size:46px;min-block-size:46px/);
  const fixture=read('scripts/verify_checkout_fixture.mjs');
  assert.ok(fixture.includes('control.width>=44&&control.height>=44&&control.inside&&control.hit&&!control.overlap'));
  assert.ok(fixture.includes("phase='wait for required checkout profile'"));
  assert.match(read('.github/workflows/public-acceptance.yml'),/DEBUG:.*pw:browser/);
});
