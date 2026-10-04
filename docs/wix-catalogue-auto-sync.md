# Wix catalogue auto-sync (B2)

Adding, editing or removing a product in Wix updates the live shop - the product list and the
product pages - without anyone refreshing a snapshot. Design: `.agents/tasks/wix-catalog-auto-sync-b2.md`.

## What it replaces

`src/content/wix-catalog.json` is a COMMITTED snapshot, read at build time by
`src/content/shop.ts`. `next.config.js` is `output: 'export'`, so there is no server of ours at
runtime and the shop is pre-generated HTML - which is where its SEO comes from. B2 keeps that and
automates the REBUILD instead of moving the shop to a client-side fetch.

Before: a product created in Wix did not appear until a human ran
`scripts/fetch-wix-catalog.js`, committed it, and let Amplify redeploy. Measured 2026-10-04:
`1-test-product` and `contribute` were live in Wix and absent from the site, and
`/shop/1-test-product/` was a 404.

## The two paths

| | Latency | Needs | Status |
|---|---|---|---|
| **Scheduled** `.github/workflows/catalogue-sync.yml` | up to 6 hours | nothing | ✅ LIVE |
| **Webhook** `wecare-wix-catalog-webhook` -> `repository_dispatch` | seconds | owner registration + a public key | ⏳ WAITING_FOR_OWNER |

**The scheduled job is the mechanism, not the fallback.** It needs no credential, no AWS role and
no provider registration: `scripts/fetch-wix-catalog.js` mints an anonymous VISITOR token from the
PUBLIC `WIX_CLIENT_ID` in `src/config/wix.ts` and reads the storefront catalogue with it. So
auto-sync works today, with the webhook unregistered. The webhook only makes it near-instant.

### What the scheduled job does

1. `cp src/content/wix-catalog.json $RUNNER_TEMP/catalogue-before.json`
2. `node scripts/fetch-wix-catalog.js` - rewrites the snapshot, including per-product variant ids
   from `/stores/v3/products/query-variants`. Dies and writes NOTHING on 0 products or a failed
   variants call.
3. `node scripts/catalogue-diff.js <before> <after>` - did the catalogue actually change?
4. If it did: `git commit --only src/content/wix-catalog.json` and push to `stack`.
5. Branch `stack` has `enableAutoBuild: true` on Amplify app `d22dm4b0jn71jw`, so the push starts
   the production build. New slug -> new `/shop/<slug>/` page.

#### Why step 3 exists

`fetch-wix-catalog.js` restamps `fetchedAt` and `variantVerifiedAt` on EVERY run, so
`git diff --quiet` is dirty on every run even when Wix returned byte-identical products. Branching
on `git diff` would commit four times a day with nothing in it and trigger four production builds.
`catalogue-diff.js` ignores exactly those two fields, compares every other field of every product
by deep equality (key-order insensitive, because Wix does not promise a stable serialisation
order), and reports added / removed / modified slugs. `src/test/CatalogueDiff.test.ts` pins both
directions: a timestamp-only refetch is no change, and a new product is.

#### The two refusals

| Guard | Where | Why |
|---|---|---|
| 0 products -> write nothing | `fetch-wix-catalog.js` | an empty catalogue is far likelier a scope or query problem than a real change |
| more than half the catalogue removed -> fail, do not commit | `catalogue-sync.yml` | that is what a changed OAuth client or a site-wide visibility edit looks like; committing it would unpublish those pages in one build |

The second is overridable, deliberately and with a record:
`gh workflow run catalogue-sync.yml -f allow_large_removal=true`.

## Route registration is PREFIX-BASED, so a new product needs no code edit

This is the property the whole feature rests on, verified 2026-10-04 by building the export:

| Surface | How it registers | Covers a new slug? |
|---|---|---|
| `src/pages/shop/[slug].tsx` | `getStaticPaths` maps over `SHOP_PRODUCTS` | yes |
| `scripts/generate-sitemap.js` | `PUBLIC_PREFIXES` contains `'/shop/'` | yes |
| `src/pages/_app.tsx` | `isContentPublic` keys on the `'/shop/[slug]'` PATTERN | yes |
| `config/public-pages.json` | product pages were never listed; the dynamic route is not a page entry | n/a |
| `scripts/provision_legacy_redirects.py` | three EXACT `/shop` index sources, never a `/shop/<*>` wildcard | unaffected |

**Evidence rather than assertion.** `npm run build` on the refreshed snapshot emitted
`out/shop/1-test-product/index.html` (41 kB) and 8 `/shop/` URLs in `out/sitemap.xml`.
`1-test-product` was created in Wix after every one of those files was written, and nothing was
hand-edited to let it through.

**One per-slug list existed and was removed.** `src/test/ShopCatalogue.test.tsx` pinned an explicit
eight-slug literal. It is now derived from the snapshot with a LOWER-BOUND floor of 6 - which keeps
the blank-catalogue protection the literal was defending (a derived check cannot pass on an empty
array while the floor must also hold) while costing no hand edit when a product is added. Two more
tests in the same file pinned one product's PRICE and one product's TAGLINE; both now assert the
pass-through property against the raw snapshot row, for every product, so an owner editing copy or
a price in Wix cannot turn CI red.

`tests/test_wix_catalog_snapshot.py` was relaxed the same way: it required EVERY product to carry a
description, and a product with no description is a real shape - it is how a Wix product looks
before anybody writes copy for it. `src/content/shop.ts` synthesises a safe name-based tagline and
body for that case, which is why `/shop/1-test-product/` renders a complete page and a valid meta
description today. The catalogue-wide failures that test was written against (an empty projection,
Ricos JSON instead of HTML) still fail it.

## The contribution product stays in the snapshot

`contribute` (`af326b8c-f373-45ea-ad0d-b7a38b8ce0cc`) must remain a snapshot row: the blog and
VayuLok contribution blocks resolve it through `CONTRIBUTION_PRODUCT` and `CONTRIBUTION_RAW` in
`src/content/shop.ts`. The sync does not drop it and must never be made to - only the shop LISTING
excludes it, by product id first and slug second, so it has no `/shop/contribute/` page and no
sitemap entry. Verified on the refreshed snapshot: the product id is present once in
`wix-catalog.json`, and `shop/contribute` appears 0 times in `out/sitemap.xml`.

## The webhook receiver

`amplify/functions/ecommerce/wix-catalog-webhook/handler.py`, verified by
`amplify/functions/shared/lambda_utils/ecommerce/wix_webhook.py`.

| | |
|---|---|
| Endpoint | `https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/wix-catalog-webhook` |
| Route | `POST /wix-catalog-webhook`, `AuthorizationType=NONE`, no authorizer |
| Verification | the request BODY is an RS256 JWT signed by Wix; verified against the app's PUBLIC key |
| Secret | `wecare/wix/catalog-webhook`, fields `public_key` and (optionally) `app_id` |
| Then | `POST https://api.github.com/repos/<repo>/dispatches` with `{"event_type":"wix-catalogue-changed"}` |
| Token | `wecare/github-pat`, field `token`, read BY REFERENCE at request time |
| Role | `wecare-wix-catalog-webhook-role` - those two secret reads and its own log group, nothing else |
| Layer | `cryptography-python312:1` |

It does not call Wix, does not touch DynamoDB, does not import the catalogue, and does not inspect
which product changed. A verified Wix event means "re-read the catalogue", and re-reading is right
whatever the event said - so a change in Wix's envelope shape costs a log field and can never cost
a missed sync or an unauthenticated rebuild. `tests/test_wix_catalog_webhook.py` asserts that on
the AST: the receiver may not reference `dynamodb`, `wixapis.com`, `put_item`, `start_job` or
`fetch-wix-catalog` in code.

### Why a GitHub dispatch and not an Amplify `StartJob`

`StartJob` would rebuild the CURRENT commit, which still carries the stale snapshot - so the site
would redeploy unchanged. The snapshot has to be refreshed and committed first, and the thing that
can do that is the GitHub workflow. The cost is recorded: this needs a GitHub token, where
`amplify:StartJob` would have needed no credential at all.

### It ships refusing everything, and that is correct

`wecare/wix/catalog-webhook` does not exist, so `verify_signature` raises "no usable public key is
configured" and the handler answers **401 with an empty body**. Every rejection path is tested with
the assertion that NO dispatch was attempted - not merely that the status was 401 - because each
accepted call starts an Amplify build, so an endpoint that rebuilds on an unauthenticated POST is a
free denial-of-wallet.

### A burst collapses at GitHub, not here

Ten edits in a minute produce ten dispatches. There is no dedup table, on purpose: the workflow's
`concurrency: catalogue-sync` with `cancel-in-progress: false` keeps one run going and at most one
queued, superseding the older queued one.

## WAITING_FOR_OWNER

Two steps, both owner-only. Neither blocks auto-sync - the six-hourly cron already covers it.

**1. Register the webhook in Wix.** Wix webhooks belong to a Wix APP, not to a site, so this needs
an app in the [Wix app dashboard](https://dev.wix.com/) with the site installed on it:

- Webhook category: **Wix Stores / Catalog**, events **Product Created**, **Product Updated**,
  **Product Deleted** (V3 catalogue; the names may read `wix.stores.catalog.v3.product_*`).
- Callback URL: `https://zllr9lrg7j.execute-api.us-east-1.amazonaws.com/prod/wix-catalog-webhook`
- On the app's Webhooks page, copy the **public key** (also reachable from the app home page under
  *More Actions -> View ID & keys*) and the **App ID**.

**2. Put the key in Secrets Manager.** Create `wecare/wix/catalog-webhook` as a JSON secret with
`public_key` (the PEM, newlines intact) and `app_id`. Do this through the console or an
`asm-exec`-style by-reference path - **never** with the value on a command line, per
`.kiro/steering/secret-handling.md`. The agent will not create it: reading or writing a provider
credential is a standing refusal.

The `app_id` is optional in the verifier and should still be set. Without it the `aud` check is
skipped; with it, a token signed by the right key but aimed at another app is refused too.

Then confirm:

```
python scripts/provision_wix_catalog_webhook.py --verify
```

## Operating it

```
gh workflow run catalogue-sync.yml                                  # sync now
gh workflow run catalogue-sync.yml -f allow_large_removal=true       # override the removal guard
node scripts/fetch-wix-catalog.js                                    # refresh the snapshot locally
node scripts/catalogue-diff.js <before.json> <after.json>            # did it change?
python scripts/provision_wix_catalog_webhook.py --verify              # the receiver's live state
```

If a sync commit ever lands on `stack` with no Amplify build following it, check that first: a push
made with `GITHUB_TOKEN` does not start other GitHub Actions workflows (a documented GitHub
restriction) but does deliver the push webhook to the Amplify GitHub App. `deps-upgrade.yml` has
relied on exactly this since before B2 - its commit step is named "(triggers Amplify deploy)".

## Related

- `.agents/tasks/wix-catalog-auto-sync-b2.md` - the design
- `.kiro/steering/lambda-snapstart-deploy.md` - why a receiver code change is not live until the
  `live` alias moves
- `.kiro/steering/secret-handling.md` - why the public key arrives by reference
