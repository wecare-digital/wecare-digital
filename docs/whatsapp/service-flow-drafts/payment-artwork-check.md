# Service payment and artwork check — 9 October 2026

Historical checkpoint: versions and repair gaps below describe the earlier inspection. For the subsequent deployed Vault retry/paid-state repairs, business API 88, checkout 41 readback and catalog-sync 7 staging, use [the current execution ledger](../../superpowers/plans/2026-10-09-whatsapp-customer-service.md). Native payment/customer QA remains incomplete.

Vault does not require a WhatsApp Flow. The owner-selected journey is catalog → choose an owned document in a native WhatsApp list → Review and Pay → verified payment and order association → paid file grant → dynamic download template/PDF → review. The prior Vault design draft is unused and must not be published or connected.

## Verified live

- Business API live version 79 and checkout live version 40 have native catalog service flags unset, so this rollout is off. `VAULT_DYNAMIC_DOWNLOAD_TEMPLATE_ENABLED` is also unset. Checkout's `WIX_WRITEBACK_ENABLED` and `WIX_ECOM_WRITE_CONFIRMED` are unset, so site-bound external-order writeback is gated.
- Meta readback confirms `wecarepay_wa`, `wecare_default_download` and `wecare_leave_review` are APPROVED in English. Download template 1410998911012572 has an IMAGE header and URL button `https://wecare.digital/vault/?file={{1}}`.
- Paid Submit Request Flow 1107164111921876 is PUBLISHED, with no validation errors and the WECARE flow-data endpoint.
- Each of the six stored catalog PNG objects has a 4096 × 4096 IHDR. Verified by S3 GetObject range bytes 0–23, not inferred from the filename. Exact keys, sizes and ETags are in payment-artwork-check.json. No image compression or replacement occurred.

## Source connection matrix

| Service | Payment / fulfillment connection | Remaining gap |
|---|---|---|
| Submit Request ₹99 | Native checkout source, verified payment dispatch and published paid form exist | Native rollout/writeback off; new design ID is not connected; manual missing-order reconciliation not implemented in published paid form |
| Request Amendment ₹99 | Wix variant and website service path exist | Native catalog service allowlist excludes it; new design not connected to payment or fulfillment |
| Drop Docs ₹350 | Wix variant and website service/upload paths exist | Native catalog service allowlist excludes it; new picker draft is not connected to secure file ingestion |
| Vault ₹49 | Native document list, frozen selected file, payment intent, payment activation, paid grant and delivery code exist | Native rollout/writeback and dynamic-template flags off; delivery retry and consumed-grant purchase UX need repair |
| Shipments | Order lookup utility draft | No independent paid SKU is established; do not invent a charge; live shipment status binding pending |
| Leave Review | Existing published review Flow and approved template | No payment is collected for a review; new design is not routed |

## Missing-order behavior

All four order-related design drafts already offer **I cannot find my order** and a manual **Order number**. Review does not require an order. Vault uses its document ownership selection instead of a form. A manual reference is an unverified claim: do not attach it to someone else's order or charge another service while ownership is unresolved. Future integration must preserve the reference, create a reconciliation state and allow a customer who also lacks the number to contact the team.

The published paid Submit Request implementation currently returns NO_ORDERS for an empty owned-order lookup. Catalog start also declines the payment when no parent order is found. Therefore, the design fallback is not yet implemented in the customer backend. Keep the original order ID separate from the ₹99 service purchase ID and the payment attempt/reference.

## Vault trace and limits

`flows/catalog_services.py` selects only active customer-owned unpaid files; the customer taps a `vaultpick` list row. The selected file is frozen into the checkout session and service intent before any payable message. Zero available files means no charge. `service_request_dispatch.py` sends an ids-only paid-order hint; `paid_submit_request.py` re-reads payment/order proof and delegates VAULT purchases to `paid_vault.py`. `vault_access.py` checks customer, service variant, original file ownership, reference and payment attempt, then transactionally creates one grant.

The dynamic button supplies only the file identifier. `VaultFilePurchase.tsx` retains this pointer through sign-in and filters the authenticated file list. The secure-files backend checks ownership and an unconsumed paid grant before returning a short-lived S3 URL. The public file pointer alone does not authorize a download.

Current delivery chooses `wecare_share_pdf` unless the dynamic-template flag is enabled. With the flag enabled, it uses the verified `wecare_default_download` URL template. That template has an IMAGE header, so it cannot itself contain a PDF attachment. Existing source sends a separate document message during the open 24-hour customer-service window. Outside that window the download template is the access path; use an approved DOCUMENT-header template if an unsolicited PDF attachment is also required.

Two concrete gaps must be repaired before activation: `_send_once` claims each send using attribute_not_exists; SEND_FAILED/SENDING claims cannot retry automatically. Also, the website's paidGrantId disappears after grant consumption, while the file retains vaultPaymentStatus PAID; the current buy box can then display Continue to payment. Reconciliation and a paid/consumed state must prevent accidental repeat purchases. API acceptance is not a delivered-message confirmation.

No customer messages, payment transactions, publications, live flag changes or catalog item mutations were performed in this check. Meta-rendered design screen navigation remains unconfirmed from the previous browser check; handset testing is still required.
