export const PRODUCT_SKU_BY_SLUG: Readonly<Record<string, string>> = {
  'grahak-os': 'GOS7K4M2',
  'sehat': 'BRX5N8Q3',
  'elsewhere-visa': 'EVS9P4L7',
  'elsewhere-trip': 'ETR6M3K8',
  'expo-week': 'EXP4Q7N5',
  'dastavez-drafting': 'DDF8K5P2',
  'dastavez-registration': 'DRG7M4Q9',
  'dastavez-legal-reference': 'DLR5P8K3',
  'guided-resolution': 'CGR9N6M4',
  'file-assist': 'CCS7K3P8',
  'paperwork': 'CPW5M9Q2',
  'ritual-guru-puja-guidance': 'RPG8N4K6',
  'ritual-guru-diy-puja-kit': 'RDK6P3M9',
  'anew': 'ANW7Q5K2',
  'hunar-kaushal': 'KSL9M2Q4',
  'hunar-prastuti': 'PST7K4N2',
  'niji-setu': 'NJS5K8Q3',
  'submit-request': 'RSR7M2P9',
  'request-amendment': 'RAM5Q8K4',
  'drop-docs': 'RDD9P3M7',
  'vault': 'RVT6K4Q8',
  'shipments-track': 'SHT8M5P3',
  'request-pickup': 'SHP7Q4N9',
  'merchandise': 'PMD9Q3P6',
  'kiosk': 'PKS7K5M4',
  'contribute': 'CNT5Q2M8',
};

export const PRODUCT_REFUNDS =
  'Cancellation eligibility depends on work performed and the disclosed terms. Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.';

export interface ProductPolicyCopy {
  shipping: string;
  returns: string;
  refunds: string;
  disclaimer: string;
}

const PHYSICAL_PRODUCT_SLUGS = new Set<string>( [
  'ritual-guru-diy-puja-kit',
  'merchandise',
  'kiosk',
] );

const POLICY_OVERRIDES: Readonly<Record<string, Partial<ProductPolicyCopy>>> = {
  'grahak-os': {
    shipping: 'The consultation is delivered digitally. Any separately agreed implementation or physical items follow their own fulfilment arrangements.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'The purchase covers one Relay OS consultation. Deployment, integrations and third-party platform or messaging charges are separate unless included in writing. Channel availability and approvals depend on the relevant providers.',
  },
  'sehat': {
    shipping: 'Arogya Yatra arranges appointments with qualified professionals under the confirmed booking conditions. Any separate travel or physical items follow their own terms.',
    returns: 'Appointment changes and cancellations follow the disclosed booking conditions. Statutory remedies for deficient services remain available.',
    refunds: 'Appointment cancellation eligibility depends on the disclosed booking terms. Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
    disclaimer: 'Arogya Yatra is an appointment-booking service, not medical advice, diagnosis or treatment. For emergencies, contact the appropriate emergency service.',
  },
  'elsewhere-visa': {
    shipping: 'Application preparation, documentation and tracking are delivered according to the confirmed service scope. Physical document handling, if included, follows the agreed arrangements.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    refunds: 'Cancellation may depend on work performed and disclosed non-recoverable government or filing charges. Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
    disclaimer: 'Visa decisions, entry permissions and processing times are controlled by the relevant authority. Application support does not guarantee approval.',
  },
  'elsewhere-trip': {
    shipping: 'Travel planning is supplied digitally. Tickets, accommodation and transport are supplied according to the confirmed provider arrangements.',
    returns: 'Booking changes and returns depend on the provider\'s disclosed conditions and applicable passenger or consumer rights.',
    refunds: 'Cancellation may depend on recoverable booking costs and disclosed provider charges. Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
    disclaimer: 'Travel availability, prices, entry conditions and schedules depend on providers and public authorities.',
  },
  'expo-week': {
    shipping: 'Virtual expo access and planning are delivered digitally under the agreed service conditions.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Supplier offers, destination availability and travel conditions may change. Any separately purchased travel service follows its own terms.',
  },
  'dastavez-drafting': {
    shipping: 'Drafts and supporting documents are delivered in the agreed format. Physical documents, if included, follow the agreed delivery arrangements.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Drafting is document-preparation support, not legal advice or representation. Have a qualified advocate review documents where legal advice is needed.',
  },
  'dastavez-registration': {
    shipping: 'Paperwork and filing support follow the agreed scope. Physical documents and official certificates depend on the agreed arrangements and relevant authority.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    refunds: 'Cancellation may depend on work performed and disclosed non-recoverable filing charges. Eligible voluntary cancellations and discretionary adjustments may be resolved through WECARE.DIGITAL store credit valid for 30 calendar days. Monetary refunds are provided where required by law.',
    disclaimer: 'Registration acceptance and processing times are controlled by the relevant authority. Filing support does not guarantee a decision.',
  },
  'dastavez-legal-reference': {
    shipping: 'Research and reference material are supplied digitally in the agreed format.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Legal Reference provides research support, not legal advice, representation or predictions about a legal outcome.',
  },
  'guided-resolution': {
    shipping: 'Preparation and coordination follow the agreed service scope and schedule.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Guided Resolution provides preparation and coordination support. A settlement or other outcome is not guaranteed.',
  },
  'file-assist': {
    shipping: 'Case materials are prepared and submitted according to the agreed service scope and recipient requirements.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Case Submission helps organise and submit materials. Acceptance and decisions remain with the recipient.',
  },
  'paperwork': {
    shipping: 'Prepared documents are supplied in the agreed format; any physical delivery is arranged separately.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Paperwork is document-preparation support, not legal advice or representation.',
  },
  'ritual-guru-puja-guidance': {
    shipping: 'Puja guidance is supplied digitally unless a physical item is separately included.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Ritual practices vary by family, region and tradition. Vidhi provides guidance for self-led worship without claiming that one sequence is universally correct.',
  },
  'ritual-guru-diy-puja-kit': {
    shipping: 'Puja kits are shipped to the confirmed delivery address. Delivery coverage, charges and estimated dates are disclosed for the order.',
    returns: 'Returns or replacements depend on item condition, disclosed conditions and applicable law. Statutory remedies for defective, damaged or misdescribed goods remain available.',
    disclaimer: 'Kit contents may vary by puja, tradition and availability. Check the confirmed item list against your requirements before purchasing.',
  },
  'ritual-guru-ritva': {
    shipping: 'Panchang and traditional guidance are supplied digitally unless physical delivery is separately agreed.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Panchang, astrology and Vastu are traditional interpretive practices, not guaranteed predictions or regulated professional advice.',
  },
  'anew': {
    shipping: 'Reflection sessions or written materials are supplied according to the confirmed service arrangements.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Anew offers reflection-led support, not therapy or personalised medical, legal, financial or tax advice.',
  },
  'hunar-kaushal': {
    shipping: 'Learning plans and supporting material are supplied digitally according to the agreed scope.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Kaushal supports learning and evidence of progress. It does not issue accredited qualifications or guarantee employment.',
  },
  'hunar-prastuti': {
    shipping: 'CVs, profiles and presentation materials are supplied in the agreed digital format.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Prastuti presents your genuine experience. It does not fabricate achievements or guarantee interviews, employment or funding.',
  },
  'niji-setu': {
    shipping: 'Digital communication services follow the confirmed service scope and availability.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Niji Setu masks personal numbers in supported calling arrangements. Availability depends on calling and telecom services.',
  },
  'submit-request': {
    shipping: 'Fulfilment follows the service scope, price and schedule agreed for the request.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Submitting a request does not guarantee acceptance, timing or outcome. Confirm the scope before work begins.',
  },
  'request-amendment': {
    shipping: 'Amendment services follow the confirmed request and relevant recipient conditions.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Acceptance and processing times may depend on the relevant provider or authority.',
  },
  'drop-docs': {
    shipping: 'Document handling follows the confirmed submission and any agreed physical collection or delivery arrangements.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Submit only documents required for the service. Do not share passwords, one-time codes, card credentials or unrequested originals.',
  },
  'vault': {
    shipping: 'Authorised files are supplied digitally, subject to the applicable access conditions.',
    returns: 'Change-of-mind returns may be limited once service work begins or a digital deliverable is supplied. Statutory remedies for deficient or misdescribed services remain available.',
    disclaimer: 'Protect file links and verification codes. Access and retention are governed by the applicable service conditions and Privacy Policy.',
  },
  'shipments-track': {
    shipping: 'Tracking information follows the confirmed shipment and information provided by the courier or fulfilment partner.',
    returns: 'Returns and replacement requests are handled under the original order terms and applicable law.',
    disclaimer: 'Tracking information may change as the courier updates shipment status. Estimated dates do not affect statutory remedies.',
  },
  'request-pickup': {
    shipping: 'Collection follows the confirmed pickup address, schedule and courier arrangements.',
    returns: 'Returns or replacement eligibility follows the relevant purchase and disclosed return conditions.',
    disclaimer: 'Pickup depends on courier availability. Hand over only the items or documents agreed for collection.',
  },
  'merchandise': {
    shipping: 'Physical merchandise is delivered according to the confirmed variant, address, charges and estimated delivery schedule.',
    returns: 'Returns or replacements depend on item condition, customisation and disclosed conditions. Statutory remedies for defective, damaged or misdescribed goods remain available.',
    disclaimer: 'Check the confirmed variant and availability before purchase.',
  },
  'kiosk': {
    shipping: 'Hardware delivery and any installation follow the confirmed order and agreed site requirements.',
    returns: 'Return and replacement eligibility depends on equipment condition and disclosed terms. Statutory remedies for defective goods or deficient installation remain available.',
    disclaimer: 'Hardware availability, installation and connectivity requirements are confirmed for the order.',
  },
  'contribute': {
    shipping: 'Voluntary contributions support published editorial work and do not create a delivery obligation.',
    returns: 'A voluntary contribution does not purchase goods or services.',
    refunds: 'Voluntary contributions are generally non-refundable. Erroneous, duplicate, unauthorised or fraudulent payments may be reviewed for refund or reversal.',
    disclaimer: 'Contributions do not confer editorial influence, ownership or a financial return.',
  },
};

export function productPolicyCopy(
  slug: string,
  name: string,
  disclaimer?: string,
): ProductPolicyCopy {
  const physical = PHYSICAL_PRODUCT_SLUGS.has( slug );
  const base: ProductPolicyCopy = physical
    ? {
        shipping: `Delivery coverage, charges and estimated dates for ${name} follow the confirmed order.`,
        returns: 'Return and replacement eligibility depends on item condition, customisation and disclosed terms. Statutory remedies remain available.',
        refunds: PRODUCT_REFUNDS,
        disclaimer: `Check the confirmed specifications and availability for ${name} before purchasing.`,
      }
    : {
        shipping: `Delivery or service fulfilment for ${name} follows the confirmed scope, schedule and applicable charges.`,
        returns: 'Return, replacement or service-correction eligibility follows the disclosed conditions. Statutory remedies for faulty or misdescribed goods and deficient services remain available.',
        refunds: PRODUCT_REFUNDS,
        disclaimer: `Availability and service-specific conditions for ${name} are confirmed before purchase. Statutory rights remain unaffected.`,
      };

  const override = POLICY_OVERRIDES[ slug ] || {};
  return {
    shipping: override.shipping || base.shipping,
    returns: override.returns || base.returns,
    refunds: override.refunds || base.refunds,
    disclaimer: override.disclaimer || disclaimer || base.disclaimer,
  };
}
