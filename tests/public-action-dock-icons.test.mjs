import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source=readFileSync(new URL('../src/components/PublicShare.tsx',import.meta.url),'utf8');
test('shared action dock is independent of icon fonts and retains accessible names',()=>{
  assert.doesNotMatch(source,/symbol\(|ps-material|Material Symbols Rounded/);
  assert.equal((source.match(/className="ps-vector(?: ps-chevron)?"[^>]*aria-hidden="true" focusable="false"/g)||[]).length,10);
  assert.match(source,/aria-label=\{ \x60Contribute \$\{CONTRIBUTION_AMOUNT_LABEL\}\x60 \}/);
  assert.match(source,/aria-label="Subscribe on WhatsApp"/);
  assert.match(source,/aria-label=\{ label === 'Share' \? 'Share this page' : label \}/);
  assert.match(source,/href=\{ CUSTOMER_MENU_HREFS\.contribute \}/);
  assert.match(source,/Review, then pay on website/);
  assert.match(source,/\.ps-tip\{[^}]*visibility:hidden/);
  assert.match(source,/\.ps-kicker\{min-width:0;box-sizing:border-box;padding-inline:8px;overflow-wrap:anywhere\}/);
});
