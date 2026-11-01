/**
 * Customer file collection: verify over WhatsApp, pay, download.
 *
 * Design
 * ------
 * Home is the typography source of truth. Exact-file Vault uses a compact, static
 * RotatingHero, an accessible ownership/status summary, and one clear primary action.
 * The file stays on the canonical 560px public-copy measure. Only presentation changes
 * here; all checkout, entitlement and download decisions remain server-owned.
 *
 * Route ownership
 * ---------------
 * /vault/?file=<id> is the one customer download route. This component is mounted only by that
 * exact-file Vault surface and always scopes the authenticated view to the named file.
 * /get/ is not a second file-collection page; the /get/<*> namespace remains reserved for
 * media delivery through CloudFront.
 *
 * It also has to be in the public allowlist in `_app.tsx`. Without that entry it
 * renders the staff Authenticator at HTTP 200 - which is how it shipped the first
 * time.
 *
 * The trust model, which is the whole point
 * -----------------------------------------
 * Nothing on this page can grant access. For UNPAID, the browser names only this
 * exact fileId to secure-files under the customer session. The backend re-proves
 * ownership and entitlement state before handing off to verified payment rails.
 * ProductsTable pricing, GST/fees, PaymentAttempt/PAYREF and Meta ORDER_DETAILS stay server-owned.
 * An OPEN/READY entitlement enables the Download action.
 *
 * Customer-facing states
 * ----------------------
 * UNPAID can choose website or WhatsApp checkout. OPEN/READY show Download;
 * PAID_UNVERIFIED awaits verification. Missing, revoked or EXPIRED links
 * navigate Home after owner-scoped verification, never displaying a temporary
 * status or payment action. The backend remains authoritative.
 */

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import SEO from '../SEO';
import RotatingHero from '../RotatingHero';
import PublicNotice from '../public/PublicNotice';
import { publicActionText, publicApiFailureText } from '../../lib/publicActionNotices';
import type { CycleWord } from '../RotatingHero';
import * as api from '../../api/client';
import type { SecureFile, SecureFileAccessState } from '../../api/client';
import { fetchServicePrices, rupeesFromPaise } from '../../lib/servicePricing';
import { restoreSession, clearSession, getSession } from '../../lib/customerAuth';
import { serviceByKind } from '../../config/services';
import { postRequestIntent } from '../../lib/serviceRequests';
import { setServiceLine, serviceIntentFor, toLineItems, readCart, isServiceItem } from '../../lib/cart';

function formatBytes ( bytes: number ): string {
    if ( !bytes ) return '0 B';
    const units = [ 'B', 'KB', 'MB', 'GB' ];
    const i = Math.min( Math.floor( Math.log( bytes ) / Math.log( 1024 ) ), units.length - 1 );
    return `${( bytes / Math.pow( 1024, i ) ).toFixed( i === 0 ? 0 : 1 )} ${units[ i ]}`;
}

/** The server's access state, or what an older backend's fields imply. */
function accessStateOf ( file: SecureFile ): SecureFileAccessState {
    if ( file.accessState ) return file.accessState;
    // No server state: a paid id alone does not prove the file is ready to open, so say the
    // payment is confirming (never offered checkout again) rather than READY.
    return file.paidEntitlementId || file.paidGrantId ? 'PAID_UNVERIFIED' : 'UNPAID';
}

/** An owner-verified expired Vault file returns Home, never Contact or Orders. */
function expiredVaultFile ( file: SecureFile ): boolean {
    const state = accessStateOf( file );
    if ( state === 'EXPIRED' ) return true;
    const endsAt = Number( file.accessWindowEndsAt || 0 );
    return ( state === 'OPEN' || state === 'READY' )
        && Number.isFinite( endsAt ) && endsAt > 0 && endsAt * 1000 <= Date.now();
}

/** "26 Oct 2026, 4:30 pm" in the reader's locale, or '' when there is no window end. */
function windowEndLabel ( epochSeconds?: number ): string {
    if ( !epochSeconds ) return '';
    try
    {
        return new Date( epochSeconds * 1000 ).toLocaleString( undefined, { dateStyle: 'medium', timeStyle: 'short' } );
    } catch
    {
        return '';
    }
}

/** One calm, stationary hero word for a private, single-file download task. */
const GET_WORDS: CycleWord[] = [
    { word: 'document', tint: '#e0f7c8', dot: '#3da35a' },
];

function fileStatusLabel ( state: SecureFileAccessState ): string {
    switch ( state ) {
        case 'OPEN': return '';
        case 'READY': return 'Payment verified';
        case 'PAID_UNVERIFIED': return 'Verifying payment';
        case 'EXPIRED': return 'Access expired';
        default: return 'Access locked';
    }
}

const VAULT_AUTH_RETURN_FILE_KEY = 'wecare.vault.authReturnFile';
export const VAULT_WEBSITE_RETURN_FILE_KEY = 'wecare.vault.websiteCheckoutReturnFile';
const VAULT_FILE_ID_PATTERN = /^[A-Za-z0-9_-]{1,120}$/;

type Stage = 'loading' | 'files';

interface FilesPageProps {
    /** Canonical Vault deep-link target. Ownership is still proven server-side. */
    targetFileId: string;
}

type FileFeedback = { kind: 'status' | 'error'; message: string };

export default function FilesPage ( { targetFileId }: FilesPageProps ) {
    const [ stage, setStage ] = useState<Stage>( 'loading' );
    const [ error, setError ] = useState( '' );

    const [ files, setFiles ] = useState<SecureFile[]>( [] );
    // Display-only preview from the ProductsTable-backed pricing endpoint. The native payment
    // backend re-prices independently before it creates any payment attempt.
    const [ payablePrice, setPayablePrice ] = useState<number | null>( null );
    const [ vaultLinePrice, setVaultLinePrice ] = useState<number | null>( null );
    const [ working, setWorking ] = useState<string>( '' );
    const [ paymentWaiting, setPaymentWaiting ] = useState<Record<string, boolean>>( {} );
    const [ fileFeedback, setFileFeedback ] = useState<Record<string, FileFeedback>>( {} );
    // Used only to hide the Download action exactly when the local window reaches its cutoff.
    // Server-side access checks remain authoritative.
    const [ nowSeconds, setNowSeconds ] = useState( () => Math.floor( Date.now() / 1000 ) );

    const redirectToAuth = useCallback( (): void => {
        if ( targetFileId && VAULT_FILE_ID_PATTERN.test( targetFileId ) )
        {
            try
            {
                window.sessionStorage.setItem( VAULT_AUTH_RETURN_FILE_KEY, targetFileId );
            } catch
            {
                // Same-tab storage is best-effort. Ownership still has to pass on the server.
            }
        }
        window.location.replace( `/auth?return=${ encodeURIComponent( '/vault/' ) }` );
    }, [ targetFileId ] );

    const loadFiles = useCallback( async () => {
        const result = await api.listMySecureFiles();
        if ( result.ok )
        {
            const ownedFiles = result.data.files || [];
            const visibleFiles = targetFileId
                ? ownedFiles.filter( file => file.fileId === targetFileId && file.status === 'active' )
                : ownedFiles;
            if ( targetFileId && ( visibleFiles.length === 0 || visibleFiles.some( expiredVaultFile ) ) ) {
                // Check only after an authenticated owner-scoped read. Missing,
                // revoked and expired file links all return directly to Home.
                window.location.replace( '/' );
                return;
            }
            setFiles( visibleFiles );
            setStage( 'files' );
            setError( '' );
        } else if ( result.failure.status === 401 )
        {
            clearSession();
            redirectToAuth();
            return;
        } else
        {
            setError( publicApiFailureText( result.failure.status ) );
        }
    }, [ targetFileId, redirectToAuth ] );

    // Fetch prices only after the owned file is verified; invalid and expired links
    // must not start a second background API request while navigating Home.
    useEffect( () => {
        if ( stage !== 'files' ) return;
        let active = true;
        void fetchServicePrices().then( prices => {
            if ( !active ) return;
            const vault = prices.vault;
            setPayablePrice(
                vault?.available && vault.breakdown
                    ? vault.breakdown.totalPayablePaise
                    : null
            );
            setVaultLinePrice( vault?.available && vault.breakdown ? vault.paise : null );
        } );
        return () => { active = false; };
    }, [ stage ] );

    // /auth is the only customer sign-in surface. Exact-file /vault/?file= links restore a
    // server-owned customer session here; when none exists, the file id is kept in same-tab
    // storage and /auth returns to /vault/, which restores the exact file query.
    useEffect( () => {
        let active = true;
        void restoreSession()
            .then( restored => {
                if ( !active ) return null;
                if ( !restored )
                {
                    redirectToAuth();
                    return null;
                }
                return api.listMySecureFiles();
            } )
            .then( result => {
                if ( !active || !result ) return;
                if ( result.ok )
                {
                    const ownedFiles = result.data.files || [];
                    const visibleFiles = targetFileId
                        ? ownedFiles.filter( file => file.fileId === targetFileId && file.status === 'active' )
                        : ownedFiles;
                    if ( targetFileId && ( visibleFiles.length === 0
                        || visibleFiles.some( expiredVaultFile ) ) )
                    {
                        // Missing, revoked or expired: never prompt for a
                        // fresh payment or disclose a file's existence.
                        window.location.replace( '/' );
                        return;
                    }
                    setFiles( visibleFiles );
                    setStage( 'files' );
                    setError( '' );
                } else if ( result.failure.status === 401 )
                {
                    clearSession();
                    redirectToAuth();
                } else
                {
                    setError( publicApiFailureText( result.failure.status ) );
                }
            } )
            .catch( () => {
                if ( active ) setError( 'Sign-in is temporarily unavailable. Please try again.' );
            } );
        return () => { active = false; };
    }, [ targetFileId, redirectToAuth ] );

    // After native Review and Pay is sent, the website stays on this exact file. Refresh while
    // payment is pending or reconciling, and whenever the customer returns from WhatsApp.
    useEffect( () => {
        const waiting = files.some( file => paymentWaiting[ file.fileId ] );
        const reconciling = files.some( file => accessStateOf( file ) === 'PAID_UNVERIFIED' );
        if ( stage !== 'files' || ( !waiting && !reconciling ) ) return;

        let active = true;
        const refresh = () => {
            if ( active ) void loadFiles();
        };
        const interval = window.setInterval( refresh, 5000 );
        window.addEventListener( 'focus', refresh );

        return () => {
            active = false;
            window.clearInterval( interval );
            window.removeEventListener( 'focus', refresh );
        };
    }, [ stage, files, paymentWaiting, loadFiles ] );

    // Switch an already-open page to Access expired at the paid cutoff, including mobile
    // tabs resumed later. A server refresh confirms the authoritative state.
    useEffect( () => {
        if ( stage !== 'files' ) return;
        const refresh = () => {
            if ( files.some( expiredVaultFile ) ) {
                window.location.replace( '/' );
                return;
            }
            setNowSeconds( Math.floor( Date.now() / 1000 ) );
            void loadFiles();
        };
        const nowMs = Date.now();
        const upcomingEnds = files
            .filter( file => accessStateOf( file ) === 'OPEN'
                && ( file.accessWindowEndsAt || 0 ) * 1000 > nowMs )
            .map( file => Number( file.accessWindowEndsAt ) * 1000 );
        const nextExpiryMs = upcomingEnds.length ? Math.min( ...upcomingEnds ) : null;
        const timer = nextExpiryMs === null
            ? null
            : window.setTimeout( refresh, Math.max( 0, nextExpiryMs - nowMs + 50 ) );
        window.addEventListener( 'focus', refresh );
        return () => {
            if ( timer !== null ) window.clearTimeout( timer );
            window.removeEventListener( 'focus', refresh );
        };
    }, [ stage, files, loadFiles ] );

    // Once the backend moves a file out of its sale state, the temporary "check WhatsApp"
    // message has done its job. The authoritative OPEN/READY/PAID_UNVERIFIED UI takes over.
    useEffect( () => {
        const completed = files
            .filter( file => paymentWaiting[ file.fileId ]
                && accessStateOf( file ) !== 'UNPAID'
                && accessStateOf( file ) !== 'EXPIRED' )
            .map( file => file.fileId );
        if ( completed.length === 0 ) return;
        setPaymentWaiting( current => {
            const next = { ...current };
            completed.forEach( id => { delete next[ id ]; } );
            return next;
        } );
        setFileFeedback( current => {
            const next = { ...current };
            completed.forEach( id => { delete next[ id ]; } );
            return next;
        } );
    }, [ files, paymentWaiting ] );

    const handleDownload = async ( file: SecureFile ) => {
        const accessId = file.paidEntitlementId || file.paidGrantId;
        const feedback = ( kind: FileFeedback['kind'], message: string ) => {
            setFileFeedback( current => ( { ...current, [ file.fileId ]: { kind, message } } ) );
        };
        if ( !accessId )
        {
            feedback( 'error', 'Paid Vault access is not ready for this file yet.' );
            return;
        }
        setWorking( file.fileId );
        setFileFeedback( current => {
            const next = { ...current };
            delete next[ file.fileId ];
            return next;
        } );
        try
        {
            const result = await api.redeemSecureFileDownload( file.fileId, accessId );
            if ( !result.ok )
            {
                const code = result.failure.code;
                if ( result.failure.status === 401 )
                {
                    clearSession();
                    setFiles( [] );
                    redirectToAuth();
                    return;
                }
                if ( code === 'ACCESS_WINDOW_CLOSED' )
                {
                    // The server confirmed the access window is over.
                    // Return to Home; do not show a stale Vault download action.
                    window.location.replace( '/' );
                    return;
                }
                feedback(
                    'error',
                    code === 'NOT_REGISTERED'
                        ? 'This file is not registered to your verified number.'
                        : code === 'ACCESS_NOT_AUTHORIZED'
                            ? 'We could not confirm paid access for this file. If you already paid, do not pay again.'
                            : publicApiFailureText( result.failure.status )
                );
                return;
            }
            if ( !result.data.downloadUrl )
            {
                feedback( 'error', 'The download URL was not returned. Please try again.' );
                return;
            }
            // Only the approved private S3 bucket is a valid transport destination.
            let destination: URL;
            try { destination = new URL( result.data.downloadUrl ); }
            catch {
                feedback( 'error', 'The secure file link is invalid. Please try downloading again.' );
                return;
            }
            // SigV4 in us-east-1 legitimately uses either regional or legacy
            // virtual-hosted S3 endpoint. Allow only these exact bucket hostnames.
            const approvedS3Hosts = new Set( [
                'wecare-digital-get.s3.us-east-1.amazonaws.com',
                'wecare-digital-get.s3.amazonaws.com',
            ] );
            if ( destination.protocol !== 'https:' || destination.port || destination.username
                || destination.password || !approvedS3Hosts.has( destination.hostname ) ) {
                feedback( 'error', 'The file was not hosted at the expected secure location. Please contact support.' );
                return;
            }
            window.location.assign( destination.href );
        } catch ( err: any )
        {
            feedback( 'error', publicActionText( 'failure' ) );
        } finally
        {
            setWorking( '' );
        }
    };

    const handleWebsiteCheckout = async ( file: SecureFile ) => {
        const state = accessStateOf( file );
        if ( state !== 'UNPAID' ) return;
        const service = serviceByKind( 'VAULT' );
        if ( !service || !vaultLinePrice ) {
            setFileFeedback( current => ( { ...current, [ file.fileId ]: {
                kind: 'error', message: 'The current Vault price is unavailable. Nothing has been charged.',
            } } ) );
            return;
        }
        // The Vault/Drop Docs pricing contract is for a single service line.
        // Do not silently replace a customer's shopping basket, and never
        // apply the file-service GST/handling quote to unrelated merchandise.
        if ( readCart().some( item => !isServiceItem( item )
            || item.productId !== service.productId || item.variantId !== service.variantId ) ) {
            setFileFeedback( current => ( { ...current, [ file.fileId ]: {
                kind: 'error',
                message: 'Other items are already in your cart. Complete or remove those items before adding Vault access. Your shopping cart has not been changed.',
            } } ) );
            return;
        }
        setWorking( file.fileId );
        try {
            const session = getSession() || await restoreSession();
            if ( !session ) {
                redirectToAuth();
                return;
            }
            // Bind exactly THIS owner-verified Vault file to a pre-payment service
            // intent. The checkout verifies the same entitlement again before Razorpay.
            const response = await postRequestIntent(
                session.accessToken, 'VAULT', undefined, file.fileId,
            );
            if ( response.kind === 'expired' ) {
                clearSession();
                redirectToAuth();
                return;
            }
            if ( response.kind !== 'ok' || response.intent.variantId !== service.variantId ) {
                const message = response.kind === 'refused'
                    ? response.message
                    : response.kind === 'rate'
                        ? 'Too many attempts. Try again shortly.'
                        : 'We could not verify this file for website payment. Nothing has been charged.';
                setFileFeedback( current => ( { ...current, [ file.fileId ]: { kind: 'error', message } } ) );
                if ( response.kind === 'refused' ) void loadFiles();
                return;
            }
            const cart = setServiceLine( service.variantId, response.intent.intentId, vaultLinePrice );
            const lineItems = toLineItems( cart );
            const bound = serviceIntentFor( lineItems ) === response.intent.intentId
                && cart.some( item => item.productId === service.productId && item.variantId === service.variantId );
            if ( !bound ) {
                setFileFeedback( current => ( { ...current, [ file.fileId ]: {
                    kind: 'error',
                    message: 'Your cart could not preserve the verified Vault file selection. No payment was started.',
                } } ) );
                return;
            }
            // Same-tab, non-authoritative link for the success/status screen to offer.
            // File access still requires authenticated exact-file authorization.
            window.sessionStorage.setItem( VAULT_WEBSITE_RETURN_FILE_KEY, file.fileId );
            window.location.assign( '/checkout/' );
        } catch {
            setFileFeedback( current => ( { ...current, [ file.fileId ]: {
                kind: 'error',
                message: 'Website checkout could not be prepared. Nothing has been charged. Try again.',
            } } ) );
        } finally {
            setWorking( '' );
        }
    };

    const handleVaultPayment = async ( file: SecureFile ) => {
        const state = accessStateOf( file );
        if ( state !== 'UNPAID' ) return;
        // This is only a display price preview. The native WhatsApp payment
        // rail re-prices on the server and shows the approved total before the
        // customer authorises anything. A failed preview must not disable it.
        setWorking( file.fileId );
        setFileFeedback( current => {
            const next = { ...current };
            delete next[ file.fileId ];
            return next;
        } );
        try {
            const identityReady = await api.ensureCustomerPaymentIdentity();
            if ( !identityReady.ok ) {
                if ( identityReady.failure.status === 401 ) {
                    clearSession();
                    setFiles( [] );
                    redirectToAuth();
                    return;
                }
                setFileFeedback( current => ( {
                    ...current,
                    [ file.fileId ]: {
                        kind: 'error',
                        message: identityReady.failure.code === 'CONTACT_IDENTITY_CONFLICT'
                            ? 'Your WhatsApp number is linked to conflicting customer records. Contact support to reconcile your account. Nothing has been charged.'
                            : 'We could not prepare your verified WhatsApp identity. Nothing has been charged. Please try again.',
                    },
                } ) );
                return;
            }

            const result = await api.requestMySecureFilePayment( file.fileId );
            if ( !result.ok ) {
                if ( result.failure.status === 401 ) {
                    clearSession();
                    setFiles( [] );
                    redirectToAuth();
                    return;
                }
                if ( result.failure.code === 'VAULT_ACCESS_ACTIVE'
                    || result.failure.code === 'PAID_UNVERIFIED' ) {
                    await loadFiles();
                    return;
                }
                setFileFeedback( current => ( {
                    ...current,
                    [ file.fileId ]: {
                        kind: 'error',
                        message: publicActionText( 'whatsappFailed' ),
                    },
                } ) );
                return;
            }

            // HTTP 202 is also 'ok' at the fetch layer, but a sender outcome
            // of PAYMENT_REQUEST_UNCONFIRMED (or any non-SENT result) is NOT
            // provider acceptance. Never show "Sent" based on HTTP 2xx alone.
            const accepted = result.data.outcome === 'PAYMENT_REQUEST_SENT';
            setPaymentWaiting( current => ( { ...current, [ file.fileId ]: true } ) );
            setFileFeedback( current => ( {
                ...current,
                [ file.fileId ]: {
                    kind: accepted ? 'status' : 'error',
                    message: publicActionText( accepted ? 'whatsappAccepted' : 'whatsappFailed' ),
                },
            } ) );
            void loadFiles();
        } catch {
            setFileFeedback( current => ( {
                ...current,
                [ file.fileId ]: {
                    kind: 'error',
                    message: publicActionText( 'whatsappFailed' ),
                },
            } ) );
        } finally {
            setWorking( '' );
        }
    };

    // Blank during identity and ownership lookup. Only a verified, active file
    // may render the Vault hero. Failed requests still show a retry/error state.
    if ( stage === 'loading' && !error ) return null;

    return (
        <>
            {/* noindex: a personal collection point, not a marketing page. There is
                nothing here for a crawler, and an indexed URL inviting a phone number
                is a phishing template waiting to be copied. */}
            <SEO
                title="Your files"
                description="Collect files shared with you by WECARE.DIGITAL"
                noindex
            />

            {/* THE HOME PAGE'S TOP SECTION, on owner instruction. This page previously opened
                straight into a bordered panel with no hero, which is why it read as a different
                site from the former customer sign-in page, which already sat on RotatingHero. The hero is
                the shared component rather than a copy of its markup, so the "animate as one
                family" guarantee holds (tools/browser/animcheck.js asserts the family shares one
                computed transition set) and this surface cannot drift from the other fifteen.

                NOT SUBORDINATE: the hero owns the page's single <main> landmark and its single
                <h1>, and the panel below is its child. The former <main className="sf-shell"> and
                <h1 className="sf-title"> are therefore GONE - keeping either would produce two
                mains and two h1s, which fails htmlcheck's MANY-MAIN and H1-MANY at once. The
                document-access heading is an <h2> inside the panel, while the file name
                is its subordinate <h3>. No duplicate page landmark is introduced.

                NO badgeLabel, matching the home page and /blog/: the label here would just be the
                company name again, 109px under the header's own lockup, which is exactly what the
                home page removed. The old <p className="sf-eyebrow">WECARE.DIGITAL</p> is gone for
                the same reason. */}
            <RotatingHero
                frame="Your secure"
                words={ GET_WORDS }
                sub="View your access and download the file shared with you."
                ariaLabel="Your secure document"
                mobileFoundation
                compact
            >
                <div className="sf-card">
                    <div className="sf-card-overview">
                        <span className="sf-vault-icon" aria-hidden="true">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                <rect x="5" y="10" width="14" height="11" rx="2" />
                                <path d="M8 10V7a4 4 0 0 1 8 0v3M12 15v2" />
                            </svg>
                        </span>
                        <div className="sf-card-overview-copy">
                            <p className="sf-card-kicker">PRIVATE VAULT</p>
                            <h2 className="sf-card-title">Your file access</h2>
                            <p className="sf-card-description">Protected by your verified account.</p>
                        </div>
                    </div>
                    { stage === 'loading' && error && (
                        <div className="sf-load-error">
                            <PublicNotice mode="inline" tone="error" message={ error } flush />
                            <button type="button" className="sf-file-action-button sf-secondary-btn"
                                onClick={ () => { window.location.reload(); } }>Try again</button>
                        </div>
                    ) }
                    { stage === 'files' && (
                        <div className="sf-form">
                            { files.length === 0 && (
                                <div className="sf-empty-state">
                                    { error
                                        ? <PublicNotice mode="inline" tone="error" message={ error } flush />
                                        : <p className="sf-empty">There are no files shared with your number right now.</p> }
                                    <Link className="sf-back-link" href="/orders/">Back to Orders</Link>
                                </div>
                            ) }

                            { files.map( file => {
                                const serverState = accessStateOf( file );
                                const state = serverState === 'OPEN' && !!file.accessWindowEndsAt
                                    && nowSeconds >= file.accessWindowEndsAt ? 'EXPIRED' : serverState;
                                const isPaid = state === 'OPEN' || state === 'READY';
                                const ends = state === 'OPEN' ? windowEndLabel( file.accessWindowEndsAt ) : '';
                                const feedback = fileFeedback[ file.fileId ];
                                const waitingForPayment = Boolean( paymentWaiting[ file.fileId ] );

                                return (
                                    <div key={ file.fileId } className="sf-file">
                                        <div className="sf-file-head">
                                            <span className="sf-file-icon" aria-hidden="true">
                                                <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                                                    stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                                                    <path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10Z" />
                                                    <path d="M13 3v7h7M8 15h8M8 18h5" />
                                                </svg>
                                            </span>
                                            <div className="sf-file-copy">
                                                <h3 className="sf-file-name">{ file.displayName }</h3>
                                                <div className="sf-file-meta">
                                                    { formatBytes( file.sizeBytes ) }
                                                    { file.contentType === 'application/pdf' ? ' · PDF' : '' }
                                                    { file.downloadCount > 0
                                                        && ` · downloaded ${ file.downloadCount } time${ file.downloadCount === 1 ? '' : 's' }` }
                                                </div>
                                            </div>
                                        </div>
                                        { state !== 'OPEN' && state !== 'EXPIRED' && (
                                            <div className="sf-file-status-row" role="status" aria-live="polite">
                                                <span className={ `sf-status-chip ${ isPaid ? 'sf-status-ready'
                                                    : state === 'PAID_UNVERIFIED' ? 'sf-status-pending' : 'sf-status-locked' }` }>
                                                    <span className="sf-status-dot" aria-hidden="true" />
                                                    { fileStatusLabel( state ) }
                                                </span>
                                            </div>
                                        ) }
                                        <div className="sf-file-divider" aria-hidden="true" />

                                        { isPaid ? (
                                            <>
                                                <div className="sf-file-action">
                                                    <button
                                                        type="button"
                                                        className="sf-file-action-button sf-download-button"
                                                        onClick={ () => { void handleDownload( file ); } }
                                                        disabled={ working === file.fileId }
                                                        aria-busy={ working === file.fileId }
                                                    >
                                                        { working === file.fileId ? 'Preparing…' : 'Download' }
                                                    </button>
                                                </div>
                                                <p className="sf-state-note" role="status">
                                                    { state === 'OPEN'
                                                        ? `Access active${ ends ? ` until ${ ends }` : '' }. Download before expiry.`
                                                        : 'Payment verified. 24-hour access starts on delivery or first download.' }
                                                </p>
                                            </>
                                        ) : state === 'EXPIRED' ? (
                                            <div className="sf-file-action" role="status" aria-live="polite">
                                                <button type="button"
                                                    className="sf-file-action-button sf-download-button sf-expired-button"
                                                    disabled>
                                                    Access expired
                                                </button>
                                            </div>
                                        ) : state === 'PAID_UNVERIFIED' ? (
                                            <p className="sf-confirming-note" role="status">
                                                Payment recorded. Confirming access. Do not pay again.
                                            </p>
                                        ) : state === 'UNPAID' ? (
                                            <>
                                                { waitingForPayment ? (
                                                    <div className="sf-pay-waiting">
                                                        <p className="sf-payment-note"
                                                            role={ feedback?.kind === 'error' ? 'alert' : 'status' }>
                                                            { feedback?.message
                                                                || publicActionText( 'whatsappFailed' ) }
                                                        </p>
                                                        <button type="button" className="sf-file-action-button sf-secondary-btn"
                                                            onClick={ () => { void loadFiles(); } }
                                                            disabled={ working === file.fileId }>Refresh payment status</button>
                                                    </div>
                                                ) : (
                                                    <div className="sf-payment-options" role="group" aria-label="Vault payment options">
                                                        <p className="sf-payment-lead">
                                                            Choose how to unlock this private file for 24 hours.
                                                        </p>
                                                        <p className="sf-payment-total">
                                                            { payablePrice !== null
                                                                ? 'Estimated total: ₹' + rupeesFromPaise( payablePrice )
                                                                    + '. Final total and tax are calculated at checkout.'
                                                                : 'Website estimate unavailable. WhatsApp Review & Pay will show the verified amount before you approve.' }
                                                        </p>
                                                        <div className="sf-payment-option sf-payment-option-primary">
                                                            <div className="sf-payment-choice-head">
                                                                <strong>Website checkout</strong>
                                                                { vaultLinePrice !== null && <span className="sf-choice-tag">Recommended</span> }
                                                            </div>
                                                            <span>Use your cart and secure Razorpay checkout. Review the final amount before paying.</span>
                                                            <button type="button" className="sf-file-action-button"
                                                                onClick={ () => { void handleWebsiteCheckout( file ); } }
                                                                disabled={ working === file.fileId || vaultLinePrice === null }
                                                                aria-busy={ working === file.fileId }>
                                                                { working === file.fileId ? 'Preparing cart…'
                                                                    : payablePrice === null ? 'Price unavailable'
                                                                        : 'Add 24-hour Vault access to cart' }
                                                            </button>
                                                        </div>
                                                        <div className="sf-payment-option">
                                                            <strong>WhatsApp Review &amp; Pay</strong>
                                                            <span>Receive the server-priced Review &amp; Pay request on your registered WhatsApp number. Check the amount before approving.</span>
                                                            <button type="button" className="sf-file-action-button sf-secondary-btn"
                                                                onClick={ () => { void handleVaultPayment( file ); } }
                                                                disabled={ working === file.fileId }
                                                                aria-busy={ working === file.fileId }>
                                                                { working === file.fileId ? 'Sending to WhatsApp…'
                                                                    : 'Pay on WhatsApp instead' }
                                                            </button>
                                                        </div>
                                                    </div>
                                                ) }
                                            </>
                                        ) : null }

                                        { state !== 'EXPIRED' && feedback?.kind === 'status' && !waitingForPayment && (
                                            <p className="sf-payment-note" role="status">{ feedback.message }</p>
                                        ) }
                                        { state !== 'EXPIRED' && feedback?.kind === 'error' && !waitingForPayment && (
                                            <PublicNotice mode="inline" tone="error" message={ feedback.message } />
                                        ) }
                                    </div>
                                );
                            } ) }

                        </div>
                    ) }
                </div>

            </RotatingHero>

            <style jsx>{ `
                /* NO .sf-shell ANY MORE, and no header offset here.

                   This page used to render its own <main className="sf-shell"> and pad the top by
                   calc(108px + 48px) to clear the fixed header. RotatingHero now owns the <main>
                   and the page measure, and it already handles the header offset for all sixteen
                   surfaces built on it - so repeating the padding here would double it and push
                   the panel half a screen down. The panel is simply the hero's child now.

                   The former min-height:100vh (removed earlier) is likewise still absent: _app.tsx
                   wraps every public route in <Header/> + page + <Footer/>, so claiming the whole
                   viewport pushed the shared footer a full screen down. */

                /* /auth is the one sign-in screen. After it returns here, Vault uses the same
                   card language: 560px measure, lime top rule, 24px radius and quiet lift. */
                .sf-card{
                  width:100%;max-width:560px;margin:0;padding:clamp(28px,4vw,36px) clamp(24px,4.5vw,40px) clamp(30px,4.5vw,40px);
                  border:1px solid var(--public-hairline);border-top:4px solid var(--public-brand-lime);
                  border-radius:24px;background:var(--public-bg);box-shadow:0 14px 38px rgba(26,58,42,.08);
                  box-sizing:border-box;
                }
                .sf-card-overview{display:flex;align-items:center;gap:14px;padding-bottom:20px;margin-bottom:24px;
                  border-bottom:1px solid var(--public-hairline)}
                .sf-vault-icon{display:grid;place-items:center;flex:0 0 auto;width:50px;height:50px;
                  border-radius:16px;background:var(--public-lime-tint);color:var(--public-brand-green)}
                .sf-card-overview-copy{min-width:0;flex:1}
                .sf-card-kicker{margin:0 0 4px;font-size:11px;letter-spacing:.13em;font-weight:800;
                  color:var(--public-brand-green)}
                .sf-card-title{margin:0;font-size:clamp(22px,2.4vw,27px);font-weight:750;line-height:1.2;
                  letter-spacing:-.04em;color:var(--public-heading)}
                .sf-card-description{margin:6px 0 0;font-size:14px;line-height:1.45;color:var(--public-muted)}
                .sf-load-error{display:grid;gap:12px;width:100%;padding-top:8px}
                .sf-load-error .sf-file-error{margin:0}
                .sf-load-error .sf-file-action-button{min-width:140px;justify-content:center}
                .sf-form{display:block}

                /* The auth-inspired outer card owns the surface; the exact file is its content,
                   not a second nested card. */
                .sf-file{padding:0;margin:0;background:transparent;border:0;border-radius:0;box-shadow:none}
                .sf-file-head{display:flex;gap:14px;align-items:flex-start}
                .sf-file-icon{
                  width:46px;height:46px;border-radius:13px;background:var(--public-lime-tint);
                  color:var(--public-brand-green);display:flex;align-items:center;justify-content:center;flex:0 0 auto;
                }
                .sf-file-copy{min-width:0;flex:1}
                .sf-file-name{
                  margin:0;font-size:var(--public-card-size);font-weight:var(--public-card-weight);
                  line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);
                  color:var(--public-heading);overflow-wrap:anywhere;
                }
                .sf-file-meta{
                  margin:8px 0 0;font-size:var(--public-supporting-size);line-height:1.4;color:var(--public-muted);
                }
                .sf-file-status-row{margin:16px 0 0;display:flex;flex-wrap:wrap;gap:8px}
                .sf-status-chip{display:inline-flex;align-items:center;gap:8px;max-width:100%;
                  padding:8px 12px;border-radius:999px;border:1px solid var(--public-hairline);
                  font-size:13px;font-weight:750;line-height:1.3;overflow-wrap:anywhere}
                .sf-status-dot{width:8px;height:8px;border-radius:50%;background:currentColor;flex:0 0 auto}
                .sf-status-ready{color:var(--public-brand-green);background:var(--public-lime-tint);border-color:#cce7ae}
                .sf-status-pending{color:#6d531c;background:#fff8e5;border-color:#ead9aa}
                .sf-status-locked{color:var(--public-muted);background:var(--public-bg)}
                .sf-file-divider{height:1px;background:var(--public-hairline);margin:22px 0}
                .sf-file-action{margin-top:22px}
                .sf-file-divider + .sf-file-action{margin-top:0}
                .sf-file-action-button{
                  display:inline-flex;align-items:center;width:max-content;max-width:100%;
                  min-height:48px;padding:8px 14px;border:0;border-radius:10px;
                  background:var(--public-lime-tint);color:var(--public-brand-green);
                  font-family:inherit;font-size:var(--public-cta-font-size);font-weight:700;line-height:1.35;
                  text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:4px;
                  cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;
                  transition:background-color .18s,transform .18s,box-shadow .18s,text-decoration-color .18s;
                }
                .sf-file-action-button:hover:not(:disabled){
                  background:var(--public-brand-lime);transform:translateY(-1px);
                  box-shadow:0 5px 14px rgba(26,58,42,.10);text-decoration-color:transparent;
                }
                .sf-file-action-button:focus-visible{
                  background:var(--public-brand-lime);text-decoration-color:transparent;
                  outline:3px solid var(--public-brand-green);outline-offset:3px;
                }
                .sf-file-action-button:disabled{opacity:.6;cursor:wait;transform:none;box-shadow:none}
                .sf-expired-button:disabled{opacity:1;cursor:not-allowed}
                /* Exact /auth and /orders notification treatment: 4px lime rule,
                   11px/13px padding, 10px radius, lime tint and supporting typography.
                   Access details stay visible rather than auto-dismissing. */
                .sf-state-note,.sf-confirming-note,.sf-payment-note,.sf-file-error{
                  box-sizing:border-box;inline-size:fit-content;max-inline-size:100%;
                  margin:14px 0 0;padding:11px 13px;
                  border-inline-start:4px solid var(--public-brand-lime);border-radius:10px;
                  background:var(--public-lime-tint);color:var(--public-text);
                  font-family:var(--font-sans);font-size:var(--public-supporting-size);
                  font-weight:600;line-height:1.4;overflow-wrap:anywhere;
                }
                .sf-confirming-note,.sf-payment-note{margin-top:0}
                .sf-payment-options{display:grid;gap:12px;min-width:0}
                .sf-payment-lead{margin:0 0 3px;font-size:var(--public-supporting-size);color:var(--public-heading);font-weight:650;line-height:1.5}
                .sf-payment-option{display:grid;gap:10px;padding:16px;border:1px solid #dce8d6;border-radius:14px;background:#fff}
                .sf-payment-option-primary{background:#f6fbf0;border-color:#bedcac}
                .sf-payment-choice-head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px}
                .sf-payment-option strong{font-weight:800;color:var(--public-brand-green);font-size:var(--public-supporting-size)}
                .sf-payment-option span{font-size:var(--public-supporting-size);color:var(--public-muted);line-height:1.5}
                .sf-payment-option .sf-choice-tag{display:inline-flex;align-items:center;border-radius:999px;
                  padding:4px 9px;background:var(--public-brand-lime);color:var(--public-brand-green);
                  font-size:12px;line-height:1.3;font-weight:750}
                .sf-payment-option .sf-file-action-button{justify-content:center;width:100%;text-align:center}
                .sf-payment-option .sf-secondary-btn,.sf-pay-waiting .sf-secondary-btn{border:1px solid #d0e0c8;background:#fff;color:var(--public-brand-green)}
                .sf-payment-total{font-size:var(--public-supporting-size);color:var(--public-heading);
                  padding:12px 14px;margin:0;line-height:1.5;background:var(--public-lime-tint);
                  border-radius:12px;border:1px solid #dce8d6}
                .sf-pay-waiting{display:grid;gap:12px}

                .sf-empty-state{display:grid;justify-items:start;gap:16px}
                /* The no-file refusal uses the same lime-accent notice as Vault/Auth errors,
                   at full card width instead of unstyled body copy. */
                .sf-empty-state .sf-unavailable-notice{inline-size:100%;margin:0}
                .sf-empty{
                  font-size:var(--public-body-size);font-weight:var(--public-body-weight);line-height:var(--public-body-leading);letter-spacing:var(--public-body-tracking);color:var(--public-muted);margin:0;
                }
                .sf-back-link{display:inline-flex;align-items:center;min-height:44px;padding:8px 12px;
                  border-radius:10px;background:var(--public-lime-tint);color:var(--public-brand-green);
                  font-weight:700;text-decoration:underline;text-underline-offset:3px}
                .sf-back-link:hover{background:var(--public-brand-lime)}
                .sf-back-link:focus-visible{outline:3px solid var(--public-brand-green);outline-offset:3px}

                @media(max-width:767px){
                  .sf-card{padding:28px 20px max(30px,env(safe-area-inset-bottom));border-radius:20px}
                  .sf-file-name{font-size:var(--public-mobile-card-size)}
                  .sf-file-meta,.sf-state-note,.sf-confirming-note,.sf-payment-note,.sf-file-error{
                    font-size:var(--public-mobile-supporting-size);
                  }
                  .sf-card-overview{align-items:flex-start;gap:12px}
                  .sf-vault-icon{width:44px;height:44px;border-radius:13px}
                  .sf-card-title{font-size:22px}
                  .sf-file-head{gap:12px}
                  .sf-file-icon{width:42px;height:42px}
                  .sf-file-action-button{font-size:var(--public-mobile-cta-font-size)}
                  .sf-file-action-button:not(.sf-download-button){width:100%;justify-content:center;text-align:center}
                }
                @media(prefers-reduced-motion:reduce){
                  .sf-file-action-button{transition:none}
                  .sf-file-action-button:hover:not(:disabled){transform:none;box-shadow:none}
                }
            ` }</style>
        </>
    );
}
