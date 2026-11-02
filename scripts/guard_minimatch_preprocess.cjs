'use strict';

// GHSA-g3hv-75wg-m249: CDK bundles 10.2.6, which npm overrides cannot replace.
// Backport the maintainer's limits without changing package identity or hiding alerts.
// https://github.com/isaacs/minimatch/commit/77a0f5c4b80bdc641c3c930a1d9edf5ad2db57f8
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const checkOnly = process.argv.includes('--check');
const sha = source => crypto.createHash('sha256').update(source).digest('hex');
const reviewed = {
  'dist/commonjs/index.js': 'd224f71f20d7c206fcc5b7e9f747324c7698345a0b2c28d717dd9cf698306783',
  'dist/esm/index.js': '59821ec2ce0d3df968292036e5c831ad322b33e9c33a949ecbc9dfe125d165be',
};
const edits = [
  ['    firstPhasePreProcess(globParts) {\n',
    '        // WECARE upstream preprocessing limits (GHSA-g3hv-75wg-m249).\n' +
    '        const { braceExpandMax = 100_000 } = this.options;\n'],
  ["                        p2 === '..'",
    ' ||\n                        globParts.length >= braceExpandMax'],
  ['    secondPhasePreProcess(globParts) {\n',
    '        if (globParts.length > 1000) return globParts;\n'],
];
let checked = 0;
for (const lockfile of ['package-lock.json', 'amplify/package-lock.json']) {
  const base = path.dirname(path.join(root, lockfile));
  const lock = JSON.parse(fs.readFileSync(path.join(root, lockfile), 'utf8'));
  for (const [relative, meta] of Object.entries(lock.packages)) {
    if (!relative.endsWith('/minimatch')) continue;
    const directory = path.join(base, relative);
    if (!fs.existsSync(directory)) continue;
    const installed = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'));
    if (installed.version !== meta.version) throw new Error('Installed minimatch differs from lockfile');
    const major = Number(installed.version.split('.')[0]);
    if (major >= 11) {
      if (installed.version === '11.0.0') throw new Error('Unpatched minimatch 11.0.0');
    } else if (major < 9) {
      // These callable-API releases predate the vulnerable optimization feature.
      const source = fs.readFileSync(path.join(directory, 'minimatch.js'), 'utf8');
      if (/firstPhasePreProcess|optimizationLevel/.test(source)) {
        throw new Error('Legacy minimatch unexpectedly contains modern preprocessing; review required');
      }
    } else {
      if (installed.version !== '10.2.6') throw new Error('Review changed minimatch against upstream fix');
      for (const [file, pristineSha] of Object.entries(reviewed)) {
        const target = path.join(directory, file);
        const source = fs.readFileSync(target, 'utf8');
        let restored = source;
        const patched = source.includes(edits[0][1]);
        if (patched) {
          for (const [anchor, addition] of edits) {
            if (restored.split(anchor + addition).length !== 2) throw new Error('Incomplete minimatch mitigation');
            restored = restored.replace(anchor + addition, anchor);
          }
        }
        if (sha(restored) !== pristineSha) throw new Error('Refusing unreviewed minimatch source: ' + target);
        if (!patched) {
          if (checkOnly) throw new Error('Bundled minimatch preprocessing mitigation is missing');
          let output = source;
          for (const [anchor, addition] of edits) {
            if (output.split(anchor).length !== 2) throw new Error('Minimatch mitigation anchor changed');
            output = output.replace(anchor, anchor + addition);
          }
          fs.writeFileSync(target, output);
        }
      }
    }
    checked++;
    console.log('Verified minimatch preprocessing safety: ' + path.relative(root, directory));
  }
}
if (!checked) throw new Error('No installed minimatch package was available to verify');
