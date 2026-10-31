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
