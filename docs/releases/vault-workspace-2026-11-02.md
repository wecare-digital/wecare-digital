# Dedicated Vault workspace

`/workspace/vault/` has Create, Control and Log. Payments navigation and the old bare Vault Create bookmark lead here. Collect remains a separate custom invoice workspace.

Create selects a saved customer, previews a local PDF/JPEG/PNG, registers and verifies a create-only private upload, or selects that customer's current file. Only an active, unpaid file with a fresh staff preview can request payment. The reviewed integer total is sent to the backend. An uncertain upload retains its known file ID; confirmation recovers that upload rather than registering another one. A previously attempted payment stays blocked in the session until the operator checks the existing journey.

Express is mandatory: Contribute 1500 paise, Request · Vault 2500 paise, all other 27 fixed items 4500 paise. The existing GST, Delight and convenience formulas are retained. At the current 4900-paise Vault base the total is 8497 paise. Vault identification uses the exact server-owned product and variant, so Shipment Track's identical base does not receive the exception. Frozen historical orders/invoices are not rewritten.

Log separates file/access state and provider message evidence. The staff message-log API exposes a paid invoice ID only after matching file owner, paid entitlement, grant and payment reference. Receipt view/download obtains a fresh signed URL for the saved PNG; order navigation requires the invoice/order link to match. Unavailable evidence remains unverified. Staff file preview does not redeem a customer access window.

New access resends use a unique request ID, compare-and-set file claim and stable outbound idempotency key. Unconfirmed sends block a different request ID. Existing paid/file/owner/storage guards remain authoritative. No new standalone interactive sender or Meta Flow is introduced. Approved template content and native payment transport are retained.

Control contains the live sender, approved message content/media/variables, ordered journey, existing access timing editor and API/function/table map. Configured waits and measured evidence gaps are displayed separately.

Verification: TypeScript, lint, Node tests, Python tests, 29-item exact-paise pricing checks and production export. The actual TSX was also exercised with isolated browser API fixtures at 1440/390/320 pixels: private preview, upload recovery, exact total, double-click guards, invoice/order link, PNG download and access resend. No real file upload, customer message, invoice or payment is created by these checks.

Backend rollout: canonical packager; publish reviewed code and update `live` aliases with revision checks for secure-files, checkout/commerce, and consumers of the shared current service-pricing modules. Preserve environment variables, layers and infrastructure. Verify live service-prices and the authenticated staff page after rollout.
