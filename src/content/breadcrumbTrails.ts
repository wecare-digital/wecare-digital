import type { Crumb } from '../components/Breadcrumbs';

/**
 * ONE SOURCE FOR THE PRODUCT-FAMILY BREADCRUMB TRAILS.
 *
 * .kiro/steering/30-seo.md: the BreadcrumbList JSON-LD must "mirror the visible breadcrumb trail
 * exactly". Until 2026-10-16 it did not on any of these fifteen pages. Each page typed its
 * visible trail by hand (Home / Shop / Dastavez / Drafting) while _app.tsx's
 * getPublicPageSchema emitted a fixed two-item list (Home / Drafting) for every route in
 * PUBLIC_PAGE_META - two trails for one page, and the one Google reads was the shorter.
 *
 * Both now read this map: the page passes `breadcrumbTrail( route )` to ProductPage's `crumbs`,
 * and getPublicPageSchema builds the ListItems from the same entry, so the two cannot disagree.
 * src/test/BreadcrumbTrails.test.ts pins that every key is a PUBLIC_PAGE_META route whose name
 * ends the trail, and that every page under src/pages takes its crumbs from here.
 *
 * DELIBERATELY SMALL. _app.tsx imports this module, which puts it in the bundle every page
 * loads, so it carries labels and hrefs only - not the product copy in products.ts or
 * productChildren.ts. The labels repeat the product names; the test is what keeps them equal.
 *
 * Keys are router.pathname spellings (no trailing slash), the same keys PUBLIC_PAGE_META uses.
 * hrefs carry the trailing slash, because next.config.js sets trailingSlash and a crumb pointing
 * at the slashless URL names a redirect.
 *
 * Routes NOT here render no visible trail, and keep the two-item JSON-LD default.
 */
const HOME: Crumb = { label: 'Home', href: '/' };
const SHOP: Crumb = { label: 'Shop', href: '/shop/' };
const DASTAVEZ: Crumb = { label: 'Dastavez', href: '/dastavez/' };
const RITUAL_GURU: Crumb = { label: 'Ritual Guru', href: '/ritual-guru/' };

const here = ( label: string ): Crumb => ( { label } );

export const BREADCRUMB_TRAILS: Readonly<Record<string, readonly Crumb[]>> = {
  // Product pages: Home / Shop / <Product>, matching what /shop/<slug>/ renders, so the trail
  // from the listing into a product is unbroken.
  '/expo-week': [ HOME, SHOP, here( 'Expo Week' ) ],
  '/dastavez': [ HOME, SHOP, here( 'Dastavez' ) ],
  '/clear-closure': [ HOME, SHOP, here( 'Clear Closure' ) ],
  '/ritual-guru': [ HOME, SHOP, here( 'Ritual Guru' ) ],
  '/anew': [ HOME, SHOP, here( 'Anew' ) ],
  '/hunar': [ HOME, SHOP, here( 'Hunar' ) ],
  '/niji-setu': [ HOME, SHOP, here( 'Niji Setu' ) ],
  // Elsewhere is a category with no page of its own (the Header renders it as a label), so its
  // children sit directly under Shop. A crumb for it would have to link a URL that 404s.
  '/elsewhere/visa': [ HOME, SHOP, here( 'Visa' ) ],
  '/elsewhere/trip': [ HOME, SHOP, here( 'Trip' ) ],
  '/elsewhere/activities': [ HOME, SHOP, here( 'Activities' ) ],
  // Family children with a parent page.
  '/dastavez/drafting': [ HOME, SHOP, DASTAVEZ, here( 'Drafting' ) ],
  '/dastavez/registration': [ HOME, SHOP, DASTAVEZ, here( 'Registration' ) ],
  '/dastavez/legal-reference': [ HOME, SHOP, DASTAVEZ, here( 'Legal Reference' ) ],
  '/ritual-guru/puja-guidance': [ HOME, SHOP, RITUAL_GURU, here( 'Puja Guidance' ) ],
  '/ritual-guru/diy-puja-kit': [ HOME, SHOP, RITUAL_GURU, here( 'DIY Puja Kit' ) ],
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
