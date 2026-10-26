/**
 * The customer's words for an order's two statuses, shared by the order history (/orders/) and
 * the order page (/orders/?o=).
 *
 * Two vocabularies, deliberately kept apart, because they answer different questions:
 *   - PAYMENT: what the money did. Keyed on the canonical `lambda_utils.payment_status` word the
 *     server already mapped ('PAYMENT_PAID', 'paid' and 'completed' all arrive as 'captured').
 *     Re-introducing any provider spelling here would start a second payment vocabulary.
 *   - FULFILMENT: what happened to the order after it was paid. Keyed on Meta's order_status
 *     wire words (`lambda_utils/ecommerce/wa_order_status.py`), which the order row carries.
 *
 * Lookups rather than chains of comparisons, which is the shape that cannot drift. An unknown
 * word has no label; the caller says the status is unavailable rather than guessing one.
 */

/** Payment status labels, keyed on the canonical payment word. */
export const PAYMENT_STATUS_LABEL: Readonly<Record<string, string>> = {
  captured: 'Paid',
  authorized: 'Payment held',
  pending: 'Payment confirming',
  created: 'Started',
  failed: 'Not paid',
  refunded: 'Refunded',
  disputed: 'Under review',
};

/** The one-line explanation shown beside a payment status that needs one. */
export const PAYMENT_STATUS_NOTE: Readonly<Record<string, string>> = {
  authorized: 'We are confirming this with the bank.',
  pending: 'This usually settles within a few minutes.',
  created: 'This order was started but not paid.',
  failed: 'No money was taken.',
  refunded: 'The amount has been returned.',
  disputed: 'We are looking into this payment with the bank.',
};

/** Fulfilment status labels, keyed on Meta's order_status word. */
export const FULFILMENT_STATUS_LABEL: Readonly<Record<string, string>> = {
  pending: 'Awaiting payment',
  processing: 'Being prepared',
  'partially-shipped': 'Partly shipped',
  shipped: 'Shipped',
  completed: 'Completed',
  canceled: 'Cancelled',
};
