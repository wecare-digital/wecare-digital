'use strict';

// Run adversarial cases in a bounded process so a missing mitigation cannot hang CI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
let copies = 0;
for (const lockfile of ['package-lock.json', 'amplify/package-lock.json']) {
  const base = path.dirname(path.join(root, lockfile));
  const lock = JSON.parse(fs.readFileSync(path.join(root, lockfile), 'utf8'));
  for (const [relative, meta] of Object.entries(lock.packages)) {
    if (!relative.endsWith('/minimatch')) continue;
    const directory = path.join(base, relative);
    if (!fs.existsSync(directory)) continue;
    const major = Number(meta.version.split('.')[0]);
    const probe = `
      const assert = require('node:assert/strict');
      const mm = require(${JSON.stringify(directory)});
      const match = typeof mm === 'function' ? mm : mm.minimatch;
      assert.equal(match('src/file.tsx', '**/*.tsx'), true);
      assert.equal(match('src/file.py', '**/*.tsx'), false);
      if (${major} >= 9) {
        const limited = new mm.Minimatch(Array(30).fill('**/../a/b').join('/'),
          {optimizationLevel: 2, braceExpandMax: 64});
        assert.equal(limited.set.length, 64);
        const large = new mm.Minimatch('{x,*}/{0..999}', {optimizationLevel: 2});
        assert.equal(large.set.length, 2000);
        assert.equal(large.match('y/999'), true);
      }
    `;
    const result = spawnSync(process.execPath, ['-e', probe], {timeout: 8000, encoding: 'utf8'});
    assert.equal(result.status, 0, directory + ': ' + (result.error || result.stderr));
    copies++;
  }
}
assert.ok(copies > 0, 'No installed minimatch copies tested');
console.log('PASS: matching compatibility and bounded preprocessing for ' + copies + ' minimatch copies');
