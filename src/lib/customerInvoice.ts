/**
 * Authenticated customer invoice download, using the EXISTING paid-order API.
 * URLs are short-lived signed S3 grants; never expose or persist them in JSX.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const INVOICE_URL = `${API_BASE}/ecommerce/my-invoice`;
const SIGNED_MARKERS = [ 'X-Amz-Signature=', 'X-Amz-Credential=', 'Signature=', 'Expires=' ];

export type InvoiceDownloadResult = 'ok' | 'unavailable' | 'expired' | 'rate' | 'failed';

export function isSignedInvoiceUrl ( value: unknown ): value is string {
  return typeof value === 'string' && value.startsWith( 'https://' )
    && SIGNED_MARKERS.some( marker => value.includes( marker ) );
}

/** Only the server issues an invoice grant; no client-generated invoice or GST number. */
export async function downloadOrderInvoice (
  token: string, referenceId: string, createdAt: number,
): Promise<InvoiceDownloadResult> {
  if ( !token || !referenceId || !Number.isSafeInteger( createdAt ) || createdAt < 1 ) {
    return 'unavailable';
  }
  let response: Response;
  try {
    response = await fetch( INVOICE_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json',
        authorization: `Bearer ${token}` },
      body: JSON.stringify( { referenceId, createdAt, format: 'png' } ),
    } );
  } catch { return 'failed'; }
  if ( response.status === 401 ) return 'expired';
  if ( response.status === 429 ) return 'rate';
  if ( [ 400, 403, 404 ].includes( response.status ) ) return 'unavailable';
  if ( !response.ok ) return 'failed';
  let body: { available?: unknown; url?: unknown };
  try { body = await response.json(); }
  catch { return 'unavailable'; }
  if ( body.available !== true ) return 'unavailable';
  if ( !isSignedInvoiceUrl( body.url ) ) return 'failed';
  const anchor = document.createElement( 'a' );
  anchor.href = body.url;
  anchor.rel = 'noopener';
  // The S3 signer, not browser-supplied order details, sets the attachment filename.
  document.body.appendChild( anchor );
  anchor.click();
  anchor.remove();
  return 'ok';
}
