/** Offline behavioural tests for the real website cart and quote modules.
 * No AWS, Razorpay, Meta, customer data or payment traffic.
 */
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { buildSync } from 'esbuild';

function loadModule ( path, windowStub ) {
  const bundle = buildSync( {
    entryPoints: [ path ], bundle: true, platform: 'node', format: 'cjs',
    target: 'node24', define: { 'process.env.NODE_ENV': '"test"' },
    write: false,
  } );
  const module = { exports: {} };
  const runtime = { module, exports: module.exports,
    window: windowStub, process: { env: { NODE_ENV: 'test' } }, console };
  vm.runInNewContext( bundle.outputFiles[0].text, runtime, { timeout: 3000 } );
  return module.exports;
}

const storage = new Map();
const fakeWindow = {
  localStorage: {
    getItem: key => storage.get( key ) ?? null,
    setItem: ( key, value ) => storage.set( key, String( value ) ),
    removeItem: key => storage.delete( key ),
  },
  dispatchEvent: () => {},
  CustomEvent: class CustomEvent {},
};
const cart = loadModule( 'src/lib/cart.ts', fakeWindow );
const { parseCheckoutQuote } = loadModule( 'src/lib/checkoutQuote.ts', fakeWindow );
const { isSignedInvoiceUrl } = loadModule( 'src/lib/customerInvoice.ts', fakeWindow );
assert.equal( isSignedInvoiceUrl( 'https://s3.amazonaws.com/invoice?X-Amz-Signature=abc' ), true );
assert.equal( isSignedInvoiceUrl( 'javascript:alert(1)//Expires=123' ), false );
assert.equal( isSignedInvoiceUrl( 'http://s3.amazonaws.com/invoice?Signature=abc' ), false );

const kiosk = {
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', slug: 'kiosk',
  name: 'Kiosk', formattedPrice: '₹24,999.00',
  variants: [ { id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    label: 'Standard', inStock: true } ],
};
const apparel = {
  id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', slug: 'merchandise',
  name: 'Merchandise', formattedPrice: '₹1,199.00',
  variants: [ { id: 'c0000001-0000-4000-8000-000000000001',
    label: 'Men / S', inStock: true } ],
};

let selected = cart.addItem( kiosk, 3, kiosk.variants[0].id );
assert.equal( selected.length, 1 );
assert.equal( selected[0].quantity, 3 );
selected = cart.addItem( apparel, 2, apparel.variants[0].id );
assert.equal( selected.length, 2, 'new product must not discard the earlier line' );
assert.equal( cart.cartCount(), 5 );
selected = cart.addItem( kiosk, 1, kiosk.variants[0].id );
assert.equal( selected.find( x => x.productId === kiosk.id ).quantity, 4 );
assert.equal( selected.find( x => x.productId === apparel.id ).quantity, 2 );
assert.equal( cart.setQuantity( apparel.id + ':' + apparel.variants[0].id, 5 )
  .find( x => x.productId === apparel.id ).quantity, 5 );

const outgoing = JSON.stringify( cart.toLineItems() );
const lines = JSON.parse( outgoing );
assert.equal( lines.length, 2 );
assert.equal( lines.find( x => x.catalogReference.catalogItemId === kiosk.id ).quantity, 4 );
assert.equal( lines.find( x => x.catalogReference.catalogItemId === apparel.id ).quantity, 5 );
for ( const key of [ 'formattedPrice', 'unitPrice', 'amount', 'currency', 'price' ] ) {
  assert.equal( outgoing.includes( key ), false, key );
}
assert.throws( () => cart.addItem( kiosk, 100, kiosk.variants[0].id ), /quantity/ );
assert.throws( () => cart.setQuantity( kiosk.id + ':' + kiosk.variants[0].id, 100 ), /quantity/ );

// Older persisted carts with multiple products and quantities survive rehydration.
storage.set( 'wecare.cart.v1', JSON.stringify( [
  { productId: kiosk.id, variantId: kiosk.variants[0].id,
    ref: kiosk.id + ':' + kiosk.variants[0].id,
    slug: 'kiosk', name: 'Kiosk', formattedPrice: '₹24,999.00', quantity: 3 },
  { productId: apparel.id, variantId: apparel.variants[0].id,
    ref: apparel.id + ':' + apparel.variants[0].id,
    slug: 'merchandise', name: 'Merchandise',
    formattedPrice: '₹1,199.00', quantity: 4 },
] ) );
assert.equal( cart.readCart().length, 2 );
assert.equal( cart.toLineItems()[1].quantity, 4 );
assert.equal( cart.removeItem( apparel.id + ':' + apparel.variants[0].id ).length, 1 );

// Special contribution and paid service contracts still require one selected line.
selected = cart.setContribution( '7a7a7a7a-7a7a-47a7-87a7-7a7a7a7a7a7a' );
assert.equal( selected.length, 1 );
selected = cart.setServiceLine( '22222222-2222-4222-8222-222222222222',
  'fake-test-intent', 7500 );
assert.equal( selected.length, 1 );
assert.equal( cart.serviceIntentFor( cart.toLineItems( selected ) ), 'fake-test-intent' );

// WhatsApp basket claims are unchanged: no silent truncation of native multi-items.
const before = JSON.stringify( cart.readCart() );
const one = { productId: kiosk.id, variantId: kiosk.variants[0].id, quantity: 1 };
assert.equal( cart.mergeClaimedLines( [ one, one ] ).merged, 0 );
assert.equal( cart.mergeClaimedLines( [ { ...one, quantity: 2 } ] ).merged, 0 );
assert.equal( JSON.stringify( cart.readCart() ), before );

// Server quote: exact integer paise including taxes, fee, discount, delivery.
const good = {
  status: 'QUOTE_READY',
  quote: {
    currency: 'INR', items: [
      { name: 'Kiosk', quantity: 2, unitPricePaise: 10000, totalPaise: 20000 },
      { name: 'Merchandise', quantity: 1, unitPricePaise: 3000, totalPaise: 3000 },
    ],
    charges: {
      merchandisePaise: 23000, supplyGstPaise: 1000,
      deliveryPaise: 200, discountPaise: 500,
      convenienceFeePaise: 50, convenienceGstPaise: 9, totalPaise: 23759,
      discountLabel: 'Delight',
    },
  },
};
const parsed = parseCheckoutQuote( good );
assert.equal( parsed.charges.totalPaise, 23759 );
assert.equal( parsed.items.length, 2 );
assert.equal( parseCheckoutQuote( {
  ...good, quote: { ...good.quote,
    charges: { ...good.quote.charges, totalPaise: 23760 } },
} ), null, 'one-paise mismatch must not allow payment' );
assert.equal( parseCheckoutQuote( {
  ...good, quote: { ...good.quote, items: [
    { ...good.quote.items[0], totalPaise: 1 }, good.quote.items[1],
  ] },
} ), null, 'client line tampering must fail closed' );
assert.equal( parseCheckoutQuote( { ...good, quote: { ...good.quote, currency: 'USD' } } ), null );

console.log( 'Website full-cart and server quote runtime: PASS' );
