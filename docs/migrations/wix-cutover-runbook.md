# Wix cutover runbook — the owner-gated production steps

Everything in `wix-removal-resolution-matrix.md` up to this point is BUILT, tested,
and merged behind flags that default to Wix. This runbook is the exact, ordered
set of PRODUCTION-MUTATING steps that finish the exit. **Each step is irreversible
or affects live commerce/payments; none is run automatically.** Do them in order —
the ordering is a safety property, not a preference.

Account 775261844268 · us-east-1 · Amplify `d22dm4b0jn71jw` · branch `stack`.

## Pre-flight (must all be true before step 1)
- [ ] PR #432 merged to `stack`, Amplify build green.
- [ ] A recent DynamoDB/account backup exists.
- [ ] `scripts/check-wix-policy.sh --expect-fail` still passes (Wix still live).

## Step 1 — Provision the native tables  🔒 billable
Wire `addCatalogResources`/`addCartResources` into `amplify/backend.ts` (one diff,
reviewed), then let the Amplify build create them. Creates
`stack-wecare-digital-ProductsTable` and `-CartTable` (PAY_PER_REQUEST, PITR,
RETAIN). Grant the checkout + meta-sync + seo roles read/write.
VERIFY: `aws dynamodb describe-table` shows both tables ACTIVE.
ROLLBACK: tables are RETAIN + empty; leaving them costs ~$0 (on-demand, no data).

## Step 2 — Seed from a live Wix export  🔒 reads live Wix + writes data
Run `python -m scripts.wix_export.export --live --out outputs/wix-export` (needs
Wix admin creds). Load blog → `SeoToolsTable` blogPost records and products →
`ProductsTable`, **preserving the Wix UUIDs as the product/variant ids** (the Meta
retailer-id contract requires UUIDs).
VERIFY: the reconciliation report shows `verdict: RECONCILED` for both blog and
store — exported counts == fresh authoritative Wix counts, zero checksum
mismatches, zero missing media. **Do NOT proceed on a DISCREPANCY.**
ROLLBACK: delete the seeded rows (tables are new; no live reader yet).

## Step 3 — Shadow-run (no customer impact)  🔒 compute-only
With flags STILL on Wix, compute the native total alongside the Wix total for live
carts and log both in paise. Run for several days. The native path must match the
Wix total paise-for-paise (or differ only by an explained, approved amount).
VERIFY: shadow logs show equality for every real cart. A mismatch is a bug to fix
BEFORE any flip, not after.
ROLLBACK: n/a (nothing changed).

## Step 4 — Migrate the gift-card pepper  🔒 credential op
Copy the `code_pepper` VALUE verbatim from `wecare/wix/giftcard-spi` into a new
`wecare/prod/security/giftcard-pepper`, then set `GIFTCARD_PEPPER_SECRET` on the
gift-card + invoice functions. The value MUST be identical (identical value →
identical card hash → no card is re-keyed).
VERIFY: a known test gift-card still resolves (`code_hash` unchanged); redemption
works end to end.
ROLLBACK: unset `GIFTCARD_PEPPER_SECRET` → falls back to the Wix SPI secret.

## Step 5 — Flip the read flags first  🔒 changes live behaviour
Set, one at a time, with a verify between each:
1. `CATALOG_SOURCE=aws` on meta-catalog-sync + the shop-snapshot build. Verify the
   Meta catalog + shop pages still show the right products/prices.
2. `BLOG_SOURCE=aws` on `wecare-seo-tools`. Verify `/blog`, `/post/<slug>`,
   sitemap, RSS are non-empty and correct, with no `wixapis.com` call.
ROLLBACK: set the flag back to `wix` (instant).

## Step 6 — Flip checkout LAST  🔒 changes live payments
Only after steps 2–5 are proven: set `CHECKOUT_MODE=AWS_NATIVE` and disable Wix
writeback (`WIX_WRITEBACK_ENABLED=false`). Place a REAL low-value test order; verify
Razorpay signature verification, order + invoice creation, inventory decrement, and
that the amount equals the shadow-run figure.
ROLLBACK: set `CHECKOUT_MODE=WIX_HEADLESS` (instant); no Wix order drift
accumulated because writeback was already off on the native path.

## Step 7 — Prove independence (Gate 4)  🔒 verification
Block Wix hosts at the network and run `npm run build` + a checkout e2e. The build
must produce a non-empty blog + sitemap and checkout must complete, with zero
`wixapis.com` calls. `scripts/check-wix-policy.sh` (gate mode) still reports
findings because the CODE is not deleted yet — that is step 8.

## Step 8 — Retire Wix  🔒 irreversible
Only after a stable period on the native path:
1. Delete the dead Wix modules (`wix_gift_cards.py`, then `cart_v2`, `wix_ecom`,
   `wix_coupons`, `wix_writeback`, the Wix branches in handlers, `src/config/wix.ts`,
   `provider_adapters.py` Wix branch) + their tests. The exit gate now reaches 0 →
   flip `.github/workflows/wix-exit-policy.yml` to blocking (drop `--expect-fail`).
2. Remove Wix env vars + IAM GetSecretValue grants via IaC.
3. Disable Wix OAuth/API at the provider; rotate the exposed `wecare/wix/app-oauth`.
4. `aws secretsmanager delete-secret --recovery-window-in-days 30` for the 3 Wix
   secrets (NEVER `--force-delete-without-recovery`). Keep the migrated pepper.
5. Rebuild backups excluding retired creds; review old S3 versions.
6. Cancel the Wix subscription (off-AWS) only after all the above is verified.

## Why the order cannot change
Seed before flip (an empty ProductsTable + `CHECKOUT_MODE=AWS_NATIVE` = every
checkout refused). Shadow before flip (prove totals match while Wix is still the
safety net). Reads before checkout (lowest blast radius first). Delete last (the
flags are the rollback; deleting code removes the rollback). Pepper before SPI
retirement (or every gift card becomes unlookupable).
