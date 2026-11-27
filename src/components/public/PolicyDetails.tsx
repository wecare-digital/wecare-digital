import React from 'react';
import { PRODUCT_REFUNDS } from '../../content/productCommerce';

interface PolicyDetailsCopy {
  shipping: string;
  returns: string;
  disclaimer: string;
}

interface PolicyDetailsProps extends PolicyDetailsCopy {
  className?: string;
  refunds?: string;
}

/**
 * Canonical public commerce-policy disclosure.
 *
 * Keep this to four concise concepts only: fulfilment, returns,
 * refunds/cancellations, and disclaimer. No extra preface or legal footer
 * is appended here.
 */
const PolicyDetails: React.FC<PolicyDetailsProps> = ( {
  shipping,
  returns,
  disclaimer,
  className,
  refunds = PRODUCT_REFUNDS,
} ) => (
  <details className={ ['wc-policy', className].filter( Boolean ).join( ' ' ) }>
    <summary>Policy details</summary>
    <div className="wc-policy-body">
      <p><strong>Shipping / fulfilment:</strong> { shipping }</p>
      <p><strong>Returns:</strong> { returns }</p>
      <p><strong>Refunds & cancellations:</strong> { refunds }</p>
      { disclaimer.split( /\n{2,}/ ).map( ( paragraph, index ) => (
        <p className="wc-policy-disclaimer" key={ index }>
          { index === 0 && <strong>Disclaimer:</strong> }{ index === 0 ? ' ' : '' }{ paragraph.trim() }
        </p>
      ) ) }
    </div>

    <style jsx>{`
      /* Use the same Home colour accents on the four policy text rules.
         Keep the original underlined lime disclosure, without a decorative
         arrow, and retain the shared unboxed layout on all policy pages. */
      .wc-policy{
        margin:8px 0 0;max-inline-size:700px;min-inline-size:0;
        font-family:var(--font-sans);
      }
      .wc-policy summary{inline-size:max-content;max-inline-size:100%;list-style:none}
      .wc-policy summary::-webkit-details-marker{display:none}
      .wc-policy-body{padding:4px 0 0}
      .wc-policy p{
        max-inline-size:680px;margin:14px 0 0;
        padding:9px 0 9px 14px;
        border-inline-start:3px solid var(--public-brand-lime);
        /* Match Home's 20px narrative type scale while preserving the softer
           secondary grey from the original policy design, not near-black copy. */
        font-size:var(--public-body-size);
        font-weight:var(--public-body-weight);
        line-height:var(--public-body-leading);
        letter-spacing:var(--public-body-tracking);
        color:var(--public-muted);
        overflow-wrap:anywhere;text-wrap:pretty;
      }
      /* As on Home: green, blue and purple accent rules, followed by
         forest green for the disclaimer. Hues are decorative, not status. */
      .wc-policy p:nth-of-type(1){border-inline-start-color:var(--public-accent-green)}
      .wc-policy p:nth-of-type(2){border-inline-start-color:var(--public-accent-blue)}
      .wc-policy p:nth-of-type(3){border-inline-start-color:var(--public-accent-purple)}
      .wc-policy p.wc-policy-disclaimer{border-inline-start-color:var(--public-brand-green)}
      .wc-policy strong{color:var(--public-brand-green);font-weight:700}
      .wc-policy p.wc-policy-disclaimer{
        margin-block-start:20px;padding-block-start:13px;
        border-block-start:1px solid var(--public-hairline);
      }
    `}</style>
  </details>
);

export default PolicyDetails;
