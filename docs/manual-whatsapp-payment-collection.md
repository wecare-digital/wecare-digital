# Manual WhatsApp payment collection

The reusable, Meta-approved payment template is `wecare_whatapp_native_pay_template` (English, primary account,
Review and Pay / ORDER_DETAILS). Checkout and invoice requests already use it. Staff do not
create a new template per invoice or fill its order parameters by hand.

## Recommended route: Pay Flow

1. Sign in to the workspace with an Admin role and open **Pay → Pay Flow**
   (`/workspace/pay?tab=flow`).
2. In **Customers**, select or save the intended customer and their WhatsApp number.
   For physical goods, save the complete delivery address, city, state and six-digit India PIN.
3. Open **Create**, select the customer and choose **Digital Goods** or **Physical Goods**.
   Enter item descriptions, quantities and unit prices. GST defaults to 18%. Invoice item
   amounts are exclusive of GST; review the server-generated invoice before sending.
4. Check delivery charges deliberately. Set them to zero when delivery is not charged.
   The form's saved/default delivery value is not a determination that delivery applies.
   Delight and convenience fees are calculated by the invoice engine, not entered manually.
5. Choose **Create and send payment request** to create and send one request.
   For a review first, choose **Save invoice for review**, then **Review and send payment request**
   to open that exact saved invoice in **Invoices**. Check its customer,
   goods type, amount and delivery details.
6. Use the primary sender **+91 93309 94400** and choose **Send payment request**. The server
   resolves and verifies the registered payment configuration and reserves the invoice's
   payment identity before sending `wecare_whatapp_native_pay_template`.
7. The customer receives **Review and Pay**, checks the order and pays inside WhatsApp using
   the verified Razorpay configuration. Sending the message does not itself charge them.
8. Check **Invoices**, **Dues**, or **Invoice records** (`/workspace/pay?tab=records`) for the
   reconciled result. A delivered message is not proof of payment; a paid invoice is not proof
   of shipment or completed service.

## Quicker route: Inbox

Open **Engage → Inbox** (`/workspace/engage/inbox`), select a saved customer conversation,
then **Request payment**. Choose the goods type, add the items and applicable GST/delivery,
and select **Send payment request**. This uses the same server-owned invoice and approved
payment template as Pay Flow. There is no manual-discount input or secondary payment sender.
The displayed subtotal is before final server adjustments; the invoice is authoritative.

If sending is refused after an invoice is created, the open composer retains that invoice
for a retry. Changing the draft requires resolving the existing invoice in Pay → Invoices.
After a reload, timeout or uncertain result, check that ledger before creating another invoice.

## Commerce panel

The bill composer at `/workspace/commerce?tab=engine` also calls the invoice path. Select the
primary number for collection. Both numbers remain available for ordinary catalogue messaging;
that does not make both valid payment senders. Physical bills require a saved payable address.
For a payment that needs review before send, use the two-step Pay Flow route above.

## Reuse, retries and status updates

- Reuse `wecare_whatapp_native_pay_template` for different invoices with server-reserved references and exact totals.
- Retrying a single invoice goes through the same reservation/interlock. It does not authorize
  a new charge. Resolve uncertain/pending outcomes before creating a replacement collection.
- Paid or canceled invoices cannot be collected again. To correct an unpaid issued invoice,
  follow the invoice cancellation/replacement process rather than editing its frozen amounts.
- The generic template picker is not a payment composer: it does not reserve an invoice or
  construct the authoritative order_details action. Use Pay Flow, Inbox Request payment, or
  the Commerce bill composer for collection.
- `wecare_whatapp_native_pay_template` requests payment. After verified capture, the paid invoice
  template is sent once. The historical `wecare_order_status_v3` template is retired and is not
  a release prerequisite.
- Capture starts the internal fulfilment state at `processing`. Staff manage fulfilment in
  Commerce → Orders; Track Order reads the same state and no automatic WhatsApp status is sent.

## Release and go-live checks

`WA_LIVE_SMOKE_TEST=true` restricts outbound to the configured QA recipient. The owner has
requested ordinary customer recipients after validation; remove that lockdown only in a
validated, published version, verify the live alias and preserve the old version for rollback.
This permission does not authorize a test message to a customer.

Run `scripts/commerce_release_audit.py` with the deterministic release manifest and the
expected merged website commit. It compares all seven live code hashes, payment expectations,
QA mode, actual provider template/configuration readback and the hosting deployment. It reports
payment readiness and the hosted commit separately. It never prints credentials.

CI checks run for pull requests, stack pushes and merge-queue candidates. At the owner's
request, required status-check enforcement was removed from stack so running checks do not
block merging. Review their reported results before releasing a change.

The convenience fee is 2.5% of the canonical collection amount, plus 18% GST on
that fee (2.95% effective). Item GST is separate. Existing tax-inclusive catalogue
prices and captured invoice totals must not have GST added a second time.

Cancel an unpaid invoice with **Cancel Invoice**. Its number and history are retained;
previous WhatsApp messages are not retracted. The default **Active** invoice list hides
cancelled invoices, which remain available under **Cancelled** or **All**. Commerce is
always available without an environment switch. Standard Indian state abbreviations
(such as WB) and their existing ISO subdivision codes resolve through the shared state table.
