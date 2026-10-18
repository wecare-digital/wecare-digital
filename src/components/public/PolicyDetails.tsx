import React from 'react';
import { PRODUCT_POLICY_TEXT, PRODUCT_POLICY_TITLE } from '../../content/productCommerce';

export interface PolicyDetailsCopy {
  shipping: string;
  returns: string;
  disclaimer: string;
}

interface PolicyDetailsProps extends PolicyDetailsCopy {
  className?: string;
}

/**
 * Canonical public commerce-policy disclosure.
 *
 * The UI is deliberately one object across product/service pages; only the copy changes.
 * Cancellation lives inside Refunds, rather than becoming a fourth policy category.
 */
const PolicyDetails: React.FC<PolicyDetailsProps> = ( {
  shipping,
  returns,
  disclaimer,
  className,
} ) => (
  <details className={ ['wc-policy', className].filter( Boolean ).join( ' ' ) }>
    <summary>Policy details</summary>
    <div className="wc-policy-body">
      <p><strong>{ PRODUCT_POLICY_TITLE }:</strong> { PRODUCT_POLICY_TEXT }</p>
      <p><strong>Shipping / fulfilment:</strong> { shipping }</p>
      <p><strong>Returns:</strong> { returns }</p>
      <p><strong>Refunds & cancellations:</strong> Cancellation is handled as part of the refund policy above. Eligible voluntary cancellations or discretionary adjustments are issued as WECARE.DIGITAL store credit valid for 30 calendar days, not as cash or a refund to the original payment method, except where applicable law requires otherwise.</p>
      { disclaimer.split( /\n{2,}/ ).map( ( paragraph, index, paragraphs ) => (
        <p className="wc-policy-disclaimer" key={ index }>
          { index === 0 && <strong>Disclaimer:</strong> }{ index === 0 ? ' ' : '' }{ paragraph.trim() }
          { index === paragraphs.length - 1 && ' Statutory consumer rights remain unaffected.' }
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
        font-size:17px;
        font-weight:600;
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
      .wc-policy-disclaimer{padding-top:8px}
      @media(prefers-reduced-motion:reduce){
        .wc-policy summary{transition:none}
        .wc-policy summary:hover{transform:none;box-shadow:none}
      }
    `}</style>
  </details>
);

export default PolicyDetails;
