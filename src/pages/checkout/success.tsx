/**
 * Backwards-compatible entry point for historical /checkout/success/ links.
 * Do not maintain a second success/failed/pending decision: the one
 * /checkout/status/ component reads the authenticated PaymentAttempt and
 * shows paid only with a verified state and owned order number. Reusing the
 * same component also preserves the secure Vault return and invoice/order CTA.
 * An arbitrary ?a= URL is never proof of payment.
 */
export { default } from './status';
