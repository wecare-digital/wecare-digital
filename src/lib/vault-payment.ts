import type {SecureFile} from '../api/domains/platform';
type PaymentFile = Pick<SecureFile, 'status' | 'accessState'>;
export function isVaultPaymentRefused(outcome?: string): boolean {
  return outcome === 'PAYMENT_REQUEST_REFUSED'
    || outcome === 'VAULT_QUOTE_CHANGED'
    || outcome === 'VAULT_DELIVERY_CONFIRMATION_REQUIRED';
}
/** Owner decision (2026-11-04): staff Vault payments have no send limit. Any active, unpaid file
 *  can be sent (or resent) at any time; only a request already in flight from this screen
 *  (`localPending`) waits for its answer. Paid/open/expired files are never sold again. */
export function canRequestVaultPayment(file?: PaymentFile | null, localPending = false): boolean {
  return !!file && file.status === 'active' && file.accessState === 'UNPAID' && !localPending;
}
