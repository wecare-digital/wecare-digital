/**
 * Canonical phone entry for staff customer forms.
 *
 * The country code is visible in the selector, not inferred from number length. National
 * inputs use that selected code; explicit +E.164 and 00-prefixed international inputs keep
 * their own calling code. Formatting punctuation is ignored for identity comparisons.
 *
 * This is not a validation or identity authority: the Contacts API still normalizes and
 * enforces uniqueness before any write.
 */
export function contactPhoneE164 ( raw: string, selectedDialCode: string ): string {
  const value = String( raw || '' ).trim();
  if ( !value || !/^\+?[0-9\s().-]+$/.test( value ) ) return '';
  const digits = value.replace( /\D/g, '' );
  if ( value.startsWith( '+' ) ) return digits ? `+${digits}` : '';
  if ( value.startsWith( '00' ) ) return digits.length > 2 ? `+${digits.slice( 2 )}` : '';
  const dial = selectedDialCode.replace( /\D/g, '' );
  const national = digits.replace( /^0+/, '' );
  return dial && national ? `+${dial}${national}` : '';
}

/** Comparison key only; never use a digit-stripped value as the canonical stored phone. */
export function contactPhoneMatchKey ( value: string ): string {
  return String( value || '' ).replace( /\D/g, '' );
}
