import { API_BASE } from '../../config/constants';
import '../../lib/amplifyConfig';
import { apiCall, apiCallResult, normalizeCheckoutAddress, normalizeEpochSeconds, normalizeTimestamp } from '../core';
import type { ApiResult, CheckoutDeliveryAddress } from '../core';

// ============================================================================
// CONTACTS API
// ============================================================================


export interface ConsentEvidence {
  source: string;
  purpose: string;
  reference: string;
  occurredAt?: string;
}

export interface ConsentEvent extends ConsentEvidence {
  eventId: string;
  field: string;
  channel: 'whatsapp' | 'sms' | 'email' | string;
  scope: 'consent' | 'allowlist' | string;
  previousState: boolean;
  state: boolean;
  status: 'OPTED_IN' | 'OPTED_OUT' | 'ALLOWED' | 'NOT_ALLOWED' | string;
  recordedAt: number;
}

export type ContactMutation = Partial<Contact> & {
  /** Required by the server only when consent/allowlist state actually changes. */
  consentEvidence?: ConsentEvidence;
};

export interface Contact {
  id: string;
  contactId: string;
  /** Server-minted, immutable, workspace-scoped Subscriber ID. */
  subscriberId?: string;
  workspaceId?: string;
  customerUuid?: string;
  customerDisplayId?: string;
  locked?: boolean;
  lockedReason?: string;
  lockedAt?: number;
  name: string;
  firstName?: string;
  lastName?: string;
  phone: string;
  email?: string;
  phoneVerifiedAt?: string;
  emailVerifiedAt?: string;
  blogSubscribedAt?: string;
  // WhatsApp BSUID (Business-Scoped User ID) — unique per WABA portfolio
  bsuid?: string;
  // Parent BSUID (linked account)
  parentBsuid?: string;
  // WhatsApp username (e.g. "@pablomorales")
  username?: string;
  // Contact book name — auto-populated by Meta's contact book feature
  contactBookName?: string;
  shippingAddress?: string;
  billingAddress?: string;
  /**
   * The address the customer typed at checkout, written by `auth/customer-profile` through
   * `lambda_utils.ecommerce.contact_address` and READ-ONLY here. Structured, not a string, and
   * deliberately NOT merged into `shippingAddress`: the two answer different questions - this
   * one is what the customer gave for their own order, `shippingAddress` is what the business
   * curated - and collapsing them would let a checkout save overwrite a hand-typed CRM address.
   */
  checkoutDeliveryAddress?: CheckoutDeliveryAddress;
  /** Epoch seconds the checkout address was last written. */
  checkoutAddressUpdatedAt?: number;
  /**
   * FEAT-003 WRITE-side structured address. When present on a create/update, the server runs it
   * through the one shared validator (`contact_address.normalize_for_storage`, international) and
   * writes `checkoutDeliveryAddress`. This is the single validated write path; the flat
   * `addressLine1`/`city`/… fields below remain for existing readers. Not the same as
   * `checkoutDeliveryAddress`, which is the stored/read result.
   */
  address?: {
    addressLine1: string;
    addressLine2?: string;
    /**
     * FEAT-003: the eighth `contact_address._RULES` field, and the one the staff forms label
     * "Landmark / Locality". It was missing from this interface while being accepted by the
     * server, so a landmark typed in the CRM reached `landmark` (a flat CRM field nothing in the
     * payment path reads) and never reached `checkoutDeliveryAddress.locality`.
     */
    locality?: string;
    city: string;
    state: string;
    postalCode: string;
    country?: string;
    countryCode?: string;
  };
  // Structured address JSON (Meta shipping_info format) — set by subscribe flow
  shippingAddressJson?: string;
  billingAddressJson?: string;
  // GSTIN for B2B invoicing
  gstin?: string;
  // Structured address fields for WhatsApp Payments shipping_info
  addressLine1?: string;
  addressLine2?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  landmark?: string;
  countryCode?: string;
  houseNumber?: string;
  buildingName?: string;
  towerNumber?: string;
  floorNumber?: string;
  // Country
  country?: string;
  pincode?: string;
  // Customer-entered WECARE.DIGITAL profile name. Separate from Meta's provider username.
  profileUsername?: string;
  // Business/profile fields
  companyName?: string;
  designation?: string;
  preferredLanguage?: string;
  isPep?: boolean;
  pepDetails?: string;
  paidBy?: string; // self, company
  // Tracking fields (read-only, set by backend)
  lastFlowInteractionAt?: string;
  satisfactionScore?: number;
  welcomeSent?: boolean;
  welcomeSentAt?: string;
  /**
   * Current WHATSAPP + MARKETING consent derived by the server from the append-only ledger.
   * This, not the legacy booleans below, is the authority for marketing audience selection.
   */
  whatsappMarketingConsent?: ConsentState;
  // Legacy opt-in fields retained for compatibility with non-ledger callers.
  optInWhatsApp: boolean;
  optInSms: boolean;
  optInEmail: boolean;
  // Allowlist fields (Requirement 3.2)
  allowlistWhatsApp: boolean;
  allowlistSms: boolean;
  allowlistEmail: boolean;
  lastInboundMessageAt?: string;
  tags?: string[];
  createdAt: string;
  updatedAt: string;
  deletedAt?: string;
  /** Non-destructive staff archive. Identity/history remain linked and duplicate checks still see it. */
  archivedAt?: number;
  archivedBy?: string;
  archivedReason?: string;
  consentHistory?: ConsentEvent[];
}

export async function listContactsResult (): Promise<ApiResult<Contact[]>> {
  const result = await apiCallResult<any>( `${API_BASE}/contacts` );
  if (!result.ok) return result;
  const contacts = Array.isArray(result.data) ? result.data : (result.data?.contacts || []);
  return {ok: true, data: contacts.map(normalizeContact)};
}
export async function listContacts (): Promise<Contact[]> {
  const result = await listContactsResult();
  return result.ok ? result.data : [];
}

export async function searchContactsResult ( query: string, limit = 20 ): Promise<ApiResult<Contact[]>> {
  const q = query.trim();
  if ( !q ) return { ok: true, data: [] };
  const result = await apiCallResult<any>(
    `${API_BASE}/contacts/search?q=${encodeURIComponent( q )}&limit=${Math.max( 1, Math.min( limit, 100 ) )}`
  );
  if ( !result.ok ) return result;
  const contacts = Array.isArray( result.data ) ? result.data : ( result.data?.contacts || [] );
  return { ok: true, data: contacts.map( normalizeContact ) };
}

export async function searchContacts ( query: string, limit = 20 ): Promise<Contact[]> {
  const result = await searchContactsResult( query, limit );
  return result.ok ? result.data : [];
}

export async function getContact ( contactId: string ): Promise<Contact | null> {
  const data = await apiCall<any>( `${API_BASE}/contacts/${contactId}` );
  if ( data )
  {
    return normalizeContact( data.contact || data );
  }
  return null;
}

export async function createContactResult ( contact: ContactMutation ): Promise<ApiResult<Contact | null>> {
  const result = await apiCallResult<any>( `${API_BASE}/contacts`, {
    method: 'POST',
    body: JSON.stringify( contact ),
  } );
  if ( !result.ok ) return result;
  const data = result.data;
  return { ok: true, data: data ? normalizeContact( data.contact || data ) : null };
}

export async function createContact ( contact: ContactMutation ): Promise<Contact | null> {
  const result = await createContactResult( contact );
  return result.ok ? result.data : null;
}

/**
 * A contact update that says WHY it failed.
 *
 * `contacts/handler.py` refuses some inputs on purpose - a phone carrying no dial code is a
 * 400 `PHONE_COUNTRY_CODE_REQUIRED` rather than a guessed `+91` - so the reason for a refusal
 * is information the operator needs. `updateContact` below collapses every one of those to
 * `null`, which a caller cannot tell apart from a 503, and the CRM's inline cell editor
 * rendered that `null` as a silent no-op. Prefer this in new code; `updateContact` stays for
 * the callers that only branch on success.
 */
export async function updateContactResult ( contactId: string, updates: ContactMutation ): Promise<ApiResult<Contact | null>> {
  const result = await apiCallResult<any>( `${API_BASE}/contacts/${contactId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  if ( !result.ok )
  {
    return result;
  }
  // `data` is still guarded: a 2xx with an empty body normalises to null rather than throwing
  // inside `normalizeContact`, which is exactly what `updateContact` returned before.
  const data = result.data;
  return { ok: true, data: data ? normalizeContact( data.contact || data ) : null };
}

export async function updateContact ( contactId: string, updates: ContactMutation ): Promise<Contact | null> {
  const result = await updateContactResult( contactId, updates );
  return result.ok ? result.data : null;
}

export async function unlockContact ( contactId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/contacts/${contactId}/unlock`, { method: 'POST', body: '{}' } );
  return data !== null && data.locked === false;
}

export async function deleteContact ( contactId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${API_BASE}/contacts/${contactId}`, {
    method: 'DELETE',
  } );
  // This remains the legacy tombstone/delete contract. Normal workspace "Archive" uses
  // archiveContact below so customers with financial history keep their identity intact.
  return data !== null && !data.error;
}

/**
 * Operator-requested soft delete. This never asks the disabled hard-delete endpoint to purge
 * messages or identity claims. Preserve server 403/409 reasons (legal lock, payment linkage,
 * unknown linkage) so the staff UI never reports a false deletion.
 */
export async function softDeleteContactResult (
  contactId: string,
): Promise<ApiResult<{ success: boolean; contactId: string; deleteType: 'soft' }>> {
  return apiCallResult<{ success: boolean; contactId: string; deleteType: 'soft' }>(
    `${API_BASE}/contacts/${encodeURIComponent(contactId)}`, { method: 'DELETE' },
  );
}

export async function archiveContact (
  contactId: string,
  reason: string,
): Promise<ApiResult<Contact | null>> {
  const result = await apiCallResult<any>( `${API_BASE}/contacts`, {
    method: 'POST',
    body: JSON.stringify( { _action: 'archive', contactId, reason } ),
  } );
  if ( !result.ok ) return result;
  return { ok: true, data: result.data ? normalizeContact( result.data.contact || result.data ) : null };
}

export async function restoreContact ( contactId: string ): Promise<ApiResult<Contact | null>> {
  const result = await apiCallResult<any>( `${API_BASE}/contacts`, {
    method: 'POST',
    body: JSON.stringify( { _action: 'restore', contactId } ),
  } );
  if ( !result.ok ) return result;
  return { ok: true, data: result.data ? normalizeContact( result.data.contact || result.data ) : null };
}

export interface CustomerMergeResult {
  merged: boolean;
  idempotent?: boolean;
  sourceContactId: string;
  targetContactId: string;
  customerUuid?: string;
  preservedFinancialHistory?: boolean;
}

export async function mergeContacts (
  sourceContactId: string,
  targetContactId: string,
  reason: string,
): Promise<ApiResult<CustomerMergeResult>> {
  return apiCallResult<CustomerMergeResult>( `${API_BASE}/contacts`, {
    method: 'POST',
    body: JSON.stringify( {
      _action: 'merge',
      sourceContactId,
      targetContactId,
      reason,
    } ),
  } );
}

// ============================================================================
// CONSENT EVIDENCE API
// ----------------------------------------------------------------------------
// Consent is an append-only ledger of EVIDENCE records, not the legacy opt-in booleans. A read
// derives the current per-channel state from the ledger; an append layers a record on top and
// never rewrites history; an import ingests EXISTING evidence only and can never manufacture an
// opt-in for an address book. These mirror `lambda_utils.identity.consent` on the backend.
// ============================================================================

export type ConsentChannel = 'WHATSAPP' | 'SMS' | 'EMAIL' | 'RCS' | 'VOICE' | 'PUSH';
export type ConsentState = 'OPTED_IN' | 'OPTED_OUT' | 'PENDING';
export type ConsentPurpose = 'MARKETING' | 'TRANSACTIONAL' | 'SERVICE';

export interface ConsentRecord {
  channel: ConsentChannel;
  state: ConsentState;
  source: string;
  at: number;
  purpose: ConsentPurpose;
  reference?: string;
  expiry?: number;
}

export interface ConsentChannelSummary {
  state: ConsentState;
  latestRecordState: ConsentState;
  source: string;
  at: number;
  purpose: ConsentPurpose;
  reference: string;
  expiry?: number | null;
  history: number;
  sendable: boolean;
}

export interface ConsentView {
  contactId: string;
  ledger: ConsentRecord[];
  summary: Partial<Record<ConsentChannel, ConsentChannelSummary>>;
}

/** The append-only consent ledger plus the derived per-channel summary for one contact. */
export async function getConsent ( contactId: string ): Promise<ApiResult<ConsentView>> {
  return apiCallResult<ConsentView>(
    `${API_BASE}/contacts?consent=${encodeURIComponent( contactId )}` );
}

/**
 * Append ONE consent evidence record. Never a casual boolean flip: the record must name a
 * channel, a state (OPTED_IN / OPTED_OUT / PENDING), a source and a purpose. The append layers
 * onto the ledger so prior evidence survives.
 */
export async function appendConsent (
  contactId: string,
  record: {
    channel: ConsentChannel;
    state: ConsentState;
    source: string;
    purpose?: ConsentPurpose;
    reference?: string;
    expiry?: number;
  },
): Promise<ApiResult<ConsentView>> {
  return apiCallResult<ConsentView>( `${API_BASE}/contacts`, {
    method: 'POST',
    body: JSON.stringify( { _action: 'consent_append', contactId, ...record } ),
  } );
}

export interface ConsentImportResult extends ConsentView {
  imported: number;
  refused: { index: number; reason: string }[];
}

/**
 * Import EXISTING consent evidence. A row claiming OPTED_IN must name the originating source and
 * an evidence reference or it is refused; an address book can never manufacture an opt-in.
 */
export async function importConsent (
  contactId: string,
  records: Record<string, unknown>[],
): Promise<ApiResult<ConsentImportResult>> {
  return apiCallResult<ConsentImportResult>( `${API_BASE}/contacts`, {
    method: 'POST',
    body: JSON.stringify( { _action: 'consent_import', contactId, records } ),
  } );
}

function normalizeContact ( item: any ): Contact {
  return {
    id: item.id || item.contactId || '',
    contactId: item.contactId || item.id || '',
    subscriberId: item.subscriberId || '',
    workspaceId: item.workspaceId || '',
    customerUuid: item.customerUuid || '',
    customerDisplayId: item.customerDisplayId || '',
    locked: item.locked === true,
    lockedReason: item.lockedReason || '',
    lockedAt: normalizeEpochSeconds( item.lockedAt ),
    name: item.name || '',
    firstName: item.firstName || '',
    lastName: item.lastName || '',
    phone: item.phone || '',
    email: item.email || '',
    phoneVerifiedAt: normalizeTimestamp( item.phoneVerifiedAt ),
    emailVerifiedAt: normalizeTimestamp( item.emailVerifiedAt ),
    blogSubscribedAt: normalizeTimestamp( item.blogSubscribedAt ),
    bsuid: item.bsuid || '',
    parentBsuid: item.parentBsuid || '',
    username: item.username || '',
    profileUsername: item.profileUsername || '',
    contactBookName: item.contactBookName || '',
    shippingAddress: item.shippingAddress || '',
    billingAddress: item.billingAddress || '',
    /*
     * READ-ONLY, written by `auth/customer-profile`.
     *
     * This mapper is a CLOSED whitelist and the only way a contact reaches the UI
     * (`listContacts`, `getContact`, `createContact`, `updateContact` all funnel through it),
     * so an attribute the backend already returns stays `undefined` in the browser until it is
     * named HERE. That is not hypothetical: the first attempt at this fix added both fields to
     * the `Contact` interface only, and shipped a CRM column that rendered the em-dash for every
     * contact while `tsc` and the suite stayed green.
     *
     * Carried through WHOLE rather than rebuilt field by field. The stored map also holds
     * `fullAddress` (derived by `identity.address.normalize_address`), and a second closed
     * whitelist at this layer would be a second place to forget a field — the exact failure
     * mode this comment exists to record. Only the shape is checked; `formatCheckoutAddress`
     * coerces each part, because this is server data and a legacy row may hold a number or a
     * null where a string is expected.
     */
    checkoutDeliveryAddress: normalizeCheckoutAddress( item.checkoutDeliveryAddress ),
    // Epoch SECONDS, deliberately NOT through `normalizeTimestamp`: `Contact` types this as a
    // number, and the page's `timeAgo` already handles both epoch scales.
    checkoutAddressUpdatedAt: normalizeEpochSeconds( item.checkoutAddressUpdatedAt ),
    shippingAddressJson: item.shippingAddressJson || '',
    billingAddressJson: item.billingAddressJson || '',
    gstin: item.gstin || '',
    // Structured address fields
    addressLine1: item.addressLine1 || '',
    addressLine2: item.addressLine2 || '',
    city: item.city || '',
    state: item.state || '',
    postalCode: item.postalCode || '',
    landmark: item.landmark || '',
    houseNumber: item.houseNumber || '',
    buildingName: item.buildingName || '',
    towerNumber: item.towerNumber || '',
    floorNumber: item.floorNumber || '',
    country: item.country || '',
    pincode: item.pincode || item.postalCode || '',
    companyName: item.companyName || item.contactBookName || '',
    designation: item.designation || '',
    preferredLanguage: item.preferredLanguage || '',
    isPep: item.isPep || false,
    pepDetails: item.pepDetails || '',
    paidBy: item.paidBy || '',
    lastFlowInteractionAt: normalizeTimestamp( item.lastFlowInteractionAt ),
    satisfactionScore: item.satisfactionScore || undefined,
    welcomeSent: item.welcomeSent || false,
    welcomeSentAt: normalizeTimestamp( item.welcomeSentAt ),
    // Canonical WhatsApp marketing consent, derived server-side from consentLedger.
    whatsappMarketingConsent: (
      item.whatsappMarketingConsent === 'OPTED_IN'
      || item.whatsappMarketingConsent === 'OPTED_OUT'
      || item.whatsappMarketingConsent === 'PENDING'
    ) ? item.whatsappMarketingConsent as ConsentState : 'PENDING',
    // Legacy opt-in fields
    optInWhatsApp: item.optInWhatsApp || false,
    optInSms: item.optInSms || false,
    optInEmail: item.optInEmail || false,
    // Allowlist fields (Requirement 3.2)
    allowlistWhatsApp: item.allowlistWhatsApp || false,
    allowlistSms: item.allowlistSms || false,
    allowlistEmail: item.allowlistEmail || false,
    lastInboundMessageAt: normalizeTimestamp( item.lastInboundMessageAt ),
    tags: Array.isArray( item.tags ) ? item.tags : [],
    createdAt: normalizeTimestamp( item.createdAt ) || new Date().toISOString(),
    updatedAt: normalizeTimestamp( item.updatedAt ) || new Date().toISOString(),
    deletedAt: item.deletedAt,
    archivedAt: normalizeEpochSeconds( item.archivedAt ),
    archivedBy: item.archivedBy || '',
    archivedReason: item.archivedReason || '',
    consentHistory: Array.isArray( item.consentHistory ) ? item.consentHistory : [],
  };
}

