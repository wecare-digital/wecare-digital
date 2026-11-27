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
