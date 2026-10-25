# Dependabot triage

Companion to `docs/security-codeql-triage.md`, and it exists for the same reason: a
dismissal without a recorded reason is indistinguishable from a dismissal without a thought,
and an alert left open with no note is indistinguishable from one nobody read.

Measured 2026-10-25 against `repos/wecare-digital/wecare-digital/dependabot/alerts?state=open`
(first measured 2026-09-30).

**Closed out 2026-10-25: 0 open alerts.** The three `brace-expansion` alerts are now genuinely
fixed, the one fixable copy of the new `zod` advisory was bumped, and 119/120 are dismissed with
recorded evidence and watched by `scripts/check_bundled_advisories.py`.

| # | Sev | Package | Vulnerable range | Manifest | Verdict |
|---:|---|---|---|---|---|
| 132 | HIGH | `zod` | `< 4.6.6` | `tools/browser/package-lock.json` | ✅ **FIXED** 2026-10-24 by another change |
| 125 | HIGH | `zod` | `< 4.6.6` | `package-lock.json` | ✅ **FIXED** 2026-10-25 — dev-only copy bumped 4.6.5 → 4.6.7 (GitHub had auto-dismissed it) |
| 120 | HIGH | `zod` | `< 4.6.6` | `amplify/package-lock.json` | ⛔ **DISMISSED `tolerable_risk`** — every copy 3.x, Amplify pins 3.25.17, watched by script |
| 119 | MEDIUM | `@opentelemetry/core` | `< 2.8.0` | `amplify/package-lock.json` | ⛔ **DISMISSED `inaccurate`** — lockfile-only entries; nothing below 2.8.0 installs, watched by script |
| 59 | MEDIUM | `oauthlib` | `>= 3.0.0, < 4.0.0` | `requirements-dev.txt` | ✅ **FIXED** — pinned to 4.0.0, closed by Dependabot 06:41:48Z |
| 58 | MEDIUM | `oauthlib` | `>= 0.6.1, <= 3.3.1` | `requirements-dev.txt` | ✅ **FIXED** — same bump |
| 57 | MEDIUM | `brace-expansion` | `>= 4.0.0, < 5.0.12` | `amplify/package-lock.json` | ✅ **FIXED** 2026-10-25 — `aws-cdk-lib` 2.274.0 bundles 5.0.12; dismissal undone |
| 56 | HIGH | `brace-expansion` | `>= 4.0.0, < 5.0.11` | `amplify/package-lock.json` | ✅ **FIXED** 2026-10-25 — same bump |
| 55 | HIGH | `brace-expansion` | `>= 4.0.0, < 5.0.10` | `amplify/package-lock.json` | ✅ **FIXED** 2026-10-25 — same bump |
| 23 | MEDIUM | `uuid` | `< 11.1.1` | `package-lock.json` | ⛔ **DISMISSED `not_used`** — vulnerable function never called |

## 120 / 125 / 132 — `zod`, one advisory in three lockfiles

GHSA-mrhx-c7xc-m3w5 (CVE-2023-54404): array parsing records an issue for every failing element
with no cap, so a huge array against an unbounded array schema can exhaust memory. Every release
before 4.6.6 is in range, the whole 3.x line included. Each lockfile needed a different answer:

| Alert | Lockfile | Copy | Answer |
|---|---|---|---|
| 132 | `tools/browser/package-lock.json` | — | already fixed 2026-10-24 |
| 125 | `package-lock.json` | 4.6.5, `dev`, via `eslint-config-next` → `eslint-plugin-react-hooks` | **bumped to 4.6.7.** GitHub's dev-scope rule had auto-dismissed it, but 4.6.6+ sits inside the plugin's `^3.25.0 \|\| ^4.0.0`, so it was fixable |
| 120 | `amplify/package-lock.json` | seven 3.x copies | **dismissed `tolerable_risk`**, below |

**125 is a three-line lockfile change, taken by hand on purpose.** `npm update zod` under the
pinned npm 11.6.2 resolved 4.6.7 but also rewrote an unrelated `peer` flag on
`eslint-plugin-import`, so only the `version` / `resolved` / `integrity` lines were kept.
Verified: a clean `npm ci` under npm 11.6.2 exits 0 without touching the lockfile, `npm ls zod`
shows 4.6.7 deduped under the plugin, and ESLint over `src/` from that install reports 0 errors
(208 warnings, the existing baseline).

**120 cannot be fixed here.**

- The only patched line is 4.x. Six Amplify packages, each already at its latest version,
  require zod **exactly** `3.25.17`: backend-cli 1.10.0, backend-output-schemas 1.8.0 (peer),
  cli-core 2.2.7, client-config 1.11.1, deployed-backend-client 1.8.3 and platform-core 1.12.1.
- `data-construct` and `graphql-api-construct` **bundle** their own 3.24.2 and 3.25.17 copies,
  read from the 1.17.7 / 1.22.2 tarballs and the latest 1.17.8 / 1.22.3. No `overrides` entry
  reaches a bundled copy; that is the lesson recorded under 55/56/57.
- Forcing 4.x through an override would hand the v4 API to code written against v3.

**The risk is tolerable, on reachability.**

- Nothing deployed contains it. Every Lambda is Python, and `amplify.yml` installs only the root
  lockfile. `amplify/` is a separate install root, used only when a developer runs `ampx`
  locally (see 55/56/57 and `docs/npm-ci-backend-isolation.md`).
- The schemas validate Amplify's own data: backend outputs, storage access definitions, bucket
  config and the CLI's notices manifest. None of it is request data from site visitors; the
  worst case is a crashed local CLI process.
- The `$ZodArray` / `handleArrayResult` code the advisory names exists in 3.25.17 only under the
  `zod/v4` subpath, and a clean install of the amplify lockfile has **zero** importers of
  `zod/v4` outside zod itself. That is deliberately not the dismissal reason: the v3 array
  parser collects issues the same way, and the advisory covers 3.x on purpose.

The watch fails its gate if a 4.x copy below 4.6.6 appears (a patch bump would fix that one) or
a copy appears that this triage never measured; `--check-upstream` reports when the Amplify
packages stop requiring 3.x.

## 119 — `@opentelemetry/core`, a copy that is never installed

GHSA-8988-4f7v-96qf (CVE-2026-54285): `W3CBaggagePropagator.extract()` did not cap inbound
`baggage` headers. Fixed in 2.8.0.

The lockfile lists four 2.0.0 copies, all `inBundle: true`:

```
node_modules/@aws-amplify/{data-construct,graphql-api-construct}/node_modules/
    @opentelemetry/{resources,sdk-trace-base}/node_modules/@opentelemetry/core
```

**None of them is installed, and none is in any tarball.**

- The 1.17.7 / 1.22.2 tarballs, and the latest 1.17.8 / 1.22.3, each contain exactly one core:
  `node_modules/@opentelemetry/core` **2.8.0**. Beside it, `resources` and `sdk-trace-base`
  2.0.0 declare `"@opentelemetry/core": "2.0.0"` and resolve upward to that 2.8.0 copy.
- A clean `npm ci` of the committed amplify lockfile installs core 2.8.0 (once per construct)
  and 2.11.0 (top level), nothing else. All four nested paths are absent on disk.
- The entries exist because `npm ci` demands a lockfile node for that exact `2.0.0` edge, the
  inconsistency recorded in `docs/npm-ci-backend-isolation.md`. Removing them breaks `npm ci`
  ("Missing: @opentelemetry/core@2.0.0 from lock file" ×4). A full `npm install` strips them and
  `npm install --package-lock-only` puts them back, byte-identical.
- Dependabot's own security update (`cbf45228`, titled "2.0.0 to 2.8.0") changed only `peer`
  flags. It could not move the entries either, and the alert stayed open.

`inaccurate` is exact: the alert describes a vulnerable copy that is recorded but never
installed. `not_used` would be wrong, because that reason is for installed code whose
vulnerable function is never called, and `tolerable_risk` would concede a risk that does not
exist. The watch fails its gate if a sub-2.8.0 copy appears anywhere else or one of the four
stops being `inBundle`, since either would be a real copy hidden by this dismissal.

## All four dismissals said `fix_started`, and that was wrong

Every one of these four was first dismissed with reason **`fix_started`** and **no comment**.
Both halves are defects, and the second is what this document exists to prevent.

`fix_started` asserts a fix is underway. For `brace-expansion` that is not merely inaccurate,
it is unachievable — the copy is bundled inside a tarball (below), so no amount of work here
produces a fix. For `uuid` it is equally false: `xcode` pins `uuid@^7`, so the copy will never
reach the patched 11.1.1. A reason that claims work is in progress on something nobody can fix
guarantees the next reader wastes time confirming it.

Corrected to the reasons in the table, each with an evidence comment naming this file. Verified
by read-back: 0 open, 0 remaining `fix_started`, all four carrying a comment.

**A dismissal is not free, and the cost is specific.** These were going to be left open so that
the eventual upstream fix would surface on its own. Dismissing removes that — a dismissed alert
cannot come back to tell you it became fixable. That is replaced by
`scripts/check_bundled_advisories.py`, described under 55/56/57.

## 55 / 56 / 57 — `brace-expansion`, and why an override does not work

**Fixed 2026-10-25.** The watch below did its job: `--check-upstream` reported that
`aws-cdk-lib` 2.274.0 bundles `brace-expansion` 5.0.12, which clears all three ranges. The pin in
`amplify/package.json` moved 2.270.0 → 2.274.0 (with `packages/config/vendorVersions.ts`), the
three dismissals were undone so Dependabot could close them as fixed, and the brace-expansion
watch was retired from the script.

Regenerating the backend lockfile needed the two-step this install root always needs. A full
`npm install` reads the new tarball's real bundle but strips the four lockfile-only
`@opentelemetry/core@2.0.0` entries (see 119), after which `npm ci` refuses. A follow-up
`npm install --package-lock-only` restores them byte-identical. Verified under the pinned npm
11.6.2: `npm ci` exits 0 and installs `aws-cdk-lib` 2.274.0 with bundled `brace-expansion`
5.0.12; `tsc --noEmit -p amplify/tsconfig.json` reports 0 errors before and after. No CDK synth
was run. The analysis below stays because its override lesson applies to every bundled
dependency.

The three alerts are one copy: `node_modules/aws-cdk-lib/node_modules/brace-expansion` at
**5.0.9**, reached through `aws-cdk-lib`'s bundled `minimatch`. The top-level
`node_modules/brace-expansion` is already 5.0.12 and clean.

**An npm `overrides` entry cannot fix this, and the attempt is recorded so nobody repeats
it.** Adding `"brace-expansion@5": "5.0.12"` to `amplify/package.json` and regenerating the
lockfile left the copy at 5.0.9 while churning the lockfile by 1537 lines. The reason is in
the lockfile itself:

```
node_modules/aws-cdk-lib
    bundleDependencies = [..., 'minimatch', ...]
node_modules/aws-cdk-lib/node_modules/brace-expansion
    version  = 5.0.9
    inBundle = True
```

`inBundle: True` means the code ships **inside the `aws-cdk-lib` tarball**. Overrides,
resolutions and manual lockfile edits all describe what npm should *fetch*; none of them
changes the contents of a tarball that has already been fetched. The override was reverted.

**Upgrading does not fix it either.** Both `aws-cdk-lib@2.270.0` (pinned here) and
`2.271.0` (latest at the time of measuring) bundle `brace-expansion@5.0.9` — confirmed by
downloading both tarballs and reading
`package/node_modules/brace-expansion/package.json`. The fix has to come from AWS
republishing `aws-cdk-lib` with a refreshed bundle.

### The `scope=runtime` label is misleading here, and this is the part worth knowing

Dependabot derives scope from `dependencies` versus `devDependencies`. `aws-cdk-lib` sits in
`dependencies` of `amplify/package.json`, so it reports **runtime**. It reaches no deployed
artifact:

- **Every Lambda function is `python3.12`** (65 zip-packaged plus one container). Measured
  via `list-functions --query 'Functions[].Runtime'`. A Node package cannot be inside a
  Python function zip, and `deploy_all_lambdas.py` bundles no third-party packages at all.
- **The Amplify build never installs it.** `amplify.yml` runs `npm ci` against the **root**
  lockfile, and `amplify/package.json` is deliberately a separate install root whose
  packages the root lockfile does not contain — see `docs/npm-ci-backend-isolation.md`.

So the copy exists only when a developer runs `npm install` inside `amplify/` to use
`ampx sandbox` or `ampx pipeline-deploy`. The advisories are ReDoS in a glob brace expander;
reaching it needs attacker-controlled glob patterns, and at CDK synth time the patterns come
from our own asset-bundling code.

**`not_used` would be the wrong reason, and `tolerable_risk` is the right one.** The code is
genuinely present in a manifest and genuinely installed whenever someone runs `npm install`
inside `amplify/` — unlike the `uuid` case below, where the vulnerable *function* is never
called. What makes it tolerable is reachability, not absence.

### They were dismissed, so a script did the noticing

The plan recorded here was to leave them open so the upstream fix would surface by itself. They
were dismissed instead, which is defensible on reachability but removes that mechanism
entirely: **a dismissed alert cannot come back to tell you it became fixable.**

`scripts/check_bundled_advisories.py` replaced it, and was better than what it replaced — an
open alert nags on every page load and gets tuned out, whereas this answers the actual question
on demand. It noticed the fix on 2026-10-25; the brace-expansion watch is retired and the script
now watches 119 and 120 with the same two modes:

```
python scripts/check_bundled_advisories.py --gate            # offline, CI-safe
python scripts/check_bundled_advisories.py --check-upstream  # is it fixable yet?
```

`--gate` reads the committed lockfile only and separates two things that must not be conflated:

- a **PROBLEM** is the reasoning above no longer holding — the copy stops being `inBundle` (so
  an `overrides` entry *would* now work), or a vulnerable copy appears under a different parent
  and is therefore **not** covered by this dismissal;
- a **NOTICE** is a fact having moved — a version bump, including the good one, which prints
  "CLEARS all three advisories" and tells you to undo the dismissal.

Getting that split wrong is how a gate ends up firing on routine upgrades and then switched
off. `tests/test_bundled_advisory_watch.py` asserted the split against doctored lockfiles until
the tests directory was retired (`c1f38b2b`). The 119/120 watches were checked the same way by
hand on 2026-10-25, against nine doctored lockfiles: every case that invalidates a dismissal
exits 1, and every version move that does not exits 0 with a notice.

`--check-upstream` read the newest `aws-cdk-lib` **tarball** rather than registry metadata,
because a bundled dependency does not appear in a package's declared dependency list — it is
simply inside the archive. Measured 2026-09-30: latest `2.271.0`, still bundles `5.0.9`,
`FIX AVAILABLE: False`. Measured 2026-10-25: latest `2.274.0` bundles `5.0.12`,
`FIX AVAILABLE: True`, and the pin moved.

## 23 — `uuid`, and what the earlier fix actually achieved

GHSA-w5hq-g745-h8pq affects `uuid` before 11.1.1 when a caller supplies its own output
buffer. The vulnerable copy is `node_modules/xcode/node_modules/uuid@7.0.3`, pulled in by
`@capacitor/cli` → `xcode`.

Two things were established and both still hold:

1. **Not reachable from our code.** Nothing under `src/` or `amplify/` imports `uuid` at
   all — zero hits. The separate top-level `node_modules/uuid` is already 11.1.1.
2. **Now correctly scoped.** `@capacitor/cli` was moved to `devDependencies`, and the
   lockfile confirms the effect: `node_modules/xcode/node_modules/uuid` is `dev=True`, so
   the alert reports `scope=development` rather than runtime.

It cannot be resolved by upgrading, because `xcode` requires `uuid@^7`, and native packaging
is **POST-PROJECT** per `.kiro/steering/00-current-owner-overrides.md` (retired 2026-10-09, af7858fa) — so the tool that
drags it in is not used in the current phase either.

### Dismissed `not_used` on owner instruction, and the evidence is sharper than "we don't import it"

Re-reading the advisory text closed this properly. GHSA-w5hq-g745-h8pq is *"Missing buffer
bounds check in **v3/v5/v6** when `buf` is provided"* — it is not "uuid is vulnerable", it is
three specific functions called with a caller-supplied buffer. So the question is not whether
`uuid` is present but whether anything calls those three.

`xcode` calls **`uuid.v4()` only** (`node_modules/xcode/lib/pbxProject.js:90`). A search across
the whole package for `v3`/`v5`/`v6` calls returns matches only inside the `uuid` package's own
deprecation-warning strings, never a call site. `v4` does not take the vulnerable path.

That makes `not_used` exactly right rather than approximately right:

| | |
|---|---|
| Affected function called? | **No** — `v4` only |
| Copy | `node_modules/xcode/node_modules/uuid@7.0.3`, `dev=True` |
| Reached via | `@capacitor/cli` → `xcode`, both `dev=True` |
| First-party imports of `uuid` | **zero** under `src/` or `amplify/` |
| Production copy | already `uuid@11.1.1` — the first patched version |
| Upgradable? | No. `xcode` requires `uuid@^7` |
| Phase | native packaging is POST-PROJECT per `00-current-owner-overrides.md` |

## 58 / 59 — `oauthlib`, fixed

Both advisories had to be read together to find the fix. GHSA-hj66-6f7g-4r5v covers
`<= 3.3.1` and GHSA-xpv3-w29h-x7cv covers `>= 3.0.0, < 4.0.0` — so **every 3.x release is
affected** and only the 4.x line clears both. A patch bump would have closed one alert and
left the other, which is the trap in treating two alerts on one package as one problem.

`requests-oauthlib` declares `oauthlib >= 3.0.0` with no upper bound, so 4.0.0 is within the
declared range rather than forced past it. Verified in a throwaway venv before changing the
pin: `oauthlib 4.0.0` + `requests-oauthlib 2.0.0` + `google-auth-oauthlib 1.4.1` all import,
and `OAuth2Session.authorization_url` still round-trips. 5201 pytest pass after the bump.

Worth noting for whoever revisits this: **nothing in this repository imports `oauthlib` or
`google_auth_oauthlib`.** They are transitive dev dependencies. Removing them outright would
also have closed both alerts and was deliberately not done — the Google API work in
`scripts/` uses service-account impersonation through `google-auth`, and pulling packages a
concurrent session might reach for is a worse trade than a version bump that costs nothing.

## Reproducing

```
gh api "repos/wecare-digital/wecare-digital/dependabot/alerts?state=open&per_page=20" \
  --jq '.[] | "\(.number)  \(.security_advisory.severity)  \(.dependency.package.name)@\(.security_vulnerability.vulnerable_version_range)  scope=\(.dependency.scope)  \(.dependency.manifest_path)"'
```

To check what a bundled dependency really contains, read the tarball rather than the
lockfile — the lockfile records what was requested, the tarball records what shipped:

```
curl -sSL -o cdk.tgz "$(npm view aws-cdk-lib@2.271.0 dist.tarball)"
tar -xzOf cdk.tgz 'package/node_modules/brace-expansion/package.json'
```
