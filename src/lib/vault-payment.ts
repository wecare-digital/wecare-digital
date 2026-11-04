import type {SecureFile} from '../api/domains/platform';
type PaymentFile = Pick<SecureFile, 'status' | 'accessState' | 'lastPaymentRequestedAt' | 'lastPaymentRequestOutcome' | 'paymentRequestLapsed'>;
export function isVaultPaymentRefused(outcome?: string): boolean {
  return outcome === 'PAYMENT_REQUEST_REFUSED'
    || outcome === 'VAULT_QUOTE_CHANGED'
    || outcome === 'VAULT_DELIVERY_CONFIRMATION_REQUIRED';
}
/** One payable card per file: a sent card blocks another request unless it was refused, or it was
 *  an old 15-minute card that WhatsApp has already cancelled (server flag `paymentRequestLapsed`).
 *  Cards sent now never expire, like Collect, so they never lapse. */
export function canRequestVaultPayment(file?: PaymentFile | null, localPending = false): boolean {
  return !!file && file.status === 'active' && file.accessState === 'UNPAID'
    && !localPending && (!file.lastPaymentRequestedAt
      || isVaultPaymentRefused(file.lastPaymentRequestOutcome)
      || file.paymentRequestLapsed === true);
}
