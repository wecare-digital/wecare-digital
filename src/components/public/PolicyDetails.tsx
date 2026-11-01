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
  /** Set null on the Terms page itself to avoid linking to the current page. */
  termsHref?: string | null;
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
  termsHref = '/terms/',
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
      { termsHref && (
        <a className="wc-policy-terms" href={ termsHref }>Read full Terms of Service</a>
      ) }
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
        font-size:var(--public-supporting-size);font-weight:400;
        line-height:1.55;letter-spacing:normal;
        color:#505852;overflow-wrap:break-word;text-wrap:pretty;
      }
      .wc-policy strong{color:var(--public-brand-green);font-weight:700}
      .wc-policy p.wc-policy-disclaimer{
        margin-block-start:14px;padding-block-start:12px;
        border-block-start:1px solid var(--public-hairline);
      }
      /* One quiet legal destination beneath the content, not a boxed footer
         or several links interrupting the statement labels. */
      .wc-policy-terms{
        display:inline-flex;align-items:center;min-height:var(--tap-min);
        box-sizing:border-box;margin-block-start:10px;padding:6px 0;
        color:var(--public-brand-green);font-family:inherit;
        font-size:var(--public-meta-size);font-weight:600;
        text-decoration:underline;text-underline-offset:3px;
      }
      .wc-policy-terms:hover{text-decoration-thickness:2px}
      .wc-policy-terms:focus-visible{
        outline:2px solid var(--public-brand-green);outline-offset:3px;
      }
      @media(prefers-reduced-motion:reduce){
        .wc-policy summary,.wc-policy summary::after{transition:none}
        .wc-policy summary:hover{transform:none;box-shadow:none}
      }
    `}</style>
  </details>
);

export default PolicyDetails;
