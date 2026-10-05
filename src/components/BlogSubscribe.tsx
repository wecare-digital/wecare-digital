import React, { useMemo, useState } from 'react';
import OtpResend from './OtpResend';
import PhoneField from './PhoneField';
import PillButton from './PillButton';
import { DEFAULT_DIAL_CODE, isValidNationalLength, nationalLengthHint } from '../lib/dialCodes';

type Step = 'idle' | 'sending' | 'sent' | 'verifying' | 'verified' | 'error';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const SUBSCRIBE_URL = `${API_BASE}/blog/subscribe`;

interface ApiReply {
  status?: string;
  proof?: string;
  error?: string;
  retryAfterSeconds?: number;
}

function composePhone ( dialCode: string, national: string ): string {
  const digits = national.replace( /\D/g, '' ).replace( /^0+/, '' );
  return `${dialCode}${digits}`;
}

async function postAction ( body: Record<string, unknown> ): Promise<ApiReply> {
  const response = await fetch( SUBSCRIBE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify( body ),
  } );
  const payload = await response.json().catch( () => ( {} as ApiReply ) );
  if ( !response.ok ) {
    const err = new Error( payload.error || 'REQUEST_FAILED' ) as Error & { payload?: ApiReply };
    err.payload = payload;
    throw err;
  }
  return payload;
}

const BlogSubscribe: React.FC = () => {
  const [ firstName, setFirstName ] = useState( '' );
  const [ lastName, setLastName ] = useState( '' );
  const [ dialCode, setDialCode ] = useState( DEFAULT_DIAL_CODE );
  const [ national, setNational ] = useState( '' );
  const [ email, setEmail ] = useState( '' );
  const [ phoneCode, setPhoneCode ] = useState( '' );
  const [ emailCode, setEmailCode ] = useState( '' );
  const [ phoneProof, setPhoneProof ] = useState( '' );
  const [ emailProof, setEmailProof ] = useState( '' );
  const [ phoneStep, setPhoneStep ] = useState<Step>( 'idle' );
  const [ emailStep, setEmailStep ] = useState<Step>( 'idle' );
  const [ busy, setBusy ] = useState( false );
  const [ message, setMessage ] = useState( '' );
  const [ done, setDone ] = useState( false );

  const phone = useMemo( () => composePhone( dialCode, national ), [ dialCode, national ] );
  const phoneValid = national.trim().length > 0 && isValidNationalLength( dialCode, national );
  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test( email.trim() );

  const resetPhoneVerification = () => {
    setPhoneProof( '' );
    setPhoneCode( '' );
    setPhoneStep( 'idle' );
    setDone( false );
  };
  const resetEmailVerification = () => {
    setEmailProof( '' );
    setEmailCode( '' );
    setEmailStep( 'idle' );
    setDone( false );
  };

  const requestPhone = async () => {
    setMessage( '' );
    if ( !phoneValid ) {
      setPhoneStep( 'error' );
      setMessage( `Enter a ${nationalLengthHint( dialCode ) || 'valid'} WhatsApp number.` );
      return;
    }
    setPhoneStep( 'sending' );
    try {
      await postAction( { action: 'phone_request', phone } );
      setPhoneStep( 'sent' );
    } catch {
      setPhoneStep( 'error' );
      setMessage( 'Could not send the WhatsApp code. Please try again.' );
    }
  };

  const verifyPhone = async () => {
    if ( phoneCode.trim().length < 4 ) return;
    setMessage( '' );
    setPhoneStep( 'verifying' );
    try {
      const reply = await postAction( { action: 'phone_verify', phone, code: phoneCode.trim() } );
      if ( reply.status !== 'VERIFIED' || !reply.proof ) throw new Error( 'INVALID' );
      setPhoneProof( reply.proof );
      setPhoneStep( 'verified' );
      setPhoneCode( '' );
    } catch {
      setPhoneStep( 'error' );
      setMessage( 'That WhatsApp code is invalid or expired.' );
    }
  };

  const requestEmail = async () => {
    setMessage( '' );
    if ( !emailValid ) {
      setEmailStep( 'error' );
      setMessage( 'Enter a valid email address.' );
      return;
    }
    setEmailStep( 'sending' );
    try {
      await postAction( {
        action: 'email_request',
        email: email.trim(),
        phone,
        firstName: firstName.trim(),
      } );
      setEmailStep( 'sent' );
    } catch {
      setEmailStep( 'error' );
      setMessage( 'Could not send the email code. Please try again.' );
    }
  };

  const verifyEmail = async () => {
    if ( emailCode.trim().length < 4 ) return;
    setMessage( '' );
    setEmailStep( 'verifying' );
    try {
      const reply = await postAction( {
        action: 'email_verify',
        email: email.trim(),
        code: emailCode.trim(),
      } );
      if ( reply.status !== 'VERIFIED' || !reply.proof ) throw new Error( 'INVALID' );
      setEmailProof( reply.proof );
      setEmailStep( 'verified' );
      setEmailCode( '' );
    } catch {
      setEmailStep( 'error' );
      setMessage( 'That email code is invalid or expired.' );
    }
  };

  const subscribe = async ( event: React.FormEvent ) => {
    event.preventDefault();
    setMessage( '' );
    if ( !firstName.trim() || !lastName.trim() ) {
      setMessage( 'Enter your first and last name.' );
      return;
    }
    if ( !phoneProof || !emailProof ) {
      setMessage( 'Verify both WhatsApp and email before subscribing.' );
      return;
    }
    setBusy( true );
    try {
      const reply = await postAction( {
        action: 'subscribe',
        firstName: firstName.trim(),
        lastName: lastName.trim(),
        phone,
        email: email.trim(),
        phoneProof,
        emailProof,
      } );
      if ( reply.status !== 'SUBSCRIBED' ) throw new Error( 'FAILED' );
      setDone( true );
      setMessage( 'Subscribed. You are on the WECARE.DIGITAL blog list.' );
    } catch ( error ) {
      const code = String( ( error as Error & { payload?: ApiReply } )?.payload?.error || '' );
      setMessage(
        code === 'SUBSCRIPTION_CONFLICT'
          ? 'That phone and email belong to different existing contacts. Please contact us.'
          : 'Could not save the subscription. Please try again.'
      );
    } finally {
      setBusy( false );
    }
  };

  return (
    <section className="blog-subscribe" aria-labelledby="blog-subscribe-title">
      <div className="blog-subscribe-head">
        <div>
          <p className="blog-subscribe-eyebrow">Blog updates</p>
          <h2 id="blog-subscribe-title">Get new posts directly</h2>
        </div>
        <p>Verify WhatsApp and email once. We’ll use both only for WECARE.DIGITAL blog updates you subscribe to.</p>
      </div>

      <form onSubmit={ subscribe } noValidate>
        <div className="blog-subscribe-fields">
          <label className="blog-subscribe-cell">
            <span>First name</span>
            <input
              value={ firstName }
              onChange={ e => { setFirstName( e.target.value ); setDone( false ); } }
              autoComplete="given-name"
              maxLength={ 100 }
              placeholder="First name"
            />
          </label>

          <label className="blog-subscribe-cell">
            <span>Last name</span>
            <input
              value={ lastName }
              onChange={ e => { setLastName( e.target.value ); setDone( false ); } }
              autoComplete="family-name"
              maxLength={ 100 }
              placeholder="Last name"
            />
          </label>

          <div className="blog-subscribe-cell phone-cell">
            <span className="field-label">WhatsApp</span>
            <PhoneField
              id="blog-subscribe-phone"
              dialCode={ dialCode }
              onDialCodeChange={ next => { setDialCode( next ); resetPhoneVerification(); } }
              number={ national }
              onNumberChange={ next => { setNational( next ); resetPhoneVerification(); } }
              invalid={ phoneStep === 'error' }
              verified={ phoneStep === 'verified' }
              describedBy="blog-subscribe-status"
            />
            <div className="verify-row">
              { phoneStep === 'sent' || phoneStep === 'error' || phoneStep === 'verifying' ? (
                <>
                  <input
                    className="otp"
                    value={ phoneCode }
                    onChange={ e => setPhoneCode( e.target.value.replace( /\D/g, '' ).slice( 0, 6 ) ) }
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    aria-label="WhatsApp verification code"
                    placeholder="Code"
                    disabled={ phoneStep === 'verifying' }
                  />
                  <button type="button" onClick={ verifyPhone } disabled={ phoneStep === 'verifying' }>
                    { phoneStep === 'verifying' ? 'Checking…' : 'Confirm WhatsApp code' }
                  </button>
                  {/* THE RESEND IS THE DERIVED SECONDARY NOW, not a second lime fill.
                      `.verify-row button` paints every button in this row lime, so the code step
                      rendered "Confirm WhatsApp code" and the resend as two equal lime surfaces -
                      four of them once the email pair below is counted - against the owner's one
                      primary lime surface per page. It also had no cooldown, where
                      CheckoutProfile's resend has one. OtpResend supplies both, and it is the
                      same control /account/sign-in/ and /get/ use. */}
                  <OtpResend
                    onResend={ requestPhone }
                    size="md"
                    busy={ phoneStep === 'verifying' || !phoneValid }
                  />
                </>
              ) : phoneStep === 'verified' ? (
                <span className="verified">✓ WhatsApp verified</span>
              ) : (
                <button type="button" onClick={ requestPhone } disabled={ phoneStep === 'sending' || !phoneValid }>
                  { phoneStep === 'sending' ? 'Sending…' : 'Send OTP on WhatsApp' }
                </button>
              ) }
            </div>
          </div>

          <div className="blog-subscribe-cell email-cell">
            <label htmlFor="blog-subscribe-email">Email</label>
            <input
              id="blog-subscribe-email"
              type="email"
              value={ email }
              onChange={ e => { setEmail( e.target.value ); resetEmailVerification(); } }
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={ emailStep === 'error' ? 'true' : undefined }
            />
            <div className="verify-row">
              { emailStep === 'sent' || emailStep === 'error' || emailStep === 'verifying' ? (
                <>
                  <input
                    className="otp"
                    value={ emailCode }
                    onChange={ e => setEmailCode( e.target.value.replace( /\D/g, '' ).slice( 0, 6 ) ) }
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    aria-label="Email verification code"
                    placeholder="Code"
                    disabled={ emailStep === 'verifying' }
                  />
                  <button type="button" onClick={ verifyEmail } disabled={ emailStep === 'verifying' }>
                    { emailStep === 'verifying' ? 'Checking…' : 'Confirm email code' }
                  </button>
                  {/* channel="email" because this IS the one-time email verification, which is
                      the only thing email is used for on this site - never a sign-in OTP. The
                      control says "Resend email code" so it cannot read as an email OTP
                      channel. "Resend verification code by email" was the old wording and was
                      the longest string in a row that scrolls horizontally on a phone. */}
                  <OtpResend
                    onResend={ requestEmail }
                    channel="email"
                    size="md"
                    busy={ emailStep === 'verifying' || !emailValid }
                  />
                </>
              ) : emailStep === 'verified' ? (
                <span className="verified">✓ Email verified</span>
              ) : (
                <button type="button" onClick={ requestEmail } disabled={ emailStep === 'sending' || !emailValid }>
                  { emailStep === 'sending' ? 'Sending…' : 'Send verification code by email' }
                </button>
              ) }
            </div>
          </div>

          <div className="blog-subscribe-action">
            <PillButton
              as="button"
              type="submit"
              action={ done ? 'Subscribed' : 'Subscribe' }
              disabled={ busy || done || !phoneProof || !emailProof || !firstName.trim() || !lastName.trim() }
              busy={ busy }
            />
          </div>
        </div>

        <p id="blog-subscribe-status" className={ `blog-subscribe-status${done ? ' is-done' : ''}` } role="status">
          { message }
        </p>
      </form>

      <style jsx>{`
        .blog-subscribe{
          margin-top:44px;padding:24px;border:2px solid #d1f470;border-radius:14px;
          background:rgba(209,244,112,.22);
          font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
        }
        .blog-subscribe-head{display:flex;gap:24px;justify-content:space-between;align-items:flex-end;margin-bottom:20px}
        .blog-subscribe-head>div{min-width:0}
        .blog-subscribe-eyebrow{margin:0 0 7px;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#1a3a2a}
        h2{margin:0;font-size:clamp(24px,3vw,32px);line-height:1.08;letter-spacing:-.8px;color:rgba(0,0,0,.95)}
        .blog-subscribe-head>p{margin:0;max-width:38ch;font-size:15px;line-height:1.5;color:rgba(0,0,0,.66)}
        .blog-subscribe-fields{display:flex;align-items:flex-end;gap:12px;flex-wrap:wrap}
        .blog-subscribe-cell{display:flex;flex-direction:column;gap:7px;min-width:150px;flex:1 1 150px}
        .phone-cell{min-width:310px;flex:2 1 310px}
        .email-cell{min-width:250px;flex:2 1 250px}
        .blog-subscribe-cell>span,.blog-subscribe-cell>label,.field-label{
          font-size:12px;font-weight:700;letter-spacing:.01em;color:#1a3a2a
        }
        .blog-subscribe-cell>input,.verify-row .otp{
          min-height:52px;box-sizing:border-box;border:1px solid #e5e7eb;border-radius:999px;
          padding:0 14px;background:#fff;color:#1a1a1a;font:inherit;font-size:16px;outline:none
        }
        .blog-subscribe-cell>input:focus-visible,.verify-row .otp:focus-visible{
          outline:3px solid #1a3a2a;outline-offset:2px;border-color:#1a3a2a
        }
        .phone-cell :global(.pf){margin-bottom:0}
        .verify-row{display:flex;align-items:center;gap:8px;min-height:44px;flex-wrap:wrap}
        /* 600, the home CTA's weight, not 700. CheckoutProfile's identical verify row now reads
           14px/600 too; it was 12px/700 there and 14px/700 here, which is the same control
           rendering at two type sizes and a weight the rest of the site does not use. */
        .verify-row button{
          min-height:44px;padding:0 16px;border:2px solid #1a3a2a;border-radius:999px;
          background:#d1f470;color:#1a3a2a;font:inherit;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap;
          transition:background-color .2s,transform .2s,box-shadow .2s
        }
        .verify-row button:hover:not(:disabled){background:#fff;transform:translateY(-1px);box-shadow:0 4px 12px rgba(26,58,42,.12)}
        .verify-row button:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
        .verify-row button:disabled{opacity:.55;cursor:default;transform:none;box-shadow:none}
        /* 17px AND 120px WIDE. It was 15px, which only ever looked right because
           Layout.css forced every input to 16px with !important - a rule this sweep removed,
           because it was overriding four components' deliberate 17px. With the override gone
           the declared size is what paints, so 15px would have become real: the one field on
           this card smaller than every other field on the site, and under the 16px floor below
           which iOS Safari zooms the viewport on focus. The box widens with the type so six
           digits still fit. */
        .verify-row .otp{min-height:44px;width:120px;font-size:17px;padding:0 14px}
        .verified{font-size:12px;font-weight:700;color:#1a3a2a;white-space:nowrap}
        .blog-subscribe-action{display:flex;align-items:center;min-height:91px}
        .blog-subscribe-status{min-height:22px;margin:12px 0 0;font-size:14px;line-height:1.45;color:rgba(0,0,0,.7)}
        .blog-subscribe-status.is-done{color:#1a3a2a;font-weight:600}
        @media(max-width:767px){
          .blog-subscribe{padding:20px 16px}
          .blog-subscribe-head{display:block}
          .blog-subscribe-head>p{margin-top:10px}
          .blog-subscribe-fields{
            flex-wrap:nowrap;overflow-x:auto;overscroll-behavior-inline:contain;
            scroll-snap-type:x proximity;padding-bottom:8px
          }
          .blog-subscribe-cell,.blog-subscribe-action{flex:0 0 auto;scroll-snap-align:start}
          .blog-subscribe-cell{width:170px}
          .phone-cell{width:330px}
          .email-cell{width:270px}
          .blog-subscribe-action{min-height:91px;padding-inline-end:4px}
        }
      `}</style>
    </section>
  );
};

export default BlogSubscribe;
