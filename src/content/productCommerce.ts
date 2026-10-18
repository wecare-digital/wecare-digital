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

export const PRODUCT_POLICY_TITLE = 'Shipping, returns & refunds';

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
  // Frozen reference copy: do not rewrite Grahak while propagating the pattern.
  'grahak-os': {
    shipping: 'Delivered digitally; no physical shipping applies. Separate physical items follow their own delivery terms.',
    returns: 'The consultation is digital and cannot be physically returned. Separate physical items follow their own return or replacement terms.',
    disclaimer: 'Your purchase covers one Grahak OS consultation. Deployment, implementation, integrations and third-party platform or messaging charges are separate unless included in writing. Channel availability and approvals may depend on third parties.',
  },
  'bharat-rx': {
    shipping: 'Bharat Rx is fulfilled as a service. Physical delivery applies only when a separately identified item is included in the confirmed order.',
    returns: 'Service work and digital records are not physically returnable. Separate physical items follow their disclosed return terms and applicable law.',
    disclaimer: 'Bharat Rx coordinates requests and records; it is not medical advice, diagnosis or treatment. In an emergency, contact local emergency services.',
  },
  'elsewhere-visa': {
    disclaimer: 'WECARE.DIGITAL can prepare and track the application; approval and processing time remain with the relevant authority.',
  },
  'elsewhere-trip': {
    disclaimer: 'Airlines, hotels, transport providers and authorities control availability, prices, conditions and entry decisions.',
  },
  'expo-week': {
    disclaimer: 'Expo Week is a virtual travel-planning experience; destination availability, supplier offers and travel conditions can change.',
  },
  'dastavez-drafting': {
    disclaimer: 'Drafting is document-preparation and paralegal support, not legal advice or legal representation.',
  },
  'dastavez-registration': {
    disclaimer: 'The relevant authority controls acceptance and processing time; preparation or filing support cannot guarantee its decision.',
  },
  'dastavez-legal-reference': {
    disclaimer: 'Legal Reference is research and source-finding support, not legal advice, representation or a prediction of an authority or court outcome.',
  },
  'guided-resolution': {
    disclaimer: 'Guided Resolution supports preparation and coordination; it does not guarantee agreement, settlement or a third-party decision.',
  },
  'file-assist': {
    disclaimer: 'Case Submission helps organise and submit materials; acceptance and outcomes remain with the receiving party or authority.',
  },
  'paperwork': {
    disclaimer: 'Paperwork is document-preparation support, not legal advice or legal representation.',
  },
  'ritual-guru-puja-guidance': {
    disclaimer: 'Ritual practice varies by family, region and tradition; this guidance is not a claim that one sequence is the only correct form.',
  },
  'ritual-guru-diy-puja-kit': {
    disclaimer: 'Kit contents can vary by puja, tradition and availability; the item list confirmed for the order controls.',
  },
  'anew': {
    disclaimer: 'Anew is written reflection, not therapy, counselling or medical, legal, financial or tax advice. You remain responsible for any decision or action.',
  },
  'hunar-kaushal': {
    disclaimer: 'Kaushal supports learning structure and evidence of progress; it does not issue accredited qualifications or guarantee proficiency, interviews or employment.',
  },
  'hunar-prastuti': {
    disclaimer: 'Prastuti improves presentation of real experience; it does not invent achievements or guarantee interviews, jobs, funding or other outcomes.',
  },
  'niji-setu': {
    disclaimer: 'Niji Setu is designed to keep personal numbers hidden in supported masked-call flows; availability depends on the calling and telecom services used.',
  },
  'submit-request': {
    disclaimer: 'Submitting a request does not guarantee acceptance, timing or outcome; scope is confirmed before work starts.',
  },
  'request-amendment': {
    disclaimer: 'An amendment may depend on a third party or authority; WECARE.DIGITAL cannot guarantee acceptance or processing time.',
  },
  'drop-docs': {
    disclaimer: 'Do not send passwords, one-time codes, card numbers or unrequested originals. Document handling follows the Privacy Policy.',
  },
  'vault': {
    disclaimer: 'Vault access and retention follow the Privacy Policy; documents may not be retained indefinitely or released to unauthorised people.',
  },
  'shipments-track': {
    shipping: 'Tracking is a service. Any collection or delivery follows the fulfilment terms of the underlying order and courier or partner.',
    returns: 'Tracking does not create a return right; eligibility follows the underlying order, disclosed terms and applicable law.',
    disclaimer: 'Tracking shows the latest confirmed status; courier or partner timing is not guaranteed until confirmed.',
  },
  'request-pickup': {
    shipping: 'Pickup timing and hand-off follow the confirmed collection arrangement and any courier or logistics partner used.',
    returns: 'A pickup request is a service action, not a return by itself; any remedy follows the underlying order terms and applicable law.',
    disclaimer: 'Pickup depends on courier or partner availability; do not hand over unrequested original certificates.',
  },
  'merchandise': {
    disclaimer: 'Availability, variant details and fulfilment are those confirmed for the order.',
  },
  'kiosk': {
    disclaimer: 'Hardware availability, installation requirements and connectivity are confirmed for the order.',
  },
  'contribute': {
    disclaimer: 'Contribute is processed for the amount shown at checkout; it does not promise an investment or financial return.',
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
        shipping: `${name} requires physical fulfilment. Delivery coverage, timing and any charge are confirmed before fulfilment.`,
        returns: 'Return or replacement eligibility depends on item condition, customisation, the disclosed product terms and applicable law.',
        refunds: PRODUCT_REFUNDS,
        disclaimer: `The confirmed order details and availability for ${name} control fulfilment.`,
      }
    : {
        shipping: `Fulfilment follows the confirmed scope for ${name}. Any physical delivery, if included, is confirmed separately.`,
        returns: 'Completed service work and digital deliverables are not physically returnable. Separate physical items follow their disclosed terms and applicable law.',
        refunds: PRODUCT_REFUNDS,
        disclaimer: `The confirmed scope and any third-party dependencies for ${name} control the transaction.`,
      };

  const override = POLICY_OVERRIDES[ slug ] || {};
  return {
    shipping: override.shipping || base.shipping,
    returns: override.returns || base.returns,
    refunds: override.refunds || base.refunds,
    disclaimer: override.disclaimer || disclaimer || base.disclaimer,
  };
}
