# Service-specific WhatsApp messaging after payment (31 Oct 2026)

## Why this was raised

A real ₹84.97 paid Vault QA journey (`WD-PAY-GQNGK9FS9TW2YN`) confirmed that payment,
the issued GST invoice, the paid 24-hour entitlement, and the dynamic Vault
download template were working. It also sent an extra raw PDF document in
WhatsApp because the buyer had replied within the 24-hour conversation window.
That additional attachment was not necessary for this **download** service,
and bypassed the owner-bound Vault page. Remove that send while preserving
the approved Access Vault template and download authorization.

The customer should see a **service-specific next action**, never the same
generic post-payment CTA for unrelated services.

## Signed-off common payment rail (do not change without owner approval)

The WhatsApp-native Meta ORDER_DETAILS rail retains the provider-approved
payment-only state machine:

1. `wecare_order_status_v3` processing — *Payment received*.
2. `wecare_order_status_v3` completed — *Payment complete*.
3. One `wecare_default_invoice_image_template` receipt with the issued invoice
   **PNG/image header** and Leave Review Flow button.
4. After the invoice's accepted send, dispatch the service-specific next action.

This is not a second payment and does **not** mean the fulfilment action is
completed. The receipt's currently approved body is generic:
“✅ Payment received. Your transaction has been confirmed.” This duplicates
the processing status in customer-facing copy. **Do not silently edit an
APPROVED template** or change the invoice Flow button; a different invoice
message needs a separately approved Meta template and release plan.

## Routing and customer next action

| Paid service or action | Intended post-invoice WhatsApp action | Source/authorization boundary |
| --- | --- | --- |
| **Submit Request** | Approved `submit_request_flow`, button **Submit Request** | One paid, owner-bound existing-order F004 Flow session |
| **Request Amendment** | Approved `request_amendment_flow`, button **Request Amendment** | Paid owner-bound existing-order F005 session |
| **Drop Docs** | Approved `_dropdoc_flow`, button **Drop Docs**; **upload** via F003 | Paid Flow session, one upload completion only |
| **Vault** | Approved `wecare_default_download`, button **Access Vault**; **download** at `https://wecare.digital/vault/?file=<fileId>` | Verified owner + paid entitlement and time-bounded access; **no raw PDF attachment** |
| **Shipments → Track** | Approved `track_ship_flow`, button **Track Shipment** | Customer/owned shipment or paid Track Shipping SKU when applicable |
| **Shipments → Pickup Request** | Approved `pickup_request_flow`, button **Pickup Request** | Paid owner-bound session, contingent on the pickup published-asset release gate |

Vault does **not** send F003 or another Meta upload Flow. Drop Docs does **not**
send a Vault download URL. Shipping tracking and paid pickup are distinct
operations, not interchangeable with the five request-service SKUs.

### Implemented in this change

- Stop the raw WhatsApp PDF media message for automatic *paid Vault*
  fulfilment, even with a recently active WhatsApp conversation.
- Keep the approved image-header Access Vault template with its per-file URL
  button suffix and the existing `vaultNotificationStatus` exactly-once send
  claim and 24-hour paid entitlement opening.
- Keep invoice generation/receipt, ORDER_STATUS sequencing, prices, Meta
  payment template, and Drop Docs F003 Flow untouched.
- Add an offline runtime regression: a paid PDF file with a private
  `deliveryKey` produces **one** approved Access Vault link, not a media send;
  a replay cannot send a second link or open a second paid window.

### Follow-up requiring separate approval

- If the customer-facing invoice should say *Payment confirmed for Vault*
  instead of the current *Payment received*, propose a revised Meta **UTILITY**
  invoice template and test it with the actual approved template ID before
  using it. Service-specific CTA templates already exist; do not blast a
  generic list of all services after a captured payment.
- Validate real handset order: payment status states, invoice, then only the
  purchased service action; check provider **delivered/read**, not only accepted.
- Reconcile existing `vaultDocumentStatus` audit fields as historical
  evidence. Do not auto-resend the old PDF for purchases completed before this
  change.
- Keep `REQUEST_PICKUP` fail-closed until its separate published-asset and
  paid-handset checks pass.

No post-payment service launch may create another Razorpay order, reopen a
terminal payment, or infer access to another customer's file/order.
