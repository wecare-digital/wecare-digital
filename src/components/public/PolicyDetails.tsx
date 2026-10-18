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
      .wc-policy{
        margin:12px 0 0;
        border:1px solid var(--public-hairline);
        border-radius:14px;
        background:#fcfdfb;
        color:var(--public-body);
        overflow:hidden;
      }
      .wc-policy summary{
        min-height:var(--public-cta-height);
        display:flex;
        align-items:center;
        padding:0 18px;
        cursor:pointer;
        color:var(--public-brand-green);
        font-size:17px;
        font-weight:700;
        line-height:1.4;
        list-style:none;
        transition:background-color .2s,transform .2s,box-shadow .2s;
      }
      .wc-policy summary::-webkit-details-marker{display:none}
      .wc-policy summary::after{
        content:'+';
        margin-inline-start:auto;
        font-size:var(--public-card-size);
        font-weight:600;
        line-height:1;
      }
      .wc-policy[open] summary::after{content:'−'}
      .wc-policy summary:hover{background:var(--public-lime-tint)}
      .wc-policy summary:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:-3px}
      .wc-policy-body{
        padding:0 18px 18px;
        border-top:1px solid var(--public-hairline);
      }
      .wc-policy p{
        margin:14px 0 0;
        font-size:var(--public-body-size);
        font-weight:var(--public-body-weight);
        line-height:var(--public-body-leading);
        letter-spacing:var(--public-body-tracking);
        color:var(--public-body);
      }
      .wc-policy strong{color:var(--public-brand-green);font-weight:700}
      .wc-policy-disclaimer{
        padding-top:14px;
        border-top:1px solid var(--public-hairline);
      }
      @media(prefers-reduced-motion:reduce){
        .wc-policy summary{transition:none}
      }
    `}</style>
  </details>
);

export default PolicyDetails;
