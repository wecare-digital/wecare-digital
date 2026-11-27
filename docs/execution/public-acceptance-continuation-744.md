# Website acceptance continuation — production builds 744/745

Baseline: Amplify #744 BUILD/DEPLOY/VERIFY succeeded, commit
13feb7afd2d65dbd77f17709ef9ad25435ce00f8, 27 Nov 2026.

PR #2453 merged while this audit was prepared, at 2cbdcbd90b1a18a0ff1c879001e6e84115193127 (Amplify #745). Run live tests only after confirming deployment and verify before/after fingerprints.

The preceding live matrix crossed deployments and is not exact-revision
acceptance. Re-run all 15 browser/profile jobs with Home asset fingerprints
before/after; selectors and glyph/overflow measurements are recorded in each
route's evidence. A fingerprint identifies consistent assets, not a Git SHA;
confirm Amplify before and after. The separate synthetic checkout matrix
blocks all external and transactional requests, intercepts identity, quote,
SDK, status and Orders responses; screenshots use fake data only. It cannot
certify provider capture or actual receipts. Static SEO checks every exported
sitemap URL, plus protected noindex pages, without crawling production.

Read-only AWS evidence: the active checkout Lambda uses the expected native
ProductsTable, which reports ItemCount 0; a strongly consistent GetItem for
the exact configured contribution product returned no row. No catalogue row
was inserted or guessed. Reconcile authoritative catalogue with its owner
before live quotes/capture. The deployed Arogya booking Lambda still exposes
only draft configuration, not approved provider access. Merged PR #2453's provider activation still
requires a verified mailbox delegation, provider authorization, exact live
schema and reviewed backend release. Never transmit actual OTPs or money
during QA. Actual Razorpay test capture, signed invoice, real-device and
screen-reader evidence, field CWV and provider booking remain explicit gates.

## Catalogue recovery evidence — read-only 27 November

A strongly consistent GetItem on the configured contribution product returned no
row. AWS Backup metadata lists completed daily recovery points of 23,678 bytes
on 18–21 November (05:00 UTC); 22–27 November daily points report zero bytes.
This bounds a likely data-loss window, but backup size alone does not prove
which records exist. DynamoDB PITR is enabled, 35 days, with earliest restorable
23 October and latest restorable approximately 27 November 10:05 UTC at inspection.
The committed 17 October display snapshot includes the original contribution
product/SKU; the current seed file has nine unrelated entries and does not
contain it. Neither is an approved authoritative live price source.

Safe recovery sequence (requires catalogue owner and AWS administrator approval):
1. Preserve the current table, stack, stream, IAM, and payment safety gates. Audit
   catalogue administration/change events and independently confirm the loss window.
2. Review an isolated recovery-table restore from the 21 November point (or
   selected pre-loss PITR time), with approved cost, encryption and deletion plan.
   Do not restore over production, repoint checkout, or enable writes/charging.
3. Compare exact product and variant identifiers, stock, visibility, pricing,
   currency, tax and policy fields with the authoritative catalogue and current
   configuration. Reconcile any intended changes since the recovery time.
4. Prepare a reviewed conditional repair, full catalogue diff and rollback plan.
   Apply only after explicit approval; verify live read-only quotes before using
   an authorized Razorpay test-mode capture. Never seed guessed records.

No recovery table, product row, payment, OTP, credential, or IAM permission was
created during this audit. No backup contents were inspected; only metadata.
