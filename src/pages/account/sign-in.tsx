/**
 * /account/sign-in/ - the customer OTP sign-in / register step that gates checkout.
 *
 * WHAT THIS IS. A minimal WhatsApp-OTP sign-in built on src/lib/customerAuth.ts, reached when a
 * shopper proceeds from the cart without a session. It signs the shopper in and returns them to
 * the cart (or wherever `return` in the query string points) with the cart intact - the cart lives
 * in localStorage (src/lib/cart.ts), so it survives this hop untouched.
 *
 * WHAT THIS IS NOT. It does not reimplement any OTP crypto: requestOtp / submitOtp talk to Cognito
 * directly and the code is delivered over WhatsApp by the pool trigger. This page only collects a
 * number and a code and calls those functions.
 *
 * THE COUNTRY CODE IS AN EXPLICIT, REQUIRED FIELD, on owner instruction.
 * customerAuth.normaliseMobile() infers +91 for any ten digits beginning 6-9, which is right for
 * this market and silent everywhere else: a ten-digit number from another country was accepted and
 * then signed in as an Indian one. That function is NOT changed - its docblock requires it to match
 * the backend's normalisation byte for byte, and a disagreement means a customer signs in
 * successfully and owns nothing. So the dial code is composed here instead, ahead of it: this page
 * always hands over a string that already carries a country code, which leaves normaliseMobile
 * nothing to infer and reduces it to the length check it also performs on the server. The select
 * defaults to +91 because that is the market, not because the field is optional - it is `required`,
 * always submitted, and always applied.
 *
 * THE SEND-FAILURE ERROR NAMES NO CAUSE IT CANNOT PROVE. The registration front door answers 502
 * {status:'send_failed'} when the challenge was stored but the WhatsApp message did not go - which
 * is what happens when the number is not reachable on WhatsApp, and ALSO what happens when Meta's
 * send fails transiently. The two are indistinguishable from the browser, so this page does NOT
 * mention WhatsApp in that message: it says the code could not be sent and asks the shopper to
 * check the number. An earlier version named WhatsApp explicitly ("Check the country code and that
 * it is your WhatsApp number"), which is a confident wrong answer about our own outage every time
 * the second cause is the real one. "Use a WhatsApp number." is reserved for the case where
 * provider evidence supports it, which needs the recipient-not-found code from Meta surfaced by the
 * backend; see docs/execution/website-payment-handover.md.
 *
 * A CONTRADICTORY PASTED PREFIX IS REJECTED RATHER THAN CONCATENATED. See composeE164 - the
 * fifteen-digit case it describes produced a valid-looking number for a customer who does not
 * exist, which is worse than an error.
 *
 * THE HONEST UNREGISTERED-NUMBER HANDLING. customerAuth.ts documents that Cognito returns a masked
 * challenge for an UNKNOWN number too (PreventUserExistenceErrors), and no code is ever sent to
 * one - so claiming "we sent you a code" would be a lie for a number that is not a customer. When
 * requestOtp reports `registered: false` this page does NOT show an OTP box; it routes the shopper
 * through the registration front door (POST /auth/customer-registration {action:'request'|'verify'})
 * to create the customer, then completes sign-in via customerAuth.submitOtp.
 *
 * TWO CODES, NOT ONE, ON THE REGISTER PATH. The registration handler never returns a session
 * credential - "the session credential comes from the Cognito sign-in, not from here." So once
 * `verify` provisions the login, the shopper still has to complete the ordinary WhatsApp-OTP
 * CUSTOM_AUTH sign-in, and that Cognito challenge sends its OWN, second code. This page treats that
 * as its own step (the `signin-code` phase): it starts the Cognito challenge, says a fresh code is
 * on its way, and answers the challenge with THAT code - it never replays the registration code,
 * which Cognito would reject.
 *
 * CHROME AND INDEXING. This is a customer-session route registered in the _app.tsx isPublic chain
 * beside /checkout/status and /checkout/success; it is noindex and imports no Layout/Header/Footer/
 * SupportWidget (those are mounted centrally). It is intentionally absent from PUBLIC_PAGE_META,
 * the sitemap and the browser route lists.
 */

import Head from 'next/head';
import Link from 'next/link';
import React, { useCallback, useEffect, useState } from 'react';

import OtpResend from '../../components/OtpResend';
import PageTopBand from '../../components/PageTopBand';
import PhoneField from '../../components/PhoneField';
import PillButton from '../../components/PillButton';
import { DEFAULT_DIAL_CODE } from '../../lib/dialCodes';
import {
  requestOtp, submitOtp, normaliseMobile, getSession, restoreSession, nextSessionFrom,
} from '../../lib/customerAuth';
import * as signInMessages from '../../lib/signInMessages';
import { safeLocalReturnPath } from '../../lib/safeReturnPath';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const REGISTRATION_URL = `${API_BASE}/auth/customer-registration`;

/**
 * THE OWNER'S MESSAGE TABLE, verbatim, and the only strings this page shows for a failure.
 *
 * WHY A TABLE AND NOT INLINE LITERALS. Two of these are a hair apart in wording and far apart in
 * meaning - CHECK_NUMBER points the shopper at their own number, TRY_LATER tells them it is our
 * problem - and the entire honesty question on this page is which one a given server response earns.
 * Naming them makes that choice reviewable at the call site instead of buried in a ternary.
 *
 * NOT_ON_WHATSAPP IS DEFINED BUT DELIBERATELY NEVER USED, and the comment is the point of it. The
 * only signal the backend offers today is the registration front door's 502 {status:'send_failed'},
 * which covers a number that is genuinely unreachable on WhatsApp AND a transient failure in Meta's
 * send. Those are indistinguishable from the browser, so asserting the first would be a confident
 * wrong answer about our own outage every time the second is the real cause. This message becomes
 * usable only when the backend surfaces Meta's recipient-not-found code; until then the generic
 * CHECK_NUMBER is the honest line. It is kept here, unused, so the next person to wire that signal
 * finds the approved wording rather than inventing one.
 *
 * NONE OF THESE DISTINGUISH A REGISTERED NUMBER FROM AN UNKNOWN ONE. That is a hard requirement, not
 * a nicety: the sign-in front door must not become a way to discover who is a customer, so the same
 * string is shown for the same failure whether or not the number has an account behind it.
 */
const MSG = {
  /*
   * SOURCED FROM ../../lib/signInMessages, which holds all seven section-6 strings verbatim in one
   * auditable place. This page no longer re-types the copy; it references the approved constants, so
   * the wording cannot drift between the page and the test that pins it.
   *
   * MISSING_CODE IS PRESENT BUT DELIBERATELY NOT WIRED TO A REACHABLE STATE. It read "Include your
   * country code, like +91." and existed for the single-input version of this field, where the
   * shopper had to type the code and could leave it out. The field is now divided (PhoneField) and
   * its leading segment always carries a code, so the state the message described cannot occur -
   * there is no input that produces it. The owner's §25 selector wording "Choose a country code." is
   * unreachable for the same reason: a <select> with a default always has a value. The approved
   * string is kept as a named constant so the sanctioned wording is present and auditable, NOT
   * forced into a code path just to make it render - a message no state earns is one the next person
   * wires to the wrong condition.
   */
  MISSING_CODE: signInMessages.MISSING_CODE,
  /** Invalid number or format. */
  BAD_NUMBER: signInMessages.BAD_NUMBER,
  /** Reserved for provider evidence this page does not yet receive. See signInMessages. */
  NOT_ON_WHATSAPP: signInMessages.NOT_ON_WHATSAPP,
  /** Generic delivery failure, or unknown WhatsApp availability. */
  CHECK_NUMBER: signInMessages.CHECK_NUMBER,
  /** Provider temporary outage - our side, so it does not send the shopper to edit anything. */
  TRY_LATER: signInMessages.TRY_LATER,
  /** Invalid code, attempts remaining. */
  BAD_CODE: signInMessages.BAD_CODE,
  /** The challenge is no longer answerable. */
  CODE_EXPIRED: signInMessages.CODE_EXPIRED,
  /** Send or guess limit reached. */
  RATE_LIMITED: signInMessages.RATE_LIMITED,
} as const;

/**
 * Which message a thrown Cognito failure earns.
 *
 * cognito() in customerAuth.ts sets error.name from the __type Cognito returns, so the name is the
 * classification and nothing has to be parsed out of a human-readable message. The distinction that
 * matters: a dead challenge is the shopper's cue to SEND A NEW CODE, while a throttle is a cue to
 * WAIT - telling someone who is rate-limited to request another code sends them straight back into
 * the limit.
 */
function messageForAuthError ( error: unknown ): string {
  const name = String( ( error as { name?: string } )?.name || '' );
  if ( /TooManyRequests|LimitExceeded|TooManyFailedAttempts/i.test( name ) ) return MSG.RATE_LIMITED;
  // NotAuthorizedException on a CUSTOM_AUTH challenge means the whole attempt is finished - the
  // session is spent or timed out - so the only way forward is a fresh code, not another guess.
  if ( /ExpiredCode|NotAuthorized|ExpiredToken|ResourceNotFound/i.test( name ) ) return MSG.CODE_EXPIRED;
  if ( /CodeMismatch/i.test( name ) ) return MSG.BAD_CODE;
  return MSG.TRY_LATER;
}

/**
 * Which message a REJECTED registration code earns.
 *
 * Separate from messageForHttpStatus because the default is the opposite way round. On a send the
 * unexplained failure is ours, so the shopper is told to wait; on a code submission the overwhelming
 * cause is a mistyped code, so an unexplained 4xx says to check it. Only a 5xx is read as our fault.
 * RATE_LIMITED and CODE_EXPIRED are split out first because "wait" and "send a new one" are opposite
 * instructions - handing a throttled shopper the second walks them straight back into the limit.
 */
function messageForVerifyRejection ( status: number, payload: string ): string {
  if ( status === 429 ) return MSG.RATE_LIMITED;
  if ( status === 410 || /expired/i.test( payload ) ) return MSG.CODE_EXPIRED;
  if ( status >= 500 ) return MSG.TRY_LATER;
  return MSG.BAD_CODE;
}

/** Which message an HTTP status from the registration front door's SEND earns. */
function messageForHttpStatus ( status: number, payload: string ): string {
  if ( status === 429 ) return MSG.RATE_LIMITED;
  if ( status === 410 || /expired/i.test( payload ) ) return MSG.CODE_EXPIRED;
  // 502, or an explicit send_failed, is the only send-failure signal there is, and it cannot tell a
  // number that is not on WhatsApp from a Meta outage. The generic line points at the number without
  // asserting anything about it. See MSG.NOT_ON_WHATSAPP.
  if ( status === 502 || /send_failed/i.test( payload ) ) return MSG.CHECK_NUMBER;
  return MSG.TRY_LATER;
}

/** Where to send the shopper once signed in. Defaults to the cart. */
function returnPathFromUrl (): string {
  if ( typeof window === 'undefined' ) return '/cart/';
  const raw = String( new URLSearchParams( window.location.search ).get( 'return' ) || '' ).trim();
  // Reject-by-default allowlist. The regex this replaced claimed it "can never be turned into
  // an open redirect" and two measured inputs falsified that: `//evil` passed every character
  // in the class while a browser reads the leading `//` as protocol-relative and resolves
  // `evil` as a HOST, and `/workspace/access` passed as a well-formed local path while being
  // the STAFF login. See src/lib/safeReturnPath.ts for why this is an allowlist and not a
  // character class. It returns the value to use rather than a boolean, so what was checked
  // is what navigates.
  return safeLocalReturnPath( raw );
}

/**
 * The step the form is on.
 *   'phone'         collect the country code and the number.
 *   'code'          registered path: answer the live Cognito challenge from requestOtp.
 *   'register-code' unregistered path: answer the registration front-door OTP (creates the customer).
 *   'signin-code'   unregistered path, second leg: answer the SECOND, Cognito sign-in code that the
 *                   CUSTOM_AUTH challenge sends after the customer is provisioned.
 */
type Phase = 'phone' | 'code' | 'register-code' | 'signin-code';

export default function CustomerSignIn (): React.ReactElement {
  const [ phase, setPhase ] = useState<Phase>( 'phone' );
  /*
   * TWO PIECES OF STATE FOR ONE FIELD, which is what the divided control needs. The dial code is a
   * selection with a VISIBLE default; the number is whatever was typed, unnormalised.
   *
   * This replaces a single `mobile` string that was prefilled "+91 " and parsed. The prefill existed
   * to make the required shape obvious; a segment that shows "+91" does that better, and without
   * asking the shopper to type a prefix they can get wrong.
   */
  const [ dialCode, setDialCode ] = useState<string>( DEFAULT_DIAL_CODE );
  const [ national, setNational ] = useState<string>( '' );
  const [ normalised, setNormalised ] = useState<string>( '' );
  const [ persistent, setPersistent ] = useState<boolean>( true );
  const [ code, setCode ] = useState<string>( '' );
  const [ session, setSession ] = useState<string>( '' );
  const [ destination, setDestination ] = useState<string>( '' );
  const [ error, setError ] = useState<string>( '' );
  const [ busy, setBusy ] = useState<boolean>( false );

  // Already signed in: nothing to do here, go straight back.
  useEffect( () => {
    if ( getSession() ) window.location.replace( returnPathFromUrl() );
    else void restoreSession().then( restored => {
      if ( restored ) window.location.replace( returnPathFromUrl() );
    } ).catch( () => setError( 'Sign-in is temporarily unavailable. Please try again.' ) );
  }, [] );

  /**
   * The single field's contents, as the E.164 string the backend will key the customer on.
   *
   * THE CODE COMES FROM THE SEGMENT, AND IS STILL NEVER INFERRED. The divided field always carries a
   * dial code, so there is no "missing country code" state left to refuse - which is why MSG no
   * longer has a MISSING_CODE entry. The guarantee that message existed to protect is intact and now
   * structural rather than conditional: normaliseMobile() treats any ten digits starting 6-9 as
   * Indian, which is right for the store's market and wrong for everyone else, and a shopper in
   * Dubai would have no way to see it happen. A code is never inferred here because one is always
   * SELECTED and on screen - see DEFAULT_DIAL_CODE.
   */
  const composeE164 = useCallback( (): string => {
    const raw = String( national || '' ).trim();
    if ( !raw ) throw new Error( MSG.BAD_NUMBER );
    /*
     * A PASTED INTERNATIONAL NUMBER BEATS THE SELECTOR, and this is not a nicety. People paste
     * "+971 50 123 4567" into a number box constantly. Prefixing the selected code regardless would
     * build "+91971501234567" - a number that is wrong in a way the shopper cannot see, because
     * both the code they pasted and the code on screen look right.
     *
     * "00" counts as a typed code too: it is how the international prefix is dialled across much of
     * Europe and the Gulf, and someone who types it means exactly what "+" means.
     */
    const typedOwnCode = /^(\+|00)/.test( raw );
    const digits = typedOwnCode
      // Strip the international prefix itself, then any zeros it was padded with, so "+0091…",
      // "0091…" and "+91…" all reduce to the same digits.
      ? raw.replace( /^(\+|00)/, '' ).replace( /\D/g, '' ).replace( /^0+/, '' )
      // Otherwise the selection supplies the code. The national part has its trunk zero stripped -
      // "09876543210" is how the same number is dialled domestically in much of the world.
      : dialCode.replace( /\D/g, '' ) + raw.replace( /\D/g, '' ).replace( /^0+/, '' );
    if ( !digits ) throw new Error( MSG.BAD_NUMBER );
    // normaliseMobile is the single source of the E.164 rule and the length bound, and is NOT
    // changed - it has to match the backend byte for byte. It is handed a string that already
    // carries the country code, so its ten-digit +91 inference cannot fire. Its own message is
    // restated in this page's short form rather than surfaced raw.
    try
    {
      return normaliseMobile( digits );
    }
    catch
    {
      throw new Error( MSG.BAD_NUMBER );
    }
  }, [ dialCode, national ] );

  const startPhone = useCallback( async ( event: React.FormEvent ): Promise<void> => {
    event.preventDefault();
    setError( '' );
    // There is no missing-country-code guard at all now: the divided field's leading segment always
    // carries one, so the only thing composeE164 can refuse is the number itself.
    let e164 = '';
    try
    {
      e164 = composeE164();
    }
    catch ( err )
    {
      setError( ( err as Error ).message );
      return;
    }
    setBusy( true );
    try
    {
      const challenge = await requestOtp( e164 );
      setNormalised( e164 );
      if ( challenge.registered )
      {
        // A real customer: Cognito's challenge is live, so the code was genuinely sent.
        setSession( challenge.session );
        setDestination( challenge.destination );
        setPhase( 'code' );
      }
      else
      {
        // Unknown number. NO code was sent (see customerAuth.ts), so do not pretend one was -
        // register the number through the front door, which sends its own WhatsApp OTP.
        //
        // SAFETY CONTRACT: this branch discards `challenge.session` and pushes the shopper into
        // registration. That is only correct while the CreateAuthChallenge trigger guarantees it
        // sends NO WhatsApp code when it reports `registered:false` - i.e. `registered:false`
        // means "no live code is outstanding," never "a code was sent to a real customer." If the
        // trigger ever changes to send a code alongside `registered:false`, this branch would
        // strand that real customer (their live Cognito code is thrown away and they are asked to
        // register instead), and it must switch to honouring `challenge.session` here.
        const response = await fetch( REGISTRATION_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( { action: 'request', phone: e164 } ),
        } );
        if ( !response.ok )
        {
          // 502 send_failed MUST NOT BE REPORTED AS "not a WhatsApp number", and this is the
          // correction rather than the original wording. That status covers two causes which are
          // indistinguishable from here - a number that is genuinely not reachable on WhatsApp,
          // and a transient failure in Meta's send - so naming WhatsApp specifically is a
          // confident wrong answer about our own outage on every occurrence of the second. The
          // owner's message table reserves "Use a WhatsApp number." for the case where provider
          // evidence supports it, which needs the recipient-not-found code surfaced by the
          // backend; until then both causes take the generic line, which points at the number
          // without asserting anything about it. The other refusals are an outage on our side and
          // say to wait rather than to check anything.
          const data = ( await response.json().catch( () => ( {} ) ) ) as { status?: string };
          setError( messageForHttpStatus( response.status, String( data.status || '' ) ) );
          return;
        }
        setDestination( '' );
        setPhase( 'register-code' );
      }
    }
    catch ( err )
    {
      // requestOtp throws for two different reasons and they do not share a message. A rejected
      // NUMBER is the shopper's to fix; a throttle or a Cognito fault is not. normaliseMobile's own
      // rejection is restated in the approved short form rather than surfaced raw.
      const raw = ( err as Error ).message || '';
      setError( /valid mobile number|valid number/i.test( raw )
        ? MSG.BAD_NUMBER
        : messageForAuthError( err ) );
    }
    finally
    {
      setBusy( false );
    }
  }, [ composeE164 ] );

  const submitCode = useCallback( async ( event: React.FormEvent ): Promise<void> => {
    event.preventDefault();
    setError( '' );
    setBusy( true );
    try
    {
      if ( phase === 'register-code' )
      {
        // Leg one of the register path: verify the FRONT-DOOR code, which provisions the login.
        // This does NOT sign the shopper in - the registration handler never returns a session.
        const response = await fetch( REGISTRATION_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( { action: 'verify', phone: normalised, code: code.trim() } ),
        } );
        if ( !response.ok )
        {
          const data = ( await response.json().catch( () => ( {} ) ) ) as { status?: string };
          setError( messageForVerifyRejection( response.status, String( data.status || '' ) ) );
          return;
        }
        // Leg two: start the Cognito CUSTOM_AUTH sign-in, which sends its own, SECOND code. Move to
        // a fresh code step and clear the input so the shopper enters that new code, not the old one.
        const challenge = await requestOtp( normalised );
        setSession( challenge.session );
        setDestination( challenge.destination );
        setCode( '' );
        setPhase( 'signin-code' );
        return;
      }

      // Registered path AND the second leg of the register path both answer a live Cognito
      // challenge with the code the shopper just entered against the session we hold.
      let result;
      try
      {
        result = persistent ? await submitOtp( normalised, code, session ) : await submitOtp( normalised, code, session, false );
      }
      catch ( err )
      {
        // Cognito failed the whole attempt but may hand back a session for a retry. WHICH message
        // this earns depends on WHY: a spent or timed-out challenge needs a new code, a throttle
        // needs a pause, and telling a throttled shopper to send another code is the one answer
        // that makes their situation worse.
        const next = nextSessionFrom( err );
        if ( next ) setSession( next );
        setError( messageForAuthError( err ) );
        return;
      }
      if ( !result )
      {
        // Cognito re-issued the challenge: wrong code, attempts remain.
        setError( MSG.BAD_CODE );
        return;
      }
      window.location.replace( returnPathFromUrl() );
    }
    catch ( err )
    {
      setError( messageForAuthError( err ) );
    }
    finally
    {
      setBusy( false );
    }
  }, [ phase, normalised, code, session, persistent ] );

  /**
   * ASK FOR ANOTHER CODE. This page had no resend affordance at all, which the Phase 4 audit
   * measured as the one functional gap in the OTP surfaces: a shopper whose WhatsApp code never
   * arrived had nothing to press and had to leave the page. OtpResend owns the control, the
   * wording and the 30s cooldown; this callback owns only which send to repeat.
   *
   * IT REPEATS THE SEND THAT GOT US TO THIS PHASE, rather than starting over, and the three
   * phases do not share one send:
   *   'register-code'  the registration front door, which issues its own WhatsApp OTP.
   *   'code' / 'signin-code'  the Cognito CUSTOM_AUTH challenge, via requestOtp.
   * requestOtp returns a NEW session, and it is stored - answering the new code against the
   * old session is a guaranteed rejection, which would read to the shopper as "the resend
   * broke the page".
   *
   * `code` IS CLEARED. Whatever is in the box belongs to the superseded challenge. Leaving it
   * would let a shopper press Confirm on a code that can no longer be right.
   *
   * THE MESSAGES ARE THE EXISTING TABLES. A resend fails for exactly the reasons a first send
   * fails, so messageForHttpStatus and messageForAuthError are reused rather than a third
   * wording invented here - and RATE_LIMITED is the one that matters, because this is the
   * control most likely to reach a throttle.
   */
  const resendCode = useCallback( async (): Promise<void> => {
    if ( !normalised ) return;
    setError( '' );
    setBusy( true );
    try
    {
      if ( phase === 'register-code' )
      {
        const response = await fetch( REGISTRATION_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify( { action: 'request', phone: normalised } ),
        } );
        if ( !response.ok )
        {
          const data = ( await response.json().catch( () => ( {} ) ) ) as { status?: string };
          setError( messageForHttpStatus( response.status, String( data.status || '' ) ) );
          return;
        }
        setCode( '' );
        return;
      }
      const challenge = await requestOtp( normalised );
      setSession( challenge.session );
      setDestination( challenge.destination );
      setCode( '' );
    }
    catch ( err )
    {
      setError( messageForAuthError( err ) );
    }
    finally
    {
      setBusy( false );
    }
  }, [ phase, normalised ] );

  return (
    <>
      <Head>
        <title>Sign in — WECARE.DIGITAL</title>
        {/* Customer-session, per-person, transactional: never indexed. */}
        <meta name="robots" content="noindex,nofollow" />
      </Head>
      <PageTopBand
        heading="Sign in to check out"
        sub="We confirm it is you with a code on WhatsApp. New here? Same step sets you up."
        ariaLabel="Customer sign in"
      >
        <div className="si-card">
          {phase === 'phone' && (
            <form className="si-form" onSubmit={ startPhone }>
              {/* ONE FIELD, DIVIDED, on owner instruction: "countcode + number should bin same
                  dived divide and rounded corner". PhoneField owns the anatomy and the CSS; this
                  page owns only the label, the hint and what the two segments mean. See that
                  component for the Material 3 grounding and the two documented departures from it.
                  The <label> points at the NUMBER segment, which is the part a shopper types into.
                  The code segment carries its own aria-label, because a visible second label inside
                  the box would defeat the point of the box. */}
              <label className="si-label" htmlFor="si-mobile">WhatsApp number</label>
              {/* aria-invalid AND aria-describedby, because the error is rendered at the BOTTOM of
                  the card rather than beside the field it concerns. role=alert announces it once,
                  but without the association a screen-reader user who tabs back to the input to
                  correct it gets no indication that this is the control at fault. The hint is in
                  the same description list so it is not lost when the error appears. */}
              <PhoneField
                id="si-mobile"
                dialCode={ dialCode }
                onDialCodeChange={ setDialCode }
                number={ national }
                onNumberChange={ setNational }
                disabled={ busy }
                invalid={ !!error }
                describedBy={ error ? 'si-hint si-error' : 'si-hint' }
/* NO placeholder OVERRIDE. PhoneField derives it from the selected country's own
                   length rule - "10-digit WhatsApp number" on +91, "8- or 9-digit WhatsApp
                   number" on +971 - the owner's requested resting-state wording, derived from the
                   same table the validation reads so it cannot contradict what the field accepts.
                   This also closes the root cause upstream identified for the reported failure:
                   the old hardcoded "9876543210" is a structurally valid Indian mobile number, so
                   in placeholder grey it read as a value ALREADY IN THE FIELD - the shopper
                   submitted, the then-present `required` refused an empty input, and the browser
                   objected about a field that visibly contained a number. A worded hint cannot be
                   mistaken for a value. */
                /*
                 * onInvalid IS KEPT FROM UPSTREAM, THOUGH `required` IS NOW GONE.
                 *
                 * Upstream added this to mirror the browser's native refusal into this page's own
                 * error region, because `required` blocked submit so startPhone never ran and
                 * composeE164's empty-number branch - and the approved BAD_NUMBER message - were
                 * UNREACHABLE. Correct diagnosis. The resolution differs only because the owner
                 * reported the native bubble ITSELF as the defect (unthemeable, untranslatable,
                 * and against the standing no-red rule), so `required` was removed instead.
                 *
                 * With no constraint the browser no longer blocks submit: startPhone runs,
                 * composeE164 rejects the empty value, and BAD_NUMBER lands in the in-page error
                 * region - the same destination upstream was routing to, reached without the
                 * bubble. This handler therefore never fires today and is retained deliberately:
                 * it costs nothing, and it is the correct wiring the moment any constraint
                 * attribute is added back.
                 */
                onInvalid={ () => setError( MSG.BAD_NUMBER ) }
              />
              {/* A text node, so it translates. It no longer tells the shopper to include a country
                  code - the segment beside the number does that - so the line says the one thing
                  left that they cannot see for themselves: the code arrives on WhatsApp, so the
                  number has to be the one WhatsApp is on. */}
              <p className="si-hint" id="si-hint">
                Pick your country code, then the number WhatsApp is on.
              </p>
              {/* THE TWO-SEGMENT PILL, the home-page phone-number treatment (PillButton). The LEFT
                  segment is the static "Sign in" label; the RIGHT segment is the ACTION, which is
                  also the control's accessible name - so the button still answers to "Send code"
                  (and "Sending…" while busy), the name the sign-in tests pin. Semantics are
                  unchanged: a real type="submit" that runs startPhone, disabled while busy.

                  The run-together "Sign inSend code" the owner reported was a styled-jsx SCOPING
                  failure, not a duplicate label: the segments were hoisted into a variable, so
                  they shipped with no `jsx-*` hash against rules that required one and rendered
                  completely unstyled. Fixed upstream in 2f742ec6, which also unified /get onto
                  this same pill. See PillButton's docblock. */}
              <PillButton
                as="button"
                type="submit"
                label="Sign in"
                action={ busy ? 'Sending…' : 'Send OTP on WhatsApp' }
                disabled={ busy }
                busy={ busy }
                describedBy={ error ? 'si-error' : undefined }
              />
            </form>
          )}

          {( phase === 'code' || phase === 'register-code' || phase === 'signin-code' ) && (
            <form className="si-form" onSubmit={ submitCode }>
              {/* SHORTENED, AND "all set up" IS LOAD-BEARING RATHER THAN DECORATIVE. On the
                  signin-code leg the shopper has just answered one code and is being asked for a
                  second one, which reads as a failure of the first unless the screen says the
                  registration worked. "Enter it below" was dropped from all four: the labelled
                  input directly beneath is the instruction. */}
              <p className="si-body">
                { phase === 'signin-code'
                  ? ( destination
                    ? `You're all set up. New code sent on WhatsApp to ${destination}.`
                    : "You're all set up. New code sent on WhatsApp." )
                  : ( phase === 'code' && destination
                    ? `Code sent on WhatsApp to ${destination}.`
                    : 'Code sent on WhatsApp.' ) }
              </p>
              <label className="si-label" htmlFor="si-code">WhatsApp code</label>
              <input
                id="si-code"
                className="si-input"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                aria-invalid={ error ? 'true' : undefined }
                aria-describedby={ error ? 'si-error' : undefined }
                value={ code }
                onChange={ e => setCode( e.target.value ) }
                disabled={ busy }
              />
              <label className="si-remember">
                <input type="checkbox" checked={ persistent } onChange={ e => setPersistent( e.target.checked ) } />
                Keep me signed in on this device
              </label>
              {/* Same two-segment pill. The right segment carries "Confirm code" (and "Checking…"
                  while busy), which is both the visible action and the accessible name the test
                  queries - this is the button the owner saw render as "Sign inConfirm code",
                  which 2f742ec6 fixed by restoring the segments' styled-jsx scoping.
                  Real type="submit" running submitCode, disabled while busy. */}
              <PillButton
                as="button"
                type="submit"
                label="Sign in"
                action={ busy ? 'Checking…' : 'Confirm WhatsApp code' }
                disabled={ busy }
                busy={ busy }
                describedBy={ error ? 'si-error' : undefined }
              />
              {/* THE WAY OUT OF A CODE THAT NEVER ARRIVED. This page had none, which is the
                  functional half of the owner's OTP report. The control is the derived
                  SECONDARY - white fill, lime on hover - so the lime primary above it is still
                  the only lime surface on the page. OtpResend owns the wording and the
                  cooldown so this and /get/ cannot drift apart again. */}
              <div className="si-resend">
                <OtpResend onResend={ () => { void resendCode(); } } busy={ busy } />
              </div>
            </form>
          )}

          {error && <p className="si-error" id="si-error" role="alert">{ error }</p>}

          <p className="si-back"><Link href="/cart/">Back to your cart</Link></p>
        </div>

        <style jsx>{`
          /* No top padding, no measure, no font stack: PageTopBand owns all three. 460px is the
             form's own measure, inside the band's 1300px. */
          .si-remember{display:flex;align-items:center;gap:10px;margin:16px 0;color:#1a3a2a;font-size:16px}
          .si-remember input{accent-color:#b8e24a;width:18px;height:18px}
          .si-card{width:100%;max-width:460px;margin:0}
          .si-form{display:flex;flex-direction:column}
          /* The body rung, 20px/400/1.4/-.125px at rgba(0,0,0,.898). It was 16px at .7 alpha,
             which is neither rung this site has. */
          .si-body{
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);margin:0 0 24px;
          }
          .si-label{font-size:14px;font-weight:700;color:#1a3a2a;margin-bottom:8px}
          /* 52px, matching the CTA below it, so the field and the button it feeds are the same
             height. 1px #e5e7eb is the static hairline. */
          .si-input{
            min-height:52px;padding:0 16px;border:1px solid #e5e7eb;border-radius:999px;
            font-family:inherit;font-size:17px;color:#1a1a1a;background:#fff;margin-bottom:20px;
            box-sizing:border-box;
          }
          /* .si-input now dresses the CODE field only. The WhatsApp number is PhoneField, which owns
             its own outline, radius and height - so the two controls on this page are styled in two
             places on purpose, and the numbers above are the ones PhoneField matches. */
          .si-input:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px;box-shadow:0 0 0 3px rgba(209,244,112,.28)}
          /* THE CODE FIELD NEEDS THE SAME HEADER CLEARANCE THE NUMBER FIELD HAS, and it needs
             it MORE: the code phase is reached by submitting, which moves focus into this input
             on a page the shopper has usually already scrolled. Without it the browser reveals
             the field at the top of the scrollport, which is behind the fixed 108px header - so
             the shopper cannot see the code they are typing. 128px/112px are the site's
             clearance constants for this header; see the long note on .pf-num in PhoneField for
             why this is scroll-margin on the input and not scroll-padding on the document. */
          .si-input{scroll-margin-top:128px}
          .si-hint{
            margin:0 0 20px;font-size:16px;line-height:1.55;color:rgba(0,0,0,.54);
          }
          /* THE PRIMARY ACTION IS NOW PillButton, the home-page two-segment pill, so this page no
             longer carries a .si-cta rule: the component owns the pill's shape, colours, focus ring
             and reduced-motion handling. The lime single-surface treatment that used to live here
             was replaced on owner instruction to make the login CTA the dark-green + mint pill. */

          /* NO RED, ON OWNER INSTRUCTION. This was #fbe9e9 on #f0c0c0 with #8a1f1f text - three
             colours the home design does not contain, on a site whose only red is the full stop in
             the wordmark. It is now the lime state tint behind a 4px #d1f470 inline-start edge with
             #1a3a2a type at weight 700, which is .shop-asof's treatment for "read this first".
             Colour is not carrying the meaning: role=alert announces it, and the sentence states
             the problem. The 4px edge and the weight are a luminance and weight step rather than a
             hue change, so they survive forced-colors and reduced colour discrimination.
             Logical inline-start, so the edge follows the reading direction. */
          .si-error{
            margin:20px 0 0;padding:14px 16px;border-radius:10px;
            background:rgba(209,244,112,.22);border-inline-start:4px solid #d1f470;
            font-size:16px;font-weight:700;line-height:1.5;color:#1a3a2a;
          }
          /* The resend sits under the confirm button with one gap between them, not beside it:
             at 280px two 52px pills on one row cannot both fit without wrapping mid-label, and
             a wrapped button row reads as a layout fault. Stacked is the same at every width. */
          .si-resend{margin-top:12px}
          /* 44px, so the way back off this page is a real target. */
          .si-back{margin:28px 0 0;font-size:16px;line-height:1.55}
          .si-back :global(a){
            display:inline-flex;align-items:center;min-height:44px;
            color:#1a3a2a;font-weight:700;text-underline-offset:3px;
          }
          .si-back :global(a:focus-visible){outline:3px solid #1a3a2a;outline-offset:3px;border-radius:2px}
          @media(max-width:767px){
            .si-body{font-size:18px}
            /* The header is 96px below this breakpoint, so the clearance steps with it. */
            .si-input{scroll-margin-top:112px}
          }
        `}</style>
      </PageTopBand>
    </>
  );
}
