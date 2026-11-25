import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { compareBudgets, formatBudget, readCommittedBudget, warningBudget } from '../scripts/check_lint_warning_ratchet.mjs';

const cwd = process.cwd();
const report = ( file, messages ) => ( { filePath: path.join( cwd, file ), messages } );
const warning = ruleId => ( { severity: 1, ruleId } );

test( 'warnings are counted by relative file and rule, with stable ordering', () => {
  const results = [
    report( 'src/b.ts', [ warning( 'rule-b' ), warning( 'rule-a' ), warning( 'rule-b' ) ] ),
    report( 'src/a.ts', [ warning( null ), { severity: 2, ruleId: 'error-rule' } ] ),
  ];
  const budget = warningBudget( results, cwd );
  assert.deepEqual( budget, {
    'src/a.ts': { '<unattributed>': 1 },
    'src/b.ts': { 'rule-a': 1, 'rule-b': 2 },
  } );
  assert.equal( formatBudget( budget ),
    '{\n  "src/a.ts": {"<unattributed>":1},\n  "src/b.ts": {"rule-a":1,"rule-b":2}\n}\n' );
} );

test( 'removing an old warning does not buy capacity for another file or rule', () => {
  const baseline = { 'a.ts': { existing: 2, removed: 1 } };
  const current = { 'a.ts': { existing: 1, added: 1 }, 'b.ts': { existing: 1 } };
  assert.deepEqual( compareBudgets( baseline, current ), {
    increased: [
      { file: 'a.ts', rule: 'added', previous: 0, observed: 1 },
      { file: 'b.ts', rule: 'existing', previous: 0, observed: 1 },
    ],
    decreased: [
      { file: 'a.ts', rule: 'existing', previous: 2, observed: 1 },
      { file: 'a.ts', rule: 'removed', previous: 1, observed: 0 },
    ],
  } );
} );

test( 'only fully pruned budgets match after warning cleanup', () => {
  const baseline = { 'a.ts': { first: 2 }, 'old.ts': { second: 1 } };
  const cleaned = { 'a.ts': { first: 1 } };
  const comparison = compareBudgets( baseline, cleaned );
  assert.equal( comparison.increased.length, 0 );
  assert.equal( comparison.decreased.length, 2 );
  assert.deepEqual( compareBudgets( cleaned, cleaned ), { increased: [], decreased: [] } );
} );

test( 'a raised worktree budget cannot redefine the PR base allowance', t => {
  const repo = fs.mkdtempSync( path.join( os.tmpdir(), 'wecare-lint-base-' ) );
  t.after( () => fs.rmSync( repo, { recursive: true, force: true } ) );
  const git = ( ...args ) => execFileSync( 'git', args, { cwd: repo, encoding: 'utf8' } ).trim();
  const commit = () => git( '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
    'commit', '--allow-empty', '-qm', 'fixture' );
  git( 'init', '-q' );
  commit();
  const first = git( 'rev-parse', 'HEAD' );
  assert.equal( readCommittedBudget( repo, first ), null );
  fs.mkdirSync( path.join( repo, 'config' ) );
  const budget = path.join( repo, 'config', 'eslint-warning-budget.json' );
  fs.writeFileSync( budget, formatBudget( { 'a.ts': { example: 1 } } ) );
  git( 'add', 'config/eslint-warning-budget.json' );
  commit();
  const base = git( 'rev-parse', 'HEAD' );
  const raised = { 'a.ts': { example: 2 } };
  fs.writeFileSync( budget, formatBudget( raised ) );
  assert.deepEqual( compareBudgets( readCommittedBudget( repo, base ), raised ).increased,
    [ { file: 'a.ts', rule: 'example', previous: 1, observed: 2 } ] );
} );
