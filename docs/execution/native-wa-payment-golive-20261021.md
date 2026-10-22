# Native WhatsApp ORDER_DETAILS payment — go-live checklist

**Status as of 2026-10-21:** the full native WhatsApp payment leg (both the
catalog-service/invoice leg and the general product-cart leg) is **built and enabled in
code + repo config** on `stack`. This was an explicit, owner-authorized reversal of the
2026-10-01 website-only ruling.

> **What "enabled in code" does NOT mean.** Merging the code does not charge any customer.
> Going live requires the real-world deployment + provisioning steps below, which cannot be
> done or verified from the repository alone. Until these are done, the deployed Lambdas keep
> running the previously-deployed behavior regardless of what the repo says.

---

## What is already true in the repo (verified on `stack` @ 32c99b33)

| Item | State | Location |
| --- | --- | --- |
| Checkout initiation gate | removed — `INITIATION_ENABLED = True` | `amplify/functions/ecommerce/checkout/handler.py:199` |
| `CART_PAYMENT_IS_WEBSITE_ONLY` guard | removed (general cart can pay natively) | (absent from `amplify/`) |
| Inbound money sender | rebuilt — `_send_payment_request` + token-guarded `_rollback_cart_order_index` | `amplify/functions/messaging/inbound-whatsapp-handler/handler.py:6464, 6440` |
| General-cart checkout action | `prepareNativeCart` → `_native_cart` (twin of `_native_catalog_service`) | `amplify/functions/ecommerce/checkout/handler.py:467, 2404` |
| `WA_CATALOG_ORDERS_ENABLED` | `"true"` | `config/lambda-env-manifest.json:180` |
| `WHATSAPP_CATALOG_SERVICES_ENABLED` | `"true"` (3 readers) | `config/lambda-env-manifest.json:110, 181, 502` |
| Readiness values (manifest) | `WECAREDIGITAL` / `acc_TTFSyolquKEZEy` | `config/lambda-env-manifest.json:101-102` |
| `CHECKOUT_FUNCTION` | `wecare-checkout:live` | `config/lambda-env-manifest.json:172` |

### Safety invariants held (do not regress)

- **Server-side pricing only.** The inbound invoke payload carries `lines`/variants/quantities
  only — never a client amount. `_native_cart` resolves price via `_create` → `_native_quote`
  (ProductsTable, integer paise).
- **One PaymentAttempt + one idempotent Order** carrying `contactId` + `customerUuid`, shared by
  both legs. `finalization.accept_paid` keeps the CUSTOMER_IDENTITY terminal invariant.
- **WABA1-only** collects (`wa_payment_request.PAYMENT_SENDERS`); a verified customer
  (`checkoutCustomerId` matching the sender E.164) is required; unpriceable/unattributable carts
  leave no attempt, reference or order behind.
- **Website Razorpay path unchanged** and authoritative (`amplify/functions/payments/razorpay-webhook`).

---

## Go-live steps (real world — owner / operator actions)

These are ordered. Do not skip the verification sub-steps; each one is the difference between
"the repo says enabled" and "a real customer can actually be charged".

### 1. Confirm the Meta side is real

- [ ] An **approved** WhatsApp **ORDER_DETAILS** payment template exists on the live WABA
      (WABA1 — the only one permitted to collect).
- [ ] An **active payment configuration** (Razorpay) is attached to that WABA and is in **live**
      (not test) mode.
- [ ] If out-of-window order-status updates are wanted, the **ORDER_STATUS** template is approved:
      `python scripts/provision_order_status_template.py`.

### 2. Supply the readiness values to the LIVE checkout function

The repo manifest records the intended readiness values, but `scripts/provision_checkout.py`
writes them **empty** by design (`EXPECTED_CONFIGURATION_NAME` / `EXPECTED_PROVIDER_MID` at
`:542-543`) — `payment_readiness` stays owner-gated until an operator supplies them from a live
Meta/Razorpay readback.

- [ ] Set `EXPECTED_CONFIGURATION_NAME` and `EXPECTED_PROVIDER_MID` on the **deployed**
      `wecare-checkout` function from the live readback (the values in the manifest are the
      intended ones: `WECAREDIGITAL` / `acc_TTFSyolquKEZEy` — confirm against the live WABA before
      trusting them).
- [ ] Verify: `python scripts/provision_checkout.py --verify` — it checks the readiness keys for
      presence and fails if initiation is on while readiness is unsatisfiable.

### 3. Deploy the three changed Lambdas and move their `live` aliases

- [ ] `wecare-checkout` (new `prepareNativeCart` action, `_native_cart`): deploy + publish a
      version + move the `live` alias.
- [ ] `wecare-inbound-whatsapp` (rebuilt `_send_payment_request`, `_rollback_cart_order_index`):
      `python scripts/deploy_inbound_whatsapp.py` (deploys `$LATEST`, publishes a version, moves
      the live alias; uses `snapstart_publish.py` for the alias).
- [ ] `wecare-whatsapp-business-api` if its env (`WHATSAPP_CATALOG_SERVICES_ENABLED`) changed.
- [ ] Confirm each function's **live env** actually carries the flag values from
      `config/lambda-env-manifest.json` (a manifest is a declaration, not a readback). Use
      `scripts/check_deployed_source.py` to compare deployed bytes.

### 4. Post-deploy verification (read-only, no sends)

- [ ] `python scripts/checkout_release_check.py --live` — read-only customer release gate
      (checks `/cart/`, `/checkout/`, `/account/sign-in/`, `/orders/` real rendered anchors).
- [ ] `python scripts/post_deploy_health.py` — post-deploy health.
- [ ] `python scripts/provision_checkout.py --verify` again against the live artifact.

### 5. Controlled first live transaction

- [ ] With a **real but internal** phone + a minimal cart, run one end-to-end native WhatsApp
      purchase: catalog `order` message → ORDER_DETAILS template → pay → `razorpay-webhook`
      confirms → one Order appears in `/orders/`.
- [ ] Confirm exactly **one** PaymentAttempt and **one** Order were created (idempotency), both
      carrying `contactId` + `customerUuid`.
- [ ] Confirm a redelivery of the same WhatsApp message does **not** create a second attempt/send.

---

## Rollback

Every change is flag- or alias-reversible without a code revert:

- Set `WA_CATALOG_ORDERS_ENABLED=false` on `wecare-inbound-whatsapp` (fail-closed; a SystemConfig
  row can also toggle `_catalog_orders_enabled()` at runtime with no deploy).
- Set `WHATSAPP_CATALOG_SERVICES_ENABLED=false` on the readers.
- Clear the readiness values on `wecare-checkout` — `payment_readiness` then blocks every payable
  send independently of any other flag.
- Move any `live` alias back to the prior version.

Any one of these stops new native WhatsApp charges immediately.

---

## Audit trail

- Owner authorization (2026-10-21): "build and enable the FULL native WhatsApp ORDER_DETAILS
  payment leg for BOTH the catalog-service/invoice leg and the general cart leg: rebuild
  `_send_payment_request`, relax `CART_PAYMENT_IS_WEBSITE_ONLY`, and turn on
  `WHATSAPP_CATALOG_SERVICES_ENABLED` and `WA_CATALOG_ORDERS_ENABLED`."
- Implemented across PRs #1187 (initiation gate), #1195 (customerUuid parity), #1216 (full native
  payment, both legs). Two semantic reviews APPROVED; full backend suite green.
- This reverses the 2026-10-01 website-only ruling for these legs. Earlier repo docs/learnings
  describing native WhatsApp payment as "retired / not live" are **superseded** by this change.
