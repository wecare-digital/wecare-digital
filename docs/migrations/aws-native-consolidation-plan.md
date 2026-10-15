# AWS-native consolidation — plan, approval gates and rollback

Tool-neutral plan (Codex, Kiro or a human). The checkbox mirror for Kiro is
`.kiro/specs/aws-native-consolidation/tasks.md`; change both together. Measured 2026-10-14/15
against account 775261844268 (us-east-1). Repository changes for this plan are on branch
`feat/aws-consolidation-master-20261014`; nothing in it is deployed.

## Working rules

- Several agents share one working tree. Never `git checkout` another branch in it, never stage
  tree-wide; this branch was built with a temporary index and does not move `HEAD`.
- Read-only discovery is always allowed. Every 🔒 step needs explicit owner approval and is a
  separate change: never batch CMS, payment, credential and SIP changes in one deployment.
- No secret value is read during discovery. The CLI currently authenticates as the root user;
  B-0 below removes that.

## Where things stand

| Area | State | Evidence |
| --- | --- | --- |
| Blog | AWS-native, 1,421 posts reconciled | `final-wix-retained-evidence-reconciliation-20261014.md` |
| Catalog / storefront | ProductsTable authoritative (10 / 23); media on CloudFront | same |
| Checkout | `AWS_NATIVE`, live v53; IAM drift fixed 2026-10-15 | `evidence/live-provider-independence-20261015.md` |
| Wix cloud surface | functions, routes, tables, secrets, DNS gone | live check PASS on 5 of 8 checks |
| Wix residue | 1 rollback alias with WIX_* env; 1 WIX_* env key; 1 dangling grant | same |
| Meta catalog sync | disabled (`META_CATALOG_SYNC_ENABLED=false`); no stream trigger | Lambda config |
| Secrets | 19 active; shared role reads all of them | `secrets-access-matrix.md` |
| Lightsail | NO-GO, keep Micro | `lightsail-nano-feasibility.md` |
| Cost | $101.30 gross in Sep, 100% credited | `aws-cost-optimization.md` |

## Applied on 2026-10-15 (owner approval: "complete all")

Each change ran on its own, was verified, and has a saved rollback in the main checkout's
`.scratch/iam-rollback/` (git-ignored).

| Time (IST) | Change | Verification | Rollback |
| --- | --- | --- | --- |
| 05:47 | P0: `remediate_commerce_keys_iam.py --apply` on 3 inline policies | 17/17 SimulatePrincipalPolicy cases; live check `commerce-key-access` PASS | `--rollback .scratch/iam-rollback/commerce-keys-iam-20261015T001739Z.json --confirm I-APPROVE-COMMERCE-KEYS-IAM-ROLLBACK` |
| 05:48 | A.8: deleted `NativeCommerceCatalogRead` from `wecare-meta-catalog-sync-role` | meta-sync Scan/GetItem on ProductsTable still allowed | `put-role-policy` with the saved document |
| 05:49 | A.6: deleted alias `wecare-seo-tools:blog-rollback-20261014` | public blog API 200, 1,421 posts | `create-alias --function-version 1` and re-add the 2 saved permissions |
| 05:47* | A.7: `WIX_ORDER_IDS_TABLE` removed (v116, by another session) | live check `lambda-env-keys` PASS | `update-alias live` to v115 |
| 05:56 | B-1a: managed policy `wecare-shared-role-secret-guard` attached to `wecare-digital-lambda-role` | 11/11 simulated cases; 0 errors on razorpay-webhook, whatsapp-business-api, invoice-engine | `shared_role_secret_guard.py --rollback --confirm I-APPROVE-SHARED-ROLE-SECRET-GUARD-ROLLBACK` |
| 05:58 | `wecare/meta/payments` scheduled for deletion, then restored the same minute | `DeletedDate` null | n/a: it is referenced by `.env.local.example` as the payment-config mapping, so it stays |
| 06:00 | Deletion protection on ProductsTable and CommerceKeys | `DeletionProtectionEnabled=True` | `update-table --no-deletion-protection-enabled` |

Live check after the changes (`evidence/live-provider-independence-20261015.md`): 7 of 8 PASS.
The remaining FAIL lists two non-Wix dangling grants (email verification → missing
`CustomersTable`; an Amplify data role → missing `Contact-…-NONE`), outside this program.

## Execution order

1. **P0 — Commerce-key IAM (do first, alone).**
2. Workstream A residue (A.6–A.8), one change each.
3. Secrets B-0, then B-1, B-2, B-3/B-4, B-5, one change each.
4. Meta catalog sync enablement (separate owner decision; Meta writes).
5. Lightsail host-access session, then re-decide (independent release).
6. Month-end cost re-measure.

## P0 — Commerce-key IAM drift 🔒

**What is broken.** `wecare-checkout:live` (v53) and `wecare-service-requests:live` (v6) read
`stack-wecare-digital-CommerceKeys`, but their dedicated roles still grant only the deleted
`stack-wecare-digital-WixOrderIds`. IAM simulator: checkout `PutItem`/`GetItem` on CommerceKeys
→ implicitDeny; checkout `UpdateItem` on ProductsTable → implicitDeny (stock reservation is on:
`NATIVE_STOCK_RESERVATION_ENABLED=true`); service-requests `GetItem` on CommerceKeys →
implicitDeny. Consequence: the next website or WhatsApp checkout fails closed, and paid service
activation fails. No customer failure is logged yet (2 checkout invocations since the cutover,
0 orders in OrderTable). Rolling back the functions is not possible: the old table is deleted.

**Change (three inline policies, from the IaC homes):**

```bash
.venv/bin/python scripts/remediate_commerce_keys_iam.py            # plan: diff + Access Analyzer + 17 simulations
.venv/bin/python scripts/remediate_commerce_keys_iam.py --apply --confirm I-APPROVE-COMMERCE-KEYS-IAM
```

The apply also adds two grants the IaC already declares and live lacks: invoke on
`wecare-outbound-whatsapp` (+`:live`) for checkout, and `GetItem` on OrderTable
(`ReadOriginalOwnedOrder`) for service-requests. DeleteItem stays withheld everywhere.

**Verify:** the script re-simulates the roles; then
`scripts/check_live_provider_independence.py` must report `commerce-key-access` PASS. An owner
QA checkout (no real charge unless separately approved) confirms end to end.

**Rollback:** `--rollback .scratch/iam-rollback/commerce-keys-iam-<stamp>.json --confirm
I-APPROVE-COMMERCE-KEYS-IAM-ROLLBACK` restores the saved documents (which re-breaks checkout;
use only if the new grants misbehave).

## Workstream A residue 🔒

| Step | Change | Verify | Rollback |
| --- | --- | --- | --- |
| A.6 | `aws lambda delete-alias --function-name wecare-seo-tools --name blog-rollback-20261014` | live check `lambda-env-keys` no longer lists seo-tools | `create-alias` to version 1 (still published) |
| A.7 | remove `WIX_ORDER_IDS_TABLE` from `wecare-whatsapp-business-api` env through its deploy path, publish, move `live`; then `scripts/env_manifest.py --export` | live check `lambda-env-keys` PASS | move `live` back to v114 |
| A.8 | `aws iam delete-role-policy --role-name wecare-meta-catalog-sync-role --policy-name NativeCommerceCatalogRead` (save the document first) | live check `iam-dangling-tables` no longer lists it | `put-role-policy` with the saved document |

Remaining dangling grants outside Wix (not part of this program, listed for the owner):
`wecare-email-verification-role` → missing `stack-wecare-digital-CustomersTable`, and an Amplify
data role → missing `Contact-…-NONE`.

## Secrets 🔒

Phases B-0 to B-5 with reasons and rollback are in `secrets-consolidation.md`. Summary: stop
using root keys; narrow the shared role's `secret:wecare/*`; replace the exposed PAT; retire
`aws/iam-access-keys`; owner-confirm `meta/payments` and `bing/api`; regenerate the backup
archive before any old version is expired. Every deletion uses a 30-day recovery window.

## Lightsail 🔒

Independent release. Only an approved host-access session to run `preflight.sh` is needed to
re-decide. Any Nano attempt follows `lightsail-nano-cutover.md` with
`scripts/lightsail-nano-migration/` (dry-run default; `rollback.sh` moves the IP back).

## Remaining risks

- **Payment:** P0 is fixed in IAM; an owner QA checkout (no real charge unless approved) is still the end-to-end proof.
- **Security:** root access keys in daily automation; 61 functions can read every secret; the
  exposed PAT is still valid as far as metadata shows; agents have force-deleted secrets without
  a recovery window (Wix and Airtel, 2026-10-14).
- **Data:** the credential backup is 18 days old and has no lifecycle; CommerceKeys and
  ProductsTable have deletion protection off (PITR on).
- **SEO:** builds are green again; the static blog export must keep all 1,421 posts.
- **Voice:** the SIP certificate expires 2026-11-18; renewal is expected around 2026-10-19 and
  the alarm fires at ≤10 days.
- **Concurrency:** other agents push to `stack` many times a day; Amplify built 50–67 times a
  day this week, which is also the largest controllable cost.
