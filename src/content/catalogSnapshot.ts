export interface CatalogSnapshotVariant {
  id: string;
  label?: string;
  inStock?: boolean;
  [key: string]: unknown;
}

export interface CatalogSnapshotProduct {
  id?: string;
  name?: string;
  slug?: string;
  formattedPrice?: string;
  price?: string;
  currency?: string;
  inStock?: boolean;
  visible?: boolean;
  descriptionHtml?: string;
  image?: string;
  canonicalPath?: string;
  websiteEnabled?: boolean;
  metaEnabled?: boolean;
  variantCount?: number;
  variants?: CatalogSnapshotVariant[];
  [key: string]: unknown;
}

export interface CatalogSnapshot {
  source?: string;
  catalogVersion?: string;
  fetchedAt?: string;
  productCount?: number;
  products: CatalogSnapshotProduct[];
  variantVerifiedAt?: string;
  [key: string]: unknown;
}

const TESTING = process.env.NODE_ENV === 'test';

const TEST_PRODUCTS: CatalogSnapshotProduct[] = [
  {
    id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', name:'Kiosk', slug:'kiosk',
    formattedPrice:'₹24,999.00', price:'24999.00', currency:'INR', inStock:true, visible:true,
    descriptionHtml:'<p>Put your location to work.</p><p>A synthetic product used only by tests.</p>',
    variants:[{ id:'dddddddd-dddd-4ddd-8ddd-dddddddddddd', label:'Standard', inStock:true }],
  },
  {
    id:'cccccccc-cccc-4ccc-8ccc-cccccccccccc', name:'Merchandise', slug:'merchandise',
    formattedPrice:'₹1,199.00', price:'1199.00', currency:'INR', inStock:true, visible:true,
    descriptionHtml:'<p>Wear it.</p><p>A synthetic multi-option product used only by tests.</p>',
    variants:[
      { id:'c0000001-0000-4000-8000-000000000001', label:'Men’s / S', inStock:true },
      { id:'c0000002-0000-4000-8000-000000000002', label:'Men’s / M', inStock:true },
      { id:'c0000003-0000-4000-8000-000000000003', label:'Men’s / L', inStock:true },
      { id:'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', label:'Men’s / XL', inStock:true },
      { id:'c0000005-0000-4000-8000-000000000005', label:'Men’s / XXL', inStock:true },
      { id:'c0000006-0000-4000-8000-000000000006', label:'Women’s / S', inStock:true },
      { id:'c0000007-0000-4000-8000-000000000007', label:'Women’s / M', inStock:true },
      { id:'c0000008-0000-4000-8000-000000000008', label:'Women’s / L', inStock:true },
      { id:'c0000009-0000-4000-8000-000000000009', label:'Women’s / XL', inStock:true },
      { id:'c0000010-0000-4000-8000-000000000010', label:'Women’s / XXL', inStock:true },
    ],
  },
  {
    id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', name:'Anew', slug:'anew',
    formattedPrice:'₹599.00', price:'599.00', currency:'INR', inStock:true, visible:true,
    canonicalPath:'/anew/',
    descriptionHtml:'<p>Reflection into clarity and action.</p><p>A synthetic product used only by tests.</p>',
    variants:[{ id:'abababab-abab-4bab-8bab-abababababab', label:'Standard', inStock:true }],
  },
  {
    id:'77777777-7777-4777-8777-777777777777', name:'Contribute', slug:'contribute',
    formattedPrice:'₹250.00', price:'250.00', currency:'INR', inStock:true, visible:true,
    descriptionHtml:'<p>Contribute to WECARE.DIGITAL.</p><p>A synthetic payment vehicle used only by tests.</p>',
    variants:[{ id:'7a7a7a7a-7a7a-47a7-87a7-7a7a7a7a7a7a', label:'₹250', inStock:true }],
  },
  {
    id:'11111111-1111-4111-8111-111111111111', name:'Request', slug:'request-services',
    formattedPrice:'₹99.00', price:'99.00', currency:'INR', inStock:true, visible:true,
    descriptionHtml:'<p>Request services.</p><p>A synthetic payment vehicle used only by tests.</p>',
    variants:[
      { id:'22222222-2222-4222-8222-222222222222', label:'Submit Request', inStock:true },
      { id:'33333333-3333-4333-8333-333333333333', label:'Request Amendment', inStock:true },
      { id:'44444444-4444-4444-8444-444444444444', label:'Drop Docs', inStock:true },
      { id:'55555555-5555-4555-8555-555555555555', label:'Vault', inStock:true },
      { id:'66666666-6666-4666-8666-666666666666', label:'Request Pickup', inStock:true },
    ],
  },
];

/**
 * Production catalog is intentionally empty. Synthetic rows exist only under Vitest so generic
 * cart/catalog behavior remains testable without any retired production identity.
 */
export const CATALOG_SNAPSHOT: CatalogSnapshot = {
  source: TESTING ? 'synthetic-test-catalog' : 'clean-slate',
  catalogVersion: 'SKU_FIRST_V1',
  fetchedAt: '2026-10-17T00:00:00.000Z',
  productCount: TESTING ? TEST_PRODUCTS.length : 0,
  products: TESTING ? TEST_PRODUCTS : [],
  variantVerifiedAt: '2026-10-17T00:00:00.000Z',
};

export default CATALOG_SNAPSHOT;
