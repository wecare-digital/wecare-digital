import React from 'react';

interface CheckoutActionProps {
  children: React.ReactNode;
  disabled?: boolean;
  busy?: boolean;
  onClick?: () => void;
  ariaLabel?: string;
}

/** Shared checkout CTA: appearance comes from public-interactions.css. */
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
      {/* A ligature renders as unbreakable text before its font loads. Keep
          the decorative icon a fixed-size vector in the button's layout. */}
      <svg className="checkout-action-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false" width="20" height="20">
        <path
          fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
          d="M2 3h3l2.7 12H19l2-7h-8M8 11l3-3-3-3m3 3H6m3 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2Zm9 0a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z"
        />
      </svg>
      <span>{ busy ? 'One moment…' : children }</span>
    </button>
    <style jsx>{`
      .checkout-action{gap:8px;width:max-content;max-width:100%}
      .checkout-action > span{min-width:0;overflow-wrap:anywhere}
      .checkout-action-icon{flex:0 0 20px;width:20px;height:20px}
      .checkout-action[aria-busy='true']{cursor:progress}
    `}</style>
  </>
);

export default CheckoutAction;
