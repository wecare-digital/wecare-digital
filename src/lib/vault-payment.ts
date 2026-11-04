import type {SecureFile, VaultMessageDeliveryEvidence} from '../api/domains/platform';
type PaymentFile = Pick<SecureFile, 'status' | 'accessState'>;
type AuditFile = Pick<SecureFile, 'lastPaymentRequestedAt' | 'lastPaymentRequestOutcome'>;

export function isVaultPaymentRefused(outcome?: string): boolean {
  return outcome === 'PAYMENT_REQUEST_REFUSED'
    || outcome === 'VAULT_QUOTE_CHANGED'
    || outcome === 'VAULT_DELIVERY_CONFIRMATION_REQUIRED';
}

/** Why a new Vault payment request is not available, or '' when it is.
 *  Owner decision (2026-11-04): staff Vault payments have no send limit. Only a paid, open,
 *  expired, unverified or inactive file is blocked, plus a request THIS browser started that has
 *  no server answer yet (`PENDING_LOCAL`). */
export type VaultPaymentBlock =
  | '' | 'NO_FILE' | 'INACTIVE' | 'ACCESS_OPEN' | 'ACCESS_READY' | 'ACCESS_EXPIRED'
  | 'PAID_UNVERIFIED' | 'PENDING_LOCAL';

export function vaultPaymentBlock(file?: PaymentFile | null, localPending = false): VaultPaymentBlock {
  if (!file) return 'NO_FILE';
  if (file.status !== 'active') return 'INACTIVE';
  switch (file.accessState) {
    case 'OPEN': return 'ACCESS_OPEN';
    case 'READY': return 'ACCESS_READY';
    case 'EXPIRED': return 'ACCESS_EXPIRED';
    case 'PAID_UNVERIFIED': return 'PAID_UNVERIFIED';
    case 'UNPAID': return localPending ? 'PENDING_LOCAL' : '';
    default: return 'NO_FILE';
  }
}

export function canRequestVaultPayment(file?: PaymentFile | null, localPending = false): boolean {
  return vaultPaymentBlock(file, localPending) === '';
}

/** One plain sentence per blocking reason. Never groups different states into one warning. */
export function vaultPaymentBlockMessage(block: VaultPaymentBlock, pendingSince?: number | null): string {
  switch (block) {
    case '': return '';
    case 'NO_FILE': return 'Select a saved file to review its payment.';
    case 'INACTIVE': return 'This file is no longer active (revoked or not yet verified). No payment can be requested for it.';
    case 'ACCESS_OPEN': return 'Already paid: the customer\u2019s 24-hour access window is open. Do not request payment again.';
    case 'ACCESS_READY': return 'Already paid: access is ready and opens on the customer\u2019s first download. Do not request payment again.';
    case 'ACCESS_EXPIRED': return 'Already paid: the access window has expired. This file is not sold again.';
    case 'PAID_UNVERIFIED': return 'A payment is recorded for this file but access is not confirmed yet. Reconcile in Log; do not request payment again.';
    case 'PENDING_LOCAL': return 'This browser started a payment request'
      + (pendingSince ? ` at ${new Date(pendingSince).toLocaleTimeString('en-IN')}` : '')
      + ' and no server answer is recorded yet. Check Log for the payment attempt and WhatsApp delivery before sending again.';
  }
}

/** The browser's in-flight marker for one file. Stored as `{"at": <epoch ms>}`; the legacy
 *  value `requested` (no time) reads as 0, meaning "started at an unknown time". */
export function parseLocalPending(raw: string | null): number | null {
  if (raw == null) return null;
  try {
    const value = JSON.parse(raw);
    if (value && typeof value.at === 'number' && Number.isFinite(value.at)) return value.at;
  } catch { /* legacy plain string */ }
  return 0;
}

export function localPendingValue(now: number = Date.now()): string {
  return JSON.stringify({at: now});
}

/** Whether the server recorded an answer to a request this browser started at `sinceMs`.
 *  The server stamps `lastPaymentRequestedAt` (UTC, whole seconds) when it answers, so an
 *  answer at or after the browser's start (60 s clock slack) is that request's answer. A legacy
 *  marker (0) accepts any recorded answer. */
export function serverAnsweredSince(file: AuditFile | null | undefined, sinceMs: number): boolean {
  if (!file?.lastPaymentRequestedAt || !file.lastPaymentRequestOutcome) return false;
  const answered = Date.parse(file.lastPaymentRequestedAt);
  if (!Number.isFinite(answered)) return false;
  return sinceMs <= 0 || answered >= sinceMs - 60_000;
}

const DELIVERY_WORDS: Record<VaultMessageDeliveryEvidence['status'], string> = {
  NOT_TRACKED: 'not tracked', UNAVAILABLE: 'unavailable', ACCEPTED: 'accepted by WhatsApp',
  SENT: 'sent', DELIVERED: 'delivered', READ: 'read by the customer', FAILED: 'failed',
  UNKNOWN: 'unknown', PENDING: 'pending',
};

/** Staff summary of the last confirmed server answer and its WhatsApp evidence, if any. */
export function lastRequestSummary(file: AuditFile | null | undefined,
                                   nativePay?: VaultMessageDeliveryEvidence | null): string {
  if (!file?.lastPaymentRequestedAt || !file.lastPaymentRequestOutcome) return '';
  const at = new Date(file.lastPaymentRequestedAt).toLocaleString('en-IN');
  const delivery = nativePay ? ` WhatsApp: ${DELIVERY_WORDS[nativePay.status] || 'unknown'}.` : '';
  return `Last payment request: ${file.lastPaymentRequestOutcome} at ${at}.${delivery}`;
}
