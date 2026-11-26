/** Shared local, bounded, multilingual public website text search. */
export const normalizeNavigationText = ( value: string ): string =>
  value.normalize( 'NFKC' ).toLocaleLowerCase().replace( /[^\p{L}\p{N}\p{M}]+/gu, ' ' ).trim();
const words = ( value: string ) => normalizeNavigationText( value ).split( ' ' ).filter( Boolean );
// Ignore conversational scaffolding in longer queries, but never discard an entire query or an identifier.
const QUERY_FILLERS = new Set( ['how','what','where','when','which','who','why','can','could','would','should','do','does','did','is','are','was','were','the','a','an','i','we','you','my','our','your','me','us','to','for','of','in','on','with','please','tell','show','find','get','about'] );
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
  const queryWords = words( term );
  const focused = queryWords.length > 1 ? queryWords.filter( word => !QUERY_FILLERS.has( word ) ) : queryWords;
  const tokens = Array.from( new Set( focused.length ? focused : queryWords ) ).slice( 0, 12 );
  const focusTerm = tokens.join( ' ' );
  // Large content indexes reuse many words. Cache each fuzzy comparison only
  // for this query; no unbounded global cache or repeated distance matrices.
  const fuzzy = new Map<string, boolean>();
  const near = ( token: string, word: string ) => {
    if ( !/^[a-z]{4,32}$/.test( token ) || !/^[a-z]{3,32}$/.test( word ) || Math.abs( token.length - word.length ) > ( token.length >= 7 ? 2 : 1 ) ) return false;
    const key = token + ':' + word;
    const cached = fuzzy.get( key );
    if ( cached !== undefined ) return cached;
    const match = closeWord( token, word );
    // Cap the cache even for very large public indexes.
    if ( fuzzy.size < 20000 ) fuzzy.set( key, match );
    return match;
  };
  const hits: { entry: T; score: number; index: number }[] = [];
  entries.forEach( ( entry, index ) => {
    const label = normalizeNavigationText( entry.label );
    const haystack = normalizeNavigationText( entry.searchText + ' ' + localized( entry ) );
    const candidates = Array.from( new Set( words( haystack ) ) );
    const exact = new Set( candidates );
    const titleWords = new Set( words( label ) );
    let score = label === term ? 1000 : label === focusTerm ? 850 : label.startsWith( term ) ? 600 : label.includes( focusTerm ) ? 400 : haystack.includes( focusTerm ) ? 200 : 0;
    for ( const token of tokens ) {
      if ( exact.has( token ) ) score += titleWords.has( token ) ? 80 : 40;
      else if ( candidates.some( word => word.startsWith( token ) ) ) score += 20;
      else if ( candidates.some( word => near( token, word ) ) ) score += 5;
      else return;
    }
    hits.push( { entry, score, index } );
  } );
  return hits.sort( ( a, b ) => b.score - a.score || a.index - b.index ).map( hit => hit.entry );
}
/** Curated topical synonyms and Hindi/Bengali terms. Expand only documents
 * that already contain the corresponding English topic, never invent content.
 * This is local text discovery, not an AI answer generator or translation API. */
const CONTENT_TOPICS: readonly { triggers: readonly string[]; aliases: string }[] = [
  { triggers: ['refund', 'refunds', 'reimbursement'], aliases: 'refund refunds money back reimbursement repay refund status धन वापसी रिफंड টাকা ফেরত রিফান্ড' },
  { triggers: ['privacy', 'personal data', 'personal information'], aliases: 'privacy personal data गोपनीयता निजी जानकारी গোপনীয়তা ব্যক্তিগত তথ্য' },
  { triggers: ['payment', 'payments', 'billing'], aliases: 'payment billing भुगतान पेमेंट পেমেন্ট অর্থপ্রদান' },
  { triggers: ['invoice', 'invoices', 'invoicing'], aliases: 'invoice bill billing चालान इनवॉइस बिल ইনভয়েস চালান বিল' },
  { triggers: ['cancellation', 'cancel', 'cancellations'], aliases: 'cancellation cancel रद्द निरस्तीकरण বাতিল' },
  { triggers: ['delivery', 'shipping', 'shipment', 'shipments'], aliases: 'delivery shipping shipment डिलीवरी शिपमेंट पार्सल ডেলিভারি শিপমেন্ট পার্সেল' },
  { triggers: ['consent', 'permission', 'permissions'], aliases: 'consent permission सहमति अनुमति সম্মতি অনুমতি' },
  { triggers: ['deletion', 'delete', 'erasure'], aliases: 'delete deletion erasure remove removal erase हटाना मिटाना মুছে ফেলা' },
  { triggers: ['grievance', 'complaint', 'complaints', 'grievances'], aliases: 'complaint grievance dispute escalation शिकायत शिकायतकर्ता অভিযোগ' },
  { triggers: ['return', 'returns', 'replacement', 'replacements'], aliases: 'return returns replacement exchange defective damaged faulty वापस बदलना ফেরত বদল' },
  { triggers: ['retention', 'retain', 'retained'], aliases: 'retention retain stored storage keep how long संग्रह সংরক্ষণ' },
  { triggers: ['account', 'accounts'], aliases: 'account खाता अकाउंट অ্যাকাউন্ট হিসাব' },
  { triggers: ['cookies', 'cookie'], aliases: 'cookie cookies कुकी কুকি' },
  { triggers: ['liability', 'responsibility'], aliases: 'liability responsibility दायित्व जिम्मेदारी দায় দায়িত্ব' },
  { triggers: ['visa', 'visas'], aliases: 'visa वीज़ा वीजा ভিসা' },
  { triggers: ['travel', 'trip', 'journey'], aliases: 'travel trip journey यात्रा सफर ভ্রমণ যাত্রা' },
  { triggers: ['weather', 'climate', 'air quality'], aliases: 'weather climate air quality मौसम जलवायु আবহাওয়া জলবায়ু' },
  { triggers: ['astrology', 'panchang', 'panchanga'], aliases: 'astrology panchang पंचांग ज्योतिष পঞ্জিকা জ্যোতিষ' },
  { triggers: ['career', 'resume', 'cv'], aliases: 'career resume cv रिज्यूमे करियर জীবনবৃত্তান্ত সিভি' },
  { triggers: ['documents', 'document', 'paperwork'], aliases: 'documents paperwork दस्तावेज़ कागजात নথি কাগজপত্র' },
  { triggers: ['contact', 'support', 'help'], aliases: 'contact support help संपर्क सहायता যোগাযোগ সহায়তা' },
  { triggers: ['decision', 'decisions', 'choice', 'choices'], aliases: 'decision choice deciding choices निर्णय फैसला निर्णय लेना সিদ্ধান্ত পছন্দ' },
  { triggers: ['commitment', 'commitments', 'promise', 'promises'], aliases: 'commitment commitments promise promises वादा प्रतिबद्धता প্রতিশ্রুতি অঙ্গীকার' },
  { triggers: ['integrity', 'honesty'], aliases: 'integrity honesty ईमानदारी सत्यनिष्ठा সততা' },
  { triggers: ['communication', 'conversation', 'conversations'], aliases: 'communication conversation संवाद बातचीत যোগাযোগ কথোপকথন' },
  { triggers: ['leadership', 'leader', 'leaders'], aliases: 'leadership leader नेतृत्व নেতা নেতৃত্ব প্রদান' },
  { triggers: ['gastronomy', 'cooking', 'cuisine', 'recipe', 'recipes'], aliases: 'gastronomy cooking cuisine recipe पाक कला व्यंजन खाना पकाना রান্না রেসিপি' },
];
export function contentSearchText ( fields: readonly string[] ): string {
  const text = normalizeNavigationText( fields.join( ' ' ) );
  const padded = ' ' + text + ' ';
  const aliases = CONTENT_TOPICS.filter( topic => topic.triggers.some( trigger => padded.includes( ' ' + trigger + ' ' ) ) ).map( topic => topic.aliases );
  return [ text, ...aliases ].join( ' ' );
}
export function rankPublicContent<T> (
  entries: readonly T[], query: string, label: ( entry: T ) => string, fields: ( entry: T ) => readonly string[],
): T[] {
  if ( !query.trim() ) return [...entries];
  return rankNavigation( entries.map( entry => ( {
    entry, label: label( entry ), searchText: contentSearchText( [ label( entry ), ...fields( entry ) ] ),
  } ) ), query ).map( item => item.entry );
}
export function rankBlogContent<T extends { title: string; excerpt?: string | null; category?: string | null; tags?: readonly string[] | null }> (
  entries: readonly T[], query: string,
): T[] {
  return rankPublicContent( entries, query, post => post.title, post => [ post.excerpt || '', post.category || '', ...( post.tags || [] ) ] );
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
  Android: [ 'Android apps on Google Play', 'ऐप एंड्रॉइड অ্যাপ অ্যান্ড্রয়েড' ],
  iOS: [ '', 'आईओएस ऐप আইওএস অ্যাপ' ],
  ChatGPT: [ 'Open ChatGPT', 'एआई এআই' ],
  Claude: [ 'Open Claude', 'एआई এআই' ],
  Gemini: [ 'Open Gemini', 'एआई এআই' ],
  'Contact us': [ 'Contact and support', 'संपर्क सहायता যোগাযোগ সহায়তা' ],
  Terms: [ 'Terms of service refund cancellation returns consumer rights liability store credit', 'नियम शर्तें শর্তাবলী' ],
  Privacy: [ 'Privacy policy personal data consent deletion retention grievance', 'गोपनीयता निजता গোপনীয়তা' ],
};
