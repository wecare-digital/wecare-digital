/**
 * Customer file collection: verify over WhatsApp, pay, download.
 *
 * Design
 * ------
 * Home is the typography source of truth. The shared RotatingHero consumes the canonical
 * public hero/body tokens directly. The file block stays left-aligned on the 560px public
 * copy measure. File actions preserve the established Vault treatment: lime-tint surface,
 * dark-green underlined label, 10px radius and 48px minimum height.
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
 * Nothing on this page can grant access. For UNPAID or EXPIRED, the browser names only this
 * exact fileId to secure-files under the customer session. The backend re-proves ownership and
 * entitlement state, then hands the file to the existing native WhatsApp Review and Pay rail.
 * ProductsTable pricing, GST/fees, PaymentAttempt/PAYREF and Meta ORDER_DETAILS are server-owned.
 * There is no website cart and Vault has no Meta Flow. After authoritative capture the durable
 * entitlement changes this same card to confirming/download state.
 *
 * Paying and renewing
 * -------------------
 * Each file carries `accessState`. UNPAID and EXPIRED can request native WhatsApp payment;
 * OPEN/READY never charge again, and PAID_UNVERIFIED only reconciles. After a payment request is
 * sent, this page stays on /vault/?file=<id>, refreshes on focus and polls until the server-owned
 * state changes.
 */

import React, { useCallback, useEffect, useState } from 'react';
import SEO from '../SEO';
import RotatingHero from '../RotatingHero';
import type { CycleWord } from '../RotatingHero';
import * as api from '../../api/client';
import type { SecureFile, SecureFileAccessState } from '../../api/client';
import { fetchServicePrices, rupeesFromPaise } from '../../lib/servicePricing';
import { restoreSession, clearSession, getSession } from '../../lib/customerAuth';
import { serviceByKind } from '../../config/services';
import { postRequestIntent } from '../../lib/serviceRequests';
import { setServiceLine, serviceIntentFor, toLineItems } from '../../lib/cart';

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

/**
 * The hero's rotating nouns, TRUE OF THIS PAGE rather than borrowed from the home page's
 * marketing audiences. This is the collection point for files someone has shared with you, so the
 * rotation names what arrives here. The pill sits on its own line (.rh-head-line is
 * display:block) so the headline's line count cannot change as the word changes. Tints/dots are
 * the four per-subject pairs the Grahak OS hero established and the home page reuses verbatim; no
 * new colour is introduced.
 */
const GET_WORDS: CycleWord[] = [
    { word: 'files', tint: '#dbeafe', dot: '#2563eb' },
    { word: 'docs', tint: '#ede9fe', dot: '#9849e8' },
    { word: 'records', tint: '#e0f7c8', dot: '#3da35a' },
    { word: 'papers', tint: '#fef3c7', dot: '#f0a818' },
];

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
                ? ownedFiles.filter( file => file.fileId === targetFileId )
                : ownedFiles;
            setFiles( visibleFiles );
            setStage( 'files' );
            setError(
                targetFileId && visibleFiles.length === 0
                    ? 'This document is not available right now.'
                    : ''
            );
        } else if ( result.failure.status === 401 )
        {
            clearSession();
            redirectToAuth();
            return;
        } else
        {
            setError( result.failure.message || 'Could not load your files' );
        }
    }, [ targetFileId, redirectToAuth ] );

    // Vault has no file-local or deploy-local price. This preview is display-only; the native
    // WhatsApp payment backend independently re-prices before a payment attempt exists.
    useEffect( () => {
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
    }, [] );

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
                        ? ownedFiles.filter( file => file.fileId === targetFileId )
                        : ownedFiles;
                    setFiles( visibleFiles );
                    setStage( 'files' );
                    if ( targetFileId && visibleFiles.length === 0 )
                    {
                        setError( 'This document is not available right now.' );
                    }
                } else if ( result.failure.status === 401 )
                {
                    clearSession();
                    redirectToAuth();
                } else
                {
                    setError( result.failure.message || 'Could not load your files. Please try again.' );
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
                    setFiles( current => current.map( row => row.fileId === file.fileId
                        ? { ...row, accessState: 'EXPIRED', accessWindowOpen: false }
                        : row ) );
                    feedback( 'status', 'Your free 24-hour window has ended. Choose website cart renewal or WhatsApp payment to open another paid window.' );
                    void loadFiles();
                    return;
                }
                feedback(
                    'error',
                    code === 'NOT_REGISTERED'
                        ? 'This file is not registered to your verified number.'
                        : code === 'ACCESS_NOT_AUTHORIZED'
                            ? 'We could not confirm paid access for this file. If you already paid, do not pay again.'
                            : ( result.failure.message || 'Could not prepare the download.' )
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
            if ( destination.protocol !== 'https:'
                || destination.hostname !== 'wecare-digital-get.s3.us-east-1.amazonaws.com' ) {
                feedback( 'error', 'The file was not hosted at the expected secure location. Please contact support.' );
                return;
            }
            feedback( 'status', 'Your secure file download is starting. The short-lived link will expire automatically.' );
            window.location.assign( destination.href );
        } catch ( err: any )
        {
            feedback( 'error', err?.message || 'Could not prepare the download.' );
        } finally
        {
            setWorking( '' );
        }
    };

    const handleWebsiteCheckout = async ( file: SecureFile ) => {
        const state = accessStateOf( file );
        if ( state !== 'UNPAID' && state !== 'EXPIRED' ) return;
        const service = serviceByKind( 'VAULT' );
        if ( !service || !vaultLinePrice || payablePrice === null ) {
            setFileFeedback( current => ( { ...current, [ file.fileId ]: {
                kind: 'error', message: 'The current Vault price is unavailable. Nothing has been charged.',
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
            window.location.assign( '/cart/' );
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
        if ( state !== 'UNPAID' && state !== 'EXPIRED' ) return;
        if ( payablePrice === null ) {
            setFileFeedback( current => ( {
                ...current,
                [ file.fileId ]: {
                    kind: 'error',
                    message: 'The live Vault price could not be confirmed. Nothing has been charged. Please refresh and try again.',
                },
            } ) );
            return;
        }

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
                        message: 'We could not prepare your verified WhatsApp identity. Nothing has been charged. Please try again.',
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
                        message: result.failure.message
                            || 'We could not send the Vault payment request. Nothing has been charged.',
                    },
                } ) );
                return;
            }

            setPaymentWaiting( current => ( { ...current, [ file.fileId ]: true } ) );
            setFileFeedback( current => ( {
                ...current,
                [ file.fileId ]: {
                    kind: 'status',
                    message: result.data.message
                        || 'Payment request sent to your registered WhatsApp number. Complete Review and Pay there.',
                },
            } ) );
            void loadFiles();
        } catch {
            setFileFeedback( current => ( {
                ...current,
                [ file.fileId ]: {
                    kind: 'error',
                    message: 'We could not send the Vault payment request. Nothing has been charged. Please try again.',
                },
            } ) );
        } finally {
            setWorking( '' );
        }
    };

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
                stage-dependent heading is now an <h2> inside the panel, styled by the same class,
                so nothing moves visually.

                NO badgeLabel, matching the home page and /blog/: the label here would just be the
                company name again, 109px under the header's own lockup, which is exactly what the
                home page removed. The old <p className="sf-eyebrow">WECARE.DIGITAL</p> is gone for
                the same reason. */}
            <RotatingHero
                frame="Collect your"
                words={ GET_WORDS }
                sub="Your shared files are right here."
                ariaLabel="Collect your files"
                mobileFoundation
            >
                <div className="sf-card">
                    { stage === 'loading' && (
                        <div className="sf-loading" role="status" aria-live="polite">
                            <span className="sf-loading-mark" aria-hidden="true">V</span>
                            <strong>Opening your Vault…</strong>
                            <span>Checking your verified customer session.</span>
                        </div>
                    ) }
                    { stage === 'files' && (
                        <div className="sf-form">
                            { files.length === 0 && (
                                <p className="sf-empty" role={ error ? 'alert' : undefined }>
                                    { error || 'There are no files shared with your number right now.' }
                                </p>
                            ) }

                            { files.map( file => {
                                const state = accessStateOf( file );
                                const isPaid = state === 'OPEN' || state === 'READY';
                                const ends = state === 'OPEN' ? windowEndLabel( file.accessWindowEndsAt ) : '';
                                const feedback = fileFeedback[ file.fileId ];
                                const waitingForPayment = Boolean( paymentWaiting[ file.fileId ] );

                                return (
                                    <div key={ file.fileId } className="sf-file">
                                        <div className="sf-file-head">
                                            <div className="sf-file-copy">
                                                <div className="sf-file-name">{ file.displayName }</div>
                                                <div className="sf-file-meta">
                                                    { formatBytes( file.sizeBytes ) }
                                                    { file.contentType === 'application/pdf' ? ' · PDF' : '' }
                                                    { file.downloadCount > 0
                                                        && ` · downloaded ${ file.downloadCount } time${ file.downloadCount === 1 ? '' : 's' }` }
                                                </div>
                                            </div>
                                        </div>
                                        <div className="sf-file-divider" aria-hidden="true" />

                                        { isPaid ? (
                                            <>
                                                <div className="sf-file-action">
                                                    <button
                                                        type="button"
                                                        className="sf-file-action-button"
                                                        onClick={ () => { void handleDownload( file ); } }
                                                        disabled={ working === file.fileId }
                                                        aria-busy={ working === file.fileId }
                                                    >
                                                        { working === file.fileId ? 'Preparing…' : 'Download' }
                                                    </button>
                                                </div>
                                                <p className="sf-state-note">
                                                    { state === 'OPEN'
                                                        ? `Access is active${ ends ? ` until ${ ends }` : '' }. Download again anytime before it ends.`
                                                        : 'Payment is verified. Your 24-hour window begins when access is first delivered or downloaded; refreshing this page never extends it.' }
                                                </p>
                                            </>
                                        ) : state === 'PAID_UNVERIFIED' ? (
                                            <p className="sf-confirming-note" role="status">
                                                Your payment is recorded and access is being confirmed. Do not pay again.
                                            </p>
                                        ) : (
                                            <>
                                                { waitingForPayment ? (
                                                    <div className="sf-pay-waiting">
                                                        <p className="sf-payment-note" role="status">
                                                            { feedback?.message
                                                                || 'Review & Pay was sent to WhatsApp. Complete it or check the status before starting another checkout.' }
                                                        </p>
                                                        <button type="button" className="sf-file-action-button sf-secondary-btn"
                                                            onClick={ () => { void loadFiles(); } }
                                                            disabled={ working === file.fileId }>Refresh payment status</button>
                                                    </div>
                                                ) : (
                                                    <div className="sf-payment-options" role="group" aria-label="Vault payment options">
                                                        <p className="sf-expired-lead">
                                                            { state === 'EXPIRED'
                                                                ? 'Your previous 24-hour access expired. Renew this same document for another 24-hour window.'
                                                                : 'Choose how to unlock this private file for 24 hours.' }
                                                        </p>
                                                        <div className="sf-payment-option sf-payment-option-primary">
                                                            <strong>Website checkout</strong>
                                                            <span>Use your cart and secure Razorpay checkout · recommended for quick renewal</span>
                                                            <button type="button" className="sf-file-action-button"
                                                                onClick={ () => { void handleWebsiteCheckout( file ); } }
                                                                disabled={ working === file.fileId || payablePrice === null || vaultLinePrice === null }
                                                                aria-busy={ working === file.fileId }>
                                                                { working === file.fileId ? 'Preparing cart…'
                                                                    : payablePrice === null ? 'Price unavailable'
                                                                        : state === 'EXPIRED' ? 'Add 24-hour renewal to cart'
                                                                            : 'Add 24-hour Vault access to cart' }
                                                            </button>
                                                        </div>
                                                        <div className="sf-payment-option">
                                                            <strong>WhatsApp Review &amp; Pay</strong>
                                                            <span>Receive the native payment request on your registered WhatsApp number</span>
                                                            <button type="button" className="sf-file-action-button sf-secondary-btn"
                                                                onClick={ () => { void handleVaultPayment( file ); } }
                                                                disabled={ working === file.fileId || payablePrice === null }
                                                                aria-busy={ working === file.fileId }>
                                                                { working === file.fileId ? 'Sending to WhatsApp…'
                                                                    : payablePrice === null ? 'Price unavailable'
                                                                        : 'Pay on WhatsApp instead' }
                                                            </button>
                                                        </div>
                                                        <p className="sf-payment-total">
                                                            { payablePrice !== null
                                                                ? 'Estimated total: ₹' + rupeesFromPaise( payablePrice )
                                                                    + '. Final total and tax are calculated at checkout.'
                                                                : 'The current amount is being verified. No payment can begin until it is available.' }
                                                        </p>
                                                    </div>
                                                ) }
                                                <p className="sf-state-note">
                                                    Free downloads and access-link resends last only for the active paid 24-hour window.
                                                    Renewal opens a new paid window on this same secure file—no new upload.
                                                </p>
                                            </>
                                        ) }

                                        { feedback?.kind === 'status' && !waitingForPayment && (
                                            <p className="sf-payment-note" role="status">{ feedback.message }</p>
                                        ) }
                                        { ( state === 'OPEN' || state === 'READY' ) && (
                                            <p className="sf-link-help">
                                                The WhatsApp file link is not a public download. Sign-in, ownership and your active paid window are checked before a short-lived secure URL is issued.
                                            </p>
                                        ) }
                                        { feedback?.kind === 'error' && (
                                            <p className="sf-file-error" role="alert">{ feedback.message }</p>
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
                .sf-loading{display:grid;gap:8px;justify-items:start;color:var(--public-text)}
                .sf-loading-mark{
                  display:grid;place-items:center;width:48px;height:48px;margin-bottom:10px;
                  border-radius:12px;background:var(--public-brand-lime);color:var(--public-brand-green);
                  font-size:20px;font-weight:800;line-height:1;
                }
                .sf-loading strong{font-size:var(--public-card-size);line-height:1.2;color:var(--public-heading)}
                .sf-loading>span:last-child{font-size:var(--public-supporting-size);line-height:1.45;color:var(--public-muted)}
                .sf-form{display:block}

                /* The auth-inspired outer card owns the surface; the exact file is its content,
                   not a second nested card. */
                .sf-file{padding:0;margin:0;background:transparent;border:0;border-radius:0;box-shadow:none}
                .sf-file-head{display:flex;gap:11px;align-items:flex-start}
                .sf-file-icon{
                  width:38px;height:38px;border-radius:10px;background:var(--public-lime-tint);
                  color:var(--public-brand-green);display:flex;align-items:center;justify-content:center;flex:0 0 auto;
                }
                .sf-file-copy{min-width:0;flex:1}
                .sf-file-name{
                  font-size:var(--public-card-size);font-weight:var(--public-card-weight);
                  line-height:var(--public-card-leading);letter-spacing:var(--public-card-tracking);
                  color:var(--public-heading);overflow-wrap:anywhere;
                }
                .sf-file-meta{
                  margin:8px 0 0;font-size:var(--public-supporting-size);line-height:1.4;color:var(--public-muted);
                }
                .sf-file-divider{height:1px;background:#eef0e6;margin:24px 0}
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
                .sf-state-note{
                  margin:14px 0 0;max-width:480px;color:var(--public-muted);
                  font-size:var(--public-supporting-size);line-height:1.45;
                }
                .sf-payment-options{display:grid;gap:12px;min-width:0}
                .sf-expired-lead{margin:0 0 3px;font-size:var(--public-supporting-size);color:var(--public-heading);font-weight:650;line-height:1.5}
                .sf-payment-option{display:grid;gap:10px;padding:16px;border:1px solid #dce8d6;border-radius:14px;background:#fff}
                .sf-payment-option-primary{background:#f6fbf0;border-color:#bedcac}
                .sf-payment-option strong{font-weight:800;color:var(--public-brand-green);font-size:var(--public-supporting-size)}
                .sf-payment-option span{font-size:var(--public-supporting-size);color:var(--public-muted);line-height:1.5}
                .sf-payment-option .sf-file-action-button{justify-content:center;width:100%;text-align:center}
                .sf-payment-option .sf-secondary-btn,.sf-pay-waiting .sf-secondary-btn{border:1px solid #d0e0c8;background:#fff;color:var(--public-brand-green)}
                .sf-payment-total{font-size:var(--public-supporting-size);color:var(--public-muted);margin:2px 0 0;line-height:1.5}
                .sf-pay-waiting{display:grid;gap:12px}
                .sf-link-help{margin:16px 0 0;border-top:1px solid #e9eee5;padding-top:12px;color:var(--public-muted);font-size:var(--public-supporting-size);line-height:1.55}
                .sf-confirming-note{
                  margin:0;padding:12px 14px;border-inline-start:4px solid var(--public-brand-lime);
                  border-radius:10px;background:var(--public-lime-tint);color:var(--public-brand-green);
                  font-size:var(--public-supporting-size);font-weight:600;line-height:1.45;
                }
                .sf-payment-note{
                  margin:0;max-width:480px;color:var(--public-brand-green);
                  font-size:var(--public-supporting-size);font-weight:600;line-height:1.45;
                }
                .sf-file-error{
                  margin:14px 0 0;max-width:480px;color:var(--public-brand-green);
                  font-size:var(--public-supporting-size);font-weight:600;line-height:1.45;
                }

                .sf-empty{
                  font-size:var(--public-supporting-size);line-height:1.5;color:var(--public-muted);margin:0;
                }

                @media(max-width:767px){
                  .sf-card{padding:28px 20px max(30px,env(safe-area-inset-bottom));border-radius:20px}
                  .sf-loading-mark{width:46px;height:46px;border-radius:11px}
                  .sf-loading strong,.sf-file-name{font-size:var(--public-mobile-card-size)}
                  .sf-file-meta,.sf-state-note,.sf-confirming-note,.sf-payment-note,.sf-file-error{
                    font-size:var(--public-mobile-supporting-size);
                  }
                  .sf-file-action-button{font-size:var(--public-mobile-cta-font-size)}
                }
                @media(prefers-reduced-motion:reduce){
                  .sf-file-action-button{transition:none}
                  .sf-file-action-button:hover:not(:disabled){transform:none;box-shadow:none}
                }
            ` }</style>
        </>
    );
}
