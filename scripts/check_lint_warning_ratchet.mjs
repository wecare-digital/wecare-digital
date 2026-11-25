// Keep ESLint errors blocking, and prevent new warning debt without requiring
// unrelated cleanup. Run with --prune after fixing warnings; this can only
// reduce the committed budget, never approve new warnings.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { ESLint } from 'eslint';

const root = fileURLToPath( new URL( '..', import.meta.url ) );
const budgetPath = 'config/eslint-warning-budget.json';
const budgetFile = path.join( root, budgetPath );

export function warningBudget( results, cwd ) {
  const counts = new Map();
  for ( const result of results ) {
    const file = path.relative( cwd, result.filePath ).split( path.sep ).join( '/' );
    for ( const message of result.messages ) {
      if ( message.severity !== 1 ) continue;
      const rule = message.ruleId ?? '<unattributed>';
      if ( !counts.has( file ) ) counts.set( file, new Map() );
      const rules = counts.get( file );
      rules.set( rule, ( rules.get( rule ) ?? 0 ) + 1 );
    }
  }
  const sortedObject = map => Object.fromEntries( [ ...map.keys() ].sort().map( key => [ key, map.get( key ) ] ) );
  return sortedObject( new Map( [ ...counts ].map( ( [ file, rules ] ) => [ file, sortedObject( rules ) ] ) ) );
}

export function compareBudgets( baseline, current ) {
  const increased = [];
  const decreased = [];
  const files = new Set( [ ...Object.keys( baseline ), ...Object.keys( current ) ] );
  for ( const file of [ ...files ].sort() ) {
    const before = baseline[ file ] ?? {};
    const after = current[ file ] ?? {};
    const rules = new Set( [ ...Object.keys( before ), ...Object.keys( after ) ] );
    for ( const rule of [ ...rules ].sort() ) {
      const previous = before[ rule ] ?? 0;
      const observed = after[ rule ] ?? 0;
      if ( observed === previous ) continue;
      const change = { file, rule, previous, observed };
      ( observed > previous ? increased : decreased ).push( change );
    }
  }
  return { increased, decreased };
}

export function formatBudget( budget ) {
  return '{\n' + Object.entries( budget ).map(
    ( [ file, rules ] ) => '  ' + JSON.stringify( file ) + ': ' + JSON.stringify( rules ),
  ).join( ',\n' ) + '\n}\n';
}

export function readCommittedBudget( cwd, sha ) {
  if ( !/^[a-f0-9]{40}$/.test( sha ) ) throw new Error( 'Expected a full Git base commit SHA' );
  const git = ( ...args ) => execFileSync( 'git', args, { cwd, encoding: 'utf8' } );
  // An unavailable base is an error, not an invitation to initialize a new budget.
  if ( !git( 'ls-tree', sha, '--', budgetPath ).trim() ) return null;
  return JSON.parse( git( 'show', `${sha}:${budgetPath}` ) );
}

async function main( args ) {
  if ( args.length > 1 || ( args.length === 1 && args[ 0 ] !== '--prune' ) ) {
    throw new Error( 'Usage: node scripts/check_lint_warning_ratchet.mjs [--prune]' );
  }
  const baseline = JSON.parse( await fs.readFile( budgetFile, 'utf8' ) );
  const baseSha = process.env.WECARE_LINT_BASE_SHA;
  if ( process.env.GITHUB_ACTIONS === 'true' && process.env.GITHUB_EVENT_NAME === 'pull_request' && !baseSha ) {
    throw new Error( 'GitHub pull request CI requires the base commit SHA for the warning budget' );
  }
  const describe = ( { file, rule, previous, observed } ) => `${file}: ${rule} ${previous} -> ${observed}`;
  if ( baseSha ) {
    const committed = readCommittedBudget( root, baseSha );
    if ( committed ) {
      const increased = compareBudgets( committed, baseline ).increased;
      if ( increased.length ) {
        console.error( 'A pull request may not raise the base branch warning budget:\n' + increased.map( describe ).join( '\n' ) );
        return 1;
      }
    } else {
      console.log( 'Base commit has no warning budget; checking first adoption against the PR baseline.' );
    }
  }
  const eslint = new ESLint( { cwd: root } );
  const results = await eslint.lintFiles( [ '.' ] );
  const formatter = await eslint.loadFormatter( 'stylish' );
  const messages = formatter.format( results );
  if ( messages ) console.log( messages );
  if ( results.some( result => result.errorCount > 0 ) ) return 1;

  const current = warningBudget( results, root );
  const { increased, decreased } = compareBudgets( baseline, current );

  if ( increased.length > 0 ) {
    console.error( 'New ESLint warning debt (fix it without raising the budget):\n' + increased.map( describe ).join( '\n' ) );
    return 1;
  }
  if ( decreased.length > 0 ) {
    if ( args[ 0 ] === '--prune' ) {
      await fs.writeFile( budgetFile, formatBudget( current ), 'utf8' );
      console.log( `Pruned ${decreased.length} lint warning budget entries.` );
      return 0;
    }
    console.warn( 'Warnings decreased. Run node scripts/check_lint_warning_ratchet.mjs --prune and commit the lower budget.\n' + decreased.map( describe ).join( '\n' ) );
    return 0;
  }
  console.log( 'ESLint warning budget matched; no new warning debt.' );
  return 0;
}

if ( process.argv[ 1 ] && import.meta.url === pathToFileURL( process.argv[ 1 ] ).href ) {
  try {
    process.exitCode = await main( process.argv.slice( 2 ) );
  } catch ( error ) {
    console.error( error );
    process.exitCode = 1;
  }
}
