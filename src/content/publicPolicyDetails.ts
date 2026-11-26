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
  '/relay-os',
  '/elsewhere/arogya-yatra',
  '/elsewhere/visa',
  '/elsewhere/trip',
  '/expo-week',
  '/dastavez/drafting',
  '/dastavez/registration',
  '/dastavez/legal-reference',
  '/aastha/vidhi',
  '/aastha/samagri',
  '/anew',
  '/hunar/kaushal',
  '/hunar/prastuti',
  '/submit-request',
  '/request-amendment',
  '/drop-docs',
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
  '/niji-setu/parichay': { shipping: 'No fulfilment starts by visiting this information page.', returns: 'Nothing is sold on this page.', refunds: 'No payment is taken here.', disclaimer: 'Profile creation and sharing are not available on this page yet.' },
  '/niji-setu/khata': { shipping: 'No fulfilment starts by visiting this information page.', returns: 'Nothing is sold on this page.', refunds: 'No payment is taken here.', disclaimer: 'Invoice creation is not available on this page yet. Verify applicable invoicing and tax requirements before issuing invoices.' },
  '/atmos/green-ledger': { shipping: 'No fulfilment starts by visiting this information page.', returns: 'Nothing is sold on this page.', refunds: 'No payment is taken here.', disclaimer: 'Product scope and availability must be confirmed before any order.' },
  '/elsewhere/rail': { shipping: 'No ticket is issued on this page.', returns: 'Nothing is sold on this page.', refunds: 'No payment is taken here.', disclaimer: 'Rail availability, fares, timetables and terms remain with the relevant operator.' },
  '/elsewhere/cruise': { shipping: 'No ticket is issued on this page.', returns: 'Nothing is sold on this page.', refunds: 'No payment is taken here.', disclaimer: 'Cruise availability, fares, itineraries and terms remain with the relevant operator.' },
  // Customer sign-in is a no-payment account access step; do not imply that an
  // OTP verification itself creates an order or any return/refund entitlement.
  '/vault': {
    shipping: 'Vault files are delivered digitally after owner verification; no physical shipment is included.',
    returns: 'A downloaded digital file cannot be returned as a physical item. Contact support if the shared file is incorrect.',
    refunds: 'Refund and cancellation eligibility follows the confirmed Vault purchase, its terms and applicable law.',
    disclaimer: 'A file link alone grants no download access. The server verifies the exact owner, payment and access window.',
  },
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
  // Nano Climate Standard is listed at ₹99.00 in the catalog (owner-approved in #1449), so this copy
  // must not call Nano Climate itself free. What stays true is page-scoped: the live data here is free
  // to use and the page takes no payment; a catalog order is governed by that order.
  '/atmos/nano-climate': {
    shipping: 'No fulfilment starts by using the live air and weather information on this page.',
    returns: 'Nothing on this page is returnable.',
    refunds: 'No payment is taken on this page; a paid Nano Climate catalog order follows its confirmed order terms.',
    disclaimer: 'Air-quality and weather data may be delayed, estimated or third-party supplied. Use official sources for safety-critical decisions.',
  },
  '/elsewhere/activities': {
    shipping: 'Planning is delivered digitally; separate tickets or items follow their own delivery terms.',
    returns: 'Completed planning work is not returnable; third-party items follow provider terms.',
    refunds: 'Refunds and cancellations depend on work started and third-party terms.',
    disclaimer: 'Availability, weather, operating rules and prices remain with the relevant provider.',
  },
  '/aastha/panchang': {
    shipping: 'Guidance is delivered digitally unless a physical item is included.',
    returns: 'Delivered guidance is not returnable; physical items follow their disclosed terms.',
    refunds: 'Refunds and cancellations depend on whether preparation has started.',
    disclaimer: 'Panchang is traditional spiritual and calendar guidance, not medical, legal, financial or other regulated professional advice.',
  },
  '/privacy': {
    shipping: 'We share delivery details, including your name, address and phone number, with couriers, sellers and fulfilment partners as needed to complete delivery.',
    returns: 'We use relevant order and contact information to handle return and replacement requests and share information with the relevant providers as needed.',
    refunds: 'Payment providers may receive information needed to process refunds or resolve payment disputes. Transaction records may be retained for accounting, tax, fraud prevention and legal obligations.',
    disclaimer: 'Independent providers may handle personal data under their own privacy policies. For access, correction, erasure, withdrawal of consent or a privacy grievance, contact one@wecare.digital. Your statutory rights remain unaffected.',
  },
  '/terms': {
    shipping: 'Delivery availability, charges and estimated timelines depend on the product or service, destination and applicable provider. Delivery dates are estimates unless expressly guaranteed.',
    returns: 'Eligibility depends on the item or service, the reason for the request, fulfilment progress and disclosed conditions. Statutory remedies for faulty, damaged, misdescribed or deficient goods and services remain available.',
    refunds: 'Eligible voluntary cancellations and discretionary adjustments are resolved through WECARE.DIGITAL store credit valid for 30 calendar days, rather than a monetary refund. Monetary refunds are provided where required by law.',
    disclaimer: 'Services are subject to availability and applicable service-specific terms. General information does not constitute personalised professional advice. Nothing in these Terms limits rights or remedies that cannot lawfully be excluded.',
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
