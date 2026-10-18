export const PRODUCT_SKU_BY_SLUG: Readonly<Record<string, string>> = {
  'grahak-os': 'GOS7K4M2',
  'bharat-rx': 'BRX5N8Q3',
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
  'Cancellation may not be available once work starts. Approved cancellations or adjustments are issued as WECARE.DIGITAL store credit valid for 30 calendar days. No cash or original-payment-method refund is provided unless required by law.';

export interface ProductPolicyCopy {
  shipping: string;
  returns: string;
  refunds: string;
  disclaimer: string;
}

const PHYSICAL_PRODUCT_SLUGS = new Set<string>( [
  'ritual-guru-diy-puja-kit',
  'merchandise',
] );

const POLICY_OVERRIDES: Readonly<Record<string, Partial<ProductPolicyCopy>>> = {
  // Grahak OS is the copy benchmark for the rest of the site.
  'grahak-os': {
    shipping: 'Delivered digitally; no physical shipping applies. Separate physical items follow their own delivery terms.',
    returns: 'The consultation is digital and cannot be physically returned. Separate physical items follow their own return or replacement terms.',
    disclaimer: 'Your purchase covers one Grahak OS consultation. Deployment, implementation, integrations and third-party platform or messaging charges are separate unless included in writing. Channel availability and approvals may depend on third parties.',
  },
  'bharat-rx': {
    shipping: 'Bharat Rx is fulfilled as a service; physical delivery applies only if an item is included.',
    returns: 'Service work and digital records are not returnable; physical items follow their disclosed terms.',
    disclaimer: 'Bharat Rx coordinates requests and records; it is not medical advice, diagnosis or treatment. In an emergency, contact local emergency services.',
  },
  'elsewhere-visa': {
    disclaimer: 'We can prepare and track the application; approval and timing remain with the relevant authority.',
  },
  'elsewhere-trip': {
    disclaimer: 'Providers and authorities control availability, prices, conditions and entry decisions.',
  },
  'expo-week': {
    disclaimer: 'Expo Week is virtual planning; destination availability, supplier offers and travel conditions can change.',
  },
  'dastavez-drafting': {
    disclaimer: 'Drafting is document-preparation support, not legal advice or representation.',
  },
  'dastavez-registration': {
    disclaimer: 'The relevant authority controls acceptance and timing; filing support cannot guarantee its decision.',
  },
  'dastavez-legal-reference': {
    disclaimer: 'Legal Reference is research support, not legal advice, representation or an outcome prediction.',
  },
  'guided-resolution': {
    disclaimer: 'Guided Resolution supports preparation and coordination; outcomes are not guaranteed.',
  },
  'file-assist': {
    disclaimer: 'Case Submission helps organise and submit materials; acceptance and outcomes remain with the recipient.',
  },
  'paperwork': {
    disclaimer: 'Paperwork is document-preparation support, not legal advice or representation.',
  },
  'ritual-guru-puja-guidance': {
    disclaimer: 'Ritual practice varies by family, region and tradition; this guidance is not the only valid sequence.',
  },
  'ritual-guru-diy-puja-kit': {
    disclaimer: 'Kit contents can vary by puja, tradition and availability; the confirmed item list controls.',
  },
  'anew': {
    disclaimer: 'Anew is written reflection, not therapy or professional medical, legal, financial or tax advice.',
  },
  'hunar-kaushal': {
    disclaimer: 'Kaushal supports learning and evidence of progress; it does not issue accredited qualifications or guarantee employment.',
  },
  'hunar-prastuti': {
    disclaimer: 'Prastuti presents real experience; it does not invent achievements or guarantee interviews, jobs or funding.',
  },
  'niji-setu': {
    disclaimer: 'Niji Setu masks personal numbers in supported call flows; availability depends on calling and telecom services.',
  },
  'submit-request': {
    disclaimer: 'Submitting a request does not guarantee acceptance, timing or outcome; scope is confirmed before work starts.',
  },
  'request-amendment': {
    disclaimer: 'Acceptance and timing can depend on a third party or authority and are not guaranteed.',
  },
  'drop-docs': {
    disclaimer: 'Do not send passwords, one-time codes, card numbers or unrequested originals.',
  },
  'vault': {
    disclaimer: 'Vault access and retention follow the Privacy Policy; storage is not indefinite.',
  },
  'shipments-track': {
    shipping: 'Tracking follows the underlying order and courier or partner.',
    returns: 'Return rights come from the underlying order, not tracking.',
    disclaimer: 'Tracking shows the latest confirmed status; courier timing is not guaranteed.',
  },
  'request-pickup': {
    shipping: 'Pickup follows the confirmed collection arrangement and courier or partner.',
    returns: 'A pickup request is not a return; remedies follow the underlying order.',
    disclaimer: 'Pickup depends on courier availability; do not hand over unrequested original certificates.',
  },
  'merchandise': {
    disclaimer: 'Availability, variant details and fulfilment are those confirmed for the order.',
  },
  'kiosk': {
    disclaimer: 'Hardware availability, installation requirements and connectivity are confirmed for the order.',
  },
  'contribute': {
    disclaimer: 'Contribute is processed for the amount shown at checkout; it does not promise a financial return.',
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
        shipping: `${name} requires physical fulfilment; delivery coverage, timing and any charge are confirmed before fulfilment.`,
        returns: 'Returns or replacements depend on item condition, customisation, disclosed terms and applicable law.',
        refunds: PRODUCT_REFUNDS,
        disclaimer: `The confirmed order details and availability for ${name} control fulfilment.`,
      }
    : {
        shipping: `Fulfilment follows the confirmed scope for ${name}; physical delivery, if included, is confirmed separately.`,
        returns: 'Completed service work and digital deliverables are not returnable; physical items follow their disclosed terms.',
        refunds: PRODUCT_REFUNDS,
        disclaimer: `The confirmed scope and third-party dependencies for ${name} control the transaction.`,
      };

  const override = POLICY_OVERRIDES[ slug ] || {};
  return {
    shipping: override.shipping || base.shipping,
    returns: override.returns || base.returns,
    refunds: override.refunds || base.refunds,
    disclaimer: override.disclaimer || disclaimer || base.disclaimer,
  };
}
