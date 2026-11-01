import React, { useState } from 'react';
import PublicNotice from './public/PublicNotice';
import { publicActionText } from '../lib/publicActionNotices';

import AddressFields, {
  AddressDraft, EMPTY_ADDRESS_DRAFT, StoredAddress,
  addressDraftValid, addressPayload, draftFromStored,
} from './AddressFields';

const PROFILE_URL = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/customer/profile`;

export type CheckoutProfileMode = 'create' | 'address' | 'profile' | 'name' | 'email';

export interface CheckoutProfileValue {
  contactId: string;
  name: string;
  username: string;
  companyName: string;
  designation: string;
  phone: string;
  addressComplete: boolean;
  address: StoredAddress | null;
  /** Legacy response members kept for callers outside /cart/ while they migrate to F001. */
  firstName: string;
  lastName: string;
  email: string;
  emailVerified?: boolean;
}

interface Props {
  accessToken: string;
  mode?: CheckoutProfileMode;
  initial?: {
    name?: string;
    username?: string;
    firstName?: string;
    lastName?: string;
    companyName: string;
    designation: string;
    email?: string;
    address: StoredAddress | null;
  };
  onReady: ( profile: CheckoutProfileValue ) => void;
}

/**
 * Website checkout uses the same customer-declared profile fields as F001 Subscribe.
 * The authenticated WhatsApp session owns the phone identity, so the number is never editable
 * here. Email is deliberately not part of this checkout profile surface.
 */
const CheckoutProfile: React.FC<Props> = ( {
  accessToken, mode = 'create', initial, onReady,
} ) => {
  const [ fullName, setFullName ] = useState(
    initial?.name || [ initial?.firstName, initial?.lastName ].filter( Boolean ).join( ' ' )
  );
  const [ username, setUsername ] = useState( initial?.username || '' );
  const [ companyName, setCompanyName ] = useState( initial?.companyName || '' );
  const [ designation, setDesignation ] = useState( initial?.designation || '' );
  const [ email, setEmail ] = useState( initial?.email || '' );
  const [ address, setAddress ] = useState<AddressDraft>(
    () => initial?.address ? draftFromStored( initial.address ) : { ...EMPTY_ADDRESS_DRAFT }
  );
  const [ saving, setSaving ] = useState( false );
  const [ message, setMessage ] = useState( '' );
  const [ addressField, setAddressField ] = useState( '' );

  const showProfile = mode === 'create' || mode === 'profile' || mode === 'name';
  const showAddress = mode === 'create' || mode === 'address';
  const showEmail = mode === 'email';
  const profileValid = !showProfile || fullName.trim().length > 0;
  const emailValid = !showEmail || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test( email.trim() );
  const canSave = profileValid && emailValid && ( !showAddress || addressDraftValid( address ) );

  const saveProfile = async (): Promise<void> => {
    if ( !canSave || saving ) return;
    setSaving( true );
    setMessage( '' );
    setAddressField( '' );

    const body = {
      ...( showProfile ? {
        fullName: fullName.trim(),
        username: username.trim(),
        companyName: companyName.trim(),
        designation: designation.trim(),
      } : {} ),
      ...( showEmail ? { email: email.trim() } : {} ),
      ...( showAddress ? { address: addressPayload( address ) } : {} ),
    };

    try {
      const response = await fetch( PROFILE_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          Authorization: `Bearer ${ accessToken }`,
        },
        body: JSON.stringify( body ),
      } );
      const reply = await response.json().catch( () => ( {} ) );
      if ( !response.ok || reply.status !== 'PROFILE_READY' ) {
        if ( reply.error === 'CONTACT_IDENTITY_CONFLICT' ) {
          setMessage( 'We could not link these details to your signed-in WhatsApp account.' );
        } else if ( reply.error === 'INVALID_ADDRESS' ) {
          setAddressField( String( reply.field || '' ) );
          setMessage( 'Please check your delivery address.' );
        } else if ( reply.error === 'NAME_REQUIRED' ) {
          setMessage( 'Enter your full name.' );
        } else {
          setMessage( publicActionText( 'failure' ) );
        }
        return;
      }

      onReady( {
        contactId: String( reply.contactId || '' ),
        name: String( reply.name || '' ),
        username: String( reply.username || '' ),
        companyName: String( reply.companyName || '' ),
        designation: String( reply.designation || '' ),
        phone: String( reply.phone || '' ),
        addressComplete: Boolean( reply.addressComplete ),
        address: reply.address && typeof reply.address === 'object'
          ? reply.address as StoredAddress
          : null,
        firstName: String( reply.firstName || '' ),
        lastName: String( reply.lastName || '' ),
        email: String( reply.email || '' ),
        emailVerified: reply.emailVerified === true,
      } );
      setMessage( '' );
    } catch {
      setMessage( publicActionText( 'failure' ) );
    } finally {
      setSaving( false );
    }
  };

  return (
    <section className="checkout-profile" aria-label="Checkout details">

      { showProfile && (
        <div className="checkout-profile-grid">
          <label className="span-2">
            <span>Full name</span>
            <input
              value={ fullName }
              onChange={ event => setFullName( event.target.value ) }
              autoComplete="name"
              maxLength={ 200 }
              aria-required="true"
            />
          </label>

          <label>
            <span>WhatsApp username</span>
            <input
              value={ username }
              onChange={ event => setUsername( event.target.value ) }
              autoComplete="off"
              maxLength={ 50 }
            />
          </label>

          <label>
            <span>Organisation</span>
            <input
              value={ companyName }
              onChange={ event => setCompanyName( event.target.value ) }
              autoComplete="organization"
              maxLength={ 200 }
            />
          </label>

          <label>
            <span>Job title</span>
            <input
              value={ designation }
              onChange={ event => setDesignation( event.target.value ) }
              autoComplete="organization-title"
              maxLength={ 200 }
            />
          </label>
        </div>
      ) }

      { showEmail && (
        <div className="checkout-profile-grid">
          <label className="span-2">
            <span>Email</span>
            <input
              type="email"
              value={ email }
              onChange={ event => setEmail( event.target.value ) }
              autoComplete="email"
              maxLength={ 254 }
              aria-required="true"
            />
          </label>
        </div>
      ) }

      { showAddress && (
        <AddressFields
          value={ address }
          onChange={ setAddress }
          disabled={ saving }
          invalidField={ addressField }
        />
      ) }

      { message && (
        <PublicNotice mode="inline" tone="error" message={ message } />
      ) }

      <div className="checkout-profile-actions">
        <button
          className="checkout-profile-action checkout-profile-primary"
          type="button"
          onClick={ () => { void saveProfile(); } }
          disabled={ saving || !canSave }
          aria-busy={ saving ? 'true' : undefined }
        >
          { saving ? 'Saving…' : mode === 'create' ? 'Save & continue' : 'Save changes' }
        </button>
      </div>

      <style>{`
        .checkout-profile{
          margin:24px 0 0;padding:0;border:0;border-radius:0;
          background:transparent;color:var(--public-text);font-family:var(--font-sans);
        }
        .checkout-profile-grid{
          display:grid;grid-template-columns:1fr 1fr;gap:20px 24px;margin:0 0 24px;
        }
        .checkout-profile-grid .span-2{grid-column:1/-1}
        .checkout-profile-grid label{
          display:flex;flex-direction:column;gap:7px;min-width:0;color:var(--public-text);
          font-size:var(--public-supporting-size);font-weight:600;
        }
        .checkout-profile-grid label>span{min-width:0}
        .checkout-profile-grid input{
          min-width:0;width:100%;min-height:54px;padding:0 2px;box-sizing:border-box;
          border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;
          background:transparent;color:var(--public-text);
          font:var(--public-body-weight) var(--public-body-size)/1.2 var(--font-sans);
          box-shadow:none;outline:0;-webkit-appearance:none;appearance:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .checkout-profile-grid input::placeholder{color:rgba(0,0,0,.42)}
        .checkout-profile-grid input:focus{
          border-bottom-color:var(--public-brand-green);
          box-shadow:0 1px 0 0 var(--public-brand-lime);
        }
        .checkout-profile-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:22px}
        .checkout-profile-action{
          min-height:48px;min-width:48px;padding:8px 14px;border:0;border-radius:10px;
          background:var(--public-lime-tint);color:var(--public-brand-green);
          font:600 var(--public-cta-font-size)/1.35 var(--font-sans);
          text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;
          touch-action:manipulation;cursor:pointer;
          transition:background-color .18s,transform .18s,box-shadow .18s;
        }
        .checkout-profile-action:hover:not(:disabled){
          background:var(--public-brand-lime);transform:translateY(-1px);
          box-shadow:var(--public-lift-shadow);text-decoration-color:transparent;
        }
        .checkout-profile-action:focus-visible{
          outline:3px solid var(--public-brand-green);outline-offset:3px;
        }
        .checkout-profile-action:disabled{opacity:.6;cursor:wait;transform:none;box-shadow:none}
        .checkout-profile-primary{font-weight:700}
        @media(max-width:767px){
          .checkout-profile-grid{grid-template-columns:1fr;gap:18px}
          .checkout-profile-grid .span-2{grid-column:auto}
          .checkout-profile-grid input{min-height:52px;font-size:16px}
          .checkout-profile-actions{display:grid;grid-template-columns:1fr;width:100%}
          .checkout-profile-action{width:100%;font-size:var(--public-mobile-cta-font-size)}
        }
        @media(prefers-reduced-motion:reduce){
          .checkout-profile-action{transition:none}
          .checkout-profile-action:hover:not(:disabled){transform:none;box-shadow:none}
        }
      `}</style>
    </section>
  );
};

export default CheckoutProfile;
