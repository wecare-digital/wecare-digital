# Wix catalogue sync + Dependabot alerts — diagnosis and resolution

Run date 2026-10-09. Branch `stack`, repo `wecare-digital/wecare-digital`, AWS account
775261844268 / us-east-1. Iteration: FIRST (no `dep-wix-review-gate.json` existed).

Scope: the two gated items from the deep audit — F-008 (Wix catalogue sync failing, P1) and
F-016 (Dependabot alerts). This is a focused diagnose-and-fix pass, not a re-audit.

Repo state during this run: HEAD and `origin/stack` both at **`118aa93e`**. All AWS calls were
read-only. No secret value was read, printed or logged; secrets are referenced by key name only.

> **Concurrency note.** Another session was committing and pushing to `stack` throughout this
> run. `HEAD` moved three times under me (`9d91c4e1` → `74a9d42d` → `b5b6c588` → `7bd014b1` →
> `118aa93e`). Two consequences are recorded in place below: the Handlebars fix for Issue 2 was
> landed by that session, not by me; and `amplify/package-lock.json` is foreign-modified in the
> shared working tree, so I did not stage it (F-017 ownership rule).

---

## Summary

| Item | Root cause | Classification | Disposition |
|---|---|---|---|
| Issue 1 — Wix catalogue sync | Genuine owner-side catalogue change: the 12 Wix **template sample** products were deleted from the Wix store. No code, auth, pagination or visibility defect. | n/a (not a vulnerability) | **BLOCKED — owner action.** No in-repo fix is correct. |
| Issue 2 — handlebars ×3 (GHSA-p8wg-vrv2-v86f crit, GHSA-8r5x-fm3f-whwj crit, GHSA-xw65-4hp5-5hc7 med) | `@aws-amplify/graphql-docs-generator` → `handlebars@^4.7.9` resolved to 4.7.9 | **BUILD-ONLY** | **FIXED** in `74a9d42d` (another session), pushed. Alerts auto-closed. Install-verified by me. |
| Issue 2 — `@graphql-tools/utils` (GHSA-7mx3-vvmw-hjmv, high) | appsync-modelgen / graphql-codegen chain pins majors 6/7/9; patch is 12.0.1 | **BUILD-ONLY** | **REVIEW_REQUIRED.** Exact override given; 3–6 major jumps, serves 0 live AppSync APIs. Not applied. |
| Issue 2 — `braces` (GHSA-vfj7-8cjw-p6xm, high) | `micromatch` → `braces@^3.0.3`; no patched version exists anywhere | **BUILD-ONLY** (amplify) / **DEV-ONLY** (root, already auto-dismissed) | **BLOCKED-UPSTREAM.** Nothing to upgrade to. |

Open Dependabot alerts went from **5 (2 crit, 2 high, 1 mod)** at the start of this run to
**2 (both high)** — the three Handlebars alerts are now `state=fixed`.

---

# ISSUE 1 — Wix catalogue sync failing (P1)

## Verdict

**The guard is working correctly, and the thing it caught is a genuine owner-side catalogue
edit, not a fault.** The live Wix catalogue really does contain 10 products. The committed
snapshot's 22 is the stale number, and 12 of those 22 are the Wix store template's own demo
products which this repo already refuses to publish.

There is **no code defect to fix** in the fetch script, the diff script or the workflow. I
changed none of them.

## ⛔ Guard-weakening prohibition (stated explicitly, as required)

I did **not**, and no one should as a shortcut to a green workflow:

- weaken or delete the "Refuse a mass disappearance" step in `.github/workflows/catalogue-sync.yml`;
- lower the `>50%` (`gone > before / 2`) threshold;
- set, default, or pass `allow_large_removal=true` from automation;
- make the guard skip instead of fail (silence there is indistinguishable from "nothing changed");
- touch the zero-products guard or the variants guard in `scripts/fetch-wix-catalog.js`.

Invoking `allow_large_removal=true` is a **deliberate human act with the reason in the run log**,
which is how the workflow author designed it. It is an owner decision, taken below as the unblock
step — not something this pass performed.

## Where the refusal happens, and the exact threshold

`.github/workflows/catalogue-sync.yml`, step **"Refuse a mass disappearance"** (runs when
`steps.diff.outputs.changed == 'true'` and `inputs.allow_large_removal != true`):

```bash
gone=$(printf '%s' "$removed" | tr ',' '\n' | grep -c . || true)
before=$(jq '.products | length' "$RUNNER_TEMP/catalogue-before.json")
if [ "$gone" -gt $(( before / 2 )) ]; then   # strict >, integer division
  echo "::error::$gone of $before products disappeared ..."
  exit 1
fi
```

`removed` comes from `scripts/catalogue-diff.js`, which keys products **by slug** and emits
`removed` as the slugs present in `before` and absent from `after`. The threshold is therefore
`gone > floor(before/2)` — with `before=22` the trip point is `gone >= 12`.

Observed: **`gone=12`, `before=22`** → `12 > 11` → refuse. It cleared the bar by exactly one
product.

## Evidence from the real failing CI runs

`gh run list --workflow=catalogue-sync.yml -L 20` → **16 failures, 4 cancelled, 0 successes**.
Latest run `37859673823` (schedule, 2026-10-08T23:28:58Z); the failures run back through many
`repository_dispatch` runs from the Wix webhook on 2026-10-08.

`gh run view 37859673823 --log-failed`:

```
removed=12 of 22
##[error]12 of 22 products disappeared from Wix in one fetch (baseball-cap,
ceramic-flower-vase,crew-t-shirt,essential-oil-diffuser,foaming-facial-cleanser,
hydrating-eye-serum,knitted-golf-sweater,minimalist-tote-bag,round-eyeglasses,
solid-wood-chair,stainless-steel-water-bottle,textured-loop-earrings). Refusing to commit...
```

Run `37857668884` is byte-identical in outcome — same 12 slugs, same counts.

The **fetch step itself succeeded** in the same run, which is the single most important fact
here. `gh run view 37859673823 --log`, step "Read the live Wix catalogue":

```
fetch-wix-catalog: wrote 10 product(s) to src/content/wix-catalog.json
  1-test-product             ₹1.00  PHYSICAL  opts=0 variants=1/1  media=0 info=0
  contribute              ₹100.00+  PHYSICAL  opts=1 variants=3/3  media=0 info=0
  file-assist            ₹6,999.00  PHYSICAL  opts=0 variants=1/1  media=0 info=10
  guided-resolution     ₹13,999.00  PHYSICAL  opts=0 variants=1/1  media=0 info=11
  kiosk                 ₹24,999.00  PHYSICAL  opts=0 variants=1/1  media=0 info=10
  merchandise            ₹1,199.00  PHYSICAL  opts=2 variants=10/10 media=0 info=8
  paperwork              ₹3,499.00  PHYSICAL  opts=0 variants=1/1  media=0 info=9
  referral-partner         ₹999.00  PHYSICAL  opts=0 variants=1/1  media=0 info=7
  viveka                   ₹599.00  PHYSICAL  opts=0 variants=1/1  media=0 info=7
  wecaredigital-services     ₹49.00+  PHYSICAL  opts=1 variants=4/4  media=2 info=0
```

No HTTP error, no `(HIDDEN)` marker on any row, and `variantCount/variants.length` agree on
every product (`1/1`, `3/3`, `10/10`, `4/4`) — so the variants endpoint answered too. A broken
credential or a scope change cannot produce this output.

## Local read-only re-verification

`scripts/fetch-wix-catalog.js` has **no `--dry-run` / probe mode** (no `process.argv` handling at
all) — running it unconditionally overwrites `src/content/wix-catalog.json`. So I did **not** run
it. Instead I wrote a throwaway read-only probe in `.scratch/` that mints the same anonymous
visitor token from the same public `WIX_CLIENT_ID` and issues the same two calls, reporting counts
only. `git status --short -- src/content/wix-catalog.json` was empty afterwards: the snapshot was
never touched.

```
oauth2/token HTTP 200
visitor token minted: yes (value not printed)
limit=100 page1 count=10 pagingMetadata={"count":10,"cursors":{},"hasNext":false}
limit=100 -> TOTAL 10 product(s) over 1 page(s)
slugs: 1-test-product, contribute, file-assist, guided-resolution, kiosk, merchandise,
       paperwork, referral-partner, viveka, wecaredigital-services
visible===false: (none)
limit=10  -> TOTAL 10 product(s) over 1 page(s)
limit=5   -> TOTAL 10 product(s) over 2 page(s)   # cursor followed correctly
products/slug/baseball-cap           -> HTTP 404 NOT_FOUND
products/slug/crew-t-shirt           -> HTTP 404 NOT_FOUND
products/slug/textured-loop-earrings -> HTTP 404 NOT_FOUND
```

**Live fetch = 10. Committed snapshot = 22.** (`src/content/wix-catalog.json`: `productCount: 22`,
`fetchedAt: 2026-10-06T04:43:35.265Z`.)

## Root-cause classification

Each candidate cause, against the evidence:

| Candidate | Ruled out by |
|---|---|
| Expired / invalid `WIX_CLIENT_ID`, or headless OAuth token failure | `POST /oauth2/token` → **HTTP 200**, visitor token minted, and the catalogue read succeeded with it. The script's own `die()` on a token failure never fired. |
| Headless app deauthorized in Wix | Same: a deauthorized client cannot mint a visitor token, and cannot return 10 fully-hydrated products with variants. |
| Product visibility flipped to hidden/draft | `visible === false` on **zero** rows. The CI log shows no `(HIDDEN)` marker. The three sampled vanished slugs return `404 NOT_FOUND` ("Entity not found"), not a hidden row. |
| Pagination / cursor bug truncating results | `PAGE_SIZE = 100` in `fetch-wix-catalog.js`, and at `limit=100` Wix itself reports `count:10, cursors:{}, hasNext:false` — there is no next page to lose. My probe mirrors the script's cursor loop exactly and at `limit=5` correctly walks **2 pages to reach all 10**, proving the loop terminates on `hasNext`/empty-cursor rather than truncating. 10 ≪ 100. |
| **Genuine owner-side catalogue change** | **CONFIRMED — see below.** |

### Why it is a genuine catalogue change

The 12 "removed" slugs are not arbitrary. `git log --follow src/content/wix-catalog.json` shows
the same 12 **arriving together** in one automated sync, three days before they left:

| Commit | When | `productCount` | What |
|---|---|---|---|
| `87c8ba52` | 2026-10-04 20:25 +0530 | **9** | the real WECARE catalogue |
| `11367306` | 2026-10-05 15:04 UTC | **21** | `github-actions[bot]`: *added* baseball-cap, ceramic-flower-vase, crew-t-shirt, essential-oil-diffuser, foaming-facial-cleanser, hydrating-eye-serum, knitted-golf-sweater, minimalist-tote-bag, round-eyeglasses, solid-wood-chair, stainless-steel-water-bottle, textured-loop-earrings |
| `7e2fdb81` | 2026-10-06 04:43 UTC | **22** | added `wecaredigital-services` |
| *(now)* | 2026-10-08 → | *(10)* | those same 12 are gone; `22 − 12 = 10` = the 9 originals + `wecaredigital-services` |

And the repo already names them, in `src/content/shop.ts`:

> *"**THE WIX TEMPLATE'S OWN SAMPLE PRODUCTS, which are not this storefront.** Owner decision,
> 2026-10-05 … The new site was created from a Wix store template, so it shipped with twelve demo
> products already in its catalogue … the snapshot went from 9 products to 21."*

`WIX_TEMPLATE_SAMPLE_PRODUCT_IDS` (12 ids) and `WIX_TEMPLATE_SAMPLE_SLUGS` (12 slugs) list exactly
the 12 slugs now reported as removed.

**Root cause: the Wix store template's 12 demo products, which were seeded into site
`c993128b-26be-41cd-9fcd-904abe23462f` when it was created from a template and auto-synced into
the snapshot on 2026-10-05, have since been deleted from the Wix catalogue. The fetch returning 10
is the correct current state of the store.**

Honest limit on the evidence: a visitor token cannot see hidden products, so `404 NOT_FOUND`
alone cannot distinguish *deleted in Wix* from *hidden in Wix*. The git history above, plus the
fact that the vanished set is exactly the documented template-sample set, is what settles it.
Either way the disposition is identical — the owner confirms intent, and neither case is a repo bug.

## Blast radius — the guard's stated premise does not hold for these 12 slugs

The guard's error says committing *"would unpublish those `/shop/<slug>/` pages"*. For **these 12
specific slugs that is not true**, because `src/content/shop.ts` already excludes all 12 from
`SHOP_PRODUCTS` by product id **and** by slug via `isTemplateSampleRow`, and `getStaticPaths` in
`src/pages/shop/[slug].tsx` enumerates `SHOP_PRODUCTS`. They were never published.

Verified against the live site:

```
https://wecare.digital/shop/baseball-cap/  -> 404
https://wecare.digital/shop/crew-t-shirt/  -> 404
https://wecare.digital/shop/merchandise/   -> 200
```

And computed over the committed snapshot, applying `shop.ts`'s own filters
(`visible !== false`, has slug, has name, minus contribution row, minus services row, minus
template samples):

```
committed snapshot rows: 22
SHOP_PRODUCTS now   (8): 1-test-product, file-assist, guided-resolution, kiosk,
                         merchandise, paperwork, referral-partner, viveka
SHOP_PRODUCTS after (8): 1-test-product, file-assist, guided-resolution, kiosk,
                         merchandise, paperwork, referral-partner, viveka
IDENTICAL: True
FLOOR=6 satisfied after refresh: True     # FLOOR in src/test/ShopCatalogue.test.tsx:127
```

**Accepting the removal changes `SHOP_PRODUCTS` by zero products and removes zero live pages.** It
also stays above the `FLOOR = 6` lower bound that `src/test/ShopCatalogue.test.tsx` enforces, so
the test suite would not regress.

This does **not** make the guard wrong. The guard cannot know that `shop.ts` filters those slugs —
it compares raw snapshot rows, which is the right thing for a guard to do, and on any other 12
products the refusal would have saved 12 live pages.

## Disposition — BLOCKED, owner action

Not fixable from this repo and nothing here should change. The sync will keep failing every 6
hours (cron `25 */6 * * *`) plus on every Wix webhook dispatch until the owner acts.

**Key-holder: the repo/Wix owner (WECARE.DIGITAL).** Exact unblock steps, in order:

1. **Confirm intent in the Wix dashboard.** Wix → Store Products, for site
   `c993128b-26be-41cd-9fcd-904abe23462f`. Confirm the catalogue now holds **10** products and
   that the 12 template demo products (Baseball Cap, Ceramic Flower Vase, Crew T-Shirt, Essential
   Oil Diffuser, Foaming Facial Cleanser, Hydrating Eye Serum, Knitted Golf Sweater, Minimalist
   Tote Bag, Round Eyeglasses, Solid Wood Chair, Stainless Steel Water Bottle, Textured Loop
   Earrings) were deliberately deleted and are not merely hidden or in draft.
   - If the deletion was **accidental**, restore them in Wix instead and the next scheduled run
     goes green on its own with no repo change.
2. **If deliberate — accept the removal once, by hand.** Actions → "Wix catalogue sync" →
   *Run workflow* on branch `stack` with **`allow_large_removal` = true**. This is the designed
   human override and it records the reason in the run log. It commits the 10-product snapshot to
   `stack` and that push triggers the Amplify production build on app `d22dm4b0jn71jw`.
   - User-visible effect: **none on `/shop/`** — `SHOP_PRODUCTS` is identical (8 products, proven
     above) and all 12 removed slugs already 404. The snapshot's `productCount` drops 22 → 10 and
     the stale demo rows leave the committed file.
   - This must be done by the owner, not by automation, and `allow_large_removal` must stay
     `default: false`.
3. **Optional follow-up, owner's call, NOT done here.** Once the snapshot is back in sync, the
   12 now-dead entries in `WIX_TEMPLATE_SAMPLE_PRODUCT_IDS` / `WIX_TEMPLATE_SAMPLE_SLUGS` in
   `src/content/shop.ts` become redundant. The code comment deliberately keeps them *"so the
   exclusion survives a product being re-created in Wix"*, so leaving them is the safer default.
   No change made.

### Parked proposal, deliberately NOT implemented

A reviewer may ask why the guard is not taught to ignore removals of slugs already excluded by
`WIX_TEMPLATE_SAMPLE_SLUGS` — a removal that cannot unpublish a page arguably should not count
toward the 50% threshold. That would make this class of failure self-clearing. I did not do it:
it changes the behaviour of a safety guard, it narrows what the guard counts, and it sits squarely
inside the "do not weaken the guard" prohibition. **Recording it as an option for the owner, not a
recommendation acted on.**

---

# ISSUE 2 — Dependabot alerts

## Full current alert set

`gh api repos/wecare-digital/wecare-digital/dependabot/alerts --paginate` returned 73 alerts
total; 5 were open when this run started (matching the reported 2 critical / 2 high / 1 moderate),
and 2 are open now.

| # | Sev | Package | GHSA / CVE | Manifest | Scope | Vulnerable range | Patched | In ROOT lock? | Reach | State |
|---|---|---|---|---|---|---|---|---|---|---|
| 72 | critical | handlebars | GHSA-8r5x-fm3f-whwj / CVE-2026-106446 | `amplify/package-lock.json` | runtime | `>= 4.0.0, <= 4.7.9` | **4.7.10** | **No** (0 entries) | BUILD-ONLY | **fixed** 2026-10-08T23:40:35Z |
| 71 | critical | handlebars | GHSA-p8wg-vrv2-v86f / CVE-2026-106445 | `amplify/package-lock.json` | runtime | `>= 4.0.0, <= 4.7.9` | **4.7.10** | **No** | BUILD-ONLY | **fixed** 2026-10-08T23:40:35Z |
| 73 | medium | handlebars | GHSA-xw65-4hp5-5hc7 / CVE-2026-106444 | `amplify/package-lock.json` | runtime | `>= 4.0.0, <= 4.7.9` | **4.7.10** | **No** | BUILD-ONLY | **fixed** 2026-10-08T23:40:35Z |
| 63 | high | `@graphql-tools/utils` | GHSA-7mx3-vvmw-hjmv / CVE-2026-104852 | `amplify/package-lock.json` | runtime | `<= 12.0.0` | **12.0.1** | **No** (0 entries) | BUILD-ONLY | **open** |
| 61 | high | braces | GHSA-vfj7-8cjw-p6xm / CVE-2026-93687 | `amplify/package-lock.json` | runtime | `<= 3.0.3` | **none** | yes, but `dev: true` | BUILD-ONLY | **open** |

Context rows, for completeness — not part of the 5:

- **#62** `braces` same GHSA against the **root** `package-lock.json`, `scope: development` —
  GitHub already set it `auto_dismissed`. Root path is `fast-glob → micromatch → braces@^3.0.3`,
  `dev: true`. **DEV-ONLY.**
- **#55 / #56 / #57** `brace-expansion` (amplify) were dismissed on 2026-09-30.
- Everything else in the 73 is `fixed` (next, axios, tar, source-map-js, uuid, lxml, PyJWT,
  oauthlib, mysql2, csv-parse, @opentelemetry/core).

Note on the `scope: runtime` label: GitHub derives it from the **amplify** manifest, where
`@aws-amplify/backend` is a `dependencies` entry. It does **not** mean "reaches production" — see
the reachability proof below.

## Reachability — why every amplify alert is BUILD-ONLY

Three independent facts, each verified in this run:

1. **The deployed Lambdas are Python.** 81 `handler.py` files under `amplify/functions/`.
   First-party amplify source (excluding vendored `node_modules`) declares exactly one runtime:
   `Runtime.PYTHON_3_12` (2 occurrences, 0 `NODEJS_*`), and `resource.ts` entries point at
   `entry: './handler.py'`. `find amplify/functions -name node_modules` returns nothing — no node
   tree is packaged into any function bundle.
2. **`amplify/` is a deploy-time install root, not a shipped artifact.** Its `package.json`
   describes itself as the *"Amplify Gen 2 backend definition"*, a *"SEPARATE INSTALL ROOT from
   the web app on purpose"*, with only `sandbox` (`ampx sandbox`) and `deploy`
   (`ampx pipeline-deploy`) scripts. Its entire manifest is 3 runtime deps
   (`@aws-amplify/backend`, `aws-cdk-lib`, `constructs`) + 1 devDep (`@aws-amplify/backend-cli`).
   These synthesise CloudFormation at deploy time; they are not bundled into any artifact.
3. **The web app ships a static export.** `next.config.js` sets
   `output: process.env.NODE_ENV === 'production' ? 'export' : undefined` — the artifact is
   pre-rendered HTML/JS, with no `node_modules`. And the **root** lockfile contains **zero**
   entries for `handlebars` and **zero** for `@graphql-tools/utils`; its only `braces` entry is
   `dev: true`.

Reverse-dependency paths in `amplify/package-lock.json` at `origin/stack`:

```
handlebars            <- @aws-amplify/graphql-docs-generator -> handlebars@^4.7.9
braces                <- micromatch -> braces@^3.0.3
@graphql-tools/utils  <- @aws-amplify/appsync-modelgen-plugin   -> ^6.0.18   (6.2.4)
                      <- @graphql-codegen/visitor-plugin-common -> ^7.9.1    (7.10.0)
                      <- @aws-amplify/graphql-generator         -> ^9.2.1    (9.2.1)
                      <- @graphql-codegen/core                  -> ^9.1.1    (9.2.1)
                      <- @graphql-codegen/plugin-helpers        -> ^9.0.0    (9.2.1)
                      <- @graphql-tools/{merge,schema,relay-operation-optimizer} -> ^9.2.1
                      (plus 11.2.2 / 12.0.1 copies already at dev: true)
```

All three sit inside the Amplify **codegen / CLI** chain. None is imported by first-party
application code.

## handlebars ×3 — FIXED (by the concurrent session), verified by me

**Not my commit.** The concurrent session landed it mid-run:

- Commit **`74a9d42d`** — *"Patch critical Handlebars advisories and integrate retired credential
  guidance"*, 2026-10-09 05:10:22 +0530, committer WECARE.DIGITAL. Now on `origin/stack` (an
  ancestor of `118aa93e`), **pushed**.
- Change: `amplify/package.json` overrides gained `+    "handlebars": "4.7.10"`, and
  `amplify/package-lock.json` moved `handlebars` `4.7.9` → `4.7.10`.
- It is a clean in-range bump — the only requirer asks for `^4.7.9`, which already admits 4.7.10,
  so no consumer contract changes.
- **Alerts #71 / #72 / #73 are now `state=fixed`, `fixed_at=2026-10-08T23:40:35Z`** (confirmed via
  `gh api .../dependabot/alerts/{71,72,73}`). Dependabot closed them itself on rescanning `stack`.

I added nothing to this fix. What I did add is the **install verification it was missing**, because
the fix was committed without one: `amplify/node_modules/handlebars` on disk was still **4.7.9**
(the shared tree's install dates from 2026-10-08 21:17, before the commit), so the override had
never been materialised.

### Verification I ran (reviewer: these do not need re-running)

Done in a throwaway copy under `.scratch/`, never against the shared `amplify/` tree, because
`amplify/package-lock.json` is foreign-modified.

1. **Override is satisfiable / resolves correctly** — copied `amplify/package.json` +
   `amplify/package-lock.json` into `.scratch/amplify-verify/`:
   ```
   npm install --package-lock-only --no-audit --no-fund
     -> "up to date in 2s", exit 0
     -> resolved handlebars: [('node_modules/handlebars', '4.7.10')]
   ```
2. **Real install from the committed manifests + `ampx` still works** — `origin/stack` versions of
   both files into `.scratch/amplify-committed/`:
   ```
   npm install --no-audit --no-fund --ignore-scripts
     -> added 910 packages in 12s, exit 0
   node -e "require('./node_modules/handlebars/package.json').version"
     -> 4.7.10
   ls -l node_modules/.bin/ampx
     -> ampx -> ../@aws-amplify/backend-cli/lib/ampx.js   (resolves)
   npm exec -- ampx --version
     -> 1.10.0
   npm exec -- ampx --help
     -> full command surface intact (generate, sandbox, pipeline-deploy, deploy,
        configure, info, notices, secret)
   ```
   (`node .../ampx.js --version` invoked directly fails with
   `NoPackageManagerError: npm_config_user_agent environment variable is undefined` — that is
   ampx requiring invocation through npm, not a defect. Via `npm exec` it reports 1.10.0.)
3. **Repo gates at `118aa93e`** (shared tree, read-only commands):
   ```
   npm run lint       -> 191 problems (0 errors, 191 warnings)   PASS
   npm run typecheck  -> tsc --noEmit, no output                 PASS
   npx vitest run     -> Test Files 122 passed | 2 skipped (124)
                         Tests 1581 passed | 11 skipped (1592)   PASS
   ```

**Commit: `74a9d42d` (not mine). Pushed: yes, by the other session. Paths:
`amplify/package.json`, `amplify/package-lock.json` (+ unrelated docs/test paths in the same
commit).**

## `@graphql-tools/utils` GHSA-7mx3-vvmw-hjmv — REVIEW_REQUIRED, not applied

Prototype pollution in `mergeDeep`. High. Vulnerable `<= 12.0.0`, patched **12.0.1**
(`gh api /advisories/GHSA-7mx3-vvmw-hjmv`; no CVSS vector published).

Installed tree in `amplify/package-lock.json` — 12 copies:

| Version | Scope | Path |
|---|---|---|
| **6.2.4** | runtime | `node_modules/@graphql-tools/utils` (hoisted root copy) |
| **7.10.0** | runtime | `…/@graphql-codegen/visitor-plugin-common/node_modules/…` |
| **9.2.1** ×5 | runtime | under `@aws-amplify/graphql-generator`, `@graphql-codegen/core`, `@graphql-codegen/plugin-helpers`, `@graphql-tools/merge`, `@graphql-tools/relay-operation-optimizer`, `@graphql-tools/schema` |
| 11.2.2 ×2 | dev | under `@graphql-codegen/schema-ast`, `@graphql-codegen/typescript` |
| 12.0.1 ×2 | 1 dev / 1 runtime | `@graphql-tools/apollo-engine-loader`, `…/relay-operation-optimizer/…` — already patched |

**Exact override, if the owner accepts the risk** — in `amplify/package.json`:

```json
"overrides": {
  "@graphql-tools/utils": "12.0.1"
}
```
then `npm install --prefix amplify` (**not** `npm ci` — see the install-root note below).

**Breakage risk: HIGH, and asymmetric.** The override forces **3 to 6 major versions** at once on
consumers that pin old ranges: `@aws-amplify/appsync-modelgen-plugin` declares `^6.0.18`
(6 → 12), `@graphql-codegen/visitor-plugin-common` declares `^7.9.1` (7 → 12), and five more sit
at `^9.x` (9 → 12). `@graphql-tools/utils` has shipped majors 5 through 12, and npm resolves a
single exact override across every one of those edges. The realistic failure mode is `ampx`
synth breaking.

**Why not force it:** the vulnerable code serves **0 live AppSync APIs** —
`aws appsync list-graphql-apis --region us-east-1` returns **`[]`**, confirming the audit's
finding that `amplify/data/resource.ts`'s models are CODE_ONLY. So the override would protect a
GraphQL codegen path that executes against nothing in production, while risking the one tool
(`ampx pipeline-deploy`) that deploys all 81 Python Lambdas. Trading a live deploy path for a
build-time-only, zero-reachability advisory is the wrong direction, so this is parked rather than
applied.

**Key-holder: repo owner.** Unblock options: (a) accept as-is and dismiss the alert as
build-time-only with no deployed reach; (b) wait for `@aws-amplify/backend-cli` to carry
`@graphql-tools/utils >= 12.0.1` upstream (the clean exit — nothing to decide, it just resolves);
(c) apply the override above in a throwaway branch and prove `ampx pipeline-deploy --help` plus a
full `ampx sandbox` synth still succeed before merging.

## `braces` GHSA-vfj7-8cjw-p6xm — BLOCKED-UPSTREAM

Stack-exhaustion DoS through deeply nested patterns. High, published 2026-09-18.

**There is no patched version to move to.** Confirmed from two sources:

```
gh api /advisories/GHSA-vfj7-8cjw-p6xm
  -> vulnerable_version_range: "<= 3.0.3",  first_patched_version: null
npm view braces version        -> 3.0.3
npm view braces time           -> 3.0.3 published 2024-05-21  (latest release)
```

The newest `braces` on npm is 3.0.3, which is *inside* the vulnerable range. No override, no
`npm audit fix`, no lockfile bump can resolve this — the fix does not exist yet.

Paths: `amplify` → `micromatch → braces@^3.0.3` (**BUILD-ONLY**, inside the Amplify CLI chain);
root → `fast-glob → micromatch → braces@^3.0.3` with `dev: true` (**DEV-ONLY**, which is why
GitHub auto-dismissed #62).

**What to wait on, key-holder = upstream maintainer (`micromatch/braces`):** a `braces` release
above 3.0.3 carrying the recursion-depth fix, or a `micromatch` release that drops/replaces
`braces`. Then `npm install --prefix amplify` picks it up through the existing `^3.0.3` range
with no manifest change at all. Re-check with
`gh api /advisories/GHSA-vfj7-8cjw-p6xm -q .vulnerabilities[].first_patched_version`.
No repo change is possible or appropriate now.

## Ownership — `amplify/package-lock.json` NOT staged (F-017 honoured)

`git status --short` immediately before any consideration of touching it:

```
 M amplify/package-lock.json      <- foreign, uncommitted
```

Its uncommitted delta against `HEAD` is **91 added entries, 0 removed, 0 version changes** — all
nested bundled-dependency rows under `@aws-amplify/data-construct` (`@aws-cdk/toolkit-lib`,
`@aws-cdk/cloud-assembly-api`, `archiver`, `cdk-from-cfn`, …). It is `npm install` materialisation
churn, it is **security-neutral** (it changes the resolved version of no vulnerable package —
`handlebars` is 4.7.10 both before and after, `braces` 3.0.3, `@graphql-tools/utils` unchanged),
and the `pending-resolution-20261008/plan.md` from the prior pass records *"Ten foreign modified
paths preserved"*, which this file is one of.

**I did not stage it and made no change to it.** I also did not run `npm install --prefix amplify`
against the shared tree, which would have written to it. All my installs ran in `.scratch/` copies.

Intended change, had it been mine to make: none — it needs no security edit. Whoever owns that
delta should commit or discard it; it is **REVIEW_REQUIRED** for its owner, not a security item.

## Observation — `npm ci` in `amplify/` fails, and that is documented, not a regression

Surfaced while verifying, and worth recording so a reviewer does not read it as fallout from the
Handlebars fix. Against the **committed** `origin/stack` manifests in an isolated copy:

```
npm ci  ->  npm error code EUSAGE
            `npm ci` can only install packages when your package.json and
            package-lock.json ... are in sync.
            Missing: @aws-cdk/toolkit-lib@1.19.0, @aws-cdk/cloud-assembly-api@2.2.0,
            archiver@7.0.1, ... @opentelemetry/core@2.0.0 ...  (~100 entries)
```

This is expected. `docs/npm-ci-backend-isolation.md` states it outright: *"`npm ci` in `amplify/`
is still broken, and always will be while the upstream bundle is inconsistent — the defect moved
with the packages. Use `npm install` there."* The cause is Amplify packages shipping
`inBundle: true` OpenTelemetry copies with exact, mutually inconsistent `@opentelemetry/core@2.0.0`
pins; the doc records five attempted override strategies, all rejected. `amplify/package.json`'s
own description says the same.

So the supported verification path is `npm install --prefix amplify` (= `npm run amplify:install`),
which is what I used and which **succeeded** (910 packages, exit 0, `ampx 1.10.0`). Unaffected by
the Handlebars change. Incidentally the foreign working-tree lock reduces the `npm ci` mismatch
from ~100 missing entries to the 4 documented `@opentelemetry/core@2.0.0` ones — i.e. back to the
documented baseline — but that is the other session's work to land, not mine.

---

## What changed in the repo during this pass

**Nothing, other than this report.** No source file, workflow, manifest or lockfile was modified
by me:

- Issue 1 had no code defect, and the only resolution is an owner action in Wix / a human
  `workflow_dispatch` override. Touching the guard was prohibited and would have been wrong.
- Issue 2's one safe fix (handlebars) was already committed and pushed by the concurrent session
  as `74a9d42d`; I verified it rather than duplicating it. The other two alerts are
  REVIEW_REQUIRED and BLOCKED-UPSTREAM respectively, and neither has a safe non-breaking fix.

Committed by me: `.kiro/work/pending-resolution-20261008/dep-wix-findings.md` only, staged by
exact path with `git commit --only`.

Temporary artifacts under `.scratch/` (read-only Wix probe, two isolated amplify install copies,
alert JSON dumps) were deleted before finishing.
