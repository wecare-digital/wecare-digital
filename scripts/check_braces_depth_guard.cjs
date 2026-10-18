'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
let copies = 0;
for (const lockfile of ['package-lock.json', 'amplify/package-lock.json']) {
  const base = path.dirname(path.join(root, lockfile));
  const lock = JSON.parse(fs.readFileSync(path.join(root, lockfile), 'utf8'));
  for (const name of Object.keys(lock.packages).filter(name => name.endsWith('/braces'))) {
    const directory = path.join(base, name);
    if (!fs.existsSync(directory)) continue;
    const braces = require(directory);
    assert.deepEqual(braces.expand('a/{b,c}/file.{js,ts}'),
      ['a/b/file.js', 'a/b/file.ts', 'a/c/file.js', 'a/c/file.ts']);
    assert.deepEqual(braces.expand('file{01..03}'), ['file01', 'file02', 'file03']);
    assert.equal(braces.compile('a/{b,c}'), 'a/(b|c)');
    for (const pattern of ['{'.repeat(4500) + 'a,b' + '}'.repeat(4500),
                           '('.repeat(4500) + 'a' + ')'.repeat(4500)]) {
      for (const run of [braces, braces.parse, braces.compile, braces.expand, braces.stringify]) {
        assert.throws(() => run(pattern), error => error instanceof SyntaxError &&
          error.message.includes('nesting exceeds'));
      }
    }
    copies++;
  }
}
assert.ok(copies > 0, 'No installed braces package tested');
console.log('PASS: normal glob behavior and bounded recursion for ' + copies + ' braces copies');
