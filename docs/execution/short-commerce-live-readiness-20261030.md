# Short Commerce Part 1 — production audit and activation gates

Date: 2026-10-30. Scope: WECARE.DIGITAL, GitHub `wecare.digital`, AWS
account `775261844268` region `us-east-1`, Meta app
`2238810740192680`, Wecare.Digital verified business.

## Current release state and strict read-only attestation (updated 2026-10-30)

- The website release is **live**: Amplify production job #400 completed BUILD, DEPLOY and VERIFY.
  The legacy /checkout/ missing-heading build failure was fixed via merged PR #1979.
  Public design-token drift is now a mandatory CI gate via merged PR #1978.
- The backend one-unit contract is **not activated**. AWS readback still shows
  checkout :live v288, commerce :live v168 and inbound WhatsApp :live v191,
  with SHORT_COMMERCE_PART1_ENABLED absent on all. The reviewed source is
  staged in $LATEST for all three but those mutable versions are not eligible
  for an immutable live release attestation. The last staged packaging was
  pinned to Git commit `3cd052daeb7e057a529b95feaff4fa5bdac98883`;
  subsequent main commit `e09d6441d407885c8f303e14413b0d75bd7ff438`
  includes nine newer commits, among them changes to shared
  `lambda_utils/ecommerce/service_requests.py` and the new Pickup gate.
  Rebuild the exact latest approved source tree before publishing any versions;
  never promote those existing $LATEST ZIPs as if they matched current main.
- The eight named wecare-payment alarms were OK on the most recent read.
  Alarm state is not proof of provider capture, Meta handset, or invoice parity.

The read-only `scripts/check_short_commerce_live.py` gate now refuses to mark
production ready from three flags alone. It requires an independently reviewed,
**operator-supplied** JSON release manifest naming the exact Git source commit,
AWS account and region, and immutable published Lambda version + CodeSha256 for
each of the three receivers. The checker independently reads each `:live`
alias target, rejects weighted/mixed traffic, verifies the actual published
version and deployed code hash, checks healthy update status and the explicit
one-unit flag, and requires all eight named payment alarms in OK state. Missing
manifest, missing alarms, stale aliases, mismatched hashes or absent flags all
fail closed. No customer records or payments are accessed.

Operator-reviewed manifest shape (placeholder values are **not** valid release
evidence; do not copy current $LATEST SHAs as if they were approved):

```json
{
  "schema_version": "short-commerce-release-v1",
  "account": "775261844268",
  "region": "us-east-1",
  "source_commit": "<full 40-character reviewed Git SHA>",
  "receivers": {
    "wecare-commerce": {"version": "<published version>", "code_sha256": "<Lambda CodeSha256 base64>"},
    "wecare-checkout": {"version": "<published version>", "code_sha256": "<Lambda CodeSha256 base64>"},
    "wecare-inbound-whatsapp": {"version": "<published version>", "code_sha256": "<Lambda CodeSha256 base64>"}
  }
}
```

After **release-owner approval, isolated staging with both flag states, Meta
asset/recipient verification and authorized payment parity checks**, save the
reviewed manifest outside the source tree and run:

```sh
python scripts/check_short_commerce_live.py \
  --region us-east-1 \
  --expect-account 775261844268 \
  --release-manifest /secure/operator-reviewed-short-commerce-release.json
```

This is a configuration/coded-artifact check only, **not a signature verifier**
or an approval system. A manifest does not prove that its stated Git source was
really used to package a ZIP; independently retain the pinned CodeBuild tree,
package SHA evidence, and operator's review. This command alone cannot satisfy
real provider capture/invoice/fulfillment or Meta published Flow QA. Keep issue
#1973 open until all independently required checks and signoffs are evidenced.

## Credential-free deployment ZIP preflight

Before staging a new immutable receiver release, package the *exact reviewed
commit* using the same deterministic ZIP assembler as production:

```sh
uv run --no-project --python 3.12 --with boto3==1.43.116 \
  python scripts/check_short_commerce_packages.py
```

This command creates **no** AWS client and makes **no** cloud calls or writes.
It builds the checkout, commerce and inbound WhatsApp ZIPs twice to prove
reproducibility, checks the archived bytes against their in-tree handlers,
required shared one-unit/checkout policy, and the single invoice engine with
receipt layout and font assets. It validates packaged Python syntax and prints
each candidate Lambda CodeSha256, package file count, and ZIP size.

The Short Commerce CI now runs the same check, its negative-test suite, and the
hermetic payment rail on relevant handler, shared-module, invoice and packaging
changes. A candidate hash is **not** approval to deploy or proof that an AWS
published version has that hash. Keep the code-build source SHA, review, and
operator-approved manifest separate; continue requiring protected staging,
provider parity, Meta QA, and release-owner approval before changing :live.

## Verified at audit time

- GitHub PRs #1964 and #1965 are merged; branch push CI passed on
  `715edaefa06fbd224e46f97369c6e09eaf1c580e`.
- The website cart enforces one line / quantity 1, offers direct
  **Pay here** / **Pay on WhatsApp**, and sends product references, NOT prices.
- The existing backend freezes a ProductsTable-priced `QuoteSnapshot`
  with the eligible Delight discount and checkout fee/tax policy, and the
  Razorpay order and native WhatsApp `ORDER_DETAILS` show that amount.
  A list/catalogue price is not a binding final quote.
- The checkout's authenticated `/checkout/status/` uses one
  paid/failed/pending/finalizing decision. Legacy `/checkout/success/`
  is made a strict alias in this change. Payment status, not URL content,
  controls any success state.
- Production Lambda live versions read back: `wecare-commerce:168`,
  `wecare-checkout:288`, `wecare-inbound-whatsapp:191`,
  `wecare-outbound-whatsapp:262`, `wecare-razorpay-webhook:264`,
  `wecare-invoice-engine:271`. All were active; eight inspected
  payment CloudWatch alarms were `OK`.
- The **new backend one-unit flag is absent on all three receiving
  live functions**. Most importantly, inbound version 191 was published
  before PR #1965 merged. Therefore global native WhatsApp one-item
  enforcement is **NOT LIVE**, even though the code is on the main branch.
  Setting an environment flag without verified updated code on published
  aliases is insufficient.
- Meta app is live and compliant, with active WhatsApp event subscription.
  Approved templates include `wecare_whatapp_native_pay_template`
  (ORDER_DETAILS) and `wecare_default_invoice_image_template`.
  Separate `catalog_management` permission is rejected.
- AWS Data Analytics read-only inventory found a default Glue catalog,
  a `wecare_analytics` database and no `order`-matching Glue tables
  or S3 Tables buckets in us-east-1. **DynamoDB remains the live order /
  payment / invoice authority**; do not create a second payment ledger
  from analytics.
- Verified webhook capture calls the existing idempotent order, invoice,
  WhatsApp order-status and customer-invoice pipeline. Service-specific
  post-invoice Flow dispatch is present, but not every SKU has an
  automated Flow: offline physical fulfillment remains an internal task.
  PR #1967 merged source changes for Pickup's terminal payload and
  paid, order-bound completion, but Meta's published Flow JSON and the
  relevant live Lambda versions still need verification before enabling it.
  A merged source fix alone is not a completed courier booking.

## Commercial and customer contract

1. Exactly one product/variant, quantity one per new transaction;
   unsupported native Meta multi-baskets must be refused, not truncated.
2. Authenticated customer sees either website Razorpay or WhatsApp native
   payment, without another payment-method page or a second pending charge.
3. A single immutable server quote in integer paise includes applicable
   discount, GST/fees and shipping. **Provider payment presentation** is
   the review point for the final amount; browser list prices cannot
   compute or override it.
4. Only a verified captured payment becomes a paid order. A pending or
   unknown state must not show success or invite an immediate new payment.
5. One paid order -> exactly one statutory invoice and eligible WhatsApp
   template send. A supported service gets its own approved Flow after
   invoice confirmation. Other paid products are entered into the existing
   offline or digital fulfillment process; do not mark shipping complete
   merely because payment/order-status is complete.

## Activation sequence (separate from merging this PR)

1. Review and approve the payment-contract change described in
   `docs/execution/short-commerce-part1-server-review-20261030.md`
   against the existing frozen payment rail.
2. Follow the current manual, release-scoped payment validation policy in
   `docs/operations/repository-validation.md`, including reviewed WhatsApp
   and Razorpay capture/order/invoice evidence on the exact tree to be bundled.
   The historical CI job and test suites are retired.
3. Stage the same bundle and shared `lambda_utils` policy on all
   **three** receivers: checkout, commerce and inbound WhatsApp.
   Verify signed package SHA, published version, alias, and that
   `SHORT_COMMERCE_PART1_ENABLED=false` preserves current behavior.
4. Stage `SHORT_COMMERCE_PART1_ENABLED=true` on all three
   receivers. Test multi-product, quantity >1, unknown item, pending
   WhatsApp address resumptions, claims, retries and redelivery with
   **zero** unexpected PaymentAttempts; single product must still pay.
5. Verify both provider amounts against the quote, paid order and
   invoice with an authorized test customer. Confirm Meta native payment
   availability by account and market. Verify invoice and Flow/offline
   outcomes for each SKU without sending messages to real customers
   as a test.
6. Only after explicit release-owner approval, deploy published immutable
   aliases with monitored rollback, then enable the same flag in the
   version-published environments. Never update only `$LATEST` while
   production traffic stays on `:live`.
7. Monitor the existing payment-related alerts and paid-but-not-fulfilled
   cases; revert the flag or aliases if any invariant fails. Never
   delete or rewrite paid attempts, captured payments or invoices.

## Read-only live configuration check

Use the **operator-reviewed release manifest** and exact command shown near
the top of this runbook. Without the manifest, the checker exits non-zero even
if all three flags are enabled; that is the intended fail-closed behavior.
The checker never touches customer records, money, messages or AWS state.

## Release CI baseline note

The original 2026-10-30 CI run 41075565699 failed on four public
design-token consumers, although the payment-specific regressions passed.
Issue #1970 has since been resolved, and merged PR #1978 restored the
mandatory `scripts/check_design_drift.py --gate`. This is no longer an
advisory design check. Checkout, hermetic payment, release attestation
and ZIP packaging tests must all remain blocking in the same workflow.

## Remaining release blockers

The website static release was verified through AWS Amplify job #400. The
**backend** one-unit policy remains OFF on all three live aliases. Still
outstanding are immutable published-version and code-hash attestation, the
owner-approved staged OFF/ON matrix, capture-to-quote-to-invoice reconciliation
for website and native WhatsApp, Meta handset and Pickup asset validation,
and per-SKU Flow/offline fulfillment outcomes. A passing offline package
preflight does not close any of these operational gates.
