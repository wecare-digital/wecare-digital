/**
 * THE ONE ADDRESS FORMAT, as the browser sees it.
 *
 * WHY THIS MODULE EXISTS AT ALL
 * -----------------------------
 * "One address format for the website, WhatsApp and Wix" was already true on the server:
 * `lambda_utils/ecommerce/contact_address.py` owns `_RULES` - eight fields, four required -
 * `normalize_for_storage` validates and stores them at `checkoutDeliveryAddress`, and
 * `payment_address.for_wix` / `for_meta_beneficiary` project that one stored shape onto Wix and
 * onto Meta's beneficiary block. There was never a second server format.
 *
 * What there WAS, twice over, is a browser that did not use it. The Contacts form and the Pay
 * Flow customer form each carried a free-text "Delivery Address" textarea beside a partial set
 * of structured inputs, so a staff member could type one address into the textarea and a
 * different one into the fields, and nothing reconciled them. Worse, on Contacts the structured
 * half was not even wired: `formAddressLine1` had no input bound to it, the field LABELLED
 * "Address" wrote `formBuildingName`, and both payloads gated the structured `address` object on
 * `formAddressLine1` being truthy - so `address` was permanently `undefined` and
 * `checkoutDeliveryAddress` was NEVER written from the CRM.
 *
 * ONE FORMAT IS ENFORCED BY THERE BEING ONE FUNCTION, NOT BY TWO FORMS AGREEING.
 * Both pages render `ADDRESS_FIELDS` in order and compose through `formatAddress`. A field added
 * to one form and not the other is now impossible to express, because neither form holds its own
 * field list.
 *
 * WHAT THIS MODULE IS NOT
 * -----------------------
 * It computes no money, performs no validation the server does not repeat, and is not the
 * authority on anything. `addressComplete` mirrors the four `_RULES` required fields so a form
 * can skip an obviously-incomplete payload rather than round-trip for a 400; the server
 * re-validates every one of them and answers with the field that failed. A rule relaxed here
 * cannot loosen storage.
 *
 * `src/components/AddressFields.tsx` is a different thing and stays as it is: a rendered
 * India-only CUSTOMER checkout form over five collected fields. This module is the field
 * contract and the composition, shared by the two STAFF forms, which are international (storage
 * became international in FEAT-003 and payability moved to `payment_address`, asked at pay time).
 */

/** The eight `contact_address._RULES` keys, and nothing else. */
export type AddressFieldKey =
  | 'addressLine1'
  | 'addressLine2'
  | 'locality'
  | 'city'
  | 'state'
  | 'postalCode'
  | 'country'
  | 'countryCode';

export interface AddressFieldSpec {
  key: AddressFieldKey;
  /** The visible caption. Both forms use it verbatim, so one rename moves both. */
  label: string;
  /** Mirrors the `required` column of `contact_address._RULES`. */
  required: boolean;
  /** Mirrors the `limit` column of `contact_address._RULES`. */
  maxLength: number;
  placeholder: string;
}

/**
 * Field order, captions and limits, mirrored from `contact_address._RULES`.
 *
 * The order is the reading order of an address, which is also the order `formatAddress` composes
 * in - so the preview a staff member sees is the fields they just typed, top to bottom.
 */
export const ADDRESS_FIELDS: readonly AddressFieldSpec[] = [
  { key: 'addressLine1', label: 'Address line 1', required: true, maxLength: 200, placeholder: 'Flat or house, building, street' },
  { key: 'addressLine2', label: 'Address line 2 (House / Unit)', required: false, maxLength: 200, placeholder: 'House or unit number, floor, tower' },
  { key: 'locality', label: 'Landmark / Locality', required: false, maxLength: 100, placeholder: 'Nearby landmark or area' },
  { key: 'city', label: 'City', required: true, maxLength: 100, placeholder: 'e.g. Mumbai' },
  { key: 'state', label: 'State', required: true, maxLength: 100, placeholder: 'e.g. Maharashtra' },
  { key: 'postalCode', label: 'Postal Code', required: true, maxLength: 100, placeholder: 'e.g. 400051' },
  { key: 'country', label: 'Country', required: false, maxLength: 100, placeholder: 'India' },
  { key: 'countryCode', label: 'Country code', required: false, maxLength: 2, placeholder: 'IN' },
];

/** What the eight inputs hold. Always strings, because an input value is always a string. */
export type AddressFormFields = Record<AddressFieldKey, string>;

/** `identity.address.DEFAULT_COUNTRY` / `DEFAULT_COUNTRY_CODE`, mirrored. */
export const DEFAULT_ADDRESS_COUNTRY = 'India';
export const DEFAULT_ADDRESS_COUNTRY_CODE = 'IN';

export const EMPTY_ADDRESS_FIELDS: AddressFormFields = {
  addressLine1: '',
  addressLine2: '',
  locality: '',
  city: '',
  state: '',
  postalCode: '',
  country: DEFAULT_ADDRESS_COUNTRY,
  countryCode: DEFAULT_ADDRESS_COUNTRY_CODE,
};

const trimmed = ( fields: Partial<AddressFormFields>, key: AddressFieldKey ): string =>
  String( fields[ key ] ?? '' ).trim();

/**
 * The one human-readable address string, composed from the eight fields in `ADDRESS_FIELDS`
 * order. Empty fields are skipped, so a partial address reads as a partial address rather than
 * as a row of commas.
 *
 * `state` and `postalCode` join with a SPACE rather than a comma, because "Maharashtra 400051"
 * is how a postal address is written and "Maharashtra, 400051" is how a spreadsheet export looks.
 *
 * `countryCode` is deliberately NOT printed. It is a real stored field - `payment_address`
 * branches on it to decide whether India's place-of-supply rules apply - but printing it beside
 * `country` renders "India, IN", which is one fact twice. Nothing downstream parses this string
 * back into fields; the structured `address` object is what the server validates and stores.
 */
export function formatAddress ( fields: Partial<AddressFormFields> ): string {
  // Default country fields alone are not an address. Preserve the saved legacy fallback.
  if ( !ADDRESS_FIELDS.some( spec =>
    spec.key !== 'country' && spec.key !== 'countryCode' && trimmed( fields, spec.key ) ) ) return '';
  const statePin = [ trimmed( fields, 'state' ), trimmed( fields, 'postalCode' ) ]
    .filter( Boolean )
    .join( ' ' );
  return [
    trimmed( fields, 'addressLine1' ),
    trimmed( fields, 'addressLine2' ),
    trimmed( fields, 'locality' ),
    trimmed( fields, 'city' ),
    statePin,
    trimmed( fields, 'country' ),
  ].filter( Boolean ).join( ', ' );
}

/**
 * True when the four `_RULES` required fields are present. A MIRROR of the server rule, not the
 * rule: the server re-validates and names the failing field, and this only decides whether a
 * form sends the structured `address` object at all.
 */
export function addressComplete ( fields: Partial<AddressFormFields> ): boolean {
  return ADDRESS_FIELDS
    .filter( spec => spec.required )
    .every( spec => trimmed( fields, spec.key ).length > 0 );
}

/**
 * The structured `address` object to post, or `undefined` when the required fields are not all
 * present.
 *
 * `undefined` rather than a partial object is the contract: the server refuses an incomplete
 * address with `400 FIELD_REQUIRED` and writes nothing, so sending one would fail the whole
 * contact save over an address a staff member had not finished typing. Optional fields that are
 * empty are omitted rather than sent as `''`, because `contact_address._text` treats absent and
 * empty identically and an omitted key keeps the payload honest about what was collected.
 */
export function addressPayload (
  fields: Partial<AddressFormFields>,
): Partial<AddressFormFields> | undefined {
  if ( !addressComplete( fields ) ) return undefined;
  const out: Partial<AddressFormFields> = {};
  for ( const spec of ADDRESS_FIELDS )
  {
    const value = trimmed( fields, spec.key );
    if ( value || spec.required ) out[ spec.key ] = value;
  }
  return out;
}
