/**
 * Country dial codes, in one place.
 *
 * MOVED HERE RATHER THAN COPIED. This list already existed as a `COUNTRY_CODES` literal inside
 * the former Contacts workspace, since consolidated into /workspace/customers. The
 * public sign-in field needs the same entries; keeping a single list avoids divergence
 * between customer sign-in and the Workspace customer editor.
 *
 * ORDER IS DELIBERATE AND NOT ALPHABETICAL. India is first because it is the store's market; the
 * rest follow broadly by how likely they are for this audience (Gulf and SE Asia before Europe,
 * because that is where the diaspora this store serves actually is). A select whose first option
 * is the common answer is faster than one that opens on Argentina.
 *
 * ── NO FLAGS, BY OWNER INSTRUCTION (2026-10-02) ─────────────────────────────────────────────────
 * An emoji flag was briefly carried per row and has been REMOVED. It also removes a real rendering
 * problem rather than only a preference: Windows ships no flag glyphs, so Chrome and Edge there
 * rendered each regional-indicator pair as two bare letters ("IN") instead of a flag, which looked
 * broken on a large share of desktop visits. The dial code and the country name carry all the
 * information the flag did. Do not reintroduce emoji flags; if flags are ever wanted again they
 * need an SVG sprite and a decision about its weight on a static export.
 *
 * ── WHICH TERRITORIES ARE OFFERED, AND WHY ──────────────────────────────────────────────────────
 * Two separate reasons remove a territory from this list, and they should not be conflated:
 *
 * 1. TECHNICAL - WhatsApp cannot deliver there, so an OTP could never arrive. Offering such a code
 *    is a dead end the person cannot see, the same class of defect as the "no files are registered
 *    to this number" guard on /get. Excluded on this ground:
 *      +86  China        - WhatsApp blocked since 2017 (was previously offered here; removed)
 *      +98  Iran         - WhatsApp blocked
 *      +963 Syria        - WhatsApp blocked / unavailable
 *      +850 North Korea  - no consumer internet access
 *
 * 2. COMMERCIAL / REGULATORY - the owner has decided the business does not serve that market.
 *    This is an ordinary market-scope decision of the kind every business makes, and it is the
 *    owner's call, not this file's. Excluded on this ground:
 *      +92  Pakistan     - owner instruction, 2026-10-02
 *
 * HOW TO RECORD A FUTURE EXCLUSION: add the dial code, the country, the date, and WHICH of the two
 * reasons above applies. Keep the reason factual - a market-scope or compliance decision, stated as
 * such. This file is read by engineers, auditors and anyone reviewing the repo, so the comment
 * should say what was decided and when, not characterise the people who live there.
 *
 * HONEST LIMIT ON COMPLETENESS. WhatsApp is available in most of the world, so an exhaustive list
 * runs to ~195 entries. This is a CURATED SUBSET of the markets this store plausibly serves, not a
 * claim to completeness, and it is deliberately easy to extend: add a row with its name, code and
 * nationalDigits. It is NOT generated from a vendor feed - no vendor publishes a machine-readable
 * "supported countries" list - so anyone extending it should check the territory is not blocked
 * before adding it.
 *
 * NOT THE VALIDATION AUTHORITY. `nationalDigits` is a CLIENT-SIDE pre-check so a shopper learns
 * about a wrong-length number before a round trip. The server remains the authority:
 * customerAuth.normaliseMobile() and the Python validators have to agree with the backend byte for
 * byte, and neither is relaxed by anything here.
 */

export interface DialCode {
  /** The dial code with its leading plus, e.g. "+91". Display AND value. */
  code: string;
  /** Country name, as a shopper would recognise it. Translatable text when rendered. */
  country: string;
  /**
   * Valid NATIONAL number lengths (digits after the dial code, trunk zero stripped).
   *
   * An array because many countries have more than one valid length - UK mobiles are 10 but some
   * landlines are 9, UAE is 8 or 9. India is the one the owner named explicitly: EXACTLY 10.
   * An empty array means "we do not have a rule for this country" and the client-side check must
   * then pass anything non-empty and let the server decide, rather than inventing a bound.
   */
  nationalDigits: readonly number[];
}

export const DIAL_CODES: readonly DialCode[] = [
  // The store's market, and the only entry with a single hard length the owner specified.
  { code: '+91', country: 'India', nationalDigits: [ 10 ] },
  // Gulf - the largest diaspora markets for this store.
  { code: '+971', country: 'United Arab Emirates', nationalDigits: [ 8, 9 ] },
  { code: '+966', country: 'Saudi Arabia', nationalDigits: [ 9 ] },
  { code: '+974', country: 'Qatar', nationalDigits: [ 8 ] },
  { code: '+965', country: 'Kuwait', nationalDigits: [ 8 ] },
  { code: '+968', country: 'Oman', nationalDigits: [ 8 ] },
  { code: '+973', country: 'Bahrain', nationalDigits: [ 8 ] },
  // Anglophone.
  { code: '+1', country: 'United States / Canada', nationalDigits: [ 10 ] },
  { code: '+44', country: 'United Kingdom', nationalDigits: [ 9, 10 ] },
  { code: '+61', country: 'Australia', nationalDigits: [ 9 ] },
  { code: '+64', country: 'New Zealand', nationalDigits: [ 8, 9 ] },
  { code: '+353', country: 'Ireland', nationalDigits: [ 9 ] },
  // South Asia. (+92 Pakistan excluded on owner instruction - see the header.)
  { code: '+880', country: 'Bangladesh', nationalDigits: [ 10 ] },
  { code: '+94', country: 'Sri Lanka', nationalDigits: [ 9 ] },
  { code: '+977', country: 'Nepal', nationalDigits: [ 10 ] },
  { code: '+960', country: 'Maldives', nationalDigits: [ 7 ] },
  { code: '+975', country: 'Bhutan', nationalDigits: [ 8 ] },
  // South-East and East Asia. (+86 China excluded - WhatsApp blocked.)
  { code: '+65', country: 'Singapore', nationalDigits: [ 8 ] },
  { code: '+60', country: 'Malaysia', nationalDigits: [ 9, 10 ] },
  { code: '+62', country: 'Indonesia', nationalDigits: [ 9, 10, 11 ] },
  { code: '+63', country: 'Philippines', nationalDigits: [ 10 ] },
  { code: '+66', country: 'Thailand', nationalDigits: [ 9 ] },
  { code: '+84', country: 'Vietnam', nationalDigits: [ 9 ] },
  { code: '+81', country: 'Japan', nationalDigits: [ 10 ] },
  { code: '+82', country: 'South Korea', nationalDigits: [ 9, 10 ] },
  { code: '+852', country: 'Hong Kong', nationalDigits: [ 8 ] },
  // Europe.
  { code: '+49', country: 'Germany', nationalDigits: [ 10, 11 ] },
  { code: '+33', country: 'France', nationalDigits: [ 9 ] },
  { code: '+34', country: 'Spain', nationalDigits: [ 9 ] },
  { code: '+39', country: 'Italy', nationalDigits: [ 9, 10 ] },
  { code: '+31', country: 'Netherlands', nationalDigits: [ 9 ] },
  { code: '+41', country: 'Switzerland', nationalDigits: [ 9 ] },
  { code: '+46', country: 'Sweden', nationalDigits: [ 7, 8, 9 ] },
  { code: '+47', country: 'Norway', nationalDigits: [ 8 ] },
  { code: '+45', country: 'Denmark', nationalDigits: [ 8 ] },
  { code: '+351', country: 'Portugal', nationalDigits: [ 9 ] },
  { code: '+48', country: 'Poland', nationalDigits: [ 9 ] },
  { code: '+30', country: 'Greece', nationalDigits: [ 10 ] },
  { code: '+90', country: 'Türkiye', nationalDigits: [ 10 ] },
  // Africa.
  { code: '+27', country: 'South Africa', nationalDigits: [ 9 ] },
  { code: '+234', country: 'Nigeria', nationalDigits: [ 10 ] },
  { code: '+254', country: 'Kenya', nationalDigits: [ 9 ] },
  { code: '+255', country: 'Tanzania', nationalDigits: [ 9 ] },
  { code: '+256', country: 'Uganda', nationalDigits: [ 9 ] },
  { code: '+233', country: 'Ghana', nationalDigits: [ 9 ] },
  { code: '+20', country: 'Egypt', nationalDigits: [ 10 ] },
  { code: '+212', country: 'Morocco', nationalDigits: [ 9 ] },
  { code: '+230', country: 'Mauritius', nationalDigits: [ 7, 8 ] },
  // Americas.
  { code: '+55', country: 'Brazil', nationalDigits: [ 10, 11 ] },
  { code: '+52', country: 'Mexico', nationalDigits: [ 10 ] },
  { code: '+54', country: 'Argentina', nationalDigits: [ 10 ] },
  { code: '+56', country: 'Chile', nationalDigits: [ 9 ] },
  { code: '+57', country: 'Colombia', nationalDigits: [ 10 ] },
  { code: '+51', country: 'Peru', nationalDigits: [ 9 ] },
  // Rest.
  { code: '+972', country: 'Israel', nationalDigits: [ 9 ] },
  { code: '+7', country: 'Russia / Kazakhstan', nationalDigits: [ 10 ] },
  { code: '+380', country: 'Ukraine', nationalDigits: [ 9 ] },
  { code: '+998', country: 'Uzbekistan', nationalDigits: [ 9 ] },
  { code: '+679', country: 'Fiji', nationalDigits: [ 7 ] },
];

/**
 * The default selection: the store's own market.
 *
 * A VISIBLE DEFAULT, NOT AN INFERENCE. This is the difference that matters in the sign-in field:
 * normaliseMobile() quietly treats any ten digits starting 6-9 as Indian, which is wrong for a
 * shopper in Dubai and invisible to them. A selector that SHOWS "+91" from the first paint is a
 * default the shopper can see and change; an inference is one they cannot.
 */
export const DEFAULT_DIAL_CODE = '+91';

/** Lookup by dial code. Returns undefined for a code not in the offered list. */
export const findDialCode = ( code: string ): DialCode | undefined =>
  DIAL_CODES.find( entry => entry.code === code );

/**
 * Is this national number the right LENGTH for the selected country?
 *
 * DIGITS ONLY, AND LENGTH ONLY. This deliberately does not attempt to judge whether a number is
 * real, allocated, or mobile-vs-landline - that is normaliseMobile()'s job on the client and the
 * backend's job authoritatively. It answers one question a shopper benefits from hearing
 * immediately: "that is not the right number of digits for the country you picked."
 *
 * Returns true when we have NO rule for the country (nationalDigits empty), because refusing a
 * number on the basis of a bound we never established would block a legitimate shopper to enforce
 * a guess. An empty input is NOT valid - that is a separate, earlier check.
 */
export const isValidNationalLength = ( code: string, national: string ): boolean => {
  const digits = national.replace( /\D/g, '' ).replace( /^0+/, '' );
  if ( !digits ) return false;
  const entry = findDialCode( code );
  if ( !entry || entry.nationalDigits.length === 0 ) return true;
  return entry.nationalDigits.includes( digits.length );
};

/**
 * The expected-length hint for a country, as a short phrase for a placeholder or an error.
 * "10-digit" for India, "8- or 9-digit" for the UAE, and an empty string where we have no rule -
 * so a caller can omit the hint entirely rather than print something vague.
 */
export const nationalLengthHint = ( code: string ): string => {
  const entry = findDialCode( code );
  if ( !entry || entry.nationalDigits.length === 0 ) return '';
  const lengths = [ ...entry.nationalDigits ].sort( ( a, b ) => a - b );
  if ( lengths.length === 1 ) return `${lengths[ 0 ]}-digit`;
  const last = lengths.pop();
  return `${lengths.join( ', ' )}- or ${last}-digit`;
};
