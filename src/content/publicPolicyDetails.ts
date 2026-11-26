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
  shipping: 'Delivery, collection or service fulfilment follows your confirmed order, booking or request.',
  returns: 'Request a return or replacement under the conditions disclosed for your purchase. Statutory remedies remain available for faulty, misdescribed or deficient goods and services.',
  refunds: 'Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
  disclaimer: 'Keep your order reference for enquiries. If an order, payment or delivery status appears incorrect, contact customer care.',
};

/**
 * Public policy copy stays on the Grahak pattern: four short, specific concepts.
 * The page itself already explains the product or journey, so Policy Details does not
 * repeat page context or append a generic legal footer.
 */
const PAGE_POLICY: Readonly<Record<string, PublicPolicyCopy>> = {
  '/': {
    shipping: 'Physical products are delivered according to the confirmed order; digital services and appointments follow their agreed scope and schedule.',
    returns: 'Return and replacement conditions depend on the product or service and the terms disclosed before purchase. Statutory consumer remedies remain available.',
    refunds: 'Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
    disclaimer: 'Services are subject to availability and applicable service-specific terms. General information is not personalised professional advice.',
  },
  '/niji-setu/parichay': {
    shipping: 'Any profile service, when available, will be supplied digitally under the terms disclosed before purchase.',
    returns: 'Digital profile deliverables may have change-of-mind return restrictions; remedies for deficient services remain available under applicable law.',
    refunds: 'If a paid profile service is offered, its disclosed cancellation conditions and applicable refund rights will apply.',
    disclaimer: 'Parichay is a planned digital profile tool. Availability must be confirmed; share personal information only with intended recipients.',
  },
  '/niji-setu/khata': {
    shipping: 'Any invoice creation service, when available, will be supplied digitally under the terms disclosed before purchase.',
    returns: 'Digital invoice services may have change-of-mind return restrictions; remedies for deficient services remain available under applicable law.',
    refunds: 'If a paid invoice service is offered, its disclosed cancellation conditions and applicable refund rights will apply.',
    disclaimer: 'Khata is a planned invoice creation tool, not tax or accounting advice. Verify invoice particulars and applicable tax requirements.',
  },
  '/atmos/green-ledger': {
    shipping: 'Environmental record and sustainability tracking services, if offered, follow the agreed scope and delivery schedule.',
    returns: 'Return and correction conditions depend on the agreed service. Statutory remedies for deficient or misdescribed work remain available.',
    refunds: 'Cancellation and refund eligibility depends on the confirmed service and disclosed terms; monetary refunds are provided where required by law.',
    disclaimer: 'Green Ledger availability and scope must be confirmed before purchase. Environmental records alone do not establish regulatory compliance or independent certification.',
  },
  '/elsewhere/rail': {
    shipping: 'Rail planning and any confirmed ticket or booking arrangements follow the relevant operator\'s delivery and travel conditions.',
    returns: 'Ticket changes and cancellations depend on the operator\'s fare rules and applicable passenger rights.',
    refunds: 'Any booking refund is subject to the disclosed fare conditions, recoverable charges and applicable law. Our service charges follow the agreed terms.',
    disclaimer: 'Rail enquiries do not guarantee tickets, fares, seats or schedules. Confirm travel details with the operator before departure.',
  },
  '/elsewhere/cruise': {
    shipping: 'Cruise planning and any confirmed booking documents follow the agreed arrangements and relevant operator conditions.',
    returns: 'Booking changes or cancellations depend on the operator\'s fare conditions and applicable passenger rights.',
    refunds: 'Refund eligibility depends on the confirmed booking, disclosed cancellation charges and applicable law. Our service charges follow the agreed terms.',
    disclaimer: 'Cruise itineraries, availability, prices, entry requirements and sailing schedules are subject to operator confirmation.',
  },
  '/vault': {
    shipping: 'Authorised Vault files are supplied digitally, subject to the applicable access conditions.',
    returns: 'If a file is incorrect or incomplete, contact customer care. Change-of-mind restrictions do not affect statutory remedies for deficient services.',
    refunds: 'Any paid Vault service follows its disclosed cancellation conditions. Monetary refunds are provided where required by law.',
    disclaimer: 'Access requires the applicable identity and access verification. Protect file links and verification codes; retention is governed by our Privacy Policy.',
  },
  '/auth': {
    shipping: 'Delivery and service arrangements apply to your confirmed orders and bookings.',
    returns: 'Purchased items and services follow their disclosed return or replacement conditions and applicable law.',
    refunds: 'Cancellation and refund rights apply to the relevant confirmed transaction; eligible discretionary credits follow our Terms of Service.',
    disclaimer: 'Keep your sign-in credentials and verification codes private. Sign-in does not confirm a purchase or payment.',
  },
  '/contact': {
    shipping: 'Delivery, collection or service fulfilment follows the arrangements confirmed for your request or order.',
    returns: 'Contact customer care about damaged, incorrect or deficient goods or services and any available return or replacement remedy.',
    refunds: 'Contact us to request a cancellation or refund. Eligibility follows the confirmed transaction and applicable law.',
    disclaimer: 'A general enquiry does not confirm acceptance, price, scope or timing. For a complaint, contact one@wecare.digital.',
  },
  '/atmos/nano-climate': {
    shipping: 'Air-quality and weather information is provided digitally; any purchased service follows its confirmed scope and fulfilment terms.',
    returns: 'Digital information and service deliverables may have change-of-mind return restrictions; statutory remedies for deficient services remain available.',
    refunds: 'Any paid Nano Climate service follows its disclosed cancellation conditions and applicable refund rights.',
    disclaimer: 'Air-quality and weather data may be delayed, estimated or supplied by third parties. Refer to official advisories for safety-critical decisions.',
  },
  '/elsewhere/activities': {
    shipping: 'Activity planning is supplied digitally. Tickets, bookings and other items follow their confirmed delivery arrangements.',
    returns: 'Changes or cancellations to third-party activities follow the disclosed operator terms and applicable passenger or consumer rights.',
    refunds: 'Refund eligibility depends on work performed, recoverable provider charges, disclosed conditions and applicable law.',
    disclaimer: 'Activity availability, local rules, weather, prices and safety conditions are subject to operator confirmation.',
  },
  '/aastha/panchang': {
    shipping: 'Panchang and traditional guidance are supplied digitally unless physical delivery is separately agreed.',
    returns: 'Change-of-mind returns may be limited after personalised guidance is prepared. Statutory remedies for deficient services remain available.',
    refunds: 'Cancellation and adjustment eligibility depends on preparation already performed and disclosed terms. Monetary refunds are provided where required by law.',
    disclaimer: 'Panchang, astrology and Vastu are traditional interpretive practices, not guaranteed predictions or medical, legal, financial or other regulated advice.',
  },
  '/privacy': {
    shipping: 'We share delivery details, including your name, address and phone number, with couriers, sellers and fulfilment partners as needed to complete delivery.',
    returns: 'We use relevant order and contact information to handle return and replacement requests and share information with the relevant providers as needed.',
    refunds: 'Payment providers may receive information needed to process refunds or resolve payment disputes. Transaction records may be retained for accounting, tax, fraud prevention and legal obligations.',
    disclaimer: 'Independent providers may handle personal data under their own privacy policies. For access, correction, erasure, withdrawal of consent or a privacy grievance, contact one@wecare.digital. Your statutory rights remain unaffected.',
  },
  '/terms': {
    shipping: 'Delivery availability, charges and timelines depend on the product or service, destination and provider. Estimated dates do not affect your statutory rights for late or failed delivery.',
    returns: 'Eligibility depends on the product or service, reason for the request, fulfilment progress and disclosed conditions. Statutory remedies for defective or misdescribed goods, deficient services or late deliveries remain available in accordance with law.',
    refunds: 'Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days, subject to applicable law. Monetary refunds are provided where required by law.',
    disclaimer: 'Services are subject to availability and applicable service-specific terms. General information does not constitute personalised professional advice. Your mandatory consumer and other statutory rights and remedies remain unaffected.',
  },
  '/shop': {
    shipping: 'Delivery or digital fulfilment depends on the selected product, confirmed destination and disclosed delivery charges or service arrangements.',
    returns: 'Return and replacement eligibility depends on the item, its condition, customisation and disclosed terms. Statutory remedies for defective, misdescribed or late goods and deficient services remain available.',
    refunds: 'Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
    disclaimer: 'Prices, availability and service scope are confirmed before purchase. Independent providers may have separate terms. Your statutory rights remain unaffected.',
  },
  '/checkout': {
    shipping: 'Delivery or service fulfilment follows the confirmed order, payment requirements and disclosed charges or schedule.',
    returns: 'Return and replacement eligibility depends on the purchased product or service and disclosed conditions. Statutory remedies remain available.',
    refunds: 'Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
    disclaimer: 'Review the items, charges, delivery details and payment amount before confirming. If payment status is unclear, check your order or contact customer care before trying again.',
  },
  '/checkout/status': {
    shipping: 'Delivery or service arrangements follow your confirmed order and its applicable payment conditions.',
    returns: 'Return and replacement requests are handled against the relevant purchase, subject to its disclosed conditions and applicable law.',
    refunds: 'Cancellation and refund eligibility follows the confirmed transaction. Contact customer care for help with a delayed or disputed payment.',
    disclaimer: 'If payment status is unclear, check your order reference or contact customer care before paying again.',
  },
  '/checkout/success': {
    shipping: 'Your confirmed order sets out the applicable delivery or service arrangements.',
    returns: 'Return and replacement eligibility depends on the purchased item or service and disclosed conditions. Statutory remedies remain available.',
    refunds: 'Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
    disclaimer: 'Keep your order and payment reference for enquiries. Contact customer care if the confirmation differs from your purchase.',
  },
  '/get': {
    shipping: 'Authorised files are supplied digitally under the applicable access conditions.',
    returns: 'Contact customer care if a supplied digital file is incorrect or incomplete. Statutory remedies remain available.',
    refunds: 'Refund and cancellation eligibility for a paid file or service follows its disclosed terms and applicable law.',
    disclaimer: 'Access may require verification and may expire or be withdrawn when no longer authorised. Protect shared file links.',
  },
};

const BLOG_INDEX_POLICY: PublicPolicyCopy = {
  shipping: 'Articles are available online. Any separately purchased products or services follow their confirmed delivery terms.',
  returns: 'Return and replacement eligibility for a related purchase follows its disclosed conditions and applicable law.',
  refunds: 'Reading articles is free. Voluntary contributions support editorial work and are generally non-refundable; erroneous, duplicate, unauthorised or fraudulent payments may be reviewed for reversal.',
  disclaimer: 'Articles provide general information, not personalised professional advice. Check current information with authoritative sources.',
};

const BLOG_POST_POLICY: PublicPolicyCopy = {
  shipping: 'Articles are published digitally; any separate purchase or service follows its confirmed delivery arrangements.',
  returns: 'Return and replacement rights apply to separately purchased goods or services under their disclosed terms and applicable law.',
  refunds: 'Voluntary contributions support editorial work and do not purchase goods or services. Contributions are generally non-refundable; contact us about erroneous, duplicate, unauthorised or fraudulent payments.',
  disclaimer: 'Published information may become outdated. Verify material facts with authoritative sources and seek qualified advice where necessary. Contributions do not confer editorial influence or a financial return.',
};

const SHOP_PAGE_POLICY: PublicPolicyCopy = {
  shipping: 'Delivery or digital fulfilment depends on the selected product, confirmed destination and disclosed delivery charges or service arrangements.',
  returns: 'Return and replacement eligibility depends on the item, its condition, customisation and disclosed terms. Statutory remedies for defective, misdescribed or late goods and deficient services remain available.',
  refunds: 'Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
  disclaimer: 'Prices, availability and service scope are confirmed before purchase. Independent providers may have separate terms. Your statutory rights remain unaffected.',
};

export function publicPolicyDetailsForRoute( pathname: string ): PublicPolicyCopy | null {
  if ( pathname === '/404' ) return null;
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
