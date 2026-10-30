import React from 'react';

import { StoredAddress } from './AddressFields';

export interface CheckoutIdentity {
  name: string;
  username?: string;
  companyName?: string;
  designation?: string;
  phone: string;
  address: StoredAddress | null;
}

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
  editorOpen?: boolean;
  emptyAddressLabel?: string;
  showAddress?: boolean;
  onEditProfile: () => void;
  onEditAddress: () => void;
}

const CheckoutIdentityCard: React.FC<Props> = ( {
  identity, editorOpen, emptyAddressLabel, showAddress = true, onEditProfile, onEditAddress,
} ) => {
  const locked = !!editorOpen;

  return (
    <section className="identity-card" aria-label="Checkout details">
      <div className="identity-head">
        <button type="button" onClick={ onEditProfile } disabled={ locked }>Edit profile</button>
      </div>

      <dl className="identity-rows">
        <div className="identity-row">
          <dt>Name</dt>
          <dd><span className="identity-value">{ identity.name }</span></dd>
        </div>

        { identity.username && (
          <div className="identity-row">
            <dt>WhatsApp username</dt>
            <dd><span className="identity-value">{ identity.username }</span></dd>
          </div>
        ) }

        { identity.companyName && (
          <div className="identity-row">
            <dt>Organisation</dt>
            <dd><span className="identity-value">{ identity.companyName }</span></dd>
          </div>
        ) }

        { identity.designation && (
          <div className="identity-row">
            <dt>Job title</dt>
            <dd><span className="identity-value">{ identity.designation }</span></dd>
          </div>
        ) }

        <div className="identity-row">
          <dt>WhatsApp</dt>
          <dd><span className="identity-value">{ maskPhone( identity.phone ) }</span></dd>
        </div>

        { showAddress && <div className="identity-row identity-address-row">
          <dt>Deliver</dt>
          <dd>
            <span className="identity-value">
              { identity.address ? identity.address.fullAddress : ( emptyAddressLabel || '' ) }
            </span>
          </dd>
          <button type="button" onClick={ onEditAddress } disabled={ locked }>Edit address</button>
        </div> }
      </dl>

      <style jsx>{`
        .identity-card{
          margin:24px 0 0;padding:0;border:0;border-radius:0;background:transparent;color:var(--public-text);
          font-family:var(--font-sans);
        }
        .identity-head{display:flex;align-items:center;justify-content:flex-start;margin-bottom:12px}
        .identity-rows{margin:0;display:grid;gap:0}
        .identity-row{
          display:grid;grid-template-columns:minmax(120px,170px) minmax(0,1fr);gap:16px;
          align-items:center;padding:13px 0;border-bottom:1px solid var(--public-hairline);
        }
        .identity-address-row{grid-template-columns:minmax(120px,170px) minmax(0,1fr) auto}
        dt{color:var(--public-brand-green);font-size:var(--public-supporting-size);font-weight:700}
        dd{margin:0;display:flex;flex-wrap:wrap;align-items:center;gap:8px;min-inline-size:0}
        .identity-value{
          color:var(--public-text);font-size:var(--public-data-size);line-height:1.5;overflow-wrap:anywhere;
        }
        button{
          min-height:48px;min-width:48px;padding:8px 14px;border:0;border-radius:10px;
          background:var(--public-lime-tint);color:var(--public-brand-green);
          font:600 var(--public-cta-font-size)/1.35 var(--font-sans);
          text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;
          touch-action:manipulation;cursor:pointer;
          transition:background-color .18s,transform .18s,box-shadow .18s;
        }
        button:hover:not(:disabled){
          background:var(--public-brand-lime);transform:translateY(-1px);
          box-shadow:var(--public-lift-shadow);text-decoration-color:transparent;
        }
        button:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
        button:disabled{opacity:.6;cursor:default;transform:none;box-shadow:none}
        @media(max-width:767px){
          .identity-row,.identity-address-row{grid-template-columns:1fr;gap:4px;padding:14px 0}
          .identity-address-row button{justify-self:start;margin-top:6px}
        }
        @media(prefers-reduced-motion:reduce){
          button{transition:none}
          button:hover:not(:disabled){transform:none;box-shadow:none}
        }
      `}</style>
    </section>
  );
};

export default CheckoutIdentityCard;
