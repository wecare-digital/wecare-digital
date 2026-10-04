# Grahak OS frontend handoff

Rewritten 2026-09-24. The previous version was stale in a way worth naming, because it
keeps happening: it opened by describing **PR #5** as the most recent merge when PRs up to
**#35** had already landed, it quoted a test count of 33 when the suite runs 73, a lint
count of 237 when it is 230, and it cited a browser harness (`animcheck.js`) that existed
in **no** file on disk. The revision before that one opened by asking for PR #3 to be
merged, long after it was.

**So: treat every number, hash and PR reference below as a claim to re-verify, not as
fact.** Each section now says how to re-measure it. The one structural fix made for this
is that the harness now lives in `tools/browser/` inside the repo, so "re-run the harness"
is an instruction that survives a sandbox reset.

## Position

- Repo `wecare-digital/wecare-digital`. Default branch is **`stack`**, not `main`.
  (Renamed from `bharat-stack` on 2026-09-27. GitHub still redirects the old path, so
  a stale URL appears to work — which is why three IAM trust policies and the Amplify
  app broke silently while `git` did not. Use the current name everywhere.)
- All work is on the single long-lived branch **`feat/grahak-os-trust-a-i`**.
- **THE BRANCH AUTO-DELETES ON MERGE.** It is squash-merged into `stack` and the remote
  branch is then removed, so at the start of a session it usually **does not exist** —
  `git ls-remote --heads origin` showed only `stack`. Recreate it from the default
  branch:
  ```bash
  git fetch origin --prune
  git checkout stack && git reset --hard origin/stack
  git checkout -b feat/grahak-os-trust-a-i
  ```
  **Never trust a local copy of this branch after a merge.** A squash merge leaves the
  old local branch looking "ahead" of `stack` by commits whose content is already
  merged, so `git log` reads like unshipped work that is in fact live.
- **Do not trust any commit hash, PR number or count written in this file.** Every
  previous revision named something stale by the time it was read — the revision before
  this one opened by describing PR **#5** as the latest merge when PRs up to **#35** had
  landed. Read the real state: `gh api "repos/wecare-digital/wecare-digital/pulls?state=all&per_page=10"`
  and `git log --oneline -1`.
- Merges from this branch so far include PRs #26, #28, #32 and #35, all squash-merged
  into `stack`. Anything described in earlier revisions of this file as "shipped on this
  branch" is therefore already on `stack` and live.
- No PR is open **now**. Owner's standing instruction: push to this one branch, open
  a PR only when explicitly asked, and the **owner merges** — never the agent.

## Shipped in the latest session

Deliberately no commit hashes: they are squash-merged away, and hashes in this file have
misled every reader so far. Re-verify with the harness, not with this table.

| What | Where |
|---|---|
| **The rotating-headline reflow is fixed.** `animcheck.js` went **16/20 → 18/18**. `/grahak-os/` jumped 40–41px at 320–360px and `/vayulok/` 39–40px at 320 and 450–520px, every 2400ms. Fixed with media queries scoped to only the widths that measured broken, so desktop line structure is unchanged | `src/pages/grahak-os/index.tsx`, `src/pages/vayulok/index.tsx` |
| **The type contract now matches the site.** `typecheck.js` went **1/3 → 3/3**. The contract specified a 53.76px section-h2 rung that existed nowhere; both the steering file and the harness are now on `clamp(28px,3.2vw,40px)` | `.kiro/steering/grahak-os-design.md`, `tools/browser/typecheck.js` |
| **Home section 3 is on the same rungs as section 2.** `.home-close-points li` 17px/600 → 20px/400 (the site's one body level), tick `top` 6px → 7px to stay on the x-height, and the mobile-only 18px lead override deleted so both section leads hold 20px down to 320px | `src/pages/index.tsx` |
| **The sitewide SEO no longer advertises one product.** `<title>`, `og:title`, `twitter:title`, `og:description` and `twitter:description` were WhatsApp-product copy inherited by all 15 public routes; `twitter:url` was hardcoded to the site root on every page. The messaging `Service` schema is now scoped to `/grahak-os/` instead of being emitted everywhere | `src/pages/_app.tsx` |
| **`/grahak-os/` no longer ships two of every `og:` tag.** `next/head` de-duplicates meta by `name`, **not** by `property`, so the page's own og set and `_app`'s coexisted — measured 2× each of type, url, title, description, image, site_name, locale. Fixed with matching `key` props on both sides | `src/pages/_app.tsx`, `src/pages/grahak-os/index.tsx` |
| **The home page stopped overriding its own metadata.** It declared `<title>WECARE.DIGITAL</title>` and `description="WECARE.DIGITAL."`, which beat the sitewide copy — so the most important URL on the site had a title with no content and a one-word description | `src/pages/index.tsx` |
| **`[retired public path b180810d]` and `/product-page/*` answer again.** They 404'd since a8d6a6c2 (#20) while 99 and 27 references stayed live, including the "Start Now" / "Book Slot" / "Upload Now" button URLs on outbound WhatsApp messages | `src/components/RetiredUrl.tsx`, `src/pages/customerservice.tsx`, `src/pages/product-page/*` |

## Needs the owner, not an agent

1. **Merge.** Nothing above reaches production until this branch lands in `stack`.
2. ~~**Dependency vulnerabilities are not code-fixable today.**~~ **FIXED — `npm audit`
   now reports 0 vulnerabilities.** It had been 5 (4 moderate, 1 high).

   Everything earlier revisions of this file said about this was stale, which is worth
   noting because it was stated with confidence: there was no `@wix/cli` finding and no
   `tar` finding in the audit at all, and nothing about `plivo-browser-sdk`,
   `wasm-pack` or `binary-install`. **Re-run `npm audit` rather than trusting any
   description of it, including this one.**

   What was actually there: all 5 findings traced to the single direct devDependency
   `@aws-amplify/backend-cli` → `@aws-amplify/schema-generator` →
   `@aws-amplify/graphql-schema-generator` → `csv-parse` (prototype replacement) and
   `mysql2` (auth-plugin downgrade, unbounded zlib inflate).

   `npm audit fix` was NOT the answer: its `fixAvailable` proposed dropping
   `@aws-amplify/backend-cli` from **1.10.0 to 0.11.1**, a major *downgrade* to a 0.x
   line, because every 1.x release is inside the advisory range. 1.10.0 is the newest
   published version, so there was nothing to upgrade to — the same shape as the old
   `@wix/cli` note, and the same trap.

   The fix was to patch the two **leaf** packages instead, via `overrides` in
   `package.json`: `mysql2` 3.9.9 → **3.24.4** (clears the `<=3.23.0` range) and
   `csv-parse` 5.6.0 → **7.0.2**. That clears all five, because the other three were
   only flagged as parents of these two.

   Safe because it is dev-only and unused: both are reached solely through the `ampx`
   CLI's SQL schema generator, and this project never invokes it — there is no
   `schema-from-database` call anywhere and `amplify/data/resource.ts` is a
   DynamoDB-backed `defineData`/`a.model` schema with no SQL data source. Verified after
   the change: build 0, tsc 0, vitest 99/99, provider policy 8/8.

   Applied **incrementally**, not by regenerating the lockfile: a from-scratch regen
   touched ~19,700 lines, while `npm install` over the existing lock touched **35
   insertions / 56 deletions** for the same result. Prefer the small diff.
3. ~~**`npm ci` IS BROKEN AGAIN, and the usual fix provably does not work.**~~
   **FIXED — see `docs/npm-ci-backend-isolation.md`.** `npm ci` exits 0 and the lockfile is
   stable under both `npm ci` and `npm install`.

   The upstream defect described below is still real and unchanged. What changed is that the
   four packages carrying it — `@aws-amplify/backend`, `@aws-amplify/backend-cli`,
   `aws-cdk-lib`, `constructs` — are no longer in the web app's lockfile. They are
   backend-only (`tsconfig.json` excludes `amplify/**/*`, nothing under `src/` imports them,
   and `amplify.yml` has no `backend:` phase), so they moved to `amplify/package.json` as a
   separate install root. The root lockfile went from 1922 packages to 783, and
   `.github/workflows/build-test.yml` now installs with `npm ci` plus a lockfile-drift gate.

   Two corrections to what this item used to say. **`patch-package` cannot work** — it was
   listed as the remaining local option, but `npm ci` fails during install, before any
   lifecycle script runs, so a `postinstall` patch never executes. And the list of failed
   approaches below was incomplete: a package-scoped exact override *does* make `npm ci` pass
   with a byte-identical tree, but `npm install` strips the lockfile entries it needs, so it is
   an unstable equilibrium rather than a fix. Range overrides, `npm@11.6.2` and downgrading
   `@aws-amplify/backend` were all tried and all fail. The full table is in the new doc.

   Retained below for the history, because the diagnosis is accurate and worth keeping:

   Earlier revisions of this file said "`package-lock.json` resynced — `npm ci` works again".
   That was no longer true. On `stack` at `e4cfbe0e`:
   ```
   npm error `npm ci` can only install packages when your package.json and
   npm error package-lock.json ... are in sync.
   npm error Missing: @opentelemetry/core@2.0.0 from lock file   (x4)
   ```
   **`npm install` exits 0 and leaves `package-lock.json` byte-identical** — `git diff`
   is empty afterwards — so "update your lock file with `npm install`", which is what the
   error message and the previous fix both say, cannot resolve it. `npm ci
   --legacy-peer-deps` (what `deps-upgrade.yml` actually runs) fails identically.

   The drift is **inside upstream tarballs, not in this repo.**
   `@aws-amplify/data-construct` and `@aws-amplify/graphql-api-construct` each *bundle*
   (`inBundle: true`) their own OpenTelemetry copies. Their bundled
   `@opentelemetry/resources@2.0.0` and `sdk-trace-base@2.0.0` both declare an **exact**
   dependency on `@opentelemetry/core@2.0.0`, while the `@opentelemetry/core` bundled
   beside them is **2.8.0**. Two packages x two dependents = the four errors. `npm
   install` succeeds because it trusts bundled deps rather than resolving them; `npm ci`
   validates those edges and refuses.

   **EVERY LOCAL FIX IS NOW A CLOSED DEAD END. Do not spend another round on it.** Two
   were tried and measured (lockfile regen, an `overrides` entry); a third
   (`patch-package`) is ruled out by mechanism below without needing to be tried. Nothing
   is failing because of this — CI installs with `npm install` and probes for the fix — so
   the correct posture is to leave it alone until it actually blocks something.

   *Regenerating the lockfile from scratch does not work.* `rm package-lock.json && npm
   install` on a networked machine produces a completely fresh tree — 12,404 lines
   removed, 7,302 added — and `npm ci` still fails. That matters because it is exactly
   what `deps-upgrade.yml` at `mode=lock-only` does, so **that workflow cannot fix this
   either**; an earlier revision of this file recommended it as "the most likely thing to
   fix this", and that advice was wrong.

   **Corrected 2026-09-29: the regen does not reproduce the "identical four errors",
   it produces far more.** This paragraph said "identical four" and that was measured on
   an older npm. Re-measured on Node 24.21.0 / npm 11.19.0, from HEAD's `package.json`
   with the exact command `deps-upgrade.yml` runs, in an isolated directory so the
   working tree was untouched:

   | lockfile | `npm ci --legacy-peer-deps` |
   |---|---|
   | committed at HEAD | exit 1, **4** findings, **1** distinct (the OTel edge) |
   | fresh regen | exit 1, **87** findings, **62** distinct |

   The extra 61 are a second bundled subtree — `@aws-cdk/toolkit-lib`,
   `@aws-cdk/cloud-assembly-api`, `archiver`, `cdk-from-cfn`, the `bare-*` family,
   `chalk`, `fs-extra` — which the fresh resolve hoists differently from what `aws-cdk`
   bundles. `npm install` exits 0 against that lockfile and every workflow here uses
   `npm install`, so the regression is invisible everywhere except `npm ci`. But the
   committed lockfile is **the better of the two states**, which inverts the premise this
   workflow was built on.

   Consequence for the item below: splitting the failure classes fixed the **gate**, not
   the **job**. `npm_ci_gate.py` correctly refuses the regenerated lockfile — 61
   unexpected findings — so `deps-upgrade.yml` still cannot commit, now because the regen
   produces a regression rather than because the gate was unconditionally red. Verified
   by running the gate in both directions: exit 0 against HEAD's lockfile reporting the 4
   tolerated findings, exit 1 against a fresh regen naming the 61. Do not "fix" that by
   widening the allowlist or passing `--strict`; the honest unblock is to stop
   regenerating from scratch and use the incremental `npm install` in item 2 above, which
   is a change to that workflow's purpose and so an owner decision.

   *An `overrides` entry does not work either — it crashes npm.* Adding
   `"@opentelemetry/core": "2.8.0"` to rewrite the bundled requirement made `npm install`
   abort with a V8 stack trace and exit **134**, and the follow-up `npm ci` then hung
   until it was killed. The override was removed; do not re-add it.

   Note this is specific to overriding a **bundled** dependency, not to `overrides` as a
   feature. `package.json` carries five overrides today (`lodash`, `fast-xml-parser`,
   `immutable@3`, `mysql2`, `csv-parse`) and they are fine. The OTel entries are
   `inBundle: true`, which is the difference.

   *Reported 2026-09-29, and it closes the overrides route from a second direction: even
   where an override does not crash, `npm install` undoes it.* npm re-reads the bundled
   manifests out of the published tarball and rewrites those lockfile entries back to what
   the tarball declares, so the override leaves no durable trace in `package-lock.json`.
   That kills the "override it and commit the resulting lockfile" variant, which is
   otherwise the obvious next thing to try after the crash. **Not re-measured here** — it
   is recorded from the investigation that found it, and deliberately not re-run, because
   reproducing it means letting `npm install` write to the shared lockfile.

   Consequences: to install, use `npm install`, never `npm ci`.
   `.github/workflows/build-test.yml` already does, and carries a non-blocking probe that
   will announce the day `npm ci` starts working.

   **There is exactly one realistic resolution, and it is upstream:** Amplify fixing the
   bundled dependency edge in `data-construct` / `graphql-api-construct`.

   *Corrected 2026-09-29: `patch-package` was listed here as the second option, described
   as "heavy for a lint-level annoyance". That undersold it — it cannot work at all, and
   the reason is structural rather than a matter of effort.* `patch-package` applies its
   diffs from a `postinstall` script, and `npm ci` fails while validating the lockfile
   against `package.json`, before it fetches a tarball, before `node_modules` is
   populated, and therefore before any lifecycle script runs. On the failing path the
   hook never executes. Nor does it help on the succeeding path: `patch-package` edits
   files inside `node_modules`, `npm ci` deletes `node_modules` outright and re-reads the
   registry tarballs, so nothing it patched survives into the comparison that fails. A
   postinstall hook cannot repair a failure that happens before postinstall. Do not
   reach for it, and note the repo has neither the dependency nor a `postinstall` script,
   so nothing has to be undone.

   **Resolved 2026-09-29 for `deps-upgrade.yml`, which this used to brick.** That
   workflow regenerates the lockfile and then gated on a bare `npm ci`, under a comment
   asserting both spellings were "verified ... exit 0" — measurably false, re-checked on
   Node 24.21.0 / npm 11.19.0, where `npm ci` and `npm ci --legacy-peer-deps` each fail
   with the same four findings. So the gate could never pass and the job could never
   commit what it had just regenerated. Reverting it to `continue-on-error` was rejected:
   that is exactly what let the lockfile rot into missing five real entries.

   Both framings assumed one verdict for the whole command, and there are two failure
   classes in that one output. `scripts/npm_ci_gate.py` splits them — the four known
   upstream edges are tolerated **by exact whole-finding string**, and any other
   `Missing:`/`Invalid:`/`Extraneous:`/`Conflicting peer dependency:` line still fails the
   job, as does a failure carrying no sync findings at all (that means network or engine,
   not drift). So drift detection survives for the class we cause while the class we
   cannot fix stops blocking. Verified against live npm on `stack`: allowlist-active exits
   0 reporting the 4 tolerated findings, `--strict` exits 1, and `package-lock.json` is
   unmodified either way. When upstream is fixed the gate exits 0 and prints a `::notice::`
   naming the three things to undo, so the workaround cannot quietly outlive its cause.
   `tests/test_npm_ci_gate.py` (24 cases) pins the boundary, including real drift arriving
   alongside the known finding and a different `@opentelemetry/core` version counting as
   new drift.
4. ~~**`amplify.yml` still deploys with `npm install`.**~~ **Closed 2026-09-29: it now
   deploys with `npm ci --no-audit --no-fund`**, the same command `build-test.yml` gates on.
   The reasoning recorded here — "blocked outright by the item above", "`npm install` is
   currently the only command that works" — stopped being true when the four
   `@opentelemetry` backend packages moved into `amplify/package.json`. That removed the
   inconsistent bundled subtree from the ROOT lockfile, which is the only one this build
   installs, so `npm ci` resolves it cleanly. The upstream defect is unfixed and `npm ci`
   inside `amplify/` still fails on it; that root installs with `npm install` and is not on
   the per-push path. Verification and the rollback are in
   `docs/npm-ci-backend-isolation.md`.
5. **Real-device pass.** Everything has been verified in headless Chromium only. iOS
   Safari and the Android WebView shells have not been checked.
5b. **`KIRO_API_KEY` secret, to switch on automated PR review.**
   `.github/workflows/kiro-review.yml` is merged and wired but **gated on that secret**,
   so it currently reports a notice and skips. Add it under Settings → Secrets and
   variables → Actions and it starts working with no further edit. Two things to decide
   with it: `konippi/kiro-cli-review-action` is a third-party **personal** action whose
   `v1.0.1` tag is mutable, and this repo holds AWS deploy credentials in four other
   workflows — pinning to a full commit SHA is the stronger choice. And leave its `debug`
   input off; the action's own description warns it prints tool output that may contain
   sensitive data into build logs.

   **Actions evaluated and deliberately NOT added**, so nobody re-litigates it:
   - `microsoft/setup-msbuild` — there is **nothing here for MSBuild to build**. No
     `.sln`, `.csproj`, `.vcxproj` or `.vbproj` anywhere in the tree; this is 269
     TS/TSX files and 309 Python files. It would also force `runs-on: windows-latest`,
     billed at 2x Linux minutes, to configure a toolchain with no inputs.
   - `redhat-actions/try-in-web-ide` — clones a PR into a Che-based IDE on the Red Hat
     Developer Sandbox. It **requires a devfile**, and this repo has none. It would add
     a PR comment pointing at an IDE nobody here uses.
   - `aws-actions/configure-aws-credentials@v6.3.0` — **already in use**, at `@v6`, in
     `docs-scraper-deploy.yml`, `plivo-drift.yml`, `route-auth.yml` and
     `seo-tools-deploy.yml`. `@v6` is a floating major tag that already resolves to the
     newest 6.x, so it is on 6.3.0 today and picks up future patches automatically.
     Re-pinning to `@v6.3.0` would *freeze* it and stop security patches arriving. If
     hardening is the goal, SHA-pin instead — that is a different change, and it should
     be done to all four call sites at once.
   - Minor drift worth a one-line cleanup while in there: `ui-labels.yml` is on
     `actions/checkout@v5` and `actions/setup-python@v5` while the rest of the repo is on
     `v7`, and `blog-migration-validate.yml` / `seo-tools-deploy.yml` are on
     `setup-python@v6`.
6. **The contact map's three Google controls are LIVE, not inert — pick a fix.** The
   code claimed the interaction overlay made them inert. Measured, it does not: all three
   sit in the 26px bottom strip the overlay deliberately leaves uncovered for attribution,
   and a click hit-test lands on the iframe, so `Show satellite imagery` will actually
   change the map. They cannot be safely patched with geometry, because the attribution
   links sit in the same strip at coordinates Google does not document — a pixel-tuned
   cut-out risks covering attribution, which is a licence breach worse than the defect.
   Three options, all needing a decision: set `NEXT_PUBLIC_GOOGLE_MAPS_KEY` (the keyed
   Maps JS path already passes `disableDefaultUI` and removes them outright), move to
   Static Maps, or set `pointer-events:none` on the iframe and render our own attribution
   links outside it. Full measurements are in the comment above `.cl-lock`.
7. **Type ladder: the section-h2 rung in the design contract is the site's minority
   spelling — pick one.** Measured on all 15 public routes at 1280px with
   `node tools/browser/typecheck.js`. Six distinct h2 treatments, each traceable to a
   different authored `clamp()`, so **none of this is a browser rendering difference** —
   every browser computes the same numbers.

   | Declaration | @1280 | Owners |
   |---|---|---|
   | `clamp(32px,4.2vw,54px)`/700/1.04/-1.875px | 53.76px | `/grahak-os/` only — 3 headings. **This is what the contract says.** |
   | `clamp(28px,3.2vw,40px)`/700/1.08/-1.2px | 40px | **12 headings on 10 pages** — `.home-close-title`, `.home-flow-title`, `.cl-h2`, `.mo-h2`, `.brx-h2`, `.pdp-h2` (×7) |
   | `clamp(22px,2.4vw,28px)`/700/1.2/-0.6px | 28px | `.lgd-h2` ×69 on `/terms/` + `/privacy/` |
   | `clamp(36px,4.3vw,60px)`/**600** | 55.04px | `/grahak-os/` `.gos-closer-head` — the **hero h1 clamp**, on an h2 |
   | `14px`/600/uppercase/.04em | 14px | `.lgd-toc-title` "Contents" ×2 — an **eyebrow**, not a heading |

   **Recommendation: adopt `clamp(28px,3.2vw,40px)`/700/1.08/-1.2px** as the marketing
   section-h2 rung and amend the contract to match, rather than raising 12 headings to
   meet 3. Two reasons beyond the head count. It is already one *byte-identical*
   declaration under five class names in five files, so it was clearly deliberate. And the
   contract's own rung barely reads as subordinate: the hero h1 is
   `clamp(36px,4.3vw,60px)` = 55.04px at 1280, so a 53.76px h2 sits **1.28px** below its
   own h1 — the size hierarchy collapses and only the 700/600 weight inversion separates
   them. Every page authored after `/grahak-os/` quietly chose the smaller rung.

   Then keep two rungs as deliberate exceptions, written into the contract so they stop
   reading as drift: `.lgd-h2` at 28px (a legal document with 45 numbered sections cannot
   carry 54px headings), and `.lgd-toc-title`, which should become a `<p>` or move onto the
   12px/700/.08em eyebrow rung.

   Already fixed, because it needed no decision: `/` carried **two** section-h2 sizes,
   `.home-flow-title` at 33.28px beside `.home-close-title` at 40px, under a comment
   claiming it was "the contract's rung … the same on every page". It is now on the 40px
   rung and the home page is internally consistent. Still open on `/grahak-os/`:
   `.gos-closer-head` at 55.04px/600 both exceeds the contract's 54px cap and inverts its
   one hard rule that a section h2 is 700 and heavier than the h1. Either it is a
   hero-scale closer by design — in which case the contract should name it and it probably
   should not be an `<h2>` — or it is drift.
8. **`/grahak-os/` and `/vayulok/` heroes reflow at narrow widths — needs a design call.**
   This is the "page jumps every 2400ms" defect the code believes it fixed. It was fixed
   on Home and in `RotatingHero` by putting the pill on its own line, but the two inline
   copies still set it mid-sentence (`Bharat <pill> Intelligence`, `across <pill>`), so
   their h1 line count depends on the active word. Measured with `animcheck.js`:
   Grahak OS at 320px is **168px on `WhatsApp` against 128px** on the other three, and at
   360px 128 vs 87; VayuLok at 320px is **126px on `Weather`/`Forecast`/`Heatmap` against
   87px** on `Air`/`Pollen`/`Solar`, and at 480px 87 vs 47. The fix is to move those two
   onto `RotatingHero`, or to force the pill onto its own line at narrow widths — either
   changes the hero's line structure on two product pages, which is why it was not done
   unasked.

## Open work an agent can pick up

### Needs the owner's wording, not an agent's

These are the three copy items left on the public pages. Each one has been deliberately
left alone rather than guessed at, because the owner has rewritten every other line on
these pages personally and rejected several agent drafts on substance:

- **The hero sub-line is the only element on the home page never revised** — "Transparent
  pricing, guided journeys, and dependable support — on one shared foundation."
- **The flow section has no call to action**, which is also the last ~136px of the measured
  panel-vs-copy height gap. There is no action above the fold on the home page.
- **"say it" in the closing lead implies voice input.** Confirm that is real, or soften the
  word. The lead is the owner's own wording, so only the owner should change it.

### Still open, and an agent can do these

- **A real 301 for `[retired public path b180810d]` and `/product-page/*`.** The stubs added this session are
  the in-repo fix and they work, but `output:'export'` means Next cannot emit a 3xx and
  Amplify Hosting redirects are console-managed. A CDN-level 301 would make
  `src/components/RetiredUrl.tsx` obsolete — which is the preferred outcome.
- **Per-page SEO beyond the sitewide block.** `PUBLIC_PAGE_META` already holds a name, type
  and description per route; only the JSON-LD consumes them. Titles and descriptions are
  still hand-written per page, and two are thin: `/vayulok/` is titled "VayuLok by
  WECARE.DIGITAL" and described as "VayuLok - Bharat Air Intelligence, by WECARE.DIGITAL.",
  neither of which says what it does.
- **Product schema from `src/content/wix-catalog.json`**, once the commerce decisions below
  are made.
- **Reconcile the two Wix API versions.** `scripts/fetch-wix-catalog.js` uses
  `stores-reader/v1`; `amplify/functions/ecommerce/wix-store/handler.py` uses `stores/v3`
  in 17 places. Inspect a real v3 payload before mapping — the field shapes are not mapped,
  and v3 adds price ranges and cursor paging.
- **The catalog snapshot will not scale.** 7 products is 9,500 bytes; the owner expects
  ~4,000, which is 5–6MB of committed JSON. That needs a `ProductsTable`, a scheduled
  `catalog-sync` Lambda and DynamoDB Streams fan-out, not a bigger file.
- **No price appears on the home page**, and the closing band promises "Know the price
  before you commit." When a number is added it must be **derived** from the catalog, not
  typed: the floor is ₹599 today (Viveka) and the owner expects ₹49 once several thousand
  more products load.

### Blocked on the owner

- **A Google Maps API key.** Blocks the last red harness assertion, and blocks recolouring
  the red pin to lime. There is no `AIza` key anywhere in the tree or in
  `git log --all -S AIza`, and `.env.example:58` has it commented out.
- **Wix product images.** All 7 products report `mediaCount: 0` on both API versions, which
  blocks the Meta WhatsApp catalog entirely.
- **`productType`.** All 7 products are `physical`; 4 of them are services. Google Merchant
  will reject those.
- **A join key for commerce.** Every SKU is empty. Recommendation: the Wix `id` UUID, with
  `slug` used only for URLs.
- **Turn off "Automatically delete head branches".** The working branch has now been
  recreated **seven** times, which has cost two near-reverts and one 28-file conflict.
- **Rotate the Wix API key.** It was pasted into a chat transcript and is account-scoped,
  so it cannot be referrer-restricted. Move it to Secrets Manager under the existing
  `WIX_API_KEY_SECRET` pattern.

- ~~`_document.tsx` sets an `X-Frame-Options` meta tag.~~ **Deleted.** It gave zero
  protection, since browsers honour XFO only as a header, and it logged an error on every
  page load of the site — `animcheck.js` now reports **zero** console errors on `/`,
  `/grahak-os/`, `/vayulok/` and `/contact/`. `amplify.yml` still sets the real
  `SAMEORIGIN` header. A comment marks the spot so it is not re-added.
- **`npm run lint` is red repo-wide**: **230 errors / 63 warnings**, including ~115
  `react-hooks/set-state-in-effect` errors. Only the `LanguageBar` one was fixed.
  Measured baseline, so it can be used as one: `git stash`-ing the latest session's
  changes produced the identical 230/63, i.e. that work added no lint debt. Earlier
  revisions of this file claimed 236/63 and 237/63; re-count rather than trusting a
  number here.
- ~~Home page is a scaffold, DEFERRED.~~ **Home now has a hero.** Owner asked for the
  rotating headline from Grahak OS and VayuLok, so `src/pages/index.tsx` carries the
  same pill on the same constants — 2400ms, `cubic-bezier(.16,1,.3,1)` for the wipe
  and width glide, `(.34,1.56,.64,1)` for the dot pop. **There are FOUR rotating
  surfaces, not three** — `home-` on `/`, `hero-` on `/grahak-os/`, `vl-` on
  `/vayulok/`, and `rh-` in `RotatingHero` (used by `/contact/`, `/terms/`, `/privacy/`,
  `/bharat-rx/`, `[retired public path aaee9dd4]/`). They are one animation family: retune one and you must
  retune all four. `animcheck.js` compares the computed transitions across all four and
  currently measures them identical; `HomePage.test.tsx` fails if Home drifts.
  - Copy is **provisional** and carries owner positioning (lower cost, less
    complexity, utility over scale). The rotation itself is the "across every domain"
    claim, enacted rather than asserted. Reword via `CYCLE_WORDS` and `.home-sub`.
  - **No service names in the rotation.** travel, rituals, documents, reflection and
    disputes were each in it at some point; a service can be discontinued, and on that
    day the headline is false. Channel names (WhatsApp, SMS, email, phone) are fine,
    which is why the Grahak OS hero may rotate them. Note `/contact/` still rotates
    **`drop documents`** — it reads as an action rather than a service, but it is worth
    an owner ruling given "documents" is on the banned list.
  - **Rotating word length is a layout constraint.** The pill animates to each word's
    *measured* width, so the spread is how far the headline's tail travels per tick.
    Measured at 1280px: `consumers` 278, `enterprises` 280, `climate tech` 298,
    `frontier tech` 300 — spread **22px**. `AI applications` (361px) was dropped from the
    rotation, which is what cut the spread from 83px to 22px; do **not** re-add it, because
    the h1 frame now reads "Everyday AI, built for" and it would render as "Everyday AI,
    built for AI applications". The real failure mode is the h1 reflowing on the longest
    word only, which would shift the page every 2400ms;
    `.home-head-line` is `display:block` so the pill owns its line and this cannot
    happen. `node tools/browser/animcheck.js` measures h1 height for every word at 21
    viewports from 320 to 1920 **and** through a live rotation: constant, 131px at
    1280px. The same check now passes on all four surfaces — `/grahak-os/` and `/vayulok/`
    were the two that reflowed, and both are fixed with width-scoped media queries rather
    than by restructuring their headlines.
  - Below the hero there are now two sections — `.home-flow` (the `WorkflowTerminal`)
    and the `.home-close` band, which reveals on scroll via `IntersectionObserver`
    rather than a timer. `.home-layout`'s `gap:96px` is the section rhythm.
- ~~`[retired public path 1965ee0f]` and `/partners` are now in the nav but are visually off-system.~~
  **Both pages are deleted**, and the nav entries that pointed at
  `www.wecare.digital/customerservice` and `.../product-page/referral-partner` — both of which
  **404'd** — now point at `/contact/`. Those two external URLs also answer again: see
  `src/components/RetiredUrl.tsx`. Note a 200 on a `[retired public path 6b3a02b3]/*` path is **not** evidence a
  route is public — those render `<Layout user onSignOut>` and are auth-gated, which is why
  the nav links go to `/contact/` and not there.
  Consequence worth knowing: `/partners` was the only **public**
  WhatsApp Embedded Signup entry point. `EmbeddedSignupPanel` survives because
  `dm/whatsapp/connected-accounts` and `dm/whatsapp/embedded-signup` still use it, but
  it is now reachable only behind auth. Two backend WhatsApp replies still send
  customers to `[retired public path ef456375]`
  (`inbound-whatsapp-handler/handler.py:1887` and `:6414`) — **owner call**, since
  that is marketing-site content, not a route in this app.
- **VayuLok's rotation promises Pollen and Heatmap**, which have no endpoint wired.
- **`trust-subtext` restates the channel list a third time** on `/grahak-os`.

## Traps that have already cost real time

- **styled-jsx drops a `className` passed via spread.** `{...props}` then styled-jsx
  appends its *own* `className` attribute, which wins — the element ships with only
  `class="jsx-hash"` and no styling at all. Write `className` **inline** on the
  element. This broke the whole nav menu and **all 33 tests still passed**, because
  they assert role/name/href and never look at classes.
- **styled-jsx does not scope composite components.** A parent's `<style jsx>` cannot
  reach into `<BrandBadge />`. Such components style themselves — see `BrandBadge`,
  `BrandLockup`, `AuthBrand`.
- **`src/styles/*.css` is imported globally by `_app.tsx` and declares unscoped rules
  for generic names** — `.page`, `.tab`, `.code-block`, `.nav-item`, `.badge`,
  `.section-header`. Several "my change didn't apply" bugs were this. Prefix new
  classes (`pp-`, `ft-`, `ag-`, `acp-`).
- **A stray backtick inside `<style jsx>{`…`}</style>` breaks the build** (once for 520
  tsc errors). Check with:
  ```bash
  python -c "s=open('src/pages/grahak-os/index.tsx').read();i=s.find('<style jsx>{\`');j=s.rfind('\`}</style>');print(s[i+13:j].count('\`'))"
  ```
- **`npx tsc --noEmit` must run *after* `npm run build`** — it needs generated
  `next-env.d.ts`.
- **`cmd | tail; echo $?` reports `tail`'s exit code, not the command's.** Redirect to
  a file and check `$?`, or use `PIPESTATUS`.
- **`trailingSlash: true`.** Links to exported pages need the trailing slash
  (`/vayulok/`), or they redirect. `[retired public path ef531503]` is deliberately bare.
- **The Amplify `Authenticator` renders client-side only** — the static export contains
  none of its markup, so anything in that tree must be verified in a browser.
- **`hideSignUp` means the Authenticator renders no tabs at all.** The
  `components.tabs.item` tokens in `authTheme` are therefore **inert** — measured in a
  browser, `[role="tab"]` matches zero elements on `[retired public path ef531503]`. A whole block of theme
  config had drifted off-palette (`#6b7280`) with nothing on screen to reveal it. Do
  not tune those tokens expecting a visible change.
- **The public pages' typeface came from an auth library.** `/` and `/vayulok/`
  rendered in Inter only because `@aws-amplify/ui-react/styles.css` sets a
  `font-family` on `body` beginning with Inter; neither shell declared one, and
  `--font-sans` in `Pages.css` contains **no Inter** to fall back to. Both shells now
  declare the stack explicitly. Measuring `getComputedStyle().fontFamily` alone will
  not catch this class of bug — compare the **rendered advance width** of a fixed
  string against the same string forced to Inter, which is what `verify.js` does.
- **Its `components.Header` slot is typed `() => JSX.Element | null`.** `React.FC` is
  `(props, context?)` and is **not assignable**; tsc fails with "Target signature
  provides too few arguments."
- **`Header.test.tsx` asserts literal CSS substrings**, including
  `"@media(max-width:767px){.hdr-in{height:96px"`. `.hdr-in` must stay the first rule
  in that media query, and `container.querySelector('button')` must return the nav
  trigger — so no `<button>` may precede it.
- **Node 24 is required** (`engines: >=24.0.0`). In the sandbox:
  `export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 24`.
- **jsdom does not implement `window.matchMedia`**, and calling it *throws* rather
  than returning undefined. Any component gating animation on
  `prefers-reduced-motion` therefore crashes on mount under vitest — it surfaced as
  all 8 Home tests failing at once with a green build and clean lint. `src/test/setup.ts`
  now stubs it, defaulting to `matches:false` so tests exercise the animated path.
  VayuLok has gated its rotation this way from the start and never hit this only
  because **it has no test of its own**.
- **`/tmp` does not persist between tool calls in this sandbox.** Writing a log there
  and reading it in the next command gets "No such file or directory", which looks
  like the command failed when it did not. Keep the write and the read in one call,
  or put the file under `/projects`.
- **A JSX comment cannot contain `*/`, and a glob will put one there.** Writing
  `customHeaders` pattern `"**/*"` inside a `{/* … */}` block closes the comment early
  and the build fails with `Expression expected` / `Unterminated string constant`
  pointing at a *prose* line, which reads like a mangled file rather than a comment
  delimiter. Cost one build cycle in `_document.tsx`.
- **`elementFromPoint` takes VIEWPORT coordinates and returns `null` off-screen.**
  Hit-testing the contact map's controls without scrolling the map into view returned
  `null` for all five, which the harness then scored as "the click was blocked" — so the
  check **passed while three controls were live**. Scroll the target into view first, and
  treat "could not determine" as a failure rather than a pass. This is the same shape as
  the `[role="tab"]`-matches-nothing trap above: an assertion that cannot see its subject
  reports success.
- **`cmd | grep -c …` in an `&&` chain aborts the chain when the count is zero**, because
  `grep` exits 1 on no matches. A diagnostic command then silently never runs and the log
  it was supposed to write does not exist, which looks like the tool failed. Related to
  the `PIPESTATUS` note above and bites just as often.
- **`npm ci` cannot install this repo** — see "Needs the owner". Use `npm install`. The
  error tells you to run `npm install` to fix the lockfile; doing so exits 0 and changes
  nothing, because the inconsistency is inside bundled upstream tarballs.

## Verification gate

**The first four of these now run in CI** on every pull request, via
`.github/workflows/build-test.yml`. Until that workflow existed, **no CI job compiled
the app or ran its tests** — the ten other workflows cover CodeQL, route auth, provider
policy, UI labels, plivo and the deploys, none of which would notice a repo that does
not build. A pull request could go green while broken, and it only stayed honest because
a human ran the commands below by hand. If a check is ever needed that CI does not have,
assume it is not there rather than assuming it is.

Measured on this branch, based on `stack` at `80a877f9`, Node 24.19.0. The harness reads
`out/`, so **`npm run build` has to come first** or it measures the previous build:

```bash
npm run build                        # exit 0; then:
npx tsc --noEmit                     # 0 errors
npx vitest run                       # 152 passed / 13 files
./scripts/check-provider-policy.sh   # no violations
npx eslint .                         # 225e/63w — red, pre-existing
node tools/browser/animcheck.js      # 18/18
node tools/browser/typecheck.js      # 3/3
node tools/browser/uicheck.js        # 28/28
node tools/browser/contactcheck.js   # 12/13 — 1 known failure, see below
```

Only **one** harness assertion is red now, and it is blocked on the owner rather than on
code: three Google map controls on `/contact/` stay reachable until a Maps API key exists.
Earlier revisions of this file recorded `animcheck` at 16/20 and `typecheck` at 1/3; both
are green as of this session, so if you see those numbers you are reading a stale copy.
The lint count is a **measured baseline, not a target** — `225e/63w` is what `stack`
carries, and this session's work added none of it (the only error inside the changed files
is the long-documented `<a>` in `index.tsx`, which must stay an `<a>`).

Three things to know about that list. **`npm ci` is not in it** — it is broken, see
"Needs the owner"; the CI workflow therefore installs with `npm install` and carries a
non-blocking probe step that will announce the day `npm ci` starts working. **eslint is
reported but not enforced** in CI, because a gate that fails every pull request
regardless of its contents just teaches people to ignore CI; compare the count against
the base branch instead. And `.venv/bin/python -m pytest -q` is not in it: there is no
`.venv` in a fresh sandbox.

The **browser harnesses are not in CI either**, deliberately for now — they need a
Chromium download and three of their assertions fail by design pending owner decisions,
so they would land permanently red. Worth adding as a non-blocking job once those
decisions are made.

Numbers move: earlier revisions of this file quoted `33 passed / 7 files`, `73/8`,
`237e/63w` and `230e/63w`, each true when written. Re-count rather than trusting these.

Browser harnesses now live **inside the repo**, at **`tools/browser/`**. They used to
live in `/projects/pwtest`, and a sandbox reset destroys that whole directory — which is
how `animcheck.js` came to be cited in four files while existing nowhere on disk, and
`mapprobe.js` in a fifth. Under version control that cannot recur. See
`tools/browser/README.md`.

```bash
cd tools/browser && npm install   # one package: playwright-core, no browser download
cd ../.. && npm run build         # produces out/
node tools/browser/animcheck.js
node tools/browser/contactcheck.js
```

`playwright-core` rather than `playwright` is deliberate: it never downloads a browser,
so the app's own dependency tree and its already-fragile lockfile stay untouched, and
nothing runs a browser-download postinstall on an Amplify deploy.

**Never hardcode the Chromium path.** In this sandbox it lands in
`/opt/playwright/chromium-<rev>/chrome-linux64/chrome`, not `~/.cache/ms-playwright`
— but **the revision changes across resets**, and harnesses pinned to
`chromium-1243` all died with `executable doesn't exist` on a box that had
`chromium-1232` sitting right there. That reads like a broken harness, not a missing
browser, and it cost a debugging round. `lib/browser.js` resolves it: `CHROME` env
var, then Playwright's own lookup, then the highest `chromium-*` under
`/opt/playwright`, then `~/.cache/ms-playwright`; it throws naming every path it
searched rather than returning undefined.

**Harnesses are dual-mode.** `lib/serve.js` exports `target()`: with no `BASE` it
boots its own static server against `out/` (background servers are blocked, so each
run owns one) and handles `trailingSlash` resolution; with `BASE` set it points at
that origin instead and starts nothing. So the same assertions run against either
render:

```bash
node tools/browser/animcheck.js                              # against out/
BASE=http://localhost:3000 node tools/browser/animcheck.js   # against next dev
```

That distinction is load-bearing: `next.config.js` only sets `output:'export'` when
`NODE_ENV` is production, so `out/` is pre-generated HTML and dev is a live server.
A suite that only ever ran against `out/` has not tested what you see locally.

**State of that claim, stated precisely.** The `BASE` branch is verified: `animcheck.js`
returns an identical 16/20 pointed at a separate origin as it does booting its own server.
It has **not** been run against `next dev` in this sandbox, because a dev server started in
one tool call is killed before the next one runs (`curl` then gets `000`, which reads as a
broken harness rather than a dead server). To cover dev, start the server and run the
harness **in a single command**, and **warm every route first** — dev compiles per route on
first request, and an uncompiled route answers slowly enough that a harness measures a blank
page and reports a false failure. The old `rundev.sh` that did this was lost with
`/projects/pwtest`; rewriting it under `tools/browser/` is worth doing.

`animcheck.js` allows **three** console-error patterns and nothing else. Two appear only
under dev and are dev-server infrastructure, not regressions: `_clientMiddlewareManifest.js`
is served with a MIME type Chromium refuses, and the `_next/hmr` websocket cannot complete
a handshake through this sandbox's networking. The third applies in **both** modes and is
a local-origin artifact: `LanguageBar` fetches `api.wecare.digital/site-language`, which
sends no `Access-Control-Allow-Origin` for `127.0.0.1`, so the request is refused by CORS.
On the deployed site the page origin *is* `wecare.digital` and it succeeds. That entry is
scoped to the one host, and the generic `Failed to load resource` line it also produces is
matched by **request URL** rather than by text, so the exemption cannot swallow every
failed request on the page.

Keep that list narrow. A broad `/error/i` filter would have permanently hidden the
`X-Frame-Options` error these checks exist to surface — it sat in that channel on every
page load until it was found by exactly this assertion.

| Script | Checks | In repo |
|---|---|---|
| `lib/browser.js` | Chromium resolution; throws naming every path searched | yes |
| `lib/serve.js` | Static server for `out/`, resolves `trailingSlash`, or honours `BASE` | yes |
| `animcheck.js` | Rotation reflow at 21 viewports on all four surfaces, animation-family transition parity, word widths, console errors — 20 assertions | yes |
| `contactcheck.js` | Card and `#cl-title` vs the fixed header at 4 viewports, in-frame Google controls with a click hit-test, keyless-embed tile canary — 13 assertions | yes |
| `typecheck.js` | Every visible h1/h2/h3 on all 15 public routes at 2 widths; per-page consistency, the de-facto 40px rung, the contract gap — 3 assertions | yes |
| `verify.js`, `fontcheck.js`, `signprobe.js`, `navprobe.js` | Nav labels/hrefs, type ladder, Authenticator tree, nav row colours | **lost with `/projects/pwtest`** |
| `check.js`, `langbar.js`, `authcheck.js`, `ordercheck.js` | Viewport overflow, language restore, sign-in badge order | **lost** |

The lost ones are a description of what to write, not of what exists. Rewrite them under
`tools/browser/` so they stop evaporating.

**Both in-repo harnesses have known failures, left failing on purpose** rather than tuned
green — the same convention the old `langbar.js` note used:

- `animcheck.js` — **4 failures**, all the `/grahak-os/` and `/vayulok/` hero reflow.
- `contactcheck.js` — **1 failure**, the three live Google map controls.
- `typecheck.js` — **2 failures**, the section-h2 rung decision and `.gos-closer-head`.

Both are owner decisions, described under "Needs the owner". Nothing else is red.
`langbar.js`'s old known failure — "no console errors", caused by the `X-Frame-Options`
meta tag — is **fixed at the source**: that tag is gone and all four public pages now
measure zero console errors.

When writing new browser checks: compare the **rects** returned by
`getBoundingClientRect`, not DOM elements, and **scope selectors**. Both mistakes
produced false failures here — `document.querySelector('input')` matched the header's
new nav search field, not a sign-in field.

## Running it locally (Windows / PowerShell 5.1)

PowerShell 5.1 has no `&&`; run these as separate lines.

```powershell
cd C:\Users\wecar\bharat-stack
git checkout feat/grahak-os-trust-a-i
git checkout -- package-lock.json     # see the trap below
git pull origin feat/grahak-os-trust-a-i
git log --oneline -1                  # MUST print the expected commit
npm ci
Remove-Item -Recurse -Force .next
npm run dev
```

Then `http://localhost:3000/grahak-os/` — **trailing slash required**.

Three things that have each wasted a full round trip:

1. **`git pull` aborts if `package-lock.json` is locally modified** (`npm install`
   leaves it that way) and prints `Aborting` in a wall of output. The pull silently
   does nothing and you keep running old code. **Always confirm with
   `git log --oneline -1` after pulling.**
2. **`Remove-Item ... -ErrorAction SilentlyContinue` hides its own failure.** On
   Windows the delete fails while a `node` process holds `.next` open. Stop the dev
   server first (`Ctrl+C`, then `Stop-Process -Name node -Force`).
3. **If an old `next dev` still holds port 3000**, the new one starts on **3001**
   while 3000 keeps serving the old build. Read the port it prints.

Fastest check that you are on this branch: **`http://localhost:3000/vayulok/`**. That
page does not exist on `stack`, so a 404 means the pull did not land.

The dev service worker no longer needs Ctrl+Shift+R — `_app.tsx` unregisters workers
and clears caches outside production. But a worker installed *before* that fix can
still replay a stale bundle, and the code that removes it lives inside the bundle it
is replaying; one hard reload breaks that loop permanently.

## Design contract

`.kiro/steering/grahak-os-design.md`, scoped to `src/pages/grahak-os/**`,
`src/components/**`, `src/styles/**`. Load-bearing points:

- Section `h2` (700) is deliberately **heavier** than the hero `h1` (600).
- Exactly **one** body level: 20px/400.
- Card-heading rung is **22px/700** — `.pp-strip-title`, `.trust-wordmark`.
- Lime `#d1f470` is for **our own surfaces only** — never on a third-party mark, which
  is why the Meta card stays neutral while the brand badge is full lime.
- Hairlines: 2px = hoverable, 1px = static, always `#e5e7eb`.
- Retired, do not reintroduce: `#2f6b52`, `#075e54`, `#f2fbf6`, `#fbfff0`, `#1e293b`.
- Inter is loaded at **400;500;600;700;800**. There is no 300 face — asking for one
  gets a synthesised weight.
