import type { CreateInvoiceEngineResult } from '../api/client';

/**
 * Why an invoice create produced no invoice, in the server's own words.
 *
 * ONE interpreter for every staff surface that raises an invoice (Pay, and the Inbox payment
 * composer), so the same refusal reads the same everywhere.
 *
 * Two outcomes that must not be confused. A deliberate refusal (any 4xx, or a 5xx the engine
 * marked `retryable`) wrote nothing, so the operator is told what to fix. No answer, a 2xx with
 * no invoice id, or a gateway 5xx is UNKNOWN: the write may have landed, and a second click mints
 * a fresh referenceId the server cannot dedupe against, so the ledger comes before the button.
 *
 * `ledger` names where that ledger is from the calling page.
 */
export function describeInvoiceCreateRefusal (
  result: Extract<CreateInvoiceEngineResult, { ok: false }>,
  ledger = 'Invoices',
): string {
  const { status, message, retryable } = result;
  const check = `Check ${ ledger } before creating another.`;
  if ( status === null ) return `Creation was not confirmed. ${ check }`;
  if ( status < 400 || ( status >= 500 && !retryable ) ) {
    return `Creation was not confirmed (status ${ status }). ${ check }`;
  }
  const said = message ? `: ${ message.replace( /\.$/, '' ) }` : '';
  const next = status === 401 ? ' Sign in again, then retry.' : retryable ? ' You can retry.' : '';
  return `Invoice not created (status ${ status })${ said }.${ next }`;
}
