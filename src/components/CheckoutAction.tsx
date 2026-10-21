import React from 'react';

interface CheckoutActionProps {
  children: React.ReactNode;
  disabled?: boolean;
  busy?: boolean;
  onClick?: () => void;
  ariaLabel?: string;
}

/**
 * The compact checkout action used by the Elsewhere activity results.
 *
 * Commerce routes use this same treatment so a customer sees one consistent Checkout action
 * before the cart. Payment-channel choice belongs after cart review, never on the product route.
 */
const CheckoutAction: React.FC<CheckoutActionProps> = ( {
  children,
  disabled = false,
  busy = false,
  onClick,
  ariaLabel,
} ) => (
  <>
    <button
      type="button"
      className="checkout-action"
      onClick={ onClick }
      disabled={ disabled }
      aria-busy={ busy }
      aria-label={ ariaLabel }
    >
      { children }
    </button>
    <style jsx>{`
      .checkout-action{
        display:inline-flex;align-items:center;gap:8px;width:max-content;max-width:100%;
        min-height:var(--tap-min);box-sizing:border-box;padding:6px 9px;border:0;border-radius:8px;
        background:var(--public-lime-tint);color:var(--public-brand-green);font-family:inherit;
        font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);
        line-height:1.4;letter-spacing:-.05px;cursor:pointer;white-space:normal;overflow-wrap:anywhere;
        text-align:start;text-decoration:underline;text-decoration-thickness:1.5px;
        text-underline-offset:3px;touch-action:manipulation;-webkit-tap-highlight-color:transparent;
        transition:background-color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s;
      }
      .checkout-action:active:not(:disabled){
        background:var(--public-brand-lime);text-decoration-color:transparent;
      }
      .checkout-action:focus-visible{
        outline:3px solid var(--public-brand-green);outline-offset:3px;
      }
      .checkout-action:disabled{opacity:.5;cursor:default}
      @media(prefers-reduced-motion:reduce){
        .checkout-action{transition:background-color .18s,text-decoration-color .18s}
      }
    `}</style>
  </>
);

export default CheckoutAction;
