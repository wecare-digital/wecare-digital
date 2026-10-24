'use strict';

/**
 * branchstate - is it safe to push to this branch, and is anything actually unmerged?
 *
 * WHY THIS EXISTS. Three times in one session (#82, #83, #88) work was pushed to a branch whose
 * pull request had ALREADY been squash-merged. Every push succeeded, every push was a no-op, and
 * the owner reported "I cannot see the change" each time.
 *
 * THE TRAP IS SQUASH-MERGE PLUS `git log`. A squash merge replays the branch as ONE NEW COMMIT with
 * a new SHA, so the original commits are not ancestors of the default branch. `git log wecare.digital..HEAD`
 * therefore lists them as unmerged - truthfully, by SHA - while their content is already in. Every
 * time, the answer looked like "four commits still to land" when the real answer was "one".
 *
 * SO THIS CHECKS CONTENT, NOT COMMITS. `git diff wecare.digital...HEAD` is the question that matters: does
 * this branch change anything relative to the default branch? If the diff is empty, there is
 * nothing to push no matter what the log says. Reporting both side by side is deliberate - seeing
 * "7 commits ahead, 0 files differing" is what makes the trap obvious.
 *
 * AND IT ASKS GITHUB WHETHER THE PR IS CLOSED. The other half of the failure: a merged PR's branch
 * must not be reused, because a push to it neither reopens the PR nor reaches the default branch.
 * gh is optional here - without it the content check still works, which matters because the content
 * check is the load-bearing one.
 *
 * Run: node tools/audit/branchstate.js
 * Exit 1 when pushing would be pointless or wrong, so it can gate a pre-push hook.
 */

const { execSync } = require( 'child_process' );

const sh = ( cmd, allowFail = false ) => {
  try {
    return execSync( cmd, { stdio: [ 'ignore', 'pipe', 'ignore' ] } ).toString().trim();
  } catch ( error ) {
    if ( allowFail ) return '';
    throw error;
  }
};

const results = [];
const ok = ( name, detail ) => results.push( { pass: true, name, detail } );
const bad = ( name, detail ) => results.push( { pass: false, name, detail } );
const note = ( name, detail ) => results.push( { note: true, name, detail } );

const branch = sh( 'git branch --show-current' );
if ( !branch ) {
  console.error( 'Detached HEAD - check out a branch first.' );
  process.exit( 2 );
}

/* The default branch, asked for rather than assumed: this repo uses `wecare.digital`, not `main`. */
const base = sh( 'git symbolic-ref --short refs/remotes/origin/HEAD', true ).replace( /^origin\//, '' )
  || ( sh( 'git rev-parse --verify origin/wecare.digital', true ) ? 'wecare.digital' : 'main' );

note( 'branch', branch );
note( 'default branch', base );

if ( branch === base ) {
  bad( 'not on the default branch', `you are on ${base} - commit to a branch and open a PR instead` );
  report();
}

sh( `git fetch -q origin ${base}`, true );

/* ---------- the load-bearing check: does this branch change anything? ---------- */

const commitsAhead = Number( sh( `git rev-list --count origin/${base}..HEAD`, true ) || '0' );

/*
 * COMPARE THE FILES' CONTENT AGAINST THE BASE'S CURRENT TREE, and note carefully that the obvious
 * way does not work. `git diff base...HEAD` uses the MERGE BASE, and a squash-merged branch's
 * commit is not an ancestor of the base - so that diff happily reports the branch's changes as
 * outstanding even though identical content is already merged. Tested here on a branch whose PR had
 * been merged: three-dot said 6 files differing, which is exactly the false reassurance this tool
 * was written to eliminate.
 *
 * The honest question is per file: does the base's CURRENT version already match this branch's
 * version? Comparing blob hashes answers it regardless of how the merge was performed.
 */
const touched = ( sh( `git diff --name-only origin/${base}...HEAD`, true ) || '' )
  .split( '\n' ).filter( Boolean );

const stillDifferent = touched.filter( file => {
  const mine = sh( `git rev-parse "HEAD:${file}"`, true );
  const theirs = sh( `git rev-parse "origin/${base}:${file}"`, true );
  // No blob on either side means added or deleted - a real difference either way.
  if ( !mine || !theirs ) return true;
  return mine !== theirs;
} );

note( 'commits ahead of ' + base, String( commitsAhead ) );
note( 'files this branch touches', String( touched.length ) );
note( 'of those, still differing', String( stillDifferent.length ) );

if ( touched.length > 0 && stillDifferent.length === 0 ) {
  bad( 'this branch has something to contribute',
    `${commitsAhead} commit(s) ahead and ${touched.length} file(s) touched, but every one already MATCHES ${base} - the content is merged, almost certainly by squash, and the commits only look outstanding because the SHAs differ. Pushing achieves nothing. Branch off origin/${base}.` );
} else if ( touched.length === 0 ) {
  bad( 'this branch has something to contribute', `no difference from ${base}` );
} else {
  ok( 'this branch has something to contribute',
    `${stillDifferent.length} of ${touched.length} touched file(s) genuinely differ: ${stillDifferent.slice( 0, 3 ).join( ', ' )}${stillDifferent.length > 3 ? ' …' : ''}` );
}

/* Uncommitted work is the other way a push silently omits something. */
const dirty = sh( 'git status --porcelain', true );
if ( dirty ) {
  const n = dirty.split( '\n' ).filter( Boolean ).length;
  bad( 'working tree is committed', `${n} uncommitted change(s) - these will NOT be pushed` );
} else {
  ok( 'working tree is committed', 'clean' );
}

/* ---------- has this branch's PR already closed? ---------- */

/*
 * STRIP .git BEFORE splitting owner/repo. Doing both in one regex with an optional (?:\.git)? group
 * silently kept the suffix, so every API call 404'd - and because the failure was swallowed, this
 * check reported "no pull request found for it yet" and PASSED. A check that cannot distinguish an
 * API error from a real answer is worse than no check, and that is precisely the class of bug this
 * whole file exists to eliminate. Two steps instead.
 */
const originUrl = sh( 'git remote get-url origin', true ).replace( /\.git$/, '' );
const repo = ( originUrl.match( /([^/:]+\/[^/]+)$/ ) || [] )[ 1 ];
const ghAvailable = Boolean( sh( 'command -v gh', true ) );

if ( !ghAvailable || !repo ) {
  note( 'pull request state', 'gh unavailable - content check above still applies' );
} else {
  /*
   * Distinguish THREE outcomes, not two: an answer, an empty answer, and a failed call. The command
   * is run without allowFail so a non-zero exit is caught here rather than collapsing into "".
   */
  let raw = null;
  let queryFailed = false;
  try {
    raw = sh( `gh api "repos/${repo}/pulls?head=${repo.split( '/' )[ 0 ]}:${branch}&state=all&per_page=5" --jq '.[] | "\\(.number) \\(.state) \\(.merged_at // "-")"'` );
  } catch {
    queryFailed = true;
  }

  if ( queryFailed ) {
    bad( 'no closed PR blocks this branch', 'could not query GitHub - this check could not run, so do not read its silence as a pass' );
  } else if ( !raw ) {
    ok( 'no closed PR blocks this branch', 'no pull request found for it yet' );
  } else {
    const rows = raw.split( '\n' ).map( line => {
      const [ number, state, merged ] = line.split( ' ' );
      return { number, state, merged: merged !== '-' };
    } );
    const merged = rows.filter( r => r.merged );
    const open = rows.filter( r => r.state === 'open' );
    if ( merged.length ) {
      bad( 'no closed PR blocks this branch',
        `PR #${merged[ 0 ].number} for this branch is ALREADY MERGED. A push here will not reopen it and will not reach ${base}. Branch off origin/${base} and open a new PR.` );
    } else if ( open.length ) {
      ok( 'no closed PR blocks this branch', `PR #${open[ 0 ].number} is open - pushing updates it` );
    } else {
      bad( 'no closed PR blocks this branch', `PR #${rows[ 0 ].number} is closed unmerged - reopen it or start a new branch` );
    }
  }
}

report();

function report() {
  console.log( '' );
  for ( const r of results ) {
    const tag = r.note ? 'note' : r.pass ? 'ok  ' : 'FAIL';
    console.log( `  ${tag}  ${r.name.padEnd( 38 )} ${r.detail}` );
  }
  const fails = results.filter( r => r.pass === false ).length;
  console.log( fails ? `\n${fails} reason(s) not to push\n` : '\nok: safe to push\n' );
  process.exit( fails ? 1 : 0 );
}
