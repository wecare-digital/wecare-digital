# Contact cleanup dry run

`scripts/contact_cleanup_dry_run.py` is a read-only report. It tells an operator which contacts must be kept and which are candidates for the existing reversible Archive. It never archives, deletes, updates or writes anything, and it never changes TTL settings. The governing policy is `docs/ops/scoped-whatsapp-contact-payment-retention-2026-11-20.md`.

## Prerequisites

- Python 3 with `boto3`.
- Your own AWS credentials with read access: `dynamodb:Scan`, `dynamodb:Query`, `dynamodb:DescribeTimeToLive` on ContactsTable, MessagesTable, WhatsAppInboundTable, WhatsAppOutboundTable, PaymentsTable, PaymentAttemptsTable, InvoicesTable and OrderTable (including the `contactId-index` of InvoicesTable and the `customerId-createdAt-index` and `customerPhone` indexes of OrderTable).
- Table names default to `stack-wecare-digital-<Name>`. Override with `--table-prefix` or `--contacts-table`, `--messages-table`, `--inbound-table`, `--outbound-table`, `--payments-table`, `--attempts-table`, `--invoices-table`, `--orders-table`.

## Choosing the contacts to keep

Selection is by identifier only: canonical contact id, exact full phone, or BSUID. Contacts merged into a selected contact (or merged into it by an earlier merge) are kept too. A display name is never a selector, and two contacts with the same name stay distinct.

Pass identifiers on the command line, or in a private JSON file:

```json
{ "contactIds": ["<contact id>"], "phones": ["<full E.164 phone>"], "bsuids": ["<bsuid>"] }
```

Keep that file outside the repository (or in a gitignored path). The script refuses a selection file or an `--output` path that is inside the git work tree and not gitignored. Do not commit identifiers.

Use the expectations as a safety check:

```
python scripts/contact_cleanup_dry_run.py \
  --keep-config ~/private/keep.json \
  --expect-keep-contacts <N> --expect-keep-messages <M> \
  --output ~/private/dry-run-report.json
```

If the resolved kept contacts or messages differ from the expected numbers, a selector matches nothing, or a selector matches more than one contact, the run exits with code 3 and no contact is reported as eligible.

## Reading the output

Each contact gets one label, highest precedence first:

| Label | Meaning |
| --- | --- |
| `OPERATOR_HOLD` | Selected by you. Its identity and every message in all three message tables are kept. |
| `FINANCIAL_RETENTION` | Linked to an invoice, order, payment, payment attempt, or a payment-related message. |
| `LEGAL_OR_IDENTITY_LOCK` | The contact row is locked. |
| `REVIEW_REQUIRED` | Anything unknown, unreadable, ambiguous or truncated. |
| `ELIGIBLE_FOR_APPROVED_ACTION` | Every read succeeded and nothing protects it. |

Message classification only adds protection. A payment reference attribute, a payment-like template or message type, provider ids, payment keywords, or a match against ids in the payment tables keeps a message. Not finding any of those is not proof that a message is unrelated, so review the eligible list before acting.

Stdout shows hashed labels, masked phones (last four digits) and counts, never message bodies. The eligible list prints the exact contact ids you would archive. The `--output` JSON (mode 0600) adds per-table counts, reasons, and the TTL at-risk list. Keep it private.

Exit codes: `0` complete, `2` an inventory read failed or was truncated (nothing eligible), `3` selection problem or expectation mismatch (nothing eligible), `64` usage error.

## TTL gap

TTL is enabled on `expiresAt` for the three message tables and disabled for the three payment tables. The report shows the live TTL state (read only) and lists every payment-related message and every kept-contact message that expires within `--ttl-warn-days` (default 90) or has already passed. Remediation is in the policy: copy to an approved durable evidence store, or get a reviewed, minimized TTL exception. The script does neither.

## Acting on the result

The only cleanup path is the existing reversible Archive in the contacts API, run by the operator with Admin + MFA and a reason, for individually reviewed contacts. Archive keeps identity and history. Permanent delete stays refused (`CONTACT_ERASURE_NOT_READY`), and locked contacts cannot be archived. Copies in S3, Meta and Razorpay are not covered by this report.
