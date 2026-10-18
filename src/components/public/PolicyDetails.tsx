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
      .wc-policy{margin:8px 0 0;font-family:inherit}
      .wc-policy summary{
        display:inline-flex;
        align-items:center;
        width:max-content;
        padding:6px 9px;
        border-radius:8px;
        cursor:pointer;
        color:var(--public-brand-green);
        background:var(--public-lime-tint);
        font-family:inherit;
        font-size:var(--public-cta-font-size);
        font-weight:var(--public-cta-font-weight);
        line-height:1.4;
        letter-spacing:-.05px;
        text-decoration:underline;
        text-decoration-thickness:1.5px;
        text-underline-offset:3px;
        list-style:none;
        transition:background-color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s;
      }
      .wc-policy summary::-webkit-details-marker{display:none}
      .wc-policy summary:hover{
        background:var(--public-brand-lime);
        text-decoration-color:transparent;
        transform:translateY(-1px);
        box-shadow:0 5px 14px rgba(26,58,42,.1);
      }
      .wc-policy summary:focus-visible{
        background:var(--public-brand-lime);
        text-decoration-color:transparent;
        outline:3px solid var(--public-brand-green);
        outline-offset:3px;
      }
      .wc-policy-body{padding:0}
      .wc-policy p{
        max-width:640px;
        margin:10px 0 0;
        padding:8px 0 8px 12px;
        border-inline-start:3px solid var(--public-brand-lime);
        font-size:var(--public-body-size);
        font-weight:var(--public-body-weight);
        line-height:var(--public-body-leading);
        letter-spacing:var(--public-body-tracking);
        color:var(--public-muted);
        text-wrap:pretty;
      }
      .wc-policy strong{color:var(--public-brand-green);font-weight:700}
      .wc-policy-disclaimer{padding-top:8px;border-top:1px solid var(--public-hairline)}
      @media(prefers-reduced-motion:reduce){
        .wc-policy summary{transition:none}
        .wc-policy summary:hover{transform:none;box-shadow:none}
      }
    `}</style>
  </details>
);

export default PolicyDetails;
