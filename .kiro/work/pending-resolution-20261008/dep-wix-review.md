# Review gate — Wix catalogue sync refusal and the five Dependabot alerts

The diagnose-and-fix pass produced one commit, `79ad7ef3`, containing only
`.kiro/work/pending-resolution-20261008/dep-wix-findings.md`. No source file, workflow, manifest
or lockfile was touched by this pass; the single code-level fix in scope (handlebars 4.7.10
override) was landed by a concurrent session as `74a9d42d` and was install-verified here rather
than duplicated. Both diagnoses are evidence-backed to a concrete root-cause classification, the
hard safety invariants hold on inspection, and all three unresolvable items are parked with named
key-holders and literal unblock commands.

Watch for: the shared `amplify/node_modules` still has handlebars **4.7.9** on disk while both the
committed and working-tree locks say 4.7.10 (confirmed), so a local `ampx` run out of that tree
still loads the vulnerable copy until someone runs `npm install --prefix amplify`; and the Wix P1
stays red on a 6-hourly cron plus every webhook dispatch until the owner acts (confirmed), which
is correct fail-closed behaviour but accumulates failure noise that could mask a later genuine
auth break.

**Verdict**: APPROVED

## High-level view

The Wix diagnosis lands on a concrete classification — owner-side catalogue edit, not a defect.
Run `37859673823` is cited with the literal guard output (`removed=12 of 22`) and the twelve
slugs, and the decisive fact is that the fetch step in that *same* run succeeded with ten
fully-hydrated products, no `(HIDDEN)` marker and matching variant counts, which rules out the
credential, scope and visibility hypotheses from CI alone. A read-only `.scratch/` probe re-mints
the same visitor token and reproduces ten products; walking it at `limit=5` across two pages
shows the cursor loop terminating rather than truncating. Git history closes it: the same twelve
slugs arrived together in one automated sync (`11367306`, 9 → 21 products) and
`src/content/shop.ts` already names them as the Wix store template's demo products. The report
states its own evidentiary limit — a visitor token cannot distinguish deleted from hidden, so the
404s alone do not settle that, and the owner confirmation step covers both.

The guard-weakening prohibition was honored, and that is verifiable independently of the report's
assertion. `.github/workflows/catalogue-sync.yml` has exactly one commit in its entire history
(`0e6b1ab8`, which created it); nothing in `9d91c4e1..HEAD` touched it or the fetch/diff scripts.
The threshold is still `[ "$gone" -gt $(( before / 2 )) ]` with the step gated on
`inputs.allow_large_removal != true`, and the input is still `default: false`. No
override-style escape hatch was introduced anywhere.

The Dependabot analysis enumerates all five open alerts with package, severity, GHSA and CVE,
manifest path, vulnerable range and patched version, and classifies each. The BUILD-ONLY
classification rests on three independently checkable facts, all of which hold: first-party
amplify TypeScript declares only `Runtime.PYTHON_3_12` (two occurrences, zero `NODEJS_*`), there
are 81 `handler.py` files and zero `node_modules` trees under `amplify/functions`, and the root
lockfile carries zero `handlebars` and zero `@graphql-tools/utils` entries with its single
`braces` row marked `dev: true`. The report also pre-empts the obvious misread of GitHub's
`scope: runtime` label, which is derived from the amplify manifest and does not mean deployed
reach.

The handlebars fix is the only applied change. It is an in-range bump — the sole requirer asks
`^4.7.9`, which already admits 4.7.10 — so no consumer contract moves, and the committed lock at
HEAD resolves `node_modules/handlebars` to 4.7.10. Verification is recorded with commands and
outputs: lock-only resolution, a real 910-package install from the committed manifests,
`ampx 1.10.0` through `npm exec`, and repo gates at `118aa93e` (lint 0 errors, typecheck clean,
vitest 1581 passed / 11 skipped), all run in isolated `.scratch/` copies to avoid writing to the
foreign-modified shared lockfile. The fix had been committed by the other session without any
install verification, and the shared tree was still on 4.7.9 — this pass caught that gap.

The two remaining alerts are parked rather than forced.
`@graphql-tools/utils@12.0.1` would force three to six major jumps across consumers pinned at
`^6.0.18`, `^7.9.1` and `^9.x`, risking `ampx pipeline-deploy` — the tool that ships all 81 Python
Lambdas — to protect a codegen path serving zero live AppSync APIs (`list-graphql-apis` → `[]`).
`braces` has no patched release in existence: the advisory reports `first_patched_version: null`
and npm's latest is 3.0.3, inside the vulnerable range. Both record the exact override or the
exact re-check command, and name the key-holder (repo owner; upstream `micromatch/braces`).

Ownership discipline was kept. `amplify/package-lock.json` is still unstaged and unmodified by
this pass — it shows as ` M` in the working tree and does not appear in `79ad7ef3`, whose only
path is the findings doc. Its foreign delta was characterised as 91 added bundled-dependency rows
with zero version changes and no movement in any vulnerable package, so leaving it alone costs
nothing security-wise. `origin/stack` advanced only by pushes and fast-forwards across the whole
run, and every SHA the report cites (`9d91c4e1`, `74a9d42d`, `b5b6c588`, `7bd014b1`, `118aa93e`)
is an ancestor of HEAD — no rewrite. No secret value appears in the committed doc; `WIX_CLIENT_ID`
is referenced twice, by name only.

One judgment call is worth naming. The report proves that accepting this particular removal
changes `SHOP_PRODUCTS` by zero products and unpublishes zero pages, since `shop.ts` filters all
twelve slugs by id and by slug before `getStaticPaths` ever sees them — and it still declines to
teach the guard that exclusion, on the grounds that narrowing what a safety guard counts is itself
guard-weakening. It is recorded as an owner option rather than acted on, which is the reading the
prohibition demands.

<details>
<summary>Issues (4)</summary>

1. **Stale handlebars in the shared amplify install** (confirmed) — `amplify/node_modules/handlebars`
   is 4.7.9 on disk while both the committed and working-tree locks say 4.7.10, so a local `ampx`
   invocation from that tree still loads the vulnerable copy. Run `npm install --prefix amplify`
   (not `npm ci`) once the foreign lock delta is resolved by its owner. Non-blocking: CI and
   deploy install fresh.
2. **Wix sync stays red until the owner acts** (confirmed) — cron `25 */6 * * *` plus every webhook
   dispatch will keep failing (16 failures / 0 successes so far). Correct fail-closed behaviour and
   correctly parked, but the owner should execute the recorded step 1 → 2 promptly so sustained red
   does not mask a later genuine auth failure. Non-blocking.
3. **Deleted-vs-hidden not provable from a visitor token** (confirmed, already disclosed) — the
   404s cannot distinguish a deleted product from a hidden one. The unblock step already requires
   the owner to confirm in the Wix dashboard that the twelve are deleted and not merely hidden or
   in draft; keep that check mandatory rather than assumed. Non-blocking.
4. **Work-directory tracking is asymmetric** (confirmed) — `dep-wix-findings.md` is committed while
   `plan.md` in the same `pending-resolution-20261008/` directory is untracked. Decide one way for
   the directory so the parked-item record is not half in git. Non-blocking.

</details>

<details>
<summary>Details</summary>

### Guard integrity, verified independently of the report

The prohibition in the findings doc is an assertion; these are the checks behind accepting it.

```
git log --oneline 9d91c4e1..HEAD -- .github/workflows/catalogue-sync.yml \
    scripts/fetch-wix-catalog.js scripts/catalogue-diff.js \
    src/content/shop.ts src/content/wix-catalog.json
  -> (empty)

git log --oneline -- .github/workflows/catalogue-sync.yml
  -> 0e6b1ab8  feat(catalogue): sync the Wix catalogue ...   # the only commit, ever
```

Live text at HEAD:

```yaml
      allow_large_removal:
        description: 'Commit even if more than half the catalogue disappeared (see the guard)'
        type: boolean
        default: false
...
      - name: Refuse a mass disappearance
        if: steps.diff.outputs.changed == 'true' && inputs.allow_large_removal != true
...
          if [ "$gone" -gt $(( before / 2 )) ]; then
```

Threshold unchanged, gate unchanged, default still `false`, no new override input or env var. The
snapshot is also untouched — `src/content/wix-catalog.json` still reports `productCount: 22`,
`fetchedAt: 2026-10-06T04:43:35.265Z`, 22 rows — so the read-only probe did not write through.

### Reachability spot-checks

The BUILD-ONLY classification is the load-bearing claim for all five alerts, so each supporting
fact was re-checked rather than taken on the report's word:

```
amplify/*.ts first-party runtimes   -> lambda.Runtime.PYTHON_3_12  (seo-resources.ts:33,
                                                                    link-resources.ts:113)
                                       zero NODEJS_* declarations
find amplify/functions -name handler.py      -> 81
find amplify/functions -name node_modules    -> 0
root package-lock.json: "node_modules/handlebars"          -> 0 entries
                        "node_modules/@graphql-tools/utils" -> 0 entries
                        "node_modules/braces"               -> 1 entry, "dev": true
git show HEAD:amplify/package-lock.json      -> node_modules/handlebars 4.7.10
amplify/package.json                         -> overrides { ... "handlebars": "4.7.10" }
```

A Node advisory in a chain that is never installed into a Python Lambda bundle, never present in
the static-export web artifact, and absent from the root lockfile cannot reach production.

### Ownership and history invariants

```
git status --short                 ->  M amplify/package-lock.json      (unstaged, foreign)
git show --name-only 79ad7ef3      ->  .kiro/work/pending-resolution-20261008/dep-wix-findings.md
git rev-parse HEAD origin/stack    ->  79ad7ef3 == 79ad7ef3
git reflog show origin/stack       ->  pushes and fast-forwards only, no forced update
merge-base --is-ancestor           ->  9d91c4e1, 74a9d42d, b5b6c588, 7bd014b1, 118aa93e all yes
```

Exactly one path in the commit, so `git add .` was not used and the foreign lockfile was not
swept in. No secret-shaped string (`client_secret`, bearer token, `AKIA…`, JWT) appears in the
committed doc.

### The `npm ci` failure is not fallout from the handlebars bump

Worth separating so a later reader does not chase it: `npm ci` in `amplify/` fails with ~100
missing entries, and that is pre-existing and documented in `docs/npm-ci-backend-isolation.md` —
Amplify packages ship `inBundle` OpenTelemetry copies with mutually inconsistent
`@opentelemetry/core@2.0.0` pins. The supported path there is `npm install --prefix amplify`,
which is what the verification used and what succeeded. Unrelated to the override.

Confirmed on disk during this review: `amplify/node_modules/handlebars` reports `4.7.9` while both
the committed and working-tree locks resolve `4.7.10`.

</details>

<details>
<summary>File map</summary>

- `.kiro/work/pending-resolution-20261008/dep-wix-findings.md` — the pass's only commit
  (`79ad7ef3`), 533 lines: Wix root cause with CI/probe/git evidence, five-alert Dependabot table,
  reachability proof, verification log, parked items with key-holders.
- `amplify/package.json`, `amplify/package-lock.json` — handlebars `4.7.10` override and
  resolution, landed by the concurrent session in `74a9d42d`, verified here.
- `.github/workflows/catalogue-sync.yml`, `scripts/fetch-wix-catalog.js`,
  `scripts/catalogue-diff.js`, `src/content/shop.ts`, `src/content/wix-catalog.json` — inspected,
  deliberately unchanged.

Full diff: `git show 79ad7ef3`; fix under review: `git show 74a9d42d -- amplify/package.json amplify/package-lock.json`.

</details>
