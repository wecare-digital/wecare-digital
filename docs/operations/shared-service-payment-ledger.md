# Reusable service pricing, payment imagery and invoice ledger

## One money engine, several entry points

Vault, Drop Docs, Submit Request, Request Amendment, Request Pickup and future
service areas **must not** create independent Razorpay, Meta payment,
PaymentAttempt, GST invoice or fee calculators. The canonical Commerce checkout
and invoice engine own all financial transitions, and the existing outbound
WhatsApp sender owns the approved template payload.

### Server-owned presentation contract

`GET /ecommerce/service-prices` is a *public, read-only* catalogue quote preview,
not permission to charge. The catalogue's variant `priceMinor` is authoritative,
currency is INR, and a missing/malformed price fails closed. Vault and Drop Docs
receive the same GST, Delight, Express and convenience-fee breakdown in integer
paise. The actual checkout still prices and freezes its own server-side quote.

The `prices.vault.templates` and `prices.drop-docs.templates` payloads both
include `nativePay`, `orderStatus`, `orderStatusStates`, `receipt`,
`delivery`, `headerImage` and `itemThumbnail`. The **only** source of these
two images is `lambda_utils.template_media`:

- Approved payment template header:
  `PAYMENT_TEMPLATE_HEADER` / shared WhatsApp template header
- Approved ORDER_DETAILS icon:
  `DEFAULT_ORDER_ITEM_THUMBNAIL` / original 2048px WECARE image

These assets are **different**. The item icon is not a replacement for the
Meta-approved IMAGE header. They are metadata for staff previews; passing them
from the browser to Meta or to a payment API is forbidden. The invoice template
always uses the separately generated *paid* PNG, after provider capture.

### The same ledger in Pay and Vault

The one read-only invoice API accepts a **staff** service filter, for example:

```
GET /invoices?serviceKind=VAULT
```

`serviceKind` is checked against the existing service allowlist, then verified
against the exact immutable `PAYREF#<referenceId>` reservation, corresponding
`PaymentAttemptsTable` row, **paid** status, Razorpay provider payment ID,
captured amount in integer paise and optional same invoice identity. String
matching on an invoice description, price, customer phone, template name or
filename is never sufficient evidence for a Vault purchase.

An unclassified invoice stays in the **all-invoices** ledger; it is not falsely
attributed to Vault. This filter is read-only. It does not write a payment,
counter, attempt, entitlement, or invoice. It reuses existing GetItem IAM
permissions and requires no new table or GSI. At higher volume, introduce an
audited service-attribution projection rather than scanning payment events.

Staff UI entry points:

- `/workspace/payments?view=ledger&ledger=invoices`: all invoices (unchanged)
- `/workspace/payments?view=ledger&ledger=activity`: latest stored activity (unchanged)
- `/workspace/payments?view=ledger&ledger=vault`: Vault-filtered canonical invoice records
- `/workspace/service?view=vault&tab=ledger`: *the same* Vault-filtered component
- Future internal services can reuse `InvoiceRecords embedded serviceKind="..."`
  without maintaining an independent ledger or rendering new money state.

Ledger rows, stored totals, payment statuses and invoice delivery evidence are
shown as recorded, never recalculated. The invoice number and receipt image are
issued only on verified capture. Staff payments views remain authenticated; do
not expose this ledger in the public `/vault/` customer file browser.

### Vault target binding

A Vault charge must be bound to **one owner-verified file**. The Vault workspace
offers/reissues the approved payment request; public website Vault checkout
uses the owner-bound service intent. A generic free-text staff invoice with a
`Vault` item does **not** create an access entitlement. Therefore the Pay
"Default invoice items" Vault shortcut opens Workspace Vault instead of
prefilling generic Collect; old `?view=collect&preset=vault` deep links fail
closed and tell the operator to open the service first.

### Release / acceptance

1. Run payment-safe PR CI, new `test_service_payment_contract_ledger.py` tests,
   and the hermetic Meta + Razorpay capture/refusal suite.
2. Backend invoice filtering and media data need a new **reviewed** immutable
   Commerce Lambda bundle; a front-end deployment alone cannot activate them.
3. Verify `wecare-commerce:live` version, source and `CodeSha256` against
   that bundle before announcing Vault ledger availability.
4. Smoke-test authenticated Vault Ledger and Pay Vault ledger on the same
   invoice and inspect WhatsApp delivery log. Verify a non-Vault invoice is
   excluded and the all-invoices ledger still includes every record.
5. Do not create an unnecessary live charge, resend a customer message,
   modify the FY invoice counter or change the frozen payment rail to test UI.


## 2026-10-31: Service workspace expanded to all requested operations

Staff route: `/workspace/service`. Top-level sections now include:

| Workspace area | Backend identity | Staff action / fulfilment | Shared price and ledger |
| --- | --- | --- | --- |
| Submit Request | `SUBMIT_REQUEST`, `RSR7M2P9` | Existing owned order, paid Submit Request Meta Flow | Server catalog item price, verified service invoices |
| Request Amendment | `REQUEST_AMENDMENT`, `RAM5Q8K4` | Amend verified existing-order request in paid Flow | Same |
| Drop Docs | `DROP_DOCS`, `RDD9P3M7` | Document manager for **upload**; F003 after paid authorization | Same; separate upload fulfilment template |
| Vault | `VAULT`, `RVT6K4Q8` | Staff SecureFiles and private **download** entitlement, no F003 | Same; separate download fulfilment template |
| Shipments → Track | Catalog product `SHT8M5P3` | Existing owned-order tracking in Commerce Orders; separate paid SKU exists | Catalog price only, not a sixth service-Flow ledger |
| Shipments → Pickup Request | `REQUEST_PICKUP`, `SHP7Q4N9` | Paid pickup Flow; separate published-asset + availability gate | Server price and verified pickup invoice ledger |
| Contribute | `CNT5Q2M8` catalog product | Voluntary purchase; no fulfilment Flow | Catalog price/fee policy; existing commerce invoice/activity, legacy non-invoice captures stay in PaymentsTable |

**Not all item prices are final totals.** Only Vault/Drop Docs have an exposed full
server breakdown in `GET /ecommerce/service-prices`; other services can quote their
catalog item price, but final payable authority remains the frozen backend
checkout (GST, Delight and convenience policy can differ by service).

The same approved Meta payment template and shared default IMAGE header +
ORDER_DETAILS item icon metadata are published for the five request services.
Their post-payment fulfilment buttons are **not interchangeable**. Contribute
and paid Track SKU must not be advertised as request service Flows.

### URL and release contract

- `/workspace/service?view=vault&tab=ledger` must route to **Ledger**,
  never `tab=logs`. `scripts/test-workspace-service-routes.mjs` tests the
  actual TypeScript route helper at runtime for every combination.
- `/workspace/service?view=drop-docs` opens the authenticated upload manager.
  `/workspace/service?view=vault` opens SecureFiles; no shared file-send action.
- `/workspace/service?view=shipments&tab=track` shows existing-order tracking
  entry and a separate, read-only Track catalog SKU price.
- `/workspace/service?view=shipments&tab=pickup` shows Pickup catalog price;
  the server and public checkout keep Pickup **disabled** until separate release
  gates confirm the published Meta asset and successful paid end-to-end flow.
- `/workspace/payments?view=ledger&ledger=<service-slug>` reuses verified
  `InvoiceRecords` for any of the **five** request services, and nothing else.
- `/workspace/forms` legacy redirect `view=requests` resolves to the new
  Submit Request staff section; it does not reopen retired public routes.

**No payment initiation, message send, price write, invoice numbering or
fulfilment mutation** is permitted by any price or ledger tab. A backend and
Amplify release must pass the existing payment-safe checks, read back the live
Lambda alias and Amplify job, then verify an owner-bound Vault invoice appears
in Vault and Pay while unrelated invoices are excluded. Legacy Contribute
settlement cannot be attributed to a statutory invoice because it intentionally
creates none. Do not fabricate one or sum it as a paid service invoice.
