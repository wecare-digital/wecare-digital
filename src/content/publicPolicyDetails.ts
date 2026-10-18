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
  '/bharat-rx',
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
] );

/**
 * Step 6 copy rule: four concise concepts only. These routes do not need a generic
 * "what this page is" paragraph before the policy; the page content already supplies that
 * context. Keep fulfilment, returns, refunds/cancellations and the route-specific disclaimer.
 */
const PAGE_POLICY: Readonly<Record<string, PublicPolicyCopy>> = {
  '/contact': {
    shipping: 'Contact itself has no fulfilment. Any later paid order follows the terms confirmed for that transaction.',
    returns: 'Nothing is delivered by this page to return. Any later return right belongs to the purchased item or service.',
    refunds: 'Contact is free. Any later cancellation or refund follows the confirmed transaction.',
    disclaimer: 'A message is an enquiry, not acceptance of price, timing, availability or outcome.',
  },
  '/orders': {
    shipping: 'Fulfilment follows the underlying order or request and may depend on a courier or other provider.',
    returns: 'Return or replacement eligibility follows the underlying item or service and applicable law.',
    refunds: 'Refund or cancellation eligibility follows the underlying transaction; this status page does not change it.',
    disclaimer: 'Status can change as systems and partners update; the latest confirmed order record controls.',
  },
  '/vayulok': {
    shipping: 'No fulfilment applies; VayuLok is free informational access.',
    returns: 'Nothing on this page is delivered as a returnable item.',
    refunds: 'No page charge is taken, so there is nothing to cancel or refund.',
    disclaimer: 'Air-quality and weather data may be delayed, estimated or supplied by third parties. Use official sources for safety-critical decisions.',
  },
  '/elsewhere/activities': {
    shipping: 'Planning is delivered digitally. Any separately included ticket, pass or item follows the delivery terms confirmed for it.',
    returns: 'Completed planning work is not physically returnable. Third-party items follow the provider terms and applicable law.',
    refunds: 'Cancellation or refund eligibility depends on work already started and any third-party provider terms.',
    disclaimer: 'Availability, weather, operating rules and third-party prices remain controlled by the relevant provider.',
  },
  '/ritual-guru/ritva': {
    shipping: 'Guidance is delivered digitally unless a physical item is expressly included.',
    returns: 'Prepared or delivered guidance is not physically returnable. Separate physical items follow their disclosed terms.',
    refunds: 'Cancellation or adjustment eligibility depends on whether preparation has started and the confirmed transaction terms.',
    disclaimer: 'Ritva is interpretive spiritual guidance, not medical, legal, financial, structural or other regulated professional advice.',
  },
  '/leave-review': {
    shipping: 'No fulfilment applies to submitting feedback.',
    returns: 'A review is not a return. Product or service return issues belong to the underlying order.',
    refunds: 'Submitting or editing feedback does not change refund or cancellation rights.',
    disclaimer: 'Feedback may be moderated for privacy, relevance and abuse; submission does not guarantee publication.',
  },
  '/privacy': {
    shipping: 'No fulfilment applies to reading the Privacy Policy.',
    returns: 'Nothing is delivered by this page to return.',
    refunds: 'No payment is taken for accessing this page.',
    disclaimer: 'The full Privacy Policy above controls; this disclosure does not replace it.',
  },
  '/terms': {
    shipping: 'No fulfilment applies to reading the Terms. Paid products and services follow their own confirmed transaction terms.',
    returns: 'Nothing is delivered by this page to return.',
    refunds: 'No payment is taken for accessing this page.',
    disclaimer: 'The full Terms above control; this disclosure does not replace or shorten them.',
  },
  '/shop': {
    shipping: 'Fulfilment depends on the selected item or service and is confirmed before fulfilment.',
    returns: 'Return or replacement eligibility is item-specific and follows the disclosed terms and applicable law.',
    refunds: 'Browsing the catalogue creates nothing to cancel. Confirmed orders follow their transaction terms.',
    disclaimer: 'Price, availability and fulfilment can change before checkout; the confirmed cart and order control.',
  },
  '/account/sign-in': {
    shipping: 'Signing in does not start fulfilment. Existing orders keep their own fulfilment terms.',
    returns: 'Authentication does not change return or replacement eligibility.',
    refunds: 'Signing in does not create, approve or cancel a refund.',
    disclaimer: 'Use only an account you are authorised to access; authentication does not itself confirm payment or ownership.',
  },
  '/cart': {
    shipping: 'Fulfilment starts only after the relevant order is confirmed. Timing depends on the selected items.',
    returns: 'Return or replacement eligibility is determined item by item after an order exists.',
    refunds: 'Removing an item from the cart is not a refund. After payment, the confirmed order policy applies.',
    disclaimer: 'Price, availability and totals can change before payment; the final checkout and confirmed order control.',
  },
  '/checkout/status': {
    shipping: 'Fulfilment starts only after the order is confirmed as paid or otherwise accepted.',
    returns: 'Return or replacement rights belong to the purchased item or service, not this status screen.',
    refunds: 'A pending or unavailable status is not a refund. Cancellation and refund handling starts from the confirmed transaction.',
    disclaimer: 'If status is unclear, check the order record or contact support before paying again.',
  },
  '/checkout/success': {
    shipping: 'Fulfilment follows the items and timing in the confirmed order.',
    returns: 'Return or replacement eligibility remains item-specific and follows the confirmed order terms and applicable law.',
    refunds: 'Any later cancellation or refund request is handled against the confirmed order.',
    disclaimer: 'Keep the order reference; the confirmed order record is the authoritative transaction record.',
  },
  '/get': {
    shipping: 'This access page creates no physical shipping. Any separate delivery follows the request or order it belongs to.',
    returns: 'A securely released digital copy is not a physical item to return.',
    refunds: 'This access page takes no payment, so there is no page charge to cancel or refund.',
    disclaimer: 'Access may require identity or possession checks and can expire or be withdrawn when no longer authorised.',
  },
};

const BLOG_INDEX_POLICY: PublicPolicyCopy = {
  shipping: 'No fulfilment is created by browsing the Blog or a topic page.',
  returns: 'There is no product or paid deliverable on a blog listing page to return.',
  refunds: 'Browsing the Blog is free, so there is nothing to cancel or refund.',
  disclaimer: 'Articles are general information and do not replace qualified professional advice where one is required.',
};

const BLOG_POST_POLICY: PublicPolicyCopy = {
  shipping: 'No fulfilment is created by reading or sharing this article.',
  returns: 'There is no product or paid deliverable in the article itself to return.',
  refunds: 'Reading the article is free, so there is nothing to cancel or refund.',
  disclaimer: 'Articles are general information at the date of publication; verify time-sensitive facts and seek qualified advice where required.',
};

const SHOP_PAGE_POLICY: PublicPolicyCopy = {
  shipping: 'Fulfilment depends on the selected item or service and is confirmed before fulfilment.',
  returns: 'Return or replacement eligibility is item-specific and follows the disclosed terms and applicable law.',
  refunds: 'Browsing a catalogue page creates nothing to cancel. Confirmed orders follow their transaction terms.',
  disclaimer: 'Price, availability and fulfilment can change before checkout; the confirmed cart and order control.',
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
