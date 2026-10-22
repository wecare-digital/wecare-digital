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
 * before the cart. Amber distinguishes the paid action from the quieter lime-tint Policy details
 * disclosure. Payment-channel choice belongs after cart review, never on the product route.
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
      aria-label={ busy ? undefined : ariaLabel }
    >
      <span className="checkout-action-icon" aria-hidden="true">shopping_cart_checkout</span>
      <span>{ busy ? 'One moment…' : children }</span>
    </button>
    <style jsx>{`
      .checkout-action{
        display:inline-flex;align-items:center;gap:8px;width:max-content;max-width:100%;
        min-height:var(--tap-min);box-sizing:border-box;padding:8px 12px;
        border:2px solid transparent;border-radius:11px;
        background:var(--public-accent-amber);color:var(--public-brand-green);font-family:inherit;
        font-size:var(--public-cta-font-size);font-weight:var(--public-cta-font-weight);
        line-height:1.4;letter-spacing:-.05px;cursor:pointer;white-space:normal;overflow-wrap:anywhere;
        text-align:start;text-decoration:none;
        touch-action:manipulation;-webkit-tap-highlight-color:transparent;
        transition:background-color .18s,border-color .18s,color .18s,transform .18s,box-shadow .18s;
      }
      .checkout-action-icon{
        font-family:'Material Symbols Rounded';font-size:20px;font-weight:500;line-height:1;
        font-variation-settings:'FILL' 0,'wght' 500,'GRAD' 0,'opsz' 20;
      }
      .checkout-action:active:not(:disabled){
        background:var(--public-accent-amber-tint);border-color:var(--public-accent-amber);
        transform:translateY(0) scale(.98);
      }
      .checkout-action:focus-visible{
        background:#fff;
        outline:3px solid var(--public-brand-green);outline-offset:3px;
      }
      .checkout-action:disabled{opacity:.5;cursor:default}
      .checkout-action[aria-busy='true']{cursor:progress}
      @media(hover:hover) and (pointer:fine){
        .checkout-action:hover:not(:disabled){
          background:#fff;border-color:var(--public-accent-amber);
          transform:translateY(-1px);
          box-shadow:0 5px 14px rgba(240,168,24,.18),0 2px 5px rgba(26,58,42,.08);
        }
      }
      @media(prefers-reduced-motion:reduce){
        .checkout-action{transition:none}
        .checkout-action:hover:not(:disabled){transform:none;box-shadow:none}
      }
    `}</style>
  </>
);

export default CheckoutAction;
