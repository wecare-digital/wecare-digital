import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (name) => readFileSync(new URL('../src/components/' + name + '.tsx', import.meta.url), 'utf8');

test('browse routes keep crawlable destinations without eager viewport prefetch', () => {
  assert.match(read('ShopListingView'), /href=\{ listing\.href \} prefetch=\{ false \}/);
  assert.match(read('BlogIndexView'), /href=\{ href \} prefetch=\{ false \}/);
  assert.match(read('BlogIndexView'), /href=\{ `\/post\/\$\{post\.slug\}\/\x60 \} prefetch=\{ false \}/);
  assert.match(read('ProductBlogPanel'), /className="pbp-link"[^>]*href=[^>]+prefetch=\{ false \}[^>]*tabIndex=/);
  assert.match(read('ProductBlogPanel'), /href="\/blog\/" prefetch=\{ false \}/);
  assert.match(read('BlogTags'), /href=\{ `\/blog\/\?q=\$\{encodeURIComponent\( tag \)\}\x60 \}\s*prefetch=\{ false \}/);
});
