export interface PublicPolicyCopy {
  overview: string;
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

const PAGE_POLICY: Readonly<Record<string, PublicPolicyCopy>> = {
  '/contact': {
    overview: 'Contact is an enquiry and service-entry page. Sending a message here does not by itself create an order, booking or paid service.',
    shipping: 'No shipping is created by contacting us. If the conversation leads to a paid product, service, pickup or delivery, its fulfilment terms are confirmed for that transaction.',
    returns: 'A contact message is not a returnable item. Any later return or replacement right belongs to the product or service actually ordered.',
    refunds: 'There is no charge to refund for using this contact page. If a paid transaction follows, its refund and cancellation terms apply to that transaction.',
    disclaimer: 'A message does not confirm acceptance, availability, timing, price or an outcome until WECARE.DIGITAL confirms the relevant request or order.',
  },
  '/orders': {
    overview: 'Orders is a tracking surface for transactions or requests that already exist; it does not create a new fulfilment promise.',
    shipping: 'Delivery, collection or service timing remains the timing attached to the underlying order or request and may depend on a courier, provider or other third party.',
    returns: 'Return or replacement eligibility is determined by the item or service in the tracked order and applicable law, not by this status page.',
    refunds: 'Refund or cancellation eligibility follows the underlying transaction. A status shown here does not itself approve, deny or alter a refund.',
    disclaimer: 'Tracking information can change as an order or request moves between systems or third parties; the latest confirmed order record controls.',
  },
  '/grahak-os': {
    overview: 'This page describes the Grahak OS consultation and the transaction attached to that stated scope.',
    shipping: 'The Grahak OS consultation is delivered digitally, so no physical shipping applies. Any separately ordered physical item follows the shipping terms disclosed for that item.',
    returns: 'There is no physical return for the Grahak OS consultation. If a separate physical item is supplied, return or replacement eligibility follows its product-specific terms and applicable law.',
    refunds: 'Eligible voluntary cancellations or discretionary adjustments are handled under the confirmed Grahak OS transaction terms and, unless law requires otherwise, are issued as WECARE.DIGITAL store credit valid for 30 calendar days.',
    disclaimer: 'The purchase covers the stated Grahak OS consultation only. Deployment, integrations and third-party platform or messaging charges are separate unless expressly included in writing, and third-party approvals or availability cannot be guaranteed.',
  },
  '/vayulok': {
    overview: 'VayuLok is an informational web application. Viewing air-quality, weather, forecast or history data does not create a paid order.',
    shipping: 'No physical shipping or service fulfilment is created by using the VayuLok page.',
    returns: 'There is no physical item or paid deliverable on this page to return.',
    refunds: 'Because this public VayuLok experience is free to use, there is no page charge to refund or cancel.',
    disclaimer: 'Environmental and weather data can be delayed, estimated or supplied by third parties. Use appropriate official or professional sources for safety-critical, medical or emergency decisions.',
  },
  '/elsewhere/activities': {
    overview: 'Activities is a planning and coordination service; the page itself does not guarantee a third-party activity, ticket or reservation.',
    shipping: 'Planning is fulfilled digitally. If a physical ticket, pass or other item is separately included, its delivery terms are confirmed before fulfilment.',
    returns: 'Service work already performed is not physically returnable. Any third-party activity, ticket or item follows the provider-specific change, return and replacement terms disclosed for the transaction.',
    refunds: 'Cancellation and refund eligibility can depend on the activity provider and how much work has already started; any eligible WECARE.DIGITAL discretionary adjustment is handled under the confirmed transaction terms.',
    disclaimer: 'Availability, operating hours, admission rules, weather dependency and third-party prices can change and remain subject to the relevant provider.',
  },
  '/ritual-guru/ritva': {
    overview: 'Ritva is personal astrology and Vastu guidance delivered as a service, not a physical product.',
    shipping: 'The guidance is fulfilled digitally unless a separate physical item is expressly included in the confirmed order.',
    returns: 'Guidance already prepared or delivered is not physically returnable. Any separately supplied physical item follows its own disclosed return terms and applicable law.',
    refunds: 'Cancellation or discretionary adjustment eligibility depends on whether preparation has started and on the confirmed transaction terms.',
    disclaimer: 'Ritva provides interpretive spiritual guidance and does not replace medical, legal, financial, structural, engineering or other regulated professional advice.',
  },
  '/leave-review': {
    overview: 'Leave Review is a feedback page. Submitting feedback does not create a purchase, shipment or paid service.',
    shipping: 'No shipping or fulfilment is created by leaving a review.',
    returns: 'A review submission is not a returnable product. Any return or replacement issue about the underlying order must be handled against that order.',
    refunds: 'Submitting or editing feedback does not create or change refund eligibility for an order or service.',
    disclaimer: 'Feedback may be reviewed for relevance, privacy and abuse before it is used or published, and submitting it does not guarantee publication.',
  },
  '/privacy': {
    overview: 'This page explains how WECARE.DIGITAL handles personal data; reading it does not create a transaction.',
    shipping: 'No shipping or fulfilment applies to the Privacy page itself.',
    returns: 'There is no product or service delivered by this page to return.',
    refunds: 'No payment is taken for accessing this Privacy page, so there is no page charge to refund or cancel.',
    disclaimer: 'This summary block does not replace the Privacy Policy text above. Where there is any difference, the full Privacy Policy and applicable law control.',
  },
  '/terms': {
    overview: 'This page states the terms that govern use of WECARE.DIGITAL; reading it does not itself create a purchase.',
    shipping: 'No shipping applies to the Terms page itself. Product or service fulfilment is governed by the terms disclosed for the relevant transaction.',
    returns: 'There is nothing on this page to return. Any return or replacement right belongs to the applicable product, service and law.',
    refunds: 'No payment is taken for accessing the Terms page. Refunds and cancellations for paid transactions are governed by the applicable transaction terms and law.',
    disclaimer: 'This summary block is only a route-specific pointer. It does not override or shorten the full Terms above; the full Terms and applicable law control.',
  },
  '/shop': {
    overview: 'The Shop is a catalogue. Browsing a listing does not create an order; transaction terms attach to the item or service you actually select.',
    shipping: 'Shipping or fulfilment depends on the selected listing and is disclosed or confirmed before fulfilment.',
    returns: 'Return or replacement eligibility is item-specific and depends on the product or service, its condition or progress, the disclosed terms and applicable law.',
    refunds: 'A catalogue view has nothing to cancel. Once an order exists, its refund and cancellation terms apply to that order.',
    disclaimer: 'Availability, price and fulfilment can change before checkout. The cart and confirmed order show the transaction that actually applies.',
  },
  '/account/sign-in': {
    overview: 'Sign in is an authentication step for customer-session features; it is not a purchase or order by itself.',
    shipping: 'Signing in does not start shipping or service fulfilment. Any existing order keeps the fulfilment terms already attached to it.',
    returns: 'Authentication does not change return or replacement eligibility for any item or service.',
    refunds: 'Signing in does not create, approve or cancel a refund. Refund rights remain attached to the underlying transaction.',
    disclaimer: 'Use only your own account or an account you are authorised to access. Authentication does not itself confirm payment, ownership or fulfilment.',
  },
  '/cart': {
    overview: 'The cart is a pre-checkout summary. Items placed here are not paid, accepted or fulfilled until the checkout flow and payment state say so.',
    shipping: 'Shipping or service fulfilment begins only after the relevant order is confirmed. Timing and delivery terms depend on the selected items.',
    returns: 'Return or replacement eligibility is determined item by item after an order exists and follows the disclosed product or service terms and applicable law.',
    refunds: 'Removing an item from the cart is not a refund because no completed transaction is being reversed. After payment, the confirmed order policy applies.',
    disclaimer: 'Prices, availability and totals can change before payment. The final checkout and confirmed order record control.',
  },
  '/checkout/status': {
    overview: 'Checkout Status reports the state of a payment attempt; it does not independently prove that money was captured or that an order was fulfilled.',
    shipping: 'Fulfilment starts only after the order is confirmed as paid or otherwise accepted. This status screen does not accelerate or change fulfilment.',
    returns: 'Return or replacement rights belong to the purchased item or service and are unaffected by viewing this status screen.',
    refunds: 'Do not treat a pending or unavailable status as a refund or as permission to pay twice. Refund or cancellation handling begins from the confirmed transaction record.',
    disclaimer: 'If the status is unclear, use the order record or contact support before repeating payment. Payment networks and providers can report asynchronously.',
  },
  '/checkout/success': {
    overview: 'Checkout Success confirms the completed checkout state shown for this session and points back to the resulting order.',
    shipping: 'Shipping or service fulfilment follows the items in the confirmed order and the timing disclosed for those items.',
    returns: 'Return or replacement eligibility remains item-specific and follows the confirmed order terms and applicable law.',
    refunds: 'Any later cancellation or refund request is handled against the confirmed order; a successful checkout screen does not remove statutory remedies.',
    disclaimer: 'Keep the order reference. The confirmed order record, rather than a saved screenshot of this page, is the authoritative transaction record.',
  },
  '/get': {
    overview: 'Get is a secure file-access entry point. Opening or verifying access does not create a purchase.',
    shipping: 'No physical shipping is created by this file-access page. Any separate delivery arrangement is governed by the request or order it belongs to.',
    returns: 'A securely released digital copy is not a physical item to return.',
    refunds: 'This access page does not itself take a payment, so there is no page charge to refund or cancel.',
    disclaimer: 'File access can require identity or possession checks and may expire or be withdrawn when access is no longer authorised.',
  },
};

const BLOG_INDEX_POLICY: PublicPolicyCopy = {
  overview: 'The Blog is editorial and informational content. Reading, browsing or subscribing to it does not create an order.',
  shipping: 'No physical shipping or paid-service fulfilment is created by a blog index or topic page.',
  returns: 'There is no product or paid deliverable on a blog listing page to return.',
  refunds: 'There is no charge for browsing these blog pages, so there is no page charge to refund or cancel.',
  disclaimer: 'Articles can discuss products, services, law, health, travel or other subjects, but the editorial page itself is general information and does not replace advice from a qualified professional where one is required.',
};

const BLOG_POST_POLICY: PublicPolicyCopy = {
  overview: 'This article is editorial content. Reading or sharing it does not create an order, booking or professional engagement.',
  shipping: 'No physical shipping or paid-service fulfilment is created by reading this article.',
  returns: 'There is no product or paid deliverable in the article itself to return.',
  refunds: 'There is no charge for reading the article, so there is no article charge to refund or cancel.',
  disclaimer: 'The article is general information at the date of publication. Verify time-sensitive facts and obtain qualified professional advice where the subject requires it.',
};

const SHOP_PAGE_POLICY: PublicPolicyCopy = {
  overview: 'This is another page of the Shop catalogue. Browsing it does not create an order; the selected listing and checkout determine the transaction.',
  shipping: 'Shipping or fulfilment depends on the item or service selected and is disclosed or confirmed before fulfilment.',
  returns: 'Return or replacement eligibility is item-specific and depends on the selected product or service, its condition or progress, disclosed terms and applicable law.',
  refunds: 'A catalogue page has nothing to cancel. Once an order exists, refund and cancellation handling follows that confirmed transaction.',
  disclaimer: 'Availability, price and fulfilment can change before checkout. The cart and confirmed order are the authoritative transaction record.',
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
