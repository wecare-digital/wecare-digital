/**
 * The payment-attempt vocabulary, mirrored for the browser.
 *
 * Why this exists
 * ---------------
 * Two checkout screens decided what a customer was told by comparing a raw string:
 * `status === 'PAYMENT_PAID'` in /checkout/success and a chain of `s === '…'` in
 * /checkout/status. The backend has never allowed that — `lambda_utils/payment_status`
 * exists precisely because the same real-world state was spelled five different ways
 * across five tables, and `lambda_utils/ecommerce/payment_attempt` holds the attempt
 * ladder as named frozen sets so the rule is greppable and cannot be widened by editing
 * an `or`. The browser had no such module, so the one screen a paying customer reads was
 * the only place in the payment path still comparing literals.
 *
 * The sets below mirror `payment_attempt.ORDER_ELIGIBLE_STATES`, `RETRYABLE_STATES` and
 * `IN_FLIGHT_STATES` one-for-one. If a state is added there, add it here in the same
 * change: a state this file does not know ranks as unknown, and an unknown state is
 * rendered as a neutral holding screen rather than as success or as failure.
 *
 * Money
 * -----
 * `rupeesFromPaise` is integer-only, deliberately. `formatters.formatCurrency` divides by
 * 100 and calls `toFixed(2)`, which is the float path R6.1 forbids anywhere in the payment
 * path; this mirrors `payment_status.rupees_str` instead — integer division and a modulo,
 * so a displayed amount cannot drift from the paise that were actually captured.
 */

/** The one state from which an order may exist. A set, not a comparison. */
const ORDER_ELIGIBLE_STATES: ReadonlySet<string> = new Set( [ 'PAYMENT_PAID' ] );

/** Definitely over. Only these may offer a new checkout. */
const RETRYABLE_STATES: ReadonlySet<string> = new Set( [
  'PAYMENT_FAILED', 'PAYMENT_CANCELLED', 'PAYMENT_EXPIRED',
] );

/** Still in flight: the outcome is not known yet, and money may already have moved. */
const IN_FLIGHT_STATES: ReadonlySet<string> = new Set( [
  'CREATED', 'PAYMENT_READINESS_CHECKED', 'PAYMENT_REQUEST_SENT', 'PAYMENT_PENDING',
] );

function normalise ( status: string | null | undefined ): string {
  return String( status || '' ).trim().toUpperCase();
}

/**
 * Whether the money is captured.
 *
 * This answers one question only — did the payment succeed — and it deliberately knows
 * nothing about the Wix writeback. An attempt sitting at `NEEDS_RECONCILIATION` with
 * `WIX_WRITE_CONTRACT_REQUIRED` is paid: the capture was verified by the webhook and the
 * internal order committed before that stage was ever written. The outstanding step is our
 * bookkeeping against the store, not the customer's payment, so it must never reach the
 * customer as doubt. `finalizationStage` is not returned by the status endpoint at all,
 * which is the structural version of that rule.
 */
export function isPaid ( status: string | null | undefined ): boolean {
  return ORDER_ELIGIBLE_STATES.has( normalise( status ) );
}

/** Whether a NEW checkout may be offered. False while in flight, false once paid. */
export function isRetryable ( status: string | null | undefined ): boolean {
  return RETRYABLE_STATES.has( normalise( status ) );
}

/** Whether the outcome is still unknown and the screen should keep asking. */
export function isInFlight ( status: string | null | undefined ): boolean {
  return IN_FLIGHT_STATES.has( normalise( status ) );
}

/** The shape of a server-minted public order number, e.g. `WD-ORD-7ZTSG8X7`. */
const ORDER_NUMBER = /^[A-Z0-9-]{8,20}$/;

/**
 * Whether this is a server order number worth showing. A URL is never evidence — the
 * number still only renders when the authenticated status read returned it alongside a
 * paid state — so this is a shape check, not an authorisation.
 */
export function isOrderNumber ( value: string | null | undefined ): boolean {
  return ORDER_NUMBER.test( String( value || '' ) );
}

/**
 * Integer paise rendered as rupees for display. `''` when there is no usable amount, so a
 * caller omits the line rather than printing a zero it cannot stand behind.
 *
 * No division, no `toFixed`, no `Number` arithmetic on the way to the screen: `0.1 + 0.2`
 * is not `0.3` in binary floating point, and a one-paise drift between what the customer
 * was charged and what the confirmation claims is the one error on this screen that cannot
 * be explained away.
 */
export function rupeesFromPaise ( amountPaise: unknown ): string {
  if ( typeof amountPaise !== 'number' || !Number.isSafeInteger( amountPaise ) ) return '';
  if ( amountPaise < 0 ) return '';
  const rupees = Math.trunc( amountPaise / 100 );
  const paise = amountPaise % 100;
  return `${rupees.toLocaleString( 'en-IN' )}.${String( paise ).padStart( 2, '0' )}`;
}

/**
 * The amount with its symbol. Currency is compared EXPLICITLY and never inferred from the
 * amount; anything other than INR returns `''` so an unexpected currency shows no amount
 * rather than a wrong one.
 */
export function amountLabel ( amountPaise: unknown, currency: string | null | undefined ): string {
  if ( String( currency || 'INR' ).toUpperCase() !== 'INR' ) return '';
  const rupees = rupeesFromPaise( amountPaise );
  return rupees ? `\u20b9${rupees}` : '';
}
