'use strict';

/**
 * Fail the build if .gitignore would mask a protected tracked directory.
 *
 * On 2026-11-02 an edit added bare `.github/` and `.kiro/` to .gitignore. That
 * does not un-track already-committed files (tracking overrides .gitignore), so
 * `git check-ignore` stays quiet — which is exactly why the mistake was easy to
 * miss. The real damage is future: a new `.github/workflows/ci.yml` or
 * `.kiro/hooks/x.json` would be silently ignored and never committed.
 *
 * So this guard probes the FUTURE: for each protected directory it asks
 * `git check-ignore` about a hypothetical new child path. If a new file there
 * would be ignored, the directory is being masked and the build fails. The
 * repo's intentional `.kiro/*` + `!.kiro/steering/` pattern is respected,
 * because git resolves the `!` re-include: a new steering file is NOT ignored,
 * so that healthy pattern passes.
 *
 * Runs offline as an npm/Amplify prebuild check. No network, no AWS, no writes.
 */
const path = require('node:path');
const { execSync, spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');

// Representative NEW child paths that must stay committable, chosen to match
// THIS repo's tracking policy, not an invented one: `.github/` is tracked in
// full, and `.kiro/` is ignored EXCEPT steering (the `.kiro/*` + `!.kiro/
// steering/` pattern). We therefore protect `.github/*` and `.kiro/steering/*`.
// We intentionally do NOT probe `.kiro/hooks` or `.kiro/agents`: the repo
// deliberately keeps those local, and flagging them would invent a new rule.
const PROTECTED_PROBES = [
  '.github/workflows/__guard_probe__.yml',
  '.github/__guard_probe__.yml',
  '.kiro/steering/__guard_probe__.md',
];

function isGitTree() {
  const r = spawnSync('git', ['rev-parse', '--is-inside-work-tree'], { cwd: root });
  return r.status === 0;
}

if (!isGitTree()) {
  console.log('gitignore safety guard: not a git tree, skipping');
  process.exit(0);
}

const failures = [];

for (const probe of PROTECTED_PROBES) {
  // check-ignore exits 0 and prints the path when it WOULD be ignored,
  // exits 1 when it would be tracked. We want all probes to be trackable.
  const r = spawnSync('git', ['check-ignore', '-q', '--', probe], { cwd: root });
  if (r.status === 0) {
    // Find the offending rule for a precise message.
    let rule = '(unknown rule)';
    try {
      rule = execSync(`git check-ignore -v -- '${probe}'`, { cwd: root, encoding: 'utf8' }).trim();
    } catch { /* ignore */ }
    failures.push(
      `A new file at "${probe}" would be IGNORED by .gitignore, masking a ` +
      `protected directory (CI workflows / steering / hooks / agents). ` +
      `Offending rule: ${rule}. Remove the bare directory ignore, or add a ` +
      `"!" re-include that covers this path.`
    );
  }
}

if (failures.length) {
  console.error('gitignore safety guard FAILED:\n' + failures.map(x => ' - ' + x).join('\n'));
  process.exit(1);
}
console.log('gitignore safety guard passed: protected directories stay committable');
