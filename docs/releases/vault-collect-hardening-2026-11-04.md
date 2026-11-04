# Vault and Collect hardening — 4 November 2026

## Changes

- Restore the native Meta shipping phone fix to the checkout source and validate
  the trusted country-qualified phone before quote/reservation. Both checkout
  Lambda names use this source.
- Treat ambiguous outbound responses consistently across Vault and Collect:
  provider/server 5xx, Lambda FunctionError, unreadable/missing application status
  and keyed in-flight results retain the original payment identity and send claim.
  Application 2xx alone cannot prove a send; require provider WAMID evidence and
  reject contradictory unknown/error/dry-run markers.
- Preserve only safe machine reason/status through the native service boundary;
  diagnostic logs no longer copy arbitrary provider/customer messages.
- Keep Collect's allocated invoice number, reference and monetary fields in a
  staged `claiming` row while persisting items. Publish completion only when all
  items are durable. Scan/atomic dedup and send paths refuse incomplete documents.
- Both Collect creation UIs verify full saved details against the exact retained
  reference and invoice ID before clearing recovery state. Incomplete or mismatched
  details stay unresolved; list rows are not proof of completed creation.
- Update the maintained architecture and recovery guide at
  `worker-docs/vault-collect-payment-architecture.md`.

## Validation

Behavioral tests include failure injection at provider-response and item-write
boundaries, positive provider acceptance/completed-invoice cases, physical shipping
validation, safe outcome/diagnostic mapping and exact-reference browser recovery.
Run all Python and Node tests, `scripts/check_collect_contract.py`, TypeScript,
ESLint, handler compilation and the full frontend build before promotion.

No live payment messages, payment captures, paid grants or customer record changes
are part of offline validation. Existing financial documents are not rewritten.

## Release boundary

This change contains source and tests. A frontend merge/Amplify build does not
promote the backend fixes. Release through the existing committed-source route:

- `wecare-checkout` and `wecare-commerce`: checkout source; verify coherent package
  hashes and both live aliases.
- `wecare-whatsapp-business-api`: conservative outcome mapping and machine diagnostics.
- `wecare-secure-files`: sanitized native-payment diagnostic log.
- `wecare-invoice-engine`: Collect uncertainty and document-completeness guards.

Record prior aliases and compare uploaded/promoted package hashes. Preserve roles,
environments, secret references and grants. Never use a broad Amplify backend
redeployment for these existing functions.

Rollback of invoice-engine to a version without the incomplete-document guard can
make a staged claiming row appear complete to that old version. Inspect unfinished
claims and preserve numbering/reference evidence before rollback; prefer a forward
repair when staged records exist. Do not delete claims or issue new numbers as a
rollback shortcut.

## Remaining operational limits

A consumed-number unfinished invoice needs manual reconciliation under its original
identity. This change does not automatically reconstruct missing historical items,
migrate previously partial final invoices or reissue numbered documents. Uncertain
provider sends likewise require exact-reference evidence before another operation.
Existing browser pending markers are retained on uncertainty. The fixes prevent the
identified failure classes; successful offline tests do not establish delivery,
capture or access for a new live transaction.
