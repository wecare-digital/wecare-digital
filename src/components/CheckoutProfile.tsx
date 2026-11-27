import React, { useId, useRef, useState } from 'react';
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
  /** Non-shipping checkout may use the existing verified-phone bootstrap. */
  allowIdentityBootstrap?: boolean;
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
  onSessionExpired?: () => void;
  onCancel?: () => void;
}

/**
 * Website checkout uses the same customer-declared profile fields as F001 Subscribe.
 * The authenticated WhatsApp session owns the phone identity, so the number is never editable
 * here. Email is deliberately not part of this checkout profile surface.
 */
const CheckoutProfile: React.FC<Props> = ( {
  accessToken, mode = 'create', allowIdentityBootstrap = false, initial, onReady, onSessionExpired, onCancel,
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
  const saveInFlight = useRef( false );
  const [ message, setMessage ] = useState( '' );
  const [ addressField, setAddressField ] = useState( '' );
  const noticeId = useId();

  const showProfile = mode === 'create' || mode === 'profile' || mode === 'name';
  const showAddress = mode === 'create' || mode === 'address';
  const showEmail = mode === 'email';
  const profileValid = !showProfile || fullName.trim().length > 0;
  const emailValid = !showEmail || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test( email.trim() );
  const canSave = profileValid && emailValid && ( !showAddress || addressDraftValid( address ) );

  const saveProfile = async (): Promise<void> => {
    if ( !canSave || saveInFlight.current ) return;
    saveInFlight.current = true;
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
      const save = ( payload: object ) => fetch( PROFILE_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
          Authorization: `Bearer ${ accessToken }`,
        },
        body: JSON.stringify( payload ),
      } );
      let response = await save( body );
      let reply = await response.json().catch( () => ( {} ) );
      // The server's existing authenticated phone-only bootstrap can establish
      // a first contact without inventing a shipping address. Retry only after
      // a definitive missing-address refusal, never an ambiguous save.
      if ( allowIdentityBootstrap && mode === 'name' && !showAddress
        && response.status === 400 && reply.error === 'INVALID_ADDRESS' && reply.code === 'ADDRESS_REQUIRED' ) {
        const bootstrap = await save( {} );
        const result = await bootstrap.json().catch( () => ( {} ) );
        if ( bootstrap.status === 401 ) {
          response = bootstrap;
          reply = result;
        } else if ( bootstrap.ok && result.status === 'PROFILE_READY' ) {
          response = await save( body );
          reply = await response.json().catch( () => ( {} ) );
        }
      }
      if ( !response.ok || reply.status !== 'PROFILE_READY' ) {
        if ( reply.error === 'CONTACT_IDENTITY_CONFLICT' ) {
          setMessage( publicActionText( 'blocked' ) );
        } else if ( response.status === 401 ) {
          if ( onSessionExpired ) onSessionExpired();
          else setMessage( 'Your sign-in has expired. Return to checkout and sign in again.' );
        } else if ( reply.error === 'INVALID_ADDRESS' ) {
          setAddressField( String( reply.field || '' ) );
          setMessage( publicActionText( 'failure' ) );
        } else if ( reply.error === 'NAME_REQUIRED' ) {
          setMessage( publicActionText( 'failure' ) );
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
      saveInFlight.current = false;
      setSaving( false );
    }
  };

  return (
    <section className="checkout-profile" aria-label="Checkout details" aria-busy={ saving }>

      { showProfile && (
        <div className="checkout-profile-grid">
          <label className="span-2">
            <span>Full name</span>
            <input
              value={ fullName }
              disabled={ saving }
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
              disabled={ saving }
              onChange={ event => setUsername( event.target.value ) }
              autoComplete="off"
              maxLength={ 50 }
            />
          </label>

          <label>
            <span>Organisation</span>
            <input
              value={ companyName }
              disabled={ saving }
              onChange={ event => setCompanyName( event.target.value ) }
              autoComplete="organization"
              maxLength={ 200 }
            />
          </label>

          <label>
            <span>Job title</span>
            <input
              value={ designation }
              disabled={ saving }
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
              disabled={ saving }
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
          errorDescriptionId={ message ? noticeId : undefined }
        />
      ) }

      { message && (
        <PublicNotice id={ noticeId } mode="inline" tone="error" message={ message } />
      ) }

      <div className="checkout-profile-actions">
        <button
          className="checkout-profile-action checkout-profile-primary"
          type="button"
          onClick={ () => { void saveProfile(); } }
          disabled={ saving || !canSave }
          aria-busy={ saving ? 'true' : undefined }
        >
          { saving ? 'Saving…' : mode === 'create' || mode === 'name' ? 'Save & continue' : 'Save changes' }
        </button>
        { onCancel && <button className="checkout-profile-action" type="button" disabled={ saving } onClick={ onCancel }>Cancel</button> }
      </div>

      <style>{`
        .checkout-profile{
          margin:24px 0 0;padding:0;border:0;border-radius:0;
          background:transparent;color:var(--public-text);font-family:var(--font-sans);
        }
        .checkout-profile-grid{
          display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px 24px;margin:0 0 24px;
        }
        .checkout-profile-grid .span-2{grid-column:1/-1}
        .checkout-profile-grid label{
          display:flex;flex-direction:column;gap:7px;min-width:0;color:var(--public-text);
          font-size:var(--public-supporting-size);font-weight:600;
        }
        .checkout-profile-grid label>span{min-width:0;overflow-wrap:anywhere}
        .checkout-profile-grid input{
          min-width:0;width:100%;min-height:54px;padding:0 2px;box-sizing:border-box;
          border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;
          background:transparent;color:var(--public-text);
          font:var(--public-body-weight) var(--public-body-size)/1.2 var(--font-sans);
          box-shadow:none;outline:0;-webkit-appearance:none;appearance:none;
          transition:border-color .2s,box-shadow .2s;
        }
        .checkout-profile-grid input::placeholder{color:var(--public-muted)}
        .checkout-profile-grid input:focus{
          border-bottom-color:var(--public-brand-green);
          box-shadow:0 1px 0 0 var(--public-brand-lime);
        }
        .checkout-profile-grid input:focus-visible{outline:2px solid var(--public-brand-green);outline-offset:-2px}
        .checkout-profile-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:22px}
        @media(max-width:767px){
          .checkout-profile-grid{grid-template-columns:1fr;gap:18px}
          .checkout-profile-grid .span-2{grid-column:auto}
          .checkout-profile-grid input{min-height:52px;font-size:16px}
          .checkout-profile-actions{display:grid;grid-template-columns:1fr;width:100%}
          .checkout-profile-action{width:100%}
        }
      `}</style>
    </section>
  );
};

export default CheckoutProfile;
