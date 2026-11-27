/**
 * Short, catalogue-specific cues. These describe the product surface, not offers or
 * entitlements. Keep copy in sync with the catalogue and product policy descriptions.
 */
const LABELS: Readonly<Partial<Record<string, readonly [string, string, string]>>> = {
  'grahak-os': ['Channels', 'Workflow', 'Consultation'],
  'sehat': ['Appointments', 'Booking', 'Coordination'],
  'elsewhere-visa': ['Preparation', 'Documents', 'Tracking'],
  'elsewhere-trip': ['Planning', 'Itinerary', 'Travel'],
  'expo-week': ['Destinations', 'Discovery', 'Expo access'],
  'dastavez-drafting': ['Drafts', 'Documents', 'Preparation'],
  'dastavez-registration': ['Paperwork', 'Filing', 'Requirements'],
  'dastavez-legal-reference': ['Research', 'References', 'Context'],
  'guided-resolution': ['Preparation', 'Guidance', 'Coordination'],
  'file-assist': ['Case materials', 'Organisation', 'Submission'],
  'paperwork': ['Documents', 'Preparation', 'Format'],
  'anew': ['Reflection', 'Perspective', 'Reading'],
  'hunar-kaushal': ['Skills', 'Learning', 'Practice'],
  'hunar-prastuti': ['CV', 'Profile', 'Pitch deck'],
  'merchandise': ['Merchandise', 'Fit', 'Delivery'],
  'kiosk': ['Kiosk', 'Specifications', 'Delivery'],
  'contribute': ['Contribution', 'Review', 'Receipt'],
};

const COLOURS = [
  { tint: '#e0f7c8', dot: '#3da35a' },
  { tint: '#dbeafe', dot: '#2563eb' },
  { tint: '#ede9fe', dot: '#9849e8' },
];

export function shopHeroWords( slug: string ) {
  const labels = Object.hasOwn( LABELS, slug ) ? LABELS[ slug ] : undefined;
  // New catalogue items retain a usable band until editorial copy is reviewed.
  return ( labels ?? ['Details', 'Price', 'Checkout'] )
    .map( ( word, index ) => ( { word, ...COLOURS[ index ] } ) );
}
