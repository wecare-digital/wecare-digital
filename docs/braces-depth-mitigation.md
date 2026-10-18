# Braces recursion mitigation

The upstream advisory [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
still lists braces through 3.0.3 with no patched release. Keep the alert open. A locally
mitigated installation is not an upstream-fixed package, and the version is not relabeled.

Both install roots use `scripts/guard_braces_depth.cjs` in postinstall. It applies a small,
reviewed parser guard to every braces installation named in the two committed lockfiles.
The guard rejects patterns with 100 nested AST containers before recursive compilation or
expansion. It covers both brace and parenthesis containers and preserves ordinary glob
behavior. It does not claim to bound every possible expensive regular expression or the
size of an expansion; callers must still avoid accepting arbitrary customer glob patterns.

The patch accepts only braces 3.0.3 with the original parse.js SHA-256
`e572166565f15fa6ad9865ae49d678218e32aabfd1b3720f6d0d43d39800d310`.
An already-patched parser is checked by removing the exact guard and verifying that same
hash. Unexpected source or version changes fail rather than receiving a speculative patch.
The MIT-licensed installed package otherwise remains intact. No third-party fork is fetched.

Build and Amplify npm entry points verify the guard. CI repeats verification and exercises
normal glob compilation/ranges plus 4,500-level brace and parenthesis patterns across parse,
compile, expand, stringify and the main API. Reapplying the patch is idempotent. Backend CI
uses `--ignore-scripts` for dependency installation and explicitly runs the patch afterward.

After any intentional install with `--ignore-scripts`, run:

```sh
node scripts/guard_braces_depth.cjs
node scripts/guard_braces_depth.cjs --check
node scripts/check_braces_depth_guard.cjs
```

Do not expose arbitrary manually constructed AST objects to braces: those bypass its parser.
The application source has no direct braces/micromatch/fast-glob imports; current use is
transitive tooling. `scripts/check_braces_advisory.py --check-upstream` reports when an
upstream patch becomes available. Review that release, replace the mitigation deliberately,
and update the pinned hash and tests rather than suppressing the advisory.
