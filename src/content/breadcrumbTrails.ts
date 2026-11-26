import type { Crumb } from '../components/Breadcrumbs';

/** Shared product breadcrumb trails for visible navigation and BreadcrumbList JSON-LD.
 * Keys match PUBLIC_PAGE_META router paths; links include the configured trailing slash.
 * Keep labels aligned with products.ts and productChildren.ts. Routes absent from this
 * map retain their two-item schema default.
 */
const HOME: Crumb = { label: 'Home', href: '/' };
const SHOP: Crumb = { label: 'Shop', href: '/shop/' };

const here = ( label: string ): Crumb => ( { label } );

export const BREADCRUMB_TRAILS: Readonly<Record<string, readonly Crumb[]>> = {
  '/atmos/green-ledger': [ HOME, here( 'Green Ledger' ) ],
  '/elsewhere/rail': [ HOME, here( 'Rail' ) ],
  '/elsewhere/cruise': [ HOME, here( 'Cruise' ) ],
  // Product pages: Home / Shop / <Product>, matching what /shop/<slug>/ renders, so the trail
  // from the listing into a product is unbroken.
  '/expo-week': [ HOME, SHOP, here( 'Expo Week' ) ],
  '/anew': [ HOME, SHOP, here( 'Anew' ) ],
  '/hunar/kaushal': [ HOME, SHOP, here( 'Kaushal' ) ],
  '/hunar/prastuti': [ HOME, SHOP, here( 'Prastuti' ) ],
  '/niji-setu/parichay': [ HOME, here( 'Parichay' ) ],
  '/niji-setu/khata': [ HOME, here( 'Khata' ) ],
  // Product families have no page of their own (Header renders each as a label), so their
  // children sit directly under Shop. A parent crumb would have to link a URL that 404s.
  '/elsewhere/visa': [ HOME, SHOP, here( 'Visa' ) ],
  '/elsewhere/trip': [ HOME, SHOP, here( 'Trip' ) ],
  '/elsewhere/activities': [ HOME, SHOP, here( 'Activities' ) ],
  '/dastavez/drafting': [ HOME, SHOP, here( 'Drafting' ) ],
  '/dastavez/registration': [ HOME, SHOP, here( 'Registration' ) ],
  '/dastavez/legal-reference': [ HOME, SHOP, here( 'Legal Reference' ) ],
  '/aastha/panchang': [ HOME, SHOP, here( 'Panchang' ) ],
  '/aastha/vidhi': [ HOME, SHOP, here( 'Vidhi' ) ],
  '/aastha/samagri': [ HOME, SHOP, here( 'Samagri' ) ],
  '/shipments/track': [ HOME, SHOP, here( 'Track' ) ],
};

/**
 * The trail for a route, or undefined when the route renders none. Accepts the route with or
 * without its trailing slash. Returns a fresh array, so a caller can never edit the shared one.
 */
export const breadcrumbTrail = ( route: string ): Crumb[] | undefined => {
  const key = route.length > 1 ? route.replace( /\/+$/, '' ) : route;
  const trail = BREADCRUMB_TRAILS[ key ];
  return trail ? trail.map( crumb => ( { ...crumb } ) ) : undefined;
};
