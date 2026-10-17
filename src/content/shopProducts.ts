/** The fresh SKU-first Shop shelf. */
export interface ShopListing {
  slug: string;
  name: string;
  blurb: string;
  sku?: string;
  href: string;
  formattedPrice?: string;
  inStock?: boolean;
  image?: string;
  source: 'product' | 'catalogue';
}

export const SHOP_LISTINGS: ShopListing[] = [
  { slug:'grahak-os', name:'Grahak OS', blurb:'Customer journeys and business workflows in one operating layer.', sku:'GOS7K4M2', href:'/grahak-os/', formattedPrice:'₹899.00', inStock:true, source:'product' },
  { slug:'bharat-rx', name:'Bharat Rx', blurb:'Practical health-document support for everyday needs.', sku:'BRX5N8Q3', href:'/bharat-rx/', formattedPrice:'₹550.00', inStock:true, source:'product' },
  { slug:'elsewhere-visa', name:'Elsewhere · Visa', blurb:'Visa paperwork, preparation and tracking for a planned trip.', sku:'EVS9P4L7', href:'/elsewhere/visa/', formattedPrice:'₹899.00', inStock:true, source:'product' },
  { slug:'elsewhere-trip', name:'Elsewhere · Trip', blurb:'A trip planned around the people actually taking it.', sku:'ETR6M3K8', href:'/elsewhere/trip/', formattedPrice:'₹899.00', inStock:true, source:'product' },
  { slug:'expo-week', name:'Expo Week', blurb:'A virtual travel fair you can walk through from home.', sku:'EXP4Q7N5', href:'/expo-week/', formattedPrice:'₹899.00', inStock:true, source:'product' },
  { slug:'dastavez-drafting', name:'Dastavez · Drafting', blurb:'Structured business documents prepared from the facts you provide.', sku:'DDF8K5P2', href:'/dastavez/drafting/', formattedPrice:'₹1,499.00', inStock:true, source:'product' },
  { slug:'dastavez-registration', name:'Dastavez · Registration', blurb:'Registration paperwork and filing steps organised end to end.', sku:'DRG7M4Q9', href:'/dastavez/registration/', formattedPrice:'₹899.00', inStock:true, source:'product' },
  { slug:'dastavez-legal-reference', name:'Dastavez · Legal Reference', blurb:'Find the source material behind a legal or compliance question.', sku:'DLR5P8K3', href:'/dastavez/legal-reference/', formattedPrice:'₹599.00', inStock:true, source:'product' },
  { slug:'guided-resolution', name:'Clear Closure · Guided Resolution', blurb:'Guided online resolution for a matter that needs a structured path.', sku:'CGR9N6M4', href:'/shop/guided-resolution/', formattedPrice:'₹1,999.00', inStock:true, source:'product' },
  { slug:'file-assist', name:'Clear Closure · Case Submission', blurb:'Prepare and submit the material a case needs.', sku:'CCS7K3P8', href:'/shop/file-assist/', formattedPrice:'₹1,499.00', inStock:true, source:'product' },
  { slug:'paperwork', name:'Clear Closure · Paperwork', blurb:'Paperwork support for an active resolution matter.', sku:'CPW5M9Q2', href:'/shop/paperwork/', formattedPrice:'₹899.00', inStock:true, source:'product' },
  { slug:'ritual-guru-puja-guidance', name:'Ritual Guru · Puja Guidance', blurb:'Clear step-by-step guidance for a puja you are doing yourself.', sku:'RPG8N4K6', href:'/ritual-guru/puja-guidance/', formattedPrice:'₹399.00', inStock:true, source:'product' },
  { slug:'ritual-guru-diy-puja-kit', name:'Ritual Guru · DIY Puja Kit', blurb:'A clearly labelled set of puja essentials for self-led worship.', sku:'RDK6P3M9', href:'/ritual-guru/diy-puja-kit/', formattedPrice:'₹899.00', inStock:true, source:'product' },
  { slug:'anew', name:'Anew', blurb:'A second look at a decision that matters.', sku:'ANW7Q5K2', href:'/anew/', formattedPrice:'₹599.00', inStock:true, source:'product' },
  { slug:'hunar', name:'Hunar', blurb:'Turn your skills and experience into a clearer professional story.', sku:'HNR9M4P6', href:'/hunar/', formattedPrice:'₹599.00', inStock:true, source:'product' },
  { slug:'niji-setu', name:'Niji Setu', blurb:'A private QR bridge for masked calls without exposing your number.', sku:'NJS5K8Q3', href:'/niji-setu/', formattedPrice:'₹299.00', inStock:true, source:'product' },
  { slug:'submit-request', name:'Request · Submit Request', blurb:'Start a new tracked request.', sku:'RSR7M2P9', href:'/submit-request/', formattedPrice:'₹99.00', inStock:true, source:'product' },
  { slug:'request-amendment', name:'Request · Amendment', blurb:'Change a detail on a request already in motion.', sku:'RAM5Q8K4', href:'/request-amendment/', formattedPrice:'₹199.00', inStock:true, source:'product' },
  { slug:'drop-docs', name:'Request · Drop Docs', blurb:'Send the paperwork an existing request needs.', sku:'RDD9P3M7', href:'/drop-docs/', formattedPrice:'₹199.00', inStock:true, source:'product' },
  { slug:'vault', name:'Request · Vault', blurb:'Get a copy of a document held against your request.', sku:'RVT6K4Q8', href:'/vault/', formattedPrice:'₹49.00', inStock:true, source:'product' },
  { slug:'shipments-track', name:'Shipment · Track', blurb:'Track what is on its way.', sku:'SHT8M5P3', href:'/shipments/', formattedPrice:'₹49.00', inStock:true, source:'product' },
  { slug:'request-pickup', name:'Shipment · Pickup', blurb:'Arrange collection of paperwork for an existing request.', sku:'SHP7Q4N9', href:'/request-pickup/', formattedPrice:'₹650.00', inStock:true, source:'product' },
  { slug:'referral-partner', name:'Partner · Referral', blurb:'Introduce someone who would find WECARE.DIGITAL useful.', sku:'PRF5M8K2', href:'/refer-and-earn/', formattedPrice:'₹899.00', inStock:true, source:'product' },
  { slug:'merchandise', name:'Partner · Merchandise', blurb:'WECARE.DIGITAL merchandise.', sku:'PMD9Q3P6', href:'/shop/merchandise/', formattedPrice:'₹1,999.00', inStock:true, source:'product' },
  { slug:'kiosk', name:'Partner · Kiosk', blurb:'A WECARE.DIGITAL kiosk setup.', sku:'PKS7K5M4', href:'/shop/kiosk/', formattedPrice:'₹26,999.00', inStock:true, source:'product' },
  { slug:'contribute', name:'Contribute', blurb:'A voluntary ₹250 contribution to support the work.', sku:'CNT5Q2M8', href:'/shop/contribute/', formattedPrice:'₹250.00', inStock:true, source:'product' },
];

export const SHOP_LISTINGS_PER_PAGE = 6;
export const shopListingPageCount = ( total: number ): number =>
  Math.max( 1, Math.ceil( total / SHOP_LISTINGS_PER_PAGE ) );
export const shopListingPageHref = ( page: number ): string =>
  ( page <= 1 ? '/shop/' : `/shop/page/${page}/` );
