'use strict';

// Local mitigation for GHSA-vfj7-8cjw-p6xm until an upstream patch is available.
// Keep the original package version and alert visible; patch only the reviewed parser.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const pristineSha = 'e572166565f15fa6ad9865ae49d678218e32aabfd1b3720f6d0d43d39800d310';
const anchor = '  const push = node => {\n';
const marker = '    // WECARE braces container-depth guard (GHSA-vfj7-8cjw-p6xm).\n';
const guard = marker +
  '    if (node.nodes && stack.length >= 100) {\n' +
  "      throw new SyntaxError('Brace pattern nesting exceeds the supported depth of 100');\n" +
  '    }\n';
const checkOnly = process.argv.includes('--check');
let checked = 0;
for (const lockfile of ['package-lock.json', 'amplify/package-lock.json']) {
  const base = path.dirname(path.join(root, lockfile));
  const lock = JSON.parse(fs.readFileSync(path.join(root, lockfile), 'utf8'));
  for (const [relative, meta] of Object.entries(lock.packages)) {
    if (!relative.endsWith('/braces')) continue;
    const directory = path.join(base, relative);
    if (!fs.existsSync(directory)) continue;
    const installed = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'));
    if (meta.version !== '3.0.3' || installed.version !== '3.0.3') {
      throw new Error('Review the braces mitigation against the changed package version');
    }
    const parser = path.join(directory, 'lib/parse.js');
    const source = fs.readFileSync(parser, 'utf8');
    const hash = crypto.createHash('sha256').update(source).digest('hex');
    if (source.includes(marker)) {
      const restored = source.replace(guard, '');
      if (crypto.createHash('sha256').update(restored).digest('hex') !== pristineSha) {
        throw new Error('Patched braces parser differs from the reviewed source');
      }
    } else {
      if (checkOnly) throw new Error('The installed braces depth guard is missing');
      if (hash !== pristineSha || source.split(anchor).length !== 2) {
        throw new Error('Refusing to modify an unreviewed braces parser');
      }
      fs.writeFileSync(parser, source.replace(anchor, anchor + guard));
    }
    checked++;
    console.log('Verified braces depth guard: ' + path.relative(root, directory));
  }
}
if (!checked) throw new Error('No installed braces package was available to verify');
