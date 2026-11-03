'use strict';

/**
 * Script-reference audit. Answers "which scripts are referenced, and which are
 * not" as a repeatable report instead of a manual guess.
 *
 * For every tracked file under scripts/, it counts inbound references across
 * the whole tracked tree (build config, package.json, source, docs and OTHER
 * scripts), matching both the basename and, for python, the module stem used
 * by `import` / `subprocess` / `-m`.
 *
 * CRITICAL HONESTY RULE baked in: a zero-reference script is NOT automatically
 * dead. Operational tools (deploy_*, backup_*, provision_*, audit_*, check_*,
 * verify_*, reconcile_*, restore_*, migrate_*, remediate_*, etc.) are invoked
 * by hand by an operator and are EXPECTED to have no inbound code reference.
 * The report therefore separates:
 *   - WIRED:        referenced by build/package/code
 *   - OPERATIONAL:  zero-ref but name matches a known operational verb -> KEEP
 *   - REVIEW:       zero-ref and NOT operational -> candidate, needs a human
 * Nothing is deleted. This only prints a table (and JSON with --json).
 *
 * Usage:
 *   node scripts/audit_script_references.cjs
 *   node scripts/audit_script_references.cjs --json > /tmp/script-audit.json
 *
 * Offline. No network, no AWS, no writes to the repo.
 */
const fs = require('node:fs');
const path = require('node:path');
const { execSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const asJson = process.argv.includes('--json');

function tracked(patterns) {
  const out = execSync(`git ls-files ${patterns}`, { cwd: root, encoding: 'utf8' });
  return out.split('\n').map(s => s.trim()).filter(Boolean);
}

const scripts = tracked('scripts/');
// Corpus = all tracked files except vendored / generated trees.
const corpus = tracked('')
  .filter(p => !p.startsWith('node_modules/'))
  .filter(p => !p.startsWith('amplify/node_modules/'));

// Operational verbs: a zero-ref match here is a manual tool, not dead code.
const OPERATIONAL = /(^|[_/-])(deploy|backup|restore|provision|audit|check|verify|reconcile|migrate|remediate|refresh|protect|configure|enable|scope|smoke|seed|sync|backfill|report|triage|export|update|rotate|scrub|bootstrap|retire|remove)([_/.-]|$)/i;

// Read every corpus file once.
const corpusText = new Map();
for (const p of corpus) {
  try { corpusText.set(p, fs.readFileSync(path.join(root, p), 'utf8')); }
  catch { /* binary or unreadable: skip */ }
}

function referencesTo(scriptPath) {
  const base = path.basename(scriptPath);
  const stem = base.replace(/\.[^.]+$/, '');
  const hits = [];
  for (const [p, text] of corpusText) {
    if (p === scriptPath) continue;
    // Match the full basename, OR a python module import/-m of the stem.
    if (text.includes(base)
        || new RegExp(`\\b(import|from)\\s+${stem}\\b`).test(text)
        || text.includes(`-m ${stem}`)
        || text.includes(`${stem}.py`)) {
      hits.push(p);
    }
  }
  return hits;
}

const rows = [];
for (const s of scripts) {
  const refs = referencesTo(s);
  let bucket;
  if (refs.length > 0) bucket = 'WIRED';
  else if (OPERATIONAL.test(path.basename(s))) bucket = 'OPERATIONAL';
  else bucket = 'REVIEW';
  rows.push({ script: s, refs: refs.length, bucket, referencedBy: refs.slice(0, 4) });
}

const by = b => rows.filter(r => r.bucket === b);
const summary = {
  total: rows.length,
  wired: by('WIRED').length,
  operational: by('OPERATIONAL').length,
  review: by('REVIEW').length,
};

if (asJson) {
  process.stdout.write(JSON.stringify({ summary, rows }, null, 2) + '\n');
} else {
  console.log('Script-reference audit');
  console.log('======================');
  console.log(`total=${summary.total}  wired=${summary.wired}  operational=${summary.operational}  review=${summary.review}`);
  console.log('\nREVIEW (zero-ref, NOT an operational verb — human must confirm before any delete):');
  const review = by('REVIEW').sort((a, b) => a.script.localeCompare(b.script));
  if (!review.length) console.log('  (none)');
  for (const r of review) console.log('  - ' + r.script);
  console.log('\nNote: WIRED and OPERATIONAL scripts are retained. A zero-reference');
  console.log('operational tool (deploy/backup/provision/...) is invoked by hand and');
  console.log('is expected to have no inbound reference. Never mass-delete on ref count.');
}
