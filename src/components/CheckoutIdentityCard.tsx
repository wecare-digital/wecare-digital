import React from 'react';

import { StoredAddress } from './AddressFields';

interface CheckoutIdentity {
  name: string;
  username?: string;
  companyName?: string;
  designation?: string;
  email?: string;
  customerId?: string;
  phone: string;
  address: StoredAddress | null;
}

function maskPhone ( phone: string ): string {
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
  compact?: boolean;
  identity: CheckoutIdentity;
  editorOpen?: boolean;
  emptyAddressLabel?: string;
  showAddress?: boolean;
  onEditProfile: () => void;
  onEditAddress: () => void;
}

const CheckoutIdentityCard: React.FC<Props> = ( {
  identity, editorOpen, emptyAddressLabel, showAddress = true, onEditProfile, onEditAddress, compact = false,
} ) => {
  const locked = !!editorOpen;

  return (
    <section className={`identity-card${compact ? ' identity-compact' : ''}`}  aria-label="Checkout details">
      <div className="identity-head">
        <button className="public-auth-action" type="button" onClick={ onEditProfile } disabled={ locked }>Edit profile</button>
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

        { identity.email && (
          <div className="identity-row">
            <dt>Email</dt>
            <dd><span className="identity-value">{ identity.email }</span></dd>
          </div>
        ) }

        { identity.customerId && (
          <div className="identity-row">
            <dt>Customer ID</dt>
            <dd><span className="identity-value" data-wc-no-translate="true">{ identity.customerId }</span></dd>
          </div>
        ) }

        { showAddress && <div className="identity-row identity-address-row">
          <dt>Deliver</dt>
          <dd>
            <span className="identity-value">
              { identity.address ? identity.address.fullAddress : ( emptyAddressLabel || '' ) }
            </span>
          </dd>
          <button className="public-auth-action" type="button" onClick={ onEditAddress } disabled={ locked }>Edit address</button>
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
        @media(max-width:767px){
          .identity-row,.identity-address-row{grid-template-columns:1fr;gap:4px;padding:14px 0}
          .identity-address-row button{justify-self:start;margin-top:6px}
        }
        .identity-compact .identity-row,.identity-compact .identity-address-row{grid-template-columns:minmax(75px,.4fr) minmax(0,1fr);gap:10px}
        .identity-compact .identity-address-row button{grid-column:2;justify-self:start;margin-top:4px}
        @media(max-width:400px){.identity-compact .identity-row,.identity-compact .identity-address-row{grid-template-columns:1fr}.identity-compact .identity-address-row button{grid-column:1}}
      `}</style>
    </section>
  );
};

export default CheckoutIdentityCard;
