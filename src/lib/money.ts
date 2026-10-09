/**
 * Integer paise -> a rupee string, by STRING SLICING rather than by dividing.
 *
 * Slicing the decimal string is exact for every value DynamoDB can hold in a Number, because
 * there is no division to be inexact. Only the WHOLE-rupee part is handed to Intl, and grouping
 * an integer cannot introduce a fractional artefact. Indian grouping (lakh/crore) is `en-IN`, so
 * 10000000 paise formats as ₹1,00,000.00 and not ₹100,000.00.
 *
 * The currency is COMPARED, never inferred and never defaulted. A row whose amount is null, or
 * whose currency is anything but 'INR', returns '' and the caller renders "Amount unavailable" -
 * a number behind a rupee sign that is not rupees is worse than no number at all.
 *
 * TWO EXISTING FORMATTERS DO THIS WRONG AND NEITHER MAY BE USED ON THIS PAGE.
 *   src/pages/cart.tsx:124        `Math.round( paise ) / 100` then toLocaleString - a float
 *                                 division on the display path. cart.tsx belongs to another
 *                                 phase and is deliberately left alone.
 *   retired formatters pilot      `formatCurrency( amount, currency = 'INR' )`: divides by 100,
 *                                 DEFAULTS the currency instead of comparing it, has no en-IN
 *                                 grouping, and renders a formatted FOREIGN amount rather than
 *                                 refusing it - the exact behaviour this module forbids.
 *                                 Measured: zero callers anywhere in src/, tests/, scripts/ or
 *                                 tools/, so it is exported dead code. It is left in place
 *                                 (another phase's file, and a removal is its own change) but it
 *                                 is the one an implementer searching for "an existing money
 *                                 helper" finds first.
 */
export function formatPaiseINR ( paise: number | null, currency: string ): string {
  if ( paise === null || !Number.isInteger( paise ) || paise < 0 ) return '';
  if ( currency !== 'INR' ) return '';
  const digits = String( paise );
  const whole = digits.length > 2 ? digits.slice( 0, -2 ) : '0';
  const frac = digits.slice( -2 ).padStart( 2, '0' );
  return `₹${ Number( whole ).toLocaleString( 'en-IN' ) }.${ frac }`;
}

export default formatPaiseINR;
