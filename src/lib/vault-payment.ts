import type {SecureFile} from '../api/domains/platform';

type PaymentFile = Pick<SecureFile, 'status' | 'accessState' | 'lastPaymentRequestedAt' | 'lastPaymentRequestOutcome'>;

export function isVaultPaymentRefused(outcome?: string): boolean {
  return outcome === 'PAYMENT_REQUEST_REFUSED'
    || outcome === 'VAULT_QUOTE_CHANGED'
    || outcome === 'VAULT_DELIVERY_CONFIRMATION_REQUIRED';
}

export function canRequestVaultPayment(file?: PaymentFile | null, localPending = false): boolean {
  return !!file && file.status === 'active' && file.accessState === 'UNPAID'
    && !localPending && (!file.lastPaymentRequestedAt
      || isVaultPaymentRefused(file.lastPaymentRequestOutcome));
}
