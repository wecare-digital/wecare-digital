import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Head from 'next/head';
import RotatingHero, { type CycleWord } from '../components/RotatingHero';
import PublicNotice from '../components/public/PublicNotice';
import { DEFAULT_DIAL_CODE, DIAL_CODES, isValidNationalLength } from '../lib/dialCodes';
import { rankNavigation } from '../lib/navigationSearch';
import SearchClearButton from '../components/SearchClearButton';
import { authStateQuery } from '../lib/authStateQuery';
import { authCountryPanelGeometry } from '../lib/authCountryPanelGeometry';
import { publicActionText, publicApiFailureText } from '../lib/publicActionNotices';
import { authStepFeedback } from '../lib/authStepFeedback';
import { preserveOrderRequest } from '../lib/orderRequestSelection';

type AuthPhase = 'phone' | 'code' | 'registration';

interface AuthStep {
  phase: AuthPhase;
  csrf: string;
  message: string;
  outcome?: string;
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
  const [ feedback, setFeedback ] = useState<string>( '' );
  const [ countryOpen, setCountryOpen ] = useState( false );
  const [ countryQuery, setCountryQuery ] = useState( '' );
  const countryRef = useRef<HTMLDivElement | null>( null );
  const countryTriggerRef = useRef<HTMLButtonElement | null>( null );
  const countrySearchRef = useRef<HTMLInputElement | null>( null );
  const phoneRef = useRef<HTMLInputElement | null>( null );
  const focusCountrySearch = useRef( false );
  const [ countryPanelStyle, setCountryPanelStyle ] = useState<React.CSSProperties | null>( null );

  const closeCountryPicker = useCallback( () => {
    setCountryOpen( false );
    setCountryQuery( '' );
    setCountryPanelStyle( null );
    focusCountrySearch.current = false;
  }, [] );

  const openCountryPicker = ( keyboard: boolean ) => {
    // Do not summon a software keyboard just to browse calling codes.
    focusCountrySearch.current = keyboard || window.matchMedia( '(hover: hover) and (pointer: fine)' ).matches;
    setCountryOpen( true );
  };

  useEffect( () => {
    if ( !countryOpen ) return;
    const onPointer = ( event: PointerEvent ) => {
      if ( countryRef.current && !countryRef.current.contains( event.target as Node ) ) closeCountryPicker();
    };
    const viewport = window.visualViewport;
    const place = () => {
      const trigger = countryTriggerRef.current;
      if ( !trigger ) return;
      const layoutWidth = document.documentElement.clientWidth || window.innerWidth;
      const layoutHeight = document.documentElement.clientHeight || window.innerHeight;
      setCountryPanelStyle( authCountryPanelGeometry( {
        layoutWidth, layoutHeight,
        viewportLeft: viewport?.offsetLeft ?? 0,
        viewportTop: viewport?.offsetTop ?? 0,
        viewportWidth: viewport?.width ?? layoutWidth,
        viewportHeight: viewport?.height ?? layoutHeight,
        anchor: trigger.getBoundingClientRect(),
        rtl: getComputedStyle( trigger ).direction === 'rtl',
      } ) );
    };
    place();
    document.addEventListener( 'pointerdown', onPointer );
    window.addEventListener( 'resize', place );
    window.addEventListener( 'scroll', place, { passive: true } );
    viewport?.addEventListener( 'resize', place );
    viewport?.addEventListener( 'scroll', place );
    return () => {
      document.removeEventListener( 'pointerdown', onPointer );
      window.removeEventListener( 'resize', place );
      window.removeEventListener( 'scroll', place );
      viewport?.removeEventListener( 'resize', place );
      viewport?.removeEventListener( 'scroll', place );
    };
  }, [ countryOpen, closeCountryPicker ] );

  useEffect( () => {
    if ( countryOpen && countryPanelStyle && focusCountrySearch.current ) {
      focusCountrySearch.current = false;
      countrySearchRef.current?.focus( { preventScroll: true } );
    }
  }, [ countryOpen, countryPanelStyle ] );

  useEffect( () => {
    let cancelled = false;
    const begin = async () => {
      try {
        const query = authStateQuery( new URLSearchParams( window.location.search ) );
        if ( query.size === 0 && sessionStorage.getItem( 'wecare.vault.authReturnFile' ) ) query.set( 'return', '/vault/' );
        const url = '/auth/state' + ( query.size ? `?${query.toString()}` : '' );
        const response = await fetch( url, { credentials: 'same-origin', cache: 'no-store' } );
        const next = await response.json() as AuthStep;
        if ( !response.ok ) throw new Error( 'start' );
        if ( next.redirect ) {
          window.location.assign( preserveOrderRequest( next.redirect, window.location.hash ) );
          return;
        }
        if ( !cancelled ) {
          setStep( next );
          const notice = authStepFeedback( next.message, next.outcome );
          if ( notice?.tone === 'error' ) setError( notice.message );
          else if ( notice ) setFeedback( notice.message );
        }
      } catch {
        if ( !cancelled ) setError( publicActionText( 'blocked' ) );
      }
    };
    void begin();
    return () => { cancelled = true; };
  }, [] );

  const countries = useMemo( () => {
    const query = countryQuery.trim().toLocaleLowerCase();
    if ( !query ) return DIAL_CODES;
    const matches = DIAL_CODES.filter( item => (
      item.country.toLocaleLowerCase().includes( query ) || item.code.includes( query )
    ) );
    if ( matches.length || !/^[a-z]{4,}(?: [a-z]+)*$/i.test( query ) ) return matches;
    // Only fuzzy-match names when exact name/code matching has no result.
    return rankNavigation( DIAL_CODES.map( item => ( { item, label: item.country, searchText: item.country } ) ), query ).map( hit => hit.item );
  }, [ countryQuery ] );

  const selectCountry = ( nextCode: string ) => {
    setDialCode( nextCode );
    setError( '' );
    closeCountryPicker();
    phoneRef.current?.focus( { preventScroll: true } );
  };

  const onCountryKeyDown = ( event: React.KeyboardEvent<HTMLDivElement> ) => {
    if ( event.nativeEvent.isComposing ) return;
    if ( event.key === 'Escape' && countryOpen ) {
      event.preventDefault();
      closeCountryPicker();
      countryTriggerRef.current?.focus( { preventScroll: true } );
      return;
    }
    const fromSearch = event.target === countrySearchRef.current;
    const fromTrigger = event.target === countryTriggerRef.current;
    const options = Array.from( countryRef.current?.querySelectorAll<HTMLButtonElement>( '.country-row' ) ?? [] );
    const current = options.indexOf( event.target as HTMLButtonElement );
    if ( fromSearch && event.key === 'Enter' ) {
      // Never submit the sign-in form from the country search.
      event.preventDefault();
      if ( countries.length === 1 ) selectCountry( countries[0].code );
      else options[0]?.focus( { preventScroll: true } );
      return;
    }
    if ( ![ 'ArrowDown', 'ArrowUp', 'Home', 'End' ].includes( event.key ) ) return;
    if ( ( fromSearch || fromTrigger ) && ( event.key === 'Home' || event.key === 'End' ) ) return;
    if ( !countryOpen && fromTrigger ) {
      event.preventDefault();
      openCountryPicker( true );
      return;
    }
    if ( !countryOpen || !options.length || ( !fromSearch && !fromTrigger && current < 0 ) ) return;
    event.preventDefault();
    if ( event.key === 'ArrowUp' && current === 0 ) {
      countrySearchRef.current?.focus( { preventScroll: true } );
      return;
    }
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
      : event.key === 'ArrowDown' ? Math.min( options.length - 1, current + 1 )
        : current < 0 ? options.length - 1 : current - 1;
    const option = options[next];
    if ( option ) {
      option.focus( { preventScroll: true } );
      option.scrollIntoView( { block: 'nearest', inline: 'nearest' } );
    }
  };

  const submitStep = async ( values: Record<string, string> ) => {
    if ( !step || busy ) return;
    setBusy( true );
    setError( '' );
    setFeedback( '' );
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
        window.location.assign( preserveOrderRequest( next.redirect, window.location.hash ) );
        return;
      }
      if ( !response.ok ) {
        setError( publicApiFailureText( response.status ) );
        return;
      }
      setStep( next );
      setCode( '' );
      if ( next.phase === 'phone' ) setPhone( '' );
      const notice = authStepFeedback( next.message, next.outcome );
      if ( notice?.tone === 'error' ) setError( notice.message );
      else if ( notice ) setFeedback( notice.message );
    } catch {
      setError( publicActionText( 'failure' ) );
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
        setError( publicActionText( 'failure' ) );
        return;
      }
      if ( !isValidNationalLength( dialCode, national ) ) {
        setError( publicActionText( 'failure' ) );
        return;
      }
      void submitStep( { country: dialCode, phone: national } );
      return;
    }
    if ( !/^\d{6}$/.test( code ) ) {
      setError( publicActionText( 'failure' ) );
      return;
    }
    void submitStep( { code } );
  };

  return (
    <>
      <Head>
        <title>Auth | WECARE.DIGITAL</title>
        <meta name="robots" content="noindex, nofollow, noarchive" />
        <meta name="description" content="Secure WECARE.DIGITAL customer sign in." />
      </Head>

      <RotatingHero
        badgeLabel="Account access"
        ariaLabel="WECARE.DIGITAL sign in"
        frame="One account."
        words={ WORDS }
        sub="Pick up where you left off."
        mobileFoundation
        compact
      >
        <section className="auth-card" aria-label="Sign in">
          <div className="auth-eyebrow" aria-hidden="true">
            <img className="auth-eyebrow-icon" src={ AUTH_LOGO_URL } alt="" width={ 1080 } height={ 1080 } decoding="async" />
          </div>

          <h2 className="auth-label">Secure sign-in</h2>
          <form noValidate onSubmit={ onSubmit } aria-busy={ busy }>
                        { step?.phase === 'phone' && (
              <>
                <label className="sr-only" htmlFor="auth-phone">WhatsApp number</label>
                <div className="phone-control">
                  <div className="country-picker" ref={ countryRef }
                    onKeyDown={ onCountryKeyDown }
                    onBlur={ event => {
                      if ( countryOpen && event.relatedTarget && !event.currentTarget.contains( event.relatedTarget as Node ) ) closeCountryPicker();
                    } }>
                    <button
                      ref={ countryTriggerRef }
                      className="country-trigger"
                      type="button"
                      aria-haspopup="listbox"
                      aria-expanded={ countryOpen }
                      aria-controls={ countryOpen ? 'auth-country-list' : undefined }
                      aria-label={ `Calling code ${ dialCode }. Choose country.` }
                      onClick={ event => { if ( countryOpen ) closeCountryPicker(); else openCountryPicker( event.detail === 0 ); } }
                      disabled={ busy }
                    >
                      <span>{ dialCode }</span>
                      <span className="country-arrow" aria-hidden="true">
                        <svg viewBox="0 0 16 16" width="16" height="16" focusable="false"><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </span>
                    </button>
                    { countryOpen && (
                      <div className="country-panel" style={ countryPanelStyle ?? { visibility: 'hidden' } }>
                        <div className="country-search">
                          <input
                            ref={ countrySearchRef }
                            type="search"
                            value={ countryQuery }
                            placeholder="Search country"
                            aria-label="Search countries"
                            autoComplete="off"
                            autoCapitalize="none"
                            autoCorrect="off"
                            spellCheck={ false }
                            enterKeyHint="search"
                            onChange={ event => setCountryQuery( event.target.value ) }
                          />
                          <SearchClearButton query={ countryQuery } placement="inline" onClear={ () => setCountryQuery( '' ) } />
                        </div>
                        { countries.length === 0 && (
                          <p className="country-empty" role="status">No countries found.</p>
                        ) }
                        <div id="auth-country-list" className="country-list" role="listbox" aria-label="Country code">
                          { countries.map( item => (
                            <button
                              key={ item.code }
                              type="button"
                              className="country-row"
                              role="option"
                              tabIndex={ -1 }
                              aria-selected={ item.code === dialCode }
                              onClick={ () => selectCountry( item.code ) }
                            >
                              <span>{ item.country }</span><span>{ item.code }</span>
                            </button>
                          ) ) }
                        </div>
                      </div>
                    ) }
                  </div>
                  <input
                    ref={ phoneRef }
                    id="auth-phone"
                    type="tel"
                    inputMode="numeric"
                    autoComplete="tel-national"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={ false }
                    enterKeyHint="next"
                    maxLength={ 18 }
                    placeholder="WhatsApp"
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
                <label className="sr-only" htmlFor="auth-code">WhatsApp code</label>
                <input
                  id="auth-code"
                  className="code-control"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  enterKeyHint="done"
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

            { error && <PublicNotice id="auth-error" mode="inline" tone="error" message={ error } /> }
            { !error && feedback && <PublicNotice mode="inline" tone="info" message={ feedback } /> }

            { step && (
              <div className="auth-actions">
                <button className="auth-action auth-primary" type="submit" disabled={ busy }>
                  { step.phase === 'phone' ? 'Sign in' : 'Verify' }
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
        .auth-card{width:min(100%,560px);max-width:100%;padding:clamp(28px,4vw,36px) clamp(24px,4.5vw,40px) clamp(30px,4.5vw,40px);border:0;border-radius:0;background:transparent;box-shadow:none;color:var(--public-text);font-family:var(--font-sans);box-sizing:border-box}
        /* Match the header navigation chip: soft neutral rounded square, not a circle. */
        .auth-eyebrow{display:flex;align-items:center;justify-content:center;width:48px;height:48px;margin:0 0 24px;border:0;border-radius:12px;background:var(--public-brand-lime);overflow:hidden;flex:0 0 auto;box-sizing:border-box}
        .auth-eyebrow-icon{width:34px;height:34px;display:block;object-fit:contain}
        .auth-label{display:block;margin:0 0 12px;color:var(--public-text);font-size:var(--public-card-size);font-weight:var(--public-card-weight);line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking)}
        /* Exact public-menu search treatment: no box, no side border, no fill; one bottom hairline. */
        .phone-control{position:relative;display:flex;align-items:stretch;width:100%;min-width:0;min-height:56px;border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;background:transparent;box-shadow:none;transition:border-color .2s,box-shadow .2s}
        .phone-control:focus-within{border-bottom-color:var(--public-brand-green);box-shadow:0 2px 0 0 var(--public-brand-green)}
        .country-picker{--public-hover-radius:6px;position:relative;display:flex;flex:0 0 auto;min-width:0}
        .country-trigger{min-width:92px;min-height:54px;padding:0 12px 0 2px;border:0;border-radius:var(--public-hover-radius);display:flex;align-items:center;justify-content:flex-start;gap:8px;background:transparent;color:var(--public-brand-green);font:600 var(--public-body-size)/1 var(--font-sans);white-space:nowrap;touch-action:manipulation;cursor:pointer}
        .country-trigger[aria-expanded='true']{background:var(--public-lime-tint)}
        @media(hover:hover) and (pointer:fine){.country-trigger:not(:disabled):hover{background:var(--public-hover-surface)}}
        .country-arrow{color:var(--public-nav-arrow)}
        .country-arrow svg{display:block;flex:none}
        .country-trigger[aria-expanded='true'] .country-arrow{transform:rotate(180deg)}
        .country-trigger:focus-visible{outline:2px solid var(--public-brand-green);outline-offset:-2px;z-index:2}
        .phone-control>input,.code-control{min-width:0;width:100%;min-height:54px;padding:0 2px 0 14px;border:0;border-radius:0;background:transparent;color:var(--public-text);font:var(--public-body-weight) var(--public-body-size)/1.2 var(--font-sans);letter-spacing:var(--public-body-tracking);text-overflow:ellipsis;box-shadow:none;outline:0;-webkit-appearance:none;appearance:none}
        .phone-control>input::placeholder,.code-control::placeholder{color:var(--public-muted)}
        .phone-control>input:focus-visible,.code-control:focus-visible{outline:0}
        .country-row:focus-visible{outline:2px solid var(--public-brand-green);outline-offset:-2px}
        .code-control{border:0;border-bottom:1px solid var(--public-hairline);border-radius:0;box-shadow:none;transition:border-color .2s,box-shadow .2s}
        .code-control:focus{border-bottom-color:var(--public-brand-green);box-shadow:0 2px 0 0 var(--public-brand-green)}
        .country-panel{position:fixed;z-index:1200;display:flex;flex-direction:column;box-sizing:border-box;min-width:0;overflow:hidden;border:1px solid var(--public-hairline);border-radius:8px;background:var(--public-bg);box-shadow:0 6px 20px rgba(26,58,42,.10);overscroll-behavior:contain;padding:4px}
        .country-search{display:flex;align-items:center;gap:4px;min-width:0;padding:0 4px 4px;border-bottom:0;flex:0 0 auto}
        .country-search input{width:100%;min-width:0;flex:1;min-height:44px;margin:0;padding:0 10px;border:0;border-bottom:2px solid var(--public-search-underline);border-radius:var(--public-hover-radius);background:transparent;color:var(--public-body);font:500 var(--public-supporting-size)/1.2 var(--font-sans);outline:0}
        .country-search input::-webkit-search-cancel-button,.country-search input::-webkit-search-decoration{display:none;-webkit-appearance:none}
        .country-search input::-ms-clear{display:none}
        .country-search input:focus{border-bottom-color:var(--public-search-underline);box-shadow:var(--public-search-focus-shadow);outline:none}
        @media (hover:hover) and (pointer:fine){.country-search input:hover{background:var(--public-hover-surface)}}
        @media (forced-colors: active){.country-search input:focus{outline:2px solid Highlight;outline-offset:-2px}}
        .country-list{min-height:0;flex:1 1 auto;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;scrollbar-gutter:stable;padding:2px}
        .country-row{width:100%;box-sizing:border-box;min-height:48px;padding:10px 10px;border:0;border-inline-start:2px solid transparent;border-radius:var(--public-hover-radius);background:transparent;display:flex;align-items:center;justify-content:space-between;gap:8px;text-align:start;color:var(--public-brand-green);font:600 var(--public-supporting-size)/1.3 var(--font-sans);touch-action:manipulation;cursor:pointer}
        .country-row>span:first-child{min-width:0;overflow-wrap:anywhere;white-space:normal}
        .country-row>span:last-child{flex:0 0 auto;font-variant-numeric:tabular-nums}
        .country-empty{margin:0;padding:18px 14px;color:var(--public-muted);font-size:var(--public-supporting-size);line-height:1.4}
        @media(hover:hover) and (pointer:fine){.country-row:not([aria-selected='true']):hover{background:var(--public-hover-surface)}}
        .country-row[aria-selected='true']{background:var(--public-lime-tint);border-inline-start-color:var(--public-brand-green);font-weight:700}
        @media(forced-colors:active){.country-row[aria-selected='true']{border-inline-start-color:Highlight}}
        /* Shared action treatment for Sign in, Verify, Resend and Edit on all viewports. */
        .auth-actions{display:flex;align-items:stretch;flex-wrap:wrap;gap:10px;margin-top:22px;width:100%}
        .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
        @media(max-width:1024px){
          .auth-card{width:min(100%,540px)}
        }
        @media(max-width:767px){
          .auth-card{width:100%;padding:28px 20px max(30px,env(safe-area-inset-bottom))}
          .auth-eyebrow{width:46px;height:46px;margin-bottom:22px;border-radius:11px}
          .auth-eyebrow-icon{width:32px;height:32px}
          .auth-label{font-size:var(--public-mobile-card-size)}
          .phone-control{min-height:54px}
          .country-trigger{min-width:82px;min-height:52px;padding:0 10px 0 2px;font-size:16px}
          .phone-control>input{min-height:52px;padding:0 2px 0 12px;font-size:16px}
          .code-control{min-height:52px;padding:0 2px;border-radius:0;font-size:16px}
          .country-search input{min-height:48px;font-size:16px}
          .country-row{min-height:48px;padding:10px;font-size:16px}
        }
        @media(max-width:480px){
          .auth-actions{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;width:100%}
          .auth-primary{grid-column:1/-1}
          .auth-action{width:100%;min-width:0}
        }
        @media(max-width:359px){
          .auth-card{padding-inline:16px}
          .country-trigger{min-width:74px;padding-inline-end:8px;gap:6px}
          .phone-control>input{padding-inline-start:10px}
          .country-row{gap:6px;padding-inline:6px}
          .country-search input{padding-inline:4px}
        }
        @media(max-width:279px){
          .auth-card{padding-inline:10px}
          .phone-control{flex-wrap:wrap}
          .country-picker{flex:0 0 100%}
          .phone-control>input{padding-inline-start:2px;flex:0 0 100%}
          .auth-actions{grid-template-columns:minmax(0,1fr)}
        }
        @media(prefers-reduced-motion:reduce){
          .phone-control,.code-control{transition:none}
        }
        @media(max-height:600px) and (min-width:768px){
          .auth-card{padding-top:28px;padding-bottom:30px}
          .auth-eyebrow{margin-bottom:24px}
          /* Picker height follows the measured visual viewport. */
        }
      `}</style>
    </>
  );
};

export default AuthPage;
