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

const LIVE_PRODUCTS: CatalogSnapshotProduct[] = [
  {
    id:'2d5dff1a-2542-5839-9c6e-e65d10fcc643', name:'Grahak OS', slug:'grahak-os',
    formattedPrice:'₹899.00', price:'899.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/grahak-os/',
    descriptionHtml:'<p>Grahak OS from WECARE.DIGITAL.</p>',
    variants:[{ id:'GOS7K4M2', label:'Standard', inStock:true }],
  },
  {
    id:'032039ce-c4ec-5d44-8fdb-d4d9ffb91f02', name:'Sehat', slug:'sehat',
    formattedPrice:'₹850.00', price:'850.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/sehat/',
    descriptionHtml:'<p>Appointments with qualified professionals.</p>',
    variants:[{ id:'BRX5N8Q3', label:'Standard', inStock:true }],
  },
  {
    id:'f74ed861-5945-5893-a0cc-02024511687a', name:'Elsewhere · Visa', slug:'elsewhere-visa',
    formattedPrice:'₹899.00', price:'899.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/elsewhere/visa/',
    descriptionHtml:'<p>Elsewhere · Visa from WECARE.DIGITAL.</p>',
    variants:[{ id:'EVS9P4L7', label:'Standard', inStock:true }],
  },
  {
    id:'619ac1ba-159e-5811-b1b7-98131020cd03', name:'Elsewhere · Trip', slug:'elsewhere-trip',
    formattedPrice:'₹899.00', price:'899.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/elsewhere/trip/',
    descriptionHtml:'<p>Elsewhere · Trip from WECARE.DIGITAL.</p>',
    variants:[{ id:'ETR6M3K8', label:'Standard', inStock:true }],
  },
  {
    id:'331e83ee-384e-5f4e-b348-e205990ba546', name:'Expo Week', slug:'expo-week',
    formattedPrice:'₹899.00', price:'899.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/expo-week/',
    descriptionHtml:'<p>Expo Week from WECARE.DIGITAL.</p>',
    variants:[{ id:'EXP4Q7N5', label:'Standard', inStock:true }],
  },
  {
    id:'94af52d3-d91f-5a84-aab5-2033237aba46', name:'Dastavez · Drafting', slug:'dastavez-drafting',
    formattedPrice:'₹1,499.00', price:'1499.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/dastavez/drafting/',
    descriptionHtml:'<p>Dastavez · Drafting from WECARE.DIGITAL.</p>',
    variants:[{ id:'DDF8K5P2', label:'Standard', inStock:true }],
  },
  {
    id:'3ddcc49c-86f4-59e0-b6ec-b5cffee7ea4d', name:'Dastavez · Registration', slug:'dastavez-registration',
    formattedPrice:'₹899.00', price:'899.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/dastavez/registration/',
    descriptionHtml:'<p>Dastavez · Registration from WECARE.DIGITAL.</p>',
    variants:[{ id:'DRG7M4Q9', label:'Standard', inStock:true }],
  },
  {
    id:'7d7eda2f-943a-5131-852e-32483dda0259', name:'Dastavez · Legal Reference', slug:'dastavez-legal-reference',
    formattedPrice:'₹599.00', price:'599.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/dastavez/legal-reference/',
    descriptionHtml:'<p>Dastavez · Legal Reference from WECARE.DIGITAL.</p>',
    variants:[{ id:'DLR5P8K3', label:'Standard', inStock:true }],
  },
  {
    id:'c3921ac7-32d5-5852-96b8-434161bb53fd', name:'Clear Closure · Guided Resolution', slug:'guided-resolution',
    formattedPrice:'₹1,999.00', price:'1999.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/shop/guided-resolution/',
    descriptionHtml:'<p>Clear Closure · Guided Resolution from WECARE.DIGITAL.</p>',
    variants:[{ id:'CGR9N6M4', label:'Standard', inStock:true }],
  },
  {
    id:'9e51eb4c-00f2-523e-91be-6c9d312adfa7', name:'Clear Closure · Case Submission', slug:'file-assist',
    formattedPrice:'₹1,499.00', price:'1499.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/shop/file-assist/',
    descriptionHtml:'<p>Clear Closure · Case Submission from WECARE.DIGITAL.</p>',
    variants:[{ id:'CCS7K3P8', label:'Standard', inStock:true }],
  },
  {
    id:'78334b88-160f-5811-9827-d958e50dfcde', name:'Clear Closure · Paperwork', slug:'paperwork',
    formattedPrice:'₹899.00', price:'899.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/shop/paperwork/',
    descriptionHtml:'<p>Clear Closure · Paperwork from WECARE.DIGITAL.</p>',
    variants:[{ id:'CPW5M9Q2', label:'Standard', inStock:true }],
  },
  {
    id:'0e0cc8ea-036c-5b57-aec2-8f98e3c2df82', name:'Ritual Guru · Puja Guidance', slug:'ritual-guru-puja-guidance',
    formattedPrice:'₹399.00', price:'399.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/ritual-guru/puja-guidance/',
    descriptionHtml:'<p>Ritual Guru · Puja Guidance from WECARE.DIGITAL.</p>',
    variants:[{ id:'RPG8N4K6', label:'Standard', inStock:true }],
  },
  {
    id:'45af1dfb-fddb-53b0-950c-da703ade9264', name:'Ritual Guru · DIY Puja Kit', slug:'ritual-guru-diy-puja-kit',
    formattedPrice:'₹899.00', price:'899.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/ritual-guru/diy-puja-kit/',
    descriptionHtml:'<p>Ritual Guru · DIY Puja Kit from WECARE.DIGITAL.</p>',
    variants:[{ id:'RDK6P3M9', label:'Standard', inStock:true }],
  },
  {
    id:'6794847f-303e-598e-bdfb-74db0a642fed', name:'Anew', slug:'anew',
    formattedPrice:'₹599.00', price:'599.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/anew/',
    descriptionHtml:'<p>Anew from WECARE.DIGITAL.</p>',
    variants:[{ id:'ANW7Q5K2', label:'Standard', inStock:true }],
  },
  {
    id:'native:hunar-kaushal', name:'Hunar · Kaushal', slug:'hunar-kaushal',
    formattedPrice:'₹99.00', price:'99.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/hunar/kaushal/',
    descriptionHtml:'<p>Skills and learning built around what you want to do next.</p>',
    variants:[{ id:'KSL9M2Q4', label:'Standard', inStock:true }],
  },
  {
    id:'native:hunar-prastuti', name:'Hunar · Prastuti', slug:'hunar-prastuti',
    formattedPrice:'₹299.00', price:'299.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/hunar/prastuti/',
    descriptionHtml:'<p>CV, professional profile and pitch deck built from the same evidence.</p>',
    variants:[{ id:'PST7K4N2', label:'Standard', inStock:true }],
  },
  {
    id:'abe4870e-fae3-59cc-b1a7-9bd28eff048a', name:'Niji Setu', slug:'niji-setu',
    formattedPrice:'₹299.00', price:'299.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/niji-setu/',
    descriptionHtml:'<p>Niji Setu from WECARE.DIGITAL.</p>',
    variants:[{ id:'NJS5K8Q3', label:'Standard', inStock:true }],
  },
  {
    id:'f829697a-b1db-5c4e-bfce-51d1487278a7', name:'Request · Submit Request', slug:'submit-request',
    formattedPrice:'₹99.00', price:'99.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:false, metaEnabled:false, canonicalPath:'/orders/',
    descriptionHtml:'<p>Request · Submit Request from WECARE.DIGITAL.</p>',
    variants:[{ id:'RSR7M2P9', label:'Standard', inStock:true }],
  },
  {
    id:'7133c98d-de8d-5e56-94ff-8d9fea7aa331', name:'Request · Amendment', slug:'request-amendment',
    formattedPrice:'₹199.00', price:'199.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:false, metaEnabled:false, canonicalPath:'/orders/',
    descriptionHtml:'<p>Request · Amendment from WECARE.DIGITAL.</p>',
    variants:[{ id:'RAM5Q8K4', label:'Standard', inStock:true }],
  },
  {
    id:'e1ca7833-5d7d-567b-837c-face04647598', name:'Request · Drop Docs', slug:'drop-docs',
    formattedPrice:'₹199.00', price:'199.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:false, metaEnabled:false, canonicalPath:'/orders/',
    descriptionHtml:'<p>Request · Drop Docs from WECARE.DIGITAL.</p>',
    variants:[{ id:'RDD9P3M7', label:'Standard', inStock:true }],
  },
  {
    id:'d4cfc6e8-10b3-5c47-94c8-3c69f4c03907', name:'Request · Vault', slug:'vault',
    formattedPrice:'₹49.00', price:'49.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:false, metaEnabled:false, canonicalPath:'/orders/',
    descriptionHtml:'<p>Request · Vault from WECARE.DIGITAL.</p>',
    variants:[{ id:'RVT6K4Q8', label:'Standard', inStock:true }],
  },
  {
    id:'f45dec5c-5bcc-5fca-9c50-5f63b57554d2', name:'Shipment · Track', slug:'shipments-track',
    formattedPrice:'₹49.00', price:'49.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:false, metaEnabled:false, canonicalPath:'/orders/',
    descriptionHtml:'<p>Shipment · Track from WECARE.DIGITAL.</p>',
    variants:[{ id:'SHT8M5P3', label:'Standard', inStock:true }],
  },
  {
    id:'166370fe-69a8-5ad2-9f9a-e9ce3f92839c', name:'Shipment · Pickup', slug:'request-pickup',
    formattedPrice:'₹650.00', price:'650.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:false, metaEnabled:false, canonicalPath:'/orders/',
    descriptionHtml:'<p>Shipment · Pickup from WECARE.DIGITAL.</p>',
    variants:[{ id:'SHP7Q4N9', label:'Standard', inStock:true }],
  },
  {
    id:'884281fd-e6e3-537a-b58e-9c6e1342597d', name:'Partner · Merchandise', slug:'merchandise',
    formattedPrice:'₹1,999.00', price:'1999.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/shop/merchandise/',
    descriptionHtml:'<p>Partner · Merchandise from WECARE.DIGITAL.</p>',
    variants:[{ id:'PMD9Q3P6', label:'Standard', inStock:true }],
  },
  {
    id:'84eb1e0c-0d07-5a64-8cf4-cff09e8ee5be', name:'Partner · Kiosk', slug:'kiosk',
    formattedPrice:'₹26,999.00', price:'26999.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/shop/kiosk/',
    descriptionHtml:'<p>Partner · Kiosk from WECARE.DIGITAL.</p>',
    variants:[{ id:'PKS7K5M4', label:'Standard', inStock:true }],
  },
  {
    id:'24fa0f39-330b-5365-b7eb-9caf27ad37f1', name:'Contribute', slug:'contribute',
    formattedPrice:'₹250.00', price:'250.00', currency:'INR',
    inStock:true, visible:true, websiteEnabled:true, metaEnabled:false, canonicalPath:'/shop/contribute/',
    descriptionHtml:'<p>Contribute from WECARE.DIGITAL.</p>',
    variants:[{ id:'CNT5Q2M8', label:'Standard', inStock:true }],
  },
];

export const CATALOG_SNAPSHOT: CatalogSnapshot = {
  source: TESTING ? 'synthetic-test-catalog' : 'aws-native-fresh-catalog',
  catalogVersion: 'SKU_FIRST_V1',
  fetchedAt: '2026-10-17T11:00:00.000Z',
  productCount: TESTING ? TEST_PRODUCTS.length : LIVE_PRODUCTS.length,
  products: TESTING ? TEST_PRODUCTS : LIVE_PRODUCTS,
  variantVerifiedAt: '2026-10-17T11:00:00.000Z',
};

export default CATALOG_SNAPSHOT;
