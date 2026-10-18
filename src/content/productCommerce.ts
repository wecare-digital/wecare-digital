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

export const PRODUCT_POLICY_TEXT =
  'Shipping or fulfilment timing depends on the product or service and is disclosed for the transaction. Return eligibility depends on the product or service, its condition, whether work or customisation has started, and applicable law. Refunds include approved voluntary cancellations and discretionary adjustments: cash refunds and refunds to the original payment method are not available; where eligible, we issue WECARE.DIGITAL store credit instead. Store credit issued under this policy is valid for 30 calendar days from the date of issue; any unused balance expires at the end of that period, unless applicable law requires otherwise. This does not limit any refund, replacement, return or other remedy required by applicable law.';


export interface ProductPolicyCopy {
  shipping: string;
  returns: string;
  disclaimer: string;
}

const PHYSICAL_PRODUCT_SLUGS = new Set<string>( [
  'ritual-guru-diy-puja-kit',
  'merchandise',
] );

const POLICY_OVERRIDES: Readonly<Record<string, Partial<ProductPolicyCopy>>> = {
  'grahak-os': {
    shipping: 'The Grahak OS consultation is delivered digitally, so no physical shipping applies. Any separately ordered physical item follows the shipping terms disclosed for that item.',
    returns: 'There is no physical return for the Grahak OS consultation. If a separate physical item is supplied, return or replacement eligibility follows its product-specific terms and applicable law.',
    disclaimer: 'The purchase shown on this page covers the stated Grahak OS consultation only. Full deployment, implementation, integrations and third-party platform or messaging charges are separate unless expressly included in writing. Channel availability, approvals and delivery can depend on third-party providers and your configuration.',
  },
  'bharat-rx': {
    shipping: 'Bharat Rx is fulfilled as a service, so no physical shipping applies unless a separately identified physical item is included in your confirmed order.',
    returns: 'Service work and digital records are not physically returnable. Any separately supplied physical item follows the return or replacement terms disclosed for that item and applicable law.',
    disclaimer: 'Bharat Rx coordinates requests and records. It is not a substitute for professional medical advice, diagnosis or treatment, and nothing on the page is medical advice. In an emergency, contact local emergency services.',
  },
  'shipments-track': {
    shipping: 'Tracking itself is a service. Any underlying collection or delivery follows the shipping or fulfilment terms of the relevant order, courier or partner.',
    returns: 'Track does not itself create a return right. Return or replacement eligibility is determined by the underlying order, the applicable product or service terms and applicable law.',
  },
  'request-pickup': {
    shipping: 'Pickup timing and hand-off depend on the confirmed collection arrangement and, where used, the relevant courier or logistics partner.',
    returns: 'A pickup request is a service action rather than a returned product by itself. Any return, replacement or other remedy follows the underlying order terms and applicable law.',
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
        shipping: 'This item requires physical fulfilment. Shipping timing, destination coverage and any delivery charge are disclosed or confirmed for the transaction before fulfilment.',
        returns: 'Return or replacement eligibility depends on the item condition, whether it was customised or used, the product-specific terms disclosed for the transaction and applicable law.',
        disclaimer: `${name} is supplied subject to the product details, availability and fulfilment conditions confirmed for your order.`,
      }
    : {
        shipping: 'Fulfilment follows the product or service details disclosed for the transaction. If physical delivery is involved, the delivery terms are confirmed before fulfilment.',
        returns: 'Service work and digital deliverables are not physically returnable. Any physical item supplied separately follows its disclosed return or replacement terms and applicable law.',
        disclaimer: `The scope, inclusions, timing and any third-party dependencies for ${name} are those confirmed for your transaction. Nothing on this page guarantees an outcome controlled by a third party, supplier, authority or platform.`,
      };

  const override = POLICY_OVERRIDES[ slug ] || {};
  return {
    shipping: override.shipping || base.shipping,
    returns: override.returns || base.returns,
    disclaimer: disclaimer || override.disclaimer || base.disclaimer,
  };
}
