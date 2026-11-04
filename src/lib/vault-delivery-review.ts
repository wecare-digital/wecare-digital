import {addressComplete, addressFieldsFromContact, formatAddress} from './address-format';
import type {Contact} from '../api/domains/contacts';
import type {VaultDeliveryAddressConfirmation} from '../api/domains/platform';

/**
 * THE one Vault delivery-address review, shared by every staff screen that requests a Vault
 * payment (/workspace/vault, /ws Vault panel, Vault workbench).
 *
 * Vault is physical goods: the backend refuses a payment request without an explicit operator
 * confirmation bound to the contact's CURRENT saved address revision
 * (`VAULT_DELIVERY_CONFIRMATION_REQUIRED`). This builds that confirmation from the saved contact,
 * or refuses locally with a plain reason, and supplies the text the operator must confirm.
 */
export type VaultDeliveryReview =
  | {ok: true; addressText: string; confirmation: VaultDeliveryAddressConfirmation}
  | {ok: false; message: string};

type ReviewContact = Pick<Contact, 'name' | 'phone'>;

export function vaultDeliveryReview(contact: ReviewContact | null | undefined): VaultDeliveryReview {
  if (!contact) {
    return {ok: false, message: 'Select the file owner\u2019s customer record to review the delivery address before payment.'};
  }
  const fields = addressFieldsFromContact(contact as never);
  const addressText = formatAddress(fields);
  const revision = Number((contact as {checkoutAddressUpdatedAt?: unknown}).checkoutAddressUpdatedAt);
  if (!addressComplete(fields) || !addressText || !Number.isSafeInteger(revision) || revision <= 0) {
    return {ok: false, message: 'A current saved physical delivery address is mandatory. Edit and save the customer address before requesting payment.'};
  }
  return {ok: true, addressText, confirmation: {confirmed: true, checkoutAddressUpdatedAt: revision}};
}

/** The confirmation dialog copy every screen shows before sending. */
export function vaultDeliveryReviewPrompt(input: {
  ownerName: string; ownerPhone: string; fileName: string; totalText: string; addressText: string;
}): {title: string; message: string; confirmText: string} {
  return {
    title: 'Confirm delivery address and send Review & Pay?',
    message: `Verify with the customer that this is the CURRENT and CORRECT physical-goods delivery address: ${input.addressText}. `
      + `Owner: ${input.ownerName} \u00b7 ${input.ownerPhone}. File: ${input.fileName}. Total ${input.totalText}, including \u20b925 Express. `
      + 'Confirm only if this saved address is correct; the server checks it again before payment.',
    confirmText: 'Address verified \u00b7 Send payment request',
  };
}
