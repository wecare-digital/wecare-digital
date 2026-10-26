/**
 * ISO country choices shared by the browser address editors.
 *
 * Keep this data byte-for-byte aligned with
 * amplify/functions/messaging/whatsapp-business-api/flows/country_options.py.
 * F001 Subscribe is the visible address contract; countryCode is derived system data,
 * never a separate customer-facing address field.
 */
export interface CountryOption {
  code: string;
  name: string;
}

const COUNTRY_DATA = `AF:Afghanistan|AL:Albania|DZ:Algeria|AD:Andorra|AO:Angola|AG:Antigua and Barbuda|AR:Argentina|AM:Armenia|AU:Australia|AT:Austria|AZ:Azerbaijan|BS:Bahamas|BH:Bahrain|BD:Bangladesh|BB:Barbados|BY:Belarus|BE:Belgium|BZ:Belize|BJ:Benin|BT:Bhutan|BO:Bolivia|BA:Bosnia and Herzegovina|BW:Botswana|BR:Brazil|BN:Brunei|BG:Bulgaria|BF:Burkina Faso|BI:Burundi|CV:Cabo Verde|KH:Cambodia|CM:Cameroon|CA:Canada|CF:Central African Republic|TD:Chad|CL:Chile|CN:China|CO:Colombia|KM:Comoros|CG:Congo|CR:Costa Rica|HR:Croatia|CU:Cuba|CY:Cyprus|CZ:Czechia|CI:Côte d'Ivoire|CD:DR Congo|DK:Denmark|DJ:Djibouti|DM:Dominica|DO:Dominican Republic|EC:Ecuador|EG:Egypt|SV:El Salvador|GQ:Equatorial Guinea|ER:Eritrea|EE:Estonia|SZ:Eswatini|ET:Ethiopia|FJ:Fiji|FI:Finland|FR:France|GA:Gabon|GM:Gambia|GE:Georgia|DE:Germany|GH:Ghana|GR:Greece|GD:Grenada|GT:Guatemala|GN:Guinea|GW:Guinea-Bissau|GY:Guyana|HT:Haiti|HN:Honduras|HU:Hungary|IS:Iceland|IN:India|ID:Indonesia|IR:Iran|IQ:Iraq|IE:Ireland|IL:Israel|IT:Italy|JM:Jamaica|JP:Japan|JO:Jordan|KZ:Kazakhstan|KE:Kenya|KI:Kiribati|KW:Kuwait|KG:Kyrgyzstan|LA:Laos|LV:Latvia|LB:Lebanon|LS:Lesotho|LR:Liberia|LY:Libya|LI:Liechtenstein|LT:Lithuania|LU:Luxembourg|MG:Madagascar|MW:Malawi|MY:Malaysia|MV:Maldives|ML:Mali|MT:Malta|MH:Marshall Islands|MR:Mauritania|MU:Mauritius|MX:Mexico|FM:Micronesia|MD:Moldova|MC:Monaco|MN:Mongolia|ME:Montenegro|MA:Morocco|MZ:Mozambique|MM:Myanmar|NA:Namibia|NR:Nauru|NP:Nepal|NL:Netherlands|NZ:New Zealand|NI:Nicaragua|NE:Niger|NG:Nigeria|KP:North Korea|MK:North Macedonia|NO:Norway|OM:Oman|PK:Pakistan|PW:Palau|PS:Palestine|PA:Panama|PG:Papua New Guinea|PY:Paraguay|PE:Peru|PH:Philippines|PL:Poland|PT:Portugal|QA:Qatar|RO:Romania|RU:Russia|RW:Rwanda|KN:Saint Kitts and Nevis|LC:Saint Lucia|WS:Samoa|SM:San Marino|ST:Sao Tome and Principe|SA:Saudi Arabia|SN:Senegal|RS:Serbia|SC:Seychelles|SL:Sierra Leone|SG:Singapore|SK:Slovakia|SI:Slovenia|SB:Solomon Islands|SO:Somalia|ZA:South Africa|KR:South Korea|SS:South Sudan|ES:Spain|LK:Sri Lanka|VC:St Vincent & Grenadines|SD:Sudan|SR:Suriname|SE:Sweden|CH:Switzerland|SY:Syria|TJ:Tajikistan|TZ:Tanzania|TH:Thailand|TL:Timor-Leste|TG:Togo|TO:Tonga|TT:Trinidad and Tobago|TN:Tunisia|TM:Turkmenistan|TV:Tuvalu|TR:Türkiye|UG:Uganda|UA:Ukraine|AE:United Arab Emirates|GB:United Kingdom|US:United States|UY:Uruguay|UZ:Uzbekistan|VU:Vanuatu|VA:Vatican City|VE:Venezuela|VN:Vietnam|YE:Yemen|ZM:Zambia|ZW:Zimbabwe`;

const PAIRS: readonly CountryOption[] = COUNTRY_DATA.split('|').map( item => {
  const split = item.indexOf(':');
  return { code: item.slice( 0, split ), name: item.slice( split + 1 ) };
} );

const INDIA = PAIRS.find( item => item.code === 'IN' ) as CountryOption;

/** India first, matching the published F001 dropdown; the remaining ISO choices follow. */
export const COUNTRY_OPTIONS: readonly CountryOption[] = [
  INDIA,
  ...PAIRS.filter( item => item.code !== 'IN' ),
];

const CODE_BY_NAME = new Map( PAIRS.map( item => [ item.name, item.code ] as const ) );
const NAME_BY_CODE = new Map( PAIRS.map( item => [ item.code, item.name ] as const ) );

export function countryCodeForName ( name: string ): string {
  return CODE_BY_NAME.get( String( name || '' ).trim() ) || '';
}

export function countryNameForCode ( code: string ): string {
  return NAME_BY_CODE.get( String( code || '' ).trim().toUpperCase() ) || '';
}
