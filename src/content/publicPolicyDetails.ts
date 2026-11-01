export interface PublicPolicyCopy {
  shipping: string;
  returns: string;
  refunds: string;
  disclaimer: string;
}

/**
 * Routes that already render PolicyDetails inside their own product transaction block.
 * The shared public tail must not add a second copy on those pages.
 */
export const EMBEDDED_POLICY_ROUTES = new Set<string>( [
  '/grahak-os',
  '/sehat',
  '/elsewhere/visa',
  '/elsewhere/trip',
  '/expo-week',
  '/dastavez/drafting',
  '/dastavez/registration',
  '/dastavez/legal-reference',
  '/ritual-guru/puja-guidance',
  '/ritual-guru/diy-puja-kit',
  '/anew',
  '/hunar/kaushal',
  '/hunar/prastuti',
  '/niji-setu',
  '/submit-request',
  '/request-amendment',
  '/drop-docs',
  '/vault',
  '/shipments/track',
  '/request-pickup',
  '/orders',
] );

/** Orders renders its disclosure beneath the history inside the page. Keep the
 * same four canonical policy statements without a second global tail. */
export const ORDERS_POLICY_DETAILS: PublicPolicyCopy = {
  shipping: 'Delivery or service fulfilment follows your confirmed order and any applicable courier or provider terms.',
  returns: 'Return or replacement eligibility depends on the purchased item or service, its confirmed terms and applicable law.',
  refunds: 'Cancellation and refund eligibility depends on the confirmed transaction and applicable terms.',
  disclaimer: 'The latest confirmed order record controls the status shown here. If a paid order is missing or looks incorrect, contact us.',
};

/**
 * Public policy copy stays on the Grahak pattern: four short, specific concepts.
 * The page itself already explains the product or journey, so Policy Details does not
 * repeat page context or append a generic legal footer.
 */
const PAGE_POLICY: Readonly<Record<string, PublicPolicyCopy>> = {
  // Customer sign-in is a no-payment account access step; do not imply that an
  // OTP verification itself creates an order or any return/refund entitlement.
  '/auth': {
    shipping: 'Signing in or verifying your number does not start a delivery. Fulfilment follows only a separately confirmed order.',
    returns: 'Signing in does not provide a returnable item or service. Any purchased item follows its confirmed return or replacement terms.',
    refunds: 'No payment is taken by signing in. Cancellation and refund eligibility applies to a separately confirmed purchase.',
    disclaimer: 'Keep verification codes private. Signing in alone does not confirm an order, booking or payment.',
  },
  '/contact': {
    shipping: 'No fulfilment starts by visiting or contacting us on this page.',
    returns: 'Nothing submitted on this page is a returnable product.',
    refunds: 'No payment is taken on this page, so nothing is refundable here.',
    disclaimer: 'Submitting a request does not confirm acceptance, price, timing or scope; the later confirmed request or order controls.',
  },
  // VayuLok Standard is listed at ₹99.00 in the catalog (owner-approved in #1449), so this copy
  // must not call VayuLok itself free. What stays true is page-scoped: the live data here is free
  // to use and the page takes no payment; a catalog order is governed by that order.
  '/vayulok': {
    shipping: 'No fulfilment starts by using the live air and weather information on this page.',
    returns: 'Nothing on this page is returnable.',
    refunds: 'No payment is taken on this page; a paid VayuLok catalog order follows its confirmed order terms.',
    disclaimer: 'Air-quality and weather data may be delayed, estimated or third-party supplied. Use official sources for safety-critical decisions.',
  },
  '/elsewhere/activities': {
    shipping: 'Planning is delivered digitally; separate tickets or items follow their own delivery terms.',
    returns: 'Completed planning work is not returnable; third-party items follow provider terms.',
    refunds: 'Refunds and cancellations depend on work started and third-party terms.',
    disclaimer: 'Availability, weather, operating rules and prices remain with the relevant provider.',
  },
  '/ritual-guru/ritva': {
    shipping: 'Guidance is delivered digitally unless a physical item is included.',
    returns: 'Delivered guidance is not returnable; physical items follow their disclosed terms.',
    refunds: 'Refunds and cancellations depend on whether preparation has started.',
    disclaimer: 'Ritva is spiritual guidance, not medical, legal, financial or other regulated professional advice.',
  },
  '/privacy': {
    shipping: 'No fulfilment applies to this page.',
    returns: 'Nothing on this page is returnable.',
    refunds: 'No payment is taken here.',
    disclaimer: 'The Privacy Policy above controls.',
  },
  '/terms': {
    shipping: 'No fulfilment applies to this page.',
    returns: 'Nothing on this page is returnable.',
    refunds: 'No payment is taken here.',
    disclaimer: 'The Terms above control.',
  },
  '/shop': {
    shipping: 'Fulfilment depends on the selected item or service.',
    returns: 'Returns or replacements are item-specific and follow disclosed terms and applicable law.',
    refunds: 'Browsing creates nothing to cancel; confirmed orders follow their terms.',
    disclaimer: 'Price, availability and fulfilment can change before checkout; the confirmed order controls.',
  },
  '/checkout': {
    shipping: 'Fulfilment starts after the payment and order are confirmed; delivery or service timing follows the confirmed item.',
    returns: 'Return and replacement eligibility depends on the selected item or service, its confirmed terms and applicable law.',
    refunds: 'Cancellation and refund eligibility follows the confirmed transaction, disclosed terms and applicable law.',
    disclaimer: 'Check your items, amount and details before paying. If payment status is unclear, check the order record instead of paying again.',
  },
  '/checkout/status': {
    shipping: 'Fulfilment starts after the order is confirmed.',
    returns: 'Returns or replacements follow the purchased item or service terms.',
    refunds: 'A pending status is not a refund; the confirmed transaction controls.',
    disclaimer: 'If status is unclear, check the order record before paying again.',
  },
  '/checkout/success': {
    shipping: 'Fulfilment follows the confirmed order.',
    returns: 'Returns or replacements follow the confirmed item or service terms.',
    refunds: 'Later refunds or cancellations are handled against the confirmed order.',
    disclaimer: 'Keep the order reference; the confirmed order record controls.',
  },
  '/get': {
    shipping: 'This page creates no physical shipping.',
    returns: 'A released digital copy is not a physical return.',
    refunds: 'No payment is taken on this page.',
    disclaimer: 'Access can require verification and may expire or be withdrawn when no longer authorised.',
  },
};

const BLOG_INDEX_POLICY: PublicPolicyCopy = {
  shipping: 'No fulfilment applies to browsing the Blog.',
  returns: 'Nothing on a blog listing is returnable.',
  refunds: 'Browsing is free, so nothing is refundable.',
  disclaimer: 'Articles are general information, not professional advice.',
};

const BLOG_POST_POLICY: PublicPolicyCopy = {
  shipping: 'No fulfilment applies to reading or sharing this article.',
  returns: 'Nothing in the article itself is returnable.',
  refunds: 'Reading is free, so nothing is refundable.',
  disclaimer: 'Articles are general information as published; verify time-sensitive facts and seek qualified advice where needed.',
};

const SHOP_PAGE_POLICY: PublicPolicyCopy = {
  shipping: 'Fulfilment depends on the selected item or service.',
  returns: 'Returns or replacements are item-specific and follow disclosed terms and applicable law.',
  refunds: 'Browsing creates nothing to cancel; confirmed orders follow their terms.',
  disclaimer: 'Price, availability and fulfilment can change before checkout; the confirmed order controls.',
};

export function publicPolicyDetailsForRoute( pathname: string ): PublicPolicyCopy | null {
  if ( pathname === '/' || pathname === '/404' ) return null;
  if ( pathname === '/shop/[slug]' || EMBEDDED_POLICY_ROUTES.has( pathname ) ) return null;

  if (
    pathname === '/blog'
    || pathname === '/blog/page/[page]'
    || pathname === '/blog/topic/[topic]'
    || pathname === '/blog/topic/[topic]/page/[page]'
  ) return BLOG_INDEX_POLICY;

  if ( pathname === '/post/[slug]' ) return BLOG_POST_POLICY;
  if ( pathname === '/shop/page/[page]' ) return SHOP_PAGE_POLICY;

  return PAGE_POLICY[ pathname ] || null;
}
