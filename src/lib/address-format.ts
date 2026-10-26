import { countryCodeForName, countryNameForCode } from '../config/countryOptions';

/**
 * THE ONE ADDRESS FORMAT, as the browser sees it.
 *
 * WHY THIS MODULE EXISTS AT ALL
 * -----------------------------
 * "One address format for the website, WhatsApp and the order" was already true on the server:
 * `lambda_utils/ecommerce/contact_address.py` owns `_RULES` - eight fields, four required -
 * `normalize_for_storage` validates and stores them at `checkoutDeliveryAddress`, and
 * `payment_address` projects that one stored shape onto the order payload and onto Meta's
 * beneficiary block (`for_meta_beneficiary`). There was never a second server format.
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

/** The eight stored `contact_address._RULES` keys, including derived `countryCode`. */
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
  /** Customer-visible F001 field; countryCode is derived and therefore excluded. */
  key: Exclude<AddressFieldKey, 'countryCode'>;
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
  { key: 'addressLine1', label: 'Street address', required: true, maxLength: 200, placeholder: 'Street address' },
  { key: 'addressLine2', label: 'Apartment / suite / unit', required: false, maxLength: 200, placeholder: 'Optional' },
  { key: 'locality', label: 'Landmark / neighborhood', required: false, maxLength: 100, placeholder: 'Optional' },
  { key: 'city', label: 'City', required: true, maxLength: 100, placeholder: 'e.g. Mumbai' },
  { key: 'state', label: 'State / region', required: true, maxLength: 100, placeholder: 'State / region' },
  { key: 'postalCode', label: 'Postal code', required: true, maxLength: 100, placeholder: 'Postal code' },
  { key: 'country', label: 'Country', required: true, maxLength: 100, placeholder: 'India' },
];

/** The seven visible F001 fields plus derived `countryCode`, all held as strings. */
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
    spec.key !== 'country' && trimmed( fields, spec.key ) ) ) return '';
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
  if ( !ADDRESS_FIELDS
    .filter( spec => spec.required )
    .every( spec => trimmed( fields, spec.key ).length > 0 ) ) return false;
  const country = trimmed( fields, 'country' );
  const code = trimmed( fields, 'countryCode' ).toUpperCase();
  return Boolean( countryCodeForName( country ) || countryNameForCode( code ) );
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
  const country = trimmed( fields, 'country' );
  const suppliedCode = trimmed( fields, 'countryCode' ).toUpperCase();
  const countryCode = countryCodeForName( country ) || suppliedCode;
  const canonicalCountry = countryNameForCode( countryCode ) || country;
  const out: Partial<AddressFormFields> = {};
  for ( const spec of ADDRESS_FIELDS )
  {
    const value = spec.key === 'country' ? canonicalCountry : trimmed( fields, spec.key );
    if ( value || spec.required ) out[ spec.key ] = value;
  }
  out.countryCode = countryCode;
  return out;
}


/**
 * Minimal structural shape needed to resolve a contact's delivery address.
 * This module intentionally does not import api/client.ts.
 */
export interface ContactAddressSource {
  checkoutDeliveryAddress?: Partial<AddressFormFields> & { fullAddress?: string };
  shippingAddressJson?: string;
  shippingAddress?: string;
  addressLine1?: string;
  addressLine2?: string;
  landmark?: string;
  city?: string;
  state?: string;
  postalCode?: string;
  country?: string;
  houseNumber?: string;
  buildingName?: string;
  towerNumber?: string;
  floorNumber?: string;
}

/**
 * Resolve the ONE browser address field-set from a contact.
 *
 * Priority:
 * 1. checkoutDeliveryAddress (server-normalised source of truth)
 * 2. Meta structured shipping JSON
 * 3. historical flat CRM columns
 */
export function addressFieldsFromContact ( contact: ContactAddressSource ): AddressFormFields {
  const canonical = contact.checkoutDeliveryAddress || {};
  let meta: Record<string, unknown> = {};
  if ( contact.shippingAddressJson )
  {
    try
    {
      const parsed = JSON.parse( contact.shippingAddressJson );
      if ( parsed && typeof parsed === 'object' && !Array.isArray( parsed ) ) meta = parsed;
    } catch { /* malformed legacy JSON is ignored */ }
  }
  const line2Legacy = [
    contact.houseNumber, contact.buildingName, contact.towerNumber, contact.floorNumber,
    meta.house_number, meta.building_name, meta.tower_number, meta.floor_number,
  ].map( v => String( v ?? '' ).trim() ).filter( ( v, i, all ) => v && all.indexOf( v ) === i ).join( ', ' );

  const rawCode = String( canonical.countryCode ?? meta.country_code ?? '' ).trim().toUpperCase();
  const rawCountry = String( canonical.country ?? contact.country ?? '' ).trim();
  const country = countryNameForCode( rawCode ) || rawCountry || DEFAULT_ADDRESS_COUNTRY;
  const countryCode = countryCodeForName( country ) || rawCode || DEFAULT_ADDRESS_COUNTRY_CODE;

  return {
    addressLine1: String( canonical.addressLine1 ?? meta.address ?? contact.addressLine1 ?? '' ).trim(),
    addressLine2: String( canonical.addressLine2 ?? contact.addressLine2 ?? line2Legacy ?? '' ).trim(),
    locality: String( canonical.locality ?? meta.landmark_area ?? contact.landmark ?? '' ).trim(),
    city: String( canonical.city ?? meta.city ?? contact.city ?? '' ).trim(),
    state: String( canonical.state ?? meta.state ?? contact.state ?? '' ).trim(),
    postalCode: String( canonical.postalCode ?? meta.in_pin_code ?? meta.postal_code ?? contact.postalCode ?? '' ).trim(),
    country,
    countryCode,
  };
}

/** Canonical one-line contact address, with legacy fallbacks only for pre-convergence rows. */
export function contactDeliveryAddress ( contact: ContactAddressSource ): string {
  return formatAddress( addressFieldsFromContact( contact ) ) || String( contact.shippingAddress || '' ).trim();
}
