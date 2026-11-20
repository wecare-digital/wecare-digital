import { defineFunction } from '@aws-amplify/backend';

/**
 * Unified Contacts Lambda Function
 * 
 * Replaces: contacts-create, contacts-read, contacts-update, contacts-delete, contacts-search
 * Routes by HTTP method: GET (list/read/search), POST (create), PUT (update), DELETE (refused pending complete erasure)
 */
export const contacts = defineFunction({
  name: 'wecare-contacts',
  entry: './handler.py',
  runtime: 20, // Python 3.12
  timeoutSeconds: 300, // Junk-contact cleanup scan reads the contact, message and payment tables
  memoryMB: 512,
  environment: {
    AWS_REGION: 'us-east-1',
    LOG_LEVEL: 'INFO',
    CONTACTS_TABLE: 'stack-wecare-digital-ContactsTable',
    INBOUND_TABLE: 'stack-wecare-digital-WhatsAppInboundTable',
    OUTBOUND_TABLE: 'stack-wecare-digital-WhatsAppOutboundTable',
    // Read-only for guarded deletion refusals: a contact tied to a payment or an order
    // may be archived but never destroyed. Both indexes are already readable by the shared
    // role, so these names add no grant. The handler defaults match these literals, so the
    // guard works whether or not the variable is live yet.
    INVOICES_TABLE: 'stack-wecare-digital-InvoicesTable',
    ORDERS_TABLE: 'stack-wecare-digital-OrderTable',
    // Read-only inputs to the junk-contact cleanup scan (payment evidence and message history).
    // The shared role already reads every stack-wecare-digital-* table (amplify/iam-policies.ts).
    MESSAGES_TABLE: 'stack-wecare-digital-MessagesTable',
    PAYMENTS_TABLE: 'stack-wecare-digital-PaymentsTable',
    PAYMENT_ATTEMPTS_TABLE: 'stack-wecare-digital-PaymentAttemptsTable',
    SYSTEM_CONFIG_TABLE: 'stack-wecare-digital-SystemConfigTable',
    // The handler already defaults to media_paths.BUCKET, so this line only mattered
    // on deploy — where it would have overridden a correct default with the bucket
    // deleted on 2026-09-28.
    MEDIA_BUCKET: 'wecare-digital-get',
  },
});
