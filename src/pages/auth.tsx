import React, { useEffect, useMemo, useRef, useState } from 'react';
import Head from 'next/head';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';
import { DEFAULT_DIAL_CODE, DIAL_CODES, findDialCode, isValidNationalLength, nationalLengthHint } from '../lib/dialCodes';

type AuthPhase = 'phone' | 'code' | 'registration';

interface AuthStep {
  phase: AuthPhase;
  csrf: string;
  message: string;
  website: boolean;
  returnPath: string;
  clientName: string;
  destination: string;
  redirect?: string;
}

const AUTH_LOGO_URL = 'https://wecare.digital/get/o/stream/media/m/wecaredigital.png';

const WORDS: CycleWord[] = [
  { word: 'securely', tint: '#e0f7c8', dot: '#3da35a' },
  { word: 'simply', tint: '#dbeafe', dot: '#2563eb' },
  { word: 'anywhere', tint: '#ede9fe', dot: '#9849e8' },
];

const AuthPage: React.FC = () => {
  const [ step, setStep ] = useState<AuthStep | null>( null );
  const [ dialCode, setDialCode ] = useState( DEFAULT_DIAL_CODE );
  const [ phone, setPhone ] = useState( '' );
  const [ code, setCode ] = useState( '' );
  const [ busy, setBusy ] = useState( false );
  const [ error, setError ] = useState( '' );
  const [ countryOpen, setCountryOpen ] = useState( false );
  const [ countryQuery, setCountryQuery ] = useState( '' );
  const countryRef = useRef<HTMLDivElement | null>( null );

  useEffect( () => {
    const onPointer = ( event: MouseEvent ) => {
      if ( countryRef.current && !countryRef.current.contains( event.target as Node ) ) setCountryOpen( false );
    };
    document.addEventListener( 'mousedown', onPointer );
    return () => document.removeEventListener( 'mousedown', onPointer );
  }, [] );

  useEffect( () => {
    let cancelled = false;
    const begin = async () => {
      try {
        const query = new URLSearchParams( window.location.search );
        if ( query.size === 0 && sessionStorage.getItem( 'wecare.vault.authReturnFile' ) ) query.set( 'return', '/vault/' );
        const url = '/auth/state' + ( query.size ? `?${query.toString()}` : '' );
        const response = await fetch( url, { credentials: 'same-origin', cache: 'no-store' } );
        const next = await response.json() as AuthStep;
        if ( !response.ok ) throw new Error( 'start' );
        if ( next.redirect ) {
          window.location.assign( next.redirect );
          return;
        }
        if ( !cancelled ) setStep( next );
      } catch {
        if ( !cancelled ) setError( 'Sign in is temporarily unavailable. Please try again.' );
      }
    };
    void begin();
    return () => { cancelled = true; };
  }, [] );

  const countries = useMemo( () => {
    const query = countryQuery.trim().toLocaleLowerCase();
    if ( !query ) return DIAL_CODES;
    return DIAL_CODES.filter( item => (
      item.country.toLocaleLowerCase().includes( query ) || item.code.includes( query )
    ) );
  }, [ countryQuery ] );

  const submitStep = async ( values: Record<string, string> ) => {
    if ( !step || busy ) return;
    setBusy( true );
    setError( '' );
    try {
      const body = new URLSearchParams( { csrf: step.csrf, ...values } );
      if ( step.website ) {
        body.set( '_flow', 'website' );
        body.set( '_return', step.returnPath || '/' );
      }
      const response = await fetch( '/auth/step', {
        method: 'POST',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8' },
        body: body.toString(),
      } );
      const next = await response.json() as AuthStep;
      if ( next.redirect ) {
        window.location.assign( next.redirect );
        return;
      }
      if ( !response.ok ) throw new Error( 'step' );
      setStep( next );
      setCode( '' );
      if ( next.phase === 'phone' ) setPhone( '' );
      if ( next.message ) setError( next.message );
    } catch {
      setError( 'Something went wrong. Please try again.' );
    } finally {
      setBusy( false );
    }
  };

  const onSubmit = ( event: React.FormEvent<HTMLFormElement> ) => {
    event.preventDefault();
    if ( !step || busy ) return;
    if ( step.phase === 'phone' ) {
      const national = phone.replace( /\D/g, '' ).replace( /^0+/, '' );
      if ( !national ) {
        setError( 'Enter your WhatsApp number.' );
        return;
      }
      if ( !isValidNationalLength( dialCode, national ) ) {
        const hint = nationalLengthHint( dialCode );
        setError( hint ? `Enter a valid ${hint} number for ${findDialCode( dialCode )?.country || 'this country'}.` : 'Check the number and try again.' );
        return;
      }
      void submitStep( { country: dialCode, phone: national } );
      return;
    }
    if ( !/^\d{6}$/.test( code ) ) {
      setError( 'Enter the 6-digit code.' );
      return;
    }
    void submitStep( { code } );
  };

  return (
    <>
      <Head>
        <title>Sign in | WECARE.DIGITAL</title>
        <meta name="robots" content="noindex, nofollow, noarchive" />
        <meta name="description" content="Secure WECARE.DIGITAL customer sign in." />
      </Head>

      <RotatingHero
        ariaLabel="WECARE.DIGITAL sign in"
        frame="One account."
        words={ WORDS }
        sub="Sign in securely. Pick up where you left off."
        mobileFoundation
      >
        <section className="auth-card" aria-labelledby="auth-card-title">
          <div className="auth-eyebrow" id="auth-card-title">
            <img className="auth-eyebrow-icon" src={ AUTH_LOGO_URL } alt="" aria-hidden="true" width={ 1080 } height={ 1080 } decoding="async" />
            <span>Sign in</span>
          </div>

          { step?.clientName && <p className="auth-context">Continue to <strong>{ step.clientName }</strong></p> }

          <form noValidate onSubmit={ onSubmit } aria-busy={ busy }>
            { !step && !error && <p className="auth-status">Preparing secure sign in…</p> }

            { step?.phase === 'phone' && (
              <>
                <label className="auth-field-label" htmlFor="auth-phone">WhatsApp</label>
                <div className="phone-control">
                  <div className="country-picker" ref={ countryRef }>
                    <button
                      className="country-trigger"
                      type="button"
                      aria-haspopup="listbox"
                      aria-expanded={ countryOpen }
                      onClick={ () => setCountryOpen( open => !open ) }
                      disabled={ busy }
                    >
                      <span>{ dialCode }</span><span aria-hidden="true">⌄</span>
                    </button>
                    { countryOpen && (
                      <div className="country-panel">
                        <label className="country-search">
                          <span className="sr-only">Search countries</span>
                          <input
                            autoFocus
                            type="search"
                            value={ countryQuery }
                            placeholder="Search country"
                            onChange={ event => setCountryQuery( event.target.value ) }
                          />
                        </label>
                        <div className="country-list" role="listbox" aria-label="Country code">
                          { countries.map( item => (
                            <button
                              key={ item.code }
                              type="button"
                              className="country-row"
                              role="option"
                              aria-selected={ item.code === dialCode }
                              onClick={ () => {
                                setDialCode( item.code );
                                setCountryOpen( false );
                                setCountryQuery( '' );
                                setError( '' );
                              } }
                            >
                              <span>{ item.country }</span><span>{ item.code }</span>
                            </button>
                          ) ) }
                        </div>
                      </div>
                    ) }
                  </div>
                  <input
                    id="auth-phone"
                    type="tel"
                    inputMode="numeric"
                    autoComplete="tel-national"
                    placeholder="WhatsApp number"
                    value={ phone }
                    onChange={ event => {
                      setPhone( event.target.value.replace( /[^0-9 ]/g, '' ) );
                      if ( error ) setError( '' );
                    } }
                    disabled={ busy }
                    aria-invalid={ Boolean( error ) }
                    aria-describedby={ error ? 'auth-error' : undefined }
                  />
                </div>
              </>
            ) }

            { step && step.phase !== 'phone' && (
              <>
                <label className="auth-label" htmlFor="auth-code">Verification code</label>
                <input
                  id="auth-code"
                  className="code-control"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="6-digit code"
                  maxLength={ 6 }
                  value={ code }
                  onChange={ event => {
                    setCode( event.target.value.replace( /\D/g, '' ).slice( 0, 6 ) );
                    if ( error ) setError( '' );
                  } }
                  disabled={ busy }
                  aria-invalid={ Boolean( error ) }
                  aria-describedby={ error ? 'auth-error' : undefined }
                />
              </>
            ) }

            { error && <p className="auth-error" id="auth-error" role="alert">{ error }</p> }

            { step && (
              <div className="auth-actions">
                <button className="auth-action auth-primary" type="submit" disabled={ busy }>
                  { step.phase === 'phone' ? 'Get Code' : 'Verify' }
                </button>
                { step.phase !== 'phone' && (
                  <>
                    <button className="auth-action" type="button" disabled={ busy } onClick={ () => void submitStep( { action: 'resend', code: '' } ) }>
                      Resend
                    </button>
                    <button className="auth-action" type="button" disabled={ busy } onClick={ () => void submitStep( { action: 'edit_phone', code: '' } ) }>
                      Edit
                    </button>
                  </>
                ) }
              </div>
            ) }
          </form>
        </section>
      </RotatingHero>

      <style jsx>{`
        .auth-card{width:min(100%,560px);padding:36px 40px 40px;border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);border-radius:24px;background:var(--public-bg);box-shadow:0 14px 38px rgba(26,58,42,.08);color:var(--public-text);font-family:var(--font-sans)}
        .auth-eyebrow{display:inline-flex;align-items:center;gap:12px;min-height:52px;margin:0 0 34px;padding:0 22px;border-radius:999px;background:var(--public-brand-lime);color:var(--public-brand-green);font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking)}
        .auth-eyebrow-icon{width:36px;height:36px;border-radius:8px;display:block;object-fit:contain;flex:0 0 auto}
        .auth-context,.auth-status{margin:0 0 20px;color:var(--public-muted);font-size:var(--public-supporting-size);line-height:1.45}
        .auth-label{display:block;margin:0 0 12px;color:var(--public-text);font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking)}
        .auth-field-label{display:block;margin:0 0 10px;color:var(--public-muted);font-size:var(--public-supporting-size);font-weight:600;line-height:1.35;letter-spacing:.01em}
        .phone-control{position:relative;display:flex;width:100%;min-height:64px;border:1px solid rgba(26,58,42,.16);border-radius:18px;background:#fff;box-shadow:none;transition:box-shadow .18s,border-color .18s}
        .phone-control:focus-within{border-color:rgba(26,58,42,.28);box-shadow:0 0 0 2px rgba(209,244,112,.32)}
        .country-picker{position:relative;display:flex;flex:0 0 auto}
        .country-trigger{min-width:126px;min-height:62px;padding:0 18px;border:0;border-inline-end:1px solid rgba(26,58,42,.12);border-radius:17px 0 0 17px;display:flex;align-items:center;justify-content:center;gap:10px;background:var(--public-lime-tint);color:var(--public-brand-green);font:600 var(--public-body-size)/1 var(--font-sans);cursor:pointer}
        .country-trigger:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:2px;z-index:2}
        .phone-control>input,.code-control{min-width:0;width:100%;min-height:62px;padding:0 20px;border:0;border-radius:0 17px 17px 0;background:#fff;color:var(--public-text);font:var(--public-body-weight) var(--public-body-size)/1.2 var(--font-sans);letter-spacing:var(--public-body-tracking);box-shadow:none;outline:0}
        .phone-control>input::placeholder,.code-control::placeholder{color:rgba(0,0,0,.5)}
        .code-control{border:1.5px solid var(--public-brand-lime);border-radius:18px;box-shadow:0 2px 0 rgba(26,58,42,.18)}
        .code-control:focus{border-color:var(--public-brand-green);box-shadow:0 0 0 3px rgba(209,244,112,.4),0 2px 0 rgba(26,58,42,.18)}
        .country-panel{position:absolute;z-index:1200;top:calc(100% + 10px);inset-inline-start:0;width:min(340px,calc(100vw - 48px));max-height:360px;overflow:hidden;border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);border-radius:16px;background:#fff;box-shadow:0 18px 46px rgba(26,58,42,.15)}
        .country-search{display:block;padding:0 14px;border-bottom:0}
        .country-search input{width:100%;min-height:44px;margin:0;padding:0 2px;border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;background:transparent;color:var(--public-body);font:500 var(--public-supporting-size)/1.2 var(--font-sans);outline:0}
        .country-search input:focus{border-bottom-color:var(--public-brand-green);box-shadow:0 1px 0 0 var(--public-brand-lime)}
        .country-list{max-height:286px;overflow:auto}
        .country-row{width:100%;min-height:50px;padding:10px 14px;border:0;background:#fff;display:flex;align-items:center;justify-content:space-between;gap:14px;text-align:start;color:var(--public-brand-green);font:600 var(--public-supporting-size)/1.3 var(--font-sans);cursor:pointer}
        .country-row:hover,.country-row[aria-selected='true']{background:var(--public-lime-tint)}
        .auth-error{margin:14px 0 0;padding:11px 13px;border-inline-start:4px solid var(--public-brand-lime);border-radius:10px;background:var(--public-lime-tint);color:var(--public-text);font-size:var(--public-supporting-size);font-weight:600;line-height:1.4}
        .auth-actions{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-top:22px}
        .auth-action{min-height:48px;padding:8px 14px;border:0;border-radius:10px;background:var(--public-lime-tint);color:var(--public-brand-green);font:600 var(--public-cta-font-size)/1.35 var(--font-sans);text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;cursor:pointer;transition:background-color .18s,transform .18s,box-shadow .18s}
        .auth-action:hover{background:var(--public-brand-lime);transform:translateY(-1px);box-shadow:var(--public-lift-shadow);text-decoration-color:transparent}
        .auth-action:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
        .auth-action:disabled{opacity:.6;cursor:wait;transform:none;box-shadow:none}
        .auth-primary{font-weight:700}
        .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
        @media(max-width:767px){
          .auth-card{width:100%;padding:28px 20px 30px;border-radius:20px}
          .auth-eyebrow{min-height:48px;margin-bottom:28px;padding-inline:18px;font-size:var(--public-mobile-card-size)}
          .auth-label{font-size:var(--public-mobile-card-size)}
          .auth-field-label{font-size:var(--public-mobile-supporting-size)}
          .phone-control,.code-control{min-height:58px;border-radius:16px}
          .country-trigger{min-width:104px;min-height:56px;padding-inline:14px;border-radius:15px 0 0 15px;font-size:var(--public-mobile-form-font-size)}
          .phone-control>input,.code-control{min-height:56px;padding-inline:16px;font-size:var(--public-mobile-form-font-size)}
          .phone-control>input{border-radius:0 15px 15px 0}
          .code-control{border-radius:16px}
          .auth-action{font-size:var(--public-mobile-cta-font-size);min-height:46px}
          .country-panel{width:min(320px,calc(100vw - 32px))}
        }
      `}</style>
    </>
  );
};

export default AuthPage;
