import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import PolicyDetails from '../components/public/PolicyDetails';
import { productPolicyCopy } from '../content/productCommerce';
import { productBySlug } from '../content/products';

describe( 'PolicyDetails', () => {
  const retiredFooter = [ 'Statutory consumer rights', 'remain unaffected.' ].join( ' ' );

  it( 'renders only the four concise policy concepts', () => {
    const product = productBySlug( 'anew' );
    const policy = productPolicyCopy( product.slug, product.name, product.note );
    const html = renderToStaticMarkup(
      <PolicyDetails
        shipping={ policy.shipping }
        returns={ policy.returns }
        refunds={ policy.refunds }
        disclaimer={ policy.disclaimer }
      />,
    );

    expect( html ).toContain( 'Shipping / fulfilment:' );
    expect( html ).toContain( 'Returns:' );
    expect( html ).toContain( 'Refunds &amp; cancellations:' );
    expect( html ).toContain( 'Disclaimer:' );
    expect( html ).not.toContain( retiredFooter );

    const disclaimerParagraphs = html.match( /<p[^>]*wc-policy-disclaimer[^>]*>[\s\S]*?<\/p>/g ) || [];
    expect( disclaimerParagraphs ).toHaveLength( 1 );
    expect( disclaimerParagraphs[ 0 ] ).toContain( 'Anew is written reflection' );
    expect( disclaimerParagraphs[ 0 ] ).not.toContain( 'If you need mental-health support' );
  } );

  it( 'does not expose retired overview or statutory-footer controls', () => {
    const html = renderToStaticMarkup(
      <PolicyDetails
        shipping="Delivered digitally."
        returns="Nothing physical to return."
        refunds="Approved adjustments are issued as store credit."
        disclaimer="Confirmed transaction terms control."
      />,
    );

    expect( html ).not.toContain( retiredFooter );
    expect( html ).not.toContain( 'Shipping, returns &amp; refunds' );
  } );
} );
