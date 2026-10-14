/**
 * THE INDIAN STATES AND UNION TERRITORIES THE DELIVERY FORM OFFERS - display names only.
 *
 * WHY A SECOND COPY OF A PYTHON TABLE EXISTS
 * ------------------------------------------
 * The address form must not let a customer type a state the server cannot map. A free-text state
 * is the unmapped-state failure class: the save succeeds, and then pay time refuses with
 * UNMAPPABLE_STATE on a value the customer has no way to correct, because nothing tells them
 * which spelling the server wanted. A select over this table removes that class at source - the
 * only states on offer are the ones the tax table resolves.
 *
 * THESE ARE DISPLAY NAMES, NEVER ISO CODES. The server resolves a NAME through
 * lambda_utils.ecommerce.india_address.india_subdivision, and the ISO 3166-2 code plus the GST
 * state code it returns are a server-side tax concern. A browser that posted IN-KA would be
 * relying on a lookup branch that exists for legacy rows, not for this form.
 *
 * THE NAMES MUST BE THE EXACT TITLE-CASE OF THE 36 india_address.INDIA_SUBDIVISIONS KEYS.
 * Specifically including "Dadra and Nagar Haveli and Daman and Diu" (one merged union territory
 * since 2020, not two) and "Delhi" - NOT "NCT of Delhi", which lives in the separate
 * INDIA_ALIASES table. That table is a lookup convenience for spellings seen in real data and in
 * Google Places output; it is not part of the key set, so offering an alias here would be
 * offering a name that is not canonical.
 *
 * PINNED BY tests/test_india_subdivision_drift.py, BECAUSE THIS TABLE DECIDES THE TAX.
 * The subdivision is the place of supply, which decides the CGST/SGST versus IGST split. A state
 * this file offers but the Python table cannot map is a dead-end loop for the customer and a
 * wrong tax split if it ever got through, so the two sides are compared in CI. The server
 * lowercases before lookup, so the comparison is case-insensitive and only the SET of names is
 * pinned - not their order, which is alphabetical here purely so the select is scannable.
 *
 * ONE CONSTRAINT ON EDITING THIS FILE: the drift test collects every single-quoted literal in the
 * whole source, so no other single-quoted string may appear anywhere in it, comments included.
 * Use double quotes in prose, as above.
 */
export const INDIA_SUBDIVISION_NAMES: readonly string[] = [
  'Andaman and Nicobar Islands',
  'Andhra Pradesh',
  'Arunachal Pradesh',
  'Assam',
  'Bihar',
  'Chandigarh',
  'Chhattisgarh',
  'Dadra and Nagar Haveli and Daman and Diu',
  'Delhi',
  'Goa',
  'Gujarat',
  'Haryana',
  'Himachal Pradesh',
  'Jammu and Kashmir',
  'Jharkhand',
  'Karnataka',
  'Kerala',
  'Ladakh',
  'Lakshadweep',
  'Madhya Pradesh',
  'Maharashtra',
  'Manipur',
  'Meghalaya',
  'Mizoram',
  'Nagaland',
  'Odisha',
  'Puducherry',
  'Punjab',
  'Rajasthan',
  'Sikkim',
  'Tamil Nadu',
  'Telangana',
  'Tripura',
  'Uttar Pradesh',
  'Uttarakhand',
  'West Bengal',
] as const;

export default INDIA_SUBDIVISION_NAMES;
