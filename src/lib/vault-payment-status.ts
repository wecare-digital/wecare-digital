import type {SecureFile} from '../api/domains/platform';

type PaymentFile = Pick<SecureFile, 'fileId' | 'accessState' | 'vaultPaymentStatus' | 'downloadCount'>;

export function vaultPaymentStatusMessage(file: PaymentFile | undefined): string {
  if (file?.accessState === 'OPEN') {
    return `Payment verified. Access is open. Downloads: ${file.downloadCount}. View Log for the saved invoice and access details.`;
  }
  if (file?.accessState === 'READY') {
    return `Payment verified. Paid access is ready; the download window starts when the customer opens the file. Downloads: ${file.downloadCount}.`;
  }
  if (file?.accessState === 'EXPIRED') {
    return `Payment verified. The access window has expired. Downloads: ${file.downloadCount}. Do not request another payment for this file.`;
  }
  if (file?.accessState === 'PAID_UNVERIFIED' || file?.vaultPaymentStatus === 'PAID') {
    return 'Payment is recorded; access needs reconciliation. Inspect Log before another action.';
  }
  return 'Payment request sent. Waiting for verified payment on WhatsApp.';
}
