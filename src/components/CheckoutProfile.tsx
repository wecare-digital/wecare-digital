import React, { useState } from 'react';
import PillButton from './PillButton';
import AddressFields, { AddressDraft, EMPTY_ADDRESS_DRAFT, StoredAddress, addressDraftValid, addressPayload, draftFromStored } from './AddressFields';

const PROFILE_URL = `${process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api'}/customer/profile`;
export type CheckoutProfileMode = 'create' | 'address' | 'email' | 'name';
export interface CheckoutProfileValue {
  contactId: string;
  name: string;
  firstName: string;
  lastName: string;
  companyName: string;
  designation: string;
  email: string;
  phone: string;
  emailVerified?: boolean;
  addressComplete: boolean;
  address: StoredAddress | null;
}
interface Props {
  accessToken: string;
  mode?: CheckoutProfileMode;
  initial?: { firstName: string; lastName: string; companyName: string; designation: string; email: string; address: StoredAddress | null };
  onReady: ( profile: CheckoutProfileValue ) => void;
}

/** The signed-in WhatsApp number owns the profile. Email is contact information. */
const CheckoutProfile: React.FC<Props> = ( { accessToken, mode = 'create', initial, onReady } ) => {
  const [ firstName, setFirstName ] = useState( initial?.firstName || '' );
  const [ lastName, setLastName ] = useState( initial?.lastName || '' );
  const [ companyName, setCompanyName ] = useState( initial?.companyName || '' );
  const [ designation, setDesignation ] = useState( initial?.designation || '' );
  const [ email, setEmail ] = useState( initial?.email || '' );
  const [ address, setAddress ] = useState<AddressDraft>( () => initial?.address ? draftFromStored( initial.address ) : { ...EMPTY_ADDRESS_DRAFT } );
  const [ saving, setSaving ] = useState( false );
  const [ message, setMessage ] = useState( '' );
  const [ addressField, setAddressField ] = useState( '' );
  const showNames = mode === 'create' || mode === 'name';
  const showEmail = mode === 'create' || mode === 'email';
  const showAddress = mode === 'create' || mode === 'address';
  const namesValid = !!firstName.trim() && !!lastName.trim();
  const businessProfileValid = !!companyName.trim() && !!designation.trim();
  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test( email.trim() );
  const canSave = ( !showNames || ( namesValid && businessProfileValid ) ) && ( !showEmail || emailValid ) && ( !showAddress || addressDraftValid( address ) );

  const saveProfile = async () => {
    if ( !canSave || saving ) return;
    setSaving( true ); setMessage( '' ); setAddressField( '' );
    const body = {
      ...( showNames ? {
        firstName: firstName.trim(),
        lastName: lastName.trim(),
        companyName: companyName.trim(),
        designation: designation.trim(),
      } : {} ),
      ...( showEmail ? { email: email.trim() } : {} ),
      ...( showAddress ? { address: addressPayload( address ) } : {} ),
    };
    try {
      const response = await fetch( PROFILE_URL, {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json', Authorization: `Bearer ${ accessToken }` },
        body: JSON.stringify( body ),
      } );
      const reply = await response.json().catch( () => ( {} ) );
      if ( !response.ok || reply.status !== 'PROFILE_READY' ) {
        if ( reply.error === 'CONTACT_IDENTITY_CONFLICT' ) setMessage( 'We could not link these details to your account automatically. Please contact us and we will complete this for you.' );
        else if ( reply.error === 'INVALID_ADDRESS' ) { setAddressField( String( reply.field || '' ) ); setMessage( 'Please check your delivery address.' ); }
        else if ( reply.error === 'INVALID_EMAIL' ) setMessage( 'Enter a valid email address.' );
        else setMessage( 'We could not save your details. Please try again.' );
        return;
      }
      onReady( {
        contactId: String( reply.contactId || '' ), name: String( reply.name || '' ),
        firstName: String( reply.firstName || '' ), lastName: String( reply.lastName || '' ),
        companyName: String( reply.companyName || '' ), designation: String( reply.designation || '' ),
        email: String( reply.email || '' ), phone: String( reply.phone || '' ),
        emailVerified: reply.emailVerified === true,
        addressComplete: Boolean( reply.addressComplete ), address: reply.address && typeof reply.address === 'object' ? reply.address as StoredAddress : null,
      } );
      setMessage( 'Details saved.' );
    } catch {
      setMessage( 'We could not reach the server. Please try again.' );
    } finally { setSaving( false ); }
  };
  return <section className="checkout-profile" aria-labelledby="checkout-profile-title">
    <div className="checkout-profile-head"><div><p className="checkout-profile-eyebrow">Checkout details</p>
      <h2 id="checkout-profile-title">{ mode === 'name' ? 'Update your name' : mode === 'address' ? 'Update your delivery address' : mode === 'email' ? 'Change your email' : 'Confirm your details' }</h2>
    </div><span className="phone-verified">✓ WhatsApp verified by sign-in</span></div>
    <div className="checkout-profile-grid">
      { showNames && <><label><span>First name</span><input value={ firstName } onChange={ e => setFirstName( e.target.value ) } autoComplete="given-name" maxLength={ 100 } placeholder="First name" /></label>
        <label><span>Last name</span><input value={ lastName } onChange={ e => setLastName( e.target.value ) } autoComplete="family-name" maxLength={ 100 } placeholder="Last name" /></label>
        <label><span>Organisation</span><input value={ companyName } onChange={ e => setCompanyName( e.target.value ) } autoComplete="organization" maxLength={ 200 } placeholder="Organisation" /></label>
        <label><span>Role / designation</span><input value={ designation } onChange={ e => setDesignation( e.target.value ) } autoComplete="organization-title" maxLength={ 200 } placeholder="Role or designation" /></label></> }
      { showEmail && <label><span>Email</span><input type="email" value={ email } onChange={ e => setEmail( e.target.value ) } autoComplete="email" placeholder="you@example.com" /></label> }
    </div>
    { showAddress && <AddressFields value={ address } onChange={ setAddress } disabled={ saving } invalidField={ addressField } /> }
    <p className="checkout-profile-status" role="status" aria-live="polite">{ message }</p>
    <div className="checkout-profile-action"><PillButton type="button" onClick={ saveProfile } disabled={ saving || !canSave } action={ saving ? 'Saving…' : mode === 'create' ? 'Save & continue' : 'Save changes' } /></div>
    <style>{`
      .checkout-profile{padding:24px;border:1px solid #e5e7eb;border-radius:24px;background:#fff;color:#1a1a1a}
      .checkout-profile-head{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:20px}
      .checkout-profile-eyebrow{margin:0 0 6px;font-size:14px}.checkout-profile h2{margin:0;font-size:22px}
      .phone-verified{font-size:14px;font-weight:600;color:#1a3a2a}.checkout-profile-grid{display:grid;grid-template-columns:1fr 1fr 1.5fr;gap:16px;margin-bottom:20px}
      .checkout-profile-grid label{display:flex;flex-direction:column;gap:8px;font-size:14px}.checkout-profile-grid input{min-height:52px;box-sizing:border-box;border:1px solid #e5e7eb;border-radius:999px;padding:0 16px;background:#fff;color:#1a1a1a;font:inherit;font-size:16px;outline:none}
      .checkout-profile-grid input:focus-visible{outline:3px solid #1a3a2a;outline-offset:2px}.checkout-profile-status{font-size:14px;color:#1a3a2a}.checkout-profile-action{margin-top:16px}
      @media(max-width:767px){.checkout-profile{padding:18px 14px}.checkout-profile-head{display:block}.phone-verified{display:inline-flex;margin-top:10px}.checkout-profile-grid{grid-template-columns:1fr}}
    `}</style>
  </section>;
};
export default CheckoutProfile;
