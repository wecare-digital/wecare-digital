import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { rankBlogContent } from '../src/lib/navigationSearch.ts';
import { loadBlogCardIndex } from '../src/lib/blog-card-index.ts';

const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');

test('all legal and editorial search surfaces provide the shared accessible clear button', () => {
  const clear = read('src/components/SearchClearButton.tsx');
  assert.ok(clear.includes('aria-label="Clear search"'));
  assert.ok(clear.includes('type="button"'));
  assert.ok(clear.includes('input?.focus'));
  assert.ok(clear.includes('width:44px;height:44px'));
  assert.ok(clear.includes(':focus-visible'));
  for (const path of [
    'src/components/LegalDocument.tsx', 'src/components/BlogIndexView.tsx',
    'src/components/ProductBlogPanel.tsx', 'src/components/BlogSearch.tsx',
    'src/pages/post/[slug].tsx',
  ]) {
    const source = read(path);
    assert.ok(source.includes('<SearchClearButton'), path);
    assert.ok(source.includes("key === 'Escape'"), path);
    assert.ok(source.includes('padding-inline-end:90px'), path);
    assert.ok(source.includes('::-webkit-search-cancel-button'), path);
    assert.ok(source.includes('VoiceSearchMic'), path);
  }
  assert.ok(read('src/components/ProductBlogPanel.tsx').includes("setQuery( '' ); resetToFirstPage()"));
  assert.ok(read('src/pages/post/[slug].tsx').includes('action="/blog/" method="get"'));
});

test('blog index query hydrates after mount and full index loads only for search', () => {
  const source = read('src/components/BlogIndexView.tsx');
  assert.ok(source.includes("const [ query, setQuery ] = useState<string>( '' );"));
  assert.ok(source.includes("window.addEventListener( 'popstate', syncQuery )"));
  assert.ok(source.includes("url.searchParams.delete( 'q' )"));
  assert.ok(source.includes('if ( !needsIndex || requested.current ) return;'));
  assert.ok(source.includes('requested.current = false; setAttempt'));
});

test('editorial topics support curated Bengali and Hindi synonyms without unrelated results', () => {
  const posts = [
    { title: 'Commitments and promises', excerpt: 'Keeping your word', category: 'Conversations' },
    { title: 'A difficult decision', excerpt: 'Clarify your choice', category: 'Conversations' },
    { title: 'Integrity in daily life', excerpt: 'Honesty and action', category: 'Conversations' },
    { title: 'A recipe for rice', category: 'Gastronomy' },
  ];
  assert.equal(rankBlogContent(posts, 'প্রতিশ্রুতি')[0]?.title, 'Commitments and promises');
  assert.equal(rankBlogContent(posts, 'फैसला')[0]?.title, 'A difficult decision');
  assert.equal(rankBlogContent(posts, 'সততা')[0]?.title, 'Integrity in daily life');
  assert.equal(rankBlogContent(posts, 'रसोईxyz').length, 0);
  assert.equal(rankBlogContent(posts.filter(post => post.category === 'Conversations'), 'रান্না').length, 0);
  assert.deepEqual(rankBlogContent(posts, ''), posts);
});

test('static index retries after failure and empty responses, deduplicates requests and caches success', async t => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => {
    calls += 1;
    if (calls === 1) return new Response('', {status: 503});
    if (calls === 2) return Response.json({posts: []});
    return Response.json({posts: [{slug: 'sample', title: 'Sample'}]});
  };
  await assert.rejects(loadBlogCardIndex(), /503/);
  assert.deepEqual(await loadBlogCardIndex(), []);
  const [a, b] = await Promise.all([loadBlogCardIndex(), loadBlogCardIndex()]);
  assert.strictEqual(a, b);
  assert.strictEqual(await loadBlogCardIndex(), a);
  assert.equal(calls, 3);
});
