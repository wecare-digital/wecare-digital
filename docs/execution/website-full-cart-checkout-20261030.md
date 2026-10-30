# Website full-cart checkout — staged, not live

## Owner-directed customer flow

1. Every product selected stays in the same unpaid basket; quantities and current variants are editable.
2. `/checkout/` reviews every line and a **server-authoritative** financial breakdown:
   merchandise subtotal, supply GST (if applicable), delivery, Delight discount,
   convenience fee, GST on the fee, and the exact final payable.
3. **Pay here** opens existing Razorpay Standard Checkout **directly**, using
   only server-created order ID, gateway key and amount. If the payable amount
   changed by even one paise since the reviewed quote, the browser refuses to
   open the provider modal and asks the customer to review the new quote.
4. Captured/pending/failed is determined by the existing authenticated
   `/checkout/status/` flow. Only a verified paid status routes to the
   customer-owned `/orders/?o=<real order number>` page.
5. The order detail page shows a semantic line-item table (product, quantity,
   unit price, total), actual GST/tax terms, the real order number and real
   invoice number. Authenticated **Download GST invoice** requests a short-lived
   signed URL using the existing `/ecommerce/my-invoice` API.
6. **Checkout with WhatsApp** leads to its own `/checkout/whatsapp/` page.
   That route is *non-paying* and sends no messages until the separate
   native WhatsApp payment phase is specified, built and verified.

No browser-supplied price, subtotal, GST or discount is sent as payment input.

## Release-order safety

**The existing live checkout Lambda predates the `action:'quote'` handler.**
Unknown actions on that older implementation fall through to `create`,
which may initiate native payment rather than perform a read-only quote.
The frontend therefore has an explicitly default-OFF compilation switch:

`NEXT_PUBLIC_WEBSITE_FULL_CART_QUOTE_ENABLED=true`

Do **not** set it until the following are independently verified:

- Latest reviewed website checkout backend ZIP is built and version-published
  and the authorized backend `:live` alias has been changed under a monitored
  deployment. A `$LATEST` upload by itself is not a live deployment.
- The `action:'quote'` read is proven in an isolated environment to create **zero**
  PaymentAttempts, Razorpay orders, invoices or Meta/WhatsApp sends.
- Website `prepare` supports full baskets and produces exactly the same
  items, supply GST, discounts, delivery, convenience fee, fee GST and final paise
  as the read-only quote; negative tests cover changed products, stale prices,
  changed addresses, unavailable items, retries and concurrent attempts.
- An operator-approved Razorpay test verifies the exact modal amount, the
  captured amount and order/invoice amount agree, including refund/replay
  scenarios. Confirm a completed order gets its actual invoice and download grant.
- The payment-rail owner and release operator approve the deployment and
  document versions, CodeSha256, alarms, canary/rollback and final readback.

**Never publish the new static frontend on its own.** A disabled switch fails
safe but prevents website checkout from opening Razorpay; the production
backend must be deployed and verified *before* enabling the frontend build.

The global Short Commerce native one-unit issue #1973 is independent. Its
existing native guard remains untouched by this website-only full-cart change.
WhatsApp checkout must not be activated as part of this phase.

## Tests

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck
node scripts/test-short-commerce-part1.mjs
python -m pytest -q tests/test_short_commerce_part1.py
python -m unittest discover -s tests -p test_short_purchase_policy.py
```

The existing Short Commerce GitHub workflow additionally verifies the hermetic
payment/order/invoice rail. The checkout export release gate must still pass.

**Current status: draft PR / branch validation only. Not a production release.**
