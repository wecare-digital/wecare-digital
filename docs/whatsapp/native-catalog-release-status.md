# Native WhatsApp catalog service integration — 8 October 2026

Implementation and AWS deployment are complete for the bounded draft. Customer release is NOT certified: no owner QA number has been supplied, the paid Submit Request Flow is still DRAFT, and external Wix writeback/purchase rollout remain disabled.

## Deployed changes

| Function | Live | Original rollback |
| --- | --- | --- |
| wecare-checkout | 36 | 34 |
| wecare-whatsapp-business-api | 76 | 74 |
| wecare-inbound-whatsapp | 88 | 86 |
| wecare-outbound-whatsapp | 55 | 54 |

Existing deployed archives were preserved and only the named integration modules overlaid. Revision and code hash checks refused concurrent deployment drift. The dedicated checkout role now has an additive CheckoutNativeCatalogAuthority policy for GetItem on the contact/service-intent tables, ListUsers on the customer pool, and InvokeFunction on the live outbound sender. All four exact permissions read back as allowed. Existing provider secret access, payment configuration and webhook verification were not changed.

## Customer journeys

Submit Request:
WhatsApp catalog item -> permanent verified customer identity -> at least one earlier owned order -> authoritative Wix service price and frozen quote -> wecarepay_wa payment request -> provider-verified capture -> canonical internal order -> non-charging Wix external order/payment record -> completed Wix cart -> paid details Flow -> earlier order selection -> subject/details/review/submit -> transactional service request and workspace projection -> once-only wecare_leave_review.

The new Submit Request purchase is a service order. It does not become the earlier order the request is about. The selector includes the latest 100 earlier customer-owned orders across product/service types, not only Submit Request purchases.

Vault:
WhatsApp catalog item -> verified owner -> select an active customer-owned unpaid file -> freeze file/intent -> authoritative Wix quote -> wecarepay_wa -> verified payment and canonical/Wix order linkage -> deterministic file access grant -> approved dynamic download template (when its release flag is enabled) -> authenticated Vault link -> private signed download; an ordinary PDF message is sent when a PDF delivery object is ready and the 24-hour session permits it -> once-only review message after delivery acceptance.

Catalog prices remain service base prices INR 99 / INR 49. Existing convenience fee and GST policy remains in the quoted payable total; the native payment message itemizes it.

## Fixes made during integration

- Submit Request refuses payment when no earlier owned order can be fetched.
- Vault refuses to charge for an unavailable/revoked/foreign file and excludes already unlocked files; ownership is checked again on selection.
- One active native service purchase per permanent customer and one source-message claim prevent duplicated payment preparation.
- Changed/re-added contacts need a verified link to the permanent customer; matching a phone alone never grants ownership.
- Native checkout verifies the site-bound writeback gates and exact approved Meta templates before preparing a payable reference.
- Submit Request payment preparation also requires Flow 1107164111921876 to be PUBLISHED with no validation errors.
- Dynamic download buttons accept file identifiers only. Outbound wiring limits the feature to wecare_default_download; no arbitrary URL is passed.
- Wix mapping relays per-line calculated taxes, includes service item types and verified phone, records convenience GST separately, and uses the documented shipping field.
- Created Wix order totals/currency must match the frozen quote. A mismatch retains the provider order ID and stops fulfillment; re-entry cannot create another order.
- Main order records retain channel/source, paid amount and finalization state; the workspace list maps PAYMENT_PAID to paid, traverses result pages and searches public order numbers/Wix IDs.
- Frontend changes display the public order number, Wix order ID, payment reference and correct total. These require the frontend release, separate from the deployed Lambda versions.
- Submit Request review is queued only after saved details and rechecks the verified recipient. Persistent send claims prevent automatic duplicate messages.

## Provider readback

| Provider object | Verified state |
| --- | --- |
| WD_Leave_Review_v2 / 1578178897413815 | PUBLISHED, no validation errors |
| WD_Submit_Request_Paid_v1 / 1107164111921876 | DRAFT, no validation errors; endpoint https://wecare.digital/api/wa-business/flow-data |
| wecarepay_wa / 1783774039408860 | APPROVED, English, image header and ORDER_DETAILS button |
| wecare_default_download / 1410998911012572 | APPROVED, English; URL https://wecare.digital/vault/?file={{1}} |
| wecare_leave_review / 1801972550682516 | APPROVED, English; FLOW button points to review Flow 1578178897413815 |

The normal native purchase starts from an inbound customer message. Paid Submit Request invitations require that conversation to remain within Meta's 24-hour window. Outside that window, the current handler returns AWAITING_CUSTOMER_MESSAGE; it does not substitute a review template or send an unapproved Flow invitation.

## Validation

532 integration/regression tests passed, 1 skipped, 1 existing expected failure. Secure files: 84 passed. Vault frontend: 6 passed. TypeScript typecheck passed. Total backend passing tests: 616.

Live invocations verified native preparation/entry return NATIVE_SERVICE_ROLLOUT_DISABLED while gated; HTTP-shaped diagnostic access returns 403; incomplete encrypted Flow input returns 400. These are deployment/safety smoke checks, not customer purchase evidence.

## Remaining release steps

1. Owner approval to publish the exact paid Submit Request draft. Automatic approval review rejected publication because approval for this specific draft was required; approval has been requested. No bypass was attempted.
2. Owner supplies a personal QA WhatsApp number with country code, signs into the verified customer account, and completes the payments personally. An earlier legitimate order is required for Submit Request; an uploaded owner-specific file is required for Vault.
3. Validate the runtime site's external-order write scope and complete one controlled writeback for each paid QA journey. Enable WIX_WRITEBACK_ENABLED, WIX_ECOM_WRITE_CONFIRMED and the exact site-bound cart-v2-external-v1 contract only when attested.
4. Enable bounded native rollout/dynamic-download flags for QA, then verify each purchase produces one canonical order, correct paid reference, correct Wix order ID, correct request/file, workspace display, delivery and a single review invitation. Do not treat duplicate webhook replay as a new purchase.
5. Keep both Meta catalog items out of stock until those checks pass, then enable availability through the existing two-variant sync.

Ambiguous external creates/sends remain claimed for provider readback/staff reconciliation. They are not automatically retried. No customer test payment, capture, refund, live message, writeback transaction or catalog availability change occurred during this implementation turn.

Machine-readable deployment/readback evidence: native-catalog-integration-evidence.json.

