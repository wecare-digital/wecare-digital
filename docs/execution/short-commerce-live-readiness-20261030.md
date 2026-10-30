# Short Commerce Part 1 — production audit and activation gates

Date: 2026-10-30. Scope: WECARE.DIGITAL, GitHub `wecare.digital`, AWS
account `775261844268` region `us-east-1`, Meta app
`2238810740192680`, Wecare.Digital verified business.

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
  The Pickup Flow payload gap documented in the original Part 1 plan
  remains a separate fulfillment blocker.

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
2. Run the new `Short Commerce payment-safe regression` CI,
   existing full release gates, and the hermetic WhatsApp+Razorpay
   capture/order/invoice test on the exact tree to be bundled.
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

From the authorized operations runner with AWS read access:

```sh
python scripts/check_short_commerce_live.py --region us-east-1 --expect-account 775261844268
```

This intentionally exits non-zero while a required alias is unflagged.
It does not query customer records, print secrets, send WhatsApp messages,
create payment attempts, update Lambda aliases or alter AWS resources.

## Unverified conditions at this audit

No real-money test of PR #1965 on **live** AWS aliases, no deployed-code SHA
attestation for the inbound receiver, no production proof of one-SKU
offline fulfillment/Flow completion, and no reliable confirmation that
the public website's static release matches this GitHub commit.
Do not describe Part 1 as fully enabled until those are closed.
