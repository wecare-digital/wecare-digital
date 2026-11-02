# WECARE Shop — single checkout URL, dual payment rails
**Audit and implementation record — 2026-11-02**

## Decision and scope
- **Only one customer checkout page:** `https://wecare.digital/checkout/`. No second card/WhatsApp checkout page and no browser-built payment link.
- **Two explicitly chosen actions, after read-only server quote:** Pay on Website (Razorpay Standard Checkout) and Pay on WhatsApp (approved Meta native ORDER_DETAILS / Review and Pay).
- Existing `/checkout/status/` is **payment-status reconciliation**, not a second checkout. Orders remain at `/orders/`.
- Catalog items, images, prices, product status, WhatsApp templates, and production settings are not mutated by this change.

## Traced paths
| Step | Pay on Website | Pay on WhatsApp |
|---|---|---|
| Customer page | `/checkout/` | Same `/checkout/` |
| Quote | Authenticated `POST /api/ecommerce/prepare-checkout` with `action: quote` | Same read-only quote |
| Start | Authenticated `POST /api/ecommerce/prepare-checkout` with `action: prepare` | Authenticated `POST /api/ecommerce/checkout` with `action: create` and `expectedTotalPaise` |
| Pricing authority | `ProductsTable`, `_native_quote`, `checkout_pricing` | Same `ProductsTable` and `_native_quote` |
| Pay initiation | Server-created Razorpay order, customer confirms in SDK | Server attempts one approved `wecare_whatapp_native_pay_template` `ORDER_DETAILS` message to verified number |
| Deduplication | Request key, basket and cross-rail payment pointers | Same request key + cross-rail guard; dedup returns prior attempt |
| Verification | Signed callback + provider capture readback/webhook | Provider/Meta capture readback + webhook; message acceptance is **not** PAID |
| Continuation | `/checkout/status/` then `/orders/` | Same payment-status route then `/orders/` |

## Verified current AWS / Meta configuration
- AWS HTTP API `zllr9lrg7j` already maps `POST /ecommerce/checkout`, `POST /ecommerce/prepare-checkout`, `POST /ecommerce/verify-callback` and `POST /ecommerce/checkout/status` to the commerce integration; production integration points at `wecare-commerce:live`.
- Observed `wecare-commerce:live` version **183** and `wecare-checkout:live` version **301**; this PR's new backend guard is **not deployed** there.
- `SHORT_COMMERCE_PART1_ENABLED=true` on both checkout functions. Native WhatsApp payment currently only supports **one line and quantity one**; disabled WhatsApp CTA and explanatory text for a larger cart.
- WECARE.DIGITAL messaging account template **`wecare_whatapp_native_pay_template`** is **APPROVED**, English, UTILITY, subtype ORDER_DETAILS with the fixed **Review and Pay** button. Its approved header is an image; the no-product-catalog-images policy must not delete that approved template asset.
- Production Amplify branch has not set `NEXT_PUBLIC_WEBSITE_FULL_CART_QUOTE_ENABLED=true`. The source deliberately fails closed on the frontend while the old-backend quote compatibility is unverified. Do **not** flip the flag on production before controlled version-pinned checkout QA.
- In a read-only scan of the past 24 hours of `/aws/lambda/wecare-commerce` logs, no events matched the selected checkout failure markers. That **does not prove** checkout succeeds: the frontend currently blocks invocation and not all failures emit those markers.

## Price-breakdown policy findings and release blocker
- The browser quote reconciles in integer paise: `base merchandise + supply GST + delivery - discount + convenience fee + fee GST == total`. The quote is **read-only** and must be refreshed after a cart/profile change.
- **Vault / Drop Docs are already explicitly GST-exclusive**, using 18% supply GST, Delight, ₹45 Express, 2.5% convenience and 18% GST on the fee. Example for Vault: ₹49.00 + ₹8.82 − ₹0.28 + ₹45.00 + ₹2.56 + ₹0.46 = **₹105.56**.
- **Contribute is an isolated ₹300 gross-target contract** with server-computed ₹235.41 base, ₹42.37 supply GST, −₹1.38 Delight, ₹15 Express, ₹7.29 convenience and ₹1.31 fee GST. Do not reinterpret its catalog ₹300 as a taxable base without a separate price-policy decision.
- **Express policy update (2026-11-02):** Contribute alone retains ₹15 inside its exact ₹300 total. All other 28 customer-facing items receive a single mandatory ₹45 Express line **per checkout**, including Vault, Drop Docs, other services and multi-item orders; Delight is computed before Express, and convenience + fee GST after it. The unlisted ₹2 commerce QA SKU remains exempt. Both payment rails use the same frozen quote; existing payment attempts remain frozen under their original policy.
- **Ordinary catalog items are still GST-inclusive in `_native_quote`** (`gst_bps=0`). User's requested “existing amount as base + 18% GST on top” is therefore **not yet live** and cannot be represented truthfully by frontend-only arithmetic. Converting all 29 items requires a separate server-side, versioned tax/pricing migration covering category rules, service exceptions, receipt/invoice fields, Meta order-details arithmetic, mixed baskets and refunds. This PR does not silently start charging that extra GST.
- The native quote may be recalculated between review and send. The new `expectedTotalPaise` precondition rejects any mismatch **before** attempt, reference, or template-send side effects; the browser re-quotes before retry.

## Safety cases
1. **Changing cart/profile after quote:** clears quote state; both buttons disabled until current quote revalidates.
2. **Already live payment on the other rail:** backend returns `CHECKOUT_AMBIGUOUS` and original attempt id; browser navigates to status instead of starting a second charge.
3. **Duplicate WhatsApp clicks:** React synchronous latch prevents local re-entry; backend dedup/cross-rail pointer remains the authoritative guard across tabs.
4. **WhatsApp native send timeout:** `SEND_FAILED` with `sendUnconfirmed=true` is *ambiguous*, so browser navigates to status (or latches as unknown if the attempt id is missing); never invites an unsafe retry.
5. **Native request returns amount other than reviewed total:** browser navigates to status; only provider capture can mark payment paid. Price mismatch before send is refused by server.
6. **Missing name/address or invalid service intent:** backend continues to refuse before payment; client shows the same profile editor / service explanation.
7. **Native attempt accepted by Meta:** no `PAID` status is assumed from delivery/read/acceptance. Completion requires verified capture.
8. **No standalone WhatsApp checkout page or `wa.me` payment link**: native template is sent by `wecare-outbound-whatsapp:live` with approved configuration and template.

## Release and QA checklist (must pass before merging/enabling)
1. Review this PR's diff for accidental price, provider, template or security changes.
2. Compile Python checkout handler, run static checkout release gate, and TypeScript `tsc --noEmit` / Next build on the correct Node/npm versions.
3. Deploy review-approved backend Lambda update and pin/verify the active **commerce** alias, not just `wecare-checkout`; inspect API Gateway integration and Lambda invoke permissions.
4. On a nonproduction Amplify branch set `NEXT_PUBLIC_WEBSITE_FULL_CART_QUOTE_ENABLED=true` and verify `action: quote` is a read-only `QUOTE_READY` (never a CREATE).
5. Exercise Vault ₹84.97 example; Contribute ₹300 special case; ordinary GST-inclusive item as currently configured; multi-line cart (website only); session expiry; expired/unresolved variant; address required; service intent.
6. Assert both buttons call the same customer checkout page and WhatsApp invokes `action:create` with `expectedTotalPaise`; verify mismatch returns `QUOTE_CHANGED` *without* outbound send.
7. Controlled WhatsApp test **only with authorized QA customer and explicit send authorization**, then verify the template, amount, status, receipt, invoice and webhook capture. Do not use a real customer's WhatsApp number for unattended tests.
8. Simulate duplicate click, provider timeout and ambiguous sender, stale amount, cross-rail in-flight attempt and webhook delay. On all ambiguous states verify no second payment can begin.
9. Only after QA approval: enable the quote feature on production; monitor logs/errors, payment reconciliation and roll back the frontend flag if inconsistent.
10. The 18% ordinary-product GST-exclusive migration needs its **own reviewed backend release**. Do not represent missing GST as a paid/collectible line before it is implemented.

## Source references
- https://github.com/wecare-digital/wecare-digital/blob/wecare.digital/src/components/cart/CartPage.tsx
- https://github.com/wecare-digital/wecare-digital/blob/wecare.digital/src/lib/checkoutQuote.ts
- https://github.com/wecare-digital/wecare-digital/blob/wecare.digital/amplify/functions/ecommerce/checkout/handler.py
- https://github.com/wecare-digital/wecare-digital/blob/wecare.digital/amplify/functions/shared/lambda_utils/ecommerce/native_checkout.py
- https://github.com/wecare-digital/wecare-digital/blob/wecare.digital/amplify/functions/shared/lambda_utils/ecommerce/default_coupon.py
