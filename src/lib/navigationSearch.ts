/** Local, bounded, multilingual public-navigation search. */
export const normalizeNavigationText = ( value: string ): string =>
  value.normalize( 'NFKC' ).toLocaleLowerCase().replace( /[^\p{L}\p{N}\p{M}]+/gu, ' ' ).trim();
const words = ( value: string ) => normalizeNavigationText( value ).split( ' ' ).filter( Boolean );
function closeWord ( a: string, b: string ): boolean {
  if ( !/^[a-z]{4,32}$/.test( a ) || !/^[a-z]{3,32}$/.test( b ) ) return false;
  const limit = a.length >= 7 ? 2 : 1;
  if ( Math.abs( a.length - b.length ) > limit ) return false;
  const d = Array.from( { length: a.length + 1 }, () => Array<number>( b.length + 1 ).fill( 0 ) );
  for ( let i = 0; i <= a.length; i++ ) d[i][0] = i;
  for ( let j = 0; j <= b.length; j++ ) d[0][j] = j;
  for ( let i = 1; i <= a.length; i++ ) for ( let j = 1; j <= b.length; j++ ) {
    d[i][j] = Math.min( d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + ( a[i - 1] === b[j - 1] ? 0 : 1 ) );
    if ( i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1] ) d[i][j] = Math.min( d[i][j], d[i - 2][j - 2] + 1 );
  }
  return d[a.length][b.length] <= limit;
}
export function rankNavigation<T extends { label: string; searchText: string }> (
  entries: readonly T[], query: string, localized: ( entry: T ) => string = () => '',
): T[] {
  const term = normalizeNavigationText( query.slice( 0, 120 ) );
  if ( !term ) return [];
  const tokens = words( term ).slice( 0, 12 );
  const hits: { entry: T; score: number; index: number }[] = [];
  entries.forEach( ( entry, index ) => {
    const label = normalizeNavigationText( entry.label );
    const haystack = normalizeNavigationText( entry.searchText + ' ' + localized( entry ) );
    const candidates = words( haystack );
    let score = label === term ? 1000 : label.startsWith( term ) ? 600 : label.includes( term ) ? 400 : haystack.includes( term ) ? 200 : 0;
    for ( const token of tokens ) {
      if ( candidates.includes( token ) ) score += 40;
      else if ( candidates.some( word => word.startsWith( token ) ) ) score += 20;
      else if ( candidates.some( word => closeWord( token, word ) ) ) score += 5;
      else return;
    }
    hits.push( { entry, score, index } );
  } );
  return hits.sort( ( a, b ) => b.score - a.score || a.index - b.index ).map( hit => hit.entry );
}
export const NAV_DISCOVERY: Readonly<Record<string, readonly [string, string]>> = {
  Home: [ 'WECARE.DIGITAL home', 'होम मुख्य पृष्ठ হোম প্রধান পাতা' ],
  Shop: [ 'Browse products and services', 'दुकान खरीदारी দোকান কেনাকাটা' ],
  'Relay OS': [ 'Customer messaging across channels', 'संदेश मैसेजिंग মেসেজ বার্তা' ],
  'Nano Climate': [ 'Weather and air quality', 'मौसम हवा वायु प्रदूषण আবহাওয়া বায়ু দূষণ' ],
  'Green Ledger': [ 'Environmental records', 'पर्यावरण लेखा পরিবেশ হিসাব' ],
  Visa: [ 'Visa guidance and travel documents', 'वीज़ा वीजा ভিসা' ],
  Trip: [ 'Travel planning and journeys', 'यात्रा सफर घूमना ভ্রমণ যাত্রা' ],
  Activities: [ 'Tours and experiences', 'गतिविधियाँ भ्रमण কার্যকলাপ ট্যুর' ],
  Rail: [ 'Railway travel', 'रेल ट्रेन रेलवे রেল ট্রেন' ],
  Cruise: [ 'Cruise journeys', 'क्रूज़ जहाज़ क्रूज ক্রুজ জাহাজ' ],
  'Arogya Yatra': [ 'Medical travel coordination', 'चिकित्सा यात्रा চিকিৎসা ভ্রমণ' ],
  'Expo Week': [ 'Exhibitions and events', 'प्रदर्शनी মেলা প্রদর্শনী' ],
  Drafting: [ 'Document drafting', 'दस्तावेज़ मसौदा দলিল খসড়া' ],
  Registration: [ 'Document registration guidance', 'पंजीकरण रजिस्ट्रेशन নিবন্ধন রেজিস্ট্রেশন' ],
  'Legal Reference': [ 'Legal information', 'कानूनी जानकारी আইন আইনি তথ্য' ],
  'Guided Resolution': [ 'Guidance on resolving a matter', 'समाधान सहायता সমাধান' ],
  'Case Submission': [ 'Prepare a case submission', 'मामला दाखिल মামলা জমা' ],
  Paperwork: [ 'Organise paperwork', 'कागजात कागज़ात কাগজপত্র' ],
  Vidhi: [ 'Puja guidance and ritual steps', 'पूजा विधि पूजा पद्धति পূজা পুজো বিধি' ],
  Samagri: [ 'DIY puja kits and essentials', 'पूजा सामग्री पूजा सामान পূজার সামগ্রী পুজোর উপকরণ' ],
  Panchang: [ 'Astrology, Vastu and ritual calendar guidance', 'पंचांग ज्योतिष वास्तु तिथि পঞ্জিকা পঞ্চাঙ্গ জ্যোতিষ বাস্তু তিথি' ],
  Anew: [ 'Start a conversation', 'नई शुरुआत बातचीत নতুন শুরু কথা' ],
  Kaushal: [ 'Skills and learning', 'कौशल सीखना দক্ষতা শিক্ষা' ],
  Prastuti: [ 'CV, professional profile and pitch deck', 'रिज्यूमे बायोडाटा सीवी জীবনবৃত্তান্ত সিভি' ],
  Parichay: [ 'Planned digital bio and profile tool', 'परिचय बायो प्रोफाइल পরিচয় বায়ো প্রোফাইল' ],
  Khata: [ 'Planned invoice creation tool', 'खाता बिल चालान इनवॉइस হিসাব বিল চালান ইনভয়েস' ],
  Orders: [ 'View your order history', 'ऑर्डर आदेश অর্ডার' ],
  'Submit Request': [ 'Raise an order-related request', 'अनुरोध आवेदन অনুরোধ আবেদন' ],
  'Request Amendment': [ 'Change a request', 'संशोधन बदलाव সংশোধন পরিবর্তন' ],
  'Drop Docs': [ 'Upload documents', 'दस्तावेज अपलोड নথি আপলোড' ],
  Vault: [ 'Secure file access', 'सुरक्षित फाइल সুরক্ষিত ফাইল' ],
  Track: [ 'Track a shipment', 'ट्रैक पार्सल ट्रैकिंग ট্র্যাক পার্সেল' ],
  'Pickup Request': [ 'Request collection or pickup', 'पिकअप संग्रह পিকআপ সংগ্রহ' ],
  'Leave Review': [ 'Share feedback', 'समीक्षा प्रतिक्रिया পর্যালোচনা মতামত' ],
  Subscribe: [ 'Update your profile', 'सदस्यता প্রোফাইল সাবস্ক্রাইব' ],
  Referral: [ 'Refer and earn', 'रेफरल রেফারেল' ],
  Merchandise: [ 'Partner merchandise', 'सामान পণ্য' ],
  Kiosk: [ 'Partner kiosk', 'कियोस्क কিয়স্ক' ],
  Perks: [ 'Benefits on WhatsApp', 'लाभ সুবিধা' ],
  'Google Play': [ 'Android apps', 'ऐप एंड्रॉइड অ্যাপ অ্যান্ড্রয়েড' ],
  ChatGPT: [ 'Open ChatGPT', 'एआई এআই' ],
  Claude: [ 'Open Claude', 'एआई এআই' ],
  Gemini: [ 'Open Gemini', 'एआई এআই' ],
  'Contact us': [ 'Contact and support', 'संपर्क सहायता যোগাযোগ সহায়তা' ],
  Terms: [ 'Terms of service', 'नियम शर्तें শর্তাবলী' ],
  Privacy: [ 'Privacy policy', 'गोपनीयता निजता গোপনীয়তা' ],
};
