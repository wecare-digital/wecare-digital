import React from 'react';
import { PRODUCT_REFUNDS } from '../../content/productCommerce';

export interface PolicyDetailsCopy {
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
      /* Keep the existing light-lime disclosure button and four lime-ruled paragraphs.
         Every public PolicyDetails consumer now uses this single, unboxed style. */
      .wc-policy{
        margin:8px 0 0;max-inline-size:700px;min-inline-size:0;
        font-family:var(--font-sans);
      }
      .wc-policy summary{
        display:inline-flex;align-items:center;gap:12px;
        inline-size:max-content;max-inline-size:100%;
        min-height:calc(var(--tap-min) + 1px);box-sizing:border-box;
        padding:6px 12px;border-radius:9px;cursor:pointer;
        color:var(--public-brand-green);background:var(--public-lime-tint);
        font-family:inherit;font-size:var(--public-cta-font-size);
        font-weight:var(--public-cta-font-weight);line-height:1.4;
        letter-spacing:-.05px;white-space:normal;overflow-wrap:anywhere;
        text-align:start;text-decoration:underline;
        text-decoration-thickness:1.5px;text-underline-offset:3px;
        list-style:none;
        transition:background-color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s;
      }
      .wc-policy summary::-webkit-details-marker{display:none}
      .wc-policy summary::after{
        content:'';display:inline-block;flex:none;
        inline-size:8px;block-size:8px;margin-inline-end:3px;
        border-inline-end:2px solid currentColor;border-block-end:2px solid currentColor;
        transform:rotate(45deg);transition:transform .18s;
      }
      .wc-policy[open] summary::after{transform:rotate(225deg)}
      .wc-policy summary:hover{
        background:var(--public-brand-lime);
        text-decoration-color:transparent;
        transform:translateY(-1px);
        box-shadow:0 5px 14px rgba(26,58,42,.1);
      }
      .wc-policy summary:focus-visible{
        background:var(--public-brand-lime);text-decoration-color:transparent;
        outline:3px solid var(--public-brand-green);outline-offset:3px;
      }
      .wc-policy-body{padding:4px 0 0}
      .wc-policy p{
        max-inline-size:680px;margin:10px 0 0;
        padding:8px 0 8px 12px;
        border-inline-start:3px solid var(--public-brand-lime);
        /* Match Home's 20px narrative type scale while preserving the softer
           secondary grey from the original policy design, not near-black copy. */
        font-size:var(--public-body-size);
        font-weight:var(--public-body-weight);
        line-height:var(--public-body-leading);
        letter-spacing:var(--public-body-tracking);
        color:var(--public-muted);
        overflow-wrap:break-word;text-wrap:pretty;
      }
      .wc-policy strong{color:var(--public-brand-green);font-weight:700}
      .wc-policy p.wc-policy-disclaimer{
        margin-block-start:14px;padding-block-start:12px;
        border-block-start:1px solid var(--public-hairline);
      }
      @media(prefers-reduced-motion:reduce){
        .wc-policy summary,.wc-policy summary::after{transition:none}
        .wc-policy summary:hover{transform:none;box-shadow:none}
      }
    `}</style>
  </details>
);

export default PolicyDetails;
