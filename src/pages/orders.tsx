import React, { useEffect, useRef, useState } from 'react';

import PageMeta from '../components/PageMeta';
import PageTopBand from '../components/PageTopBand';
import PillButton from '../components/PillButton';
import CheckoutIdentityCard from '../components/CheckoutIdentityCard';
import CheckoutProfile, {
  type CheckoutProfileMode,
  type CheckoutProfileValue,
} from '../components/CheckoutProfile';
import { type StoredAddress } from '../components/AddressFields';
// The MODULE is the mockable seam, and the boolean is read as a property access INSIDE the
// render body - never captured in a module-scope const. An ESM const cannot be spied and
// vi.stubEnv runs strictly after module evaluation, which is exactly why API_BASE below is not
// overridable today. There is deliberately no local alias either: two names for one fact.
import { featureFlags } from '../config/featureFlags';
import { clearSession, getSession, restoreSession } from '../lib/customerAuth';
import { formatPaiseINR } from '../lib/money';

/**
 * /orders — what a customer has bought from us, and what each payment is doing.
 *
 * RENAMED FROM [retired public path] ON OWNER INSTRUCTION, label and URL together. UNVERIFIED IN
 * THIS PASS, and carried forward as a claim rather than restated as fact: the old path is
 * believed to 301 here from Amplify customRules written by a now-retired provisioning script,
 * and the same change repointed a FROZEN_EXTERNAL entry printed inside a DLT-approved SMS
 * template that cannot be edited. The route this page serves is unchanged by this rebuild, so
 * nothing here can break that redirect - but nobody re-measured it against the live Amplify app
 * while writing this, so do not treat the 301 as measured.
 *
 * FOUR REGISTRY LISTS HAVE TO AGREE OR THE SUITE FAILS. '/orders' must be in the EXACT-MATCH
 * allowlist in _app.tsx (:523) or this renders an empty body with HTTP 200 - a 404 that does not
 * look like one; in PUBLIC_EXACT in scripts/generate-sitemap.js (:44); and as both path and name
 * in config/public-pages.json (:107), whose description must stay BYTE-IDENTICAL to the one in
 * _app.tsx. trailingSlash means the URL is /orders/. All four are already in step and this
 * rebuild changes none of them.
 *
 * THE PAGE IS PUBLIC AND INDEXED, WHICH IS A CONSTRAINT ON THE FIRST RENDER. /orders is in
 * PUBLIC_PAGE_META, the sitemap allowlist and public-pages.json, and generate-sitemap.js refuses
 * a URL that is both allowlisted and blocked - so there is no noindex here, and the static export
 * is a real public page. The SERVER-RENDERED state is therefore `signedOut`: a useful page saying
 * what this is for plus the sign-in control, with no personal data. `loading` must never be the
 * first render, or the indexed headline would be "Loading…". The order list is client-only, which
 * is correct: it is per-person and must never sit in a static artifact.
 *
 * NO CODE IS SENT FROM THIS PAGE. The sign-in control is a LINK into the existing flow at
 * /account/sign-in/ (which owns all four of its phases, the two-codes-not-one registration path
 * and the owner's approved failure strings). Reimplementing any of that here is the one kind of
 * near-miss that is a sign-in outage. See the note on the gate below for why the label reads
 * "Sign in on WhatsApp".
 *
 * WHAT THIS PAGE DOES NOT CLAIM. It lists paid website orders, read from one bounded query over
 * the caller's own partition. It is not a tracker for a request or a booking, and the empty state
 * says so rather than asserting that nothing was bought - a captured payment can leave no order
 * row at all (finalization stages PURCHASED_SNAPSHOT_MISSING and returns before the order write),
 * and no later writer creates one. Phase 3 cannot repair that; the repair is on the money path.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const MY_ORDERS_URL = `${ API_BASE }/ecommerce/my-orders`;

/**
 * How long after an empty FIRST page we ask once more. The arrival path that needs it is real:
 * cart.tsx's terminal rail links straight here after a payment, and the index is eventually
 * consistent, so a just-created order can be briefly absent. One extra read per visit, no poll.
 */
const RECHECK_DELAY_MS = 4000;

/** One page is 20 server-side; the request sends no `limit` and takes that default. */
interface OrderRow {
  orderNumber: string;
  referenceId: string;
  /** INT epoch SECONDS, UTC. Formatted in the browser so an IST reader sees their own day. */
  createdAt: number | null;
  amountPaise: number | null;
  currency: string;
  currencyUnexpected: boolean;
  /** payment_status canonical. '' when unmappable. Never a raw provider spelling. */
  status: string;
  /** On the wire for a future filter. Deliberately not read here. */
  statusRank: number;
}

interface ProfilePayload {
  name: string;
  firstName: string;
  lastName: string;
  email: string;
  emailVerified: boolean;
  phone: string;
  addressComplete: boolean;
  address: StoredAddress | null;
}

/**
 * `profile` is OPTIONAL on purpose, and the difference matters. It is PRESENT ONLY on a
 * first-page request: a response that carried a cursor OMITS the key entirely. So `undefined`
 * means "not answered on this request" and `null` means "no contact row, or a degraded read".
 * Treating `undefined` as `null` would blank the card the customer is looking at on page two.
 */
interface OrdersResponse {
  orders?: OrderRow[];
  cursor?: string;
  profile?: ProfilePayload | null;
}

type View = 'signedOut' | 'loading' | 'ready' | 'empty' | 'error';
type Failure = 'rate' | 'unavailable';

type Outcome =
  | { kind: 'ok'; data: OrdersResponse }
  | { kind: 'expired' }
  | { kind: 'rate' }
  | { kind: 'unavailable' };

/**
 * The §3.6 map, keyed on the CANONICAL word and nothing else. A lookup rather than a chain of
 * comparisons, which is the shape that cannot drift: the mapping from 'PAYMENT_PAID', 'paid' and
 * 'completed' happened once, on the server, in payment_status. Re-introducing any of those
 * spellings here would be the frontend starting a sixth vocabulary.
 */
const STATUS_LABEL: Record<string, string> = {
  captured: 'Paid',
  authorized: 'Payment held',
  pending: 'Payment confirming',
  created: 'Started',
  failed: 'Not paid',
  refunded: 'Refunded',
  disputed: 'Under review',
};

const STATUS_NOTE: Record<string, string> = {
  authorized: 'We are confirming this with the bank.',
  pending: 'This usually settles within a few minutes.',
  created: 'This order was started but not paid.',
  failed: 'No money was taken.',
  refunded: 'The amount has been returned.',
  disputed: 'We are looking into this payment with the bank.',
};

/** The two states that read as firm rather than advisory. A weight step, never a hue. */
const STATUS_FIRM = new Set( [ 'captured', 'refunded' ] );

function dateLabel ( createdAt: number | null ): string {
  if ( createdAt === null || !Number.isFinite( createdAt ) ) return '';
  return new Date( createdAt * 1000 )
    .toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: 'numeric' } );
}

async function fetchOrders ( token: string, cursor: string ): Promise<Outcome> {
  try
  {
    const response = await fetch( MY_ORDERS_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        Authorization: `Bearer ${ token }`,
      },
      // The body allowlist is {limit, cursor} and nothing else - any other key is a 400.
      body: JSON.stringify( cursor ? { cursor } : {} ),
    } );
    // A 401 is the normal end of an hour-long token, not a fault. It is handled as a return to
    // the signed-out state with the expiry line, never as the error state.
    if ( response.status === 401 ) return { kind: 'expired' };
    if ( response.status === 429 ) return { kind: 'rate' };
    if ( !response.ok ) return { kind: 'unavailable' };
    const data = ( await response.json() ) as OrdersResponse;
    return { kind: 'ok', data };
  }
  catch
  {
    return { kind: 'unavailable' };
  }
}

export default function OrdersPage (): React.ReactElement {
  const [ view, setView ] = useState<View>( 'signedOut' );
  const [ failure, setFailure ] = useState<Failure>( 'unavailable' );
  const [ expired, setExpired ] = useState( false );
  const [ token, setToken ] = useState( '' );
  const [ orders, setOrders ] = useState<OrderRow[]>( [] );
  const [ cursor, setCursor ] = useState( '' );
  const [ profile, setProfile ] = useState<ProfilePayload | null>( null );
  const [ rechecked, setRechecked ] = useState( false );
  const [ loadingMore, setLoadingMore ] = useState( false );
  const [ moreFailed, setMoreFailed ] = useState( false );
  const [ showProfile, setShowProfile ] = useState( false );
  const [ profileMode, setProfileMode ] = useState<CheckoutProfileMode>( 'name' );

  const liveRef = useRef( true );
  useEffect( () => () => { liveRef.current = false; }, [] );

  /**
   * The 4-second window is DERIVED, not stored. A boolean set from inside an effect is the
   * react-hooks/set-state-in-effect shape PageTopBand works around with a timeout; there is
   * nothing to store here, because "we are between an empty first page and its one re-ask" is
   * exactly `view === 'empty' && !rechecked`.
   */
  const checking = view === 'empty' && !rechecked && !!token;

  const expire = () => {
    clearSession();
    setToken( '' );
    setOrders( [] );
    setCursor( '' );
    setProfile( null );
    setExpired( true );
    setView( 'signedOut' );
  };

  const applyFirstPage = ( data: OrdersResponse ) => {
    const rows = data.orders || [];
    setOrders( rows );
    setCursor( String( data.cursor || '' ) );
    // A first page always answers `profile`, so reading it unconditionally here is correct.
    // `?? null` and not `|| null`: the key is present, and `null` is a meaningful value.
    if ( 'profile' in data ) setProfile( data.profile ?? null );
    setView( rows.length === 0 ? 'empty' : 'ready' );
  };

  const applyFailure = ( kind: Failure ) => {
    setFailure( kind );
    setView( 'error' );
  };

  // The mount effect. `signedOut` is already rendered, so the only job is to find a session and
  // move off it. restoreSession's rejection is swallowed into `signedOut` rather than into the
  // error state: a failed silent refresh is not something the customer did.
  useEffect( () => {
    let live = true;
    ( async () => {
      let session = getSession();
      if ( !session )
      {
        try { session = await restoreSession(); }
        catch { /* stay signedOut */ }
      }
      if ( !live ) return;
      if ( !session ) return;
      setToken( session.accessToken );
      setView( 'loading' );
      const outcome = await fetchOrders( session.accessToken, '' );
      if ( !live ) return;
      if ( outcome.kind === 'ok' ) applyFirstPage( outcome.data );
      else if ( outcome.kind === 'expired' ) expire();
      else applyFailure( outcome.kind );
    } )();
    return () => { live = false; };
  }, [] );

  /**
   * The one-shot re-ask, in its own effect WITH a clearTimeout cleanup. Without the cleanup,
   * leaving the page inside the window still fires a request against a token the page no longer
   * holds and then sets state on an unmounted tree. Keyed on `view === 'empty'`, which is a
   * FIRST-PAGE condition: an empty page returned from a cursor leaves `view` at 'ready' and so
   * cannot enter this branch, which is exactly the distinction between "I have nothing" and "I
   * reached the end of a page".
   */
  useEffect( () => {
    if ( view !== 'empty' || rechecked || !token ) return undefined;
    let live = true;
    const timer = window.setTimeout( () => {
      ( async () => {
        const outcome = await fetchOrders( token, '' );
        if ( !live ) return;
        setRechecked( true );
        if ( outcome.kind === 'ok' ) applyFirstPage( outcome.data );
        else if ( outcome.kind === 'expired' ) expire();
        else applyFailure( outcome.kind );
      } )();
    }, RECHECK_DELAY_MS );
    return () => { live = false; window.clearTimeout( timer ); };
  }, [ view, rechecked, token ] );

  const loadMore = async () => {
    if ( !token || !cursor || loadingMore ) return;
    setLoadingMore( true );
    setMoreFailed( false );
    const outcome = await fetchOrders( token, cursor );
    if ( !liveRef.current ) return;
    setLoadingMore( false );
    if ( outcome.kind === 'expired' ) { expire(); return; }
    if ( outcome.kind !== 'ok' )
    {
      // The rows already on screen stay, and so does the button, so a second tap retries. An
      // error view here would throw away a list the customer is reading over a pagination hiccup.
      setMoreFailed( true );
      return;
    }
    const rows = outcome.data.orders || [];
    setOrders( prev => [ ...prev, ...rows ] );
    // An empty cursored page appends nothing and drops the button, silently: DynamoDB hands out
    // a cursor whenever a query stops at Limit, so a customer with exactly 20 orders gets one.
    // There is no "no more orders" message, because there is nothing to tell them.
    setCursor( String( outcome.data.cursor || '' ) );
    // A cursored response OMITS `profile`. Touching the card on a key that is not there would
    // blank an identity the customer is looking at.
    if ( 'profile' in outcome.data ) setProfile( outcome.data.profile ?? null );
  };

  /**
   * THE FLAG COMES FROM THE MODE THAT COMPLETED, NEVER FROM `saved`.
   *
   * CheckoutProfileValue has NO `emailVerified` member (CheckoutProfile.tsx:39-48). Spreading
   * `saved` into the card's `identity` therefore leaves it `undefined`, `undefined !== false` is
   * true, and the "✓ verified" badge returns over an email nothing verified - on a page whose
   * server-side predicate deliberately does not prove the email at all.
   *
   * The asymmetry is load-bearing rather than tidy: mode 'email' completes only after a fresh
   * code bound to the NEW address, so it should flip the flag true; 'name' and 'address' post
   * with no code at all and must leave it exactly as it was. The mode is read from page state,
   * which is where the affordance put it, rather than inferred from the saved value.
   */
  const applyProfile = ( saved: CheckoutProfileValue, mode: CheckoutProfileMode ) => {
    setProfile( prev => ( prev && {
      ...prev,
      name: saved.name,
      firstName: saved.firstName,
      lastName: saved.lastName,
      email: saved.email,
      address: saved.address,
      addressComplete: saved.addressComplete,
      emailVerified: mode === 'email' ? true : ( prev?.emailVerified ?? false ),
    } ) );
  };

  const openEditor = ( mode: CheckoutProfileMode ) => {
    setProfileMode( mode );
    setShowProfile( true );
  };

  const signedIn = view === 'ready' || view === 'empty';

  return (
    <>
      <PageMeta
        title="Your orders — WECARE.DIGITAL"
        description="Sign in on WhatsApp to see what you have bought from WECARE.DIGITAL, each order's payment status, and the details we have on file."
        path="/orders/"
      />
      <PageTopBand
        heading="Your orders"
        sub="What you have bought from us, and what each payment is doing."
        ariaLabel="Your orders"
      >
        { /* The band owns the h1, the <main>, both header clearances, the measure, the gutters
             and the 'Inter' stack. Nothing below re-declares any of them, and nothing
             conversion-shaped - no button, link or price - goes inside the band itself. */ }
        <div className="ord-page">
          { view === 'signedOut' && (
            <div className="ord-gate">
              { expired && (
                <p className="ord-notice" role="status">
                  Your sign-in has expired. Sign in again to see your orders.
                </p>
              ) }
              <p className="ord-p">Sign in on your WhatsApp number to see your orders.</p>
              { /* A LINK, and the label says so. "Send OTP on WhatsApp" belongs on a control
                   that sends a code; this one navigates, and a customer tapping it would
                   otherwise be told a code was sent, receive none, and then be asked for their
                   number on the next screen. /orders/ is in safeReturnPath's ALLOWED set, so the
                   return survives rather than falling back to /cart/. PillButton renders ONLY
                   `action`, so this string is both the visible text and the accessible name. */ }
              <PillButton
                as="a"
                href="/account/sign-in/?return=/orders/"
                action="Sign in on WhatsApp"
              />
            </div>
          ) }

          { view === 'loading' && (
            <p className="ord-p" role="status">Loading your orders…</p>
          ) }

          { view === 'error' && (
            <div className="ord-gate">
              <p className="ord-notice" role="status">
                { failure === 'rate'
                  ? 'Too many requests. Wait a moment and try again.'
                  : 'We could not load your orders just now. Try again shortly.' }
              </p>
              <button
                type="button"
                className="ord-quiet"
                onClick={ () => {
                  if ( !token ) return;
                  setView( 'loading' );
                  ( async () => {
                    const outcome = await fetchOrders( token, '' );
                    if ( !liveRef.current ) return;
                    if ( outcome.kind === 'ok' ) applyFirstPage( outcome.data );
                    else if ( outcome.kind === 'expired' ) expire();
                    else applyFailure( outcome.kind );
                  } )();
                } }
              >
                Try again
              </button>
            </div>
          ) }

          { signedIn && ( profile
            ? (
              <>
                <CheckoutIdentityCard
                  identity={ {
                    name: profile.name,
                    email: profile.email,
                    phone: profile.phone,
                    // An incomplete address is not an address on file, so the row says so rather
                    // than showing a partial line as if it were the delivery address.
                    address: profile.addressComplete ? profile.address : null,
                    emailVerified: profile.emailVerified,
                  } }
                  eyebrow="Your details"
                  title="What we have on file"
                  emptyAddressLabel="No address on file"
                  editorOpen={ showProfile }
                  onEditName={ () => openEditor( 'name' ) }
                  onChangeEmail={ () => openEditor( 'email' ) }
                  onEditAddress={ () => openEditor( 'address' ) }
                />
                { showProfile && (
                  <CheckoutProfile
                    accessToken={ token }
                    mode={ profileMode }
                    initial={ {
                      firstName: profile.firstName,
                      lastName: profile.lastName,
                      email: profile.email,
                      address: profile.address,
                    } }
                    onReady={ saved => {
                      applyProfile( saved, profileMode );
                      setShowProfile( false );
                    } }
                  />
                ) }
              </>
            )
            : (
              // Four empty rows would assert we know nothing while looking like we know
              // something. One line and a route to where the create-mode form actually lives.
              <p className="ord-p ord-nodetails">
                We do not have your details yet. You can add them in your{ ' ' }
                { /* A plain anchor, not next/link, for the reason Footer.tsx documents:
                     styled-jsx does not scope composite components, so a Link carrying
                     ord-link would arrive with no styling at all. */ }
                { /* eslint-disable-next-line @next/next/no-html-link-for-pages */ }
                <a className="ord-link" href="/cart/">cart</a>.
              </p>
            )
          ) }

          { orders.length > 0 && (
            <section className="ord-list" aria-labelledby="ord-history">
              <h2 className="ord-h2" id="ord-history">Order history</h2>
              <ul className="ord-items">
                { orders.map( ( order, index ) => {
                  const date = dateLabel( order.createdAt );
                  const amount = order.currencyUnexpected
                    ? ''
                    : formatPaiseINR( order.amountPaise, order.currency );
                  const label = STATUS_LABEL[ order.status ] || 'Status unavailable';
                  const note = order.status
                    ? ( STATUS_NOTE[ order.status ] || '' )
                    : 'Contact us and we will check.';
                  return (
                    <li className="ord-item" key={ order.referenceId || order.orderNumber || index }>
                      { /* An h3: the band owns the only h1 and the identity card owns an h2. A
                           heading rather than a styled <p> so a screen reader can move order to
                           order. data-wc-no-translate because it is an identifier. */ }
                      <h3 className="ord-itemh" data-wc-no-translate>
                        { order.orderNumber || order.referenceId || date }
                      </h3>
                      <dl className="ord-facts">
                        { date && (
                          <>
                            <dt>Date</dt>
                            { /* Deliberately TRANSLATABLE: a localised month name is an
                                 improvement and no decision depends on its spelling. */ }
                            <dd className="ord-date">{ date }</dd>
                          </>
                        ) }
                        <dt>Amount</dt>
                        <dd>
                          { amount
                            // Flagged because SupportWidget rewrites text-node values, and a
                            // regrouped or renumbered amount would make this page lie about
                            // money. "Amount unavailable" stays unflagged prose, so it translates.
                            ? <span className="ord-amount" data-wc-no-translate>{ amount }</span>
                            : 'Amount unavailable' }
                        </dd>
                        <dt>Payment</dt>
                        <dd>
                          <span
                            className={ STATUS_FIRM.has( order.status )
                              ? 'ord-status ord-status-firm'
                              : 'ord-status' }
                          >
                            <span className="ord-status-label">{ label }</span>
                            { note && <span className="ord-status-note">{ note }</span> }
                          </span>
                        </dd>
                      </dl>
                    </li>
                  );
                } ) }
              </ul>

              { moreFailed && (
                <p className="ord-notice" role="status">
                  We could not load your orders just now. Try again shortly.
                </p>
              ) }

              { !!cursor && (
                <button
                  type="button"
                  className="ord-quiet"
                  onClick={ loadMore }
                  disabled={ loadingMore }
                >
                  { loadingMore ? 'Loading…' : 'Show more orders' }
                </button>
              ) }
            </section>
          ) }

          { view === 'empty' && (
            <section className="ord-empty" aria-labelledby="ord-empty-title">
              <h2 className="ord-h2" id="ord-empty-title">No orders yet</h2>
              { checking
                ? (
                  // A SUB-STATE, not a sixth state: only the body is replaced, and it resolves
                  // on its own. The line is neutral because this endpoint cannot know whether a
                  // payment exists - it only knows the first page was empty, and the common
                  // visitor on that branch has never bought anything. "Your order is being
                  // confirmed" would be a confident wrong statement to most of them.
                  <p className="ord-p" role="status">Checking for recent orders…</p>
                )
                : (
                  <>
                    <p className="ord-p">
                      Anything you buy from us will show up here with its payment status.
                    </p>
                    <PillButton as="a" href="/shop/" action="Shop" />
                    { /* WIDENED on purpose, and the second clause is the load-bearing half:
                         finalization can stage PURCHASED_SNAPSHOT_MISSING and return BEFORE the
                         order write, so a captured payment can leave no order row at all,
                         permanently, with no later writer able to create one. This page must
                         therefore not assert that nothing was bought. */ }
                    <p className="ord-aside">
                      Ordered over WhatsApp, or paid in the last few minutes and don&apos;t see
                      it here? Contact us and we will check.
                    </p>
                  </>
                ) }
            </section>
          ) }
        </div>

        <style jsx>{`
          /* ord- prefixed throughout: the globally imported src/styles/*.css declares unscoped
             rules for generic names and styled-jsx does not shield a page from them. Every rule
             lives in THIS return tree - no row helper and no hoisted <style jsx> variable,
             because styled-jsx stamps its scoping class only onto JSX it compiles alongside, and
             the run-together "Sign inSend code" the owner reported was that exact bug.

             No top padding, no measure, no gutters, no font-family on a container and no
             viewport height at all: PageTopBand owns every one of those, and a second copy is a
             second thing to get wrong at one of the two header heights. */

          /* Declared rather than inferred. prefers-color-scheme appears zero times under src/,
             so the site is light-only; stating it stops a browser inferring a scheme and
             recolouring form controls against a hardcoded light palette. */
          .ord-page{color-scheme:light;display:flex;flex-direction:column;gap:32px;max-width:700px}

          /* The section rung: 700 against the band's 600 h1. That inversion is the site's and is
             deliberate - PageTopBand says not to "correct" it. Font stack DECLARED, not
             inherited: with the global body rule absent an inheriting lockup falls to a serif
             while a declaring headline stays on Inter. */
          .ord-h2{
            font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
            font-size:clamp(28px,3.2vw,40px);font-weight:700;line-height:1.08;
            letter-spacing:-1.2px;color:rgba(0,0,0,.95);margin:0 0 14px;
          }
          /* The one body rung: 20px/400/1.4/-.125px at rgba(0,0,0,.898), 18px under 767px. */
          .ord-p,.ord-aside{
            font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
            font-size:20px;font-weight:400;line-height:1.4;letter-spacing:-.125px;
            color:rgba(0,0,0,.898);margin:0;
          }
          .ord-gate{display:flex;flex-direction:column;align-items:flex-start;gap:20px}
          .ord-nodetails{padding:18px;border:1px solid #e5e7eb;border-radius:14px;background:#fff}
          .ord-link{color:#1a3a2a;font-weight:600;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}

          /* The state treatment, lifted from .cart-status: a lime tint behind a solid lime
             inline-start edge with #1a3a2a type. A luminance and weight step rather than a hue,
             which is what survives forced-colors and reduced colour discrimination - and colour
             is never the only cue, because every one of these states is also stated in words. */
          .ord-notice{
            font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
            margin:0;padding:14px 16px;border-inline-start:4px solid #d1f470;border-radius:10px;
            background:rgba(209,244,112,.22);color:#1a3a2a;
            font-size:16px;font-weight:700;line-height:1.5;
          }

          .ord-items{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:14px}
          .ord-item{padding:18px;border:1px solid #e5e7eb;border-radius:14px;background:#fff}
          .ord-itemh{
            font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
            margin:0 0 12px;font-size:18px;font-weight:700;line-height:1.3;
            letter-spacing:-.25px;color:#1a1a1a;overflow-wrap:anywhere;
          }
          /* Not a table: devicecheck.js measures 280px, where four columns are a horizontal
             scroll. A definition list collapses to one column for free. */
          .ord-facts{margin:0;display:grid;grid-template-columns:96px 1fr;gap:8px 12px;align-items:baseline}
          .ord-facts dt{font-size:12px;font-weight:700;color:#1a3a2a}
          .ord-facts dd{margin:0;font-size:16px;line-height:1.5;color:#1a1a1a}
          .ord-amount{font-weight:700}
          .ord-status{
            display:inline-flex;flex-direction:column;gap:2px;
            padding:14px 16px;border-inline-start:3px solid #d1f470;border-radius:10px;
            background:rgba(209,244,112,.22);color:#1a3a2a;line-height:1.5;
          }
          .ord-status-firm{border-inline-start-width:4px}
          .ord-status-label{font-size:16px;font-weight:600}
          .ord-status-firm .ord-status-label{font-weight:700}
          .ord-status-note{font-size:14px;font-weight:400}

          /* The quiet secondary, reused from /checkout/status/'s co-btn-quiet so the page keeps
             exactly one lime SURFACE (the pill) and this one carries a lime EDGE instead. The
             control is identified by its <button> semantics and its #1a3a2a-on-white label, not
             by the edge - #d1f470 on white is 1.24:1 and does not clear 1.4.11 on its own - and
             the focus indicator is the dark outline. */
          .ord-quiet{
            align-self:flex-start;display:inline-flex;align-items:center;justify-content:center;
            min-height:44px;padding:0 24px;border:2px solid #d1f470;border-radius:50px;
            background:#fff;color:#1a3a2a;font:inherit;font-size:17px;font-weight:600;cursor:pointer;
          }
          .ord-quiet:hover:not(:disabled){background:rgba(209,244,112,.22)}
          .ord-quiet:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
          .ord-quiet:disabled{opacity:.55;cursor:default}

          .ord-list,.ord-empty{display:flex;flex-direction:column;align-items:flex-start;gap:18px}
          .ord-list .ord-h2,.ord-empty .ord-h2{margin:0}

          @media(max-width:767px){
            .ord-p,.ord-aside{font-size:18px}
            .ord-facts{grid-template-columns:1fr;gap:4px}
          }

          /* NO ENTRANCE ANIMATION OF ITS OWN, and the absence is the point: opacity:0 does not
             remove an element from the tab order, and this page's children contain buttons, a
             link and a form. PageTopBand arms only its heading and sub-line, never children. */
        `}</style>
      </PageTopBand>
    </>
  );
}
