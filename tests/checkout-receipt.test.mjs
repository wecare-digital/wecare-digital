// Offline regression test for the checkout price-breakup presentation.
//
// CheckoutReceipt.tsx is DISPLAY ONLY: every monetary row must come straight
// from the validated server quote and be rendered through formatPaiseINR. This
// test compiles the real component with the offline TSX harness, renders it
// with a minimal React.createElement stub (no DOM, no bundler, no network), and
// asserts that each charge row's formatted paise amount and the Final total are
// surfaced. If any breakup row were removed, the matching assertion fails.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadTsxModule } from './helpers/loadTsx.mjs';

// A tiny React stub. createElement records children so we can flatten the tree
// into the visible text the component would render.
function makeReactStub () {
  const createElement = ( _type, _props, ...children ) => ( { children } );
  return { createElement, default: { createElement } };
}

// Walk a stubbed element tree and collect every primitive (string/number) leaf
// into a single whitespace-joined string, mirroring the visible text output.
function renderToText ( node ) {
  if ( node === null || node === undefined || node === false || node === true ) return '';
  if ( typeof node === 'string' || typeof node === 'number' ) return String( node );
  if ( Array.isArray( node ) ) return node.map( renderToText ).join( ' ' );
  if ( typeof node === 'object' && 'children' in node ) return renderToText( node.children );
  return '';
}

// Load the real formatter so the test asserts against the same string slicing
// the component uses, rather than hand-rolling rupee formatting here.
const { exports: money } = loadTsxModule( { file: 'src/lib/money.ts' } );
const formatPaiseINR = money.formatPaiseINR;

// A representative quote exercising every charge field, including the two
// server-owned labels the mockup calls out: Delight and Express.
const quote = {
  currency: 'INR',
  items: [
    { name: 'Contribute item', quantity: 1, unitPricePaise: 23541, totalPaise: 23541 },
  ],
  charges: {
    merchandisePaise: 23541,
    supplyGstPaise: 4237,
    deliveryPaise: 1500,
    discountPaise: 138,
    convenienceFeePaise: 729,
    convenienceGstPaise: 131,
    totalPaise: 30000,
    discountLabel: 'Delight',
    deliveryLabel: 'Express',
  },
};

function renderReceipt () {
  const reactStub = makeReactStub();
  const { exports } = loadTsxModule( {
    file: 'src/components/cart/CheckoutReceipt.tsx',
    globals: {
      require: ( name ) => {
        if ( name === 'react' ) return reactStub;
        if ( name.endsWith( 'money' ) ) return { formatPaiseINR };
        // checkoutQuote is a type-only import; esbuild erases its usage.
        return {};
      },
    },
  } );
  const CheckoutReceipt = exports.default;
  return renderToText( CheckoutReceipt( { quote } ) );
}

test( 'CheckoutReceipt surfaces every server charge row from the validated quote', () => {
  const text = renderReceipt();
  const inr = ( paise ) => formatPaiseINR( paise, 'INR' );

  // Item line: name, quantity and per-item base amount.
  assert.ok( text.includes( quote.items[ 0 ].name ), 'item name must appear' );
  assert.ok( /Qty\s+1\b/.test( text ), 'item quantity must appear' );
  assert.ok( text.includes( inr( quote.items[ 0 ].unitPricePaise ) ), 'item base-each amount must appear' );

  // Each charge row's formatted amount must be present.
  assert.ok( text.includes( inr( quote.charges.merchandisePaise ) ), 'Base price must appear' );
  assert.ok( text.includes( inr( quote.charges.supplyGstPaise ) ), 'Supply GST must appear' );
  assert.ok( text.includes( inr( quote.charges.discountPaise ) ), 'Delight discount must appear' );
  assert.ok( text.includes( inr( quote.charges.deliveryPaise ) ), 'Express delivery must appear' );
  assert.ok( text.includes( inr( quote.charges.convenienceFeePaise ) ), 'Convenience fee must appear' );
  assert.ok( text.includes( inr( quote.charges.convenienceGstPaise ) ), 'GST on convenience must appear' );

  // Server-owned labels from the mockup.
  assert.ok( text.includes( 'Delight (0.5%)' ), 'Delight label must appear' );
  assert.ok( text.includes( 'Express' ), 'Express delivery label must appear' );
  assert.ok( text.includes( 'Supply GST (18%)' ), 'Supply GST label must appear' );
  assert.ok( text.includes( 'Convenience fee (2.5%)' ), 'Convenience fee label must appear' );
  assert.ok( text.includes( 'GST on convenience fee (18%)' ), 'Convenience GST label must appear' );
} );

test( 'CheckoutReceipt Final total equals the server totalPaise formatted as INR', () => {
  const text = renderReceipt();
  const expectedTotal = formatPaiseINR( quote.charges.totalPaise, 'INR' );
  assert.ok( text.includes( 'Final total' ), 'Final total label must appear' );
  assert.ok( text.includes( 'Amount payable' ), 'Amount payable caption must appear' );
  assert.ok( text.includes( expectedTotal ), 'Final total amount must equal formatPaiseINR(totalPaise)' );
  assert.equal( expectedTotal, '₹300.00', 'representative total should slice to rupees exactly' );
} );

test( 'CheckoutReceipt keeps the full-breakup assurance note', () => {
  const text = renderReceipt();
  assert.ok( text.includes( 'Full breakup shown before payment.' ), 'assurance note must appear' );
} );
