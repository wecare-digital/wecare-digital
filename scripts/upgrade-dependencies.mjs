import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// Read the authoritative web manifest; never recreate a retired hard-coded list.
const root = fileURLToPath(new URL('../', import.meta.url));
const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
const args = process.argv.slice(2);
if (args.some(arg => arg !== '--apply')) throw new Error('Only --apply is supported; default is a read-only plan');
const plan = ['dependencies', 'devDependencies'].map(group => ({
  group,
  packages: Object.entries(manifest[group] ?? {})
    .filter(([, version]) => !/^(file:|link:|workspace:|git|https?:)/.test(version))
    .map(([name]) => `${name}@latest`),
}));
console.log(JSON.stringify({ installRoot: root, plan }, null, 2));
if (args.includes('--apply')) {
  for (const { group, packages } of plan) {
    if (!packages.length) continue;
    const flag = group === 'devDependencies' ? '--save-dev' : '--save';
    const result = spawnSync('npm', ['install', flag, '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund', ...packages], { cwd: root, stdio: 'inherit' });
    if (result.error) throw result.error;
    if (result.status !== 0) process.exit(result.status ?? 1);
  }
}
