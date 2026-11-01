/**
 * The ONLY short action-notification vocabulary on customer-facing pages.
 *
 * A public API/Meta response is never rendered verbatim in a toast. Call sites
 * must map a trusted, domain-specific outcome to a key in this vocabulary.
 *
 * "whatsappAccepted" is for an EXPLICIT provider-accepted send, never a
 * generic HTTP 2xx: e.g. Vault's 202 PAYMENT_REQUEST_UNCONFIRMED is NOT sent.
 * Payments, auth validation, file access and other safety-critical guidance
 * remain persistent inline with the action they describe.
 *
 * Workspace owns its own wording; this module is customer-facing only.
 */
export type PublicActionNoticeKind =
  | 'processing' | 'success' | 'failure' | 'blocked'
  | 'whatsappAccepted' | 'whatsappFailed';

export const PUBLIC_ACTION_TEXT: Readonly<Record<PublicActionNoticeKind, string>> = {
  processing: 'Processing…',
  success: 'Done.',
  failure: "Couldn't complete. Try again.",
  blocked: 'This action is unavailable right now.',
  whatsappAccepted: 'Sent to WhatsApp.',
  whatsappFailed: "Couldn't confirm. Check WhatsApp.",
};

export function publicActionText ( kind: PublicActionNoticeKind ): string {
  return PUBLIC_ACTION_TEXT[ kind ];
}

/** Status/code classification, not server-provided free text. A 429/503 must
 * not invite immediate retries; transient or unknown errors use 'failure'. */
export function publicApiFailureKind ( httpStatus?: number | null ): 'failure' | 'blocked' {
  switch ( httpStatus ) {
    case 403:
    case 404:
    case 409:
    case 423:
    case 429:
    case 501:
    case 503:
      return 'blocked';
    default:
      return 'failure';
  }
}

export function publicApiFailureText ( httpStatus?: number | null ): string {
  return publicActionText( publicApiFailureKind( httpStatus ) );
}
