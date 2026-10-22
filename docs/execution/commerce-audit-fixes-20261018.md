# Delight and WhatsApp commerce audit fixes

Fresh invoice collections and native checkout use the same Delight policy: 0.5% of eligible
GST-inclusive goods, capped at Rs50. Delivery, packing, notifications and handling do not
increase Delight. Settled receipts and exact-price service flows retain their existing totals.
A new invoice refuses retired coupon/manual-discount inputs before consuming a number.
Service/contribution baskets do not display the automatic-discount promise.

Checkout data-exchange callbacks cannot change an already reserved payable. Shipping changes
return `SHIPPING_REQUIRES_CHECKOUT`; the customer must choose delivery before a new payment
request is reserved. Retired coupon actions return a versioned refusal without mutating the order.

The order-status template fallback from upstream is retained. Its readback now requires the
the approved `wecare_default_invoice_image_template` in English on the sender's WABA.
The template inventory follows cursors on the same WABA endpoint and refuses partial results.
The `order_status` preset creates a fixed-body utility template with the required subcategory;
its provider approval remains an external prerequisite. A captured Razorpay payment reports
`processing`, leaving actual fulfillment completion to the order lifecycle.

## Production rollout

Pushing this branch does not update production Lambda aliases. During the audit the published
invoice/outbound functions still lacked the expected payment configuration and merchant ID;
the published checkout had both. An order-status template was not configured on outbound.

1. Verify the checkout's published payment expectations against the intended merchant and live
   provider configuration. Never substitute guessed merchant IDs or disable readiness gates.
2. Validate the affected packages and the configuration synchronization without mutation:

   ```sh
   python scripts/deploy_all_lambdas.py --dry-run --sync-payment-config \
     wecare-checkout wecare-invoice-engine wecare-outbound-whatsapp \
     wecare-whatsapp-business-api wecare-razorpay-webhook \
     wecare-whatsapp-templates wecare-whatsapp-template-management
   ```

   Use the exact names printed by `python scripts/deploy_all_lambdas.py --list` for the
   deployment account. The explicit synchronization copies only `EXPECTED_CONFIGURATION_NAME`
   and `EXPECTED_PROVIDER_MID` from `wecare-checkout:live` into invoice/outbound `$LATEST`.
   It retains other variables, guards updates with `RevisionId`, waits and verifies readback.
   Runtime provider readiness is still mandatory. Dry-run never updates configuration.
3. In an authorized rollout, run the same command without `--dry-run`. Selected functions that
   fail validation/update prevent alias publication for the batch. Publication detects changed
   environment variables even if the code hash is unchanged.
4. Verify `wecare_default_invoice_image_template` is APPROVED in English on the payment WABA.
   Fulfilment state is stored internally and every customer-facing status notification re-sends
   the issued invoice image from `secure/Invoice/customer_invoice/`.

MCP's bundled page catalogue matched the source at audit time; the source handler's newer
sitemap filtering still requires its separate deployment/verification workflow.
