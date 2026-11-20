# Contact cleanup in the workspace

Customers, Manage data, Contact cleanup removes junk contacts from view with the existing reversible Archive. It deletes nothing. The policy is `docs/ops/scoped-whatsapp-contact-payment-retention-2026-11-20.md`. The read-only command line report is described in `docs/ops/contact-cleanup-dry-run.md`.

## Scan

1. Optionally enter the contacts to keep by exact contact id, exact full phone or BSUID. Names are never used, and two contacts with the same name stay distinct.
2. Run the scan. It is read-only and reads the contact, message, payment, invoice and order tables.
3. The result shows counts, one page of archive candidates (masked phone and message total), the kept contacts with their keep reasons, and a TTL note.

If the scan could not read every record, the status is not `OK`, the page shows the problems, and there are zero candidates and no confirmation token. Nothing can be archived from an incomplete scan.

## What is kept

A contact is kept, never a candidate, when it has any of:

- paid messages or other payment communication
- invoices
- payment links or payment attempts
- orders
- a lock (legal or financial retention)
- an operator hold by exact id, phone or BSUID, including contacts merged into a held contact

Everything else that is not already archived is a junk candidate.

## Archive and restore

- Archive applies to the whole scanned page. To exclude a contact, add it to the keep list and scan again.
- A reason is required (up to 500 characters).
- Each scan returns a single-use confirmation token bound to exactly the ids on that page. Archive consumes it.
- Scan and archive both require an Admin with MFA (the scan reads every table and writes a token row, so Operators cannot start it).
- Archive re-runs the scan first. If any contact is no longer eligible (new evidence, a lock, already archived), the request returns 409 `CLEANUP_NOT_ELIGIBLE` with a per-id reason map, nothing is archived, and the UI shows the first reasons. Scan again.
- Archived contacts are restored from the contact's Restore action. Every archive is audited with masked ids.

## Limits

- Page and batch limit: 200 contacts per scan page and per archive request (scan default 100). Work through further pages with the next offset.
- Keep list: at most 500 values per list.
- Scan time: the contacts function timeout is 300 seconds, and the UI request waits up to 300 seconds. The scan reads whole tables, so it grows with data volume.

## TTL gap

TTL is enabled on MessagesTable, WhatsAppInboundTable and WhatsAppOutboundTable and disabled on PaymentsTable, PaymentAttemptsTable and InvoicesTable (verified 2026-11-20). Payment related WhatsApp messages can therefore expire on their own. The scan shows the TTL note from the report, but the UI does not rely on live TTL: it does not query TTL settings (`checked` is false) and does not change them. Treat the note as a warning and resolve the gap as described in the retention policy.

## Identity deletion: not delivered

Permanent deletion of contact identities is not implemented. The only cleanup action is Archive. Deleting identities stays blocked until these gates from the retention policy are met:

- a cross-service exact-key and S3 object version dry run
- a reviewed retention and legal decision
- operator approval with MFA
- a writer-fencing lease
- audited, resumable deletion
- reconciliation of every dependent record, with any partial state reported as a refusal

Until then, remove junk by archiving, and do not delete rows from DynamoDB or S3 by hand.

## Review follow-up (2026-11-20)

Fixed:

- MFA gate: tests now run the real `require_auth` with `ADMIN_MFA_REQUIRED=true`. An Admin without MFA is refused on scan and archive, an Admin with MFA passes, and an Operator is refused.
- Unthrottled scans: `cleanup_scan` is now Admin with MFA, and the Scan button is disabled for other roles.

Not fixed, with reasons:

- Synchronous full-table scans and the 29 s API Gateway limit: not verified, and moving to a job plus poll design is a larger change than this review pass. If the route is behind a 29 s cap, the UI will see a 504 while the Lambda keeps running. Nothing is archived in that case (fail closed). Before using this on a large dataset, confirm the integration timeout. Follow-up: asynchronous scan job.
- Memory ceiling: per-page aggregation is a classifier redesign. A crash fails closed. Follow-up with the async job.
- Identity erasure: out of scope by policy, `CONTACT_ERASURE_NOT_READY` unchanged. The owner must start the legal review described above.
