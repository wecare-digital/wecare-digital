import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import PolicyDetails from '../components/public/PolicyDetails';
import { productPolicyCopy } from '../content/productCommerce';
import { productBySlug } from '../content/products';

describe( 'PolicyDetails', () => {
  it( 'keeps Anew disclaimer paragraphs separate', () => {
    const product = productBySlug( 'anew' );
    const policy = productPolicyCopy( product.slug, product.name, product.note );
    const html = renderToStaticMarkup(
      <PolicyDetails
        shipping={ policy.shipping }
        returns={ policy.returns }
        disclaimer={ policy.disclaimer }
      />,
    );

    const disclaimerParagraphs = html.match( /<p[^>]*wc-policy-disclaimer[^>]*>[\s\S]*?<\/p>/g ) || [];
    expect( disclaimerParagraphs ).toHaveLength( 2 );
    expect( disclaimerParagraphs[ 0 ] ).toContain( 'Anew is a guided written reflection' );
    expect( disclaimerParagraphs[ 0 ] ).not.toContain( 'If you need mental-health support' );
    expect( disclaimerParagraphs[ 1 ] ).toContain( 'If you need mental-health support' );
    expect( disclaimerParagraphs[ 1 ] ).toContain( 'Statutory consumer rights remain unaffected.' );
  } );

  it( 'can suppress the statutory-rights footer for a concise embedded disclosure', () => {
    const policy = productPolicyCopy( 'grahak-os', 'Grahak OS' );
    const html = renderToStaticMarkup(
      <PolicyDetails
        shipping={ policy.shipping }
        returns={ policy.returns }
        disclaimer={ policy.disclaimer }
        overview={ null }
        refunds="Approved adjustments are issued as store credit."
        showStatutoryRights={ false }
      />,
    );

    expect( html ).not.toContain( 'Shipping, returns &amp; refunds' );
    expect( html ).not.toContain( 'Statutory consumer rights remain unaffected.' );
    expect( html ).toContain( 'Delivered digitally' );
    expect( html ).toContain( 'Approved adjustments are issued as store credit.' );
  } );
} );
