import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { ORDER_REQUESTS, orderRequestById, orderRequestForLabel, stashOrderRequest, takeOrderRequest } from '../src/lib/orderRequestSelection.ts';
import { rankNavigation, NAV_DISCOVERY, normalizeNavigationText, contentSearchText, rankPublicContent, rankBlogContent } from '../src/lib/navigationSearch.ts';

const items = ['Khata','Visa','Panchang','Orders','Trip','Drop Docs','Track','Parichay'].map( label => ( { label, searchText: [label, ...(NAV_DISCOVERY[label] || [])].join(' ') } ) );
const first = query => rankNavigation(items, query)[0]?.label;
test('ranked navigation finds typed, translated, misspelled and multiword requests', () => {
  assert.equal(first('Khata'), 'Khata');
  assert.equal(first('inovice'), 'Khata');
  assert.equal(first('ভিসা'), 'Visa');
  assert.equal(first('पंचांग'), 'Panchang');
  assert.equal(first('digital profile'), 'Parichay');
  assert.equal(first('upload documents'), 'Drop Docs');
  assert.equal(rankNavigation(items, 'zzzzzzz').length, 0);
  assert.equal(rankNavigation(items, '!!').length, 0);
  assert.equal(normalizeNavigationText('   VISA!  '), 'visa');
});

test('every request selection is allowlisted and independent of WhatsApp send intents', () => {
  assert.equal(ORDER_REQUESTS.length, 6);
  for (const request of ORDER_REQUESTS) {
    assert.equal(orderRequestForLabel(request.label)?.id, request.id);
    assert.equal(orderRequestById(request.id)?.label, request.label);
  }
  assert.equal(orderRequestForLabel('Subscribe'), null);
  assert.equal(orderRequestById('javascript:alert(1)'), null);
  const header = readFileSync(new URL('../src/components/Header.tsx', import.meta.url), 'utf8');
  const orders = readFileSync(new URL('../src/components/orders/OrdersPage.tsx', import.meta.url), 'utf8');
  const actions = readFileSync(new URL('../src/components/orders/OrderActionsMenu.tsx', import.meta.url), 'utf8');
  const requestEntries = readFileSync(new URL('../src/config/whatsappServiceEntries.ts', import.meta.url), 'utf8');
  for (const request of ORDER_REQUESTS) assert.ok(requestEntries.includes("slug: '" + request.id + "'"));
  assert.ok(header.includes('stashOrderRequest( request.id )'));
  assert.ok(header.includes('void takeCustomerMenuAction()'));
  assert.ok(header.includes('aria-expanded={ familyOpen } aria-controls={ familyId }'));
  assert.ok(header.includes('hidden={ !familyOpen }'));
  assert.ok(orders.includes('const selection = takeOrderRequest()'));
  assert.ok(orders.includes('whatsappServiceLink( selectedRequest.id )'));
  assert.ok(actions.includes('onRequest( request.id )'));
  assert.ok(actions.includes("from '../../lib/publicNavigationIcons'"));
});
test('legal scroll tracking and search retain native fragment navigation and full prose', () => {
  const legal = readFileSync(new URL('../src/components/LegalDocument.tsx', import.meta.url), 'utf8');
  assert.ok(legal.includes("window.addEventListener( 'scroll', schedule, { passive: true } )"));
  assert.ok(legal.includes('window.cancelAnimationFrame( frame )'));
  assert.ok(legal.includes('aria-label="Find a legal clause"'));
  assert.ok(legal.includes('placeholder="Search"'));
  assert.ok(legal.includes("import VoiceSearchMic from './VoiceSearchMic'"));
  assert.ok(legal.includes('<VoiceSearchMic onTranscript={ applySectionQuery } />'));
  assert.ok(legal.includes('input::-webkit-search-cancel-button'));
  assert.ok(legal.includes('padding-inline-end:46px'));
  assert.ok(legal.includes("event.key === 'Escape' && sectionQuery"));
  assert.ok(legal.includes('setSectionQuery( value.slice( 0, 120 ) )'));
  assert.ok(legal.indexOf('<input id={ searchId }') < legal.indexOf('<details className="lgd-contents"'));
  assert.ok(legal.includes('onFocus={ () => { if ( tocRef.current ) tocRef.current.open = true; } }'));
  assert.ok(legal.includes('border:0;border-bottom:2px solid var(--public-search-underline);border-radius:var(--public-hover-radius);background:transparent'));
  assert.ok(legal.includes('font-size:var(--public-body-size);font-weight:var(--public-body-weight)'));
  assert.ok(legal.includes('background:var(--public-accent-blue-tint)'));
  assert.ok(legal.includes('aria-label="Open legal section search"'));
  assert.ok(legal.includes('className="lgd-return-to-contents"'));
  assert.ok(legal.includes('section.paragraphs.map'));
});

test('request selection survives one auth handoff and rejects expired or tampered selections', () => {
  const store = new Map();
  const fakeWindow = { sessionStorage: { setItem: (key,value) => store.set(key,value), getItem: key => store.get(key) ?? null, removeItem: key => store.delete(key) } };
  const prior = globalThis.window;
  try {
    globalThis.window = fakeWindow;
    stashOrderRequest('drop-docs');
    assert.equal(takeOrderRequest(), 'drop-docs');
    assert.equal(takeOrderRequest(), null);
    const key = 'wecare.orders.requestSelection.v1';
    store.set(key, JSON.stringify({id:'vault', at:Date.now()-11*60*1000}));
    assert.equal(takeOrderRequest(), null);
    store.set(key, JSON.stringify({id:'arbitrary', at:Date.now()}));
    assert.equal(takeOrderRequest(), null);
  } finally {
    if (prior === undefined) delete globalThis.window;
    else globalThis.window = prior;
  }
});

test('Extras contains two expandable families, with clean iOS label and no Perks', () => {
  const header = readFileSync(new URL('../src/components/Header.tsx', import.meta.url), 'utf8');
  const aliases = readFileSync(new URL('../src/lib/navigationSearch.ts', import.meta.url), 'utf8');
  const extras = header.slice(header.indexOf("heading: 'Extras'"), header.indexOf("heading: 'Contact'"));
  assert.ok(extras.includes("label: 'App',\n            searchTerms:"));
  assert.ok(extras.includes("label: 'AI',\n            searchTerms:"));
  for (const label of ['Android', 'iOS']) assert.ok(extras.includes("label: '" + label + "', href: PLAY_STORE.developerUrl, external: true"));
  for (const [label, href] of [['ChatGPT','https://chatgpt.com/'], ['Claude','https://claude.ai/'], ['Gemini','https://gemini.google.com/']]) {
    assert.ok(extras.includes("label: '" + label + "', href: '" + href + "', external: true"));
  }
  assert.ok(!extras.includes("note: 'Temporarily opens Google Play'"));
  assert.ok(!header.includes('child.note'));
  assert.ok(!header.includes("label: 'Perks'"));
  assert.ok(!header.includes('377GALDW4E26F1'));
  assert.ok(!header.includes("heading: 'With AI'"));
  assert.ok(!header.includes("label: 'Google Play'"));
  assert.ok(!aliases.includes('  Perks:'));
  assert.ok(aliases.includes("  iOS: [ '',"));
  assert.ok(!aliases.includes('Temporarily opens Google Play'));
  assert.ok(header.includes('for ( const child of link.children || [] ) push( child, [ ...terms, link.label ], true )'));
  assert.ok(header.includes('hidden={ !familyOpen }'));
});

test('Contact and Legal Stuff use the same dotted submenu arrow in the menu and search', () => {
  const header = readFileSync(new URL('../src/components/Header.tsx', import.meta.url), 'utf8');
  const icons = readFileSync(new URL('../src/lib/publicNavigationIcons.ts', import.meta.url), 'utf8');
  for (const heading of ['Contact', 'Legal Stuff']) assert.ok(header.includes("heading: '" + heading + "',\n        nestedLinks: true,"));
  assert.ok(header.includes("heading: 'Legal Stuff',\n        nestedLinks: true,\n        collapsible: true,"));
  assert.ok(header.includes('aria-expanded={ sectionOpen } aria-controls={ sectionId }'));
  assert.ok(header.includes('id={ sectionId } hidden={ !sectionOpen }'));
  assert.ok(header.includes('familyOverrides[ sectionId ] ?? section.links.some( isActive )'));
  assert.ok(header.includes('.nav-section-toggle[aria-expanded=\'true\'] .nav-row-chevron{transform:rotate(90deg)}'));
  for (const [label, href] of [['Contact us','/contact/'], ['Terms','/terms/'], ['Privacy','/privacy/']]) {
    assert.ok(header.includes("label: '" + label + "', href: '" + href + "'"));
  }
  assert.ok(header.includes('section.nestedLinks === true'));
  assert.ok(header.includes("{ section.nestedLinks ? ("));
  assert.ok(header.includes("section.nestedLinks ? 'nav-child' : ''"));
  assert.ok(header.includes('{ link.nested ? ('));
  assert.ok(icons.includes('SUBNAV_DOT_PATH'));
  assert.ok(!icons.includes("  'Contact us':"));
  assert.ok(!icons.includes('  Terms:'));
  assert.ok(!icons.includes('  Privacy:'));
});

test('shared content search ranks titles, matches multiword typos and curated Hindi/Bengali topics', () => {
  const posts = [
    { title: 'Travel planning', excerpt: 'Preparation and dates for a trip', category: 'Conversations', tags: ['visa'] },
    { title: 'Refund policy', excerpt: 'How refunds and cancellation work', category: 'Conversations', tags: ['payment'] },
    { title: 'Payment processing', excerpt: 'Invoice and billing records', category: 'Conversations', tags: [] },
    { title: 'A billing guide', excerpt: 'Refund policy and invoice records', category: 'Conversations', tags: [] },
  ];
  assert.equal(rankBlogContent(posts, 'refnud policy')[0]?.title, 'Refund policy');
  assert.equal(rankBlogContent(posts, 'visa travel')[0]?.title, 'Travel planning');
  assert.ok(rankBlogContent(posts, 'invoice billing').some(post => post.title === 'Payment processing'));
  assert.equal(rankBlogContent(posts, 'billing guide')[0]?.title, 'A billing guide');
  assert.ok(rankBlogContent(posts, 'धन वापसी').some(post => post.title === 'Refund policy'));
  assert.ok(rankBlogContent(posts, 'ভিসা').some(post => post.title === 'Travel planning'));
  assert.equal(rankBlogContent(posts, 'zzzzzzzzz').length, 0);
  assert.deepEqual(rankBlogContent(posts, ''), posts);
  assert.ok(!contentSearchText(['Cooking rice']).includes('refund'));
  const products = [{ name: 'Khata', blurb: 'Invoice creation' }, { name: 'Visa', blurb: 'Travel documents' }];
  assert.equal(rankPublicContent(products, 'inovice', p => p.name, p => [p.blurb])[0]?.name, 'Khata');
  assert.equal(rankPublicContent(products, 'ভিসা', p => p.name, p => [p.blurb])[0]?.name, 'Visa');
});
test('public content surfaces share search ranking without broadening source or category scope', () => {
  const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
  const legal = read('src/components/LegalDocument.tsx');
  const blog = read('src/components/BlogIndexView.tsx');
  const anew = read('src/components/ProductBlogPanel.tsx');
  const shop = read('src/components/ShopListingView.tsx');
  assert.ok(legal.includes('rankNavigation( sectionIndex, sectionQuery )'));
  assert.ok(legal.includes("item.section.number === exactNumber || item.section.number.startsWith( exactNumber + '.' )"));
  assert.ok(blog.includes('rankBlogContent( scoped, trimmedQuery )'));
  assert.ok(blog.includes('available.filter( post => post.category === activeCategory )'));
  assert.ok(blog.includes('const available = allCards ?? posts'));
  assert.ok(anew.includes('rankBlogContent( scoped, query )'));
  assert.ok(anew.includes('cards.filter( card => card.category === category )'));
  assert.ok(shop.includes('rankPublicContent( shelfListings, query'));
  assert.ok(shop.includes('listing.showOnShopShelf !== false'));
  assert.ok(read('src/pages/post/[slug].tsx').includes('action="/blog/" method="get"'));
  assert.ok(read('src/components/SupportWidget.tsx').includes('rankNavigation( all.map( lang'));
  assert.ok(read('src/pages/auth.tsx').includes('rankNavigation( DIAL_CODES.map'));
  const header = read('src/components/Header.tsx');
  const orders = read('src/components/orders/OrderActionsMenu.tsx');
  for (const source of [header, orders]) assert.ok(source.includes('font-size:var(--public-nav-heading-size);font-weight:var(--public-nav-heading-weight);line-height:var(--public-nav-heading-leading)'));
});


test('floating WhatsApp widget links directly to the approved contact URL', () => {
  const widget = readFileSync(new URL('../src/components/SupportWidget.tsx', import.meta.url), 'utf8');
  assert.match(widget, /className="wc-wa"\s+href="https:\/\/wa\.me\/message\/APDM5HUWH26SG1"\s+target="_blank"\s+rel="noopener noreferrer"/);
  assert.doesNotMatch(widget, /href="https:\/\/wecare\.digital\/r\/wa"/);
});
