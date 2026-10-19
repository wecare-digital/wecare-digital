# Unified commerce completion

Approved by the user for autonomous implementation, testing, deployment and recovery.

Every verified invoice payment must finish as exactly one row in the existing OrderTable using its existing CommerceKeys claim and public order number. Preserve fulfillment on replay. Carry the contact's existing public customerUuid to the invoice and order; never mint an identity on a money path. Require matching reference, invoice, amount, currency, provider payment and contact evidence.

Customer ownership uses Cognito customerId, distinct from public customerUuid and contactId. After the authenticated profile path verifies and binds a contact, promote only paid orders explicitly waiting for that same contact's website link. Query the existing phone index as discovery only, compare contactId and former owner, and condition every write. Never adopt an order solely from a phone match, transfer an existing customer's order, or alter payment/fulfillment state. Paginate and allow retries.

Create customerId-createdAt-v2-index beside v1 with channel and customerUuid, wait for ACTIVE, grant only required index Query access, then publish customer-orders with its serving index updated. Preserve v1 for rollback.

Package tested source deterministically and deploy only the affected functions. Read back live aliases, hashes and routes. A private IAM-only recovery action on the webhook may materialize a saved verified payment from its existing claim without charging, minting a new order, or sending a message. Verify the actual paid 467-paise record, its invoice/contact links, staff and Flow indexes. Website access must remain unavailable until the actual customer proves their account; do not fabricate verification to satisfy a test.

Test behavior first, full backend suite, relevant frontend suite, negative authorization and duplicate-replay paths. Save production changes and readback evidence without customer personal details in outputs. Use AWS MCP for AWS operations. The original checkout contains concurrent changes and must remain untouched.

Review refinement: profile/projection interleavings and eventually consistent phone-index reads require durable retry. The existing webhook's IAM-only reconcileCustomerOrderLinks action runs every five minutes through the CloudFormation-managed EventBridge rule in amplify/infra/commerce-history-reconciliation.json. It scans only pending-link projections, rereads saved contacts consistently and conditionally promotes the original contact's paid order. It cannot charge or send. The profile role receives no scan permission. Existing same-owner orders can be enriched with their authoritative missing UUID without replacing snapshots or fulfillment.
