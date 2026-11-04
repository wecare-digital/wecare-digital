import type { ApiFailure, ApiResult } from '../api/core';
import type { Contact } from '../api/domains/contacts';

/**
 * Staff "Create customer" recovery, shared by every workspace screen that creates a contact.
 *
 * `core/contacts` makes the contact, the customer account and the `checkoutCustomerId` link in
 * one operation. If the account step fails AFTER the contact row is saved, the server answers
 * with `contactCreated: true` + `contactId` and the screen must offer "Complete customer setup"
 * for THAT record - never a second create, which would only hit the duplicate-phone refusal.
 * Mirrors the /ws CustomerEditor behaviour so every screen recovers the same way.
 */
export const SETUP_INCOMPLETE_MESSAGE =
  'Customer saved, but account setup is incomplete. Use Complete customer setup for this record; do not create another customer.';

export type CustomerSetupOutcome =
  | { ok: true; contact: Contact }
  | { ok: false; pendingContactId: string; message: string };

type Provision = ( contactId: string ) => Promise<ApiResult<Contact | null>>;

/** The retained contact id when a create saved the contact but not the account, else ''. */
export function partialCreateContactId ( failure: ApiFailure | undefined | null ): string {
  const details = failure?.details;
  if ( !details || details.contactCreated !== true ) return '';
  return typeof details.contactId === 'string' ? details.contactId.trim() : '';
}

/** True when the record has a phone but no customer-account link yet. */
export function needsCustomerSetup ( contact: Pick<Contact, 'phone' | 'checkoutCustomerId'> | null | undefined ): boolean {
  return !!contact && !!String( contact.phone || '' ).trim() && !String( contact.checkoutCustomerId || '' ).trim();
}

/** Run (or re-run) the server's account setup for one already-saved contact. Never creates one. */
export async function completeCustomerSetup ( contactId: string, provision: Provision ): Promise<CustomerSetupOutcome> {
  const id = String( contactId || '' ).trim();
  if ( !id ) return { ok: false, pendingContactId: '', message: 'No saved customer record to complete. Search the directory first.' };
  let result: ApiResult<Contact | null>;
  try {
    result = await provision( id );
  } catch {
    return { ok: false, pendingContactId: id, message: 'Account setup could not be confirmed. Retry Complete customer setup for this record.' };
  }
  if ( result.ok && result.data && String( result.data.checkoutCustomerId || '' ).trim() ) {
    return { ok: true, contact: result.data };
  }
  if ( !result.ok && result.failure.details?.errorCode === 'CUSTOMER_IDENTITY_CONFLICT' ) {
    return { ok: false, pendingContactId: id, message: 'This number is linked to a different customer account. Ask an administrator to review it before payments.' };
  }
  const message = !result.ok && typeof result.failure.details?.error === 'string'
    ? String( result.failure.details.error )
    : SETUP_INCOMPLETE_MESSAGE;
  return { ok: false, pendingContactId: id, message };
}

/**
 * After a successful create/update, make sure the saved record is payment-ready. A record that
 * already carries the link is returned unchanged with no extra request.
 */
export async function ensureCustomerSetup ( contact: Contact, provision: Provision ): Promise<CustomerSetupOutcome> {
  if ( !needsCustomerSetup( contact ) ) return { ok: true, contact };
  return completeCustomerSetup( contact.contactId || contact.id, provision );
}
