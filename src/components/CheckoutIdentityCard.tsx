import React from 'react';

import { StoredAddress } from './AddressFields';

/**
 * THE RETURNING CUSTOMER SEES WHAT IS ON FILE, AND WHAT IS VERIFIED, BEFORE THEY PAY.
 *
 * Four rows - Name, Email, Phone, Deliver - plus three edit affordances. Rendered on /cart once
 * the readiness question has answered PROFILE_READY, in place of the form a first-time customer
 * gets. A returning customer should not be asked for details they already gave us.
 *
 * THE DELIVER LINE IS `address.fullAddress`, RENDERED VERBATIM. THIS IS THE LOAD-BEARING RULE.
 * ------------------------------------------------------------------------------------------
 * `fullAddress` is derived SERVER-SIDE by `identity.address.full_address`, and that same string
 * is what reaches Wix and the invoice. Composing this line here from the six form fields would be
 * a SECOND rendering of the address, with its own separator and ordering choices, that can drift
 * from the server one - and then the card would be reassuring the customer about a string nobody
 * downstream uses. So this component does no composition at all. It is also why the stored
 * `fullAddress` ends with the country: the server appends it.
 * `src/test/CheckoutIdentityCard.test.tsx` pins this with a fixture whose components would
 * compose a DIFFERENT line, so a re-composition fails the build rather than shipping quietly.
 *
 * WHAT IS VERIFIED IS STATED INLINE RATHER THAN IMPLIED
 * -----------------------------------------------------
 *   - the PHONE carries "verified", which is always true because it IS the session - there is no
 *     path to this card without having signed in on that number. The badge deliberately does NOT
 *     name the mechanism: how we proved it is our business, not the customer's, and the owner
 *     asked for plain customer copy here rather than an internal-sounding label;
 *   - the EMAIL carries "verified", because a one-time code proved it before it was stored;
 *   - the ADDRESS carries NO badge. Nobody verified it. A tick there would be a claim we cannot
 *     support, and the customer is the only authority on where they live.
 *
 * THERE IS NO EDIT AFFORDANCE FOR THE PHONE, DELIBERATELY. It is the identity the contact row is
 * keyed on; changing it is a different account, not an edit. Offering the control and then
 * refusing would be worse than not offering it.
 *
 * THE CARD STAYS WHILE THE EDITOR IS OPEN, WITH ITS BUTTONS DISABLED. Staying means the customer
 * can see what they are changing FROM. Disabling means a second affordance cannot swap the mode
 * out from under a half-typed edit.
 */

export interface CheckoutIdentity {
  name: string;
  email: string;
  phone: string;
  address: StoredAddress | null;
}

/**
 * The phone as the design mock shows it - `+91 81006 ·····`. The customer knows their own
 * number, and a checkout page is routinely read over someone's shoulder, so the last digits are
 * not needed on screen to confirm which account this is. Degrades to the raw value for anything
 * too short to mask meaningfully rather than inventing digits.
 */
export function maskPhone ( phone: string ): string {
  const raw = String( phone || '' );
  const digits = raw.replace( /\D/g, '' );
  if ( digits.length < 7 ) return raw;
  const hidden = '·'.repeat( Math.min( 5, digits.length - 6 ) );
  const shown = digits.slice( 0, digits.length - hidden.length );
  const country = digits.length > 10 ? digits.slice( 0, digits.length - 10 ) : '';
  const local = country ? shown.slice( country.length ) : shown;
  return `+${ country }${ country ? ' ' : '' }${ local } ${ hidden }`;
}

interface Props {
  identity: CheckoutIdentity;
  /** True while a CheckoutProfile editor is mounted below this card. */
  editorOpen?: boolean;
  onEditName: () => void;
  onChangeEmail: () => void;
  onEditAddress: () => void;
}

const CheckoutIdentityCard: React.FC<Props> = ( {
  identity, editorOpen, onEditName, onChangeEmail, onEditAddress,
} ) => {
  const locked = !!editorOpen;

  /*
   * The four rows are written out inline. styled-jsx only stamps its scoping class onto JSX in
   * the same return tree as the <style jsx> block below, so a row helper would render with
   * unhashed class names and lose every rule - the failure PillButton and RotatingHero both
   * record. Do not refactor these into a map.
   */
  return (
    <section className="identity-card" aria-labelledby="identity-card-title">
      <div className="identity-head">
        <p className="identity-eyebrow">Checkout details</p>
        <h2 id="identity-card-title">Ready to pay</h2>
      </div>

      <dl className="identity-rows">
        <div className="identity-row">
          <dt>Name</dt>
          <dd>
            <span className="identity-value">{ identity.name }</span>
          </dd>
          <button type="button" onClick={ onEditName } disabled={ locked }>Edit name</button>
        </div>

        <div className="identity-row">
          <dt>Email</dt>
          <dd>
            <span className="identity-value">{ identity.email }</span>
            <span className="identity-badge">✓ verified</span>
          </dd>
          <button type="button" onClick={ onChangeEmail } disabled={ locked }>Change email</button>
        </div>

        <div className="identity-row">
          <dt>Phone</dt>
          <dd>
            <span className="identity-value">{ maskPhone( identity.phone ) }</span>
            <span className="identity-badge">✓ verified</span>
          </dd>
        </div>

        <div className="identity-row">
          <dt>Deliver</dt>
          <dd>
            { /* VERBATIM. No composition from the components - see the docblock. */ }
            <span className="identity-value">{ identity.address ? identity.address.fullAddress : '' }</span>
          </dd>
          <button type="button" onClick={ onEditAddress } disabled={ locked }>Edit address</button>
        </div>
      </dl>

      <style jsx>{`
        .identity-card{
          margin:28px 0 0;padding:22px;border:1px solid #e5e7eb;border-radius:14px;background:#fff;
        }
        .identity-head{margin-bottom:16px}
        .identity-eyebrow{
          margin:0 0 6px;font-size:12px;font-weight:700;letter-spacing:.08em;
          text-transform:uppercase;color:#1a3a2a;
        }
        h2{margin:0;font-size:22px;line-height:1.25;letter-spacing:-.25px;color:#1a1a1a}
        .identity-rows{margin:0;display:grid;gap:12px}
        .identity-row{
          display:grid;grid-template-columns:88px 1fr auto;gap:12px;align-items:baseline;
        }
        dt{font-size:12px;font-weight:700;color:#1a3a2a}
        dd{margin:0;display:flex;flex-wrap:wrap;align-items:center;gap:8px;min-inline-size:0}
        .identity-value{font-size:16px;line-height:1.5;color:#1a1a1a;overflow-wrap:anywhere}
        .identity-badge{
          padding:4px 10px;border-radius:999px;background:#d1f470;color:#1a3a2a;
          font-size:12px;font-weight:700;white-space:nowrap;
        }
        button{
          min-height:34px;padding:0 14px;border:1px solid #1a3a2a;border-radius:999px;
          background:#fff;color:#1a3a2a;font:inherit;font-size:12px;font-weight:700;cursor:pointer;
        }
        button:hover:not(:disabled){background:#d1f470}
        button:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}
        button:disabled{opacity:.55;cursor:default}
        @media(max-width:767px){
          .identity-card{padding:18px 14px}
          .identity-row{grid-template-columns:1fr;gap:4px}
          button{justify-self:start;margin-top:4px}
        }
      `}</style>
    </section>
  );
};

export default CheckoutIdentityCard;
