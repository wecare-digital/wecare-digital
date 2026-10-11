/**
 * Phone masking for Service Operations list views.
 *
 * Lists mask the mobile to the last four digits (the brief: "lists should mask phone where
 * required"); a customer-detail view may show more to an authorized role. One helper so every
 * list masks identically rather than each page slicing the string its own way.
 */

/** Mask a phone to its last 4 digits, e.g. "919330994400" -> "•••• 4400". Safe on junk input. */
export const maskPhone = ( phone?: string | null ): string => {
  const digits = ( phone || '' ).replace( /\D/g, '' );
  if ( !digits ) return '—';
  if ( digits.length <= 4 ) return digits;
  return `•••• ${digits.slice( -4 )}`;
};

/** The last 4 digits alone, for compact columns. */
export const phoneLast4 = ( phone?: string | null ): string => {
  const digits = ( phone || '' ).replace( /\D/g, '' );
  return digits ? digits.slice( -4 ) : '—';
};
