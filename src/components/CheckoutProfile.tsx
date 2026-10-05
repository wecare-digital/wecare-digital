import React, { useEffect, useState } from 'react';
import OtpResend from './OtpResend';

import PillButton from './PillButton';
import AddressFields, {
  AddressDraft,
  EMPTY_ADDRESS_DRAFT,
  StoredAddress,
  addressDraftValid,
  addressPayload,
  draftFromStored,
} from './AddressFields';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const EMAIL_VERIFY_URL = `${API_BASE}/auth/email-verification`;
const PROFILE_URL = `${API_BASE}/customer/profile`;

/**
 * Mirrors `otp_challenge.DEFAULT_RESEND_COOLDOWN` (60 s). A COURTESY, NOT THE CONTROL: the
 * server's own cooldown and its five-per-hour cap are what bound abuse, and they are enforced
 * whatever this browser believes. This exists so the customer is told to wait instead of being
 * handed a 429 they did not ask for.
 */
const RESEND_COOLDOWN_MS = 60_000;

type VerificationStep = 'idle' | 'sending' | 'sent' | 'verifying' | 'verified' | 'error';

/**
 * WHICH QUESTION THIS FORM IS ASKING. One component rather than four, because all four modes
 * post to the same endpoint and share the same validation - only the fields shown, the body
 * posted and the Save predicate differ.
 *
 *   create  - first-time checkout: name + email(+OTP) + address, all four posted
 *   address - returning customer editing the delivery address only, no OTP
 *   name    - returning customer editing their name only, no OTP
 *   email   - returning customer changing their email, OTP required for a NEW address
 */
export type CheckoutProfileMode = 'create' | 'address' | 'email' | 'name';

export interface CheckoutProfileValue {
  contactId: string;
  name: string;
  firstName: string;
  lastName: string;
  email: string;
  phone: string;
  addressComplete: boolean;
  address: StoredAddress | null;
}

interface Props {
  accessToken: string;
  /**
   * OPTIONAL, defaulting to 'create'. The default is load-bearing rather than convenient: every
   * caller that only ever created a profile keeps compiling and keeps exercising the create
   * path, and `src/test/CheckoutProfile.test.tsx` is the regression guard on exactly that.
   */
  mode?: CheckoutProfileMode;
  /**
   * Pre-fill for the edit modes, read once at mount. The cart page mounts a fresh editor per
   * affordance, so there is no need to track later changes to this prop - and tracking them
   * would overwrite what the customer is mid-way through typing.
   */
  initial?: { firstName: string; lastName: string; email: string; address: StoredAddress | null };
  onReady: ( profile: CheckoutProfileValue ) => void;
}

async function jsonPost (
  url: string,
  body: Record<string, unknown>,
  accessToken?: string,
): Promise<Record<string, any>> {
  const response = await fetch( url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...( accessToken ? { Authorization: `Bearer ${ accessToken }` } : {} ),
    },
    body: JSON.stringify( body ),
  } );
  const payload = await response.json().catch( () => ( {} ) );
  if ( !response.ok ) {
    const error = new Error( String( payload.error || 'REQUEST_FAILED' ) ) as Error & {
      payload?: Record<string, any>;
      status?: number;
    };
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

const CheckoutProfile: React.FC<Props> = ( { accessToken, mode = 'create', initial, onReady } ) => {
  const [ firstName, setFirstName ] = useState( initial?.firstName || '' );
  const [ lastName, setLastName ] = useState( initial?.lastName || '' );
  const [ email, setEmail ] = useState( initial?.email || '' );
  const [ address, setAddress ] = useState<AddressDraft>(
    () => ( initial?.address ? draftFromStored( initial.address ) : { ...EMPTY_ADDRESS_DRAFT } ) );
  const [ addressField, setAddressField ] = useState( '' );
  const [ code, setCode ] = useState( '' );
  const [ proof, setProof ] = useState( '' );
  const [ step, setStep ] = useState<VerificationStep>( 'idle' );
  const [ saving, setSaving ] = useState( false );
  const [ message, setMessage ] = useState( '' );

  // The resend state. `cooldownUntil` is an epoch millisecond, so it survives a re-render and
  // cannot drift the way a decrementing counter can; `sendBlocked` is the one failure that has no
  // retry hint and must simply stop asking.
  const [ cooldownUntil, setCooldownUntil ] = useState( 0 );
  const [ sendBlocked, setSendBlocked ] = useState( false );
  const [ sendFailed, setSendFailed ] = useState( false );
  const [ clockTick, setClockTick ] = useState( () => Date.now() );

  const showNames = mode === 'create' || mode === 'name';
  const showEmail = mode === 'create' || mode === 'email';
  const showAddress = mode === 'create' || mode === 'address';

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test( email.trim() );
  const namesValid = firstName.trim().length > 0 && lastName.trim().length > 0;
  const addressValid = addressDraftValid( address );

  // An unchanged email needs no fresh proof - the backend's ordered table accepts re-submitting
  // the address already proven on a row this session owns. Compared trimmed and lowercased,
  // because that is what `identity.normalize_email` does before it decides the same thing.
  const emailUnchanged = mode === 'email'
    && !!initial?.email
    && email.trim().toLowerCase() === initial.email.trim().toLowerCase();

  // §4.2's table, one line per mode. The old single predicate (`!namesValid || !proof`) would
  // leave Save permanently disabled in `address` and `name` mode, where no name and no proof are
  // ever collected.
  const canSave = mode === 'create'
    ? namesValid && emailValid && !!proof && addressValid
    : mode === 'address'
      ? addressValid
      : mode === 'name'
        ? namesValid
        : emailValid && ( emailUnchanged || !!proof );

  /*
   * The countdown ticks only while a cooldown is running, and the interval clears BOTH on unmount
   * and the moment it expires - an interval left running past its purpose is a re-render every
   * second for the life of the page.
   */
  useEffect( () => {
    if ( cooldownUntil <= Date.now() ) return undefined;
    setClockTick( Date.now() );
    const id = setInterval( () => {
      const tick = Date.now();
      setClockTick( tick );
      if ( tick >= cooldownUntil ) clearInterval( id );
    }, 1000 );
    return () => clearInterval( id );
  }, [ cooldownUntil ] );

  const cooldownSeconds = Math.max( 0, Math.ceil( ( cooldownUntil - clockTick ) / 1000 ) );
  const sendDisabled = step === 'sending' || !emailValid || sendBlocked || cooldownSeconds > 0;

  const resetEmail = ( next: string ) => {
    setEmail( next );
    setProof( '' );
    setCode( '' );
    setStep( 'idle' );
    setMessage( '' );
    setSendFailed( false );
    // The five-per-hour cap is counted per email address, so a different address has its own
    // budget and the block lifts. The cooldown deliberately does NOT lift: the other 429 axis is
    // per phone and per IP, and clearing it on an email edit would hand out a free retry.
    setSendBlocked( false );
  };

  /**
   * §4.2's failure table. The question each row answers is not "what went wrong" but "was a send
   * consumed": a 503 or a 500 fires BEFORE `otp_challenge.issue`, so nothing was spent and a
   * client cooldown would make a transient store outage look like rate limiting. A 502 fires
   * AFTER it, so the server's own 60 s is already running and one of five hourly sends is gone.
   */
  const applySendFailure = ( error: unknown ) => {
    const detail = ( error || {} ) as { payload?: Record<string, any>; status?: number };
    const payload = detail.payload || {};
    const status = detail.status;
    const hint = Number( payload.retryAfterSeconds );

    // Back to the Send code control, not left staring at a code box for a code that never came.
    setStep( 'idle' );
    setCode( '' );
    setSendFailed( true );

    // One rule for both 429 shapes - `RESEND_TOO_SOON` from the challenge store and
    // `TOO_MANY_REQUESTS` from the per-phone/per-IP throttle, which is the axis actually bounding
    // abuse now that both WAF web ACLs are gone. Keying on the hint rather than on the code means
    // a new throttle that carries one is handled without a code list to update.
    if ( Number.isFinite( hint ) && hint > 0 ) {
      setCooldownUntil( Date.now() + Math.ceil( hint ) * 1000 );
      setMessage( `Wait ${ Math.ceil( hint ) } seconds before asking for another code.` );
      return;
    }
    if ( payload.error === 'RESEND_LIMIT_REACHED' ) {
      setSendBlocked( true );
      setMessage( 'Too many codes requested. Try again later.' );
      return;
    }
    if ( payload.error === 'SEND_FAILED' || status === 502 ) {
      setCooldownUntil( Date.now() + RESEND_COOLDOWN_MS );
      setMessage( 'We could not send the email code. You can ask for another in a moment.' );
      return;
    }
    setCooldownUntil( 0 );
    if ( payload.error === 'INVALID_EMAIL' ) {
      setMessage( 'Enter a valid email address.' );
      return;
    }
    if ( status === 503 || status === 500 ) {
      setMessage( 'We could not reach the verification service. Try again.' );
      return;
    }
    setMessage( 'We could not reach the server. Try again.' );
  };

  const sendCode = async () => {
    if ( !emailValid ) {
      setMessage( 'Enter a valid email address.' );
      return;
    }
    setMessage( '' );
    setSendFailed( false );
    setStep( 'sending' );
    try {
      await jsonPost( EMAIL_VERIFY_URL, {
        action: 'request',
        email: email.trim(),
        // In `email` mode the name inputs are not rendered, so the live value is empty and the
        // verification email would greet nobody. Fall back to the name already on the row.
        firstName: ( firstName || initial?.firstName || '' ).trim(),
      } );
      setStep( 'sent' );
      setCooldownUntil( Date.now() + RESEND_COOLDOWN_MS );
      setMessage( 'Verification code sent to your email.' );
    } catch ( error ) {
      applySendFailure( error );
    }
  };

  /**
   * The verify counterpart of `applySendFailure`, and it exists for the same reason: the
   * question is not "what went wrong" but "was the code judged at all". A 5xx fires BEFORE or
   * INSTEAD OF the comparison, so the code was never ruled on - telling the customer it is
   * "invalid or expired" is a false statement about their input, and clearing `proof` would
   * discard a verification they may already hold. Only a 400 is the server saying it looked.
   *
   * This is not hypothetical. A reserved-word defect in the consume step made every CORRECT
   * code answer 503, and the bare `catch` that used to live here reported all eight of them as
   * a bad code, which is what the customer and the owner both saw.
   */
  const applyVerifyFailure = ( error: unknown ) => {
    const detail = ( error || {} ) as { status?: number };
    const status = detail.status;
    setStep( 'error' );
    if ( typeof status === 'number' && status >= 500 ) {
      // `proof` deliberately NOT cleared: a server fault must not revoke a proof already held.
      setMessage( 'We could not check that code just now. Try again.' );
      return;
    }
    if ( typeof status !== 'number' ) {
      // NO status at all, which is a different failure from a 5xx and arrives by a different
      // route: `jsonPost` only ever sets `error.status` from a real response, so an offline
      // browser, a DNS failure, a CORS rejection, an aborted request - and the local
      // `PROOF_MISSING` throw on a 200 that carried no proof - all land here. None of them is
      // the server saying it looked at the code, so the same two rules as the 5xx arm apply:
      // do not claim the customer's input was wrong, and do not clear a proof already held.
      // This mirrors `applySendFailure`'s terminal arm; omitting it is what still let a dropped
      // connection report a correct code as invalid.
      setMessage( 'We could not reach the server. Try again.' );
      return;
    }
    setProof( '' );
    setMessage( 'That email code is invalid or expired.' );
  };

  const verifyCode = async () => {
    if ( code.trim().length < 4 ) return;
    setMessage( '' );
    setStep( 'verifying' );
    try {
      const reply = await jsonPost( EMAIL_VERIFY_URL, {
        action: 'verify',
        email: email.trim(),
        code: code.trim(),
      } );
      const nextProof = String( reply.proof || '' );
      if ( reply.status !== 'VERIFIED' || !nextProof ) throw new Error( 'PROOF_MISSING' );
      setProof( nextProof );
      setCode( '' );
      setStep( 'verified' );
      setMessage( 'Email verified.' );
    } catch ( error ) {
      applyVerifyFailure( error );
    }
  };

  /**
   * The body, per mode. **No mode ever posts an `emailProof` without an `email`** - that is the
   * shape the backend refuses with 400 on the grounds that a proof is a claim about an address,
   * so binding it to a stored value would let a proof minted for one address verify another.
   */
  const saveBody = (): Record<string, unknown> => {
    if ( mode === 'address' ) return { address: addressPayload( address ) };
    if ( mode === 'name' ) return { firstName: firstName.trim(), lastName: lastName.trim() };
    if ( mode === 'email' ) {
      return proof
        ? { email: email.trim(), emailProof: proof }
        : { email: email.trim() };
    }
    return {
      firstName: firstName.trim(),
      lastName: lastName.trim(),
      email: email.trim(),
      emailProof: proof,
      address: addressPayload( address ),
    };
  };

  const saveProfile = async () => {
    if ( !canSave ) {
      if ( showNames && !namesValid ) setMessage( 'Enter your first and last name.' );
      else if ( showEmail && !emailValid ) setMessage( 'Enter a valid email address.' );
      else if ( showEmail && !proof && !emailUnchanged ) setMessage( 'Verify your email before continuing.' );
      else setMessage( 'Complete your delivery address.' );
      return;
    }
    setSaving( true );
    setMessage( '' );
    setAddressField( '' );
    try {
      const reply = await jsonPost( PROFILE_URL, saveBody(), accessToken );
      if ( reply.status !== 'PROFILE_READY' ) throw new Error( 'PROFILE_NOT_READY' );
      const storedAddress = ( reply.address && typeof reply.address === 'object' )
        ? reply.address as StoredAddress
        : null;
      onReady( {
        contactId: String( reply.contactId || '' ),
        name: String( reply.name || '' ),
        firstName: String( reply.firstName || '' ),
        lastName: String( reply.lastName || '' ),
        email: String( reply.email || '' ),
        phone: String( reply.phone || '' ),
        addressComplete: Boolean( reply.addressComplete ),
        address: storedAddress,
      } );
      setMessage( 'Details saved. You can continue to secure payment.' );
    } catch ( error ) {
      const payload = ( error as Error & { payload?: Record<string, any> } ).payload || {};
      if ( payload.error === 'CONTACT_IDENTITY_CONFLICT' ) {
        setMessage( 'This phone and email are already linked to different contact records. Please contact us.' );
      } else if ( payload.error === 'EMAIL_VERIFICATION_REQUIRED' ) {
        setProof( '' );
        setStep( 'idle' );
        setMessage( 'Email verification expired. Please verify your email again.' );
      } else if ( payload.error === 'INVALID_ADDRESS' ) {
        // The server names the field it refused, so mark that input rather than showing a
        // form-level message the customer has to guess at. No value is echoed back.
        setAddressField( String( payload.field || '' ) );
        setMessage( payload.code === 'INVALID_PIN'
          ? 'Enter a six-digit Indian PIN code.'
          : 'Check your delivery address and try again.' );
      } else {
        setMessage( 'We could not save your checkout details. Please try again.' );
      }
    } finally {
      setSaving( false );
    }
  };

  return (
    <section className="checkout-profile" aria-labelledby="checkout-profile-title">
      <div className="checkout-profile-head">
        <div>
          <p className="checkout-profile-eyebrow">Checkout details</p>
          <h2 id="checkout-profile-title">
            { mode === 'name' ? 'Update your name'
              : mode === 'address' ? 'Update your delivery address'
                : mode === 'email' ? 'Change your email'
                  : 'Confirm who is placing the order' }
          </h2>
        </div>
        <span className="phone-verified">✓ WhatsApp verified by sign-in</span>
      </div>

      { mode === 'email' && (
        <p className="checkout-profile-note">A new email needs a fresh code before we save it.</p>
      ) }
      { ( mode === 'name' || mode === 'address' ) && (
        <p className="checkout-profile-note">Saved. No verification needed.</p>
      ) }

      <div className="checkout-profile-grid">
        { showNames && (
          <label>
            <span>First name</span>
            <input
              value={ firstName }
              onChange={ event => setFirstName( event.target.value ) }
              autoComplete="given-name"
              maxLength={ 100 }
              placeholder="First name"
            />
          </label>
        ) }

        { showNames && (
          <label>
            <span>Last name</span>
            <input
              value={ lastName }
              onChange={ event => setLastName( event.target.value ) }
              autoComplete="family-name"
              maxLength={ 100 }
              placeholder="Last name"
            />
          </label>
        ) }

        { showEmail && (
          <div className="email-field">
            <label htmlFor="checkout-email">Email</label>
            <input
              id="checkout-email"
              type="email"
              value={ email }
              onChange={ event => resetEmail( event.target.value ) }
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={ step === 'error' ? 'true' : undefined }
            />
            <div className="verify-row">
              { step === 'verified' ? (
                <span className="verified">✓ Email verified</span>
              ) : step === 'sent' || step === 'error' || step === 'verifying' ? (
                <>
                  <input
                    className="otp"
                    value={ code }
                    onChange={ event => setCode( event.target.value.replace( /\D/g, '' ).slice( 0, 6 ) ) }
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    aria-label="Email verification code"
                    placeholder="Code"
                    disabled={ step === 'verifying' }
                  />
                  <button type="button" onClick={ verifyCode } disabled={ step === 'verifying' }>
                    { step === 'verifying' ? 'Checking…' : 'Confirm email code' }
                  </button>
                  {/* THE SHARED RESEND CONTROL, so this row is not a fourth answer to the same
                      question. `.verify-row button` below paints every button in the row lime,
                      which made the confirm and the resend two equal lime surfaces; OtpResend is
                      the derived secondary, so the row keeps one lime fill.
                      cooldownUntil is passed because THIS surface's wait is the SERVER's - a 429
                      carries retryAfterSeconds and the challenge store's own 60s window is
                      longer than the component's 30s floor. OtpResend takes the later of the
                      two, so a server throttle is never shortened by the client. */}
                  <OtpResend
                    onResend={ sendCode }
                    channel="email"
                    size="md"
                    busy={ step === 'verifying' || !emailValid }
                    blocked={ sendBlocked }
                    cooldownUntil={ cooldownUntil }
                  />
                </>
              ) : (
                <button type="button" onClick={ sendCode } disabled={ sendDisabled }>
                  { step === 'sending' ? 'Sending…'
                    : cooldownSeconds > 0 ? `Send email code ${ cooldownSeconds }s` : 'Send verification code by email' }
                </button>
              ) }
            </div>
            { /* The seconds are announced as they change, and they are also part of the
                 button's own visible text, so its accessible name contains its label -
                 WCAG 2.5.3 Label in Name, the rule PillButton's docblock records. */ }
            <p className="resend-countdown" aria-live="polite">
              { cooldownSeconds > 0
                ? `Another code can be requested in ${ cooldownSeconds }s.`
                : '' }
            </p>
          </div>
        ) }
      </div>

      { showAddress && (
        <AddressFields
          value={ address }
          onChange={ next => { setAddress( next ); setAddressField( '' ); } }
          disabled={ saving }
          invalidField={ addressField }
        />
      ) }

      <p className="checkout-profile-note">
        Your verified phone and email are saved to the existing WECARE.DIGITAL Contacts workspace
        for this order. Purchasing does not automatically opt you into marketing.
      </p>

      { message && <p className="checkout-profile-status" role="status">{ message }</p> }

      <div className="checkout-profile-action">
        <PillButton
          as="button"
          type="button"
          label="Details"
          action={ saving ? 'Saving…' : 'Save & continue' }
          disabled={ saving || !canSave }
          busy={ saving }
          onClick={ saveProfile }
        />
      </div>

      <style jsx>{`
        .checkout-profile{
          margin:28px 0 0;padding:22px;border:1px solid #e5e7eb;border-radius:14px;background:#fff;
        }
        .checkout-profile-head{
          display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:18px;
        }
        .checkout-profile-eyebrow{
          margin:0 0 6px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#1a3a2a;
        }
        h2{margin:0;font-size:22px;line-height:1.25;letter-spacing:-.25px;color:#1a1a1a}
        .phone-verified,.verified{
          flex:0 0 auto;padding:5px 10px;border-radius:999px;background:#d1f470;color:#1a3a2a;
          font-size:12px;font-weight:700;white-space:nowrap;
        }
        .checkout-profile-grid{display:grid;grid-template-columns:1fr 1fr 1.5fr;gap:12px;align-items:start}
        .checkout-profile-grid label,.email-field{display:flex;flex-direction:column;gap:7px}
        .checkout-profile-grid label>span,.email-field>label{
          font-size:12px;font-weight:700;color:#1a3a2a;
        }
        /* 999px, NOT 10px. Every other field a customer meets on this site is a full pill -
           .si-input, .sf-input, PhoneField's .pf, BlogSubscribe's cells and the .otp box below -
           and this grid was the only place that rounded its corners partway. Measured in the
           built export before the change; nothing else about the field moves. */
        .checkout-profile-grid input{
          min-height:52px;box-sizing:border-box;border:1px solid #e5e7eb;border-radius:999px;
          padding:0 16px;background:#fff;color:#1a1a1a;font:inherit;font-size:16px;outline:none;
        }
        .checkout-profile-grid input:focus-visible{
          outline:3px solid #1a3a2a;outline-offset:2px;border-color:#1a3a2a;
        }
        .verify-row{display:flex;align-items:center;gap:8px;min-height:44px;flex-wrap:wrap}
        /* 14px/600, matching BlogSubscribe's identical row. It was 12px/700 here and 14px/700
           there - the same control, two type sizes, on two pages a customer can see in one
           session. 12px is also the smallest type on this card, on a button. 600 is the weight
           the home CTA uses; 700 was heavier than anything else it sits beside. */
        .verify-row button{
          min-height:44px;padding:0 16px;border:2px solid #1a3a2a;border-radius:999px;background:#d1f470;
          color:#1a3a2a;font:inherit;font-size:14px;font-weight:600;cursor:pointer;
        }
        .verify-row button:hover:not(:disabled){background:#fff;transform:translateY(-1px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .verify-row button:disabled{opacity:.55;cursor:default}
        /* 17px AND 120px WIDE. It was 15px, which only ever looked right because
           Layout.css forced every input to 16px with !important - a rule this sweep removed,
           because it was overriding four components' deliberate 17px. With the override gone
           the declared size is what paints, so 15px would have become real: the one field on
           this card smaller than every other field on the site, and under the 16px floor below
           which iOS Safari zooms the viewport on focus. The box widens with the type so six
           digits still fit. */
        .verify-row .otp{width:120px;min-height:44px;padding:0 14px;font-size:17px;border-radius:999px}
        .resend-countdown{margin:6px 0 0;font-size:12px;line-height:1.4;color:rgba(0,0,0,.66)}
        .checkout-profile-note,.checkout-profile-status{
          margin:14px 0 0;font-size:14px;line-height:1.5;color:rgba(0,0,0,.66);
        }
        .checkout-profile-status{color:#1a3a2a;font-weight:600}
        .checkout-profile-action{margin-top:16px}
        @media(max-width:767px){
          .checkout-profile{padding:18px 14px}
          .checkout-profile-head{display:block}
          .phone-verified{display:inline-flex;margin-top:10px}
          .checkout-profile-grid{grid-template-columns:1fr}
        }
      `}</style>
    </section>
  );
};

export default CheckoutProfile;
