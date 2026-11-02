import { API_BASE } from '../../config/constants';
import '../../lib/amplifyConfig';
import { apiCall, apiCallResult, authFetch, WA_BIZ_BASE } from '../core';
import type { ApiResult } from '../core';

// ============================================================================
// INVOICE API (Unified Invoice System)
// Canonical route: /api/invoices -> wecare-commerce:live.
// The legacy standalone wecare-invoice-engine remains only as a rollback target.
// ============================================================================

const INVOICE_BASE = `${API_BASE}/invoices`;

export interface InvoiceItem {
  invoiceId: string;
  itemIndex: number;
  name: string;
  amount: number;
  quantity: number;
  gstRate?: number;
  taxAmount?: number;
  hsnSac?: string;
  productId?: string;
  isCharge?: boolean;
}

export interface InvoiceAsset {
  invoiceId: string;
  // `image` / `pdf` for the document of record, and `image#v2` / `pdf#v2` ... for a rendition
  // generated after the invoice was issued. The engine writes a NEW row rather than overwriting
  // the first one, so the union of two literals is no longer the truth about this field.
  assetType: string;
  s3Key: string;
  url: string;
  contentType: string;
  version: number;
  generatedAt: number;
}

export interface InvoiceDeliveryLog {
  timestamp: number;
  channel: string;
  toNumber: string;
  waMessageId: string;
  status: string;
  error: string;
  imageUrl: string;
}

/** Invoice-PK-bound, backend-projected evidence. Never a browser-side join. */
export interface InvoiceEvidenceEvent {
  role: string;
  label: string;
  at: number;
  utc: string;
  source: string;
  actor: string;
  verificationClass: string;
  /** SHA-256 fragment, never an unmasked provider ID, phone or reference. */
  recordFragment: string;
}
export interface InvoiceEvidenceGap {
  label: string;
  seconds: number | null;
  status: 'measured' | 'unverified';
  basis: string;
}
export interface InvoiceEvidenceTimeline {
  scope: 'authoritative_invoice_id';
  invoiceFragment: string;
  events: InvoiceEvidenceEvent[];
  gaps: InvoiceEvidenceGap[];
  note: string;
}

export interface Invoice {
  fixedPresetId?: string;
  itemProcessId?: string;
  itemProcessIds?: string[];
  itemProcessStates?: Record<string,string>;
  postPaymentProcessState?: string;
  invoiceId: string;
  invoiceNumber: string;
  paymentId: string;
  orderId: string;
  referenceId: string;
  entryPoint: string;
  /** Exact service-kind attribution from verified payment lineage, when requested. */
  serviceKind?: string;
  status: string;
  paymentStatus: string;
  /** Local projection of the WhatsApp payment-order lifecycle. Distinct from paymentStatus,
   *  which records what the money did. The payment rail normally ends at completed. */
  orderStatus?: string;
  /** Last order_status value Meta accepted for this invoice/reference. This is the transition
   *  authority and must advance only after Meta accepts the corresponding template message. */
  waOrderStatus?: string;
  contactId: string;
  customerName: string;
  customerPhone: string;
  paidByPhone: string;
  customerEmail: string;
  /**
   * The public customer id — a uuid4 the server mints and `invoice-engine` re-validates with
   * `customer_uuid.is_customer_uuid` before storing, so a junk value is dropped rather than
   * recorded. Optional because an invoice raised before the attribute existed carries none, and
   * absent must stay distinguishable from empty here: the invoice renderers print no Customer ID
   * row at all in that case rather than a placeholder.
   *
   * Safe to show in full. It is opaque, carries no timestamp (uuid4, deliberately not uuid7) and
   * is not a credential — which is the point: a staff member can quote it instead of the phone.
   */
  customerUuid?: string;
  shippingAddress: string;
  billingAddress: string;
  goodsType?: 'digital-goods' | 'physical-goods';
  subtotal: number;
  discount: number;
  shipping: number;
  gstRate: number;
  tax: number;
  /** Historical combined convenience amount (net fee + GST), retained for compatibility. */
  convenienceFee: number;
  /** Canonical net convenience fee for new invoices. */
  convenienceFeeNet?: number;
  /** GST charged on the convenience fee. */
  convenienceFeeGst?: number;
  /** Canonical combined convenience amount. */
  convenienceFeeTotal?: number;
  /** Supply GST + convenience-fee GST. */
  totalGst?: number;
  /** Internal filing/reconciliation facts; not a customer-receipt presentation contract. */
  gstAccounting?: {
    supplyTax: number;
    convenienceFeeGst: number;
    totalGst: number;
    sellerGstin: string;
    state?: string;
    gstStateCode?: string;
    isoSubdivision?: string;
    delightTaxTreatment: string;
  };
  total: number;
  currency: string;
  gstin: string;
  buyerGstin?: string;
  state?: string;
  gstWorkpaper?: Record<string, unknown>;
  purpose: string;
  notes: string;
  createdAt: number;
  updatedAt: number;
  paidAt: number;
  /** Provider evidence written only after a verified refund webhook is reconciled. */
  refundId?: string;
  refundAmount?: number;
  refundAmountPaise?: number;
  refundAt?: number;
  /**
   * The always-on Delight discount recorded on the invoice. `couponCode` is the fixed `DELIGHT`
   * code and nothing a browser supplied; there is no coupon system and no gift-card system any
   * more.
   *
   * Both fields are OPTIONAL, and that is a contract rather than caution: an invoice raised
   * before Delight existed (or one it did not apply to) carries neither, so `undefined` ("no
   * Delight applied") must stay distinguishable from `0` ("Delight applied and was worth
   * nothing"). Rendering `₹0.00` for the first case would be a lie about the document.
   */
  couponCode?: string;
  /**
   * Delight's share of `discount`, in rupees. On a current invoice `discount == couponDiscount`
   * (manual entry is retired); a legacy row may carry a manual remainder of `discount -
   * couponDiscount`. Meta validates `total == subtotal + tax + shipping - discount`.
   */
  couponDiscount?: number;
  remarks?: string | InvoiceRemark[];
  items?: InvoiceItem[];
  assets?: InvoiceAsset[];
}

export interface CreateInvoiceEngineRequest {
  fixedPresetId?: string;
  customerPhone: string;
  paidByPhone?: string;
  customerEmail: string;
  shippingAddress: string;
  billingAddress: string;
  customerName?: string;
  contactId?: string;
  goodsType?: 'digital-goods' | 'physical-goods';
  items: { name: string; amount: number; quantity: number; productId?: string; gstRate?: number; hsnSac?: string }[];
  discount?: number;
  shipping?: number;
  gstRate?: number;       // Fallback global GST rate (used if items don't have per-item rates)
  convenienceFee?: number;
  purpose?: string;
  orderId?: string;
  referenceId?: string;
  entryPoint?: string;
  paymentId?: string;
  gstin?: string;
  buyerGstin?: string;
  currency?: string;
  /** Structured address fields for WhatsApp Payments shipping_info */
  addressLine1?: string;
  addressLine2?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  landmark?: string;
  /** ISO country code for the delivery address; the engine stores it and defaults to IN. */
  countryCode?: string;
  /*
   * Coupon, gift-card and manual discount entry are retired. Fresh Workspace invoices do not
   * send `discount`; the invoice engine applies automatic Delight. The optional field remains
   * only for verified captured/legacy invoice contracts and non-zero fresh values are refused.
   */
}

/**
 * What the server decided about a create. Every amount is the SERVER's: a form must render these
 * rather than recompute anything locally.
 */
export interface CreateInvoiceEngineResponse {
  invoiceId: string;
  invoiceNumber: string;
  referenceId?: string;
  total: number;
  convenienceFee?: number;
  convenienceFeeNet?: number;
  convenienceFeeGst?: number;
  totalGst?: number;
  /** The fixed `DELIGHT` code, present only when the always-on Delight discount applied. */
  couponCode?: string;
  /** Rupees Delight took off, server-computed. */
  couponDiscount?: number;
}

/** Pre-issue quote from the invoice engine. No invoice row/number is created. */
export interface InvoiceEnginePreview {
  preview: true;
  subtotal: string;
  discount: string;
  shipping: string;
  tax: string;
  convenienceFee: string;
  convenienceFeeNet: string;
  convenienceFeeGst: string;
  totalGst: string;
  total: string;
  couponCode?: string | null;
  couponDiscount: string;
  goodsType: 'digital-goods' | 'physical-goods';
  sellerGstin: string;
  pricingAuthority: 'invoice-engine';
  previewImageBase64?: string;
  previewImageContentType?: 'image/png';
}

export async function previewInvoiceEngine (
  request: CreateInvoiceEngineRequest,
  renderPreview = true,
): Promise<InvoiceEnginePreview | null> {
  return apiCall<InvoiceEnginePreview>( INVOICE_BASE, {
    method: 'POST',
    body: JSON.stringify( {
      ...request,
      referenceId: undefined,
      paymentId: undefined,
      _action: 'preview',
      renderPreview,
    } ),
  } );
}

// Create invoice directly
export async function createInvoiceEngine ( request: CreateInvoiceEngineRequest ): Promise<CreateInvoiceEngineResponse | null> {
  return apiCall<CreateInvoiceEngineResponse>( INVOICE_BASE, {
    method: 'POST',
    body: JSON.stringify( request ),
  } );
}

/**
 * A create that reports WHY it was refused.
 *
 * `createInvoiceEngine` stays exactly as it is, because ~every other caller wants the invoice or
 * nothing. But `apiCall` collapses a non-2xx to `null`, so a form built on it can only say
 * "Create failed" - for a 400 address refusal, a 401 the auth gate raised, a 403 role/MFA
 * refusal and a dropped connection alike - and the staff member has no idea what to fix.
 *
 * So this follows `hardDeleteContact`'s precedent and uses `authFetch` directly: the refusal
 * lives in the body and the body is the one thing this caller needs. It returns a discriminated
 * result rather than throwing, because a refusal is an ordinary answer and not an exception.
 *
 * `errorCode` and `message` are passed through VERBATIM and are never invented here. An
 * unrecognised code must still reach the UI so a new server refusal degrades to an honest
 * unknown-reason message rather than to a wrong one.
 */
export type CreateInvoiceEngineResult =
  | { ok: true; invoice: CreateInvoiceEngineResponse }
  // `message` is the server's own sentence; '' when the body carried none.
  | { ok: false; status: number | null; errorCode: string; retryable: boolean; message: string };

export async function createInvoiceEngineResult (
  request: CreateInvoiceEngineRequest,
): Promise<CreateInvoiceEngineResult> {
  let response: Response;
  try
  {
    response = await authFetch( INVOICE_BASE, {
      method: 'POST',
      body: JSON.stringify( request ),
    } );
  } catch ( error )
  {
    console.error( 'Invoice create request failed:', error );
    return { ok: false, status: null, errorCode: 'REQUEST_FAILED', retryable: true, message: '' };
  }

  let data: any = null;
  try { data = await response.json(); } catch { data = null; }

  if ( response.ok && data && data.invoiceId )
  {
    return { ok: true, invoice: data as CreateInvoiceEngineResponse };
  }

  // The engine refuses with `error` (plus `detail` on the Admin MFA gate); API Gateway's own
  // answers carry `message` instead.
  const text = ( v: unknown ): string => ( typeof v === 'string' ? v.trim() : '' );
  const error = text( data?.error ), detail = text( data?.detail );
  const message = ( error && detail ? `${ error.replace( /\.$/, '' ) }. ${ detail }` : error || detail )
    || text( data?.message );

  return {
    ok: false,
    status: response.status,
    errorCode: typeof data?.errorCode === 'string' && data.errorCode ? data.errorCode : 'CREATE_FAILED',
    retryable: data?.retryable === true,
    message,
  };
}

// Create invoice from Razorpay payment ID
export async function createInvoiceFromPayment ( paymentId: string, extras?: Record<string, any> ): Promise<{ invoiceId: string; invoiceNumber: string; total: number } | null> {
  return apiCall<{ invoiceId: string; invoiceNumber: string; total: number }>( `${INVOICE_BASE}/from-payment`, {
    method: 'POST',
    body: JSON.stringify( { paymentId, ...extras } ),
  } );
}

// List invoices with optional filters
export async function listInvoicesEngine ( params?: { status?: string; contactId?: string; paymentId?: string; serviceKind?: string; limit?: number } ): Promise<{ invoices: Invoice[]; count: number }> {
  const query = new URLSearchParams();
  if ( params?.status ) query.set( 'status', params.status );
  if ( params?.contactId ) query.set( 'contactId', params.contactId );
  if ( params?.paymentId ) query.set( 'paymentId', params.paymentId );
  if ( params?.serviceKind ) query.set( 'serviceKind', params.serviceKind );
  if ( params?.limit ) query.set( 'limit', String( params.limit ) );
  const qs = query.toString();
  const data = await apiCall<any>( `${INVOICE_BASE}${qs ? '?' + qs : ''}` );
  return { invoices: data?.invoices || [], count: data?.count || 0 };
}

// Get single invoice with items and assets
export async function getInvoiceEngine ( invoiceId: string ): Promise<Invoice | null> {
  const data = await apiCall<any>( `${INVOICE_BASE}/${invoiceId}` );
  return data?.invoice || null;
}

// Update invoice (admin)
export async function updateInvoiceEngine ( invoiceId: string, updates: Partial<Invoice> ): Promise<boolean> {
  const data = await apiCall<any>( `${INVOICE_BASE}/${invoiceId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return data?.updated === true;
}

// Generate invoice image (PNG)
export async function generateInvoiceImage ( invoiceId: string ): Promise<{ invoiceId: string; imageUrl: string; s3Key: string } | null> {
  return apiCall<{ invoiceId: string; imageUrl: string; s3Key: string }>( `${INVOICE_BASE}/${invoiceId}/generate-image`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId } ),
  } );
}

// Send invoice image on WhatsApp
export async function sendInvoiceWhatsApp ( invoiceId: string, toWhatsAppNumber: string, phoneNumberId?: string ): Promise<{ invoiceId: string; waMessageId: string; status: string; imageUrl: string } | null> {
  return apiCall<{ invoiceId: string; waMessageId: string; status: string; imageUrl: string }>( `${INVOICE_BASE}/${invoiceId}/send-whatsapp`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId, toWhatsAppNumber, phoneNumberId } ),
  } );
}

/**
 * The invoice-engine native ORDER_DETAILS payment send response.
 *
 * `status` is the primary verdict (`payment_link_sent` is the ONLY success;
 * `payment_link_rejected` is terminal; `send_in_progress` is a deduplicated no-op). The remaining
 * fields are the server's own disambiguators, surfaced so the UI can give state-aware guidance
 * instead of a generic "retry": `sendStatus` is the durable send state (e.g. `REJECTED`, `PENDING`,
 * `SENT`), `downstreamStatusCode` is the HTTP status the engine saw from Meta, `deduplicated` marks
 * a repeat invoke that did nothing, and `retryable` says whether trying again could plausibly help.
 */
export interface SendPaymentLinkResult {
  invoiceId: string;
  referenceId: string;
  status: string;
  toPhone: string;
  total: number;
  sendStatus?: string;
  downstreamStatusCode?: number;
  deduplicated?: boolean;
  retryable?: boolean;
}

// Send the approved WhatsApp native ORDER_DETAILS payment template for a pending invoice.
export async function sendPaymentLink ( invoiceId: string, phoneNumberId?: string ): Promise<SendPaymentLinkResult | null> {
  return apiCall<SendPaymentLinkResult>( `${INVOICE_BASE}/${invoiceId}/send-payment-link`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId, phoneNumberId } ),
  } );
}

// Staff-facing payment sends preserve actionable server refusal messages.
export async function sendPaymentLinkResult ( invoiceId: string, phoneNumberId?: string ): Promise<ApiResult<NonNullable<Awaited<ReturnType<typeof sendPaymentLink>>>>> {
  return apiCallResult<NonNullable<Awaited<ReturnType<typeof sendPaymentLink>>>>( `${INVOICE_BASE}/${invoiceId}/send-payment-link`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId, phoneNumberId } ),
  } );
}

// Cancel/void an invoice
export async function cancelInvoice ( invoiceId: string, reason?: string ): Promise<{ invoiceId: string; status: string } | null> {
  return apiCall<{ invoiceId: string; status: string }>( `${INVOICE_BASE}/${invoiceId}/cancel`, {
    method: 'POST',
    body: JSON.stringify( { invoiceId, reason } ),
  } );
}

/** The staff void action must show the invoice engine's precise money-state refusal. */
export async function cancelInvoiceResult (
  invoiceId: string,
  reason: string,
): Promise<ApiResult<{ invoiceId: string; status: string }>> {
  return apiCallResult<{ invoiceId: string; status: string }>(
    `${INVOICE_BASE}/${encodeURIComponent(invoiceId)}/cancel`, {
      method: 'POST',
      body: JSON.stringify( { invoiceId, reason } ),
    },
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// CHECKOUT BUTTON TEMPLATE — Send via outbound-whatsapp Lambda
// Per Meta docs: Checkout button templates use order_details button with
// sale_amount, shipping_info, importer_address, and payment_settings.
// ═══════════════════════════════════════════════════════════════════════════

export interface CheckoutItem {
  name: string;
  amount: { offset: number; value: number };
  sale_amount?: { offset: number; value: number };
  quantity: number;
  country_of_origin: string;
  importer_name: string;
  importer_address: {
    address_line1: string;
    address_line2?: string;
    city: string;
    zone_code: string;
    postal_code: string;
    country_code: string;
  };
}

export interface CheckoutShippingAddress {
  name: string;
  phone_number: string;
  address: string;
  city: string;
  state: string;
  in_pin_code: string;
  house_number?: string;
  tower_number?: string;
  building_name?: string;
  landmark_area?: string;
}

// `CheckoutOrderDetails`, `SendCheckoutTemplateRequest` and `sendCheckoutTemplate` stood here.
// `sendCheckoutTemplate` had ZERO callers in `src/`, and the two interfaces existed only to type
// its argument — a browser-side `order_details` composer kept alive by nothing. Removed for the
// same reason as `sendWhatsAppPaymentMessage` above: no payment is composed outside `amplify/`.

// Get delivery log for an invoice
export async function getInvoiceDeliveryLog ( invoiceId: string ): Promise<{
  deliveryLogs: InvoiceDeliveryLog[];
  count: number;
  evidenceTimeline: InvoiceEvidenceTimeline | null;
}> {
  const data = await apiCall<any>( `${INVOICE_BASE}/${encodeURIComponent(invoiceId)}/delivery-log`, { cache: 'no-store' } );
  // Old invoice-engine deployments do not return a server-scoped chronology.
  // Do not synthesize one from unrelated browser rows.
  const evidenceTimeline = data?.evidenceTimeline?.scope === 'authoritative_invoice_id'
    && Array.isArray(data?.evidenceTimeline?.events)
    && Array.isArray(data?.evidenceTimeline?.gaps)
    ? data.evidenceTimeline as InvoiceEvidenceTimeline : null;
  return { deliveryLogs: data?.deliveryLogs || [], count: data?.count || 0, evidenceTimeline };
}

// Preview next invoice number (without incrementing)
export async function previewNextInvoiceNumber ( fy?: string ): Promise<{ nextInvoiceNumber: string; fy: string; lastSeq: number } | null> {
  return apiCall<{ nextInvoiceNumber: string; fy: string; lastSeq: number }>( `${INVOICE_BASE}/next-sequence`, {
    method: 'POST',
    body: JSON.stringify( { fy } ),
  } );
}

// Delete invoice (hard delete + optional sequence adjustment)
export async function deleteInvoice ( invoiceId: string, adjustSequence = false ): Promise<{ invoiceId: string; deleted: boolean; invoiceNumber: string } | null> {
  return apiCall<{ invoiceId: string; deleted: boolean; invoiceNumber: string }>( `${INVOICE_BASE}/${invoiceId}`, {
    method: 'DELETE',
    body: JSON.stringify( { adjustSequence } ),
  } );
}

// ============================================================================
// REFUND INITIATION (server-authoritative, webhook-confirmed)
// ============================================================================

/**
 * The outcome of a refund-initiation POST, as the invoice-engine reports it.
 *
 * This deliberately mirrors the server's truthful states rather than flattening them. A
 * refund is money leaving, so the UI must never claim "refunded" before provider/webhook
 * evidence. The states are:
 *
 *  - `submitted`  — the provider accepted one refund POST. `webhookConfirmed` is still false
 *                   until razorpay-webhook writes the authoritative REFUNDED state, so the UI
 *                   shows "submitted, awaiting confirmation", never "refunded".
 *  - `confirmed`  — the payment row already carries webhook-proven refund evidence (idempotent
 *                   re-submit of a case the webhook has settled). `webhookConfirmed` is true.
 *  - `ambiguous`  — the provider outcome is unknown (5xx/timeout). NOT retryable here; a human
 *                   must reconcile Razorpay/webhook evidence before any further attempt.
 *  - `rejected`   — the provider refused (4xx) or eligibility failed server-side. NOT retryable
 *                   blindly; review before another attempt.
 *  - `disabled`   — refund initiation is switched off in this deployment.
 */
export type RefundInitiationOutcome =
  | 'submitted'
  | 'confirmed'
  | 'ambiguous'
  | 'rejected'
  | 'disabled';

export interface RefundInitiationResult {
  outcome: RefundInitiationOutcome;
  /** True ONLY when the webhook has already recorded the refund. Gate any "refunded" copy on this. */
  webhookConfirmed: boolean;
  refundId?: string;
  paymentId?: string;
  amountPaise?: number;
  /** 'full' | 'partial' as the server executed it. */
  mode?: 'full' | 'partial';
  /** The server's authoritative refundable remainder, returned when an amount was over-cap. */
  maxRefundablePaise?: number;
  /** The server's errorCode, surfaced verbatim so the operator sees why. */
  errorCode?: string;
  /** Human-readable message, safe to show. */
  message?: string;
}

/**
 * Shared non-retrying refund POST.
 *
 * Deliberately uses `authFetch`, NOT `apiCall`/`apiCallResult`: those auto-retry 502/503/504,
 * and a refund is irreversible — re-POSTing an ambiguous outcome is exactly the double-refund
 * the backend's no-retry boundary exists to prevent. This reads the body for every status so
 * the caller gets the server's truthful outcome instead of a collapsed null.
 */
async function postRefundInitiation (
  action: 'initiate-refund' | 'initiate-partial-refund',
  invoiceId: string,
  returnSubmissionId: string,
  reason: string,
  extra: Record<string, unknown>,
): Promise<RefundInitiationResult> {
  let response: Response;
  try
  {
    response = await authFetch( INVOICE_BASE, {
      method: 'POST',
      body: JSON.stringify( { _action: action, invoiceId, returnSubmissionId, reason, ...extra } ),
    } );
  } catch
  {
    // No response means the POST may or may not have reached the provider boundary. Treat it
    // as ambiguous — never as a failure the caller might retry into a second refund.
    return {
      outcome: 'ambiguous',
      webhookConfirmed: false,
      message: 'The refund request did not get a response. Reconcile Razorpay before retrying.',
    };
  }

  let body: Record<string, any> = {};
  try { body = await response.json(); } catch { body = {}; }

  const base: RefundInitiationResult = {
    outcome: 'rejected',
    webhookConfirmed: !!body.webhookConfirmed,
    refundId: body.refundId,
    paymentId: body.paymentId,
    amountPaise: typeof body.amountPaise === 'number' ? body.amountPaise : undefined,
    mode: body.mode === 'partial' || body.mode === 'full' ? body.mode : undefined,
    maxRefundablePaise: typeof body.maxRefundablePaise === 'number' ? body.maxRefundablePaise : undefined,
    errorCode: typeof body.errorCode === 'string' ? body.errorCode : undefined,
    message: typeof body.error === 'string' ? body.error : undefined,
  };

  if ( response.ok )
  {
    // 200 = webhook already confirmed; 202 = provider accepted, awaiting webhook.
    return { ...base, outcome: body.webhookConfirmed ? 'confirmed' : 'submitted' };
  }
  if ( response.status === 503 ) return { ...base, outcome: 'ambiguous' };
  if ( base.errorCode === 'REFUND_INITIATION_DISABLED' ) return { ...base, outcome: 'disabled' };
  return base; // 4xx/409/other -> rejected
}

/**
 * Initiate a FULL refund for a refund-eligible Return / Refund case.
 *
 * The browser supplies only the invoice and return-case identity plus the operator's audit
 * `reason`; the server derives the payment, the eligibility and the amount, and persists the
 * reason on the return-case / audit record. Returns the truthful outcome — callers must gate
 * any "refunded" wording on `webhookConfirmed`.
 */
export async function initiateFullRefund (
  invoiceId: string,
  returnSubmissionId: string,
  reason: string,
): Promise<RefundInitiationResult> {
  return postRefundInitiation( 'initiate-refund', invoiceId, returnSubmissionId, reason, {} );
}

/**
 * Initiate a PARTIAL refund of `amountPaise` for a refund-eligible Return / Refund case.
 *
 * The amount is a PROPOSAL: the server caps it to the captured total minus any already-refunded
 * amount and rejects anything over the cap or <= 0 (`REFUND_AMOUNT_OVER_CAP` /
 * `REFUND_AMOUNT_INVALID`), returning `maxRefundablePaise` so the UI can correct itself. The
 * operator's audit `reason` is persisted on the return-case / audit record server-side.
 */
export async function initiatePartialRefund (
  invoiceId: string,
  returnSubmissionId: string,
  amountPaise: number,
  reason: string,
): Promise<RefundInitiationResult> {
  return postRefundInitiation(
    'initiate-partial-refund', invoiceId, returnSubmissionId, reason, { amountPaise },
  );
}

// Add remark / refund / credit note to an invoice
export interface InvoiceRemark {
  id: string;
  type: 'remark' | 'refund' | 'credit_note';
  text: string;
  amount: number;
  author: string;
  createdAt: number;
}

// `author` is GONE from the signature and from the body. The server derives it from the
// Cognito token (`invoice-engine._remark_author`) and ignores `body.author` entirely, so a
// parameter here could only ever be a value the browser sends and the server throws away -
// and before that, it was the value the server STORED, which made a refund note signable
// with anyone's name.
export async function addInvoiceRemark (
  invoiceId: string,
  remarkType: 'remark' | 'refund' | 'credit_note',
  text: string,
  amount = 0,
  evidence?: { refundId?: string; paymentId?: string },
): Promise<{ invoiceId: string; remark: InvoiceRemark; totalRemarks: number } | null> {
  return apiCall<{ invoiceId: string; remark: InvoiceRemark; totalRemarks: number }>( `${INVOICE_BASE}/${invoiceId}/remark`, {
    method: 'POST',
    body: JSON.stringify( {
      type: remarkType,
      text,
      amount,
      ...( evidence?.refundId ? { refundId: evidence.refundId } : {} ),
      ...( evidence?.paymentId ? { paymentId: evidence.paymentId } : {} ),
    } ),
  } );
}

// ============================================================================
// SYSTEM CLEANUP API
// ============================================================================

export interface CleanupResource {
  id: string;
  label: string;
  category: string;
  type: 'dynamodb' | 's3' | 'sqs';
  table?: string;
  prefix?: string;
  queue?: string;
  count: number;
  /**
   * Whether the SERVER will act on this id. The server is the authority — it refuses a
   * protected table whatever the client sends — and these three fields exist so the UI can
   * stop offering an action that is going to be refused, rather than discovering it in the
   * result list.
   *
   * Optional because a response from an older deployment carries neither field. Absent is
   * read as SELECTABLE, which keeps the tab working against an un-upgraded backend; the
   * guard that matters is the server's, and it is not optional there.
   */
  selectable?: boolean;
  /** Set when the server will never clear this id: customer, financial or message history. */
  protected?: boolean;
  /** Why it is protected, in the server's words. Shown to the operator verbatim. */
  protectedReason?: string;
}

/**
 * The full `GET /system-cleanup` envelope.
 *
 * `getCleanupPreview` keeps returning just the rows, because that is what the Data tab
 * renders and what `src/test/DataTabCheckbox.test.tsx` mocks. The confirmation token rides
 * alongside, and `lastCleanupConfirmation()` is how the caller reads it.
 */
export interface CleanupPreview {
  resources: CleanupResource[];
  /** The ids the server minted this token for. */
  selectableIds: string[];
  /** Single-use, bound to `selectableIds`. `''` when the server could not store one. */
  confirmationToken: string;
  /** Present when the confirmation store is unavailable, i.e. nothing can be deleted. */
  warning?: string;
}

export interface CleanupResult {
  id: string;
  label: string;
  deleted: number;
  elapsed?: number;
  error?: string;
  /**
   * Rows the server PROTECTED, counted apart from `deleted` and from `error`. A contact with
   * payments is refused by design, which is a correct outcome rather than a failure — and
   * folding it into either number is how a sweep that left rows behind reads as finished.
   */
  refused?: number;
  /** The server declined this whole id. `deleted` is 0 and that is the correct outcome. */
  protected?: boolean;
  /** Why, in the server's words. */
  protectedReason?: string;
}

/** What `POST /system-cleanup` reports back. `protected`/`skipped` are server counts. */
export interface CleanupRun {
  results: CleanupResult[];
  totalDeleted: number;
  /** Ids the server declined. Rendered as "kept", NOT as an error. */
  protected?: number;
  /** Ids it did not act on at all, protected or unknown. */
  skipped?: number;
}

/**
 * The most recent preview envelope.
 *
 * Module-level because `getCleanupPreview` has to keep its `CleanupResource[]` return type:
 * `src/test/DataTabCheckbox.test.tsx` mocks it with a bare array and that test must keep
 * passing unchanged. Holding the token here rather than widening the signature means the
 * Data tab gets both from one request instead of minting a second token it would not use.
 *
 * "Most recent" is the right scope: the server's token is single-use and bound to the
 * selection it was minted for, so an older one is worthless by construction.
 */
let lastPreview: CleanupPreview | null = null;

export async function getCleanupPreview (): Promise<CleanupResource[]> {
  const data = await apiCall<CleanupPreview>( `${API_BASE}/system-cleanup` );
  lastPreview = data ?? null;
  return data?.resources || [];
}

/** The confirmation token from the most recent `getCleanupPreview`, if any. */
export function lastCleanupConfirmation (): { token: string; selectableIds: string[]; warning?: string } {
  return {
    token: lastPreview?.confirmationToken || '',
    selectableIds: lastPreview?.selectableIds || [],
    warning: lastPreview?.warning,
  };
}

export async function executeCleanup ( selected: string[], confirmationToken?: string ): Promise<CleanupRun> {
  const data = await apiCall<any>( `${API_BASE}/system-cleanup`, {
    method: 'POST',
    // The server REQUIRES the token and refuses 400 without it. Sent as a plain field
    // rather than made a required argument so the one remaining legacy caller still
    // compiles; it gets the refusal, which is the correct outcome for a call that never
    // previewed.
    body: JSON.stringify( { selected, confirmationToken: confirmationToken || '' } ),
  } );
  return {
    results: data?.results || [],
    totalDeleted: data?.totalDeleted || 0,
    protected: data?.protected || 0,
    skipped: data?.skipped || 0,
  };
}

// ============================================================================
// SUBMIT REQUESTS API (WhatsApp Flow Submissions)
// ============================================================================

export interface SubmitRequest {
  id: string;
  requestId: string;
  requestNumber?: string;  // WD-SR-XXXXXXXX
  flowToken?: string;
  phone: string;
  senderName?: string;
  contactId?: string;
  orderId: string;
  subject?: string;
  description?: string;
  paymentStatus: string; // pending, captured, failed
  paymentReferenceId?: string;
  paymentAmount?: number;
  transactionId?: string;
  invoiceId?: string;
  invoiceNumber?: string;
  daysOld?: number;
  isExpired?: boolean;
  createdAt: number;
  updatedAt?: number;
}

export async function listSubmitRequests ( paymentStatus?: string ): Promise<SubmitRequest[]> {
  let url = `${API_BASE}/wa-business/submit-requests`;
  if ( paymentStatus ) url += `?paymentStatus=${paymentStatus}`;
  const data = await apiCall<any>( url );
  return data?.requests || [];
}

export interface FlowLog {
  id: string;
  type: string;
  flowToken?: string;
  phone: string;
  action: string;
  screen: string;
  dataKeys?: string[];
  requestId?: string;
  createdAt: number;
  // Enhanced flow data fields
  order_id?: string;
  subject?: string;
  description?: string;
  email?: string;
  flowData?: string; // JSON string of full submitted data
}

export async function listFlowLogs ( phone?: string ): Promise<FlowLog[]> {
  let url = `${API_BASE}/wa-business/flow-logs`;
  if ( phone ) url += `?phone=${encodeURIComponent( phone )}`;
  const data = await apiCall<any>( url );
  return data?.logs || [];
}

export async function resendSubmitRequestPayment ( invoiceId: string ): Promise<boolean> {
  try
  {
    const data = await apiCall<any>( `${INVOICE_BASE}/${invoiceId}/send-payment-link`, {
      method: 'POST',
      body: JSON.stringify( { invoiceId } ),
    } );
    return !!data;
  } catch { return false; }
}

// ============================================================================
// FLOW MANAGEMENT ENGINE
// ============================================================================

/** Snapshot mapping verified against Meta at lastVerifiedAt; not a send-readiness grant. */
export interface TemplateFlowMappingItem {
  templateId: string;
  templateName: string;
  flowId: string;
  buttonLabel: string;
  flowButtonAction: string;
  metaTemplateStatus: string;
  lastVerifiedAt: number;
}

export interface FlowRegistryItem {
  flowId: string;
  flowCode: string;
  flowName: string;
  flowType: string;
  flowVersion?: string;
  dataApiVersion?: string;
  wabaId?: string;
  status: string;
  category?: string;
  entryMode?: 'keyword_interactive' | 'payment_template' | 'internal_event' | 'manual' | 'none' | string;
  entryTemplateName?: string;
  requiresPayment?: boolean;
  paymentAmount?: number;
  paymentDescription?: string;
  screenConfig?: string;
  contactMapping?: string;
  dataFetchers?: string;
  submissionPrefix?: string;
  endpointUri?: string;
  publishedAt?: number;
  createdAt?: number;
  updatedAt?: number;
  /** Staff identity of the last Workspace registry write. */
  updatedBy?: string;
  /** Meta's own lifecycle status from the last sync. Separate from the registry `status`. */
  metaStatus?: string;
  metaName?: string;
  jsonVersion?: string;
  lastSyncedAt?: number;
  validationErrorsJson?: string;
  healthStatusJson?: string;
  /** Read-only mappings from the dedicated table; included only when requested. */
  templateFlowMappings?: TemplateFlowMappingItem[];
}

/** One launch decision computed server-side by lambda_utils.flow_launch. */
export interface FlowLaunchDecision {
  allowed: boolean;
  reason: string;
  explanation: string;
}

/** GET /wa-business/flow-launch-status: every control that decides whether a Flow can open. */
export interface FlowLaunchStatus {
  capability: string;
  contract: {
    flowNumber: string; flowCode: string; label: string; flowType: string; entryMode: string;
    entryTemplateName: string; requiresPayment: boolean; submissionPrefix: string; wabaId: string;
    tokenPrefix: string; defaultKeywords: string[]; legacyFlowCodes: string[];
  };
  canonical: { flowId: string; status: string; metaName: string };
  registry: FlowRegistryItem | null;
  registryError: string;
  registryProblems: string[];
  runtime: { enabled: boolean; keywords: string[]; entryMode: string; flowId: string; configured: boolean; readError: string };
  keywordLaunch: FlowLaunchDecision;
  session: { ttlSeconds: number };
  endpoint: string;
}

/** GET /wa-business/flow-funnel: per-day counters, newest day first. No customer data. */
export interface FlowFunnelReport {
  flowCode: string;
  stages: string[];
  days: { day: string; counts: Record<string, number> }[];
  totals: Record<string, number>;
}

export interface FlowRegistrySaveResult {
  success: boolean;
  flowId: string;
  flow: FlowRegistryItem;
}

export async function getFlowLaunchStatus ( capability: string ): Promise<ApiResult<FlowLaunchStatus>> {
  return apiCallResult<FlowLaunchStatus>( `${WA_BIZ_BASE}/flow-launch-status?capability=${encodeURIComponent( capability )}` );
}

export async function getFlowFunnel ( flowCode: string, days = 7 ): Promise<ApiResult<FlowFunnelReport>> {
  const qs = new URLSearchParams( { flowCode, days: String( days ) } );
  return apiCallResult<FlowFunnelReport>( `${WA_BIZ_BASE}/flow-funnel?${qs.toString()}` );
}

export interface FlowSubmissionItem {
  submissionId: string;
  flowId: string;
  flowCode: string;
  flowType?: string;
  flowVersion?: string;
  phone: string;
  contactId?: string;
  /** Public customer id a staff member can quote instead of the phone number. */
  customerUuid?: string;
  senderName?: string;
  formData?: string;
  orderId?: string;
  requestType?: string;
  subject?: string;
  description?: string;
  submissionNumber?: string;
  flowToken?: string;
  paymentRequired?: boolean;
  paymentAmount?: number;
  paymentStatus: string;
  paymentRefId?: string;
  invoiceId?: string;
  /** WAMID for an endpointless WhatsApp Flow completion. Used by the unified Inbox to join the
   * message bubble to its canonical FlowSubmission row without duplicating a second inbox item. */
  whatsappMessageId?: string;
  /** WhatsApp send outcome for an invoice-copy request, e.g. 'ACCEPTED' or 'SEND_FAILED'. */
  invoiceDeliveryStatus?: string;
  transactionId?: string;
  paidAt?: number;
  status: string;
  assignedTo?: string;
  notes?: string;
  tags?: string[];
  resolvedAt?: number;
  createdAt: number;
  updatedAt?: number;
  // Service-request (post-payment) fields
  requestId?: string;
  referenceId?: string;
  /** Audited Return / Refund workflow stage; absent on non-return requests. */
  returnStage?: 'requested' | ReturnStage;
  returnUpdatedAt?: number;
  returnUpdatedBy?: string;
  refundEligibleAt?: number;
  orderNumber?: string;
  /** Order reference as the customer typed it — unverified, so never treat it as a linked order. */
  orderReference?: string;
  product?: string;
  amount?: string;
  customerName?: string;
  shippingAddress?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  landmark?: string;
  preferredTime?: string;
  attachments?: { key?: string; url?: string; type?: string; filename?: string; mime?: string; ts?: number }[];
}

export interface FlowSubmissionStats {
  total: number;
  byStatus: Record<string, number>;
  byPaymentStatus: Record<string, number>;
  totalPaymentAmount: number;
  capturedAmount: number;
  pendingAmount: number;
}

export async function listFlowRegistry ( includeTemplateMappings = false ): Promise<FlowRegistryItem[]> {
  const suffix = includeTemplateMappings ? '?includeTemplateMappings=true' : '';
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-registry${suffix}` );
  return data?.flows || [];
}

/**
 * Create or update one FlowRegistry row (Admin). The server merges the fields sent into the
 * stored row and validates the result, so a partial update is safe; a refusal carries the
 * server's reason in `failure.message`.
 */
export async function upsertFlowRegistry ( item: Partial<FlowRegistryItem> ): Promise<ApiResult<FlowRegistrySaveResult>> {
  return apiCallResult<FlowRegistrySaveResult>( `${WA_BIZ_BASE}/flow-registry`, {
    method: 'POST',
    body: JSON.stringify( item ),
  } );
}

export async function listFlowSubmissions ( params?: {
  flowCode?: string; paymentStatus?: string; status?: string; phone?: string; limit?: number;
} ): Promise<FlowSubmissionItem[]> {
  const qs = new URLSearchParams();
  if ( params?.flowCode ) qs.set( 'flowCode', params.flowCode );
  if ( params?.paymentStatus ) qs.set( 'paymentStatus', params.paymentStatus );
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.phone ) qs.set( 'phone', params.phone );
  if ( params?.limit ) qs.set( 'limit', String( params.limit ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions${query ? '?' + query : ''}` );
  return data?.submissions || [];
}

/** Stats for one flow code, keeping a refused or failed read distinguishable from zero rows. */
export async function getFlowSubmissionStatsResult ( flowCode: string ): Promise<ApiResult<FlowSubmissionStats>> {
  return apiCallResult<FlowSubmissionStats>( `${WA_BIZ_BASE}/flow-submissions/stats?flowCode=${encodeURIComponent( flowCode )}` );
}

export async function getFlowSubmissionStats ( flowCode?: string ): Promise<FlowSubmissionStats | null> {
  const qs = flowCode ? `?flowCode=${flowCode}` : '';
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions/stats${qs}` );
  return data || null;
}

export async function updateSubmissionStatus ( submissionId: string, status: string, notes?: string ): Promise<{ updated: boolean; oldStatus: string; newStatus: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions/update-status`, {
    method: 'POST',
    body: JSON.stringify( { submissionId, status, notes } ),
  } );
  return data || { updated: false, oldStatus: '', newStatus: '' };
}

export type ReturnStage = 'approved' | 'rejected' | 'item_received' | 'return_waived' | 'refund_eligible';

export async function updateReturnStage (
  submissionId: string,
  returnStage: ReturnStage,
  notes?: string,
): Promise<{ updated: boolean; oldStage: string; newStage: string; idempotent?: boolean }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions/update-status`, {
    method: 'POST',
    body: JSON.stringify( { submissionId, returnStage, notes } ),
  } );
  return data || { updated: false, oldStage: '', newStage: '' };
}

export interface CustomerJourney {
  phone: string;
  contactId: string;
  contact: Record<string, any>;
  submissions: FlowSubmissionItem[];
  logs: any[];
  summary: { flowsCompleted: string[]; totalSubmissions: number; totalPaid: number; totalInteractions: number };
}

export async function getCustomerJourney ( phone: string ): Promise<CustomerJourney | null> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-customer-journey?phone=${encodeURIComponent( phone )}` );
  return data || null;
}

export async function runSlaCheck ( params?: { slaDays?: number; reminderDays?: number; defaultAssignee?: string } ): Promise<any> {
  return apiCall<any>( `${WA_BIZ_BASE}/flow-sla-check`, { method: 'POST', body: JSON.stringify( params || {} ) } );
}

export async function cloneFlowToWaba ( sourceFlowCode: string, targetWabaId: string, targetFlowId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-clone`, {
    method: 'POST', body: JSON.stringify( { sourceFlowCode, targetWabaId, targetFlowId } ),
  } );
  return !!data?.success;
}

export async function exportSubmissionsCsv ( params?: { flowCode?: string; paymentStatus?: string } ): Promise<string> {
  const qs = new URLSearchParams();
  if ( params?.flowCode ) qs.set( 'flowCode', params.flowCode );
  if ( params?.paymentStatus ) qs.set( 'paymentStatus', params.paymentStatus );
  const query = qs.toString();
  const data = await apiCall<any>( `${WA_BIZ_BASE}/flow-submissions/export${query ? '?' + query : ''}` );
  return data?.csv || '';
}

// `FlowVersionHealth` and `checkFlowVersionHealth` were here. Removed 2026-10-07:
// the call went to `${WA_BIZ_BASE}/flow-version-health`, i.e.
// /wa-business/flow-version-health, and no live route matches it. Its one caller was
// the Flow Hub's 'Health' tab, which swallowed the 404 in a catch and rendered an
// empty panel — so the tab went with it rather than being left to render nothing.
// The flow-submissions and flow-registry calls above and below are live and stay.

// The `WhatsApp Commerce Catalog` block — `CATALOG_BASE` (`${API_BASE}/catalog`) and
// `getCatalogProducts` — was here. Removed 2026-10-07: /catalog/products has no live
// route, and the deployment never had one, so every caller got a 404 body back. That
// is worse than an error, because `apiCall` hands the parsed body on and the callers
// read `products` off it as an empty array — the UI then said "no products in this
// catalog" when the truth was "there is no catalog endpoint". Its two consumers went
// with it: src/components/CatalogBrowser.tsx (deleted) and the inbox composer's
// 'Load products' picker. This is the CUT branch of the catalog-lookup decision; the
// catalog SEND below and in the inbox is a DIFFERENT, LIVE surface over WA_BIZ_BASE
// and deliberately stays.

// ── Catalog product admin (Meta catalog create/list/delete via WA Business API) ──
export interface CatalogProductInput {
  catalogId: string;
  retailerId: string;
  name: string;
  price: number;            // rupees
  description?: string;
  imageUrl?: string;
  url?: string;
  currency?: string;
  availability?: string;
  brand?: string;
  condition?: string;
  salePrice?: number;       // rupees
}

export async function listCatalogProductsAdmin ( catalogId: string, search?: string ): Promise<any[]> {
  const qs = new URLSearchParams( { catalogId } );
  if ( search ) qs.set( 'search', search );
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-products?${qs.toString()}` );
  return data?.products || [];
}

export async function createCatalogProduct (
  input: CatalogProductInput
): Promise<{ success: boolean; productId?: string; imageFetchStatus?: string; error?: string }> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-products`, {
    method: 'POST', body: JSON.stringify( input ),
  } );
  if ( !data || data.error )
  {
    return { success: false, error: typeof data?.error === 'string' ? data.error : ( data?.error?.message || data?.error?.error_user_msg || 'Failed to create product' ) };
  }
  return { success: true, productId: data.productId, imageFetchStatus: data.imageFetchStatus };
}

/**
 * Update fields on an existing Meta catalog product.
 * `price` is sent in RUPEES, exactly as createCatalogProduct does — the handler owns the
 * rupees -> paise conversion for both, so the two paths share one unit contract.
 * `imageUrl` is mapped to `image_url` because that is the key Graph accepts on a product
 * edit; the handler filters to name/price/currency/availability/description/image_url/url.
 * It is a partial update: an `undefined` field is dropped by JSON.stringify, the handler
 * never sets the key, and Graph keeps the stored value. Callers rely on that to leave a
 * field they did not touch alone — notably `price`, which must not be re-sent on an edit
 * that did not change it.
 */
export async function updateCatalogProduct (
  productId: string,
  updates: { name?: string; price?: number; currency?: string; availability?: string; description?: string; imageUrl?: string; url?: string }
): Promise<boolean> {
  const { imageUrl, ...rest } = updates;
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-products`, {
    method: 'PUT',
    body: JSON.stringify( { productId, ...rest, ...( imageUrl ? { image_url: imageUrl } : {} ) } ),
  } );
  return data?.success === true;
}

export async function deleteCatalogProduct ( productId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${WA_BIZ_BASE}/catalog-products?productId=${encodeURIComponent( productId )}`, { method: 'DELETE' } );
  return data?.success === true;
}

// ============================================================================
// ORDERS API
// ============================================================================

export interface Order {
  orderId: string;
  orderNumber?: string;
  referenceId?: string;
  finalizationStage?: string;
  shortId?: string;
  orderDate?: string;
  orderTime?: string;
  orderDateIST?: string;
  source: string; // native source/category
  sourceOrderId?: string;
  sourceOrderNumber?: string;
  customerPhone?: string;
  customerName?: string;
  customerEmail?: string;
  totalAmount?: number;
  currency?: string;
  itemsSummary?: string;
  itemsJson?: string;
  items?: OrderItem[];
  itemCount?: number;
  orderStatus?: string; // active, fulfilled, cancelled
  status: string; // alias for orderStatus
  paymentStatus: string; // pending, captured, failed, refunded
  paymentAmount?: number;
  fulfillmentStatus?: string;
  requestCount?: number;
  notes?: string;
  adminNotes?: string;
  invoiceId?: string;
  /** How the order was paid. WhatsApp `order_details` modes take status updates by send only. */
  checkoutMode?: string;
  /** Operator-entered shipment metadata. No courier/provider sync is implied. */
  carrierName?: string;
  trackingNumber?: string;
  trackingUrl?: string;
  trackingSource?: string;
  trackingUpdatedAt?: number;
  createdAt: number;
  updatedAt?: number;
  syncedAt?: number;
}

export interface OrderItem {
  productId?: string;
  name: string;
  quantity: number;
  price: number;
  sku?: string;
  imageUrl?: string;
}

const ORDERS_BASE = `${WA_BIZ_BASE}/orders`;

export async function listOrders ( params?: {
  status?: string;
  source?: string;
  phone?: string;
  search?: string;
  limit?: number;
} ): Promise<{ orders: Order[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.source ) qs.set( 'source', params.source );
  if ( params?.phone ) qs.set( 'phone', params.phone );
  if ( params?.search ) qs.set( 'search', params.search );
  if ( params?.limit ) qs.set( 'limit', String( params.limit ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${ORDERS_BASE}${query ? '?' + query : ''}` );
  return data || { orders: [], count: 0 };
}

export async function getOrder ( orderId: string ): Promise<Order | null> {
  const order = await apiCall<Order>( `${ORDERS_BASE}/${orderId}` );
  if ( !order ) return null;
  // No invented status: an order with none stays blank rather than reading as 'active'.
  return { ...order, status: order.status || order.orderStatus || '',
    paymentStatus: order.paymentStatus === 'PAYMENT_PAID' ? 'paid' : order.paymentStatus };
}

export async function createOrder ( order: Partial<Order> ): Promise<Order | null> {
  return apiCall<Order>( ORDERS_BASE, {
    method: 'POST',
    body: JSON.stringify( order ),
  } );
}

export interface OrderPatch {
  /** Fulfilment only. Payment state is provider-controlled and intentionally absent here. */
  status?: string;
  orderStatus?: string;
  fulfillmentStatus?: string;
  adminNotes?: string;
  notes?: string;
  /** Manual shipment metadata only; tracking provenance/timestamps remain server-owned. */
  carrierName?: string;
  trackingNumber?: string;
  trackingUrl?: string;
}

export async function updateOrder ( orderId: string, updates: OrderPatch ): Promise<boolean> {
  const data = await apiCall<any>( `${ORDERS_BASE}/${encodeURIComponent( orderId )}`, {
    method: 'PATCH',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

/** Explicit audited order cancellation; deliberately separate from OrderPatch. */
export async function cancelOrder ( orderId: string, reason: string ): Promise<{ canceled: boolean; idempotent?: boolean }> {
  const data = await apiCall<any>( `${ORDERS_BASE}/${encodeURIComponent( orderId )}`, {
    method: 'PATCH',
    body: JSON.stringify( { action: 'cancel', reason } ),
  } );
  return data || { canceled: false };
}

export async function getOrderSubmissions ( orderId: string ): Promise<FlowSubmissionItem[]> {
  const data = await apiCall<any>( `${ORDERS_BASE}/${encodeURIComponent( orderId )}/submissions` );
  return data?.submissions || [];
}

// ============================================================================
// DOCUMENTS API (Drop Docs)
// ============================================================================

export interface Document {
  documentId: string;
  documentRef?: string;
  referenceIssuedAt?: number;
  referenceVersion?: number;
  originalFileName?: string;
  /** Staff's label when the type is "other", e.g. "Trade licence". */
  documentTypeLabel?: string;
  vaultFileId?: string;
  vaultPublishedAt?: number;
  /** The Vault file's name: {{1}} of the ₹49 Vault message (wecare_valut_49). */
  vaultDisplayName?: string;
  customerPhone?: string;
  customerName?: string;
  contactId?: string;
  orderId?: string;
  /** The linked order's WD-ORD number, resolved by the list. */
  orderNumber?: string;
  /** Paid F003 customer-upload identity; absent for staff Vault documents and other Flows. */
  dropDocsRequestId?: string;
  dropDocsOrderId?: string;
  dropDocsPaymentAttemptId?: string;
  source: string; // flow (customer F003), manual (staff Vault), whatsapp attachments
  type: string; // prescription, id_proof, invoice, photo, other
  status: string; // pending, uploaded, approved, rejected, reupload_requested
  fileName?: string;
  mimeType?: string;
  fileUrl?: string;
  storageKey?: string;
  s3Bucket?: string;
  fileSize?: number;
  notes?: string;
  reviewedBy?: string;
  reviewedAt?: number;
  archivedAt?: number;
  archivedBy?: string;
  createdAt: number;
  updatedAt?: number;
}

const DOCUMENTS_BASE = `${WA_BIZ_BASE}/documents`;

export async function listDocuments ( params?: {
  status?: string;
  source?: string;
  type?: string;
  phone?: string;
  limit?: number;
} ): Promise<{ documents: Document[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.source ) qs.set( 'source', params.source );
  if ( params?.type ) qs.set( 'type', params.type );
  if ( params?.phone ) qs.set( 'phone', params.phone );
  if ( params?.limit ) qs.set( 'limit', String( params.limit ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${DOCUMENTS_BASE}${query ? '?' + query : ''}` );
  return data || { documents: [], count: 0 };
}

export async function getDocument ( documentId: string ): Promise<Document | null> {
  return apiCall<Document>( `${DOCUMENTS_BASE}/${documentId}` );
}

export async function updateDocument ( documentId: string, updates: Partial<Document> ): Promise<boolean> {
  const data = await apiCall<any>( `${DOCUMENTS_BASE}/${documentId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

export async function archiveDocument ( documentId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${DOCUMENTS_BASE}/${documentId}`, {
    method: 'PUT',
    body: JSON.stringify( { _action: 'archive' } ),
  } );
  return data?.updated === true;
}

export async function restoreArchivedDocument ( documentId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${DOCUMENTS_BASE}/${documentId}`, {
    method: 'PUT',
    body: JSON.stringify( { _action: 'restore_archive' } ),
  } );
  return data?.updated === true;
}

export async function getDocumentDownloadUrl ( documentId: string ): Promise<string | null> {
  const data = await apiCall<any>( `${DOCUMENTS_BASE}/${documentId}/download` );
  return data?.url || null;
}

export async function createDocument ( doc: Partial<Document> ): Promise<Document | null> {
  return apiCall<Document>( DOCUMENTS_BASE, {
    method: 'POST',
    body: JSON.stringify( doc ),
  } );
}


export interface DocumentUploadTicket {
  documentId: string;
  documentRef: string;
  fileName: string;
  uploadUrl: string;
  expiresInSeconds: number;
  contentType: string;
}

/** Start a staff manual Drop Docs upload. The actual bytes go straight to S3. */
export async function initDocumentUpload ( input: {
  contactId?: string;
  customerName?: string;
  customerPhone?: string;
  orderId?: string;
  type: string;
  typeLabel?: string;
  fileName: string;
  mimeType: string;
  fileSize: number;
  notes?: string;
} ): Promise<ApiResult<DocumentUploadTicket>> {
  return apiCallResult<DocumentUploadTicket>( DOCUMENTS_BASE, {
    method: 'POST',
    body: JSON.stringify( { _action: 'upload_init', ...input } ),
  } );
}

/** Upload document bytes to the private Drop Docs object using its presigned PUT. */
export async function uploadDocumentBytes (
  uploadUrl: string,
  file: File,
  contentType: string,
): Promise<boolean> {
  const response = await fetch( uploadUrl, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: file,
  } );
  return response.ok;
}

/** Confirm a staff manual Drop Docs upload after S3 has the bytes. */
export async function confirmDocumentUpload ( documentId: string ): Promise<ApiResult<Document>> {
  return apiCallResult<Document>(
    `${DOCUMENTS_BASE}/${encodeURIComponent( documentId )}`,
    { method: 'PUT', body: JSON.stringify( { _action: 'confirm_upload' } ) },
  );
}


/** Start a replacement for a document that staff explicitly marked reupload_requested. */
export async function initDocumentReplacement (
  documentId: string,
  input: { fileName: string; mimeType: string; fileSize: number },
): Promise<ApiResult<DocumentUploadTicket>> {
  return apiCallResult<DocumentUploadTicket>(
    `${DOCUMENTS_BASE}/${encodeURIComponent( documentId )}`,
    {
      method: 'PUT',
      body: JSON.stringify( { _action: 'replace_upload_init', ...input } ),
    },
  );
}

/** Confirm the replacement only after S3 proves the new bytes exist. */
export async function confirmDocumentReplacement (
  documentId: string,
): Promise<ApiResult<Document>> {
  return apiCallResult<Document>(
    `${DOCUMENTS_BASE}/${encodeURIComponent( documentId )}`,
    { method: 'PUT', body: JSON.stringify( { _action: 'replace_upload_confirm' } ) },
  );
}


export async function revalidateDocumentReference (
  documentId: string,
): Promise<ApiResult<{
  updated: boolean;
  documentId: string;
  documentRef: string;
  fileName: string;
  referenceIssuedAt: number;
}>> {
  return apiCallResult(
    `${DOCUMENTS_BASE}/${encodeURIComponent( documentId )}`,
    { method: 'PUT', body: JSON.stringify( { _action: 'revalidate_reference' } ) },
  );
}

// ============================================================================
// FAQ API
// ============================================================================

export interface FaqEntry {
  faqId: string;
  question: string;
  answer: string;
  category: string;
  sortOrder: number;
  active: boolean;
  tags?: string[];
  createdAt: number;
  updatedAt?: number;
}

const FAQ_BASE = `${WA_BIZ_BASE}/faq`;

export async function listFaqs ( params?: {
  category?: string;
  active?: boolean;
} ): Promise<{ faqs: FaqEntry[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.category ) qs.set( 'category', params.category );
  if ( params?.active !== undefined ) qs.set( 'active', String( params.active ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${FAQ_BASE}${query ? '?' + query : ''}` );
  return data || { faqs: [], count: 0 };
}

export async function createFaq ( faq: Partial<FaqEntry> ): Promise<FaqEntry | null> {
  return apiCall<FaqEntry>( FAQ_BASE, {
    method: 'POST',
    body: JSON.stringify( faq ),
  } );
}

export async function updateFaq ( faqId: string, updates: Partial<FaqEntry> ): Promise<boolean> {
  const data = await apiCall<any>( `${FAQ_BASE}/${faqId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

export async function deleteFaq ( faqId: string ): Promise<boolean> {
  const data = await apiCall<any>( `${FAQ_BASE}/${faqId}`, { method: 'DELETE' } );
  return !!data;
}

// ============================================================================
// APPOINTMENTS API
// ============================================================================

export interface Appointment {
  appointmentId: string;
  contactId?: string;
  customerName?: string;
  customerPhone?: string;
  type: string;
  scheduledAt: number;
  duration?: number; // minutes
  status: string; // scheduled, confirmed, in_progress, completed, cancelled, no_show
  provider?: string;
  location?: string;
  notes?: string;
  createdAt: number;
  updatedAt?: number;
}

const APPOINTMENTS_BASE = `${WA_BIZ_BASE}/appointments`;

export async function listAppointments ( params?: {
  status?: string;
  type?: string;
  from?: string;
  to?: string;
} ): Promise<{ appointments: Appointment[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.type ) qs.set( 'type', params.type );
  if ( params?.from ) qs.set( 'from', params.from );
  if ( params?.to ) qs.set( 'to', params.to );
  const query = qs.toString();
  const data = await apiCall<any>( `${APPOINTMENTS_BASE}${query ? '?' + query : ''}` );
  return data || { appointments: [], count: 0 };
}

export async function updateAppointment ( appointmentId: string, updates: Partial<Appointment> ): Promise<boolean> {
  const data = await apiCall<any>( `${APPOINTMENTS_BASE}/${appointmentId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

// ============================================================================
// SEHAT APPOINTMENTS API
// ============================================================================

export interface SehatAppointment {
  slotId: string;
  date: string; // YYYY-MM-DD
  time: string; // HH:mm
  duration?: number;
  provider?: string;
  status: string; // available, booked, blocked, completed
  patientName?: string;
  patientPhone?: string;
  contactId?: string;
  appointmentId?: string;
  notes?: string;
  createdAt: number;
  updatedAt?: number;
}

const SEHAT_APPOINTMENTS_BASE = `${WA_BIZ_BASE}/sehat-appointments`;

export async function listSehatAppointments ( params?: {
  status?: string;
  date?: string;
  provider?: string;
} ): Promise<{ slots: SehatAppointment[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.date ) qs.set( 'date', params.date );
  if ( params?.provider ) qs.set( 'provider', params.provider );
  const query = qs.toString();
  const data = await apiCall<any>( `${SEHAT_APPOINTMENTS_BASE}${query ? '?' + query : ''}` );
  return data || { slots: [], count: 0 };
}

export async function updateSehatAppointment ( slotId: string, updates: Partial<SehatAppointment> ): Promise<boolean> {
  const data = await apiCall<any>( `${SEHAT_APPOINTMENTS_BASE}/${slotId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

export async function createSehatAppointment ( slot: Partial<SehatAppointment> ): Promise<SehatAppointment | null> {
  return apiCall<SehatAppointment>( SEHAT_APPOINTMENTS_BASE, {
    method: 'POST',
    body: JSON.stringify( slot ),
  } );
}

// ============================================================================
// ENTERPRISE ASSIST API
// ============================================================================

export interface EnterpriseCase {
  caseId: string;
  contactId?: string;
  customerName?: string;
  customerPhone?: string;
  subject: string;
  description?: string;
  category?: string;
  priority: string; // low, medium, high, critical
  status: string; // open, in_progress, waiting, resolved, closed
  assignedTo?: string;
  resolution?: string;
  resolvedAt?: number;
  createdAt: number;
  updatedAt?: number;
}

const ENTERPRISE_BASE = `${WA_BIZ_BASE}/enterprise-assist`;

export async function listEnterpriseCases ( params?: {
  status?: string;
  priority?: string;
  assignedTo?: string;
} ): Promise<{ cases: EnterpriseCase[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.priority ) qs.set( 'priority', params.priority );
  if ( params?.assignedTo ) qs.set( 'assignedTo', params.assignedTo );
  const query = qs.toString();
  const data = await apiCall<any>( `${ENTERPRISE_BASE}${query ? '?' + query : ''}` );
  return data || { cases: [], count: 0 };
}

export async function updateEnterpriseCase ( caseId: string, updates: Partial<EnterpriseCase> ): Promise<boolean> {
  const data = await apiCall<any>( `${ENTERPRISE_BASE}/${caseId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}

// ============================================================================
// REVIEWS API
// ============================================================================

export interface Review {
  reviewId: string;
  contactId?: string;
  customerName?: string;
  customerPhone?: string;
  rating?: number; // 1-5 when the customer supplied a rating
  reviewType?: string;
  visibility?: string;
  comment?: string;
  source: string; // whatsapp, web, google, manual
  status: string; // pending, approved, hidden, flagged
  response?: string;
  respondedAt?: number;
  orderId?: string;
  productId?: string;
  createdAt: number;
  updatedAt?: number;
}

const REVIEWS_BASE = `${WA_BIZ_BASE}/reviews`;

export async function listReviews ( params?: {
  customerPhone?: string;
  contactId?: string;
  status?: string;
  source?: string;
  minRating?: number;
} ): Promise<{ reviews: Review[]; count: number }> {
  const qs = new URLSearchParams();
  if ( params?.customerPhone ) qs.set('customerPhone', params.customerPhone);
  if ( params?.contactId ) qs.set('contactId', params.contactId);
  if ( params?.status ) qs.set( 'status', params.status );
  if ( params?.source ) qs.set( 'source', params.source );
  if ( params?.minRating ) qs.set( 'minRating', String( params.minRating ) );
  const query = qs.toString();
  const data = await apiCall<any>( `${REVIEWS_BASE}${query ? '?' + query : ''}` );
  return data || { reviews: [], count: 0 };
}

export async function updateReview ( reviewId: string, updates: Partial<Review> ): Promise<boolean> {
  const data = await apiCall<any>( `${REVIEWS_BASE}/${reviewId}`, {
    method: 'PUT',
    body: JSON.stringify( updates ),
  } );
  return !!data;
}


// ============================================================================
// SERVICE REQUEST API (Submit / Track / Amend — Order-Centric)
// ============================================================================

export interface SubmitRequestPayload {
  orderId: string;
  requestType: string;
  subject: string;
  description: string;
}

export interface AmendRequestPayload {
  submissionId: string;
  orderId: string;
  amendmentType: string;
  description: string;
  attachments?: string[];
}

export interface TrackingData {
  order: Order;
  submissions: FlowSubmissionItem[];
  statusHistory: StatusHistoryEntry[];
  documents: Document[];
}

export interface StatusHistoryEntry {
  historyId: string;
  submissionId: string;
  orderId?: string;
  oldStatus: string;
  newStatus: string;
  changedBy: string;
  changedByName?: string;
  notes?: string;
  changedAt: number;
}

export interface DraftData {
  draftKey: string;
  phone: string;
  flowCode: string;
  screen: string;
  formData: string;
  updatedAt: number;
}

const SERVICE_BASE = `${WA_BIZ_BASE}/service`;

export async function submitRequest ( payload: SubmitRequestPayload ): Promise<{ submissionId: string; submissionNumber: string } | null> {
  return apiCall<{ submissionId: string; submissionNumber: string }>( `${SERVICE_BASE}/submit`, {
    method: 'POST',
    body: JSON.stringify( payload ),
  } );
}

export async function amendRequest ( payload: AmendRequestPayload ): Promise<{ success: boolean; amendmentId?: string } | null> {
  return apiCall<{ success: boolean; amendmentId?: string }>( `${SERVICE_BASE}/amend`, {
    method: 'POST',
    body: JSON.stringify( payload ),
  } );
}

export async function getTrackingData ( orderId: string ): Promise<TrackingData | null> {
  return apiCall<TrackingData>( `${SERVICE_BASE}/track/${encodeURIComponent( orderId )}` );
}

export async function getStatusHistory ( params: { orderId?: string; submissionId?: string } ): Promise<StatusHistoryEntry[]> {
  const qs = new URLSearchParams();
  if ( params.orderId ) qs.set( 'orderId', params.orderId );
  if ( params.submissionId ) qs.set( 'submissionId', params.submissionId );
  const query = qs.toString();
  const data = await apiCall<any>( `${SERVICE_BASE}/history${query ? '?' + query : ''}` );
  return data?.history || [];
}

export async function saveDraft ( draft: Partial<DraftData> ): Promise<boolean> {
  const data = await apiCall<any>( `${SERVICE_BASE}/drafts`, {
    method: 'POST',
    body: JSON.stringify( draft ),
  } );
  return !!data;
}

export async function getDraft ( flowCode: string ): Promise<DraftData | null> {
  return apiCall<DraftData>( `${SERVICE_BASE}/drafts/${encodeURIComponent( flowCode )}` );
}

export async function deleteDraft ( flowCode: string ): Promise<boolean> {
  const data = await apiCall<any>( `${SERVICE_BASE}/drafts/${encodeURIComponent( flowCode )}`, { method: 'DELETE' } );
  return !!data;
}

export async function createAppointment ( appointment: Partial<Appointment> ): Promise<Appointment | null> {
  return apiCall<Appointment>( APPOINTMENTS_BASE, {
    method: 'POST',
    body: JSON.stringify( appointment ),
  } );
}

export async function createEnterpriseCase ( caseData: Partial<EnterpriseCase> ): Promise<EnterpriseCase | null> {
  return apiCall<EnterpriseCase>( ENTERPRISE_BASE, {
    method: 'POST',
    body: JSON.stringify( caseData ),
  } );
}

export async function createReview ( review: Partial<Review> ): Promise<Review | null> {
  return apiCall<Review>( REVIEWS_BASE, {
    method: 'POST',
    body: JSON.stringify( review ),
  } );
}

